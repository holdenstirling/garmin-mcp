"""Training load: fitness (CTL, 42-day), fatigue (ATL, 7-day) and form (TSB = CTL - ATL)
from Garmin activities, projected forward through the built plan to race day.

Daily load uses one consistent scale for history and plan, a TSS-like score:
``hours * IF^2 * 100``. For an activity, IF is avg HR / threshold HR when both are known,
otherwise a typical value for the sport. For a planned session, IF comes from its kind.
Garmin's own "training load" (EPOC) is a different scale, so it isn't mixed in.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from .planbuilder import iter_sessions
from .stats import _rows
from .weekplan import _seconds

CTL_DAYS, ATL_DAYS = 42, 7
HISTORY_DAYS = 180
SHOW_DAYS = 90
SPORT_IF = {"run": 0.75, "bike": 0.7, "swim": 0.7, "brick": 0.75, "strength": 0.55, "hike": 0.6,
            "climb": 0.65, "ski": 0.65, "paddle": 0.65, "other": 0.6}
KIND_IF = {"easy": 0.68, "endurance": 0.72, "long": 0.72, "recovery": 0.55, "strides": 0.72,
           "tempo": 0.85, "threshold": 0.92, "vo2": 0.95, "racepace": 0.88, "openers": 0.75,
           "shakeout": 0.6, "technique": 0.62, "css": 0.86, "brick": 0.78, "strength": 0.55}
RACE_HOURS = {"sprint triathlon": 1.4, "olympic triathlon": 2.6, "70.3": 5.5, "140.6": 12.0, "5k": 0.4,
              "10k": 0.8, "half marathon": 1.8, "marathon": 3.8, "ultra": 20.0, "century ride": 6.0}


def activity_load(a: dict[str, Any], threshold_hr: int | None) -> float:
    from .stats import category
    hours = _seconds(a.get("duration")) / 3600
    if hours <= 0:
        return 0.0
    hr = a.get("avg_hr")
    if isinstance(hr, int | float) and threshold_hr:
        intensity = max(0.4, min(1.15, hr / threshold_hr))
    else:
        intensity = SPORT_IF.get(category(a.get("sport")), 0.6)
    return round(hours * intensity ** 2 * 100, 1)


def session_load(s: dict[str, Any], distance: str | None = None) -> float:
    if s.get("sport") == "rest":
        return 0.0
    if s.get("kind") == "race":
        hours = RACE_HOURS.get((distance or "").lower(), 2.0)
        return round(min(hours, 6) * 0.85 ** 2 * 100 + max(0, hours - 6) * 0.6 ** 2 * 100, 1)
    minutes = s.get("minutes") or sum(lg.get("minutes", 0) for lg in s.get("legs") or [])
    return round(minutes / 60 * KIND_IF.get(s.get("kind") or "easy", 0.7) ** 2 * 100, 1)


def compute(acts: list[dict[str, Any]], today: date, *, threshold_hr: int | None = None,
            plan: dict[str, Any] | None = None) -> dict[str, Any]:
    # Actual load per day (multisport legs counted once via stats._rows' rule).
    keep = {r["id"] for r in _rows(acts)}
    actual: dict[str, float] = {}
    for a in acts:
        if a.get("activity_id") not in keep:
            continue
        d = str(a.get("date") or "")[:10]
        actual[d] = actual.get(d, 0.0) + activity_load(a, threshold_hr)
    planned: dict[str, float] = {}
    race_date = None
    if plan:
        race_date = plan.get("race_date")
        for _, d, s in iter_sessions(plan):
            if d > today.isoformat():
                planned[d] = planned.get(d, 0.0) + session_load(s, plan.get("distance"))
    start = today - timedelta(days=HISTORY_DAYS)
    end = date.fromisoformat(race_date) if race_date and race_date > today.isoformat() else today + timedelta(days=28)
    k_ctl, k_atl = 1 - math.exp(-1 / CTL_DAYS), 1 - math.exp(-1 / ATL_DAYS)
    ctl = atl = 0.0
    series = []
    d = start
    while d <= end:
        key = d.isoformat()
        future = d > today
        load = planned.get(key, 0.0) if future else actual.get(key, 0.0)
        tsb = ctl - atl  # form going into the day
        ctl += (load - ctl) * k_ctl
        atl += (load - atl) * k_atl
        if d >= today - timedelta(days=SHOW_DAYS):
            series.append({"date": key, "load": round(load), "ctl": round(ctl, 1), "atl": round(atl, 1),
                           "tsb": round(tsb, 1), "planned": future})
        d += timedelta(days=1)
    now = next((p for p in series if p["date"] == today.isoformat()), series[-1] if series else None)
    race = next((p for p in series if p["date"] == race_date), None) if race_date else None
    return {"today": today.isoformat(), "series": series, "now": now, "race_day": race,
            "race_date": race_date, "has_plan": bool(plan), "advice": advice(now, race)}


def advice(now: dict[str, Any] | None, race: dict[str, Any] | None) -> str:
    if not now:
        return "Log some workouts and your fitness curve will appear here."
    tsb = now["tsb"]
    if tsb < -30:
        today = "You're carrying a lot of fatigue. An easy day or two would pay off."
    elif tsb < -10:
        today = "Productive fatigue: you're building. Keep easy days easy."
    elif tsb <= 10:
        today = "Fresh enough to train well."
    else:
        today = "Very fresh. Good time for a quality session, or fitness may start to slip."
    if race:
        r = race["tsb"]
        if 5 <= r <= 25:
            plan = f" On race day your plan projects form +{r:.0f} with fitness {race['ctl']:.0f}: right in the zone."
        elif r < 5:
            plan = f" Race-day form projects at {r:+.0f}: on the tired side; a longer taper may help."
        else:
            plan = f" Race-day form projects at +{r:.0f}: very fresh; some fitness may fade before the race."
        return today + plan
    return today


__all__ = ["compute", "activity_load", "session_load", "advice"]
