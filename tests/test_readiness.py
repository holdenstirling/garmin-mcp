"""Race readiness: deterministic grade per race, plus the athlete and coach APIs."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2

from garmin_mcp.planbuilder import build_plan
from garmin_mcp.readiness import LONG, ReadinessService, compute, grade_for, race_key, target_fitness
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, COACH, _apps
from tests.test_stats import act

TODAY = date(2026, 10, 14)


def trained(daily: int = 60, long: int = 170, long_km: float = 32, days: int = 150) -> list[dict]:
    out = []
    for i in range(1, days):
        d = TODAY - timedelta(days=i)
        if d.weekday() == 6:
            out.append(act(d, minutes=long, km=long_km, aid=i))
        elif d.weekday() != 0:
            out.append(act(d, minutes=daily, km=11, aid=i))
    return out


def race(weeks: int, **kw) -> dict:
    return {"id": "e1", "name": "City Marathon", "type": "running", "distance": "marathon", "priority": "A",
            "date": (TODAY + timedelta(weeks=weeks)).isoformat()} | kw


def test_grade_bands() -> None:
    assert [grade_for(s) for s in (100, 90, 89, 85, 80, 75, 70, 65, 58, 50, 49, 0)] == \
        ["A", "A", "A-", "A-", "B+", "B", "B-", "C+", "C", "D", "F", "F"]


def test_well_trained_marathoner_is_ahead_with_full_output() -> None:
    out = compute(race(10), {}, today=TODAY, acts=trained())
    assert out["grade"] == "A" and out["status"] == "ahead" and out["confidence"] == "high"
    assert [c["id"] for c in out["components"]] == ["fitness", "key_session", "consistency", "race_factors", "health"]
    assert sum(c["weight"] for c in out["components"]) == 100
    assert all(c["detail"] and c["tip"] and 0 <= c["score"] <= 100 for c in out["components"])
    assert len(out["headline"]) <= 70 and len(out["summary"]) <= 200
    assert out["weeks_to_race"] == 10 and out["target_fitness"] == 55 and not out["forecast"]


def test_no_plan_path_vs_plan_forecast() -> None:
    light = trained(daily=30, long=60, long_km=10)
    out = compute(race(10), {}, today=TODAY, acts=light)
    assert out["status"] in ("behind", "on_track") and out["score"] < 85 and not out["forecast"]
    assert any("long run" in a for a in out["actions"]) and len(out["actions"]) <= 3
    plan = build_plan({"weekly_hours": 7, "level": "intermediate"},
                      {"title": "M", "date": race(10)["date"], "distance": "marathon"}, today=TODAY)
    out = compute(race(10), {}, today=TODAY, acts=trained(), plan=plan)
    assert out["forecast"] and "plan projects" in out["components"][0]["detail"]


def test_pain_flag_is_at_risk_and_top_action() -> None:
    cis = [{"date": (TODAY - timedelta(days=2)).isoformat(), "pain_flag": True, "feel": 2,
            "soreness": [{"area": "achilles", "side": "left", "level": 3}]}]
    out = compute(race(10), {}, today=TODAY, acts=trained(), checkins=cis)
    assert out["status"] == "at_risk" and out["headline"].startswith("At risk")
    assert out["actions"][0] == "Get your left achilles checked before adding load"
    old = [dict(cis[0], date=(TODAY - timedelta(days=20)).isoformat())]
    assert compute(race(10), {}, today=TODAY, acts=trained(), checkins=old)["status"] != "at_risk"


def test_unreachable_target_is_at_risk() -> None:
    out = compute(race(4, name="Leadville Trail 100 Run", type="trail", distance="ultra"), {}, today=TODAY,
                  acts=trained(daily=20, long=40, long_km=6))
    assert out["status"] == "at_risk" and "safely" in out["headline"]


def test_far_race_low_confidence_graded_for_this_point() -> None:
    out = compute(race(45), {}, today=TODAY, acts=trained())
    assert out["confidence"] == "low" and out["summary"].startswith("Early days")
    assert "on track at this point" in out["components"][0]["detail"]
    assert next(c for c in out["components"] if c["id"] == "key_session")["weight"] == 10
    out = compute(race(10), {}, today=TODAY, acts=trained(days=10))
    assert out["confidence"] == "low"
    out = compute(race(10), {}, today=TODAY, acts=[])
    assert out["confidence"] == "low" and out["headline"].startswith("Early days")


def test_hundred_miler_vs_10k_targets() -> None:
    hundred = race(12, name="Leadville Trail 100 Run", type="trail", distance="ultra")
    tenk = race(12, name="Turkey Trot", distance="10k")
    assert race_key(hundred) == "ultra100" and race_key(tenk) == "10k"
    assert target_fitness(hundred, {}) == 75 and target_fitness(tenk, {}) == 35
    assert target_fitness(dict(tenk, priority="C"), {"level": "new"}) < 35
    assert LONG["ultra100"]["run"][0] >= 360 and LONG["10k"]["run"][0] <= 90
    acts = trained(daily=45, long=90, long_km=15)
    h, t = compute(hundred, {}, today=TODAY, acts=acts), compute(tenk, {}, today=TODAY, acts=acts)
    assert t["score"] > h["score"] and t["grade"] < h["grade"]  # "A" sorts before "C"
    assert "Back-to-back" in h["components"][1]["detail"]
    assert race_key({"name": "x", "type": "trail", "distance": "50 mi"}) == "ultra"
    assert race_key({"name": "Ride", "type": "cycling", "distance": "century ride"}) == "century ride"


def test_service_caches_and_skips_past(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("u").date()
    ev = agent.events.create("u", {"name": "Spring 50K", "type": "trail", "distance": "ultra",
                                   "date": (today + timedelta(weeks=8)).isoformat()})
    agent.events.create("u", {"name": "Old", "date": (today - timedelta(days=3)).isoformat()})
    svc = ReadinessService.from_agent(agent)
    a = svc.get("u", ev["id"])
    assert a["event_id"] == ev["id"] and svc.get("u", ev["id"]) is a
    races = svc.upcoming("u")
    assert [r["name"] for r in races] == ["Spring 50K"] and set(races[0]) >= {"grade", "status", "headline"}


def test_readiness_api_and_coach_access(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    ev = agent.events.create("friend", {"name": "Spring 50K", "type": "trail", "distance": "ultra",
                                        "date": (today + timedelta(weeks=8)).isoformat()})
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            r = await a.get(f"/app/api/events/{ev['id']}/readiness")
            assert r.status_code == 200 and r.json()["grade"] and len(r.json()["components"]) == 5
            assert (await a.get("/app/api/events/nope/readiness")).status_code == 400
            assert (await o.get(f"/app/api/events/{ev['id']}/readiness")).status_code == 400
            races = (await a.get("/app/api/readiness")).json()["races"]
            assert races[0]["event_id"] == ev["id"] and "components" not in races[0]
            # Coach account: athlete routes refused; coach route only once linked.
            assert (await c.get("/app/api/readiness")).status_code == 403
            assert (await c.get(f"/app/api/events/{ev['id']}/readiness")).status_code == 403
            assert (await c.get("/app/api/coach/athletes/friend/readiness")).status_code == 400
            await a.post("/app/api/coaches", headers=h, json={"email": COACH})
            r = await c.get("/app/api/coach/athletes/friend/readiness")
            assert r.status_code == 200 and r.json()["races"][0]["name"] == "Spring 50K"
            assert (await c.get("/app/api/coach/athletes/other/readiness")).status_code == 400
            assert (await o.get("/app/api/coach/athletes/friend/readiness")).status_code == 400
    asyncio.run(go_())
