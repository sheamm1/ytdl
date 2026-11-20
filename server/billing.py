"""
server/billing.py - Tier, quality-gating, and bandwidth accounting.

Kept separate from app.py so the pricing rules are easy to read, test, and
tune. The whole model is "price the data, not the dream": tiers are defined
by a monthly bandwidth allowance, and 720p+ is a paid feature.

All state is in-memory for the MVP (see MONETIZATION.md for the swap to
Postgres at scale). Identity is a cookie token — no sign-up.
"""
import time
import threading

# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
# bandwidth_cap_bytes: monthly allowance. None = unlimited.
TIERS = {
    "free": {
        "bandwidth_cap_bytes": 3 * 1024 ** 3,   # 3 GB / month
        "max_quality": "480",                    # free is capped at 480p
        "concurrent": 1,
    },
    "plus": {
        "bandwidth_cap_bytes": 50 * 1024 ** 3,  # 50 GB / month
        "max_quality": "1080",
        "concurrent": 3,
    },
    "power": {
        "bandwidth_cap_bytes": 300 * 1024 ** 3, # 300 GB / month
        "max_quality": "best",
        "concurrent": 8,
    },
}

DEFAULT_TIER = "free"

# Quality ordering, lowest -> highest. A user may select any quality at or
# below their tier's max_quality.
QUALITY_ORDER = ["480", "720", "1080", "1440", "2160", "best"]


def quality_rank(q: str) -> int:
    """Higher = higher quality. Unknown qualities rank lowest."""
    try:
        return QUALITY_ORDER.index(q)
    except ValueError:
        return -1


def can_select(tier: str, quality: str) -> bool:
    """True if `tier` is allowed to download at `quality`."""
    max_q = TIERS.get(tier, TIERS[DEFAULT_TIER])["max_quality"]
    return quality_rank(quality) <= quality_rank(max_q)


def max_quality_for(tier: str) -> str:
    return TIERS.get(tier, TIERS[DEFAULT_TIER])["max_quality"]


def bandwidth_cap_for(tier: str) -> int | None:
    return TIERS.get(tier, TIERS[DEFAULT_TIER])["bandwidth_cap_bytes"]


# ---------------------------------------------------------------------------
# Usage store (in-memory, MVP)
# ---------------------------------------------------------------------------
class _Usage:
    __slots__ = ("bandwidth_bytes", "month", "tier")

    def __init__(self, tier: str = DEFAULT_TIER):
        self.bandwidth_bytes = 0
        self.month = _current_month()
        self.tier = tier


def _current_month() -> str:
    """YYYY-MM key; usage resets when this changes."""
    return time.strftime("%Y-%m")


class UsageStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._users: dict[str, _Usage] = {}

    def _get_unlocked(self, uid: str) -> _Usage:
        """Get-or-create a user's usage, rolling over the month if needed.
        Caller must hold self._lock."""
        u = self._users.get(uid)
        if u is None:
            u = _Usage()
            self._users[uid] = u
        if u.month != _current_month():
            u.month = _current_month()
            u.bandwidth_bytes = 0
        return u

    def set_tier(self, uid: str, tier: str):
        if tier not in TIERS:
            return
        with self._lock:
            self._get_unlocked(uid).tier = tier

    def tier(self, uid: str) -> str:
        with self._lock:
            return self._get_unlocked(uid).tier

    def add_bandwidth(self, uid: str, nbytes: int):
        if nbytes <= 0:
            return
        with self._lock:
            self._get_unlocked(uid).bandwidth_bytes += nbytes

    def used_bytes(self, uid: str) -> int:
        with self._lock:
            return self._get_unlocked(uid).bandwidth_bytes

    def snapshot(self, uid: str) -> dict:
        with self._lock:
            u = self._get_unlocked(uid)
            cap = bandwidth_cap_for(u.tier)
            used = u.bandwidth_bytes
            remaining = (cap - used) if cap is not None else None
            tier = u.tier
            month = u.month
        return {
            "tier": tier,
            "max_quality": max_quality_for(tier),
            "bandwidth_cap_bytes": cap,
            "bandwidth_used_bytes": used,
            "bandwidth_remaining_bytes": remaining,
            "month": month,
            # Human-friendly, for the UI.
            "bandwidth_cap_gb": round(cap / 1024 ** 3, 1) if cap else None,
            "bandwidth_used_gb": round(used / 1024 ** 3, 2),
            "bandwidth_remaining_gb": round(remaining / 1024 ** 3, 2) if remaining is not None else None,
        }


# Singleton for the app.
store = UsageStore()
