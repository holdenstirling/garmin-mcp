"""Plan calendar: an easy-to-move week/month calendar over the built plan, a deterministic
re-balance after every change, weekly mileage goals, a "why + how" note on every session and
one-tap fixes for missed sessions.

Everything that decides is pure and deterministic (no model, never Oura); ``PlanCal`` only
gathers inputs (plan, Garmin activities, athlete) and writes through ``PlanService._edit`` so
the plan's change hook (``PlanService.add_listener``, used for TrainingPeaks sync) fires.

* **Distances** are estimated from a session's steps and the athlete's paces: run = minutes
  at each step's zone pace (``planbuilder.PACE_ZONES`` x threshold pace; else the median of
  recent Garmin runs read as easy pace; else 5:30/km threshold), bike = zone speeds, swim =
  meters. A session may carry an explicit ``km`` (imports, TrainingPeaks), which wins.
* **Weekly goal** per sport = the sessions' ``base_km`` (frozen the first time Rabbit changes a
  session, so skips, swaps and bumps don't move the goal) or their estimate; the athlete can
  override it per week (``plan["km_goals"][monday][sport]``).
* **Re-balance** (``rebalance``) after a move, swap or fix, for the touched weeks only, from
  today on: (1) new back-to-back hard days (quality, long, brick, race) are undone by moving
  the movable one (never the session the athlete just placed, quality before long) to the
  nearest available day with no hard neighbour, else a quality session becomes easy;
  (2) the week's mileage is kept on goal by adding 5-minute steps to future easy / long /
  endurance / recovery sessions of that sport, each at most +15% over its original length
  (``base_minutes``); a surplus first takes those bumps back. No session or hard day is ever
  added.
* **Missed**: a past non-rest session with no matching Garmin activity (``weekplan.merge``)
  that wasn't skipped. Fixes: ``move`` (to a day from today on), ``easy`` (an easy session of
  the same sport on a good free day this week; the original is kept as skipped) or ``skip``
  (marked skipped; its miles re-spread). The morning after a miss a ``plan_missed`` moment
  offers the same fix.
* **Undo**: every operation stores the touched weeks before the change and before the
  re-balance (``plan["cal_undo"]``, last 6): ``<id>`` undoes everything, ``<id>r`` only the
  re-balance. Synced Garmin workouts of moved sessions become orphans (removed on the next
  sync); a restored session whose workout is already an orphan simply syncs again.
"""

from __future__ import annotations

import copy
import secrets
import statistics
from collections.abc import Callable
from datetime import date, datetime, time as dtime, timedelta
from typing import TYPE_CHECKING, Any

from .moments import Moments, action
from .planbuilder import (
    DAYS,
    KINDS_BY_SPORT,
    MAX_PER_DAY,
    PACE_ZONES,
    QUALITY,
    STRENGTH_DETAIL,
    PlanError,
    describe,
    iter_sessions,
    make_session,
    rebuild_session,
    recompute_week,
    swim_meters,
    week_for,
)
from .weekplan import _seconds, merge, sport_of
from .workouttargets import how_it_went, session_targets

if TYPE_CHECKING:
    from .plans import PlanService

HARD = frozenset(QUALITY | {"long", "brick", "race"})
EASYISH = frozenset({"easy", "long", "endurance", "recovery"})
DIST_SPORTS = ("run", "bike", "swim")
MAX_BUMP = 0.15
STEP_MIN = 5
DEFAULT_THRESHOLD = 330.0          # s/km when nothing better is known (5:30/km)
EASY_FACTOR = 1.22                 # easy pace / threshold pace (middle of zone 2)
BIKE_KMH = {1: 22.0, 2: 27.0, 3: 30.0, 4: 33.0, 5: 36.0}
UNDO_KEEP = 6
KM_PER_MI = 1.609344
WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MISSED_FROM, MISSED_UNTIL = dtime(7, 0), dtime(12, 0)
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim", "brick": "brick", "strength": "session",
              "other": "session"}

# kind -> (why, how, cues). {word} = run/ride/swim, {pace} = ", about 9:10-9:50/mi" (runs).
NOTES: dict[str, tuple[str, str, str]] = {
    "easy": ("Easy aerobic miles build your engine without adding fatigue.",
             "Conversational effort{pace}. When in doubt, slower.", "Relaxed shoulders, light quick steps."),
    "recovery": ("A recovery {word}: blood flow for tired legs, nothing more.",
                 "Very easy{pace}. Walk breaks are fine.", "Stop early if your legs feel worse, not better."),
    "long": ("The long {word} builds endurance and teaches your body to go the distance.",
             "Steady and easy{pace}; only the last part may drift toward steady.",
             "Fuel every 30-45 minutes and drink to thirst."),
    "endurance": ("Aerobic endurance: the base everything else sits on.",
                  "Mostly easy{pace} with a few steady blocks.", "Smooth and even; hold back early."),
    "strides": ("Easy miles plus short strides keep your legs quick.",
                "Easy{pace}, then 6 x 20 s strides with full recovery.", "Strides are fast but relaxed, never a sprint."),
    "tempo": ("Tempo raises the pace you can hold for a long time.",
              "Comfortably hard{pace}: you can say a few words.", "Settle in; an even effort beats a fast start."),
    "threshold": ("Threshold reps push your lactate threshold up.",
                  "Hard but controlled reps{pace}, easy between.", "The last rep should feel like the first."),
    "vo2": ("Speed work: short hard reps lift your top-end fitness.",
            "Hard reps{pace}; recover fully between.", "Tall posture, quick arms; stop if form falls apart."),
    "racepace": ("Race-pace practice locks in the feel of goal pace.",
                 "Blocks at goal effort{pace}.", "Rehearse your race fueling too."),
    "openers": ("Openers wake your legs up before a race.", "Short pickups, mostly easy.",
                "Finish fresh, not tired."),
    "shakeout": ("A shakeout loosens you up for race day.", "Very easy and short.", "Save it for tomorrow."),
    "brick": ("A brick teaches your legs to run off the bike.",
              "Steady ride, then run straight off at an easy-steady effort.", "Quick transition; short steps at first."),
    "technique": ("Better form makes every lap cheaper.", "Easy effort with drills.",
                  "Long body, relaxed kick, exhale underwater."),
    "css": ("Swim speed work at your threshold (CSS) pace.", "Hard 100s with short rests.",
            "Hold the same time on every rep."),
    "strength": ("Strength keeps you durable and injury-resistant.", "Controlled reps, 2-3 rounds.",
                 "Quality over load; no grinding."),
    "mobility": ("Mobility keeps you moving well.", "Gentle, 15-20 minutes.", "Breathe into each stretch."),
    "race": ("Race day: everything you trained for.", "Start conservatively and fuel early.", "Trust the taper."),
}
MISSED_WHY = {
    "vo2": "That was this week's speed work.",
    "threshold": "That was this week's threshold session.",
    "tempo": "That was this week's tempo {word}.",
    "racepace": "That was this week's race-pace practice.",
    "long": "That was this week's long {word}, the key endurance session.",
    "brick": "That was this week's brick.",
    "css": "That was this week's swim speed set.",
    "endurance": "That was an aerobic endurance {word}.",
    "strides": "That was an easy {word} with strides.",
    "easy": "That was an easy {word} for aerobic miles.",
    "recovery": "That was a recovery {word}; missing it costs little.",
    "technique": "That was a technique swim.",
    "strength": "That was a strength session.",
}


