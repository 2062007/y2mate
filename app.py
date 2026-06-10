# app.py
import os
import time
import re
import random
import threading
import uuid
import json
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import requests
from flask import Flask, request, jsonify, render_template_string, send_file, abort, Response
import yt_dlp

CURRENT_DIR = Path(__file__).parent
TMP_DIR = CURRENT_DIR / "download"
TMP_DIR.mkdir(parents=True, exist_ok=True)

print(f"📁 Thư mục lưu file tạm: {TMP_DIR}")

BACKENDS = [b.strip() for b in os.environ.get("BACKENDS", "").split(",") if b.strip()]
DISPATCH_STRATEGY = os.environ.get("DISPATCH_STRATEGY", "roundrobin")
FILE_TTL = int(os.environ.get("FILE_TTL_SECONDS", 600))
CONCURRENT_FRAGMENTS = int(os.environ.get("CONCURRENT_FRAGMENTS", 10))

app = Flask(__name__)
_tasks: Dict[str, Dict[str, Any]] = {}

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
  <div class="w-full max-w-3xl bg-gray-900/90 backdrop-blur-sm rounded-2xl shadow-2xl p-6 border border-gray-800">
    <h1 class="text-2xl font-bold mb-4 flex items-center gap-3">
      <svg class="w-6 h-6 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.196-3L10 9v6z"/><path d="M21 7.5a2.5 2.5 0 00-2.5-2.5H5.5A2.5 2.5 0 003 7.5v9A2.5 2.5 0 005.5 19h13a2.5 2.5 0 002.5-2.5v-9z"/></svg>
      Mini-Y2mate - <span class="text-emerald-400">Nam2006©</span>
    </h1>

    <div class="space-y-4">
      <div class="flex gap-2 flex-wrap">
        <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=... hoặc playlist" class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
      </div>

      <div class="flex gap-4 flex-wrap">
        <label class="inline-flex items-center gap-2"><input type="radio" name="dlType" value="video" checked> <span>🎬 Video</span></label>
        <label class="inline-flex items-center gap-2"><input type="radio" name="dlType" value="audio"> <span>🎵 Audio</span></label>
        <label class="inline-flex items-center gap-2"><input type="radio" name="dlType" value="playlist"> <span>📀 Playlist (zip)</span></label>
      </div>

      <div id="videoOptions" class="space-y-3">
        <div class="flex gap-2 flex-wrap">
          <select id="quality" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700">
            <option value="360p">360p</option>
            <option value="720p" selected>720p</option>
            <option value="1080p">1080p</option>
            <option value="1440p">1440p</option>
            <option value="2160p">2160p (4K)</option>
          </select>
          <select id="videoFormat" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700">
            <option value="mp4">MP4</option>
            <option value="webm">WebM</option>
            <option value="mkv">MKV</option>
          </select>
        </div>
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
      </div>

      <div id="audioOptions" class="hidden space-y-3">
        <select id="audioFormat" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700">
          <option value="mp3">MP3</option>
          <option value="m4a">M4A (AAC)</option>
          <option value="ogg">OGG</option>
          <option value="aac">AAC</option>
          <option value="flac">FLAC</option>
          <option value="wav">WAV</option>
          <option value="opus">Opus</option>
        </select>
      </div>

      <div id="progressContainer" class="hidden space-y-3">
        <div>
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span id="progressLabel">📥 Tiến độ</span>
            <span id="progressPercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="progressBar" class="bg-emerald-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        <div id="extraInfo" class="text-xs text-gray-500 text-center"></div>
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
  const radios = document.querySelectorAll('input[name="dlType"]');
  const videoOpts = document.getElementById('videoOptions');
  const audioOpts = document.getElementById('audioOptions');

  function toggleOptions() {
    const selected = document.querySelector('input[name="dlType"]:checked').value;
    if (selected === 'audio') {
      videoOpts.classList.add('hidden');
      audioOpts.classList.remove('hidden');
    } else {
      videoOpts.classList.remove('hidden');
      audioOpts.classList.add('hidden');
    }
  }
  radios.forEach(r => r.addEventListener('change', toggleOptions));
  toggleOptions();

  const btnDownload = document.getElementById('btnDownload');
  const urlInput = document.getElementById('url');
  const qualitySelect = document.getElementById('quality');
  const iphoneMode = document.getElementById('iphoneMode');
  const videoFormatSelect = document.getElementById('videoFormat');
  const audioFormatSelect = document.getElementById('audioFormat');
  const statusDiv = document.getElementById('status');
  const linkbox = document.getElementById('linkbox');
  const dlink = document.getElementById('dlink');
  const progressContainer = document.getElementById('progressContainer');
  const progressBar = document.getElementById('progressBar');
  const progressPercent = document.getElementById('progressPercent');
  const progressLabel = document.getElementById('progressLabel');
  const extraInfo = document.getElementById('extraInfo');
  const speedInfo = document.getElementById('speedInfo');

  let eventSource = null;

  btnDownload.onclick = async () => {
    const url = urlInput.value.trim();
    if (!url) return alert('🔗 Paste URL đi bro');

    const dlType = document.querySelector('input[name="dlType"]:checked').value;
    const quality = qualitySelect.value;
    const iphone = iphoneMode.checked;
    const videoFormat = videoFormatSelect.value;
    const audioFormat = audioFormatSelect.value;

    statusDiv.textContent = '';
    linkbox.classList.add('hidden');
    progressContainer.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressPercent.textContent = '0%';
    extraInfo.textContent = '';
    speedInfo.textContent = '';
    btnDownload.disabled = true;
    btnDownload.textContent = '⏳ Đang tải...';
    progressLabel.textContent = dlType === 'playlist' ? '📀 Tổng tiến độ playlist' : '📥 Tiến độ';

    if (eventSource) eventSource.close();

    try {
      const response = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          type: dlType,
          quality,
          iphone_compatible: iphone,
          video_format: videoFormat,
          audio_format: audioFormat
        })
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }

      const data = await response.json();
      const taskId = data.task_id;

      eventSource = new EventSource(`/progress/${taskId}`);
      eventSource.onmessage = (e) => {
        const prog = JSON.parse(e.data);
        
        let percent = 0;
        if (prog.type === 'playlist') {
          percent = prog.playlist_progress || 0;
          extraInfo.textContent = prog.current_item ? `📌 Đang tải: ${prog.current_item} (${prog.done_count}/${prog.total_count})` : '';
        } else {
          percent = prog.video_progress || prog.audio_progress || 0;
          if (prog.speed) speedInfo.textContent = '⚡ ' + prog.speed;
        }
        progressBar.style.width = percent + '%';
        progressPercent.textContent = Math.round(percent) + '%';
        
        if (prog.status === 'completed') {
          eventSource.close();
          dlink.href = prog.file;
          dlink.textContent = '📥 ' + prog.filename;
          linkbox.classList.remove('hidden');
          statusDiv.textContent = '✅ Thành công! File tự xóa sau 10 phút';
          btnDownload.disabled = false;
          btnDownload.textContent = '⬇️ Tải xuống';
          setTimeout(() => progressContainer.classList.add('hidden'), 3000);
        } else if (prog.status === 'error') {
          eventSource.close();
          throw new Error(prog.error);
        }
      };
      eventSource.onerror = () => eventSource.close();
    } catch (e) {
      statusDiv.textContent = '❌ Lỗi: ' + e.message;
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

def sanitize_title(t: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", t).strip()

_rr_lock = threading.Lock()
_rr_index = 0

def choose_backend() -> Optional[str]:
    if not BACKENDS:
        return None
    if DISPATCH_STRATEGY == "random":
        return random.choice(BACKENDS)
    with _rr_lock:
        b = BACKENDS[_rr_index % len(BACKENDS)]
        _rr_index += 1
        return b

def background_cleaner():
    while True:
        now = time.time()
        try:
            for p in TMP_DIR.iterdir():
                if p.is_file() and now - p.stat().st_mtime > FILE_TTL:
                    p.unlink()
                    print(f"🗑️ Đã xóa file cũ: {p.name}")
        except Exception:
            pass
        time.sleep(30)

threading.Thread(target=background_cleaner, daemon=True).start()

class ProgressHook:
    def __init__(self, task_id, is_audio=False):
        self.task_id = task_id
        self.is_audio = is_audio

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

            if self.is_audio:
                _tasks[self.task_id]['audio_progress'] = percent
            else:
                _tasks[self.task_id]['video_progress'] = percent
                _tasks[self.task_id]['speed'] = speed_str

        elif d['status'] == 'finished':
            if self.is_audio:
                _tasks[self.task_id]['audio_progress'] = 100
            else:
                _tasks[self.task_id]['video_progress'] = 100

def download_single(task_id: str, url: str, dl_type: str, quality: str, iphone: bool,
                    video_format: str, audio_format: str):
    try:
        if dl_type == 'audio':
            outtmpl = str(TMP_DIR / f"%(title)s_%(id)s.%(ext)s")
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "192",
                }],
                "progress_hooks": [ProgressHook(task_id, is_audio=True)],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = sanitize_title(info.get("title", "audio"))
                vid_id = info.get("id", "")
                final_file = TMP_DIR / f"{title}_{vid_id}.{audio_format}"
                if not final_file.exists():
                    for f in TMP_DIR.glob(f"{title}_{vid_id}*"):
                        if f.suffix == f".{audio_format}":
                            final_file = f
                            break
                _tasks[task_id]['status'] = 'completed'
                _tasks[task_id]['file'] = f"/file/{final_file.name}"
                _tasks[task_id]['filename'] = final_file.name
                _tasks[task_id]['audio_progress'] = 100
        else:
            format_map = {
                "360p": ("bestvideo[height<=360]", "bestaudio"),
                "720p": ("bestvideo[height<=720]", "bestaudio"),
                "1080p": ("bestvideo[height<=1080]", "bestaudio"),
                "1440p": ("bestvideo[height<=1440]", "bestaudio"),
                "2160p": ("bestvideo[height<=2160]", "bestaudio"),
            }
            video_fmt, audio_fmt = format_map.get(quality, ("bestvideo", "bestaudio"))

            if iphone:
                video_fmt = f"{video_fmt}[vcodec^=avc1]"
                audio_fmt = f"{audio_fmt}[acodec^=mp4a]"
                fmt = f"{video_fmt}+{audio_fmt}/best[ext=mp4][vcodec^=avc1]"
                merge_fmt = "mp4"
            else:
                merge_fmt = video_format if video_format in ['mp4', 'webm', 'mkv'] else 'mp4'
                fmt = f"{video_fmt}+{audio_fmt}/best[ext={merge_fmt}]"

            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = sanitize_title(info.get("title", "video"))
                vid_id = info.get("id", "")

            outtmpl = str(TMP_DIR / f"{title}_{vid_id}_{quality}_{iphone}_video.%(ext)s")
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": fmt,
                "merge_output_format": merge_fmt,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
                "progress_hooks": [ProgressHook(task_id, is_audio=False)],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            pattern = f"{title}_{vid_id}_{quality}_{iphone}_video*.{merge_fmt}"
            matches = list(TMP_DIR.glob(pattern))
            if matches:
                final_file = matches[0]
            else:
                matches = list(TMP_DIR.glob(f"{title}_{vid_id}*.{merge_fmt}"))
                final_file = matches[0] if matches else None

            if final_file and final_file.exists():
                _tasks[task_id]['status'] = 'completed'
                _tasks[task_id]['file'] = f"/file/{final_file.name}"
                _tasks[task_id]['filename'] = final_file.name
                _tasks[task_id]['video_progress'] = 100
            else:
                raise Exception("Không tìm thấy file sau khi tải")
    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

