"""Built plans: storage per goal, edits, and sync to the athlete's Garmin calendar.

A built plan lives in the user's encrypted ``plan-<goal_id>`` doc (see planbuilder for its
shape). Building or editing it also refreshes the goal's text summary (``goal.plan``), its
start date and length, so the coach's context and the coach log's week view follow it.

Garmin sync uploads each upcoming session in a window (default 14 days) as a structured
workout and schedules it on its day. Every synced session remembers its Garmin workout ids
and a hash of what was sent, so a re-sync only touches sessions that changed; workouts for
sessions that were deleted, moved out of the plan or replaced by a rebuild are kept as
"orphans" and deleted from Garmin on the next sync. Past days are never touched.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .appstore import AppStore
from .coaching import CoachError, CoachStore
from .logs import log_event
from .planbuilder import (
    KINDS_BY_SPORT,
    PlanError,
    build_plan,
    clamp_minutes,
    garmin_workouts,
    iter_sessions,
    make_session,
    rebuild_session,
    recompute_week,
    session_hash,
    summary_markdown,
    week_for,
)
from .providers import GarminError, ReauthRequired

if TYPE_CHECKING:
    from .tools import GarminService

logger = logging.getLogger(__name__)

SYNC_WINDOWS = (7, 14, 28)
SYNC_PAUSE_S = 0.4  # between Garmin calls, to stay polite
MAX_SESSIONS_PER_DAY = 4
TEXT_LIMITS = {"title": 60, "detail": 400}


class PlanService:
    def __init__(self, store: AppStore, coach: CoachStore, service: "GarminService | None",
                 *, now: Callable[[str], datetime], clock: Callable[[], float] = time.time,
                 pause: float = SYNC_PAUSE_S) -> None:
        self._s = store
        self._coach = coach
        self._service = service
        self._now = now
        self._clock = clock
        self._pause = pause
        self._sync_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------ storage --
    def _doc(self, user_id: str, goal_id: str):
        return self._s.user_doc(user_id, f"plan-{goal_id}")

    def _goal(self, user_id: str) -> dict[str, Any]:
        g = self._coach.active_goal(user_id)
        if g is None:
            raise PlanError("Set up your race first.")
        return g

    def get(self, user_id: str) -> dict[str, Any] | None:
        g = self._coach.active_goal(user_id)
        if g is None or g.get("plan_source") != "builder":
            return None
        plan = self._doc(user_id, g["id"]).load()
        return plan or None

    def today(self, user_id: str) -> date:
        return self._now(user_id).date()

    def _publish(self, user_id: str, goal: dict[str, Any], plan: dict[str, Any]) -> None:
        """Keep the goal's summary, dates and source in step with the built plan."""
        summary = summary_markdown(plan, goal)

        def apply(d: dict[str, Any]) -> None:
            gg = d["goals"][goal["id"]]
            gg["plan"] = summary
            gg["plan_start"] = plan["start"]
            gg["plan_weeks"] = len(plan["weeks"])
            gg["plan_source"] = "builder"
        self._s.user_doc(user_id, "goals").update(apply)

    # ------------------------------------------------------------- build --
    def build(self, user_id: str, start: str | None = None) -> dict[str, Any]:
        goal = self._goal(user_id)
        today = self.today(user_id)
        try:
            first = date.fromisoformat(start) if start else None
        except ValueError:
            raise PlanError("Start date must be YYYY-MM-DD.") from None
        plan = build_plan(self._coach.athlete(user_id), goal, today=today, start=first)
        plan["created"] = plan["updated"] = int(self._clock())
        plan["goal_id"] = goal["id"]

        def put(d: dict[str, Any]) -> None:
            # Anything synced from an earlier version gets cleaned up on the next sync.
            orphans = list(d.get("garmin_orphans", []))
            for _, day, s in iter_sessions(d) if d else []:
                if day >= today.isoformat():
                    orphans += (s.get("garmin") or {}).get("workout_ids", [])
            garmin = d.get("garmin") or {}
            d.clear()
            d.update(plan)
            d["garmin_orphans"] = orphans
            d["garmin"] = {"window": garmin.get("window", 14), "synced_at": None}
        self._doc(user_id, goal["id"]).update(put)
        self._publish(user_id, goal, plan)
        log_event(logger, logging.INFO, "plan_built", user_id=user_id, weeks=len(plan["weeks"]),
                  distance=plan["distance"])
        return self.get(user_id) or plan

    def delete(self, user_id: str) -> dict[str, Any]:
        """Drop the built plan (after removing its workouts from Garmin when connected)."""
        goal = self._goal(user_id)
        removed = {"removed": 0, "errors": []}
        if self.get(user_id) is not None:
            try:
                removed = self.unsync(user_id)
            except (GarminError, PlanError):
                pass  # not connected: nothing we can clean up remotely
        self._doc(user_id, goal["id"]).delete()

        def apply(d: dict[str, Any]) -> None:
            gg = d["goals"][goal["id"]]
            for k in ("plan_source", "plan_start", "plan_weeks"):
                gg.pop(k, None)
            gg["plan"] = ""
        self._s.user_doc(user_id, "goals").update(apply)
        return removed

    # ------------------------------------------------------------- edits --
    def _edit(self, user_id: str, fn: Callable[[dict[str, Any], date], Any]) -> dict[str, Any]:
        goal = self._goal(user_id)
        today = self.today(user_id)

        def apply(d: dict[str, Any]) -> None:
            if not d:
                raise PlanError("Build a plan first.")
            fn(d, today)
            d["updated"] = int(self._clock())
        self._doc(user_id, goal["id"]).update(apply)
        plan = self.get(user_id)
        assert plan is not None
        self._publish(user_id, goal, plan)
        return plan

    @staticmethod
    def _find(plan: dict[str, Any], sid: str) -> tuple[dict[str, Any], str, int]:
        for w in plan["weeks"]:
            for d, ss in w["days"].items():
                for i, s in enumerate(ss):
                    if s["id"] == sid:
                        return w, d, i
        raise PlanError("That session isn't in your plan anymore.")

    @staticmethod
    def _validate(patch: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in patch.items():
            if k == "sport":
                if v not in KINDS_BY_SPORT:
                    raise PlanError("Unknown sport.")
                out[k] = v
            elif k == "kind":
                if not isinstance(v, str) or len(v) > 20:
                    raise PlanError("Unknown session type.")
                out[k] = v
            elif k == "minutes":
                out[k] = clamp_minutes(v)
            elif k in TEXT_LIMITS:
                if not isinstance(v, str):
                    raise PlanError(f"{k} must be text")
                out[k] = v.strip()[:TEXT_LIMITS[k]]
            elif k == "date":
                try:
                    out[k] = date.fromisoformat(str(v)).isoformat()
                except ValueError:
                    raise PlanError("date must be YYYY-MM-DD") from None
            else:
                raise PlanError(f"Unknown field {k!r}.")
        return out

    def _place(self, plan: dict[str, Any], day: str, s: dict[str, Any]) -> None:
        w = week_for(plan, date.fromisoformat(day))
        if w is None:
            raise PlanError("That day is outside your plan.")
        ss = [x for x in w["days"].get(day, []) if x["sport"] != "rest" or s["sport"] == "rest"]
        if len(ss) >= MAX_SESSIONS_PER_DAY:
            raise PlanError(f"Up to {MAX_SESSIONS_PER_DAY} sessions a day.")
        ss.append(s)
        w["days"][day] = ss

    @staticmethod
    def _orphan(plan: dict[str, Any], s: dict[str, Any]) -> None:
        ids = (s.get("garmin") or {}).get("workout_ids", [])
        if ids:
            plan.setdefault("garmin_orphans", []).extend(ids)

    def update_session(self, user_id: str, sid: str, patch: dict[str, Any]) -> dict[str, Any]:
        upd = self._validate(patch)

        def fn(plan: dict[str, Any], today: date) -> None:
            w, day, i = self._find(plan, sid)
            s = dict(w["days"][day][i])
            if s.get("kind") == "race":
                raise PlanError("Race day can't be edited here; change the race in your goal.")
            target = upd.get("date", day)
            if day < today.isoformat() and target != day:
                raise PlanError("Past sessions can't be moved.")
            if "title" in upd:
                s["title"], s["title_custom"] = upd["title"] or s["title"], bool(upd["title"])
            if "detail" in upd:
                s["detail"], s["detail_custom"] = upd["detail"], bool(upd["detail"])
            structural = {k: upd[k] for k in ("sport", "kind", "minutes") if k in upd}
            if structural:
                if structural.get("sport", s["sport"]) != s["sport"] and "kind" not in structural:
                    structural["kind"] = KINDS_BY_SPORT[structural["sport"]][0]
                s.update(structural)
                s.pop("legs", None)
                s = rebuild_session(s, swim_pace=plan.get("swim_pace", 125.0), phase=w["phase"])
            s["edited"] = True
            del w["days"][day][i]
            if not w["days"][day]:
                w["days"][day] = [make_session("rest", "rest", 0)]
            self._place(plan, target, s)
            recompute_week(w)
            w2 = week_for(plan, date.fromisoformat(target))
            if w2 is not None and w2 is not w:
                recompute_week(w2)
        return self._edit(user_id, fn)

    def add_session(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        upd = self._validate(body)
        if "date" not in upd or "sport" not in upd:
            raise PlanError("Pick a day and a sport.")
        if upd["sport"] == "rest":
            raise PlanError("Pick a sport for the new session.")

        def fn(plan: dict[str, Any], today: date) -> None:
            if upd["date"] < today.isoformat():
                raise PlanError("Add sessions from today on.")
            w = week_for(plan, date.fromisoformat(upd["date"]))
            phase = w["phase"] if w else "base"
            kind = upd.get("kind") if upd.get("kind") in KINDS_BY_SPORT[upd["sport"]] \
                else KINDS_BY_SPORT[upd["sport"]][0]
            s = make_session(upd["sport"], kind, upd.get("minutes", 45),
                             swim_pace=plan.get("swim_pace", 125.0), phase=phase,
                             title=upd.get("title") or None)
            if upd.get("title"):
                s["title_custom"] = True
            if upd.get("detail"):
                s["detail"], s["detail_custom"] = upd["detail"], True
            s["edited"] = True
            self._place(plan, upd["date"], s)
            if w:
                recompute_week(w)
        return self._edit(user_id, fn)

    def delete_session(self, user_id: str, sid: str) -> dict[str, Any]:
        def fn(plan: dict[str, Any], today: date) -> None:
            w, day, i = self._find(plan, sid)
            s = w["days"][day][i]
            if s.get("kind") == "race":
                raise PlanError("Race day stays in the plan.")
            self._orphan(plan, s)
            del w["days"][day][i]
            if not w["days"][day]:
                w["days"][day] = [make_session("rest", "rest", 0)]
            recompute_week(w)
        return self._edit(user_id, fn)

    # -------------------------------------------------------------- sync --
    def _lock(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._sync_locks.setdefault(user_id, threading.Lock())

    def _need_service(self) -> "GarminService":
        if self._service is None:
            raise PlanError("Garmin isn't available on this server.")
        return self._service

    def sync(self, user_id: str, days: int = 14) -> dict[str, Any]:
        """Upload/schedule changed sessions from today through ``days`` ahead; delete orphans."""
        if days not in SYNC_WINDOWS:
            raise PlanError(f"Sync window must be one of {SYNC_WINDOWS} days.")
        svc = self._need_service()
        goal = self._goal(user_id)
        lock = self._lock(user_id)
        if not lock.acquire(blocking=False):
            raise PlanError("A Garmin sync is already running.")
        try:
            return self._sync(user_id, goal, svc, days)
        finally:
            lock.release()

    def _sync(self, user_id: str, goal: dict[str, Any], svc: "GarminService",
              days: int) -> dict[str, Any]:
        plan = self.get(user_id)
        if plan is None:
            raise PlanError("Build a plan first.")
        athlete = self._coach.athlete(user_id)
        today = self.today(user_id)
        first, last = today.isoformat(), (today + timedelta(days=days - 1)).isoformat()
        result: dict[str, Any] = {"uploaded": 0, "unchanged": 0, "removed": 0, "skipped": 0,
                                  "errors": [], "window": [first, last]}

        # 1. Orphans (sessions deleted/rebuilt since the last sync).
        orphans = list(plan.get("garmin_orphans", []))
        gone: list[int] = []
        for wid in orphans:
            try:
                svc.workout_delete(user_id, wid)
                result["removed"] += 1
                gone.append(wid)
            except ReauthRequired:
                raise
            except GarminError as e:
                if "does not exist" in str(e):
                    gone.append(wid)
                else:
                    result["errors"].append({"title": "Old workout", "error": str(e)[:160]})
            self._sleep()
        if gone:
            self._update_plan(user_id, goal, lambda p: p.__setitem__(
                "garmin_orphans", [w for w in p.get("garmin_orphans", []) if w not in gone]))

        # 2. Sessions in the window.
        for _, day, s in list(iter_sessions(plan)):
            if not (first <= day <= last):
                continue
            wos = garmin_workouts(s, athlete)
            if not wos:
                result["skipped"] += s["sport"] != "rest"
                continue
            h = session_hash(s, day, athlete)
            g = s.get("garmin") or {}
            if g.get("hash") == h and g.get("workout_ids"):
                result["unchanged"] += 1
                continue
            try:
                for wid in g.get("workout_ids", []):
                    try:
                        svc.workout_delete(user_id, wid)
                    except GarminError as e:
                        if "does not exist" not in str(e):
                            raise
                    self._sleep()
                ids, sched = [], []
                for wo in wos:
                    up = svc.workout_upload(user_id, wo)
                    wid = up.get("workoutId")
                    if not isinstance(wid, int):
                        raise GarminError("Garmin didn't return a workout id.")
                    ids.append(wid)
                    self._sleep()
                    sc = svc.workout_schedule(user_id, wid, day)
                    sched.append(sc.get("workoutScheduleId") or sc.get("scheduleId") or sc.get("id"))
                    self._sleep()
            except ReauthRequired:
                raise
            except GarminError as e:
                result["errors"].append({"title": s["title"], "date": day, "error": str(e)[:160]})
                continue
            rec = {"workout_ids": ids, "schedule_ids": sched, "hash": h, "date": day,
                   "synced_at": int(self._clock())}
            self._set_garmin(user_id, goal, s["id"], rec)
            result["uploaded"] += 1

        def stamp(p: dict[str, Any]) -> None:
            p["garmin"] = {"window": days, "synced_at": int(self._clock()),
                           "last": {k: result[k] for k in ("uploaded", "unchanged", "removed")},
                           "errors": len(result["errors"])}
        self._update_plan(user_id, goal, stamp)
        log_event(logger, logging.INFO, "plan_synced", user_id=user_id, window=days,
                  **{k: result[k] for k in ("uploaded", "unchanged", "removed", "skipped")},
                  errors=len(result["errors"]))
        return result

    def unsync(self, user_id: str) -> dict[str, Any]:
        """Delete every workout Rabbit put on Garmin for this plan (today onward + orphans)."""
        svc = self._need_service()
        goal = self._goal(user_id)
        plan = self.get(user_id)
        if plan is None:
            raise PlanError("Build a plan first.")
        lock = self._lock(user_id)
        if not lock.acquire(blocking=False):
            raise PlanError("A Garmin sync is already running.")
        try:
            today = self.today(user_id).isoformat()
            ids = list(plan.get("garmin_orphans", []))
            owners: list[str] = []
            for _, day, s in iter_sessions(plan):
                g = s.get("garmin") or {}
                if g.get("workout_ids") and day >= today:
                    ids += g["workout_ids"]
                    owners.append(s["id"])
            removed, errors = 0, []
            for wid in ids:
                try:
                    svc.workout_delete(user_id, wid)
                    removed += 1
                except ReauthRequired:
                    raise
                except GarminError as e:
                    if "does not exist" not in str(e):
                        errors.append({"title": "Workout", "error": str(e)[:160]})
                self._sleep()

            def clear(p: dict[str, Any]) -> None:
                p["garmin_orphans"] = []
                for _, _, s in iter_sessions(p):
                    if s["id"] in owners:
                        s.pop("garmin", None)
                p["garmin"] = {"window": (p.get("garmin") or {}).get("window", 14), "synced_at": None}
            self._update_plan(user_id, goal, clear)
            return {"removed": removed, "errors": errors}
        finally:
            lock.release()

    def _update_plan(self, user_id: str, goal: dict[str, Any], fn: Callable[[dict[str, Any]], Any]) -> None:
        def apply(d: dict[str, Any]) -> None:
            if d:
                fn(d)
        self._doc(user_id, goal["id"]).update(apply)

    def _set_garmin(self, user_id: str, goal: dict[str, Any], sid: str, rec: dict[str, Any]) -> None:
        def fn(p: dict[str, Any]) -> None:
            for _, _, s in iter_sessions(p):
                if s["id"] == sid:
                    s["garmin"] = rec
                    return
            p.setdefault("garmin_orphans", []).extend(rec["workout_ids"])  # deleted meanwhile
        self._update_plan(user_id, goal, fn)

    def _sleep(self) -> None:
        if self._pause:
            time.sleep(self._pause)

    # ----------------------------------------------------------- prefill --
    def garmin_numbers(self, user_id: str) -> dict[str, Any]:
        return self._need_service().training_numbers(user_id)


def public_plan(plan: dict[str, Any] | None, today: date) -> dict[str, Any] | None:
    """What the app shows: drops internal fields, adds per-session sync state."""
    if plan is None:
        return None
    weeks = []
    for w in plan["weeks"]:
        days = []
        for d in sorted(w["days"]):
            ss = []
            for s in w["days"][d]:
                g = s.get("garmin") or {}
                ss.append({k: s.get(k) for k in ("id", "sport", "kind", "title", "minutes",
                                                 "detail", "meters", "edited")}
                          | {"synced": bool(g.get("workout_ids")),
                             "steps": s.get("steps") or [], "legs": s.get("legs") or []})
            days.append({"date": d, "sessions": ss})
        weeks.append({k: w[k] for k in ("index", "start", "phase", "recovery", "hours", "focus")}
                     | {"days": days})
    cur = week_for(plan, today)
    return {k: plan.get(k) for k in ("start", "first_day", "race_date", "distance", "race_kind",
                                     "level", "peak_hours", "start_hours", "note", "created",
                                     "updated")} | {
        "weeks": weeks, "current_week": cur["index"] if cur else None,
        "garmin": plan.get("garmin") or {}, "pending_removals": len(plan.get("garmin_orphans", [])),
        "kinds": {k: list(v) for k, v in KINDS_BY_SPORT.items()},
    }


__all__ = ["PlanService", "PlanError", "public_plan", "SYNC_WINDOWS", "CoachError"]
