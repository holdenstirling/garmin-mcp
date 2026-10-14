"""Explore "For you": personal race picks from the athlete's interests, goal and calendar.

Deterministic and transparent: every pick carries the reasons it scored and a one-line "why".
Sections (each only when non-empty):

- ``picks``: RunSignup races (``explore.RaceSearch``, interest-derived event types, home zip and
  travel radius, today..12 months in two windows) scored by type match, distance match, timing
  vs the main race (tune-up 3-10 weeks before), registration open and a couple of goal nudges.
  Races in avoided months, in the 14 days before any A race, or already on the calendar are out.
- ``tuneups``: shorter races 3-10 weeks before the main race.
- ``near``: registration-open races in the next 90 days near home. RunSignup gives us no
  participant counts, so this is "Coming up near you", never "Popular".
- ``friends``: future races on followed friends' Rabbit calendars, only for friends who turned on
  race sharing (off by default). Name/date/place/distance only.
- ``bucket``: famous races from the web (``explore.WEB_SYSTEM`` research), only when the athlete
  picked the bucket-list vibe or a travel-race goal; at most once a week per user, stored.

RunSignup failures degrade to whatever is available (``partial``). No Oura data anywhere, and
the web prompt holds only the interests (never other athlete data).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from . import explore as ex

CACHE_TTL = 6 * 3600
PICKS_MAX = 6
SECTION_MAX = 8
RSU_TYPES_MAX = 5
TUNE_MIN_DAYS, TUNE_MAX_DAYS = 21, 70
A_TAPER_DAYS = 14
NEAR_DAYS = 90
PICKS_LEAD_DAYS = 14
BUCKET_EVERY_S = 7 * 86400
MIN_SCORE = 3

# Interest race type -> RunSignup event type (query) and explore categories (matching).
INTEREST_RSU = {"road": "running_race", "trail": "trail_race", "ultra": "ultra", "triathlon": "triathlon",
                "duathlon": "duathlon", "gravel": "gravel_grinder", "road_cycling": "bike_race",
                "mtb": "mountain_bike_race", "swim": "swim", "hike": "hike", "obstacle": "obstacle_course",
                "adventure": "other"}
INTEREST_CATS = {"road": {"road"}, "trail": {"trail"}, "ultra": {"ultra"}, "triathlon": {"triathlon"},
                 "duathlon": {"duathlon"}, "gravel": {"gravel"}, "road_cycling": {"cycling"}, "mtb": {"mtb"},
                 "swim": {"swim"}, "hike": {"hike"}, "obstacle": {"obstacle"}, "adventure": {"other", "obstacle"}}
TYPE_WORD = {"road": "road race", "trail": "trail race", "ultra": "ultra", "triathlon": "triathlon",
             "duathlon": "duathlon", "gravel": "gravel race", "cycling": "bike race", "mtb": "MTB race",
             "swim": "swim", "hike": "hike", "obstacle": "obstacle race", "other": "race"}
_RUN = frozenset({"road", "trail", "ultra", "other", "obstacle", "hike"})
_TRI = frozenset({"triathlon", "duathlon"})
_BIKE = frozenset({"cycling", "gravel", "mtb"})
# Interest distance -> (min km, max km or None, event categories it applies to).
BUCKETS: dict[str, tuple[float, float | None, frozenset[str]]] = {
    "5k": (4.5, 5.5, _RUN), "10k": (9.5, 10.5, _RUN), "half": (20.5, 21.6, _RUN),
    "marathon": (41.5, 42.8, _RUN), "ultra_50k": (43.0, 90.0, _RUN), "ultra_100k_plus": (95.0, None, _RUN),
    "sprint": (15.0, 35.0, _TRI), "olympic": (45.0, 60.0, _TRI), "70.3": (100.0, 125.0, _TRI),
    "140.6": (200.0, 240.0, _TRI), "century": (150.0, 175.0, _BIKE),
}
BUCKET_LABEL = {"5k": "5K", "10k": "10K", "half": "Half-marathon", "marathon": "Marathon", "ultra_50k": "Ultra",
                "ultra_100k_plus": "100K+ ultra", "sprint": "Sprint tri", "olympic": "Olympic tri",
                "70.3": "70.3", "140.6": "140.6", "century": "Century ride"}
RADIUS = {"local": 50, "regional": 250, "anywhere": 250}
DEFAULT_RADIUS = 100
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")


def _key(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _short_name(name: str, n: int = 28) -> str:
    name = " ".join(str(name).split())
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


# ----------------------------------------------------------------- matching --
def event_bucket(ev: dict[str, Any]) -> str | None:
    km = ev.get("distance_km")
    if not isinstance(km, int | float) or isinstance(km, bool):
        return None
    cat = ev.get("type") or "other"
    for name, (lo, hi, cats) in BUCKETS.items():
        if cat in cats and lo <= km and (hi is None or km <= hi):
            return name
    return None


def race_buckets(race: dict[str, Any]) -> set[str]:
    return {b for e in race.get("events") or [] if (b := event_bucket(e))}


def _cats(interests: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for t in interests.get("race_types") or []:
        out |= INTEREST_CATS.get(t, set())
    return out


def _dist_label(ev: dict[str, Any]) -> str:
    b = event_bucket(ev)
    if b:
        return BUCKET_LABEL[b]
    lab = str(ev.get("distance_label") or "").strip()
    if lab:
        return lab[:20]
    km = ev.get("distance_km")
    return f"{km:g} km" if isinstance(km, int | float) else "Shorter race"


def main_race(events: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """The main event if it's still ahead, else the next A race."""
    future = [e for e in events if (_d(e.get("date")) or date.min) >= today]
    return next((e for e in future if e.get("main")), None) or next(
        (e for e in future if e.get("priority") == "A"), None)


