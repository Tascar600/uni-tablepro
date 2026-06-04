import os, sys
sys.path.insert(0, os.path.dirname(__file__))
port = os.environ.get('PORT', 10000)
os.system(f"gunicorn app:app --bind 0.0.0.0:{port} --workers=2 --timeout=120 --log-level=info")
