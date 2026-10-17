"""Sick mode (sick.py): rest or short easy days, undo, the easy return, streaks, nudges, travel, AI."""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from garmin_mcp import sick as S
from garmin_mcp.adjust import propose
from garmin_mcp.planbuilder import PlanError, iter_sessions, week_for
from garmin_mcp.stats import plan_rest_days
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _setup

INTENSE = {"tempo", "threshold", "vo2", "racepace", "css", "brick"}


def _day(plan, d: date):
    w = week_for(plan, d)
    return (w or {"days": {}})["days"].get(d.isoformat(), [])


def _noop(p, s):
    return None


def _work_days(plan, today: date, n: int):
    return [today + timedelta(days=i) for i in range(n)
            if any(x["sport"] != "rest" for x in _day(plan, today + timedelta(days=i)))]


def test_body_severity_rests_everything_then_undo_restores(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    before = {d: [x["title"] for x in ss] for w in plan["weeks"] for d, ss in w["days"].items()}
    end = today + timedelta(days=3)
    p = agent.plans.sick_start("friend", {"severity": "body", "until": end.isoformat()})
    for i in range(4):
        ss = _day(p, today + timedelta(days=i))
        if any(x.get("kind") == "race" for x in ss):
            continue
        assert all(x["sport"] == "rest" for x in ss)
    v = agent.plans.sick_view("friend")
    assert v["active"] and v["severity"] == "body" and v["day"] == 1 and v["through"] == end.isoformat()
    assert "doctor" in v["safety"]
    p = agent.plans.sick_undo("friend")
    after = {d: [x["title"] for x in ss] for w in p["weeks"] for d, ss in w["days"].items()}
    for i in range(4):
        d = (today + timedelta(days=i)).isoformat()
        assert after[d] == before[d]
    assert "sick" not in p
    with pytest.raises(PlanError):
        agent.plans.sick_undo("friend")


def test_head_cold_keeps_one_short_easy_session_or_rest_anyway(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    p = agent.plans.sick_start("friend", {"severity": "head"})  # open-ended: today + 2 days
    for i in range(S.DEFAULT_COVER):
        ss = [x for x in _day(p, today + timedelta(days=i)) if x["sport"] != "rest"]
        assert len(ss) <= 1
        for x in ss:
            assert x.get("sick") and (x.get("minutes") or 0) <= S.HEAD_CAP and x.get("kind") not in INTENSE
    assert p["sick"]["until"] == "better"
    p = agent.plans.sick_start("friend", {"severity": "head", "rest_all": True})
    for i in range(S.DEFAULT_COVER):
        assert all(x["sport"] == "rest" for x in _day(p, today + timedelta(days=i))
                   if x.get("kind") != "race")


def test_preview_changes_nothing(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    snap = copy.deepcopy(agent.plans.get("friend")["weeks"])
    pv = agent.plans.sick_preview("friend", {"severity": "body", "until": (today + timedelta(days=4)).isoformat()})
    assert pv["sessions"] >= 1 and pv["through"] == (today + timedelta(days=4)).isoformat()
    assert agent.plans.get("friend")["weeks"] == snap
    with pytest.raises(PlanError):
        agent.plans.sick_preview("friend", {"severity": "flu"})


def test_better_builds_an_easy_ramp_proportional_to_days_sick(env) -> None:
    _, plan, today = _setup(env, weeks=20)
    plan = copy.deepcopy(plan)
    S.start(plan, {"severity": "body", "start": today.isoformat()}, today, _noop)
    for n_days, ramp in ((1, 2), (4, 4), (12, 7)):
        p = copy.deepcopy(plan)
        later = today + timedelta(days=n_days)
        S.extend(p, today, n_days + 2, _noop)
        ret = S.better(p, later, _noop)
        assert ret["days"] == ramp
        for i in range(ramp):
            for x in _day(p, later + timedelta(days=i)):
                if x["sport"] == "rest" or x.get("kind") == "race":
                    continue
                assert x.get("sick_return") == ret["id"]
                assert x.get("kind") not in INTENSE and (x.get("minutes") or 0) <= 60
        assert "sick" not in p and p["sick_history"][-1]["severity"] == "body"
        # After the ramp the plan resumes as written: nothing tagged sick, nothing crammed in.
        nxt = later + timedelta(days=ramp)
        assert not any(x.get("sick") or x.get("sick_return") for x in _day(p, nxt))
        assert len([x for x in _day(p, nxt) if x["sport"] != "rest"]) == len(
            [x for x in _day(plan, nxt) if x["sport"] != "rest" and not x.get("sick")]) or \
            nxt.isoformat() in plan["sick"]["original"]


def test_tick_extends_open_ended_and_returns_after_expected_end(env) -> None:
    _, plan, today = _setup(env, weeks=20)
    p = copy.deepcopy(plan)
    S.start(p, {"severity": "body"}, today, _noop)
    end0 = p["sick"]["cover_end"]
    assert S.tick(p, today + timedelta(days=2), _noop) == "extended"
    assert p["sick"]["cover_end"] > end0
    q = copy.deepcopy(plan)
    S.start(q, {"severity": "head", "until": (today + timedelta(days=1)).isoformat()}, today, _noop)
    assert S.tick(q, today + timedelta(days=2), _noop) == "returned"
    assert "sick" not in q and q["sick_return"]["start"] == (today + timedelta(days=2)).isoformat()


def test_race_near_gets_a_note(env) -> None:
    agent, plan, today = _setup(env, weeks=1)
    p = agent.plans.sick_start("friend", {"severity": "body"})
    assert p["sick"]["race_note"] and "race" in p["sick"]["race_note"].lower()
    race_days = [d for _, d, x in iter_sessions(p) if x.get("kind") == "race"]
    assert all(x.get("kind") == "race" for d in race_days for x in _day(p, date.fromisoformat(d))
               if x["sport"] != "rest")


def test_sick_days_keep_the_streak_and_pause_adjust(env) -> None:
    _, plan, today = _setup(env, weeks=20)
    p = copy.deepcopy(plan)
    S.start(p, {"severity": "head", "start": (today - timedelta(days=2)).isoformat()}, today, _noop)
    rest = plan_rest_days(p, today)
    assert {today - timedelta(days=2), today - timedelta(days=1), today} <= rest
    assert propose(p, [], today)["status"] == "ok"
    S.better(p, today + timedelta(days=1), _noop)
    assert today in plan_rest_days(p, today + timedelta(days=1))
    assert propose(p, [], today + timedelta(days=1))["status"] == "ok"  # easing back


def test_nudges_suppressed_and_one_checkin(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    m = agent.moments
    m.sick_active = lambda uid: True
    assert m.post("friend", {"type": "streak_risk", "key": "risk:x", "text": "x"}) == "skipped"
    assert m.post("friend", {"type": "week_nudge", "key": "wk:x", "text": "x"}) == "skipped"
    sick = {"id": "s1", "start": (today - timedelta(days=2)).isoformat()}
    cm = S.checkin_moment(sick, today)
    assert cm and cm["key"] == "sick:s1" and cm["actions"][0]["id"] == "sick"
    assert S.checkin_moment({"id": "s1", "start": today.isoformat()}, today) is None


def test_travel_and_sick_overlap(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    before = {d: [x["title"] for x in ss] for w in plan["weeks"] for d, ss in w["days"].items()}
    trip_end = today + timedelta(days=5)
    p = agent.plans.add_travel("friend", {"start": today.isoformat(), "end": trip_end.isoformat(), "treadmill": True})
    tid = p["trips"][0]["id"]
    p = agent.plans.sick_start("friend", {"severity": "body", "until": (today + timedelta(days=2)).isoformat()})
    for i in range(3):
        assert all(x["sport"] == "rest" for x in _day(p, today + timedelta(days=i)) if x.get("kind") != "race")
    # Undo travel while sick: sick days stay rest.
    p = agent.plans.remove_travel("friend", tid)
    for i in range(3):
        assert all(x["sport"] == "rest" for x in _day(p, today + timedelta(days=i)) if x.get("kind") != "race")
    # Undo sick: the pre-trip plan comes back.
    p = agent.plans.sick_undo("friend")
    for i in range(3):
        d = (today + timedelta(days=i)).isoformat()
        assert [x["title"] for x in _day(p, today + timedelta(days=i))] == before[d]


def test_ai_context_and_public_plan(env) -> None:
    from garmin_mcp.plans import public_plan
    agent, plan, today = _setup(env, weeks=20)
    agent.plans.sick_start("friend", {"severity": "head"})
    lines = agent._sick_lines("friend", agent._now("friend"))
    assert lines and "Sick mode is ON" in lines[0] and "head cold" in lines[0]
    pub = public_plan(agent.plans.get("friend"), today)
    assert pub["sick"]["active"] and "original" not in pub["sick"]
    assert any(s.get("sick") for w in pub["weeks"] for d in w["days"] for s in d["sessions"])
    agent.plans.sick_better("friend")
    lines = agent._sick_lines("friend", agent._now("friend"))
    assert lines and "Easing back" in lines[0]


def test_validation(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    with pytest.raises(PlanError):
        agent.plans.sick_start("friend", {"severity": "meh"})
    with pytest.raises(PlanError):
        agent.plans.sick_start("friend", {"severity": "body", "start": (today - timedelta(days=30)).isoformat()})
    with pytest.raises(PlanError):
        agent.plans.sick_start("friend", {"severity": "body", "until": (today - timedelta(days=1)).isoformat()})
    with pytest.raises(PlanError):
        agent.plans.sick_better("friend")
