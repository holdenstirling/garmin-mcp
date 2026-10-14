"""Gamification: XP, levels, setup quests and badge celebrations.

Sport-agnostic and race-optional. XP comes from what the athlete actually does:

* every workout Garmin records: 10 XP plus 1 XP per 2 minutes (capped at 3 hours),
* planned sessions completed (+15 each) and perfect plan weeks (+100),
* each badge earned (+100) and each setup quest finished (its own XP).

Awards are kept in a per-user ledger (``progress`` doc) keyed by activity id, plan, badge
and quest, so XP only ever goes up, a workout is never counted twice, and a plan rebuild
doesn't hand out the same sessions again. The first read back-fills the past year, so
existing athletes start at the level their training has earned.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .appstore import AppStore
from .stats import ACTIVE_WEEK, HISTORY_DAYS, _rows

PLAN_SESSION_XP = 15
PERFECT_WEEK_XP = 100
BADGE_XP = 100

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
]


def workout_xp(minutes: float) -> int:
    return 10 + int(min(max(minutes, 0), 180) // 2)


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


def quests_view(state: dict[str, bool], available: dict[str, bool]) -> list[dict[str, Any]]:
    """Quests the athlete can do here (optional ones only when the integration exists)."""
    return [{"id": qid, "title": t, "hint": h, "xp": xp, "optional": opt, "done": bool(state.get(qid))}
            for qid, t, h, xp, opt in QUESTS if available.get(qid, True)]


def week_goal(stats: dict[str, Any]) -> dict[str, Any]:
    """This week's target: the plan's sessions when there is a plan, else active-week workouts."""
    pw = ((stats.get("plan") or {}).get("week")) or None
    if pw and pw.get("planned"):
        return {"kind": "plan", "done": pw["done"], "target": pw["planned"], "label": "planned sessions"}
    n = stats["totals"]["week"]["workouts"]
    return {"kind": "active", "done": n, "target": ACTIVE_WEEK, "label": "workouts"}


class Progress:
    def __init__(self, store: AppStore, *, clock: Callable[[], float]) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "progress")

    def update(self, user_id: str, *, acts: list[dict[str, Any]], today: date, stats: dict[str, Any],
               plan_key: str | None, quests: dict[str, bool]) -> dict[str, Any]:
        """Award anything new, then return the level, quests and pending celebrations."""
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
            seen = d.setdefault("acts", {})
            for r in rows:
                k = str(r["id"])
                if k not in seen:
                    seen[k] = r["date"].isoformat()
                    gained += workout_xp(r["min"])
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
            for b in earned:
                if b not in got:
                    got.append(b)
                    gained += BADGE_XP
            qd = d.setdefault("quests", [])
            qxp = {q[0]: q[3] for q in QUESTS}
            for q, ok in quests.items():
                if ok and q in qxp and q not in qd:
                    qd.append(q)
                    gained += qxp[q]
            xp += gained
            d["xp"] = xp
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

    def seen(self, user_id: str) -> None:
        """The athlete saw the celebration: clear new badges and level-ups."""
        def apply(d: dict[str, Any]) -> None:
            d["badges_seen"] = list(d.get("badges") or [])
            d["level_seen"] = level_of(int(d.get("xp") or 0))
        self._doc(user_id).update(apply)


__all__ = ["Progress", "QUESTS", "level_of", "level_floor", "level_view", "quests_view", "week_goal",
           "workout_xp", "tier_name"]