def a_race_dates(events: list[dict[str, Any]], today: date) -> list[date]:
    out = []
    for e in events:
        d = _d(e.get("date"))
        if d and d >= today and (e.get("main") or e.get("priority") == "A"):
            out.append(d)
    return out


def blocked(race: dict[str, Any], *, interests: dict[str, Any], a_dates: list[date],
            calendar: set[tuple[str, str]]) -> str | None:
    """Why a race is out ("month", "taper", "calendar"), or None."""
    d = _d(race.get("date"))
    if d is None:
        return "date"
    if d.month in (interests.get("months_avoid") or []):
        return "month"
    if any(0 <= (a - d).days <= A_TAPER_DAYS for a in a_dates):
        return "taper"
    if (str(race.get("name", "")).strip().lower(), race.get("date")) in calendar:
        return "calendar"
    return None


def tune_up(race: dict[str, Any], main: dict[str, Any] | None) -> tuple[int, dict[str, Any]] | None:
    """(weeks before the main race, the shorter event) when ``race`` is a tune-up for it."""
    if not main:
        return None
    md, rd = _d(main.get("date")), _d(race.get("date"))
    if not md or not rd:
        return None
    before = (md - rd).days
    if not TUNE_MIN_DAYS <= before <= TUNE_MAX_DAYS:
        return None
    gkm = ex._goal_km(main)
    evs = [e for e in race.get("events") or [] if isinstance(e.get("distance_km"), int | float)]
    shorter = [e for e in evs if gkm is None or e["distance_km"] < gkm * 0.9]
    if not shorter:
        return None
    best = max(shorter, key=lambda e: e["distance_km"])  # the longest that's still shorter
    return round(before / 7), best


def score(race: dict[str, Any], *, interests: dict[str, Any], main: dict[str, Any] | None,
          a_dates: list[date]) -> dict[str, Any]:
    """Transparent score: {"score", "reasons", "why", "fit"}."""
    pts, reasons = 0, []
    cats = _cats(interests)
    rtypes = set(race.get("types") or [])
    type_hit = sorted(rtypes & cats)
    if type_hit:
        pts += 3
        reasons.append(TYPE_WORD.get(type_hit[0], "race").capitalize())
    want = set(interests.get("distances") or [])
    dist_hit = [b for b in BUCKETS if b in want and b in race_buckets(race)]
    if dist_hit:
        pts += 3
        reasons.append(BUCKET_LABEL[dist_hit[0]])
    tu = tune_up(race, main)
    if tu:
        pts += 4
        reasons.append(f"{tu[0]} weeks before {_short_name(main['name'])}" if main else "Tune-up")
    if race.get("registration_open"):
        pts += 1
        reasons.append("Registration open")
    goals = set(interests.get("goals_next_12mo") or [])
    kms = [e["distance_km"] for e in race.get("events") or [] if isinstance(e.get("distance_km"), int | float)]
    if "first_ultra" in goals and any(k >= 43 for k in kms):
        pts += 2
        reasons.append("First-ultra material")
    if "first_race" in goals and race_buckets(race) & {"5k", "10k", "sprint"}:
        pts += 1
        reasons.append("Friendly first-race distance")
    rd = _d(race.get("date"))
    if rd and any(0 < (rd - a).days <= 21 for a in a_dates):
        pts -= 2
        reasons.append("Soon after your A race")
    why = _why(race, tu, main, type_hit, dist_hit, goals, kms)
    fit = ({"label": "Great fit", "tone": "helps"} if pts >= 8 else
           {"label": "Good fit", "tone": "helps"} if pts >= 5 else {"label": "Worth a look", "tone": "neutral"})
    return {"score": pts, "reasons": reasons, "why": why, "fit": fit}


