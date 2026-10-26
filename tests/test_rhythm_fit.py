"""Saving a weekly rhythm fits it into the plan the athlete already has (plans.apply_rhythm,
rhythmfit.py): same sessions on new days, hand edits / trips / club runs / race week / the
past untouched, coach plans never gain or lose endurance sessions, strength added and removed
by the opt-in rules, moved Garmin workouts orphaned like a hand move, and the rebuild flag."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import DAYS
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
RUN_BIKE = {"mon": ["run"], "wed": ["run"], "fri": ["run"], "tue": ["bike"], "thu": ["bike"], "sat": ["bike"],
            "sun": ["rest"]}
LIFT_BIKE = {"mon": ["strength"], "wed": ["strength"], "fri": ["strength"],
             "tue": ["bike"], "thu": ["bike"], "sat": ["bike"]}


def _setup(env, distance="half marathon", **ath):
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    a = {"weekly_hours": 7, "level": "intermediate", "available_days": list(ALL), "long_day": "sat"}
    a.update(ath)
    agent.coach.update_athlete("friend", a)
    agent.coach.create_goal("friend", {"title": "Race", "distance": distance,
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    return agent, today


def _all(plan):
    return [(d, s) for w in plan["weeks"] for d, ss in w["days"].items() for s in ss if s["sport"] != "rest"]


def _wd(d):
    return DAYS[date.fromisoformat(d).weekday()]


def _doc(agent):
    g = agent.coach.active_goal("friend")
    return agent.plans._doc("friend", g["id"])


def _race_week_start(plan):
    return next(w["start"] for w in plan["weeks"] if any(s.get("kind") == "race" for ss in w["days"].values() for s in ss))


def test_built_plan_keeps_its_sessions_and_moves_them_to_rhythm_days(env) -> None:
    agent, today = _setup(env, distance="other")
    before = agent.plans.get("friend")
    ids_before = {s["id"] for _, s in _all(before) if s["sport"] != "strength"}
    agent.coach.update_athlete("friend", {"week_rhythm": RUN_BIKE})
    plan = agent.plans.apply_rhythm("friend")
    after = {s["id"] for _, s in _all(plan) if s["sport"] != "strength"}
    assert after == ids_before  # nothing regenerated, nothing lost
    assert plan["moved"] > 0
    race_start = _race_week_start(plan)
    for d, s in _all(plan):
        if today.isoformat() < d < race_start and s["sport"] in ("run", "bike") and not s.get("edited"):
            want = "run" if s["sport"] == "run" else "bike"
            assert want in RUN_BIKE.get(_wd(d), []) or _wd(d) not in RUN_BIKE, (d, s["sport"])
        if today.isoformat() < d < race_start:
            assert _wd(d) != "sun", "rest days end up empty"


def test_hand_edits_trips_club_runs_past_and_race_week_stay(env) -> None:
    agent, today = _setup(env)
    plan = agent.plans.get("friend")
    future = [(d, s) for d, s in _all(plan) if d > (today + timedelta(days=2)).isoformat() and s.get("kind") != "race"]
    (d_edit, s_edit), (d_trip, s_trip) = future[0], future[3]
    past = [(d, s["id"]) for d, s in _all(plan) if d <= today.isoformat()]
    race_start = _race_week_start(plan)
    race_week = sorted((d, s["id"]) for d, s in _all(plan) if d >= race_start)

    def mark(p):
        for w in p["weeks"]:
            for ss in w["days"].values():
                for s in ss:
                    if s["id"] == s_edit["id"]:
                        s["edited"] = True
                    if s["id"] == s_trip["id"]:
                        s["travel"] = "t1"
    _doc(agent).update(mark)
    agent.coach.update_athlete("friend", {"week_rhythm": RUN_BIKE})
    plan = agent.plans.apply_rhythm("friend")
    where = {s["id"]: d for d, s in _all(plan)}
    assert where[s_edit["id"]] == d_edit and where[s_trip["id"]] == d_trip
    assert all(where.get(i) == d for d, i in past)
    assert sorted((d, s["id"]) for d, s in _all(plan) if d >= race_start) == race_week


def test_coach_plan_never_gains_or_loses_endurance_and_warns_when_full(env) -> None:
    agent, today = _setup(env)
    _doc(agent).update(lambda d: d.__setitem__("origin", {"kind": "coach", "by_name": "Coach"}))
    before = sorted(s["id"] for _, s in _all(agent.plans.get("friend")))
    # One run day and no open days: most runs can't fit.
    agent.coach.update_athlete("friend", {"week_rhythm": {"mon": ["run"], "tue": ["bike"], "wed": ["bike"],
                                                          "thu": ["bike"], "fri": ["bike"], "sat": ["bike"],
                                                          "sun": ["rest"]}})
    plan = agent.plans.apply_rhythm("friend")
    assert sorted(s["id"] for _, s in _all(plan)) == before
    assert any("Your coach's plan has more runs" in w for w in plan["warnings"])
    assert all("—" not in w for w in plan["warnings"])


def test_strength_added_when_opted_in_and_removed_when_off(env) -> None:
    agent, today = _setup(env)
    agent.coach.update_athlete("friend", {"week_rhythm": LIFT_BIKE, "strength_opt_in": True})
    plan = agent.plans.apply_rhythm("friend")
    race_start = _race_week_start(plan)
    st = [(d, s) for d, s in _all(plan) if s["sport"] == "strength" and s.get("kind") == "strength"
          and today.isoformat() < d < race_start]
    assert st and all(_wd(d) in ("mon", "wed", "fri") for d, _ in st)
    assert all(s["exercises"] and s["exercises"][0].get("sets") for _, s in st)
    assert not any(s["sport"] == "strength" and d >= race_start for d, s in _all(plan))
    agent.coach.update_athlete("friend", {"week_rhythm": {"tue": ["bike"]}, "strength_opt_in": False})
    plan = agent.plans.apply_rhythm("friend")
    assert not any(s["sport"] == "strength" and s.get("kind") == "strength" and d > today.isoformat()
                   for d, s in _all(plan))


def test_coach_strength_is_never_removed(env) -> None:
    agent, today = _setup(env, favorite_sports=["run", "strength"])
    _doc(agent).update(lambda d: d.__setitem__("origin", {"kind": "coach", "by_name": "Coach"}))
    coach_st = {s["id"] for d, s in _all(agent.plans.get("friend")) if s["sport"] == "strength" and d > today.isoformat()}
    assert coach_st
    agent.coach.update_athlete("friend", {"strength_opt_in": False})
    plan = agent.plans.apply_rhythm("friend")
    assert coach_st <= {s["id"] for _, s in _all(plan)}


def test_moved_garmin_session_is_orphaned_like_a_hand_move(env) -> None:
    agent, today = _setup(env)
    plan = agent.plans.get("friend")
    race_start = _race_week_start(plan)
    runs = [(d, s) for d, s in _all(plan) if s["sport"] == "run" and today.isoformat() < d < race_start
            and _wd(d) not in ("mon", "wed", "fri") and s.get("kind") != "long"
            and (date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())) > today]
    d0, s0 = runs[0]

    def sync(p):
        for w in p["weeks"]:
            for ss in w["days"].values():
                for s in ss:
                    if s["id"] == s0["id"]:
                        s["garmin"] = {"workout_ids": [987], "hash": "x"}
    _doc(agent).update(sync)
    agent.coach.update_athlete("friend", {"week_rhythm": RUN_BIKE})
    agent.plans.apply_rhythm("friend")
    raw = _doc(agent).load()
    moved = next(s for w in raw["weeks"] for d, ss in w["days"].items() for s in ss if s["id"] == s0["id"])
    where = next(d for w in raw["weeks"] for d, ss in w["days"].items() for s in ss if s["id"] == s0["id"])
    assert where != d0 and _wd(where) in ("mon", "wed", "fri")
    assert 987 in raw["garmin_orphans"] and "garmin" not in moved  # removed on the next sync, re-uploaded on its new day


def test_chat_fits_instead_of_rebuilding(env) -> None:
    agent, today = _setup(env)
    ids = {s["id"] for _, s in _all(agent.plans.get("friend")) if s["sport"] != "strength"}
    out = agent._dispatch("friend", "update_athlete_profile", {"week_rhythm": RUN_BIKE})
    assert out["plan_rebuilt"] is True and "sessions_moved" in out
    assert {s["id"] for _, s in _all(agent.plans.get("friend")) if s["sport"] != "strength"} == ids


def test_api_fits_by_default_and_refuses_rebuild_for_coach_plans(env, tmp_path) -> None:
    agent, today = _setup(env)
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    h = {"origin": BASE}
    ids = {s["id"] for _, s in _all(agent.plans.get("friend")) if s["sport"] != "strength"}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"week_rhythm": RUN_BIKE})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["rebuilt"] is False and isinstance(body["moved"], int) and body["plan"]
            got = {s["id"] for w in body["plan"]["weeks"] for d in w["days"] for s in d["sessions"]
                   if s["sport"] not in ("rest", "strength")}
            assert got == ids
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"rebuild": True})
            assert r.status_code == 200 and r.json()["rebuilt"] is True
            _doc(agent).update(lambda d: d.__setitem__("origin", {"kind": "coach", "by_name": "Coach"}))
            r = await c.put("/app/api/plan/rhythm", headers=h, json={"week_rhythm": RUN_BIKE, "rebuild": True})
            assert r.status_code == 400 and "coach" in r.json()["error"]
    asyncio.run(go_())
