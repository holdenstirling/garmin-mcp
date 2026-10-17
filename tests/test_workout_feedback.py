"""Workout page feedback: tapped RPE / feel / pain on check-ins and Rabbit's deterministic
feedback (workoutday.coach_feedback), plus the /app/api/workout/feedback route."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2

from garmin_mcp.planbuilder import iter_sessions
from garmin_mcp.workoutday import coach_feedback
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plancal import ATHLETE
from tests.test_profile import BASE, _apps


def test_feedback_reads_the_plan_intent_and_the_athletes_own_numbers() -> None:
    easy, tempo = {"kind": "easy"}, {"kind": "tempo"}
    assert coach_feedback(easy, None, None) is None  # nothing to say before it's done
    hot = coach_feedback(easy, {"verdict": "fast"}, {"rpe": 7})
    assert hot["tone"] == "ease" and any("7/10" in x and "2-4/10" in x for x in hot["lines"])
    assert coach_feedback(easy, {"verdict": "hard"}, None)["headline"] == "Easy day ran hot"
    fit = coach_feedback(tempo, {"verdict": "hit"}, {"rpe": 4})
    assert fit["headline"].startswith("Felt easy") and any("faster paces" in x for x in fit["lines"])
    ok = coach_feedback(tempo, {"verdict": "hit"}, {"rpe": 6})
    assert ok["tone"] == "good" and any("right where" in x for x in ok["lines"])
    pain = coach_feedback(tempo, {"verdict": "hit"}, {"rpe": 6, "pain_flag": True})
    assert pain["tone"] == "care" and "pain" in pain["lines"][0]
    short = coach_feedback(easy, {"verdict": "short"}, None)
    assert short["headline"] == "Cut short"
    assert coach_feedback(easy, {"verdict": "hit"}, None)["lines"] == ["Right on target. That's exactly the work the plan asked for."]
    assert len(coach_feedback(easy, {"verdict": "short"}, {"rpe": 9, "feel": 1, "pain_flag": True})["lines"]) <= 4


def test_checkin_takes_tapped_rpe_and_pain_over_parsing(env) -> None:
    agent, _ = env.agent([])
    e, _src = asyncio.run(agent.checkin("friend", "", session_id="s_1", rpe=7, feel=4))
    assert e["rpe"] == 7 and e["feel"] == 4 and e["session_id"] == "s_1" and e["summary"].startswith("RPE 7/10")
    e, _src = asyncio.run(agent.checkin("friend", "legs 3 out of 10", rpe=8, pain=True))
    assert e["rpe"] == 8 and e["pain_flag"] is True  # the slider wins over the words
    e, _src = asyncio.run(agent.checkin("friend", "fine", rpe=42, pain="yes"))
    assert e["rpe"] is None and e["pain_flag"] is False  # out-of-range taps are ignored


def test_feedback_route(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    sid = next(s["id"] for _, _, s in iter_sessions(agent.plans.get("friend")) if s["sport"] != "rest")
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get(f"/app/api/workout/feedback?session_id={sid}")
            assert r.status_code == 200 and r.json() == {"checkin": None, "feedback": None}
            r = await a.post("/app/api/checkins", headers=h, json={"text": "", "session_id": sid, "rpe": 9, "feel": 2})
            assert r.status_code == 201, r.text
            fb = (await a.get(f"/app/api/workout/feedback?session_id={sid}")).json()
            assert fb["checkin"]["rpe"] == 9 and fb["feedback"]["lines"]
            assert (await a.get("/app/api/workout/feedback?session_id=nope0")).status_code == 404
            assert (await a.get("/app/api/workout/feedback?session_id=../x")).status_code == 400
            assert (await c.get(f"/app/api/workout/feedback?session_id={sid}")).status_code == 403
    asyncio.run(go_())
