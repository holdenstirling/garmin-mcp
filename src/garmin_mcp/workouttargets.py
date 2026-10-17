"""Exact targets for every step of a plan session, and "how it went" after a workout.

Pure and deterministic (no model, never Oura). Used by the plan calendar (``plancal.calendar_view``
adds ``targets`` and ``went`` per session) so the Day view, Garmin sync and other screens read the
same numbers.

* **Heart rate** (bpm) per zone, from the athlete's numbers (profile, filled from Garmin):
  lactate-threshold HR first (Friel run zones, % of LTHR), else max + resting HR (heart-rate
  reserve), else max HR alone (% of max, Garmin's default zones). None when nothing is known: the
  app then shows the zone and asks for a max heart rate.
* **Pace** (run, s/km) = threshold pace x ``planbuilder.PACE_ZONES``; **power** (bike, W) = FTP x
  ``POWER_ZONES`` when FTP is known; **swim** (s/100 m) = CSS + a per-zone offset.
* **Cadence**: runs 160-190 steps/min rising with intensity, rides 80-105 rpm; plain ranges, not
  personal (cadence is individual, so these are a starting point the athlete can ignore).
* **Effort** out of 10 and a talk-test cue per zone.
* **Summary**: total time, minutes per zone, average target run pace, and an estimated training
  stress (TSS-style: hours x intensity factor^2 x 100) so hard and easy days compare.

``went`` compares a finished Garmin activity (compact summary: duration, distance, avg HR, avg
pace / speed, cadence, power) with the plan: short / too hard / too fast / slower / on target.
"""

from __future__ import annotations

from typing import Any

from .planbuilder import PACE_ZONES, POWER_ZONES

HR_LTHR = {1: (0.65, 0.84), 2: (0.85, 0.89), 3: (0.90, 0.94), 4: (0.95, 0.99), 5: (1.00, 1.06)}
HR_RESERVE = {1: (0.50, 0.60), 2: (0.60, 0.70), 3: (0.70, 0.80), 4: (0.80, 0.90), 5: (0.90, 1.00)}
HR_MAX = {1: (0.50, 0.60), 2: (0.60, 0.70), 3: (0.70, 0.80), 4: (0.80, 0.90), 5: (0.90, 1.00)}
# swim: seconds per 100 m added to CSS (negative = faster than CSS)
SWIM_OFFSET = {1: (18, 25), 2: (8, 14), 3: (4, 7), 4: (-1, 3), 5: (-6, -2)}
CADENCE = {"run": {1: (160, 170), 2: (165, 175), 3: (170, 180), 4: (175, 185), 5: (180, 190)},
           "bike": {1: (80, 90), 2: (85, 95), 3: (85, 95), 4: (90, 100), 5: (95, 105)}}
RPE = {1: "2-3", 2: "3-4", 3: "5-6", 4: "7-8", 5: "9"}
TALK = {1: "Full conversation", 2: "Chatting in sentences", 3: "A few words at a time",
        4: "A word or two", 5: "No talking"}
INTENSITY = {1: 0.55, 2: 0.68, 3: 0.80, 4: 0.92, 5: 1.05}
LABEL = {"warmup": "Warm-up", "cooldown": "Cool-down", "recover": "Easy recovery", "steady": "Steady",
         "work": "Work"}
DEFAULT_CSS = 113.0  # s/100 m, when neither the profile nor the plan knows


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _zone(z: Any) -> int:
    return min(5, max(1, int(z))) if isinstance(z, int | float) and not isinstance(z, bool) else 2


def hr_zones(athlete: dict[str, Any]) -> tuple[dict[int, tuple[int, int]] | None, str | None]:
    """({zone: (low, high) bpm}, source) with source threshold | reserve | max, or (None, None)."""
    lthr, mx, rest = _num(athlete.get("threshold_hr")), _num(athlete.get("max_hr")), _num(athlete.get("resting_hr"))
    if lthr and 80 <= lthr <= 220:
        z = {k: (round(lthr * lo), round(lthr * hi)) for k, (lo, hi) in HR_LTHR.items()}
        if mx and mx > lthr:
            z[5] = (z[5][0], min(z[5][1], round(mx)))
        return z, "threshold"
    if mx and 100 <= mx <= 230 and rest and 25 <= rest < mx:
        return {k: (round(rest + (mx - rest) * lo), round(rest + (mx - rest) * hi)) for k, (lo, hi) in HR_RESERVE.items()}, "reserve"
    if mx and 100 <= mx <= 230:
        return {k: (round(mx * lo), round(mx * hi)) for k, (lo, hi) in HR_MAX.items()}, "max"
    return None, None


def css_of(athlete: dict[str, Any], plan_swim_pace: float | None = None) -> float:
    css = _num(athlete.get("swim_css"))
    if css and 50 <= css <= 240:
        return css
    if plan_swim_pace and 60 <= plan_swim_pace <= 260:
        return plan_swim_pace - 12  # the plan's easy swim pace is CSS + 12
    return DEFAULT_CSS


