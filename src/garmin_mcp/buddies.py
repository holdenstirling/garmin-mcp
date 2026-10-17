"""Training buddies: opt-in matching with people near you at a similar easy pace and schedule.

Off by default. A buddy profile holds: sports, an easy-pace band per sport (suggested from the
athlete's own recent Garmin workouts: runs as seconds per km, rides as km/h; the band, never a
single workout, and never heart rate), usual training slots (weekday x morning / midday /
evening, suggested from recent start times), an optional race and a short note. Where: the
athlete's Local area (area.py: saved "Use my location" spot when on, plus radius) stored only as
a point rounded to 2 decimals (about 1 km) for distance math, and their city for display.

Matching is deterministic: both opted in and not paused, not blocked either way, a sport in
common, within BOTH people's radius (or the same city when either has no point), and at least
one of: easy-pace bands overlapping within 10 % or a training slot in common. Scored by pace
fit, shared slots, same race and distance; explained in plain chips ("Similar easy pace",
"Both run Tue and Thu evenings", "About 2 mi away").

Others see: first name / photo, the sports, the pace band, the slots, the race, the note, their
city and a rounded distance. Never coordinates, neighbourhood, heart rate or single workouts.

"Say hi" opens a direct message (messages.py): a request unless you're already connected.
Rate limited per day. "Not now" hides a match for you only.
"""

from __future__ import annotations

import math
import re
import statistics
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from .area import WEEKDAYS, WHEN, part_of_day

SPORTS = ("run", "trail", "ride", "swim")
SPORT_WORD = {"run": "run", "trail": "trail run", "ride": "ride", "swim": "swim"}
SLOTS = tuple(f"{d}-{w}" for d in WEEKDAYS for w in WHEN)
NOTE_LEN = 160
RACE_LEN = 60
MAX_SLOTS = 12
HI_PER_DAY = 10
LOOKBACK_DAYS = 56
PACE_TOL = 0.10
KM_PER_MI = 1.609344
# sane bands: run / trail pace in s/km, ride in km/h, swim in s/100 m
RANGES = {"run": (150, 900), "trail": (150, 1200), "ride": (8, 60), "swim": (50, 240)}
_UID = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")
DAY_NAME = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


class BuddyError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------ suggestion --
def _sport(a: dict[str, Any]) -> str | None:
    k = str(a.get("sport") or "").lower()
    if "trail" in k:
        return "trail"
    if "run" in k:
        return "run"
    if "cycl" in k or "bik" in k or "ride" in k:
        return "ride"
    if "swim" in k:
        return "swim"
    return None


def _minutes(v: Any) -> float | None:
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v) / 60
    if isinstance(v, str) and re.fullmatch(r"\d+(:\d{1,2}){1,2}", v.strip()):
        p = [int(x) for x in v.strip().split(":")]
        sec = p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
        return sec / 60
    return None


