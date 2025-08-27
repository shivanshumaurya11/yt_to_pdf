# Video → PDF (Frames) — Render-ready Flask App

This repository contains a Flask application that:
- Accepts a **YouTube URL** or local video upload.
- Downloads the video with **yt-dlp**.
- Extracts visually-unique frames using **OpenCV** + **SSIM**.
- Generates a single **PDF** with timestamps using **FPDF**.
- Provides a web UI to preview and trigger processing.

---

## What I fixed / improved (analysis of your original code)

Your input script already had the right pieces. I analyzed it and applied these fixes and hardening:

1. **Installation commands**: original single-line `!pip install ...` fixed to `requirements.txt` for reproducible installs.
2. **Redundant imports and PIL handling**: removed `sys.modules['ImageFile']` hack and used `Pillow` properly.
3. **Frame extraction edge cases**: ensured the last unique frame is saved and limited `max_frames` to avoid enormous PDFs.
4. **FPDF font**: used `Helvetica` (built-in) to avoid missing font errors; fallback handled.
5. **Colab-only code**: removed `google.colab`-specific `files.download()` – app now works in any environment (Colab, local, Render).
6. **Robust yt-dlp usage**: retries and sane output template, prefer MP4 for OpenCV compatibility.
7. **Security / hygiene**: per-task temp directories, filename sanitization, cleanup thread to remove temp results after 1 hour.
8. **Playlist support**: not included in this repo (playlist handling is more complex and better handled as a background job). The app processes single videos or uploaded files.
9. **Error handling**: JSON-friendly errors that help debug issues on Render.

---

## Files included

- `app.py` — main Flask application (see routes `/` and `/process`)
- `requirements.txt` — Python dependencies
- `Procfile` — for Render (uses Gunicorn)
- `Dockerfile` — optional: includes `ffmpeg` (useful for some yt-dlp setups); choose Docker on Render if you need system packages
- `templates/index.html` — UI (Bootstrap), file upload, preview, and client-side processing
- `static/style.css`
- `README.md` — this file

---

## Notes about Render hosting

- Start command: Render will use a start command to run your app. The official docs recommend **Gunicorn** for Python web services. Example: `gunicorn app:app`. (Render docs: deploy start command). citeturn0search1
- Timeouts: If your processing takes a long time, increase Gunicorn timeout (example in `Procfile` uses `--timeout 300`). Render troubleshooting docs show adjusting worker/gunicorn timeout can help avoid worker timeouts. citeturn0search18turn0search10
- ffmpeg: Some yt-dlp features or video containers require `ffmpeg`. If you need `ffmpeg`, use the included `Dockerfile` and select **Docker** in Render for the service so system packages (like ffmpeg) are installed. (See Docker/ffmpeg guidance). citeturn0search5turn0search20

---

## Quick local test

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

For production-like run locally:
```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --timeout 300
```

---

## Deploy to Render (step-by-step)

1. Initialize git and push this repository to GitHub:
```bash
git init
git add .
git commit -m "Initial commit - video to pdf"
git branch -M main
# create a repo on GitHub and replace URL below:
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

2. On Render.com:
   - Click **New +** → **Web Service**.
   - Connect your GitHub account and select your repo.
   - Choose **Environment**: *Python* (or **Docker** if you included `Dockerfile` and want ffmpeg).
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 300`
   - Click **Create Web Service** → Deploy.

3. After deploy, Render will give you a public URL like `https://<service>.onrender.com`. Open it and test by pasting a YouTube link or uploading a short video.

---

## Docker option (if you need ffmpeg)

If you need `ffmpeg`, choose **Docker** on Render and the provided `Dockerfile` will install `ffmpeg` on the container. This is recommended if your use-case uses formats that require post-processing.

---

## Caveats and recommendations

- Processing long videos on a web request can be slow and may hit request limits on some hosts. For production, consider:
  - Offloading processing to a background worker (e.g., Redis + RQ, Celery, or Render Background Worker) and provide the user a job status endpoint or email when ready.
  - Limit upload sizes and max frames to keep PDFs reasonable.
- Playlist support is intentionally omitted in this initial repo to keep the app simple and deployable quickly.

---

## Helpful references
- Render start command / deploy docs. citeturn0search1  
- Render troubleshooting (gunicorn/worker timeout). citeturn0search18  
- Installing ffmpeg in Docker (useful if you need system packages). citeturn0search5turn0search20