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
BASE_TMP = Path(os.environ.get("TMPDIR", "/tmp"))
TMP_DIR = BASE_TMP / "mini_y2mate_tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

BACKENDS = [b.strip() for b in os.environ.get("BACKENDS", "").split(",") if b.strip()]
DISPATCH_STRATEGY = os.environ.get("DISPATCH_STRATEGY", "roundrobin")
FILE_TTL = int(os.environ.get("FILE_TTL_SECONDS", 600))
CONCURRENT_FRAGMENTS = int(os.environ.get("CONCURRENT_FRAGMENTS", 10))

# ============== APP ==============
app = Flask(__name__)

# ---------- HTML UI (Dark Mode + Progress) ----------
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
      <div class="flex gap-2 flex-wrap">
        <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="quality" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
          <option value="1440p">1440p</option>
          <option value="2160p">2160p (4K)</option>
        </select>
      </div>

      <!-- iPhone Compatible Toggle -->
      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          <span class="text-sm font-medium">iPhone Compatible (H.264 + AAC)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="iphoneMode" class="sr-only peer" checked>
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <!-- Progress Bar -->
      <div id="progressContainer" class="hidden">
        <div class="flex justify-between text-xs text-gray-400 mb-1">
          <span id="progressStatus">Đang chuẩn bị...</span>
          <span id="progressPercent">0%</span>
        </div>
        <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
          <div id="progressBar" class="bg-emerald-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <div id="speedInfo" class="text-xs text-gray-500 mt-1 text-center"></div>
      </div>

      <button id="btnDownload" class="w-full rounded-xl py-3 bg-emerald-500 hover:bg-emerald-600 text-black font-semibold transition-all">
        ⬇️ Tải xuống
      </button>

      <div id="status" class="text-sm text-gray-300 text-center"></div>

      <div id="linkbox" class="hidden mt-2">
        <div class="bg-gray-800 rounded-xl p-3">
          <a id="dlink" class="text-emerald-400 font-semibold hover:underline break-all" href="#">📥 Tải xuống tại đây</a>
        </div>
      </div>

      <div class="mt-3 text-xs text-gray-500 text-center">
        ⏱️ File được giữ trong <span class="font-medium">10 phút</span> | 
        📱 Bật "iPhone Compatible" để tương thích tuyệt đối với iOS
      </div>
    </div>
  </div>

  <script>
  const btnDownload = document.getElementById('btnDownload');
  const urlInput = document.getElementById('url');
  const qualitySelect = document.getElementById('quality');
  const iphoneMode = document.getElementById('iphoneMode');
  const status = document.getElementById('status');
  const linkbox = document.getElementById('linkbox');
  const dlink = document.getElementById('dlink');
  const progressContainer = document.getElementById('progressContainer');
  const progressBar = document.getElementById('progressBar');
  const progressPercent = document.getElementById('progressPercent');
  const progressStatus = document.getElementById('progressStatus');
  const speedInfo = document.getElementById('speedInfo');

  let eventSource = null;

  btnDownload.onclick = async () => {
    const url = urlInput.value.trim();
    const quality = qualitySelect.value;
    const iphone = iphoneMode.checked;

    if (!url) return alert('🔗 Paste URL đi bro');

    // Reset UI
    status.textContent = '';
    linkbox.classList.add('hidden');
    progressContainer.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressPercent.textContent = '0%';
    progressStatus.textContent = 'Đang kết nối...';
    speedInfo.textContent = '';
    btnDownload.disabled = true;
    btnDownload.textContent = '⏳ Đang tải...';

    // Close existing EventSource
    if (eventSource) eventSource.close();

    try {
      // Start download with progress tracking
      const response = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, quality, iphone_compatible: iphone })
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }

      const data = await response.json();

      if (data.progress_url) {
        // Connect to SSE for progress updates
        eventSource = new EventSource(data.progress_url);
        eventSource.onmessage = (e) => {
          const progress = JSON.parse(e.data);
          const percent = progress.percent || 0;
          progressBar.style.width = percent + '%';
          progressPercent.textContent = Math.round(percent) + '%';
          progressStatus.textContent = progress.status || 'Đang tải...';
          if (progress.speed) speedInfo.textContent = '⚡ ' + progress.speed;
        };
        eventSource.onerror = () => eventSource.close();

        // Poll for completion
        const checkInterval = setInterval(async () => {
          const checkRes = await fetch(`/status/${data.task_id}`);
          if (checkRes.ok) {
            const result = await checkRes.json();
            if (result.completed && result.file) {
              clearInterval(checkInterval);
              eventSource.close();
              dlink.href = result.file;
              dlink.textContent = '📥 ' + result.filename;
              linkbox.classList.remove('hidden');
              status.textContent = '✅ Thành công! File tự xóa sau 10 phút';
              progressStatus.textContent = 'Hoàn tất!';
              btnDownload.disabled = false;
              btnDownload.textContent = '⬇️ Tải xuống';
              setTimeout(() => progressContainer.classList.add('hidden'), 2000);
            } else if (result.error) {
              throw new Error(result.error);
            }
          }
        }, 1000);
      } else if (data.file) {
        dlink.href = data.file;
        dlink.textContent = '📥 ' + data.filename;
        linkbox.classList.remove('hidden');
        status.textContent = '✅ Thành công!';
        progressContainer.classList.add('hidden');
        btnDownload.disabled = false;
        btnDownload.textContent = '⬇️ Tải xuống';
      }
    } catch (e) {
      status.textContent = '❌ Lỗi: ' + e.message;
      progressContainer.classList.add('hidden');
      btnDownload.disabled = false;
      btnDownload.textContent = '⬇️ Tải xuống';
      if (eventSource) eventSource.close();
    }
  };
  </script>