class _Ctx:
    def __init__(self, athlete: dict[str, Any], thr: float, swim_pace: float | None) -> None:
        self.hr, self.hr_source = hr_zones(athlete)
        ftp = _num(athlete.get("ftp_w"))
        self.ftp = ftp if ftp and 50 <= ftp <= 600 else None
        self.thr = thr
        self.css = css_of(athlete, swim_pace)


def _step(st: dict[str, Any], sport: str, ctx: _Ctx) -> dict[str, Any]:
    kind = str(st.get("type") or "steady")
    z = _zone(st.get("zone") if kind != "recover" else st.get("zone", 1))
    minutes = _num(st.get("minutes"))
    meters = _num(st.get("meters"))
    if sport == "swim" and meters and not minutes:
        lo, hi = SWIM_OFFSET[z]
        minutes = meters / 100 * (ctx.css + (lo + hi) / 2) / 60
    out: dict[str, Any] = {"type": kind, "label": LABEL.get(kind, "Steady"), "zone": z,
                           "minutes": round(minutes, 2) if minutes else None,
                           "meters": round(meters) if meters else None,
                           "rpe": RPE[z], "talk": TALK[z]}
    if ctx.hr and sport != "swim":
        lo, hi = ctx.hr[z]
        if sport == "bike":  # riding HR sits a little lower than running HR at the same effort
            lo, hi = lo - 5, hi - 5
        out["hr"] = [lo, hi]
    if sport == "run":
        f, s = PACE_ZONES[z]
        out["pace"] = [round(ctx.thr * f), round(ctx.thr * s)]
    if sport == "bike" and ctx.ftp:
        lo, hi = POWER_ZONES[z]
        out["power"] = [round(ctx.ftp * lo), round(ctx.ftp * hi)]
    if sport == "swim":
        lo, hi = SWIM_OFFSET[z]
        out["swim"] = [round(ctx.css + lo), round(ctx.css + hi)]
    if sport in CADENCE:
        lo, hi = CADENCE[sport][z]
        if kind in ("warmup", "cooldown", "recover") and z > 1:
            lo, hi = CADENCE[sport][z - 1]
        out["cadence"] = [lo, hi]
    return out


def _steps(steps: list[dict[str, Any]], sport: str, ctx: _Ctx) -> list[dict[str, Any]]:
    out = []
    for st in steps or []:
        if st.get("type") == "repeat":
            out.append({"type": "repeat", "reps": int(st.get("reps") or 1),
                        "steps": _steps(st.get("steps") or [], sport, ctx)})
        else:
            out.append(_step(st, sport, ctx))
    return out


def _walk(steps: list[dict[str, Any]], mult: int = 1):
    for st in steps:
        if st.get("type") == "repeat":
            yield from _walk(st["steps"], mult * int(st.get("reps") or 1))
        else:
            yield st, mult


def _summary(blocks: list[tuple[str, list[dict[str, Any]]]], hr_known: bool) -> dict[str, Any]:
    zone_min: dict[int, float] = {}
    total = stress = run_sec = run_km = hr_w = hr_min = 0.0
    for sport, steps in blocks:
        for st, mult in _walk(steps):
            m = (st.get("minutes") or 0) * mult
            total += m
            zone_min[st["zone"]] = zone_min.get(st["zone"], 0.0) + m
            stress += m / 60 * INTENSITY[st["zone"]] ** 2 * 100
            if sport == "run" and st.get("pace") and m:
                pace = sum(st["pace"]) / 2
                run_sec += m * 60
                run_km += m * 60 / pace
            if st.get("hr") and m:
                hr_w += m * sum(st["hr"]) / 2
                hr_min += m
    return {"minutes": round(total), "zones": {str(k): round(v) for k, v in sorted(zone_min.items()) if v >= 0.5},
            "stress": round(stress) if total else None,
            "run_pace": round(run_sec / run_km) if run_km else None,
            "avg_hr": round(hr_w / hr_min) if hr_known and hr_min else None}


def session_targets(s: dict[str, Any], athlete: dict[str, Any], thr: float,
                    swim_pace: float | None = None) -> dict[str, Any] | None:
    """{hr_source, steps | legs, summary} for a session with structure; None for rest / race /
    strength / unstructured sessions."""
    sport = s.get("sport")
    if sport in ("rest", "strength", "other", None) or s.get("kind") == "race":
        return None
    ctx = _Ctx(athlete, thr, swim_pace)
    out: dict[str, Any] = {"hr_source": ctx.hr_source, "ftp": ctx.ftp is not None}
    if sport == "brick":
        legs = [{"sport": lg.get("sport"), "steps": _steps(lg.get("steps") or [], str(lg.get("sport")), ctx)}
                for lg in s.get("legs") or [] if lg.get("sport") in ("bike", "run")]
        if not legs:
            return None
        out["legs"] = legs
        out["summary"] = _summary([(str(lg["sport"]), lg["steps"]) for lg in legs], ctx.hr is not None)
        return out
    steps = s.get("steps") or []
    if not steps and s.get("minutes"):
        steps = [{"type": "steady", "minutes": s["minutes"], "zone": 2}]
    if not steps:
        return None
    out["steps"] = _steps(steps, str(sport), ctx)
    out["summary"] = _summary([(str(sport), out["steps"])], ctx.hr is not None)
    return out


