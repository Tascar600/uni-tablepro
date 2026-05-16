import smtplib
import ssl
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from models import get_db

SMTP_CONFIG = {
    'enabled': False,
    'host': 'smtp.gmail.com',
    'port': 587,
    'username': '',
    'password': '',
    'from_address': 'noreply@timetable.uni.edu',
    'use_tls': True,
}


def configure_smtp(host, port, username, password, from_address):
    SMTP_CONFIG.update({
        'enabled': True,
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'from_address': from_address,
    })


def send_email(to_address, subject, html_body):
    if not SMTP_CONFIG['enabled'] or not to_address:
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_CONFIG['from_address']
        msg['To'] = to_address

        part = MIMEText(html_body, 'html')
        msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_CONFIG['host'], SMTP_CONFIG['port']) as server:
            if SMTP_CONFIG['use_tls']:
                server.starttls(context=context)
            server.login(SMTP_CONFIG['username'], SMTP_CONFIG['password'])
            server.sendmail(SMTP_CONFIG['from_address'], to_address, msg.as_string())
        return True
    except Exception:
        return False


def create_notification(user_id, title, message, type='info', link=None):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, title, message, type, link) VALUES (?,?,?,?,?)",
        (user_id, title, message, type, link)
    )
    db.commit()

    user = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()

    if user and user['email'] and SMTP_CONFIG['enabled']:
        send_email(
            user['email'],
            f"[Timetable] {title}",
            f"<h2>{title}</h2><p>{message}</p>"
        )


def notify_timetable_change(entry, change_type='updated'):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id=?", (entry['course_id'],)).fetchone()
    lecturer = db.execute("SELECT * FROM users WHERE id=?", (entry['lecturer_id'],)).fetchone()

    if lecturer:
        msg = f"Your class {course['name']} ({course['code']}) has been {change_type}: {entry['day']} {entry['start_time']}-{entry['end_time']} in {entry.get('room_name', 'TBD')}"
        create_notification(lecturer['id'], f"Class {change_type}", msg, 'warning' if change_type == 'rescheduled' else 'info')

    students = db.execute("""
        SELECT u.* FROM users u
        JOIN student_enrollments se ON u.id = se.student_id
        WHERE se.course_id = ? AND se.group_name = ?
    """, (entry['course_id'], entry['group_name'])).fetchall()

    for student in students:
        msg = f"Your class {course['name']} ({course['code']}) has been {change_type}: {entry['day']} {entry['start_time']}-{entry['end_time']} in {entry.get('room_name', 'TBD')}"
        create_notification(student['id'], f"Class {change_type}", msg, 'warning' if change_type == 'rescheduled' else 'info')

    db.close()


def get_unread_count(user_id):
    db = get_db()
    row = db.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id=? AND read=0", (user_id,)).fetchone()
    db.close()
    return row['count'] if row else 0


def get_notifications(user_id, limit=50):
    db = get_db()
    rows = db.execute("""
        SELECT * FROM notifications WHERE user_id=?
        ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def mark_notification_read(notification_id, user_id):
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (notification_id, user_id))
    db.commit()
    db.close()


def mark_all_read(user_id):
    db = get_db()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user_id,))
    db.commit()
    db.close()


def log_activity(user_id, action, details, entity_type=None, entity_id=None):
    db = get_db()
    db.execute(
        "INSERT INTO activity_logs (user_id, action, details, entity_type, entity_id) VALUES (?,?,?,?,?)",
        (user_id, action, details, entity_type, entity_id)
    )
    db.commit()
    db.close()


def get_activity_logs(limit=100):
    db = get_db()
    rows = db.execute("""
        SELECT al.*, u.full_name as user_name
        FROM activity_logs al
        JOIN users u ON al.user_id = u.id
        ORDER BY al.timestamp DESC LIMIT ?
    """, (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]
