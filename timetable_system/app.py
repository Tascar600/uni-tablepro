import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, session,
                   url_for, jsonify, flash, send_file, Response, abort)

from models import init_db, seed_data, seed_force, get_db
from scheduler import (generate_timetable, get_timetable, is_published,
                       publish_timetable, unpublish_timetable, calculate_efficiency)
from analytics import get_analytics_data, get_lecturer_workload, get_room_heatmap
from export_utils import export_ics, export_csv, save_draft, get_draft
from ai_service import detect_conflicts, suggest_resolution, chatbot_response
from notifications import (create_notification, get_unread_count, get_notifications,
                           mark_notification_read, mark_all_read, log_activity,
                           get_activity_logs, notify_timetable_change)

from document_parser import DocumentParser

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'timetable-secret-key-2026')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                if request.is_json:
                    return jsonify({'error': 'Forbidden'}), 403
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def add_notification_count(context):
    if 'user_id' in session:
        context['unread_count'] = get_unread_count(session['user_id'])
    return context


@app.context_processor
def inject_globals():
    ctx = {'now': datetime.now()}
    return add_notification_count(ctx)


@app.before_request
def ensure_db():
    if not hasattr(app, '_db_initialized'):
        init_db()
        seed_data()
        app._db_initialized = True
    if 'user_id' in session:
        db = get_db()
        exists = db.execute("SELECT id FROM users WHERE id=?", (session['user_id'],)).fetchone()
        db.close()
        if not exists:
            session.clear()


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role', 'student')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if role == 'admin':
            if password == 'admin2026':
                db = get_db()
                user = db.execute("SELECT * FROM users WHERE role='admin' AND is_active=1").fetchone()
                db.close()
                if not user:
                    return render_template('login.html', error='Admin account not found')
                session['user_id'] = user['id']
                session['role'] = user['role']
                session['full_name'] = user['full_name']
                log_activity(user['id'], 'login', 'Admin logged in')
                return redirect(url_for('dashboard'))
            return render_template('login.html', error='Invalid admin password')

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=? AND password=? AND role=? AND is_active=1",
                          (username, password, role)).fetchone()
        db.close()
        if user:
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            log_activity(user['id'], 'login', 'User logged in')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error=f'Invalid {role} credentials')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    role = request.args.get('role', 'student')
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        full_name = request.form['full_name'].strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'student')
        if not username or not password or not full_name:
            return render_template('register.html', error='All fields are required', role=role, role_label=role.title())
        db = get_db()
        try:
            db.execute("INSERT INTO users (username, password, role, full_name, email) VALUES (?,?,?,?,?)",
                       (username, password, role, full_name, email))
            db.commit()
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            log_activity(user['id'], 'register', 'User registered')
            db.close()
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            db.close()
            return render_template('register.html', error='Username already taken', role=role, role_label=role.title())
    return render_template('register.html', role=role, role_label=role.title())


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    role = session['role']
    db = get_db()
    data = {'role': role}

    if role == 'admin':
        lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()
        courses = db.execute("SELECT COUNT(*) as c FROM courses").fetchone()
        rooms = db.execute("SELECT COUNT(*) as c FROM rooms").fetchone()
        entries = db.execute("SELECT COUNT(*) as c FROM timetable_entries").fetchone()
        timetable = get_timetable()
        data['lecturer_count'] = len(lecturers)
        data['course_count'] = courses['c']
        data['room_count'] = rooms['c']
        data['entry_count'] = entries['c']
        data['timetable'] = timetable
        data['published'] = is_published()
        data['recent_logs'] = get_activity_logs(10)
        db.close()
        return render_template('admin_dashboard.html', **data)

    elif role == 'lecturer':
        courses = db.execute("""
            SELECT c.*, d.name as department_name
            FROM courses c
            LEFT JOIN departments d ON c.department_id = d.id
            WHERE c.lecturer_id=?
        """, (session['user_id'],)).fetchall()
        entries = db.execute("""
            SELECT te.*, c.name as course_name, c.code, r.name as room_name
            FROM timetable_entries te
            JOIN courses c ON te.course_id = c.id
            JOIN rooms r ON te.room_id = r.id
            WHERE te.lecturer_id=? AND te.published=1
            ORDER BY te.day, te.start_time
        """, (session['user_id'],)).fetchall()
        data['courses'] = [dict(c) for c in courses]
        data['timetable'] = [dict(e) for e in entries]
        data['published'] = is_published()
        workload = get_lecturer_workload(session['user_id'])
        data['workload'] = workload
        depts = db.execute("SELECT * FROM departments").fetchall()
        data['departments'] = [dict(d) for d in depts]
        db.close()
        return render_template('lecturer_dashboard.html', **data)

    elif role == 'student':
        entries = db.execute("""
            SELECT DISTINCT te.*, c.name as course_name, c.code, c.color,
                   u.full_name as lecturer_name, r.name as room_name
            FROM timetable_entries te
            JOIN courses c ON te.course_id = c.id
            JOIN users u ON te.lecturer_id = u.id
            JOIN rooms r ON te.room_id = r.id
            JOIN student_enrollments se ON se.course_id = c.id AND se.student_id = ?
            WHERE te.published = 1
            ORDER BY te.day, te.start_time
        """, (session['user_id'],)).fetchall()
        data['timetable'] = [dict(e) for e in entries]
        data['published'] = is_published()
        enrolled = db.execute("""
            SELECT c.id, c.name, c.code, se.group_name
            FROM student_enrollments se
            JOIN courses c ON se.course_id = c.id
            WHERE se.student_id = ?
        """, (session['user_id'],)).fetchall()
        data['enrolled_courses'] = [dict(e) for e in enrolled]
        db.close()
        return render_template('student_dashboard.html', **data)

    return redirect(url_for('login'))

