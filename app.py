import os
import time
import re
import random
import threading
import uuid
import json
import zipfile
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

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

# ------------------ HTML (giữ nguyên) ------------------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Mini-Y2mate Pro - Nam2006©</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .tab-active {
      background-color: #10b981;
      color: black;
    }
    .tab-inactive {
      background-color: #1f2937;
      color: #9ca3af;
    }
    .tab-inactive:hover {
      background-color: #374151;
      color: white;
    }
  </style>
</head>
<body class="bg-black text-gray-100 min-h-screen flex items-center justify-center p-6">
  <div class="w-full max-w-2xl bg-gray-900/90 backdrop-blur-sm rounded-2xl shadow-2xl p-6 border border-gray-800">
    <h1 class="text-2xl font-bold mb-4 flex items-center gap-3">
      <svg class="w-6 h-6 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.196-3L10 9v6z"/><path d="M21 7.5a2.5 2.5 0 00-2.5-2.5H5.5A2.5 2.5 0 003 7.5v9A2.5 2.5 0 005.5 19h13a2.5 2.5 0 002.5-2.5v-9z"/></svg>
      Mini-Y2mate Pro - <span class="text-emerald-400">Nam2006©</span>
    </h1>

    <div class="flex gap-2 mb-6">
      <button id="tabYoutube" class="tab-active px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2">
        <img src="https://upload.wikimedia.org/wikipedia/commons/e/ef/Youtube_logo.png" class="w-5 h-5 object-contain" alt="YouTube">
        <span>YouTube</span>
      </button>
      <button id="TabFacebook" class="tab-inactive px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2">
        <img src="https://img.magnific.com/psd-cao-cap/logo-facebook-tren-mot-vong-tron-mau-xanh-lam_705838-12823.jpg" class="w-5 h-5 object-contain" alt="Facebook">
        <span>Facebook</span>
      </button>
      <button id="TabTikTok" class="tab-inactive px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2">
        <img src="https://cdn.pixabay.com/photo/2021/06/15/12/28/tiktok-6338432_1280.png" class="w-5 h-5 object-contain" alt="TikTok">
        <span>TikTok</span>
      </button>
    </div>

    <div id="youtubeTab" class="space-y-4">
      <div class="flex gap-2 flex-wrap">
        <input id="urlYoutube" type="text" placeholder="https://www.youtube.com/watch?v=... hoặc playlist" class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="qualityYoutube" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
          <option value="1440p">1440p</option>
          <option value="2160p">2160p (4K)</option>
        </select>
      </div>

      <div class="flex gap-4 bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeYoutube" value="video" checked class="accent-emerald-500"> 
          <span>🎬 Video</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeYoutube" value="audio" class="accent-purple-500"> 
          <span>🎵 Audio</span>
        </label>
      </div>

      <div id="youtubeVideoOptions" class="space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng video:</span>
          <select id="videoFormatYoutube" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp4">MP4</option>
            <option value="webm">WebM</option>
            <option value="mkv">MKV</option>
            <option value="avi">AVI</option>
            <option value="mov">MOV</option>
            <option value="flv">FLV</option>
          </select>
        </div>
      </div>

      <div id="youtubeAudioOptions" class="hidden space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng:</span>
          <select id="youtubeAudioFormat" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp3">MP3</option>
            <option value="m4a">M4A</option>
            <option value="webm">WEBM</option>
            <option value="aac">AAC</option>
            <option value="flac">FLAC</option>
            <option value="ogg">OGG</option>
            <option value="wav">WAV</option>
            <option value="opus">OPUS</option>
          </select>
          <span class="text-sm font-medium ml-2">Bitrate:</span>
          <select id="youtubeAudioBitrate" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="64">64 kbps</option>
            <option value="128" selected>128 kbps</option>
            <option value="192">192 kbps</option>
            <option value="256">256 kbps</option>
            <option value="320">320 kbps</option>
          </select>
        </div>
      </div>

      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M4 6h16v2H4V6zm2 4h12v2H6v-2zm14 4H4v2h16v-2z"/></svg>
          <span class="text-sm font-medium">Tải toàn bộ playlist</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="youtubePlaylistMode" class="sr-only peer">
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          <span class="text-sm font-medium">iPhone Compatible (H.264 + AAC)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="youtubeIphoneMode" class="sr-only peer" checked>
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>
    </div>

    <div id="facebookTab" class="space-y-4 hidden">
      <div class="flex gap-2 flex-wrap">
        <input id="urlFacebook" type="text" placeholder="https://www.facebook.com/.../videos/... hoặc https://fb.watch/..." class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="qualityFacebook" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
        </select>
      </div>

      <div class="flex gap-4 bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeFacebook" value="video" checked class="accent-emerald-500"> 
          <span>🎬 Video</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeFacebook" value="audio" class="accent-purple-500"> 
          <span>🎵 Audio</span>
        </label>
      </div>

      <div id="facebookVideoOptions" class="space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng video:</span>
          <select id="videoFormatFacebook" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp4">MP4</option>
            <option value="webm">WebM</option>
            <option value="mkv">MKV</option>
            <option value="avi">AVI</option>
            <option value="mov">MOV</option>
            <option value="flv">FLV</option>
          </select>
        </div>
      </div>

      <div id="facebookAudioOptions" class="hidden space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng:</span>
          <select id="facebookAudioFormat" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp3">MP3</option>
            <option value="m4a">M4A</option>
            <option value="aac">AAC</option>
            <option value="flac">FLAC</option>
            <option value="ogg">OGG</option>
            <option value="wav">WAV</option>
            <option value="opus">OPUS</option>
          </select>
          <span class="text-sm font-medium ml-2">Bitrate:</span>
          <select id="facebookAudioBitrate" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="64">64 kbps</option>
            <option value="128" selected>128 kbps</option>
            <option value="192">192 kbps</option>
            <option value="256">256 kbps</option>
            <option value="320">320 kbps</option>
          </select>
        </div>
      </div>

      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          <span class="text-sm font-medium">Chuyển đổi cho iPhone (H.264 + AAC)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="facebookConvertForIphone" class="sr-only peer" checked>
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>
      
      <div class="bg-yellow-900/30 border border-yellow-700 rounded-xl p-3 text-xs">
        ⚠️ <span class="font-semibold">Lưu ý:</span> Facebook không có H.264 sẵn. Bật "Chuyển đổi cho iPhone" sẽ tự động convert video sau khi tải (cần FFmpeg).
      </div>
    </div>

    <div id="tiktokTab" class="space-y-4 hidden">
      <div class="flex gap-2 flex-wrap">
        <input id="urlTikTok" type="text" placeholder="https://www.tiktok.com/@username/video/... hoặc @username hoặc #hashtag" class="flex-1 rounded-xl px-4 py-2 bg-gray-800 border border-gray-700 outline-none text-gray-100"/>
        <select id="qualityTikTok" class="rounded-xl px-3 py-2 bg-gray-800 border border-gray-700 text-gray-100">
          <option value="360p">360p</option>
          <option value="720p" selected>720p</option>
          <option value="1080p">1080p</option>
        </select>
      </div>

      <div class="flex gap-4 bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeTikTok" value="video" checked class="accent-emerald-500"> 
          <span>🎬 Video</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="downloadTypeTikTok" value="audio" class="accent-purple-500"> 
          <span>🎵 Audio</span>
        </label>
      </div>

      <div id="tiktokVideoOptions" class="space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng video:</span>
          <select id="videoFormatTikTok" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp4">MP4</option>
            <option value="webm">WebM</option>
            <option value="mkv">MKV</option>
            <option value="avi">AVI</option>
            <option value="mov">MOV</option>
            <option value="flv">FLV</option>
          </select>
        </div>
      </div>

      <div id="tiktokAudioOptions" class="hidden space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Định dạng:</span>
          <select id="tiktokAudioFormat" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="mp3">MP3</option>
            <option value="m4a">M4A</option>
            <option value="aac">AAC</option>
            <option value="flac">FLAC</option>
            <option value="ogg">OGG</option>
            <option value="wav">WAV</option>
            <option value="opus">OPUS</option>
          </select>
          <span class="text-sm font-medium ml-2">Bitrate:</span>
          <select id="tiktokAudioBitrate" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm">
            <option value="64">64 kbps</option>
            <option value="128" selected>128 kbps</option>
            <option value="192">192 kbps</option>
            <option value="256">256 kbps</option>
            <option value="320">320 kbps</option>
          </select>
        </div>
      </div>

      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
          <span class="text-sm font-medium">iPhone Compatible (H.264 + AAC)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="tiktokIphoneMode" class="sr-only peer" checked>
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <div class="flex items-center justify-between bg-gray-800/50 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24"><path d="M4 6h16v2H4V6zm2 4h12v2H6v-2zm14 4H4v2h16v-2z"/></svg>
          <span class="text-sm font-medium">Tải toàn bộ (profile/hashtag)</span>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" id="tiktokBatchMode" class="sr-only peer">
          <div class="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-500"></div>
        </label>
      </div>

      <div id="tiktokBatchOptions" class="hidden space-y-2 bg-gray-800/30 rounded-xl p-3 border border-gray-700">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="text-sm font-medium">Giới hạn số lượng:</span>
          <input id="tiktokLimit" type="number" value="10" min="1" max="100" class="rounded-lg px-3 py-1.5 bg-gray-800 border border-gray-700 text-sm w-24"/>
          <span class="text-xs text-gray-400">(tối đa 100)</span>
        </div>
      </div>
      
      <div class="bg-blue-900/30 border border-blue-700 rounded-xl p-3 text-xs">
        💡 <span class="font-semibold">Hỗ trợ:</span> Video đơn, profile (@username), hashtag (#tag). Bật "Tải toàn bộ" để tải nhiều video.
      </div>
      
      <div class="bg-green-900/30 border border-green-700 rounded-xl p-3 text-xs">
        📱 <span class="font-semibold">iPhone Compatible:</span> Bật để chuyển đổi video sang chuẩn H.264 + AAC tương thích iPhone.
      </div>
    </div>

    <div id="progressSection" class="mt-6">
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

      <div id="playlistProgressContainer" class="hidden space-y-2">
        <div class="flex justify-between text-xs text-gray-400 mb-1">
          <span>📀 Đang xử lý</span>
          <span id="playlistPercent">0%</span>
        </div>
        <div class="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
          <div id="playlistBar" class="bg-emerald-500 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <div id="playlistDetail" class="text-xs text-gray-500 text-center"></div>
      </div>
    </div>

    <button id="btnDownload" class="w-full mt-4 rounded-xl py-3 bg-emerald-500 hover:bg-emerald-600 text-black font-semibold transition-all">
      ⬇️ Tải xuống
    </button>

    <div id="status" class="text-sm text-gray-300 text-center mt-2"></div>
    <div id="linkbox" class="hidden mt-2">
      <div class="bg-gray-800 rounded-xl p-3">
        <a id="dlink" class="text-emerald-400 font-semibold hover:underline break-all" href="#">📥 Tải xuống tại đây</a>
      </div>
    </div>
    <div class="mt-3 text-xs text-gray-500 text-center">
      ⏱️ File được giữ trong <span class="font-medium">10 phút</span>
    </div>
  </div>

  <script>
  const btnDownload = document.getElementById('btnDownload');
  const statusDiv = document.getElementById('status');
  const linkbox = document.getElementById('linkbox');
  const dlink = document.getElementById('dlink');
  const multiProgress = document.getElementById('multiProgressContainer');
  const playlistProgress = document.getElementById('playlistProgressContainer');
  const videoBar = document.getElementById('videoBar');
  const videoPercent = document.getElementById('videoPercent');
  const audioBar = document.getElementById('audioBar');
  const audioPercent = document.getElementById('audioPercent');
  const mergeBar = document.getElementById('mergeBar');
  const mergePercent = document.getElementById('mergePercent');
  const speedInfo = document.getElementById('speedInfo');
  const playlistBar = document.getElementById('playlistBar');
  const playlistPercentSpan = document.getElementById('playlistPercent');
  const playlistDetail = document.getElementById('playlistDetail');
  
  let eventSource = null;
  let currentTab = 'youtube';
  let currentTaskId = null; // Lưu task_id để resume

  const tabYoutube = document.getElementById('tabYoutube');
  const tabFacebook = document.getElementById('TabFacebook');
  const tabTikTok = document.getElementById('TabTikTok');
  const youtubeTab = document.getElementById('youtubeTab');
  const facebookTab = document.getElementById('facebookTab');
  const tiktokTab = document.getElementById('tiktokTab');

  function setActiveTab(tab) {
    currentTab = tab;
    tabYoutube.className = tab === 'youtube' ? 'tab-active px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2' : 'tab-inactive px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2';
    tabFacebook.className = tab === 'facebook' ? 'tab-active px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2' : 'tab-inactive px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2';
    tabTikTok.className = tab === 'tiktok' ? 'tab-active px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2' : 'tab-inactive px-4 py-2 rounded-lg font-semibold transition-all flex-1 flex items-center justify-center gap-2';
    youtubeTab.classList.toggle('hidden', tab !== 'youtube');
    facebookTab.classList.toggle('hidden', tab !== 'facebook');
    tiktokTab.classList.toggle('hidden', tab !== 'tiktok');
  }

  tabYoutube.onclick = () => setActiveTab('youtube');
  tabFacebook.onclick = () => setActiveTab('facebook');
  tabTikTok.onclick = () => setActiveTab('tiktok');

  // Xử lý hiển thị tùy chọn video/audio cho YouTube
  const youtubeVideoOptions = document.getElementById('youtubeVideoOptions');
  const youtubeAudioOptions = document.getElementById('youtubeAudioOptions');
  const youtubeRadios = document.querySelectorAll('input[name="downloadTypeYoutube"]');
  youtubeRadios.forEach(r => r.addEventListener('change', () => {
    const isAudio = document.querySelector('input[name="downloadTypeYoutube"]:checked').value === 'audio';
    youtubeVideoOptions.classList.toggle('hidden', isAudio);
    youtubeAudioOptions.classList.toggle('hidden', !isAudio);
  }));

  // Facebook
  const facebookVideoOptions = document.getElementById('facebookVideoOptions');
  const facebookAudioOptions = document.getElementById('facebookAudioOptions');
  const facebookRadios = document.querySelectorAll('input[name="downloadTypeFacebook"]');
  facebookRadios.forEach(r => r.addEventListener('change', () => {
    const isAudio = document.querySelector('input[name="downloadTypeFacebook"]:checked').value === 'audio';
    facebookVideoOptions.classList.toggle('hidden', isAudio);
    facebookAudioOptions.classList.toggle('hidden', !isAudio);
  }));

  // TikTok
  const tiktokVideoOptions = document.getElementById('tiktokVideoOptions');
  const tiktokAudioOptions = document.getElementById('tiktokAudioOptions');
  const tiktokRadios = document.querySelectorAll('input[name="downloadTypeTikTok"]');
  tiktokRadios.forEach(r => r.addEventListener('change', () => {
    const isAudio = document.querySelector('input[name="downloadTypeTikTok"]:checked').value === 'audio';
    tiktokVideoOptions.classList.toggle('hidden', isAudio);
    tiktokAudioOptions.classList.toggle('hidden', !isAudio);
  }));

  const tiktokBatchCheckbox = document.getElementById('tiktokBatchMode');
  const tiktokBatchOptions = document.getElementById('tiktokBatchOptions');
  tiktokBatchCheckbox.onchange = () => {
    tiktokBatchOptions.classList.toggle('hidden', !tiktokBatchCheckbox.checked);
  };

  btnDownload.onclick = async () => {
    let url, quality, iphone, downloadType, audioFormat, audioBitrate, playlistMode, convertForIphone, batchMode, limit, videoFormat;
    
    if (currentTab === 'youtube') {
      url = document.getElementById('urlYoutube').value.trim();
      quality = document.getElementById('qualityYoutube').value;
      iphone = document.getElementById('youtubeIphoneMode').checked;
      downloadType = document.querySelector('input[name="downloadTypeYoutube"]:checked').value;
      audioFormat = document.getElementById('youtubeAudioFormat').value;
      audioBitrate = parseInt(document.getElementById('youtubeAudioBitrate').value);
      playlistMode = document.getElementById('youtubePlaylistMode').checked;
      convertForIphone = false;
      batchMode = false;
      limit = 0;
      videoFormat = document.getElementById('videoFormatYoutube').value;
    } else if (currentTab === 'facebook') {
      url = document.getElementById('urlFacebook').value.trim();
      quality = document.getElementById('qualityFacebook').value;
      iphone = false;
      downloadType = document.querySelector('input[name="downloadTypeFacebook"]:checked').value;
      audioFormat = document.getElementById('facebookAudioFormat').value;
      audioBitrate = parseInt(document.getElementById('facebookAudioBitrate').value);
      playlistMode = false;
      convertForIphone = document.getElementById('facebookConvertForIphone').checked;
      batchMode = false;
      limit = 0;
      videoFormat = document.getElementById('videoFormatFacebook').value;
    } else {
      url = document.getElementById('urlTikTok').value.trim();
      quality = document.getElementById('qualityTikTok').value;
      iphone = document.getElementById('tiktokIphoneMode').checked;
      downloadType = document.querySelector('input[name="downloadTypeTikTok"]:checked').value;
      audioFormat = document.getElementById('tiktokAudioFormat').value;
      audioBitrate = parseInt(document.getElementById('tiktokAudioBitrate').value);
      playlistMode = false;
      convertForIphone = iphone;
      batchMode = document.getElementById('tiktokBatchMode').checked;
      limit = parseInt(document.getElementById('tiktokLimit').value) || 10;
      videoFormat = document.getElementById('videoFormatTikTok').value;
    }

    if (!url) return alert('🔗 Nhập URL đi bro');

    // Nếu đã có task_id và task đang lỗi, gửi lại để resume
    const resumePayload = currentTaskId ? { resume_task_id: currentTaskId } : {};

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
          ...resumePayload,
          url, quality, iphone_compatible: iphone, download_type: downloadType,
          audio_format: audioFormat, audio_bitrate: audioBitrate,
          playlist_mode: playlistMode, convert_for_iphone: convertForIphone,
          batch_mode: batchMode, limit: limit, platform: currentTab,
          video_format: videoFormat
        })
      });

      if (!response.ok) throw new Error(await response.text());

      const data = await response.json();
      const taskId = data.task_id;
      currentTaskId = taskId;

      eventSource = new EventSource(`/progress/${taskId}`);
      eventSource.onmessage = (e) => {
        const prog = JSON.parse(e.data);
        
        if (prog.type === 'single') {
          multiProgress.classList.remove('hidden');
          playlistProgress.classList.add('hidden');
          const videoRow = document.getElementById('videoRow');
          if (prog.is_audio) videoRow.style.display = 'none';
          else videoRow.style.display = 'block';
          
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
            statusDiv.textContent = '✅ Thành công!';
            btnDownload.disabled = false;
            btnDownload.textContent = '⬇️ Tải xuống';
            currentTaskId = null;
            setTimeout(() => multiProgress.classList.add('hidden'), 3000);
          } else if (prog.status === 'error') {
            // Lưu task_id để có thể resume
            statusDiv.textContent = '❌ Lỗi: ' + prog.error + ' (có thể thử lại)';
            btnDownload.disabled = false;
            btnDownload.textContent = '🔄 Thử lại';
            if (eventSource) eventSource.close();
          }
        } else if (prog.type === 'playlist') {
          multiProgress.classList.add('hidden');
          playlistProgress.classList.remove('hidden');
          playlistBar.style.width = (prog.overall_progress || 0) + '%';
          playlistPercentSpan.textContent = Math.round(prog.overall_progress || 0) + '%';
          if (prog.detail) playlistDetail.textContent = prog.detail;
          
          if (prog.status === 'completed') {
            eventSource.close();
            dlink.href = prog.file;
            dlink.textContent = '📥 ' + prog.filename;
            linkbox.classList.remove('hidden');
            statusDiv.textContent = '✅ Hoàn thành!';
            btnDownload.disabled = false;
            btnDownload.textContent = '⬇️ Tải xuống';
            currentTaskId = null;
          } else if (prog.status === 'error') {
            statusDiv.textContent = '❌ Lỗi: ' + prog.error + ' (có thể thử lại)';
            btnDownload.disabled = false;
            btnDownload.textContent = '🔄 Thử lại';
            if (eventSource) eventSource.close();
          }
        }
      };
      eventSource.onerror = () => {
        // Nếu kết nối bị ngắt, vẫn giữ task_id để resume
        eventSource.close();
      };
    } catch (e) {
      statusDiv.textContent = '❌ Lỗi: ' + e.message;
      btnDownload.disabled = false;
      btnDownload.textContent = '⬇️ Tải xuống';
      if (eventSource) eventSource.close();
    }
  };
  </script>
