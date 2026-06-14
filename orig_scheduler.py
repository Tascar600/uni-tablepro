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

SLOT_START = time(7, 0)
SLOT_END = time(18, 0)
SLOT_INTERVAL = 30


def time_to_minutes(t):
    return t.hour * 60 + t.minute


def minutes_to_time(m):
    return time(m // 60, m % 60)


def generate_start_times():
    start_m = time_to_minutes(SLOT_START)
    end_m = time_to_minutes(SLOT_END)
    times = []
    m = start_m
    while m + 30 <= end_m:
        times.append(minutes_to_time(m))
        m += SLOT_INTERVAL
    return times


START_TIMES = generate_start_times()


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
    import traceback
    db = get_db()

    courses = db.execute("""
        SELECT c.*, u.full_name as lecturer_name
        FROM courses c JOIN users u ON c.lecturer_id = u.id
    """).fetchall()

    db.execute("DELETE FROM substitute_allocations")
    db.execute("DELETE FROM conflict_resolutions")
    db.execute("DELETE FROM timetable_versions")
    db.execute("DELETE FROM timetable_entries")
    db.execute("UPDATE app_settings SET value='0' WHERE key='timetable_published'")

    rooms = db.execute("SELECT * FROM rooms WHERE is_active=1").fetchall()
    lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()

    lecture_prefs = {}
    for lec in lecturers:
        pref = db.execute("SELECT * FROM lecturer_preferences WHERE user_id=?", (lec['id'],)).fetchone()
        if pref:
            lecture_prefs[lec['id']] = {
                'days': json.loads(pref['preferred_days']) if pref['preferred_days'] else DAYS[:],
                'start': time_to_minutes(datetime.strptime(pref['preferred_time_start'] or '08:00', '%H:%M').time()),
                'end': time_to_minutes(datetime.strptime(pref['preferred_time_end'] or '17:00', '%H:%M').time()),
                'max_hours': pref['max_hours_per_week'] or 40,
                'avoid_back_to_back': pref['avoid_back_to_back'],
                'lunch_break': pref['lunch_break_optimize'],
                'max_consecutive': pref['max_consecutive_hours'] or 8.0,
            }
        else:
            lecture_prefs[lec['id']] = {
                'days': DAYS[:], 'start': time_to_minutes(time(8, 0)),
                'end': time_to_minutes(time(17, 0)), 'max_hours': 40,
                'avoid_back_to_back': 1, 'lunch_break': 1, 'max_consecutive': 8.0,
            }

    lunch_start = time_to_minutes(LUNCH_START_TIME)
    lunch_end = time_to_minutes(LUNCH_END_TIME)
    break_start = time_to_minutes(BREAK_START)
    break_end = time_to_minutes(BREAK_END)

    missing_rooms_fallback = False
    if not rooms:
        db.execute("INSERT INTO rooms (name, capacity, is_active) VALUES ('Default Room', 30, 1)")
        db.commit()
        rooms = db.execute("SELECT * FROM rooms WHERE is_active=1").fetchall()
        missing_rooms_fallback = True

    courses_list = list(courses)
    random.shuffle(courses_list)

    assigned = []
    entries = []
    lecturer_hours = {lec['id']: 0 for lec in lecturers}

    unassigned = []

    for course in courses_list:
        lec_id = course['lecturer_id']
        prefs = lecture_prefs.get(lec_id, {})
        pref_days = prefs.get('days', DAYS[:])
        pref_start = prefs.get('start', time_to_minutes(time(8, 0)))
        pref_end = prefs.get('end', time_to_minutes(time(17, 0)))
        avoid_b2b = prefs.get('avoid_back_to_back', 1)
        lunch_opt = prefs.get('lunch_break', 1)
        course_duration = course['duration_hours']
        course_duration_min = int(course_duration * 60)

        assigned_flag = False
        reason = None

        trial_times = []
        for d in pref_days:
            for t in START_TIMES:
                trial_times.append((d, t))
        random.shuffle(trial_times)

        for day, start_time in trial_times:
            if assigned_flag:
                break

            start_mins = time_to_minutes(start_time)
            actual_end_min = start_mins + course_duration_min
            day_end_mins = time_to_minutes(SLOT_END)

            if actual_end_min > min(day_end_mins, pref_end):
                continue
            if start_mins < pref_start:
                continue

            actual_end = minutes_to_time(actual_end_min)

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
                    if start_mins > a_end:
                        gap = start_mins - a_end
                    elif actual_end_min < a_start:
                        gap = a_start - actual_end_min
                    else:
                        continue
                    if 0 < gap < BREAK_MINUTES:
                        b2b_conflict = True
                        break
                if b2b_conflict:
                    continue

            new_hours = lecturer_hours.get(lec_id, 0) + course_duration
            if new_hours > prefs.get('max_hours', 40):
                reason = f"Lecturer max hours ({prefs.get('max_hours', 40)}) exceeded"
                continue

            valid_rooms = list(rooms)
            random.shuffle(valid_rooms)
            placed = False

            for room in valid_rooms:
                room_id = room['id']
                conflict, _ = has_conflict(assigned, lec_id, room_id, course['group_name'],
                                           day, start_mins, actual_end_min)
                if not conflict:
                    entry_data = {
                        'course_id': course['id'], 'lecturer_id': lec_id, 'room_id': room_id,
                        'day': day, 'start_time': start_time.strftime('%H:%M'),
                        'end_time': actual_end.strftime('%H:%M'), 'group_name': course['group_name'],
                        'course_name': course['name'], 'code': course['code'],
                        'level': course['level'], 'lecturer_name': course['lecturer_name'],
                        'room_name': room['name'],
                    }

                    db.execute("""
                        INSERT INTO timetable_entries (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
                        VALUES (?,?,?,?,?,?,?,0)
                    """, (entry_data['course_id'], entry_data['lecturer_id'], entry_data['room_id'],
                          entry_data['day'], entry_data['start_time'], entry_data['end_time'], entry_data['group_name']))

                    assigned.append({
                        'id': len(assigned) + 1,
                        'lecturer_id': lec_id, 'room_id': room_id, 'day': day,
                        'start_time': start_time.strftime('%H:%M'),
                        'end_time': actual_end.strftime('%H:%M'),
                        'start_m': start_mins, 'end_m': actual_end_min,
                        'group_name': course['group_name'],
                        'course_name': course['name'],
                    })
                    lecturer_hours[lec_id] = lecturer_hours.get(lec_id, 0) + course_duration
                    entries.append(entry_data)
                    assigned_flag = True
                    placed = True
                    break

        if not assigned_flag and reason is None:
            reason = "No available time slot in preferred days"

        if not assigned_flag:
            fallback_times = []
            for d in DAYS:
                if d in pref_days:
                    continue
                for t in START_TIMES:
                    fallback_times.append((d, t))
            random.shuffle(fallback_times)

            for day, start_time in fallback_times:
                if assigned_flag:
                    break

                start_mins = time_to_minutes(start_time)
                actual_end_min = start_mins + course_duration_min
                day_end_mins = time_to_minutes(SLOT_END)

                if actual_end_min > min(day_end_mins, pref_end):
                    continue
                if start_mins < pref_start:
                    continue

                actual_end = minutes_to_time(actual_end_min)

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

                valid_rooms = list(rooms)
                random.shuffle(valid_rooms)
                for room in valid_rooms:
                    room_id = room['id']
                    conflict, _ = has_conflict(assigned, lec_id, room_id, course['group_name'],
                                               day, start_mins, actual_end_min)
                    if not conflict:
                        entry_data = {
                            'course_id': course['id'], 'lecturer_id': lec_id, 'room_id': room_id,
                            'day': day, 'start_time': start_time.strftime('%H:%M'),
                            'end_time': actual_end.strftime('%H:%M'), 'group_name': course['group_name'],
                            'course_name': course['name'], 'code': course['code'],
                            'level': course['level'], 'lecturer_name': course['lecturer_name'],
                            'room_name': room['name'],
                        }
                        db.execute("""
                            INSERT INTO timetable_entries (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
                            VALUES (?,?,?,?,?,?,?,0)
                        """, (entry_data['course_id'], entry_data['lecturer_id'], entry_data['room_id'],
                              entry_data['day'], entry_data['start_time'], entry_data['end_time'], entry_data['group_name']))
                        assigned.append({
                            'id': len(assigned) + 1,
                            'lecturer_id': lec_id, 'room_id': room_id, 'day': day,
                            'start_time': start_time.strftime('%H:%M'),
                            'end_time': actual_end.strftime('%H:%M'),
                            'start_m': start_mins, 'end_m': actual_end_min,
                            'group_name': course['group_name'],
                            'course_name': course['name'],
                        })
                        entries.append(entry_data)
                        assigned_flag = True
                        reason = None
                        break

            if not assigned_flag:
                unassigned.append({
                    'course_name': course['name'],
                    'code': course['code'],
                    'lecturer_name': course.get('lecturer_name', 'N/A'),
                    'reason': reason or 'Could not find any available time slot',
                })

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
    return entries, unassigned


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
