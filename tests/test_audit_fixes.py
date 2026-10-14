"""Regression tests for the October 2026 audit: goal/event drift, stale plans, Garmin
bookkeeping, per-day limits, atomic setup, favorites, profile text fields."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.events import type_for_distance
from garmin_mcp.planbuilder import PlanError, build_plan, iter_sessions
from garmin_mcp.providers import GarminError
from garmin_mcp.providers.fake import FAKE_WORKOUTS
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _athlete, _setup

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 14)


def _reset():
    FAKE_WORKOUTS.update({"next": 0, "uploaded": {}, "scheduled": {}, "deleted": []})


def test_goal_edits_flow_to_the_main_event_and_back(env) -> None:
    agent, _ = env.agent([])
    ev = agent.events.create("u", {"name": "Big Race", "date": "2027-06-01", "type": "running",
                                   "distance": "marathon", "target_time": "3:30:00", "goal_type": "time"})
    agent.events.set_main("u", ev["id"])
    g = agent.coach.active_goal("u")
    # Rabbit (save_goal) moves the race: the event follows.
    agent.coach.update_goal("u", g["id"], {"date": "2027-07-15", "target_time": "3:20:00"})
    e = agent.events.get("u", ev["id"])
    assert e["date"] == "2027-07-15" and e["target_time"] == "3:20:00"
    # An unrelated event edit doesn't roll the goal back.
    agent.events.update("u", ev["id"], {"notes": "book hotel"})
    g = agent.coach.active_goal("u")
    assert g["date"] == "2027-07-15" and g["target_time"] == "3:20:00"


def test_plan_flags_a_moved_race(env) -> None:
    agent, plan, today = _setup(env, distance="marathon", weeks=20)
    assert agent.plans.get("friend")["race_changed"] is False
    g = agent.coach.active_goal("friend")
    agent.coach.update_goal("friend", g["id"], {"date": (today + timedelta(weeks=22)).isoformat()})
    assert agent.plans.get("friend")["race_changed"] is True
    agent.plans.build("friend")
    assert agent.plans.get("friend")["race_changed"] is False


def test_moves_into_the_past_are_refused_and_synced_moves_are_cleaned_up(env) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    s = next(x for _, d, x in iter_sessions(agent.plans.get("friend"))
             if d >= today.isoformat() and (x.get("garmin") or {}).get("workout_ids"))
    with pytest.raises(PlanError, match="past"):
        agent.plans.update_session("friend", s["id"], {"date": (today - timedelta(days=1)).isoformat()})
    ids = s["garmin"]["workout_ids"]
    agent.plans.update_session("friend", s["id"], {"date": (today + timedelta(days=40)).isoformat()})
    p = agent.plans.get("friend")
    assert set(ids) <= set(p["garmin_orphans"])  # removed on the next sync
    agent.plans.sync("friend", 7)
    assert set(ids) <= set(FAKE_WORKOUTS["deleted"])


def test_turning_a_synced_session_into_rest_removes_its_workout(env) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    s = next(x for _, d, x in iter_sessions(agent.plans.get("friend"))
             if (x.get("garmin") or {}).get("workout_ids") and x["sport"] != "brick")
    agent.plans.update_session("friend", s["id"], {"sport": "rest"})
    assert set(s["garmin"]["workout_ids"]) <= set(agent.plans.get("friend")["garmin_orphans"])


def test_half_made_uploads_are_recorded(env, monkeypatch) -> None:
    _reset()
    agent, plan, today = _setup(env)
    svc = agent.plans._service

    def broken_schedule(user_id, wid, day):
        raise GarminError("Garmin returned an error.")
    monkeypatch.setattr(svc, "workout_schedule", broken_schedule)
    r = agent.plans.sync("friend", 7)
    assert r["errors"] and r["uploaded"] == 0
    orphans = agent.plans.get("friend")["garmin_orphans"]
    assert orphans and set(orphans) <= set(FAKE_WORKOUTS["uploaded"])


def test_crowded_days_stay_editable_and_capped() -> None:
    a = _athlete(available_days=["sat", "sun"], long_day="sat", level="advanced")
    plan = build_plan(a, {"title": "T", "date": "2027-06-26", "distance": "70.3"}, today=TODAY)
    assert max(len(ss) for w in plan["weeks"] for ss in w["days"].values()) <= 4


def test_same_day_edit_ignores_the_limit(env) -> None:
    agent, plan, today = _setup(env)
    day, s = next((d, x) for _, d, x in iter_sessions(agent.plans.get("friend"))
                  if d > today.isoformat() and x["sport"] != "rest" and x.get("kind") != "race")
    for _ in range(3):
        try:
            agent.plans.add_session("friend", {"date": day, "sport": "run"})
        except PlanError:
            break
    agent.plans.update_session("friend", s["id"], {"title": "Renamed"})  # must not raise


def test_setup_saves_nothing_when_the_build_would_fail(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/plan/setup", headers=h, json={
                "athlete": {"weekly_hours": 9}, "goal": {"title": "Old", "distance": "10k", "date": "2020-01-01"}})
            assert r.status_code == 400
    asyncio.run(go_())
    assert agent.coach.active_goal("friend") is None
    assert agent.coach.athlete("friend").get("weekly_hours") is None


def test_new_goal_hands_old_garmin_workouts_to_the_new_plan(env, tmp_path) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    old_ids = [i for _, _, x in iter_sessions(agent.plans.get("friend"))
               for i in (x.get("garmin") or {}).get("workout_ids", [])]
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/plan/setup", headers={"origin": BASE}, json={
                "new_goal": True, "goal": {"title": "New", "distance": "10k",
                                           "date": (today + timedelta(weeks=12)).isoformat()}})
            assert r.status_code == 201, r.text
    asyncio.run(go_())
    assert set(old_ids) <= set(agent.plans.get("friend")["garmin_orphans"])


def test_favorite_sports_shape_a_general_plan(env) -> None:
    agent, _ = env.agent([])
    with pytest.raises(CoachError):
        agent.coach.update_athlete("u", {"favorite_sports": ["quidditch"]})
    a = agent.coach.update_athlete("u", {"favorite_sports": ["swim", "trail", "yoga"]})
    plan = build_plan(_athlete(**a), {"title": "Fun", "date": "2027-03-01", "distance": "other"},
                      today=TODAY)
    sports = {x["sport"] for _, _, x in iter_sessions(plan)}
    assert "swim" in sports and "run" in sports and "bike" not in sports


def test_profile_text_fields_can_be_cleared(env) -> None:
    agent, _ = env.agent([])
    assert agent.coach.update_athlete("u", {"experience": None})["experience"] == ""


def test_type_for_distance() -> None:
    assert type_for_distance("other") == "other" and type_for_distance("") == "other"
    assert type_for_distance("70.3") == "triathlon" and type_for_distance("century ride") == "cycling"
