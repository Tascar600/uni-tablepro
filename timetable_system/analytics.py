import json
from collections import defaultdict
from datetime import datetime
from models import get_db


def get_analytics_data():
    db = get_db()
    entries = db.execute("""
        SELECT te.*, c.name as course_name, c.code, c.level,
               u.full_name as lecturer_name, r.name as room_name,
               r.capacity, r.building, r.room_type,
               dep.name as department_name
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
        LEFT JOIN departments dep ON c.department_id = dep.id
    """).fetchall()

    lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()
    rooms = db.execute("SELECT * FROM rooms").fetchall()
    courses = db.execute("SELECT * FROM courses").fetchall()
    depts = db.execute("SELECT * FROM departments").fetchall()
    students = db.execute("SELECT COUNT(*) as count FROM users WHERE role='student'").fetchone()

    eff_row = db.execute("SELECT value FROM app_settings WHERE key='efficiency_score'").fetchone()
    efficiency = int(eff_row['value']) if eff_row else 0

    db.close()

    entries_list = [dict(e) for e in entries]

    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

    day_distribution = defaultdict(int)
    hour_distribution = defaultdict(int)
    lecturer_load = defaultdict(lambda: {'count': 0, 'hours': 0.0, 'courses': []})
    room_usage = defaultdict(lambda: {'count': 0, 'hours': 0.0, 'capacity': 0, 'name': '', 'entries': []})
    level_distribution = defaultdict(int)
    department_stats = defaultdict(lambda: {'courses': 0, 'hours': 0.0})
    group_distribution = defaultdict(int)

    for e in entries_list:
        day_distribution[e['day']] += 1

        start_h = int(e['start_time'].split(':')[0])
        hour_distribution[f"{start_h}:00"] += 1

        lec_id = e['lecturer_id']
        duration = (datetime.strptime(e['end_time'], '%H:%M') - datetime.strptime(e['start_time'], '%H:%M')).seconds / 3600
        lecturer_load[lec_id]['count'] += 1
        lecturer_load[lec_id]['hours'] += duration
        lecturer_load[lec_id]['courses'].append(e['course_name'])

        room_id = e['room_id']
        room_usage[room_id]['count'] += 1
        room_usage[room_id]['hours'] += duration
        room_usage[room_id]['entries'].append(e)

        level_distribution[e['level']] += 1
        group_distribution[e['group_name']] += 1

    for r in rooms:
        rid = r['id']
        room_usage[rid]['capacity'] = r['capacity']
        room_usage[rid]['name'] = r['name']

    lecturer_chart = []
    for lec in lecturers:
        lid = lec['id']
        data = lecturer_load.get(lid, {'count': 0, 'hours': 0.0, 'courses': []})
        lecturer_chart.append({
            'name': lec['full_name'],
            'count': data['count'],
            'hours': round(data['hours'], 1),
        })

    room_chart = []
    for rid, data in sorted(room_usage.items(), key=lambda x: x[1]['hours'], reverse=True):
        room_chart.append({
            'name': data['name'],
            'count': data['count'],
            'hours': round(data['hours'], 1),
            'capacity': data['capacity'],
            'utilization': min(100, round((data['hours'] / 40) * 100)),
        })

    return {
        'total_entries': len(entries_list),
        'total_lecturers': len(lecturers),
        'total_rooms': len(rooms),
        'total_courses': len(courses),
        'total_students': students['count'] if students else 0,
        'efficiency': efficiency,
        'day_distribution': dict(day_distribution),
        'hour_distribution': dict(hour_distribution),
        'lecturer_load': lecturer_chart,
        'room_usage': room_chart,
        'level_distribution': dict(level_distribution),
        'group_distribution': dict(group_distribution),
        'days_order': days_order,
        'published_count': sum(1 for e in entries_list if e['published']),
    }


def get_lecturer_workload(lecturer_id=None):
    db = get_db()
    query = """
        SELECT te.*, c.name as course_name, c.code,
               u.full_name as lecturer_name, r.name as room_name
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
    """
    params = []
    if lecturer_id:
        query += " WHERE te.lecturer_id = ?"
        params.append(lecturer_id)

    entries = db.execute(query, params).fetchall()
    db.close()

    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    daily = defaultdict(list)
    total_hours = 0
    total_classes = len(entries)

    for e in entries:
        e = dict(e)
        duration = (datetime.strptime(e['end_time'], '%H:%M') - datetime.strptime(e['start_time'], '%H:%M')).seconds / 3600
        total_hours += duration
        daily[e['day']].append({**e, 'duration': round(duration, 1)})

    daily_stats = {}
    for day in days_order:
        day_entries = daily.get(day, [])
        day_hours = sum(e['duration'] for e in day_entries)
        daily_stats[day] = {
            'count': len(day_entries),
            'hours': round(day_hours, 1),
            'entries': day_entries,
        }

    return {
        'total_classes': total_classes,
        'total_hours': round(total_hours, 1),
        'daily_stats': daily_stats,
        'days_order': days_order,
        'average_daily_hours': round(total_hours / max(len(daily), 1), 1),
    }


def get_room_heatmap():
    db = get_db()
    entries = db.execute("""
        SELECT te.day, te.start_time, te.end_time, te.room_id, r.name as room_name, r.capacity
        FROM timetable_entries te
        JOIN rooms r ON te.room_id = r.id
    """).fetchall()
    db.close()

    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    time_slots = ['08:00-10:00', '10:00-12:00', '12:00-14:00', '14:00-16:00', '16:00-17:00']

    rooms_data = defaultdict(lambda: {day: {slot: 0 for slot in time_slots} for day in days_order})

    for e in entries:
        e = dict(e)
        start_h = int(e['start_time'].split(':')[0])
        for slot in time_slots:
            slot_start = int(slot.split('-')[0].split(':')[0])
            slot_end = int(slot.split('-')[1].split(':')[0])
            if slot_start <= start_h < slot_end:
                rooms_data[e['room_id']][e['day']][slot] += 1
                break

    heatmap = []
    for rid, days in rooms_data.items():
        heatmap.append({
            'room_id': rid,
            'data': dict(days),
        })

    return {
        'rooms': heatmap,
        'days': days_order,
        'slots': time_slots,
    }
