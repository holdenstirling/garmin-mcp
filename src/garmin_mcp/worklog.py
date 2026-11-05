"""Workouts the athlete logs by hand (a lifting session with sets and weights, a run without a
watch, a class), stored per user in the encrypted ``worklog`` doc.

Model::

    {"id": "a1b2c3d4e5", "key": "manual:a1b2c3d4e5", "source": "manual", "sport": "strength",
     "title": "Lower body", "date": "2026-11-05", "time": "07:30" | None, "minutes": 50,
     "km": None, "rpe": 7, "notes": "", "session_id": "s123" | None,
     "exercises": [{"name": "Back squat", "note": "", "sets": [{"reps": "5", "weight": 185, "unit": "lb"}]}],
     "created": 1793000000, "updated": 1793000000}

These are the athlete's own words, so unlike Oura/WHOOP/Apple imports they count everywhere a
Garmin workout does: ``compact()`` turns each one into a ``tools.compact_activity``-shaped row that
``StatsService.activities`` merges in (plan "done" status, streaks, week ring, stats, the coach's
context). Garmin wins when both saw it: a logged workout is left out when Garmin has one of the
same sport family that day (untimed log) or starting within two hours (timed log), so nothing
counts twice. Sets and weights never leave the athlete's own views and the coach: Feed cards
carry sport, time and distance only.
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

DOC = "worklog"
MAX_ITEMS = 1500
MAX_EXERCISES = 30
MAX_SETS = 20
SPORTS = ("strength", "run", "bike", "swim", "walk", "hike", "other")
SPORT_NAME = {"strength": "Strength", "run": "Run", "bike": "Ride", "swim": "Swim", "walk": "Walk",
              "hike": "Hike", "other": "Workout"}
# tools.compact_activity's ``sport`` is Garmin's typeKey; these map back through weekplan.sport_of.
TYPE_KEY = {"strength": "strength_training", "run": "running", "bike": "cycling", "swim": "lap_swimming",
            "walk": "walking", "hike": "hiking", "other": "other"}
FAMILY = {"walk": "foot", "hike": "foot"}
_ID = re.compile(r"^[a-f0-9]{10}$")
_REPS = re.compile(r"^(\d{1,3}(-\d{1,3})?|\d{1,3}\s?(s|sec|m|min|cal)|\d{1,4}\s?m)( each( side)?)?$", re.I)
SAME_WINDOW_S = 2 * 3600


class WorklogError(ValueError):
    pass


def _clip(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _num(v: Any, lo: float, hi: float, what: str, *, integer: bool = False) -> float | int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, int | float | str):
        raise WorklogError(f"{what} must be a number.")
    try:
        n = float(v)
    except ValueError:
        raise WorklogError(f"{what} must be a number.") from None
    if not lo <= n <= hi:
        raise WorklogError(f"{what} must be between {lo:g} and {hi:g}.")
    return int(round(n)) if integer else round(n, 2)


def _reps(v: Any) -> str:
    if isinstance(v, bool):
        raise WorklogError("Reps must be a number like 8 or a time like 30s.")
    if isinstance(v, int | float):
        if not 0 < v <= 500:
            raise WorklogError("Reps must be between 1 and 500.")
        return str(int(v))
    s = _clip(v, 24).lower()
    if not s or not _REPS.fullmatch(s):
        raise WorklogError("Reps must be a number like 8, a range like 8-10, or a time like 30s.")
    return s


def clean_exercises(raw: Any, default_unit: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorklogError("exercises must be a list.")
    if len(raw) > MAX_EXERCISES:
        raise WorklogError(f"At most {MAX_EXERCISES} exercises in one workout.")
    out = []
    for ex in raw:
        if not isinstance(ex, dict):
            raise WorklogError("Each exercise needs a name and sets.")
        name = _clip(ex.get("name"), 60)
        if not name:
            raise WorklogError("Each exercise needs a name.")
        sets_in = ex.get("sets") or []
        if not isinstance(sets_in, list):
            raise WorklogError("sets must be a list.")
        if len(sets_in) > MAX_SETS:
            raise WorklogError(f"At most {MAX_SETS} sets per exercise.")
        sets = []
        for st in sets_in:
            if not isinstance(st, dict):
                raise WorklogError("Each set needs reps.")
            unit = st.get("unit") or default_unit
            if unit not in ("lb", "kg"):
                raise WorklogError("Weight unit must be lb or kg.")
            sets.append({"reps": _reps(st.get("reps")),
                         "weight": _num(st.get("weight"), 0, 2000 if unit == "lb" else 900, "Weight"),
                         "unit": unit})
        out.append({"name": name, "note": _clip(ex.get("note"), 140), "sets": sets})
    return out


def clean(body: Any, *, today: date, default_unit: str = "lb", partial: bool = False) -> dict[str, Any]:
    """Validate a create (or, with ``partial``, a PATCH) body into stored fields."""
    if not isinstance(body, dict):
        raise WorklogError("Send the workout as an object.")
    out: dict[str, Any] = {}
    if "sport" in body or not partial:
        sport = str(body.get("sport") or "").lower().strip()
        sport = {"lift": "strength", "lifting": "strength", "gym": "strength", "weights": "strength",
                 "hyrox": "strength", "ride": "bike", "cycling": "bike", "running": "run",
                 "swimming": "swim"}.get(sport, sport)
        if sport not in SPORTS:
            raise WorklogError("Pick a sport: strength, run, bike, swim, walk, hike or other.")
        out["sport"] = sport
    if "date" in body or not partial:
        raw = body.get("date") or today.isoformat()
        try:
            d = date.fromisoformat(str(raw)[:10])
        except ValueError:
            raise WorklogError("date must be YYYY-MM-DD.") from None
        if d > today:
            raise WorklogError("You can only log a workout you've already done.")
        if d < today - timedelta(days=365):
            raise WorklogError("That date is more than a year ago.")
        out["date"] = d.isoformat()
    if "time" in body:
        t = body.get("time")
        if t in (None, ""):
            out["time"] = None
        elif isinstance(t, str) and re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t.strip()):
            h, m = t.strip().split(":")
            out["time"] = f"{int(h):02d}:{m}"
        else:
            raise WorklogError("time must be HH:MM.")
    elif not partial:
        out["time"] = None
    for k, lo, hi, what, integer in (("minutes", 1, 1440, "Minutes", True), ("km", 0, 1000, "Distance", False),
                                     ("rpe", 1, 10, "Effort (1-10)", True)):
        if k in body or not partial:
            out[k] = _num(body.get(k), lo, hi, what, integer=integer)
    if "title" in body or not partial:
        out["title"] = _clip(body.get("title"), 80)
    if "notes" in body or not partial:
        out["notes"] = _clip(body.get("notes"), 600)
    if "session_id" in body or not partial:
        sid = body.get("session_id")
        if sid not in (None, "") and not (isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", sid)):
            raise WorklogError("session_id isn't valid.")
        out["session_id"] = sid or None
    if "exercises" in body or not partial:
        out["exercises"] = clean_exercises(body.get("exercises"), default_unit)
    return out


def _set_line(sets: list[dict[str, Any]]) -> str:
    """'3 x 5 @ 185 lb' when the sets match, else each set: '5 @ 185, 5 @ 195 lb'."""
    if not sets:
        return ""
    unit = sets[0].get("unit") or "lb"

    def w(x: Any) -> str:
        return f"{x:g}" if isinstance(x, int | float) else ""
    if all(s["reps"] == sets[0]["reps"] and s.get("weight") == sets[0].get("weight") for s in sets):
        base = f"{len(sets)} x {sets[0]['reps']}"
        return f"{base} @ {w(sets[0]['weight'])} {unit}" if sets[0].get("weight") is not None else base
    parts = [f"{s['reps']} @ {w(s['weight'])}" if s.get("weight") is not None else s["reps"] for s in sets]
    return ", ".join(parts) + (f" {unit}" if any(s.get("weight") is not None for s in sets) else "")


def summary(w: dict[str, Any]) -> str:
    """One plain line for the coach and lists: 'Back squat 3 x 5 @ 185 lb; Bench press 3 x 8 @ 135 lb'."""
    return "; ".join(f"{e['name']} {_set_line(e['sets'])}".strip() for e in w.get("exercises") or [])


def compact(w: dict[str, Any]) -> dict[str, Any]:
    """A ``tools.compact_activity``-shaped row (activity_id is the string key ``manual:<id>``)."""
    start = f"{w['date']} {w.get('time') or '12:00'}:00"
    sets = [s for e in w.get("exercises") or [] for s in e["sets"]]
    reps = sum(int(s["reps"]) for s in sets if s["reps"].isdigit())
    mins = w.get("minutes")
    return {"activity_id": w["key"], "date": start, "name": w.get("title") or SPORT_NAME[w["sport"]],
            "sport": TYPE_KEY[w["sport"]], "duration": (f"{mins // 60}:{mins % 60:02d}:00" if mins and mins >= 60
                                                        else f"{mins}:00" if mins else None),
            "moving_duration": None, "distance_km": w.get("km"), "avg_hr": None, "max_hr": None,
            "elevation_gain_m": None, "training_load": None, "event": None,
            "total_sets": len(sets) or None, "total_reps": reps or None,
            "source": "manual", "manual": True, "timed": bool(w.get("time")),
            "session_id": w.get("session_id"), "rpe": w.get("rpe")}


def _family(sport: str) -> str:
    return FAMILY.get(sport, sport)


def _garmin_family(type_key: Any) -> str:
    from .weekplan import sport_of
    k = str(type_key or "").lower()
    return "foot" if ("walk" in k or "hik" in k) else sport_of(k)


def _start(row: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(row.get("date") or "").replace(" ", "T")[:19])
    except ValueError:
        return None


def dedupe(garmin: list[dict[str, Any]], manual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The logged rows Garmin didn't already record (same family that day: untimed; within two
    hours: timed)."""
    out = []
    for m in manual:
        ms, fam = _start(m), _family({v: k for k, v in TYPE_KEY.items()}.get(m["sport"], "other"))
        dup = False
        for g in garmin:
            gs = _start(g)
            if gs is None or ms is None or gs.date() != ms.date() or _garmin_family(g.get("sport")) != fam:
                continue
            if not m.get("timed") or abs((gs - ms).total_seconds()) <= SAME_WINDOW_S:
                dup = True
                break
        if not dup:
            out.append(m)
    return out


