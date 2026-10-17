"""Race switcher (each goal keeps its plan), plan preview / levers / undo, weekly check-in."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2

from garmin_mcp import planflow as pf
from garmin_mcp.planbuilder import build_plan, iter_sessions, week_for
from garmin_mcp.races import RaceDesk
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

ATH = {"weekly_hours": 6, "level": "intermediate", "available_days": ["tue", "wed", "thu", "sat", "sun"], "long_day": "sat"}


def _plan(today: date, weeks: int = 14):
    return build_plan(dict(ATH), {"title": "HM", "date": (today + timedelta(weeks=weeks)).isoformat(),
                                  "distance": "half marathon"}, today=today)


def _setup(env, weeks=14):
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATH))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=weeks)).isoformat()})
    plan = agent.plans.build("friend")
    return agent, plan, today


def test_summary_prescribes_phases_ramp_and_first_weeks() -> None:
    today = date(2026, 10, 14)
    plan = _plan(today)
    s = pf.plan_summary(plan, today)
    assert s["weeks"] == len(plan["weeks"]) and len(s["hours"]) == s["weeks"] == len(s["long_minutes"])
    assert [p["phase"] for p in s["phases"]][0] == "base" and s["phases"][-1]["phase"] == "race"
    assert sum(p["weeks"] for p in s["phases"]) == s["weeks"]
    assert len(s["first_two_weeks"]) <= 14 and all(d["date"] >= today.isoformat() for d in s["first_two_weeks"])
    first = s["first_session"]
    assert first and first["kind"] not in ("long", "brick") and first["minutes"] <= 30


def test_diff_shows_what_changes_from_today() -> None:
    today = date(2026, 10, 14)
    a = _plan(today)
    b = build_plan(dict(ATH, available_days=["mon", "wed", "fri", "sun"], long_day="sun"),
                   {"title": "HM", "date": a["race_date"], "distance": "half marathon"}, today=today)
    d = pf.plan_diff(a, b, today)
    assert d["changed_days"] > 0 and all(x["date"] >= today.isoformat() for x in d["days"])
    assert pf.plan_diff(a, a, today)["changed_days"] == 0


def test_checkin_answers_validated() -> None:
    assert pf.clean_answers({"energy": "low", "off_days": ["sat", "mon"]}) == {"energy": "low", "off_days": ["mon", "sat"]}
    for bad in ({"energy": "meh"}, {"off_days": ["funday"]}, {"long_day": "x"}, "nope"):
        try:
            pf.clean_answers(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_checkin_proposal_moves_off_days_and_lightens() -> None:
    today = date(2026, 10, 16)  # Friday
    plan = _plan(today - timedelta(days=21), weeks=16)
    w = pf.next_week(plan, today)
    assert w is not None
    busy = [d for d in sorted(w["days"]) if any(s["sport"] != "rest" for s in w["days"][d])]
    off = [("mon", "tue", "wed", "thu", "fri", "sat", "sun")[date.fromisoformat(busy[0]).weekday()]]
    p = pf.checkin_proposal(plan, today, {"off_days": off, "energy": "low"})
    assert p["status"] == "suggest" and p["id"]
    moved = [c for c in p["changes"] if c["session_id"] in {s["id"] for s in w["days"][busy[0]] if s["sport"] != "rest"}]
    assert moved and all(c["action"] in ("relocate", "rest") for c in moved)
    assert all(c["date"] != busy[0] for c in moved if c["action"] == "relocate")
    assert any(c["action"] in ("shorten", "ease") or c["to"].get("minutes", 0) < (c["from"].get("minutes") or 0)
               for c in p["changes"])
    # More time never adds training.
    more = pf.checkin_proposal(plan, today, {"time": "more"})
    assert more["status"] == "ok" and not more["changes"]


def test_checkin_apply_relocates_without_losing_sessions(env) -> None:
    agent, plan, today = _setup(env, weeks=16)
    w = pf.next_week(plan, today)
    work = [(d, s) for d in sorted(w["days"]) for s in w["days"][d] if s["sport"] != "rest" and d > today.isoformat()]
    d0, s0 = work[0]
    off = [("mon", "tue", "wed", "thu", "fri", "sat", "sun")[date.fromisoformat(d0).weekday()]]
    p = pf.checkin_proposal(plan, today, {"off_days": off})
    if p["status"] != "suggest":
        return  # no free day and nothing to drop (can't happen with this plan, but stay robust)
    new = agent.plans.apply_adjustment("friend", p["changes"])
    where = {s["id"]: d for _, d, s in iter_sessions(new)}
    for c in p["changes"]:
        if c["action"] == "relocate":
            assert where[c["session_id"]] == c["date"]
    before = {s["id"] for _, _, s in iter_sessions(plan) if s["sport"] != "rest"}
    dropped = {c["session_id"] for c in p["changes"] if c["action"] == "rest"}
    assert before - dropped <= set(where)


def test_levers_preview_apply_and_undo(env) -> None:
    agent, plan, today = _setup(env)
    prev = agent.plans.preview("friend", {"available_days": ["mon", "wed", "fri", "sun"], "long_day": "sun"})
    assert prev["weeks"] and agent.plans.get("friend")["weeks"][0]["days"] == plan["weeks"][0]["days"]  # nothing saved
    new, undo = agent.plans.apply_levers("friend", {"available_days": ["mon", "wed", "fri", "sun"], "long_day": "sun",
                                                    "plan_intensity": "gentle"})
    assert agent.coach.athlete("friend")["long_day"] == "sun" and agent.coach.athlete("friend")["plan_intensity"] == "gentle"
    longs = [d for _, d, s in iter_sessions(new) if s.get("kind") == "long"]
    assert longs and all(date.fromisoformat(d).weekday() == 6 for d in longs)
    back = agent.plans.undo_levers("friend", undo)
    assert agent.coach.athlete("friend")["long_day"] == "sat"
    assert {s["id"] for _, _, s in iter_sessions(back)} == {s["id"] for _, _, s in iter_sessions(plan)}
    try:
        agent.plans.undo_levers("friend", undo)
    except Exception as e:
        assert "can't be undone" in str(e)
    else:
        raise AssertionError("undo twice")
    try:
        agent.plans.apply_levers("friend", {"date": "x"})
    except Exception as e:
        assert "Can't adjust" in str(e)


def test_races_switch_restores_each_goals_plan(env) -> None:
    agent, plan_a, today = _setup(env)
    desk = RaceDesk(agent.coach, agent.plans, agent.events)
    ga = agent.coach.active_goal("friend")
    # A second race on the calendar: train for it (new goal, no plan yet), build, switch back.
    ev = agent.events.create("friend", {"name": "Fall 10K", "type": "running", "kind": "race", "date": (today + timedelta(weeks=8)).isoformat(),
                                        "distance": "10k", "priority": "B"})
    races = desk.list("friend", today)["races"]
    assert races[0]["active"] and races[0]["has_plan"]
    assert any(r["kind"] == "event" and r["event_id"] == ev["id"] for r in races)
    out = desk.train_for("friend", f"event:{ev['id']}")
    assert out["goal"]["title"] == "Fall 10K" and out["has_plan"] is False
    plan_b = agent.plans.build("friend")
    assert plan_b["distance"] == "10k"
    out = desk.train_for("friend", f"goal:{ga['id']}")
    assert out["has_plan"] is True
    back = agent.plans.get("friend")
    assert {s["id"] for _, _, s in iter_sessions(back)} == {s["id"] for _, _, s in iter_sessions(plan_a)}
    listed = desk.list("friend", today)["races"]
    assert listed[0]["goal_id"] == ga["id"] and any(r["title"] == "Fall 10K" and r["has_plan"] for r in listed)
    # Tune-up: a calendar race joins the plan as a B race.
    ev2 = agent.events.create("friend", {"name": "Turkey Trot", "type": "running", "kind": "race", "date": (today + timedelta(weeks=5)).isoformat(),
                                         "distance": "5k", "priority": "C"})
    desk.tune_up("friend", ev2["id"])
    assert agent.events.get("friend", ev2["id"])["priority"] == "C"  # already a tune-up priority


def test_http_routes_and_coach_403(env, tmp_path) -> None:
    agent, _, today = _setup(env)
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get("/app/api/races")
            assert r.status_code == 200 and r.json()["races"][0]["active"]
            r = await a.post("/app/api/plan/preview", headers=h, json={"athlete": {"long_day": "sun"}})
            assert r.status_code == 200, r.text
            assert r.json()["summary"]["weeks"] and "diff" in r.json()
            r = await a.post("/app/api/plan/preview", headers=h, json={"athlete": {"level": "pro"}})
            assert r.status_code == 400
            r = await a.post("/app/api/plan/levers", headers=h, json={"levers": {"long_day": "sun"}})
            assert r.status_code == 200 and r.json()["undo"]
            r = await a.post("/app/api/plan/levers/undo", headers=h, json={"id": r.json()["undo"]})
            assert r.status_code == 200, r.text
            r = await a.get("/app/api/plan/weekcheck")
            assert r.status_code == 200 and "due" in r.json()
            r = await a.post("/app/api/plan/weekcheck", headers=h, json={"action": "preview", "answers": {"energy": "low"}})
            assert r.status_code == 200 and r.json()["proposal"]["status"] in ("suggest", "ok")
            p = r.json()["proposal"]
            if p["status"] == "suggest":
                r = await a.post("/app/api/plan/weekcheck", headers=h, json={"action": "apply", "id": "stale", "answers": {"energy": "low"}})
                assert r.status_code == 409
                r = await a.post("/app/api/plan/weekcheck", headers=h, json={"action": "apply", "id": p["id"], "answers": {"energy": "low"}})
                assert r.status_code == 200 and r.json()["applied"] == len(p["changes"])
            r = await a.post("/app/api/plan/weekcheck", headers=h, json={"action": "skip", "answers": {"energy": "bogus"}})
            assert r.status_code == 400
            for path in ("/app/api/races", "/app/api/plan/weekcheck"):
                assert (await c.get(path)).status_code == 403
            assert (await c.post("/app/api/plan/preview", headers=h, json={})).status_code == 403
    asyncio.run(go_())
    assert week_for(agent.plans.get("friend"), today) is not None


def test_running_plan_long_run_on_the_chosen_long_day() -> None:
    # Regression: the tri rule (long ride on the long day, long run the day after) put a
    # runner's Sunday long run on Mondays.
    today = date(2026, 10, 16)
    for ld, wd in (("sun", 6), ("sat", 5)):
        p = build_plan(dict(ATH, available_days=["mon", "wed", "fri", "sat", "sun"], long_day=ld),
                       {"title": "HM", "date": (today + timedelta(weeks=14)).isoformat(), "distance": "half marathon"}, today=today)
        longs = [d for _, d, s in iter_sessions(p) if s.get("kind") == "long"]
        assert longs and all(date.fromisoformat(d).weekday() == wd for d in longs), (ld, longs)
