import sqlite3, os
os.chdir(os.path.dirname(__file__))
conn = sqlite3.connect('timetable.db')
for table in ['users', 'courses', 'rooms']:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"{table}: {count} rows")
    if table == 'users':
        cur = conn.execute("SELECT username, role FROM users")
        for r in cur.fetchall():
            print(f"  - {r[0]} ({r[1]})")
    elif table == 'courses':
        cur = conn.execute("SELECT code, name FROM courses")
        for r in cur.fetchall():
            print(f"  - {r[0]}: {r[1]}")
    elif table == 'rooms':
        cur = conn.execute("SELECT name FROM rooms")
        for r in cur.fetchall():
            print(f"  - {r[0]}")
conn.close()