# --------------------------------------------------------------- basics ---
def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def is_hard(s: dict[str, Any]) -> bool:
    return s.get("sport") != "rest" and s.get("kind") in HARD and not s.get("skipped")


def _word(s: dict[str, Any]) -> str:
    return SPORT_WORD.get(str(s.get("sport")), "session")


def threshold_pace(athlete: dict[str, Any], acts: list[dict[str, Any]] | None = None) -> tuple[float, str]:
    """Run threshold pace in s/km and where it came from (profile | recent | default)."""
    p = _num(athlete.get("run_threshold_pace"))
    if p is not None and 150 <= p <= 720:
        return p, "profile"
    runs = []
    for a in sorted(acts or [], key=lambda a: str(a.get("date") or ""), reverse=True):
        km, sec = _num(a.get("distance_km")), _seconds(a.get("duration"))
        if sport_of(a.get("sport")) == "run" and km and km >= 3 and sec > 0 and 180 <= sec / km <= 900:
            runs.append(sec / km)
        if len(runs) >= 15:
            break
    if len(runs) >= 3:
        return round(statistics.median(runs) / EASY_FACTOR, 1), "recent"
    return DEFAULT_THRESHOLD, "default"


def _zone(z: Any) -> int:
    return min(5, max(1, int(z))) if isinstance(z, int | float) and not isinstance(z, bool) else 2


def _zone_pace(thr: float, zone: int) -> float:
    slow, fast = PACE_ZONES[zone]
    return thr * (slow + fast) / 2


def _steps_km(steps: list[dict[str, Any]], sport: str, thr: float) -> float:
    total = 0.0
    for st in steps or []:
        if st.get("type") == "repeat":
            total += int(st.get("reps") or 0) * _steps_km(st.get("steps") or [], sport, thr)
        elif st.get("meters"):
            total += float(st["meters"]) / 1000.0
        else:
            m = float(st.get("minutes") or 0)
            z = _zone(st.get("zone"))
            total += m * 60 / _zone_pace(thr, z) if sport == "run" else m / 60 * BIKE_KMH[z]
    return total


def session_km(s: dict[str, Any], thr: float) -> dict[str, float]:
    """Estimated distance per sport ({} for rest/strength/race/other)."""
    sport = s.get("sport")
    if s.get("kind") == "race" or sport not in (*DIST_SPORTS, "brick"):
        return {}
    km = _num(s.get("km"))
    if km is not None and km > 0 and sport in DIST_SPORTS:
        return {sport: round(km, 2)}
    if sport == "swim":
        m = _num(s.get("meters")) or swim_meters(s.get("steps") or [])
        return {"swim": round(m / 1000.0, 2)} if m else {}
    if sport == "brick":
        out: dict[str, float] = {}
        for leg in s.get("legs") or []:
            if leg.get("sport") in ("run", "bike"):
                out[leg["sport"]] = round(out.get(leg["sport"], 0.0) + _steps_km(leg.get("steps") or [], leg["sport"], thr), 2)
        return out
    minutes = _num(s.get("minutes")) or 0.0
    if s.get("steps"):
        val = _steps_km(s["steps"], sport, thr)
    else:
        val = minutes * 60 / _zone_pace(thr, 2) if sport == "run" else minutes / 60 * BIKE_KMH[2]
    return {sport: round(val, 2)} if val > 0 else {}


def goal_km(s: dict[str, Any], thr: float) -> dict[str, float]:
    """What a session counts toward the weekly goal: frozen ``base_km`` once Rabbit changed it."""
    if s.get("sport") == "rest":
        return {}
    if "base_km" in s and isinstance(s["base_km"], dict):
        return {k: float(v) for k, v in s["base_km"].items() if k in DIST_SPORTS and _num(v)}
    return session_km(s, thr)


def _freeze(s: dict[str, Any], thr: float) -> None:
    if "base_km" not in s:
        s["base_km"] = session_km(s, thr)
    if "base_minutes" not in s and s.get("minutes"):
        s["base_minutes"] = s["minutes"]


def _main_zone(steps: list[dict[str, Any]]) -> int | None:
    zs: list[int] = []
    for st in steps or []:
        if st.get("type") == "repeat":
            z = _main_zone(st.get("steps") or [])
            if z:
                zs.append(z)
        elif st.get("type") in ("work", "steady"):
            zs.append(_zone(st.get("zone")))
    return max(zs) if zs else None


