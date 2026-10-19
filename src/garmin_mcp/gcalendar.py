"""Google Calendar (read-only), so the plan can work around real life.

The athlete connects from Settings; the OAuth round trip reuses Rabbit's Google client and
callback (``WebAuth.start_calendar``), asking only for ``calendar.readonly``. The refresh
token is stored encrypted per user (``gcal`` doc). Rabbit reads the primary calendar's
events for the next few weeks and reduces them to:

* busy minutes per day (timed, opaque events), and
* likely travel: multi-day all-day events, or events whose title says flight, trip,
  travel, vacation, conference, hotel, out of office, etc.

Event titles are only used for the travel heuristics and shown back to the athlete; the
coach model sees busy hours and travel windows (with the title), nothing else.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import httpx2

from .appstore import AppStore
from .logs import log_event
from .providers import GarminError

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MAX_DAYS = 70
CACHE_S = 600
MAX_PAGES = 4  # of 250 events each
TRAVEL_WORDS = re.compile(
    r"\b(flight|fly|flying|trip|travel|traveling|travelling|vacation|holiday|conference|summit|"
    r"offsite|off-site|hotel|airbnb|ooo|out of office|pto|away|camp)\b|✈", re.I)


def _zone(tz: str | None):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(tz or "UTC")
    except Exception:
        return ZoneInfo("UTC")


class CalendarError(GarminError):
    """Message safe to show the athlete (subclasses GarminError so routes report it)."""


class CalendarNotConnected(CalendarError):
    pass


def summarize(events: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    """Busy minutes per day, travel windows, and each day's busy blocks as local
    [start_min, end_min] pairs (times only, no titles: calinsights.py finds free windows)."""
    busy: dict[str, int] = defaultdict(int)
    blocks: dict[str, list[list[int]]] = defaultdict(list)
    travel: list[dict[str, Any]] = []
    for e in events:
        s, t = e["start"], e["end"]
        if e["all_day"]:
            d0, d1 = date.fromisoformat(s), date.fromisoformat(t) - timedelta(days=1)  # end exclusive
            multi = (d1 - d0).days >= 1
            if multi or TRAVEL_WORDS.search(e["title"]):
                travel.append({"start": d0.isoformat(), "end": d1.isoformat(), "title": e["title"][:80],
                               "location": e.get("location", "")[:80]})
            continue
        ds, de = datetime.fromisoformat(s), datetime.fromisoformat(t)
        if TRAVEL_WORDS.search(e["title"]):
            travel.append({"start": ds.date().isoformat(), "end": de.date().isoformat(),
                           "title": e["title"][:80], "location": e.get("location", "")[:80]})
        if not e.get("busy", True):
            continue
        cur = ds
        while cur < de:
            day_end = datetime.combine(cur.date() + timedelta(days=1), datetime.min.time(), tzinfo=cur.tzinfo)
            seg = min(de, day_end)
            if start <= cur.date() <= end:
                busy[cur.date().isoformat()] += int((seg - cur).total_seconds() // 60)
                a = cur.hour * 60 + cur.minute
                b = a + int((seg - cur).total_seconds() // 60)
                blocks[cur.date().isoformat()].append([a, min(b, 24 * 60)])
            cur = seg
    # Merge overlapping/adjacent travel windows.
    travel.sort(key=lambda x: x["start"])
    merged: list[dict[str, Any]] = []
    for t in travel:
        if merged and t["start"] <= (date.fromisoformat(merged[-1]["end"]) + timedelta(days=1)).isoformat():
            m = merged[-1]
            m["end"] = max(m["end"], t["end"])
            if t["title"] not in m["title"]:
                m["title"] = f"{m['title']} · {t['title']}"[:120]
        else:
            merged.append(dict(t))
    merged = [t for t in merged if t["end"] >= start.isoformat() and t["start"] <= end.isoformat()]
    merged_blocks: dict[str, list[list[int]]] = {}
    for day, bl in sorted(blocks.items()):
        out_b: list[list[int]] = []
        for a, b in sorted(bl):
            if out_b and a <= out_b[-1][1]:
                out_b[-1][1] = max(out_b[-1][1], b)
            else:
                out_b.append([a, b])
        merged_blocks[day] = out_b
    return {"busy": {k: min(v, 24 * 60) for k, v in sorted(busy.items())}, "travel": merged,
            "blocks": merged_blocks}


def compact_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("status") == "cancelled":
        return None
    st, en = raw.get("start") or {}, raw.get("end") or {}
    all_day = "date" in st
    s = st.get("date") or st.get("dateTime")
    t = en.get("date") or en.get("dateTime")
    if not s or not t:
        return None
    return {"title": str(raw.get("summary") or "Busy"), "start": s, "end": t, "all_day": all_day,
            "location": str(raw.get("location") or ""),
            "busy": raw.get("transparency") != "transparent" and raw.get("eventType") != "workingLocation"}


class GoogleCalendar:
    def __init__(self, store: AppStore, client_id: str, client_secret: str, *,
                 http: httpx2.AsyncClient | None = None, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._id = client_id
        self._secret = client_secret
        self._http = http
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "gcal")

    def connected(self, user_id: str) -> bool:
        return bool(self._doc(user_id).load().get("refresh_token"))

    def save_tokens(self, user_id: str, tok: dict[str, Any]) -> None:
        if SCOPE not in str(tok.get("scope", "")).split():
            raise CalendarError("Calendar access wasn't granted. Try again and tick the calendar box.")
        rt = tok.get("refresh_token")
        if not rt:
            raise CalendarError("Google didn't return a refresh token. Remove rabbt's access in your "
                                "Google account, then connect again.")
        now = int(self._clock())
        self._doc(user_id).save({"refresh_token": rt, "access_token": tok.get("access_token"),
                                 "expires": now + int(tok.get("expires_in", 3000)) - 60,
                                 "connected_at": now})
        self._cache.pop(user_id, None)

    async def disconnect(self, user_id: str) -> None:
        d = self._doc(user_id).load()
        self._doc(user_id).delete()
        self._cache.pop(user_id, None)
        if d.get("refresh_token"):
            client = self._client()
            try:
                await client.post(REVOKE_URL, data={"token": d["refresh_token"]})
            except Exception:  # best effort; the token is gone from our side either way
                pass
            finally:
                if self._http is None:
                    await client.aclose()

    def last_read(self, user_id: str) -> float | None:
        """When data was last read for this user (wall clock; in memory, None after a restart)."""
        hit = self._cache.get(user_id)
        return hit[0] if hit else None

    def forget(self, user_id: str) -> None:
        """Drop the cached read so the next one goes to the provider ("Sync now")."""
        self._cache.pop(user_id, None)

    def _client(self) -> httpx2.AsyncClient:
        return self._http or httpx2.AsyncClient(timeout=15)

    async def _access(self, user_id: str) -> str:
        d = self._doc(user_id).load()
        if not d.get("refresh_token"):
            raise CalendarNotConnected("Google Calendar isn't connected.")
        if d.get("access_token") and d.get("expires", 0) > self._clock():
            return str(d["access_token"])
        client = self._client()
        try:
            r = await client.post(TOKEN_URL, data={"client_id": self._id, "client_secret": self._secret,
                                                   "refresh_token": d["refresh_token"],
                                                   "grant_type": "refresh_token"})
        finally:
            if self._http is None:
                await client.aclose()
        if r.status_code in (400, 401):
            self._doc(user_id).delete()
            raise CalendarNotConnected("Google Calendar access was revoked. Connect it again in settings.")
        r.raise_for_status()
        tok = r.json()
        d.update(access_token=tok["access_token"],
                 expires=int(self._clock()) + int(tok.get("expires_in", 3000)) - 60)
        self._doc(user_id).save(d)
        return str(tok["access_token"])

    async def summary(self, user_id: str, today: date, days: int = 42, tz: str | None = None) -> dict[str, Any]:
        days = max(7, min(MAX_DAYS, days))
        hit = self._cache.get(user_id)
        if hit and self._clock() - hit[0] < CACHE_S and hit[1].get("days") == days:
            return hit[1]
        token = await self._access(user_id)
        start, end = today, today + timedelta(days=days - 1)
        zone = _zone(tz)
        t0 = datetime.combine(start, datetime.min.time(), tzinfo=zone)
        t1 = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=zone)
        params = {"timeMin": t0.isoformat(), "timeMax": t1.isoformat(),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": "250",
                  "fields": "nextPageToken,items(summary,start,end,location,transparency,eventType,status)"}
        if tz:
            params["timeZone"] = tz
        items: list[dict[str, Any]] = []
        client = self._client()
        try:
            for _ in range(MAX_PAGES):
                r = await client.get(EVENTS_URL, params=params, headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 403:
                    log_event(logger, logging.WARNING, "gcal_forbidden", user_id=user_id)
                    raise CalendarError("Google Calendar refused the request. The Calendar API may need "
                                        "to be enabled for this project.")
                if r.status_code == 401:
                    self._doc(user_id).delete()
                    raise CalendarNotConnected("Google Calendar access expired. Connect it again in settings.")
                r.raise_for_status()
                body = r.json()
                items += body.get("items", [])
                if not body.get("nextPageToken"):
                    break
                params = params | {"pageToken": body["nextPageToken"]}
        finally:
            if self._http is None:
                await client.aclose()
        events = [e for e in (compact_event(x) for x in items) if e]
        out = {"connected": True, "days": days, "start": start.isoformat(), "end": end.isoformat()}
        out |= summarize(events, start, end)
        self._cache[user_id] = (self._clock(), out)
        return out


__all__ = ["GoogleCalendar", "CalendarError", "CalendarNotConnected", "summarize", "compact_event", "SCOPE"]
