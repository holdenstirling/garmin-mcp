"""The sports an event (and a public meetup) can be: one catalog for the event form's dropdown.

Each sport has an id (stored on the event as ``activity``), a label, the group the dropdown files
it under, the coarse event ``type`` the rest of the app already understands (events.TYPES: race
distances, finish estimates, featured clubs) and the plan sport a group session of it counts as
(``run`` / ``bike`` / ``swim`` / ``strength`` / ``other``). Old events have no ``activity`` and
keep working from their ``type``.

The web app mirrors this list in ``web/src/lib/sports.ts`` (tests/test_event_sports.py checks the
two stay in step).
"""

from __future__ import annotations

from typing import Any

# (id, label, group, event type, plan sport)
CATALOG: tuple[tuple[str, str, str, str, str], ...] = (
    ("road_run", "Road running", "Running", "running", "run"),
    ("trail_run", "Trail running", "Running", "trail", "run"),
    ("track", "Track", "Running", "running", "run"),
    ("ultra", "Ultra running", "Running", "trail", "run"),
    ("cross_country", "Cross-country", "Running", "running", "run"),
    ("triathlon", "Triathlon", "Multisport", "triathlon", "bike"),
    ("duathlon", "Duathlon", "Multisport", "duathlon", "bike"),
    ("aquathlon", "Aquathlon", "Multisport", "other", "run"),
    ("road_ride", "Road cycling", "Cycling", "cycling", "bike"),
    ("gravel", "Gravel", "Cycling", "cycling", "bike"),
    ("mtb", "Mountain biking", "Cycling", "cycling", "bike"),
    ("cyclocross", "Cyclocross", "Cycling", "cycling", "bike"),
    ("indoor_ride", "Indoor cycling", "Cycling", "cycling", "bike"),
    ("pool_swim", "Pool swimming", "Swimming", "swimming", "swim"),
    ("open_water", "Open water swimming", "Swimming", "swimming", "swim"),
    ("walking", "Walking", "Outdoors", "other", "other"),
    ("hiking", "Hiking", "Outdoors", "mountaineering", "other"),
    ("mountaineering", "Mountaineering", "Outdoors", "mountaineering", "other"),
    ("climbing", "Climbing", "Outdoors", "other", "other"),
    ("bouldering", "Bouldering", "Outdoors", "other", "other"),
    ("rowing", "Rowing", "Water", "other", "other"),
    ("paddleboard", "Paddleboarding", "Water", "other", "other"),
    ("kayak", "Kayaking", "Water", "other", "other"),
    ("alpine_ski", "Alpine skiing", "Snow", "other", "other"),
    ("nordic_ski", "Nordic skiing", "Snow", "other", "other"),
    ("skimo", "Ski mountaineering", "Snow", "other", "other"),
    ("snowboard", "Snowboarding", "Snow", "other", "other"),
    ("volleyball", "Volleyball", "Team sports", "team_sport", "other"),
    ("beach_volleyball", "Beach volleyball", "Team sports", "team_sport", "other"),
    ("soccer", "Soccer", "Team sports", "team_sport", "other"),
    ("basketball", "Basketball", "Team sports", "team_sport", "other"),
    ("softball", "Softball", "Team sports", "team_sport", "other"),
    ("kickball", "Kickball", "Team sports", "team_sport", "other"),
    ("flag_football", "Flag football", "Team sports", "team_sport", "other"),
    ("ultimate", "Ultimate frisbee", "Team sports", "team_sport", "other"),
    ("hockey", "Hockey", "Team sports", "team_sport", "other"),
    ("rugby", "Rugby", "Team sports", "team_sport", "other"),
    ("lacrosse", "Lacrosse", "Team sports", "team_sport", "other"),
    ("pickleball", "Pickleball", "Racket sports", "team_sport", "other"),
    ("tennis", "Tennis", "Racket sports", "team_sport", "other"),
    ("padel", "Padel", "Racket sports", "team_sport", "other"),
    ("badminton", "Badminton", "Racket sports", "team_sport", "other"),
    ("squash", "Squash", "Racket sports", "team_sport", "other"),
    ("yoga", "Yoga", "Fitness", "other", "other"),
    ("pilates", "Pilates", "Fitness", "other", "other"),
    ("hiit", "CrossFit / HIIT", "Fitness", "other", "strength"),
    ("strength", "Strength training", "Fitness", "other", "strength"),
    ("spin", "Spin class", "Fitness", "cycling", "bike"),
    ("golf", "Golf", "More", "other", "other"),
    ("dance", "Dance", "More", "other", "other"),
    ("martial_arts", "Martial arts", "More", "other", "other"),
    ("other", "Something else", "More", "other", "other"),
)
IDS = tuple(c[0] for c in CATALOG)
_BY_ID = {c[0]: c for c in CATALOG}
OTHER_LEN = 40


def label(sport_id: str | None) -> str | None:
    c = _BY_ID.get(sport_id or "")
    return c[1] if c else None


def event_type(sport_id: str | None) -> str | None:
    """The coarse event type (events.TYPES) a sport belongs to."""
    c = _BY_ID.get(sport_id or "")
    return c[3] if c else None


def plan_sport(sport_id: str | None) -> str | None:
    """What a group session of this sport counts as in the plan (None = unknown sport)."""
    c = _BY_ID.get(sport_id or "")
    return c[4] if c else None


def catalog() -> list[dict[str, Any]]:
    return [{"id": i, "label": lb, "group": g, "type": t, "plan": p} for i, lb, g, t, p in CATALOG]


__all__ = ["CATALOG", "IDS", "OTHER_LEN", "catalog", "event_type", "label", "plan_sport"]
