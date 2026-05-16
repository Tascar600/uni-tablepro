import sys, threading, time, socket, requests
sys.path.insert(0, '.')
from app import app

hostname = socket.gethostname()
ips = []
for info in socket.getaddrinfo(hostname, 5000, socket.AF_INET):
    ip = info[4][0]
    if ip not in ips and not ip.startswith('127.'):
        ips.append(ip)

t = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False), daemon=True)
t.start()
time.sleep(4)

r = requests.get('http://127.0.0.1:5000/login')
print('=' * 55)
print('  TIMETABLE SYSTEM IS RUNNING')
print('=' * 55)
print()
print('  Try these URLs in your browser:')
print()
print('    http://127.0.0.1:5000')
print('    http://localhost:5000')
for ip in ips:
    print(f'   http://{ip}:5000')
print()
print('  Demo accounts:')
print('    Admin:    admin / admin123')
print('    Lecturer: lecturer1 / pass123')
print('    Student:  student1 / pass123')
print()
print('  Press Ctrl+C to stop.')
print('=' * 55)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print('Stopped.')
