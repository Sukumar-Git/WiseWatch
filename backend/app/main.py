"""BlindSpot 2.0 backend: upload -> sample frames -> YOLO -> SQLite -> search -> playback."""
import json, os, re, shutil, sqlite3, threading, time
from pathlib import Path
from typing import Optional

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
UPLOADS, THUMBS = ROOT / "uploads", ROOT / "thumbnails"
DB_PATH = ROOT / "blindspot.db"
UPLOADS.mkdir(exist_ok=True); THUMBS.mkdir(exist_ok=True)

FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", 2))   # seconds between analysed frames
CONF = float(os.getenv("CONF_THRESHOLD", 0.35))
MODEL_NAME = os.getenv("YOLO_MODEL", "yolov8n.pt")        # downloaded automatically on first use
ALLOWED = {".mp4", ".avi", ".mov"}
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", 500))

app = FastAPI(title="BlindSpot 2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/thumbs", StaticFiles(directory=THUMBS), name="thumbs")

_model, _model_lock = None, threading.Lock()

def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from ultralytics import YOLO
            _model = YOLO(MODEL_NAME)
        return _model

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS videos(
      id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, path TEXT, size INTEGER,
      duration REAL DEFAULT 0, status TEXT DEFAULT 'uploaded', error TEXT,
      processed INTEGER DEFAULT 0, total INTEGER DEFAULT 0, created REAL);
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER, ts REAL, event_type TEXT,
      description TEXT, objects TEXT, confidence REAL, thumbnail TEXT, boxes TEXT);
    CREATE INDEX IF NOT EXISTS ev_video ON events(video_id, ts);
    """)

# ---------- upload / video management ----------
@app.post("/api/videos")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use MP4, AVI or MOV.")
    safe = f"{int(time.time()*1000)}_{re.sub(r'[^A-Za-z0-9._-]', '_', file.filename)}"
    dest, size = UPLOADS / safe, 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_MB * 1024 * 1024:
                f.close(); dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_MB} MB limit.")
            f.write(chunk)
    cap = cv2.VideoCapture(str(dest))
    fps, n = cap.get(cv2.CAP_PROP_FPS) or 0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    if not fps or not n:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Could not read this video file.")
    with db() as c:
        cur = c.execute("INSERT INTO videos(filename,path,size,duration,created) VALUES(?,?,?,?,?)",
                        (file.filename, str(dest), size, n / fps, time.time()))
        return {"video_id": cur.lastrowid, "status": "uploaded"}

@app.get("/api/videos")
def list_videos():
    with db() as c:
        rows = c.execute("""SELECT v.*, (SELECT COUNT(*) FROM events e WHERE e.video_id=v.id) AS events
                            FROM videos v ORDER BY id DESC""").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/videos/{vid}/file")
def video_file(vid: int):
    with db() as c:
        r = c.execute("SELECT path FROM videos WHERE id=?", (vid,)).fetchone()
    if not r: raise HTTPException(404, "Video not found")
    return FileResponse(r["path"])   # supports HTTP range requests so seeking works

@app.delete("/api/videos/{vid}")
def delete_video(vid: int):
    with db() as c:
        r = c.execute("SELECT path FROM videos WHERE id=?", (vid,)).fetchone()
        if not r: raise HTTPException(404, "Video not found")
        for t in c.execute("SELECT thumbnail FROM events WHERE video_id=?", (vid,)):
            if t["thumbnail"]: (THUMBS / t["thumbnail"]).unlink(missing_ok=True)
        c.execute("DELETE FROM events WHERE video_id=?", (vid,))
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
    Path(r["path"]).unlink(missing_ok=True)
    return {"deleted": vid}

# ---------- processing ----------
def describe(labels):
    counts = {}
    for l in labels: counts[l] = counts.get(l, 0) + 1
    parts = [f"{n} {l}" if n > 1 else f"1 {l}" for l, n in sorted(counts.items(), key=lambda x: -x[1])]
    return "Detected: " + ", ".join(parts)

def process_video(vid: int, interval: float):
    try:
        with db() as c:
            v = c.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
            c.execute("DELETE FROM events WHERE video_id=?", (vid,))
            c.execute("UPDATE videos SET status='processing', error=NULL, processed=0 WHERE id=?", (vid,))
        model = get_model()
        cap = cv2.VideoCapture(v["path"])
        times = []
        t = 0.0
        while t < v["duration"]:
            times.append(round(t, 2)); t += interval
        with db() as c:
            c.execute("UPDATE videos SET total=? WHERE id=?", (len(times), vid))
        for i, ts in enumerate(times):
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ok, frame = cap.read()
            if ok:
                res = model(frame, conf=CONF, verbose=False)[0]
                dets = []
                for b in res.boxes:
                    dets.append({"label": model.names[int(b.cls)], "conf": round(float(b.conf), 3),
                                 "box": [round(float(x), 1) for x in b.xyxy[0].tolist()]})
                if dets:
                    h, w = frame.shape[:2]
                    for d in dets:   # draw boxes on the saved thumbnail
                        x1, y1, x2, y2 = map(int, d["box"])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
                        cv2.putText(frame, f'{d["label"]} {d["conf"]:.2f}', (x1, max(14, y1 - 6)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
                    scale = 480 / w
                    small = cv2.resize(frame, (480, int(h * scale)))
                    name = f"v{vid}_{int(ts*1000)}.jpg"
                    cv2.imwrite(str(THUMBS / name), small)
                    labels = [d["label"] for d in dets]
                    with db() as c:
                        c.execute("""INSERT INTO events(video_id,ts,event_type,description,objects,confidence,thumbnail,boxes)
                                     VALUES(?,?,?,?,?,?,?,?)""",
                                  (vid, ts, "object_detected", describe(labels), json.dumps(sorted(set(labels))),
                                   max(d["conf"] for d in dets), name, json.dumps(dets)))
            with db() as c:
                c.execute("UPDATE videos SET processed=? WHERE id=?", (i + 1, vid))
        cap.release()
        with db() as c:
            c.execute("UPDATE videos SET status='completed' WHERE id=?", (vid,))
    except Exception as e:
        with db() as c:
            c.execute("UPDATE videos SET status='failed', error=? WHERE id=?", (str(e), vid))

@app.post("/api/videos/{vid}/process")
def start_processing(vid: int, interval: Optional[float] = None):
    with db() as c:
        r = c.execute("SELECT status FROM videos WHERE id=?", (vid,)).fetchone()
    if not r: raise HTTPException(404, "Video not found")
    if r["status"] == "processing": raise HTTPException(409, "Already processing")
    threading.Thread(target=process_video, args=(vid, max(0.5, interval or FRAME_INTERVAL)), daemon=True).start()
    return {"video_id": vid, "status": "processing"}

# ---------- search ----------
GROUPS = {
    "person": ["person", "people", "persons", "man", "men", "woman", "women", "human", "humans", "pedestrian", "pedestrians", "someone"],
    "vehicle": ["vehicle", "vehicles", "traffic"],
    "car": ["car", "cars"], "bus": ["bus", "buses"], "truck": ["truck", "trucks"],
    "motorcycle": ["motorcycle", "motorcycles", "motorbike", "bike", "bikes"],
    "bicycle": ["bicycle", "bicycles", "cyclist", "cyclists"],
    "bag": ["bag", "bags"], "backpack": ["backpack", "backpacks"], "handbag": ["handbag", "handbags"],
    "suitcase": ["suitcase", "luggage"], "dog": ["dog", "dogs"], "cat": ["cat", "cats"],
    "bench": ["bench"], "umbrella": ["umbrella"], "cell phone": ["phone", "cellphone"],
    "bottle": ["bottle", "bottles"], "chair": ["chair", "chairs"], "laptop": ["laptop"],
    "traffic light": ["traffic light"],
}
EXPAND = {"vehicle": ["car", "bus", "truck", "motorcycle", "bicycle"], "bag": ["backpack", "handbag", "suitcase"]}
UNSUPPORTED = ["fall", "falling", "fell", "collision", "collide", "crash", "accident", "suspicious", "fight",
               "unattended", "left behind", "abandoned", "running", "theft", "steal", "weapon", "face", "entering", "entered"]

def parse_query(q: str):
    ql = q.lower()
    notes, unsupported = [], []
    labels = []
    for canon, words in GROUPS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", ql):
                labels.append(canon); break
    # expand group terms into concrete COCO classes
    flat = []
    for l in labels:
        flat.append(EXPAND.get(l, [l]))
    require_all = bool(re.search(r"\b(near|with|and|next to|beside)\b", ql)) and len(flat) > 1
    t_from = t_to = None
    m = re.search(r"between\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)", ql)
    if m: t_from, t_to = float(m.group(1)), float(m.group(2))
    else:
        a = re.search(r"after\s+(\d+(?:\.\d+)?)\s*(s|sec|seconds?|min|minutes?)\b", ql)
        b = re.search(r"before\s+(\d+(?:\.\d+)?)\s*(s|sec|seconds?|min|minutes?)\b", ql)
        if a: t_from = float(a.group(1)) * (60 if a.group(2).startswith("min") else 1)
        if b: t_to = float(b.group(1)) * (60 if b.group(2).startswith("min") else 1)
    if re.search(r"\b\d{1,2}(:\d\d)?\s*(am|pm)\b", ql):
        unsupported.append("clock times (AM/PM) – videos only have offsets in seconds, so use e.g. 'between 20 and 60 seconds'")
    for w in UNSUPPORTED:
        if re.search(rf"\b{re.escape(w)}\b", ql):
            unsupported.append(f"'{w}' (event/behaviour detection is not implemented; only object detection is)")
    return flat, require_all, t_from, t_to, unsupported

class SearchReq(BaseModel):
    query: str = ""
    video_id: Optional[int] = None
    objects: list[str] = []
    t_from: Optional[float] = None
    t_to: Optional[float] = None
    min_conf: float = 0.0

@app.post("/api/search")
def search(req: SearchReq):
    flat, require_all, t_from, t_to, unsupported = parse_query(req.query)
    t_from = req.t_from if req.t_from is not None else t_from
    t_to = req.t_to if req.t_to is not None else t_to
    groups = flat + [[o] for o in req.objects]
    if req.query.strip() and not groups and t_from is None and t_to is None:
        return {"results": [], "interpreted": None, "unsupported": unsupported,
                "message": "I couldn't map that to something I can search. Try object names (person, car, bus, truck, bag…) and/or a time range like 'between 20 and 60 seconds'."
                           + (" Not supported: " + "; ".join(unsupported) if unsupported else "")}
    sql = """SELECT e.*, v.filename FROM events e JOIN videos v ON v.id=e.video_id WHERE e.confidence>=?"""
    args = [req.min_conf]
    if req.video_id: sql += " AND e.video_id=?"; args.append(req.video_id)
    if t_from is not None: sql += " AND e.ts>=?"; args.append(t_from)
    if t_to is not None: sql += " AND e.ts<=?"; args.append(t_to)
    sql += " ORDER BY e.confidence DESC, e.ts LIMIT 500"
    with db() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        objs = set(json.loads(r["objects"]))
        hit = [bool(objs & set(g)) for g in groups]
        if groups and not (all(hit) if (require_all or req.objects) else any(hit)): continue
        out.append({"id": r["id"], "video_id": r["video_id"], "filename": r["filename"], "timestamp": r["ts"],
                    "objects": sorted(objs), "confidence": r["confidence"], "description": r["description"],
                    "thumbnail": f"/thumbs/{r['thumbnail']}", "boxes": json.loads(r["boxes"])})
    interp = {"object_groups": groups, "match": "all" if require_all else "any", "from": t_from, "to": t_to}
    msg = None
    if unsupported: msg = "Partly supported. Not understood: " + "; ".join(unsupported) + ". Showing object/time matches only."
    elif not out: msg = "No matching detections found."
    return {"results": out, "interpreted": interp, "unsupported": unsupported, "message": msg}

@app.get("/api/videos/{vid}/events")
def events(vid: int):
    with db() as c:
        rows = c.execute("SELECT id, ts, objects, confidence FROM events WHERE video_id=? ORDER BY ts", (vid,)).fetchall()
    return [{"id": r["id"], "timestamp": r["ts"], "objects": json.loads(r["objects"]), "confidence": r["confidence"]} for r in rows]

@app.get("/api/stats")
def stats():
    with db() as c:
        counts = {}
        for r in c.execute("SELECT objects FROM events"):
            for o in json.loads(r["objects"]): counts[o] = counts.get(o, 0) + 1
        return {"videos": c.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
                "events": c.execute("SELECT COUNT(*) FROM events").fetchone()[0], "by_object": counts}
