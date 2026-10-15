"""Live race grade on Rabbit home: the main race's readiness grade with a weekly delta.

Deterministic, no model, never Oura (it only reads ``readiness.compute`` output). Every time
the grade is read (the home card, and the daily 09:00 grade check in ``Moments.tick``) one
snapshot per Monday-start week is upserted in the per-user ``grade_history`` doc: grade,
score, status and each component's score (plus the key-session score per sport). The delta
compares today's grade with the newest snapshot from an earlier week, and the reasons are
the 1-2 component changes that moved the weighted score most ("+ long rides on target",
"- swim volume low").

The race is the main event when it's an upcoming race, else the next upcoming race.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .appstore import AppStore
from .events import is_race
from .readiness import SPORT_WEIGHT, SPORT_WORD

KEEP_WEEKS = 12
KEEP_EVENTS = 8
MIN_MOVE = 3  # component points before it counts as a reason
STATUS_WORD = {"ahead": "ahead", "on_track": "on track", "behind": "behind", "at_risk": "at risk"}
UP = {"fitness": "fitness building", "consistency": "steady weeks", "race_factors": "course prep coming together",
      "health": "recovery looking better"}
DOWN = {"fitness": "fitness slipping", "consistency": "sessions missed", "race_factors": "course needs prep",
        "health": "rough check-ins"}


def week_of(day: date) -> str:
    return (day - timedelta(days=day.weekday())).isoformat()


def snapshot(r: dict[str, Any], today: date) -> dict[str, Any]:
    return {"week": week_of(today), "date": today.isoformat(), "grade": r.get("grade"),
            "score": int(r.get("score") or 0), "status": r.get("status"),
            "comps": {c["id"]: int(c["score"]) for c in r.get("components") or []},
            "weights": {c["id"]: int(c.get("weight") or 0) for c in r.get("components") or []},
            "keys": {k: int(v) for k, v in (r.get("key_sports") or {}).items()}}


def record(doc: dict[str, Any], event_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Upsert ``row`` as this week's snapshot; returns the event's rows (oldest first)."""
    evs = doc.setdefault("events", {})
    rows = [x for x in evs.get(event_id) or [] if isinstance(x, dict) and x.get("week") != row["week"]]
    rows.append(row)
    rows.sort(key=lambda x: x["week"])
    evs[event_id] = rows[-KEEP_WEEKS:]
    if len(evs) > KEEP_EVENTS:
        for k in sorted(evs, key=lambda k: (evs[k] or [{}])[-1].get("date") or "")[: len(evs) - KEEP_EVENTS]:
            del evs[k]
    return evs[event_id]


def reasons(prev: dict[str, Any], cur: dict[str, Any], *, limit: int = 2) -> list[dict[str, str]]:
    """The component changes that moved the weighted score most, in the delta's direction first."""
    cands: list[tuple[float, str, str]] = []  # (impact, sign, text)
    weights = cur.get("weights") or {}
    for cid, now in (cur.get("comps") or {}).items():
        if cid == "key_session":
            continue
        before = (prev.get("comps") or {}).get(cid)
        if before is None or abs(now - before) < MIN_MOVE:
            continue
        up = now > before
        cands.append(((now - before) * weights.get(cid, 0), "+" if up else "-", (UP if up else DOWN)[cid]))
    keys_now, keys_before = cur.get("keys") or {}, prev.get("keys") or {}
    share_total = sum(SPORT_WEIGHT.get(s, 1.0) for s in keys_now) or 1.0
    for sport, now in keys_now.items():
        before = keys_before.get(sport)
        if before is None or abs(now - before) < MIN_MOVE:
            continue
        word = SPORT_WORD.get(sport, sport)
        share = SPORT_WEIGHT.get(sport, 1.0) / share_total if len(keys_now) > 1 else 1.0
        if now > before:
            text = f"long {word}s on target" if now >= 90 else f"long {word}s growing"
        else:
            text = f"{word} volume low" if sport == "swim" else f"long {word}s falling short"
        cands.append(((now - before) * weights.get("key_session", 0) * share, "+" if now > before else "-", text))
    delta = int(cur.get("score") or 0) - int(prev.get("score") or 0)
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    cands.sort(key=lambda c: (c[1] != sign, -abs(c[0])))
    return [{"sign": s, "text": t} for _, s, t in cands[:limit]]


def trend(rows: list[dict[str, Any]], cur: dict[str, Any]) -> dict[str, Any]:
    prev = next((x for x in reversed(rows) if x["week"] < cur["week"]), None)
    if prev is None:
        return {"delta": None, "direction": None, "since": None, "prev_grade": None, "reasons": []}
    delta = int(cur["score"]) - int(prev["score"])
    return {"delta": delta, "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            "since": prev["week"], "prev_grade": prev.get("grade"), "reasons": reasons(prev, cur)}


def pick_race(events: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    up = [e for e in events if (e.get("date") or "") >= today.isoformat() and is_race(e)]
    return next((e for e in up if e.get("main")), None) or (up[0] if up else None)


def view(ev: dict[str, Any], r: dict[str, Any], t: dict[str, Any], today: date) -> dict[str, Any]:
    name = str(ev.get("name") or "Your race")[:40]
    status = STATUS_WORD.get(r.get("status") or "", "")
    weekly = t["since"] == (date.fromisoformat(week_of(today)) - timedelta(days=7)).isoformat()
    return {"event_id": ev.get("id"), "name": name, "date": ev.get("date"), "grade": r.get("grade"),
            "score": r.get("score"), "status": r.get("status"), "confidence": r.get("confidence"),
            "line": " · ".join(x for x in (name, str(r.get("grade") or ""), status) if x),
            "days_to_race": r.get("days_to_race"), **t, "weekly": bool(t["since"]) and weekly}


class GradeTrend:
    def __init__(self, store: AppStore, *, readiness: Callable[[str, str], dict[str, Any]],
                 events: Callable[[str], list[dict[str, Any]]], today: Callable[[str], date]) -> None:
        self._s, self._readiness, self._events, self._today = store, readiness, events, today

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "grade_history")

    def _snap(self, uid: str, ev: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        today = self._today(uid)
        r = self._readiness(uid, ev["id"])
        row = snapshot(r, today)
        rows = self._doc(uid).update(lambda d: [dict(x) for x in record(d, ev["id"], row)])
        return r, trend(rows, row)

    def grade(self, uid: str, event_id: str) -> str | None:
        """For ``Moments.grade`` (daily check): the grade, recording this week's snapshot."""
        ev = next((e for e in self._events(uid) if e.get("id") == event_id), None)
        if ev is None:
            return self._readiness(uid, event_id).get("grade")
        return self._snap(uid, ev)[0].get("grade")

    def live(self, uid: str) -> dict[str, Any] | None:
        today = self._today(uid)
        ev = pick_race(self._events(uid), today)
        if ev is None:
            return None
        r, t = self._snap(uid, ev)
        return view(ev, r, t, today)


__all__ = ["GradeTrend", "pick_race", "reasons", "record", "snapshot", "trend", "view", "week_of"]
