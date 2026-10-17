"""Calendar export for events and the private subscribe feed.

* ``event_ics(ev)``: one event as an .ics file. A repeating event is one VEVENT with RRULE and
  EXDATE (skipped dates); times are floating local time (the athlete's own clock). UID is stable
  per event and SEQUENCE grows on every edit, so importing again replaces the old copy.
* ``feed_ics(events, plan, today)``: the subscribe feed: every event plus plan sessions from two
  weeks back to four months ahead, so Google / Apple calendars stay in sync on their own.
* ``CalSub``: one secret feed link per person. Only a SHA-256 of the token is stored (per-user doc
  ``calsub`` and the global index ``calsub-index``); creating a new link replaces the old one, and
  revoking deletes it, so an old URL stops working at once.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import recur
from .planformats import _fold, _ics_escape, _ics_event, iter_sessions

FEED_BACK_DAYS = 14
FEED_AHEAD_DAYS = 120
TOKEN_BYTES = 24


def _stamp(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _where(ev: dict[str, Any]) -> str:
    bits = [str(ev.get(k) or "").strip() for k in ("at", "location", "neighborhood")]
    out: list[str] = []
    for b in bits:
        if b and b.lower() not in (x.lower() for x in out):
            out.append(b)
    return ", ".join(out)


def _start_time(ev: dict[str, Any]) -> tuple[int, int] | None:
    t = ev.get("time")
    if isinstance(t, str) and len(t) == 5 and t[2] == ":" and t[:2].isdigit() and t[3:].isdigit():
        return int(t[:2]), int(t[3:])
    return None


def event_lines(ev: dict[str, Any], stamp: str) -> list[str]:
    """One VEVENT for an event (repeating events: one VEVENT with RRULE/EXDATE)."""
    try:
        start = date.fromisoformat(ev.get("date") or "")
    except ValueError:
        return []
    rule = recur.loose(ev.get("recurring"), start)
    first = recur.first_date(rule, start) if rule else start
    if first is None:
        return []
    hm = _start_time(ev)
    lines = ["BEGIN:VEVENT", f"UID:ev-{ev.get('id')}@rabbit", f"DTSTAMP:{stamp}",
             f"SEQUENCE:{int(ev.get('seq') or 0)}"]
    if hm:
        dt = datetime(first.year, first.month, first.day, hm[0], hm[1])
        mins = int(ev.get("duration_min") or 60)
        lines += [f"DTSTART:{dt:%Y%m%dT%H%M%S}", f"DTEND:{dt + timedelta(minutes=mins):%Y%m%dT%H%M%S}"]
    else:
        end = first + timedelta(days=1)
        if not rule and ev.get("end_date"):
            try:
                end = date.fromisoformat(ev["end_date"]) + timedelta(days=1)
            except ValueError:
                pass
        lines += [f"DTSTART;VALUE=DATE:{first:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
    if rule:
        lines.append(f"RRULE:{recur.rrule(rule, timed=bool(hm))}")
        for x in rule.get("except") or []:
            d = date.fromisoformat(x)
            lines.append(f"EXDATE:{d:%Y%m%d}T{hm[0]:02d}{hm[1]:02d}00" if hm else f"EXDATE;VALUE=DATE:{d:%Y%m%d}")
    lines.append(f"SUMMARY:{_ics_escape(str(ev.get('name') or 'Event'))}")
    where = _where(ev)
    if where:
        lines.append(f"LOCATION:{_ics_escape(where)}")
    desc = [str(ev.get("notes") or "").strip(), str(ev.get("url") or "").strip(), "From Rabbit"]
    lines.append(f"DESCRIPTION:{_ics_escape(chr(10).join(x for x in desc if x))}")
    url = str(ev.get("url") or "")
    if url.startswith(("https://", "http://")):
        lines.append(f"URL:{url}")
    lines.append("END:VEVENT")
    return lines


def _wrap(name: str, body: list[str]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Rabbit//Events//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(name)}", *body, "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def event_ics(ev: dict[str, Any], *, now: datetime | None = None) -> str:
    return _wrap(str(ev.get("name") or "Rabbit"), event_lines(ev, _stamp(now)))


def feed_ics(events: list[dict[str, Any]], plan: dict[str, Any] | None, today: date, *,
             now: datetime | None = None) -> str:
    """Events + plan sessions (today - 14 days .. today + 120 days), for a calendar subscription."""
    stamp = _stamp(now)
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seq = max(0, int(when.timestamp() // 60) - 29_000_000)
    body: list[str] = []
    for ev in events:
        body += event_lines(ev, stamp)
    lo, hi = (today - timedelta(days=FEED_BACK_DAYS)).isoformat(), (today + timedelta(days=FEED_AHEAD_DAYS)).isoformat()
    for _, d, s in iter_sessions(plan or {}):
        if s.get("sport") != "rest" and lo <= d <= hi:
            body += _ics_event(s, d, stamp, seq)
    return _wrap("Rabbit", body)


def google_url(ev: dict[str, Any]) -> str | None:
    """Google Calendar's own "add event" page, prefilled (recurrence included)."""
    from urllib.parse import urlencode
    try:
        start = date.fromisoformat(ev.get("date") or "")
    except ValueError:
        return None
    rule = recur.loose(ev.get("recurring"), start)
    first = recur.first_date(rule, start) if rule else start
    if first is None:
        return None
    hm = _start_time(ev)
    if hm:
        dt = datetime(first.year, first.month, first.day, hm[0], hm[1])
        dates = f"{dt:%Y%m%dT%H%M%S}/{dt + timedelta(minutes=int(ev.get('duration_min') or 60)):%Y%m%dT%H%M%S}"
    else:
        dates = f"{first:%Y%m%d}/{first + timedelta(days=1):%Y%m%d}"
    q = {"action": "TEMPLATE", "text": str(ev.get("name") or "Event"), "dates": dates,
         "details": str(ev.get("notes") or "From Rabbit")[:500], "location": _where(ev)}
    if rule:
        q["recur"] = f"RRULE:{recur.rrule(rule, timed=bool(hm))}"
    return "https://calendar.google.com/calendar/render?" + urlencode(q)


