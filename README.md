# ytdl

Download videos (or audio) at the highest quality from YouTube, Instagram, or
X (Twitter) — straight from the terminal.

## Quick start

```bash
./setup.sh                 # one-time: installs yt-dlp + ffmpeg
./ytdl "https://www.youtube.com/watch?v=XXXX"
./ytdl "https://x.com/user/status/1234567890"
YTDL_COOKIES=~/ig-cookies.txt ./ytdl "https://www.instagram.com/reel/XXXX/"
```

Files land in `./downloads/`.

**Instagram** requires a logged-in cookies file (Netscape format) — export one
from your browser (e.g. a "Get cookies.txt" extension) and point `YTDL_COOKIES`
at it. YouTube and X work without cookies.

## CLI

```bash
./ytdl "URL"                        # best quality
./ytdl "URL" -o ~/Videos            # choose output folder
./ytdl "URL" -q 720                 # cap resolution
./ytdl "URL" --audio-only           # audio only (MP3)
./ytdl "URL" --audio-only --audio-format opus
./ytdl "URL" --info                 # title / length / views, no download
./ytdl "URL" --list                 # all available formats
```

## Requirements

`python3` (3.9+) and `curl`. `setup.sh` handles the rest (yt-dlp + ffmpeg,
no sudo needed).

## License

MIT
