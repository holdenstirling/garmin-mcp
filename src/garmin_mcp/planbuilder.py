"""Rabbit's plan builder: athlete profile + race goal -> a periodized plan of structured
sessions, plus the conversions the rest of the app needs (detail text, Garmin workout JSON,
a Markdown summary for the coach's context).

Everything here is pure and deterministic: no I/O, no model calls. ``plans.py`` stores the
result per goal and syncs sessions to Garmin.

Plan shape::

    {"start": "YYYY-MM-DD" (Monday of week 1), "race_date", "weeks": [
        {"index": 1, "start": "YYYY-MM-DD", "phase": "base"|"build"|"peak"|"taper"|"race",
         "recovery": bool, "hours": float, "focus": str,
         "days": {"YYYY-MM-DD": [session, ...], ...}}, ...]}

Session::

    {"id", "sport": swim|bike|run|brick|strength|rest|other, "kind", "title", "minutes",
     "detail", "steps": [step|repeat], "legs": [{"sport", "minutes", "steps"}] (bricks only),
     "meters" (swims)}

Step: ``{"type": warmup|steady|work|recover|cooldown, "minutes"|"meters", "zone": 1..5}``;
repeat: ``{"type": "repeat", "reps": n, "steps": [step, ...]}``. Zones are the athlete's
own five training zones (heart rate, or power/pace when their thresholds are known).
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import recur

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LEVELS = ("new", "intermediate", "advanced")
EQUIPMENT = ("pool", "open_water", "power_meter", "indoor_trainer", "hr_strap", "treadmill", "gym")
DEFAULT_DAYS = ("tue", "wed", "thu", "sat", "sun")
MAX_WEEKS = 52
MAX_PER_DAY = 4
# Favorite sports (athlete profile) -> the engine sport they train.
FAVORITE_SPORTS = ("run", "trail", "bike", "gravel", "mtb", "swim", "open_water", "strength",
                   "yoga", "hike", "climb", "ski", "row", "walk")
FAVORITE_ENGINE = {"run": "run", "trail": "run", "hike": "run", "walk": "run", "climb": "run",
                   "ski": "run", "bike": "bike", "gravel": "bike", "mtb": "bike", "row": "bike",
                   "swim": "swim", "open_water": "swim"}
ZONE_NAMES = {1: "easy", 2: "aerobic", 3: "tempo", 4: "threshold", 5: "hard"}

# kind: tri | run | bike | general. peak: weekly hours at peak for new/intermediate/advanced.
# taper: weeks. long: caps on the long session per sport (minutes).
RACES: dict[str, dict[str, Any]] = {
    "sprint triathlon": {"kind": "tri", "peak": (5.0, 7.0, 9.0), "taper": 1,
                         "long": {"bike": 90, "run": 60, "swim": 45}},
    "olympic triathlon": {"kind": "tri", "peak": (7.0, 9.0, 12.0), "taper": 1,
                          "long": {"bike": 150, "run": 80, "swim": 60}},
    "70.3": {"kind": "tri", "peak": (9.0, 12.0, 15.0), "taper": 2,
             "long": {"bike": 210, "run": 110, "swim": 70}},
    "140.6": {"kind": "tri", "peak": (12.0, 16.0, 20.0), "taper": 3,
              "long": {"bike": 330, "run": 150, "swim": 80}},
    "5k": {"kind": "run", "peak": (3.5, 5.0, 7.0), "taper": 1, "long": {"run": 70}},
    "10k": {"kind": "run", "peak": (4.0, 6.0, 8.0), "taper": 1, "long": {"run": 85}},
    "half marathon": {"kind": "run", "peak": (5.0, 7.0, 9.0), "taper": 2, "long": {"run": 120}},
    "marathon": {"kind": "run", "peak": (6.0, 9.0, 12.0), "taper": 3, "long": {"run": 180}},
    "ultra": {"kind": "run", "peak": (8.0, 11.0, 14.0), "taper": 2, "long": {"run": 240}},
    "century ride": {"kind": "bike", "peak": (7.0, 10.0, 13.0), "taper": 1, "long": {"bike": 300}},
    "other": {"kind": "general", "peak": (5.0, 7.0, 9.0), "taper": 1,
              "long": {"bike": 150, "run": 90}},
}
SPLIT = {
    "tri": {"swim": 0.2, "bike": 0.5, "run": 0.3},
    "run": {"run": 0.88, "strength": 0.12},
    "bike": {"bike": 0.9, "strength": 0.1},
    "general": {"run": 0.45, "bike": 0.45, "strength": 0.1},
}
# Relative share of a sport's weekly minutes per session kind.
WEIGHT = {"long": 2.2, "brick": 2.4, "endurance": 1.4, "threshold": 1.2, "tempo": 1.2,
          "racepace": 1.2, "vo2": 1.0, "easy": 1.0, "strides": 1.0, "recovery": 0.7,
          "technique": 1.0, "css": 1.0, "strength": 1.0}
QUALITY = {"threshold", "tempo", "vo2", "racepace", "css"}
KIND_TITLES = {
    "long": "Long {sport}", "endurance": "Endurance {sport}", "easy": "Easy {sport}",
    "recovery": "Recovery {sport}", "strides": "Easy run + strides", "tempo": "Tempo {sport}",
    "threshold": "Threshold {sport}", "vo2": "VO2 intervals", "racepace": "Race-pace {sport}",
    "technique": "Technique swim", "css": "CSS swim intervals", "strength": "Strength & mobility", "mobility": "Mobility",
    "brick": "Brick: bike + run", "openers": "Openers", "shakeout": "Shakeout {sport}",
    "race": "Race day", "rest": "Rest day",
}
SPORT_WORD = {"swim": "swim", "bike": "ride", "run": "run", "strength": "strength", "other": "session"}
KINDS_BY_SPORT = {
    "run": ("easy", "long", "recovery", "strides", "tempo", "threshold", "vo2", "racepace",
            "openers", "shakeout"),
    "bike": ("easy", "long", "endurance", "recovery", "tempo", "threshold", "vo2", "racepace",
             "openers", "shakeout"),
    "swim": ("technique", "endurance", "css", "easy"),
    "brick": ("brick",),
    "strength": ("strength", "mobility"),
    "other": ("easy",),
    "rest": ("rest",),
}
STRENGTH_DETAIL = ("2-3 rounds: squats, reverse lunges, single-leg deadlifts, push-ups, "
                   "planks, side planks, glute bridges. Then 10' mobility.")


class PlanError(ValueError):
    """Validation error whose message is safe to show the user."""


def new_id() -> str:
    return "s" + secrets.token_hex(5)


def race_profile(distance: str | None) -> dict[str, Any]:
    return RACES.get((distance or "").strip().lower(), RACES["other"])


def _r5(x: float) -> int:
    return max(5, int(round(x / 5.0)) * 5)


# ----------------------------------------------------------------- steps ---
def _st(t: str, minutes: float, zone: int) -> dict[str, Any]:
    return {"type": t, "minutes": round(float(minutes), 2), "zone": zone}


def _sw(t: str, meters: int, zone: int) -> dict[str, Any]:
    return {"type": t, "meters": int(meters), "zone": zone}


def _rep(reps: int, *steps: dict[str, Any]) -> dict[str, Any]:
    return {"type": "repeat", "reps": int(reps), "steps": list(steps)}


def step_minutes(steps: list[dict[str, Any]], swim_pace: float = 120.0) -> float:
    """Total minutes; swim steps in meters use ``swim_pace`` (seconds per 100 m)."""
    total = 0.0
    for s in steps:
        if s.get("type") == "repeat":
            total += s["reps"] * step_minutes(s["steps"], swim_pace)
        elif s.get("meters"):
            total += s["meters"] / 100.0 * swim_pace / 60.0
        else:
            total += float(s.get("minutes") or 0)
    return total


def build_steps(sport: str, kind: str, minutes: int, *, swim_pace: float = 120.0,
                phase: str = "base") -> list[dict[str, Any]]:
    """Structured steps for one session of ``minutes`` (rounded to fit the kind)."""
    m = max(15, int(minutes))
    if sport == "swim":
        return _swim_steps(kind, m, swim_pace)
    if sport in ("strength", "other", "rest") or kind in ("strength", "rest", "race"):
        return [_st("steady", m, 1)] if kind != "rest" else []
    hard_rep = 3 if sport == "run" else 4
    if kind == "recovery":
        return [_st("steady", m, 1)]
    if kind in ("easy", "shakeout"):
        if m < 40:
            return [_st("steady", m, 2 if kind == "easy" else 1)]
        return [_st("warmup", 10, 1), _st("steady", m - 15, 2), _st("cooldown", 5, 1)]
    if kind == "long":
        return [_st("warmup", 10, 1), _st("steady", m - 15, 2), _st("cooldown", 5, 1)]
    if kind == "endurance":
        if m < 70:
            return [_st("warmup", 10, 1), _st("steady", m - 15, 2), _st("cooldown", 5, 1)]
        return [_st("warmup", 10, 1), _st("steady", m - 40, 2), _rep(3, _st("work", 5, 3), _st("steady", 5, 2))]
    if kind == "strides":
        main = max(10, m - 22)
        return [_st("warmup", 10, 1), _st("steady", main, 2),
                _rep(6, _st("work", 0.33, 5), _st("recover", 1.67, 1))]
    if kind == "openers":
        return [_st("warmup", 10, 1), _rep(4, _st("work", 1, 4), _st("recover", 2, 1)),
                _st("steady", max(5, m - 22), 2)]
    if kind == "tempo":
        return [_st("warmup", 15, 2), _st("steady", max(10, m - 25), 3), _st("cooldown", 10, 1)]
    if kind == "threshold":
        on, off = (8, 3) if sport == "run" else (10, 4)
        reps = min(6 if sport == "run" else 5, max(2, (m - 25) // (on + off)))
        cd = max(5, m - 15 - reps * (on + off))
        return [_st("warmup", 15, 2), _rep(reps, _st("work", on, 4), _st("recover", off, 1)),
                _st("cooldown", cd, 1)]
    if kind == "vo2":
        on = hard_rep
        reps = min(8 if sport == "run" else 6, max(3 if sport == "bike" else 4, (m - 25) // (2 * on)))
        cd = max(5, m - 15 - reps * 2 * on)
        return [_st("warmup", 15, 2), _rep(reps, _st("work", on, 5), _st("recover", on, 1)),
                _st("cooldown", cd, 1)]
    if kind == "racepace":
        block = 12 if sport == "run" else 20
        reps = max(2, min(5, (m - 25) // (block + 3)))
        cd = max(5, m - 15 - reps * (block + 3))
        return [_st("warmup", 15, 2), _rep(reps, _st("work", block, 3), _st("recover", 3, 2)),
                _st("cooldown", cd, 1)]
    return [_st("steady", m, 2)]


def _swim_steps(kind: str, minutes: int, pace: float) -> list[dict[str, Any]]:
    """Meters-based swim. ``pace`` is seconds per 100 m at steady effort; rests ~15%."""
    total = int(round(minutes * 60 / pace * 100 * 0.85 / 100.0)) * 100
    total = max(800, total)
    rest = lambda s: {"type": "recover", "minutes": round(s / 60.0, 2), "zone": 1}  # noqa: E731
    if kind == "css":
        reps = max(6, min(20, (total - 600) // 100))
        return [_sw("warmup", 400, 1), _rep(reps, _sw("work", 100, 4), rest(15)), _sw("cooldown", 200, 1)]
    if kind == "technique":
        main = max(200, total - 300 - 400 - 200)
        k = max(1, main // 200)
        return [_sw("warmup", 300, 1), _rep(8, _sw("work", 50, 2), rest(15)),
                _rep(k, _sw("steady", 200, 2), rest(20)), _sw("cooldown", 200, 1)]
    # endurance / easy
    k = max(2, (total - 600) // 400)
    return [_sw("warmup", 400, 1), _rep(k, _sw("steady", 400, 2), rest(30)), _sw("cooldown", 200, 1)]


def swim_meters(steps: list[dict[str, Any]]) -> int:
    total = 0
    for s in steps:
        if s.get("type") == "repeat":
            total += s["reps"] * swim_meters(s["steps"])
        else:
            total += int(s.get("meters") or 0)
    return total


def _fmt_min(m: float) -> str:
    if m < 1:
        return f'{int(round(m * 60))}"'
    if abs(m - round(m)) > 0.01:
        mm, ss = int(m), int(round((m - int(m)) * 60))
        return f"{mm}'{ss:02d}\""
    return f"{int(round(m))}'"


def _step_text(s: dict[str, Any]) -> str:
    if s["type"] == "repeat":
        return f"{s['reps']}× (" + ", ".join(_step_text(x) for x in s["steps"]) + ")"
    amount = f"{s['meters']}m" if s.get("meters") else _fmt_min(s.get("minutes") or 0)
    if s["type"] == "warmup":
        return f"{amount} warm-up"
    if s["type"] == "cooldown":
        return f"{amount} cool-down"
    if s["type"] == "recover":
        return f"{amount} easy" if not s.get("meters") else f"{amount} easy"
    return f"{amount} Z{s['zone']}"


def describe(steps: list[dict[str, Any]]) -> str:
    return " · ".join(_step_text(s) for s in steps)


def session_title(sport: str, kind: str) -> str:
    t = KIND_TITLES.get(kind, "{sport}").format(sport=SPORT_WORD.get(sport, sport))
    return t[0].upper() + t[1:]


def make_session(sport: str, kind: str, minutes: int, *, swim_pace: float = 120.0,
                 phase: str = "base", title: str | None = None,
                 run_off: int = 20) -> dict[str, Any]:
    """One session with steps, minutes and detail filled in."""
    s: dict[str, Any] = {"id": new_id(), "sport": sport, "kind": kind,
                         "title": title or session_title(sport, kind)}
    if sport == "rest":
        s.update(minutes=None, detail="", steps=[])
        return s
    if sport == "brick":
        bike_m = max(30, minutes - run_off)
        bike_kind = "racepace" if phase == "peak" else "endurance"
        legs = [{"sport": "bike", "minutes": bike_m,
                 "steps": build_steps("bike", bike_kind, bike_m)},
                {"sport": "run", "minutes": run_off,
                 "steps": [_st("steady", run_off, 3 if phase == "peak" else 2)]}]
        s.update(legs=legs, steps=[],
                 minutes=_r5(sum(step_minutes(lg["steps"]) for lg in legs)),
                 detail=f"Bike: {describe(legs[0]['steps'])}. Then straight into a "
                        f"{run_off}' run at Z{legs[1]['steps'][0]['zone']}.")
        return s
    if kind == "race":
        s.update(minutes=None, steps=[], detail="Race day. Trust the taper, start conservatively and fuel early.")
        return s
    steps = build_steps(sport, kind, minutes, swim_pace=swim_pace, phase=phase)
    s["steps"] = steps
    s["minutes"] = _r5(step_minutes(steps, swim_pace)) if steps else _r5(minutes)
    if sport == "swim":
        s["meters"] = swim_meters(steps)
        s["detail"] = f"{s['meters']}m: " + describe(steps)
    elif sport == "strength":
        s["detail"] = STRENGTH_DETAIL
    else:
        s["detail"] = describe(steps)
    return s


def rebuild_session(s: dict[str, Any], *, swim_pace: float = 120.0, phase: str = "base") -> dict[str, Any]:
    """Recompute steps/detail after an edit to sport, kind or minutes (keeps id and title
    unless the title was the generated default)."""
    sport, kind = s["sport"], s.get("kind") or "easy"
    if kind not in KINDS_BY_SPORT.get(sport, ("easy",)):
        kind = KINDS_BY_SPORT.get(sport, ("easy",))[0]
    fresh = make_session(sport, kind, int(s.get("minutes") or 45), swim_pace=swim_pace,
                         phase=phase, title=s.get("title") if s.get("title_custom") else None)
    fresh["id"] = s["id"]
    for k in ("garmin", "edited", "title_custom", "time"):
        if k in s:
            fresh[k] = s[k]
    if sport == "strength" and s.get("exercises") and s.get("kind") == fresh.get("kind"):
        for k in ("exercises", "prehab", "detail"):
            if k in s:
                fresh[k] = s[k]
    if s.get("detail_custom") and s.get("detail"):
        fresh["detail"], fresh["detail_custom"] = s["detail"], True
    return fresh


# ----------------------------------------------------------- generator ---
@dataclass
class Inputs:
    race_date: date
    distance: str
    level: str
    weekly_hours: float | None
    days: list[str]
    long_day: str
    limiters: list[str]
    equipment: list[str]
    swim_pace: float
    title: str
    favorites: list[str] = field(default_factory=list)
    injuries: str = ""
    level_given: bool = True
    longest_run_min: float | None = None
    longest_ride_min: float | None = None


def inputs_from(athlete: dict[str, Any], goal: dict[str, Any]) -> Inputs:
    if not goal.get("date"):
        raise PlanError("Add your race date first.")
    try:
        race = date.fromisoformat(goal["date"])
    except ValueError:
        raise PlanError("Race date must be YYYY-MM-DD.") from None
    days = [d for d in (athlete.get("available_days") or []) if d in DAYS] or list(DEFAULT_DAYS)
    long_day = athlete.get("long_day") if athlete.get("long_day") in DAYS else (
        "sat" if "sat" in days else days[-1])
    if long_day not in days:
        days.append(long_day)
    css = athlete.get("swim_css")
    pace = float(css) + 12 if isinstance(css, int | float) and 50 <= css <= 240 else 125.0
    level_given = athlete.get("level") in LEVELS
    level = athlete.get("level") if level_given else "intermediate"
    # "How hard should it feel?" (Adjust my plan): gentle is one level easier (fewer hard
    # sessions, lower defaults), push one harder. The progression caps apply either way.
    shift = {"gentle": -1, "push": 1}.get(str(athlete.get("plan_intensity") or ""), 0)
    if shift:
        order = list(LEVELS)
        level = order[max(0, min(len(order) - 1, order.index(level) + shift))]
    def _pos(k: str) -> float | None:
        v = athlete.get(k)
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and v > 0 else None
    return Inputs(race_date=race, distance=(goal.get("distance") or "other").lower(),
                  level=level, weekly_hours=athlete.get("weekly_hours"),
                  days=sorted(set(days), key=DAYS.index), long_day=long_day,
                  limiters=[x for x in (goal.get("limiters") or []) if x in ("swim", "bike", "run")],
                  equipment=list(athlete.get("equipment") or []), swim_pace=pace,
                  title=goal.get("title") or "Race",
                  favorites=[f for f in (athlete.get("favorite_sports") or []) if f in FAVORITE_SPORTS],
                  injuries=str(athlete.get("injuries") or "")[:500], level_given=level_given,
                  longest_run_min=_pos("longest_run_min"), longest_ride_min=_pos("longest_ride_min"))


def phases(n: int, taper: int) -> list[str]:
    """Phase per week for an n-week plan ending in race week."""
    if n <= 1:
        return ["race"]
    t = min(taper, max(0, n - 2))
    r = n - 1 - t
    if r >= 8:
        peak = min(4, max(2, round(r * 0.2)))
    else:
        peak = r // 4
    build = round((r - peak) * 0.45)
    base = r - peak - build
    return ["base"] * base + ["build"] * build + ["peak"] * peak + ["taper"] * t + ["race"]


# Safe-progression rules (every plan, every distance):
GROWTH = 1.10            # a week's volume is at most 10% above the last full (non-recovery) week
RECOVERY_EVERY = 4       # every 4th build week is lighter
RECOVERY_FACTOR = 0.7
FIRST_WEEK_FACTOR = 0.9  # week 1 sits a little under where you are now
LONG_SHARE = {"run": 0.35, "bike": 0.45}   # long session vs that sport's weekly minutes
# With nothing to go on (no Garmin history, no hours given), start like this.
DEFAULT_START_H = {"new": 1.5, "intermediate": 2.5, "advanced": 4.0}
DEFAULT_LONG = {"run": {"new": 30, "intermediate": 40, "advanced": 50},
                "bike": {"new": 45, "intermediate": 60, "advanced": 75}}
# The smallest week that still makes a plan for each race kind (3 x ~25' runs, etc.).
MIN_START_H = {"run": 1.25, "bike": 1.75, "tri": 2.5, "general": 1.5}
# Weeks a new / experienced athlete needs to build safely for the distance.
MIN_WEEKS = {"5k": (6, 4), "10k": (8, 6), "half marathon": (12, 8), "marathon": (18, 12),
             "ultra": (20, 14), "sprint triathlon": (8, 6), "olympic triathlon": (12, 8),
             "70.3": (16, 12), "140.6": (24, 18), "century ride": (10, 8), "other": (6, 4)}


def long_growth(prev: float, sport: str) -> float:
    """The most a long session may grow in one week: 10%, between 5 and 10 minutes for runs
    (10-15 for rides)."""
    lo, hi = (5.0, 10.0) if sport != "bike" else (10.0, 15.0)
    return max(lo, min(hi, prev * 0.10))


def week_hours(ph: list[str], start_h: float, peak_h: float) -> list[tuple[float, bool]]:
    """(hours, recovery?) per week. Base/build weeks grow geometrically from ``start_h`` to at
    most ``peak_h``, never more than 10% over the last full week; long runways hold the
    early base flat (up to half the growth steps) instead of ramping early; every 4th build
    week is a recovery week; then peak, taper and race week."""
    ramp = [i for i, p in enumerate(ph) if p in ("base", "build")]
    n = len(ramp)
    rec_flags = [(k + 1) % RECOVERY_EVERY == 0 and k != n - 1 for k in range(n)]
    steps = sum(1 for k in range(2, n) if not rec_flags[k])
    rate = 1.0
    hold = 0
    if steps and peak_h > start_h:
        need = math.ceil(math.log(peak_h / start_h) / math.log(1.07))  # ~7% a week is plenty
        active = min(steps, max(need, math.ceil(steps / 2)))
        hold = steps - active
        rate = min(GROWTH, (peak_h / start_h) ** (1.0 / active))
    out: list[tuple[float, bool]] = []
    cur = start_h
    grown = 0
    for k in range(n):
        if k == 0:
            h = start_h * FIRST_WEEK_FACTOR
        elif k == 1:
            h = start_h  # the first full week: where you are now, no growth yet
        elif rec_flags[k]:
            out.append((round(cur * RECOVERY_FACTOR, 2), True))
            continue
        else:
            grown += 1
            if grown > hold:
                cur = cur * rate
            h = cur
        out.append((round(h, 2), False))
    top = max([h for h, r in out if not r] or [start_h])
    taper_curve = {1: [0.6], 2: [0.7, 0.5], 3: [0.8, 0.65, 0.5]}
    t_total = ph.count("taper")
    curve = taper_curve.get(t_total, [0.6] * t_total)
    full: list[tuple[float, bool]] = []
    it = iter(out)
    taper_seen = 0
    peak_level = min(peak_h, top * GROWTH)
    for p in ph:
        if p in ("base", "build"):
            full.append(next(it))
        elif p == "peak":
            full.append((round(peak_level, 2), False))
        elif p == "taper":
            full.append((round(peak_level * curve[min(taper_seen, len(curve) - 1)], 2), False))
            taper_seen += 1
        else:
            full.append((round(peak_level * 0.35, 2), False))
    return full


def _split(kind: str, limiters: list[str], favorites: list[str] | None = None) -> dict[str, float]:
    s = dict(SPLIT[kind])
    fav = set(favorites or [])
    if kind == "general" and fav:
        # No specific race: train the sports they actually like.
        engine = {FAVORITE_ENGINE[f] for f in fav if f in FAVORITE_ENGINE}
        if engine:
            share = 0.9 / len(engine)
            s = {sp: share for sp in sorted(engine)} | {"strength": 0.1}
    if fav & {"strength", "yoga"} and "strength" not in s:
        s["strength"] = 0.07
    for lim in limiters:
        if lim in s:
            s[lim] += 0.05
    total = sum(s.values())
    return {k: v / total for k, v in s.items()}


def _sport_kinds(sport: str, race_kind: str, phase: str, minutes: int, eq: list[str],
                 recovery: bool) -> list[str]:
    if minutes < 20:
        return []
    if sport == "strength":
        return ["strength"] if phase in ("base", "build") or minutes >= 60 else []
    if sport == "swim":
        n = 2 if minutes < 120 else 3
        kinds = (["technique", "endurance", "css"] if phase == "base"
                 else ["css", "endurance", "technique"])
        return kinds[:n]
    if sport == "bike":
        n = 2 if minutes < 150 else 3
        if race_kind == "bike":
            n = min(4, max(2, minutes // 90))
        if recovery or phase == "base":
            kinds = ["long", "endurance", "easy", "easy"]
        elif phase == "build":
            kinds = ["long", "threshold", "easy", "tempo"]
        else:
            kinds = ["long", "vo2" if race_kind != "tri" else "racepace", "easy", "threshold"]
        return kinds[:n]
    # run: enough sessions that none is tiny or bigger than the long run (~30-45' each)
    if race_kind == "run":
        n = 2 if minutes < 60 else 3 if minutes < 150 else 4 if minutes < 240 else 5
    else:
        n = 2 if minutes < 100 else 3
    if recovery or phase == "base":
        kinds = ["long", "strides", "easy", "easy", "recovery"]
    elif phase == "build":
        kinds = ["long", "threshold", "easy", "strides", "recovery"]
    else:
        quality = "vo2" if race_kind == "run" else "racepace"
        kinds = ["long", quality, "easy", "threshold", "recovery"]
    return kinds[:n]


def _place(sessions: list[dict[str, Any]], days: list[str], long_day: str) -> dict[str, list[dict[str, Any]]]:
    """Assign sessions to weekdays: long bike/brick on the long day, the long run the day
    after (or before), quality spread out, then by lightest day without the same sport."""
    out: dict[str, list[dict[str, Any]]] = {d: [] for d in DAYS}
    load = {d: 0 for d in DAYS}
    li = DAYS.index(long_day)
    after = DAYS[(li + 1) % 7]
    before = DAYS[(li - 1) % 7]
    # Triathlon / multisport: long ride (or brick) on the long day, long run the day after (or
    # before). A running plan has no long ride, so its long run goes on the long day itself.
    bike_long = any(s["kind"] == "brick" or (s["kind"] == "long" and s["sport"] == "bike") for s in sessions)
    run_long_day = (after if after in days else before if before in days else long_day) if bike_long else long_day

    def put(day: str, s: dict[str, Any]) -> None:
        out[day].append(s)
        load[day] += s.get("minutes") or 0

    rest: list[dict[str, Any]] = []
    for s in sessions:
        if s["kind"] in ("brick",) or (s["kind"] == "long" and s["sport"] == "bike"):
            put(long_day, s)
        elif s["kind"] == "long" and s["sport"] == "run":
            put(run_long_day, s)
        else:
            rest.append(s)
    order = {k: i for i, k in enumerate(("threshold", "vo2", "racepace", "tempo", "css",
                                         "strides", "endurance", "technique", "easy",
                                         "strength", "recovery"))}
    rest.sort(key=lambda s: order.get(s["kind"], 99))
    quality_days: set[str] = set()
    for s in rest:
        avail = [d for d in days if len(out[d]) < MAX_PER_DAY]
        if not avail:
            continue  # few training days: the least important sessions are left out
        def cost(d: str) -> tuple[int, int, int, int]:
            same = sum(x["sport"] == s["sport"] for x in out[d])
            near = 0
            if s["kind"] in QUALITY:
                i = DAYS.index(d)
                hard = quality_days | {long_day, run_long_day}
                near = sum(DAYS[(i + o) % 7] in hard for o in (-1, 0, 1))
            return (same, near, load[d], DAYS.index(d))
        day = min(avail, key=cost)
        put(day, s)
        if s["kind"] in QUALITY:
            quality_days.add(day)
    return out


def _race_week(inp: Inputs, race_kind: str, week_start: date, plan_start: date,
               hours: float) -> dict[str, list[dict[str, Any]]]:
    rd = inp.race_date
    days: dict[str, list[dict[str, Any]]] = {}
    sports = {"tri": ["bike", "run", "swim"], "run": ["run", "run", "run"],
              "bike": ["bike", "bike", "bike"], "general": ["run", "bike", "run"]}[race_kind]
    plan = {5: ("easy", sports[0], 45), 4: ("openers", sports[1], 35), 3: ("easy", sports[2], 30),
            1: ("shakeout", sports[0] if race_kind != "tri" else "run", 20)}
    for i in range(7):
        d = week_start + timedelta(days=i)
        key = d.isoformat()
        if d < plan_start:
            continue
        out = (rd - d).days
        if out == 0:
            race = make_session("other", "race", 0, title=f"Race day: {inp.title}")
            race["sport"] = "brick" if race_kind == "tri" else ("bike" if race_kind == "bike" else "run")
            race["kind"] = "race"
            days[key] = [race]
        elif out in plan:  # short sessions: they go in even on usual rest days
            kind, sport, m = plan[out]
            if sport == "swim" and "pool" not in inp.equipment and "open_water" not in inp.equipment and inp.equipment:
                sport = "run"
            days[key] = [make_session(sport, kind, m, swim_pace=inp.swim_pace, phase="race")]
        else:
            days[key] = [make_session("rest", "rest", 0)]
    return days


# ------------------------------------------------------- starting point ---
FITNESS_DAYS = 42


def _act_sport(t: Any) -> str:
    k = str(t or "").lower()
    if "swim" in k:
        return "swim"
    if any(w in k for w in ("cycl", "bik", "ride")):
        return "bike"
    if any(w in k for w in ("run", "treadmill")):
        return "run"
    return "other"


def _hms_min(v: Any) -> float | None:
    """"1:02:03" / "39:12" (compact activities) or seconds -> minutes."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return v / 60.0
    if isinstance(v, str):
        try:
            p = [int(x) for x in v.strip().split(":")]
        except ValueError:
            return None
        if len(p) == 3:
            return p[0] * 60 + p[1] + p[2] / 60.0
        if len(p) == 2:
            return p[0] + p[1] / 60.0
    return None


