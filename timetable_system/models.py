import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), 'timetable.db')
_DATABASE_URL = os.environ.get('DATABASE_URL')


class _DB:
    def __init__(self, conn, pg=False):
        self.conn = conn
        self.pg = pg

    def execute(self, sql, params=None):
        if self.pg:
            import psycopg2.extras
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            try:
                if params is not None:
                    s = sql.replace('?', '%s')
                    cur.execute(s, params)
                else:
                    cur.execute(sql)
                return cur
            except:
                cur.close()
                raise
        else:
            cur = self.conn.cursor()
            if params is not None:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return cur

    def executescript(self, sql):
        if self.pg:
            cur = self.conn.cursor()
            for stmt in sql.split(';'):
                s = stmt.strip()
                if s:
                    cur.execute(s)
            cur.close()
        else:
            self.conn.executescript(sql)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def cursor(self):
        return self.conn.cursor()


def get_db():
    if _DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(_DATABASE_URL)
        conn.autocommit = True
        return _DB(conn, pg=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return _DB(conn)


def _pg_create(conn):
    cur = conn.conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('lecturer','admin','student')),
            full_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            department_id INTEGER REFERENCES departments(id),
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecturer_preferences (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            preferred_days TEXT DEFAULT '[]',
            preferred_time_start TEXT DEFAULT '08:00',
            preferred_time_end TEXT DEFAULT '17:00',
            max_hours_per_week REAL DEFAULT 20,
            avoid_back_to_back INTEGER DEFAULT 1,
            lunch_break_optimize INTEGER DEFAULT 1,
            max_consecutive_hours REAL DEFAULT 3.0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('university','department','single')),
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            group_name TEXT NOT NULL,
            duration_hours REAL DEFAULT 1.0,
            department_id INTEGER REFERENCES departments(id),
            color TEXT DEFAULT '#4A90D9',
            max_students INTEGER DEFAULT 0,
            semester TEXT DEFAULT 'Semester 1',
            academic_year TEXT DEFAULT '2025-2026'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_enrollments (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            group_name TEXT NOT NULL,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, course_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            capacity INTEGER DEFAULT 30,
            building TEXT DEFAULT 'Main',
            floor INTEGER DEFAULT 1,
            room_type TEXT DEFAULT 'classroom' CHECK(room_type IN ('classroom','lab','lecture_hall','seminar')),
            has_projector INTEGER DEFAULT 0,
            has_computers INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timetable_entries (
            id SERIAL PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            room_id INTEGER NOT NULL REFERENCES rooms(id),
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            group_name TEXT NOT NULL,
            published INTEGER DEFAULT 0,
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled','rescheduled','cancelled')),
            semester TEXT DEFAULT 'Semester 1',
            academic_year TEXT DEFAULT '2025-2026',
            notes TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records (
            id SERIAL PRIMARY KEY,
            timetable_entry_id INTEGER NOT NULL REFERENCES timetable_entries(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('present','absent','late','excused')),
            marked_by INTEGER REFERENCES users(id),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timetable_entry_id, student_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timetable_versions (
            id SERIAL PRIMARY KEY,
            version_number INTEGER NOT NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            snapshot_data TEXT NOT NULL,
            notes TEXT,
            is_active INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            details TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info' CHECK(type IN ('info','success','warning','error')),
            read INTEGER DEFAULT 0,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timetable_shares (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            created_by INTEGER REFERENCES users(id),
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS substitute_allocations (
            id SERIAL PRIMARY KEY,
            timetable_entry_id INTEGER NOT NULL REFERENCES timetable_entries(id),
            original_lecturer_id INTEGER NOT NULL REFERENCES users(id),
            substitute_lecturer_id INTEGER NOT NULL REFERENCES users(id),
            reason TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','declined')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conflict_resolutions (
            id SERIAL PRIMARY KEY,
            timetable_entry_id INTEGER REFERENCES timetable_entries(id),
            conflict_type TEXT NOT NULL,
            description TEXT,
            suggestion TEXT,
            applied INTEGER DEFAULT 0,
            resolved_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS draft_timetables (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT DEFAULT 'Draft',
            data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lecturer_availability (
            id SERIAL PRIMARY KEY,
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_available INTEGER DEFAULT 1,
            date_from TEXT,
            date_to TEXT,
            UNIQUE(lecturer_id, day, start_time, end_time)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    for k, v in [('timetable_published', '0'), ('lunch_start', '13:00'), ('lunch_end', '13:30'), ('efficiency_score', '0')]:
        cur.execute("INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (k, v))
    cur.close()
    conn.commit()


def init_db():
    conn = get_db()
    if conn.pg:
        _pg_create(conn)
        conn.close()
        return
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('lecturer','admin','student')),
            full_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            department_id INTEGER REFERENCES departments(id),
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lecturer_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            preferred_days TEXT DEFAULT '[]',
            preferred_time_start TEXT DEFAULT '08:00',
            preferred_time_end TEXT DEFAULT '17:00',
            max_hours_per_week REAL DEFAULT 20,
            avoid_back_to_back INTEGER DEFAULT 1,
            lunch_break_optimize INTEGER DEFAULT 1,
            max_consecutive_hours REAL DEFAULT 3.0
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('university','department','single')),
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            group_name TEXT NOT NULL,
            duration_hours REAL DEFAULT 1.0,
            department_id INTEGER REFERENCES departments(id),
            color TEXT DEFAULT '#4A90D9',
            max_students INTEGER DEFAULT 0,
            semester TEXT DEFAULT 'Semester 1',
            academic_year TEXT DEFAULT '2025-2026'
        );

        CREATE TABLE IF NOT EXISTS student_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            group_name TEXT NOT NULL,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, course_id)
        );

        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            capacity INTEGER DEFAULT 30,
            building TEXT DEFAULT 'Main',
            floor INTEGER DEFAULT 1,
            room_type TEXT DEFAULT 'classroom' CHECK(room_type IN ('classroom','lab','lecture_hall','seminar')),
            has_projector INTEGER DEFAULT 0,
            has_computers INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS timetable_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            room_id INTEGER NOT NULL REFERENCES rooms(id),
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            group_name TEXT NOT NULL,
            published INTEGER DEFAULT 0,
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled','rescheduled','cancelled')),
            semester TEXT DEFAULT 'Semester 1',
            academic_year TEXT DEFAULT '2025-2026',
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timetable_entry_id INTEGER NOT NULL REFERENCES timetable_entries(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('present','absent','late','excused')),
            marked_by INTEGER REFERENCES users(id),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timetable_entry_id, student_id)
        );

        CREATE TABLE IF NOT EXISTS timetable_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number INTEGER NOT NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            snapshot_data TEXT NOT NULL,
            notes TEXT,
            is_active INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            details TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info' CHECK(type IN ('info','success','warning','error')),
            read INTEGER DEFAULT 0,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS timetable_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            created_by INTEGER REFERENCES users(id),
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS substitute_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timetable_entry_id INTEGER NOT NULL REFERENCES timetable_entries(id),
            original_lecturer_id INTEGER NOT NULL REFERENCES users(id),
            substitute_lecturer_id INTEGER NOT NULL REFERENCES users(id),
            reason TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','declined')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conflict_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timetable_entry_id INTEGER REFERENCES timetable_entries(id),
            conflict_type TEXT NOT NULL,
            description TEXT,
            suggestion TEXT,
            applied INTEGER DEFAULT 0,
            resolved_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS draft_timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT DEFAULT 'Draft',
            data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lecturer_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lecturer_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_available INTEGER DEFAULT 1,
            date_from TEXT,
            date_to TEXT,
            UNIQUE(lecturer_id, day, start_time, end_time)
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        INSERT OR IGNORE INTO app_settings (key, value) VALUES ('timetable_published', '0');
        INSERT OR IGNORE INTO app_settings (key, value) VALUES ('lunch_start', '13:00');
        INSERT OR IGNORE INTO app_settings (key, value) VALUES ('lunch_end', '13:30');
        INSERT OR IGNORE INTO app_settings (key, value) VALUES ('efficiency_score', '0');
    ''')
    conn.commit()
    conn.close()


def seed_data():
    db = get_db()
    # Only seed if no courses exist (fresh database)
    existing = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    if existing > 0:
        db.close()
        return

    # Departments
    db.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Computer Science', 'CS'))
    dept_id = db.execute("SELECT id FROM departments WHERE code='CS'").fetchone()[0]

    # Rooms
    for name, cap, rtype in [('FSE HALL', 200, 'lecture_hall'), ('PC108', 60, 'lab')]:
        db.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, is_active) VALUES (?,?,?,?,?,1,1)",
                   (name, cap, 'Main', 1, rtype))

    room_map = {r['name']: r['id'] for r in db.execute("SELECT id, name FROM rooms").fetchall()}

    # Admin
    db.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
               ('admin', 'admin2026', 'admin', 'System Admin', 'admin@uni.edu', dept_id))

    # Lecturers
    lec_names = [('mhlangamiso','Mhlanga Miso'),('chaitezvi','Chaitezvi'),('mhlanga','Mhlanga'),
                 ('chituna','Chituna'),('zano','Zano'),('sakala','Sakala'),
                 ('ndumiyana','Ndumiyana'),('chikwiriro','Chikwiriro')]
    for uname, fname in lec_names:
        db.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   (uname, 'password', 'lecturer', fname, f'{uname}@uni.edu', dept_id))
    lec_map = {l['username']: l['id'] for l in db.execute("SELECT id, username FROM users WHERE role='lecturer'").fetchall()}

    color_lec = {'Yellow':['mhlangamiso','chituna'],'Green':['mhlangamiso','chaitezvi'],'Orange':['zano'],
                 'Purple':['sakala'],'Light Blue':['ndumiyana'],'Pink/Red':['chikwiriro'],
                 'Red':['sakala'],'Brown':['mhlanga']}
    def get_lec(c): return lec_map[color_lec.get(c,['sakala'])[0]]

    # Courses
    courses_list = [
        'CS216','CSH116','SWE115','CS214','NWE214','SWE212','SWE214','NWE216',
        'SWE211','EEE2203','NWE411','C112','EEE1204','AMT114','SWE201','CS412',
        'CS218','CS201','CSH115','NWE111','SWE114','NWE410','SWE416','SWE112','SWE205','SWE215'
    ]
    for code in courses_list:
        db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, color, department_id) VALUES (?,?,?,?,?,?,?,?)",
                   (code, code, 'department', lec_map['sakala'], 'A', 2.0, '#4A90D9', dept_id))
    c_map = {c['code']: c['id'] for c in db.execute("SELECT id, code FROM courses").fetchall()}

    # Timetable entries
    time_slots = [('0750','0950'),('1000','1200'),('1210','1410'),('1415','1615'),('1620','1820')]
    entries = [
        (0,'Monday','FSE HALL','F06','CS216/CSH116/SWE115','Yellow'),
        (0,'Monday','FSE HALL','F10','CS214/NWE214/SWE212','Purple'),
        (0,'Tuesday','PC108','F06','SWE214','Brown'),
        (0,'Tuesday','PC108','F10','NWE216','Pink/Red'),
        (0,'Wednesday','FSE HALL','F10','SWE211/EEE2203','Red'),
        (0,'Thursday','FSE HALL','F06','NWE411','Light Blue'),
        (0,'Thursday','FSE HALL','F10','C112/EEE1204/AMT114/SWE201','Light Blue'),
        (0,'Friday','FSE HALL','F10','CS412','Green'),
        (1,'Monday','FSE HALL','F06','CS216/CSH116/SWE115','Yellow'),
        (1,'Monday','FSE HALL','F10','CS214/NWE214/SWE212','Purple'),
        (1,'Tuesday','PC108','F06','SWE214','Brown'),
        (1,'Tuesday','PC108','F10','NWE216','Pink/Red'),
        (1,'Wednesday','FSE HALL','F10','SWE211/EEE2203','Red'),
        (1,'Thursday','FSE HALL','F06','NWE411','Light Blue'),
        (1,'Thursday','FSE HALL','F10','C112/EEE1204/AMT114/SWE201','Light Blue'),
        (1,'Friday','FSE HALL','F10','CS412','Green'),
        (2,'Monday','FSE HALL','F06','CS218','Purple'),
        (2,'Monday','FSE HALL','F10','CS201/CSH115/NWE111/SWE114','Purple'),
        (2,'Tuesday','PC108','F06','NWE410','Yellow'),
        (2,'Thursday','FSE HALL','F06','SWE416','Light Blue'),
        (2,'Thursday','FSE HALL','F10','SWE112','Green'),
        (2,'Friday','FSE HALL','F06','SWE215','Green'),
        (3,'Monday','FSE HALL','F06','CS218','Purple'),
        (3,'Monday','FSE HALL','F10','CS201/CSH115/NWE111/SWE114','Purple'),
        (3,'Tuesday','PC108','F06','NWE410','Yellow'),
        (3,'Thursday','FSE HALL','F06','SWE416','Light Blue'),
        (3,'Thursday','FSE HALL','F10','SWE205','Green'),
        (3,'Friday','FSE HALL','F06','SWE215','Green'),
    ]
    for si, day, venue, group, codes_str, color in entries:
        st, et = time_slots[si]
        lec = get_lec(color)
        for code in codes_str.split('/'):
            cid = c_map.get(code.strip())
            if cid:
                db.execute("INSERT INTO timetable_entries (course_id,lecturer_id,room_id,day,start_time,end_time,group_name,published) VALUES (?,?,?,?,?,?,?,?)",
                           (cid, lec, room_map[venue], day, f'{st[:2]}:{st[2:]}', f'{et[:2]}:{et[2:]}', group, 1))

    # App settings
    if db.pg:
        db.execute("INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
                   ('timetable_published', '1', '1'))
    else:
        db.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", ('timetable_published', '1'))

    db.commit()
    db.close()

def seed_force():
    """Force reseed - clears all data and re-inserts."""
    db = get_db()
    for t in ['attendance_records','substitute_allocations','conflict_resolutions','timetable_versions',
              'student_enrollments','timetable_entries','courses','lecturer_preferences',
              'lecturer_availability','activity_logs','notifications','timetable_shares','users','rooms','departments']:
        try: db.execute(f"DELETE FROM {t}")
        except Exception: pass
    try: db.execute("DELETE FROM app_settings")
    except Exception: pass
    db.commit()
    db.close()
    seed_data()
