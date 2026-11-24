@echo off
cd /d "%~dp0"
echo Starting BlindSpot. Two windows will open; keep both open.
echo First run installs everything and can take several minutes.
start "BlindSpot backend" cmd /k "cd backend && (if not exist .venv python -m venv .venv) && call .venv\Scripts\activate && pip install -r requirements.txt && uvicorn app.main:app --port 8000"
start "BlindSpot frontend" cmd /k "npm install && npm run dev -- --open"
