"""Privacy-first usage counts for the Rabbit web app (our own server, no third parties).

The app batches tiny events ``{name, props, ts}`` to ``POST /app/api/usage`` (``/app/api/events``
is the race calendar). Only names in ``EVENTS`` count, and only their whitelisted prop keys with
whitelisted values: no free text, no health data, no location, nothing else gets through.
Nothing is kept per event: each batch only bumps daily counters in the global ``usage`` doc.

Daily active users: ``sha256(salt_of_today | user_id | key)`` in today's ``seen`` set dedupes a
person (and "unique users per key", e.g. per setup step) within the day. The salt is random and
replaced at the first event of each UTC day, and the old ``seen`` set is dropped with it, so
yesterday's hashes can't be linked to today's or to anyone.

WAU / MAU / retention need to know when *you* were last active, so each person's own encrypted
doc ``usage`` holds two dates, ``{first, last}`` (no events, no counts). On someone's first
event of a day: ``dau[today] += 1``; their activity covers WAU for today..today+6 and MAU for
today..today+29, so those future days are bumped only where an earlier active day didn't
already cover them (``covered_days``); a first-ever day bumps ``new``; activity exactly 1 or 7
days after the first day bumps that cohort day's ``r1`` / ``r7``.

Counters are kept ``KEEP_DAYS``. Respect: Do Not Track / Global Privacy Control headers and the
"Don't count my usage" setting (``profile.usage_off``) drop the batch; coach accounts never get
here (``_api`` 403s them). The owner-only summary (``summary``) is for ``access`` owners.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .appstore import AppStore

# feed + clubs replaced community + races (Schedule holds events); old names still count for old clients
TABS = frozenset({"rabbit", "plan", "feed", "clubs", "community", "races", "progress", "me"})
CARDS = frozenset({"upnext", "ring", "race_grade", "reward", "actions"})
SETUP_STEPS = ("intro", "race", "goal", "you", "numbers", "week", "rhythm", "review")
SHARES = frozenset({"workout", "post", "month", "race", "plan", "invite", "profile"})
RSVPS = frozenset({"meetup", "group", "race"})
PUSHES = frozenset({"coach", "recap", "community", "workout", "brief", "other"})

# name -> {prop key -> allowed values}. Anything else is dropped.
EVENTS: dict[str, dict[str, frozenset[str]]] = {
    "app_open": {},
    "tab_view": {"tab": TABS},
    "card_tap": {"card": CARDS},
    "setup_step": {"step": frozenset(SETUP_STEPS)},
    "setup_complete": {},
    "invite_join": {},
    "share": {"what": SHARES},
    "cheer": {},
    "rsvp": {"kind": RSVPS},
    "push_open": {"kind": PUSHES},
    # traction.py: a person's firsts (counted once per person there)
    "milestone": {"what": frozenset({"area_set", "rsvp", "run_posted", "plan_built", "post", "follow", "watch_connected"})},
}

MAX_BATCH = 50          # events per request (more are ignored)
MAX_BODY = 16 * 1024    # bytes per request
MAX_PROPS = 3
PER_MINUTE = 120        # events per person per rolling minute
PER_DAY = 3000          # events per person per UTC day
PAST_S = 2 * 86400      # an event's ts may lag this much (queued offline) ...
FUTURE_S = 600          # ... or run this far ahead (clock skew); else dropped
KEEP_DAYS = 90
WAU_DAYS, MAU_DAYS = 7, 30
WINDOW = 30             # dashboard days


def clean_event(raw: Any, now_s: float) -> tuple[str, dict[str, str]] | None:
    """One validated event or None. ``ts`` is ms since the epoch."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or name not in EVENTS:
        return None
    ts = raw.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        return None
    if not (now_s - PAST_S <= ts / 1000 <= now_s + FUTURE_S):
        return None
    allowed = EVENTS[name]
    props: dict[str, str] = {}
    raw_props = raw.get("props")
    if isinstance(raw_props, dict):
        for k, v in list(raw_props.items())[:16]:
            if k in allowed and isinstance(v, str) and v in allowed[k] and len(props) < MAX_PROPS:
                props[k] = v
    return name, props


def clean_batch(body: Any, now_s: float) -> list[tuple[str, dict[str, str]]]:
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise ValueError("events")
    out = []
    for raw in body["events"][:MAX_BATCH]:
        ev = clean_event(raw, now_s)
        if ev is not None:
            out.append(ev)
    return out


def event_keys(name: str, props: dict[str, str]) -> list[str]:
    return [name, *(f"{name}.{k}={v}" for k, v in sorted(props.items()))]


def covered_days(today: date, prev: date | None, span: int) -> list[date]:
    """Days whose rolling ``span``-day active count gains this person by being active
    ``today`` when they were last active on ``prev`` (those already covered are skipped)."""
    start = today if prev is None else max(today, prev + timedelta(days=span))
    return [start + timedelta(days=i) for i in range((today + timedelta(days=span) - start).days)]


def _d(s: str) -> date:
    return date.fromisoformat(s)