</body>
</html>
"""

# ============== Helpers ==============
def sanitize_title(t: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", t).strip()

_rr_lock = threading.Lock()
_rr_index = 0
_tasks = {}  # task_id -> {'completed': bool, 'file': str, 'error': str, 'progress': dict}

def choose_backend() -> Optional[str]:
    global _rr_index
    if not BACKENDS:
        return None
    if DISPATCH_STRATEGY == "random":
        return random.choice(BACKENDS)
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

# ============== Progress Hook for yt-dlp ==============
class ProgressHook:
    def __init__(self, task_id):
        self.task_id = task_id
        self.last_percent = 0

    def __call__(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total) * 100 if total > 0 else 0
            
            speed = d.get('speed', 0)
            speed_str = ''
            if speed:
                if speed > 1024*1024:
                    speed_str = f'{speed/(1024*1024):.1f} MB/s'
                elif speed > 1024:
                    speed_str = f'{speed/1024:.1f} KB/s'
                else:
                    speed_str = f'{speed:.0f} B/s'
            
            _tasks[self.task_id]['progress'] = {
                'percent': percent,
                'status': f'Đang tải... {percent:.1f}%',
                'speed': speed_str
            }
        elif d['status'] == 'finished':
            _tasks[self.task_id]['progress'] = {
                'percent': 100,
                'status': 'Đang xử lý video...',
                'speed': ''
            }

# ============== Core local download ==============
def local_download(url: str, quality: str, iphone_compatible: bool = True) -> Tuple[bool, str, Optional[str]]:
    format_map = {
        "360p": ("bestvideo[height<=360]", "bestaudio"),
        "720p": ("bestvideo[height<=720]", "bestaudio"),
        "1080p": ("bestvideo[height<=1080]", "bestaudio"),
        "1440p": ("bestvideo[height<=1440]", "bestaudio"),
        "2160p": ("bestvideo[height<=2160]", "bestaudio"),
    }
    
    video_fmt, audio_fmt = format_map.get(quality, ("bestvideo", "bestaudio"))
    
    if iphone_compatible:
        # iPhone: H.264 video + AAC audio in MP4 container
        video_fmt = f"{video_fmt}[vcodec^=avc1]"
        audio_fmt = f"{audio_fmt}[acodec^=mp4a]"
        fmt = f"{video_fmt}+{audio_fmt}/best[ext=mp4][vcodec^=avc1]"
    else:
        fmt = f"{video_fmt}+{audio_fmt}/best"

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video")
            vid_id = info.get("id", "") or ""
        safe_title = sanitize_title(title)
        final_file = TMP_DIR / f"{safe_title}_{vid_id}_{quality}{'_iphone' if iphone_compatible else ''}.mp4"

        if final_file.exists():
            return True, "exists", final_file.name

        outtmpl = str(TMP_DIR / f"{safe_title}_{vid_id}_{quality}{'_iphone' if iphone_compatible else ''}.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
            "http_chunk_size": 10485760,
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
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    quality = (data.get("quality") or "720p").strip()
    iphone_compatible = data.get("iphone_compatible", True)
    
    if not url:
        return "No url", 400

    if not BACKENDS:
        ok, msg, fname = local_download(url, quality, iphone_compatible)
        if ok:
            return jsonify({"file": f"/file/{fname}", "filename": fname})
        else:
            return msg, 500

    tried = []
    for attempt in range(len(BACKENDS)):
        backend = choose_backend()
        if backend in tried:
            continue
        tried.append(backend)
        try:
            resp = requests.post(
                f"{backend.rstrip('/')}/download",
                json={"url": url, "quality": quality, "iphone_compatible": iphone_compatible},
                timeout=300,
            )
            if resp.status_code == 200:
                try:
                    return jsonify(resp.json())
                except Exception:
                    return resp.text, resp.status_code
            else:
                continue
        except Exception:
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
    app.run(host="0.0.0.0", port=port, debug=False)
