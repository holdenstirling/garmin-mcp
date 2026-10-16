"""Search everywhere (``GET /app/api/search?q=``), deterministic, no model, no Garmin calls.

Groups, each capped at ``PER_GROUP`` and each best effort (a failing source is just empty):

* ``people``: people I follow or who follow me (social.people), matched on first name.
* ``clubs``: my clubs, clubs I could join (clubs.discover, which already skips blocked owners
  and full clubs), and the public clubs & leagues directory for my metro.
* ``events``: my races and events (events.list).
* ``sessions``: my plan's sessions (title, kind, sport, date), the nearest dates first.
* ``workouts``: my past workouts from the cached activity list (stats.activities).

Matching is case-insensitive on every word of the query (all must appear), min 2 characters.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from .planbuilder import iter_sessions
from .stats import _rows

logger = logging.getLogger(__name__)

PER_GROUP = 5
MIN_LEN = 2
MAX_LEN = 60
GROUPS = ("people", "clubs", "events", "sessions", "workouts")
SPORT_WORD = {"run": "run running", "bike": "bike ride cycling", "swim": "swim swimming",
              "brick": "brick", "strength": "strength gym", "rest": "rest", "other": "workout"}


def norm(q: Any) -> str:
    return " ".join(str(q or "").lower().split())[:MAX_LEN]


def matches(words: list[str], *fields: Any) -> bool:
    hay = " ".join(str(f or "") for f in fields).lower()
    return all(w in hay for w in words)


def _safe(name: str, fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        return fn()
    except Exception:  # one broken source never breaks search
        logger.warning("search source %s failed", name, exc_info=True)
        return []


class Search:
    def __init__(self, *, today: Callable[[str], date],
                 people: Callable[[str], dict[str, Any]] | None = None,
                 person: Callable[[str], dict[str, Any] | None] | None = None,
                 clubs: Callable[[str, str], dict[str, Any]] | None = None,
                 directory: Callable[[str], list[dict[str, Any]]] | None = None,
                 events: Callable[[str], list[dict[str, Any]]] | None = None,
                 plan: Callable[[str], dict[str, Any] | None] | None = None,
                 activities: Callable[[str], list[dict[str, Any]]] | None = None) -> None:
        self._today, self._people, self._person = today, people, person
        self._clubs, self._directory, self._events = clubs, directory, events
        self._plan, self._acts = plan, activities

    def run(self, uid: str, q: Any) -> dict[str, Any]:
        query = norm(q)
        out: dict[str, Any] = {"q": query, **{g: [] for g in GROUPS}}
        if len(query) < MIN_LEN:
            return out
        words = query.split()
        out["people"] = _safe("people", lambda: self.people(uid, words))
        out["clubs"] = _safe("clubs", lambda: self.clubs(uid, query, words))
        out["events"] = _safe("events", lambda: self.events(uid, words))
        out["sessions"] = _safe("sessions", lambda: self.sessions(uid, words))
        out["workouts"] = _safe("workouts", lambda: self.workouts(uid, words))
        return out

    def people(self, uid: str, words: list[str]) -> list[dict[str, Any]]:
        if self._people is None or self._person is None:
            return []
        lists = self._people(uid)
        seen: dict[str, str] = {}
        for key, rel in (("following", "following"), ("followers", "follows you")):
            for e in lists.get(key) or []:
                other = e.get("user_id")
                if other and other != uid and other not in (lists.get("blocked") or []):
                    seen.setdefault(other, rel)
        out = []
        for other, rel in seen.items():
            p = self._person(other)
            if p and matches(words, p.get("name")):
                out.append({**p, "relation": rel})
        out.sort(key=lambda p: str(p.get("name") or "").lower())
        return out[:PER_GROUP]

    def clubs(self, uid: str, query: str, words: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._clubs is not None:
            ov = self._clubs(uid, query)
            for c in ov.get("clubs") or []:
                if c.get("id") and matches(words, c.get("name"), c.get("city")):
                    out.append({"id": c["id"], "name": c.get("name") or "Club", "city": c.get("city") or "",
                                "members": c.get("members") if isinstance(c.get("members"), int) else None,
                                "mine": True, "source": "club"})
            for c in ov.get("discover") or []:
                if c.get("id") and matches(words, c.get("name"), c.get("city")):
                    out.append({"id": c["id"], "name": c.get("name") or "Club", "city": c.get("city") or "",
                                "members": c.get("members") if isinstance(c.get("members"), int) else None,
                                "mine": False, "source": "club"})
        if self._directory is not None and len(out) < PER_GROUP:
            for x in self._directory(uid):
                if matches(words, x.get("name"), x.get("kind_label"), x.get("meet_spot"), x.get("description")):
                    out.append({"id": x["id"], "name": x.get("name") or "Group", "city": x.get("meet_spot") or "",
                                "kind": x.get("kind_label") or "Group", "mine": False, "source": "directory"})
        return out[:PER_GROUP]

    def events(self, uid: str, words: list[str]) -> list[dict[str, Any]]:
        if self._events is None:
            return []
        today = self._today(uid).isoformat()
        rows = [e for e in self._events(uid)
                if matches(words, e.get("title") or e.get("name"), e.get("location"), e.get("distance"), e.get("sport"))]
        # upcoming first (soonest), then past (most recent)
        day = lambda e: str(e.get("date") or "")  # noqa: E731
        rows = sorted((e for e in rows if day(e) >= today), key=day) + \
            sorted((e for e in rows if day(e) < today), key=day, reverse=True)
        return [{"id": e.get("id"), "title": e.get("title") or e.get("name") or "Event", "date": e.get("date"),
                 "location": e.get("location") or "", "kind": e.get("kind") or "race",
                 "past": str(e.get("date") or "") < today} for e in rows[:PER_GROUP]]

    def sessions(self, uid: str, words: list[str]) -> list[dict[str, Any]]:
        plan = self._plan(uid) if self._plan is not None else None
        if not plan:
            return []
        today = self._today(uid)
        rows = []
        for _, d, s in iter_sessions(plan):
            if s.get("sport") == "rest":
                continue
            if matches(words, s.get("title"), s.get("kind"), SPORT_WORD.get(str(s.get("sport")), s.get("sport")),
                       s.get("detail")):
                try:
                    gap = abs((date.fromisoformat(d) - today).days)
                except ValueError:
                    continue
                rows.append((gap, d, s))
        rows.sort(key=lambda r: (r[0], r[1]))
        return [{"id": s.get("id"), "date": d, "title": s.get("title") or "Session", "sport": s.get("sport"),
                 "kind": s.get("kind"), "minutes": s.get("minutes")} for _, d, s in rows[:PER_GROUP]]

    def workouts(self, uid: str, words: list[str]) -> list[dict[str, Any]]:
        if self._acts is None:
            return []
        rows = [r for r in _rows(self._acts(uid))
                if matches(words, r["name"], SPORT_WORD.get(r["sport"], r["sport"]), r["raw"], r["date"].isoformat())]
        rows.sort(key=lambda r: (r["date"], str(r["id"])), reverse=True)
        return [{"id": r["id"], "date": r["date"].isoformat(), "name": r["name"], "sport": r["sport"],
                 "minutes": round(r["min"]) or None, "km": round(r["km"], 2) or None} for r in rows[:PER_GROUP]]


__all__ = ["Search", "GROUPS", "PER_GROUP", "norm", "matches"]
