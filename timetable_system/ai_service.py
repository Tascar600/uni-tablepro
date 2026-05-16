import json
from datetime import datetime, timedelta
from collections import defaultdict
from models import get_db


def detect_conflicts():
    db = get_db()
    entries = db.execute("""
        SELECT te.*, c.name as course_name, c.code,
               u.full_name as lecturer_name, r.name as room_name,
               r.capacity
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
    """).fetchall()
    db.close()

    conflicts = []
    entries_list = [dict(e) for e in entries]

    for i, e1 in enumerate(entries_list):
        for e2 in entries_list[i + 1:]:
            if e1['day'] != e2['day']:
                continue
            e1_start = _time_to_min(e1['start_time'])
            e1_end = _time_to_min(e1['end_time'])
            e2_start = _time_to_min(e2['start_time'])
            e2_end = _time_to_min(e2['end_time'])

            if e1_start < e2_end and e1_end > e2_start:
                if e1['lecturer_id'] == e2['lecturer_id']:
                    conflicts.append({
                        'type': 'lecturer',
                        'severity': 'high',
                        'description': f"{e1['lecturer_name']} has overlapping classes: {e1['course_name']} ({e1['start_time']}-{e1['end_time']}) and {e2['course_name']} ({e2['start_time']}-{e2['end_time']}) on {e1['day']}",
                        'entry1': e1, 'entry2': e2,
                        'suggestion': f"Move {e2['course_name']} to a different time slot or assign a substitute lecturer.",
                    })
                if e1['room_id'] == e2['room_id']:
                    conflicts.append({
                        'type': 'room',
                        'severity': 'high',
                        'description': f"Room {e1['room_name']} is double-booked: {e1['course_name']} ({e1['start_time']}-{e1['end_time']}) and {e2['course_name']} ({e2['start_time']}-{e2['end_time']}) on {e1['day']}",
                        'entry1': e1, 'entry2': e2,
                        'suggestion': f"Move one session to an available room. Check {e1['room_name']} or {e2['room_name']} availability.",
                    })
                if e1['group_name'] == e2['group_name']:
                    conflicts.append({
                        'type': 'group',
                        'severity': 'high',
                        'description': f"Group {e1['group_name']} has overlapping sessions: {e1['course_name']} and {e2['course_name']} on {e1['day']} at overlapping times",
                        'entry1': e1, 'entry2': e2,
                        'suggestion': f"Reschedule one session for group {e1['group_name']} to a different time slot.",
                    })

    return conflicts


def _time_to_min(t):
    parts = t.split(':')
    return int(parts[0]) * 60 + int(parts[1])


def suggest_resolution(conflict):
    entry1 = conflict.get('entry1', {})
    entry2 = conflict.get('entry2', {})

    suggestions = []

    if conflict['type'] == 'lecturer':
        subs = find_substitutes(entry1.get('lecturer_id'), entry1.get('day'), entry1.get('start_time'), entry1.get('end_time'))
        if subs:
            suggestions.append({
                'action': 'substitute',
                'description': f"Assign substitute lecturer: {subs[0]['full_name']}",
                'details': subs[0],
            })

    suggestions.append({
        'action': 'reschedule',
        'description': f"Move {entry2.get('course_name', 'course')} to {find_alternative_slot(entry2)}",
    })

    if conflict['type'] == 'room':
        alt_room = find_alternative_room(entry2.get('room_id'), entry2.get('day'), entry2.get('start_time'), entry2.get('end_time'))
        if alt_room:
            suggestions.append({
                'action': 'change_room',
                'description': f"Move to {alt_room['name']} (capacity: {alt_room['capacity']})",
                'details': alt_room,
            })

    return suggestions


def find_substitutes(lecturer_id, day, start_time, end_time):
    db = get_db()
    subs = db.execute("""
        SELECT u.* FROM users u
        WHERE u.role='lecturer' AND u.id != ?
        AND u.id NOT IN (
            SELECT te.lecturer_id FROM timetable_entries te
            WHERE te.day = ? AND te.start_time < ? AND te.end_time > ?
            AND te.status = 'scheduled'
        )
    """, (lecturer_id, day, end_time, start_time)).fetchall()
    db.close()
    return [dict(s) for s in subs]


def find_alternative_room(current_room_id, day, start_time, end_time):
    db = get_db()
    rooms = db.execute("""
        SELECT * FROM rooms WHERE id != ? AND is_active = 1
        AND id NOT IN (
            SELECT te.room_id FROM timetable_entries te
            WHERE te.day = ? AND te.start_time < ? AND te.end_time > ?
            AND te.status = 'scheduled'
        )
        ORDER BY capacity ASC
        LIMIT 1
    """, (current_room_id, day, end_time, start_time)).fetchall()
    db.close()
    if rooms:
        return dict(rooms[0])
    return None


