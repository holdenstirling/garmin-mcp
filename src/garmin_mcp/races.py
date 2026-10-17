"""Your races and which one the plan trains for (Schedule's race switcher).

Every goal keeps its own plan doc (``plans.py``: ``plan-<goal id>``), so switching the
plan to another race and back restores the earlier plan as it was instead of rebuilding.

* ``list``: goals (the active one first) and races on the events calendar that aren't a
  goal yet, each with its date and whether it already has a plan.
* ``train_for``: make that race the one the plan targets. A goal is re-activated (its plan
  comes back); a calendar race becomes a new goal (no plan yet: the app offers to build).
  The previous main race stays on the calendar as a B race.
* ``tune_up``: keep the current plan and add a calendar race to it as a B race.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .coaching import CoachError

RACE_KINDS = ("race", "challenge", "other")


class RaceDesk:
    def __init__(self, coach: Any, plans: Any, events: Any) -> None:
        self._coach = coach
        self._plans = plans
        self._events = events

    def _has_plan(self, user_id: str, goal: dict[str, Any]) -> bool:
        if goal.get("plan_source") == "builder":
            return bool(self._plans.load_doc(user_id, goal["id"]))
        return bool(goal.get("plan"))

    def list(self, user_id: str, today: date) -> dict[str, Any]:
        gs = self._coach.goals(user_id)
        active = gs.get("active")
        t = today.isoformat()
        out: list[dict[str, Any]] = []
        linked: set[str] = set()
        for g in gs.get("goals", []):
            if g.get("event_id"):
                linked.add(g["event_id"])
            past = bool(g.get("date") and g["date"] < t)
            if g["id"] != active and (past or not g.get("date")) and not self._has_plan(user_id, g):
                continue  # old goals without a plan or a date aren't worth listing
            out.append({"id": f"goal:{g['id']}", "kind": "goal", "goal_id": g["id"], "event_id": g.get("event_id"),
                        "title": g.get("title") or g.get("event") or "Race", "date": g.get("date"),
                        "distance": g.get("distance") or "", "active": g["id"] == active, "past": past,
                        "has_plan": self._has_plan(user_id, g), "priority": "A" if g["id"] == active else g.get("priority")})
        for e in self._events.list(user_id) if self._events is not None else []:
            if e["id"] in linked or e.get("kind") not in RACE_KINDS or not e.get("date") or e["date"] < t:
                continue
            out.append({"id": f"event:{e['id']}", "kind": "event", "goal_id": None, "event_id": e["id"],
                        "title": e.get("name") or "Race", "date": e["date"], "distance": e.get("distance") or "",
                        "active": False, "past": False, "has_plan": False, "priority": e.get("priority") or "B"})
        out.sort(key=lambda r: (not r["active"], r["past"], r["date"] or "9999"))
        return {"active": active, "races": out}

    def train_for(self, user_id: str, rid: str) -> dict[str, Any]:
        kind, _, key = (rid or "").partition(":")
        if kind == "goal":
            gs = self._coach.goals(user_id)
            goal = next((g for g in gs.get("goals", []) if g["id"] == key), None)
            if goal is None:
                raise CoachError("goal not found")
            if gs.get("active") != key:
                prev = self._coach.active_goal(user_id)
                self._plans.switch_goal(user_id, lambda: self._coach.activate_goal(user_id, key))
                self._demote(user_id, prev)
        elif kind == "event":
            ev = self._events.get(user_id, key)
            if ev.get("kind") not in RACE_KINDS:
                raise CoachError("Only a race or a challenge can be what your plan trains for.")
            prev = self._coach.active_goal(user_id)
            fields = {"title": ev["name"][:80], "priority": "A"} | self._events._goal_fields(ev)
            goal = self._plans.switch_goal(user_id, lambda: self._coach.create_goal(user_id, fields))
            self._events._link_goal(user_id, goal["id"], key)
            if ev.get("priority") != "A":
                self._events.update(user_id, key, {"priority": "A"})
            self._demote(user_id, prev)
        else:
            raise CoachError("unknown race")
        goal = self._coach.active_goal(user_id) or {}
        return {"goal": goal, "has_plan": self._has_plan(user_id, goal) if goal else False}

    def _demote(self, user_id: str, prev: dict[str, Any] | None) -> None:
        """The race the plan used to target stays on the calendar as a B race."""
        if prev and prev.get("event_id") and self._events is not None:
            try:
                ev = self._events.get(user_id, prev["event_id"])
            except CoachError:
                return
            if ev.get("priority") == "A":
                self._events.update(user_id, ev["id"], {"priority": "B"})

    def tune_up(self, user_id: str, event_id: str) -> dict[str, Any]:
        ev = self._events.get(user_id, event_id)
        if ev.get("main"):
            raise CoachError("That's the race your plan trains for.")
        if ev.get("priority") not in ("B", "C"):
            self._events.update(user_id, event_id, {"priority": "B"})
        return self._events.get(user_id, event_id)


__all__ = ["RaceDesk"]
