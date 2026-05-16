import json
from datetime import time, datetime, timedelta
from models import get_db
import random

BREAK_MINUTES = 15
BREAK_START = time(10, 0)
BREAK_END = time(10, 15)
LUNCH_MINUTES = 30
LUNCH_START_TIME = time(13, 0)
LUNCH_END_TIME = time(13, 30)
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
TIME_SLOTS = [
    (time(7, 0), time(10, 0)),
    (time(10, 15), time(13, 0)),
    (time(13, 30), time(16, 0)),
    (time(16, 0), time(18, 0)),
]


def time_to_minutes(t):
    return t.hour * 60 + t.minute


def minutes_to_time(m):
    return time(m // 60, m % 60)


def has_conflict(assigned, lecturer_id, room_id, group_name, day, start_m, end_m, exclude_id=None):
    for a in assigned:
        if exclude_id and a.get('id') == exclude_id:
            continue
        if a['day'] != day:
            continue
        a_start = a['start_m']
        a_end = a['end_m']

        padded_start = start_m - BREAK_MINUTES
        padded_end = end_m + BREAK_MINUTES

        if a['lecturer_id'] == lecturer_id and padded_start < a_end and padded_end > a_start:
            return True, f"Lecturer conflict with {a.get('course_name','unknown')} ({a['start_time']}-{a['end_time']}) (needs 15min break)"
        if a['room_id'] == room_id and padded_start < a_end and padded_end > a_start:
            return True, f"Room conflict with {a.get('course_name','unknown')} ({a['start_time']}-{a['end_time']}) (needs 15min buffer)"
        if a['group_name'] == group_name and padded_start < a_end and padded_end > a_start:
            return True, f"Group conflict with {a.get('course_name','unknown')} ({a['start_time']}-{a['end_time']}) (needs 15min break)"
    return False, None


def calculate_efficiency(entries):
    if not entries:
        return 0
    score = 100
    lunch_start = time_to_minutes(LUNCH_START_TIME)
    lunch_end = time_to_minutes(LUNCH_END_TIME)
    break_start = time_to_minutes(BREAK_START)
    break_end = time_to_minutes(BREAK_END)
    lecturer_days = {}
    for e in entries:
        lec = e['lecturer_id']
        if lec not in lecturer_days:
            lecturer_days[lec] = {}
        if e['day'] not in lecturer_days[lec]:
            lecturer_days[lec][e['day']] = []
        lecturer_days[lec][e['day']].append({
            'start': time_to_minutes(datetime.strptime(e['start_time'], '%H:%M').time()),
            'end': time_to_minutes(datetime.strptime(e['end_time'], '%H:%M').time()),
        })

    for lec, days in lecturer_days.items():
        for day, slots in days.items():
            slots.sort(key=lambda x: x['start'])
            total_hours = sum((s['end'] - s['start']) / 60 for s in slots)
            if total_hours > 8:
                score -= 5
            gap_violations = 0
            lunch_covered = False
            for i in range(len(slots) - 1):
                gap = slots[i + 1]['start'] - slots[i]['end']
                if gap == 0:
                    gap_violations += 1
                    score -= 3
                elif 0 < gap < BREAK_MINUTES:
                    gap_violations += 1
                    score -= 2
                elif BREAK_MINUTES <= gap < 30:
                    score += 1
                if slots[i]['end'] <= lunch_start and slots[i + 1]['start'] >= lunch_end:
                    lunch_covered = True
            if lunch_covered:
                score += 5
        if len(days) > 5:
            score -= 5

    room_usage = {}
    for e in entries:
        room_usage[e['room_id']] = room_usage.get(e['room_id'], 0) + 1
    avg_usage = sum(room_usage.values()) / max(len(room_usage), 1)
    for r, count in room_usage.items():
        if abs(count - avg_usage) > avg_usage * 0.5:
            score -= 2

    return max(0, min(100, score))


def generate_timetable():
    db = get_db()
    db.execute("DELETE FROM timetable_entries")
    db.execute("UPDATE app_settings SET value='0' WHERE key='timetable_published'")

    courses = db.execute("""
        SELECT c.*, u.full_name as lecturer_name
        FROM courses c JOIN users u ON c.lecturer_id = u.id
        ORDER BY
            CASE c.level
                WHEN 'university' THEN 0
                WHEN 'department' THEN 1
                WHEN 'single' THEN 2
            END, c.duration_hours DESC
    """).fetchall()

    rooms = db.execute("SELECT * FROM rooms WHERE is_active=1").fetchall()
    lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()

    lecturer_prefs = {}
    for lec in lecturers:
        pref = db.execute("SELECT * FROM lecturer_preferences WHERE user_id=?", (lec['id'],)).fetchone()
        if pref:
            lecturer_prefs[lec['id']] = {
                'days': json.loads(pref['preferred_days']) if pref['preferred_days'] else DAYS[:],
                'start': time_to_minutes(datetime.strptime(pref['preferred_time_start'] or '08:00', '%H:%M').time()),
                'end': time_to_minutes(datetime.strptime(pref['preferred_time_end'] or '17:00', '%H:%M').time()),
                'max_hours': pref['max_hours_per_week'] or 20,
                'avoid_back_to_back': pref['avoid_back_to_back'],
                'lunch_break': pref['lunch_break_optimize'],
                'max_consecutive': pref['max_consecutive_hours'] or 3.0,
            }
        else:
            lecturer_prefs[lec['id']] = {
                'days': DAYS[:], 'start': time_to_minutes(time(8, 0)),
                'end': time_to_minutes(time(17, 0)), 'max_hours': 20,
                'avoid_back_to_back': 1, 'lunch_break': 1, 'max_consecutive': 3.0,
            }

    lunch_start = time_to_minutes(LUNCH_START_TIME)
    lunch_end = time_to_minutes(LUNCH_END_TIME)
    break_start = time_to_minutes(BREAK_START)
    break_end = time_to_minutes(BREAK_END)

    assigned = []
    entries = []
    random.shuffle(courses)

    expanded_slots = []
    for day in DAYS:
        for slot_start, slot_end in TIME_SLOTS:
            expanded_slots.append((day, slot_start, slot_end))

    lecturer_hours = {lec['id']: 0 for lec in lecturers}

    for course in courses:
        lec_id = course['lecturer_id']
        prefs = lecturer_prefs.get(lec_id, {})
        pref_days = prefs.get('days', DAYS[:])
        pref_start = prefs.get('start', time_to_minutes(time(8, 0)))
        pref_end = prefs.get('end', time_to_minutes(time(17, 0)))
        avoid_b2b = prefs.get('avoid_back_to_back', 1)
        lunch_opt = prefs.get('lunch_break', 1)
        course_duration = course['duration_hours']
        course_duration_min = int(course_duration * 60)

        assigned_flag = False
        slots_to_try = [(d, s, e) for d in DAYS for s, e in TIME_SLOTS]
        random.shuffle(slots_to_try)

        for day, slot_start, slot_end in slots_to_try:
            if assigned_flag:
                break
            if day not in pref_days:
                continue

            start_mins = time_to_minutes(slot_start)
            end_mins = time_to_minutes(slot_end)
            slot_duration = (end_mins - start_mins) / 60.0

            if course_duration > slot_duration + 0.1:
                continue

            available_end = min(end_mins, pref_end)
            if start_mins + course_duration_min > available_end:
                continue

            actual_end_min = start_mins + course_duration_min
            actual_end = minutes_to_time(actual_end_min)

            if start_mins < pref_start:
                continue

            if start_mins < break_end and actual_end_min > break_start:
                continue
            if start_mins >= break_start and start_mins < break_end:
                continue
            if actual_end_min > break_start and actual_end_min <= break_end:
                continue

            if lunch_opt:
                if start_mins < lunch_end and actual_end_min > lunch_start:
                    continue
                if start_mins >= lunch_start and start_mins < lunch_end:
                    continue
                if actual_end_min > lunch_start and actual_end_min <= lunch_end:
                    continue

            if avoid_b2b:
                b2b_conflict = False
                for a in assigned:
                    if a['lecturer_id'] != lec_id or a['day'] != day:
                        continue
                    a_end = a['end_m']
                    a_start = a['start_m']
                    gap = start_mins - a_end if start_mins > a_end else a_start - actual_end_min
                    if 0 < gap < BREAK_MINUTES:
                        b2b_conflict = True
                        break
                if b2b_conflict:
                    continue

            new_hours = lecturer_hours.get(lec_id, 0) + course_duration
            if new_hours > prefs.get('max_hours', 20):
                continue

            room_idx = len(entries) % len(rooms) if rooms else 0
            room_id = rooms[room_idx]['id'] if rooms else 1

            conflict, reason = has_conflict(assigned, lec_id, room_id, course['group_name'],
                                            day, start_mins, actual_end_min)
            if conflict:
                for r_idx, room in enumerate(rooms):
                    if r_idx == room_idx:
                        continue
                    conflict2, _ = has_conflict(assigned, lec_id, room['id'], course['group_name'],
                                                day, start_mins, actual_end_min)
                    if not conflict2:
                        room_id = room['id']
                        room_idx = r_idx
                        conflict = False
                        break
                if conflict:
                    continue

            entry_data = {
                'course_id': course['id'], 'lecturer_id': lec_id, 'room_id': room_id,
                'day': day, 'start_time': slot_start.strftime('%H:%M'),
                'end_time': actual_end.strftime('%H:%M'), 'group_name': course['group_name'],
                'course_name': course['name'], 'code': course['code'],
                'level': course['level'], 'lecturer_name': course['lecturer_name'],
                'room_name': next((r['name'] for r in rooms if r['id'] == room_id), 'Unknown'),
            }

            db.execute("""
                INSERT INTO timetable_entries (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
                VALUES (?,?,?,?,?,?,?,0)
            """, (entry_data['course_id'], entry_data['lecturer_id'], entry_data['room_id'],
                  entry_data['day'], entry_data['start_time'], entry_data['end_time'], entry_data['group_name']))

            assigned.append({
                'id': len(assigned) + 1,
                'lecturer_id': lec_id, 'room_id': room_id, 'day': day,
                'start_time': slot_start.strftime('%H:%M'),
                'end_time': actual_end.strftime('%H:%M'),
                'start_m': start_mins, 'end_m': actual_end_min,
                'group_name': course['group_name'],
                'course_name': course['name'],
            })
            lecturer_hours[lec_id] = lecturer_hours.get(lec_id, 0) + course_duration
            entries.append(entry_data)
            assigned_flag = True

        if not assigned_flag:
            for day in DAYS:
                if day in pref_days:
                    continue
                if assigned_flag:
                    break
                for slot_start, slot_end in TIME_SLOTS:
                    if assigned_flag:
                        break
                    start_mins = time_to_minutes(slot_start)
                    end_mins = time_to_minutes(slot_end)
                    slot_duration = (end_mins - start_mins) / 60.0
                    if course_duration > slot_duration + 0.1:
                        continue
                    actual_end_min = start_mins + course_duration_min
                    actual_end = minutes_to_time(actual_end_min)
                    if start_mins < pref_start:
                        continue
                    if start_mins < break_end and actual_end_min > break_start:
                        continue
                    if start_mins >= break_start and start_mins < break_end:
                        continue
                    if actual_end_min > break_start and actual_end_min <= break_end:
                        continue
                    if lunch_opt:
                        if start_mins < lunch_end and actual_end_min > lunch_start:
                            continue
                        if start_mins >= lunch_start and start_mins < lunch_end:
                            continue
                        if actual_end_min > lunch_start and actual_end_min <= lunch_end:
                            continue
                    room_idx = len(entries) % len(rooms) if rooms else 0
                    room_id = rooms[room_idx]['id'] if rooms else 1
                    conflict, _ = has_conflict(assigned, lec_id, room_id, course['group_name'],
                                               day, start_mins, actual_end_min)
                    if conflict:
                        for r in rooms:
                            if r['id'] == room_id:
                                continue
                            c2, _ = has_conflict(assigned, lec_id, r['id'], course['group_name'],
                                                 day, start_mins, actual_end_min)
                            if not c2:
                                room_id = r['id']
                                conflict = False
                                break
                    if conflict:
                        continue

                    entry_data = {
                        'course_id': course['id'], 'lecturer_id': lec_id, 'room_id': room_id,
                        'day': day, 'start_time': slot_start.strftime('%H:%M'),
                        'end_time': actual_end.strftime('%H:%M'), 'group_name': course['group_name'],
                        'course_name': course['name'], 'code': course['code'],
                        'level': course['level'], 'lecturer_name': course['lecturer_name'],
                        'room_name': next((r['name'] for r in rooms if r['id'] == room_id), 'Unknown'),
                    }
                    db.execute("""
                        INSERT INTO timetable_entries (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
                        VALUES (?,?,?,?,?,?,?,0)
                    """, (entry_data['course_id'], entry_data['lecturer_id'], entry_data['room_id'],
                          entry_data['day'], entry_data['start_time'], entry_data['end_time'], entry_data['group_name']))
                    entries.append(entry_data)
                    assigned_flag = True

    efficiency = calculate_efficiency(entries)
    db.execute("UPDATE app_settings SET value=? WHERE key='efficiency_score'", (str(efficiency),))

    snapshot = json.dumps([dict(e) for e in entries])
    cursor = db.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM timetable_versions")
    next_ver = cursor.fetchone()[0]
    db.execute("UPDATE timetable_versions SET is_active=0")
    db.execute("INSERT INTO timetable_versions (version_number, created_by, snapshot_data, notes, is_active) VALUES (?,?,?,?,1)",
               (next_ver, 1, snapshot, f'Auto-generated version {next_ver}'))

    db.commit()
    db.close()
    return entries


def get_timetable(published_only=False, entry_id=None):
    db = get_db()
    query = """
        SELECT te.*, c.name as course_name, c.code, c.level, c.color,
               u.full_name as lecturer_name, r.name as room_name,
               r.building, r.room_type, r.capacity
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
    """
    conditions = []
    params = []
    if published_only:
        conditions.append("te.published = 1")
    if entry_id:
        conditions.append("te.id = ?")
        params.append(entry_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += """
        ORDER BY
            CASE te.day
                WHEN 'Monday' THEN 0
                WHEN 'Tuesday' THEN 1
                WHEN 'Wednesday' THEN 2
                WHEN 'Thursday' THEN 3
                WHEN 'Friday' THEN 4
            END,
            te.start_time
    """
    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


def is_published():
    db = get_db()
    row = db.execute("SELECT value FROM app_settings WHERE key='timetable_published'").fetchone()
    db.close()
    return row and row['value'] == '1'


def publish_timetable():
    db = get_db()
    db.execute("UPDATE timetable_entries SET published=1")
    db.execute("UPDATE app_settings SET value='1' WHERE key='timetable_published'")
    db.commit()
    db.close()


def unpublish_timetable():
    db = get_db()
    db.execute("UPDATE timetable_entries SET published=0")
    db.execute("UPDATE app_settings SET value='0' WHERE key='timetable_published'")
    db.commit()
    db.close()
