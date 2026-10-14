"""Workout day: the "Ready to go" screen before a session and the reaction card after one.

``GET /app/api/workout/today?session_id=`` (pre-workout) and
``GET /app/api/workout/reaction?activity_id=`` (post-workout). Deterministic, no model
call, so Oura readiness may feed the readiness line (it comes from ``today.recommend``
and is only shown in the app; nothing here reaches a model).

Pre-workout: today's planned session (or the chosen one) with a one-line purpose by
kind and phase, steps grouped warm-up / main / cool-down with concrete targets in the
athlete's units (run pace from threshold pace, bike power from FTP, swim pace from CSS,
heart rate from threshold HR; RPE when nothing is known), fueling (``nutrition.fuel``),
default gear for the sport with mileage, the Garmin sync state, current weather at
``home_location`` (Open-Meteo, cached 30 min) and a readiness line. Rest days and no plan
get a rest card or a free "30-45 min easy" suggestion.

Post-workout: the activity is matched to the plan the same way the week view does it
(``weekplan.merge``: same day, same sport). Verdict:

* ``nailed``: matched, duration within ±10% of plan and not outside the target zone,
* ``close``: matched but off on duration or effort,
* ``different``: something else was planned that day and this didn't match it,
* ``bonus``: nothing was planned (or no plan).

Plus XP (``progress.workout_xp`` + the planned-session bonus when matched), the day
streak, new 12-month bests (this activity beats every other one), gear mileage added and
tomorrow's session.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import anyio
import httpx2

from .nutrition import fuel
from .planbuilder import PACE_ZONES, POWER_ZONES, ZONE_NAMES, iter_sessions, step_minutes, week_for
from .progress import PLAN_SESSION_XP, workout_xp
from .stats import _rows, category
from .weekplan import _seconds, merge

if TYPE_CHECKING:
    from .agent import Agent
    from .oura import OuraClient

KM_MI = 1.609344
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL = "https://api.open-meteo.com/v1/forecast"
WX_CACHE_S = 1800
WX_CACHE_MAX = 200
DUR_TOL = 0.10
HR_ZONES = {1: (0.68, 0.81), 2: (0.81, 0.89), 3: (0.90, 0.93), 4: (0.94, 1.00), 5: (1.00, 1.06)}
# Swim: seconds per 100 m added to CSS (slow end, fast end).
SWIM_ZONES = {1: (20, 12), 2: (12, 6), 3: (6, 2), 4: (2, -2), 5: (-2, -6)}
RPE = {1: "RPE 2-3 · very easy", 2: "RPE 3-4 · conversational", 3: "RPE 5-6 · comfortably hard",
       4: "RPE 7-8 · hard", 5: "RPE 9 · very hard"}
STEP_LABEL = {"warmup": "Warm-up", "cooldown": "Cool-down", "work": "Hard", "steady": "Steady",
              "recover": "Easy"}
STEADY_KINDS = {"easy", "long", "endurance", "recovery", "tempo", "shakeout", "racepace"}

PURPOSE = {
    "easy": "easy aerobic time builds your engine without adding fatigue.",
    "long": "the long session builds endurance and time on your feet.",
    "endurance": "steady endurance work grows your aerobic base.",
    "recovery": "light movement flushes the legs so the hard days land.",
    "strides": "easy running plus strides keeps your legs quick without real fatigue.",
    "tempo": "tempo raises the pace you can hold comfortably-hard for a long time.",
    "threshold": "threshold reps push up the effort you can sustain before fatigue snowballs.",
    "vo2": "VO2 reps raise your aerobic ceiling: short, hard and controlled.",
    "racepace": "race-pace work rehearses the exact effort you'll hold on race day.",
    "openers": "openers wake the legs up without tiring them.",
    "shakeout": "a shakeout keeps you loose; nothing to prove today.",
    "technique": "technique makes every stroke cheaper, which pays off over the whole swim.",
    "css": "CSS reps lift the pace you can hold for a whole race swim.",
    "brick": "the brick trains running on tired bike legs, just like race day.",
    "strength": "strength work makes you durable: fewer niggles, more consistent training.",
    "mobility": "mobility keeps you moving well so training stays comfortable.",
    "race": "race day. Everything you've done leads here.",
}
PHASE_LEAD = {"base": "Base phase", "build": "Build phase", "peak": "Peak phase", "taper": "Taper",
              "race": "Race week"}
CUE = {
    "easy": "Conversational the whole way. If you can't talk, slow down.",
    "long": "Start slower than you want, fuel early, finish strong.",
    "endurance": "Smooth and steady; keep the effort even on hills.",
    "recovery": "Easier than easy. It should feel almost too slow.",
    "strides": "Strides are fast but relaxed: tall posture, quick feet, full recovery.",
    "tempo": "Comfortably hard: a few words, not a sentence.",
    "threshold": "Hold back on rep one; the last rep should be your best.",
    "vo2": "Same effort every rep, and truly easy on the recoveries.",
    "racepace": "Lock into race effort and practise your race fueling.",
    "openers": "Quick and sharp, then done. Leave feeling fresh.",
    "shakeout": "Loose and easy; a few pickups if the legs feel good.",
    "technique": "Quality over speed: long strokes, relaxed breathing.",
    "css": "Even splits on every 100; the short rests keep it honest.",
    "brick": "Run the first kilometre easy; your legs will come round.",
    "strength": "Slow, controlled reps with good form beat heavy and sloppy.",
    "mobility": "Breathe into each position; no forcing.",
    "race": "Start easier than you want and fuel early.",
}
GEAR_SPORT = {"run": ("run",), "bike": ("bike",), "swim": ("swim",), "brick": ("bike", "run")}
BEST_LABEL = {"longest_run_km": "New longest run this year!", "longest_ride_km": "New longest ride this year!",
              "longest_swim_km": "New longest swim this year!", "longest_workout_min": "Your longest workout this year!",
              "biggest_climb_m": "Biggest climb of the year!"}


# ------------------------------------------------------------- formatting --
def _mmss(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def _amount(s: dict[str, Any]) -> str:
    if s.get("meters"):
        return f"{int(s['meters'])} m"
    m = float(s.get("minutes") or 0)
    if m < 1:
        return f"{int(round(m * 60))} s"
    if abs(m - round(m)) > 0.01:
        return f"{_mmss(m * 60)} min"
    return f"{int(round(m))} min"


def targets(sport: str, zone: int, athlete: dict[str, Any]) -> list[dict[str, str]]:
    """Concrete targets for one zone: the sport's own metric first, then heart rate."""
    zone = min(5, max(1, int(zone or 2)))
    imp = athlete.get("units") == "imperial"
    out: list[dict[str, str]] = []
    pace, ftp, css, lthr = (athlete.get("run_threshold_pace"), athlete.get("ftp_w"),
                            athlete.get("swim_css"), athlete.get("threshold_hr"))
    num = lambda v: isinstance(v, int | float) and not isinstance(v, bool) and v > 0  # noqa: E731
    if sport == "run" and num(pace):
        f = KM_MI if imp else 1.0
        lo, hi = PACE_ZONES[zone]
        out.append({"kind": "pace", "label": f"{_mmss(pace * lo * f)}–{_mmss(pace * hi * f)} /{'mi' if imp else 'km'}"})
    elif sport == "bike" and num(ftp):
        lo, hi = POWER_ZONES[zone]
        out.append({"kind": "power", "label": f"{round(ftp * lo)}–{round(ftp * hi)} W"})
    elif sport == "swim" and num(css):
        slow, fast = SWIM_ZONES[zone]
        out.append({"kind": "pace", "label": f"{_mmss(css + fast)}–{_mmss(css + slow)} /100m"})
    if sport != "swim" and num(lthr):
        lo, hi = HR_ZONES[zone]
        out.append({"kind": "hr", "label": f"{round(lthr * lo)}–{round(lthr * hi)} bpm"})
    if not out:
        out.append({"kind": "rpe", "label": RPE[zone]})
    return out