def _start(a: dict[str, Any]) -> datetime | None:
    s = str(a.get("date") or "").strip().replace("T", " ")
    try:
        return datetime.fromisoformat(s[:19]) if len(s) >= 16 else None
    except ValueError:
        return None


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def suggest(acts: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """From the athlete's own recent workouts: sports, easy-pace bands, usual slots."""
    since = today - timedelta(days=LOOKBACK_DAYS)
    by: dict[str, list[float]] = {}
    count: dict[str, int] = {}
    slots: dict[str, int] = {}
    for a in acts or []:
        if (a.get("multisport") or {}).get("is_parent"):
            continue
        sp = _sport(a)
        st = _start(a)
        if sp is None or st is None or st.date() < since or st.date() > today:
            continue
        count[sp] = count.get(sp, 0) + 1
        part = part_of_day(st.strftime("%H:%M"))
        if part:
            k = f"{WEEKDAYS[st.weekday()]}-{part}"
            slots[k] = slots.get(k, 0) + 1
        mins, km = _minutes(a.get("duration")), a.get("distance_km")
        if not mins or not isinstance(km, int | float) or km <= 0:
            continue
        if sp in ("run", "trail") and mins >= 20 and km >= 3:
            by.setdefault(sp, []).append(mins * 60 / km)
        elif sp == "ride" and mins >= 30 and km >= 8:
            by.setdefault(sp, []).append(km / (mins / 60))
        elif sp == "swim" and mins >= 15 and km >= 0.5:
            by.setdefault(sp, []).append(mins * 60 / (km * 10))
    pace: dict[str, list[float]] = {}
    for sp, xs in by.items():
        if len(xs) < 3:
            continue
        if sp == "ride":  # easy = the slower half of speeds; at least 2 km/h wide
            lo, hi = _pct(xs, 0.2), statistics.median(xs)
            mid, half = (lo + hi) / 2, max((hi - lo) / 2, 1.0)
            pace[sp] = [round(mid - half, 1), round(mid + half, 1)]
        else:  # easy = the slower half of paces; at least 20 s/km (5 s/100 m for swims) wide
            lo, hi = statistics.median(xs), _pct(xs, 0.85)
            mid, half = (lo + hi) / 2, max((hi - lo) / 2, 2.5 if sp == "swim" else 10.0)
            pace[sp] = [5 * round((mid - half) / 5), 5 * round((mid + half) / 5)]
    sports = [s for s in SPORTS if count.get(s, 0) >= 2]
    top = sorted((k for k, n in slots.items() if n >= 2), key=lambda k: (-slots[k], SLOTS.index(k)))[:6]
    return {"sports": sports, "pace": {k: v for k, v in pace.items() if k in sports}, "slots": top}


# ------------------------------------------------------------- matching --
def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h))) / KM_PER_MI


def pace_overlap(a: list[float] | None, b: list[float] | None, tol: float = PACE_TOL) -> bool | None:
    """None when either has no band (unknown); else whether the bands overlap within ``tol``."""
    if not a or not b:
        return None
    lo1, hi1 = min(a) * (1 - tol), max(a) * (1 + tol)
    lo2, hi2 = min(b), max(b)
    return lo1 <= hi2 and lo2 <= hi1


def _slot_words(slots: list[str]) -> str:
    """["tue-evening", "thu-evening"] -> "Tue and Thu evenings"."""
    by: dict[str, list[str]] = {}
    for s in slots:
        d, w = s.split("-")
        by.setdefault(w, []).append(DAY_NAME[d])
    parts = []
    for w in WHEN:
        if w in by:
            days = by[w]
            ds = days[0] if len(days) == 1 else ", ".join(days[:-1]) + " and " + days[-1]
            parts.append(f"{ds} {w}{'s' if len(days) > 1 else ''}")
    return "; ".join(parts)


def _dist_word(mi: float | None, city: str) -> str:
    if mi is None:
        return f"In {city}" if city else "Near you"
    if mi < 1:
        return "Under 1 mi away"
    return f"About {round(mi)} mi away"


def match(me: dict[str, Any], other: dict[str, Any]) -> dict[str, Any] | None:
    """Score and explain one candidate, or None when they don't fit."""
    common = [s for s in me.get("sports", []) if s in other.get("sports", [])]
    if not common:
        return None
    pa, pb = me.get("center"), other.get("center")
    mi: float | None = None
    if pa and pb:
        mi = _miles(tuple(pa), tuple(pb))  # type: ignore[arg-type]
        if mi > min(int(me.get("radius_mi") or 10), int(other.get("radius_mi") or 10)):
            return None
    elif not (me.get("metro") and me.get("metro") == other.get("metro")):
        return None
    paces = {s: pace_overlap(me.get("pace", {}).get(s), other.get("pace", {}).get(s)) for s in common}
    pace_ok = [s for s, v in paces.items() if v]
    if all(v is False for v in paces.values()):
        return None
    shared = [s for s in me.get("slots", []) if s in other.get("slots", [])]
    if not pace_ok and not shared:
        return None
    sport = pace_ok[0] if pace_ok else common[0]
    race = (other.get("race") or "").strip()
    same_race = bool(race) and race.lower() == (me.get("race") or "").strip().lower()
    score = 3 * len(pace_ok) + min(len(shared), 3) * 2 + (3 if same_race else 0) + len(common)
    if mi is not None:
        score += max(0.0, 3 - mi / 3)
    chips = []
    if pace_ok:
        chips.append("Similar easy pace")
    if shared:
        chips.append(f"Both {SPORT_WORD[sport]} {_slot_words(shared[:3])}")
    if same_race:
        chips.append(f"Both training for {race}")
    chips.append(_dist_word(mi, other.get("city") or ""))
    return {"score": round(score, 2), "sport": sport, "sports": common, "chips": chips, "shared_slots": shared,
            "distance_mi": None if mi is None else (0 if mi < 1 else round(mi))}


