"""Gamification: XP, levels, setup quests and badge celebrations.

Sport-agnostic and race-optional. XP comes from what the athlete actually does:

* every workout Garmin records: 10 XP plus 1 XP per 2 minutes (capped at 3 hours),
* planned sessions completed (+15 each) and perfect plan weeks (+100),
* each badge earned (+100) and each setup quest finished (its own XP),
* small one-off bonuses passed in by key (e.g. +25 per gear item added).

Awards are kept in a per-user ledger (``progress`` doc) keyed by activity id, plan, badge
and quest, so XP only ever goes up, a workout is never counted twice, and a plan rebuild
doesn't hand out the same sessions again. The first read back-fills the past year, so
existing athletes start at the level their training has earned.

For the weekly recap the ledger also keeps ``xp_by_week`` (Monday -> XP, last
``KEEP_WEEKS`` weeks; workouts count in their own week, everything else in the week it
was awarded) and ``badge_dates`` (badge -> date first earned). Back-filled history only
adds workout XP by week and no badge dates, so old badges never show as "this week".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .appstore import AppStore
from .intent import quest_layout
from .stats import ACTIVE_WEEK, HISTORY_DAYS, _rows

PLAN_SESSION_XP = 15
PERFECT_WEEK_XP = 100
BADGE_XP = 100
GEAR_XP = 25  # first time each gear item is added (bonus key "gear:<id>")
MAX_BONUS_KEYS = 500
KEEP_WEEKS = 26

# Level names, rabbit-themed: (first level, name).
TIERS: list[tuple[int, str]] = [(1, "Kit"), (5, "Hopper"), (10, "Runner"), (15, "Trail Hare"),
                                (20, "Mountain Hare"), (30, "Jackrabbit"), (40, "Legend")]

# Setup quests: (id, title, hint, xp, optional)
QUESTS: list[tuple[str, str, str, int, bool]] = [
    ("garmin", "Connect Garmin", "Your workouts count automatically", 100, False),
    ("sports", "Pick your favorite sports", "Shapes your plan and stats", 50, False),
    ("goal", "Set a goal or race", "Or just train to stay fit", 100, False),
    ("plan", "Build your plan", "A week-by-week plan made for you", 200, False),
    ("sync", "Send workouts to your watch", "Planned sessions show up on Garmin", 100, False),
    ("notify", "Turn on notifications", "Morning briefs and coach messages", 50, False),
    ("calendar", "Connect Google Calendar", "Plans around busy days and travel", 50, True),
    ("oura", "Connect Oura", "Readiness and sleep in your stats", 50, True),
    ("coach", "Invite a coach", "Train with a real person in the loop", 50, True),
    ("coach_status", "Coaching: do you want a coach?", "Find one or go solo", 25, True),
    ("gear", "Add your shoes or bike", "Track mileage and get retirement alerts", 50, True),
    ("friend", "Follow a friend", "Cheer each other on", 50, True),
    ("interests", "Tell Rabbit what you're into", "Personal race picks", 50, True),
]

# One-word labels for the compact header progress pill (fits a 390px phone).
QUEST_SHORT: dict[str, str] = {
    "garmin": "Garmin", "sports": "Sports", "goal": "Goal", "plan": "Plan", "sync": "Watch sync",
    "notify": "Alerts", "calendar": "Calendar", "oura": "Oura", "coach": "Coach", "coach_status": "Coach",
    "gear": "Gear", "friend": "Friends", "interests": "Interests",
}


def workout_xp(minutes: float) -> int:
    return 10 + int(min(max(minutes, 0), 180) // 2)


def week_key(d: date) -> str:
    """Monday of ``d``'s week (the recap's week id)."""
    return (d - timedelta(days=d.weekday())).isoformat()


def level_floor(level: int) -> int:
    """Total XP needed to reach ``level`` (level 1 starts at 0)."""
    return 50 * level * (level - 1)


def level_of(xp: int) -> int:
    lv = 1
    while level_floor(lv + 1) <= xp:
        lv += 1
    return lv


def tier_name(level: int) -> str:
    name = TIERS[0][1]
    for start, n in TIERS:
        if level >= start:
            name = n
    return name


def level_view(xp: int) -> dict[str, Any]:
    lv = level_of(xp)
    lo, hi = level_floor(lv), level_floor(lv + 1)
    return {"level": lv, "name": tier_name(lv), "xp": xp, "level_xp": xp - lo, "level_span": hi - lo,
            "to_next": hi - xp, "next_name": tier_name(lv + 1) if tier_name(lv + 1) != tier_name(lv) else None}


def quests_view(state: dict[str, bool], available: dict[str, bool], intents: Any = None) -> list[dict[str, Any]]:
    """Quests the athlete can do here (optional ones only when the integration exists),
    ordered and flagged core/optional for the athlete's ``intents`` (intent.quest_layout)."""
    return quest_layout([{"id": qid, "title": t, "short": QUEST_SHORT.get(qid, t), "hint": h, "xp": xp, "optional": opt, "done": bool(state.get(qid))}
                         for qid, t, h, xp, opt in QUESTS if available.get(qid, True)], intents)


