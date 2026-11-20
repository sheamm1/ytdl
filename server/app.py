"""
server/app.py - Minimal hosted YouTube downloader (MVP).

Single-process FastAPI app with an in-process job queue + worker thread.
Reuses the download logic from ytdl.py. Designed to run on one machine;
swap the in-memory job store for Redis/Postgres and add a CDN later (see
MONETIZATION.md).

Run:
    castenv/bin/python -m server.app
then open http://127.0.0.1:8000
"""
import os
import re
import sys
import uuid
import time
import shutil
import secrets
import subprocess
import threading
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Optional

# Make the repo root importable so we can reuse ytdl.build_cmd
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import ytdl  # noqa: E402  (reuses build_cmd, find_ffmpeg)
from server import billing  # noqa: E402
from server import security  # noqa: E402

try:
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Run: castenv/bin/pip install fastapi uvicorn")
    raise

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Downloads dir: overridable via FILE_DIR (Docker mounts /data/downloads).
# Vercel Functions have a read-only filesystem except for /tmp, so use that
# there to keep the app importable. Downloads still require a persistent host.
_DEFAULT_FILE_DIR = (
    "/tmp/downloads"
    if os.environ.get("VERCEL")
    else os.path.join(BASE, "downloads")
)
FILE_DIR = os.environ.get("FILE_DIR", _DEFAULT_FILE_DIR)
# Built React frontend (created by `npm run build` in frontend/).
STATIC_DIR = os.path.join(BASE, "frontend", "dist")
os.makedirs(FILE_DIR, exist_ok=True)

# Quality presets -> the -q cap passed to ytdl (None = source best)
QUALITY_CAPS = {
    "best": None,
    "2160": 2160,
    "1440": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
}

# User identity cookie (no sign-up: a random persistent token per browser).
USER_COOKIE = "ytdl_uid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # ~1 year

# Per-user Instagram cookies (Netscape format). Instagram blocks most posts
# for anonymous requests, so users connect once by pasting their browser
# cookies; we validate them and reuse them for that user's IG jobs.
IG_COOKIES_DIR = os.path.join(FILE_DIR, ".ig_cookies")
os.makedirs(IG_COOKIES_DIR, exist_ok=True)


def _get_or_make_uid(request: Request, response: Response) -> str:
    """Return a stable user id from the cookie, creating one if absent.

    A02: cookie is HttpOnly + SameSite=Lax, and Secure in production so it is
    not sent over plain HTTP.
    """
    uid = request.cookies.get(USER_COOKIE)
    if not uid:
        uid = secrets.token_urlsafe(16)
        response.set_cookie(
            USER_COOKIE, uid, max_age=COOKIE_MAX_AGE,
            httponly=True, samesite="lax", secure=security.cfg.secure_cookies,
        )
    return uid

# ---------------------------------------------------------------------------
# In-memory job store (MVP). Replace with Redis/Postgres at scale.
# ---------------------------------------------------------------------------
@dataclass
class Job:
    id: str
    url: str
    quality: str
    audio_only: bool
    audio_format: str
    uid: str = ""
    status: str = "pending"      # pending | working | done | error
    progress: str = ""
    pct: int = 0                 # 0-100 overall progress for the bar
    title: str = ""
    filename: str = ""
    error: str = ""
    created: float = field(default_factory=time.time)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()

# A01: map filename -> set of uids that requested it, so /files/{name} only
# serves a file to users who downloaded it. Ownership is additive: cached files
# are shared, and a later requester must not lock out an earlier one.
# (Files are named by video title, not user, so we track ownership explicitly.)
FILE_OWNERS: dict[str, set[str]] = {}
FILE_OWNERS_LOCK = threading.Lock()

