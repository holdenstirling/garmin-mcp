"""Insights: "What your data says". Deterministic, explainable patterns across Garmin
activities, the training load model, the built plan, check-ins, gear and recovery.

No model call, so recovery and sleep from the athlete's chosen source (``sources.recovery_for``,
Oura included) may feed the rules. Oura-derived insights are only ever *shown in the app*:
each insight lists its ``sources`` and carries ``uses_oura``; ``context_lines`` (what Rabbit
sees, via ``coaching.context_block``) and the coach view drop every insight with
``uses_oura``. Keep that invariant (Oura API terms).

Rules (each returns at most one insight; positive and negative cases are tested):

1. ``ramp``         last 7 days' load > 30% over the 4 weeks before -> injury-risk watch;
                    an ``adjust.propose`` suggestion becomes an "apply" action, else open plan.
2. ``long``         longest race-sport session (6 weeks) vs what the main race needs by now
                    (``readiness.LONG`` ramped like the readiness grade).
3. ``intensity``    share of hard time in 4 weeks (HR vs threshold, else Garmin's training
                    effect label, else the matched planned session kind) vs the 80/20 guideline.
4. ``recovery``     readiness (or HRV) the days after big days vs the athlete's baseline.
5. ``sleep``        check-in feel after short vs normal sleep (n >= 6).
6. ``time_of_day``  planned sessions finished as planned by morning/midday/evening.
7. ``missed_day``   the weekday whose planned sessions get missed most (8 weeks).
8. ``sore:<area>``  a body area in 3+ check-ins in 4 weeks -> prehab / strength session.
9. ``gear:<id>``    shoes near retirement before a key race.
10. ``fitness``     4-week change in fitness (CTL) in plain words.

Ranking: impact (action > watch > positive), then freshness (identical text shown 3+ days
ranks lower; an unchanged positive insight is dropped after 7 days), then rule priority;
at most ``MAX_ACTIVE``. Dismiss = snooze for ``SNOOZE_DAYS`` (per-user ``insights`` doc).
Actions never change anything by themselves: plan changes go through ``adjust`` (re-proposed
and checked server-side on apply); everything else just opens a screen.
"""

from __future__ import annotations

import hashlib
import re
import statistics
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from .planbuilder import QUALITY, iter_sessions
from .stats import _rows
from .weekplan import merge

MAX_ACTIVE = 5
SNOOZE_DAYS = 7
STALE_DAYS = 3
DROP_POSITIVE_DAYS = 7
CACHE_S = 1800
CONTEXT_MAX = 3
CONTEXT_FRESH_DAYS = 2
TITLE_MAX, EXPLAIN_MAX, WHY_MAX = 60, 200, 140
ID_RE = re.compile(r"^[a-z0-9_:.-]{1,64}$")
IMPACT_ORDER = {"action": 0, "watch": 1, "positive": 2}
ACTION_KINDS = ("apply_adjust", "open_plan", "open_session", "ask_rabbit", "ask_coach", "open_gear", "none")

RAMP_LIMIT = 0.30
RAMP_MIN_BASE = 100.0     # 4-week average weekly load below this: too little to judge
HARD_HR = 0.85            # avg HR / threshold HR at or above this = a hard session
HARD_LABELS = {"TEMPO", "LACTATE_THRESHOLD", "THRESHOLD", "VO2MAX", "ANAEROBIC_CAPACITY", "ANAEROBIC", "SPEED"}
ENDURANCE = {"run", "bike", "swim", "brick", "hike", "ski", "paddle", "climb", "other"}
SHORT_SLEEP_H = 6.5
MIN_SLEEP_N = 6
KM_MI = 0.621371
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SLOTS = (("morning", 0, 12), ("midday", 12, 16), ("evening", 16, 24))
PREHAB = {
    "calf": "bent- and straight-knee calf raises", "achilles": "slow heel drops off a step",
    "shin": "toe raises and calf raises", "knee": "step-downs and glute bridges",
    "hamstring": "bridges and slow hamstring curls", "quad": "split squats and wall sits",
    "hip": "clamshells and side planks", "glute": "clamshells and single-leg bridges",
    "it_band": "side-lying leg raises and hip strength", "lower_back": "dead bugs and bird dogs",
    "upper_back": "band pull-aparts and rows", "foot": "short-foot drills and towel curls",
    "ankle": "single-leg balance and ankle circles", "shoulder": "band external rotations",
    "groin": "Copenhagen planks (short holds)", "neck": "gentle chin tucks and mobility",
}


