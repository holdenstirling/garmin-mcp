"""Near-instant workout sync for Rabbit (``POST /app/api/sync``).

True Garmin push needs Garmin's partner program, so the app asks instead: on open,
when it becomes visible, and every minute while home is on screen. Each ask is one
uncached ``get_activities`` read (the newest 5), throttled to once per
``THROTTLE_S`` per user in memory; inside the window the last result comes back
(with ``changed`` false, so a second tab never repeats a toast).

The last activity id seen here lives in its own encrypted ``sync`` doc, separate
from the background poller's cursor (whose at-most-once semantics stay untouched).
The first check only records a baseline. When a newer id shows up, ``on_new`` runs
(``StatsService.invalidate(..., activities=True)``) so stats, load, XP and gear
mileage are fresh at once. Garmin errors never raise: they come back as
``{"error": ...}``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .appstore import AppStore
from .logs import log_event
from .providers import GarminError, RateLimited, ReauthRequired
from .stats import category

logger = logging.getLogger(__name__)

THROTTLE_S = 45.0
FETCH_LIMIT = 5


def _aid(a: dict[str, Any]) -> int | None:
    v = a.get("activityId")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def activity_view(a: dict[str, Any]) -> dict[str, Any]:
    atype = a.get("activityType")
    sport = category(atype.get("typeKey") if isinstance(atype, dict) else None)
    dur = a.get("duration")
    dist = a.get("distance")
    return {"id": _aid(a), "name": str(a.get("activityName") or "Workout")[:80], "sport": sport,
            "minutes": round(dur / 60) if isinstance(dur, int | float) else 0,
            "km": round(dist / 1000, 1) if isinstance(dist, int | float) and dist else 0.0}


class LiveSync:
    def __init__(self, store: AppStore, fetch: Callable[[str], list[dict[str, Any]]], *,
                 connected: Callable[[str], bool], on_new: Callable[[str], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._s = store
        self._fetch = fetch
        self._connected = connected
        self._on_new = on_new
        self._clock = clock
        self._last: dict[str, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, threading.Lock())

    def check(self, user_id: str) -> dict[str, Any]:
        with self._lock(user_id):
            hit = self._last.get(user_id)
            if hit and self._clock() - hit[0] < THROTTLE_S:
                return {**hit[1], "changed": False, "new": [], "cached": True}
            out = self._check(user_id)
            self._last[user_id] = (self._clock(), out)
            return out

    def _check(self, user_id: str) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        base: dict[str, Any] = {"checked_at": now, "new": [], "changed": False}
        if not self._connected(user_id):
            return {**base, "error": "Garmin isn't connected."}
        try:
            raw = self._fetch(user_id) or []
        except ReauthRequired:
            return {**base, "error": "Reconnect Garmin in settings to sync workouts."}
        except RateLimited:
            return {**base, "error": "Garmin is busy. Workouts will sync in a minute."}
        except GarminError:
            return {**base, "error": "Couldn't reach Garmin just now."}
        except Exception as e:  # never a 500 for a background refresh
            log_event(logger, logging.WARNING, "sync_failed", user_id=user_id, error=type(e).__name__)
            return {**base, "error": "Couldn't reach Garmin just now."}
        acts = [a for a in raw if isinstance(a, dict) and _aid(a) is not None]
        if not acts:
            return base
        newest = max(_aid(a) or 0 for a in acts)

        def advance(d: dict[str, Any]) -> int | None:
            prev = d.get("last_seen")
            prev = prev if isinstance(prev, int) else None
            d["last_seen"] = max(prev or 0, newest)
            d["checked_at"] = now
            return prev
        prev = self._s.user_doc(user_id, "sync").update(advance)
        if prev is None or newest <= prev:
            return base  # first check is a baseline; nothing newer otherwise
        new = sorted((a for a in acts if (_aid(a) or 0) > prev and not a.get("parentId")),
                     key=lambda a: _aid(a) or 0)
        try:
            self._on_new(user_id)
        except Exception as e:
            log_event(logger, logging.WARNING, "sync_invalidate_failed", user_id=user_id,
                      error=type(e).__name__)
        log_event(logger, logging.INFO, "sync_new", user_id=user_id, new=len(new))
        return {**base, "changed": True, "new": [activity_view(a) for a in new]}


__all__ = ["LiveSync", "THROTTLE_S", "activity_view"]
