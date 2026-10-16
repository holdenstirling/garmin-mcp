"""Connected apps (connections.py, GET /app/api/connections, POST .../{app}/sync): status rows,
data-use facts pinned to the privacy policy, Garmin attention from LiveSync, coach 403."""

from __future__ import annotations

import asyncio

import httpx2

from garmin_mcp import connections as conn
from garmin_mcp import legal
from garmin_mcp.oura import OuraClient
from garmin_mcp.providers import ReauthRequired
from garmin_mcp.sync import LiveSync
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps


def test_status_states() -> None:
    assert conn.status("oura", available=False, connected=False)["state"] == "unavailable"
    assert conn.status("oura", available=True, connected=False)["state"] == "not_connected"
    on = conn.status("garmin", available=True, connected=True, last_sync=0)
    assert on["state"] == "connected" and on["last_sync"] == "1970-01-01T00:00:00+00:00"
    bad = conn.status("calendar", available=True, connected=True, error="Refused", attention=True)
    assert bad["state"] == "attention" and bad["error"] == "Refused"
    # Not connected: no stale sync time or error leaks into the row.
    off = conn.status("oura", available=True, connected=False, last_sync=5, error="x")
    assert off["last_sync"] is None and off["error"] is None
    v = conn.view({a: conn.status(a, available=True, connected=False) for a in reversed(conn.ORDER)})
    assert [a["id"] for a in v["apps"]] == ["garmin", "oura", "calendar"]


def test_facts_match_the_privacy_policy() -> None:
    page = legal.privacy()
    # The popup's promises are ones the policy (and sources.py) make.
    assert "Oura data is never sent to the AI coach" in page
    assert "Oura workouts are not imported; workouts come from Garmin only" in page
    assert "Google Calendar</b> (when you connect it, read-only)" in page
    assert any("never goes to Rabbit's AI" in s for s in conn.APPS["oura"]["never"])
    assert any("never imported" in s for s in conn.APPS["oura"]["never"])
    assert any("read-only" in s for s in conn.APPS["calendar"]["reads"])
    assert all(conn.APPS[a]["reads"] and conn.APPS[a]["never"] for a in conn.ORDER)
    assert "trainingpeaks" not in conn.APPS  # MCP-server only; the app can't connect it


def test_live_sync_last_and_reauth_code(env) -> None:
    calls = {"err": None}

    def fetch(uid):
        if calls["err"]:
            raise calls["err"]
        return []
    s = LiveSync(env.store, fetch, connected=lambda u: True, on_new=lambda u: None, clock=lambda: 0.0)
    assert s.last("friend") is None
    calls["err"] = ReauthRequired("expired")
    s.check("friend")
    assert s.last("friend")["code"] == "reauth"


def test_oura_last_read_and_forget(env) -> None:
    o = OuraClient(env.store, "id", "secret", "https://x/cb", clock=lambda: 1000.0)
    assert o.last_read("friend") is None
    o._cache["friend"] = (900.0, {"window": 28})
    assert o.last_read("friend") == 900.0
    o.forget("friend")
    assert o.last_read("friend") is None


def test_api_shape_sync_guards_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get("/app/api/connections")
            assert r.status_code == 200
            body = r.json()
            assert [x["id"] for x in body["apps"]] == ["garmin", "oura", "calendar"]
            for row in body["apps"]:
                assert set(row) >= {"state", "connected", "available", "last_sync", "reads", "never", "import_label"}
            assert body["sources"]["workouts"] == "garmin"
            # No Oura/Calendar configured here: they read as unavailable, and Sync now refuses.
            assert {x["id"]: x["state"] for x in body["apps"]}["oura"] == "unavailable"
            assert (await a.post("/app/api/connections/oura/sync", headers=h, json={})).status_code == 409
            assert (await a.post("/app/api/connections/garmin/sync", headers=h, json={})).status_code == 400
            assert (await a.post("/app/api/connections/oura/sync", json={})).status_code == 403  # no origin
            assert (await c.get("/app/api/connections")).status_code == 403
            assert (await c.post("/app/api/connections/oura/sync", headers=h, json={})).status_code == 403
    asyncio.run(go_())