def target_pace(s: dict[str, Any], thr: float) -> dict[str, Any] | None:
    """Main-set pace range for runs: {zone, fast, slow} in s/km."""
    if s.get("sport") != "run" or s.get("kind") in ("race", None):
        return None
    z = _main_zone(s.get("steps") or []) or (2 if s.get("minutes") else None)
    if z is None:
        return None
    slow, fast = PACE_ZONES[z]
    return {"zone": z, "fast": round(thr * slow), "slow": round(thr * fast)}


def fmt_pace(sec_per_km: float, imperial: bool) -> str:
    v = round(sec_per_km * (KM_PER_MI if imperial else 1))
    return f"{v // 60}:{v % 60:02d}"


def fmt_km(km: float, imperial: bool) -> str:
    v = km / KM_PER_MI if imperial else km
    return f"{v:.1f}".rstrip("0").rstrip(".") + (" mi" if imperial else " km")


def note_for(s: dict[str, Any], plan: dict[str, Any], thr: float, imperial: bool) -> dict[str, str] | None:
    """A short "why + how" for a session. A coach's note (``note``, e.g. a TrainingPeaks
    description, or the notes of a coach-loaded plan) wins over Rabbit's."""
    if s.get("sport") == "rest":
        return None
    coach = s.get("note") if isinstance(s.get("note"), str) and s["note"].strip() else None
    if coach is None and (plan.get("origin") or {}).get("kind") == "coach" and not s.get("detail_custom"):
        d = str(s.get("detail") or "").strip()
        gen = describe(s.get("steps") or [])
        if d and d not in (gen, f"{s.get('meters')}m: {gen}", STRENGTH_DETAIL) and not s.get("legs"):
            coach = d
    if coach:
        text = " ".join(coach.split())[:600]
        first = text.split(". ")[0].rstrip(".")
        return {"source": "coach", "line": (first if len(first) <= 100 else first[:97].rstrip() + "...") + ".",
                "why": text, "how": "", "cues": ""}
    why, how, cues = NOTES.get(str(s.get("kind")), NOTES["easy"] if s.get("sport") in DIST_SPORTS else NOTES["strength"])
    p = target_pace(s, thr)
    unit = "/mi" if imperial else "/km"
    pace = f", about {fmt_pace(p['fast'], imperial)}-{fmt_pace(p['slow'], imperial)}{unit}" if p else ""
    fill = {"word": _word(s), "pace": pace}
    return {"source": "rabbit", "line": why.format(**fill), "why": why.format(**fill),
            "how": how.format(**fill), "cues": cues.format(**fill)}


def missed_why(s: dict[str, Any], km: dict[str, float], imperial: bool) -> str:
    t = MISSED_WHY.get(str(s.get("kind")))
    if t:
        return t.format(word=_word(s))
    total = sum(km.values())
    return f"That session added {fmt_km(total, imperial)} to your week." if total else "That was part of this week's plan."


