import os
import time
import re
import random
import threading
import uuid
import json
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from flask import Flask, request, jsonify, render_template_string, send_file, abort, Response
import yt_dlp

# ============== CONFIG ==============
CURRENT_DIR = Path(__file__).parent
TMP_DIR = CURRENT_DIR / "download"
TMP_DIR.mkdir(parents=True, exist_ok=True)

print(f"📁 Thư mục lưu file tạm: {TMP_DIR}")

BACKENDS = [b.strip() for b in os.environ.get("BACKENDS", "").split(",") if b.strip()]
DISPATCH_STRATEGY = os.environ.get("DISPATCH_STRATEGY", "roundrobin")
FILE_TTL = int(os.environ.get("FILE_TTL_SECONDS", 600))
CONCURRENT_FRAGMENTS = int(os.environ.get("CONCURRENT_FRAGMENTS", 10))

# ============== APP ==============
app = Flask(__name__)

# ============== Task Storage ==============
_tasks: Dict[str, Dict[str, Any]] = {}

# ============== HTML UI ==============
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Mini-Y2mate Pro - Nam2006©</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-black text-gray-100 min-h-screen flex items-center justify-center p-6">
  <div class="w-full max-w-2xl bg-gray-900/90 backdrop-blur-sm rounded-2xl shadow-2xl p-6 border border-gray-800">
    <h1 class="text-2xl font-bold mb-4 flex items-center gap-3">
      <svg class="w-6 h-6 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.196-3L10 9v6z"/><path d="M21 7.5a2.5 2.5 0 00-2.5-2.5H5.5A2.5 2.5 0 003 7.5v9A2.5 2.5 0 005.5 19h13a2.5 2.5 0 002.5-2.5v-9z"/></svg>
      Mini-Y2mate Pro - <span class="text-emerald-400">Nam2006©</span>
    </h1>

    <div class="space-y-4">
      <div class="flex gap-2 flex-wrap">
        <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=... hoặc playlist" class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="quality" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
          <option value="1440p">1440p</option>
          <option value="2160p">2160p (4K)</option>
        </select>
      </div>

      <!-- Loại tải: Video / Audio -->
      <div class="flex gap-4 bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadType" value="video" checked class="accent-emerald-500"> 
          <span>🎬 Video</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadType" value="audio" class="accent-purple-500"> 
          <span>🎵 Audio</span>
        </label>
      </div>

      <!-- Tuỳ chọn Audio (ẩn/hiện bằng JS) -->
      <div id="audioOptions" class="hidden space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng:</span>
          <select id="audioFormat" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp3">MP3</option>
            <option value="m4a">M4A</option>
            <option value="webm">WEBM</option>
            <option value="aac">AAC</option>
            <option value="flac">FLAC</option>
            <option value="ogg">OGG</option>
          </select>
          <span class="text-sm font-medium ml-2">Bitrate:</span>
          <select id="audioBitrate" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="64">64 kbps</option>
            <option value="128" selected>128 kbps</option>
            <option value="192">192 kbps</option>
            <option value="256">256 kbps</option>
            <option value="320">320 kbps</option>
          </select>
        </div>
      </div>

      <!-- Tuỳ chọn Playlist -->
      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M4 6h16v2H4V6zm2 4h12v2H6v-2zm14 4H4v2h16v-2z"/></svg>
          <span class="text-sm font-medium">Tải toàn bộ playlist (nếu URL là playlist)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="playlistMode" class="sr-only peer">
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <!-- iPhone Compatible (chỉ hiển thị khi chọn Video) -->
      <div id="iphoneOption" class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          <span class="text-sm font-medium">iPhone Compatible (H.264 + AAC)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="iphoneMode" class="sr-only peer" checked>
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <!-- Khu vực 3 thanh progress (cho single video) -->
      <div id="multiProgressContainer" class="hidden space-y-3">
        <div id="videoRow">
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>📹 Tải video</span>
            <span id="videoPercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="videoBar" class="bg-blue-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        <div id="audioRow">
          <div class="flex justify-between text-xs text-gray-400 mb-1">
            <span>🎵 Tải âm thanh</span>
            <span id="audioPercent">0%</span>
          </div>
          <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div id="audioBar" class="bg-purple-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
        <div id="mergeRow">
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

      <!-- Thanh progress dành cho playlist (chỉ 1 thanh) -->
      <div id="playlistProgressContainer" class="hidden space-y-2">
        <div class="flex justify-between text-xs text-gray-400 mb-1">
          <span>📀 Đang xử lý playlist</span>
          <span id="playlistPercent">0%</span>
        </div>
        <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
          <div id="playlistBar" class="bg-emerald-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <div id="playlistDetail" class="text-xs text-gray-500 text-center"></div>
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
        📱 Hỗ trợ tải audio nhiều định dạng | 🎵 Tải playlist nén zip
      </div>
    </div>
  </div>

  <script>
  // DOM elements
  const btnDownload = document.getElementById('btnDownload');
  const urlInput = document.getElementById('url');
  const qualitySelect = document.getElementById('quality');
  const iphoneMode = document.getElementById('iphoneMode');
  const downloadTypeRadios = document.querySelectorAll('input[name="downloadType"]');
  const audioOptionsDiv = document.getElementById('audioOptions');
  const iphoneOptionDiv = document.getElementById('iphoneOption');
  const playlistCheckbox = document.getElementById('playlistMode');
  const multiProgress = document.getElementById('multiProgressContainer');
  const playlistProgress = document.getElementById('playlistProgressContainer');
  const statusDiv = document.getElementById('status');
  const linkbox = document.getElementById('linkbox');
  const dlink = document.getElementById('dlink');
  // Các thanh video/audio/merge
  const videoBar = document.getElementById('videoBar');
  const videoPercent = document.getElementById('videoPercent');
  const audioBar = document.getElementById('audioBar');
  const audioPercent = document.getElementById('audioPercent');
  const mergeBar = document.getElementById('mergeBar');
  const mergePercent = document.getElementById('mergePercent');
  const speedInfo = document.getElementById('speedInfo');
  // Playlist
  const playlistBar = document.getElementById('playlistBar');
  const playlistPercentSpan = document.getElementById('playlistPercent');
  const playlistDetail = document.getElementById('playlistDetail');

  let eventSource = null;

  // Hiển thị/ẩn tuỳ chọn theo loại tải
  function toggleOptions() {
    const isAudio = document.querySelector('input[name="downloadType"]:checked').value === 'audio';
    audioOptionsDiv.classList.toggle('hidden', !isAudio);
    iphoneOptionDiv.classList.toggle('hidden', isAudio);
  }
  downloadTypeRadios.forEach(radio => radio.addEventListener('change', toggleOptions));
  toggleOptions();

  btnDownload.onclick = async () => {
    const url = urlInput.value.trim();
    const quality = qualitySelect.value;
    const iphone = iphoneMode.checked;
    const downloadType = document.querySelector('input[name="downloadType"]:checked').value;
    const audioFormat = document.getElementById('audioFormat').value;
    const audioBitrate = document.getElementById('audioBitrate').value;
    const playlistMode = playlistCheckbox.checked;

    if (!url) return alert('🔗 Nhập URL đi bro');

    // Reset UI
    statusDiv.textContent = '';
    linkbox.classList.add('hidden');
    multiProgress.classList.add('hidden');
    playlistProgress.classList.add('hidden');
    btnDownload.disabled = true;
    btnDownload.textContent = '⏳ Đang tải...';

    if (eventSource) eventSource.close();

    try {
      const response = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          quality,
          iphone_compatible: iphone,
          download_type: downloadType,
          audio_format: audioFormat,
          audio_bitrate: parseInt(audioBitrate),
          playlist_mode: playlistMode
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
        
        if (prog.type === 'single') {
          // Chế độ video/audio đơn
          multiProgress.classList.remove('hidden');
          playlistProgress.classList.add('hidden');
          
          // Ẩn thanh video nếu là audio
          const videoRow = document.getElementById('videoRow');
          if (prog.is_audio) {
            videoRow.style.display = 'none';
          } else {
            videoRow.style.display = 'block';
          }
          
          videoBar.style.width = prog.video_progress + '%';
          videoPercent.textContent = Math.round(prog.video_progress) + '%';
          audioBar.style.width = prog.audio_progress + '%';
          audioPercent.textContent = Math.round(prog.audio_progress) + '%';
          mergeBar.style.width = prog.merge_progress + '%';
          mergePercent.textContent = Math.round(prog.merge_progress) + '%';
          if (prog.speed) speedInfo.textContent = '⚡ ' + prog.speed;
          
          if (prog.status === 'completed') {
            eventSource.close();
            dlink.href = prog.file;
            dlink.textContent = '📥 ' + prog.filename;
            linkbox.classList.remove('hidden');
            statusDiv.textContent = '✅ Thành công! File tự xóa sau 10 phút';
            btnDownload.disabled = false;
            btnDownload.textContent = '⬇️ Tải xuống';
            setTimeout(() => multiProgress.classList.add('hidden'), 3000);
          } else if (prog.status === 'error') {
            eventSource.close();
            throw new Error(prog.error);
          }
        } 
        else if (prog.type === 'playlist') {
          multiProgress.classList.add('hidden');
          playlistProgress.classList.remove('hidden');
          const percent = prog.overall_progress || 0;
          playlistBar.style.width = percent + '%';
          playlistPercentSpan.textContent = Math.round(percent) + '%';
          if (prog.detail) playlistDetail.textContent = prog.detail;
          
          if (prog.status === 'completed') {
            eventSource.close();
            dlink.href = prog.file;
            dlink.textContent = '📥 ' + prog.filename;
            linkbox.classList.remove('hidden');
            statusDiv.textContent = '✅ Playlist đã được nén zip!';
            btnDownload.disabled = false;
            btnDownload.textContent = '⬇️ Tải xuống';
            setTimeout(() => playlistProgress.classList.add('hidden'), 3000);
          } else if (prog.status === 'error') {
            eventSource.close();
            throw new Error(prog.error);
          }
        }
      };
      
      eventSource.onerror = () => eventSource.close();
      
    } catch (e) {
      statusDiv.textContent = '❌ Lỗi: ' + e.message;
      multiProgress.classList.add('hidden');
      playlistProgress.classList.add('hidden');
      btnDownload.disabled = false;
      btnDownload.textContent = '⬇️ Tải xuống';
      if (eventSource) eventSource.close();
    }
  };
  </script>
