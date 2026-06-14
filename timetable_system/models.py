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

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            pass

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
    conn = sqlite3.connect(DB_PATH, timeout=60)
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
    existing = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    if existing > 0:
        db.close()
        return

    for name in ['Biological Sciences', 'Engineering and Physics', 'Statistics and Mathematics',
                 'Chemistry', 'Computer Science', 'Sports Sciences', 'Geosciences',
                 'Geography', 'Health Sciences', 'Disaster Risk Reduction', 'Optometry']:
        code = name.upper().replace(' ', '')
        db.execute("INSERT OR IGNORE INTO departments (name, code) VALUES (?,?)", (f'Department of {name}', code))
    dept_cs = db.execute("SELECT id FROM departments WHERE code='COMPUTERSCIENCE'").fetchone()[0]

    rooms_data = [
        ('F10', 150, 2, 'lab', 1, 1),
        ('F06', 50, 2, 'classroom', 1, 0),
        ('FSE HALL', 500, 1, 'lecture_hall', 0, 0),
    ]
    for name, cap, floor, rtype, proj, comp in rooms_data:
        db.execute("INSERT OR IGNORE INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers, is_active) VALUES (?,?,?,?,?,?,?,1)",
                   (name, cap, 'Main', floor, rtype, proj, comp))
    room_map = {r['name']: r['id'] for r in db.execute("SELECT id, name FROM rooms").fetchall()}

    db.execute("INSERT OR IGNORE INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
               ('admin', 'admin2026', 'admin', 'System Admin', 'admin@uni.edu', dept_cs))

    lecturers = [
        ('mhlanganiso','Mr Mhlanganiso','mhlanganiso','hmhlanganiso@buse.ac.zw'),
        ('mhlanga','Mr Mhlanga','mhlana','mhlanga@buse.ac.zw'),
        ('zano','Mr Zano','zano','zano@buse.ac.zw'),
        ('sakala','Dr Sakala','salaka','sakala@buse.ac.zw'),
        ('chituma','Mr Chituma','chituma','chituma@buse.ac.zw'),
        ('ndumiyana','Mr Ndumiyana','ndumiyana','ndumiyana@buse.ac.zw'),
        ('chikwiriro','Mr Chikwiriro','chikwiriro','chikwiriro@buse.ac.zw'),
        ('chaitezvi','Mr Chaitezvi','chaitezvi','chaitezvi@buse.ac.zw'),
        ('katsinde','Dr Katsinde','katsinde','katsinde@buse.ac.zw'),
    ]
    for uname, fname, pw, email in lecturers:
        db.execute("INSERT OR IGNORE INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   (uname, pw, 'lecturer', fname, email, None))
    lec_map = {l['username']: l['id'] for l in db.execute("SELECT id, username FROM users WHERE role='lecturer'").fetchall()}

    courses_data = [
        ('VB.NET','SWE112','single',lec_map['mhlanganiso'],'1.1',2.0,'#248b23'),
        ('SWE205','SWE205','single',lec_map['mhlanganiso'],'2.1',2.0,'#38bf36'),
        ('OOP1','CS112','department',lec_map['mhlanganiso'],'1.2',4.0,'#43b135'),
        ('NWE411','NWE411','single',lec_map['mhlanga'],'4.1',4.0,'#b3a8a8'),
        ('SWE416','SWE416','single',lec_map['mhlanga'],'4.1',4.0,'#929eaa'),
        ('GROUP PROJECT','CS218','single',lec_map['zano'],'2.2',4.0,'#640b6a'),
        ('INTERNET AND WEB DESIGN','CS214','department',lec_map['zano'],'2.2',4.0,'#7a0d82'),
        ('MINI PROJECT','SWE214','single',lec_map['sakala'],'2.2',4.0,'#63370d'),
        ('SOFTWARE ENGINEERING','CS216','department',lec_map['chituma'],'1.2',4.0,'#c8ff00'),
        ('DATABASE CONCERPT','CS201','department',lec_map['chituma'],'1.2',4.0,'#c8ff00'),
        ('NWE410','NWE410','single',lec_map['chituma'],'4.2',4.0,'#e1ff00'),
        ('NWE216','NWE216','university',lec_map['ndumiyana'],'2.2',4.0,'#d98a4a'),
        ('OOP2','SWE211','department',lec_map['chikwiriro'],'2.2',4.0,'#ff0000'),
        ('CS412','CS412','single',lec_map['chaitezvi'],'4.2',4.0,'#00ffb3'),
        ('CITIZENSHIP','PC108','university',lec_map['katsinde'],'1.1',4.0,'#4a90d9'),
    ]
    for name, code, level, lid, grp, dur, color in courses_data:
        db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, color, department_id) VALUES (?,?,?,?,?,?,?,?)",
                   (name, code, level, lid, grp, dur, color, dept_cs))

    if db.pg:
        db.execute("INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
                   ('timetable_published', '0', '0'))
    else:
        db.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", ('timetable_published', '0'))

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
