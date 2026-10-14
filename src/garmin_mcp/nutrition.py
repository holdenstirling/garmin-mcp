"""Fueling for long sessions and races, with a gut-training ramp toward race-day carbs.

General sports-nutrition ranges (carbohydrate per hour by duration; 400-800 ml fluid and
300-600 mg sodium per hour, more in heat). Long sessions practice race fueling, stepping
up from about 16 weeks out so race-day intake is familiar by the final month.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Race-day carbohydrate target (g/h) by distance.
RACE_CARBS = {"sprint triathlon": 30, "olympic triathlon": 60, "70.3": 80, "140.6": 90, "5k": 0,
              "10k": 0, "half marathon": 40, "marathon": 70, "ultra": 80, "century ride": 70, "other": 60}
RAMP_WEEKS = 16


def race_target(distance: str | None) -> int:
    return RACE_CARBS.get((distance or "other").lower(), 60)


def fuel(session: dict[str, Any], day: str, *, race_date: str | None, distance: str | None) -> dict[str, Any] | None:
    """Fueling guide for one session, or None when water is enough (< 75 min)."""
    minutes = session.get("minutes") or sum(lg.get("minutes", 0) for lg in session.get("legs") or [])
    is_race = session.get("kind") == "race"
    if session.get("sport") in ("rest", "strength") or (not is_race and minutes < 75):
        return None
    target = race_target(distance)
    if is_race:
        if target == 0:
            return {"carbs_g_per_h": 0, "note": "Short race: a carb-rich breakfast 2-3 hours before is enough. Water as needed."}
        return {"carbs_g_per_h": target, "fluid_ml_per_h": "500-800", "sodium_mg_per_h": "400-800",
                "note": f"Start fueling in the first 20-30 minutes and keep a steady {target} g/h. Use only what you've trained with."}
    weeks_out = None
    if race_date:
        try:
            weeks_out = (date.fromisoformat(race_date) - date.fromisoformat(day)).days // 7
        except ValueError:
            weeks_out = None
    base = 30 if minutes < 120 else 45
    gh = base
    note = "Practice fueling: start after 30-45 minutes, then little and often."
    if weeks_out is not None and target >= 60 and weeks_out <= RAMP_WEEKS:
        progress = min(1.0, (RAMP_WEEKS - weeks_out) / (RAMP_WEEKS - 4))
        gh = int(round((base + (target - base) * progress) / 5) * 5)
        note = (f"Gut training: {gh} g/h today, building to your race target of {target} g/h. "
                "Use your race-day products.")
    hours = minutes / 60
    return {"carbs_g_per_h": gh, "total_carbs_g": int(round(gh * max(0.0, hours - 0.5))),
            "fluid_ml_per_h": "400-800", "sodium_mg_per_h": "300-600", "note": note}


__all__ = ["fuel", "race_target", "RACE_CARBS"]
