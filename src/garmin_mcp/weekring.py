"""Rabbit home "This week" ring: a small, finishable weekly goal, plus the Friday nudge.

Deterministic (no model, never Oura). The goal is the plan's sessions this Monday-Sunday
week when a plan has any (same counting as ``stats.adherence`` / ``progress.week_goal``:
non-rest planned sessions matched by ``weekplan.merge``), else ``ACTIVE_WEEK`` workouts (the
active-week streak). Each day gets a dot state from the same vocabulary as the app's
``WeekDots`` (done / partial / missed / planned / rest / extra / empty).

Closing the week (done >= target) shows "Week closed!"; the perfect-week XP and its moment
already come from ``progress.py`` / ``moments.py``.

Friday nudge (``nudge``): Friday from ``NUDGE_FROM`` local, outside quiet hours, one or two
sessions short with at least one day left, not on a planned recovery / taper / race week,
no pain flag or illness in check-ins from the last 7 days, and only when the athlete's
"Rabbit nudges" (``moments_push``) is on. It is a ``week_nudge`` moment (pushed through
``Moments`` like the countdown, so the daily push cap applies) keyed per week, so at most
once a week.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from .moments import Moments, action
from .planbuilder import iter_sessions, week_for
from .stats import ACTIVE_WEEK, _rows
from .weekplan import merge

NUDGE_DAY = 4  # Friday
NUDGE_FROM = dtime(17, 0)
REST_PHASES = frozenset({"taper", "race"})
UNWELL_DAYS = 7
_UNWELL = re.compile(r"\b(ill|illness|sick|flu|fever|covid|virus|injur(?:ed|y|ies))\b", re.I)
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _day_state(day: dict[str, Any]) -> str:
    work = [s for s in day["sessions"] if s.get("status") != "rest"]
    if work:
        done = sum(s.get("status") == "done" for s in work)
        if done == len(work):
            return "done"
        if done:
            return "partial"
        return "missed" if any(s.get("status") == "missed" for s in work) else "planned"
    if day["extra"]:
        return "extra"
    return "rest" if day["sessions"] else "empty"


def _more(n: int) -> str:
    word = WORDS.get(n, str(n))
    return f"{word} more {'closes' if n == 1 else 'close'} your week"


def _title(t: str) -> str:
    t = (t or "session").strip()
    return t[0].lower() + t[1:] if len(t) > 1 and t[1:2].islower() else t


def ring(plan: dict[str, Any] | None, acts: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Pure: this week's ring. ``acts`` = compact activities (``StatsService.activities``)."""
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    planned: dict[str, list[dict[str, Any]]] = {}
    for _, d, s in iter_sessions(plan or {}):
        if monday.isoformat() <= d <= sunday.isoformat() and not s.get("skipped"):  # plancal skip
            planned.setdefault(d, []).append({"id": s.get("id"), "sport": s.get("sport"), "title": s.get("title"),
                                              "minutes": s.get("minutes")})
    days = merge(monday, today, planned, acts)
    work = [(day, s) for day in days for s in day["sessions"] if s["status"] != "rest"]
    pw = week_for(plan, today) if plan else None
    rest_week = bool(pw and (pw.get("recovery") or (pw.get("phase") or "") in REST_PHASES))
    nxt = None
    if work:
        kind, unit = "plan", "session"
        done, target = sum(s["status"] == "done" for _, s in work), len(work)
        left = [(day, s) for day, s in work if s["status"] == "planned"]
        later = [x for x in left if x[0]["date"] > today.isoformat()] or left
        if later:
            day, s = later[0]
            nxt = {"date": day["date"], "title": s.get("title") or "Session", "sport": s.get("sport"),
                   "id": s.get("id"), "minutes": s.get("minutes")}
        can_still = len(left)
    else:
        kind, unit = "active", "workout"
        rows = [r for r in _rows(acts) if monday <= r["date"] <= today]
        done, target = len(rows), ACTIVE_WEEK
        trained_today = any(r["date"] == today for r in rows)
        can_still = (6 - today.weekday()) + (0 if trained_today else 1)
    remaining = max(0, target - done)
    closed = target > 0 and remaining == 0
    days_left = 6 - today.weekday()
    if closed:
        line = "Week closed!"
        sub = ("Perfect week: +100 XP lands Monday" if kind == "plan"
               else "Active week: your weekly streak grows")
    elif remaining > can_still:
        line, sub = f"{done} of {target} this week", "Every session still counts"
    else:
        line = f"{done} of {target} · {_more(remaining)}"
        sub = ""
    dots = []
    for i, day in enumerate(days):
        d = monday + timedelta(days=i)
        if kind == "plan":
            st = _day_state(day)
        else:
            st = "done" if day["extra"] else "empty"
        dots.append({"date": day["date"], "weekday": day["weekday"], "today": d == today, "state": st})
    return {"kind": kind, "unit": unit, "done": done, "target": target, "remaining": remaining,
            "closed": closed, "line": line, "sub": sub, "days": dots, "days_left": days_left,
            "week_start": monday.isoformat(), "rest_week": rest_week, "next": nxt,
            "phase": (pw or {}).get("phase")}