</body>
</html>
"""

# ============== Helper Functions ==============
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

def background_cleaner():
    while True:
        now = time.time()
        try:
            for p in list(TMP_DIR.iterdir()):
                if p.is_file() and now - p.stat().st_mtime > FILE_TTL:
                    p.unlink()
                    print(f"🗑️ Xóa: {p.name}")
        except Exception:
            pass
        time.sleep(30)

threading.Thread(target=background_cleaner, daemon=True).start()

# ============== Progress Hooks ==============
class SingleProgressHook:
    def __init__(self, task_id: str, is_audio: bool = False):
        self.task_id = task_id
        self.is_audio = is_audio

    def __call__(self, d):
        task = _tasks.get(self.task_id)
        if not task:
            return
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
            # Phân biệt video hay audio dựa trên tên file hoặc format
            filename = d.get('filename', '')
            is_audio_file = any(x in filename.lower() for x in ['.m4a', '.webm', 'audio', 'f140', 'f139', 'f251'])
            if self.is_audio or is_audio_file:
                task['audio_progress'] = percent
            else:
                task['video_progress'] = percent
                task['speed'] = speed_str
        elif d['status'] == 'finished':
            task['merge_progress'] = min(100, task.get('merge_progress', 0) + 30)
        elif d['status'] == 'processing':
            if 'Merger' in str(d.get('info_dict', {})):
                task['merge_progress'] = 80
            else:
                task['merge_progress'] = min(100, task.get('merge_progress', 0) + 10)

# ============== Single Video / Audio Download ==============
def download_single(task_id: str, url: str, quality: str, iphone_compatible: bool,
                    download_type: str, audio_format: str, audio_bitrate: int):
    try:
        task = _tasks[task_id]
        task['status'] = 'downloading'
        is_audio = (download_type == 'audio')
        
        # Lấy thông tin video/playlist (chỉ 1 video)
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:  # Nếu là playlist nhưng không bật playlist_mode -> lấy video đầu
                info = info['entries'][0]
            title = info.get('title', 'video')
            vid_id = info.get('id', '')
        
        safe_title = sanitize_title(title)
        base_name = f"{safe_title}_{vid_id}"
        
        if is_audio:
            # Tải audio với định dạng mong muốn
            out_template = str(TMP_DIR / f"{base_name}_audio.%(ext)s")
            final_file = TMP_DIR / f"{base_name}_audio.{audio_format}"
            if final_file.exists():
                task['status'] = 'completed'
                task['file'] = f"/file/{final_file.name}"
                task['filename'] = final_file.name
                task['video_progress'] = 100
                task['audio_progress'] = 100
                task['merge_progress'] = 100
                return
            
            ydl_opts = {
                'outtmpl': out_template,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format,
                    'preferredquality': str(audio_bitrate),
                }],
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [SingleProgressHook(task_id, is_audio=True)],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            # File sau postprocess có đuôi đúng
            possible = TMP_DIR.glob(f"{base_name}_audio.{audio_format}")
            if possible:
                final_file = next(possible)
            else:
                raise Exception("Không tìm thấy file audio sau khi xử lý")
        else:
            # Tải video (có thể kèm merge)
            format_map = {
                "360p": "bestvideo[height<=360]+bestaudio/best",
                "720p": "bestvideo[height<=720]+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best",
                "1440p": "bestvideo[height<=1440]+bestaudio/best",
                "2160p": "bestvideo[height<=2160]+bestaudio/best",
            }
            fmt = format_map.get(quality, "bestvideo+bestaudio/best")
            if iphone_compatible:
                fmt = f"bestvideo[height<={quality[:-1]}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[ext=mp4][vcodec^=avc1]"
            
            out_template = str(TMP_DIR / f"{base_name}_{quality}.%(ext)s")
            final_file = TMP_DIR / f"{base_name}_{quality}.mp4"
            if final_file.exists():
                task['status'] = 'completed'
                task['file'] = f"/file/{final_file.name}"
                task['filename'] = final_file.name
                task['video_progress'] = 100
                task['audio_progress'] = 100
                task['merge_progress'] = 100
                return
            
            ydl_opts = {
                'outtmpl': out_template,
                'format': fmt,
                'merge_output_format': 'mp4',
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'concurrent_fragment_downloads': CONCURRENT_FRAGMENTS,
                'progress_hooks': [SingleProgressHook(task_id, is_audio=False)],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            # Kiểm tra file
            if not final_file.exists():
                candidates = list(TMP_DIR.glob(f"{base_name}_{quality}*.mp4"))
                if candidates:
                    candidates[0].rename(final_file)
                else:
                    raise Exception("File video không được tạo")
        
        task['status'] = 'completed'
        task['file'] = f"/file/{final_file.name}"
        task['filename'] = final_file.name
        task['video_progress'] = 100
        task['audio_progress'] = 100
        task['merge_progress'] = 100
        
    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

# ============== Playlist Download (zip) ==============
def download_playlist(task_id: str, url: str, quality: str, iphone_compatible: bool,
                      download_type: str, audio_format: str, audio_bitrate: int):
    try:
        task = _tasks[task_id]
        task['status'] = 'downloading'
        
        # Lấy danh sách video trong playlist
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' not in info:
                raise Exception("URL không phải là playlist hoặc không chứa video nào")
            entries = [entry for entry in info['entries'] if entry]
            total = len(entries)
            if total == 0:
                raise Exception("Playlist rỗng")
        
        task['total_items'] = total
        task['processed'] = 0
        zip_filename = f"playlist_{uuid.uuid4().hex[:8]}.zip"
        zip_path = TMP_DIR / zip_filename
        
        # Tạo file zip và thêm từng video/audio
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, entry in enumerate(entries, 1):
                video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                video_title = sanitize_title(entry.get('title', f'video_{idx}'))
                vid_id = entry.get('id', str(idx))
                
                # Cập nhật tiến độ
                task['overall_progress'] = (idx-1) / total * 100
                task['detail'] = f"Đang tải {idx}/{total}: {video_title}"
                
                # Tải từng video (gọi hàm tải single tạm thời)
                if download_type == 'audio':
                    out_template = str(TMP_DIR / f"temp_{vid_id}_audio.%(ext)s")
                    final_temp = TMP_DIR / f"temp_{vid_id}_audio.{audio_format}"
                    ydl_opts = {
                        'outtmpl': out_template,
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': audio_format,
                            'preferredquality': str(audio_bitrate),
                        }],
                        'quiet': True,
                        'no_warnings': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])
                    # Đổi tên file để thêm vào zip
                    audio_file = final_temp
                    if not audio_file.exists():
                        candidates = list(TMP_DIR.glob(f"temp_{vid_id}_audio.{audio_format}"))
                        if candidates:
                            audio_file = candidates[0]
                    arcname = f"{video_title}.{audio_format}"
                    zipf.write(audio_file, arcname)
                    audio_file.unlink()
                else:
                    # Tải video mp4
                    temp_file = TMP_DIR / f"temp_{vid_id}_{quality}.mp4"
                    fmt = f"bestvideo[height<={quality[:-1]}]+bestaudio/best" if quality != "2160p" else "bestvideo+bestaudio/best"
                    if iphone_compatible:
                        fmt = f"bestvideo[height<={quality[:-1]}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[ext=mp4]"
                    ydl_opts = {
                        'outtmpl': str(TMP_DIR / f"temp_{vid_id}_{quality}.%(ext)s"),
                        'format': fmt,
                        'merge_output_format': 'mp4',
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])
                    if not temp_file.exists():
                        candidates = list(TMP_DIR.glob(f"temp_{vid_id}_{quality}*.mp4"))
                        if candidates:
                            candidates[0].rename(temp_file)
                    arcname = f"{video_title}.mp4"
                    zipf.write(temp_file, arcname)
                    temp_file.unlink()
                
                task['processed'] = idx
                task['overall_progress'] = idx / total * 100
        
        task['status'] = 'completed'
        task['file'] = f"/file/{zip_filename}"
        task['filename'] = zip_filename
        task['overall_progress'] = 100
    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

# ============== Flask Routes ==============
@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    quality = data.get("quality", "720p")
    iphone_compatible = data.get("iphone_compatible", True)
    download_type = data.get("download_type", "video")   # 'video' or 'audio'
    audio_format = data.get("audio_format", "mp3")
    audio_bitrate = data.get("audio_bitrate", 128)
    playlist_mode = data.get("playlist_mode", False)
    
    if not url:
        return "Missing url", 400
    
    # Nếu có backend thì forward
    if BACKENDS:
        for backend in BACKENDS:
            try:
                resp = requests.post(f"{backend.rstrip('/')}/download", json=data, timeout=300)
                if resp.status_code == 200:
                    return jsonify(resp.json())
            except:
                continue
        return "All backends failed", 502
    
    task_id = str(uuid.uuid4())
    if playlist_mode:
        _tasks[task_id] = {
            'status': 'pending',
            'type': 'playlist',
            'overall_progress': 0,
            'detail': '',
            'file': None,
            'filename': None,
            'error': None
        }
        thread = threading.Thread(target=download_playlist, args=(task_id, url, quality, iphone_compatible,
                                                                   download_type, audio_format, audio_bitrate))
    else:
        _tasks[task_id] = {
            'status': 'pending',
            'type': 'single',
            'video_progress': 0,
            'audio_progress': 0,
            'merge_progress': 0,
            'speed': '',
            'file': None,
            'filename': None,
            'error': None
        }
        thread = threading.Thread(target=download_single, args=(task_id, url, quality, iphone_compatible,
                                                                download_type, audio_format, audio_bitrate))
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route("/progress/<task_id>")
def progress_stream(task_id):
    def generate():
        last_data = {}
        while True:
            task = _tasks.get(task_id)
            if not task:
                break
            if task['status'] == 'completed':
                if task.get('type') == 'playlist':
                    yield f"data: {json.dumps({'type': 'playlist', 'status': 'completed', 'file': task['file'], 'filename': task['filename'], 'overall_progress': 100})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'single', 'status': 'completed', 'file': task['file'], 'filename': task['filename'], 'video_progress': 100, 'audio_progress': 100, 'merge_progress': 100, 'is_audio': (task.get('video_progress',0)==0 and task.get('audio_progress',0)>0)})}\n\n"
                break
            elif task['status'] == 'error':
                if task.get('type') == 'playlist':
                    yield f"data: {json.dumps({'type': 'playlist', 'status': 'error', 'error': task['error']})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'single', 'status': 'error', 'error': task['error']})}\n\n"
                break
            
            if task.get('type') == 'playlist':
                data = {
                    'type': 'playlist',
                    'status': task['status'],
                    'overall_progress': task.get('overall_progress', 0),
                    'detail': task.get('detail', '')
                }
                if data != last_data.get('playlist'):
                    yield f"data: {json.dumps(data)}\n\n"
                    last_data['playlist'] = data.copy()
            else:
                data = {
                    'type': 'single',
                    'status': task['status'],
                    'video_progress': task.get('video_progress', 0),
                    'audio_progress': task.get('audio_progress', 0),
                    'merge_progress': task.get('merge_progress', 0),
                    'speed': task.get('speed', ''),
                    'is_audio': (task.get('video_progress',0)==0 and task.get('audio_progress',0)>0)
                }
                if data != last_data.get('single'):
                    yield f"data: {json.dumps(data)}\n\n"
                    last_data['single'] = data.copy()
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
    print(f"🚀 Server chạy tại: http://localhost:{port}")
    print(f"📁 File tạm: {TMP_DIR}")
    print(f"⏱️ TTL: {FILE_TTL} giây")
    app.run(host="0.0.0.0", port=port, debug=False)
