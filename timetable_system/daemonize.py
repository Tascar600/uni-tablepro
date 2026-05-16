"""Start Flask as a truly detached process that survives shell exit."""
import subprocess, sys, os, time

script = r"""
import sys, os
sys.path.insert(0, r'C:\Users\SHIMEKAh\Desktop\project\timetable_system')
os.chdir(r'C:\Users\SHIMEKAh\Desktop\project\timetable_system')
from app import app
app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
"""

# DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
flags = 0x00000008 | 0x00000200

proc = subprocess.Popen(
    [sys.executable, '-c', script],
    close_fds=True,
    creationflags=flags,
    stdout=open(os.devnull, 'w'),
    stderr=open(os.devnull, 'w'),
)

# Write PID to file so we can kill it later
with open(r'C:\Users\SHIMEKAh\Desktop\project\timetable_system\server.pid', 'w') as f:
    f.write(str(proc.pid))

print(f'Server started as PID {proc.pid}')
print('http://127.0.0.1:5000')
print('http://localhost:5000')
