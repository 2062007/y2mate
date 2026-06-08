# app.py
import os
import time
import re
import random
import threading
import uuid
from pathlib import Path
from typing import Optional, Tuple

import requests
from flask import Flask, request, jsonify, render_template_string, send_file, abort, Response
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

# ============== Task Storage ==============
_tasks = {}  # task_id -> {
              #   'status': 'downloading'|'processing'|'completed'|'error',
              #   'video_progress': 0,
              #   'audio_progress': 0,
              #   'merge_progress': 0,
              #   'file': None,
              #   'filename': None,
              #   'error': None
              # }

# ---------- HTML UI with 3 Progress Bars ----------
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

      <!-- Progress Bars -->
      <div id="progressContainer" class="hidden space-y-3">
        <!-- Video Progress -->
        <div>
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>📹 Tải video</span>
            <span id="videoPercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="videoBar" class="bg-blue-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        
        <!-- Audio Progress -->
        <div>
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>🎵 Tải âm thanh</span>
            <span id="audioPercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="audioBar" class="bg-purple-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        
        <!-- Merge Progress -->
        <div>
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>🔄 Ghép video & âm thanh</span>
            <span id="mergePercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="mergeBar" class="bg-emerald-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        
        <div id="speedInfo" class="text-xs text-gray-500 text-center"></div>
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
  const videoBar = document.getElementById('videoBar');
  const videoPercent = document.getElementById('videoPercent');
  const audioBar = document.getElementById('audioBar');
  const audioPercent = document.getElementById('audioPercent');
  const mergeBar = document.getElementById('mergeBar');
  const mergePercent = document.getElementById('mergePercent');
  const speedInfo = document.getElementById('speedInfo');

  let eventSource = null;
  let taskId = null;

  btnDownload.onclick = async () => {
    const url = urlInput.value.trim();
    const quality = qualitySelect.value;
    const iphone = iphoneMode.checked;

    if (!url) return alert('🔗 Paste URL đi bro');

    // Reset UI
    status.textContent = '';
    linkbox.classList.add('hidden');
    progressContainer.classList.remove('hidden');
    videoBar.style.width = '0%';
    videoPercent.textContent = '0%';
    audioBar.style.width = '0%';
    audioPercent.textContent = '0%';
    mergeBar.style.width = '0%';
    mergePercent.textContent = '0%';
    speedInfo.textContent = '';
    btnDownload.disabled = true;
    btnDownload.textContent = '⏳ Đang tải...';

    if (eventSource) eventSource.close();

    try {
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
      taskId = data.task_id;

      // Connect to SSE
      eventSource = new EventSource(`/progress/${taskId}`);
      eventSource.onmessage = (e) => {
        const progress = JSON.parse(e.data);
        
        videoBar.style.width = progress.video_progress + '%';
        videoPercent.textContent = Math.round(progress.video_progress) + '%';
        audioBar.style.width = progress.audio_progress + '%';
        audioPercent.textContent = Math.round(progress.audio_progress) + '%';
        mergeBar.style.width = progress.merge_progress + '%';
        mergePercent.textContent = Math.round(progress.merge_progress) + '%';
        
        if (progress.speed) speedInfo.textContent = '⚡ ' + progress.speed;
        
        if (progress.status === 'completed') {
          eventSource.close();
          dlink.href = progress.file;
          dlink.textContent = '📥 ' + progress.filename;
          linkbox.classList.remove('hidden');
          status.textContent = '✅ Thành công! File tự xóa sau 10 phút';
          btnDownload.disabled = false;
          btnDownload.textContent = '⬇️ Tải xuống';
          setTimeout(() => progressContainer.classList.add('hidden'), 3000);
        } else if (progress.status === 'error') {
          eventSource.close();
          throw new Error(progress.error);
        }
      };
      
      eventSource.onerror = () => {
        eventSource.close();
      };
      
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
        
    def __call__(self, d):
        if d['status'] == 'downloading':
            # Phân biệt video vs audio qua filename hoặc info_dict
            filename = d.get('filename', '')
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total) * 100 if total > 0 else 0
            
            # Tốc độ
            speed = d.get('speed', 0)
            speed_str = ''
            if speed:
                if speed > 1024*1024:
                    speed_str = f'{speed/(1024*1024):.1f} MB/s'
                elif speed > 1024:
                    speed_str = f'{speed/1024:.1f} KB/s'
                else:
                    speed_str = f'{speed:.0f} B/s'
            
            # Phân biệt video hay audio (thường audio có fxxx hoặc .m4a/.webm)
            if 'audio' in filename.lower() or filename.endswith(('.m4a', '.webm', '.m4v')):
                _tasks[self.task_id]['audio_progress'] = percent
            else:
                _tasks[self.task_id]['video_progress'] = percent
                _tasks[self.task_id]['speed'] = speed_str
                
        elif d['status'] == 'finished':
            # Một phần đã tải xong
            filename = d.get('filename', '')
            if 'audio' in filename.lower() or filename.endswith(('.m4a', '.webm', '.m4v')):
                _tasks[self.task_id]['audio_progress'] = 100
            else:
                _tasks[self.task_id]['video_progress'] = 100
                
        elif d['status'] == 'processing' and 'merge' in str(d.get('info_dict', {})):
            # Đang merge
            _tasks[self.task_id]['merge_progress'] = d.get('progress', 0) * 100

# ============== Core local download (async) ==============
def download_video_task(task_id: str, url: str, quality: str, iphone_compatible: bool):
    """Chạy trong thread riêng"""
    try:
        format_map = {
            "360p": ("bestvideo[height<=360]", "bestaudio"),
            "720p": ("bestvideo[height<=720]", "bestaudio"),
            "1080p": ("bestvideo[height<=1080]", "bestaudio"),
            "1440p": ("bestvideo[height<=1440]", "bestaudio"),
            "2160p": ("bestvideo[height<=2160]", "bestaudio"),
        }
        
        video_fmt, audio_fmt = format_map.get(quality, ("bestvideo", "bestaudio"))
        
        if iphone_compatible:
            video_fmt = f"{video_fmt}[vcodec^=avc1]"
            audio_fmt = f"{audio_fmt}[acodec^=mp4a]"
            fmt = f"{video_fmt}+{audio_fmt}/best[ext=mp4][vcodec^=avc1]"
        else:
            fmt = f"{video_fmt}+{audio_fmt}/best"
        
        # Lấy thông tin video
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video")
            vid_id = info.get("id", "") or ""
        
        safe_title = sanitize_title(title)
        final_file = TMP_DIR / f"{safe_title}_{vid_id}_{quality}{'_iphone' if iphone_compatible else ''}.mp4"
        
        if final_file.exists():
            _tasks[task_id]['status'] = 'completed'
            _tasks[task_id]['file'] = f"/file/{final_file.name}"
            _tasks[task_id]['filename'] = final_file.name
            _tasks[task_id]['merge_progress'] = 100
            return
        
        outtmpl = str(TMP_DIR / f"{safe_title}_{vid_id}_{quality}{'_iphone' if iphone_compatible else ''}_%(ext)s.%(ext)s")
        
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
            "http_chunk_size": 10485760,
            "progress_hooks": [ProgressHook(task_id)],
        }
        
        _tasks[task_id]['status'] = 'downloading'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Tìm file đã tải
        downloaded_files = list(TMP_DIR.glob(f"{safe_title}_{vid_id}_{quality}{'_iphone' if iphone_compatible else ''}_*"))
        
        # File cuối cùng sau merge
        final_path = None
        for f in downloaded_files:
            if f.suffix == '.mp4' and not f.stem.endswith('.fmp4'):
                final_path = f
                break
        
        if final_path and final_path.exists():
            # Rename về tên đẹp
            final_path.rename(final_file)
            _tasks[task_id]['status'] = 'completed'
            _tasks[task_id]['file'] = f"/file/{final_file.name}"
            _tasks[task_id]['filename'] = final_file.name
            _tasks[task_id]['video_progress'] = 100
            _tasks[task_id]['audio_progress'] = 100
            _tasks[task_id]['merge_progress'] = 100
        else:
            _tasks[task_id]['status'] = 'error'
            _tasks[task_id]['error'] = "File not found after download"
            
    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

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
    
    # Tạo task ID
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        'status': 'pending',
        'video_progress': 0,
        'audio_progress': 0,
        'merge_progress': 0,
        'speed': '',
        'file': None,
        'filename': None,
        'error': None
    }
    
    # Chạy task trong thread riêng
    thread = threading.Thread(target=download_video_task, args=(task_id, url, quality, iphone_compatible))
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route("/progress/<task_id>")
def progress_stream(task_id):
    """SSE endpoint cho progress"""
    def generate():
        last_progress = {}
        while True:
            task = _tasks.get(task_id)
            if not task:
                break
            
            progress_data = {
                'status': task.get('status', 'pending'),
                'video_progress': task.get('video_progress', 0),
                'audio_progress': task.get('audio_progress', 0),
                'merge_progress': task.get('merge_progress', 0),
                'speed': task.get('speed', ''),
            }
            
            if task.get('status') == 'completed':
                progress_data['file'] = task.get('file')
                progress_data['filename'] = task.get('filename')
                yield f"data: {jsonify(progress_data).get_data(as_text=True)}\n\n"
                break
            elif task.get('status') == 'error':
                progress_data['error'] = task.get('error')
                yield f"data: {jsonify(progress_data).get_data(as_text=True)}\n\n"
                break
            
            # Chỉ gửi khi có thay đổi
            if progress_data != last_progress:
                yield f"data: {jsonify(progress_data).get_data(as_text=True)}\n\n"
                last_progress = progress_data.copy()
            
            time.sleep(0.5)
    
    return Response(generate(), mimetype="text/event-stream")

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
