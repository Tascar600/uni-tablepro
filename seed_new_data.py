"""Replace all timetable data with the Comp Science Modular Timetable."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'timetable_system'))
from models import get_db, init_db

init_db()
db = get_db()

# ── Delete in FK-safe order: children before parents ──
delete_order = [
    'attendance_records',   # FK -> timetable_entries
    'substitute_allocations', # FK -> timetable_entries, users
    'conflict_resolutions',  # FK -> timetable_entries
    'draft_timetables',      # FK -> users
    'lecturer_preferences',  # FK -> users
    'lecturer_availability', # FK -> users
    'student_enrollments',   # FK -> courses, users
    'timetable_versions',    # FK -> users
    'timetable_entries',     # FK -> courses, users, rooms
    'activity_logs',         # FK -> users
    'notifications',         # FK -> users
    'timetable_shares',      # FK -> users
    'courses',               # FK -> users (lecturer_id), departments
    'users',                 # FK -> departments
]
for t in delete_order:
    db.execute(f"DELETE FROM {t}")
db.execute("DELETE FROM rooms")
db.execute("DELETE FROM departments")
db.execute("DELETE FROM app_settings")
db.commit()

# ── Departments ──
db.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Computer Science', 'CS'))
db.commit()
cs_dept_id = db.execute("SELECT id FROM departments WHERE code='CS'").fetchone()[0]
db.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Mathematics', 'MATH'))
db.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Engineering', 'ENG'))
db.commit()

# ── Rooms (venues) ──
rooms_list = [
    ('FSE HALL', 200, 'Main', 1, 'lecture_hall'),
    ('PC108', 60, 'Main', 1, 'lab'),
]
for name, cap, building, floor, rtype in rooms_list:
    db.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, is_active) VALUES (?,?,?,?,?,1,1)",
               (name, cap, building, floor, rtype))
db.commit()

room_map = {}
for r in db.execute("SELECT id, name FROM rooms").fetchall():
    room_map[r['name']] = r['id']

# ── Admin user ──
db.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
           ('admin', 'admin123', 'admin', 'System Admin', 'admin@uni.edu', cs_dept_id))
db.commit()

# ── Lecturers (from color key) ──
lecturers_data = [
    ('mhlangamiso', 'Mhlanga Miso',    'mhlangamiso@uni.edu'),
    ('chaitezvi',   'Chaitezvi',       'chaitezvi@uni.edu'),
    ('mhlanga',     'Mhlanga',         'mhlanga@uni.edu'),
    ('chituna',     'Chituna',         'chituna@uni.edu'),
    ('zano',        'Zano',            'zano@uni.edu'),
    ('sakala',      'Sakala',          'sakala@uni.edu'),
    ('ndumiyana',   'Ndumiyana',       'ndumiyana@uni.edu'),
    ('chikwiriro',  'Chikwiriro',      'chikwiriro@uni.edu'),
]
for uname, fname, email in lecturers_data:
    db.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
               (uname, 'password', 'lecturer', fname, email, cs_dept_id))
db.commit()

lec_map = {}
for l in db.execute("SELECT id, username FROM users WHERE role='lecturer'").fetchall():
    lec_map[l['username']] = l['id']

# ── Lecturer color mapping ──
color_to_lecturers = {
    'Yellow':    ['mhlangamiso', 'chituna'],
    'Green':     ['mhlangamiso', 'chaitezvi'],
    'Orange':    ['zano'],
    'Purple':    ['sakala'],
    'Light Blue':['ndumiyana'],
    'Pink/Red':  ['chikwiriro'],
    'Red':       ['sakala'],
    'Brown':     ['mhlanga'],
}

# ── Courses (unique codes) ──
course_codes = [
    ('CS216',   'Computer Science 216'),
    ('CSH116',  'Computer Science Honours 116'),
    ('SWE115',  'Software Engineering 115'),
    ('CS214',   'Computer Science 214'),
    ('NWE214',  'Network Engineering 214'),
    ('SWE212',  'Software Engineering 212'),
    ('SWE214',  'Software Engineering 214'),
    ('NWE216',  'Network Engineering 216'),
    ('SWE211',  'Software Engineering 211'),
    ('EEE2203', 'Electrical Engineering 2203'),
    ('NWE411',  'Network Engineering 411'),
    ('C112',    'Computing 112'),
    ('EEE1204', 'Electrical Engineering 1204'),
    ('AMT114',  'Applied Mathematics & Technology 114'),
    ('SWE201',  'Software Engineering 201'),
    ('CS412',   'Computer Science 412'),
    ('CS218',   'Computer Science 218'),
    ('CS201',   'Computer Science 201'),
    ('CSH115',  'Computer Science Honours 115'),
    ('NWE111',  'Network Engineering 111'),
    ('SWE114',  'Software Engineering 114'),
    ('NWE410',  'Network Engineering 410'),
    ('SWE416',  'Software Engineering 416'),
    ('SWE112',  'Software Engineering 112'),
    ('SWE205',  'Software Engineering 205'),
    ('SWE215',  'Software Engineering 215'),
]

default_lec = lec_map['sakala']
for code, name in course_codes:
    db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, color, department_id) VALUES (?,?,?,?,?,?,?,?)",
               (name, code, 'department', default_lec, 'A', 2.0, '#4A90D9', cs_dept_id))
db.commit()

course_map = {}
for c in db.execute("SELECT id, code FROM courses").fetchall():
    course_map[c['code']] = c['id']

# ── Timetable time slots ──
time_slots = [
    ('0750', '0950'),
    ('1000', '1200'),
    ('1210', '1410'),
    ('1415', '1615'),
    ('1620', '1820'),
]

color_to_hex = {
    'Yellow': '#FFD700', 'Green': '#00CC66', 'Orange': '#FF8C00',
    'Purple': '#9932CC', 'Light Blue': '#4FC3F7', 'Pink/Red': '#FF6B81',
    'Red': '#FF4444', 'Brown': '#8B4513',
}

def get_lec(color):
    names = color_to_lecturers.get(color, ['sakala'])
    return lec_map[names[0]]

# ── Timetable data: (day, slot_idx, venue, group, course_codes_str, color) ──
entries_data = [
    # === 0750-0950 (slot 0) ===
    ('Monday',    0, 'FSE HALL', 'F06', 'CS216/CSH116/SWE115',            'Yellow'),
    ('Monday',    0, 'FSE HALL', 'F10', 'CS214/NWE214/SWE212',            'Purple'),
    ('Tuesday',   0, 'PC108',    'F06', 'SWE214',                          'Brown'),
    ('Tuesday',   0, 'PC108',    'F10', 'NWE216',                          'Pink/Red'),
    ('Wednesday', 0, 'FSE HALL', 'F10', 'SWE211/EEE2203',                  'Red'),
    ('Thursday',  0, 'FSE HALL', 'F06', 'NWE411',                          'Light Blue'),
    ('Thursday',  0, 'FSE HALL', 'F10', 'C112/EEE1204/AMT114/SWE201',      'Light Blue'),
    ('Friday',    0, 'FSE HALL', 'F10', 'CS412',                           'Green'),

    # === 1000-1200 (slot 1) ===
    ('Monday',    1, 'FSE HALL', 'F06', 'CS216/CSH116/SWE115',            'Yellow'),
    ('Monday',    1, 'FSE HALL', 'F10', 'CS214/NWE214/SWE212',            'Purple'),
    ('Tuesday',   1, 'PC108',    'F06', 'SWE214',                          'Brown'),
    ('Tuesday',   1, 'PC108',    'F10', 'NWE216',                          'Pink/Red'),
    ('Wednesday', 1, 'FSE HALL', 'F10', 'SWE211/EEE2203',                  'Red'),
    ('Thursday',  1, 'FSE HALL', 'F06', 'NWE411',                          'Light Blue'),
    ('Thursday',  1, 'FSE HALL', 'F10', 'C112/EEE1204/AMT114/SWE201',      'Light Blue'),
    ('Friday',    1, 'FSE HALL', 'F10', 'CS412',                           'Green'),

    # === 1210-1410 (slot 2) ===
    ('Monday',    2, 'FSE HALL', 'F06', 'CS218',                           'Purple'),
    ('Monday',    2, 'FSE HALL', 'F10', 'CS201/CSH115/NWE111/SWE114',      'Purple'),
    ('Tuesday',   2, 'PC108',    'F06', 'NWE410',                          'Yellow'),
    ('Thursday',  2, 'FSE HALL', 'F06', 'SWE416',                          'Light Blue'),
    ('Thursday',  2, 'FSE HALL', 'F10', 'SWE112',                          'Green'),
    ('Friday',    2, 'FSE HALL', 'F06', 'SWE215',                          'Green'),

    # === 1415-1615 (slot 3) ===
    ('Monday',    3, 'FSE HALL', 'F06', 'CS218',                           'Purple'),
    ('Monday',    3, 'FSE HALL', 'F10', 'CS201/CSH115/NWE111/SWE114',      'Purple'),
    ('Tuesday',   3, 'PC108',    'F06', 'NWE410',                          'Yellow'),
    ('Thursday',  3, 'FSE HALL', 'F06', 'SWE416',                          'Light Blue'),
    ('Thursday',  3, 'FSE HALL', 'F10', 'SWE205',                          'Green'),
    ('Friday',    3, 'FSE HALL', 'F06', 'SWE215',                          'Green'),
]

entry_id = 0
for day, slot_idx, venue, group, codes_str, color in entries_data:
    start_t, end_t = time_slots[slot_idx]
    start_fmt = f"{start_t[:2]}:{start_t[2:]}"
    end_fmt = f"{end_t[:2]}:{end_t[2:]}"
    room_id = room_map.get(venue, room_map['FSE HALL'])
    lecturer = get_lec(color)

    for code in codes_str.split('/'):
        code = code.strip()
        cid = course_map.get(code)
        if not cid:
            continue
        db.execute("""INSERT INTO timetable_entries
            (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
            VALUES (?,?,?,?,?,?,?,?)""",
            (cid, lecturer, room_id, day, start_fmt, end_fmt, group, 1))
        entry_id += 1

db.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", ('timetable_published', '1'))
for k, v in [('lunch_start','13:00'), ('lunch_end','13:30'), ('efficiency_score','0')]:
    db.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?,?)", (k, v))

db.commit()
db.close()

print(f"Done! {len(course_codes)} courses, {len(lecturers_data)} lecturers, {len(rooms_list)} rooms, {entry_id} timetable entries.")
