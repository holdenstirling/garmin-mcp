"""One workout model for every source, and the rule that keeps a workout from counting twice.

Garmin is the primary source (``GarminService`` + the poller sync it on their own). Other
connected sources add workouts Garmin doesn't have: today that is **Oura** (v2
``usercollection/workout``); Whoop, Coros and Apple Health are "Coming soon" (``demand.py``).

Model (``Workout``-shaped dict)::

    {"key": "oura:abc", "source": "oura", "id": "abc", "sport": "run", "name": "Running",
     "start": "2026-10-13T07:00:00", "minutes": 45, "km": 8.0, "avg_hr": 150, "calories": 520}

``start`` is the athlete's local wall time (naive ISO, like Garmin's ``startTimeLocal``).

Same workout (``same_workout``): same sport family, starts within ``START_WINDOW_S`` (10 min) and
the time ranges overlap. When two sources saw it, the richer one wins (``PRIORITY``: Garmin first),
so a run recorded on a Garmin watch and auto-detected by an Oura ring counts once.

Privacy (Oura's API agreement, section 4(d), see ``oura.py``): workouts imported from Oura are
**display-only**. They are stored per user (``extworkouts`` doc, encrypted) and shown in the Day
view ("From Oura") and, when "Share my workouts with friends" is on, as the same compact feed
card (sport, distance, time; never heart rate). They never enter ``GarminService`` /
``Stats.activities`` / plan status / agent tools, so nothing from Oura reaches Rabbit's AI.
Disconnecting Oura deletes them (``drop_source``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

PRIORITY = ("garmin", "coros", "whoop", "apple", "oura", "manual")
START_WINDOW_S = 600
KEEP_DAYS = 120
MAX_ITEMS = 400
DOC = "extworkouts"

_OURA_SPORT = {
    "running": "run", "treadmill_running": "run", "trail_running": "run", "track_and_field": "run",
    "cycling": "bike", "indoor_cycling": "bike", "mountain_biking": "bike", "road_biking": "bike",
    "swimming": "swim", "open_water_swimming": "swim",
    "walking": "walk", "hiking": "hike",
    "strength_training": "strength", "weightlifting": "strength", "weight_lifting": "strength",
    "yoga": "other", "pilates": "other", "elliptical": "other", "rowing": "other",
}
SPORT_NAME = {"run": "Run", "bike": "Ride", "swim": "Swim", "walk": "Walk", "hike": "Hike",
              "strength": "Strength", "other": "Workout"}
# Families that count as the same kind of workout when matching across sources.
_FAMILY = {"walk": "foot", "hike": "foot", "run": "run", "bike": "bike", "swim": "swim",
           "strength": "strength", "other": "other"}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _local(ts: Any) -> datetime | None:
    """ISO with or without an offset -> naive local wall time ('2026-10-13T07:00:00-06:00' -> 07:00)."""
    if not isinstance(ts, str) or len(ts) < 16:
        return None
    s = ts.strip().replace(" ", "T")
    s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", s)
    try:
        return datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def _minutes(v: Any) -> float | None:
    if (n := _num(v)) is not None:
        return n / 60
    if isinstance(v, str) and re.fullmatch(r"\d+(:\d{1,2}){1,2}", v.strip()):
        p = [int(x) for x in v.strip().split(":")]
        return (p[0] * 3600 + p[1] * 60 + p[2]) / 60 if len(p) == 3 else (p[0] * 60 + p[1]) / 60
    return None


def garmin_sport(type_key: Any) -> str:
    k = str(type_key or "").lower()
    if "swim" in k:
        return "swim"
    if any(w in k for w in ("cycl", "bik", "ride", "virtual_ride")):
        return "bike"
    if "run" in k:
        return "run"
    if "hik" in k:
        return "hike"
    if "walk" in k:
        return "walk"
    if "strength" in k or "weight" in k:
        return "strength"
    return "other"


def from_garmin(a: dict[str, Any]) -> dict[str, Any] | None:
    """``tools.compact_activity`` row -> model (for matching only; Garmin rows stay as they are)."""
    start = _local(a.get("date"))
    if start is None:
        return None
    return {"key": f"garmin:{a.get('activity_id')}", "source": "garmin", "id": a.get("activity_id"),
            "sport": garmin_sport(a.get("sport")), "name": str(a.get("name") or "Workout")[:80],
            "start": start.isoformat(), "minutes": _minutes(a.get("duration")),
            "km": _num(a.get("distance_km")), "avg_hr": _num(a.get("avg_hr")), "calories": None}


def from_oura(w: dict[str, Any]) -> dict[str, Any] | None:
    """Oura v2 workout -> model; None when it can't be placed in time."""
    start, end = _local(w.get("start_datetime")), _local(w.get("end_datetime"))
    wid = w.get("id")
    if start is None or not isinstance(wid, str) or not wid:
        return None
    sport = _OURA_SPORT.get(str(w.get("activity") or "").lower(), "other")
    minutes = (end - start).total_seconds() / 60 if end and end > start else None
    dist = _num(w.get("distance"))
    label = w.get("label") if isinstance(w.get("label"), str) and w.get("label") else None
    return {"key": f"oura:{wid}", "source": "oura", "id": wid, "sport": sport,
            "name": (label or SPORT_NAME[sport])[:80], "start": start.isoformat(),
            "minutes": round(minutes) if minutes else None,
            "km": round(dist / 1000, 2) if dist and dist > 0 else None,
            "avg_hr": None, "calories": _num(w.get("calories"))}