</body>
</html>
"""

# ------------------ Helper functions ------------------
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
        except Exception:
            pass
        time.sleep(30)

threading.Thread(target=background_cleaner, daemon=True).start()

def convert_for_iphone(input_path: Path, output_path: Path) -> bool:
    """Chuyển đổi video sang H.264 + AAC cho iPhone."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        cmd = [
            'ffmpeg', '-i', str(input_path), '-c:v', 'libx264', '-preset', 'fast',
            '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            '-pix_fmt', 'yuv420p', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-y', str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        return output_path.exists()
    except:
        return False

def convert_video_container(input_path: Path, output_path: Path, target_format: str) -> bool:
    """Chuyển đổi container video (đã sửa lỗi cho AVI/MOV)."""
    try:
        # Thử copy stream trước (nhanh nhất)
        cmd_copy = ['ffmpeg', '-i', str(input_path), '-c', 'copy', '-y', str(output_path)]
        result = subprocess.run(cmd_copy, capture_output=True, timeout=120)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True

        # Re-encode nếu copy thất bại
        if target_format == 'webm':
            vcodec = 'libvpx-vp9'
            acodec = 'libopus'
            extra_args = ['-crf', '30', '-b:v', '0']
        elif target_format == 'flv':
            vcodec = 'flv1'
            acodec = 'mp3'
            extra_args = ['-ar', '44100', '-b:a', '128k']
        elif target_format == 'mov':
            vcodec = 'libx264'
            acodec = 'aac'
            extra_args = ['-movflags', '+faststart', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.0']
        elif target_format == 'avi':
            vcodec = 'libx264'
            acodec = 'pcm_s16le'
            extra_args = ['-pix_fmt', 'yuv420p']
        else:  # mp4, mkv, ...
            vcodec = 'libx264'
            acodec = 'aac'
            extra_args = ['-pix_fmt', 'yuv420p']
            if target_format == 'mp4':
                extra_args.extend(['-movflags', '+faststart'])

        cmd_reencode = [
            'ffmpeg', '-i', str(input_path),
            '-c:v', vcodec, '-c:a', acodec,
            *extra_args,
            '-y', str(output_path)
        ]
        subprocess.run(cmd_reencode, check=True, capture_output=True, timeout=300)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as e:
        print(f"❌ Lỗi convert container: {e}")
        return False

# ------------------ HÀM TẢI VỚI TASK_ID (RESUME) ------------------
def download_with_task_id(task_id: str, url: str, ydl_opts: dict) -> Path:
    """
    Tải video/audio với outtmpl dùng task_id.
    yt-dlp tự động resume nếu file tạm tồn tại.
    """
    ydl_opts['outtmpl'] = str(TMP_DIR / f"{task_id}.%(ext)s")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # Tìm file đã tải
    candidates = list(TMP_DIR.glob(f"{task_id}.*"))
    if not candidates:
        raise Exception(f"Không tìm thấy file đã tải cho task {task_id}")
    for f in candidates:
        if f.stat().st_size > 0:
            return f
    return candidates[0]

# ------------------ HÀM TẢI ĐƠN (CÓ RESUME) ------------------
def download_single(task_id: str, url: str, quality: str, iphone_compatible: bool,
                    download_type: str, audio_format: str, audio_bitrate: int,
                    convert_for_iphone_flag: bool = False, platform: str = 'youtube',
                    video_format: str = 'mp4'):
    try:
        task = _tasks[task_id]
        task['status'] = 'downloading'
        is_audio = (download_type == 'audio')
        is_facebook = (platform == 'facebook')
        is_tiktok = (platform == 'tiktok')

        # Lấy thông tin video
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            title = info.get('title', 'video')
            vid_id = info.get('id', '')

        safe_title = sanitize_title(title)
        base_name = f"{safe_title}_{vid_id}"

        # Xác định tên file cuối cùng
        if is_audio:
            final_ext = audio_format
            final_filename = f"{base_name}_audio.{final_ext}"
        else:
            if (iphone_compatible and platform == 'youtube') or convert_for_iphone_flag:
                final_ext = 'mp4'
            else:
                final_ext = video_format
            final_filename = f"{base_name}_{quality}.{final_ext}"
        final_path = TMP_DIR / final_filename

        # Nếu file đã tồn tại, coi như hoàn thành
        if final_path.exists():
            task['status'] = 'completed'
            task['file'] = f"/file/{final_filename}"
            task['filename'] = final_filename
            task['video_progress'] = 100
            task['audio_progress'] = 100
            task['merge_progress'] = 100
            return

        # --- Xây dựng ydl_opts ---
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [SingleProgressHook(task_id, is_audio=is_audio)],
            'concurrent_fragment_downloads': CONCURRENT_FRAGMENTS,
            # Mặc định continue = True, yt-dlp sẽ resume nếu file .part tồn tại
        }

        SAFE_MERGE_CONTAINERS = ['mp4', 'mkv', 'webm']
        
        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            postprocessor_opts = {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
            }
            if audio_format in ('flac', 'wav', 'alac'):
                postprocessor_opts['preferredquality'] = '0'
            else:
                postprocessor_opts['preferredquality'] = str(audio_bitrate)
            ydl_opts['postprocessors'] = [postprocessor_opts]
            temp_file = download_with_task_id(task_id, url, ydl_opts)
            temp_file.rename(final_path)
        else:
            if is_facebook:
                fmt = "best"
            elif is_tiktok:
                fmt = "bestvideo[ext=mp4]+bestaudio/best"
            else:
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

            ydl_opts['format'] = fmt
            ydl_opts['noplaylist'] = True

            if iphone_compatible or convert_for_iphone_flag:
                ydl_opts['merge_output_format'] = 'mp4'
            else:
                if video_format in SAFE_MERGE_CONTAINERS:
                    ydl_opts['merge_output_format'] = video_format
                else:
                    ydl_opts['merge_output_format'] = 'mp4'

            temp_file = download_with_task_id(task_id, url, ydl_opts)
            task['merge_progress'] = 70

            if iphone_compatible or convert_for_iphone_flag:
                task['merge_progress'] = 80
                if convert_for_iphone(temp_file, final_path):
                    temp_file.unlink()
                else:
                    temp_file.rename(final_path)
            else:
                if video_format in SAFE_MERGE_CONTAINERS and temp_file.suffix == f'.{video_format}':
                    temp_file.rename(final_path)
                else:
                    task['merge_progress'] = 80
                    success = convert_video_container(temp_file, final_path, video_format)
                    if success:
                        temp_file.unlink()
                    else:
                        print(f"⚠ Không thể chuyển đổi sang {video_format}, giữ nguyên container gốc")
                        actual_ext = temp_file.suffix[1:] if temp_file.suffix else 'mp4'
                        fallback_name = f"{base_name}_{quality}.{actual_ext}"
                        fallback_path = TMP_DIR / fallback_name
                        temp_file.rename(fallback_path)
                        final_path = fallback_path
                        task['file'] = f"/file/{fallback_path.name}"
                        task['filename'] = fallback_path.name

        # Xóa file tạm (nếu có)
        for p in TMP_DIR.glob(f"{task_id}.*"):
            if p != final_path:
                try:
                    p.unlink()
                except:
                    pass

        task['status'] = 'completed'
        task['file'] = f"/file/{final_path.name}"
        task['filename'] = final_path.name
        task['video_progress'] = 100
        task['audio_progress'] = 100
        task['merge_progress'] = 100
        print(f"✅ [Task {task_id}] Hoàn thành: {final_path.name}")

    except Exception as e:
        print(f"❌ [Task {task_id}] Lỗi: {str(e)}")
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)
        # Giữ nguyên file tạm để có thể resume

