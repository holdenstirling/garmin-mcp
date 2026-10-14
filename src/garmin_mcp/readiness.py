"""Race readiness: one grade per race, with what would most raise it.

Deterministic and explainable (no model). For one event it reads the athlete profile, the
built plan (may be None: chat-only plans), a year of Garmin activities, the load model
(``load.compute``: current fitness and the plan's forecast), recent check-ins (pain flags,
rough days) and the race-fit factors (``racefit.analyze``). It never reads Oura, and the
result is not put into the model's context.

Components, each 0-100 with a one-line detail and a "why it matters" tip:

==================  ======  =====================================================================
fitness             30%     projected fitness (CTL) on race day vs the target for the distance
                            (plan forecast when the race is inside the built plan, else current
                            CTL + an assumed ``ASSUMED_RAMP`` per week, capped at the target).
                            Races > 26 weeks out are graded against where fitness should be *now*.
key_session         25%     longest session in the race's sport(s), last 6 weeks, vs where it
                            should be at this point (``LONG`` targets ramped by weeks to go).
                            Weighted 10% when the race is > 16 weeks out (the rest to fitness
                            and consistency). 100-mile races also want back-to-back long days.
consistency         20%     active weeks (3+ sessions or 3+ h) in the last 8; averaged with plan
                            adherence when a built plan has 4+ sessions due.
race_factors        15%     racefit risks (-25) and watches (-10), halved while 6+ weeks remain
                            to prepare; helps +5.
health              10%     pain flags and rough check-ins in 14 days; deep fatigue (form < -20).
==================  ======  =====================================================================

Target race-day fitness (``TARGET_CTL``, same TSS-like scale as ``load.py``; a daily
1-hour easy run settles near 55): 5k 30, 10k 35, half 45, marathon 55, ultra 60/68/75 by
length (100-mile 75), sprint tri 35, olympic 45, 70.3 60, 140.6 80, century 50. Multiplied by
priority (A 1, B 0.9, C 0.8), level (new 0.85, advanced 1.15) and goal (time 1.05, compete 1.1).

Grade: A >= 90, A- 85, B+ 80, B 75, B- 70, C+ 65, C 58, D 50, F below. Status: ``at_risk``
on a pain flag in 14 days or when the target can't be reached at a safe ramp (> 7 CTL a week),
else ``ahead`` (>= 88), ``on_track`` (>= 70), ``behind``. Confidence is ``low`` with under 3
weeks of Garmin history or a race more than 9 months away.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from . import racefit
from .load import compute as load_compute
from .planbuilder import RACES
from .stats import _rows, adherence

CACHE_S = 600
LOOKBACK_DAYS = 42
SAFE_RAMP, MAX_RAMP = 5.0, 7.0   # CTL per week
ASSUMED_RAMP = 2.0               # CTL per week assumed without a plan forecast
FAR_WEEKS, KEY_LIGHT_WEEKS, LOW_CONF_WEEKS = 26, 16, 39
MIN_HISTORY_DAYS = 21

TARGET_CTL = {"5k": 30, "10k": 35, "half marathon": 45, "marathon": 55, "ultra": 68, "ultra50k": 60,
              "ultra100": 75, "sprint triathlon": 35, "olympic triathlon": 45, "70.3": 60, "140.6": 80,
              "century ride": 50, "cycling": 45, "swimming": 30, "mountaineering": 50, "other": 40}
# Peak long session per sport: (minutes, km or None). Reached 2 weeks before the taper.
LONG: dict[str, dict[str, tuple[int, float | None]]] = {
    "5k": {"run": (60, None)}, "10k": {"run": (75, None)},
    "half marathon": {"run": (105, 18)}, "marathon": {"run": (165, 32)},
    "ultra50k": {"run": (210, None)}, "ultra": {"run": (300, None)}, "ultra100": {"run": (420, None)},
    "sprint triathlon": {"bike": (60, None), "run": (45, None), "swim": (30, None)},
    "olympic triathlon": {"bike": (120, None), "run": (70, None), "swim": (45, None)},
    "70.3": {"bike": (180, None), "run": (90, None), "swim": (60, None)},
    "140.6": {"bike": (330, None), "run": (150, None), "swim": (75, None)},
    "century ride": {"bike": (300, None)}, "cycling": {"bike": (180, None)},
    "swimming": {"swim": (60, None)}, "mountaineering": {"run": (300, None)}, "other": {"run": (90, None)},
}
SPORT_WEIGHT = {"bike": 0.45, "run": 0.35, "swim": 0.2}
TAPER = {"ultra50k": 2, "ultra100": 3, "cycling": 1, "swimming": 1, "mountaineering": 2}
PRIORITY = {"A": 1.0, "B": 0.9, "C": 0.8}
LEVEL = {"new": 0.85, "intermediate": 1.0, "advanced": 1.15}
GOAL = {"compete": 1.1, "time": 1.05}
WEIGHTS = {"fitness": 30, "key_session": 25, "consistency": 20, "race_factors": 15, "health": 10}
GRADES = ((90, "A"), (85, "A-"), (80, "B+"), (75, "B"), (70, "B-"), (65, "C+"), (58, "C"), (50, "D"), (0, "F"))
LABELS = {"fitness": "Fitness trajectory", "key_session": "Key sessions", "consistency": "Consistency",
          "race_factors": "Course & conditions", "health": "Health & recovery"}
WHY = {
    "fitness": "Fitness is your last 6 weeks of training load. It's what carries you through race day, "
               "and it can only rise about 5-7 points a week without raising injury risk.",
    "key_session": "Your longest sessions teach your legs, gut and head to last the distance. They matter "
                   "most in the last 2-3 months.",
    "consistency": "Fitness comes from stacking ordinary weeks. Steady weeks beat occasional big ones.",
    "race_factors": "Altitude, heat, hills and open water can cost more than fitness on the day, and most "
                    "are fixable with specific prep if you start early enough.",
    "health": "Pain and deep fatigue are the most common reasons athletes miss the start line.",
}
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


# ----------------------------------------------------------------- helpers --
def _curve(ratio: float) -> float:
    """Ratio of achieved to needed -> 0-100 (generous near 1, steep below 0.75)."""
    pts = ((0.0, 0.0), (0.5, 35.0), (0.75, 65.0), (0.9, 85.0), (1.0, 100.0))
    if ratio >= 1:
        return 100.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if ratio <= x1:
            return y0 + (y1 - y0) * (max(ratio, 0.0) - x0) / (x1 - x0)
    return 100.0


def _dur(minutes: float) -> str:
    t = int(round(minutes))
    if t < 60:
        return f"{t} min"
    h, m = divmod(t, 60)
    return f"{h}h {m:02d}m" if m else f"{h}h"


def _dist(km: float, imperial: bool) -> str:
    return f"{km / 1.609344:.0f} mi" if imperial else f"{km:.0f} km"


def grade_for(score: float) -> str:
    return next(g for cut, g in GRADES if score >= cut)


def race_key(event: dict[str, Any]) -> str:
    """The profile key for targets: the distance, refined for ultras and typeless events."""
    dist = (event.get("distance") or "").lower()
    etype = event.get("type") or "other"
    km = racefit._distance_km(dict(event, distance="" if dist in racefit.KM else dist))  # stated, not default
    name = str(event.get("name") or "")
    m = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*(k|km|mi|miles?|milers?)\b", name, re.I)
    if not km and m:
        km = float(m.group(1)) * (1.609344 if m.group(2).lower().startswith("mi") else 1)
    elif not km and etype == "trail" and re.search(r"\b(100|200)\b", name):
        km = 161.0 * (2 if re.search(r"\b200\b", name) else 1)
    km = km or racefit.KM.get(dist)
    known = dist in TARGET_CTL and dist not in ("other", "cycling", "swimming", "mountaineering")
    if dist == "ultra" or (not known and etype in ("trail", "running") and km and km > 43):
        km = km if km and km > 43 else 80
        return "ultra50k" if km < 60 else "ultra" if km < 120 else "ultra100"
    if known:
        return dist
    if etype in ("running", "trail") and km:
        return "5k" if km <= 6 else "10k" if km <= 12 else "half marathon" if km <= 25 else "marathon"
    if etype == "triathlon":
        return "olympic triathlon"
    if etype == "cycling":
        return "century ride" if km and km >= 140 else "cycling"
    return etype if etype in ("swimming", "mountaineering") else "other"


def target_fitness(event: dict[str, Any], athlete: dict[str, Any]) -> int:
    key = race_key(event)
    mult = PRIORITY.get(event.get("priority") or "B", 0.9) * LEVEL.get(athlete.get("level") or "", 1.0) \
        * GOAL.get(event.get("goal_type") or "", 1.0)
    return round(TARGET_CTL[key] * mult)


def _taper(key: str) -> int:
    return TAPER.get(key) or RACES.get(key, {}).get("taper", 1)


def _sports(event: dict[str, Any], key: str) -> dict[str, tuple[int, float | None]]:
    return LONG.get(key) or LONG["other"]


def _counts(sport: str, etype: str) -> set[str]:
    """Activity categories that count as the race sport's long session."""
    if sport == "run" and etype in ("trail", "mountaineering"):
        return {"run", "hike"}
    return {sport}


