"""The page for one recorded workout (web: components/workout/ActivityScreen.tsx).

``build_view`` is pure: it shapes a compact Garmin activity (``tools.compact_activity``), its
laps (``paces.laps_from_splits``) and a few extra summary fields from ``get_activity`` into
what the page shows: key numbers, laps, time in heart-rate zones, the planned session it
counted for (with "how it went") and the athlete's own check-in plus Rabbit's deterministic
feedback (``workoutday.coach_feedback``).

Workouts imported from other sources (``workouts.py``: Oura today) are display-only. Their
view (``build_imported``) is built from the stored record only, carries ``ai: False`` so the
page never offers "Ask Rabbit" for them, and never goes near the coach (the import doc itself
is read in ``webapp.py``, the one place allowed to).

Time in zones: from laps with heart rate when there are laps (each lap's time in the zone of
its average heart rate), else the whole workout in the zone of its average ("estimate").
"""

from __future__ import annotations

from typing import Any

from . import sportfamily as _sf
from .workouttargets import _secs, hr_zones

ZONE_LABEL = {1: "Easy", 2: "Aerobic", 3: "Tempo", 4: "Threshold", 5: "Max"}
MAX_LAPS = 60

_SPORT = (("swim", "swim"), ("bik", "bike"), ("cycl", "bike"), ("ride", "bike"), ("run", "run"),
          ("walk", "walk"), ("hik", "hike"), ("strength", "strength"), ("yoga", "yoga"))


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def sport_of(type_key: Any) -> str:
    k = str(type_key or "").lower()
    return next((s for frag, s in _SPORT if frag in k), "other")


def garmin_url(aid: Any) -> str | None:
    return f"https://connect.garmin.com/modern/activity/{aid}" if isinstance(aid, int) and not isinstance(aid, bool) else None


def _zone_of(hr: float, zones: dict[int, tuple[int, int]]) -> int:
    for z in (5, 4, 3, 2):
        if hr >= zones[z][0]:
            return z
    return 1


def time_in_zones(laps: list[dict[str, Any]], avg_hr: float | None, total_s: float | None,
                  zones: dict[int, tuple[int, int]] | None) -> dict[str, Any] | None:
    """{basis: laps|average, zones: [{zone, label, low, high, s}]} or None without HR zones."""
    if not zones:
        return None
    secs = {z: 0.0 for z in range(1, 6)}
    with_hr = [lp for lp in laps if _num(lp.get("hr")) and _num(lp.get("s"))]
    if len(with_hr) >= 2:
        for lp in with_hr:
            secs[_zone_of(float(lp["hr"]), zones)] += float(lp["s"])
        basis = "laps"
    elif avg_hr and total_s:
        secs[_zone_of(avg_hr, zones)] = float(total_s)
        basis = "average"
    else:
        return None
    return {"basis": basis, "zones": [{"zone": z, "label": ZONE_LABEL[z], "low": zones[z][0], "high": zones[z][1],
                                       "s": round(secs[z])} for z in range(1, 6)]}


