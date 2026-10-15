"""One-tap actions on the Rabbit home (``GET /app/api/home/quick``), deterministic, no model.

At most one of each, in this order, each only when it applies:

* ``feel``: "How did it feel?" for the latest workout (today/yesterday) without a check-in
  (completed inline with ``POST /app/api/checkins {feel, activity_id, date}``).
* ``rsvp``: the next club meetup in 7 days I haven't answered (``.../meetups/{mid}/rsvp``).
* ``cheer``: the newest friend workout post (3 days) without my reaction
  (``POST /app/api/community/posts/{pid}/reactions``).
* ``watch``: the next planned session in the 7-day Garmin sync window that isn't on the
  watch yet (``POST /app/api/plan/garmin/sync {days: 7}``), only with Garmin connected.

Every source is best effort: a failing one just hides its action.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from .community import SPORT_TITLE, workout_label
from .logs import log_event
from .planbuilder import iter_sessions
from .stats import _rows

logger = logging.getLogger(__name__)

FEEL_DAYS = 1
CHEER_DAYS = 3
RSVP_DAYS = 7
WATCH_DAYS = 7  # the Garmin sync window "Send to watch" uses


def pick_feel(acts: list[dict[str, Any]], checkins: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    rows = [r for r in _rows(acts) if isinstance(r["id"], int) and 0 <= (today - r["date"]).days <= FEEL_DAYS]
    if not rows:
        return None
    r = max(rows, key=lambda r: (r["date"], r["id"]))
    day = r["date"].isoformat()
    for c in checkins:
        if str(c.get("activity_id") or "") == str(r["id"]) or (c.get("date") == day and not c.get("activity_id")):
            return None
    return {"kind": "feel", "label": "How did it feel?", "activity_id": r["id"], "date": day,
            "sport": r["sport"], "title": SPORT_TITLE.get(r["sport"], "Workout"),
            "minutes": round(r["min"]) or None, "km": round(r["km"], 2) or None}


def pick_rsvp(meetups: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    last = now.replace(tzinfo=None) + timedelta(days=RSVP_DAYS)
    for m in meetups:  # soonest first
        if m.get("my_rsvp") or not m.get("next") or datetime.fromisoformat(m["next"]) > last:
            continue
        club = m.get("club") or {}
        return {"kind": "rsvp", "label": "RSVP", "club_id": club.get("id"), "club": club.get("name") or "Your club",
                "meetup_id": m["id"], "title": m.get("title") or "Meetup", "next": m["next"],
                "where": m.get("where") or "", "going": len(m.get("going") or [])}
    return None


def pick_cheer(items: list[dict[str, Any]], now_ts: float, name: Callable[[str], str]) -> dict[str, Any] | None:
    for p in items:  # newest first
        if (p.get("mine") or p.get("kind") != "workout" or p.get("my_reaction")
                or now_ts - float(p.get("created") or 0) > CHEER_DAYS * 86400):
            continue
        return {"kind": "cheer", "label": "Cheer a friend", "post_id": p["id"], "name": name(p["author"]),
                "what": workout_label(p.get("workout")), "sport": (p.get("workout") or {}).get("sport")}
    return None


def pick_watch(plan: dict[str, Any] | None, today: date, garmin: bool) -> dict[str, Any] | None:
    if not plan or not garmin:
        return None
    last = (today + timedelta(days=WATCH_DAYS - 1)).isoformat()
    found = []
    for _, d, s in iter_sessions(plan):
        if not (today.isoformat() <= d <= last) or not s.get("id"):
            continue
        if s.get("sport") == "rest" or s.get("kind") == "race" or (s.get("garmin") or {}).get("workout_ids"):
            continue
        found.append((d, s))
    if not found:
        return None
    d, s = min(found, key=lambda x: x[0])
    return {"kind": "watch", "label": "Send to watch", "session_id": s["id"], "date": d,
            "title": s.get("title") or "Session", "sport": s.get("sport")}


class QuickActions:
    """Gathers the inputs; each one is a callable so tests can stub it."""

    def __init__(self, *, now: Callable[[str], datetime], clock: Callable[[], float],
                 activities: Callable[[str], tuple[date, list[dict[str, Any]]]] | None = None,
                 checkins: Callable[[str], list[dict[str, Any]]] | None = None,
                 meetups: Callable[[str, datetime], list[dict[str, Any]]] | None = None,
                 friend_posts: Callable[[str], list[dict[str, Any]]] | None = None,
                 name: Callable[[str], str] = lambda u: "A friend",
                 plan: Callable[[str], dict[str, Any] | None] | None = None,
                 garmin: Callable[[str], bool] = lambda u: False) -> None:
        self._now = now
        self._clock = clock
        self._acts = activities
        self._checkins = checkins
        self._meetups = meetups
        self._posts = friend_posts
        self._name = name
        self._plan = plan
        self._garmin = garmin

    def _try(self, uid: str, what: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any] | None:
        try:
            return fn()
        except Exception as e:
            log_event(logger, logging.INFO, "quick_action_failed", user_id=uid, kind=what, error=type(e).__name__)
            return None

    def get(self, uid: str) -> list[dict[str, Any]]:
        now = self._now(uid)
        today = now.date()
        out: list[dict[str, Any] | None] = []
        if self._acts is not None and self._checkins is not None:
            acts, checks = self._acts, self._checkins
            out.append(self._try(uid, "feel", lambda: pick_feel(acts(uid)[1], checks(uid), today)))
        if self._meetups is not None:
            meet = self._meetups
            out.append(self._try(uid, "rsvp", lambda: pick_rsvp(meet(uid, now), now)))
        if self._posts is not None:
            posts = self._posts
            out.append(self._try(uid, "cheer", lambda: pick_cheer(posts(uid), self._clock(), self._name)))
        if self._plan is not None:
            plan = self._plan
            out.append(self._try(uid, "watch", lambda: pick_watch(plan(uid), today, self._garmin(uid))))
        return [x for x in out if x]


__all__ = ["QuickActions", "pick_cheer", "pick_feel", "pick_rsvp", "pick_watch"]