def _step_view(s: dict[str, Any], sport: str, athlete: dict[str, Any]) -> dict[str, Any]:
    if s.get("type") == "repeat":
        return {"type": "repeat", "reps": int(s.get("reps") or 1),
                "steps": [_step_view(x, sport, athlete) for x in s.get("steps") or []]}
    z = int(s.get("zone") or 2)
    t = s.get("type") or "steady"
    tg = targets(sport, z, athlete)
    if t == "recover" and sport == "swim":
        tg = [{"kind": "rest", "label": "Rest"}]
    return {"type": t, "label": STEP_LABEL.get(t, "Steady"), "amount": _amount(s), "zone": z,
            "zone_name": ZONE_NAMES.get(z, ""), "targets": tg}


def sections(steps: list[dict[str, Any]], sport: str, athlete: dict[str, Any],
             label: str | None = None) -> list[dict[str, Any]]:
    """Leading warm-ups, the main set, trailing cool-downs (empty groups dropped)."""
    i, j = 0, len(steps)
    while i < j and steps[i].get("type") == "warmup":
        i += 1
    while j > i and steps[j - 1].get("type") == "cooldown":
        j -= 1
    groups = [("warmup", "Warm-up", steps[:i]), ("main", label or "Main set", steps[i:j]),
              ("cooldown", "Cool-down", steps[j:])]
    return [{"kind": k, "name": n, "minutes": round(step_minutes(ss, float(athlete.get("swim_css") or 120))),
             "steps": [_step_view(s, sport, athlete) for s in ss]} for k, n, ss in groups if ss]


