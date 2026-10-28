"""Fit a weekly rhythm into an existing plan, in place.

Saving a weekly rhythm ("lift Mon Wed Fri, bike Tue Thu Sat") must not throw away the plan
someone already has: a coach's or imported plan, sessions they moved or edited by hand, trip
swaps, sick days, club runs. ``fit(plan, athlete, today)`` keeps every session (same id and
content) and only changes which day of its week it's on:

* Scope: from tomorrow to the day before the race week; the past, today and race week stay.
* Locked sessions never move: edited or added by hand, trip, sick, club run, event and race.
* Each sport's sessions go to that sport's rhythm days (the long one nearest the long day),
  the rest to open ("any") days, at most two a day, quality days kept apart from heavy
  strength days where possible. Rest days end up empty.
* Strength on (``coaching.strength_on``): a rhythm strength day with no strength session
  gets an opted-in strength workout (light before a long or quality day). Strength off:
  strength sessions rabbt added are removed; a coach's own strength sessions and ones the
  athlete added never are.
* Coach and imported plans (``origin`` set) never gain or lose endurance sessions; a session
  that doesn't fit stays on its original day, with a warning.

A moved session that was on Garmin is orphaned (its old workout is removed on the next sync
and the session re-uploads on its new day), exactly like a move made by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .planbuilder import (
    DAYS,
    QUALITY,
    RHYTHM_SPORTS,
    make_session,
    recompute_week,
    strength_minutes,
)

PER_DAY = 2
LOCK_KEYS = ("edited", "travel", "sick", "club_run", "event_id")
NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
         "sat": "Saturday", "sun": "Sunday"}
WORD = {"run": "run", "bike": "ride", "swim": "swim", "strength": "strength session", "other": "session"}


def _sport(s: dict[str, Any]) -> str:
    if s.get("kind") == "mobility":
        return "other"  # a short mobility session fits any day
    sp = "bike" if s["sport"] == "brick" else s["sport"]
    return sp if sp in RHYTHM_SPORTS else "other"


def locked(s: dict[str, Any]) -> bool:
    return s.get("kind") == "race" or any(s.get(k) for k in LOCK_KEYS)


def _wd(day: str) -> str:
    return DAYS[date.fromisoformat(day).weekday()]


def _circ(a: str, b: str) -> int:
    d = abs(DAYS.index(a) - DAYS.index(b))
    return min(d, 7 - d)


def effective_rhythm(athlete: dict[str, Any], *, keep_strength: bool = False) -> tuple[dict[str, list[str]], bool, bool]:
    """(rhythm without strength days unless opted in, strength on, strength asked).
    ``keep_strength``: a HYROX plan, whose lifting days take station work either way."""
    from .coaching import strength_on
    on = strength_on(athlete)
    raw = athlete.get("week_rhythm") if isinstance(athlete.get("week_rhythm"), dict) else {}
    out: dict[str, list[str]] = {}
    asked = False
    for d in DAYS:
        sp = [x for x in (raw.get(d) or []) if x in RHYTHM_SPORTS]
        if "strength" in sp and not on and not keep_strength:
            asked = True
            sp = [x for x in sp if x != "strength"]
        if sp:
            out[d] = sp
    return out, on, asked


def _rabbt_strength(s: dict[str, Any], coach_plan: bool) -> bool:
    """A strength session rabbt put in (safe to remove when strength is turned off)."""
    if s["sport"] != "strength" or s.get("kind") in ("mobility", "hyrox") or locked(s):
        return False  # HYROX station work is race training, never opt-in strength
    return bool(s.get("auto_strength")) or not coach_plan


def fit(plan: dict[str, Any], athlete: dict[str, Any], today: date,
        orphan: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Rearrange ``plan`` in place. Returns ``{"moved", "added", "removed", "warnings"}``."""
    rh, strength_on, asked = effective_rhythm(athlete, keep_strength=plan.get("race_kind") == "hyrox")
    coach_plan = bool(plan.get("origin"))
    first = (today + timedelta(days=1)).isoformat()
    race = plan.get("race_date") or "9999-12-31"
    long_day = athlete.get("long_day") if athlete.get("long_day") in DAYS else "sat"
    avail = {d for d in (athlete.get("available_days") or []) if d in DAYS}
    warnings: list[str] = []
    stuck: dict[str, int] = {}
    moved = added = removed = 0
    rest_clash: set[str] = set()

    for w in plan.get("weeks", []):
        now = today.isoformat()
        if not strength_on and now in w["days"] and now < race:
            # Strength turned off: today's rabbt strength session goes too (nothing else moves today).
            keep = []
            for s in w["days"][now]:
                if _rabbt_strength(s, coach_plan):
                    orphan(s)
                    removed += 1
                else:
                    keep.append(s)
            w["days"][now] = keep or [make_session("rest", "rest", 0)]
            recompute_week(w)
        days = sorted(d for d in w["days"] if first <= d < race)
        if not days or w.get("phase") == "race" or any(
                x.get("kind") == "race" for ss in w["days"].values() for x in ss):
            continue
        out: dict[str, list[dict[str, Any]]] = {d: [] for d in days}
        loose: list[tuple[str, dict[str, Any]]] = []
        for d in days:
            for s in w["days"][d]:
                if s["sport"] == "rest" and not locked(s):
                    continue  # rest markers are redrawn at the end
                if locked(s) or s["sport"] == "rest":
                    out[d].append(s)
                    if rh.get(_wd(d)) == ["rest"] and s["sport"] != "rest":
                        rest_clash.add(_wd(d))
                    continue
                if not strength_on and _rabbt_strength(s, coach_plan):
                    orphan(s)
                    removed += 1
                    continue
                loose.append((d, s))

        st_days = [d for d in days if "strength" in rh.get(_wd(d), [])] if strength_on else []
        heavy = set(st_days)

        def prio(item: tuple[str, dict[str, Any]]) -> tuple[int, int]:
            s = item[1]
            if s.get("kind") in ("long", "brick"):
                return (0, -int(s.get("minutes") or 0))
            if s["sport"] == "strength":
                return (1, 0)
            if s.get("kind") in QUALITY:
                return (2, -int(s.get("minutes") or 0))
            return (3, -int(s.get("minutes") or 0))

        for orig, s in sorted(loose, key=prio):
            sp = _sport(s)
            room = [d for d in days if len([x for x in out[d] if x["sport"] != "rest"]) < PER_DAY
                    and rh.get(_wd(d)) != ["rest"]]
            picked = [d for d in room if sp in rh.get(_wd(d), [])]
            open_ = [d for d in room if _wd(d) not in rh]  # no rhythm set: "any"
            pool = picked or open_
            if not pool and room and (sp == "other" or (not coach_plan and not any(sp in v for v in rh.values()))):
                pool = room  # no day picked for it and no open day: a day picked for something else
            if not pool:
                out[orig].append(s)  # nowhere it fits: it keeps its day
                stuck[sp] = stuck.get(sp, 0) + 1
                continue

            def cost(d: str, s: dict[str, Any] = s, sp: str = sp, orig: str = orig) -> tuple[float, ...]:
                same = sum(_sport(x) == sp for x in out[d])
                long_pen = _circ(_wd(d), long_day) if s.get("kind") in ("long", "brick") else 0
                near = 0
                if s.get("kind") in QUALITY or s.get("kind") in ("long", "brick"):
                    near = sum(abs((date.fromisoformat(d) - date.fromisoformat(h)).days) <= 1 for h in heavy if h != d)
                    near += sum(1 for x in sum((out.get(n, []) for n in _nbrs(d)), [])
                                if x.get("kind") in QUALITY)
                pref = 0 if (not avail or _wd(d) in avail or _wd(d) in rh) else 1
                load = len([x for x in out[d] if x["sport"] != "rest"])
                churn = abs((date.fromisoformat(d) - date.fromisoformat(orig)).days)
                return (same, long_pen, near, pref, load, churn, days.index(d))
            day = min(pool, key=cost)
            if day != orig:
                if s.get("garmin"):
                    orphan(s)
                    s.pop("garmin", None)
                moved += 1
            out[day].append(s)

        # Strength days: one opted-in strength workout each (none in race week, which is skipped).
        if strength_on:
            from .strength import workout
            for d in st_days:
                if any(x["sport"] == "strength" and x.get("kind") != "mobility" for x in out[d]):
                    continue
                if len([x for x in out[d] if x["sport"] != "rest"]) >= PER_DAY:
                    continue
                nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
                key_next = any(x.get("kind") in QUALITY or x.get("kind") in ("long", "brick")
                               for x in out.get(nxt, w["days"].get(nxt, [])))
                week_min = sum(int(x.get("minutes") or 0) for ss in w["days"].values() for x in ss
                               if x["sport"] in ("run", "bike", "swim", "brick"))
                m = strength_minutes(w.get("phase") or "base", bool(w.get("recovery")), week_min)
                new = make_session("strength", "strength", m, phase=w.get("phase") or "base")
                new["variant"] = "light" if key_next or w.get("phase") == "taper" else "heavy"
                new["rhythm"] = new["auto_strength"] = True
                r = workout(w.get("phase") or "base", plan.get("race_kind") or "run", new["variant"], m,
                            athlete.get("injuries"))
                new.update(exercises=r["exercises"], prehab=r["prehab"], detail=r["detail"], title=r["title"])
                out[d].append(new)
                added += 1

        for d in days:
            real = [x for x in out[d] if x["sport"] != "rest"]
            w["days"][d] = real or [x for x in out[d] if x["sport"] == "rest"][:1] or [make_session("rest", "rest", 0)]
        recompute_week(w)

    for wd in sorted(rest_clash, key=DAYS.index):
        warnings.append(f"Some {NAMES[wd]}s you set as rest still have a session you set up by hand, "
                        "a trip, a sick day or a club run on them, so rabbt left those.")
    for sp, n in sorted(stuck.items()):
        who = "Your coach's plan" if coach_plan else "Your plan"
        warnings.append(f"{who} has more {WORD[sp]}s than {sp if sp != 'other' else 'open'} days and open days "
                        f"in some weeks, so {n} stayed on {'its' if n == 1 else 'their'} original day"
                        f"{'' if n == 1 else 's'}.")
    if asked:
        warnings.append("You picked lifting days but strength workouts are off, so those days are open days. "
                        "Turn on strength workouts to get them.")
    plan["week_rhythm"] = rh
    plan["needs_strength_opt_in"] = asked
    plan["warnings"] = warnings
    return {"moved": moved, "added": added, "removed": removed, "warnings": warnings}


def _nbrs(d: str) -> list[str]:
    x = date.fromisoformat(d)
    return [(x - timedelta(days=1)).isoformat(), (x + timedelta(days=1)).isoformat()]


__all__ = ["fit", "locked", "effective_rhythm"]
