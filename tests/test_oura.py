"""Oura: daily merge, baselines, and the connect gate."""

from __future__ import annotations

from garmin_mcp.oura import baseline, merge_days
from tests.test_agent import env  # noqa: F401  (fixture)


def test_merge_days_and_baseline() -> None:
    readiness = [{"day": "2026-10-10", "score": 80, "temperature_deviation": -0.1},
                 {"day": "2026-10-11", "score": 62}]
    daily_sleep = [{"day": "2026-10-10", "score": 77}, {"day": "2026-10-11", "score": 70}]
    sleeps = [{"day": "2026-10-10", "type": "long_sleep", "average_hrv": 61.4, "lowest_heart_rate": 46,
               "total_sleep_duration": 27000},
              {"day": "2026-10-10", "type": "late_nap", "average_hrv": 20},
              {"day": "2026-10-11", "type": "long_sleep", "average_hrv": 48, "lowest_heart_rate": 52,
               "total_sleep_duration": 21600}]
    activity = [{"day": "2026-10-11", "score": 90, "steps": 12000}]
    rows = merge_days(readiness, daily_sleep, sleeps, activity)
    assert rows[0] == {"date": "2026-10-10", "readiness": 80, "temp_deviation": -0.1, "sleep_score": 77,
                       "hrv": 61, "resting_hr": 46, "sleep_hours": 7.5}
    assert rows[1]["steps"] == 12000 and rows[1]["hrv"] == 48
    assert baseline(rows, "hrv") is None  # too few days
    many = [{"date": f"d{i}", "hrv": 50 + i} for i in range(10)]
    assert baseline(many, "hrv") == 54.5


def test_oura_api_not_configured(env, tmp_path) -> None:
    import asyncio

    import httpx2
    from starlette.applications import Starlette

    from garmin_mcp.config import Settings
    from garmin_mcp.webapp import build_app_routes
    from garmin_mcp.webauth import WebAuth
    from garmin_mcp.webchat import ChatRunner
    agent, _ = env.agent([])
    settings = Settings(public_base_url="http://localhost:8001", data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8001") as c:
            assert (await c.get("/app/api/oura")).json() == {"connected": False, "available": False}
            me = (await c.get("/app/api/me")).json()
            assert me["oura"] == {"available": False, "connected": False}
    asyncio.run(go_())