# --------------------------------------------------------------- service --
def _clean_band(sport: str, v: Any) -> list[float] | None:
    if v is None:
        return None
    if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int | float) and not isinstance(x, bool) for x in v)):
        raise BuddyError("Pace bands are two numbers.")
    lo, hi = sorted(float(x) for x in v)
    a, b = RANGES[sport]
    if lo < a or hi > b or hi - lo > (b - a) / 2:
        raise BuddyError("That pace band doesn't look right.")
    return [round(lo, 1), round(hi, 1)]


class Buddies:
    def __init__(self, store: Any, *, is_athlete: Callable[[str], bool], blocked: Callable[[str, str], bool],
                 follows: Callable[[str, str], bool], activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                 area: Callable[[str], dict[str, Any]], home: Callable[[str], dict[str, str]],
                 person: Callable[[str], dict[str, Any] | None], first_name: Callable[[str], str],
                 say: Callable[[str, str, str], dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._doc = store.global_doc("buddies")
        self._is_athlete = is_athlete
        self._blocked = blocked
        self._follows = follows
        self._acts = activities
        self._area = area
        self._home = home
        self._person = person
        self._first = first_name
        self._say = say  # (uid, other, text) -> conversation view (messages.py start + send)
        self._clock = clock
        self._lock = threading.Lock()

    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            raise BuddyError("Training buddies are for athletes on Rabbit.", 403)

    # -- where: rounded point + city, refreshed from the athlete's Local area on every save
    def _where(self, uid: str) -> dict[str, Any]:
        a = self._area(uid) or {}
        c = a.get("center")
        h = self._home(uid) or {}
        city, st = (h.get("city") or "").strip(), (h.get("state") or "").strip()
        return {"center": [round(float(c[0]), 2), round(float(c[1]), 2)] if c else None,
                "radius_mi": int(a.get("radius_mi") or 10),
                "metro": f"{city.lower()}|{st.upper()}" if city else "",
                "city": f"{city}, {st}" if city and st else city}

    def suggestion(self, uid: str) -> dict[str, Any]:
        try:
            today, acts = self._acts(uid)
        except Exception:  # Garmin down / not connected: start from nothing
            return {"sports": [], "pace": {}, "slots": []}
        return suggest(acts, today)

    def get(self, uid: str) -> dict[str, Any]:
        self.require(uid)
        prof = (self._doc.load().get("profiles") or {}).get(uid)
        w = self._where(uid)
        return {"profile": self._public_self(prof) if prof else None, "suggested": self.suggestion(uid),
                "area": {"city": w["city"], "radius_mi": w["radius_mi"], "has_point": w["center"] is not None}}

    @staticmethod
    def _public_self(p: dict[str, Any]) -> dict[str, Any]:
        return {k: p.get(k) for k in ("sports", "pace", "slots", "race", "note", "paused", "updated")}

    def save(self, uid: str, body: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(body, dict):
            raise BuddyError("bad request")
        sports = body.get("sports")
        if not isinstance(sports, list) or not sports or any(s not in SPORTS for s in sports):
            raise BuddyError("Pick at least one sport.")
        sports = [s for s in SPORTS if s in sports]
        pace_in = body.get("pace") or {}
        if not isinstance(pace_in, dict):
            raise BuddyError("bad pace")
        pace = {s: b for s in sports if (b := _clean_band(s, pace_in.get(s))) is not None}
        slots = body.get("slots") or []
        if not isinstance(slots, list) or any(s not in SLOTS for s in slots) or len(slots) > MAX_SLOTS:
            raise BuddyError("Pick up to 12 usual times.")
        race = body.get("race") or ""
        note = body.get("note") or ""
        if not isinstance(race, str) or not isinstance(note, str):
            raise BuddyError("bad text")
        race = " ".join(race.split())[:RACE_LEN]
        note = " ".join(note.split())[:NOTE_LEN]
        paused = body.get("paused") is True
        prof = {"sports": sports, "pace": pace, "slots": [s for s in SLOTS if s in slots], "race": race, "note": note,
                "paused": paused, "updated": int(self._clock()), **self._where(uid)}

        def put(d: dict[str, Any]) -> None:
            d.setdefault("profiles", {})[uid] = prof
        self._doc.update(put)
        return self.get(uid)

    def delete(self, uid: str) -> None:
        self.require(uid)

        def drop(d: dict[str, Any]) -> None:
            (d.get("profiles") or {}).pop(uid, None)
            (d.get("hidden") or {}).pop(uid, None)
        self._doc.update(drop)

    def hide(self, uid: str, other: Any) -> None:
        self.require(uid)
        if not isinstance(other, str) or not _UID.fullmatch(other):
            raise BuddyError("bad person")

        def put(d: dict[str, Any]) -> None:
            h = d.setdefault("hidden", {}).setdefault(uid, [])
            if other not in h:
                h.append(other)
                del h[:-500]
        self._doc.update(put)

    def matches(self, uid: str, limit: int = 20) -> dict[str, Any]:
        self.require(uid)
        d = self._doc.load()
        profs = d.get("profiles") or {}
        me = profs.get(uid)
        if not me:
            return {"matches": [], "reason": "off"}
        if me.get("paused"):
            return {"matches": [], "reason": "paused"}
        me = {**me, **self._where(uid)}  # my area may have moved since I saved
        hidden = set((d.get("hidden") or {}).get(uid, []))
        out = []
        for oid, p in profs.items():
            if oid == uid or oid in hidden or p.get("paused") or oid.startswith("coach_"):
                continue
            if not self._is_athlete(oid) or self._blocked(uid, oid):
                continue
            m = match(me, p)
            if m is None:
                continue
            who = self._person(oid) or {"id": oid, "name": self._first(oid)}
            out.append({**m, "person": who, "pace": p.get("pace", {}).get(m["sport"]), "slots": p.get("slots", []),
                        "race": p.get("race") or "", "note": p.get("note") or "", "city": p.get("city") or "",
                        "following": self._follows(uid, oid), "follows_you": self._follows(oid, uid)})
        out.sort(key=lambda x: -x["score"])
        return {"matches": out[:limit], "reason": None if out else "none"}

    def say_hi(self, uid: str, other: Any, text: Any = None) -> dict[str, Any]:
        """Open a DM (a request unless you're connected) with a short intro. Only to a current
        match; rate limited."""
        self.require(uid)
        if not isinstance(other, str) or not _UID.fullmatch(other):
            raise BuddyError("bad person")
        hit = next((m for m in self.matches(uid, limit=200)["matches"] if m["person"]["id"] == other), None)
        if hit is None:
            raise BuddyError("That person isn't a match right now.", 404)
        if text is not None and not isinstance(text, str):
            raise BuddyError("bad text")
        msg = " ".join((text or "").split())[:400] or (
            f"Hi {self._first(other)}! Rabbit matched us as training buddies ({', '.join(hit['chips'][:2]).lower()}). "
            f"Want to {SPORT_WORD[hit['sport']]} together sometime?")
        now = self._clock()

        def bump(d: dict[str, Any]) -> None:
            ts = [t for t in d.setdefault("sent", {}).get(uid, []) if now - t < 86400]
            if len(ts) >= HI_PER_DAY:
                raise BuddyError("That's plenty of hellos for today. Try again tomorrow.", 429)
            d["sent"][uid] = [*ts, now]
        with self._lock:
            self._doc.update(bump)
        if self._say is None:
            raise BuddyError("Messages aren't available right now.", 503)
        return self._say(uid, other, msg)
