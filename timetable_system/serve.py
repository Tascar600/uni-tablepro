import os, sys, threading, time, socket, requests
sys.path.insert(0, '.')
from app import app

port = int(os.environ.get('PORT', 5000))
hostname = socket.gethostname()
ips = []
for info in socket.getaddrinfo(hostname, port, socket.AF_INET):
    ip = info[4][0]
    if ip not in ips and not ip.startswith('127.'):
        ips.append(ip)

t = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False), daemon=True)
t.start()
time.sleep(4)

r = requests.get(f'http://127.0.0.1:{port}/login')
print('=' * 55)
print('  TIMETABLE SYSTEM IS RUNNING')
print('=' * 55)
print()
print('  Try these URLs in your browser:')
print()
print(f'    http://127.0.0.1:{port}')
print(f'    http://localhost:{port}')
for ip in ips:
    print(f'   http://{ip}:{port}')
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