# ------------------ PLAYLIST / BATCH (có thể resume nhưng phức tạp, giữ nguyên logic cũ) ------------------
# Để đơn giản, ta không tích hợp resume cho playlist, chỉ thêm khả năng resume cho single.
# Nếu cần, có thể mở rộng tương tự.

# ------------------ Flask routes ------------------
@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json() or {}
    resume_task_id = data.get("resume_task_id")
    
    # Nếu có resume_task_id, thử tiếp tục task cũ
    if resume_task_id and resume_task_id in _tasks:
        task = _tasks[resume_task_id]
        if task['status'] == 'error':
            # Lấy params đã lưu
            params = task.get('params')
            if not params:
                return jsonify({"error": "Task không có params để resume"}), 400
            # Khởi động lại thread
            thread = threading.Thread(target=download_single, args=(
                resume_task_id,
                params['url'],
                params['quality'],
                params['iphone_compatible'],
                params['download_type'],
                params['audio_format'],
                params['audio_bitrate'],
                params.get('convert_for_iphone', False),
                params.get('platform', 'youtube'),
                params.get('video_format', 'mp4')
            ))
            thread.daemon = True
            thread.start()
            task['status'] = 'resuming'
            return jsonify({"task_id": resume_task_id, "resumed": True})
        else:
            return jsonify({"error": "Task không thể resume (không phải lỗi)"}), 400

    # Tạo task mới
    url = data.get("url", "").strip()
    quality = data.get("quality", "720p")
    iphone_compatible = data.get("iphone_compatible", False)
    download_type = data.get("download_type", "video")
    audio_format = data.get("audio_format", "mp3")
    audio_bitrate = data.get("audio_bitrate", 128)
    playlist_mode = data.get("playlist_mode", False)
    convert_for_iphone_flag = data.get("convert_for_iphone", False)
    batch_mode = data.get("batch_mode", False)
    limit = data.get("limit", 10)
    platform = data.get("platform", "youtube")
    video_format = data.get("video_format", "mp4")

    if not url:
        return "Missing url", 400

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

    # Lưu params để resume
    params = {
        'url': url,
        'quality': quality,
        'iphone_compatible': iphone_compatible,
        'download_type': download_type,
        'audio_format': audio_format,
        'audio_bitrate': audio_bitrate,
        'playlist_mode': playlist_mode,
        'convert_for_iphone': convert_for_iphone_flag,
        'batch_mode': batch_mode,
        'limit': limit,
        'platform': platform,
        'video_format': video_format,
    }

    if platform == 'tiktok' and batch_mode:
        _tasks[task_id] = {
            'status': 'pending', 'type': 'playlist',
            'overall_progress': 0, 'detail': '',
            'file': None, 'filename': None, 'error': None,
            'params': params
        }
        thread = threading.Thread(target=download_tiktok_batch, args=(task_id, url, download_type, audio_format, audio_bitrate, limit, video_format))
    elif playlist_mode:
        _tasks[task_id] = {
            'status': 'pending', 'type': 'playlist',
            'overall_progress': 0, 'detail': '',
            'file': None, 'filename': None, 'error': None,
            'params': params
        }
        thread = threading.Thread(target=download_playlist, args=(task_id, url, quality, iphone_compatible,
                                                                   download_type, audio_format, audio_bitrate, video_format))
    else:
        _tasks[task_id] = {
            'status': 'pending', 'type': 'single',
            'video_progress': 0, 'audio_progress': 0, 'merge_progress': 0,
            'speed': '', 'file': None, 'filename': None, 'error': None,
            'params': params
        }
        thread = threading.Thread(target=download_single, args=(task_id, url, quality, iphone_compatible,
                                                                download_type, audio_format, audio_bitrate,
                                                                convert_for_iphone_flag, platform, video_format))
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
            elif task['status'] == 'resuming':
                yield f"data: {json.dumps({'type': 'single', 'status': 'resuming', 'message': 'Đang tiếp tục tải...'})}\n\n"

            if task.get('type') == 'playlist':
                data = {'type': 'playlist', 'status': task['status'], 'overall_progress': task.get('overall_progress', 0), 'detail': task.get('detail', '')}
                if data != last_data.get('playlist'):
                    yield f"data: {json.dumps(data)}\n\n"
                    last_data['playlist'] = data.copy()
            else:
                data = {'type': 'single', 'status': task['status'], 'video_progress': task.get('video_progress', 0), 'audio_progress': task.get('audio_progress', 0), 'merge_progress': task.get('merge_progress', 0), 'speed': task.get('speed', ''), 'is_audio': (task.get('video_progress',0)==0 and task.get('audio_progress',0)>0)}
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