def purpose(kind: str | None, phase: str | None, recovery: bool = False) -> str:
    what = PURPOSE.get(kind or "", "steady work that keeps the habit going.")
    lead = "Recovery week" if recovery and phase not in ("taper", "race") else PHASE_LEAD.get(phase or "", "Today")
    return f"{lead}: {what}"


def _zone_of(s: dict[str, Any]) -> tuple[int, bool]:
    """(the session's main zone by minutes outside warm-up/cool-down, has hard intervals)."""
    mins: dict[int, float] = {}
    intervals = False

    def walk(ss: list[dict[str, Any]], mult: int) -> None:
        nonlocal intervals
        for x in ss:
            if x.get("type") == "repeat":
                if any(y.get("type") == "work" and int(y.get("zone") or 0) >= 4 for y in x.get("steps") or []):
                    intervals = True
                walk(x.get("steps") or [], mult * int(x.get("reps") or 1))
            elif x.get("type") not in ("warmup", "cooldown", "recover"):
                z = int(x.get("zone") or 2)
                mins[z] = mins.get(z, 0.0) + mult * float(x.get("minutes") or (x.get("meters") or 0) / 50)
    steps = s.get("steps") or []
    for lg in s.get("legs") or []:
        steps = steps + (lg.get("steps") or [])
    walk(steps, 1)
    return (max(mins, key=lambda z: mins[z]) if mins else 2), intervals


# ----------------------------------------------------------------- weather --
_WX: dict[str, tuple[float, dict[str, Any] | None]] = {}
WX_CODES = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
            51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 61: "Rain", 63: "Rain", 65: "Heavy rain",
            66: "Freezing rain", 67: "Freezing rain", 71: "Snow", 73: "Snow", 75: "Heavy snow", 77: "Snow",
            80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
            95: "Thunderstorms", 96: "Thunderstorms", 99: "Thunderstorms"}