def download_playlist(task_id: str, url: str, dl_type: str, quality: str, iphone: bool,
                      video_format: str, audio_format: str):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            playlist_info = ydl.extract_info(url, download=False)
            if 'entries' not in playlist_info:
                raise Exception("URL không phải là playlist hoặc không có video nào")
            entries = playlist_info['entries']
            total = len(entries)
            if total == 0:
                raise Exception("Playlist rỗng")

        playlist_title = sanitize_title(playlist_info.get('title', 'playlist'))
        playlist_id = playlist_info.get('id', str(uuid.uuid4())[:8])
        playlist_dir = TMP_DIR / f"playlist_{playlist_id}"
        playlist_dir.mkdir(exist_ok=True)

        _tasks[task_id]['total_count'] = total
        _tasks[task_id]['done_count'] = 0
        _tasks[task_id]['playlist_progress'] = 0
        _tasks[task_id]['type'] = 'playlist'

        downloaded_files = []

        for idx, entry in enumerate(entries, start=1):
            video_url = entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry['id']}"
            video_title = sanitize_title(entry.get('title', f'video_{idx}'))
            _tasks[task_id]['current_item'] = f"{video_title} ({idx}/{total})"

            if dl_type == 'audio':
                outtmpl = str(playlist_dir / f"{video_title}_%(id)s.%(ext)s")
                ydl_opts = {
                    "outtmpl": outtmpl,
                    "format": "bestaudio/best",
                    "quiet": True,
                    "no_warnings": True,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": "192",
                    }],
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                for f in playlist_dir.glob(f"{video_title}_*.{audio_format}"):
                    downloaded_files.append(f)
                    break
            else:
                format_map = {
                    "360p": ("bestvideo[height<=360]", "bestaudio"),
                    "720p": ("bestvideo[height<=720]", "bestaudio"),
                    "1080p": ("bestvideo[height<=1080]", "bestaudio"),
                    "1440p": ("bestvideo[height<=1440]", "bestaudio"),
                    "2160p": ("bestvideo[height<=2160]", "bestaudio"),
                }
                video_fmt, audio_fmt = format_map.get(quality, ("bestvideo", "bestaudio"))

                if iphone:
                    video_fmt = f"{video_fmt}[vcodec^=avc1]"
                    audio_fmt = f"{audio_fmt}[acodec^=mp4a]"
                    fmt = f"{video_fmt}+{audio_fmt}/best[ext=mp4][vcodec^=avc1]"
                    merge_fmt = "mp4"
                else:
                    merge_fmt = video_format if video_format in ['mp4', 'webm', 'mkv'] else 'mp4'
                    fmt = f"{video_fmt}+{audio_fmt}/best[ext={merge_fmt}]"

                outtmpl = str(playlist_dir / f"{video_title}_%(id)s.%(ext)s")
                ydl_opts = {
                    "outtmpl": outtmpl,
                    "format": fmt,
                    "merge_output_format": merge_fmt,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                for f in playlist_dir.glob(f"{video_title}_*.{merge_fmt}"):
                    downloaded_files.append(f)
                    break

            _tasks[task_id]['done_count'] = idx
            progress = (idx / total) * 100
            _tasks[task_id]['playlist_progress'] = progress

        zip_name = f"{playlist_title}_{playlist_id}.zip"
        zip_path = TMP_DIR / zip_name
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for f in downloaded_files:
                zipf.write(f, arcname=f.name)

        import shutil
        shutil.rmtree(playlist_dir, ignore_errors=True)

        _tasks[task_id]['status'] = 'completed'
        _tasks[task_id]['file'] = f"/file/{zip_name}"
        _tasks[task_id]['filename'] = zip_name
        _tasks[task_id]['playlist_progress'] = 100

    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    dl_type = data.get("type", "video")
    quality = data.get("quality", "720p")
    iphone = data.get("iphone_compatible", True)
    video_format = data.get("video_format", "mp4")
    audio_format = data.get("audio_format", "mp3")

    if not url:
        return "No url", 400

    if BACKENDS:
        tried = []
        for attempt in range(len(BACKENDS)):
            backend = choose_backend()
            if backend in tried:
                continue
            tried.append(backend)
            try:
                resp = requests.post(
                    f"{backend.rstrip('/')}/download",
                    json=data,
                    timeout=300,
                )
                if resp.status_code == 200:
                    try:
                        return jsonify(resp.json())
                    except:
                        return resp.text, resp.status_code
            except Exception:
                continue
        return "All backends failed", 502

    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        'status': 'pending',
        'type': dl_type,
        'video_progress': 0,
        'audio_progress': 0,
        'playlist_progress': 0,
        'speed': '',
        'file': None,
        'filename': None,
        'error': None,
    }

    if dl_type == 'playlist':
        thread = threading.Thread(target=download_playlist, args=(
            task_id, url, dl_type, quality, iphone, video_format, audio_format
        ))
    else:
        thread = threading.Thread(target=download_single, args=(
            task_id, url, dl_type, quality, iphone, video_format, audio_format
        ))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id})