class Worklog:
    """Per-user logged workouts (``worklog`` doc, encrypted like every user doc)."""

    def __init__(self, store: Any, *, today: Callable[[str], date],
                 clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._today = today
        self._clock = clock
        self.on_change: list[Callable[[str], None]] = []  # stats cache, feed catch-up (webapp)

    def _doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, DOC)

    def _changed(self, uid: str) -> None:
        for fn in self.on_change:
            try:
                fn(uid)
            except Exception:  # a listener never breaks a save
                pass

    def all(self, uid: str) -> list[dict[str, Any]]:
        return sorted((self._doc(uid).load().get("items") or {}).values(),
                      key=lambda w: (w["date"], w.get("time") or "", w.get("created") or 0))

    def get(self, uid: str, wid: str) -> dict[str, Any]:
        wid = wid.removeprefix("manual:")
        w = (self._doc(uid).load().get("items") or {}).get(wid) if _ID.fullmatch(wid) else None
        if w is None:
            raise WorklogError("That logged workout isn't there anymore.")
        return w

    def add(self, uid: str, body: Any, *, unit: str = "lb") -> dict[str, Any]:
        f = clean(body, today=self._today(uid), default_unit=unit)
        now = int(self._clock())
        wid = secrets.token_hex(5)
        w = {"id": wid, "key": f"manual:{wid}", "source": "manual", **f, "created": now, "updated": now}
        if not w["title"]:
            w["title"] = SPORT_NAME[w["sport"]]

        def apply(d: dict[str, Any]) -> None:
            items = d.setdefault("items", {})
            items[wid] = w
            if len(items) > MAX_ITEMS:
                for k in sorted(items, key=lambda k: (items[k]["date"], items[k].get("created") or 0))[: len(items) - MAX_ITEMS]:
                    del items[k]
        self._doc(uid).update(apply)
        self._changed(uid)
        return w

    def update(self, uid: str, wid: str, body: Any, *, unit: str = "lb") -> dict[str, Any]:
        cur = self.get(uid, wid)
        f = clean(body, today=self._today(uid), default_unit=unit, partial=True)
        w = {**cur, **f, "updated": int(self._clock())}
        if not w.get("title"):
            w["title"] = SPORT_NAME[w["sport"]]

        def apply(d: dict[str, Any]) -> None:
            (d.setdefault("items", {}))[cur["id"]] = w
        self._doc(uid).update(apply)
        self._changed(uid)
        return w

    def delete(self, uid: str, wid: str) -> None:
        cur = self.get(uid, wid)

        def apply(d: dict[str, Any]) -> None:
            (d.get("items") or {}).pop(cur["id"], None)
        self._doc(uid).update(apply)
        self._changed(uid)

    def between(self, uid: str, start: date, end: date) -> list[dict[str, Any]]:
        a, b = start.isoformat(), end.isoformat()
        return [w for w in self.all(uid) if a <= w["date"] <= b]

    def compact(self, uid: str) -> list[dict[str, Any]]:
        return [compact(w) for w in self.all(uid)]

    def history(self, uid: str, name: str, limit: int = 5) -> list[dict[str, Any]]:
        """The last ``limit`` times this exercise was logged (newest first): date and its sets."""
        key = _clip(name, 60).lower()
        if not key:
            return []
        out = []
        for w in reversed(self.all(uid)):
            for e in w.get("exercises") or []:
                if e["name"].lower() == key and e["sets"]:
                    out.append({"date": w["date"], "workout_id": w["id"], "sets": e["sets"], "line": _set_line(e["sets"])})
                    break
            if len(out) >= limit:
                break
        return out


__all__ = ["Worklog", "WorklogError", "clean", "compact", "dedupe", "summary", "SPORTS", "TYPE_KEY"]
