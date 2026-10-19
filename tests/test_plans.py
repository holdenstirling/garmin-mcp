"""Plan builder: generation, edits, Garmin sync (against the fake Garmin) and the API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import (
    PlanError,
    build_plan,
    build_steps,
    describe,
    garmin_workouts,
    iter_sessions,
    phases,
    step_minutes,
)
from garmin_mcp.providers.fake import FAKE_WORKOUTS
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 14)  # a Wednesday


def _athlete(**kw):
    a = {"weekly_hours": 8, "level": "intermediate", "available_days": ["tue", "wed", "thu", "sat", "sun"],
         "long_day": "sat", "ftp_w": 250, "run_threshold_pace": 270}
    a.update(kw)
    return a


# ------------------------------------------------------------ generation --
def test_phases_end_in_race_week_with_taper() -> None:
    assert phases(1, 2) == ["race"]
    p = phases(37, 2)
    assert p[-1] == "race" and p[-3:-1] == ["taper", "taper"]
    assert p.index("build") < p.index("peak") and p[0] == "base"
    assert phases(5, 1) == ["base", "base", "build", "taper", "race"]


def test_70_3_plan_shape() -> None:
    plan = build_plan(_athlete(), {"title": "Boulder 70.3", "date": "2027-06-26", "distance": "70.3",
                                   "limiters": ["swim"]}, today=TODAY)
    weeks = plan["weeks"]
    assert plan["start"] == "2026-10-12" and plan["first_day"] == "2026-10-14"
    assert len(weeks) == 37 and weeks[-1]["phase"] == "race"
    assert all(d >= "2026-10-14" for d in weeks[0]["days"])  # nothing before the start day
    race = [s for _, d, s in iter_sessions(plan) if s.get("kind") == "race"]
    assert len(race) == 1 and race[0]["title"] == "Race day: Boulder 70.3"
    # Recovery weeks every 4th base/build week, and they're lighter than their neighbours.
    rec = [w for w in weeks if w["recovery"]]
    assert rec and all(w["hours"] < weeks[w["index"] - 2]["hours"] for w in rec)
    build = next(w for w in weeks if w["phase"] == "build" and not w["recovery"])
    sports = {s["sport"] for ss in build["days"].values() for s in ss}
    assert {"swim", "bike", "run", "brick"} <= sports
    sat = build["days"][(date.fromisoformat(build["start"]) + timedelta(days=5)).isoformat()]
    assert sat[0]["sport"] == "brick" and len(sat[0]["legs"]) == 2
    # Only the athlete's days (plus explicit rest days elsewhere).
    for d, ss in build["days"].items():
        wd = date.fromisoformat(d).strftime("%a").lower()[:3]
        if wd not in ("tue", "wed", "thu", "sat", "sun"):
            assert [s["sport"] for s in ss] == ["rest"]


def test_run_plan_and_no_pool_skips_swims() -> None:
    plan = build_plan(_athlete(equipment=["treadmill"]), {"title": "Tri", "date": "2027-05-01",
                                                          "distance": "olympic triathlon"}, today=TODAY)
    assert not any(s["sport"] == "swim" for _, _, s in iter_sessions(plan))
    plan = build_plan(_athlete(), {"title": "Marathon", "date": "2027-03-14", "distance": "marathon"},
                      today=TODAY)
    assert {s["sport"] for _, _, s in iter_sessions(plan)} <= {"run", "strength", "rest"}
    long_runs = [s["minutes"] for _, _, s in iter_sessions(plan) if s.get("kind") == "long"]
    assert max(long_runs) <= 180


def test_build_errors() -> None:
    with pytest.raises(PlanError):
        build_plan(_athlete(), {"title": "x", "distance": "5k"}, today=TODAY)  # no date
    with pytest.raises(PlanError):
        build_plan(_athlete(), {"title": "x", "date": "2026-01-01", "distance": "5k"}, today=TODAY)
    far = build_plan(_athlete(), {"title": "x", "date": "2028-06-01", "distance": "140.6"}, today=TODAY)
    assert len(far["weeks"]) == 52 and far["note"]


def test_steps_and_detail() -> None:
    steps = build_steps("run", "threshold", 60)
    assert describe(steps) == "15' warm-up · 3× (8' Z4, 3' easy) · 12' cool-down"
    assert step_minutes(steps) == 60
    swim = build_steps("swim", "css", 45, swim_pace=110)
    assert swim[1]["type"] == "repeat" and swim[1]["steps"][0]["meters"] == 100


def test_garmin_workout_json() -> None:
    plan = build_plan(_athlete(), {"title": "R", "date": "2027-06-26", "distance": "70.3"}, today=TODAY)
    sessions = [s for _, _, s in iter_sessions(plan)]
    thr = next(s for s in sessions if s["sport"] == "bike" and s["kind"] == "threshold")
    (wo,) = garmin_workouts(thr, {"ftp_w": 250})
    assert wo["sportType"]["sportTypeKey"] == "cycling" and wo["workoutName"].startswith("rabbt: ")
    steps = wo["workoutSegments"][0]["workoutSteps"]
    rep = next(s for s in steps if s["type"] == "RepeatGroupDTO")
    work = rep["workoutSteps"][0]
    assert work["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (work["targetValueOne"], work["targetValueTwo"]) == (228, 262)  # 91-105% of 250
    assert [s["stepOrder"] for s in steps] == sorted(s["stepOrder"] for s in steps)
    assert rep["workoutSteps"][0]["childStepId"] == rep["childStepId"]
    # No thresholds: heart-rate zones from the watch.
    (wo,) = garmin_workouts(thr, {})
    w = next(s for s in wo["workoutSegments"][0]["workoutSteps"] if s["type"] == "RepeatGroupDTO")
    assert w["workoutSteps"][0]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert w["workoutSteps"][0]["zoneNumber"] == 4
    brick = next(s for s in sessions if s["sport"] == "brick")
    assert [x["sportType"]["sportTypeKey"] for x in garmin_workouts(brick, {})] == ["cycling", "running"]
    swim = next(s for s in sessions if s["sport"] == "swim")
    (sw,) = garmin_workouts(swim, {})
    assert sw["poolLength"] == 25.0
    assert sw["workoutSegments"][0]["workoutSteps"][0]["endCondition"]["conditionTypeKey"] == "distance"
    race = next(s for s in sessions if s.get("kind") == "race")
    assert garmin_workouts(race, {}) == []


# ------------------------------------------------------- service + sync --
def _setup(env, distance="70.3", weeks=30):
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": distance,
                                       "date": (today + timedelta(weeks=weeks)).isoformat()})
    plan = agent.plans.build("friend")
    return agent, plan, today


def test_build_publishes_summary_and_week_view(env) -> None:
    agent, plan, today = _setup(env)
    g = agent.coach.active_goal("friend")
    assert g["plan_source"] == "builder" and g["plan_weeks"] == len(plan["weeks"])
    assert g["plan"].startswith("### Overview") and "Typical week" in g["plan"]
    pw, week = agent.planner.cached_days("friend", g, today)
    assert week["source"] == "builder" and today.isoformat() in week["days"]
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "plan builder" in ctx and "ftp w: 250 W" in ctx and "4:30 per km" in ctx


def test_edit_add_delete_session(env) -> None:
    agent, plan, today = _setup(env)
    day = next(d for _, d, s in iter_sessions(plan) if d > today.isoformat() and s["sport"] == "run")
    sid = next(s["id"] for _, d, s in iter_sessions(plan) if d == day and s["sport"] == "run")
    p = agent.plans.update_session("friend", sid, {"kind": "tempo", "minutes": 50})
    s = next(s for _, _, s in iter_sessions(p) if s["id"] == sid)
    assert (s["kind"], s["minutes"], s["title"]) == ("tempo", 50, "Tempo run") and "Z3" in s["detail"]
    p = agent.plans.update_session("friend", sid, {"title": "Hill tempo", "minutes": 55})
    s = next(s for _, _, s in iter_sessions(p) if s["id"] == sid)
    assert s["title"] == "Hill tempo" and s["minutes"] == 55  # custom title survives edits
    other = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    p = agent.plans.update_session("friend", sid, {"date": other})
    assert any(s["id"] == sid for _, d, s in iter_sessions(p) if d == other)
    p = agent.plans.add_session("friend", {"date": day, "sport": "swim", "minutes": 40})
    assert any(s["sport"] == "swim" for _, d, s in iter_sessions(p) if d == day)
    p = agent.plans.delete_session("friend", sid)
    assert not any(s["id"] == sid for _, _, s in iter_sessions(p))
    for bad in ({"minutes": 5}, {"sport": "curling"}, {"color": "red"}):
        with pytest.raises(PlanError):
            agent.plans.update_session("friend", next(s["id"] for _, _, s in iter_sessions(p)
                                                      if s["sport"] == "bike"), bad)
    with pytest.raises(PlanError):
        agent.plans.add_session("friend", {"date": (today - timedelta(days=3)).isoformat(), "sport": "run"})


def test_sync_is_incremental_and_cleans_up(env) -> None:
    FAKE_WORKOUTS.update({"next": 0, "uploaded": {}, "scheduled": {}, "deleted": []})
    agent, plan, today = _setup(env)
    r = agent.plans.sync("friend", 7)
    real = [s for _, d, s in iter_sessions(plan)
            if today.isoformat() <= d <= (today + timedelta(days=6)).isoformat()
            and s["sport"] != "rest"]
    want = sum(len(s.get("legs") or [1]) for s in real)
    assert r["uploaded"] == len(real) and not r["errors"]
    assert len(FAKE_WORKOUTS["uploaded"]) == want == len(FAKE_WORKOUTS["scheduled"])
    assert all(d >= today.isoformat() for _, d in FAKE_WORKOUTS["scheduled"].values())
    # Nothing changed: nothing re-uploaded.
    r = agent.plans.sync("friend", 7)
    assert (r["uploaded"], r["unchanged"]) == (0, len(real))
    # Edit one: only that one is replaced (old workout deleted).
    sid = real[0]["id"]
    agent.plans.update_session("friend", sid, {"minutes": 70})
    r = agent.plans.sync("friend", 7)
    assert r["uploaded"] == 1 and len(FAKE_WORKOUTS["deleted"]) == len(real[0].get("legs") or [1])
    # Delete one: its workout is removed on the next sync.
    victim = real[-1]
    agent.plans.delete_session("friend", victim["id"])
    before = len(FAKE_WORKOUTS["deleted"])
    r = agent.plans.sync("friend", 7)
    assert r["removed"] == len(victim.get("legs") or [1]) and len(FAKE_WORKOUTS["deleted"]) > before
    # Remove everything from Garmin.
    r = agent.plans.unsync("friend")
    assert r["removed"] >= 1 and FAKE_WORKOUTS["uploaded"] == {}
    assert not any((s.get("garmin") or {}).get("workout_ids")
                   for _, _, s in iter_sessions(agent.plans.get("friend")))
    with pytest.raises(PlanError):
        agent.plans.sync("friend", 9)


def test_rebuild_orphans_synced_workouts(env) -> None:
    FAKE_WORKOUTS.update({"next": 0, "uploaded": {}, "scheduled": {}, "deleted": []})
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    n = len(FAKE_WORKOUTS["uploaded"])
    p = agent.plans.build("friend")
    assert len(p["garmin_orphans"]) == n
    agent.plans.sync("friend", 7)
    assert len(FAKE_WORKOUTS["deleted"]) == n


def test_athlete_and_goal_validation(env) -> None:
    agent, _ = env.agent([])
    c = agent.coach
    a = c.update_athlete("friend", {"available_days": ["sun", "tue"], "equipment": ["pool"],
                                    "height_cm": 178.4, "sex": "male", "long_day": "sun"})
    assert a["available_days"] == ["tue", "sun"] and a["height_cm"] == 178
    for bad in ({"available_days": ["someday"]}, {"max_hr": 400}, {"level": "pro"}, {"long_day": "x"}):
        with pytest.raises(CoachError):
            c.update_athlete("friend", bad)
    g = c.create_goal("friend", {"title": "X", "target_time": "5:30:00", "limiters": ["run", "swim"],
                                 "goal_type": "time", "priority": "A"})
    assert g["limiters"] == ["swim", "run"] and g["target_time"] == "5:30:00"
    for bad in ({"target_time": "fast"}, {"limiters": ["ski"]}, {"goal_type": "win"}):
        with pytest.raises(CoachError):
            c.update_goal("friend", g["id"], bad)


def test_numbers_prefill_from_garmin(env) -> None:
    agent, _ = env.agent([])
    n = agent.plans.garmin_numbers("friend")
    assert n["weight_kg"] == 72.5 and n["height_cm"] == 178 and n["max_hr"] == 188
    assert n["threshold_hr"] == 168 and n["ftp_w"] == 245 and n["sex"] == "male"


# ------------------------------------------------------------------- API --
def test_api_setup_edit_sync(env, tmp_path) -> None:
    FAKE_WORKOUTS.update({"next": 0, "uploaded": {}, "scheduled": {}, "deleted": []})
    agent, _ = env.agent([])
    agent.plans._pause = 0
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    race = (agent._now("friend").date() + timedelta(weeks=20)).isoformat()
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            assert (await c.get("/app/api/plan")).json() == {"plan": None}
            r = await c.post("/app/api/plan/setup", headers=h, json={
                "athlete": {"weekly_hours": 6, "available_days": ["tue", "thu", "sat", "sun"]},
                "goal": {"title": "Half", "distance": "half marathon", "date": race,
                         "target_time": "1:45:00"}})
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["goal"]["target_time"] == "1:45:00" and body["plan"]["weeks"]
            assert body["plan"]["current_week"] == 1 and body["athlete"]["weekly_hours"] == 6.0
            # Validation errors come back with their message.
            r = await c.post("/app/api/plan/setup", headers=h, json={"goal": {"target_time": "soon"}})
            assert r.status_code == 400 and "target time" in r.json()["error"]
            sess = next(s for w in body["plan"]["weeks"] for d in w["days"] for s in d["sessions"]
                        if s["sport"] == "run")
            r = await c.patch(f"/app/api/plan/sessions/{sess['id']}", headers=h, json={"minutes": 5})
            assert r.status_code == 400 and "10 to 600" in r.json()["error"]
            r = await c.patch(f"/app/api/plan/sessions/{sess['id']}", headers=h, json={"minutes": 50})
            assert r.status_code == 200
            r = await c.post("/app/api/plan/garmin/sync", headers=h, json={"days": 14})
            assert r.status_code == 200 and r.json()["result"]["uploaded"] >= 1
            assert r.json()["plan"]["garmin"]["synced_at"]
            n = (await c.get("/app/api/garmin/numbers")).json()["numbers"]
            assert n["ftp_w"] == 245
            r = await c.request("DELETE", "/app/api/plan", headers=h, json={})
            assert r.status_code == 200 and r.json()["removed"] >= 1, r.text
            assert (await c.get("/app/api/plan")).json() == {"plan": None}
            # Without Origin, mutating calls are refused.
            assert (await c.post("/app/api/plan/rebuild", json={})).status_code == 403
    asyncio.run(go_())