def week_goal(stats: dict[str, Any]) -> dict[str, Any]:
    """This week's target: the plan's sessions when there is a plan, else active-week workouts."""
    pw = ((stats.get("plan") or {}).get("week")) or None
    if pw and pw.get("planned"):
        return {"kind": "plan", "done": pw["done"], "target": pw["planned"], "label": "sessions"}
    n = stats["totals"]["week"]["workouts"]
    return {"kind": "active", "done": n, "target": ACTIVE_WEEK, "label": "workouts"}


class Progress:
    def __init__(self, store: AppStore, *, clock: Callable[[], float]) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "progress")

    def update(self, user_id: str, *, acts: list[dict[str, Any]], today: date, stats: dict[str, Any],
               plan_key: str | None, quests: dict[str, bool],
               bonus: dict[str, int] | None = None) -> dict[str, Any]:
        """Award anything new, then return the level, quests and pending celebrations.

        ``bonus`` maps a stable key to one-off XP; each key is awarded once, ever."""
        rows = [r for r in _rows(acts) if r["date"] <= today and r.get("id") is not None]
        earned = [b["id"] for b in stats.get("badges") or [] if b.get("earned")]
        plan = stats.get("plan") or {}
        done_to_date = int((plan.get("to_date") or {}).get("done") or 0)
        perfect = int(plan.get("perfect_weeks") or 0)
        keep_after = (today - timedelta(days=HISTORY_DAYS + 30)).isoformat()

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            first = "xp" not in d
            xp = int(d.get("xp") or 0)
            gained = 0
            by_week = d.setdefault("xp_by_week", {})
            seen = d.setdefault("acts", {})
            for r in rows:
                k = str(r["id"])
                if k not in seen:
                    seen[k] = r["date"].isoformat()
                    wxp = workout_xp(r["min"])
                    gained += wxp
                    wk = week_key(r["date"])
                    by_week[wk] = int(by_week.get(wk) or 0) + wxp
            workout_gained = gained
            for k in [k for k, v in seen.items() if v < keep_after]:
                del seen[k]
            if plan_key:
                pd = d.setdefault("plans", {}).setdefault(plan_key, [0, 0])
                if done_to_date > pd[0]:
                    gained += (done_to_date - pd[0]) * PLAN_SESSION_XP
                    pd[0] = done_to_date
                if perfect > pd[1]:
                    gained += (perfect - pd[1]) * PERFECT_WEEK_XP
                    pd[1] = perfect
                if len(d["plans"]) > 20:  # oldest goals first (insertion order)
                    for old in list(d["plans"])[:-20]:
                        del d["plans"][old]
            got = d.setdefault("badges", [])
            dates = d.setdefault("badge_dates", {})
            for b in earned:
                if b not in got:
                    got.append(b)
                    gained += BADGE_XP
                    if not first:
                        dates[b] = today.isoformat()
            qd = d.setdefault("quests", [])
            qxp = {q[0]: q[3] for q in QUESTS}
            for q, ok in quests.items():
                if ok and q in qxp and q not in qd:
                    qd.append(q)
                    gained += qxp[q]
            if bonus:
                bd = d.setdefault("bonus", [])
                for k, v in bonus.items():
                    if k not in bd and isinstance(v, int) and 0 < v <= 1000:
                        bd.append(k)
                        gained += v
                del bd[:-MAX_BONUS_KEYS]
            xp += gained
            d["xp"] = xp
            if not first and gained > workout_gained:
                wk = week_key(today)
                by_week[wk] = int(by_week.get(wk) or 0) + gained - workout_gained
            for old_week in sorted(by_week)[:-KEEP_WEEKS]:
                del by_week[old_week]
            if first:
                # Back-filled history isn't news: start celebrations from here.
                d["badges_seen"] = list(got)
                d["level_seen"] = level_of(xp)
            return {"xp": xp, "gained": gained, "badges": list(got),
                    "badges_seen": list(d.get("badges_seen") or []), "level_seen": int(d.get("level_seen") or 1),
                    "quests_done": list(qd)}

        st = self._doc(user_id).update(apply)
        lv = level_view(st["xp"])
        by_id = {b["id"]: b for b in stats.get("badges") or []}
        new_badges = [{"id": b, "title": by_id[b]["title"], "description": by_id[b]["description"]}
                      for b in st["badges"] if b not in st["badges_seen"] and b in by_id]
        return {**lv, "gained": st["gained"],
                "level_up": lv["level"] > st["level_seen"],
                "new_badges": new_badges}

    def ledger(self, user_id: str) -> dict[str, Any]:
        """Read-only view for the weekly recap: total XP, XP by week, badge dates."""
        d = self._doc(user_id).load()
        return {"xp": int(d.get("xp") or 0), "xp_by_week": dict(d.get("xp_by_week") or {}),
                "badge_dates": dict(d.get("badge_dates") or {})}

    def seen(self, user_id: str) -> None:
        """The athlete saw the celebration: clear new badges and level-ups."""
        def apply(d: dict[str, Any]) -> None:
            d["badges_seen"] = list(d.get("badges") or [])
            d["level_seen"] = level_of(int(d.get("xp") or 0))
        self._doc(user_id).update(apply)


__all__ = ["Progress", "QUESTS", "QUEST_SHORT", "GEAR_XP", "level_of", "level_floor", "level_view", "quests_view", "week_goal",
           "workout_xp", "tier_name", "week_key"]
