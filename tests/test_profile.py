"""Profile traits, profile photo, race strategy and coach race notes."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaches import CoachLinks, CoachNotes, coach_user_id
from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.profilephoto import PhotoError, PhotoStore, sniff_photo
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
COACH = "coach@example.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32


# ------------------------------------------------------------- traits --
def test_athlete_traits_validate_and_bound(env) -> None:
    agent, _ = env.agent([])
    c = agent.coach
    a = c.update_athlete("u", {
        "home_location": "  Leadville, CO ", "home_elevation_m": 3094.4, "years_training": 6,
        "strengths": ["pacing", "climbing", "climbing"], "limiters": ["heat"], "heat_tolerance": "low",
        "sweat": "salty", "altitude_acclimatized": True, "terrain_access": ["trails", "mountains"],
        "race_history": [{"name": "Leadville Silver Rush 50", "date": "2025-07", "distance": "50 mi", "result": "10:42"}],
        "motivation": "Finish the big one", "season_goal": "Sub-25 at Leadville"})
    assert a["home_location"] == "Leadville, CO" and a["home_elevation_m"] == 3094
    assert a["strengths"] == ["climbing", "pacing"] and a["altitude_acclimatized"] is True
    bad = [{"home_elevation_m": 6000}, {"years_training": 61}, {"strengths": ["flying"]},
           {"heat_tolerance": "extreme"}, {"sweat": "lots"}, {"altitude_acclimatized": "yes"},
           {"terrain_access": ["moon"]}, {"race_history": [{"name": ""}]},
           {"race_history": [{"name": "x", "date": "last year"}]},
           {"race_history": [{"name": "x", "evil": 1}]},
           {"race_history": [{"name": f"r{i}"} for i in range(11)]}]
    for patch in bad:
        with pytest.raises(CoachError):
            c.validate_athlete(patch)
    assert c.validate_athlete({"motivation": "x" * 500})["motivation"] == "x" * 200
    assert c.validate_athlete({"season_goal": "y" * 500})["season_goal"] == "y" * 140
    ctx = c.context_block("u", agent._now("u"), None)
    assert "home elevation: 3094 m" in ctx and "strengths: climbing, pacing" in ctx
    assert "Leadville Silver Rush 50 (2025-07) 50 mi - 10:42" in ctx and "lives/trains at altitude: yes" in ctx
    assert "season goal: Sub-25 at Leadville" in ctx


def test_event_elevation_and_profile_fields(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("u").date()
    ev = agent.events.create("u", {"name": "Race", "date": (today + timedelta(days=40)).isoformat(),
                                   "elevation_m": 2800, "course_profile": "mountainous"})
    assert ev["elevation_m"] == 2800 and ev["course_profile"] == "mountainous"
    for patch in ({"elevation_m": 9000}, {"elevation_m": "high"}, {"course_profile": "steep"}):
        with pytest.raises(CoachError):
            agent.events.update("u", ev["id"], patch)
    from garmin_mcp.events import clean_info
    info = clean_info({"summary": "x", "suggested_elevation_m": "3,094", "suggested_course_profile": "hilly"})
    assert info["suggested_elevation_m"] == 3094 and info["suggested_course_profile"] == "hilly"
    assert "suggested_elevation_m" not in clean_info({"summary": "x", "suggested_elevation_m": 99999})


# -------------------------------------------------------------- photo --
def test_photo_magic_bytes_and_size(env) -> None:
    assert sniff_photo(PNG) == "image/png" and sniff_photo(JPEG) == "image/jpeg" and sniff_photo(WEBP) == "image/webp"
    for bad in (b"GIF89a....", b"<svg xmlns=", b"%PDF-1.4", b""):
        with pytest.raises(PhotoError):
            PhotoStore(env.store).save("u", bad)
    with pytest.raises(PhotoError, match="too large"):
        PhotoStore(env.store).save("u", JPEG + b"\x00" * 300 * 1024)
    ps = PhotoStore(env.store)
    v = ps.save("u", PNG)
    assert ps.version("u") == v and ps.load("u") == ("image/png", PNG)
    ps.delete("u")
    assert ps.version("u") is None and ps.load("u") is None


def _apps(env, tmp_path, agent):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend", "other@example.com": "other"})
    runner = ChatRunner(agent)

    def app(user):
        return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=user),
                                                 env.tokens, None, None, runner))
    return app("friend"), app(coach_user_id(COACH)), app("other")


def test_photo_api_owner_and_linked_coach_only(env, tmp_path) -> None:
    agent, _ = env.agent([])
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            assert (await a.get("/app/api/profile/photo")).status_code == 404
            assert (await a.post("/app/api/profile/photo", content=JPEG)).status_code == 403  # no origin
            r = await a.post("/app/api/profile/photo", headers=h, content=b"<svg onload=alert(1)>")
            assert r.status_code == 400
            r = await a.post("/app/api/profile/photo", headers=h, content=JPEG + b"\x00" * (300 * 1024))
            assert r.status_code == 413
            r = await a.post("/app/api/profile/photo", headers=h, content=JPEG)
            assert r.status_code == 201
            ver = r.json()["photo"]
            assert (await a.get("/app/api/me")).json()["photo"] == ver
            r = await a.get(f"/app/api/profile/photo?v={ver}")
            assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
            assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"].startswith("private")
            # Another athlete sees only their own (none); a coach account can't use the athlete route.
            assert (await o.get("/app/api/profile/photo")).status_code == 404
            assert (await c.get("/app/api/profile/photo")).status_code == 403
            # Coach: not linked yet -> denied; linked -> served; another athlete's -> denied.
            assert (await c.get("/app/api/coach/athletes/friend/photo")).status_code == 400
            await a.post("/app/api/coaches", headers=h, json={"email": COACH})
            r = await c.get("/app/api/coach/athletes/friend/photo")
            assert r.status_code == 200 and r.content == JPEG
            assert (await c.get("/app/api/coach/athletes")).json()["athletes"][0]["photo"] == ver
            assert (await c.get("/app/api/coach/athletes/other/photo")).status_code == 400
            assert (await o.get("/app/api/coach/athletes/friend/photo")).status_code == 400
            r = await a.request("DELETE", "/app/api/profile/photo", headers=h, json={})
            assert r.status_code == 200
            assert (await a.get("/app/api/profile/photo")).status_code == 404
            assert (await a.get("/app/api/me")).json()["photo"] is None
    asyncio.run(go_())


# ----------------------------------------------------------- strategy --
STRATEGY = {"summary": "Start easy, hike Hope Pass, eat every 30 minutes.", "key_risks": ["Altitude"],
            "pacing": ["Hike all climbs"], "fueling": ["60-80 g/h"], "training_focus": ["Long hikes with poles"],
            "taper_notes": "Two weeks.", "mental": ["One aid station at a time"], "evil": "ignored"}


def test_strategy_structured_call_allowance_and_storage(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("u").date()
    agent.coach.update_athlete("u", {"home_elevation_m": 10, "strengths": ["endurance"]})
    ev = agent.events.create("u", {"name": "Leadville Trail 100 Run", "type": "trail", "distance": "ultra",
                                   "location": "Leadville, CO", "date": (today + timedelta(weeks=10)).isoformat()})
    calls = []

    async def fake_structured(system, prompt, tool):
        calls.append((system, prompt, tool))
        return dict(STRATEGY)
    agent._backend.structured = fake_structured  # type: ignore[attr-defined]
    out = asyncio.run(agent.race_strategy("u", ev["id"], coach_notes=["Walk every climb above 11k ft"]))
    system, prompt, tool = calls[0]
    assert tool["name"] == "save_race_strategy" and "never suggest losing weight" in system
    assert '"Altitude"' in prompt and "Walk every climb" in prompt and '"phase": "build"' in prompt
    assert "oura" not in prompt.lower()
    assert out["summary"].startswith("Start easy") and out["training_focus"] == ["Long hikes with poles"]
    assert "evil" not in out and out["created"] > 0
    assert agent.events.get("u", ev["id"])["strategy"]["pacing"] == ["Hike all climbs"]
    for _ in range(4):
        asyncio.run(agent.race_strategy("u", ev["id"]))
    with pytest.raises(CoachError, match="used up"):
        asyncio.run(agent.race_strategy("u", ev["id"]))
    past = agent.events.create("u", {"name": "Old", "date": (today - timedelta(days=3)).isoformat()})
    with pytest.raises(CoachError, match="done"):
        asyncio.run(agent.race_strategy("u", past["id"]))


# --------------------------------------------------------- race notes --
def test_coach_race_notes(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    ev = agent.events.create("friend", {"name": "Spring 50K", "type": "trail", "date": (today + timedelta(days=50)).isoformat()})
    other_ev = agent.events.create("other", {"name": "Not yours", "date": (today + timedelta(days=50)).isoformat()})
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            await a.post("/app/api/coaches", headers=h, json={"email": COACH})
            r = await c.post("/app/api/coach/athletes/friend/notes", headers=h,
                             json={"text": "Run the first 10K by HR", "shared": True, "event_id": ev["id"]})
            assert r.status_code == 201 and r.json()["note"]["event_id"] == ev["id"]
            r = await c.post("/app/api/coach/athletes/friend/notes", headers=h,
                             json={"text": "x", "shared": True, "event_id": other_ev["id"]})
            assert r.status_code == 400
            await c.post("/app/api/coach/athletes/friend/notes", headers=h,
                         json={"text": "Private race note", "shared": False, "event_id": ev["id"]})
            await c.post("/app/api/coach/athletes/friend/notes", headers=h, json={"text": "General", "shared": True})
            view = (await a.get(f"/app/api/events/{ev['id']}/strategy")).json()
            assert [n["text"] for n in view["coach_notes"]] == ["Run the first 10K by HR"]
            assert view["strategy"] is None and isinstance(view["racefit"]["factors"], list)
            assert (await a.get("/app/api/events/nope/strategy")).status_code == 400
    asyncio.run(go_())
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "(for Spring 50K) Run the first 10K by HR" in ctx
    links = CoachLinks(env.store, athlete_emails=lambda: {"friend@example.com": "friend"})
    assert CoachNotes(env.store).for_event("friend", ev["id"], links.coach_emails("friend"))[0]["event_id"] == ev["id"]
