# app.py
import os
import time
import re
import random
import threading
from pathlib import Path
from typing import Optional, Tuple

import requests
from flask import Flask, request, jsonify, render_template_string, send_file, abort
import yt_dlp

# ============== CONFIG ==============
# TMP dir (Render containers use /tmp)
BASE_TMP = Path(os.environ.get("TMPDIR", "/tmp"))
TMP_DIR = BASE_TMP / "mini_y2mate_tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# BACKENDS: comma-separated URLs like "https://a.example.com,https://b.example.com"
BACKENDS = [b.strip() for b in os.environ.get("BACKENDS", "").split(",") if b.strip()]

# control dispatcher strategy: "roundrobin" or "random"
DISPATCH_STRATEGY = os.environ.get("DISPATCH_STRATEGY", "roundrobin")

# file lifetime seconds (default 10 minutes)
FILE_TTL = int(os.environ.get("FILE_TTL_SECONDS", 600))

# concurrent fragment downloads for yt-dlp
CONCURRENT_FRAGMENTS = int(os.environ.get("CONCURRENT_FRAGMENTS", 10))

# ============== APP ==============
app = Flask(__name__)

# ---------- HTML UI (dark) ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Mini-Y2mate - Nam2006©</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-black text-gray-100 min-h-screen flex items-center justify-center p-6">
  <div class="w-full max-w-2xl bg-gray-900/90 backdrop-blur-sm rounded-2xl shadow-2xl p-6 border border-gray-800">
    <h1 class="text-2xl font-bold mb-4 flex items-center gap-3">
      <svg class="w-6 h-6 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.196-3L10 9v6z"/><path d="M21 7.5a2.5 2.5 0 00-2.5-2.5H5.5A2.5 2.5 0 003 7.5v9A2.5 2.5 0 005.5 19h13a2.5 2.5 0 002.5-2.5v-9z"/></svg>
      Mini-Y2mate - <span class="text-emerald-400">Nam2006©</span>
    </h1>

    <div class="space-y-4">
      <div class="flex gap-2">
        <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="quality" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
          <option value="1440p">1440p</option>
          <option value="2160p">2160p (4K)</option>
        </select>
        <button id="btnDownload" class="rounded-xl px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-black font-semibold">Download</button>
      </div>

      <div id="status" class="text-sm text-gray-300"></div>

      <div id="linkbox" class="hidden mt-2">
        <a id="dlink" class="text-emerald-400 font-semibold hover:underline" href="#">Tải xuống tại đây</a>
      </div>

      <div class="mt-3 text-xs text-gray-500">
        Files kept in server for <span class="font-medium">10 minutes</span>.
      </div>
    </div>
  </div>
</body>

<script>
const btnDownload = document.getElementById('btnDownload');
const urlInput = document.getElementById('url');
const qualitySelect = document.getElementById('quality');
const status = document.getElementById('status');
const linkbox = document.getElementById('linkbox');
const dlink = document.getElementById('dlink');

btnDownload.onclick = async () => {
  const url = urlInput.value.trim();
  const quality = qualitySelect.value;
  if (!url) return alert('Paste URL đi bro');
  status.textContent = 'Đang xử lý...';
  linkbox.classList.add('hidden');
  try {
    const fd = new FormData();
    fd.append('url', url);
    fd.append('quality', quality);
    const res = await fetch('/download', { method: 'POST', body: fd });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || 'Download fail');
    }
    const data = await res.json();
    if (data.file) {
      dlink.href = data.file;
      dlink.textContent = 'Link tải: ' + data.filename;
      linkbox.classList.remove('hidden');
      status.textContent = 'Xong ✅ (file sẽ tự xóa sau 10 phút)';
    } else {
      throw new Error('No file returned');
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
  }
};
</script>
</html>
"""

# ============== Helpers ==============
def sanitize_title(t: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", t).strip()

# simple round-robin index
_rr_lock = threading.Lock()
_rr_index = 0


def choose_backend() -> Optional[str]:
    global _rr_index
    if not BACKENDS:
        return None
    if DISPATCH_STRATEGY == "random":
        return random.choice(BACKENDS)
    # round robin
    with _rr_lock:
        b = BACKENDS[_rr_index % len(BACKENDS)]
        _rr_index += 1
        return b

# ============== Cleaner Thread ==============
def background_cleaner():
    while True:
        now = time.time()
        for p in list(TMP_DIR.iterdir()):
            try:
                if p.is_file() and now - p.stat().st_mtime > FILE_TTL:
                    p.unlink()
            except Exception:
                pass
        time.sleep(30)

threading.Thread(target=background_cleaner, daemon=True).start()

# ============== Core local download ==============
def local_download(url: str, quality: str) -> Tuple[bool, str, Optional[str]]:
    """
    Returns (success, message_or_error, filename_or_none)
    """
    # format mapping (full quality merge)
    format_map = {
        "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
        "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    }
    fmt = format_map.get(quality, "bestvideo+bestaudio/best")

    try:
        # get info to build safe filename + id
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video")
            vid_id = info.get("id", "") or ""
        safe_title = sanitize_title(title)
        final_file = TMP_DIR / f"{safe_title}_{vid_id}_{quality}.mp4"

        # if exists -> return
        if final_file.exists():
            return True, "exists", final_file.name

        # prepare ydl opts
        outtmpl = str(TMP_DIR / f"{safe_title}_{vid_id}_{quality}.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
            "http_chunk_size": 10485760,  # 10MB
            # speed up merge: copy streams
            "postprocessor_args": ["-c", "copy"],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if final_file.exists():
            return True, "downloaded", final_file.name
        else:
            return False, "file not found after download", None

    except Exception as e:
        return False, str(e), None

# ============== Routes ==============
@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


@app.route("/download", methods=["POST"])
def download():
    url = (request.form.get("url") or "").strip()
    quality = (request.form.get("quality") or "720p").strip()
    if not url:
        return "No url", 400

    # If no BACKENDS configured or BACKENDS points to self, do local download
    if not BACKENDS:
        ok, msg, fname = local_download(url, quality)
        if ok:
            return jsonify({"file": f"/file/{fname}", "filename": fname})
        else:
            return msg, 500

    # Dispatch to chosen backend (with failover)
    tried = []
    for attempt in range(len(BACKENDS)):
        backend = choose_backend()
        if backend in tried:
            continue
        tried.append(backend)
        try:
            # proxy the form data
            resp = requests.post(
                f"{backend.rstrip('/')}/download",
                data={"url": url, "quality": quality},
                timeout=300,  # allow long downloads
            )
            # if backend returns json with file link, return that directly
            if resp.status_code == 200:
                # try to parse JSON
                try:
                    return jsonify(resp.json())
                except Exception:
                    # return raw text
                    return resp.text, resp.status_code
            else:
                # try next backend
                continue
        except Exception:
            # backend failed, try next
            continue

    return "All backends failed", 502


@app.route("/file/<path:filename>", methods=["GET"])
def serve_file(filename):
    safe_path = TMP_DIR / filename
    if not safe_path.exists():
        abort(404)
    return send_file(safe_path, as_attachment=True)


# ============== Run ==============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug False for production
    app.run(host="0.0.0.0", port=port, debug=False)
