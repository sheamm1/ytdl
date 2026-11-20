"""
server/security.py - OWASP Top 10 hardening for the ytdl web app.

Provides, as small composable pieces:
  - security headers middleware   (A05 misconfiguration / clickjacking / MIME sniff)
  - rate limiter                  (A05 / DoS: per-IP and per-user token buckets)
  - URL validation                (A03 injection / SSRF: scheme allowlist, length)
  - config                        (A02 / A05: env-driven SECRET_KEY, DEBUG, secure cookies)
  - logging setup                 (A10: structured request + job logging)

Kept separate from app.py so the rules are readable and unit-testable.
"""
import os
import re
import time
import logging
import threading
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Config (A02 / A05): env-driven, with safe defaults.
# ---------------------------------------------------------------------------
class Config:
    def __init__(self):
        self.debug = os.environ.get("DEBUG", "0") == "1"
        # SECRET_KEY signs the identity cookie. In prod set it to a long random
        # value; if unset we generate one (cookie identity is not a security
        # boundary, but a stable key avoids re-issuing on every restart).
        self.secret_key = os.environ.get("SECRET_KEY", "") or os.urandom(32).hex()
        # Secure cookies are only useful behind HTTPS. Default OFF so the app
        # works over plain http://localhost (browsers drop Secure cookies on
        # HTTP). Set SECURE_COOKIES=1 when serving over HTTPS in production.
        self.secure_cookies = os.environ.get("SECURE_COOKIES", "0") == "1"
        # Rate limits (requests per window).
        self.rl_submit_per_min = int(os.environ.get("RL_SUBMIT_PER_MIN", "10"))
        self.rl_tier_per_min = int(os.environ.get("RL_TIER_PER_MIN", "5"))
        self.rl_status_per_min = int(os.environ.get("RL_STATUS_PER_MIN", "120"))


cfg = Config()


def client_ip(request) -> str:
    """Best-effort client IP (respects X-Forwarded-For when behind a proxy)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Security headers middleware (A05, clickjacking, MIME-sniff, XSS aid)
# ---------------------------------------------------------------------------
SECURITY_HEADERS = {
    # Clickjacking: we don't need to be framed.
    "X-Frame-Options": "DENY",
    # MIME sniffing.
    "X-Content-Type-Options": "nosniff",
    # Referrer leakage.
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Permissions (camera/mic/etc. not needed).
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # HSTS (only meaningful over HTTPS; harmless on HTTP in dev).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # Content Security Policy: our app is same-origin only.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "upgrade-insecure-requests"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def security_headers_middleware(handler):
    """Wrap a Starlette/FastAPI app to add security headers to every response."""
    from starlette.middleware.base import BaseHTTPMiddleware

    class _Headers(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
            return response

    handler.add_middleware(_Headers)
    return handler


# ---------------------------------------------------------------------------
# Rate limiter (A05 / DoS): fixed-window token buckets, in-memory.
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        # key -> (window_start, count)
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, limit: int, window_sec: int = 60) -> bool:
        now = time.time()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= window_sec:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            # Opportunistic cleanup to bound memory.
            if len(self._hits) > 10000:
                cutoff = now - window_sec
                self._hits = {
                    k: v for k, v in self._hits.items() if v[0] > cutoff
                }
            return count <= limit


rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# URL validation (A03 injection / SSRF)
# ---------------------------------------------------------------------------
# Only accept http/https URLs from the supported sites. Block file://, ftp://,
# gopher://, data://, and bare hostnames (SSRF / local-file reads).
_ALLOWED_SCHEMES = {"http", "https"}
_MAX_URL_LEN = 2048
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
# Hosts we accept (yt-dlp supports many more, but we only advertise these).
_ALLOWED_HOSTS = (
    "youtube.com", "youtu.be",
    "instagram.com",
    "twitter.com", "x.com", "t.co",
)


def validate_url(url: str) -> str | None:
    """Return an error string if the URL is unacceptable, else None."""
    if not url:
        return "URL is required"
    if len(url) > _MAX_URL_LEN:
        return "URL too long"
    # Collapse whitespace (a common injection/obfuscation trick).
    url = url.strip()
    if any(c.isspace() for c in url):
        return "URL contains whitespace"
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return "URL must start with http:// or https://"
    if not parsed.netloc:
        return "URL is missing a host"
    if not _URL_RE.match(url):
        return "URL has an invalid format"
    host = parsed.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS):
        return "Unsupported site. Paste a YouTube, Instagram, or X (Twitter) video link."
    return None


# ---------------------------------------------------------------------------
# Logging (A10): structured, single line, safe to ship to a log aggregator.
# ---------------------------------------------------------------------------
def setup_logging():
    level = logging.DEBUG if cfg.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=os.sys.stdout,
    )
    # Quiet down noisy libs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return logging.getLogger("ytdl")


log = setup_logging()
