# ytdl

Download videos (or audio) at the highest quality from YouTube, Instagram, or
X (Twitter) — as a CLI or a hosted web app.

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

## Web app

Paste a link in a browser, pick a quality, download.

```bash
castenv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
castenv/bin/python -m server.app    # -> http://127.0.0.1:8000
```

### Tiers

|        | Free     | Plus      | Power     |
|--------|----------|-----------|-----------|
| Price  | $0       | $4/mo     | $9/mo     |
| Quality| 480p     | 1080p     | 4K / best |
| Bandwidth/mo | 3 GB | 50 GB   | 300 GB    |

720p+ requires a paid tier. Bandwidth is metered per user, monthly.

## Android app (APK)

The same UI ships as an Android app, wrapped with Capacitor. It talks to a
backend you point it at (baked in at build time via `VITE_API_BASE`).

Prereqs: Node 20+, Java 21, an Android SDK (platform 36 + build-tools 35).

```bash
cd frontend
npm install
# point the app at your backend (default: https://ytdl.app)
VITE_API_BASE=https://api.yourdomain.com npm run apk:release   # -> unsigned release APK
VITE_API_BASE=https://api.yourdomain.com npm run apk:debug     # -> debug APK
```

Outputs:
- `frontend/android/app/build/outputs/apk/release/app-release-unsigned.apk`
- `frontend/android/app/build/outputs/apk/debug/app-debug.apk`

The release APK is **unsigned** (installable by sideloading). To sign it for the
Play Store, create a keystore and add a `key.properties` file (see
`frontend/android/key.properties.example`) — then `./gradlew bundleRelease`
produces an AAB.

## Landing site + APK hosting (GitHub Pages)

A static landing page in `site/` links to the APK. A GitHub Actions workflow
(`.github/workflows/pages.yml`) builds the APK on every push to `main` and
publishes the site + `app/youfetch.apk` to GitHub Pages.

1. In the repo, enable **Settings → Pages → Source: GitHub Actions**.
2. (Optional) set a repo **variable** `API_BASE` to your real backend URL so the
   built APK points at the right host.
3. Push to `main`. The site goes live at `https://<user>.github.io/<repo>/` and
   the APK is downloadable from the page.

To preview the site locally:

```bash
cd site && python3 -m http.server 8000   # open http://127.0.0.1:8000
```

(Drop a built APK into `site/app/youfetch.apk` first so the download link works.)

## Requirements

`python3` (3.9+), `curl`, `node`. `setup.sh` handles the rest.

## License

MIT