# ─── Admin Routes ──────────────────────────────────────────────────

@app.route('/admin')
@login_required
@role_required('admin')
def admin_redirect():
    return redirect(url_for('dashboard'))


@app.route('/admin/lecturers')
@login_required
@role_required('admin')
def admin_lecturers():
    db = get_db()
    lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()
    depts = db.execute("SELECT * FROM departments").fetchall()
    all_data = []
    for lec in lecturers:
        courses = db.execute("SELECT * FROM courses WHERE lecturer_id=?", (lec['id'],)).fetchall()
        pref = db.execute("SELECT * FROM lecturer_preferences WHERE user_id=?", (lec['id'],)).fetchone()
        all_data.append({
            'lecturer': dict(lec),
            'courses': [dict(c) for c in courses],
            'preferences': dict(pref) if pref else None,
        })
    db.close()
    return render_template('admin_lecturers.html', lecturers=all_data, departments=[dict(d) for d in depts])


@app.route('/admin/add-lecturer', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_lecturer():
    username = request.form['username'].strip()
    password = request.form['password']
    full_name = request.form['full_name'].strip()
    email = request.form.get('email', '').strip()
    db = get_db()
    try:
        db.execute("INSERT INTO users (username, password, role, full_name, email) VALUES (?,?,?,?,?)",
                   (username, password, 'lecturer', full_name, email))
        db.commit()
        log_activity(session['user_id'], 'add_lecturer', f'Added lecturer: {full_name}')
        flash('Lecturer added successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_lecturers'))


@app.route('/admin/delete-lecturer/<int:lecturer_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_lecturer(lecturer_id):
    db = get_db()
    lecturer = db.execute("SELECT * FROM users WHERE id=? AND role='lecturer'", (lecturer_id,)).fetchone()
    if lecturer:
        for table, col in [('student_enrollments', 'student_id'),
                           ('attendance_records', 'student_id'),
                           ('timetable_entries', 'lecturer_id'),
                           ('courses', 'lecturer_id'),
                           ('substitute_allocations', 'original_lecturer_id'),
                           ('substitute_allocations', 'substitute_lecturer_id'),
                           ('lecturer_preferences', 'user_id'),
                           ('lecturer_availability', 'lecturer_id'),
                           ('activity_logs', 'user_id'),
                           ('notifications', 'user_id'),
                           ('timetable_versions', 'created_by'),
                           ('draft_timetables', 'user_id'),
                           ('conflict_resolutions', 'resolved_by')]:
            try:
                db.execute(f"DELETE FROM {table} WHERE {col}=?", (lecturer_id,))
            except Exception:
                pass
        db.execute("DELETE FROM users WHERE id=?", (lecturer_id,))
        db.commit()
        log_activity(session['user_id'], 'delete_lecturer', f'Deleted lecturer: {lecturer["full_name"]}')
        flash('Lecturer deleted.', 'success')
    db.close()
    return redirect(url_for('admin_lecturers'))


@app.route('/admin/edit-lecturer/<int:lecturer_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_lecturer(lecturer_id):
    full_name = request.form['full_name'].strip()
    email = request.form.get('email', '').strip()
    db = get_db()
    try:
        db.execute("UPDATE users SET full_name=?, email=? WHERE id=? AND role='lecturer'",
                   (full_name, email, lecturer_id))
        db.commit()
        log_activity(session['user_id'], 'edit_lecturer', f'Edited lecturer: {full_name}')
        flash('Lecturer updated successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_lecturers'))


@app.route('/admin/rooms')
@login_required
@role_required('admin')
def admin_rooms():
    db = get_db()
    rooms = db.execute("SELECT * FROM rooms ORDER BY building, floor").fetchall()
    db.close()
    return render_template('admin_rooms.html', rooms=[dict(r) for r in rooms])


@app.route('/admin/rooms/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_room():
    name = request.form['name']
    capacity = int(request.form.get('capacity', 30))
    building = request.form.get('building', 'Main')
    floor = int(request.form.get('floor', 1))
    room_type = request.form.get('room_type', 'classroom')
    has_projector = 1 if request.form.get('has_projector') else 0
    has_computers = 1 if request.form.get('has_computers') else 0
    db = get_db()
    try:
        db.execute("INSERT INTO rooms (name, capacity, building, floor, room_type, has_projector, has_computers) VALUES (?,?,?,?,?,?,?)",
                   (name, capacity, building, floor, room_type, has_projector, has_computers))
        db.commit()
        log_activity(session['user_id'], 'add_room', f'Added room: {name}', 'room')
        flash('Room added successfully!', 'success')
    except Exception as e:
        flash(f'Error adding room: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_rooms'))


@app.route('/admin/rooms/delete/<int:room_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_room(room_id):
    db = get_db()
    db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
    db.commit()
    log_activity(session['user_id'], 'delete_room', f'Deleted room #{room_id}', 'room', room_id)
    flash('Room deleted.', 'success')
    db.close()
    return redirect(url_for('admin_rooms'))


@app.route('/admin/edit-room/<int:room_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_room(room_id):
    name = request.form['name']
    capacity = int(request.form.get('capacity', 30))
    building = request.form.get('building', 'Main')
    floor = int(request.form.get('floor', 1))
    room_type = request.form.get('room_type', 'classroom')
    has_projector = 1 if request.form.get('has_projector') else 0
    has_computers = 1 if request.form.get('has_computers') else 0
    db = get_db()
    try:
        db.execute("UPDATE rooms SET name=?, capacity=?, building=?, floor=?, room_type=?, has_projector=?, has_computers=? WHERE id=?",
                   (name, capacity, building, floor, room_type, has_projector, has_computers, room_id))
        db.commit()
        log_activity(session['user_id'], 'edit_room', f'Edited room: {name}')
        flash('Room updated successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_rooms'))


@app.route('/admin/courses')
@login_required
@role_required('admin')
def admin_courses():
    db = get_db()
    courses = db.execute("""
        SELECT c.*, u.full_name as lecturer_name, d.name as department_name
        FROM courses c
        JOIN users u ON c.lecturer_id = u.id
        LEFT JOIN departments d ON c.department_id = d.id
        ORDER BY c.name
    """).fetchall()
    lecturers = db.execute("SELECT * FROM users WHERE role='lecturer'").fetchall()
    depts = db.execute("SELECT * FROM departments").fetchall()
    db.close()
    return render_template('admin_courses.html',
                          courses=[dict(c) for c in courses],
                          lecturers=[dict(l) for l in lecturers],
                          departments=[dict(d) for d in depts])


@app.route('/admin/add-course', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_course():
    name = request.form['name']
    code = request.form['code']
    level = request.form['level']
    lecturer_id = request.form['lecturer_id']
    group_name = request.form['group_name']
    duration = float(request.form.get('duration', 1.0))
    department_id = request.form.get('department_id') or None
    color = request.form.get('color', '#4A90D9')
    max_students = int(request.form.get('max_students', 0))
    db = get_db()
    try:
        db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color, max_students) VALUES (?,?,?,?,?,?,?,?,?)",
                   (name, code, level, lecturer_id, group_name, duration, department_id, color, max_students))
        db.commit()
        log_activity(session['user_id'], 'add_course', f'Added course: {name} ({code})', 'course')
        flash('Course added successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_courses'))


