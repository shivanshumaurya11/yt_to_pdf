"""
Flask Video -> Frames PDF (Render-ready)

Features:
- Paste a YouTube link OR upload a local video file.
- Preview video in the browser (YouTube iframe for youtube links, HTML5 <video> for direct links/ uploads).
- Server-side: downloads the video (yt-dlp), extracts unique frames using OpenCV + SSIM, converts frames to a single PDF with timestamps (FPDF).
- Designed to be deployed to Render using Gunicorn. Optional Dockerfile included if you need ffmpeg.
- IMPORTANT: long-running processing may exceed HTTP timeouts on some hosts. For Render, use a longer gunicorn timeout (example provided).
"""

import os
import re
import uuid
import shutil
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_file, url_for, render_template
from werkzeug.utils import secure_filename

# Third-party libs
import yt_dlp
import cv2
from skimage.metrics import structural_similarity as ssim
from fpdf import FPDF
from PIL import Image

# Configuration
UPLOAD_FOLDER = "/tmp/video_to_pdf_uploads"
RESULTS_FOLDER = "/tmp/video_to_pdf_results"
ALLOWED_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "avi", "ogv"}
MAX_CONTENT_LENGTH = 300 * 1024 * 1024  # 300 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def sanitize_filename(s: str) -> str:
    return secure_filename(re.sub(r"[\\\\/:*?\"<>|]+", "-", s).strip("."))

def start_cleanup(path: str, delay_seconds: int = 3600):
    def _cleanup():
        try:
            threading.Event().wait(delay_seconds)
            if os.path.exists(path):
                shutil.rmtree(path)
        except Exception:
            pass
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

def download_video_with_yt_dlp(url: str, outdir: str, prefer_mp4: bool = True, max_retries: int = 3) -> str:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    outtmpl = os.path.join(outdir, "video.%(ext)s")
    format_pref = "best[ext=mp4]/best" if prefer_mp4 else "best"
    ydl_opts = {"format": format_pref, "outtmpl": outtmpl, "noplaylist": True, "quiet": True}
    last_exc = None
    for attempt in range(1, max_retries+1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            # find downloaded file
            for f in os.listdir(outdir):
                if f.startswith("video."):
                    return os.path.join(outdir, f)
            raise RuntimeError("Download succeeded but output file not found.")
        except Exception as e:
            last_exc = e
    raise RuntimeError(f"yt-dlp failed after {max_retries} attempts: {last_exc}")

def get_video_title(url: str) -> str:
    try:
        ydl_opts = {"skip_download": True, "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title") or "video"
            return sanitize_filename(title)[:80]
    except Exception:
        return sanitize_filename(url)[:60]

def extract_unique_frames(video_path: str, frames_out: str, sample_rate: int = 3, ssim_threshold: float = 0.80, max_frames: int = 50):
    Path(frames_out).mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video file.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_idx = 0
    saved = []
    last_small = None
    ssim_size = (160, 90)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_rate != 0:
            frame_idx += 1
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, ssim_size, interpolation=cv2.INTER_AREA)
        should_save = False
        if last_small is None:
            should_save = True
        else:
            try:
                sim = ssim(small, last_small, data_range=small.max() - small.min())
            except Exception:
                sim = 0.0
            if sim < ssim_threshold:
                should_save = True
        if should_save:
            timestamp = int(frame_idx / fps)
            out_name = f"frame_{frame_idx:06d}_{timestamp}s.png"
            out_path = os.path.join(frames_out, out_name)
            cv2.imwrite(out_path, frame)
            saved.append((out_name, timestamp))
            last_small = small
            if len(saved) >= max_frames:
                break
        frame_idx += 1
    cap.release()
    return saved

def convert_frames_to_pdf(frames_dir: str, out_pdf_path: str):
    files = sorted([f for f in os.listdir(frames_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))])
    if not files:
        raise RuntimeError("No frames found.")
    pdf = FPDF(orientation='L')
    pdf.set_auto_page_break(False)
    for fname in files:
        fpath = os.path.join(frames_dir, fname)
        pdf.add_page()
        pdf.image(fpath, x=0, y=0, w=pdf.w, h=pdf.h)
        # derive timestamp
        m = re.search(r"_(\\d+)s", fname)
        seconds = int(m.group(1)) if m else 0
        ts = f"{seconds//3600:02d}:{(seconds%3600)//60:02d}:{seconds%60:02d}"
        # contrast check
        img = Image.open(fpath).convert('L')
        region = img.crop((5,5,65,20)).resize((1,1))
        mean = region.getpixel((0,0))
        pdf.set_text_color(255,255,255 if mean<64 else 0)
        pdf.set_xy(5,5)
        pdf.set_font('Helvetica', size=12)
        pdf.cell(0,0,ts)
    pdf.output(out_pdf_path)
    return out_pdf_path

# Routes
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    # parameters
    sample_rate = int(request.form.get("sample_rate", 3))
    ssim_thr = float(request.form.get("ssim", 0.80))
    max_frames = int(request.form.get("max_frames", 40))

    video_url = request.form.get("video_url")
    upload = request.files.get("video_file")

    task_id = uuid.uuid4().hex
    task_dir = os.path.join(RESULTS_FOLDER, task_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        if upload and upload.filename:
            if not allowed_file(upload.filename):
                return jsonify({"error":"Unsupported file type."}), 400
            filename = sanitize_filename(upload.filename)
            video_path = os.path.join(task_dir, filename)
            upload.save(video_path)
            title = os.path.splitext(filename)[0]
        elif video_url:
            title = get_video_title(video_url)
            # download to task_dir
            video_path = download_video_with_yt_dlp(video_url, task_dir)
        else:
            return jsonify({"error":"No video provided."}), 400

        frames_dir = os.path.join(task_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        saved = extract_unique_frames(video_path, frames_dir, sample_rate=sample_rate, ssim_threshold=ssim_thr, max_frames=max_frames)
        if not saved:
            return jsonify({"error":"No distinctive frames found. Try lowering SSIM threshold or increasing max frames."}), 400

        pdf_name = f"{sanitize_filename(title)}_{task_id}.pdf"
        pdf_path = os.path.join(task_dir, pdf_name)
        convert_frames_to_pdf(frames_dir, pdf_path)

        # schedule cleanup
        start_cleanup(task_dir, delay_seconds=60*60)

        download_url = url_for("download", task_id=task_id, filename=pdf_name, _external=True)
        return jsonify({"status":"done", "download_url":download_url})
    except Exception as e:
        shutil.rmtree(task_dir, ignore_errors=True)
        return jsonify({"error": str(e)}), 500

@app.route("/download/<task_id>/<path:filename>")
def download(task_id, filename):
    safe_dir = os.path.join(RESULTS_FOLDER, task_id)
    fpath = os.path.join(safe_dir, filename)
    if not os.path.exists(fpath):
        return "Not found", 404
    return send_file(fpath, as_attachment=True)

if __name__ == "__main__":
    # For local dev: use Flask's server
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)