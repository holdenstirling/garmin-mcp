""""Let Rabbit explore": one tap, no typing, everything Rabbit can find for you.

The webapp combines: the For you sections (``foryou.ForYou.sections``: RunSignup around the
resolved location, or nationwide), an AI web scout for notable races (``scout_prompt``: built
only from the athlete's race interests, a city/state, the main race / goal and the readiness
status word; never a zip, coordinates or any Oura data; cached 24 h per prompt, daily
allowance on a miss), places to play nearby (``local.Places``, OpenStreetMap) and group
activities (``localacts``). Races are merged, de-duplicated (same race id, or the same name
within 3 days), calendar/taper/avoided-month races dropped, ranked with ``foryou.score`` (a
small nudge for notable web finds), each with a one-line "why", plus a deterministic intro and
a "Rabbit found N things for you" summary.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

from . import explore as ex
from . import foryou as fy

MONTHS = 6
LIMIT = 20
WEB_NUDGE = 1
PLACES_SHOWN = 8
GROUPS_SHOWN = 8
SCOUT_TTL = 24 * 3600
_READINESS_WORD = {"on_track": "on track", "ahead": "ahead of schedule", "behind": "a bit behind",
                   "at_risk": "behind (keep races low-key)"}


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def dedupe(lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """First wins (pass RunSignup first: it has registration and fees); a later copy of the same
    race only fills in a missing summary."""
    out: list[dict[str, Any]] = []
    for lst in lists:
        for r in lst:
            rd = _d(r.get("date"))
            dup = next((o for o in out if o["id"] == r["id"] or (
                fy.same_name(o["name"], r["name"]) and rd and (od := _d(o["date"])) and abs((od - rd).days) <= 3)), None)
            if dup is None:
                out.append(dict(r))
            elif not dup.get("summary") and r.get("summary"):
                dup["summary"] = r["summary"]
    return out


def rank(races: list[dict[str, Any]], *, interests: dict[str, Any], events: list[dict[str, Any]],
         today: date) -> tuple[list[dict[str, Any]], int]:
    """(all ranked races with score/why/fit, how many are tune-ups for the main race); the
    caller shows the first ``LIMIT``."""
    main = fy.main_race(events, today)
    a_dates = fy.a_race_dates(events, today)
    calendar = {(str(e.get("name", "")).strip().lower(), e.get("date")) for e in events}
    out = []
    tunes = 0
    for r in races:
        rd = _d(r.get("date"))
        if rd is None or rd < today:
            continue
        if fy.blocked(r, interests=interests, a_dates=a_dates, calendar=calendar):
            continue
        s = fy.score(r, interests=interests, main=main, a_dates=a_dates)
        tu = fy.tune_up(r, main)
        tunes += bool(tu)
        pts = s["score"] + (WEB_NUDGE if r.get("source") == "web" else 0)
        why = s["why"]
        if why == "Fits your calendar":
            why = ("A notable race rabbt found on the web" if r.get("source") == "web"
                   else f"Coming up {'this week' if (rd - today).days < 7 else 'in ' + fy._MONTHS[rd.month - 1]}")
        out.append({**r, **s, "score": pts, "why": why, "tune_up": bool(tu)})
    out.sort(key=lambda r: (-r["score"], r["date"], r["name"].lower()))
    return out, tunes


def intro(n: int, *, zip_: str, state: str, radius: int, tunes: int, main: dict[str, Any] | None,
          months: int = MONTHS) -> str:
    where = f"within {radius} mi" if zip_ else (f"in {state}" if state else "around the country")
    if n == 0:
        return f"No races turned up {where} in the next {months} months. Try a bigger trip radius in your interests."
    s = f"Found {n} race{'s' if n != 1 else ''} {where} in the next {months} months"
    if tunes and main:
        s += f"; {tunes} {'is a great tune-up' if tunes == 1 else 'are great tune-ups'} for {fy._short_name(main['name'])}"
    return s + "."


def scout_prompt(interests: dict[str, Any], *, area: str, main: dict[str, Any] | None,
                 goal: dict[str, Any] | None, readiness: str | None, today: date, months: int = MONTHS) -> str:
    """The web scout's request. Only: race types/distances/vibe, "City, ST" (or nothing), the
    main race or goal (name, date, distance), and a readiness status word. Never a zip,
    coordinates, health data or anything from Oura."""
    end = ex._add_months(today, months)
    bits = [f"Find up to {ex.AI_MAX_RACES} notable upcoming races (well-known, well-reviewed or special) "
            f"between {today.isoformat()} and {end.isoformat()} that a race listing site might miss."]
    types = [fy._TYPE_LABEL[t] for t in interests.get("race_types") or [] if t in fy._TYPE_LABEL]
    if types:
        bits.append("Kinds: " + ", ".join(types) + ".")
    dists = [fy.BUCKET_LABEL[d] for d in interests.get("distances") or [] if d in fy.BUCKET_LABEL]
    if dists:
        bits.append("Distances: " + ", ".join(dists) + ".")
    if interests.get("race_vibe"):
        bits.append("Vibe: " + ", ".join(str(v).replace("_", " ") for v in interests["race_vibe"][:3]) + ".")
    if area:
        travel = interests.get("travel")
        reach = "anywhere worth the trip" if travel == "anywhere" else (
            "within a road trip" if travel == "regional" else "close by")
        bits.append(f"The athlete lives near {json.dumps(area[:80])}: mostly {reach}, plus one or two famous ones.")
    else:
        bits.append("Anywhere in the US.")
    if main and main.get("name") and main.get("date"):
        dist = str(main.get("distance") or "").strip()
        bits.append(f"Their big race: {json.dumps(ex._short(main['name'], 80))} on {main['date']}"
                    f"{f' ({dist})' if dist and dist != 'other' else ''}. Suggest good tune-ups 3-10 weeks before it, "
                    "and nothing in the 2 weeks before it.")
    elif goal and (goal.get("event") or goal.get("title")):
        bits.append(f"Their goal: {json.dumps(ex._short(goal.get('event') or goal.get('title'), 80))}.")
    if readiness in _READINESS_WORD:
        bits.append(f"Training for it is {_READINESS_WORD[readiness]}.")
    if interests.get("months_avoid"):
        bits.append("Skip races in: " + ", ".join(fy._MONTHS[m - 1] for m in interests["months_avoid"]) + ".")
    return "\n".join(bits)


class ScoutCache:
    """Scout results per prompt for 24 h (shared: the prompt holds no personal identifiers)."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._d: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()

    def get(self, prompt: str) -> list[dict[str, Any]] | None:
        with self._lock:
            hit = self._d.get(self.key(prompt))
        if hit and self._clock() - hit[0] < SCOUT_TTL:
            return [dict(r) for r in hit[1]]
        return None

    def put(self, prompt: str, races: list[dict[str, Any]]) -> None:
        with self._lock:
            self._d[self.key(prompt)] = (self._clock(), races)
            if len(self._d) > 500:
                self._d.pop(min(self._d, key=lambda k: self._d[k][0]))


def summary(n_races: int, n_places: int, n_groups: int) -> str:
    n = n_races + n_places + n_groups
    if n == 0:
        return "rabbt looked everywhere but came back empty-handed this time"
    return f"rabbt found {n} thing{'s' if n != 1 else ''} for you"


__all__ = ["ScoutCache", "dedupe", "intro", "rank", "scout_prompt", "summary"]