# ------------------------------------------------------------ statuses ---
def _planned_of(w: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {d: [{"id": s["id"], "sport": s["sport"], "title": s.get("title"), "minutes": s.get("minutes"),
                 "kind": s.get("kind")} for s in ss if not s.get("skipped")] for d, ss in w["days"].items()}


def statuses(plan: dict[str, Any], acts: list[dict[str, Any]], today: date) -> dict[str, dict[str, Any]]:
    """{session id: {"status": done|missed|planned|skipped|rest, "activity"?}}."""
    out: dict[str, dict[str, Any]] = {}
    for w in plan.get("weeks", []):
        start = date.fromisoformat(w["start"])
        if start <= today:
            for day in merge(start, today, _planned_of(w), acts):
                for s in day["sessions"]:
                    item = {"status": s["status"]}
                    if s.get("activity"):
                        item["activity"] = s["activity"]
                    out[s["id"]] = item
        for d, ss in w["days"].items():
            for s in ss:
                if s.get("skipped"):
                    out[s["id"]] = {"status": "skipped"}
                elif s["id"] not in out:
                    out[s["id"]] = {"status": "rest" if s["sport"] == "rest" else "planned"}
    return out


def acts_km_by_day(acts: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """{day: {sport: km}} from Garmin; a multisport parent is skipped (its legs count)."""
    out: dict[str, dict[str, float]] = {}
    for a in acts or []:
        if (a.get("multisport") or {}).get("is_parent"):
            continue
        sp = sport_of(a.get("sport"))
        km = _num(a.get("distance_km"))
        if sp not in DIST_SPORTS or not km:
            continue
        day = str(a.get("date") or "")[:10]
        out.setdefault(day, {})[sp] = out.get(day, {}).get(sp, 0.0) + km
    return out


# ------------------------------------------------------------- mileage ---
def week_mileage(plan: dict[str, Any], w: dict[str, Any], by_day: dict[str, dict[str, float]],
                 today: date, thr: float) -> dict[str, dict[str, Any]]:
    """{sport: {done, goal, planned, custom}} (km) for sports this week plans or did."""
    start = date.fromisoformat(w["start"])
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    goal: dict[str, float] = {}
    planned: dict[str, float] = {}
    for d in days:
        for s in w["days"].get(d, []):
            for sp, km in goal_km(s, thr).items():
                goal[sp] = goal.get(sp, 0.0) + km
            if not s.get("skipped"):
                for sp, km in session_km(s, thr).items():
                    planned[sp] = planned.get(sp, 0.0) + km
    done: dict[str, float] = {}
    for d in days:
        if d <= today.isoformat():
            for sp, km in by_day.get(d, {}).items():
                done[sp] = done.get(sp, 0.0) + km
    over = (plan.get("km_goals") or {}).get(w["start"]) or {}
    out: dict[str, dict[str, Any]] = {}
    for sp in DIST_SPORTS:
        g = _num(over.get(sp))
        if not (goal.get(sp) or planned.get(sp) or g or (done.get(sp) and sp == "run")):
            continue
        out[sp] = {"done": round(done.get(sp, 0.0), 1), "goal": round(g if g else goal.get(sp, 0.0), 1),
                   "planned": round(planned.get(sp, 0.0), 1), "custom": g is not None}
    return out


def totals(plan: dict[str, Any], by_day: dict[str, dict[str, float]], today: date, thr: float,
           first: str, last: str) -> dict[str, dict[str, float]]:
    """{sport: {done, planned}} between two days (inclusive); done counts up to today."""
    out: dict[str, dict[str, float]] = {}
    for _, d, s in iter_sessions(plan):
        if first <= d <= last and not s.get("skipped"):
            for sp, km in session_km(s, thr).items():
                out.setdefault(sp, {"done": 0.0, "planned": 0.0})["planned"] += km
    for d, kms in by_day.items():
        if first <= d <= min(last, today.isoformat()):
            for sp, km in kms.items():
                if sp in out or sp == "run":
                    out.setdefault(sp, {"done": 0.0, "planned": 0.0})["done"] += km
    return {sp: {k: round(v, 1) for k, v in x.items()} for sp, x in out.items()}


# ---------------------------------------------------------- operations ---
def _day_sessions(plan: dict[str, Any], d: str) -> list[dict[str, Any]]:
    w = week_for(plan, date.fromisoformat(d))
    return [] if w is None else w["days"].get(d, [])


def _hard_day(plan: dict[str, Any], d: str, st: dict[str, dict[str, Any]], skip: str | None = None) -> bool:
    return any(is_hard(s) and s["id"] != skip and st.get(s["id"], {}).get("status") != "missed"
               for s in _day_sessions(plan, d))


def hard_pairs(plan: dict[str, Any], monday: date, st: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """Back-to-back hard days touching this Monday-Sunday week."""
    out = set()
    for i in range(-1, 7):
        a, b = (monday + timedelta(days=i)).isoformat(), (monday + timedelta(days=i + 1)).isoformat()
        if _hard_day(plan, a, st) and _hard_day(plan, b, st):
            out.add((a, b))
    return out


def _find(plan: dict[str, Any], sid: str) -> tuple[dict[str, Any], str, int]:
    for w in plan.get("weeks", []):
        for d, ss in w["days"].items():
            for i, s in enumerate(ss):
                if s.get("id") == sid:
                    return w, d, i
    raise PlanError("That session isn't in your plan anymore.")


def _orphan(plan: dict[str, Any], s: dict[str, Any]) -> None:
    ids = (s.pop("garmin", None) or {}).get("workout_ids") or []
    if ids:
        plan.setdefault("garmin_orphans", []).extend(ids)


def _take(plan: dict[str, Any], sid: str) -> tuple[dict[str, Any], str]:
    w, d, i = _find(plan, sid)
    s = w["days"][d].pop(i)
    if not w["days"][d]:
        w["days"][d] = [make_session("rest", "rest", 0)]
    return s, d


def _put(plan: dict[str, Any], d: str, s: dict[str, Any]) -> None:
    w = week_for(plan, date.fromisoformat(d))
    if w is None:
        raise PlanError("That day is outside your plan.")
    ss = [x for x in w["days"].get(d, []) if x["sport"] != "rest"]
    if len(ss) >= MAX_PER_DAY:
        raise PlanError(f"Up to {MAX_PER_DAY} sessions a day.")
    w["days"][d] = ss + [s]


def _check_target(plan: dict[str, Any], d: str, today: date) -> None:
    try:
        day = date.fromisoformat(d)
    except (TypeError, ValueError):
        raise PlanError("Pick a day.") from None
    if day < today:
        raise PlanError("Pick today or a later day.")
    if week_for(plan, day) is None or (plan.get("race_date") and d > plan["race_date"]):
        raise PlanError("That day is outside your plan.")
    if any(s.get("kind") == "race" for s in _day_sessions(plan, d)):
        raise PlanError("Race day stays as it is.")


def move(plan: dict[str, Any], sid: str, to: str, today: date, st: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Move one session (a missed one may move forward from the past). Returns (session, from)."""
    w, d, i = _find(plan, sid)
    s = w["days"][d][i]
    if s.get("kind") == "race":
        raise PlanError("Race day stays put. Change the race date in Events.")
    if s["sport"] == "rest":
        raise PlanError("Rest days don't move; move a session onto it instead.")
    status = st.get(sid, {}).get("status")
    if status == "done":
        raise PlanError("That one's already done.")
    if d < today.isoformat() and status not in ("missed", None):
        raise PlanError("Past sessions can't be moved.")
    if to == d:
        raise PlanError("It's already on that day.")
    _check_target(plan, to, today)
    s, frm = _take(plan, sid)
    _orphan(plan, s)
    s["edited"] = True
    s.setdefault("moved_from", frm)
    s.pop("skipped", None)
    _put(plan, to, s)
    return s, frm


def swap(plan: dict[str, Any], a: str, b: str, today: date, st: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Swap everything planned on two days (from today on). Returns the moved sessions."""
    if a == b:
        raise PlanError("Pick two different days.")
    for d in (a, b):
        _check_target(plan, d, today)
        if any(st.get(s["id"], {}).get("status") == "done" for s in _day_sessions(plan, d)):
            raise PlanError("A day with a finished session can't be swapped.")
    wa, wb = week_for(plan, date.fromisoformat(a)), week_for(plan, date.fromisoformat(b))
    assert wa is not None and wb is not None
    sa = [x for x in wa["days"].get(a, []) if x["sport"] != "rest"]
    sb = [x for x in wb["days"].get(b, []) if x["sport"] != "rest"]
    if not sa and not sb:
        raise PlanError("Both days are rest days.")
    for s in sa + sb:
        _orphan(plan, s)
        s["edited"] = True
    wa["days"][a] = sb or [make_session("rest", "rest", 0)]
    wb["days"][b] = sa or [make_session("rest", "rest", 0)]
    return sa + sb


def _available(athlete: dict[str, Any]) -> set[int]:
    days = [DAYS.index(d) for d in athlete.get("available_days") or [] if d in DAYS]
    if days and athlete.get("long_day") in DAYS:
        days.append(DAYS.index(athlete["long_day"]))
    return set(days) or set(range(7))


def _label(d: str) -> str:
    return WEEKDAY[date.fromisoformat(d).weekday()]


def _short(s: dict[str, Any]) -> str:
    t = str(s.get("title") or "session").strip()
    return t[0].lower() + t[1:] if len(t) > 1 and t[1:2].islower() else t


def _free_day(plan: dict[str, Any], monday: date, today: date, st: dict[str, dict[str, Any]],
              avail: set[int], near: str, skip: str | None = None, hard: bool = True,
              sport: str | None = None) -> str | None:
    """Nearest day this week from today on that can take a session (a hard one: no hard day on it
    or next to it, ``skip`` = the session being moved; an easy one (``sport``): no hard session
    that day, fewest sessions of that sport first, ``near`` itself allowed)."""
    options = []
    for i in range(7):
        d = monday + timedelta(days=i)
        k = d.isoformat()
        if d < today or i not in avail or (k == near and sport is None) or (plan.get("race_date") and k > plan["race_date"]):
            continue
        ss = [x for x in _day_sessions(plan, k) if x["sport"] != "rest" and x["id"] != skip]
        if len(ss) >= MAX_PER_DAY or any(x.get("kind") == "race" for x in ss):
            continue
        if hard and any(_hard_day(plan, (d + timedelta(days=o)).isoformat(), st, skip) for o in (-1, 0, 1)):
            continue
        if not hard and any(is_hard(x) for x in ss):
            continue
        nd = date.fromisoformat(near)
        same = sum(x["sport"] == sport for x in ss) if sport else 0
        options.append((same, abs((d - nd).days), d < nd, k))
    return min(options)[-1] if options else None


def _easy_kind(sport: str) -> str:
    kinds = KINDS_BY_SPORT.get(sport, ("easy",))
    return "easy" if "easy" in kinds else kinds[0]


def rebalance(plan: dict[str, Any], monday: date, today: date, *, athlete: dict[str, Any],
              st: dict[str, dict[str, Any]], thr: float, by_day: dict[str, dict[str, float]],
              before: set[tuple[str, str]], pinned: set[str], imperial: bool) -> list[str]:
    """Re-balance one Monday-Sunday week in place; returns what changed, in plain words."""
    lines: list[str] = []
    w = week_for(plan, monday)
    if w is None:
        return lines
    avail = _available(athlete)
    swim_pace = plan.get("swim_pace", 125.0)
    t = today.isoformat()

    # 1. New back-to-back hard days.
    for _ in range(8):
        new = sorted(hard_pairs(plan, monday, st) - before)
        if not new:
            break
        a, b = new[0]
        cands = [(s, d) for d in (b, a) for s in _day_sessions(plan, d)
                 if is_hard(s) and s["id"] not in pinned and s.get("kind") != "race" and d >= t
                 and monday.isoformat() <= d <= (monday + timedelta(days=6)).isoformat()
                 and st.get(s["id"], {}).get("status") not in ("done", "missed")]
        cands.sort(key=lambda x: x[0].get("kind") in ("long", "brick"))
        if not cands:
            before.add((a, b))  # nothing Rabbit may touch: leave it
            continue
        s, d = cands[0]
        target = _free_day(plan, monday, today, st, avail, d, skip=s["id"])
        if target:
            moved, _ = _take(plan, s["id"])
            _orphan(plan, moved)
            moved["edited"] = moved["rebalanced"] = True
            moved["adjust_why"] = f"Moved here from {_label(d)} to keep hard days apart."
            _put(plan, target, moved)
            lines.append(f"{_label(d)} {_short(s)} moved to {_label(target)}")
        elif s.get("kind") in QUALITY:
            _, dd, i = _find(plan, s["id"])
            _freeze(s, thr)
            eased = _rebuilt(s, swim_pace, w["phase"], kind=_easy_kind(s["sport"]),
                             minutes=min(int(s.get("minutes") or 45), 45))
            eased["edited"] = eased["rebalanced"] = True
            eased["adjust_why"] = "Made easy: there was no room for another hard day this week."
            w["days"][dd][i] = eased
            lines.append(f"{_label(d)} {_short(s)} is now an easy {_word(s)} (no room for another hard day)")
        else:
            before.add((a, b))

    # 2. Mileage on goal (run and bike; swims are short and stay as planned).
    mil = week_mileage(plan, w, by_day, today, thr)
    for sport in ("run", "bike"):
        m = mil.get(sport)
        if not m or not m["goal"]:
            continue
        have = 0.0
        for i in range(7):
            k = (monday + timedelta(days=i)).isoformat()
            if k < t:
                have += by_day.get(k, {}).get(sport, 0.0)
            elif k == t and by_day.get(k, {}).get(sport):
                have += by_day[k][sport]
            else:
                have += sum(session_km(s, thr).get(sport, 0.0) for s in _day_sessions(plan, k)
                            if not s.get("skipped") and st.get(s["id"], {}).get("status") != "done")
        gap = m["goal"] - have
        cands = [(k, s) for i in range(7) for k in [(monday + timedelta(days=i)).isoformat()] if k > t
                 for s in _day_sessions(plan, k)
                 if s["sport"] == sport and s.get("kind") in EASYISH and not s.get("skipped") and s.get("minutes")]
        if not cands:
            continue
        rate = {s["id"]: (session_km(s, thr).get(sport, 0.0) / s["minutes"]) for _, s in cands}
        add: dict[str, int] = {s["id"]: 0 for _, s in cands}
        base = {s["id"]: int(s.get("base_minutes") or s["minutes"]) for _, s in cands}
        cur = {s["id"]: int(s["minutes"]) for _, s in cands}
        if gap > 0.4:
            while gap > 0.25:
                ok = [sid for sid in add if cur[sid] + add[sid] + STEP_MIN <= base[sid] * (1 + MAX_BUMP) + 0.01]
                if not ok:
                    break
                sid = min(ok, key=lambda x: ((cur[x] + add[x]) / base[x], x))
                add[sid] += STEP_MIN
                gap -= rate[sid] * STEP_MIN
        elif gap < -0.4:
            while True:  # a surplus takes earlier bumps back first
                ok = [sid for sid in add if cur[sid] + add[sid] - STEP_MIN >= base[sid]
                      and rate[sid] * STEP_MIN <= -gap + 0.25]
                if not ok:
                    break
                sid = max(ok, key=lambda x: ((cur[x] + add[x]) / base[x], x))
                add[sid] -= STEP_MIN
                gap += rate[sid] * STEP_MIN
        bumped: dict[tuple[str, str], tuple[float, int]] = {}
        for k, s in cands:
            n = add[s["id"]]
            if not n:
                continue
            _, dd, i = _find(plan, s["id"])
            _freeze(s, thr)
            upd = _rebuilt(s, swim_pace, w["phase"], minutes=cur[s["id"]] + n)
            if _num(s.get("km")):
                upd["km"] = round(float(s["km"]) * (cur[s["id"]] + n) / cur[s["id"]], 2)
            upd["edited"] = upd["rebalanced"] = True
            upd["adjust_why"] = "A little longer to keep this week's miles on goal."
            w["days"][dd][i] = upd
            key = (k, _short(s))
            km0, n0 = bumped.get(key, (0.0, 0))
            bumped[key] = (km0 + rate[s["id"]] * n, n0 + n)
        for (k, title), (km, n) in sorted(bumped.items()):
            lines.append(f"{_label(k)} {title} {'+' if n > 0 else '−'}{fmt_km(abs(km), imperial)}")
    recompute_week(w)
    return lines


def _rebuilt(s: dict[str, Any], swim_pace: float, phase: str, **changes: Any) -> dict[str, Any]:
    """``s`` with new steps/minutes/detail for ``changes``; every other field (ids from other
    calendars such as TrainingPeaks, notes, base_km, ...) is kept."""
    src = dict(s, **changes)
    src.pop("legs", None)
    fresh = rebuild_session(src, swim_pace=swim_pace, phase=phase)
    out = dict(s, **changes)
    out.pop("legs", None)
    out.update(fresh)
    return out


def _fix_easy(plan: dict[str, Any], sid: str, to: str | None, today: date, st: dict[str, dict[str, Any]],
              athlete: dict[str, Any]) -> tuple[dict[str, Any], str]:
    w, d, i = _find(plan, sid)
    s = w["days"][d][i]
    monday = today - timedelta(days=today.weekday())
    if to:
        _check_target(plan, to, today)
    else:
        sp = s["sport"] if s["sport"] in ("run", "bike", "swim") else "run"
        to = _free_day(plan, monday, today, st, _available(athlete), today.isoformat(), hard=False, sport=sp) \
            or _free_day(plan, monday, today, st, set(range(7)), today.isoformat(), hard=False, sport=sp)
        if to is None:
            raise PlanError("No free day left this week. Skip it instead; Rabbit spreads the miles.")
    sport = s["sport"] if s["sport"] in ("run", "bike", "swim") else "run"
    tw = week_for(plan, date.fromisoformat(to))
    new = make_session(sport, _easy_kind(sport), min(int(s.get("minutes") or 40), 40),
                       swim_pace=plan.get("swim_pace", 125.0), phase=(tw or w)["phase"])
    new.update(edited=True, made_up_for=sid, base_km={})
    s["skipped"], s["fixed"] = True, "easy"
    _put(plan, to, new)
    return new, to


# ---------------------------------------------------------------- undo ---
def _snapshot(plan: dict[str, Any], weeks: set[str]) -> dict[str, Any]:
    return {w["start"]: copy.deepcopy(w["days"]) for w in plan.get("weeks", []) if w["start"] in weeks}


def restore(plan: dict[str, Any], snap: dict[str, Any]) -> None:
    orphans = set(plan.get("garmin_orphans", []))
    for w in plan.get("weeks", []):
        if w["start"] not in snap:
            continue
        old_ids = {wid for ss in snap[w["start"]].values() for s in ss
                   for wid in (s.get("garmin") or {}).get("workout_ids", [])}
        for ss in w["days"].values():
            for s in ss:
                for wid in (s.get("garmin") or {}).get("workout_ids", []):
                    if wid not in old_ids:
                        plan.setdefault("garmin_orphans", []).append(wid)
        days = copy.deepcopy(snap[w["start"]])
        for ss in days.values():
            for s in ss:
                if any(wid in orphans for wid in (s.get("garmin") or {}).get("workout_ids", [])):
                    s.pop("garmin", None)  # already queued for removal: it syncs again
        w["days"] = days
        recompute_week(w)


# ------------------------------------------------------------- service ---
class PlanCal:
    """Inputs + writes for the calendar. ``activities(uid) -> (today, compact activities)``."""

    def __init__(self, plans: "PlanService", coach: Any, *, activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                 now: Callable[[str], datetime], moments: Moments | None = None) -> None:
        self._plans, self._coach, self._acts, self._now, self._moments = plans, coach, activities, now, moments

    def _ctx(self, uid: str) -> tuple[date, list[dict[str, Any]], dict[str, Any], float, str, bool]:
        try:
            today, acts = self._acts(uid)
        except Exception:  # Garmin down or not connected: the calendar still works
            today, acts = self._plans.today(uid), []
        athlete = self._coach.athlete(uid) or {}
        thr, src = threshold_pace(athlete, acts)
        return today, acts, athlete, thr, src, athlete.get("units") == "imperial"

    def view(self, uid: str) -> dict[str, Any] | None:
        plan = self._plans.get(uid)
        if plan is None:
            return None
        today, acts, athlete, thr, src, imperial = self._ctx(uid)
        return calendar_view(plan, acts, today, athlete=athlete, thr=thr, pace_source=src, imperial=imperial)

    def week_miles(self, uid: str) -> dict[str, Any] | None:
        """This week's mileage for the home ring (run first; None without a plan or miles)."""
        plan = self._plans.get(uid)
        if plan is None:
            return None
        today, acts, _, thr, _, imperial = self._ctx(uid)
        w = week_for(plan, today)
        if w is None:
            return None
        mil = week_mileage(plan, w, acts_km_by_day(acts), today, thr)
        if not any(m["goal"] for m in mil.values()):
            return None
        return {"week_start": w["start"], "imperial": imperial, "sports": mil,
                "primary": "run" if mil.get("run", {}).get("goal") else max(mil, key=lambda k: mil[k]["goal"])}

    # ---------------------------------------------------------------- ops --
    def op(self, uid: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        today, acts, athlete, thr, src, imperial = self._ctx(uid)
        by_day = acts_km_by_day(acts)
        result: dict[str, Any] = {}

        def fn(plan: dict[str, Any], _today: date) -> None:
            st = statuses(plan, acts, today)
            uid_ = "u" + secrets.token_hex(4)
            pinned: set[str] = set()
            touched: set[str] = set()
            summary = ""

            def wk(d: str) -> str:
                try:
                    w = week_for(plan, date.fromisoformat(d))
                except (TypeError, ValueError):
                    raise PlanError("Pick a day.") from None
                if w is None:
                    raise PlanError("That day is outside your plan.")
                return w["start"]

            if kind == "undo":
                entries = plan.get("cal_undo") or []
                want = str(body.get("id") or "")
                hit = next((e for e in entries if want in (e["id"], e["id"] + "r")), None)
                if hit is None or (want.endswith("r") and hit.get("rebalance") is None):
                    raise PlanError("Nothing to undo.")
                restore(plan, hit["rebalance"] if want.endswith("r") else hit["before"])
                at = entries.index(hit)
                # Undoing everything also drops newer steps (their snapshots assumed this one).
                plan["cal_undo"] = entries[:at] if not want.endswith("r") else \
                    entries[:at] + [dict(hit, rebalance=None)]
                result.update(change={"id": None, "summary": "Undone", "rebalanced": []})
                return
            if kind == "goal":
                week, sport = str(body.get("week") or ""), body.get("sport") or "run"
                if sport not in DIST_SPORTS or not any(w["start"] == week for w in plan.get("weeks", [])):
                    raise PlanError("Pick a week of your plan.")
                km = body.get("km")
                goals = plan.setdefault("km_goals", {})
                if km is None:
                    goals.get(week, {}).pop(sport, None)
                else:
                    v = _num(km)
                    if v is None or not 0 < v <= 500:
                        raise PlanError("Weekly goal must be between 0 and 500 km.")
                    goals.setdefault(week, {})[sport] = round(v, 2)
                plan["km_goals"] = {k: v for k, v in goals.items() if v}
                result.update(change=None)
                return

            if kind == "move":
                sid, to = str(body.get("session_id") or ""), str(body.get("date") or "")
                _, frm, _ = _find(plan, sid)
                touched = {wk(frm), wk(to)}
            elif kind == "swap":
                a, b = str(body.get("a") or ""), str(body.get("b") or "")
                touched = {wk(a), wk(b)}
            elif kind == "fix":
                sid = str(body.get("session_id") or "")
                _, frm, _ = _find(plan, sid)
                if st.get(sid, {}).get("status") != "missed":
                    raise PlanError("That session isn't missed.")
                touched = {wk(frm), wk(today.isoformat()) if week_for(plan, today) else wk(frm)}
                if body.get("date"):
                    touched.add(wk(str(body["date"])))
            else:
                raise PlanError("Unknown change.")
            before_snap = _snapshot(plan, touched)
            pairs = {w: hard_pairs(plan, date.fromisoformat(w), st) for w in touched}

            if kind == "move":
                s, frm = move(plan, sid, to, today, st)
                pinned.add(s["id"])
                summary = f"Moved {_short(s)} to {_label(to)}"
            elif kind == "swap":
                moved = swap(plan, a, b, today, st)
                pinned |= {s["id"] for s in moved}
                summary = f"Swapped {_label(a)} and {_label(b)}"
            else:
                how = body.get("how")
                if how == "move":
                    s, _ = move(plan, sid, str(body.get("date") or ""), today, st)
                    pinned.add(s["id"])
                    summary = f"Moved {_short(s)} to {_label(str(body['date']))}"
                elif how == "easy":
                    new, to2 = _fix_easy(plan, sid, str(body["date"]) if body.get("date") else None, today, st, athlete)
                    touched.add(wk(to2))
                    pinned.add(new["id"])
                    summary = f"Easy {_word(new)} added on {_label(to2)}"
                elif how == "skip":
                    w0, d0, i0 = _find(plan, sid)
                    w0["days"][d0][i0]["skipped"] = True
                    w0["days"][d0][i0]["fixed"] = "skip"
                    summary = f"Skipped {_short(w0['days'][d0][i0])}"
                else:
                    raise PlanError("Pick move, easy or skip.")
            for w in plan.get("weeks", []):
                if w["start"] in touched:
                    recompute_week(w)
            mid_snap = _snapshot(plan, touched)
            st2 = statuses(plan, acts, today)
            lines: list[str] = []
            for ws in sorted(touched):
                if (date.fromisoformat(ws) + timedelta(days=6)) < today:
                    continue
                lines += rebalance(plan, date.fromisoformat(ws), today, athlete=athlete, st=st2, thr=thr,
                                   by_day=by_day, before=pairs.get(ws, set()), pinned=pinned, imperial=imperial)
            entry = {"id": uid_, "at": int(self._now(uid).timestamp()), "before": before_snap,
                     "rebalance": mid_snap if lines else None}
            plan["cal_undo"] = ((plan.get("cal_undo") or []) + [entry])[-UNDO_KEEP:]
            result.update(change={"id": uid_, "summary": summary, "rebalanced": lines,
                                  "rebalance_undo": uid_ + "r" if lines else None})

        plan = self._plans._edit(uid, fn)
        result["cal"] = calendar_view(plan, acts, today, athlete=athlete, thr=thr, pace_source=src, imperial=imperial)
        result["plan"] = plan
        return result

    # ------------------------------------------------------------- moment --
    def check_missed(self, uid: str) -> str:
        """From ``Moments.on_tick``: the morning after a missed session, offer the fix once."""
        if uid.startswith("coach_") or self._moments is None:
            return "skipped"
        local = self._now(uid)
        if not (MISSED_FROM <= local.time() < MISSED_UNTIL) or Moments.quiet(local):
            return "not_now"
        prof = self._moments._profile(uid)
        if prof.get("moments_push") is False or prof.get("plan_missed_moments") is False:
            return "off"
        plan = self._plans.get(uid)
        if plan is None:
            return "no_plan"
        if not self._moments._claim(uid, "planmissed", local.date()):
            return "claimed"
        today, acts, _, thr, _, imperial = self._ctx(uid)
        m = missed_moment(plan, acts, today, thr=thr, imperial=imperial)
        return self._moments.post(uid, m) if m else "none"


def missed_moment(plan: dict[str, Any], acts: list[dict[str, Any]], today: date, *, thr: float,
                  imperial: bool) -> dict[str, Any] | None:
    """Pure: yesterday's first missed session -> a ``plan_missed`` moment with a fix action."""
    y = (today - timedelta(days=1)).isoformat()
    st = statuses(plan, acts, today)
    for s in _day_sessions(plan, y):
        if st.get(s["id"], {}).get("status") != "missed" or s.get("kind") == "race":
            continue
        km = session_km(s, thr)
        dist = f" ({fmt_km(sum(km.values()), imperial)})" if km else f" ({int(s.get('minutes') or 0)} min)"
        text = f"🗓️ Yesterday's {_short(s)}{dist} didn't happen. {missed_why(s, km, imperial)} Want to fit it in?"
        return {"type": "plan_missed", "key": f"planmissed:{s['id']}", "text": text[:140],
                "actions": [action("plan_fix", "Fix my week", session_id=s["id"]), action("plan", "Open plan")]}
    return None


def adjusted_line(plan: dict[str, Any], s: dict[str, Any]) -> str | None:
    """Why Rabbit changed this session, in a sentence (None if it didn't)."""
    if s.get("made_up_for"):
        try:
            w, d, i = _find(plan, s["made_up_for"])
            orig: dict[str, Any] | None = w["days"][d][i]
        except PlanError:
            d, orig = None, None
        what = (orig or {}).get("title") or "a session"
        return f"Added to make up for {what} you missed" + (f" on {_label(d)}." if d else ".")
    if s.get("rebalanced"):
        return s.get("adjust_why") or "Rabbit adjusted this after a change to your week."
    return None


def calendar_view(plan: dict[str, Any], acts: list[dict[str, Any]], today: date, *, athlete: dict[str, Any],
                  thr: float, pace_source: str, imperial: bool) -> dict[str, Any]:
    st = statuses(plan, acts, today)
    full = {a.get("activity_id"): a for a in acts or [] if a.get("activity_id") is not None}
    by_day = acts_km_by_day(acts)
    avail = _available(athlete)
    monday = today - timedelta(days=today.weekday())
    sessions: dict[str, Any] = {}
    for w, d, s in iter_sessions(plan):
        if s["sport"] == "rest":
            continue
        km = session_km(s, thr)
        status = st.get(s["id"], {}).get("status", "planned")
        item: dict[str, Any] = {"status": status, "km": km, "pace": target_pace(s, thr),
                                "note": note_for(s, plan, thr, imperial),
                                "rebalanced": bool(s.get("rebalanced")), "moved_from": s.get("moved_from"),
                                "made_up_for": s.get("made_up_for"), "hard": is_hard(s)}
        tg = session_targets(s, athlete, thr, plan.get("swim_pace"))
        if tg:
            item["targets"] = tg
        why = adjusted_line(plan, s)
        if why:
            item["adjusted"] = why
        act = st.get(s["id"], {}).get("activity")
        if act:
            item["activity"] = {"id": act.get("id"), "km": act.get("distance_km"), "minutes": act.get("minutes")}
            went = how_it_went(s, tg, full.get(act.get("id")) or {"duration": (act.get("minutes") or 0) * 60,
                                                                   "distance_km": act.get("distance_km")})
            if went:
                item["went"] = went
        if status == "missed":
            best = (_free_day(plan, monday, today, st, avail, today.isoformat(), skip=s["id"]) if is_hard(s) else
                    _free_day(plan, monday, today, st, avail, today.isoformat(), hard=False, sport=s["sport"])) \
                if week_for(plan, today) and monday.isoformat() <= d else None
            item["missed"] = {"why": missed_why(s, km, imperial), "best_day": best,
                              "this_week": monday.isoformat() <= d}
        sessions[s["id"]] = item
    weeks = {w["start"]: week_mileage(plan, w, by_day, today, thr) for w in plan.get("weeks", [])}
    months: dict[str, Any] = {}
    for w in plan.get("weeks", []):
        for i in range(7):
            k = (date.fromisoformat(w["start"]) + timedelta(days=i)).strftime("%Y-%m")
            if k not in months:
                y, m = int(k[:4]), int(k[5:])
                last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
                months[k] = totals(plan, by_day, today, thr, f"{k}-01", last)
    first = plan.get("first_day") or plan.get("start") or today.isoformat()
    return {"today": today.isoformat(), "imperial": imperial, "threshold_pace": thr, "pace_source": pace_source,
            "available_days": sorted(avail), "sessions": sessions, "weeks": weeks, "months": months,
            "total": totals(plan, by_day, today, thr, first, plan.get("race_date") or "9999-12-31")}


__all__ = ["PlanCal", "calendar_view", "rebalance", "move", "swap", "statuses", "session_km", "note_for",
           "week_mileage", "missed_moment", "threshold_pace", "restore"]