@app.route("/progress/<task_id>")
def progress_stream(task_id):
    def generate():
        last = {}
        while True:
            task = _tasks.get(task_id)
            if not task:
                break
            prog = {
                'status': task.get('status', 'pending'),
                'type': task.get('type', 'video'),
                'video_progress': task.get('video_progress', 0),
                'audio_progress': task.get('audio_progress', 0),
                'playlist_progress': task.get('playlist_progress', 0),
                'speed': task.get('speed', ''),
                'current_item': task.get('current_item', ''),
                'done_count': task.get('done_count', 0),
                'total_count': task.get('total_count', 0),
            }
            if task.get('status') == 'completed':
                prog['file'] = task.get('file')
                prog['filename'] = task.get('filename')
                yield f"data: {json.dumps(prog)}\n\n"
                break
            elif task.get('status') == 'error':
                prog['error'] = task.get('error')
                yield f"data: {json.dumps(prog)}\n\n"
                break
            if prog != last:
                yield f"data: {json.dumps(prog)}\n\n"
                last = prog.copy()
            time.sleep(0.5)
    return Response(generate(), mimetype="text/event-stream")

@app.route("/file/<path:filename>", methods=["GET"])
def serve_file(filename):
    safe_path = TMP_DIR / filename
    if not safe_path.exists():
        abort(404)
    return send_file(safe_path, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server chạy tại: http://localhost:{port}")
    print(f"📁 File tải về sẽ lưu tạm trong: {TMP_DIR}")
    print(f"⏱️ File tự động xóa sau: {FILE_TTL} giây")
    app.run(host="0.0.0.0", port=port, debug=False)
