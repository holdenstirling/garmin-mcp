"""Which numbers make sense for a workout, by sport family.

A run is told by pace per mile, a ride by speed, a swim by pace per 100, a row by pace per
500 m, a ski day by vertical, and a yoga or strength session by time alone. ``family`` sorts
any workout (the plan/stats sport plus Garmin's raw type, e.g. ``indoor_cycling``) into one of
these families; ``pace_fields`` and ``splits_ok`` then decide what a workout card carries.

The web app mirrors this in ``web/src/lib/sportstats.ts`` (keep the two in step).
"""

from __future__ import annotations

from typing import Any

FAMILIES = ("run", "walk", "hike", "ride", "indoor_ride", "swim", "row", "paddle", "ski", "strength",
            "mind", "hiit", "climb", "brick", "other")

# (substring of the raw type, family), checked in order: the more specific first.
_RAW: tuple[tuple[str, str], ...] = (
    ("multi_sport", "brick"), ("multisport", "brick"), ("triathlon", "brick"), ("duathlon", "brick"),
    ("brick", "brick"),
    ("indoor_cycling", "indoor_ride"), ("virtual_ride", "indoor_ride"), ("trainer", "indoor_ride"),
    ("spin", "indoor_ride"), ("indoor_bik", "indoor_ride"),
    ("swim", "swim"), ("pool", "swim"), ("open_water", "swim"),
    ("indoor_row", "row"), ("rowing", "row"),
    ("paddl", "paddle"), ("kayak", "paddle"), ("canoe", "paddle"), ("stand_up", "paddle"),
    ("ski", "ski"), ("snowboard", "ski"), ("snowshoe", "ski"),
    ("climb", "climb"), ("boulder", "climb"), ("mountaineer", "climb"),
    ("yoga", "mind"), ("pilates", "mind"), ("breath", "mind"), ("meditat", "mind"), ("stretch", "mind"),
    ("mobility", "mind"),
    ("hiit", "hiit"), ("cardio", "hiit"), ("crossfit", "hiit"), ("bootcamp", "hiit"), ("boxing", "hiit"),
    ("strength", "strength"), ("weight", "strength"), ("gym", "strength"), ("lift", "strength"),
    ("walk", "walk"),
    ("hik", "hike"), ("trek", "hike"),
    ("cycl", "ride"), ("bik", "ride"), ("ride", "ride"), ("gravel", "ride"), ("mtb", "ride"),
    ("run", "run"), ("jog", "run"), ("treadmill", "run"), ("track", "run"),
)
_SPORT: dict[str, str] = {
    "run": "run", "walk": "walk", "hike": "hike", "bike": "ride", "ride": "ride", "swim": "swim",
    "brick": "brick", "strength": "strength", "ski": "ski", "climb": "climb", "paddle": "paddle",
    "row": "row", "yoga": "mind", "hiit": "hiit",
}

# Families whose cards show a lap shape: miles (or km) for the foot sports, 100s for swims.
SPLITS = ("run", "walk", "hike", "swim")
# Families with no distance to speak of: time (and sets/reps, ...) only.
NO_DISTANCE = ("strength", "mind", "hiit", "climb", "other")

TITLE = {"run": "Run", "walk": "Walk", "hike": "Hike", "ride": "Ride", "indoor_ride": "Indoor ride",
         "swim": "Swim", "row": "Row", "paddle": "Paddle", "ski": "Ski", "strength": "Strength",
         "mind": "Yoga", "hiit": "HIIT", "climb": "Climb", "brick": "Brick", "other": "Workout"}


def family(sport: str | None, raw: str | None = None) -> str:
    """The family for a workout. ``raw`` (Garmin's typeKey or a source's name for it) wins
    over the coarse plan/stats ``sport`` when it says more (an indoor ride, a walk, yoga)."""
    k = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if k:
        for sub, fam in _RAW:
            if sub in k:
                return fam
    s = (sport or "").strip().lower()
    if s in _SPORT:
        return _SPORT[s]
    if s:
        for sub, fam in _RAW:
            if sub in s:
                return fam
    return "other"


def title(fam: str, raw: str | None = None) -> str:
    """The card title for an auto-shared workout ("Indoor ride", "Yoga", "Pilates")."""
    k = (raw or "").lower()
    if fam == "mind" and "pilates" in k:
        return "Pilates"
    if fam == "mind" and ("stretch" in k or "mobility" in k):
        return "Mobility"
    if fam == "mind" and ("breath" in k or "meditat" in k):
        return "Breathwork"
    if fam == "paddle" and "kayak" in k:
        return "Kayak"
    if fam == "ski" and "snowboard" in k:
        return "Snowboard"
    return TITLE.get(fam, "Workout")


def pace_fields(fam: str, km: float | None, minutes: float | None) -> dict[str, Any]:
    """The one rate that suits the family: s/km for the foot sports, km/h for rides, s/100 m
    for swims, s/500 m for rowing and paddling. Nothing for the rest (a ski day's average
    speed or a yoga "pace" means nothing)."""
    if not km or not minutes or km <= 0 or minutes <= 0:
        return {}
    sec = minutes * 60
    if fam in ("ride", "indoor_ride"):
        return {"speed_kmh": round(km / (sec / 3600), 1)}
    if fam == "swim":
        return {"pace_s_100m": int(round(sec / (km * 10)))}
    if fam in ("row", "paddle"):
        return {"pace_s_500m": int(round(sec / (km * 2)))}
    if fam in ("run", "walk", "hike"):
        return {"pace_s_km": int(round(sec / km))}
    return {}


def splits_ok(fam: str) -> bool:
    return fam in SPLITS


__all__ = ["FAMILIES", "SPLITS", "NO_DISTANCE", "TITLE", "family", "title", "pace_fields", "splits_ok"]