def same_workout(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Same sport family, starts within 10 min, and the time ranges overlap."""
    if _FAMILY.get(a.get("sport") or "other") != _FAMILY.get(b.get("sport") or "other"):
        return False
    sa, sb = _local(a.get("start")), _local(b.get("start"))
    if sa is None or sb is None or abs((sa - sb).total_seconds()) > START_WINDOW_S:
        return False
    ea = sa + timedelta(minutes=a.get("minutes") or 1)
    eb = sb + timedelta(minutes=b.get("minutes") or 1)
    return sa < eb and sb < ea


def _rank(w: dict[str, Any]) -> int:
    s = w.get("source")
    return PRIORITY.index(s) if s in PRIORITY else len(PRIORITY)


def merge(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``extra`` workouts that are new: not already in ``primary`` (Garmin) and not a
    duplicate of a richer extra. Oldest first."""
    out: list[dict[str, Any]] = []
    for w in sorted(extra, key=lambda x: (_rank(x), str(x.get("start")))):
        if any(same_workout(w, p) for p in primary) or any(same_workout(w, o) for o in out):
            continue
        out.append(w)
    return sorted(out, key=lambda x: str(x.get("start")))


class ExternalWorkouts:
    """Per-user store of workouts imported from non-Garmin sources (``extworkouts`` doc)."""

    def __init__(self, store: Any, *, clock: Any = None) -> None:
        self._s = store
        self._clock = clock or (lambda: datetime.now().timestamp())

    def _doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, DOC)

    def imported_at(self, uid: str, source: str) -> float | None:
        v = (self._doc(uid).load().get("imported_at") or {}).get(source)
        return float(v) if isinstance(v, int | float) else None

    def save(self, uid: str, source: str, items: list[dict[str, Any]], today: Any) -> list[str]:
        """Store ``items`` (already ``from_<source>``-shaped) for ``source``; returns the keys
        that are new. Drops anything older than ``KEEP_DAYS``."""
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        new: list[str] = []

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            have: dict[str, Any] = d.get("items") or {}
            for w in items:
                if w.get("source") != source or not isinstance(w.get("key"), str):
                    continue
                if w["key"] not in have:
                    new.append(w["key"])
                have[w["key"]] = w
            have = {k: v for k, v in have.items() if str(v.get("start") or "") >= cutoff}
            if len(have) > MAX_ITEMS:
                have = dict(sorted(have.items(), key=lambda kv: str(kv[1].get("start")))[-MAX_ITEMS:])
            d["items"] = have
            d.setdefault("imported_at", {})[source] = self._clock()
            return d
        self._doc(uid).update(apply)
        return new

    def all(self, uid: str) -> list[dict[str, Any]]:
        return list((self._doc(uid).load().get("items") or {}).values())

    def visible(self, uid: str, garmin_acts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Imported workouts that Garmin doesn't already have (re-checked every time, since
        Garmin may sync the same workout later)."""
        prim = [g for a in garmin_acts or [] if (g := from_garmin(a))]
        return merge(prim, self.all(uid))

    def by_day(self, uid: str, garmin_acts: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
        """{YYYY-MM-DD: [plancal "extra"-shaped rows with ``source``]} for the Day view."""
        out: dict[str, list[dict[str, Any]]] = {}
        for w in self.visible(uid, garmin_acts):
            day = str(w.get("start") or "")[:10]
            out.setdefault(day, []).append({
                "id": None, "name": w.get("name") or "Workout", "sport": w.get("sport") or "other",
                "km": w.get("km"), "minutes": round(w["minutes"]) if w.get("minutes") else None,
                "avg_hr": None, "source": w.get("source"), "key": w.get("key")})  # key: its page (/api/activity/<key>)
        return out


def drop_source(store: Any, uid: str, source: str) -> None:
    """Disconnecting an app deletes the workouts imported from it."""
    def apply(d: dict[str, Any]) -> dict[str, Any]:
        d["items"] = {k: v for k, v in (d.get("items") or {}).items() if v.get("source") != source}
        (d.get("imported_at") or {}).pop(source, None)
        return d
    store.user_doc(uid, DOC).update(apply)


__all__ = ["PRIORITY", "ExternalWorkouts", "drop_source", "from_garmin", "from_oura", "garmin_sport",
           "merge", "same_workout"]