class CalSub:
    """Per-user secret calendar feed tokens (only hashes are stored)."""

    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _index(self):
        return self._s.global_doc("calsub-index")

    def status(self, uid: str) -> dict[str, Any] | None:
        d = self._s.user_doc(uid, "calsub").load()
        return {"created": d["created"]} if d.get("hash") else None

    def create(self, uid: str) -> str:
        """A new secret link (the old one, if any, stops working)."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        h = self._hash(token)
        old: dict[str, Any] = {}

        def put(d: dict[str, Any]) -> None:
            old.update(d)
            d.clear()
            d.update(hash=h, created=int(self._clock()))
        self._s.user_doc(uid, "calsub").update(put)

        def idx(d: dict[str, Any]) -> None:
            if old.get("hash"):
                d.pop(old["hash"], None)
            d[h] = uid
        self._index().update(idx)
        return token

    def revoke(self, uid: str) -> None:
        old: dict[str, Any] = {}

        def drop(d: dict[str, Any]) -> None:
            old.update(d)
            d.clear()
        self._s.user_doc(uid, "calsub").update(drop)
        if old.get("hash"):
            self._index().update(lambda d: d.pop(old["hash"], None))

    def lookup(self, token: str) -> str | None:
        if not isinstance(token, str) or not 20 <= len(token) <= 80:
            return None
        h = self._hash(token)
        uid = self._index().load().get(h)
        if not uid:
            return None
        # The user's own doc must still agree (a revoke that only half finished never serves).
        return uid if self._s.user_doc(uid, "calsub").load().get("hash") == h else None


__all__ = ["CalSub", "event_ics", "feed_ics", "google_url", "event_lines"]