# Định nghĩa lại các hàm playlist và SingleProgressHook (giữ nguyên logic cũ)
# Ở đây cần khai báo lại SingleProgressHook và các hàm playlist để code hoàn chỉnh,
# nhưng để tránh trùng lặp, tôi giả định chúng đã được định nghĩa ở trên.
# Tuy nhiên, trong code thực tế, cần đặt chúng trước khi sử dụng.

# ------------------ Các hàm playlist (giữ nguyên) ------------------
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
            filename = d.get('filename', '')
            is_audio_file = any(x in filename.lower() for x in ['.m4a', '.webm', '.aac', '.mp3', '.ogg', '.flac', '.wav', '.opus'])
            if self.is_audio or is_audio_file:
                task['audio_progress'] = percent
            else:
                task['video_progress'] = percent
                task['speed'] = speed_str
        elif d['status'] == 'finished':
            task['merge_progress'] = min(100, task.get('merge_progress', 0) + 30)
        elif d['status'] == 'processing':
            task['merge_progress'] = min(100, task.get('merge_progress', 0) + 10)

def download_playlist(task_id: str, url: str, quality: str, iphone_compatible: bool,
                      download_type: str, audio_format: str, audio_bitrate: int,
                      video_format: str = 'mp4'):
    try:
        task = _tasks[task_id]
        task['status'] = 'downloading'

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

        SAFE_MERGE_CONTAINERS = ['mp4', 'mkv', 'webm']

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, entry in enumerate(entries, 1):
                video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                video_title = sanitize_title(entry.get('title', f'video_{idx}'))

                task['overall_progress'] = (idx-1) / total * 100
                task['detail'] = f"Đang tải {idx}/{total}: {video_title}"

                if download_type == 'audio':
                    temp_file = download_with_task_id(task_id, video_url, {
                        'quiet': True,
                        'no_warnings': True,
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': audio_format,
                            'preferredquality': '0' if audio_format in ('flac', 'wav') else str(audio_bitrate),
                        }],
                    })
                    arcname = f"{video_title}.{audio_format}"
                else:
                    fmt = f"bestvideo[height<={quality[:-1]}]+bestaudio/best" if quality != "2160p" else "bestvideo+bestaudio/best"
                    if iphone_compatible:
                        fmt = f"bestvideo[height<={quality[:-1]}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[ext=mp4]"

                    if iphone_compatible:
                        merge_container = 'mp4'
                    else:
                        merge_container = video_format if video_format in SAFE_MERGE_CONTAINERS else 'mp4'

                    temp_file = download_with_task_id(task_id, video_url, {
                        'quiet': True,
                        'no_warnings': True,
                        'format': fmt,
                        'merge_output_format': merge_container,
                        'noplaylist': True,
                    })

                    if not iphone_compatible and video_format not in SAFE_MERGE_CONTAINERS:
                        converted_path = TMP_DIR / f"{uuid.uuid4().hex}.{video_format}"
                        if convert_video_container(temp_file, converted_path, video_format):
                            temp_file.unlink()
                            temp_file = converted_path
                        else:
                            actual_ext = temp_file.suffix[1:] if temp_file.suffix else 'mp4'
                            arcname = f"{video_title}.{actual_ext}"
                            zipf.write(temp_file, arcname)
                            temp_file.unlink()
                            continue

                    arcname = f"{video_title}.{video_format if not iphone_compatible else 'mp4'}"

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

