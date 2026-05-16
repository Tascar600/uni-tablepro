import json
import os
from datetime import datetime, timedelta
from models import get_db


def export_ics(timetable_entries, filename=None):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Timetable System//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
    ]

    week_start = datetime.now()
    while week_start.weekday() != 0:
        week_start -= timedelta(days=1)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    day_offset = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}

    for entry in timetable_entries:
        day_name = entry.get('day', 'Monday')
        offset = day_offset.get(day_name, 0)
        event_date = week_start + timedelta(days=offset)

        start_h, start_m = map(int, entry['start_time'].split(':'))
        end_h, end_m = map(int, entry['end_time'].split(':'))

        dt_start = event_date.replace(hour=start_h, minute=start_m, second=0)
        dt_end = event_date.replace(hour=end_h, minute=end_m, second=0)

        uid = f"timetable-{entry.get('id', '0')}-{datetime.now().strftime('%Y%m%d')}@timetable"

        summary = f"{entry.get('course_name', 'Lecture')} ({entry.get('code', '')})"
        location = entry.get('room_name', '')
        description = f"Lecturer: {entry.get('lecturer_name', '')}\nGroup: {entry.get('group_name', '')}\nCourse: {entry.get('course_name', '')} ({entry.get('code', '')})"

        lines.extend([
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTART:{dt_start.strftime("%Y%m%dT%H%M%S")}',
            f'DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}',
            f'SUMMARY:{summary}',
            f'LOCATION:{location}',
            f'DESCRIPTION:{description}',
            'END:VEVENT',
        ])

    lines.append('END:VCALENDAR')
    content = '\r\n'.join(lines)

    if filename:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return filename
    return content


def export_csv(timetable_entries, filename=None):
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Day', 'Start Time', 'End Time', 'Course Name', 'Course Code',
                     'Level', 'Lecturer', 'Group', 'Room', 'Building', 'Status'])
    for e in timetable_entries:
        writer.writerow([
            e.get('day', ''), e.get('start_time', ''), e.get('end_time', ''),
            e.get('course_name', ''), e.get('code', ''),
            e.get('level', ''), e.get('lecturer_name', ''),
            e.get('group_name', ''), e.get('room_name', ''),
            e.get('building', ''), e.get('status', 'scheduled'),
        ])
    content = output.getvalue()
    output.close()

    if filename:
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(content)
        return filename
    return content


def get_ical_feed(token=None):
    db = get_db()
    entries = db.execute("""
        SELECT te.*, c.name as course_name, c.code,
               u.full_name as lecturer_name, r.name as room_name
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
        WHERE te.published = 1
    """).fetchall()
    db.close()
    return export_ics([dict(e) for e in entries])


def save_draft(user_id, data):
    db = get_db()
    existing = db.execute("SELECT id FROM draft_timetables WHERE user_id=?", (user_id,)).fetchone()
    if existing:
        db.execute("UPDATE draft_timetables SET data=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                   (json.dumps(data), user_id))
    else:
        db.execute("INSERT INTO draft_timetables (user_id, name, data) VALUES (?,?,?)",
                   (user_id, 'Draft', json.dumps(data)))
    db.commit()
    db.close()


def get_draft(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM draft_timetables WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    if row:
        return {'id': row['id'], 'data': json.loads(row['data']), 'updated_at': row['updated_at']}
    return None


def delete_old_exports(directory, max_age_hours=24):
    now = datetime.now()
    for f in os.listdir(directory):
        path = os.path.join(directory, f)
        if os.path.isfile(path):
            age = now - datetime.fromtimestamp(os.path.getmtime(path))
            if age > timedelta(hours=max_age_hours):
                os.remove(path)
