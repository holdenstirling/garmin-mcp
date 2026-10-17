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

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

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
    new_id as new_session_id,
    rebuild_session,
    recompute_week,
    session_hash,
    summary_markdown,
    week_for,
)
from .nutrition import fuel
from .providers import GarminError, ReauthRequired

if TYPE_CHECKING:
    from .events import EventStore
    from .tools import GarminService

logger = logging.getLogger(__name__)
T = TypeVar("T")

SYNC_WINDOWS = (7, 14, 28)
SYNC_PAUSE_S = 0.4  # between Garmin calls, to stay polite
MAX_SESSIONS_PER_DAY = 4
TEXT_LIMITS = {"title": 60, "detail": 400}


class PlanService:
    def __init__(self, store: AppStore, coach: CoachStore, service: "GarminService | None",
                 *, now: Callable[[str], datetime], clock: Callable[[], float] = time.time,
                 pause: float = SYNC_PAUSE_S, events: "EventStore | None" = None) -> None:
        self._s = store
        self._coach = coach
        self._service = service
        self._now = now
        self._clock = clock
        self._pause = pause
        self._events = events
        self._sync_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._listeners: list[Callable[[str, list[dict[str, Any]]], Any]] = []

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
        if not plan:
            return None
        if self._events is not None:
            sig = self._events.signature(self._events.plan_events(user_id))
            plan["events_changed"] = sig != plan.get("events_sig", sig)
        # The race itself moved (or changed distance) since the build. A plan loaded by a
        # coach or from a file is never rebuilt, so it isn't flagged.
        plan["race_changed"] = not plan.get("origin") and (
            plan.get("race_date") != g.get("date") or
            plan.get("distance") != (g.get("distance") or "other").lower())
        if plan.get("origin"):
            plan["events_changed"] = False
        return plan

    def release_garmin(self, user_id: str, goal_id: str) -> list[int]:
        """Take the Garmin workout ids of a plan that's being replaced by a new goal's plan
        (future sessions + orphans), so the new plan's next sync removes them."""
        today = self.today(user_id).isoformat()
        ids: list[int] = []

        def fn(d: dict[str, Any]) -> None:
            if not d:
                return
            ids.extend(d.get("garmin_orphans", []))
            d["garmin_orphans"] = []
            for _, day, x in iter_sessions(d):
                if day >= today and (x.get("garmin") or {}).get("workout_ids"):
                    ids.extend(x["garmin"]["workout_ids"])
                    x.pop("garmin", None)
        self._doc(user_id, goal_id).update(fn)
        return ids

    def adopt_orphans(self, user_id: str, ids: list[int]) -> None:
        """Hand Garmin workout ids to the active goal's plan, or (no goal or no plan yet)
        park them until the next build, so they're never forgotten."""
        if not ids:
            return
        goal = self._coach.active_goal(user_id)
        done: list[bool] = []
        if goal is not None:
            def fn(p: dict[str, Any]) -> None:
                p.setdefault("garmin_orphans", []).extend(ids)
                done.append(True)
            self._update_plan(user_id, goal, fn)
        if not done:
            self._s.user_doc(user_id, "garmin-pending").update(
                lambda d: d.setdefault("ids", []).extend(ids))

    def switch_goal(self, user_id: str, change: Callable[[], T]) -> T:
        """Run ``change`` (create or archive a goal). If the active goal changed, the old
        plan's Garmin workouts move to the new one, to be removed on its next sync."""
        old = self._coach.active_goal(user_id)
        out = change()
        new = self._coach.active_goal(user_id)
        if old is not None and (new is None or new["id"] != old["id"]):
            self.adopt_orphans(user_id, self.release_garmin(user_id, old["id"]))
        return out

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
        events = self._events.plan_events(user_id) if self._events is not None else []
        plan = build_plan(self._coach.athlete(user_id), goal, today=today, start=first,
                          events=events)
        if self._events is not None:
            plan["events_sig"] = self._events.signature(events)
        plan["created"] = plan["updated"] = int(self._clock())
        out = self.install(user_id, goal, plan)
        log_event(logger, logging.INFO, "plan_built", user_id=user_id, weeks=len(plan["weeks"]),
                  distance=plan["distance"])
        return out

    def install(self, user_id: str, goal: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        """Replace the goal's plan doc with ``plan`` (a build, a coach import or an undo).
        Garmin workouts of the replaced plan from today on (and its orphans, and any parked by
        a goal switch) become orphans of the new one, removed on its next sync."""
        today = self.today(user_id)
        plan = dict(plan)
        plan["goal_id"] = goal["id"]
        plan.setdefault("created", int(self._clock()))
        plan["updated"] = int(self._clock())
        if self._events is not None and "events_sig" not in plan:
            plan["events_sig"] = self._events.signature(self._events.plan_events(user_id))
        # Workouts parked by a goal switch before this goal had a plan.
        parked: list[int] = []
        self._s.user_doc(user_id, "garmin-pending").update(lambda d: parked.extend(d.pop("ids", [])))

        def put(d: dict[str, Any]) -> None:
            # Anything synced from an earlier version gets cleaned up on the next sync.
            orphans = list(d.get("garmin_orphans", [])) + parked
            for _, day, s in iter_sessions(d) if d else []:
                if day >= today.isoformat():
                    orphans += (s.get("garmin") or {}).get("workout_ids", [])
            garmin = d.get("garmin") or {}
            d.clear()
            d.update(plan)
            d["garmin_orphans"] = list(dict.fromkeys(orphans))
            d["garmin"] = {"window": garmin.get("window", 14), "synced_at": None}
        self._doc(user_id, goal["id"]).update(put)
        self._publish(user_id, goal, plan)
        return self.get(user_id) or plan

    def load_doc(self, user_id: str, goal_id: str) -> dict[str, Any]:
        """The raw plan doc (snapshot for undo)."""
        return self._doc(user_id, goal_id).load()

    def forget(self, user_id: str, goal_id: str) -> None:
        """Drop a goal's plan doc without touching Garmin: its future workouts are handed
        on (to the active plan, or parked until the next build) so they still get removed."""
        ids = self.release_garmin(user_id, goal_id)
        self._doc(user_id, goal_id).delete()
        self.adopt_orphans(user_id, ids)

    def delete(self, user_id: str) -> dict[str, Any]:
        """Drop the built plan (after removing its workouts from Garmin when connected)."""
        goal = self._goal(user_id)
        removed = {"removed": 0, "errors": []}
        plan = self.get(user_id)
        on_garmin = bool(plan) and (bool(plan.get("garmin_orphans")) or any(
            (x.get("garmin") or {}).get("workout_ids") for _, _, x in iter_sessions(plan)))
        if on_garmin:
            try:
                removed = self.unsync(user_id)
            except ReauthRequired:
                raise PlanError("Reconnect Garmin in settings first, so Rabbit can remove the "
                                "workouts it added, then delete the plan.") from None
            except (GarminError, PlanError):
                pass  # Garmin not connected at all: nothing we can clean up remotely
            else:
                if (self.get(user_id) or {}).get("garmin_orphans"):
                    raise PlanError("Some workouts couldn't be removed from Garmin. Try again "
                                    "before deleting the plan.")
        self._doc(user_id, goal["id"]).delete()

        def apply(d: dict[str, Any]) -> None:
            gg = d["goals"][goal["id"]]
            for k in ("plan_source", "plan_start", "plan_weeks"):
                gg.pop(k, None)
            gg["plan"] = ""
        self._s.user_doc(user_id, "goals").update(apply)
        return removed

    # ------------------------------------------------------------- edits --
    def add_listener(self, fn: Callable[[str, list[dict[str, Any]]], Any]) -> None:
        """``fn(user_id, changes)`` after any session edit/move/add/delete (see ``session_changes``),
        e.g. a TrainingPeaks sync. Errors in a listener are logged and never fail the edit."""
        self._listeners.append(fn)

    def _edit(self, user_id: str, fn: Callable[[dict[str, Any], date], Any]) -> dict[str, Any]:
        goal = self._goal(user_id)
        today = self.today(user_id)
        before: dict[str, tuple[str, str]] = {}
        after: dict[str, tuple[str, str]] = {}

        def apply(d: dict[str, Any]) -> None:
            if not d:
                raise PlanError("Build a plan first.")
            before.clear()
            before.update(_session_index(d))
            fn(d, today)
            d["updated"] = int(self._clock())
            after.clear()
            after.update(_session_index(d))
        self._doc(user_id, goal["id"]).update(apply)
        plan = self.get(user_id)
        assert plan is not None
        self._publish(user_id, goal, plan)
        changes = session_changes(before, after, plan) if self._listeners else []
        for listener in list(self._listeners) if changes else []:
            try:
                listener(user_id, changes)
            except Exception as e:  # a sync hook never breaks an edit
                log_event(logger, logging.WARNING, "plan_listener_failed", user_id=user_id,
                          error=type(e).__name__)
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
            elif k == "time":
                out[k] = clean_time(v)
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
            if target != day and target < today.isoformat():
                raise PlanError("Sessions can't be moved into the past.")
            old_sport = s["sport"]
            if "title" in upd:
                s["title"], s["title_custom"] = upd["title"] or s["title"], bool(upd["title"])
            if "detail" in upd:
                s["detail"], s["detail_custom"] = upd["detail"], bool(upd["detail"])
            if "time" in upd:
                if upd["time"]:
                    s["time"] = upd["time"]
                else:
                    s.pop("time", None)
            structural = {k: upd[k] for k in ("sport", "kind", "minutes") if k in upd}
            if structural:
                if structural.get("sport", s["sport"]) != s["sport"] and "kind" not in structural:
                    structural["kind"] = KINDS_BY_SPORT[structural["sport"]][0]
                s.update(structural)
                s.pop("legs", None)
                s = rebuild_session(s, swim_pace=plan.get("swim_pace", 125.0), phase=w["phase"])
            s["edited"] = True
            if s.get("garmin") and (target != day or s["sport"] != old_sport or s["sport"] == "rest"):
                # Its Garmin workout no longer matches: remove it on the next sync.
                self._orphan(plan, s)
                s.pop("garmin", None)
            if target == day:  # same day: edit in place (no per-day limit to trip over)
                w["days"][day][i] = s
            else:
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
            if upd.get("time"):
                s["time"] = upd["time"]
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

    # ------------------------------------------------------------ adjust --
    def apply_adjustment(self, user_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply a proposal from adjust.propose (already verified by id by the caller)."""
        def fn(plan: dict[str, Any], today: date) -> None:
            swim_pace = plan.get("swim_pace", 125.0)
            for c in changes:
                to = c["to"]
                if c["action"] == "move":
                    w = week_for(plan, date.fromisoformat(c["date"]))
                    if w is None or c["date"] < today.isoformat():
                        continue
                    if len([x for x in w["days"].get(c["date"], []) if x["sport"] != "rest"]) >= MAX_SESSIONS_PER_DAY:
                        continue  # that day is full
                    new = make_session(to["sport"], to.get("kind") or "easy", int(to.get("minutes") or 45),
                                       swim_pace=swim_pace, phase=w["phase"])
                    new["edited"], new["adjusted"] = True, True
                    new["detail"] = f"Moved from a missed day, shortened. {new.get('detail', '')}".strip()[:400]
                    plan["made_up"] = (plan.get("made_up", []) + [c["session_id"]])[-50:]
                    w["days"][c["date"]] = [x for x in w["days"].get(c["date"], []) if x["sport"] != "rest"] + [new]
                    recompute_week(w)
                    continue
                try:
                    w, day, i = self._find(plan, c["session_id"])
                except PlanError:
                    continue
                if day < today.isoformat():
                    continue
                cur = w["days"][day][i]
                if c["action"] == "rest":
                    self._orphan(plan, cur)
                    rest = make_session("rest", "rest", 0)
                    rest["detail"] = "Rest day (plan adjusted)."
                    w["days"][day][i] = rest
                    w["days"][day] = [x for x in w["days"][day] if x["sport"] != "rest"] or [rest]
                else:
                    upd = dict(cur, kind=to.get("kind") or cur.get("kind"), minutes=to.get("minutes") or cur.get("minutes"))
                    upd.pop("legs", None)
                    upd = rebuild_session(upd, swim_pace=swim_pace, phase=w["phase"])
                    upd["edited"], upd["adjusted"] = True, True
                    w["days"][day][i] = upd
                recompute_week(w)
        return self._edit(user_id, fn)

    def dismiss_adjustment(self, user_id: str, pid: str) -> None:
        goal = self._goal(user_id)
        self._update_plan(user_id, goal, lambda p: p.__setitem__(
            "adjust_dismissed", (p.get("adjust_dismissed", []) + [pid])[-20:]))

    # ------------------------------------------------------------ travel --
    def add_travel(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Travel mode: rework sessions on days away for what the athlete has there, and
        move long sessions to the nearest home day of the same week. Undoable: the
        originals are kept with the trip."""
        try:
            start = date.fromisoformat(str(body.get("start")))
            end = date.fromisoformat(str(body.get("end")))
        except ValueError:
            raise PlanError("Pick the days you're away.") from None
        if end < start:
            start, end = end, start
        if (end - start).days > 60:
            raise PlanError("Travel mode covers up to 60 days at a time.")
        has = {k: body.get(k) is True for k in ("gym", "treadmill", "pool", "bike")}
        label = str(body.get("label") or "Travel").strip()[:60] or "Travel"

        def fn(plan: dict[str, Any], today: date) -> None:
            first = max(start, today)
            if first > end:
                raise PlanError("Those days have already passed.")
            trips = plan.setdefault("trips", [])
            away = {(first + timedelta(days=i)).isoformat() for i in range((end - first).days + 1)}
            if any(away & {(date.fromisoformat(t["start"]) + timedelta(days=i)).isoformat()
                           for i in range((date.fromisoformat(t["end"]) - date.fromisoformat(t["start"])).days + 1)}
                   for t in trips):
                raise PlanError("Those days overlap a trip that's already in travel mode.")
            trip = {"id": "t" + new_session_id()[:8], "start": first.isoformat(), "end": end.isoformat(),
                    "label": label, "has": has, "original": {}}
            swim_pace = plan.get("swim_pace", 125.0)
            touched: set[str] = set()

            def keep(day: str) -> None:
                if day not in trip["original"]:
                    w = week_for(plan, date.fromisoformat(day))
                    if w is not None:
                        trip["original"][day] = [dict(x) for x in w["days"].get(day, [])]

            for w in plan["weeks"]:
                for day in sorted(w["days"]):
                    if day not in away:
                        continue
                    new: list[dict[str, Any]] = []
                    for x in w["days"][day]:
                        if x["sport"] == "rest" or x.get("kind") == "race":
                            new.append(x)
                            continue
                        keep(day)
                        self._orphan(plan, x)
                        if x.get("kind") in ("long", "brick"):
                            target = self._home_day(w, day, away, today)
                            if target is not None:
                                keep(target)
                                moved = {k: v for k, v in x.items() if k != "garmin"} | {"edited": True, "travel": trip["id"]}
                                w["days"][target] = [y for y in w["days"][target] if y["sport"] != "rest"] + [moved]
                                touched.add(w["start"])
                                continue
                        new.append(_travel_swap(x, has, swim_pace, w["phase"], trip["id"]))
                    if new != w["days"][day]:
                        w["days"][day] = new or [make_session("rest", "rest", 0)]
                        touched.add(w["start"])
            for w in plan["weeks"]:
                if w["start"] in touched:
                    recompute_week(w)
            trips.append(trip)
        return self._edit(user_id, fn)

    @staticmethod
    def _home_day(w: dict[str, Any], day: str, away: set[str], today: date) -> str | None:
        """Nearest day of the same week that isn't away, has no long session or race, and
        isn't in the past (the caller only passes today onward via ``away``)."""
        d0 = date.fromisoformat(day)
        today_floor = today.isoformat()
        options = []
        for k in w["days"]:
            if k in away or k < today_floor:
                continue
            ss = w["days"][k]
            if any(x.get("kind") in ("long", "brick", "race") for x in ss) or len([x for x in ss if x["sport"] != "rest"]) >= MAX_SESSIONS_PER_DAY:
                continue
            options.append((abs((date.fromisoformat(k) - d0).days), k))
        return min(options)[1] if options else None

    def remove_travel(self, user_id: str, trip_id: str) -> dict[str, Any]:
        """Undo travel mode for the days still ahead. Days already past stay as they were
        (they happened); a session is never restored twice."""
        def fn(plan: dict[str, Any], today: date) -> None:
            trips = plan.get("trips", [])
            trip = next((t for t in trips if t["id"] == trip_id), None)
            if trip is None:
                raise PlanError("That trip isn't in your plan.")
            t = today.isoformat()
            orig = trip["original"]
            restore_ids = {x["id"] for d, ss in orig.items() if d >= t for x in ss}
            # Ids that now live on days already past (a moved copy that has happened).
            past_ids = {x["id"] for _, d, x in iter_sessions(plan) if d < t}
            touched = set()
            # Moved copies on future days go away when their original comes back.
            for w in plan["weeks"]:
                for d, ss in w["days"].items():
                    if d < t or d in orig:
                        continue
                    keep = [x for x in ss if not (x.get("travel") == trip_id and x["id"] in restore_ids)]
                    if len(keep) != len(ss):
                        for x in ss:
                            if x not in keep:
                                self._orphan(plan, x)
                        w["days"][d] = keep or [make_session("rest", "rest", 0)]
                        touched.add(w["start"])
            for day, sessions in orig.items():
                if day < t:
                    continue
                w = week_for(plan, date.fromisoformat(day))
                if w is None:
                    continue
                # Only undo what the trip changed: its swapped/moved sessions go, the
                # originals it reworked on days away come back; anything else (added or
                # edited since) stays.
                keep = []
                for x in w["days"].get(day, []):
                    if x.get("travel") == trip_id:
                        self._orphan(plan, x)
                    else:
                        keep.append(x)
                kept_ids = {x["id"] for x in keep}
                back = [{k: v for k, v in x.items() if k != "garmin"} for x in sessions
                        if trip["start"] <= day <= trip["end"] and x["sport"] != "rest"
                        and x.get("kind") != "race" and x["id"] not in past_ids | kept_ids]
                back += [x for x in keep if x["sport"] != "rest"]
                w["days"][day] = back or [make_session("rest", "rest", 0)]
                touched.add(w["start"])
            # Moved copies whose original day has passed simply stop being "travel".
            for _, d, x in iter_sessions(plan):
                if x.get("travel") == trip_id and d >= t:
                    x.pop("travel", None)
            for w in plan["weeks"]:
                if w["start"] in touched:
                    recompute_week(w)
            plan["trips"] = [x for x in trips if x["id"] != trip_id]
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
            ids: list[int] = []
            sched: list[Any] = []
            old_gone = False
            try:
                for wid in g.get("workout_ids", []):
                    try:
                        svc.workout_delete(user_id, wid)
                    except GarminError as e:
                        if "does not exist" not in str(e):
                            raise
                    self._sleep()
                old_gone = True
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
            except GarminError as e:
                # Never lose track of what's on Garmin: half-made uploads get removed on
                # the next sync, and a session whose old workout is gone forgets it.
                self._record_partial(user_id, goal, s["id"], ids, old_gone)
                if isinstance(e, ReauthRequired):
                    raise
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
            gone: set[int] = set()
            for wid in ids:
                try:
                    svc.workout_delete(user_id, wid)
                    removed += 1
                    gone.add(wid)
                except ReauthRequired:
                    raise
                except GarminError as e:
                    if "does not exist" in str(e):
                        gone.add(wid)
                    else:
                        errors.append({"title": "Workout", "error": str(e)[:160]})
                self._sleep()

            def clear(p: dict[str, Any]) -> None:
                # Only forget what's really off Garmin: failed deletes (and orphans added
                # meanwhile) stay as orphans for the next sync.
                left = [w for w in p.get("garmin_orphans", []) if w not in gone]
                for _, _, s in iter_sessions(p):
                    if s["id"] in owners and s.get("garmin"):
                        left += [w for w in s["garmin"].get("workout_ids", []) if w not in gone]
                        s.pop("garmin", None)
                p["garmin_orphans"] = list(dict.fromkeys(left))
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

    def _record_partial(self, user_id: str, goal: dict[str, Any], sid: str, new_ids: list[int],
                        old_gone: bool) -> None:
        if not new_ids and not old_gone:
            return

        def fn(p: dict[str, Any]) -> None:
            p.setdefault("garmin_orphans", []).extend(new_ids)
            if old_gone:
                for _, _, x in iter_sessions(p):
                    if x["id"] == sid:
                        x.pop("garmin", None)
        self._update_plan(user_id, goal, fn)

    def _sleep(self) -> None:
        if self._pause:
            time.sleep(self._pause)

    # ----------------------------------------------------------- prefill --
    def garmin_numbers(self, user_id: str) -> dict[str, Any]:
        return self._need_service().training_numbers(user_id)


def _travel_swap(x: dict[str, Any], has: dict[str, bool], swim_pace: float, phase: str,
                 trip_id: str) -> dict[str, Any]:
    """One session, reworked for what's available on the road. Capped at 75 minutes."""
    minutes = min(75, int(x.get("minutes") or 45))
    sport, kind = x["sport"], x.get("kind") or "easy"
    note = ""
    if sport == "bike" and not has.get("bike"):
        if has.get("gym"):
            note = "Hotel gym: use a spin or stationary bike."
        else:
            sport, kind, minutes = "run", ("easy" if kind in ("long", "endurance", "recovery", "easy") else "tempo"), min(minutes, 50)
            note = "No bike while away: swapped for a run."
    elif sport == "swim" and not has.get("pool"):
        sport, kind, minutes = "strength", "strength", 30
        note = "No pool while away: strength and core instead."
    elif sport == "run" and kind in ("vo2", "threshold") and not has.get("treadmill"):
        note = "Unfamiliar roads: run this by effort, not pace."
    if sport == "brick":
        sport, kind = "run", "easy"
    if kind not in KINDS_BY_SPORT.get(sport, ("easy",)):
        kind = KINDS_BY_SPORT.get(sport, ("easy",))[0]
    new = make_session(sport, kind, minutes, swim_pace=swim_pace, phase=phase)
    new["id"] = x["id"]
    new["edited"], new["travel"] = True, trip_id
    if note:
        new["detail"] = f"{note} {new.get('detail', '')}".strip()[:400]
    return new


_SIG_KEYS = ("sport", "kind", "title", "minutes", "detail", "note", "skipped", "meters")


def _session_index(plan: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """{session id: (day, content signature)} for the change hook."""
    return {s["id"]: (d, json.dumps([s.get(k) for k in _SIG_KEYS], default=str))
            for _, d, s in iter_sessions(plan) if s.get("id") and s.get("sport") != "rest"}


def session_changes(before: dict[str, tuple[str, str]], after: dict[str, tuple[str, str]],
                    plan: dict[str, Any]) -> list[dict[str, Any]]:
    """What changed between two indexes: ``{"type": moved|edited|added|removed, "id", "from",
    "to", "session"}`` (``session`` = the stored session now, without Garmin ids; None when
    removed). Moved and edited at once is ``moved``."""
    now = {s["id"]: s for _, _, s in iter_sessions(plan) if s.get("id")}
    out: list[dict[str, Any]] = []
    for sid in sorted(set(before) | set(after)):
        b, a = before.get(sid), after.get(sid)
        if b == a:
            continue
        kind = "added" if b is None else "removed" if a is None else "moved" if b[0] != a[0] else "edited"
        s = now.get(sid)
        out.append({"type": kind, "id": sid, "from": b[0] if b else None, "to": a[0] if a else None,
                    "session": {k: v for k, v in s.items() if k != "garmin"} if s and a else None})
    return out


def clean_time(v: Any) -> str:
    """A session's start time: "HH:MM" (24 h) or "" to clear it."""
    if v is None or v == "":
        return ""
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(v).strip()) if isinstance(v, str) else None
    if not m:
        raise PlanError("Start time must be HH:MM, like 06:30.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def public_plan(plan: dict[str, Any] | None, today: date) -> dict[str, Any] | None:
    """What the app shows: drops internal fields, adds per-session sync state."""
    if plan is None:
        return None
    weeks = []
    for w in plan["weeks"]:
        days = []
        for d in sorted(w["days"]):
            ss = []
            # Timed sessions in time order, untimed ones after them in plan order.
            for s in sorted(w["days"][d], key=lambda x: x.get("time") or "~"):
                g = s.get("garmin") or {}
                ss.append({k: s.get(k) for k in ("id", "sport", "kind", "title", "minutes",
                                                 "detail", "meters", "edited", "travel", "time", "event_id")}
                          | {"synced": bool(g.get("workout_ids")),
                             "steps": s.get("steps") or [], "legs": s.get("legs") or [],
                             "exercises": s.get("exercises") or [], "prehab": s.get("prehab") or [],
                             "fuel": fuel(s, d, race_date=plan.get("race_date"), distance=plan.get("distance"))})
            days.append({"date": d, "sessions": ss})
        weeks.append({k: w[k] for k in ("index", "start", "phase", "recovery", "hours", "focus")}
                     | {"days": days})
    cur = week_for(plan, today)
    return {k: plan.get(k) for k in ("start", "first_day", "race_date", "distance", "race_kind",
                                     "level", "peak_hours", "start_hours", "note", "created",
                                     "updated")} | {
        "events": plan.get("events") or [], "events_changed": bool(plan.get("events_changed")),
        "trips": [{k: t[k] for k in ("id", "start", "end", "label", "has")} for t in plan.get("trips", [])],
        "race_changed": bool(plan.get("race_changed")),
        "origin": {k: (plan.get("origin") or {}).get(k) for k in ("kind", "by_name", "at", "source", "name")}
        if plan.get("origin") else None} | {
        "weeks": weeks, "current_week": cur["index"] if cur else None,
        "today": today.isoformat(),  # the athlete's local date (the device clock may differ)
        "garmin": plan.get("garmin") or {}, "pending_removals": len(plan.get("garmin_orphans", [])),
        "kinds": {k: list(v) for k, v in KINDS_BY_SPORT.items()},
    }


__all__ = ["PlanService", "PlanError", "public_plan", "SYNC_WINDOWS", "CoachError"]
