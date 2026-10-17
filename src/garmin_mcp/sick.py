"""Sick mode: pause or ease the plan while ill, then a gentle return.

Pure functions over a plan dict (``plans.PlanService`` wraps them in ``_edit``). Stored on the
plan: ``plan["sick"]`` while active::

    {"id", "start", "cover_end", "until": "better" | <expected last sick day>, "severity": "head" | "body",
     "rest_all": bool, "original": {day: [sessions as they were]}, "race_note": str | None}

``plan["sick_history"]``: past periods ``[{"start", "end", "severity"}]`` (streaks treat those days as
rest days). ``plan["sick_return"]``: the easy return after "I feel better"
``{"id", "start", "until", "days"}``.

Only the severity choice and dates are kept: no symptoms, no notes.

* **head** (above the neck: head cold, sniffles): each day keeps at most one short easy session
  (capped at ``HEAD_CAP`` minutes, no intensity); the athlete can pick ``rest_all``.
* **body** (fever, chest, body aches, stomach): every session becomes rest.

Days already past stay as they were. Races are never touched; a race within ``RACE_NEAR`` days
gets a short note. Ending ("I feel better") rebuilds the next ``min(RAMP_MAX, days sick)`` days as
an easy ramp (shorter first, no intensity), then the plan resumes as written: missed sessions are
never crammed back in. Undo restores the originals for the days still ahead.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from .planbuilder import PlanError, make_session, new_id, recompute_week, week_for

SEVERITIES = ("head", "body")
MAX_BACK_DAYS = 14       # "sick since" can be up to two weeks ago
DEFAULT_COVER = 3        # open-ended: today and the next 2 days, extended daily while still sick
EXTEND_DAYS = 2
MAX_COVER = 28
HEAD_CAP = 30            # minutes for a head-cold easy session
RAMP_MAX = 7
RACE_NEAR = 10
HISTORY_MAX = 20

SAFETY = ("Rest with a fever or chest symptoms. See a doctor if a fever lasts more than a few days, "
          "or with chest pain, trouble breathing or symptoms getting worse.")
HEAD_LINE = "Head cold: a short easy session is fine if you feel up to it. Skip it if not."
BODY_LINE = "Fever or below-the-neck symptoms: rest fully until they're gone."


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(a: date, b: date) -> list[str]:
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _keep(sick: dict[str, Any], plan: dict[str, Any], day: str) -> None:
    if day not in sick["original"]:
        w = week_for(plan, _d(day))
        if w is not None:
            sick["original"][day] = [dict(x) for x in w["days"].get(day, [])]


def _rest(sick_id: str) -> dict[str, Any]:
    r = make_session("rest", "rest", 0)
    r["title"], r["sick"], r["edited"] = "Rest: sick", sick_id, True
    r["detail"] = "Rest up. Sleep, fluids, easy food. Training waits."
    return r


def _easy(x: dict[str, Any], sick_id: str, swim_pace: float, phase: str) -> dict[str, Any]:
    sport = "run" if x["sport"] == "brick" else x["sport"]
    if sport == "strength":
        new = make_session("strength", "mobility", 20, phase=phase)
    elif sport == "swim":
        new = make_session("swim", "easy", min(HEAD_CAP, int(x.get("minutes") or HEAD_CAP)), swim_pace=swim_pace, phase=phase)
    else:
        sport = sport if sport in ("run", "bike") else "run"
        new = make_session(sport, "easy", min(HEAD_CAP, int(x.get("minutes") or HEAD_CAP)), phase=phase)
    new["id"], new["sick"], new["edited"] = x["id"], sick_id, True
    new["detail"] = f"Head cold: short and easy, or skip it. {new.get('detail') or ''}".strip()[:400]
    return new


def _apply_days(plan: dict[str, Any], sick: dict[str, Any], days: list[str], today: date,
                orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> int:
    """Rework ``days`` (today onward only). Returns how many sessions changed."""
    t = today.isoformat()
    swim_pace = plan.get("swim_pace", 125.0)
    changed, touched = 0, set()
    for day in days:
        if day < t:
            continue
        w = week_for(plan, _d(day))
        if w is None or day not in w["days"]:
            continue
        ss = w["days"][day]
        if any(x.get("kind") == "race" for x in ss):
            continue
        work = [x for x in ss if x["sport"] != "rest" and not x.get("sick")]
        if not work:
            continue
        _keep(sick, plan, day)
        for x in work:
            orphan(plan, x)
        if sick["severity"] == "body" or sick.get("rest_all"):
            w["days"][day] = [_rest(sick["id"])]
        else:
            first = max(work, key=lambda x: int(x.get("minutes") or 0))
            w["days"][day] = [_easy(first, sick["id"], swim_pace, w.get("phase") or "base")]
        changed += len(work)
        touched.add(w["start"])
    for w in plan["weeks"]:
        if w["start"] in touched:
            recompute_week(w)
    return changed


def _race_note(plan: dict[str, Any], today: date, until: date) -> str | None:
    horizon = (until + timedelta(days=RACE_NEAR)).isoformat()
    races = [d for w in plan.get("weeks", []) for d, ss in w["days"].items()
             if d >= today.isoformat() and d <= horizon and any(x.get("kind") == "race" for x in ss)]
    if not races and plan.get("race_date") and today.isoformat() <= plan["race_date"] <= horizon:
        races = [plan["race_date"]]
    if not races:
        return None
    rd = _d(min(races))
    n = (rd - today).days
    when = "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"
    return (f"Your race is {when}. Fitness holds over a few sick days. Get well first; decide on racing "
            "once you're symptom-free, and skip it with a fever or chest symptoms.")


def preview(plan: dict[str, Any], body: dict[str, Any], today: date) -> dict[str, Any]:
    """What starting sick mode would change, without changing anything."""
    trial = {**plan, "weeks": [{**w, "days": {d: [dict(x) for x in ss] for d, ss in w["days"].items()}}
                               for w in plan.get("weeks", [])]}
    trial.pop("sick", None)
    sick = start(trial, body, today, lambda p, s: None)
    rest = sum(1 for d in sick["original"] for x in (week_for(trial, _d(d)) or {"days": {}})["days"].get(d, [])
               if x.get("sick") and x["sport"] == "rest")
    easy = sum(1 for d in sick["original"] for x in (week_for(trial, _d(d)) or {"days": {}})["days"].get(d, [])
               if x.get("sick") and x["sport"] != "rest")
    n = sum(len([x for x in ss if x["sport"] != "rest"]) for ss in sick["original"].values())
    return {"sessions": n, "rest_days": rest, "easy_days": easy, "through": sick["cover_end"],
            "race_note": sick.get("race_note")}


def _parse(body: dict[str, Any], today: date) -> tuple[str, date, date | None, bool]:
    sev = body.get("severity")
    if sev not in SEVERITIES:
        raise PlanError("Pick how you're feeling: head cold, or fever / chest / body aches / stomach.")
    try:
        st = _d(str(body.get("start") or today.isoformat()))
    except ValueError:
        raise PlanError("Pick the day you got sick.") from None
    if st > today:
        st = today
    if (today - st).days > MAX_BACK_DAYS:
        raise PlanError("Sick mode can start up to two weeks back.")
    until: date | None = None
    if body.get("until"):
        try:
            until = _d(str(body["until"]))
        except ValueError:
            raise PlanError("Pick the day you expect to feel better.") from None
        if until < today:
            raise PlanError("That day has already passed.")
        if (until - today).days > MAX_COVER:
            raise PlanError("Sick mode covers up to four weeks at a time.")
    return sev, st, until, body.get("rest_all") is True


def start(plan: dict[str, Any], body: dict[str, Any], today: date,
          orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> dict[str, Any]:
    """Start (or, when already on, change) sick mode. Returns the sick record."""
    sev, st, until, rest_all = _parse(body, today)
    prev = plan.get("sick")
    if prev is not None:  # changing severity/dates: put the originals back, then redo
        _restore(plan, prev, today, orphan)
        st = min(st, _d(prev["start"]))
    cover_end = until or (today + timedelta(days=DEFAULT_COVER - 1))
    sick = {"id": (prev or {}).get("id") or "s" + new_id()[:8], "start": st.isoformat(),
            "cover_end": cover_end.isoformat(), "until": until.isoformat() if until else "better",
            "severity": sev, "rest_all": rest_all, "original": {}, "race_note": None}
    _apply_days(plan, sick, _days(today, cover_end), today, orphan)
    sick["race_note"] = _race_note(plan, today, cover_end)
    plan["sick"] = sick
    plan.pop("sick_return", None)
    return sick


def extend(plan: dict[str, Any], today: date, days: int,
           orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> dict[str, Any]:
    sick = plan.get("sick")
    if sick is None:
        raise PlanError("Sick mode isn't on.")
    days = max(1, min(14, int(days)))
    old_end = _d(sick["cover_end"])
    new_end = max(old_end, today) + timedelta(days=days)
    if (new_end - _d(sick["start"])).days > MAX_COVER + MAX_BACK_DAYS:
        raise PlanError("That's a long time to be sick. Check in with a doctor, then rebuild your plan when you're ready.")
    _apply_days(plan, sick, _days(max(old_end + timedelta(days=1), today), new_end), today, orphan)
    sick["cover_end"] = new_end.isoformat()
    if sick["until"] != "better":
        sick["until"] = new_end.isoformat()
    sick["race_note"] = _race_note(plan, today, new_end)
    return sick


def _restore(plan: dict[str, Any], sick: dict[str, Any], today: date,
             orphan: Callable[[dict[str, Any], dict[str, Any]], None],
             skip: set[str] | None = None) -> set[str]:
    """Put the originals back on days from today on (except ``skip``). Returns restored days."""
    t = today.isoformat()
    out, touched = set(), set()
    for day, sessions in sick["original"].items():
        if day < t or (skip and day in skip):
            continue
        w = week_for(plan, _d(day))
        if w is None:
            continue
        keep = []
        for x in w["days"].get(day, []):
            if x.get("sick") == sick["id"]:
                orphan(plan, x)
            elif x["sport"] != "rest":
                keep.append(x)
        kept = {x["id"] for x in keep}
        back = [{k: v for k, v in x.items() if k != "garmin"} for x in sessions
                if x["sport"] != "rest" and x["id"] not in kept]
        w["days"][day] = (back + keep) or [make_session("rest", "rest", 0)]
        touched.add(w["start"])
        out.add(day)
    for w in plan["weeks"]:
        if w["start"] in touched:
            recompute_week(w)
    return out


def undo(plan: dict[str, Any], today: date, orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> None:
    """Turn sick mode off as if it never happened (for the days ahead)."""
    sick = plan.get("sick")
    if sick is None:
        raise PlanError("Sick mode isn't on.")
    _restore(plan, sick, today, orphan)
    plan.pop("sick", None)


INTENSE = {"tempo", "threshold", "vo2", "racepace", "css", "brick", "openers", "strides"}


def _ramp_session(x: dict[str, Any], i: int, n: int, rid: str, swim_pace: float, phase: str) -> dict[str, Any]:
    """Day ``i`` (0-based) of an ``n``-day return: easy, from about half length up to full (max 60)."""
    if x["sport"] == "rest" or x.get("kind") == "race":
        return x
    share = 0.5 + 0.5 * (i + 1) / (n + 1)
    orig = int(x.get("minutes") or 40)
    minutes = max(20, min(60, int(round(orig * share / 5) * 5)))
    sport = "run" if x["sport"] == "brick" else x["sport"]
    if sport == "strength":
        new = make_session("strength", "strength" if i >= n // 2 else "mobility", min(orig, 30), phase=phase)
    else:
        kind = "easy" if sport in ("run", "bike", "swim") else (x.get("kind") or "easy")
        if sport == "swim":
            kind = "easy"
        new = make_session(sport, kind, minutes, swim_pace=swim_pace, phase=phase)
    new["id"], new["sick_return"], new["edited"] = x["id"], rid, True
    new["detail"] = (f"Easing back in after being sick (day {i + 1} of {n}): easy effort, stop if you feel worse. "
                     f"{new.get('detail') or ''}").strip()[:400]
    return new


def better(plan: dict[str, Any], today: date, orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> dict[str, Any]:
    """"I feel better": end sick mode and build the easy return. Returns the return record."""
    sick = plan.get("sick")
    if sick is None:
        raise PlanError("Sick mode isn't on.")
    st = _d(sick["start"])
    days_sick = max(1, (today - st).days)
    n = min(RAMP_MAX, max(2, days_sick))
    ramp = _days(today, today + timedelta(days=n - 1))
    # Days ahead: originals back first (everything after the ramp resumes as written) ...
    _restore(plan, sick, today, orphan)
    # ... then the ramp reworks the next n days, whatever is on them.
    rid = "r" + new_id()[:8]
    swim_pace = plan.get("swim_pace", 125.0)
    touched = set()
    for i, day in enumerate(ramp):
        w = week_for(plan, _d(day))
        if w is None or day not in w["days"]:
            continue
        ss = w["days"][day]
        if any(x.get("kind") == "race" for x in ss):
            continue
        work = [x for x in ss if x["sport"] != "rest"]
        if not work:
            continue
        for x in work:
            orphan(plan, x)
        # One session a day while easing back; the longest one, made easy.
        first = max(work, key=lambda x: int(x.get("minutes") or 0))
        w["days"][day] = [_ramp_session(first, i, n, rid, swim_pace, w.get("phase") or "base")]
        touched.add(w["start"])
    for w in plan["weeks"]:
        if w["start"] in touched:
            recompute_week(w)
    end = today - timedelta(days=1)
    hist = plan.setdefault("sick_history", [])
    hist.append({"start": sick["start"], "end": max(st, end).isoformat(), "severity": sick["severity"]})
    plan["sick_history"] = hist[-HISTORY_MAX:]
    plan.pop("sick", None)
    ret = {"id": rid, "start": today.isoformat(), "until": ramp[-1], "days": n}
    plan["sick_return"] = ret
    return ret


def tick(plan: dict[str, Any], today: date, orphan: Callable[[dict[str, Any], dict[str, Any]], None]) -> str:
    """Daily: keep open-ended sick mode covering the days ahead; an expected end that has passed
    starts the easy return. Clears a finished return. Returns what happened."""
    ret = plan.get("sick_return")
    if ret and ret.get("until", "") < today.isoformat():
        plan.pop("sick_return", None)
    sick = plan.get("sick")
    if sick is None:
        return "cleared" if ret and "sick_return" not in plan else "none"
    if sick["until"] != "better" and sick["until"] < today.isoformat():
        better(plan, today, orphan)
        return "returned"
    if sick["until"] == "better" and sick["cover_end"] < (today + timedelta(days=1)).isoformat():
        extend(plan, today, EXTEND_DAYS, orphan)
        return "extended"
    return "none"


def sick_days(plan: dict[str, Any] | None, today: date) -> set[date]:
    """Days counted as sick (past and today): streaks treat them as rest days."""
    out: set[date] = set()
    if not plan:
        return out
    periods = [(h.get("start"), h.get("end")) for h in plan.get("sick_history") or []]
    s = plan.get("sick")
    if s:
        periods.append((s["start"], min(s["cover_end"], today.isoformat())))
    for a, b in periods:
        try:
            da, db = _d(str(a)), min(_d(str(b)), today)
        except ValueError:
            continue
        for i in range(max(0, (db - da).days + 1)):
            out.add(da + timedelta(days=i))
    return out


def view(plan: dict[str, Any] | None, today: date) -> dict[str, Any]:
    """What the app shows (banner, sheet): no originals."""
    if not plan:
        return {"active": False, "returning": None}
    s = plan.get("sick")
    ret = plan.get("sick_return")
    out: dict[str, Any] = {"active": s is not None, "returning": None, "safety": SAFETY}
    if s is not None:
        day_n = (today - _d(s["start"])).days + 1
        changed = sum(len([x for x in ss if x["sport"] != "rest"]) for d, ss in s["original"].items()
                      if d >= today.isoformat())
        out |= {"id": s["id"], "start": s["start"], "day": max(1, day_n), "severity": s["severity"],
                "rest_all": bool(s.get("rest_all")), "until": s["until"], "through": s["cover_end"],
                "changed": changed, "race_note": s.get("race_note"),
                "line": BODY_LINE if s["severity"] == "body" or s.get("rest_all") else HEAD_LINE}
    if ret and ret.get("until", "") >= today.isoformat():
        i = (today - _d(ret["start"])).days + 1
        out["returning"] = {"day": max(1, i), "days": ret["days"], "until": ret["until"]}
    return out


def ai_line(plan: dict[str, Any] | None, today: date) -> str | None:
    """One line for Rabbit's context: severity and dates only."""
    v = view(plan, today)
    if v.get("active"):
        what = ("a head cold (above the neck)" if v["severity"] == "head"
                else "fever or below-the-neck symptoms")
        mode = "short easy sessions only" if v["severity"] == "head" and not v["rest_all"] else "full rest"
        return (f"Sick mode is ON: {what}, day {v['day']} (since {v['start']}). The plan is on {mode} through "
                f"{v['through']}. Be warm and brief, encourage rest, no training pressure, never diagnose; "
                "suggest a doctor for fever lasting days, chest pain, trouble breathing or worsening symptoms. "
                "When they feel better, point them to 'I feel better' in the app (it builds an easy return).")
    r = v.get("returning")
    if r:
        return (f"Easing back after being sick: day {r['day']} of {r['days']} of an easy return (through {r['until']}). "
                "Keep everything easy; don't add back missed sessions.")
    return None


def checkin_moment(sick: dict[str, Any], today: date) -> dict[str, Any] | None:
    """One gentle check-in after 2-3 days."""
    if (today - _d(sick["start"])).days < 2:
        return None
    return {"type": "sick_checkin", "key": f"sick:{sick['id']}",
            "text": "🛌 How are you feeling? When you're better, tap and Rabbit eases you back in. No catching up needed.",
            "actions": [{"id": "sick", "label": "I feel better"}]}


__all__ = ["start", "extend", "undo", "better", "tick", "preview", "view", "sick_days", "ai_line",
           "checkin_moment", "SEVERITIES", "SAFETY"]
