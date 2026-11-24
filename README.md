# WiseWatch (static, in-browser YOLO)
Files: index.html (the whole app) + yolov8n.onnx (you add this, export once in Colab).
Test locally: in this folder run `python -m http.server 8080`, open http://localhost:8080
(or open index.html and pick yolov8n.onnx with the file picker).
Deploy: Netlify Drop, Cloudflare Pages, or Vercel (Framework Preset = Other, no build command).

## What it does
- Object detection (YOLOv8n via ONNX Runtime Web) on frames sampled every 1/2/5 s.
- Possible events inferred from how boxes move between frames: fall, running, collision,
  unattended object, entering/leaving view, person staying in place. Shown as "possible", with a reliability label.
- Search: synonyms + typo tolerance + object names + time offsets + clock times ("after 5 PM").
  Rule-based, not an AI language model.
- Recording start time: read from MP4 metadata when present, else estimated; editable.
- Unplayable video (AVI etc.): shows an ffmpeg conversion command.

## Honest limits
- Event checks are heuristics; thresholds were tested on scripted detections, not tuned on real CCTV.
  Collision is the weakest. 1 s steps recommended for falls/running.
- "Suspicious", fights, theft, weapons, faces: not detected.
- Named places (parking area, building) are not known; the whole view is searched.
- Use only footage you have permission to analyse.
