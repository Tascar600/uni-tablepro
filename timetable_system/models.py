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
        else:
            cur = self.conn.cursor()
        if params is not None:
            s = sql.replace('?', '%s') if self.pg else sql
            cur.execute(s, params)
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
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        conn.close()
        return

    conn.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Computer Science', 'CS'))
    conn.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Mathematics', 'MATH'))
    conn.execute("INSERT INTO departments (name, code) VALUES (?,?)", ('Engineering', 'ENG'))

    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('admin', 'admin123', 'admin', 'System Admin', 'admin@uni.edu', 1))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('lecturer1', 'pass123', 'lecturer', 'Dr. Alice Johnson', 'alice@uni.edu', 1))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('lecturer2', 'pass123', 'lecturer', 'Prof. Bob Smith', 'bob@uni.edu', 1))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('lecturer3', 'pass123', 'lecturer', 'Dr. Carol Lee', 'carol@uni.edu', 2))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('lecturer4', 'pass123', 'lecturer', 'Dr. David Kim', 'david@uni.edu', 2))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('student1', 'pass123', 'student', 'Student One', 'student1@uni.edu', 1))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('student2', 'pass123', 'student', 'Student Two', 'student2@uni.edu', 1))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('student3', 'pass123', 'student', 'Student Three', 'student3@uni.edu', 2))
    conn.execute("INSERT INTO users (username, password, role, full_name, email, department_id) VALUES (?,?,?,?,?,?)",
                   ('student4', 'pass123', 'student', 'Student Four', 'student4@uni.edu', 2))

    conn.execute("INSERT INTO lecturer_preferences (user_id, preferred_days) VALUES (?,?)",
                   (2, '["Monday","Wednesday","Friday"]'))
    conn.execute("INSERT INTO lecturer_preferences (user_id, preferred_days) VALUES (?,?)",
                   (3, '["Tuesday","Thursday"]'))
    conn.execute("INSERT INTO lecturer_preferences (user_id, preferred_days) VALUES (?,?)",
                   (4, '["Monday","Tuesday","Wednesday"]'))
    conn.execute("INSERT INTO lecturer_preferences (user_id, preferred_days) VALUES (?,?)",
                   (5, '["Wednesday","Thursday","Friday"]'))

    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Introduction to Computer Science', 'CS101', 'university', 2, 'Group A', 1.5, 1, '#4A90D9'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Data Structures', 'CS201', 'university', 3, 'Group B', 1.5, 1, '#50C878'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Software Engineering', 'CS301', 'department', 2, 'Group A', 1.0, 1, '#E67E22'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Database Systems', 'CS302', 'department', 4, 'Group B', 1.0, 1, '#9B59B6'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Advanced Algorithms', 'CS401', 'single', 3, 'Group A', 1.0, 1, '#E74C3C'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Machine Learning', 'CS402', 'single', 4, 'Group B', 1.0, 1, '#1ABC9C'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Calculus I', 'MATH101', 'university', 5, 'Group C', 1.5, 2, '#F39C12'))
    conn.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
                   ('Linear Algebra', 'MATH201', 'department', 5, 'Group C', 1.5, 2, '#2ECC71'))

    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (6, 1, 'Group A'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (6, 2, 'Group B'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (6, 4, 'Group B'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (7, 1, 'Group A'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (7, 2, 'Group B'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (7, 6, 'Group B'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (8, 7, 'Group C'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (8, 8, 'Group C'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (9, 7, 'Group C'))
    conn.execute("INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)", (9, 8, 'Group C'))

    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Hall A', 100, 'Main', 1, 'lecture_hall', 1, 0))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Hall B', 80, 'Main', 1, 'lecture_hall', 1, 0))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Room 101', 40, 'Science', 1, 'classroom', 1, 0))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Room 102', 35, 'Science', 1, 'classroom', 0, 0))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Lab 1', 25, 'Science', 2, 'lab', 1, 1))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Lab 2', 25, 'Science', 2, 'lab', 1, 1))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Seminar Room A', 30, 'Main', 2, 'seminar', 1, 0))
    conn.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   ('Lecture Theatre 1', 200, 'Main', 0, 'lecture_hall', 1, 0))

    conn.commit()
    conn.close()