# --------------------------------------------------------------- how it went ---
def _secs(v: Any) -> float | None:
    if _num(v) is not None:
        return float(v)
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        parts = [float(p) for p in v.strip().split(":")]
    except ValueError:
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def how_it_went(s: dict[str, Any], targets: dict[str, Any] | None, act: dict[str, Any]) -> dict[str, Any] | None:
    """Compare a finished activity with the plan. {verdict, headline, lines, actual}; verdict is
    hit | short | long | hard | fast | slow | done (nothing to compare)."""
    if not act:
        return None
    sport = s.get("sport")
    summ = (targets or {}).get("summary") or {}
    planned = _num(summ.get("minutes")) or _num(s.get("minutes"))
    dur_s = _secs(act.get("moving_duration")) or _secs(act.get("duration"))
    mins = dur_s / 60 if dur_s else None
    actual: dict[str, Any] = {"minutes": round(mins) if mins else None, "km": _num(act.get("distance_km")),
                              "avg_hr": _num(act.get("avg_hr")), "cadence": _num(act.get("avg_cadence")),
                              "power": _num(act.get("avg_power_w"))}
    pace = None
    if sport == "run":
        pace = _secs(act.get("avg_pace_per_km"))
        if pace is None and actual["km"] and dur_s:
            pace = dur_s / actual["km"]
        actual["pace"] = round(pace) if pace else None
    lines: list[str] = []
    flags: list[str] = []
    easy = s.get("kind") in ("easy", "recovery", "long", "endurance", "technique", "shakeout")
    if planned and mins:
        r = mins / planned
        if r < 0.75:
            flags.append("short")
            lines.append(f"{round(mins)} of {round(planned)} planned minutes.")
        elif r > 1.3:
            flags.append("long")
            lines.append(f"{round(mins)} minutes, longer than the {round(planned)} planned.")
        else:
            lines.append(f"{round(mins)} minutes, right on the {round(planned)} planned.")
    hr_mid = _num(summ.get("avg_hr"))
    if hr_mid and actual["avg_hr"]:
        d = actual["avg_hr"] / hr_mid - 1
        if d > 0.07:
            flags.append("hard")
            lines.append(f"Average heart rate {round(actual['avg_hr'])} bpm, above the ~{round(hr_mid)} planned: that was harder than intended.")
        elif d < -0.10 and not easy:
            flags.append("slow")
            lines.append(f"Average heart rate {round(actual['avg_hr'])} bpm, below the ~{round(hr_mid)} planned.")
        else:
            lines.append(f"Average heart rate {round(actual['avg_hr'])} bpm, in range.")
    target_pace = _num(summ.get("run_pace"))
    if sport == "run" and pace and target_pace:
        d = (target_pace - pace) / target_pace  # >0: faster than planned
        if d > 0.08:
            flags.append("fast")
            lines.append("Faster than planned on average." + (" Easy days work best kept easy." if easy else ""))
        elif d < -0.10 and not easy:
            flags.append("slow")
            lines.append("Slower than planned on average; heat, hills or tired legs all count.")
        else:
            lines.append("Average pace on target.")
    cad_lo = cad_hi = None
    for st, _ in _walk((targets or {}).get("steps") or []):
        if st.get("cadence") and st.get("type") in ("work", "steady"):
            cad_lo = min(cad_lo or 999, st["cadence"][0])
            cad_hi = max(cad_hi or 0, st["cadence"][1])
    if actual["cadence"] and cad_lo and sport == "run":
        c = actual["cadence"]
        lines.append(f"Cadence {round(c)} steps/min" + (" (a little low: try slightly quicker, shorter steps)." if c < cad_lo - 5 else "."))
    order = ("short", "hard", "fast", "long", "slow")
    verdict = next((f for f in order if f in flags), "hit" if lines else "done")
    headline = {"short": "Shorter than planned", "hard": "Harder than planned", "fast": "Faster than planned",
                "long": "Longer than planned", "slow": "A bit slower than planned", "hit": "Right on target",
                "done": "Done"}[verdict]
    return {"verdict": verdict, "headline": headline, "lines": lines, "actual": actual}


__all__ = ["hr_zones", "session_targets", "how_it_went", "css_of"]
