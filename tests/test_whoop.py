"""WHOOP (whoop.py): OAuth state check, single-use refresh token rotation, workout import
mapping and dedupe against Garmin, display-only (never in AI inputs), feed card without
strain or heart rate, disconnect deletes everything, and "Coming soon" until configured."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx2
from starlette.applications import Starlette

from garmin_mcp import workouts as wo
from garmin_mcp.appstore import AppStore
from garmin_mcp.config import Settings
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from garmin_mcp.whoop import SCOPES, WhoopClient, WhoopNotConnected
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_friends_share import fx  # noqa: F401  (fixture)
from tests.test_profile import BASE

G_RUN = {"activity_id": 11, "date": "2026-10-13 07:00:00", "name": "Denver Running", "sport": "running",
         "duration": "0:45:00", "distance_km": 8.0, "avg_hr": 150}
W_RUN = {"id": "6a4f-run", "start": "2026-10-13T13:03:00.000Z", "end": "2026-10-13T13:47:00.000Z",
         "timezone_offset": "-06:00", "sport_name": "running", "score_state": "SCORED",
         "score": {"strain": 11.2, "average_heart_rate": 151, "max_heart_rate": 176, "kilojoule": 2100,
                   "distance_meter": 7950}}
W_PADEL = {"id": "6a4f-padel", "start": "2026-10-13T23:00:00Z", "end": "2026-10-14T00:10:00Z",
           "timezone_offset": "-06:00", "sport_name": "padel", "score_state": "PENDING_SCORE"}


def test_from_whoop_maps_local_time_sport_and_hides_health_numbers() -> None:
    r = wo.from_whoop(W_RUN)
    assert r == {"key": "whoop:6a4f-run", "source": "whoop", "id": "6a4f-run", "sport": "run", "name": "Run",
                 "start": "2026-10-13T07:03:00", "minutes": 44, "km": 7.95, "avg_hr": None, "calories": None}
    p = wo.from_whoop(W_PADEL)
    assert p["sport"] == "other" and p["name"] == "Padel" and p["start"] == "2026-10-13T17:00:00" and p["km"] is None
    assert wo.from_whoop({"sport_name": "running"}) is None  # no id / time: can't place it
    assert [wo.whoop_sport(s) for s in ("cycling", "spin", "swimming", "hiking/rucking", "weightlifting",
                                        "functional-fitness", "walking", "track & field", "yoga")] == \
        ["bike", "bike", "swim", "hike", "strength", "strength", "walk", "run", "other"]


def test_garmin_wins_when_both_saw_the_same_run(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    ext = wo.ExternalWorkouts(store, clock=lambda: 1000.0)
    items = [wo.from_whoop(W_RUN), wo.from_whoop(W_PADEL)]
    assert sorted(ext.save("ann", "whoop", items, date(2026, 10, 14))) == ["whoop:6a4f-padel", "whoop:6a4f-run"]
    assert [w["key"] for w in ext.visible("ann", [G_RUN])] == ["whoop:6a4f-padel"]


def test_authorize_url_asks_for_workouts_and_offline(tmp_path, fernet_key) -> None:
    w = WhoopClient(AppStore(tmp_path / "app", fernet_key), "cid", "sec", "https://x/app/auth/whoop/callback")
    url = w.authorize_url("s" * 40)
    assert url.startswith("https://api.prod.whoop.com/oauth/oauth2/auth?")
    assert "scope=read%3Aworkout+offline" in url and "state=" + "s" * 40 in url and SCOPES == "read:workout offline"


def test_concurrent_refresh_spends_the_rotating_token_once(env) -> None:
    calls: list[str] = []

    async def handler(req: httpx2.Request) -> httpx2.Response:
        body = req.content.decode()
        if "grant_type=refresh_token" in body:
            calls.append(body)
            await asyncio.sleep(0.01)
            if "refresh_token=r1" in body:
                return httpx2.Response(200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600})
            return httpx2.Response(400, json={"error": "invalid_grant"})
        return httpx2.Response(200, json={"records": []})

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            w = WhoopClient(env.store, "cid", "secret", "https://x/cb", http=http, clock=lambda: 1000.0)
            w._doc("u").save({"access_token": "a1", "refresh_token": "r1", "expires": 0})
            assert await asyncio.gather(w.access_token("u"), w.access_token("u")) == ["a2", "a2"]
            assert len(calls) == 1 and "scope=offline" in calls[0]
            assert w._doc("u").load()["refresh_token"] == "r2"  # the rotated token is kept
    asyncio.run(go_())


def test_revoked_refresh_disconnects(env) -> None:
    async def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": "invalid_grant"})

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            w = WhoopClient(env.store, "cid", "secret", "https://x/cb", http=http, clock=lambda: 1000.0)
            w._doc("u").save({"access_token": "a1", "refresh_token": "r1", "expires": 0})
            try:
                await w.access_token("u")
                raise AssertionError("expected WhoopNotConnected")
            except WhoopNotConnected:
                pass
            assert not w.connected("u")
    asyncio.run(go_())


def test_workouts_pages_and_keeps_the_window(env) -> None:
    seen: list[dict[str, str]] = []

    async def handler(req: httpx2.Request) -> httpx2.Response:
        q = dict(req.url.params)
        seen.append(q)
        assert req.headers["authorization"] == "Bearer a1"
        if "nextToken" not in q:
            return httpx2.Response(200, json={"records": [W_RUN], "next_token": "p2"})
        old = {**W_RUN, "id": "old", "start": "2026-09-01T13:00:00Z", "end": "2026-09-01T14:00:00Z"}
        return httpx2.Response(200, json={"records": [W_PADEL, old, "junk"], "next_token": None})

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            w = WhoopClient(env.store, "cid", "secret", "https://x/cb", http=http, clock=lambda: 1000.0)
            w._doc("u").save({"access_token": "a1", "refresh_token": "r1", "expires": 99999})
            rows = await w.workouts("u", date(2026, 10, 1), date(2026, 10, 14))
            assert [r["key"] for r in rows] == ["whoop:6a4f-run", "whoop:6a4f-padel"]
            assert seen[0]["limit"] == "25" and seen[1]["nextToken"] == "p2"
            assert w.last_read("u") == 1000.0
    asyncio.run(go_())


def test_disconnect_revokes_and_deletes_tokens_and_workouts(env) -> None:
    hits: list[str] = []

    async def handler(req: httpx2.Request) -> httpx2.Response:
        hits.append(f"{req.method} {req.url.path}")
        return httpx2.Response(204)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            w = WhoopClient(env.store, "cid", "secret", "https://x/cb", http=http, clock=lambda: 1000.0)
            w._doc("u").save({"access_token": "a1", "refresh_token": "r1", "expires": 99999})
            wo.ExternalWorkouts(env.store).save("u", "whoop", [wo.from_whoop(W_RUN)], date(2026, 10, 14))
            await w.disconnect("u")
            assert hits == ["DELETE /developer/v2/user/access"]
            assert not w.connected("u") and wo.ExternalWorkouts(env.store).all("u") == []
    asyncio.run(go_())


def test_feed_card_has_no_strain_or_heart_rate(fx) -> None:  # noqa: F811
    cm, today = fx.cm, fx.clock.at.date()
    w = {**wo.from_whoop(W_RUN), "start": f"{today.isoformat()}T07:03:00"}
    cm.put_settings("ann", {"share_prompted": True})
    assert len(cm.auto_share_external("ann", [w], today)) == 1
    card = cm.feed("bob")["items"][0]["workout"]
    assert card["source"] == "whoop" and card["title"] == "Run" and card["km"] == 7.95 and card["minutes"] == 44
    assert not {"avg_hr", "strain", "calories", "max_hr", "kilojoule"} & set(card)


def test_coming_soon_until_configured_then_connectable(env, tmp_path) -> None:  # noqa: F811
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    runner = ChatRunner(agent)
    plain = WebAuth(settings, env.store, "", dev_user="friend")
    wired = WebAuth(settings, env.store, "", dev_user="friend")
    wired.whoop = WhoopClient(env.store, "cid", "secret", f"{BASE}/app/auth/whoop/callback")

    def app(auth: WebAuth) -> Starlette:
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, runner))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app(plain)), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app(wired)), base_url=BASE) as b:
            r = (await a.get("/app/api/connections")).json()
            assert "whoop" not in [x["id"] for x in r["apps"]] and r["soon"][0]["id"] == "whoop"
            assert (await a.get("/app/api/me")).json()["whoop"] == {"available": False, "connected": False}
            r = (await b.get("/app/api/connections")).json()
            row = next(x for x in r["apps"] if x["id"] == "whoop")
            assert row["state"] == "not_connected" and any("never used in rabbt's coaching chat" in s for s in row["never"])
            assert "whoop" not in [s["id"] for s in r["soon"]]
            go = await b.get("/app/auth/whoop/start", follow_redirects=False)
            assert go.status_code == 302 and go.headers["location"].startswith("https://api.prod.whoop.com/oauth/oauth2/auth")
            # A callback with a state that wasn't issued is refused.
            bad = await b.get("/app/auth/whoop/callback?state=nope&code=x", follow_redirects=False)
            assert bad.headers["location"] == "/app/?whoop=failed"
            r = await b.post("/app/api/connections/whoop/sync", headers={"origin": BASE}, json={})
            assert r.status_code == 409, (r.status_code, r.text)
    asyncio.run(go_())