def download_tiktok_batch(task_id: str, url: str, download_type: str, audio_format: str, audio_bitrate: int, limit: int, video_format: str = 'mp4'):
    try:
        task = _tasks[task_id]
        task['status'] = 'downloading'

        ydl_opts_flat = {'quiet': True, 'extract_flat': True, 'playlistend': limit}
        with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = info.get('entries', [])
            total = len(entries)

        if total == 0:
            raise Exception("Không tìm thấy video")

        zip_filename = f"tiktok_{uuid.uuid4().hex[:8]}.zip"
        zip_path = TMP_DIR / zip_filename

        SAFE_MERGE_CONTAINERS = ['mp4', 'mkv', 'webm']

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, entry in enumerate(entries[:limit], 1):
                video_url = entry.get('url') or f"https://www.tiktok.com/@{entry.get('uploader', '')}/video/{entry['id']}"
                video_title = sanitize_title(entry.get('title', f'video_{idx}'))

                task['overall_progress'] = (idx-1) / total * 100
                task['detail'] = f"Đang tải {idx}/{total}: {video_title[:50]}"

                if download_type == 'audio':
                    temp_file = download_with_task_id(task_id, video_url, {
                        'quiet': True,
                        'no_warnings': True,
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': audio_format,
                            'preferredquality': '0' if audio_format in ('flac', 'wav') else str(audio_bitrate),
                        }],
                    })
                    arcname = f"{video_title}.{audio_format}"
                else:
                    temp_file = download_with_task_id(task_id, video_url, {
                        'quiet': True,
                        'no_warnings': True,
                        'format': 'bestvideo[ext=mp4]+bestaudio/best',
                        'merge_output_format': 'mp4',
                    })
                    if video_format != 'mp4':
                        converted_path = TMP_DIR / f"{uuid.uuid4().hex}.{video_format}"
                        if convert_video_container(temp_file, converted_path, video_format):
                            temp_file.unlink()
                            temp_file = converted_path
                        else:
                            actual_ext = temp_file.suffix[1:] if temp_file.suffix else 'mp4'
                            arcname = f"{video_title}.{actual_ext}"
                            zipf.write(temp_file, arcname)
                            temp_file.unlink()
                            continue
                    arcname = f"{video_title}.{video_format}"

                zipf.write(temp_file, arcname)
                temp_file.unlink()

                task['overall_progress'] = idx / total * 100

        task['status'] = 'completed'
        task['file'] = f"/file/{zip_filename}"
        task['filename'] = zip_filename
        task['overall_progress'] = 100
    except Exception as e:
        _tasks[task_id]['status'] = 'error'
        _tasks[task_id]['error'] = str(e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server chạy tại: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