# ------------------------------------------------------------- helpers --
def _cut(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip(" ,.;:") + "…"


def _dur(minutes: float) -> str:
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    return f"{h}h {mm:02d}m" if h and mm else f"{h}h" if h else f"{mm}m"


def _pct(x: float) -> str:
    return f"{round(abs(x) * 100)}%"


def _insight(id_: str, *, title: str, explanation: str, why: str, impact: str, confidence: str,
             evidence: dict[str, Any] | None, action: dict[str, Any] | None, sources: list[str],
             priority: int) -> dict[str, Any]:
    assert impact in IMPACT_ORDER and confidence in ("low", "medium", "high")
    act = action or {"kind": "none", "label": "", "payload": {}}
    assert act["kind"] in ACTION_KINDS
    return {"id": id_, "title": _cut(title, TITLE_MAX), "explanation": _cut(explanation, EXPLAIN_MAX),
            "why": _cut(why, WHY_MAX), "impact": impact, "confidence": confidence, "evidence": evidence,
            "action": act, "sources": sorted(set(sources)), "uses_oura": "oura" in sources, "priority": priority}


def _ev(values: list[float], labels: list[str], unit: str = "", kind: str = "line",
        target: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, "values": [round(float(v), 1) for v in values], "labels": labels, "unit": unit}
    if target is not None:
        out["target"] = round(float(target), 1)
    return out


def _act(kind: str, label: str, **payload: Any) -> dict[str, Any]:
    return {"kind": kind, "label": label, "payload": payload}


def _plan_action(plan: dict[str, Any] | None, label: str, ask: str) -> dict[str, Any]:
    return _act("open_plan", label) if plan else _act("ask_rabbit", "Ask Rabbit", text=ask)


def _daily(load: dict[str, Any] | None, today: date) -> dict[str, float]:
    return {p["date"]: float(p.get("load") or 0) for p in (load or {}).get("series") or []
            if not p.get("planned") and p["date"] <= today.isoformat()}


def _weeks_load(daily: dict[str, float], today: date, n: int) -> list[float]:
    """Load per 7-day block ending today, oldest first (n blocks)."""
    out = []
    for i in range(n - 1, -1, -1):
        end = today - timedelta(days=7 * i)
        out.append(sum(daily.get((end - timedelta(days=k)).isoformat(), 0.0) for k in range(7)))
    return out


def _week_minutes(rows: list[dict[str, Any]], today: date, i: int) -> float:
    end = today - timedelta(days=7 * i)
    return sum(r["min"] for r in rows if end - timedelta(days=6) <= r["date"] <= end)


def _plan_days(plan: dict[str, Any] | None, acts: list[dict[str, Any]], today: date,
               weeks: int = 8) -> list[dict[str, Any]]:
    """Past plan days (last ``weeks`` weeks, before today) with sessions marked done/missed."""
    if not plan:
        return []
    since = (today - timedelta(weeks=weeks)).isoformat()
    out = []
    for w in plan.get("weeks") or []:
        end = (date.fromisoformat(w["start"]) + timedelta(days=6)).isoformat()
        if end < since or w["start"] >= today.isoformat():
            continue
        planned = {d: [dict(s) for s in ss] for d, ss in w["days"].items()}
        for day in merge(date.fromisoformat(w["start"]), today, planned, acts):
            if since <= day["date"] < today.isoformat():
                out.append(day)
    return out


def _main_event(events: list[dict[str, Any]] | None, today: date) -> dict[str, Any] | None:
    up = [e for e in events or [] if (e.get("date") or "") >= today.isoformat()
          and (e.get("kind") or "race") in ("race", "challenge")]
    up.sort(key=lambda e: (not e.get("main"), e.get("priority") != "A", e.get("date") or ""))
    return up[0] if up else None


# --------------------------------------------------------------- rules --
def rule_ramp(*, today: date, load: dict[str, Any] | None, rows: list[dict[str, Any]], plan: dict[str, Any] | None,
              proposal: dict[str, Any] | None, **_: Any) -> dict[str, Any] | None:
    daily = _daily(load, today)
    if len(daily) < 35:
        return None
    first = min((r["date"] for r in rows), default=today)
    if (today - first).days < 34:  # need 4 full weeks before this one
        return None
    weeks = _weeks_load(daily, today, 5)
    cur, base = weeks[-1], sum(weeks[:-1]) / 4
    if base < RAMP_MIN_BASE or cur <= base * (1 + RAMP_LIMIT):
        return None
    jump = cur / base - 1
    hrs_now = _week_minutes(rows, today, 0) / 60
    hrs_base = sum(_week_minutes(rows, today, i) for i in range(1, 5)) / 4 / 60
    suggest = (proposal or {}).get("status") == "suggest" and (proposal or {}).get("id")
    if suggest:
        n = len((proposal or {}).get("changes") or [])
        action = _act("apply_adjust", f"Ease the next days ({n} change{'s' if n != 1 else ''})",
                      id=(proposal or {})["id"])
    else:
        action = _plan_action(plan, "Review this week", "My training jumped this week. How should I ease in?")
    return _insight(
        "ramp", title=f"Training jumped {_pct(jump)} this week",
        explanation=(f"Training load (time × intensity) was {cur:.0f} in the last 7 days vs a "
                     f"{base:.0f} weekly average over the 4 weeks before ({hrs_now:.1f} h vs {hrs_base:.1f} h)."),
        why="Most overuse injuries start after big jumps. Building 10-20% at a time is safer.",
        impact="action" if suggest or jump >= 0.5 else "watch", confidence="high" if len(daily) >= 60 else "medium",
        evidence=_ev(weeks, ["4 wk ago", "3 wk", "2 wk", "Last wk", "This wk"], "load", "bars", target=base * 1.3),
        action=action, sources=["garmin"], priority=1)


def rule_long(*, today: date, rows: list[dict[str, Any]], events: list[dict[str, Any]] | None,
              plan: dict[str, Any] | None, athlete: dict[str, Any], **_: Any) -> dict[str, Any] | None:
    from . import readiness as rd
    ev = _main_event(events, today)
    if not ev or not rows:
        return None
    days = (date.fromisoformat(ev["date"]) - today).days
    weeks = days // 7
    if days < 7 or weeks > rd.FAR_WEEKS:
        return None
    key = rd.race_key(ev)
    taper = rd._taper(key)
    stage = max(0.4, min(1.0, 1 - 0.04 * (weeks - (taper + 2))))
    prio = rd.PRIORITY.get(ev.get("priority") or "B", 0.9)
    since = today - timedelta(days=rd.LOOKBACK_DAYS)
    worst = None
    for sport, (mins, _km) in rd._sports(ev, key).items():
        cats = rd._counts(sport, ev.get("type") or "other")
        rs = [r for r in rows if r["sport"] in cats and since <= r["date"] <= today]
        need = mins * prio * stage
        best = max((r["min"] for r in rs), default=0.0)
        ratio = best / need if need else 1.0
        if worst is None or ratio < worst[0]:
            weekly = [max((r["min"] for r in rs if today - timedelta(days=7 * i + 6) <= r["date"] <= today - timedelta(days=7 * i)),
                          default=0.0) for i in range(5, -1, -1)]
            worst = (ratio, sport, best, need, weekly)
    if worst is None:
        return None
    ratio, sport, best, need, weekly = worst
    word = rd.SPORT_WORD.get(sport, sport)
    rising = max(weekly[3:]) > max(weekly[:3]) * 1.05
    name = ev.get("name") or "your race"
    evidence = _ev(weekly, [f"{6 - i} wk" if i < 5 else "This wk" for i in range(6)], "min", "bars", target=need)
    src = ["garmin", "plan"] if plan else ["garmin"]
    if ratio >= 0.95:
        return _insight(
            "long", title=f"Long {word}s on track for {name}",
            explanation=f"Your longest {word} in 6 weeks was {_dur(best)}; about {_dur(need)} is the target at this point.",
            why="The long session builds the endurance race day asks for. Hold it there and keep it easy.",
            impact="positive", confidence="medium", evidence=evidence, action=None, sources=src, priority=4)
    if ratio < 0.8 or not rising:
        step = 15 if need < 120 else 20
        return _insight(
            "long", title=f"Long {word} needs to grow for {name}",
            explanation=(f"Your longest {word} in 6 weeks was {_dur(best)}; {name} wants about {_dur(need)} by now. "
                         f"Add {step}-{step + 5} min each week."),
            why="Long sessions are the best predictor of a strong finish. Small weekly steps keep them safe.",
            impact="action" if ratio < 0.8 else "watch", confidence="medium", evidence=evidence,
            action=_plan_action(plan, "Open your plan", f"How should I build my long {word} for {name}?"),
            sources=src, priority=2)
    return None


def _session_kinds(plan: dict[str, Any] | None, acts: list[dict[str, Any]], today: date) -> dict[Any, str]:
    out: dict[Any, str] = {}
    for day in _plan_days(plan, acts, today, weeks=5):
        for s in day["sessions"]:
            a = s.get("activity") or {}
            if s.get("status") == "done" and a.get("id") is not None:
                out[a["id"]] = s.get("kind") or ""
    return out


def rule_intensity(*, today: date, acts: list[dict[str, Any]], rows: list[dict[str, Any]], plan: dict[str, Any] | None,
                   athlete: dict[str, Any], **_: Any) -> dict[str, Any] | None:
    since = today - timedelta(days=27)
    keep = {r["id"]: r for r in rows if since <= r["date"] <= today and r["sport"] in ENDURANCE}
    thr = athlete.get("threshold_hr")
    kinds = _session_kinds(plan, acts, today)
    total = known = hard = 0.0
    how: set[str] = set()
    weekly = [[0.0, 0.0] for _ in range(4)]
    n = 0
    for a in acts:
        r = keep.get(a.get("activity_id"))
        if r is None or r["min"] <= 0:
            continue
        n += 1
        total += r["min"]
        verdict = None
        if isinstance(a.get("avg_hr"), int | float) and isinstance(thr, int | float) and thr:
            verdict, m = a["avg_hr"] / thr >= HARD_HR, "heart rate"
        elif a.get("training_effect_label"):
            verdict, m = str(a["training_effect_label"]).upper() in HARD_LABELS, "Garmin's training effect"
        elif a.get("activity_id") in kinds and kinds[a["activity_id"]]:
            verdict, m = kinds[a["activity_id"]] in QUALITY or kinds[a["activity_id"]] == "race", "planned session type"
        if verdict is None:
            continue
        how.add(m)
        known += r["min"]
        hard += r["min"] if verdict else 0
        wk = min(3, (today - r["date"]).days // 7)
        weekly[3 - wk][0] += r["min"] if verdict else 0
        weekly[3 - wk][1] += r["min"]
    if n < 6 or total < 180 or known < 0.6 * total:
        return None
    share = hard / known
    method = "by heart rate" if how == {"heart rate"} else f"by {' and '.join(sorted(how))}"
    evidence = _ev([100 * h / t if t else 0 for h, t in weekly], ["3 wk ago", "2 wk", "Last wk", "This wk"], "%",
                   "bars", target=20)
    conf = "high" if how == {"heart rate"} else "medium"
    if share > 0.30:
        return _insight(
            "intensity", title=f"{_pct(share)} of your training was hard",
            explanation=(f"In 4 weeks, {_dur(hard)} of {_dur(known)} was tempo or harder ({method}). "
                         "The 80/20 guideline is about 20% hard, 80% easy."),
            why="Too much middle-to-hard work piles up fatigue without more fitness. Easy days make hard days work.",
            impact="watch", confidence=conf, evidence=evidence,
            action=_plan_action(plan, "Check your easy days", "Am I training too hard? How do I keep easy days easy?"),
            sources=["garmin", "plan"] if "planned session type" in how else ["garmin"], priority=3)
    if 0.08 <= share <= 0.25:
        return _insight(
            "intensity", title="Good easy/hard balance",
            explanation=f"In 4 weeks, {_pct(share)} of your training time was hard ({method}): close to the 80/20 guideline.",
            why="Mostly easy with a little hard is how endurance athletes get fitter without burning out.",
            impact="positive", confidence=conf, evidence=evidence, action=None,
            sources=["garmin", "plan"] if "planned session type" in how else ["garmin"], priority=8)
    return None


def rule_recovery(*, today: date, load: dict[str, Any] | None, recovery: dict[str, Any] | None,
                  recovery_source: str | None, plan: dict[str, Any] | None, **_: Any) -> dict[str, Any] | None:
    days = {d["date"]: d for d in (recovery or {}).get("days") or [] if isinstance(d, dict) and d.get("date")}
    metric = "readiness" if sum(isinstance(d.get("readiness"), int | float) for d in days.values()) >= 7 else \
        "hrv" if sum(isinstance(d.get("hrv"), int | float) for d in days.values()) >= 7 else None
    if metric is None:
        return None
    vals = [float(d[metric]) for d in days.values() if isinstance(d.get(metric), int | float)]
    base = statistics.mean(vals)
    tol = 5.0 if metric == "readiness" else base * 0.05
    daily = _daily(load, today)
    window = sorted(d for d in days if d < today.isoformat())
    loads = [daily.get(d, 0.0) for d in window if daily.get(d, 0.0) > 0]
    if len(loads) < 4:
        return None
    big = max(100.0, 1.5 * statistics.median(loads))
    drops, lags = [], []
    for d in window:
        if daily.get(d, 0.0) < big:
            continue
        dd = date.fromisoformat(d)
        nxt = [days.get((dd + timedelta(days=k)).isoformat(), {}).get(metric) for k in (1, 2, 3)]
        if not isinstance(nxt[0], int | float):
            continue
        drops.append(base - float(nxt[0]))
        lag = next((k + 1 for k, v in enumerate(nxt) if isinstance(v, int | float) and v >= base - tol), 3)
        lags.append(lag)
    if len(lags) < 3:
        return None
    lag, drop = statistics.mean(lags), statistics.mean(drops)
    src = recovery_source if recovery_source in ("garmin", "oura") else "garmin"
    label = "readiness" if metric == "readiness" else "HRV"
    unit = " points" if metric == "readiness" else " ms"
    what = {"oura": "Oura", "garmin": "Garmin"}[src]
    evidence = _ev(lags, [f"Big day {i + 1}" for i in range(len(lags))], "days", "bars", target=1)
    if lag >= 1.75:
        b2b = 0
        if plan:
            hard_days = sorted({d for _, d, s in iter_sessions(plan)
                                if today.isoformat() < d <= (today + timedelta(days=14)).isoformat()
                                and (s.get("kind") in QUALITY or s.get("kind") in ("long", "brick"))})
            b2b = sum(1 for a, b in zip(hard_days, hard_days[1:])
                      if (date.fromisoformat(b) - date.fromisoformat(a)).days == 1)
        extra = f" Your plan has {b2b} back-to-back hard day{'s' if b2b != 1 else ''} in the next 2 weeks." if b2b else ""
        return _insight(
            "recovery", title=f"You recover in about {round(lag)} days after big days",
            explanation=(f"After {len(lags)} big days (load {big:.0f}+), {what} {label} dipped about {max(0, drop):.0f}{unit} "
                         f"and took ~{lag:.1f} days to get back to your usual {base:.0f}.{extra}"),
            why="Keep hard days about 48 h apart so each one lands on recovered legs.",
            impact="action" if b2b else "watch", confidence="medium" if len(lags) >= 4 else "low", evidence=evidence,
            action=_plan_action(plan, "Space out hard days", "How should I space my hard days?") if b2b or plan else None,
            sources=["garmin", src], priority=3)
    if lag <= 1.25:
        return _insight(
            "recovery", title="You bounce back fast after big days",
            explanation=(f"After {len(lags)} big days (load {big:.0f}+), {what} {label} was back near your usual "
                         f"{base:.0f} by the next day."),
            why="Quick recovery means your current load suits you. Keep the easy days easy so it stays that way.",
            impact="positive", confidence="medium" if len(lags) >= 4 else "low", evidence=evidence, action=None,
            sources=["garmin", src], priority=7)
    return None


def rule_sleep(*, today: date, checkins: list[dict[str, Any]] | None, sleep: dict[str, Any] | None,
               sleep_source: str | None, **_: Any) -> dict[str, Any] | None:
    hours = {d["date"]: float(d["sleep_hours"]) for d in (sleep or {}).get("days") or []
             if isinstance(d, dict) and isinstance(d.get("sleep_hours"), int | float)}

    def score(c: dict[str, Any]) -> float | None:  # 1..5, higher = felt better
        if isinstance(c.get("feel"), int):
            return float(c["feel"])
        if isinstance(c.get("rpe"), int):
            return 6 - c["rpe"] / 2
        return None
    cis = [c for c in checkins or [] if isinstance(c, dict) and (c.get("date") or "") <= today.isoformat()
           and score(c) is not None]
    by_hours = [(hours[c["date"]] < SHORT_SLEEP_H, score(c) or 0.0) for c in cis if c.get("date") in hours]
    if len(by_hours) >= MIN_SLEEP_N:
        pairs, src, low_word = by_hours, sleep_source if sleep_source in ("garmin", "oura") else "garmin", f"under {SHORT_SLEEP_H} h"
    else:
        pairs = [(c["sleep"] == "poor", score(c) or 0.0) for c in cis if c.get("sleep") in ("poor", "ok", "good")]
        src, low_word = "checkins", "poor sleep"
    low = [s for short, s in pairs if short]
    ok = [s for short, s in pairs if not short]
    if len(pairs) < MIN_SLEEP_N or len(low) < 2 or len(ok) < 2:
        return None
    diff = statistics.mean(ok) - statistics.mean(low)
    if diff < 0.7:
        return None
    who = {"oura": "Oura sleep", "garmin": "Garmin sleep", "checkins": "your check-ins"}[src]
    return _insight(
        "sleep", title=f"Short sleep makes sessions feel {diff:.1f} points harder",
        explanation=(f"On {low_word} ({len(low)} sessions) your check-ins averaged feel {statistics.mean(low):.1f}/5 "
                     f"vs {statistics.mean(ok):.1f}/5 after better nights ({len(ok)}). From {who}."),
        why="Sleep is when training turns into fitness. Protect it before your hardest sessions.",
        impact="watch", confidence="medium" if len(pairs) >= 10 else "low",
        evidence=_ev([statistics.mean(low), statistics.mean(ok)], ["Short sleep", "Good sleep"], "/5", "bars"),
        action=None, sources=["checkins", src], priority=5)


def rule_time_of_day(*, today: date, acts: list[dict[str, Any]], plan: dict[str, Any] | None,
                     rows: list[dict[str, Any]], **_: Any) -> dict[str, Any] | None:
    hour = {r["id"]: r["hour"] for r in rows if r.get("hour") is not None}
    stats: dict[str, list[int]] = {name: [0, 0] for name, _, _ in SLOTS}
    for day in _plan_days(plan, acts, today):
        for s in day["sessions"]:
            a = s.get("activity") or {}
            h = hour.get(a.get("id"))
            if s.get("status") != "done" or h is None or not s.get("minutes"):
                continue
            slot = next(name for name, lo, hi in SLOTS if lo <= h < hi)
            stats[slot][1] += 1
            stats[slot][0] += int((a.get("minutes") or 0) >= 0.85 * s["minutes"])
    rated = {k: (d / n, n) for k, (d, n) in stats.items() if n >= 5}
    if len(rated) < 2:
        return None
    best = max(rated, key=lambda k: rated[k][0])
    worst = min(rated, key=lambda k: rated[k][0])
    gap = rated[best][0] - rated[worst][0]
    if gap < 0.2:
        return None
    return _insight(
        "time_of_day", title=f"{best.capitalize()} sessions go best for you",
        explanation=(f"In 8 weeks you finished {_pct(rated[best][0])} of {best} sessions as planned vs "
                     f"{_pct(rated[worst][0])} in the {worst} ({rated[best][1]} and {rated[worst][1]} sessions)."),
        why=f"Put your key sessions in the {best} when you can: the ones that matter most then happen.",
        impact="watch", confidence="medium" if min(rated[best][1], rated[worst][1]) >= 8 else "low",
        evidence=_ev([100 * rated[k][0] if k in rated else 0 for k, _, _ in SLOTS], ["Morning", "Midday", "Evening"],
                     "%", "bars"),
        action=_act("open_plan", "Open your plan"), sources=["garmin", "plan"], priority=6)


def rule_missed_day(*, today: date, acts: list[dict[str, Any]], plan: dict[str, Any] | None,
                    **_: Any) -> dict[str, Any] | None:
    due = [0] * 7
    missed = [0] * 7
    for day in _plan_days(plan, acts, today):
        wd = date.fromisoformat(day["date"]).weekday()
        for s in day["sessions"]:
            if s.get("status") in ("done", "missed") and s.get("kind") != "race":
                due[wd] += 1
                missed[wd] += s["status"] == "missed"
    if sum(due) < 8:
        return None
    rates = [missed[i] / due[i] if due[i] else 0.0 for i in range(7)]
    worst = max(range(7), key=lambda i: (rates[i] if due[i] >= 3 else -1, due[i]))
    others_due = sum(due) - due[worst]
    others = (sum(missed) - missed[worst]) / others_due if others_due else 0.0
    if due[worst] < 3 or missed[worst] < 2 or rates[worst] < 0.5 or rates[worst] < others + 0.25:
        return None
    best = min((i for i in range(7) if due[i] >= 3 and i != worst), key=lambda i: rates[i], default=None)
    tip = f" {WEEKDAYS[best]}s work best ({_pct(1 - rates[best])} done)." if best is not None else ""
    return _insight(
        f"missed_day:{worst}", title=f"{WEEKDAYS[worst]} sessions get missed",
        explanation=(f"In 8 weeks you missed {missed[worst]} of {due[worst]} {WEEKDAYS[worst]} sessions vs "
                     f"{_pct(others)} on other days.{tip}"),
        why="A plan that fits your week beats a perfect plan you can't follow. Move it to a day that works.",
        impact="action", confidence="medium" if due[worst] >= 5 else "low",
        evidence=_ev([100 * r for r in rates], [w[:3] for w in WEEKDAYS], "% missed", "bars"),
        action=_act("open_plan", f"Move {WEEKDAYS[worst]} sessions"), sources=["garmin", "plan"], priority=2)


def rule_soreness(*, today: date, checkins: list[dict[str, Any]] | None, plan: dict[str, Any] | None,
                  **_: Any) -> dict[str, Any] | None:
    from .checkins import area_label
    since = (today - timedelta(days=27)).isoformat()
    by_area: dict[str, set[str]] = {}
    pain: set[str] = set()
    label: dict[str, str] = {}
    for c in checkins or []:
        if not isinstance(c, dict) or not since <= (c.get("date") or "") <= today.isoformat():
            continue
        for s in c.get("soreness") or []:
            area = s.get("area")
            if not area or area == "other":
                continue
            by_area.setdefault(area, set()).add(c["date"])
            label.setdefault(area, area_label({"area": area}))
            if c.get("pain_flag"):
                pain.add(area)
    hits = sorted(((len(v), k) for k, v in by_area.items() if len(v) >= 3), reverse=True)
    if not hits:
        return None
    n, area = hits[0]
    name = label[area]
    weekly = [sum(1 for d in by_area[area] if (today - timedelta(days=7 * i + 6)).isoformat() <= d
                  <= (today - timedelta(days=7 * i)).isoformat()) for i in range(3, -1, -1)]
    nxt = None
    if plan:
        nxt = next(((d, s) for _, d, s in iter_sessions(plan)
                    if d >= today.isoformat() and s.get("sport") == "strength"), None)
    if nxt:
        action = _act("open_session", "Open your strength session", session_id=nxt[1]["id"], date=nxt[0])
    else:
        action = _act("ask_rabbit", "Ask Rabbit for prehab", text=f"My {name} keeps getting sore. What prehab should I add?")
    see = " Pain came up too: get it checked if it lingers." if area in pain else ""
    return _insight(
        f"sore:{area}", title=f"Your {name} keeps coming up",
        explanation=(f"Your {name} was sore in {n} check-ins in 4 weeks. Try {PREHAB.get(area, 'gentle strength and mobility work')}, "
                     f"2-3 times a week.{see}"),
        why="Recurring soreness is often a weak link. A few minutes of strength work usually fixes it (not a diagnosis).",
        impact="action", confidence="medium" if n >= 4 else "low",
        evidence=_ev(weekly, ["3 wk ago", "2 wk", "Last wk", "This wk"], "check-ins", "bars"),
        action=action, sources=["checkins", "plan"] if nxt else ["checkins"], priority=2)


def rule_gear(*, today: date, gear: list[dict[str, Any]] | None, events: list[dict[str, Any]] | None,
              athlete: dict[str, Any], **_: Any) -> dict[str, Any] | None:
    shoes = [g for g in gear or [] if g.get("kind") == "shoes" and not g.get("retired")
             and g.get("status") in ("soon", "retire") and g.get("alert_km")]
    if not shoes:
        return None
    g = max(shoes, key=lambda x: x.get("pct_of_alert") or 0)
    imperial = athlete.get("units") == "imperial"
    unit = "mi" if imperial else "km"
    f = KM_MI if imperial else 1.0
    used, limit = float(g.get("total_km") or 0) * f, float(g["alert_km"]) * f
    name = g.get("nickname") or " ".join(x for x in (g.get("brand"), g.get("model")) if x) or "Your shoes"
    runs = ("running", "trail", "triathlon", "duathlon", "ultra", "marathon", "other")
    race = next((e for e in sorted(events or [], key=lambda e: e.get("date") or "")
                 if today.isoformat() <= (e.get("date") or "") <= (today + timedelta(days=56)).isoformat()
                 and (e.get("priority") in ("A", "B") or e.get("main")) and (e.get("kind") or "race") == "race"
                 and (e.get("type") or "other") in runs), None)
    ev = _ev([min(100.0, float(g.get("pct_of_alert") or 0))], ["Used"], "%", "meter", target=100)
    if race:
        wk = max(1, (date.fromisoformat(race["date"]) - today).days // 7)
        return _insight(
            f"gear:{g['id']}", title=f"Fresh shoes before {race.get('name') or 'your race'}",
            explanation=(f"{name} has {used:.0f} of {limit:.0f} {unit} and {race.get('name') or 'your race'} is in "
                         f"{wk} week{'s' if wk != 1 else ''}. Break in a new pair now, ~{30 * f:.0f} {unit} before race day."),
            why="Worn foam cushions less, which adds strain late in a race. New shoes need a few runs first.",
            impact="action", confidence="high", evidence=ev, action=_act("open_gear", "Open your gear", gear_id=g["id"]),
            sources=["garmin", "gear"], priority=1)
    if g.get("status") == "retire":
        return _insight(
            f"gear:{g['id']}", title=f"{name} is past its mileage",
            explanation=f"{name} has {used:.0f} {unit}, past the {limit:.0f} {unit} you set to retire it.",
            why="Worn shoes cushion less, which adds strain on every run.",
            impact="watch", confidence="high", evidence=ev, action=_act("open_gear", "Open your gear", gear_id=g["id"]),
            sources=["garmin", "gear"], priority=6)
    return None


def rule_fitness(*, today: date, load: dict[str, Any] | None, plan: dict[str, Any] | None,
                 events: list[dict[str, Any]] | None, adherence_pct: int | None = None, **_: Any) -> dict[str, Any] | None:
    series = [p for p in (load or {}).get("series") or [] if not p.get("planned") and p["date"] <= today.isoformat()]
    by = {p["date"]: float(p.get("ctl") or 0) for p in series}
    now, then = by.get(today.isoformat()), by.get((today - timedelta(days=28)).isoformat())
    if now is None or then is None or then < 5:
        return None
    change = now / then - 1
    pts = [by.get((today - timedelta(days=7 * i)).isoformat(), 0.0) for i in range(8, -1, -1)]
    evidence = _ev(pts, [f"{8 - i} wk" if i < 8 else "Now" for i in range(9)], "fitness", "line")
    what = f"Fitness (your 6-week training average) went from {then:.0f} to {now:.0f} in 4 weeks"
    if change >= 0.05:
        on_plan = plan is not None and adherence_pct is not None and adherence_pct >= 80
        return _insight(
            "fitness", title=f"Fitness up {_pct(change)} in 4 weeks" + (": right on plan" if on_plan else ""),
            explanation=what + (f", with {adherence_pct}% of plan sessions done." if on_plan else "."),
            why="Steady gains like this come from consistency, not hero days. Keep stacking normal weeks.",
            impact="positive", confidence="high" if len(series) >= 56 else "medium", evidence=evidence, action=None,
            sources=["garmin", "plan"] if on_plan else ["garmin"], priority=9)
    if change <= -0.10:
        raced = any(today - timedelta(days=21) <= date.fromisoformat(e["date"]) < today for e in events or []
                    if e.get("date"))
        taper = any(w.get("phase") in ("taper", "race") and w["start"] <= today.isoformat()
                    <= (date.fromisoformat(w["start"]) + timedelta(days=6)).isoformat() for w in (plan or {}).get("weeks") or [])
        if raced or taper:
            return _insight(
                "fitness", title=f"Fitness down {_pct(change)}: planned rest",
                explanation=what + ". That's expected around a " + ("taper." if taper else "race: recover, then rebuild."),
                why="A dip after or before a race is the point: freshness for race day, then recovery.",
                impact="positive", confidence="medium", evidence=evidence, action=None, sources=["garmin"], priority=9)
        return _insight(
            "fitness", title=f"Fitness down {_pct(change)} in 4 weeks",
            explanation=what + ". A few steady, mostly easy weeks bring it back.",
            why="Fitness fades after about 2 weeks of less training. Short, regular sessions hold it.",
            impact="watch", confidence="medium", evidence=evidence,
            action=_plan_action(plan, "Open your plan", "My fitness has dropped. How do I get back on track?"),
            sources=["garmin"], priority=5)
    return None


RULES: tuple[Callable[..., dict[str, Any] | None], ...] = (
    rule_ramp, rule_long, rule_intensity, rule_recovery, rule_sleep, rule_time_of_day, rule_missed_day,
    rule_soreness, rule_gear, rule_fitness)


def compute(*, today: date, acts: list[dict[str, Any]], athlete: dict[str, Any] | None = None,
            plan: dict[str, Any] | None = None, load: dict[str, Any] | None = None,
            checkins: list[dict[str, Any]] | None = None, recovery: dict[str, Any] | None = None,
            recovery_source: str | None = None, sleep: dict[str, Any] | None = None,
            sleep_source: str | None = None,
            events: list[dict[str, Any]] | None = None, gear: list[dict[str, Any]] | None = None,
            proposal: dict[str, Any] | None = None, adherence_pct: int | None = None) -> list[dict[str, Any]]:
    """Every insight that fires (unranked). Each rule is isolated: one failing never hides the rest.

    ``recovery`` / ``sleep``: day rows shaped like ``OuraClient.recovery`` from the athlete's
    chosen sources (``recovery_source`` / ``sleep_source``: "garmin" or "oura")."""
    from .load import compute as load_compute
    a = athlete or {}
    if load is None:
        load = load_compute(acts, today, threshold_hr=a.get("threshold_hr"), plan=plan)
    ctx = {"today": today, "acts": acts, "rows": [r for r in _rows(acts) if r["date"] <= today], "athlete": a,
           "plan": plan, "load": load, "checkins": checkins, "recovery": recovery,
           "recovery_source": recovery_source, "sleep": sleep, "sleep_source": sleep_source,
           "events": events, "gear": gear, "proposal": proposal, "adherence_pct": adherence_pct}
    out = []
    for rule in RULES:
        try:
            ins = rule(**ctx)
        except Exception:  # noqa: BLE001 - a bad data shape skips one rule, never the card
            ins = None
        if ins:
            out.append(ins)
    return out


# ------------------------------------------------------------- ranking --
def text_hash(ins: dict[str, Any]) -> str:
    return hashlib.sha256(f"{ins['title']}|{ins['explanation']}".encode()).hexdigest()[:12]


def rank(items: list[dict[str, Any]], state: dict[str, Any] | None, today: date,
         cap: int = MAX_ACTIVE) -> list[dict[str, Any]]:
    """Active insights: not snoozed, not a long-unchanged positive, ordered, capped."""
    st = state or {}
    snoozed = {k for k, until in (st.get("dismissed") or {}).items() if isinstance(until, str) and until > today.isoformat()}
    seen = st.get("seen") or {}
    out = []
    for ins in items:
        if ins["id"] in snoozed:
            continue
        s = seen.get(ins["id"]) or {}
        same = s.get("h") == text_hash(ins) and isinstance(s.get("first"), str)
        age = (today - date.fromisoformat(s["first"])).days if same else 0
        if ins["impact"] == "positive" and age >= DROP_POSITIVE_DAYS:
            continue
        out.append({**ins, "fresh": age < STALE_DAYS})
    out.sort(key=lambda i: (IMPACT_ORDER[i["impact"]], not i["fresh"], i["priority"]))
    return out[:cap]


def mark_seen(state: dict[str, Any], shown: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """New ``seen`` map: first day each exact text was shown (old entries pruned)."""
    seen = dict(state.get("seen") or {})
    for ins in shown:
        h = text_hash(ins)
        if (seen.get(ins["id"]) or {}).get("h") != h:
            seen[ins["id"]] = {"h": h, "first": today.isoformat()}
    cutoff = (today - timedelta(days=30)).isoformat()
    return {k: v for k, v in seen.items() if (v.get("first") or "") >= cutoff or k in {i["id"] for i in shown}}


def context_lines(items: list[dict[str, Any]], n: int = CONTEXT_MAX) -> list[str]:
    """Up to ``n`` one-liners for Rabbit's context. Never any insight that used Oura data."""
    out = []
    for ins in items:
        if ins.get("uses_oura") or "oura" in (ins.get("sources") or []):
            continue
        out.append(f"- {ins['title']}: {ins['explanation']}")
        if len(out) >= n:
            break
    return out


def stored_context(doc: dict[str, Any], today: date) -> list[str]:
    """What ``coaching.context_block`` shows: the lines saved on the athlete's last view,
    only while recent, and re-filtered (Oura-free) on the way out."""
    when = doc.get("context_date")
    if not isinstance(when, str) or when < (today - timedelta(days=CONTEXT_FRESH_DAYS)).isoformat():
        return []
    items = [x for x in doc.get("context") or [] if isinstance(x, dict) and not x.get("oura")]
    return [str(x.get("line") or "")[:EXPLAIN_MAX + TITLE_MAX + 8] for x in items[:CONTEXT_MAX] if x.get("line")]


def public(ins: dict[str, Any], *, coach: bool = False) -> dict[str, Any]:
    out = {k: ins[k] for k in ("id", "title", "explanation", "why", "impact", "confidence", "evidence", "action",
                               "sources", "uses_oura") if k in ins}
    out["fresh"] = ins.get("fresh", True)
    if coach:
        out["action"] = {"kind": "none", "label": "", "payload": {}}
    return out


# ------------------------------------------------------------- service --
class InsightsService:
    """Computes (cached ``CACHE_S`` per user and day), ranks against the per-user ``insights``
    doc (snoozes, seen texts) and saves the Oura-free context lines for Rabbit."""

    def __init__(self, store: Any, *, gather: Callable[[str], Awaitable[dict[str, Any]]],
                 today: Callable[[str], date], clock: Callable[[], float] = time.time) -> None:
        self._store, self._gather, self._today, self._clock = store, gather, today, clock
        self._cache: dict[str, tuple[float, str, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def _doc(self, user_id: str) -> Any:
        return self._store.user_doc(user_id, "insights")

    async def all(self, user_id: str, *, fresh: bool = False) -> list[dict[str, Any]]:
        day = self._today(user_id).isoformat()
        hit = self._cache.get(user_id)
        if hit and not fresh and hit[1] == day and self._clock() - hit[0] < CACHE_S:
            return hit[2]
        items = compute(**await self._gather(user_id))
        with self._lock:
            self._cache[user_id] = (self._clock(), day, items)
        return items

    async def for_athlete(self, user_id: str, *, fresh: bool = False) -> dict[str, Any]:
        items = await self.all(user_id, fresh=fresh)
        today = self._today(user_id)
        doc = self._doc(user_id)
        state = doc.load()
        active = rank(items, state, today)

        def save(d: dict[str, Any]) -> None:
            d["seen"] = mark_seen(d, active, today)
            lines = context_lines(active)
            d["context"] = [{"id": i["id"], "line": ln, "oura": False}
                            for i, ln in zip([x for x in active if not x["uses_oura"]], lines)]
            d["context_date"] = today.isoformat()
            d["dismissed"] = {k: v for k, v in (d.get("dismissed") or {}).items()
                              if isinstance(v, str) and v > today.isoformat()}
        doc.update(save)
        return {"today": today.isoformat(), "insights": [public(i) for i in active], "total": len(items)}

    async def for_coach(self, athlete_id: str) -> dict[str, Any]:
        """Linked coach's view: never an Oura-derived insight; no athlete snoozes; no actions."""
        items = [i for i in await self.all(athlete_id) if not i["uses_oura"]]
        today = self._today(athlete_id)
        return {"today": today.isoformat(), "insights": [public(i, coach=True) for i in rank(items, None, today)]}

    def dismiss(self, user_id: str, insight_id: str, days: int = SNOOZE_DAYS) -> str:
        if not ID_RE.match(insight_id or ""):
            raise ValueError("insight id")
        days = max(1, min(30, int(days)))
        until = (self._today(user_id) + timedelta(days=days)).isoformat()

        def apply(d: dict[str, Any]) -> None:
            dm = dict(d.get("dismissed") or {})
            dm[insight_id] = until
            if len(dm) > 50:
                dm = dict(sorted(dm.items(), key=lambda kv: kv[1])[-50:])
            d["dismissed"] = dm
            d["context"] = [x for x in d.get("context") or [] if isinstance(x, dict) and x.get("id") != insight_id]
        self._doc(user_id).update(apply)
        return until

    def invalidate(self, user_id: str) -> None:
        with self._lock:
            self._cache.pop(user_id, None)


__all__ = ["InsightsService", "MAX_ACTIVE", "RULES", "SNOOZE_DAYS", "compute", "context_lines", "mark_seen",
           "public", "rank", "stored_context", "text_hash"]
