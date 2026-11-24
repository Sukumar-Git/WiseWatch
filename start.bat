@echo off
cd /d "%~dp0"
echo Starting BlindSpot. Two windows will open; keep both open.
start "BlindSpot backend" cmd /k "cd backend && (if not exist .venv python -m venv --system-site-packages .venv) && call .venv\Scripts\activate && pip install -r requirements.txt && uvicorn app.main:app --port 8000"
start "BlindSpot frontend" cmd /k "npm run dev -- --open"
