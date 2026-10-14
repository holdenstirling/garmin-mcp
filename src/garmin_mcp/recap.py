"""Weekly recap: a Monday-start week in review, plus next week's focus.

Pure ``build()`` over compact activities, the built plan (if any) and the progress
ledger (``Progress.ledger``: ``xp_by_week`` and ``badge_dates``). ``RecapService``
brings the XP ledger up to date first (so a Sunday push counts this week's workouts even
if the app wasn't opened), then builds. No model call.

Numbers: XP gained that week, workouts / hours / active days (multisport legs count
once), the day streak at the end of the week (or today, for the current week), plan
adherence (done / planned sessions that week), badges first earned that week, the best
(longest) workout, level progress, and next week's focus: the plan's phase/focus and its
2-3 key sessions (long, brick, race or quality), or a simple target without a plan.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .planbuilder import QUALITY, week_for
from .progress import level_view, week_key
from .stats import BADGES, _rows, _streaks, plan_rest_days
from .weekplan import merge

if TYPE_CHECKING:
    from .agent import Agent

BROWSE_WEEKS = 8
KEY_KINDS = {"long", "brick", "race"}


class RecapError(ValueError):
    pass


def default_week(today: date) -> date:
    """Sunday: this week (it's nearly done). Any other day: the last full week."""
    monday = today - timedelta(days=today.weekday())
    return monday if today.weekday() == 6 else monday - timedelta(days=7)


def parse_week(raw: str | None, today: date) -> date:
    if not raw:
        return default_week(today)
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        raise RecapError("week must be YYYY-MM-DD") from None
    start = d - timedelta(days=d.weekday())
    this_monday = today - timedelta(days=today.weekday())
    if start > this_monday or start < this_monday - timedelta(weeks=BROWSE_WEEKS - 1):
        raise RecapError(f"Recaps cover the last {BROWSE_WEEKS} weeks.")
    return start


def _planned(plan: dict[str, Any] | None, start: date) -> dict[str, Any] | None:
    w = week_for(plan, start) if plan else None
    if w is None:
        return None
    return {"week": w, "days": {d: [{"sport": s["sport"], "title": s["title"], "minutes": s.get("minutes"),
                                     "kind": s.get("kind"), "id": s.get("id")} for s in ss]
                                for d, ss in w["days"].items()}}


def _key_sessions(w: dict[str, Any]) -> list[dict[str, Any]]:
    ss = [(d, s) for d, xs in sorted(w["days"].items()) for s in xs if s.get("sport") != "rest"]
    key = [(d, s) for d, s in ss if s.get("kind") in KEY_KINDS or s.get("kind") in QUALITY]
    if len(key) < 2:  # fill with the longest of the rest
        rest = sorted((x for x in ss if x not in key), key=lambda x: -(x[1].get("minutes") or 0))
        key += rest[: 2 - len(key)]
    key = sorted(key, key=lambda x: x[0])[:3]
    return [{"date": d, "title": s.get("title") or "Session", "sport": s.get("sport"), "kind": s.get("kind"),
             "minutes": s.get("minutes")} for d, s in key]


def build(*, start: date, today: date, acts: list[dict[str, Any]], plan: dict[str, Any] | None,
          ledger: dict[str, Any]) -> dict[str, Any]:
    end = start + timedelta(days=6)
    upto = min(end, today)
    rows = [r for r in _rows(acts) if r["date"] <= today]
    week = [r for r in rows if start <= r["date"] <= end]
    minutes = sum(r["min"] for r in week)
    best = max(week, key=lambda r: r["min"], default=None)
    streak = _streaks({r["date"] for r in rows if r["date"] <= upto}, upto, plan_rest_days(plan, upto))

    adherence = None
    p = _planned(plan, start)
    if p is not None:
        merged = merge(start, today, p["days"], acts)
        ss = [s for d in merged for s in d["sessions"] if s["status"] != "rest"]
        done = sum(s["status"] == "done" for s in ss)
        adherence = {"done": done, "planned": len(ss), "pct": round(100 * done / len(ss)) if ss else None,
                     "phase": p["week"].get("phase"), "focus": p["week"].get("focus") or None}

    titles = {b[0]: (b[1], b[2]) for b in BADGES}
    badges = [{"id": b, "title": titles[b][0], "description": titles[b][1]}
              for b, d in sorted((ledger.get("badge_dates") or {}).items(), key=lambda x: x[1])
              if b in titles and start.isoformat() <= str(d) <= end.isoformat()]

    nxt = week_for(plan, end + timedelta(days=1)) if plan else None
    if nxt is not None:
        next_week: dict[str, Any] = {"start": nxt["start"], "phase": nxt.get("phase"), "focus": nxt.get("focus") or None,
                                     "recovery": bool(nxt.get("recovery")), "sessions": _key_sessions(nxt), "target": None}
    else:
        n = len(week)
        if n < 3:
            target = "3 workouts next week. Short ones count."
        else:
            longest = round(best["min"]) if best else 45
            target = f"{min(n + 1, 6)} workouts next week, with one a bit longer than {longest} min."
        next_week = {"start": (end + timedelta(days=1)).isoformat(), "phase": None, "focus": None,
                     "recovery": False, "sessions": [], "target": target}

    xp = int((ledger.get("xp_by_week") or {}).get(week_key(start)) or 0)
    out = {
        "week_start": start.isoformat(), "week_end": end.isoformat(), "today": today.isoformat(),
        "current": start <= today <= end,
        "xp": xp, "workouts": len(week), "hours": round(minutes / 60, 1),
        "km": round(sum(r["km"] for r in week), 1), "active_days": len({r["date"] for r in week}),
        "streak": streak["current"], "streak_best": streak["best"],
        "adherence": adherence, "badges": badges,
        "best": ({"name": best["name"], "sport": best["sport"], "minutes": round(best["min"]),
                  "km": round(best["km"], 1), "date": best["date"].isoformat()} if best else None),
        "next_week": next_week, "level": level_view(int(ledger.get("xp") or 0)),
        "browse": {"oldest": (today - timedelta(days=today.weekday()) - timedelta(weeks=BROWSE_WEEKS - 1)).isoformat(),
                   "newest": (today - timedelta(days=today.weekday())).isoformat()},
    }
    out["summary"] = push_text(out)
    return out


def push_text(r: dict[str, Any]) -> str:
    """"5 workouts · +312 XP · 9-day streak" (the Sunday notification)."""
    if not r["workouts"]:
        return "A quiet week. Tap for next week's focus."
    parts = [f"{r['workouts']} workout{'s' if r['workouts'] != 1 else ''}"]
    if r["xp"]:
        parts.append(f"+{r['xp']} XP")
    if r["streak"] >= 2:
        parts.append(f"{r['streak']}-day streak")
    elif r["hours"]:
        parts.append(f"{r['hours']:g} h")
    return " · ".join(parts)


class RecapService:
    def __init__(self, agent: "Agent") -> None:
        self._a = agent

    def get(self, user_id: str, week: str | None = None) -> dict[str, Any]:
        """Blocking (Garmin read via the stats cache); run off the event loop."""
        a = self._a
        today = a._now(user_id).date()
        start = parse_week(week, today)
        _, acts = a.stats.activities(user_id)
        plan = a.plans.get(user_id)
        try:  # record any new XP first (quests are only ever added, so {} awards none)
            goal = a.coach.active_goal(user_id)
            a.progress.update(user_id, acts=acts, today=today, stats=a.stats.get(user_id),
                              plan_key=goal["id"] if goal and plan else None, quests={})
        except Exception:
            pass
        out = build(start=start, today=today, acts=acts, plan=plan, ledger=a.progress.ledger(user_id))
        try:
            out["units"] = "imperial" if a.coach.athlete(user_id).get("units") == "imperial" else "metric"
        except Exception:
            out["units"] = "metric"
        return out


__all__ = ["build", "push_text", "parse_week", "default_week", "RecapService", "RecapError"]