# --------------------------------------------------------------- component --
def _c(id_: str, score: float, detail: str) -> dict[str, Any]:
    return {"id": id_, "label": LABELS[id_], "score": int(round(max(0.0, min(100.0, score)))),
            "weight": WEIGHTS[id_], "detail": detail, "tip": WHY[id_]}


def compute(event: dict[str, Any], athlete: dict[str, Any] | None, *, today: date,
            acts: list[dict[str, Any]], plan: dict[str, Any] | None = None,
            load: dict[str, Any] | None = None, checkins: list[dict[str, Any]] | None = None,
            fit: dict[str, Any] | None = None, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    a = athlete or {}
    imperial = a.get("units") == "imperial"
    race_day = date.fromisoformat(event["date"])
    days = (race_day - today).days
    weeks = max(0, days // 7)
    key = race_key(event)
    etype = event.get("type") or "other"
    taper = _taper(key)
    build_weeks = max(1, weeks - taper)
    target = target_fitness(event, a)
    rows = [r for r in _rows(acts) if r["date"] <= today]
    first = min((r["date"] for r in rows), default=None)
    history = (today - first).days if first else 0
    if load is None:
        load = load_compute(acts, today, threshold_hr=a.get("threshold_hr"), plan=plan)
    if fit is None:
        fit = racefit.analyze(event, a)
    now = load.get("now") or {}
    cur = float(now.get("ctl") or 0.0)
    tsb = now.get("tsb")
    actions: list[tuple[float, str]] = []
    comps: dict[str, dict[str, Any]] = {}

    # ---- 1. fitness trajectory
    point = next((p for p in load.get("series") or [] if p["date"] == event["date"]), None) if plan else None
    forecast = point is not None and point.get("planned")
    projected = float(point["ctl"]) if forecast else min(cur + ASSUMED_RAMP * build_weeks, max(cur, float(target)))
    required = (target - cur) / build_weeks
    far = weeks > FAR_WEEKS
    if far:
        expected_now = max(0.45 * target, target - 2.5 * build_weeks)
        f_ratio = cur / expected_now if expected_now else 1.0
        detail = f"Fitness {cur:.0f} now; about {expected_now:.0f} is on track at this point (race day needs ~{target})."
    else:
        f_ratio = projected / target if target else 1.0
        how = "your plan projects" if forecast else "at a steady build you'd reach about"
        detail = f"Fitness {cur:.0f} now; {how} {projected:.0f} on race day vs ~{target} needed."
        if required > MAX_RAMP:
            detail += f" Closing the gap needs +{required:.0f} a week, more than is safe."
        elif required > SAFE_RAMP and not forecast:
            detail += f" That needs +{required:.0f} a week: doable, but steep."
    unreachable = (not far and history >= MIN_HISTORY_DAYS and required > MAX_RAMP and projected < 0.85 * target)
    comps["fitness"] = _c("fitness", _curve(f_ratio), detail)
    if f_ratio < 0.97:
        if plan and forecast:
            act = "Stick with your plan's long and steady weeks: they're what lifts your fitness"
        elif plan:
            act = "Rebuild your plan around this race so Rabbit can ramp your training safely"
        else:
            hours = max(3, round(target * 7 / 50))
            act = f"Work up to about {hours} h a week of mostly easy training"
        actions.append(((100 - comps["fitness"]["score"]) * WEIGHTS["fitness"], act))

    # ---- 2. key sessions
    since = today - timedelta(days=LOOKBACK_DAYS)
    recent = [r for r in rows if r["date"] >= since]
    sports = _sports(event, key)
    prio = PRIORITY.get(event.get("priority") or "B", 0.9)
    stage = max(0.4, min(1.0, 1 - 0.04 * (weeks - (taper + 2))))
    parts, bits, worst = [], [], None
    for sport, (mins, km) in sports.items():
        cats = _counts(sport, etype)
        rs = [r for r in recent if r["sport"] in cats]
        best = max(rs, key=lambda r: r["min"], default=None)
        best_min = best["min"] if best else 0.0
        best_km = max((r["km"] for r in rs), default=0.0)
        need_min = mins * prio * stage
        ratio = best_min / need_min if need_min else 1.0
        if km:
            ratio = max(ratio, best_km / (km * prio * stage))
        s = _curve(ratio)
        parts.append((SPORT_WEIGHT.get(sport, 1.0) if len(sports) > 1 else 1.0, s))
        word = SPORT_WORD.get(sport, sport)
        have = (_dur(best_min) + (f" ({_dist(best_km, imperial)})" if km and best_km else "")) if best else "none"
        want = _dur(need_min) + (f" / {_dist(km * prio * stage, imperial)}" if km else "")
        bits.append(f"longest {word} {have} (aim ~{want} by now)")
        if worst is None or s < worst[0]:
            worst = (s, sport, mins * prio, km)
    k_score = sum(w * s for w, s in parts) / sum(w for w, _ in parts)
    detail = "Last 6 weeks: " + "; ".join(bits) + "."
    if key == "ultra100" and weeks <= KEY_LIGHT_WEEKS:
        days_long = {r["date"] for r in recent if r["sport"] in ("run", "hike") and r["min"] >= 120}
        b2b = any(d + timedelta(days=1) in days_long for d in days_long)
        k_score = 0.8 * k_score + (20 if b2b else 0)
        detail += " Back-to-back long days: " + ("yes." if b2b else "not yet.")
        if not b2b:
            actions.append((60 * WEIGHTS["key_session"], "Add back-to-back long days on weekends "
                            "(e.g. 5 h Saturday, 2-3 h Sunday)"))
    comps["key_session"] = _c("key_session", k_score, detail)
    if worst and worst[0] < 90:
        peak_by = race_day - timedelta(weeks=taper + 3)
        when = "over the next few weeks" if peak_by <= today + timedelta(days=21) else f"by {MONTHS[peak_by.month - 1]}"
        word = SPORT_WORD.get(worst[1], worst[1])
        goal = _dur(worst[2]) + (f" ({_dist(worst[3] * prio, imperial)})" if worst[3] else "")
        actions.append(((100 - worst[0]) * WEIGHTS["key_session"], f"Build your weekly long {word} toward {goal} {when}"))

    # ---- 3. consistency
    span = min(8, max(1, history // 7)) if first else 8
    active = 0
    for i in range(span):
        end = today - timedelta(days=7 * i)
        rs = [r for r in rows if end - timedelta(days=6) <= r["date"] <= end]
        active += int(len(rs) >= 3 or sum(r["min"] for r in rs) >= 180)
    c_score = 100 * active / span
    detail = f"{active} of the last {span} weeks had 3+ sessions or 3+ hours."
    adh = adherence(plan, acts, today) if plan else None
    pct = ((adh or {}).get("to_date") or {}).get("pct")
    if pct is not None and ((adh or {}).get("to_date") or {}).get("planned", 0) >= 4:
        c_score = 0.5 * c_score + 0.5 * pct
        detail += f" Plan sessions done: {pct}%."
    comps["consistency"] = _c("consistency", c_score, detail)
    if comps["consistency"]["score"] < 80:
        act = (f"Get back to your planned sessions ({pct}% done so far)" if pct is not None and pct < 75
               else "Train at least 3 times every week, even short sessions")
        actions.append(((100 - comps["consistency"]["score"]) * WEIGHTS["consistency"], act))

    # ---- 4. race-specific factors
    time_left = weeks >= 6
    r_score = 100.0
    worst_f = None
    for f in fit.get("factors") or []:
        if f["impact"] == "risk":
            r_score -= 12 if time_left else 25
        elif f["impact"] == "watch":
            r_score -= 5 if time_left else 10
        elif f["impact"] == "helps":
            r_score += 5
        if f["impact"] in ("risk", "watch") and (worst_f is None or racefit.ORDER[f["impact"]] < racefit.ORDER[worst_f["impact"]]):
            worst_f = f
    flagged = [f["title"].lower() for f in fit.get("factors") or [] if f["impact"] in ("risk", "watch")]
    good = [f["title"].lower() for f in fit.get("factors") or [] if f["impact"] == "helps"]
    if flagged:
        detail = "Prepare for " + racefit._join(flagged) + ("; there's time to adapt." if time_left else "; not much time left to adapt.")
    elif good:
        detail = "The course suits you: " + racefit._join(good) + "."
    else:
        detail = "Nothing about the course works against you."
    comps["race_factors"] = _c("race_factors", r_score, detail)
    if worst_f and worst_f.get("tip"):
        tip = re.split(r"\. |; |, or |: ", worst_f["tip"])[0].rstrip(".")[:90]
        tip = tip[0].lower() + tip[1:] if len(tip) > 1 and tip[1].islower() else tip
        actions.append(((25 if worst_f["impact"] == "risk" else 10) * WEIGHTS["race_factors"],
                        f"{worst_f['title']}: {tip}"))

    # ---- 5. health & recovery (check-ins + form; never Oura)
    since14 = (today - timedelta(days=13)).isoformat()
    cis = [c for c in checkins or [] if isinstance(c, dict) and since14 <= (c.get("date") or "") <= today.isoformat()]
    pain = [c for c in cis if c.get("pain_flag")]
    rough = [c for c in cis if (isinstance(c.get("feel"), int) and c["feel"] <= 2) or c.get("mood") == "low"
             or any((s.get("level") or 0) >= 3 for s in c.get("soreness") or [])]
    h_score = 100.0 - (50 if pain else 0) - min(30, 10 * len(rough))
    notes = []
    if pain:
        notes.append("pain flagged in a check-in")
    if rough:
        notes.append(f"{len(rough)} rough check-in{'s' if len(rough) != 1 else ''}")
    if isinstance(tsb, int | float) and tsb < -20:
        h_score -= 20 if tsb < -30 else 10
        notes.append(f"deep fatigue (form {tsb:.0f})")
    detail = ("Last 2 weeks: " + ", ".join(notes) + ".") if notes else "No pain or rough days logged in the last 2 weeks."
    comps["health"] = _c("health", h_score, detail)
    if pain:
        from .checkins import area_label
        sore = max((s for c in pain for s in c.get("soreness") or []), key=lambda s: s.get("level") or 0, default=None)
        where = f"your {area_label(sore)}" if sore and sore.get("area") != "other" else "the pain"
        actions.append((10_000, f"Get {where} checked before adding load"))
    elif isinstance(tsb, int | float) and tsb < -30:
        actions.append((40 * WEIGHTS["health"], "Take 2-3 easy days: you're carrying a lot of fatigue"))

    # ---- total
    weights = dict(WEIGHTS)
    if weeks > KEY_LIGHT_WEEKS:
        weights.update(key_session=10, fitness=35, consistency=30)
    for k, c in comps.items():
        c["weight"] = weights[k]
    score = sum(c["score"] * c["weight"] for c in comps.values()) / sum(weights.values())
    score_i = int(round(score))
    grade = grade_for(score_i)
    if pain:
        status = "at_risk"
    elif unreachable:
        status = "at_risk"
    else:
        status = "ahead" if score_i >= 88 else "on_track" if score_i >= 70 else "behind"
    if history < MIN_HISTORY_DAYS or weeks > LOW_CONF_WEEKS:
        confidence = "low"
    elif far or history < 56:
        confidence = "medium"
    else:
        confidence = "high"

    order = ["fitness", "key_session", "consistency", "race_factors", "health"]
    weakest = max(order, key=lambda k: (100 - comps[k]["score"]) * weights[k])
    weak_line = {"fitness": "fitness needs to build", "key_session": "long sessions need to grow",
                 "consistency": "training has been patchy", "race_factors": "the course needs specific prep",
                 "health": "recovery needs attention"}[weakest]
    if status == "at_risk":
        headline = "At risk: deal with the pain first" if pain else "At risk: not enough time to build safely"
    elif status == "ahead":
        headline = "Ahead: fitness ahead of schedule" if not far else "Ahead of where you need to be now"
    elif status == "on_track":
        if comps[weakest]["score"] < 75:
            headline = f"On track, but {weak_line}"
        else:
            headline = ("On track for this point" if far else "On track: fitness building as planned" if forecast
                        else "On track: training is lining up")
    else:
        headline = f"Behind: {weak_line}"
    headline = headline[:70]
    if not rows:
        headline = "Early days: no Garmin training to grade yet"
    when = "Race day" if days == 0 else f"{weeks} weeks to go" if days >= 14 else f"{days} day{'s' if days != 1 else ''} to go"
    if far:
        fit_line = f"Fitness {cur:.0f} now; race day needs ~{target}."
    else:
        fit_line = f"Fitness {cur:.0f} now, ~{projected:.0f} by race day vs ~{target} needed."
    summary = f"{when}. {fit_line} {bits[0][0].upper() + bits[0][1:]}."
    if confidence == "low":
        summary = ("Early days: grade is a rough guide. " if history >= MIN_HISTORY_DAYS or rows
                   else "No Garmin history yet: grade is a rough guide. ") + summary
    summary = summary[:200]

    seen: set[str] = set()
    top = []
    for _, text in sorted(actions, key=lambda x: -x[0]):
        if text not in seen:
            seen.add(text)
            top.append(text)
    return {"event_id": event.get("id"), "grade": grade, "score": score_i, "status": status,
            "confidence": confidence, "headline": headline, "summary": summary,
            "components": [comps[k] for k in order], "actions": top[:3], "weeks_to_race": weeks,
            "days_to_race": days, "projected_fitness": round(projected), "current_fitness": round(cur),
            "target_fitness": target, "forecast": bool(forecast), "updated": int(clock())}


def compact(r: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {"event_id": r["event_id"], "name": event.get("name"), "date": event.get("date"),
            "main": bool(event.get("main")), "grade": r["grade"], "score": r["score"],
            "status": r["status"], "headline": r["headline"], "confidence": r["confidence"]}


# ----------------------------------------------------------------- service --
class ReadinessService:
    """Gathers the inputs for one user and caches each event's grade for ``CACHE_S``."""

    def __init__(self, *, events: Any, stats: Any, plans: Any, checkins: Any,
                 athlete: Callable[[str], dict[str, Any]], today: Callable[[str], date],
                 clock: Callable[[], float] = time.time) -> None:
        self._events, self._stats, self._plans, self._checkins = events, stats, plans, checkins
        self._athlete, self._today, self._clock = athlete, today, clock
        self._cache: dict[tuple[str, str], tuple[float, str, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_agent(cls, agent: Any) -> "ReadinessService":
        return cls(events=agent.events, stats=agent.stats, plans=agent.plans, checkins=agent.checkins,
                   athlete=agent.coach.athlete, today=lambda uid: agent._now(uid).date(), clock=agent._clock)

    def _inputs(self, user_id: str) -> dict[str, Any]:
        today = self._today(user_id)
        try:
            today, acts = self._stats.activities(user_id)
        except Exception:  # Garmin not connected or unreachable: grade on what we have
            acts = []
        athlete = self._athlete(user_id)
        plan = self._plans.get(user_id)
        load = load_compute(acts, today, threshold_hr=athlete.get("threshold_hr"), plan=plan)
        return {"today": today, "acts": acts, "athlete": athlete, "plan": plan, "load": load,
                "checkins": self._checkins.list(user_id, 14)}

    def _one(self, user_id: str, ev: dict[str, Any], inp: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        today = self._today(user_id).isoformat()
        hit = self._cache.get((user_id, ev["id"]))
        if hit and self._clock() - hit[0] < CACHE_S and hit[1] == today:
            return hit[2], inp
        inp = inp or self._inputs(user_id)
        out = compute(ev, inp["athlete"], today=inp["today"], acts=inp["acts"], plan=inp["plan"],
                      load=inp["load"], checkins=inp["checkins"], clock=self._clock)
        with self._lock:
            self._cache[(user_id, ev["id"])] = (self._clock(), today, out)
        return out, inp

    def get(self, user_id: str, event_id: str) -> dict[str, Any]:
        from .coaching import CoachError
        ev = self._events.get(user_id, event_id)
        if ev["date"] < self._today(user_id).isoformat():
            raise CoachError("That race is done. Write a debrief instead.")
        return self._one(user_id, ev, None)[0]

    def upcoming(self, user_id: str) -> list[dict[str, Any]]:
        today = self._today(user_id).isoformat()
        out, inp = [], None
        for ev in self._events.list(user_id):
            if (ev.get("date") or "") < today:
                continue
            r, inp = self._one(user_id, ev, inp)
            out.append(compact(r, ev))
        return out

    def invalidate(self, user_id: str) -> None:
        with self._lock:
            for k in [k for k in self._cache if k[0] == user_id]:
                self._cache.pop(k, None)


__all__ = ["compute", "compact", "grade_for", "race_key", "target_fitness", "ReadinessService",
           "TARGET_CTL", "LONG", "WEIGHTS"]