def fitness_from(acts: list[dict[str, Any]] | None, today: date) -> dict[str, Any] | None:
    """Recent training from Garmin's compact activities (the last 6 weeks): average weekly
    hours, and per sport weekly minutes, the longest session and sessions a week. Weeks are
    counted from the first recorded week (at least 3), so a new watch doesn't look like a
    big training load. None with nothing recorded."""
    since = today - timedelta(days=FITNESS_DAYS)
    by: dict[str, dict[str, float]] = {}
    weeks: set[date] = set()
    for a in acts or []:
        if (a.get("multisport") or {}).get("is_parent"):
            continue
        try:
            day = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        if not since <= day <= today:
            continue
        mins = _hms_min(a.get("moving_duration")) or _hms_min(a.get("duration"))
        if not mins or mins < 5:
            continue
        x = by.setdefault(_act_sport(a.get("sport")), {"total": 0.0, "longest": 0.0, "n": 0})
        x["total"] += mins
        x["longest"] = max(x["longest"], mins)
        x["n"] += 1
        weeks.add(day - timedelta(days=day.weekday()))
    if not by:
        return None
    first = min(weeks)
    span = max(3, min(6, ((today - first).days // 7) + 1))
    sports = {sp: {"weekly_min": round(x["total"] / span, 1), "longest_min": round(x["longest"], 1),
                   "per_week": round(x["n"] / span, 2)} for sp, x in by.items()}
    return {"weekly_h": round(sum(v["weekly_min"] for v in sports.values()) / 60.0, 2),
            "weeks": span, "sports": sports}


def starting_point(inp: Inputs, race_kind: str, fitness: dict[str, Any] | None
                   ) -> tuple[float, dict[str, float], dict[str, Any]]:
    """(week-1 hours, first long session per sport, {known, source}). The plan starts from
    what the athlete does now: the hours they told us (never more), checked against Garmin's
    last 6 weeks when both exist (the lower, within reason), else a conservative start for
    their level. The first long run/ride is at most their recent longest."""
    declared = float(inp.weekly_hours) if isinstance(inp.weekly_hours, int | float) and inp.weekly_hours > 0 else None
    measured = fitness.get("weekly_h") if fitness and (fitness.get("weekly_h") or 0) >= 0.5 else None
    lvl = inp.level if inp.level_given else "new"
    if declared is not None and measured is not None:
        base, source = min(declared, max(measured, measured * 1.3)), "profile+garmin"
    elif declared is not None:
        base, source = declared, "profile"
    elif measured is not None:
        base, source = float(measured), "garmin"
    else:
        base, source = DEFAULT_START_H[lvl], "default"
    start_h = max(MIN_START_H.get(race_kind, 1.5), base)
    if declared is not None:
        start_h = min(start_h, max(declared, MIN_START_H.get(race_kind, 1.5)))
    sp = (fitness or {}).get("sports") or {}
    long0: dict[str, float] = {}
    for sport, given in (("run", inp.longest_run_min), ("bike", inp.longest_ride_min)):
        seen = (sp.get(sport) or {}).get("longest_min")
        known = [v for v in (given, seen) if v]
        default = float(DEFAULT_LONG[sport][lvl])
        if source != "default":
            # Hours known but not the longest session: about a quarter of that sport's week.
            share = SPLIT.get(race_kind, SPLIT["general"]).get(sport, 0.0)
            default = max(default, min(0.25 * start_h * 60 * share, 2 * default))
        # Known: start at (not above) the longest recent one. Unknown: a conservative start.
        long0[sport] = max(20.0, min(known)) if known else default
    return start_h, long0, {"known": source != "default", "source": source}


ENDURANCE = ("run", "bike", "swim", "brick")


def _week_min(week: dict[str, Any], endurance: bool = False) -> float:
    """A week's training minutes (``endurance``: run/bike/swim/brick only; strength and
    mobility are short, fixed sessions that don't drive the build)."""
    return sum((x.get("minutes") or 0) for ss in week["days"].values() for x in ss
               if x["sport"] != "rest" and (not endurance or x["sport"] in ENDURANCE))


def _trim(week: dict[str, Any], target: float, swim_pace: float) -> None:
    """Bring a week's endurance minutes down to ``target``: other sessions first (5' at a
    time, not under 20'), then the long session; bricks and races are left alone."""
    floor = {"swim": 30}
    for _ in range(200):
        if _week_min(week, endurance=True) <= target + 2:
            return
        cands = [x for ss in week["days"].values() for x in ss
                 if x["sport"] in ("run", "bike", "swim") and x.get("kind") not in ("race",)
                 and (x.get("minutes") or 0) > floor.get(x["sport"], 20)]
        easy = [x for x in cands if x.get("kind") != "long"]
        if easy:
            x = max(cands, key=lambda y: y.get("minutes") or 0)
        else:
            return
        new = dict(x, minutes=max(floor.get(x["sport"], 20), (x.get("minutes") or 0) - 5))
        fresh = rebuild_session(new, swim_pace=swim_pace, phase=week["phase"])
        if (fresh.get("minutes") or 0) >= (x.get("minutes") or 0):
            fresh["minutes"] = new["minutes"]
        x.clear()
        x.update(fresh)


def enforce_progression(weeks: list[dict[str, Any]], start_h: float, swim_pace: float) -> None:
    """Whatever rounding and minimum session lengths did, no full week is more than 10%
    over the last full week, the first full week isn't more than where the athlete is now,
    recovery weeks are clearly lighter, and the taper stays under the peak."""
    last: float | None = None
    long_last: dict[str, float] = {}
    for w in weeks:
        if w["phase"] == "race":
            continue
        partial = len(w["days"]) < 7
        if last is None:
            strength = _week_min(w) - _week_min(w, endurance=True)
            cap = max(60.0, start_h * 60 * (FIRST_WEEK_FACTOR if partial else 1.0) - strength)
        elif w["recovery"]:
            cap = last * 0.8
        elif w["phase"] == "taper":
            cap = last * 0.85
        else:
            cap = last * GROWTH
        if _week_min(w, endurance=True) > cap:
            _trim(w, cap, swim_pace)
        # Long sessions: grow at most ~10% (5-10') a week from the last actual one, ease off in
        # recovery weeks, and a runner's long run stays under ~40% of the week's running.
        for sport in ("run", "bike"):
            sess = [x for ss in w["days"].values() for x in ss if x["sport"] == sport]
            longs = [x for x in sess if x.get("kind") == "long"]
            if sport == "bike":
                longs += [x for ss in w["days"].values() for x in ss if x.get("kind") == "brick" and x.get("legs")]
            if not longs:
                continue
            leg = lambda y: float(y["legs"][0]["minutes"]) if y.get("kind") == "brick" else float(y.get("minutes") or 0)  # noqa: E731
            lx = max(longs, key=leg)
            lm = leg(lx)
            limit = lm
            prev = long_last.get(sport)
            if prev is not None:
                limit = min(limit, prev * 0.85 if w["recovery"] else prev if w["phase"] == "taper"
                            else prev + long_growth(prev, sport))
            if sport == "run" and len(sess) >= 3:
                limit = min(limit, 0.4 * sum((x.get("minutes") or 0) for x in sess))
            if limit < lm - 2:
                if lx.get("kind") == "brick":
                    run_off = int(lx["legs"][1]["minutes"])
                    fresh = make_session("brick", "brick", max(30, int(limit // 5 * 5)) + run_off,
                                         swim_pace=swim_pace, phase=w["phase"], run_off=run_off)
                    fresh["id"] = lx["id"]
                else:
                    fresh = rebuild_session(dict(lx, minutes=max(20, int(limit // 5 * 5))), swim_pace=swim_pace, phase=w["phase"])
                lx.clear()
                lx.update(fresh)
            if not w["recovery"] and w["phase"] != "taper":
                cur = leg(lx)
                long_last[sport] = cur if prev is None else max(prev, cur)
        recompute_week(w)
        if not partial and not w["recovery"] and w["phase"] != "taper":
            e = _week_min(w, endurance=True)
            last = e if last is None else max(last, e)


def ease_first_day(week: dict[str, Any], swim_pace: float) -> set[str]:
    """The plan's first training day is never its biggest or hardest: a long or quality
    session there becomes a short easy one (at most 30'). Returns the sports whose long
    session was eased."""
    days = sorted(d for d, ss in week["days"].items() if any(x["sport"] != "rest" for x in ss))
    eased: set[str] = set()
    if not days:
        return eased
    first = days[0]
    biggest = max((x.get("minutes") or 0) for d in days for x in week["days"][d] if x["sport"] != "rest")
    out = []
    for x in week["days"][first]:
        hard = x.get("kind") in QUALITY or x.get("kind") in ("long", "brick", "vo2", "strides")
        big = (x.get("minutes") or 0) >= biggest and len(days) > 1
        if x["sport"] in ("run", "bike", "swim", "brick") and (hard or big or (x.get("minutes") or 0) > 30):
            sport = "bike" if x["sport"] == "brick" else x["sport"]
            if x.get("kind") in ("long", "brick"):
                eased.add(sport)
            kind = "technique" if sport == "swim" else "easy"
            out.append(make_session(sport, kind, min(30, int(x.get("minutes") or 30)), swim_pace=swim_pace))
        else:
            out.append(x)
    week["days"][first] = out
    return eased


def build_plan(athlete: dict[str, Any], goal: dict[str, Any], *, today: date,
               start: date | None = None,
               events: list[dict[str, Any]] | None = None,
               fitness: dict[str, Any] | None = None) -> dict[str, Any]:
    """``fitness``: recent training from Garmin (``fitness_from``), when available; the plan
    then starts from what the athlete actually does now."""
    inp = inputs_from(athlete, goal)
    prof = race_profile(inp.distance)
    race_kind = prof["kind"]
    if inp.race_date < today:
        raise PlanError("That race date has already passed.")
    start = max(start or today, today)
    if start > inp.race_date:
        raise PlanError("The plan has to start before race day.")
    race_monday = inp.race_date - timedelta(days=inp.race_date.weekday())
    week1 = start - timedelta(days=start.weekday())
    n = (race_monday - week1).days // 7 + 1
    note = None
    if n > MAX_WEEKS:
        week1 = race_monday - timedelta(weeks=MAX_WEEKS - 1)
        start = week1
        n = MAX_WEEKS
        note = (f"Your race is more than {MAX_WEEKS} weeks out, so the plan starts on "
                f"{week1:%b %-d}. Until then, keep training the way you are.")
    ph = phases(n, prof["taper"])
    profile_peak = prof["peak"][LEVELS.index(inp.level if inp.level_given else "new")]
    start_h, long0, how = starting_point(inp, race_kind, fitness)
    peak_h = max(profile_peak, min(start_h, profile_peak * 1.3))
    min_weeks = MIN_WEEKS.get(inp.distance, MIN_WEEKS["other"])[0 if inp.level == "new" or not how["known"] else 1]
    if n < min_weeks and note is None:
        note = (f"{n} week{'s' if n != 1 else ''} is a short runway for this race, so the plan builds "
                f"slowly from where you are instead of cramming. Treat race day as a strong training "
                f"day, or pick a later race to build more.")
    hours = week_hours(ph, start_h, peak_h)
    peak_h = max([h for (h, _), p in zip(hours, ph, strict=True) if p == "peak"] or
                 [h for (h, r) in hours if not r] or [start_h])
    split = _split(race_kind, inp.limiters, inp.favorites)
    if race_kind == "tri" and inp.equipment and not {"pool", "open_water"} & set(inp.equipment):
        split.pop("swim", None)  # no water access: skip swims rather than plan the impossible
        tot = sum(split.values())
        split = {k: v / tot for k, v in split.items()}
    beginner = inp.level == "new" or not how["known"]

    weeks: list[dict[str, Any]] = []
    long_prev: dict[str, float | None] = {sp: None for sp in ("run", "bike")}
    for idx, (phase, (h, rec)) in enumerate(zip(ph, hours, strict=True), start=1):
        ws = week1 + timedelta(weeks=idx - 1)
        if phase == "race":
            days = _race_week(inp, race_kind, ws, start, h)
        else:
            minutes = h * 60
            sessions: list[dict[str, Any]] = []
            run_off = 0
            st_m = (30 if minutes * split["strength"] < 45 else 40) if "strength" in split else 0
            if st_m and minutes < 120:
                st_m = 0  # under 2 hours a week it's all endurance; strength comes in as it grows
            endurance = max(0.0, minutes - st_m)
            e_frac = sum(f for sp_, f in split.items() if sp_ != "strength") or 1.0
            for sport, frac in split.items():
                sm = st_m if sport == "strength" else int(endurance * frac / e_frac)
                if sport == "strength" and not sm:
                    continue
                kinds = _sport_kinds(sport, race_kind, phase, sm, inp.equipment, rec)
                if race_kind == "tri" and sport == "bike" and phase in ("build", "peak") and not rec \
                        and "long" in kinds:
                    kinds[kinds.index("long")] = "brick"
                    run_off = 25 if phase == "peak" else 15
                if beginner and idx <= 2:
                    kinds = ["easy" if k in QUALITY or k == "strides" else k for k in kinds]
                if not kinds:
                    continue
                cap = prof["long"].get(sport, 240)
                floor = 30 if sport == "swim" else 20
                plan_m: list[tuple[str, float]] = []
                rest_m = float(sm)
                long_kind = "brick" if "brick" in kinds else "long" if "long" in kinds else None
                if long_kind and sport in long_prev:
                    # The long session: its share of the week, capped by the race's cap and by
                    # safe growth from last week's long (or where the athlete is now).
                    share = sm * WEIGHT[long_kind] / sum(WEIGHT[k] for k in kinds)
                    share = min(share, sm * LONG_SHARE.get(sport, 0.4) if len(kinds) > 1 else share)
                    prev = long_prev[sport]
                    if prev is None:
                        allowed = long0[sport]
                    elif rec:
                        allowed = prev * 0.8
                    elif phase == "taper":
                        allowed = prev
                    else:
                        allowed = prev + long_growth(prev, sport)
                    lm = max(floor, min(share, allowed, cap))
                    if not rec and phase != "taper":
                        long_prev[sport] = lm if prev is None else max(prev, lm)
                    plan_m.append((long_kind, lm))
                    rest_m -= lm
                    kinds = [k for k in kinds if k != long_kind]
                    top = lm
                else:
                    top = cap
                # Other sessions share what's left; none longer than the long one, none tiny.
                while kinds and rest_m / len(kinds) < floor and len(kinds) > 1:
                    kinds = kinds[:-1]
                if kinds:
                    wsum = sum(WEIGHT[k] for k in kinds)
                    for k in kinds:
                        m = rest_m * WEIGHT[k] / wsum
                        m = min(m, top, cap * 0.75 if sport != "swim" else cap)
                        plan_m.append((k, max(floor, m)))
                order = {k: i for i, k in enumerate(_sport_kinds(sport, race_kind, phase, sm, inp.equipment, rec) + ["easy", "brick"])}
                for k, m in sorted(plan_m, key=lambda x: order.get(x[0], 99)):
                    if sport == "run" and run_off and k == "long":
                        m = max(floor, m - run_off)
                    sessions.append(make_session("brick" if k == "brick" else sport, k, _r5(m),
                                                 swim_pace=inp.swim_pace, phase=phase,
                                                 run_off=run_off or 20))
            placed = _place(sessions, inp.days, inp.long_day)
            days = {}
            for i in range(7):
                d = ws + timedelta(days=i)
                if d < start:
                    continue
                day_sessions = placed[DAYS[i]]
                days[d.isoformat()] = day_sessions or [make_session("rest", "rest", 0)]
        week = {"index": idx, "start": ws.isoformat(), "phase": phase, "recovery": rec,
                "hours": h, "focus": week_focus(phase, rec, race_kind), "days": days}
        if idx == 1 and phase != "race":
            for sp_ in ease_first_day(week, inp.swim_pace):
                if sp_ in long_prev:
                    long_prev[sp_] = None  # that long never happened: week 2 starts from the first long
        recompute_week(week)
        weeks.append(week)
    enforce_progression(weeks, start_h, inp.swim_pace)
    apply_strength(weeks, inp, race_kind)
    placed_events = apply_events(weeks, events or [], inp, start)
    return {"events": placed_events, "start": week1.isoformat(), "first_day": start.isoformat(),
            "race_date": inp.race_date.isoformat(), "distance": inp.distance,
            "race_kind": race_kind, "level": inp.level, "peak_hours": round(peak_h, 1),
            "start_hours": round(start_h, 1), "swim_pace": inp.swim_pace,
            "start_from": how["source"], "note": note, "weeks": weeks}


def apply_strength(weeks: list[dict[str, Any]], inp: Inputs, race_kind: str) -> None:
    """Phase- and sport-specific strength routines (plus prehab for listed injuries), and a
    weekly 20-minute mobility session when the athlete has injuries or likes yoga."""
    from .strength import routine
    want_mobility = bool(inp.injuries) or "yoga" in inp.favorites
    for w in weeks:
        for ss in w["days"].values():
            for x in ss:
                if x["sport"] == "strength":
                    r = routine(w["phase"], race_kind, inp.injuries, mobility=x.get("kind") == "mobility")
                    x.update(exercises=r["exercises"], prehab=r["prehab"], detail=r["detail"])
        if want_mobility and w["phase"] != "race":
            free = [d for d in sorted(w["days"]) if all(x["sport"] == "rest" for x in w["days"][d])]
            if free:
                d = free[len(free) // 2]
                m = make_session("strength", "mobility", 20)
                r = routine(w["phase"], race_kind, inp.injuries, mobility=True)
                m.update(exercises=r["exercises"], prehab=r["prehab"], detail=r["detail"])
                w["days"][d] = [m]
                recompute_week(w)


# Event type -> the sport of its race-day session.
EVENT_SPORT = {"triathlon": "brick", "duathlon": "brick", "running": "run", "trail": "run",
               "cycling": "bike", "swimming": "swim", "mountaineering": "other", "other": "other"}


# Event kinds (events.KINDS) that the plan treats like races (taper / hard day).
RACE_KINDS = ("race", "challenge")
# Effort word -> (zone for a steady group session, swim kind).
INTENSITY = {"easy": (2, "easy"), "moderate": (3, "endurance"), "hard": (4, "css")}
WEEKDAYS = DAYS
MAX_OCCURRENCES = 60
MAX_SPAN_DAYS = 30


def _ev_kind(ev: dict[str, Any]) -> str:
    return ev.get("kind") or "race"


def _span(ev: dict[str, Any], d: date) -> list[date]:
    """Every day of a (possibly multi-day) event, capped at ``MAX_SPAN_DAYS``."""
    try:
        end = date.fromisoformat(ev.get("end_date") or "")
    except ValueError:
        end = d
    end = max(d, min(end, d + timedelta(days=MAX_SPAN_DAYS - 1)))
    return [d + timedelta(days=i) for i in range((end - d).days + 1)]


def occurrences(ev: dict[str, Any], until: date) -> list[date]:
    """The dates a (possibly repeating) event happens, before ``until``: weekly on some
    weekdays, every 2 weeks or monthly (recur.py), skipped dates left out."""
    try:
        d = date.fromisoformat(ev.get("date") or "")
    except ValueError:
        return []
    rule = recur.loose(ev.get("recurring"), d)
    if not rule:
        return [d] if d < until else []
    if until <= d:
        return []
    return recur.dates(rule, d, d, until - timedelta(days=1), limit=MAX_OCCURRENCES)


def group_session(ev: dict[str, Any], swim_pace: float = 120.0) -> dict[str, Any]:
    """One occurrence of a group activity (group ride/run/swim, league game) as a planned
    session: sport from the event type, minutes from ``duration_min`` (60 by default),
    moderate effort unless the event says otherwise."""
    from .sports import plan_sport  # the specific sport (volleyball, spin, HIIT...) wins over the type
    sport = plan_sport(ev.get("activity")) or EVENT_SPORT.get(ev.get("type") or "other", "other")
    if sport == "brick":
        sport = "bike"
    try:
        minutes = clamp_minutes(ev.get("duration_min") or 60)
    except PlanError:
        minutes = 60
    zone, swim_kind = INTENSITY.get(ev.get("intensity") or "moderate", INTENSITY["moderate"])
    name = (ev.get("name") or "Group session")[:50]
    if sport == "swim":
        s = make_session("swim", swim_kind, minutes, swim_pace=swim_pace)
    elif sport == "strength":
        s = make_session("strength", "strength", minutes, swim_pace=swim_pace)
    else:
        s = make_session(sport, "easy", minutes, swim_pace=swim_pace)
        s["steps"] = [_st("steady", minutes, zone)]
        s["minutes"] = _r5(minutes)
        s["detail"] = describe(s["steps"])
    effort = {2: "Easy effort", 3: "Moderate effort", 4: "Hard effort"}[zone]
    where = ", ".join(x for x in (ev.get("with") and f"with {ev['with']}", ev.get("at") and f"at {ev['at']}",
                                   ev.get("time")) if x)
    s["title"] = f"Group: {name}"[:60]
    s["detail"] = (f"{name}{' (' + where + ')' if where else ''}. {effort}: go with the group, "
                   f"don't race it. {s.get('detail') or ''}").strip()[:400]
    s["event_id"], s["group"] = ev.get("id"), True
    return s


def apply_events(weeks: list[dict[str, Any]], events: list[dict[str, Any]], inp: Inputs,
                 start: date) -> list[dict[str, Any]]:
    """Drop the athlete's other events into the plan.

    Races (and challenges, as training races): B race = easy two days out, short openers
    the day before, rest the day after, and the next day easy. C race / challenge = raced as
    a hard training day with an easy day either side. Trips: sessions on those days become
    short and easy (≤ 45'). Life events (milestones): rest on the day(s), short easy days
    either side. Group activities: each occurrence (weekly when recurring) becomes a planned
    session in place of that day's same-sport session. Events on or after the main race,
    before the plan starts, or in race week are skipped. Returns the events that were placed."""
    by_day: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for w in weeks:
        for d in w["days"]:
            by_day[d] = (w, w["days"])

    def usable(d: date) -> bool:
        return start <= d < inp.race_date and d.isoformat() in by_day and by_day[d.isoformat()][0]["phase"] != "race"

    order = {"race": 0, "challenge": 0, "milestone": 1, "trip": 2, "group_activity": 3, "other": 3}
    placed: list[dict[str, Any]] = []
    blocked: set[str] = set()  # milestone and trip days: no group sessions there
    for ev in sorted(events, key=lambda e: (order.get(_ev_kind(e), 3), e.get("date") or "")):
        kind = _ev_kind(ev)
        if ev.get("in_plan") is False:
            continue  # on the calendar only ("Count as a workout" off)
        if kind in ("group_activity", "other"):
            if kind == "other" and not ev.get("duration_min"):
                continue  # nothing to train: it stays on the calendar only
            days = [d for d in occurrences(ev, inp.race_date) if usable(d) and d.isoformat() not in blocked]
            if not days:
                continue
            for d in days:
                s = group_session(ev, inp.swim_pace)
                cur = by_day[d.isoformat()][1][d.isoformat()]
                if any(x.get("kind") == "race" for x in cur):
                    continue
                keep = [x for x in cur if x["sport"] not in ("rest", s["sport"])][: MAX_PER_DAY - 1]
                by_day[d.isoformat()][1][d.isoformat()] = keep + [s]
            placed.append({"id": ev.get("id"), "name": ev.get("name"), "date": days[0].isoformat(),
                           "kind": kind, "priority": None, "occurrences": len(days)})
            continue
        try:
            d = date.fromisoformat(ev.get("date") or "")
        except ValueError:
            continue
        if kind in ("trip", "milestone"):
            span = [x for x in _span(ev, d) if usable(x)]
            if not span:
                continue
            name = (ev.get("name") or ("Trip" if kind == "trip" else "Life event"))[:50]
            for x in span:
                blocked.add(x.isoformat())
                ss = by_day[x.isoformat()][1][x.isoformat()]
                if any(y.get("kind") == "race" for y in ss):
                    continue
                if kind == "milestone":
                    r = make_session("rest", "rest", 0, title=f"Rest: {name}"[:60])
                    r["detail"], r["event_id"] = f"{name}. A day off training; enjoy it.", ev.get("id")
                    _put(by_day, x, [r])
                else:
                    by_day[x.isoformat()][1][x.isoformat()] = [_lighter(y, name, inp.swim_pace) for y in ss]
            if kind == "milestone":  # short, easy days either side
                for x in (span[0] - timedelta(days=1), span[-1] + timedelta(days=1)):
                    if x.isoformat() in by_day and x.isoformat() not in blocked:
                        ss = by_day[x.isoformat()][1][x.isoformat()]
                        if not any(y.get("kind") == "race" for y in ss):
                            by_day[x.isoformat()][1][x.isoformat()] = [_lighter(y, name, inp.swim_pace, cap=30)
                                                                       for y in ss][:1]
            placed.append({"id": ev.get("id"), "name": ev.get("name"), "date": span[0].isoformat(),
                           "end_date": span[-1].isoformat(), "kind": kind, "priority": None})
            continue
        # race / challenge
        if not usable(d):
            continue
        prio = "C" if kind == "challenge" else (ev.get("priority") if ev.get("priority") in ("B", "C") else "B")
        sport = EVENT_SPORT.get(ev.get("type") or "other", "other")
        word = "Challenge" if kind == "challenge" else "Race"
        race = make_session("other", "race", 0, title=f"{word}: {ev.get('name') or 'Event'}"[:60])
        race["sport"], race["kind"], race["event_id"] = sport, "race", ev.get("id")
        race["race_distance"] = (ev.get("distance") or "").lower()  # not the main race's
        race["detail"] = (f"Your challenge. Go for it, but it's a step toward {inp.title}: pace it, "
                          "fuel it and recover well after." if kind == "challenge" else
                          f"{prio} race. Race it with intent, but it's a step toward {inp.title}: "
                          "start controlled and recover well after." if prio == "B" else
                          f"Training race: treat it as a hard workout on the way to {inp.title}. "
                          "No taper; keep it controlled.")
        _put(by_day, d, [race])
        train = "run" if sport in ("run", "brick", "other") else sport
        if prio == "B":
            _put(by_day, d - timedelta(days=2), [make_session(train, "easy", 35, swim_pace=inp.swim_pace)])
            _put(by_day, d - timedelta(days=1), [make_session(train, "openers", 30, swim_pace=inp.swim_pace)])
            _put(by_day, d + timedelta(days=1), [make_session("rest", "rest", 0)])
            _put(by_day, d + timedelta(days=2), [make_session("bike" if sport != "bike" else "run",
                                                              "recovery", 40, swim_pace=inp.swim_pace)])
        else:
            _put(by_day, d - timedelta(days=1), [make_session(train, "easy", 30, swim_pace=inp.swim_pace)])
            _put(by_day, d + timedelta(days=1), [make_session("bike" if sport != "bike" else "run",
                                                              "recovery", 40, swim_pace=inp.swim_pace)])
        item = {"id": ev.get("id"), "name": ev.get("name"), "date": d.isoformat(), "priority": prio}
        if kind != "race":
            item["kind"] = kind
        placed.append(item)
    for w in weeks:
        recompute_week(w)
    placed.sort(key=lambda e: e["date"])
    return placed


def placed_label(e: dict[str, Any]) -> str:
    """"B race" / "challenge" / "trip to 2026-07-04" / "group activity, 8 sessions"."""
    kind = e.get("kind") or "race"
    if kind == "race":
        return f"{e.get('priority') or 'B'} race"
    if kind == "group_activity" or kind == "other":
        n = e.get("occurrences") or 1
        return f"{'group activity' if kind == 'group_activity' else 'activity'}, {n} session{'s' if n != 1 else ''}"
    if kind in ("trip", "milestone"):
        word = "trip" if kind == "trip" else "life event"
        return f"{word} to {e['end_date']}" if e.get("end_date") and e["end_date"] != e["date"] else word
    return kind


def _lighter(s: dict[str, Any], name: str, swim_pace: float, cap: int = 45) -> dict[str, Any]:
    """A session made short and easy (trips, days around a life event); rest stays rest."""
    if s["sport"] == "rest" or s.get("kind") == "race":
        return s
    sport = "run" if s["sport"] == "brick" else s["sport"]
    kind = "strength" if sport == "strength" else "easy"
    new = make_session(sport, kind, min(cap, int(s.get("minutes") or cap)), swim_pace=swim_pace)
    if sport == "strength":
        for k in ("exercises", "prehab"):
            if k in s:
                new[k] = s[k]
    new["detail"] = f"{name}: keep it short and easy, or skip it. {new.get('detail') or ''}".strip()[:400]
    return new


def _put(by_day: dict[str, tuple[dict[str, Any], dict[str, Any]]], d: date,
         sessions: list[dict[str, Any]]) -> None:
    """Replace a day's sessions, unless it's outside the plan or already a race day."""
    hit = by_day.get(d.isoformat())
    if hit is None:
        return
    _, days = hit
    if any(s.get("kind") == "race" for s in days[d.isoformat()]):
        return
    days[d.isoformat()] = sessions


def week_focus(phase: str, recovery: bool, race_kind: str) -> str:
    if recovery:
        return "Recovery week: lighter volume so the work sinks in."
    return {
        "base": "Base: build aerobic endurance and consistency, mostly easy.",
        "build": "Build: add threshold work while the long sessions grow.",
        "peak": ("Peak: race-specific bricks and race-pace work." if race_kind == "tri"
                 else "Peak: race-specific intensity at full volume."),
        "taper": "Taper: volume drops, keep a little intensity, arrive fresh.",
        "race": "Race week: short openers, lots of rest. You're ready.",
    }[phase]


# ----------------------------------------------------------- summaries ---
def recompute_week(week: dict[str, Any]) -> None:
    week["hours"] = round(sum((s.get("minutes") or 0) for ss in week["days"].values()
                              for s in ss if s["sport"] != "rest") / 60.0, 1)


def summary_markdown(plan: dict[str, Any], goal: dict[str, Any]) -> str:
    """Rabbit's readable summary of a built plan (the coach's context and the Plan sheet)."""
    weeks = plan["weeks"]
    if plan.get("origin"):
        return _imported_summary(plan, goal)
    lines = ["### Overview",
             f"- Built in Rabbit's plan builder for {goal.get('title') or 'the race'}"
             f" on {plan['race_date']} ({goal.get('distance') or plan['distance']}).",
             f"- {len(weeks)} weeks from {plan['first_day']}, about {plan['start_hours']} h/week "
             f"building to {plan['peak_hours']} h at peak. Recovery week every 4th week.",
             "- Sessions use the athlete's 5 training zones (Z1 easy to Z5 hard)."]
    if plan.get("note"):
        lines.append(f"- {plan['note']}")
    typical = next((w for w in weeks if w["phase"] == "build" and not w["recovery"]),
                   next((w for w in weeks if w["phase"] != "race"), weeks[-1]))
    lines += ["", "### Typical week (build)"]
    for d in sorted(typical["days"]):
        ss = typical["days"][d]
        wd = date.fromisoformat(d).strftime("%a")
        lines.append(f"- {wd}: " + "; ".join(
            s["title"] + (f" {s['minutes']}'" if s.get("minutes") else "") for s in ss))
    lines += ["", "### Phases"]
    i = 0
    while i < len(weeks):
        j = i
        while j + 1 < len(weeks) and weeks[j + 1]["phase"] == weeks[i]["phase"]:
            j += 1
        w0, w1 = weeks[i], weeks[j]
        hrs = [w["hours"] for w in weeks[i:j + 1]]
        lines.append(f"- {w0['phase'].title()}: weeks {w0['index']}-{w1['index']} "
                     f"({w0['start']} to {(date.fromisoformat(w1['start']) + timedelta(days=6)).isoformat()}), "
                     f"{min(hrs)}-{max(hrs)} h/week.")
        i = j + 1
    tgt = [x for x in (goal.get("target"), goal.get("target_time")) if x]
    if tgt or goal.get("limiters"):
        lines += ["", "### Key targets"]
        if tgt:
            lines.append("- Race target: " + " / ".join(tgt))
        if goal.get("limiters"):
            lines.append("- Extra focus on: " + ", ".join(goal["limiters"]))
    if plan.get("events"):
        lines += ["", "### Other events in the plan"]
        for e in plan["events"]:
            lines.append(f"- {e['date']}: {e['name']} ({placed_label(e)})")
    lines += ["", "### Rules",
              "- Easy days stay easy (Z1-2). Quality days are the ones with Z4-5 work.",
              "- Missed a session? Skip it and carry on; never stack two hard days.",
              "- The athlete edits sessions in the app; this summary follows their edits."]
    return "\n".join(lines)[:12000]


def _imported_summary(plan: dict[str, Any], goal: dict[str, Any]) -> str:
    """Summary of a plan a coach (or the athlete) loaded from outside the builder."""
    o = plan["origin"]
    who = (f"their coach {o.get('by_name') or ''}".rstrip() if o.get("kind") == "coach"
           else "the athlete")
    weeks = plan["weeks"]
    lines = ["### Overview",
             f"- Loaded by {who} ({o.get('source') or 'file'}) for {goal.get('title') or 'their goal'}"
             + (f": {o['name']}." if o.get("name") else "."),
             f"- {len(weeks)} weeks from {plan['first_day']}, {min(w['hours'] for w in weeks)}-"
             f"{max(w['hours'] for w in weeks)} h/week.",
             "- Follow the plan as written; the coach set the sessions. Suggest changes, don't rewrite it.",
             "", "### Weeks"]
    for w in weeks[:60]:
        n = sum(1 for ss in w["days"].values() for s in ss if s["sport"] != "rest")
        lines.append(f"- Week {w['index']} ({w['start']}): {n} sessions, {w['hours']} h"
                     + (" (recovery)" if w.get("recovery") else ""))
    return "\n".join(lines)[:12000]


# ------------------------------------------------------------- Garmin ---
GARMIN_SPORT = {
    "run": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "bike": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    "swim": {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3},
    "other": {"sportTypeId": 3, "sportTypeKey": "other", "displayOrder": 4},
}
_STEP_TYPE = {"warmup": (1, "warmup", 1), "cooldown": (2, "cooldown", 2),
              "work": (3, "interval", 3), "steady": (3, "interval", 3),
              "recover": (4, "recovery", 4)}
# Zone -> fraction of FTP (bike power) and of threshold pace time (run; >1 is slower).
POWER_ZONES = {1: (0.40, 0.55), 2: (0.56, 0.75), 3: (0.76, 0.90), 4: (0.91, 1.05), 5: (1.06, 1.20)}
PACE_ZONES = {1: (1.30, 1.45), 2: (1.15, 1.29), 3: (1.06, 1.14), 4: (0.99, 1.05), 5: (0.90, 0.98)}


def _target(sport: str, zone: int, athlete: dict[str, Any], kind: str) -> dict[str, Any]:
    none = {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",
                           "displayOrder": 1}}
    if sport == "swim" or kind == "recover_free":
        return none
    ftp = athlete.get("ftp_w")
    pace = athlete.get("run_threshold_pace")  # seconds per km
    if sport == "bike" and isinstance(ftp, int | float) and ftp > 0:
        lo, hi = POWER_ZONES[zone]
        return {"targetType": {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone",
                               "displayOrder": 2},
                "targetValueOne": round(ftp * lo), "targetValueTwo": round(ftp * hi)}
    if sport == "run" and isinstance(pace, int | float) and pace > 0:
        slow, fast = PACE_ZONES[zone]
        return {"targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone",
                               "displayOrder": 6},
                "targetValueOne": round(1000.0 / (pace * slow), 4),
                "targetValueTwo": round(1000.0 / (pace * fast), 4)}
    return {"targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone",
                           "displayOrder": 4},
            "zoneNumber": int(zone)}


def _exact_target(step: dict[str, Any], s: dict[str, Any], sport: str, athlete: dict[str, Any]) -> None:
    """Imported workout files (Zwift .zwo, .erg/.mrc) carry the exact %FTP (bike) or % of
    threshold speed (run) as ``pct``: target +-3% around it instead of the whole zone."""
    pct = s.get("pct")
    if not isinstance(pct, int | float) or pct <= 0:
        return
    ftp, pace = athlete.get("ftp_w"), athlete.get("run_threshold_pace")
    if sport == "bike" and isinstance(ftp, int | float) and ftp > 0 and \
            step["targetType"]["workoutTargetTypeKey"] == "power.zone":
        step["targetValueOne"], step["targetValueTwo"] = round(ftp * (pct - 3) / 100), round(ftp * (pct + 3) / 100)
    elif sport == "run" and isinstance(pace, int | float) and pace > 0 and \
            step["targetType"]["workoutTargetTypeKey"] == "pace.zone":
        speed = 1000.0 / pace * pct / 100.0
        step["targetValueOne"], step["targetValueTwo"] = round(speed * 0.97, 4), round(speed * 1.03, 4)


class _Order:
    def __init__(self) -> None:
        self.n = 0
        self.child = 0

    def next(self) -> int:
        self.n += 1
        return self.n


def _garmin_steps(steps: list[dict[str, Any]], sport: str, athlete: dict[str, Any],
                  order: _Order, child: int | None = None) -> list[dict[str, Any]]:
    out = []
    for s in steps:
        if s["type"] == "repeat":
            order.child += 1
            cid = order.child
            grp = {"type": "RepeatGroupDTO", "stepOrder": order.next(),
                   "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                   "childStepId": cid, "numberOfIterations": int(s["reps"]), "smartRepeat": False,
                   "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                                    "displayOrder": 7, "displayable": False},
                   "endConditionValue": float(s["reps"])}
            grp["workoutSteps"] = _garmin_steps(s["steps"], sport, athlete, order, cid)
            out.append(grp)
            continue
        tid, tkey, tord = _STEP_TYPE.get(s["type"], (3, "interval", 3))
        step: dict[str, Any] = {"type": "ExecutableStepDTO", "stepOrder": order.next(),
                                "stepType": {"stepTypeId": tid, "stepTypeKey": tkey,
                                             "displayOrder": tord}}
        if child is not None:
            step["childStepId"] = child
        if s.get("meters"):
            step["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance",
                                    "displayOrder": 3, "displayable": True}
            step["endConditionValue"] = float(s["meters"])
            step["preferredEndConditionUnit"] = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
        else:
            step["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time",
                                    "displayOrder": 2, "displayable": True}
            step["endConditionValue"] = float(round((s.get("minutes") or 1) * 60))
        if sport == "swim":
            step["strokeType"] = {"strokeTypeId": 6, "strokeTypeKey": "free", "displayOrder": 6}
        step.update(_target(sport, int(s.get("zone") or 2),
                            athlete, "recover_free" if s["type"] == "recover" and sport == "swim" else s["type"]))
        _exact_target(step, s, sport, athlete)
        out.append(step)
    return out


def garmin_workouts(session: dict[str, Any], athlete: dict[str, Any]) -> list[dict[str, Any]]:
    """Garmin Connect workout JSON for a session (a brick is two workouts). Rest and race
    days produce nothing."""
    if session["sport"] == "rest" or session.get("kind") == "race":
        return []
    parts = session.get("legs") or [{"sport": session["sport"], "minutes": session.get("minutes"),
                                     "steps": session.get("steps") or []}]
    out = []
    for i, leg in enumerate(parts):
        sport = leg["sport"] if leg["sport"] in GARMIN_SPORT else "other"
        steps = leg["steps"] or [_st("steady", leg.get("minutes") or 30, 2)]
        name = session["title"]
        if len(parts) > 1:
            name = f"{name} ({'bike' if leg['sport'] == 'bike' else 'run'} leg)"
        wo: dict[str, Any] = {
            "workoutName": f"Rabbit: {name}"[:80],
            "description": (session.get("detail") or "")[:1000],
            "sportType": GARMIN_SPORT[sport],
            "estimatedDurationInSecs": int(round(step_minutes(steps) * 60)),
            "workoutSegments": [{"segmentOrder": 1, "sportType": GARMIN_SPORT[sport],
                                 "workoutSteps": _garmin_steps(steps, sport, athlete, _Order())}],
        }
        if sport == "swim":
            wo["poolLength"] = 25.0
            wo["poolLengthUnit"] = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
        if session.get("sport") == "brick" and i == 0:
            wo["description"] = (session.get("detail") or "")[:1000]
        out.append(wo)
    return out


def session_hash(session: dict[str, Any], date_key: str, athlete: dict[str, Any]) -> str:
    """Changes whenever what we'd upload changes (content, day or the athlete's targets)."""
    import hashlib
    import json
    basis = json.dumps([date_key, session.get("title"), session.get("detail"),
                        session.get("steps"), session.get("legs"), session.get("sport"),
                        athlete.get("ftp_w"), athlete.get("run_threshold_pace")],
                       sort_keys=True, default=str)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def iter_sessions(plan: dict[str, Any]):
    """(week, day, session) for every session in the plan."""
    for w in plan.get("weeks", []):
        for d in sorted(w["days"]):
            for s in w["days"][d]:
                yield w, d, s


def week_for(plan: dict[str, Any], day: date) -> dict[str, Any] | None:
    for w in plan.get("weeks", []):
        ws = date.fromisoformat(w["start"])
        if ws <= day < ws + timedelta(days=7):
            return w
    return None


def to_planned_week(plan: dict[str, Any], start: date) -> dict[str, Any]:
    """The coach log's planned-week shape (weekplan.WeekPlanner) for the week at ``start``."""
    days: dict[str, list[dict[str, Any]]] = {(start + timedelta(days=i)).isoformat(): [] for i in range(7)}
    w = week_for(plan, start)
    if w is not None:
        for d, ss in w["days"].items():
            if d in days:
                days[d] = [{"sport": s["sport"] if s["sport"] != "other" else "other",
                            "title": s["title"], "minutes": s.get("minutes"),
                            "detail": (s.get("detail") or "")[:200], "id": s["id"]} for s in ss]
    return {"focus": w["focus"] if w else "", "week_number": w["index"] if w else None,
            "days": days, "created": 0, "source": "builder"}


def clamp_minutes(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise PlanError("minutes must be a number")
    if not 10 <= v <= 600:
        raise PlanError("Sessions can be 10 to 600 minutes.")
    return _r5(v)
