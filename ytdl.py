#!/usr/bin/env python3
"""
ytdl.py - Download a video from YouTube, Instagram, or X (Twitter).

Basic usage:
  ytdl.py <url>                          # Best quality video to ./downloads
  ytdl.py <url> -o ~/Videos              # Choose output folder
  ytdl.py <url> -f mp4                   # Force MP4 container
  ytdl.py <url> --audio-only             # Download audio only (best quality)
  ytdl.py <url> --audio-format mp3       # Audio as MP3
  ytdl.py <url> -q 720                    # Cap resolution at 720p (faster/smaller)
  ytdl.py <url> --list                    # List available formats, don't download
  ytdl.py <url> --info                    # Show title/length/uploader, don't download

Instagram needs a logged-in cookies file (Netscape format) — set the
YTDL_COOKIES env var to its path. X/Twitter works without cookies.

Examples:
  ytdl.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ytdl.py "https://youtu.be/dQw4w9WgXcQ" --audio-only --audio-format mp3
  YTDL_COOKIES=~/ig-cookies.txt ytdl.py "https://www.instagram.com/reel/XXXX/"
  ytdl.py "https://x.com/user/status/1234567890"
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
YTDL = os.path.join(BASE, "castenv", "bin", "yt-dlp")
DEFAULT_OUT = os.path.join(BASE, "downloads")

# Optional cookies file (Netscape format) for sites that need login,
# e.g. Instagram. Set via the YTDL_COOKIES env var.
COOKIES_FILE = os.environ.get("YTDL_COOKIES", "")


def find_ffmpeg():
    """Return path to a working ffmpeg, or None."""
    local = os.path.join(BASE, "bin", "ffmpeg")
    if os.path.exists(local):
        return local
    import shutil
    return shutil.which("ffmpeg")


def _is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def build_cmd(args, cookies_file: str | None = None):
    cmd = [YTDL, "--no-playlist", "--newline"]

    # Cookies (for Instagram etc.): per-call override, else the env-var file.
    cf = cookies_file or COOKIES_FILE
    if cf and os.path.exists(cf):
        cmd += ["--cookies", cf]

    if _is_youtube(args.url):
        # YouTube now needs a JS runtime + remote challenge solver for full formats
        cmd += ["--js-runtimes", "node", "--remote-components", "ejs:github"]

    # Point yt-dlp at our local ffmpeg (for merging bestvideo+bestaudio)
    ff = find_ffmpeg()
    if ff:
        cmd += ["--ffmpeg-location", os.path.dirname(ff)]

    # Output template
    outdir = args.output or DEFAULT_OUT
    os.makedirs(outdir, exist_ok=True)
    if args.audio_only:
        template = os.path.join(outdir, "%(title)s.%(ext)s")
    else:
        template = os.path.join(outdir, "%(title)s [%(id)s].%(ext)s")
    cmd += ["-o", template]

    # Audio only
    if args.audio_only:
        afmt = (args.audio_format or "best").lower()
        if afmt in ("mp3", "m4a", "opus", "wav", "flac", "aac", "ogg", "best"):
            cmd += ["-x", "--audio-format", afmt]
        else:
            cmd += ["-x"]
    else:
        # Video: pick format.
        # YouTube has separate video+audio streams to merge. Instagram/X serve
        # a single combined stream, so keep it simple and let yt-dlp pick the
        # best available (with a quality cap when requested).
        if _is_youtube(args.url):
            if args.quality:
                if args.format == "mp4":
                    fmt = (f"bestvideo[height<={args.quality}][ext=mp4]+bestaudio[ext=m4a]/"
                           f"best[height<={args.quality}]")
                else:
                    fmt = f"bestvideo[height<={args.quality}]+bestaudio/best[height<={args.quality}]"
                cmd += ["-f", fmt]
            elif args.format == "mp4":
                cmd += ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]
            else:
                # Default: highest quality, let yt-dlp/ffmpeg merge
                cmd += ["-f", "bestvideo+bestaudio/best"]
            cmd += ["--merge-output-format", "mp4"]
        else:
            if args.quality:
                cmd += ["-f", f"best[height<={args.quality}]/best"]
            else:
                cmd += ["-f", "best"]

    # Info / list only
    if args.list:
        cmd += ["-F"]
    elif args.info:
        cmd += ["--print", "%(title)s | %(uploader)s | %(duration_string)s | %(view_count)s views", "--no-download"]

    cmd.append(args.url)
    return cmd


def main():
    p = argparse.ArgumentParser(description="Download a video from YouTube, Instagram, or X (Twitter).")
    p.add_argument("url", help="YouTube, Instagram, or X/Twitter video URL")
    p.add_argument("-o", "--output", help="Output directory (default: ./downloads)")
    p.add_argument("-f", "--format", choices=["mp4", "best"], default="best",
                   help="Force MP4 container, or best (default)")
    p.add_argument("-q", "--quality", type=int,
                   help="Cap resolution in px (e.g. 720, 1080). Lower = smaller/faster.")
    p.add_argument("--audio-only", action="store_true", help="Download audio only")
    p.add_argument("--audio-format", default="mp3",
                   help="Audio format when --audio-only (mp3, m4a, opus, wav, flac, best)")
    p.add_argument("--list", action="store_true", help="List available formats and exit")
    p.add_argument("--info", action="store_true", help="Show video info and exit")
    args = p.parse_args()

    cmd = build_cmd(args)
    print(f"Running: {' '.join(cmd)}\n", file=sys.stderr)
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