def unwell(checkins: list[dict[str, Any]] | None, today: date) -> bool:
    """A pain flag or illness words in a check-in from the last ``UNWELL_DAYS`` days."""
    since = (today - timedelta(days=UNWELL_DAYS - 1)).isoformat()
    for c in checkins or []:
        if not isinstance(c, dict) or not (since <= str(c.get("date") or "")[:10] <= today.isoformat()):
            continue
        if c.get("pain_flag"):
            return True
        text = " ".join([*(str(t) for t in c.get("tags") or []), str(c.get("summary") or "")])
        if _UNWELL.search(text):
            return True
    return False


def nudge_moment(r: dict[str, Any], today: date) -> dict[str, Any]:
    n = r["remaining"]
    unit = r["unit"] + ("" if n == 1 else "s")
    head = f"{WORDS.get(n, str(n)).capitalize()} more {unit} {'closes' if n == 1 else 'close'} your week."
    nxt = r.get("next")
    if nxt:
        d = date.fromisoformat(nxt["date"])
        who = ("Tonight's" if d == today else "Tomorrow's" if d == today + timedelta(days=1)
               else f"{WEEKDAY[d.weekday()]}'s")
        tail = f" {who} {_title(nxt['title'])} would {'do it' if n == 1 else 'be a start'}."
    else:
        tail = " Even 30 easy minutes this weekend counts."
    return {"type": "week_nudge", "key": f"weeknudge:{r['week_start']}",
            "text": ("💪 " + head + tail)[:140], "push_title": "Close your week",
            "actions": [action("plan", "Open plan")]}


def nudge(r: dict[str, Any] | None, *, local: datetime, checkins: list[dict[str, Any]] | None,
          push_on: bool) -> tuple[str, dict[str, Any] | None]:
    """Pure: (reason, moment or None). ``local`` = athlete-local now."""
    today = local.date()
    if not push_on:
        return "nudges_off", None
    if local.weekday() != NUDGE_DAY:
        return "not_friday", None
    if local.time() < NUDGE_FROM:
        return "too_early", None
    if Moments.quiet(local):
        return "quiet", None
    if r is None:
        return "no_ring", None
    if r["closed"]:
        return "closed", None
    if r["remaining"] not in (1, 2):
        return "too_far", None
    if r["days_left"] < 1:
        return "no_days", None
    if r["rest_week"]:
        return "rest_week", None
    if unwell(checkins, today):
        return "unwell", None
    return "ok", nudge_moment(r, today)


class WeekRing:
    """Gathers inputs for ``ring`` / ``nudge``; posts the nudge through ``Moments``."""

    def __init__(self, *, plan: Callable[[str], dict[str, Any] | None],
                 activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                 checkins: Callable[[str], list[dict[str, Any]]], profile: Callable[[str], dict[str, Any]],
                 now: Callable[[str], datetime], moments: Moments) -> None:
        self._plan, self._acts, self._checkins = plan, activities, checkins
        self._profile, self._now, self._moments = profile, now, moments
        # Optional: this week's mileage (plancal.PlanCal.week_miles), added as ``miles``.
        self.miles: Callable[[str], dict[str, Any] | None] | None = None

    def get(self, uid: str) -> dict[str, Any] | None:
        """None when Garmin can't be read (nothing honest to count)."""
        try:
            today, acts = self._acts(uid)
        except Exception:
            return None
        r = ring(self._plan(uid), acts, today)
        if self.miles is not None:
            try:
                r["miles"] = self.miles(uid)
            except Exception:  # mileage is extra: the ring still shows
                r["miles"] = None
        return r

    def check_nudge(self, uid: str) -> str:
        """From ``Moments.tick`` (outside quiet hours). Cheap until Friday 17:00; then at
        most one evaluation a day, and the moment key makes it once a week."""
        if uid.startswith("coach_"):
            return "skipped"
        local = self._now(uid)
        if local.weekday() != NUDGE_DAY or local.time() < NUDGE_FROM or Moments.quiet(local):
            return "not_now"
        push_on = self._profile(uid).get("moments_push", True) is not False
        if not push_on:
            return "nudges_off"
        if not self._moments._claim(uid, "weeknudge", local.date()):
            return "claimed"
        reason, m = nudge(self.get(uid), local=local, checkins=self._checkins(uid), push_on=push_on)
        if m is None:
            return reason
        return self._moments.post(uid, m)


__all__ = ["WeekRing", "ring", "nudge", "nudge_moment", "unwell", "NUDGE_FROM"]
