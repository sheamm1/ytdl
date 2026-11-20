#!/bin/bash
# setup.sh - Make this tool self-contained.
# Installs yt-dlp into ./castenv and a static ffmpeg into ./bin (no sudo needed).
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "==> [1/2] Installing yt-dlp into castenv/"
if [ ! -x castenv/bin/python ]; then
    python3 -m venv castenv
fi
castenv/bin/pip install --upgrade pip >/dev/null
castenv/bin/pip install -q yt-dlp
echo "    yt-dlp: $(castenv/bin/yt-dlp --version)"

echo "==> [2/2] Setting up ffmpeg (needed to merge best video+audio)"
if [ -x bin/ffmpeg ]; then
    echo "    ffmpeg already present in bin/"
elif command -v ffmpeg >/dev/null 2>&1; then
    echo "    Using system ffmpeg: $(command -v ffmpeg)"
else
    echo "    Downloading static ffmpeg (no sudo needed)..."
    mkdir -p bin
    tmp="$(mktemp -d)"
    curl -sL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz" -o "$tmp/ffmpeg.tar.xz"
    tar -xf "$tmp/ffmpeg.tar.xz" -C "$tmp"
    extracted="$(find "$tmp" -maxdepth 2 -name ffmpeg -type f | head -1)"
    if [ -n "$extracted" ]; then
        cp "$extracted" bin/ffmpeg
        ffprobe_src="$(dirname "$extracted")/ffprobe"
        [ -f "$ffprobe_src" ] && cp "$ffprobe_src" bin/ffprobe
        chmod +x bin/ffmpeg bin/ffprobe
        echo "    ffmpeg installed to bin/ffmpeg"
    else
        echo "    WARNING: could not locate ffmpeg in download; high-quality merges may fail."
    fi
    rm -rf "$tmp"
fi

echo ""
echo "Checking JS runtime (yt-dlp uses it to solve YouTube's JS challenges)..."
if command -v node >/dev/null 2>&1; then
    echo "    node: $(node --version)  (good)"
else
    echo "    WARNING: node not found. Install node for full YouTube format access."
fi

echo ""
echo "Setup complete. Try:"
echo "  ./ytdl --info \"https://www.youtube.com/watch?v=XXXX\""