def find_alternative_slot(entry):
    db = get_db()
    day = entry.get('day', 'Monday')
    start = _time_to_min(entry.get('start_time', '08:00'))
    end = _time_to_min(entry.get('end_time', '09:00'))
    duration = end - start

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    for d in days:
        if d == day:
            continue
        occupied = db.execute("""
            SELECT start_time, end_time FROM timetable_entries
            WHERE day = ? AND status = 'scheduled'
            AND (
                (lecturer_id = ?) OR (room_id = ?) OR (group_name = ?)
            )
        """, (d, entry.get('lecturer_id'), entry.get('room_id'), entry.get('group_name'))).fetchall()
        db.close()

        taken = [( _time_to_min(o['start_time']), _time_to_min(o['end_time'])) for o in occupied]

        for slot_start in range(420, 1020, 30):
            slot_end = slot_start + duration
            if slot_end > 1020:
                break
            conflict = False
            for ts, te in taken:
                if slot_start < te and slot_end > ts:
                    conflict = True
                    break
            if not conflict:
                h1, m1 = divmod(slot_start, 60)
                h2, m2 = divmod(slot_end, 60)
                return f"{d} at {h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"
    return "a different time slot"


def chatbot_response(query, context=None):
    query = query.lower()
    responses = []

    if 'clash' in query or 'conflict' in query or 'overlap' in query:
        conflicts = detect_conflicts()
        if conflicts:
            responses.append(f"I found {len(conflicts)} conflict(s) in the timetable. " +
                           f"Types: {', '.join(set(c['type'] for c in conflicts))}. " +
                           "Check the conflict resolution page for details and suggestions.")
        else:
            responses.append("No conflicts detected in the current timetable. Everything looks good!")

    if 'efficiency' in query or 'score' in query:
        from models import get_db
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='efficiency_score'").fetchone()
        db.close()
        score = int(row['value']) if row else 0
        responses.append(f"The current timetable efficiency score is {score}/100. " +
                        ("Excellent!" if score >= 80 else "Could be improved." if score >= 50 else "Needs significant improvement."))

    if 'lecturer' in query and ('load' in query or 'workload' in query or 'hours' in query):
        db = get_db()
        lecturers = db.execute("""
            SELECT u.full_name,
                   COUNT(te.id) as classes,
                   ROUND(SUM(
                       (julianday('00:' || te.end_time) - julianday('00:' || te.start_time)) * 24
                   ), 1) as total_hours
            FROM users u
            LEFT JOIN timetable_entries te ON u.id = te.lecturer_id
            WHERE u.role = 'lecturer'
            GROUP BY u.id
        """).fetchall()
        db.close()
        responses.append("Lecturer workload summary:\n" +
                        "\n".join(f"  - {l['full_name']}: {l['classes']} classes, {l['total_hours']}h/week" for l in lecturers))

    if 'room' in query and ('usage' in query or 'utilization' in query):
        db = get_db()
        rooms = db.execute("""
            SELECT r.name, COUNT(te.id) as usage_count,
                   ROUND(COALESCE(SUM(
                       (julianday('00:' || te.end_time) - julianday('00:' || te.start_time)) * 24
                   ), 0), 1) as total_hours
            FROM rooms r
            LEFT JOIN timetable_entries te ON r.id = te.room_id
            GROUP BY r.id
            ORDER BY total_hours DESC
        """).fetchall()
        db.close()
        responses.append("Room utilization:\n" +
                        "\n".join(f"  - {r['name']}: {r['usage_count']} bookings, {r['total_hours']}h total" for r in rooms))

    if 'version' in query or 'history' in query or 'rollback' in query:
        db = get_db()
        versions = db.execute("""
            SELECT tv.*, u.full_name as created_by_name
            FROM timetable_versions tv
            LEFT JOIN users u ON tv.created_by = u.id
            ORDER BY tv.version_number DESC LIMIT 5
        """).fetchall()
        db.close()
        if versions:
            responses.append("Recent timetable versions:\n" +
                            "\n".join(f"  - v{v['version_number']}: {v['created_at']} by {v['created_by_name']} ({v['notes'] or 'no notes'})" for v in versions))
        else:
            responses.append("No version history available yet.")

    if 'today' in query or 'schedule' in query:
        today_name = datetime.now().strftime('%A')
        db = get_db()
        today_entries = db.execute("""
            SELECT te.*, c.name as course_name, c.code,
                   u.full_name as lecturer_name, r.name as room_name
            FROM timetable_entries te
            JOIN courses c ON te.course_id = c.id
            JOIN users u ON te.lecturer_id = u.id
            JOIN rooms r ON te.room_id = r.id
            WHERE te.day = ? AND te.published = 1
            ORDER BY te.start_time
        """, (today_name,)).fetchall()
        db.close()
        if today_entries:
            responses.append(f"Today's schedule ({today_name}):\n" +
                            "\n".join(f"  - {e['start_time']}-{e['end_time']}: {e['course_name']} ({e['code']}) in {e['room_name']} with {e['lecturer_name']}" for e in today_entries))
        else:
            responses.append(f"No classes scheduled for {today_name}.")

    if not responses:
        responses.append("I can help you with:\n" +
                        "- Check timetable conflicts and clashes\n" +
                        "- View efficiency score\n" +
                        "- Lecturer workload information\n" +
                        "- Room utilization stats\n" +
                        "- Version history\n" +
                        "- Today's schedule\n" +
                        "Try asking about any of these topics!")

    return "\n".join(responses)
