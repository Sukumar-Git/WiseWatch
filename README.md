**Easiest start:** install Python 3.10+ and Node 18+, then double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux).

# BlindSpot 2.0
Upload CCTV recordings, detect objects with YOLOv8n, search by object/time/keyword, and play the original video at the matching timestamp.

## Run (two terminals)
Backend (Python 3.10+; first analysis downloads yolov8n.pt, so internet is needed once):
    cd backend
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000
Frontend (Node 18+):
    cd frontend && npm install && npm run dev      # open http://localhost:5173

## Using it
1. Upload an MP4/AVI/MOV you have permission to use. 2. Click "Start analysis" (real progress is shown). 3. Search, e.g. "Find people", "Show all vehicle detections", "person near a vehicle", "people between 20 and 60 seconds". 4. Click "Play at ..." (starts 3s before the detection).

## Config (env vars)
FRAME_INTERVAL=2  CONF_THRESHOLD=0.35  YOLO_MODEL=yolov8n.pt  MAX_UPLOAD_MB=500

## Honest limits
- Search is keyword + object + time-offset filtering, NOT semantic AI.
- Only object detection exists: no fall, collision, running, unattended-object or "suspicious" detection. Such queries return a clear "not supported" message.
- No wall-clock ("after 5 PM") search; videos only have offsets in seconds.
- AVI/some MOV files may not play in the browser; convert to H.264 MP4 (ffmpeg -i in.avi out.mp4).
- Detections are candidates for human review. Never commit footage to Git.
