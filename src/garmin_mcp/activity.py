"""What a local club, league, meetup or event is *for*: one shared activity id per listing, so the
app can show the matching icon (the web app maps ids to icons in ``web/src/lib/activity.ts``) and
filter by activity ("Volleyball", "Pickleball"...).

``classify`` is deterministic keyword matching on the listing's own words (name, sports,
description, kind); nothing here calls a model. ``group_type`` says whether a listing reads as a
"Club", a "League" or a casual "Meetup".
"""

from __future__ import annotations

import re
from typing import Any

# Order matters for display (filter chips) and for ties in ``classify`` (more specific first).
ACTIVITIES: tuple[tuple[str, str], ...] = (
    ("run", "Run"), ("trail", "Trail"), ("ride", "Ride"), ("swim", "Swim"), ("tri", "Tri"),
    ("volleyball", "Volleyball"), ("pickleball", "Pickleball"), ("soccer", "Soccer"),
    ("basketball", "Basketball"), ("climbing", "Climbing"), ("yoga", "Yoga"), ("other", "Other"),
)
IDS = tuple(a for a, _ in ACTIVITIES)
LABEL = dict(ACTIVITIES)

# Checked in this order; the first activity whose words appear wins. Specific sports before the
# generic "run"/"ride" words (a "beach volleyball run-and-play" is volleyball).
_WORDS: tuple[tuple[str, str], ...] = (
    ("tri", r"triathlon|triathlete|\btri club|\btri team|\bduathlon|\baquathlon|\bbrick"),
    ("volleyball", r"volleyball|\bvolley\b"),
    ("pickleball", r"pickleball|pickle ball"),
    ("soccer", r"soccer|futsal|\bfootball club\b"),
    ("basketball", r"basketball|\bhoops\b"),
    ("climbing", r"\bclimbing\b|\bclimbers?\b|bouldering|boulder gym|\bcrag"),
    ("yoga", r"\byoga\b|pilates"),
    ("swim", r"\bswim|masters swim|open water|\bpool\b|aquatic"),
    ("trail", r"\btrail|ultra|mountain run|sky ?run|fell run|hik(?:e|ing)"),
    ("ride", r"cycl|\bbike|\bbicycl|\bride\b|\brides\b|gravel|\bmtb\b|velo|peloton|criterium|\bspin\b"),
    ("run", r"\brun|runner|running|jog|striders|harriers|\b5k\b|\b10k\b|marathon|track night|track club"),
)
_COMPILED = tuple((a, re.compile(p, re.IGNORECASE)) for a, p in _WORDS)
# Directory kinds (clubdir.KINDS) and event types (events.py) that already say what it is.
_KIND = {"run_club": "run", "trail": "trail", "tri": "tri", "ride": "ride", "swim": "swim",
         "running": "run", "cycling": "ride", "swimming": "swim", "triathlon": "tri", "duathlon": "tri"}
_SPORT_WORD = {"running": "run", "run": "run", "trail running": "trail", "trail": "trail", "cycling": "ride",
               "biking": "ride", "bike": "ride", "swimming": "swim", "swim": "swim", "triathlon": "tri",
               "volleyball": "volleyball", "pickleball": "pickleball", "soccer": "soccer",
               "basketball": "basketball", "climbing": "climbing", "bouldering": "climbing", "yoga": "yoga"}


def _text(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, list | tuple):
        return " ".join(x for x in v if isinstance(x, str))
    return ""


def classify(*texts: Any, kind: Any = None, sports: Any = None) -> str:
    """Activity id for a listing or event: its stated sports first, then its own words (name
    before description), then its kind; "other" when nothing says."""
    for s in sports if isinstance(sports, list | tuple) else ():
        if isinstance(s, str) and s.strip().lower() in _SPORT_WORD:
            return _SPORT_WORD[s.strip().lower()]
    for t in texts:
        words = _text(t)
        if not words:
            continue
        for act, rx in _COMPILED:
            if rx.search(words):
                return act
    if isinstance(kind, str) and kind in _KIND:
        return _KIND[kind]
    return "other"


_CLUBBY = re.compile(r"\b(club|team|crew|society|association|striders|harriers|runners|riders|cyclists|masters|"
                     r"triathletes?|squad|collective)\b", re.IGNORECASE)
_LEAGUE = re.compile(r"\b(league|leagues|ladder|tournament|division|season)\b", re.IGNORECASE)

TYPES = ("club", "league", "meetup")
TYPE_LABEL = {"club": "Club", "league": "League", "meetup": "Meetup"}


def group_type(name: Any, kind: Any = None, description: Any = None) -> str:
    """"league" for leagues (by kind or name), "club" for named clubs and teams, else "meetup"
    (a shop's weekly group run, a pickup game, a social ride)."""
    n, d = _text(name), _text(description)
    if kind == "league" or _LEAGUE.search(n):
        return "league"
    if _CLUBBY.search(n):
        return "club"
    if _LEAGUE.search(d):
        return "league"
    return "meetup"


__all__ = ["ACTIVITIES", "IDS", "LABEL", "TYPES", "TYPE_LABEL", "classify", "group_type"]
