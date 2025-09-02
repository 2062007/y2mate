#!/bin/bash
set -e

# Cài ffmpeg (cần cho yt-dlp để merge video+audio)
apt-get update && apt-get install -y ffmpeg

# Cập nhật lib cần thiết
pip install --upgrade pip
pip install --upgrade yt-dlp flask requests gunicorn

# In log server
echo "Starting Mini-Y2mate with Gunicorn..."

# Run Gunicorn, bind vào $PORT (Render sẽ cung cấp biến PORT)
exec gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 4 --timeout 120
