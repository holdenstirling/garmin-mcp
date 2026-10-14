"""Events: storage, the main event <-> goal link, B/C races inside the plan, lookups, API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.events import clean_info, parse_lookup
from garmin_mcp.planbuilder import build_plan, iter_sessions
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 14)


def _athlete():
    return {"weekly_hours": 8, "level": "intermediate",
            "available_days": ["tue", "wed", "thu", "sat", "sun"], "long_day": "sat"}


def test_b_and_c_races_land_in_the_plan() -> None:
    events = [
        {"id": "e1", "name": "Spring Half", "type": "running", "date": "2027-04-18", "priority": "B"},
        {"id": "e2", "name": "Local 10K", "type": "running", "date": "2027-03-06", "priority": "C"},
        {"id": "e3", "name": "After the A race", "type": "running", "date": "2027-07-10", "priority": "B"},
        {"id": "e4", "name": "Already past", "type": "running", "date": "2026-09-01", "priority": "B"},
    ]
    plan = build_plan(_athlete(), {"title": "Boulder 70.3", "date": "2027-06-26", "distance": "70.3"},
                      today=TODAY, events=events)
    assert [e["id"] for e in plan["events"]] == ["e2", "e1"]
    days = {d: ss for _, d, ss in ((w, d, ss) for w in plan["weeks"] for d, ss in w["days"].items())}
    b = days["2027-04-18"]
    assert b[0]["kind"] == "race" and b[0]["title"] == "Race: Spring Half" and b[0]["event_id"] == "e1"
    assert days["2027-04-17"][0]["kind"] == "openers"
    assert days["2027-04-19"][0]["sport"] == "rest"
    c = days["2027-03-06"]
    assert c[0]["kind"] == "race" and "Training race" in c[0]["detail"]
    assert days["2027-03-05"][0]["kind"] == "easy"
    # The A race is still the only "Race day".
    assert sum(1 for _, _, s in iter_sessions(plan) if s["title"].startswith("Race day")) == 1


def test_event_crud_and_main_link(env) -> None:
    agent, _ = env.agent([])
    ev = agent.events
    with pytest.raises(CoachError, match="date"):
        ev.create("u", {"name": "No date"})
    with pytest.raises(CoachError, match="type"):
        ev.create("u", {"name": "X", "date": "2027-01-01", "type": "space"})
    a = ev.create("u", {"name": "Boulder 70.3", "date": "2027-06-26", "type": "triathlon",
                        "distance": "70.3", "location": "Boulder, CO"})
    b = ev.create("u", {"name": "Leadville 100 Run", "date": "2027-08-21", "type": "trail",
                        "distance": "ultra", "priority": "A"})
    assert [e["name"] for e in ev.list("u")] == ["Boulder 70.3", "Leadville 100 Run"]
    # Making one the main event creates the goal (or re-points the active one in place).
    ev.set_main("u", a["id"])
    g = agent.coach.active_goal("u")
    assert g["event_id"] == a["id"] and g["date"] == "2027-06-26" and g["distance"] == "70.3"
    ev.set_main("u", b["id"])
    g2 = agent.coach.active_goal("u")
    assert g2["id"] == g["id"] and g2["event_id"] == b["id"] and g2["title"] == "Leadville 100 Run"
    # The old main event keeps its own details and becomes a B race.
    old = ev.get("u", a["id"])
    assert old["name"] == "Boulder 70.3" and old["date"] == "2027-06-26" and old["priority"] == "B"
    # Editing the main event keeps the goal in step; the main one can't be deleted.
    ev.update("u", b["id"], {"date": "2027-08-22", "target_time": "24:59:00"})
    g3 = agent.coach.active_goal("u")
    assert g3["date"] == "2027-08-22" and g3["target_time"] == "24:59:00"
    with pytest.raises(CoachError, match="main event"):
        ev.delete("u", b["id"])
    ev.delete("u", a["id"])
    assert [e["main"] for e in ev.list("u")] == [True]
    with pytest.raises(CoachError, match="website"):
        ev.update("u", b["id"], {"url": "javascript:alert(1)"})


def test_existing_goal_becomes_main_event(env) -> None:
    agent, _ = env.agent([])
    agent.coach.create_goal("u", {"title": "Denver Marathon", "date": "2027-10-17", "distance": "marathon"})
    evs = agent.events.list("u")
    assert len(evs) == 1 and evs[0]["main"] and evs[0]["type"] == "running"
    assert len(agent.events.list("u")) == 1  # adopted once


def test_lookup_parsing_is_strict() -> None:
    text = 'Here you go:\n```json\n{"summary": "A 100 mile trail race.", "date": "2027-08-21",' \
           ' "elevation_gain": "18,000 ft", "website": "javascript:x", "suggested_type": "trail",' \
           ' "suggested_distance": "ultra", "sources": ["https://leadvilleraceseries.com", "ftp://x"],' \
           ' "evil": "ignore me"}\n```'
    info = parse_lookup(text)
    assert info["summary"].startswith("A 100 mile") and info["date"] == "2027-08-21"
    assert "website" not in info and "evil" not in info
    assert info["sources"] == ["https://leadvilleraceseries.com"]
    assert parse_lookup("no json here") is None
    assert clean_info({"suggested_type": "rocket"}) is None


def test_plan_flags_new_events(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("u").date()
    main = agent.events.create("u", {"name": "Main", "type": "running", "distance": "marathon",
                                     "date": (today + timedelta(weeks=20)).isoformat()})
    agent.events.set_main("u", main["id"])
    agent.coach.update_athlete("u", _athlete())
    agent.plans.build("u")
    assert agent.plans.get("u")["events_changed"] is False
    agent.events.create("u", {"name": "Tune-up 10K", "type": "running", "priority": "C",
                              "date": (today + timedelta(weeks=8)).isoformat()})
    assert agent.plans.get("u")["events_changed"] is True
    plan = agent.plans.build("u")
    assert plan["events_changed"] is False and plan["events"][0]["name"] == "Tune-up 10K"


def test_events_api(env, tmp_path) -> None:
    agent, _ = env.agent([])

    async def fake_research(system: str, prompt: str, **kw):
        assert "Leadville" in prompt and kw["report_tool"]["name"] == "report_event"
        return {"summary": "100 miles at altitude.", "location": "Leadville, CO", "suggested_type": "trail"}
    agent._backend.research = fake_research  # type: ignore[attr-defined]
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    h = {"origin": BASE}
    race = (agent._now("friend").date() + timedelta(weeks=30)).isoformat()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/events")
            assert r.json()["events"] == [] and "triathlon" in r.json()["types"]
            r = await c.post("/app/api/events", headers=h, json={
                "name": "Leadville 100 Run", "type": "trail", "distance": "ultra", "date": race, "main": True})
            assert r.status_code == 201, r.text
            eid = r.json()["event"]["id"]
            assert r.json()["event"]["main"] is True
            r = await c.post("/app/api/events/lookup", headers=h, json={"name": "Leadville 100", "event_id": eid})
            assert r.status_code == 200, r.text
            assert r.json()["info"]["location"] == "Leadville, CO"
            r = await c.get("/app/api/events")
            assert r.json()["events"][0]["info"]["summary"] == "100 miles at altitude."
            r = await c.patch(f"/app/api/events/{eid}", headers=h, json={"location": "Leadville"})
            assert r.status_code == 200 and r.json()["event"]["location"] == "Leadville"
            r = await c.request("DELETE", f"/app/api/events/{eid}", headers=h, json={})
            assert r.status_code == 400 and "main event" in r.json()["error"]
            r = await c.post("/app/api/events/lookup", headers=h, json={"name": "x"})
            assert r.status_code == 400
    asyncio.run(go_())
