"""Weekly rhythm (sport by weekday) and the strength opt-in: validation, placement, gating,
legacy favorites, rest days, warnings, unchanged builds without a rhythm, the chat tool and
the /app/api/plan/rhythm API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaching import CoachError, strength_on, validate_rhythm
from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import DAYS, build_plan, garmin_workouts
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 26)  # a Monday
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LIFT_BIKE = {"mon": ["strength"], "wed": ["strength"], "fri": ["strength"],
             "tue": ["bike"], "thu": ["bike"], "sat": ["bike"]}


def _goal(distance="half marathon", weeks=14):
    return {"title": "Race", "distance": distance, "date": (TODAY + timedelta(weeks=weeks)).isoformat()}


def _ath(**kw):
    a = {"weekly_hours": 7, "level": "intermediate", "available_days": list(ALL), "long_day": "sun"}
    a.update(kw)
    return a


def _by_weekday(week):
    out = {}
    for d, ss in week["days"].items():
        out[DAYS[date.fromisoformat(d).weekday()]] = [s for s in ss if s["sport"] != "rest"]
    return out


def _sessions(plan):
    return [s for w in plan["weeks"] for ss in w["days"].values() for s in ss]


# ---------------------------------------------------------------- validation --
def test_validate_rhythm() -> None:
    assert validate_rhythm({"mon": ["strength"], "tue": "bike", "wed": [], "thu": "any"}) == \
        {"mon": ["strength"], "tue": ["bike"]}
    assert validate_rhythm(None) == {} and validate_rhythm({}) == {}
    assert validate_rhythm({"mon": ["run", "run", "strength"]}) == {"mon": ["run", "strength"]}
    for bad in ({"monday": ["run"]}, {"mon": ["yoga"]}, {"mon": ["run", "bike", "swim"]},
                {"mon": ["rest", "run"]}, ["mon"], {"mon": 3}):
        with pytest.raises(CoachError):
            validate_rhythm(bad)


def test_strength_on_rules() -> None:
    assert strength_on({}) is False
    assert strength_on({"favorite_sports": ["run", "strength"]}) is True  # earlier choice
    assert strength_on({"favorite_sports": ["strength"], "strength_opt_in": False}) is False  # a no wins
    assert strength_on({"strength_opt_in": True}) is True


# ----------------------------------------------------------------- placement --
def test_rhythm_places_sports_on_their_days_with_structured_strength() -> None:
    plan = build_plan(_ath(week_rhythm=LIFT_BIKE, strength_opt_in=True), _goal(), today=TODAY)
    assert plan["needs_strength_opt_in"] is False and plan["week_rhythm"] == LIFT_BIKE
    for w in plan["weeks"]:
        if w["phase"] in ("race",):
            continue
        wd = _by_weekday(w)
        for d in ("mon", "wed", "fri"):
            st = [s for s in wd.get(d, []) if s["sport"] == "strength"]
            assert len(st) == 1, (w["index"], d, wd.get(d))
            s = st[0]
            assert 25 <= s["minutes"] <= 60
            ex = s["exercises"][0]
            assert {"name", "sets", "reps", "rest_s", "cue", "dose"} <= set(ex) and ex["cue"]
        for d in ("tue", "thu", "sat"):
            assert any(s["sport"] == "bike" for s in wd.get(d, [])), (w["index"], d)
        # No strength anywhere but the strength days.
        assert all(s["sport"] != "strength" for d in ("tue", "thu", "sat", "sun") for s in wd.get(d, []))
    # Before a long or key session the lift is the lighter upper-body/core one.
    for w in plan["weeks"]:
        wd = _by_weekday(w)
        for d in ("mon", "wed", "fri"):
            for s in wd.get(d, []):
                if s["sport"] != "strength":
                    continue
                nxt = wd.get(DAYS[(DAYS.index(d) + 1) % 7], [])
                if any(x.get("kind") in ("long", "threshold", "vo2", "tempo", "racepace", "brick") for x in nxt):
                    assert s["variant"] == "light"


def test_rest_days_stay_empty_and_long_day_moves_off_rest() -> None:
    rh = {"fri": ["rest"], "sun": ["rest"], "mon": ["run"], "wed": ["run"]}
    plan = build_plan(_ath(week_rhythm=rh, long_day="sun"), _goal("marathon", 20), today=TODAY)
    for w in plan["weeks"]:
        wd = _by_weekday(w)
        assert not wd.get("fri") and not wd.get("sun"), w["index"]
    assert any(s.get("kind") == "long" for s in _sessions(plan))


def test_picked_day_with_no_session_gets_an_easy_one() -> None:
    # A marathon plan has no rides, but Tuesday is a bike day: it gets an easy ride.
    plan = build_plan(_ath(week_rhythm={"tue": ["bike"]}), _goal("marathon", 20), today=TODAY)
    w = next(w for w in plan["weeks"] if w["phase"] == "build")
    assert any(s["sport"] == "bike" for s in _by_weekday(w)["tue"])


# ---------------------------------------------------------------- strength gate --
def test_no_strength_without_opt_in() -> None:
    plan = build_plan(_ath(), _goal(), today=TODAY)  # run plans used to add strength by default
    assert not any(s["sport"] == "strength" and s.get("kind") == "strength" for s in _sessions(plan))
    on = build_plan(_ath(strength_opt_in=True), _goal(), today=TODAY)
    assert any(s["sport"] == "strength" for s in _sessions(on))
    legacy = build_plan(_ath(favorite_sports=["run", "strength"]), _goal(), today=TODAY)
    assert any(s["sport"] == "strength" for s in _sessions(legacy))


def test_strength_days_without_opt_in_are_any_days_and_flagged() -> None:
    plan = build_plan(_ath(week_rhythm=LIFT_BIKE), _goal(), today=TODAY)
    assert plan["needs_strength_opt_in"] is True
    assert not any(s["sport"] == "strength" and s.get("kind") == "strength" for s in _sessions(plan))
    assert any("strength workouts are off" in x for x in plan["warnings"])
    assert plan["week_rhythm"] == {k: v for k, v in LIFT_BIKE.items() if v != ["strength"]}


# ------------------------------------------------------------------ warnings --
def test_warns_when_rhythm_leaves_too_little_room() -> None:
    rh = {d: ["bike"] for d in ALL}  # a half marathon with no run days and no open days
    plan = build_plan(_ath(week_rhythm=rh), _goal(), today=TODAY)
    assert any("no run days" in x for x in plan["warnings"])
    assert any(s["sport"] == "run" for s in _sessions(plan))  # still builds the runs
    assert all("—" not in x for x in plan["warnings"])


def test_unchanged_without_rhythm() -> None:
    """No rhythm: same days, same sports per day as before (strength excepted)."""
    a = _ath(available_days=["tue", "wed", "thu", "sat", "sun"], long_day="sat", strength_opt_in=True)
    p1 = build_plan(a, _goal("70.3", 20), today=TODAY)
    p2 = build_plan(dict(a, week_rhythm={}), _goal("70.3", 20), today=TODAY)
    shape = lambda p: [[(d, [(s["sport"], s["kind"], s["minutes"]) for s in ss]) for d, ss in sorted(w["days"].items())]  # noqa: E731
                       for w in p["weeks"]]
    assert shape(p1) == shape(p2) and p1["warnings"] == []


def test_garmin_send_of_structured_strength() -> None:
    plan = build_plan(_ath(week_rhythm=LIFT_BIKE, strength_opt_in=True), _goal(), today=TODAY)
    s = next(s for s in _sessions(plan) if s["sport"] == "strength")
    [wo] = garmin_workouts(s, {})
    assert wo["sportType"]["sportTypeKey"] == "other" and s["exercises"][0]["name"] in wo["description"]
    assert wo["estimatedDurationInSecs"] > 0


# ---------------------------------------------------------------- chat + API --
def test_chat_tool_saves_rhythm_and_rebuilds(env) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", _ath())
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=14)).isoformat()})
    agent.plans.build("friend")
    out = agent._dispatch("friend", "update_athlete_profile", {"week_rhythm": LIFT_BIKE})
    assert out["plan_rebuilt"] is True and out["needs_strength_opt_in"] is True
    out = agent._dispatch("friend", "update_athlete_profile", {"strength_opt_in": True})
    assert out["needs_strength_opt_in"] is False
    plan = agent.plans.get("friend")
    assert any(s["sport"] == "strength" for s in _sessions(plan))


def test_rhythm_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    race = (agent._now("friend").date() + timedelta(weeks=14)).isoformat()
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/plan/rhythm")
            assert r.status_code == 200 and r.json() == {"week_rhythm": {}, "strength_opt_in": None,
                                                          "strength_on": False, "needs_strength_opt_in": False}
            # No plan yet: saves, nothing to rebuild.
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"week_rhythm": LIFT_BIKE})
            assert r.status_code == 200, r.text
            assert r.json()["needs_strength_opt_in"] is True and r.json()["plan"] is None
            # Setup accepts both fields.
            r = await c.post("/app/api/plan/setup", headers=h, json={
                "athlete": {"weekly_hours": 7, "available_days": ALL, "week_rhythm": LIFT_BIKE, "strength_opt_in": True},
                "goal": {"title": "Half", "distance": "half marathon", "date": race}})
            assert r.status_code == 201, r.text
            sess = [s for w in r.json()["plan"]["weeks"] for d in w["days"] for s in d["sessions"]]
            st = next(s for s in sess if s["sport"] == "strength")
            assert st["exercises"][0]["sets"] and st["variant"] in ("heavy", "light")
            # Opting out (with the strength days cleared) rebuilds without strength.
            r = await c.put("/app/api/plan/rhythm", headers=h, json={
                "strength_opt_in": False, "week_rhythm": {"tue": ["bike"], "thu": ["bike"], "sat": ["bike"]}})
            body = r.json()
            assert r.status_code == 200 and body["strength_opt_in"] is False and body["plan"]
            assert isinstance(body["warnings"], list)
            sess = [s for w in body["plan"]["weeks"] for d in w["days"] for s in d["sessions"]]
            assert not any(s["sport"] == "strength" and s["kind"] == "strength" for s in sess)
            # Bad input: a readable error.
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"week_rhythm": {"mon": ["rest", "run"]}})
            assert r.status_code == 400 and "rest day" in r.json()["error"]
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"nope": 1})
            assert r.status_code == 400
    asyncio.run(go_())