async def weather_now(location: str, *, http: httpx2.AsyncClient | None = None,
                      clock: Callable[[], float] = time.time) -> dict[str, Any] | None:
    """Now + the next 3 hours at ``location`` (Open-Meteo, no key), cached 30 minutes."""
    key = " ".join((location or "").split()).lower()[:80]
    if not key:
        return None
    hit = _WX.get(key)
    if hit and clock() - hit[0] < WX_CACHE_S:
        return hit[1]
    client = http or httpx2.AsyncClient(timeout=6)
    out: dict[str, Any] | None = None
    try:
        g = await client.get(GEO_URL, params={"name": location.split(",")[0].strip(), "count": 1})
        g.raise_for_status()
        res = (g.json().get("results") or [None])[0]
        if res:
            w = await client.get(WX_URL, params={
                "latitude": res["latitude"], "longitude": res["longitude"], "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "hourly": "temperature_2m,precipitation_probability,weather_code", "forecast_hours": 4})
            w.raise_for_status()
            body = w.json()
            cur = body.get("current") or {}
            hourly = body.get("hourly") or {}
            hours = []
            def pick(k: str, i: int) -> Any:
                arr = hourly.get(k) or []
                return arr[i] if i < len(arr) else None
            for i, t in enumerate((hourly.get("time") or [])[1:4], start=1):
                hours.append({"time": str(t)[11:16], "temp_c": pick("temperature_2m", i),
                              "rain_pct": pick("precipitation_probability", i),
                              "summary": WX_CODES.get(pick("weather_code", i), "")})
            out = {"place": f"{res.get('name')}, {res.get('admin1') or res.get('country') or ''}".strip(", "),
                   "temp_c": cur.get("temperature_2m"), "feels_c": cur.get("apparent_temperature"),
                   "wind_kmh": cur.get("wind_speed_10m"), "summary": WX_CODES.get(cur.get("weather_code"), ""),
                   "rain_pct": max((h["rain_pct"] for h in hours if isinstance(h["rain_pct"], int | float)), default=None),
                   "next": hours}
    except Exception:
        out = None
    finally:
        if http is None:
            await client.aclose()
    if len(_WX) >= WX_CACHE_MAX:
        _WX.pop(next(iter(_WX)))
    _WX[key] = (clock(), out)
    return out


# -------------------------------------------------------------------- gear --
def gear_for(views: list[dict[str, Any]], sport: str, *, activity_id: int | None = None,
             imperial: bool = False) -> dict[str, Any] | None:
    """The item used for ``sport``: tagged to the activity, else the active default."""
    cat = category(sport) if sport not in GEAR_SPORT else sport
    sports = GEAR_SPORT.get(cat, (cat,))
    active = [g for g in views if not g.get("retired")]
    it = next((g for g in active if activity_id is not None and activity_id in (g.get("activity_ids") or [])), None)
    if it is None:
        it = next((g for s in sports for g in active if s in (g.get("default_for") or [])), None)
    if it is None:
        return None
    unit, f = ("mi", 1 / KM_MI) if imperial else ("km", 1.0)
    name = " ".join(x for x in (it.get("brand"), it.get("model")) if x) or it.get("nickname") or it.get("kind", "Gear")
    total = float(it.get("total_km") or 0)
    warn = None
    if it.get("status") == "retire":
        warn = f"{round(total * f):,} {unit} on these: time to retire them."
    elif it.get("status") == "soon":
        warn = f"{it.get('pct_of_alert')}% of their life used. Start breaking in the next pair."
    return {"id": it.get("id"), "kind": it.get("kind"), "name": name, "total_km": round(total, 1),
            "total_label": f"{round(total * f):,} {unit}", "status": it.get("status") or "ok", "warning": warn}


# ------------------------------------------------------------ pre-workout --
def _clean_fuel(session: dict[str, Any], day: str, plan: dict[str, Any] | None) -> dict[str, Any] | None:
    try:
        return fuel(session, day, race_date=(plan or {}).get("race_date"), distance=(plan or {}).get("distance"))
    except Exception:
        return None


def session_view(s: dict[str, Any], day: str, athlete: dict[str, Any], *, phase: str | None = None,
                 recovery: bool = False, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure: everything the "Ready to go" screen shows for one planned session."""
    sport, kind = s.get("sport") or "other", s.get("kind")
    if s.get("legs"):
        secs = []
        for lg in s["legs"]:
            name = f"{'Bike' if lg.get('sport') == 'bike' else 'Run'} leg"
            for sec in sections(lg.get("steps") or [], lg.get("sport") or "run", athlete, name):
                secs.append(sec | {"name": f"{name} · {sec['name']}" if sec["kind"] != "main" else name})
    else:
        steps = s.get("steps") or []
        secs = sections(steps, sport, athlete) if steps else []
    total = s.get("minutes") or sum(int(lg.get("minutes") or 0) for lg in s.get("legs") or [])
    zone, _ = _zone_of(s)
    return {
        "id": s.get("id"), "date": day, "title": s.get("title") or "Session", "sport": sport, "kind": kind,
        "minutes": total or None, "meters": s.get("meters"), "detail": s.get("detail") or "",
        "purpose": purpose(kind, phase, recovery), "cue": CUE.get(kind or "", "Smooth and controlled."),
        "sections": secs,
        "warmup_min": sum(x["minutes"] for x in secs if x["kind"] == "warmup"),
        "cooldown_min": sum(x["minutes"] for x in secs if x["kind"] == "cooldown"),
        "main_targets": targets(sport if sport in ("run", "bike", "swim") else "other", zone, athlete)
        if sport not in ("strength", "rest") else [],
        "exercises": s.get("exercises") or [], "prehab": s.get("prehab") or [],
        "fuel": _clean_fuel(s, day, plan),
        "garmin": {"on_watch": bool((s.get("garmin") or {}).get("workout_ids")),
                   "syncable": sport not in ("rest",) and kind != "race"},
    }


FREE = {"title": "Free session", "sport": "other", "minutes": None,
        "purpose": "Nothing planned: 30-45 min easy, your choice of sport. Moving keeps the habit alive.",
        "cue": "Keep it conversational and enjoy it."}


def _planned_week(agent: "Agent", user_id: str, plan: dict[str, Any] | None, goal: dict[str, Any] | None,
                  day: date) -> tuple[date, dict[str, list[dict[str, Any]]] | None, dict[str, Any] | None]:
    """(week start, planned days for merge, the built plan week) for the week holding ``day``."""
    monday = day - timedelta(days=day.weekday())
    if plan:
        w = week_for(plan, day)
        if w is not None:
            return (date.fromisoformat(w["start"]),
                    {d: [{"sport": s["sport"], "title": s["title"], "minutes": s.get("minutes"),
                          "kind": s.get("kind"), "id": s.get("id")} for s in ss] for d, ss in w["days"].items()}, w)
        return monday, None, None
    if goal and goal.get("plan"):
        try:
            pw, cached = agent.planner.cached_days(user_id, goal, day)
            if cached:
                return date.fromisoformat(pw["start"]), cached.get("days"), None
        except Exception:
            pass
    return monday, None, None


def _find(plan: dict[str, Any] | None, sid: str) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    for w, d, s in iter_sessions(plan or {}):
        if s.get("id") == sid:
            return s, d, w
    return None


def readiness_line(card: dict[str, Any] | None) -> dict[str, Any] | None:
    """One line from the Today card's signals (form, readiness, streak)."""
    if not card:
        return None
    sig = card.get("signals") or []
    bits = [f"{s['label']} {s['value']}" for s in sig if s.get("label") in ("Form", "Readiness", "Oura readiness")]
    tone = card.get("tone")
    if tone in ("easy", "rest"):
        line = card.get("detail") or "Take it easy today."
    elif bits:
        good = all(s.get("good") for s in sig if s.get("label") in ("Form", "Readiness", "Oura readiness"))
        line = " · ".join(bits) + (": good to go." if good else ": keep the easy parts easy.")
    else:
        return None
    return {"tone": tone, "line": line, "signals": sig}


class WorkoutDay:
    def __init__(self, agent: "Agent", oura: "OuraClient | None", *,
                 gear: Callable[[str], list[dict[str, Any]]] | None = None,
                 weather: Callable[[str], Any] | None = None) -> None:
        self._a = agent
        self._oura = oura
        self._gear = gear
        self._weather = weather if weather is not None else weather_now

    async def _acts(self, user_id: str, *, fresh: bool = False) -> list[dict[str, Any]] | None:
        try:
            _, acts = await anyio.to_thread.run_sync(lambda: self._a.stats.activities(user_id, fresh=fresh))
            return acts
        except Exception:
            return None

    async def _gear_views(self, user_id: str) -> list[dict[str, Any]]:
        if self._gear is None:
            return []
        try:
            return await anyio.to_thread.run_sync(lambda: self._gear(user_id))  # type: ignore[misc]
        except Exception:
            return []

    async def today(self, user_id: str, session_id: str | None = None) -> dict[str, Any]:
        a = self._a
        today = a._now(user_id).date()
        plan = await anyio.to_thread.run_sync(a.plans.get, user_id)
        goal = a.coach.active_goal(user_id)
        athlete = a.coach.athlete(user_id)
        imperial = athlete.get("units") == "imperial"
        acts = await self._acts(user_id)
        found = _find(plan, session_id) if session_id else None
        day = date.fromisoformat(found[1]) if found else today
        start, planned, _w = _planned_week(a, user_id, plan, goal, day)
        days = merge(start, today, planned, acts or [])
        dview = next((d for d in days if d["date"] == day.isoformat()), None) or {"sessions": [], "extra": []}
        status = {s.get("id"): s for s in dview["sessions"] if s.get("id")}
        work = [s for s in dview["sessions"] if s.get("sport") != "rest"]
        others = [{"id": s.get("id"), "title": s.get("title"), "sport": s.get("sport"), "minutes": s.get("minutes"),
                   "status": s.get("status")} for s in work]
        card = None
        if day == today:
            try:
                from .today import TodayService
                card = await TodayService(a, self._oura).get(user_id)
            except Exception:
                card = None
        out: dict[str, Any] = {"date": day.isoformat(), "today": today.isoformat(), "units": "imperial" if imperial else "metric",
                               "readiness": readiness_line(card) if day == today else None, "others": others, "weather": None,
                               "has_plan": bool(plan) or planned is not None}
        home = str(athlete.get("home_location") or "").strip()
        if home and day == today:
            try:
                with anyio.fail_after(8):
                    out["weather"] = await self._weather(home)
            except Exception:
                out["weather"] = None
        if found is None and plan:
            pick = next((s for s in work if s.get("status") == "planned"), None) or (work[0] if work else None)
            if pick and pick.get("id"):
                found = _find(plan, pick["id"])
        if found is not None:
            s, d, w = found
            if s.get("sport") == "rest":
                return out | {"state": "rest"}
            view = session_view(s, d, athlete, phase=w.get("phase"), recovery=bool(w.get("recovery")), plan=plan)
            st = status.get(s.get("id")) or {}
            view["status"] = st.get("status") or ("planned" if d >= today.isoformat() else "missed")
            view["activity"] = st.get("activity")
            g = await self._gear_views(user_id)
            view["gear"] = [x for x in (gear_for(g, sp, imperial=imperial) for sp in GEAR_SPORT.get(s["sport"], ())) if x]
            return out | {"state": "session", "session": view}
        if work:  # an uploaded plan: title/minutes/detail only
            s = next((x for x in work if x.get("status") == "planned"), work[0])
            view = {"id": None, "date": day.isoformat(), "title": s.get("title") or "Session", "sport": s.get("sport"),
                    "kind": None, "minutes": s.get("minutes"), "detail": s.get("detail") or "",
                    "purpose": purpose(None, None), "cue": CUE["easy"], "sections": [], "warmup_min": 0,
                    "cooldown_min": 0, "main_targets": [], "exercises": [], "prehab": [], "fuel": None,
                    "garmin": {"on_watch": False, "syncable": False}, "status": s.get("status"),
                    "activity": s.get("activity")}
            g = await self._gear_views(user_id)
            view["gear"] = [x for x in (gear_for(g, sp, imperial=imperial) for sp in GEAR_SPORT.get(s.get("sport") or "", ())) if x]
            return out | {"state": "session", "session": view}
        if dview["sessions"]:
            return out | {"state": "rest"}
        free = FREE | {"main_targets": targets("other", 2, athlete)}
        return out | {"state": "free", "free": free}

    # --------------------------------------------------------- reaction --
    async def reaction(self, user_id: str, activity_id: int) -> dict[str, Any] | None:
        a = self._a
        today = a._now(user_id).date()
        acts = await self._acts(user_id)
        act = _by_id(acts or [], activity_id)
        if act is None:
            acts = await self._acts(user_id, fresh=True)
            act = _by_id(acts or [], activity_id)
        if act is None or acts is None:
            return None
        athlete = a.coach.athlete(user_id)
        plan = await anyio.to_thread.run_sync(a.plans.get, user_id)
        goal = a.coach.active_goal(user_id)
        try:
            day = date.fromisoformat(str(act.get("date") or "")[:10])
        except ValueError:
            day = today
        start, planned, _w = _planned_week(a, user_id, plan, goal, day)
        days = merge(start, max(today, day), planned, acts)
        dview = next((d for d in days if d["date"] == day.isoformat()), None)
        try:
            streak = (await anyio.to_thread.run_sync(a.stats.get, user_id)).get("streak") or {}
        except Exception:
            streak = {}
        gear = await self._gear_views(user_id)
        return build_reaction(act, acts, dview, plan=plan, athlete=athlete, today=today,
                              streak=streak, gear=gear, tomorrow=_tomorrow(plan, today))


def _by_id(acts: list[dict[str, Any]], aid: int) -> dict[str, Any] | None:
    a = next((x for x in acts if x.get("activity_id") == aid), None)
    parent = (a or {}).get("multisport") or {}
    if a is not None and parent.get("parent_id"):
        return next((x for x in acts if x.get("activity_id") == parent["parent_id"]), a)
    return a


def _tomorrow(plan: dict[str, Any] | None, today: date) -> dict[str, Any] | None:
    t = today + timedelta(days=1)
    w = week_for(plan or {}, t) if plan else None
    if w is None:
        return None
    ss = w["days"].get(t.isoformat()) or []
    work = [s for s in ss if s.get("sport") != "rest"]
    if not work:
        return {"date": t.isoformat(), "rest": True, "title": "Rest day", "sport": "rest", "minutes": None, "id": None}
    s = work[0]
    return {"date": t.isoformat(), "rest": False, "title": s.get("title"), "sport": s.get("sport"),
            "minutes": s.get("minutes") or sum(int(lg.get("minutes") or 0) for lg in s.get("legs") or []) or None,
            "id": s.get("id"), "more": len(work) - 1}


# ---------------------------------------------------------------- verdict --
def _sec_per_km(act: dict[str, Any]) -> float | None:
    km = act.get("distance_km")
    sec = _seconds(act.get("duration"))
    if isinstance(km, int | float) and km > 0.2 and sec > 0:
        return sec / km
    return None


def check_effort(session: dict[str, Any], act: dict[str, Any], athlete: dict[str, Any]) -> dict[str, Any]:
    """Was the effort in the session's main zone? ``in_zone`` None when it can't be judged
    (interval sessions, or no threshold numbers)."""
    zone, intervals = _zone_of(session)
    sport = session.get("sport") or "other"
    res: dict[str, Any] = {"zone": zone, "zone_name": ZONE_NAMES.get(zone, ""), "in_zone": None, "basis": None,
                           "direction": None, "target": None}
    if intervals or (session.get("kind") or "") not in STEADY_KINDS:
        return res
    lthr, pace, ftp = athlete.get("threshold_hr"), athlete.get("run_threshold_pace"), athlete.get("ftp_w")
    hr = act.get("avg_hr")
    if isinstance(hr, int | float) and isinstance(lthr, int | float) and lthr > 0 and sport != "swim":
        lo, hi = HR_ZONES[zone]
        lo_b, hi_b = lthr * lo, lthr * hi
        res.update(basis="hr", target=f"{round(lo_b)}–{round(hi_b)} bpm", actual=f"{round(hr)} bpm")
        if hr > hi_b + 3:
            res.update(in_zone=False, direction="harder")
        elif hr < lo_b - 8:
            res.update(in_zone=False, direction="easier")
        else:
            res["in_zone"] = True
        return res
    spk = _sec_per_km(act)
    if sport == "run" and spk and isinstance(pace, int | float) and pace > 0:
        lo, hi = PACE_ZONES[zone]
        fast, slow = pace * lo, pace * hi
        res.update(basis="pace", target=f"{_mmss(fast)}–{_mmss(slow)} /km", actual=f"{_mmss(spk)} /km")
        if spk < fast * 0.97:
            res.update(in_zone=False, direction="harder")
        elif spk > slow * 1.06:
            res.update(in_zone=False, direction="easier")
        else:
            res["in_zone"] = True
        return res
    pw = act.get("avg_power_w")
    if sport == "bike" and isinstance(pw, int | float) and isinstance(ftp, int | float) and ftp > 0:
        lo, hi = POWER_ZONES[zone]
        res.update(basis="power", target=f"{round(ftp * lo)}–{round(ftp * hi)} W", actual=f"{round(pw)} W")
        if pw > ftp * hi * 1.05:
            res.update(in_zone=False, direction="harder")
        elif pw < ftp * lo * 0.85:
            res.update(in_zone=False, direction="easier")
        else:
            res["in_zone"] = True
    return res


def verdict(matched: dict[str, Any] | None, act: dict[str, Any], athlete: dict[str, Any], *,
            planned_other: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Pure: the verdict and a short friendly line."""
    minutes = round(_seconds(act.get("duration")) / 60)
    sport = category(act.get("sport"))
    word = {"run": "run", "bike": "ride", "swim": "swim", "brick": "brick", "strength": "strength session",
            "hike": "hike", "ski": "ski", "climb": "climb", "paddle": "paddle"}.get(sport, "workout")
    if matched is None:
        if planned_other:
            p = planned_other[0]
            return {"verdict": "different", "line": f"You swapped {p.get('title') or 'the plan'} for a {word}. "
                    "Swaps happen; it all still counts.", "duration_ratio": None, "effort": None}
        return {"verdict": "bonus", "line": f"Bonus {word}! Unplanned time still builds fitness.",
                "duration_ratio": None, "effort": None}
    pm = matched.get("minutes") or sum(int(lg.get("minutes") or 0) for lg in matched.get("legs") or [])
    ratio = round(minutes / pm, 2) if pm else None
    effort = check_effort(matched, act, athlete)
    dur_ok = ratio is None or abs(ratio - 1) <= DUR_TOL
    title = matched.get("title") or "the session"
    if dur_ok and effort["in_zone"] is not False:
        line = (f"{title}, right on plan" + (f" and in {effort['zone_name']} range" if effort["in_zone"] else "")
                + ". That's how fitness gets built.")
        return {"verdict": "nailed", "line": line, "duration_ratio": ratio, "effort": effort}
    if effort["in_zone"] is False and effort["direction"] == "harder":
        line = f"Done, but harder than planned ({effort.get('actual')} vs {effort['target']}). Keep easy days easy."
    elif effort["in_zone"] is False:
        line = f"Done, a touch easier than planned ({effort.get('actual')} vs {effort['target']}). Totally fine."
    elif ratio is not None and ratio < 1:
        line = f"{minutes}' of {pm}' planned. Shorter still counts; consistency wins."
    else:
        line = f"{minutes}' vs {pm}' planned. Extra time banked; keep tomorrow honest."
    return {"verdict": "close", "line": line, "duration_ratio": ratio, "effort": effort}


def new_bests(acts: list[dict[str, Any]], aid: int, today: date) -> list[dict[str, Any]]:
    """12-month bests this activity sets: it beats every other activity (at least one) on
    longest run/ride/swim distance, longest workout or biggest climb."""
    year_ago = today - timedelta(days=364)
    rows = [r for r in _rows(acts) if year_ago <= r["date"] <= today]
    me = next((r for r in rows if r["id"] == aid), None)
    if me is None:
        return []
    others = [r for r in rows if r["id"] != aid]
    checks = [("longest_run_km", "km", "run"), ("longest_ride_km", "km", "bike"), ("longest_swim_km", "km", "swim"),
              ("longest_workout_min", "min", None), ("biggest_climb_m", "climb", None)]
    out = []
    for key, field, sport in checks:
        if sport is not None and me["sport"] != sport:
            continue
        pool = [r[field] for r in others if sport is None or r["sport"] == sport]
        if not pool or not me[field] or me[field] <= max(pool):
            continue
        out.append({"key": key, "label": BEST_LABEL[key], "value": round(me[field], 1),
                    "previous": round(max(pool), 1)})
    # One headline best is plenty: the sport's distance first, then time, then climb.
    return out[:2]


def build_reaction(act: dict[str, Any], acts: list[dict[str, Any]], dview: dict[str, Any] | None, *,
                   plan: dict[str, Any] | None, athlete: dict[str, Any], today: date, streak: dict[str, Any],
                   gear: list[dict[str, Any]], tomorrow: dict[str, Any] | None) -> dict[str, Any]:
    """Pure: the post-workout card for ``act`` given its merged day (``weekplan.merge``)."""
    aid = act.get("activity_id")
    imperial = athlete.get("units") == "imperial"
    sessions = (dview or {}).get("sessions") or []
    hit = next((s for s in sessions if (s.get("activity") or {}).get("id") == aid), None)
    matched = None
    if hit is not None:
        found = _find(plan, hit["id"]) if hit.get("id") else None
        matched = dict(found[0]) if found else {k: hit.get(k) for k in ("id", "sport", "title", "minutes", "kind")}
    other = [s for s in sessions if s.get("sport") != "rest" and s.get("status") != "done" and s is not hit]
    v = verdict(matched, act, athlete, planned_other=other if hit is None else None)
    minutes = _seconds(act.get("duration")) / 60
    xp = workout_xp(minutes)
    plan_xp = PLAN_SESSION_XP if matched is not None else 0
    km = float(act.get("distance_km") or 0)
    sport = category(act.get("sport"))
    g = gear_for(gear, sport, activity_id=aid, imperial=imperial) if km > 0 else None
    gear_line = None
    if g:
        unit, f = ("mi", 1 / KM_MI) if imperial else ("km", 1.0)
        gear_line = g | {"added_km": round(km, 1), "label": f"+{km * f:.1f} {unit} on {g['name']}"}
    planned = None
    if matched is not None:
        zone, _ = _zone_of(matched)
        planned = {"title": matched.get("title"), "minutes": matched.get("minutes"), "kind": matched.get("kind"),
                   "meters": matched.get("meters"), "zone": zone, "zone_name": ZONE_NAMES.get(zone, ""),
                   "targets": targets(matched.get("sport") or "other", zone, athlete)
                   if matched.get("sport") not in ("strength", "rest", "brick") else []}
    spk = _sec_per_km(act)
    pace = None
    if spk and sport in ("run", "hike"):
        pace = f"{_mmss(spk * (KM_MI if imperial else 1))} /{'mi' if imperial else 'km'}"
    elif spk and sport == "swim":
        pace = f"{_mmss(spk / 10)} /100m"
    return {
        "activity": {"id": aid, "name": act.get("name") or "Workout", "sport": sport, "date": str(act.get("date") or "")[:10],
                     "minutes": round(minutes), "distance_km": round(km, 2) if km else None,
                     "avg_hr": act.get("avg_hr"), "avg_power_w": act.get("avg_power_w"), "pace": pace,
                     "climb_m": act.get("elevation_gain_m")},
        "session_id": (matched or {}).get("id"), "planned": planned,
        **v,
        "xp": {"workout": xp, "plan": plan_xp, "total": xp + plan_xp},
        "streak": {"current": int(streak.get("current") or 0), "best": int(streak.get("best") or 0)},
        "bests": new_bests(acts, aid, today) if isinstance(aid, int) else [],
        "gear": gear_line, "tomorrow": tomorrow, "units": "imperial" if imperial else "metric",
    }


__all__ = ["WorkoutDay", "build_reaction", "check_effort", "gear_for", "new_bests", "purpose", "readiness_line",
           "session_view", "targets", "verdict", "weather_now"]