def laps_view(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lap rows: {n, km, s, pace_s_per_km, hr?, gain_m?} (pace for moving laps only)."""
    out = []
    for i, lp in enumerate(laps[:MAX_LAPS], 1):
        d, s = _num(lp.get("d")), _num(lp.get("s"))
        if not d or not s:
            continue
        row: dict[str, Any] = {"n": i, "km": round(d / 1000, 3), "s": round(s), "pace_s_per_km": round(s / (d / 1000))}
        if _num(lp.get("hr")):
            row["hr"] = round(float(lp["hr"]))
        if _num(lp.get("gain")) is not None:
            row["gain_m"] = round(float(lp["gain"]))
        out.append(row)
    return out


def build_view(act: dict[str, Any], *, laps: list[dict[str, Any]] | None = None, extra: dict[str, Any] | None = None,
               athlete: dict[str, Any] | None = None, planned: dict[str, Any] | None = None,
               checkin: dict[str, Any] | None = None, feedback: dict[str, Any] | None = None) -> dict[str, Any]:
    """The page data for a Garmin activity. ``extra``: fields only ``get_activity`` has
    (calories, bike cadence, elapsed time); ``planned``: {id, date, title, kind, went} when the
    activity counted for a plan session."""
    x = extra or {}
    aid = act.get("activity_id")
    sport = sport_of(act.get("sport"))
    moving = _secs(act.get("moving_duration")) or _secs(act.get("duration"))
    elapsed = _num(x.get("elapsed_s")) or _secs(act.get("duration"))
    km = _num(act.get("distance_km"))
    lap_rows = laps_view(laps or [])
    zones, _src = hr_zones(athlete or {})
    cadence = _num(act.get("avg_cadence")) or _num(x.get("bike_cadence"))
    numbers = {
        "km": km, "moving_s": round(moving) if moving else None, "elapsed_s": round(elapsed) if elapsed else None,
        "pace_s_per_km": (round(_secs(act.get("avg_pace_per_km")) or (moving / km)) if sport in ("run", "walk", "hike")
                          and (act.get("avg_pace_per_km") or (km and moving)) else None),
        "pace_s_per_100m": round(_secs(act.get("avg_pace_per_100m"))) if _secs(act.get("avg_pace_per_100m")) else None,
        "speed_kmh": _num(act.get("avg_speed_kmh")),
        "avg_hr": _num(act.get("avg_hr")), "max_hr": _num(act.get("max_hr")),
        "cadence": round(cadence) if cadence else None, "cadence_unit": "spm" if sport in ("run", "walk", "hike") else "rpm",
        "elevation_gain_m": _num(act.get("elevation_gain_m")),
        "avg_power_w": _num(act.get("avg_power_w")), "norm_power_w": _num(act.get("norm_power_w")),
        "calories": _num(x.get("calories")),
        "aerobic_te": _num(act.get("aerobic_te")), "anaerobic_te": _num(act.get("anaerobic_te")),
        "training_load": _num(act.get("training_load")), "te_label": act.get("training_effect_label"),
        "swolf": _num(act.get("avg_swolf")), "stroke_rate": _num(act.get("avg_stroke_rate")),
    }
    fam = _sf.family(sport, act.get("sport"))
    _fit_numbers(numbers, fam, moving, km, act)
    return {
        "id": aid, "key": str(aid), "source": "garmin", "ai": True,
        "sport": sport, "family": fam, "name": act.get("name") or "Workout", "start": act.get("date"),
        "numbers": {k: v for k, v in numbers.items() if v is not None},
        "laps": lap_rows if len(lap_rows) >= 2 else [],
        "zones": time_in_zones(laps or [], numbers["avg_hr"], moving, zones),
        "planned": planned, "checkin": checkin, "feedback": feedback,
        "garmin_url": garmin_url(aid),
    }


def build_imported(w: dict[str, Any], *, checkin: dict[str, Any] | None = None,
                   feedback: dict[str, Any] | None = None) -> dict[str, Any]:
    """A workout another source recorded (workouts.py model). Display-only: ``ai`` is False."""
    mins = _num(w.get("minutes"))
    km = _num(w.get("km"))
    sport = str(w.get("sport") or "other")
    numbers = {"km": km, "moving_s": round(mins * 60) if mins else None,
               "pace_s_per_km": round(mins * 60 / km) if sport == "run" and km and mins else None,
               "avg_hr": _num(w.get("avg_hr")), "calories": _num(w.get("calories"))}
    fam = _sf.family(sport, str(w.get("kind") or w.get("name") or ""))
    _fit_numbers(numbers, fam, (mins or 0) * 60, km, w)
    return {"id": w.get("key"), "key": w.get("key"), "source": w.get("source") or "other", "ai": False,
            "sport": sport, "family": fam, "name": w.get("name") or "Workout", "start": w.get("start"),
            "numbers": {k: v for k, v in numbers.items() if v is not None}, "laps": [], "zones": None,
            "planned": None, "checkin": checkin, "feedback": feedback, "garmin_url": None}


def _fit_numbers(n: dict[str, Any], fam: str, moving: float | None, km: float | None, act: dict[str, Any]) -> None:
    """Keep only the numbers that mean something for the family (``sportfamily``): no pace or
    distance for a yoga class, no "speed" for a run, pace per 500 m for a row, vertical for a
    ski day, sets and reps for the gym."""
    if fam in _sf.NO_DISTANCE:
        for k in ("km", "pace_s_per_km", "pace_s_per_100m", "speed_kmh"):
            n.pop(k, None)
    if fam in ("run", "walk", "hike", "swim", "row", "paddle", "ski"):
        n.pop("speed_kmh", None)
    if fam != "swim":
        n.pop("pace_s_per_100m", None)
    if fam in ("row", "paddle") and km and moving:
        n["pace_s_per_500m"] = round(moving / (km * 2))
    if fam == "ski" and _num(act.get("elevation_loss_m")):
        n["vertical_m"] = round(float(act["elevation_loss_m"]))
    if fam in ("strength", "hiit"):
        for k in ("total_sets", "total_reps"):
            v = act.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                n[k.removeprefix("total_")] = v
    if fam in ("indoor_ride", "swim", "row", "mind", "strength", "hiit"):
        n.pop("elevation_gain_m", None)


def checkin_ref(key: str) -> str:
    """A check-in's activity_id for this workout (check-in ids allow [A-Za-z0-9_-] only)."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in str(key))[:64]


def extra_from(raw: Any) -> dict[str, Any]:
    """Fields the page wants that only ``get_activity`` has (summaryDTO)."""
    s = raw.get("summaryDTO") if isinstance(raw, dict) and isinstance(raw.get("summaryDTO"), dict) else raw
    if not isinstance(s, dict):
        return {}
    out: dict[str, Any] = {}
    if _num(s.get("calories")):
        out["calories"] = round(float(s["calories"]))
    bc = _num(s.get("averageBikeCadence")) or _num(s.get("averageBikingCadenceInRevPerMinute"))
    if bc:
        out["bike_cadence"] = round(bc)
    if _num(s.get("elapsedDuration")):
        out["elapsed_s"] = round(float(s["elapsedDuration"]))
    return out