# Simple concurrency limit (bounds how many workers we need).
MAX_CONCURRENT = 2
_active = 0
_gate = threading.Semaphore(MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# Instagram cookies (per-user)
# ---------------------------------------------------------------------------
def _ig_cookies_path(uid: str) -> str:
    # uid is a base64url token; safe as a filename, but guard anyway.
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", uid)
    return os.path.join(IG_COOKIES_DIR, f"{safe}.txt")


def _is_instagram(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().split(":")[0]
    return host == "instagram.com" or host.endswith(".instagram.com")


def _cookies_for(job: Job) -> str | None:
    """Cookies file to use for this job (per-user IG cookies, if present)."""
    if _is_instagram(job.url) and job.uid:
        p = _ig_cookies_path(job.uid)
        if os.path.exists(p):
            return p
    return None


def _validate_ig_cookies(cookie_text: str) -> tuple[bool, str]:
    """Write candidate cookies to a temp file and ask yt-dlp to probe
    instagram.com. Returns (ok, message)."""
    import tempfile
    ok = False
    msg = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(cookie_text)
            tmp = f.name
        cmd = [ytdl.YTDL, "--cookies", tmp, "--skip-download",
               "--print", "%(uploader_id)s", "https://www.instagram.com/"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0 and out:
            ok = True
            msg = f"connected as {out}"
        else:
            last = err.splitlines()[-1] if err else "invalid cookies"
            msg = last[:300]
    except Exception as e:  # noqa: BLE001
        msg = str(e)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return ok, msg


# ---------------------------------------------------------------------------
# Worker: runs the download by reusing ytdl.build_cmd
# ---------------------------------------------------------------------------
def _dir_listing():
    try:
        return {f: os.path.getmtime(os.path.join(FILE_DIR, f))
                for f in os.listdir(FILE_DIR)}
    except FileNotFoundError:
        return {}


def _find_existing_for(job: Job):
    """If the video was already downloaded in a prior run, find that file.

    yt-dlp names files '<title> [<id>].<ext>'. We can't know the title without
    re-extracting, so match on the video id if present in the URL, else return
    the most recent video file (best-effort for the 'already downloaded' case).
    """
    import re
    vid = None
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", job.url)
    if m:
        vid = m.group(1)
    try:
        files = [f for f in os.listdir(FILE_DIR)
                 if not f.startswith(".") and f.lower().endswith(
                     (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".wav", ".flac"))]
    except FileNotFoundError:
        return None
    if vid:
        for f in files:
            if vid in f:
                return f
    if files:
        # fall back to the most recently modified video file
        return max(files, key=lambda f: os.path.getmtime(os.path.join(FILE_DIR, f)))
    return None


def _run_job(job: Job):
    global _active
    with _gate:
        _active += 1
        log_path = os.path.join(FILE_DIR, f".job_{job.id}.log")
        try:
            _set(job, status="working", progress="starting…")

            # Build a namespace with the attrs ytdl.build_cmd expects.
            class A:  # tiny arg container
                pass
            a = A()
            a.output = FILE_DIR
            a.audio_only = job.audio_only
            a.audio_format = job.audio_format
            a.quality = QUALITY_CAPS.get(job.quality)
            a.format = "best"
            a.list = False
            a.info = False
            a.url = job.url

            cmd = ytdl.build_cmd(a, cookies_file=_cookies_for(job))
            before = _dir_listing()

            # Run yt-dlp, writing output to a log file (avoids pipe deadlocks).
            # A tailer thread updates progress from the log while it runs.
            stop_tailer = threading.Event()

            def _tailer():
                """Map yt-dlp's lifecycle to a real 0-100 progress bar + stage text.

                yt-dlp spends most of its time BEFORE the download (extracting,
                solving JS challenges, fetching formats). Surface every stage so
                the UI never looks frozen, and drive the bar from the actual
                download percentage once it starts.
                """
                import re
                try:
                    # Robust tail: seek to end of already-written data, then
                    # repeatedly read available bytes and split on newlines.
                    # (readline() can block on \r-terminated progress lines.)
                    fh = open(log_path, "r", errors="ignore")
                    buf = ""
                    while not stop_tailer.is_set():
                        chunk = fh.read(65536)
                        if not chunk:
                            time.sleep(0.2)
                            continue
                        buf += chunk
                        # process complete lines only
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.rstrip("\r").strip()
                            if not line:
                                continue
                            low = line.lower()

                            # --- real download percentage (drives the bar) ---
                            m = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                            if m:
                                dl = float(m.group(1))
                                # map download 0-100% onto overall 30-90%
                                overall = 30 + (dl / 100.0) * 60
                                _set(job, progress=f"downloading {int(dl)}%",
                                     pct=int(overall))
                                continue

                            # --- stage markers (pre-download + post) ---
                            if "extracting url" in low:
                                _set(job, progress="reading video…", pct=5)
                            elif "downloading webpage" in low:
                                _set(job, progress="fetching page…", pct=8)
                            elif "player api json" in low or "player " in low:
                                _set(job, progress="contacting youtube…", pct=12)
                            elif "solving js challenge" in low or "jsc" in low:
                                _set(job, progress="solving security check…", pct=18)
                            elif "downloading formats" in low or "available formats" in low:
                                _set(job, progress="listing formats…", pct=25)
                            elif "[download] destination" in low or "merging formats" in low:
                                _set(job, progress="preparing file…", pct=28)
                            elif "[merger]" in low and "merging" in low:
                                _set(job, progress="merging audio + video…", pct=92)
                            elif "[extractaudio]" in low or "extracting audio" in low:
                                _set(job, progress="extracting audio…", pct=92)
                            elif "has already been downloaded" in low:
                                _set(job, progress="ready", pct=100)
                except Exception:
                    pass

            # Create the log file BEFORE starting the tailer so the tailer's
            # file handle sees the same inode that yt-dlp writes to.
            logf = open(log_path, "w")
            tailer = threading.Thread(target=_tailer, daemon=True)
            tailer.start()

            try:
                proc = subprocess.run(
                    cmd, stdout=logf, stderr=subprocess.STDOUT,
                )
            finally:
                logf.flush()
                logf.close()
            rc = proc.returncode

            stop_tailer.set()
            tailer.join(timeout=2)

            # Determine the output file. Primary: parse the real path out of the
            # yt-dlp log (handles "already downloaded" too). Fallback: diff the
            # directory for a newly-created file.
            final_name = _extract_output_path(log_path)
            if not final_name:
                after = _dir_listing()
                new_files = [
                    f for f, mt in after.items()
                    if (f not in before or mt != before.get(f))
                    and not f.startswith(".")
                    and not f.endswith((".part", ".ytdl"))
                ]
                final_name = (
                    max(new_files, key=lambda f: after[f]) if new_files else None
                )

            # "Already downloaded" case: yt-dlp exits 0 but writes no new file.
            # If the expected output already exists on disk, treat it as done.
            if rc == 0 and not final_name:
                existing = _find_existing_for(job)
                if existing:
                    final_name = existing

            if rc == 0 and final_name and os.path.exists(
                    os.path.join(FILE_DIR, final_name)):
                title = os.path.splitext(final_name)[0].rsplit(" [", 1)[0]
                with FILE_OWNERS_LOCK:  # A01: record ownership (additive)
                    FILE_OWNERS.setdefault(final_name, set()).add(job.uid)
                security.log.info("job done id=%s file=%s", job.id, final_name)
                _set(job, status="done", progress="ready", pct=100,
                     filename=final_name, title=title)
            else:
                tail = _tail(log_path, 5)
                security.log.warning("job error id=%s rc=%s tail=%s",
                                     job.id, rc, tail.replace("\n", " | "))
                _set(job, status="error",
                     error=f"yt-dlp exited {rc}. {tail}".strip())
        except Exception as e:  # noqa: BLE001
            _set(job, status="error", error=str(e))
        finally:
            _active -= 1
            try:
                os.remove(log_path)
            except OSError:
                pass


def _extract_output_path(log_path: str) -> str | None:
    """Extract the final output filename from a yt-dlp log.

    Parses line-by-line so titles containing spaces (or any non-space chars)
    work. Prefers the [Merger] target (the real merged file), then the last
    'Destination:' path (also covers [ExtractAudio]), then an
    'already been downloaded' line. Returns a basename, or None.
    """
    import re
    try:
        with open(log_path, "r", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return None

    merged = None
    destination = None
    existing = None

    for raw in lines:
        line = raw.rstrip("\r\n")

        # 1) Merged output: [Merger] Merging formats into "PATH"
        m = re.search(r'Merging formats into "(.+)"\s*$', line)
        if m:
            merged = m.group(1)
            continue

        # 2) Any 'Destination: PATH' (last one wins). Matches paths with
        #    spaces, e.g. "[ExtractAudio] Destination: .../My Song.mp3".
        m = re.search(r"Destination:\s*(.+?)\s*$", line)
        if m:
            destination = m.group(1)
            continue

        # 3) Already-downloaded case: "[download] PATH has already been downloaded"
        m = re.search(r"^\[download\]\s+(.+)\s+has already been downloaded\s*$", line)
        if m:
            existing = m.group(1)

    path = merged or destination or existing
    if not path:
        return None
    return os.path.basename(path.strip().strip('"'))


def _tail(path, n):
    try:
        with open(path, "r", errors="ignore") as fh:
            return "".join(fh.readlines()[-n:])
    except OSError:
        return ""


def _set(job: Job, **kw):
    with JOBS_LOCK:
        for k, v in kw.items():
            setattr(job, k, v)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="ytdl hosted")

# A05: add security headers (CSP, X-Frame-Options, HSTS, etc.) to every response.
security.security_headers_middleware(app)


class Submit(BaseModel):
    url: str
    quality: str = "best"
    audio_only: bool = False
    audio_format: str = "mp3"


class IgConnect(BaseModel):
    cookies: str


@app.post("/api/instagram/connect")
def ig_connect(req: IgConnect, request: Request, response: Response):
    """Store the user's Instagram cookies (Netscape format) after validating
    them against instagram.com. Cookies are kept per-user, on disk, 0600."""
    uid = _get_or_make_uid(request, response)
    ip = security.client_ip(request)
    if not security.rate_limiter.allow(f"ig:{uid}", 5, 60):
        raise HTTPException(429, "Too many attempts. Try again shortly.")

    text = req.cookies.strip()
    if len(text) < 20:
        raise HTTPException(400, "Cookies look too short — paste the full export.")

    ok, msg = _validate_ig_cookies(text)
    if not ok:
        raise HTTPException(401, f"Instagram rejected those cookies: {msg}")

    path = _ig_cookies_path(uid)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)
    security.log.info("instagram connected uid=%s", uid)
    return {"ok": True, "message": msg}


@app.get("/api/instagram/status")
def ig_status(request: Request, response: Response):
    uid = _get_or_make_uid(request, response)
    return {"connected": os.path.exists(_ig_cookies_path(uid))}


@app.get("/api/health")
def health():
    return {"ok": True, "active": _active, "max": MAX_CONCURRENT}


@app.get("/api/usage")
def usage(request: Request, response: Response):
    """Tier + bandwidth usage for the current user (sets the identity cookie)."""
    uid = _get_or_make_uid(request, response)
    return billing.store.snapshot(uid)


@app.post("/api/tier")
def set_tier(request: Request, response: Response, tier: str):
    """Set the user's tier.

    MVP: a query param (for testing / manual upgrade). In production this is
    driven by a Stripe webhook after a successful payment.
    """
    uid = _get_or_make_uid(request, response)
    if not security.rate_limiter.allow(f"tier:{uid}", security.cfg.rl_tier_per_min):
        raise HTTPException(429, "Too many requests. Try again shortly.")
    if tier not in billing.TIERS:
        raise HTTPException(400, f"tier must be one of {list(billing.TIERS)}")
    billing.store.set_tier(uid, tier)
    security.log.info("tier changed uid=%s tier=%s", uid, tier)
    return billing.store.snapshot(uid)


@app.post("/api/jobs")
def submit(req: Submit, request: Request, response: Response):
    uid = _get_or_make_uid(request, response)
    ip = security.client_ip(request)

    # A05/DoS: rate-limit job submissions per user and per IP.
    if not security.rate_limiter.allow(f"submit:{uid}", security.cfg.rl_submit_per_min):
        raise HTTPException(429, "Too many requests. Try again shortly.")
    if not security.rate_limiter.allow(f"submit:ip:{ip}", security.cfg.rl_submit_per_min * 3):
        raise HTTPException(429, "Too many requests from your network.")

    tier = billing.store.tier(uid)

    if req.quality not in QUALITY_CAPS:
        raise HTTPException(400, f"quality must be one of {list(QUALITY_CAPS)}")

    # A03: validate the URL before it reaches yt-dlp.
    url_err = security.validate_url(req.url)
    if url_err:
        raise HTTPException(400, url_err)

    # Quality gating: 720p+ requires a paid tier.
    if not billing.can_select(tier, req.quality):
        raise HTTPException(
            403,
            f"'{req.quality}' needs a paid plan. Free tier is capped at "
            f"{billing.max_quality_for(tier)}.",
        )

    # Bandwidth cap: block new jobs once the monthly allowance is used up.
    snap = billing.store.snapshot(uid)
    if snap["bandwidth_remaining_bytes"] is not None and snap["bandwidth_remaining_bytes"] <= 0:
        raise HTTPException(
            403,
            "Monthly bandwidth used up. Upgrade for more, or wait for the "
            "monthly reset.",
        )

    job = Job(
        id=uuid.uuid4().hex,
        url=req.url.strip(),
        quality=req.quality,
        audio_only=req.audio_only,
        audio_format=req.audio_format,
        uid=uid,
    )
    with JOBS_LOCK:
        JOBS[job.id] = job
    security.log.info("job submitted id=%s uid=%s quality=%s", job.id, uid, req.quality)
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return {"id": job.id}


@app.get("/api/jobs/{job_id}")
def status(job_id: str, request: Request, response: Response):
    uid = _get_or_make_uid(request, response)
    ip = security.client_ip(request)
    if not security.rate_limiter.allow(f"status:{uid}", security.cfg.rl_status_per_min):
        raise HTTPException(429, "Too many requests. Try again shortly.")

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            # A01: use 404 (not 403) to avoid leaking that a job id exists.
            raise HTTPException(404, "no such job")
        # A01 Broken Access Control: only the owner may read their job.
        if job.uid != uid:
            raise HTTPException(404, "no such job")
        data = {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "pct": job.pct,
            "title": job.title,
            "error": job.error,
        }
        if job.status == "done":
            # Percent-encode the filename: titles may contain '#', '?', '%',
            # spaces, etc. An unencoded '#' would truncate the link at the
            # browser and cause a 404.
            data["download"] = "/files/" + quote(job.filename, safe="")
    return data


@app.get("/files/{name}")
def download(name: str, request: Request, response: Response):
    uid = _get_or_make_uid(request, response)
    # Prevent path traversal
    safe = os.path.basename(name)
    path = os.path.join(FILE_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(404, "file not found")

    # A01: only users who requested this file may download it. Unknown files
    # (e.g. from before this feature) stay accessible.
    with FILE_OWNERS_LOCK:
        owners = FILE_OWNERS.get(safe)
    if owners is not None and uid not in owners:
        raise HTTPException(404, "file not found")

    size = os.path.getsize(path)
    # Count the served bytes against the user's monthly bandwidth.
    billing.store.add_bandwidth(uid, size)

    # If the user just crossed the cap, tell the client (file still serves).
    snap = billing.store.snapshot(uid)
    headers = {}
    if (snap["bandwidth_remaining_bytes"] is not None
            and snap["bandwidth_remaining_bytes"] <= 0):
        headers["X-Bandwidth-Exhausted"] = "1"
    return FileResponse(path, filename=safe, headers=headers or None)


# Serve the built React frontend (frontend/dist). If it hasn't been built yet,
# fall back to a simple message so the API still works.
if os.path.isdir(STATIC_DIR) and os.path.exists(os.path.join(STATIC_DIR, "index.html")):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:

    @app.get("/")
    def _no_frontend():
        return JSONResponse(
            {"hint": "Frontend not built. Run: cd frontend && npm install && npm run build"},
            status_code=200,
        )


def main():
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f" * ytdl hosted MVP -> http://127.0.0.1:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