@app.route('/admin/delete-course/<int:course_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_course(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    db.execute("DELETE FROM student_enrollments WHERE course_id=?", (course_id,))
    db.execute("DELETE FROM timetable_entries WHERE course_id=?", (course_id,))
    db.execute("DELETE FROM courses WHERE id=?", (course_id,))
    db.commit()
    if course:
        log_activity(session['user_id'], 'delete_course', f'Deleted course: {course["name"]}', 'course', course_id)
    db.close()
    flash('Course deleted.', 'success')
    return redirect(url_for('admin_courses'))


@app.route('/admin/delete-courses-bulk', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_courses_bulk():
    course_ids = request.form.getlist('course_ids')
    if not course_ids:
        flash('No courses selected.', 'warning')
        return redirect(url_for('admin_courses'))
    
    db = get_db()
    deleted = 0
    for cid in course_ids:
        course = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
        if course:
            db.execute("DELETE FROM student_enrollments WHERE course_id=?", (cid,))
            db.execute("DELETE FROM timetable_entries WHERE course_id=?", (cid,))
            db.execute("DELETE FROM courses WHERE id=?", (cid,))
            deleted += 1
            log_activity(session['user_id'], 'delete_course', f'Deleted course: {course["name"]}', 'course', cid)
    db.commit()
    db.close()
    flash(f'{deleted} course(s) deleted.', 'success')
    return redirect(url_for('admin_courses'))


@app.route('/admin/delete-all-timetable', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_all_timetable():
    db = get_db()
    # Delete all courses and related data, but keep lecturers
    courses = db.execute("SELECT * FROM courses").fetchall()
    for course in courses:
        db.execute("DELETE FROM student_enrollments WHERE course_id=?", (course['id'],))
        db.execute("DELETE FROM timetable_entries WHERE course_id=?", (course['id'],))
        log_activity(session['user_id'], 'delete_course', f'Deleted course: {course["name"]}', 'course', course['id'])
    db.execute("DELETE FROM courses")
    db.execute("DELETE FROM timetable_entries")
    db.commit()
    db.close()
    flash('All courses and timetable entries deleted. Lecturers preserved.', 'success')
    return redirect(url_for('admin_courses'))


@app.route('/admin/edit-course/<int:course_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_course(course_id):
    name = request.form['name']
    code = request.form['code']
    level = request.form['level']
    lecturer_id = request.form['lecturer_id']
    group_name = request.form['group_name']
    duration = float(request.form.get('duration', 1.0))
    department_id = request.form.get('department_id') or None
    color = request.form.get('color', '#4A90D9')
    max_students = int(request.form.get('max_students', 0))
    db = get_db()
    try:
        db.execute("UPDATE courses SET name=?, code=?, level=?, lecturer_id=?, group_name=?, duration_hours=?, department_id=?, color=?, max_students=? WHERE id=?",
                   (name, code, level, lecturer_id, group_name, duration, department_id, color, max_students, course_id))
        db.commit()
        log_activity(session['user_id'], 'edit_course', f'Edited course: {name} ({code})')
        flash('Course updated successfully!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    db.close()
    return redirect(url_for('admin_courses'))


@app.route('/admin/generate', methods=['POST'])
@login_required
@role_required('admin')
def admin_generate():
    from scheduler import START_TIMES
    try:
        entries, unassigned = generate_timetable()
        log_activity(session['user_id'], 'generate_timetable', f'Generated timetable with {len(entries)} entries')
        msg = f'Generated timetable with {len(entries)} entries'
        if unassigned:
            names = ', '.join(f'{c["course_name"]} ({c["reason"]})' for c in unassigned)
            msg += f'. Courses NOT placed: {names}'
        return jsonify({'status': 'ok', 'count': len(entries), 'unassigned': unassigned, 'start_times': len(START_TIMES)})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/admin/publish', methods=['POST'])
@login_required
@role_required('admin')
def admin_publish():
    publish_timetable()
    log_activity(session['user_id'], 'publish_timetable', 'Published timetable')
    flash('Timetable published!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/unpublish', methods=['POST'])
@login_required
@role_required('admin')
def admin_unpublish():
    unpublish_timetable()
    log_activity(session['user_id'], 'unpublish_timetable', 'Unpublished timetable')
    flash('Timetable unpublished.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/delete-timetable', methods=['POST'])
@login_required
@role_required('admin')
def delete_timetable():
    db = get_db()
    db.execute("DELETE FROM timetable_entries")
    db.execute("UPDATE app_settings SET value='0' WHERE key='timetable_published'")
    db.commit()
    db.close()
    log_activity(session['user_id'], 'delete_timetable', 'Cleared entire timetable')
    flash('Timetable cleared.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/activity-logs')
@login_required
@role_required('admin')
def admin_activity_logs():
    logs = get_activity_logs(500)
    return render_template('admin_logs.html', logs=logs)


@app.route('/admin/analytics')
@login_required
@role_required('admin')
def admin_analytics():
    data = get_analytics_data()
    return render_template('analytics.html', data=data)


@app.route('/admin/conflicts')
@login_required
@role_required('admin')
def admin_conflicts():
    conflicts = detect_conflicts()
    return render_template('conflict_resolution.html', conflicts=conflicts)


@app.route('/admin/versions')
@login_required
@role_required('admin')
def admin_versions():
    db = get_db()
    versions = db.execute("""
        SELECT tv.*, u.full_name as created_by_name
        FROM timetable_versions tv
        LEFT JOIN users u ON tv.created_by = u.id
        ORDER BY tv.version_number DESC
    """).fetchall()
    db.close()
    return render_template('version_history.html', versions=[dict(v) for v in versions])


@app.route('/admin/version/rollback/<int:version_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_rollback(version_id):
    db = get_db()
    version = db.execute("SELECT * FROM timetable_versions WHERE id=?", (version_id,)).fetchone()
    if not version:
        db.close()
        flash('Version not found.', 'error')
        return redirect(url_for('admin_versions'))

    snapshot = json.loads(version['snapshot_data'])
    db.execute("DELETE FROM timetable_entries")

    for e in snapshot:
        db.execute("""
            INSERT INTO timetable_entries (course_id, lecturer_id, room_id, day, start_time, end_time, group_name, published)
            VALUES (?,?,?,?,?,?,?,?)
        """, (e['course_id'], e['lecturer_id'], e['room_id'], e['day'],
              e['start_time'], e['end_time'], e['group_name'], 0))

    next_ver = db.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM timetable_versions").fetchone()[0]
    db.execute("UPDATE timetable_versions SET is_active=0")
    db.execute("INSERT INTO timetable_versions (version_number, created_by, snapshot_data, notes, is_active) VALUES (?,?,?,?,1)",
               (next_ver, session['user_id'], json.dumps(snapshot), f'Rollback to version {version["version_number"]}'))
    db.execute("UPDATE app_settings SET value='0' WHERE key='timetable_published'")

    db.commit()
    db.close()
    log_activity(session['user_id'], 'rollback', f'Rolled back to version #{version["version_number"]}')
    flash(f'Rolled back to version {version["version_number"]}', 'success')
    return redirect(url_for('admin_versions'))


@app.route('/admin/notifications')
@login_required
@role_required('admin')
def admin_notifications():
    logs = get_activity_logs(200)
    return render_template('admin_notifications.html', logs=logs)


@app.route('/admin/heatmap')
@login_required
@role_required('admin')
def admin_heatmap():
    data = get_room_heatmap()
    return render_template('heatmap.html', data=data)


@app.route('/admin/live-tv')
@login_required
@role_required('admin')
def admin_live_tv():
    timetable = get_timetable()
    return render_template('live_tv.html', timetable=timetable)


# ─── Document Upload ───────────────────────────────────────────────

@app.route('/admin/upload-documents', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_upload_documents():
    if request.method == 'GET':
        return render_template('admin_upload.html')

    # Handle confirm import from preview (no file in this request)
    if request.form.get('confirm_import') == '1':
        parsed_data = session.pop('upload_parsed_data', {})
        filename = session.pop('upload_filename', 'preview')
        if not parsed_data:
            flash('Session expired. Please re-upload.', 'error')
            return redirect(url_for('admin_upload_documents'))
        result = admin_process_parsed_data(parsed_data, filename)
        return result

    # Normal file upload flow
    if 'file' not in request.files:
        flash('No file uploaded.', 'error')
        return redirect(url_for('admin_upload_documents'))

    file = request.files['file']
    if not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('admin_upload_documents'))

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.xlsx', '.xls', '.csv', '.docx', '.pptx'):
        flash('Please upload an Excel (.xlsx, .xls), Word (.docx), PowerPoint (.pptx) or CSV (.csv) file.', 'error')
        return redirect(url_for('admin_upload_documents'))

    # Save file temporarily
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    file.save(tmp.name)
    tmp.close()

    try:
        # Parse using the document parser
        parser = DocumentParser()
        parsed_data = parser.parse_all_formats(tmp.name)
        # Debug logging
        print(f"[UPLOAD DEBUG] Parsed data keys: {parsed_data.keys()}")
        print(f"[UPLOAD DEBUG] Courses: {len(parsed_data.get('courses', []))}")
        print(f"[UPLOAD DEBUG] Lecturers: {len(parsed_data.get('lecturers', []))}")
        print(f"[UPLOAD DEBUG] Rooms: {len(parsed_data.get('rooms', []))}")
        print(f"[UPLOAD DEBUG] Notes: {parsed_data.get('notes', 'N/A')}")
        if parsed_data.get('courses'):
            print(f"[UPLOAD DEBUG] First course: {parsed_data['courses'][0]}")
    except Exception as e:
        import os
        os.unlink(tmp.name)
        flash(f'Failed to parse file: {str(e)}', 'error')
        return redirect(url_for('admin_upload_documents'))
    
    # Clean up temp file
    import os
    try:
        os.unlink(tmp.name)
    except:
        pass

    if parsed_data.get('errors') or (not parsed_data.get('courses') and not parsed_data.get('lecturers') and not parsed_data.get('rooms')):
        flash(f'No parsable data found: {parsed_data.get("notes", "")}', 'warning')
        return redirect(url_for('admin_upload_documents'))

    # Store parsed data in session for preview
    session['upload_parsed_data'] = parsed_data
    session['upload_filename'] = file.filename

    return render_template('admin_upload.html', preview=True, 
                           courses=parsed_data.get('courses', []),
                           lecturers=parsed_data.get('lecturers', []),
                           rooms=parsed_data.get('rooms', []),
                           filename=file.filename)


def admin_process_parsed_data(parsed_data: Dict, filename: str) -> Any:
    """Process parsed data and create courses/lecturers in the database."""
    from models import get_db
    import re

    db = get_db()
    results = {'lecturers_created': 0, 'lecturers_skipped': 0, 'courses_created': 0, 'courses_skipped': 0, 'errors': []}

    try:
        # Process lecturers first
        for lecturer in parsed_data.get('lecturers', []):
            username = lecturer.get('username', '')
            if not username:
                continue

            existing = db.execute("SELECT id FROM users WHERE username=? AND role='lecturer'", (username,)).fetchone()

            if not existing:
                try:
                    email = lecturer.get('email', '')
                    full_name = lecturer.get('full_name', '')
                    title = lecturer.get('title')

                    if title and title not in full_name:
                        full_name = f"{title} {full_name}"

                    db.execute("INSERT INTO users (username, password, role, full_name, email) VALUES (?,?,?,?,?)",
                               (username, '1234', 'lecturer', full_name, email))
                    db.commit()

                    lecturer_id = db.execute("SELECT id FROM users WHERE username=? AND role='lecturer'", (username,)).fetchone()['id']

                    results['lecturers_created'] += 1

                    lecturer_note = f"Uploaded from {filename}"
                    if lecturer.get('notes'):
                        lecturer_note += f": {lecturer['notes']}"

                    log_activity(session['user_id'], 'upload_lecturer', lecturer_note)

                except Exception as e:
                    results['errors'].append(f"Failed to create lecturer {username}: {str(e)}")
                    db.rollback()
                    continue
            else:
                lecturer_id = existing['id']
                results['lecturers_skipped'] += 1

            # Process courses for this lecturer
            for course in parsed_data.get('courses', []):
                if course.get('lecturer_username') == username:
                    course_code = course.get('course_code', '')
                    course_name = course.get('course_name', course_code)
                    group = course.get('group', '1.1')
                    duration = course.get('duration_hours', 4)
                    department = course.get('department', '')
                    color = course.get('color', '#4A90D9')
                    max_students = course.get('max_students', 50)
                    notes = course.get('notes', '')

                    existing_course = db.execute("SELECT id FROM courses WHERE code=? AND group_name=?", (course_code, group)).fetchone()

                    if existing_course:
                        results['courses_skipped'] += 1
                        continue

                    try:
                        db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color, max_students) VALUES (?,?,?,?,?,?,?,?,?)",
                                   (course_name, course_code, 'department', lecturer_id, group, duration, None, color, max_students))
                        db.commit()

                        results['courses_created'] += 1

                        course_note = f"Uploaded from {filename}"
                        if notes:
                            course_note += f": {notes}"

                        log_activity(session['user_id'], 'upload_course', course_note)

                    except Exception as e:
                        results['errors'].append(f"Failed to create course {course_code}: {str(e)}")
                        db.rollback()
                        continue

        return render_template('admin_upload.html', results=results, filename=filename)

    except Exception as e:
        db.close()
        flash(f'Import failed: {str(e)}', 'error')
        return redirect(url_for('admin_upload_documents'))

    return render_template('admin_upload.html', results=results, filename=filename)

# ─── Lecturer Routes ───────────────────────────────────────────────

@app.route('/lecturer')
@login_required
@role_required('lecturer')
def lecturer_redirect():
    return redirect(url_for('dashboard'))


@app.route('/lecturer/add-course', methods=['POST'])
@login_required
@role_required('lecturer')
def add_course():
    name = request.form['name']
    code = request.form['code']
    level = request.form['level']
    group_name = request.form['group_name']
    duration = float(request.form.get('duration', 1.0))
    department_id = request.form.get('department_id') or None
    color = request.form.get('color', '#4A90D9')
    db = get_db()
    db.execute("INSERT INTO courses (name, code, level, lecturer_id, group_name, duration_hours, department_id, color) VALUES (?,?,?,?,?,?,?,?)",
               (name, code, level, session['user_id'], group_name, duration, department_id, color))
    db.commit()
    log_activity(session['user_id'], 'add_course', f'Added course: {name} ({code})', 'course')
    db.close()
    flash('Course added successfully!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/lecturer/delete-course/<int:course_id>', methods=['POST'])
@login_required
@role_required('lecturer')
def delete_course(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id=? AND lecturer_id=?", (course_id, session['user_id'])).fetchone()
    if course:
        db.execute("DELETE FROM timetable_entries WHERE course_id=?", (course_id,))
        db.execute("DELETE FROM courses WHERE id=?", (course_id,))
        db.commit()
        log_activity(session['user_id'], 'delete_course', f'Deleted course: {course["name"]}', 'course', course_id)
    db.close()
    flash('Course deleted.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/lecturer/update-preferences', methods=['POST'])
@login_required
@role_required('lecturer')
def update_preferences():
    days = json.dumps(request.form.getlist('days'))
    start_time = request.form.get('preferred_time_start', '08:00')
    end_time = request.form.get('preferred_time_end', '17:00')
    max_hours = float(request.form.get('max_hours_per_week', 20))
    avoid_b2b = 1 if request.form.get('avoid_back_to_back') else 0
    lunch_opt = 1 if request.form.get('lunch_break_optimize') else 0
    max_consec = float(request.form.get('max_consecutive_hours', 3.0))

    db = get_db()
    existing = db.execute("SELECT id FROM lecturer_preferences WHERE user_id=?", (session['user_id'],)).fetchone()
    if existing:
        db.execute("""UPDATE lecturer_preferences SET
            preferred_days=?, preferred_time_start=?, preferred_time_end=?,
            max_hours_per_week=?, avoid_back_to_back=?, lunch_break_optimize=?,
            max_consecutive_hours=?
            WHERE user_id=?""",
                   (days, start_time, end_time, max_hours, avoid_b2b, lunch_opt, max_consec, session['user_id']))
    else:
        db.execute("""INSERT INTO lecturer_preferences
            (user_id, preferred_days, preferred_time_start, preferred_time_end,
             max_hours_per_week, avoid_back_to_back, lunch_break_optimize, max_consecutive_hours)
            VALUES (?,?,?,?,?,?,?,?)""",
                   (session['user_id'], days, start_time, end_time, max_hours, avoid_b2b, lunch_opt, max_consec))
    db.commit()
    db.close()
    log_activity(session['user_id'], 'update_preferences', 'Updated teaching preferences')
    flash('Preferences saved!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/lecturer/availability', methods=['GET', 'POST'])
@login_required
@role_required('lecturer')
def lecturer_availability():
    if request.method == 'POST':
        data = request.get_json()
        db = get_db()
        try:
            db.execute("DELETE FROM lecturer_availability WHERE lecturer_id=?", (session['user_id'],))
            for slot in data.get('slots', []):
                db.execute("INSERT INTO lecturer_availability (lecturer_id, day, start_time, end_time, is_available) VALUES (?,?,?,?,?)",
                           (session['user_id'], slot['day'], slot['start'], slot['end'], 1))
            db.commit()
            return jsonify({'status': 'ok'})
        finally:
            db.close()

    db = get_db()
    availability = db.execute("SELECT * FROM lecturer_availability WHERE lecturer_id=?",
                              (session['user_id'],)).fetchall()
    db.close()
    return render_template('lecturer_availability.html', availability=[dict(a) for a in availability])


# ─── Student Routes ────────────────────────────────────────────────

@app.route('/student')
@login_required
@role_required('student')
def student_redirect():
    return redirect(url_for('dashboard'))


@app.route('/student/feed/<token>')
def student_shared_feed(token):
    db = get_db()
    share = db.execute("SELECT * FROM timetable_shares WHERE token=? AND is_active=1",
                       (token,)).fetchone()
    if not share:
        db.close()
        abort(404)
    entries = get_timetable(published_only=True)
    db.close()
    return render_template('shared_timetable.html', timetable=entries)


# ─── API Routes ────────────────────────────────────────────────────

@app.route('/api/timetable')
def api_timetable():
    published_only = request.args.get('published', '0') == '1'
    lecturer_id = request.args.get('lecturer_id', type=int)
    room_id = request.args.get('room_id', type=int)
    group = request.args.get('group')
    course_id = request.args.get('course_id', type=int)

    entries = get_timetable(published_only=published_only)

    if lecturer_id:
        entries = [e for e in entries if e['lecturer_id'] == lecturer_id]
    if room_id:
        entries = [e for e in entries if e['room_id'] == room_id]
    if group:
        entries = [e for e in entries if e['group_name'] == group]
    if course_id:
        entries = [e for e in entries if e['course_id'] == course_id]

    return jsonify(entries)


@app.route('/api/timetable/<int:entry_id>')
def api_timetable_entry(entry_id):
    entries = get_timetable(entry_id=entry_id)
    if not entries:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(entries[0])


@app.route('/api/timetable/update', methods=['POST'])
@login_required
def api_update_timetable():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    entry_id = data.get('id')
    day = data.get('day')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    room_id = data.get('room_id')

    db = get_db()
    entry = db.execute("SELECT * FROM timetable_entries WHERE id=?", (entry_id,)).fetchone()
    if not entry:
        db.close()
        return jsonify({'error': 'Entry not found'}), 404

    updates = []
    params = []
    if day:
        updates.append("day=?")
        params.append(day)
    if start_time:
        updates.append("start_time=?")
        params.append(start_time)
    if end_time:
        updates.append("end_time=?")
        params.append(end_time)
    if room_id:
        updates.append("room_id=?")
        params.append(room_id)

    if updates:
        params.append(entry_id)
        db.execute(f"UPDATE timetable_entries SET {', '.join(updates)} WHERE id=?", params)
        db.commit()

        updated = dict(entry)
        if day: updated['day'] = day
        if start_time: updated['start_time'] = start_time
        if end_time: updated['end_time'] = end_time
        if room_id: updated['room_id'] = room_id

        notify_timetable_change(updated, 'rescheduled')
        log_activity(session['user_id'], 'update_entry', f'Updated timetable entry #{entry_id}', 'timetable', entry_id)

    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/timetable/reorder', methods=['POST'])
@login_required
@role_required('admin')
def api_reorder_timetable():
    data = request.get_json()
    entries = data.get('entries', [])

    db = get_db()
    for e in entries:
        db.execute("""UPDATE timetable_entries SET
            day=?, start_time=?, end_time=?, room_id=?
            WHERE id=?""",
                   (e['day'], e['start_time'], e['end_time'], e['room_id'], e['id']))
    db.commit()
    db.close()

    log_activity(session['user_id'], 'reorder_timetable', f'Reordered {len(entries)} entries')
    return jsonify({'status': 'ok', 'count': len(entries)})


@app.route('/api/conflicts')
def api_conflicts():
    conflicts = detect_conflicts()
    return jsonify(conflicts)


@app.route('/api/conflicts/resolve/<int:entry_id>', methods=['POST'])
@login_required
@role_required('admin')
def api_resolve_conflict(entry_id):
    data = request.get_json()
    db = get_db()
    db.execute("INSERT INTO conflict_resolutions (timetable_entry_id, conflict_type, description, suggestion, applied, resolved_by) VALUES (?,?,?,?,1,?)",
               (entry_id, data.get('type', 'manual'), data.get('description', ''),
                data.get('suggestion', ''), session['user_id']))
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/analytics')
def api_analytics():
    data = get_analytics_data()
    return jsonify(data)


@app.route('/api/analytics/lecturer-workload')
def api_lecturer_workload():
    lecturer_id = request.args.get('lecturer_id', type=int)
    data = get_lecturer_workload(lecturer_id)
    return jsonify(data)


@app.route('/api/analytics/heatmap')
def api_heatmap():
    data = get_room_heatmap()
    return jsonify(data)


@app.route('/api/chatbot', methods=['POST'])
def api_chatbot():
    data = request.get_json()
    query = data.get('query', '')
    response = chatbot_response(query, {'user_id': session.get('user_id')})
    return jsonify({'response': response})


@app.route('/api/student/available-courses')
@login_required
@role_required('student')
def api_student_available_courses():
    db = get_db()
    courses = db.execute("""
        SELECT DISTINCT c.id, c.name, c.code, c.group_name
        FROM courses c
        JOIN timetable_entries te ON te.course_id = c.id
        WHERE te.published = 1
        ORDER BY c.name
    """).fetchall()
    db.close()
    return jsonify([dict(c) for c in courses])


@app.route('/api/student/enroll', methods=['POST'])
@login_required
@role_required('student')
def api_student_enroll():
    data = request.get_json()
    course_id = data.get('course_id')
    if not course_id:
        return jsonify({'error': 'Missing course_id'}), 400
    db = get_db()
    course = db.execute("SELECT id, name, group_name FROM courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        db.close()
        return jsonify({'error': 'Course not found'}), 404
    existing = db.execute(
        "SELECT id FROM student_enrollments WHERE student_id=? AND course_id=?",
        (session['user_id'], course_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'Already enrolled'}), 400
    db.execute(
        "INSERT INTO student_enrollments (student_id, course_id, group_name) VALUES (?,?,?)",
        (session['user_id'], course_id, course['group_name'])
    )
    db.commit()
    db.close()
    return jsonify({'status': 'ok', 'course_name': course['name']})


@app.route('/api/student/drop', methods=['POST'])
@login_required
@role_required('student')
def api_student_drop():
    data = request.get_json()
    course_id = data.get('course_id')
    if not course_id:
        return jsonify({'error': 'Missing course_id'}), 400
    db = get_db()
    db.execute(
        "DELETE FROM student_enrollments WHERE student_id=? AND course_id=?",
        (session['user_id'], course_id)
    )
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/student/my-timetable')
@login_required
@role_required('student')
def api_student_my_timetable():
    db = get_db()
    entries = db.execute("""
        SELECT DISTINCT te.*, c.name as course_name, c.code, c.color,
               u.full_name as lecturer_name, r.name as room_name
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
        JOIN student_enrollments se ON se.course_id = c.id AND se.student_id = ?
        WHERE te.published = 1
        ORDER BY te.day, te.start_time
    """, (session['user_id'],)).fetchall()
    enrolled = db.execute("""
        SELECT c.id, c.name, c.code, se.group_name
        FROM student_enrollments se
        JOIN courses c ON se.course_id = c.id
        WHERE se.student_id = ?
    """, (session['user_id'],)).fetchall()
    published = db.execute("SELECT value FROM app_settings WHERE key='timetable_published'").fetchone()
    db.close()
    return jsonify({
        'timetable': [dict(e) for e in entries],
        'enrolled_courses': [dict(e) for e in enrolled],
        'published': bool(published and published['value'] == '1')
    })


@app.route('/api/export/ics')
def api_export_ics():
    published_only = request.args.get('published', '1') == '1'
    entries = get_timetable(published_only=published_only)
    ics_content = export_ics(entries)
    return Response(ics_content, mimetype='text/calendar',
                    headers={'Content-Disposition': 'attachment;filename=timetable.ics'})


@app.route('/api/export/csv')
def api_export_csv():
    published_only = request.args.get('published', '1') == '1'
    entries = get_timetable(published_only=published_only)
    csv_content = export_csv(entries)
    return Response(csv_content, mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=timetable.csv'})


@app.route('/api/export/ical-feed')
def api_ical_feed():
    from export_utils import get_ical_feed
    ics_content = get_ical_feed()
    return Response(ics_content, mimetype='text/calendar',
                    headers={'Content-Disposition': 'inline;filename=calendar.ics'})


@app.route('/api/share', methods=['POST'])
@login_required
def api_create_share():
    token = str(uuid.uuid4())[:8]
    expires_hours = int(request.form.get('expires_hours', 48))
    expires_at = (datetime.now() + timedelta(hours=expires_hours)).strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    db.execute("INSERT INTO timetable_shares (token, created_by, expires_at) VALUES (?,?,?)",
               (token, session['user_id'], expires_at))
    db.commit()
    db.close()

    share_url = url_for('student_shared_feed', token=token, _external=True)
    log_activity(session['user_id'], 'share_timetable', f'Created share link: {share_url}')
    return jsonify({'token': token, 'url': share_url})


@app.route('/api/draft/save', methods=['POST'])
@login_required
def api_save_draft():
    data = request.get_json()
    save_draft(session['user_id'], data.get('entries', []))
    return jsonify({'status': 'ok'})


@app.route('/api/draft/load')
@login_required
def api_load_draft():
    draft = get_draft(session['user_id'])
    return jsonify(draft or {'data': [], 'updated_at': None})


@app.route('/api/notifications')
@login_required
def api_notifications():
    notifs = get_notifications(session['user_id'])
    return jsonify(notifs)


@app.route('/api/notifications/read/<int:notif_id>', methods=['POST'])
@login_required
def api_read_notification(notif_id):
    mark_notification_read(notif_id, session['user_id'])
    return jsonify({'status': 'ok'})


@app.route('/api/notifications/read-all', methods=['POST'])
@login_required
def api_read_all_notifications():
    mark_all_read(session['user_id'])
    return jsonify({'status': 'ok'})


@app.route('/api/notifications/count')
@login_required
def api_notification_count():
    return jsonify({'count': get_unread_count(session['user_id'])})


@app.route('/api/substitutes/available', methods=['POST'])
@login_required
@role_required('admin')
def api_find_substitutes():
    data = request.get_json()
    from ai_service import find_substitutes
    subs = find_substitutes(data.get('lecturer_id'), data.get('day'),
                            data.get('start_time'), data.get('end_time'))
    return jsonify(subs)


@app.route('/api/substitutes/assign', methods=['POST'])
@login_required
@role_required('admin')
def api_assign_substitute():
    data = request.get_json()
    db = get_db()
    db.execute("""INSERT INTO substitute_allocations
        (timetable_entry_id, original_lecturer_id, substitute_lecturer_id, reason, status, created_by)
        VALUES (?,?,?,?,?,?)""",
               (data['entry_id'], data['original_lecturer_id'],
                data['substitute_lecturer_id'], data.get('reason', ''),
                'approved', session['user_id']))
    db.execute("UPDATE timetable_entries SET lecturer_id=?, status='rescheduled' WHERE id=?",
               (data['substitute_lecturer_id'], data['entry_id']))
    db.commit()

    entry = db.execute("""
        SELECT te.*, c.name as course_name FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id WHERE te.id=?
    """, (data['entry_id'],)).fetchone()

    if entry:
        create_notification(data['substitute_lecturer_id'],
                            'Substitute Assignment',
                            f"You've been assigned as substitute for {entry['course_name']}",
                            'warning')

    log_activity(session['user_id'], 'assign_substitute', f'Assigned substitute for entry #{data["entry_id"]}')
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/attendance/mark', methods=['POST'])
@login_required
@role_required('lecturer')
def api_mark_attendance():
    data = request.get_json()
    db = get_db()
    for record in data.get('records', []):
        db.execute("DELETE FROM attendance_records WHERE timetable_entry_id=? AND student_id=?",
                   (record['entry_id'], record['student_id']))
        db.execute("""INSERT INTO attendance_records
            (timetable_entry_id, student_id, status, marked_by)
            VALUES (?,?,?,?)""",
                   (record['entry_id'], record['student_id'],
                    record['status'], session['user_id']))
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})


@app.route('/api/attendance/<int:entry_id>')
@login_required
def api_get_attendance(entry_id):
    db = get_db()
    records = db.execute("""
        SELECT ar.*, u.full_name as student_name
        FROM attendance_records ar
        JOIN users u ON ar.student_id = u.id
        WHERE ar.timetable_entry_id=?
    """, (entry_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in records])


@app.route('/api/validate-entry', methods=['POST'])
@login_required
def api_validate_entry():
    data = request.get_json()
    day = data.get('day')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    room_id = data.get('room_id')
    lecturer_id = data.get('lecturer_id')
    group_name = data.get('group_name')
    exclude_id = data.get('exclude_id')

    db = get_db()
    conflicts = []

    start_m = _time_to_min(start_time)
    end_m = _time_to_min(end_time)

    entries = db.execute("""SELECT te.*, c.name as course_name, u.full_name as lecturer_name, r.name as room_name
        FROM timetable_entries te
        JOIN courses c ON te.course_id = c.id
        JOIN users u ON te.lecturer_id = u.id
        JOIN rooms r ON te.room_id = r.id
        WHERE te.day = ? AND te.id != ? AND te.status = 'scheduled'
    """, (day, exclude_id or -1)).fetchall()

    for e in entries:
        e_start = _time_to_min(e['start_time'])
        e_end = _time_to_min(e['end_time'])
        if start_m < e_end and end_m > e_start:
            if e['lecturer_id'] == lecturer_id:
                conflicts.append(f"Lecturer conflict: {e['course_name']} ({e['start_time']}-{e['end_time']})")
            if e['room_id'] == room_id:
                conflicts.append(f"Room conflict: {e['course_name']} in {e['room_name']}")
            if e['group_name'] == group_name:
                conflicts.append(f"Group conflict: {e['course_name']} with {e['group_name']}")

    db.close()
    return jsonify({'valid': len(conflicts) == 0, 'conflicts': conflicts})


def _time_to_min(t):
    parts = t.split(':')
    return int(parts[0]) * 60 + int(parts[1])


@app.route('/api/db-dump')
@login_required
@role_required('admin')
def api_db_dump():
    db = get_db()
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    result = {}
    for t in tables:
        name = t['name']
        rows = db.execute(f'SELECT * FROM [{name}]').fetchall()
        result[name] = [dict(r) for r in rows]
    db.close()
    return jsonify(result)


@app.route('/api/seed-migration')
def seed_migration():
    password = request.args.get('password', '')
    if password != 'migrate2026':
        return jsonify({'error': 'unauthorized'}), 403
    try:
        seed_force()
        seed_data()
        return jsonify({'status': 'ok', 'message': 'Database reseeded with your local data'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Initialize database and seed if fresh (required for Render/Gunicorn)
init_db()
seed_data()

if __name__ == '__main__':
    app.run(debug=False, port=5000)
