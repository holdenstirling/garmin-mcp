"""Read-only share links."""

from __future__ import annotations

import asyncio

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _setup

BASE = "http://localhost:8001"


def test_share_link_lifecycle(env, tmp_path) -> None:
    agent, plan, today = _setup(env)
    agent.events.create("friend", {"name": "Tune-up <10K>", "date": plan["race_date"]})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            assert (await c.get("/app/api/share")).json() == {"url": None}
            url = (await c.post("/app/api/share", headers=h, json={})).json()["url"]
            path = url.replace(BASE, "")
            r = await c.get(path)
            assert r.status_code == 200 and "training plan" in r.text
            assert "&lt;10K&gt;" in r.text and "<10K>" not in r.text  # escaped
            assert r.headers["x-robots-tag"].startswith("noindex")
            # A new link kills the old one; turning sharing off kills it too.
            url2 = (await c.post("/app/api/share", headers=h, json={})).json()["url"]
            assert (await c.get(path)).status_code == 404
            await c.request("DELETE", "/app/api/share", headers=h, json={})
            assert (await c.get(url2.replace(BASE, ""))).status_code == 404
            assert (await c.get("/app/s/short")).status_code == 404
    asyncio.run(go_())
