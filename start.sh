#!/usr/bin/env bash
cd "$(dirname "$0")"
(cd backend && { [ -d .venv ] || python3 -m venv .venv; } && . .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --port 8000) &
(npm install && npm run dev -- --open) &
wait