def _why(race: dict[str, Any], tu: tuple[int, dict[str, Any]] | None, main: dict[str, Any] | None,
         type_hit: list[str], dist_hit: list[str], goals: set[str], kms: list[float]) -> str:
    if tu and main:
        return f"{_dist_label(tu[1])} tune-up {tu[0]} weeks before {_short_name(main['name'])}"
    if "first_ultra" in goals and any(k >= 43 for k in kms):
        return "Could be your first ultra"
    if dist_hit and type_hit:
        word = TYPE_WORD.get(type_hit[0], "race")
        return f"{BUCKET_LABEL[dist_hit[0]]} {word}: right in your wheelhouse".replace("Ultra ultra", "Ultra")
    if dist_hit:
        return f"{BUCKET_LABEL[dist_hit[0]]}, a distance you picked"
    if type_hit:
        rd = _d(race.get("date"))
        when = f" in {_MONTHS[rd.month - 1]}" if rd else ""
        return f"A {TYPE_WORD.get(type_hit[0], 'race')}{when}, clear of your big races"
    return "Fits your calendar"


# ------------------------------------------------------------------ sections --
def compute(races: list[dict[str, Any]], *, interests: dict[str, Any], events: list[dict[str, Any]],
            today: date, near_ok: bool, readiness_status: str | None = None) -> list[dict[str, Any]]:
    """RunSignup races -> the picks / tune-ups / near sections (only non-empty ones)."""
    main = main_race(events, today)
    a_dates = a_race_dates(events, today)
    calendar = {(str(e.get("name", "")).strip().lower(), e.get("date")) for e in events}
    seen: set[str] = set()
    ok: list[dict[str, Any]] = []
    for r in races:
        rd = _d(r.get("date"))
        if r["id"] in seen or rd is None or rd < today:
            continue
        seen.add(r["id"])
        if blocked(r, interests=interests, a_dates=a_dates, calendar=calendar) is None:
            ok.append(r)
    sections: list[dict[str, Any]] = []

    scored = []
    for r in ok:
        rd = _d(r["date"])
        if rd is None or (rd - today).days < PICKS_LEAD_DAYS:
            continue
        s = score(r, interests=interests, main=main, a_dates=a_dates)
        if s["score"] >= MIN_SCORE:
            scored.append(dict(r, **s))
    scored.sort(key=lambda r: (-r["score"], r["date"], r["name"].lower()))
    picks, names = [], set()
    for r in scored:
        n = r["name"].strip().lower()
        if n in names:
            continue
        names.add(n)
        picks.append(r)
        if len(picks) >= PICKS_MAX:
            break
    if picks:
        sections.append({"id": "picks", "title": "Picked for you", "races": picks})

    if main:
        tunes = []
        for r in ok:
            tu = tune_up(r, main)
            if not tu:
                continue
            s = score(r, interests=interests, main=main, a_dates=a_dates)
            tunes.append(dict(r, **s))
        # Closest to ~6 weeks out first, then the better fit.
        md = _d(main["date"])
        tunes.sort(key=lambda r: (abs(((md - _d(r["date"])).days if md else 42) - 42) // 7, -r["score"], r["date"]))
        if tunes:
            sec: dict[str, Any] = {"id": "tuneups", "title": f"Tune-ups for {_short_name(main['name'], 40)}",
                                   "races": tunes[:SECTION_MAX]}
            if readiness_status in ("behind", "at_risk"):
                sec["note"] = "You're a bit behind for your big race: run a tune-up as a hard training day, not an all-out effort."
            sections.append(sec)

    if near_ok:
        pick_ids = {r["id"] for r in picks}
        near = []
        for r in ok:
            rd = _d(r["date"])
            if not rd or r["id"] in pick_ids or not r.get("registration_open") or (rd - today).days > NEAR_DAYS:
                continue
            days = (rd - today).days
            why = "This week" if days < 7 else f"In {days // 7} week{'s' if days >= 14 else ''}"
            near.append(dict(r, why=why))
        near.sort(key=lambda r: (r["date"], r["name"].lower()))
        if near:
            sections.append({"id": "near", "title": "Coming up near you", "races": near[:SECTION_MAX]})
    return sections


# ------------------------------------------------------------------- friends --
_EVENT_CAT = {"triathlon": "triathlon", "running": "road", "trail": "trail", "cycling": "cycling",
              "swimming": "swim", "duathlon": "duathlon", "mountaineering": "hike", "other": "other"}


def friend_races(friends: list[tuple[str, list[dict[str, Any]]]], today: date) -> list[dict[str, Any]]:
    """``friends``: [(first name, their events)] for followees who share races. Only name, date,
    place, distance and type leave their calendar; same race + date is merged."""
    by: dict[str, dict[str, Any]] = {}
    for name, events in friends:
        for e in events:
            d = _d(e.get("date"))
            if not d or d < today or not e.get("name"):
                continue
            rid = "friend:" + hashlib.sha256(f"{str(e['name']).strip().lower()}|{d}".encode()).hexdigest()[:12]
            if rid in by:
                if name not in by[rid]["friends"]:
                    by[rid]["friends"].append(name)
                continue
            cat = _EVENT_CAT.get(str(e.get("type") or "other"), "other")
            loc = ex._short(e.get("location"), 80)
            city, _, state = loc.partition(",")
            dist = ex._short(e.get("distance"), 30)
            km = ex._goal_km(e)
            evs = [{"name": dist or "Race", "distance_km": km, "distance_label": dist if dist != "other" else "",
                    "type": cat, "start_time": None, "date": d.isoformat(), "fee_from": None}]
            by[rid] = {"id": rid, "source": "friend", "name": ex._short(e["name"], 120), "date": d.isoformat(),
                       "end_date": None, "city": city.strip()[:60], "state": state.strip()[:20], "zip": "",
                       "location": loc, "url": ex._url(e.get("url")), "website": None, "logo": None,
                       "registration_open": None, "summary": "", "events": evs, "types": [cat],
                       "min_km": km, "max_km": km, "friends": [name]}
    out = sorted(by.values(), key=lambda r: (r["date"], r["name"].lower()))[:SECTION_MAX]
    for r in out:
        f = r["friends"]
        who = f[0] if len(f) == 1 else (f"{f[0]} and {f[1]}" if len(f) == 2 else f"{f[0]}, {f[1]} and {len(f) - 2} more")
        r["why"] = f"{who} {'is' if len(f) == 1 else 'are'} racing"
    return out


# -------------------------------------------------------------------- bucket --
def wants_bucket(interests: dict[str, Any]) -> bool:
    return "bucket_list" in (interests.get("race_vibe") or []) or "travel_race" in (interests.get("goals_next_12mo") or [])


_TYPE_LABEL = {"road": "road running", "trail": "trail running", "ultra": "ultramarathon", "triathlon": "triathlon",
               "duathlon": "duathlon", "gravel": "gravel cycling", "road_cycling": "road cycling",
               "mtb": "mountain biking", "swim": "open water swimming", "hike": "hiking", "obstacle": "obstacle racing",
               "adventure": "adventure racing"}


def bucket_prompt(interests: dict[str, Any], today: date) -> str:
    end = ex._add_months(today, 12)
    bits = [f"Find up to {ex.AI_MAX_RACES} famous bucket-list races (iconic, worth travelling for) "
            f"between {today.isoformat()} and {end.isoformat()}."]
    if interests.get("race_types"):
        bits.append("Kinds: " + ", ".join(_TYPE_LABEL[t] for t in interests["race_types"] if t in _TYPE_LABEL) + ".")
    if interests.get("distances"):
        bits.append("Distances: " + ", ".join(BUCKET_LABEL[d] for d in interests["distances"] if d in BUCKET_LABEL) + ".")
    if interests.get("months_avoid"):
        bits.append("Skip races in: " + ", ".join(_MONTHS[m - 1] for m in interests["months_avoid"]) + ".")
    return "\n".join(bits)


def clean_bucket(raw: Any, interests: dict[str, Any], today: date) -> list[dict[str, Any]]:
    if isinstance(raw, str):  # no tool call: try a JSON object in the text
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            raw = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            raw = {}
    avoid = set(interests.get("months_avoid") or [])
    out = []
    for r in ex.clean_web(raw, today):
        if (_d(r["date"]) or today).month in avoid:
            continue
        out.append(dict(r, why="Bucket-list race, found on the web"))
    return out


# ------------------------------------------------------------------- service --
class ForYou:
    """Fetches RunSignup for the athlete's interests and caches the computed sections per user
    for ``CACHE_TTL`` (keyed by interests + calendar, so edits show at once)."""

    def __init__(self, *, search: Callable[[], ex.RaceSearch] = ex.default_search,
                 clock: Callable[[], float] = time.time) -> None:
        self._search = search
        self.cache = ex._TTLCache(CACHE_TTL, 500, clock)

    @staticmethod
    def location(interests: dict[str, Any], athlete: dict[str, Any]) -> tuple[str, int]:
        z = interests.get("home_zip") or ex.home_zip(athlete.get("home_location"))
        return z, RADIUS.get(interests.get("travel") or "", DEFAULT_RADIUS)

    @staticmethod
    def rsu_types(interests: dict[str, Any], athlete: dict[str, Any]) -> list[str]:
        out = [INTEREST_RSU[t] for t in interests.get("race_types") or [] if t in INTEREST_RSU]
        if not out:  # no interests yet: favorite sports
            cats = ex.defaults(athlete)["types"]
            out, _ = ex.rsu_types(cats)
        seen: list[str] = []
        for t in out:
            if t not in seen:
                seen.append(t)
        return seen[:RSU_TYPES_MAX]

    def windows(self, events: list[dict[str, Any]], today: date) -> list[tuple[date, date]]:
        soon_end = ex._add_months(today, 3)
        wins = [(today, soon_end), (soon_end, ex._add_months(today, 12))]
        main = main_race(events, today)
        md = _d(main.get("date")) if main else None
        if md:
            s, e = max(today, md - timedelta(days=TUNE_MAX_DAYS)), md - timedelta(days=TUNE_MIN_DAYS)
            if e > s:
                wins.append((s, e))
        return wins

    async def sections(self, uid: str, *, interests: dict[str, Any], athlete: dict[str, Any],
                       events: list[dict[str, Any]], today: date, readiness_status: str | None = None,
                       fresh: bool = False) -> dict[str, Any]:
        """{"sections", "partial", "zip", "radius"}."""
        zip_, radius = self.location(interests, athlete)
        types = self.rsu_types(interests, athlete)
        sig = [(e.get("id"), e.get("name"), e.get("date"), e.get("priority"), e.get("main"), e.get("distance"))
               for e in events]
        key = uid + ":" + _key({"i": interests, "z": zip_, "r": radius, "t": types, "e": sig,
                                "d": today.isoformat(), "rs": readiness_status})
        if not fresh and (hit := self.cache.get(key)) is not None:
            return hit
        fs = []
        for s, e in self.windows(events, today):
            f = ex.parse_filters({"near": zip_, "radius": radius, "start": s.isoformat(), "end": e.isoformat()}
                                 if zip_ else {"start": s.isoformat(), "end": e.isoformat()}, today)
            f["rsu"] = types
            fs.append(f)
        search = self._search()
        got = await asyncio.gather(*(search.search(f) for f in fs), return_exceptions=True)
        ok = [g for g in got if isinstance(g, dict)]
        partial = len(ok) < len(got) or any(g.get("partial") for g in ok)
        races = [r for g in ok for r in g["races"]]
        out = {"sections": compute(races, interests=interests, events=events, today=today, near_ok=bool(zip_),
                                   readiness_status=readiness_status),
               "partial": partial, "failed": not ok, "zip": zip_, "radius": radius}
        if not partial:
            self.cache.put(key, out)
        return out


_default: ForYou | None = None


def default_foryou() -> ForYou:
    global _default
    if _default is None:
        _default = ForYou()
    return _default


__all__ = ["BUCKETS", "ForYou", "a_race_dates", "blocked", "bucket_prompt", "clean_bucket", "compute",
           "default_foryou", "event_bucket", "friend_races", "main_race", "score", "tune_up", "wants_bucket"]
