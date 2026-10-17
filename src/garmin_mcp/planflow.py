"""Plan review, adjust and the weekly check-in (pure functions; plans.py stores, webapp routes).

* ``plan_summary``: what a plan prescribes at a glance, for the setup Review screen and
  "Adjust my plan": weeks, phases with dates and hours, the weekly hours ramp, the first two
  weeks' sessions and the long-session progression.
* ``plan_diff``: what an adjustment would change from today on (weekly hours before/after
  and the first changed days), shown before anything is applied.
* ``checkin_proposal``: the end-of-week "How was this week?" answers turned into concrete
  changes to next week, in adjust.propose's change format (``plans.apply_adjustment``):
  lighter week when energy is low, soreness is high or there's less time; sessions on days
  the athlete can't train moved to a free day (or dropped when there's none); the long
  session moved to the day they pick. More time never adds training: plans build slowly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from .planbuilder import DAYS, QUALITY, iter_sessions, week_for

LONG_KINDS = ("long", "brick")
ENERGY = ("low", "ok", "great")
SORENESS = ("none", "some", "a_lot")
TIME = ("less", "same", "more")
LIGHTER = 0.8


def _minutes(s: dict[str, Any]) -> int:
    m = s.get("minutes")
    if isinstance(m, int | float) and m:
        return int(m)
    return int(sum(int(lg.get("minutes") or 0) for lg in s.get("legs") or []))


def _work(ss: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in ss if s.get("sport") != "rest"]


def week_hours(w: dict[str, Any]) -> float:
    return round(sum(_minutes(s) for ss in w["days"].values() for s in _work(ss)) / 60, 1)


def plan_summary(plan: dict[str, Any], today: date) -> dict[str, Any]:
    weeks = plan.get("weeks") or []
    phases: list[dict[str, Any]] = []
    for w in weeks:
        last = phases[-1] if phases else None
        end = (date.fromisoformat(w["start"]) + timedelta(days=6)).isoformat()
        if last and last["phase"] == w["phase"]:
            last["to"], last["weeks"] = end, last["weeks"] + 1
            last["hours_to"] = w.get("hours") or week_hours(w)
        else:
            h = w.get("hours") or week_hours(w)
            phases.append({"phase": w["phase"], "from": w["start"], "to": end, "weeks": 1,
                           "hours_from": h, "hours_to": h, "focus": w.get("focus") or ""})
    t = today.isoformat()
    first_two: list[dict[str, Any]] = []
    for w in weeks:
        for d in sorted(w["days"]):
            if d < t or len(first_two) >= 14:
                continue
            first_two.append({"date": d, "sessions": [
                {"sport": s["sport"], "kind": s.get("kind"), "title": s.get("title"), "minutes": _minutes(s)}
                for s in _work(w["days"][d])]})
    long: list[int] = []
    for w in weeks:
        ms = [_minutes(s) for ss in w["days"].values() for s in ss if s.get("kind") in LONG_KINDS]
        long.append(max(ms) if ms else 0)
    first = next((x for x in first_two if x["sessions"]), None)
    return {"weeks": len(weeks), "race_date": plan.get("race_date"), "start": plan.get("first_day") or plan.get("start"),
            "start_hours": plan.get("start_hours"), "peak_hours": plan.get("peak_hours"), "level": plan.get("level"),
            "start_from": plan.get("start_from"), "note": plan.get("note"),
            "phases": phases, "hours": [w.get("hours") or week_hours(w) for w in weeks],
            "long_minutes": long, "first_two_weeks": first_two,
            "first_session": ({"date": first["date"], **first["sessions"][0]} if first else None)}


def _by_week(plan: dict[str, Any] | None) -> dict[str, float]:
    return {w["start"]: (w.get("hours") or week_hours(w)) for w in (plan or {}).get("weeks", [])}


def _day_line(ss: list[dict[str, Any]]) -> str:
    work = _work(ss)
    return " + ".join(f"{s.get('title')} {_minutes(s)}'" for s in work) if work else "Rest"


def plan_diff(old: dict[str, Any] | None, new: dict[str, Any], today: date, *, limit: int = 8) -> dict[str, Any]:
    """Weekly hours before/after (from this week on) and the first days that change."""
    t = today.isoformat()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    a, b = _by_week(old), _by_week(new)
    weeks = [{"start": k, "before": a.get(k), "after": b.get(k)} for k in sorted(set(a) | set(b)) if k >= monday]
    changed_weeks = [x for x in weeks if x["before"] != x["after"]]
    days_a = {d: ss for w in (old or {}).get("weeks", []) for d, ss in w["days"].items()}
    days_b = {d: ss for w in new.get("weeks", []) for d, ss in w["days"].items()}
    days: list[dict[str, Any]] = []
    for d in sorted(set(days_a) | set(days_b)):
        if d < t:
            continue
        la, lb = _day_line(days_a.get(d, [])), _day_line(days_b.get(d, []))
        if la != lb:
            days.append({"date": d, "before": la, "after": lb})
    return {"weeks": weeks[:30], "changed_weeks": len(changed_weeks), "days": days[:limit], "changed_days": len(days),
            "race_date": {"before": (old or {}).get("race_date"), "after": new.get("race_date")},
            "peak_hours": {"before": (old or {}).get("peak_hours"), "after": new.get("peak_hours")}}


# --------------------------------------------------------- weekly check-in --
def clean_answers(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("answers")
    out: dict[str, Any] = {}
    for k, allowed in (("energy", ENERGY), ("soreness", SORENESS), ("time", TIME)):
        v = raw.get(k)
        if v not in (None, ""):
            if v not in allowed:
                raise ValueError(k)
            out[k] = v
    off = raw.get("off_days") or []
    if not isinstance(off, list) or any(x not in DAYS for x in off):
        raise ValueError("off_days")
    out["off_days"] = [d for d in DAYS if d in off]
    ld = raw.get("long_day")
    if ld not in (None, ""):
        if ld not in DAYS:
            raise ValueError("long_day")
        out["long_day"] = ld
    return out


def next_week(plan: dict[str, Any], today: date) -> dict[str, Any] | None:
    """The week a check-in plans for: next week (on a Monday, the week starting today)."""
    return week_for(plan, today + timedelta(days=(7 - today.weekday()) % 7))


def _view(s: dict[str, Any]) -> dict[str, Any]:
    return {"title": s.get("title"), "sport": s["sport"], "kind": s.get("kind"), "minutes": _minutes(s) or None}


def _r5(m: float) -> int:
    return max(15, int(round(m / 5.0) * 5))


def checkin_proposal(plan: dict[str, Any] | None, today: date, answers: dict[str, Any]) -> dict[str, Any]:
    if not plan:
        return {"status": "none"}
    w = next_week(plan, today)
    if w is None or w["phase"] == "race":
        return {"status": "ok", "reasons": ["Race week: the plan stays as it is."], "changes": []}
    changes: list[dict[str, Any]] = []
    reasons: list[str] = []
    days = sorted(w["days"])
    wd = {d: DAYS[date.fromisoformat(d).weekday()] for d in days}
    taken: set[str] = set()

    # 1. Days they can't train: move what's there to a free day, else drop easy sessions.
    off = set(answers.get("off_days") or [])
    longs = {d for d in days if any(s.get("kind") in LONG_KINDS + ("race",) for s in w["days"][d])}
    free = [d for d in days if wd[d] not in off and not _work(w["days"][d])]
    for d in days:
        if wd[d] not in off:
            continue
        for s in _work(w["days"][d]):
            if s.get("kind") == "race":
                continue
            spot = None
            for f in free:
                fd = date.fromisoformat(f)
                near = {(fd + timedelta(days=o)).isoformat() for o in (-1, 1)}
                hard = s.get("kind") in QUALITY or s.get("kind") in LONG_KINDS
                if hard and near & longs:
                    continue
                spot = f
                break
            if spot:
                free.remove(spot)
                changes.append({"session_id": s["id"], "date": spot, "action": "relocate", "from": _view(s), "to": _view(s),
                                "why": f"You can't train on {DAYS_LONG[wd[d]]}; {DAYS_LONG[wd[spot]]} is free."})
            else:
                changes.append({"session_id": s["id"], "date": d, "action": "rest", "from": _view(s), "to": _view(s) | {"minutes": None},
                                "why": f"You can't train on {DAYS_LONG[wd[d]]} and there's no free day for it, so it's dropped."})
            taken.add(s["id"])
    if off:
        reasons.append(f"Not training on {', '.join(DAYS_LONG[x] for x in DAYS if x in off)} next week.")

    # 2. The long session on the day they picked (if that day is free or easy).
    ld = answers.get("long_day")
    if ld and ld not in off:
        target = next((d for d in days if wd[d] == ld), None)
        long_s = next(((d, s) for d in days for s in _work(w["days"][d]) if s.get("kind") in LONG_KINDS and s["id"] not in taken), None)
        if target and long_s and long_s[0] != target and not any(s.get("kind") in QUALITY for s in _work(w["days"][target])):
            changes.append({"session_id": long_s[1]["id"], "date": target, "action": "relocate", "from": _view(long_s[1]),
                            "to": _view(long_s[1]), "why": f"Your long session on {DAYS_LONG[ld]}, as you asked."})
            taken.add(long_s[1]["id"])
            reasons.append(f"Long session moves to {DAYS_LONG[ld]}.")

    # 3. Lighter week: low energy, a lot of soreness or less time.
    why = []
    if answers.get("energy") == "low":
        why.append("energy was low")
    if answers.get("soreness") == "a_lot":
        why.append("you're quite sore")
    if answers.get("time") == "less":
        why.append("you have less time")
    if why:
        eased_hard = False
        for d in days:
            for s in _work(w["days"][d]):
                if s.get("kind") == "race" or not _minutes(s):
                    continue
                to = _view(s) | {"minutes": _r5(_minutes(s) * LIGHTER)}
                action = "shorten"
                if not eased_hard and s.get("kind") in QUALITY and (answers.get("energy") == "low" or answers.get("soreness") == "a_lot"):
                    to["kind"] = "easy"
                    action = "ease"
                    eased_hard = True
                if to["minutes"] == _minutes(s) and to.get("kind") == s.get("kind"):
                    continue
                ch = next((c for c in changes if c["session_id"] == s["id"]), None)
                if ch and ch["action"] == "rest":
                    continue
                if ch:  # moved and lighter: keep the move, carry the new length/kind
                    ch["to"] = to
                    ch["why"] += " About 20% shorter too."
                    continue
                changes.append({"session_id": s["id"], "date": d, "action": action, "from": _view(s), "to": to,
                                "why": "About 20% shorter" + (", and easy instead of hard" if action == "ease" else "") + f" because {' and '.join(why)}."})
        reasons.append(f"Next week about 20% lighter because {' and '.join(why)}.")
    if answers.get("time") == "more":
        reasons.append("More time is great, but the plan keeps building slowly. Use it for an extra easy walk, ride or mobility.")
    if not changes:
        return {"status": "ok", "reasons": reasons or ["Sounds like a good week. Next week stays as planned."], "changes": []}
    return {"status": "suggest", "id": proposal_id(plan, changes), "week_start": w["start"], "reasons": reasons, "changes": changes}


DAYS_LONG = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
             "sat": "Saturday", "sun": "Sunday"}


def proposal_id(plan: dict[str, Any], changes: list[dict[str, Any]]) -> str:
    ids = {c["session_id"] for c in changes}
    now = sorted((s["id"], d, s.get("minutes"), s.get("kind"), s["sport"]) for _, d, s in iter_sessions(plan) if s["id"] in ids)
    return hashlib.sha256(json.dumps([now, changes], sort_keys=True, default=str).encode()).hexdigest()[:16]


def checkin_due(plan: dict[str, Any] | None, today: date, answered: dict[str, Any]) -> dict[str, Any]:
    """Friday to Monday the "How was this week?" card shows once per plan week."""
    if not plan:
        return {"due": False}
    w = week_for(plan, today) if today.weekday() >= 4 else week_for(plan, today - timedelta(days=1))
    if w is None or w["phase"] == "race" or today.weekday() not in (4, 5, 6, 0):
        return {"due": False}
    return {"due": w["start"] not in (answered or {}), "week_start": w["start"]}


__all__ = ["plan_summary", "plan_diff", "clean_answers", "checkin_proposal", "checkin_due", "next_week", "week_hours"]
