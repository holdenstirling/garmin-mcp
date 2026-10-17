"""A race's plan FILE (coach/app plan read weekly by weekplan.py) -> a real Rabbit plan via the
import preview: POST /app/api/plan/import/from-goal (planimport_web.from_goal)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2

from garmin_mcp.coaches import coach_user_id
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_planimport import BASE, COACH, H, _apps
from tests.test_plans import _athlete


def _goal_with_file(agent, today, *, with_file: bool = True):
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Leadville Trail 100 Run", "distance": "100 mile",
                                       "date": (today + timedelta(weeks=40)).isoformat()})
    files = [agent.attachments.save("friend", "leadville.pdf", b"%PDF-1.4 plan weeks 1-46")] if with_file else []
    monday = today - timedelta(days=today.weekday())
    agent.coach.set_plan("friend", "46 weeks, base first. Long trail run on Saturdays.", files,
                         start_date=monday.isoformat(), weeks=46)
    return monday


def test_from_goal_reads_the_plan_file_and_previews_a_real_plan(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    monday = _goal_with_file(agent, today)
    seen: dict = {}

    async def structured(system, prompt, tool, **kw):
        seen["prompt"] = prompt
        return {"name": "Leadville", "sessions": [
            {"week": 2, "weekday": "tue", "sport": "run", "title": "Easy run", "minutes": 45, "intensity": "easy",
             "notes": "Easy Zone 2, conversational pace."},
            {"week": 2, "weekday": "sat", "sport": "run", "title": "Long trail run", "minutes": 120}]}
    agent._backend.structured = structured  # type: ignore[attr-defined]
    athlete_app, coach_app = _apps(env, tmp_path, agent)

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.post("/app/api/plan/import/from-goal", headers=H, json={})
            assert r.status_code == 201, r.text
            pv = r.json()["preview"]
            assert pv["totals"]["sessions"] == 2
            # Week 2 of the file plan is next week: weeks anchor at the plan's own start.
            assert pv["first_day"] == (monday + timedelta(days=8)).isoformat()
            blocks = seen["prompt"]
            assert blocks[0]["type"] == "document" and "oura" not in str(blocks).lower()
            r = await a.post(f"/app/api/plan/import/{pv['id']}/apply", headers=H, json={})
            assert r.status_code == 200, r.text
            plan = r.json()["plan"]
            s = next(s for w in plan["weeks"] for d in w["days"] for s in d["sessions"] if s["title"] == "Easy run")
            assert (await a.get(f"/app/api/workout/today?session_id={s['id']}")).status_code == 200
            assert agent.coach.active_goal("friend").get("plan_source") == "builder"
            # Coaches can't use the athlete route.
            r = await c.post("/app/api/plan/import/from-goal", headers=H, json={})
            assert r.status_code == 403
    env.store.user_doc(coach_user_id(COACH), "account").save({"name": "Bill"})
    asyncio.run(go())


def test_from_goal_summary_only_no_race_and_model_down(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    calls: list = []
    down = {"on": False}

    async def structured(system, prompt, tool, **kw):
        if down["on"]:
            raise RuntimeError("model down")
        calls.append(prompt)
        return {"sessions": [{"week": 1, "weekday": "sun", "sport": "run", "title": "Long run", "minutes": 60}]}
    agent._backend.structured = structured  # type: ignore[attr-defined]
    athlete_app, _ = _apps(env, tmp_path, agent)

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a:
            r = await a.post("/app/api/plan/import/from-goal", headers=H, json={})
            assert r.status_code == 404 and "race" in r.json()["error"]
            _goal_with_file(agent, today, with_file=False)
            r = await a.post("/app/api/plan/import/from-goal", headers=H, json={})
            assert r.status_code == 201, r.text  # the summary text alone is enough
            assert "Long trail run on Saturdays" in str(calls[-1])
            down["on"] = True
            r = await a.post("/app/api/plan/import/from-goal", headers=H, json={})
            assert r.status_code == 502 and "couldn't read" in r.json()["error"]
    asyncio.run(go())
