"""Public events: the ones their owner marked "Public" (events.VISIBILITY), findable by people
in the same area (Local, search) who can say they're going.

Every event is private unless its owner picks Public, so nothing saved before this shows up.
The owner's events doc stays the source of truth: ``sync`` copies the public ones (what a
neighbour needs to show up: name, sport, when, the public place, how it repeats) into one
global ``public-events`` doc keyed ``<owner>:<event id>``, with the owner's city/state from
their home location (the same place Local uses). Making an event private again, deleting it
or the owner moving removes or moves the copy on the next write. Notes stay private.

Read side (``nearby``): same city + state as the viewer (state alone when the viewer has no
city), never the viewer's own, never someone either side blocked, only with a date today or
later (repeating events use their next dates). Going is ``{key: {uid: ts}}``; only someone who
can see the event can mark it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from . import recur, sports

DOC = "public-events"
MAX_PER_OWNER = 30
NEARBY_MAX = 40
_FIELDS = ("name", "kind", "type", "activity", "activity_other", "date", "end_date", "time", "duration_min",
           "location", "neighborhood", "url", "recurring", "intensity")


class PublicEventError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())


def next_dates(e: dict[str, Any], today: date, limit: int = 4) -> list[str]:
    """The event's dates from today on (one-offs: the date while it hasn't passed; a multi-day
    event stays listed until its last day)."""
    try:
        start = date.fromisoformat(str(e.get("date") or ""))
    except ValueError:
        return []
    rule = recur.loose(e.get("recurring"), start)
    if rule:
        return [d.isoformat() for d in recur.dates(rule, start, max(today, start), today + timedelta(days=400), limit=limit)]
    end = start
    if e.get("end_date"):
        try:
            end = date.fromisoformat(str(e["end_date"]))
        except ValueError:
            end = start
    return [max(start, today).isoformat()] if end >= today else []


class PublicEvents:
    def __init__(self, store: Any, *, blocked: Callable[[str, str], bool] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._doc = store.global_doc(DOC)
        self._blocked = blocked or (lambda a, b: False)
        self._clock = clock
        self._lock = threading.Lock()

    # -------------------------------------------------------------- write --
    def sync(self, owner: str, events: list[dict[str, Any]], home: dict[str, str]) -> int:
        """Make the index match the owner's public events; returns how many are listed."""
        city, state = str(home.get("city") or "").strip(), str(home.get("state") or "").strip()
        mine: dict[str, dict[str, Any]] = {}
        if city or state:
            for e in events:
                if e.get("visibility") != "public" or not e.get("id") or not e.get("name"):
                    continue
                item = {k: e.get(k) for k in _FIELDS if e.get(k) not in (None, "")}
                item.update(owner=owner, eid=e["id"], city=city, state=state, updated=int(self._clock()))
                mine[f"{owner}:{e['id']}"] = item
                if len(mine) >= MAX_PER_OWNER:
                    break
        prefix = f"{owner}:"

        def apply(d: dict[str, Any]) -> None:
            items = d.setdefault("items", {})
            for k in [k for k in items if k.startswith(prefix) and k not in mine]:
                items.pop(k, None)
                (d.get("going") or {}).pop(k, None)
            items.update(mine)
        with self._lock:
            self._doc.update(apply)
        return len(mine)

    # --------------------------------------------------------------- read --
    def _visible(self, it: dict[str, Any], viewer: str, city: str, state: str) -> bool:
        if it.get("owner") == viewer or self._blocked(viewer, it.get("owner") or ""):
            return False
        icity, istate = _norm(it.get("city")), _norm(it.get("state"))
        if city:
            return icity == city and (not state or not istate or istate == state)
        return bool(state) and istate == state

    def nearby(self, viewer: str, home: dict[str, str], today: date, *, q: str = "", activity: str = "",
               name: Callable[[str], str | None] | None = None) -> list[dict[str, Any]]:
        city, state = _norm(home.get("city")), _norm(home.get("state"))
        if not city and not state:
            return []
        d = self._doc.load()
        going = d.get("going") or {}
        words = _norm(q).split()
        out = []
        for key, it in (d.get("items") or {}).items():
            if not self._visible(it, viewer, city, state):
                continue
            if activity and it.get("activity") != activity:
                continue
            hay = _norm(" ".join(str(it.get(k) or "") for k in ("name", "neighborhood", "location", "activity_other"))
                        + " " + (sports.label(it.get("activity")) or ""))
            if words and not all(w in hay for w in words):
                continue
            ds = next_dates(it, today)
            if not ds:
                continue
            g = going.get(key) or {}
            rule = recur.loose(it.get("recurring"), None)
            out.append({
                "key": key, "name": it.get("name"), "kind": it.get("kind") or "group_activity",
                "type": it.get("type"), "activity": it.get("activity"),
                "activity_label": it.get("activity_other") or sports.label(it.get("activity")),
                "next_date": ds[0], "next_dates": ds, "time": it.get("time"), "duration_min": it.get("duration_min"),
                "repeat_text": recur.describe(rule) if rule else None,
                "neighborhood": it.get("neighborhood") or "", "location": it.get("location") or "",
                "url": it.get("url") or "", "city": it.get("city") or "", "state": it.get("state") or "",
                "going": len(g), "my_going": viewer in g,
                "host": (name(it["owner"]) if name else None) or "A rabbt member",
            })
        out.sort(key=lambda x: (x["next_date"], x.get("time") or "99", x["name"] or ""))
        return out[:NEARBY_MAX]

    def item_for(self, viewer: str, key: str, home: dict[str, str]) -> dict[str, Any]:
        it = (self._doc.load().get("items") or {}).get(key)
        if not it or not self._visible(it, viewer, _norm(home.get("city")), _norm(home.get("state"))):
            raise PublicEventError("event not found", 404)
        return dict(it)

    def set_going(self, viewer: str, key: str, going: bool, home: dict[str, str]) -> dict[str, Any]:
        self.item_for(viewer, key, home)

        def apply(d: dict[str, Any]) -> int:
            g = d.setdefault("going", {}).setdefault(key, {})
            if going:
                g[viewer] = int(self._clock())
            else:
                g.pop(viewer, None)
            return len(g)
        with self._lock:
            n = self._doc.update(apply)
        return {"key": key, "going": n, "my_going": going}


__all__ = ["DOC", "PublicEventError", "PublicEvents", "next_dates"]
