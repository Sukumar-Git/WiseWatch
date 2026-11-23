# BlindSpot (static, in-browser YOLO)
Files: index.html (the whole app) + yolov8n.onnx (you add this).
Test locally: in this folder run `python -m http.server 8080`, open http://localhost:8080
(or just open index.html and pick yolov8n.onnx with the file picker).
Deploy: Netlify Drop, Cloudflare Pages, or Vercel (import the GitHub repo, Framework Preset = Other, no build command). No build step.
