import os
port = os.environ.get('PORT', 10000)
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.system(f"gunicorn app:app --bind 0.0.0.0:{port} --workers=2 --timeout=120 --log-level=info")
