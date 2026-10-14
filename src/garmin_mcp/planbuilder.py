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
    for k in ("garmin", "edited", "title_custom"):
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
    level = athlete.get("level") if athlete.get("level") in LEVELS else "intermediate"
    return Inputs(race_date=race, distance=(goal.get("distance") or "other").lower(),
                  level=level, weekly_hours=athlete.get("weekly_hours"),
                  days=sorted(set(days), key=DAYS.index), long_day=long_day,
                  limiters=[x for x in (goal.get("limiters") or []) if x in ("swim", "bike", "run")],
                  equipment=list(athlete.get("equipment") or []), swim_pace=pace,
                  title=goal.get("title") or "Race",
                  favorites=[f for f in (athlete.get("favorite_sports") or []) if f in FAVORITE_SPORTS],
                  injuries=str(athlete.get("injuries") or "")[:500])


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


def week_hours(ph: list[str], start_h: float, peak_h: float) -> list[tuple[float, bool]]:
    """(hours, recovery?) per week."""
    ramp = [i for i, p in enumerate(ph) if p in ("base", "build")]
    out: list[tuple[float, bool]] = []
    taper_seen = 0
    t_total = ph.count("taper")
    taper_curve = {1: [0.6], 2: [0.7, 0.5], 3: [0.8, 0.65, 0.5]}.get(t_total, [0.6] * t_total)
    for i, p in enumerate(ph):
        if p in ("base", "build"):
            k = ramp.index(i)
            frac = k / max(1, len(ramp) - 1)
            h = start_h + (peak_h - start_h) * frac
            rec = (k + 1) % 4 == 0 and k != len(ramp) - 1
            out.append((round(h * (0.68 if rec else 1.0), 1), rec))
        elif p == "peak":
            out.append((round(peak_h, 1), False))
        elif p == "taper":
            out.append((round(peak_h * taper_curve[min(taper_seen, len(taper_curve) - 1)], 1), False))
            taper_seen += 1
        else:
            out.append((round(peak_h * 0.35, 1), False))
    return out


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
    # run
    if race_kind == "run":
        n = 2 if minutes < 120 else 3 if minutes < 210 else 4 if minutes < 300 else 5
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
    run_long_day = after if after in days else before if before in days else long_day

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


def build_plan(athlete: dict[str, Any], goal: dict[str, Any], *, today: date,
               start: date | None = None,
               events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
    peak_h = prof["peak"][LEVELS.index(inp.level)]
    start_h = inp.weekly_hours if isinstance(inp.weekly_hours, int | float) and inp.weekly_hours > 0 \
        else peak_h * 0.6
    start_h = max(peak_h * 0.4, min(peak_h, float(start_h)))
    if n < 6:  # short runway: hold near current volume
        peak_h = max(start_h, min(peak_h, start_h * 1.15))
    hours = week_hours(ph, start_h, peak_h)
    split = _split(race_kind, inp.limiters, inp.favorites)
    if race_kind == "tri" and inp.equipment and not {"pool", "open_water"} & set(inp.equipment):
        split.pop("swim", None)  # no water access: skip swims rather than plan the impossible
        tot = sum(split.values())
        split = {k: v / tot for k, v in split.items()}

    weeks: list[dict[str, Any]] = []
    for idx, (phase, (h, rec)) in enumerate(zip(ph, hours, strict=True), start=1):
        ws = week1 + timedelta(weeks=idx - 1)
        if phase == "race":
            days = _race_week(inp, race_kind, ws, start, h)
        else:
            minutes = h * 60
            sessions: list[dict[str, Any]] = []
            run_off = 0
            for sport, frac in split.items():
                sm = int(minutes * frac)
                if sport == "strength":
                    sm = 30 if sm < 45 else 40
                kinds = _sport_kinds(sport, race_kind, phase, sm, inp.equipment, rec)
                if race_kind == "tri" and sport == "bike" and phase in ("build", "peak") and not rec \
                        and "long" in kinds:
                    kinds[kinds.index("long")] = "brick"
                    run_off = 25 if phase == "peak" else 15
                if not kinds:
                    continue
                wsum = sum(WEIGHT[k] for k in kinds)
                cap = prof["long"].get(sport, 240)
                for k in kinds:
                    m = sm * WEIGHT[k] / wsum
                    if sport == "run" and run_off and k == "long":
                        m -= run_off
                    if k in ("long", "brick"):
                        m = min(m, cap + (run_off if k == "brick" else 0))
                    else:
                        m = min(m, cap * 0.75 if sport != "swim" else cap)
                    m = max(30 if sport == "swim" else 20, m)
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
        recompute_week(week)
        weeks.append(week)
    apply_strength(weeks, inp, race_kind)
    placed_events = apply_events(weeks, events or [], inp, start)
    return {"events": placed_events, "start": week1.isoformat(), "first_day": start.isoformat(),
            "race_date": inp.race_date.isoformat(), "distance": inp.distance,
            "race_kind": race_kind, "level": inp.level, "peak_hours": round(peak_h, 1),
            "start_hours": round(start_h, 1), "swim_pace": inp.swim_pace,
            "note": note, "weeks": weeks}


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


def apply_events(weeks: list[dict[str, Any]], events: list[dict[str, Any]], inp: Inputs,
                 start: date) -> list[dict[str, Any]]:
    """Drop the athlete's other events (B and C races) into the plan as race days.

    B race: easy two days out, short openers the day before, rest the day after, and the
    next day easy. C race: raced as a hard training day with an easy day either side.
    Events on or after the main race, before the plan starts, or in race week are skipped.
    Returns the events that were placed."""
    by_day: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for w in weeks:
        for d in w["days"]:
            by_day[d] = (w, w["days"])
    placed: list[dict[str, Any]] = []
    for ev in sorted(events, key=lambda e: e.get("date") or ""):
        try:
            d = date.fromisoformat(ev.get("date") or "")
        except ValueError:
            continue
        if d < start or d >= inp.race_date or d.isoformat() not in by_day:
            continue
        week, _ = by_day[d.isoformat()]
        if week["phase"] == "race":
            continue
        prio = ev.get("priority") if ev.get("priority") in ("B", "C") else "B"
        sport = EVENT_SPORT.get(ev.get("type") or "other", "other")
        race = make_session("other", "race", 0, title=f"Race: {ev.get('name') or 'Event'}"[:60])
        race["sport"], race["kind"], race["event_id"] = sport, "race", ev.get("id")
        race["race_distance"] = (ev.get("distance") or "").lower()  # not the main race's
        race["detail"] = (f"{prio} race. Race it with intent, but it's a step toward {inp.title}: "
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
        placed.append({"id": ev.get("id"), "name": ev.get("name"), "date": d.isoformat(),
                       "priority": prio})
    for w in weeks:
        recompute_week(w)
    return placed


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
        lines += ["", "### Other races in the plan"]
        for e in plan["events"]:
            lines.append(f"- {e['date']}: {e['name']} ({e['priority']} race)")
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
