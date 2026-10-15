"""Gamification: XP ledger, levels, quests, celebrations, and rest-protected streaks."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.progress import Progress, level_floor, level_of, level_view, quests_view, week_goal, workout_xp
from garmin_mcp.stats import compute
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_stats import TODAY, act

BASE = "http://localhost:8001"


def test_levels() -> None:
    assert level_of(0) == 1 and level_of(99) == 1 and level_of(100) == 2 and level_of(level_floor(10)) == 10
    v = level_view(level_floor(5) + 10)
    assert v["level"] == 5 and v["name"] == "Hopper" and v["level_xp"] == 10 and v["to_next"] == v["level_span"] - 10
    assert workout_xp(60) == 40 and workout_xp(600) == 100 and workout_xp(-5) == 10


def test_xp_ledger_never_double_counts(env) -> None:
    p = Progress(env.store, clock=lambda: 0.0)
    acts = [act(TODAY - timedelta(days=i)) for i in range(1, 4)]
    stats = compute(acts, TODAY)
    first = p.update("u", acts=acts, today=TODAY, stats=stats, plan_key=None, quests={"garmin": True})
    # Backfill: 3 workouts (3 x 32) + badges earned + the Garmin quest, but no celebration for history.
    badges = sum(b["earned"] for b in stats["badges"])
    assert first["xp"] == 3 * workout_xp(45) + 100 * badges + 100
    assert first["new_badges"] == [] and not first["level_up"]
    again = p.update("u", acts=acts, today=TODAY, stats=stats, plan_key=None, quests={"garmin": True})
    assert again["xp"] == first["xp"] and again["gained"] == 0
    # A new workout today earns XP once, and the newly earned badge is celebrated until seen.
    acts2 = acts + [act(TODAY, minutes=200, aid=77)]
    stats2 = compute(acts2, TODAY)
    new = p.update("u", acts=acts2, today=TODAY, stats=stats2, plan_key=None, quests={"garmin": True})
    assert new["gained"] >= workout_xp(200)
    assert "long3h" in {b["id"] for b in new["new_badges"]}
    p.seen("u")
    assert p.update("u", acts=acts2, today=TODAY, stats=stats2, plan_key=None, quests={})["new_badges"] == []


def test_plan_xp_per_goal(env) -> None:
    p = Progress(env.store, clock=lambda: 0.0)
    stats = compute([], TODAY) | {"plan": {"to_date": {"done": 4}, "perfect_weeks": 1}}
    a = p.update("u", acts=[], today=TODAY, stats=stats, plan_key="g1", quests={})
    assert a["gained"] == 4 * 15 + 100
    assert p.update("u", acts=[], today=TODAY, stats=stats, plan_key="g1", quests={})["gained"] == 0


def test_quests_and_week_goal() -> None:
    qs = quests_view({"garmin": True}, {"oura": False, "calendar": True, "notify": True})
    ids = [q["id"] for q in qs]
    assert "oura" not in ids and "calendar" in ids and qs[0]["done"]
    # every quest carries a short label for the header pill (one or two words)
    assert all(q["short"] and len(q["short"]) <= 12 for q in qs)
    assert next(q for q in qs if q["id"] == "sync")["short"] == "Watch sync"
    s = compute([act(TODAY - timedelta(days=1))], TODAY)
    assert week_goal(s) == {"kind": "active", "done": 1, "target": 3, "label": "workouts"}


def test_rest_days_protect_the_streak() -> None:
    # Trained Mon-Wed of last week, rested Thu (free rest day), trained Fri-Tue.
    mon = TODAY - timedelta(days=TODAY.weekday() + 7)
    days = [mon + timedelta(days=i) for i in (0, 1, 2, 4, 5, 6, 7, 8)]
    s = compute([act(d) for d in days], TODAY)
    assert s["streak"]["current"] == 8 and not s["streak"]["at_risk"]
    # Two unplanned misses in one week break it.
    days2 = [mon + timedelta(days=i) for i in (0, 1, 4, 5, 6, 7, 8)]
    assert compute([act(d) for d in days2], TODAY)["streak"]["current"] == 5
    # A plan rest day doesn't use the free day.
    plan = {"weeks": [{"start": mon.isoformat(), "days": {(mon + timedelta(days=i)).isoformat(): [{"sport": "run", "title": "Run", "minutes": 30, "id": f"s{i}"}]
                                                          for i in (0, 1, 4, 5, 6)}}]}
    assert compute([act(d) for d in days2], TODAY, plan=plan)["streak"]["current"] == 7


def test_progress_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/progress")
            assert r.status_code == 200, r.text
            body = r.json()
            assert {"level", "xp", "quests", "setup", "week", "streak", "new_badges"} <= set(body)
            assert body["setup"]["total"] == 5  # push not configured here
            assert (await c.post("/app/api/progress/seen", headers={"origin": BASE}, json={})).status_code == 200
    asyncio.run(go_())


def test_today_is_wednesday() -> None:
    assert TODAY.weekday() == 2 and isinstance(TODAY, date)


def test_privacy_and_terms_pages(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"}, contact_email="me@example.com")
    auth = WebAuth(settings, env.store, "")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            p = await c.get("/app/privacy")
            t = await c.get("/app/terms")
            assert p.status_code == t.status_code == 200
            assert "never sent to the AI coach" in p.text and "me@example.com" in p.text
            assert "Not medical advice" in t.text
    asyncio.run(go_())