class RateLimit:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._recent: dict[str, deque[float]] = {}
        self._daily: dict[tuple[str, str], int] = {}

    def take(self, uid: str, n: int) -> int:
        """How many of ``n`` events ``uid`` may record now."""
        now = self._clock()
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        with self._lock:
            q = self._recent.setdefault(uid, deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(self._daily) > 20000:
                self._daily = {k: v for k, v in self._daily.items() if k[1] == day}
            used = self._daily.get((uid, day), 0)
            ok = max(0, min(n, PER_MINUTE - len(q), PER_DAY - used))
            q.extend([now] * ok)
            self._daily[(uid, day)] = used + ok
            return ok


class Usage:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time,
                 salt: Callable[[], str] = lambda: secrets.token_hex(16)) -> None:
        self._store = store
        self._clock = clock
        self._new_salt = salt
        self.limit = RateLimit(clock)

    def today(self) -> date:
        return datetime.fromtimestamp(self._clock(), UTC).date()

    # -------------------------------------------------------------- write --
    def record(self, uid: str, body: Any) -> int:
        """Validate and count a batch for ``uid``; returns how many events counted."""
        now = self._clock()
        events = clean_batch(body, now)
        events = events[: self.limit.take(uid, len(events))]
        if not events:
            return 0
        today = self.today()
        mine = self._store.user_doc(uid, "usage")

        def fn(doc: dict[str, Any]) -> None:
            salt = doc.get("salt") or {}
            if salt.get("day") != today.isoformat():  # rotate: yesterday's hashes are gone
                salt = doc["salt"] = {"day": today.isoformat(), "v": self._new_salt()}
                doc["seen"] = []
                cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
                doc["days"] = {k: v for k, v in (doc.get("days") or {}).items() if k >= cutoff}
            seen = set(doc.get("seen") or [])
            days: dict[str, dict[str, Any]] = doc.setdefault("days", {})

            def day(d: date) -> dict[str, Any]:
                return days.setdefault(d.isoformat(), {})

            def h(key: str) -> str:
                return hashlib.sha256(f"{salt['v']}|{uid}|{key}".encode()).hexdigest()[:20]

            t = day(today)
            n, u = t.setdefault("n", {}), t.setdefault("u", {})
            for name, props in events:
                for key in event_keys(name, props):
                    n[key] = n.get(key, 0) + 1
                    hk = h(key)
                    if hk not in seen:
                        seen.add(hk)
                        u[key] = u.get(key, 0) + 1
            me = h("")
            if me not in seen:  # first event today: daily/rolling actives, retention
                seen.add(me)
                p = mine.load()
                first = _d(p["first"]) if p.get("first") else None
                prev = _d(p["last"]) if p.get("last") else None
                t["dau"] = t.get("dau", 0) + 1
                if first is None:
                    first = today
                    t["new"] = t.get("new", 0) + 1
                for key, span in (("wau", WAU_DAYS), ("mau", MAU_DAYS)):
                    for d in covered_days(today, prev, span):
                        x = day(d)
                        x[key] = x.get(key, 0) + 1
                for key, k in (("r1", 1), ("r7", 7)):
                    if (today - first).days == k:
                        c = day(first)
                        c[key] = c.get(key, 0) + 1
                mine.save({"first": first.isoformat(), "last": today.isoformat()})
            doc["seen"] = sorted(seen)
        self._store.global_doc("usage").update(fn)
        return len(events)

    def forget(self, uid: str) -> None:
        """Opting out also drops your own first/last dates."""
        self._store.user_doc(uid, "usage").delete()

    # ------------------------------------------------------------- read --
    def summary(self) -> dict[str, Any]:
        return summarize(self._store.global_doc("usage").load().get("days") or {}, self.today())


def _sum(days: Iterable[dict[str, Any]], part: str, key: str) -> int:
    return sum(int((d.get(part) or {}).get(key, 0)) for d in days)


def retention(days: dict[str, dict[str, Any]], today: date, k: int, window: int = WINDOW) -> dict[str, Any]:
    """Of the people first seen in the window whose day ``k`` is complete (before today),
    how many came back exactly ``k`` days later."""
    cohort = returned = 0
    for i in range(k + 1, window + k + 1):
        d = days.get((today - timedelta(days=i)).isoformat()) or {}
        cohort += int(d.get("new", 0))
        returned += int(d.get(f"r{k}", 0))
    return {"cohort": cohort, "returned": returned, "pct": round(100 * returned / cohort) if cohort else None}


def summarize(days: dict[str, dict[str, Any]], today: date) -> dict[str, Any]:
    span = [(today - timedelta(days=i)).isoformat() for i in range(WINDOW - 1, -1, -1)]
    rows = [days.get(s) or {} for s in span]
    series = [{"date": s, "dau": int(r.get("dau", 0)), "wau": int(r.get("wau", 0)), "mau": int(r.get("mau", 0))}
              for s, r in zip(span, rows, strict=True)]
    steps = [{"step": s, "users": _sum(rows, "u", f"setup_step.step={s}")} for s in SETUP_STEPS]
    steps.append({"step": "complete", "users": _sum(rows, "u", "setup_complete")})
    top = steps[0]["users"] or max((s["users"] for s in steps), default=0)
    for s in steps:
        s["pct"] = round(100 * s["users"] / top) if top else None

    def ranked(event: str, key: str, values: Iterable[str]) -> list[dict[str, Any]]:
        out = [{"id": v, "taps": _sum(rows, "n", f"{event}.{key}={v}"), "users": _sum(rows, "u", f"{event}.{key}={v}")}
               for v in values]
        return sorted((o for o in out if o["taps"]), key=lambda o: (-o["taps"], o["id"]))

    return {
        "today": today.isoformat(), "days": WINDOW,
        "now": series[-1],
        "series": series,
        "retention": {"d1": retention(days, today, 1), "d7": retention(days, today, 7)},
        "funnel": steps,
        "cards": ranked("card_tap", "card", sorted(CARDS)),
        "tabs": ranked("tab_view", "tab", sorted(TABS)),
        "events": {name: _sum(rows, "n", name) for name in EVENTS},
        "new_users": sum(int(r.get("new", 0)) for r in rows),
    }


__all__ = ["EVENTS", "Usage", "clean_batch", "clean_event", "covered_days", "retention", "summarize"]
