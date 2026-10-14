"""Human coaches: invites, sign-in eligibility, access checks, chat, notes, API."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaches import CoachChat, CoachLinks, CoachNotes, coach_user_id
from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _athlete

BASE = "http://localhost:8001"
COACH = "coach@example.com"


def _links(env, allow=None):
    return CoachLinks(env.store, athlete_emails=lambda: allow or {"athlete@example.com": "ath"})


def test_invite_signin_and_revoke(env) -> None:
    links = _links(env)
    assert links.user_id_for_email(COACH) is None  # no invite, no sign-in
    with pytest.raises(CoachError):
        links.invite("ath", "not an email")
    with pytest.raises(CoachError, match="own email"):
        links.invite("ath", "athlete@example.com")
    links.invite("ath", "Coach@Example.com")
    cid = links.user_id_for_email(COACH)
    assert cid == coach_user_id(COACH) and links.is_coach_user(cid)
    ath = links.athletes_of(cid)
    assert [a["athlete_id"] for a in ath] == ["ath"] and ath[0]["status"] == "active"
    assert links.require(cid, "ath")["can_see_rabbit_chats"] is False
    with pytest.raises(CoachError, match="access"):
        links.require(cid, "ath", perm="can_see_rabbit_chats")
    with pytest.raises(CoachError):
        links.require(cid, "someone-else")
    links.remove("ath", COACH)
    assert not links.is_coach_user(cid) and links.user_id_for_email(COACH) is None


def test_allowlisted_athlete_can_also_coach(env) -> None:
    links = _links(env, {"a@x.com": "a", "b@x.com": "b"})
    links.invite("a", "b@x.com")
    assert links.user_id_for_email("b@x.com") == "b"
    assert [x["athlete_id"] for x in links.athletes_of("b")] == ["a"]


def test_chat_threads_and_unread(env) -> None:
    chat = CoachChat(env.store)
    t = chat.open_thread("ath", COACH)
    assert chat.open_thread("ath", COACH)["id"] == t["id"]  # one general thread
    w = chat.open_thread("ath", COACH, session={"id": "s1", "date": "2026-10-20", "title": "Tempo run"})
    assert w["id"] != t["id"] and w["title"].startswith("Tempo run")
    chat.post("ath", w["id"], sender="coach", text="Keep it at threshold, not above.", coach=COACH)
    assert chat.unread("ath", "athlete") == 1
    chat.mark_read("ath", w["id"], "athlete")
    assert chat.unread("ath", "athlete") == 0
    with pytest.raises(CoachError):
        chat.post("ath", w["id"], sender="coach", text="hi", coach="other@x.com")
    with pytest.raises(CoachError):
        chat.post("ath", w["id"], sender="athlete", text="   ")


def test_notes_shared_and_private(env) -> None:
    notes = CoachNotes(env.store)
    notes.add("ath", COACH, "Keep long runs under 2:30 until December.", shared=True, pinned=True)
    notes.add("ath", COACH, "Watch for overreaching after travel.", shared=False)
    assert len(notes.list("ath", coach=COACH)) == 2
    assert [n["text"][:4] for n in notes.list("ath", shared_only=True)] == ["Keep"]
    assert notes.list("ath", coach="other@x.com") == notes.list("ath", shared_only=True)


def test_shared_notes_reach_rabbit(env) -> None:
    agent, _ = env.agent([])
    links = _links(env, {"friend@example.com": "friend"})
    links.invite("friend", COACH)
    CoachNotes(env.store).add("friend", COACH, "No running on Mondays.", shared=True)
    CoachNotes(env.store).add("friend", COACH, "Private thought.", shared=False)
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "No running on Mondays." in ctx and "Private thought." not in ctx
    # A removed coach's notes stop steering Rabbit.
    links.remove("friend", COACH)
    assert "No running on Mondays." not in agent.coach.context_block("friend", agent._now("friend"), None)


def test_coach_chains_and_dropped_athletes_lose_access(env) -> None:
    allow = {"a@x.com": "a"}
    links = _links(env, allow)
    links.invite("a", "x@x.com")
    cx = links.user_id_for_email("x@x.com")
    with pytest.raises(CoachError, match="Only athletes"):
        links.invite(cx, "z@x.com")
    allow.pop("a@x.com")  # athlete removed from the allowlist
    assert links.user_id_for_email("x@x.com") is None and not links.is_coach_user(cx)


def test_coach_accounts_are_limited_to_the_coach_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    auth = WebAuth(settings, env.store, "", dev_user=coach_user_id(COACH))
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            assert (await c.get("/app/api/me")).status_code == 200
            assert (await c.get("/app/api/coach/athletes")).status_code == 200
            for path in ("/app/api/threads", "/app/api/events", "/app/api/stats", "/app/api/plan"):
                r = await c.get(path)
                assert r.status_code == 403, path
            r = await c.post("/app/api/coaches", headers={"origin": BASE}, json={"email": "z@x.com"})
            assert r.status_code == 403
    asyncio.run(go_())


def test_coach_api_end_to_end(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", _athlete())
    agent.coach.create_goal("friend", {"title": "Race", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    plan = agent.plans.build("friend")
    sess = next(s for w in plan["weeks"] for d, ss in w["days"].items() for s in ss
                if d > today.isoformat() and s["sport"] == "run")
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    runner = ChatRunner(agent)
    athlete_auth = WebAuth(settings, env.store, "", dev_user="friend")
    cid = coach_user_id(COACH)
    coach_auth = WebAuth(settings, env.store, "", dev_user=cid)
    athlete_app = Starlette(routes=build_app_routes(settings, athlete_auth, env.tokens, None, None, runner))
    coach_app = Starlette(routes=build_app_routes(settings, coach_auth, env.tokens, None, None, runner))
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            # Not invited yet: the coach sees nothing and can't open the athlete.
            assert (await c.get("/app/api/coach/athletes")).json()["athletes"] == []
            assert (await c.get("/app/api/coach/athletes/friend")).status_code == 400
            r = await a.post("/app/api/coaches", headers=h, json={"email": COACH, "can_edit_plan": True})
            assert r.status_code == 201 and r.json()["coaches"][0]["can_edit_plan"] is True
            me = (await c.get("/app/api/me")).json()
            assert me["role"] == "coach" and me["coaching"] == 1
            ov = (await c.get("/app/api/coach/athletes/friend")).json()
            assert ov["goal"]["title"] == "Race" and ov["link"]["status"] == "active"
            # Coach edits a session in the plan.
            r = await c.patch(f"/app/api/coach/athletes/friend/plan/sessions/{sess['id']}", headers=h,
                              json={"minutes": 55})
            assert r.status_code == 200, r.text
            # Workout chat: coach opens a thread on that session, athlete replies.
            r = await c.post("/app/api/coach/athletes/friend/chat", headers=h, json={"session_id": sess["id"]})
            tid = r.json()["thread"]["id"]
            await c.post(f"/app/api/coach/athletes/friend/chat/{tid}/messages", headers=h, json={"text": "Easy first 10'"})
            assert (await a.get("/app/api/me")).json()["coach_unread"] == 1
            t = (await a.get(f"/app/api/coachchat/{tid}")).json()["thread"]
            assert t["session_id"] == sess["id"] and t["messages"][0]["from"] == "coach"
            await a.post(f"/app/api/coachchat/{tid}/messages", headers=h, json={"text": "Got it"})
            assert (await c.get("/app/api/coach/athletes")).json()["athletes"][0]["unread"] == 1
            # Rabbit chats stay private until the athlete allows it.
            assert (await c.get("/app/api/coach/athletes/friend/rabbit")).status_code == 400
            await a.patch(f"/app/api/coaches/{COACH}", headers=h, json={"can_see_rabbit_chats": True})
            assert (await c.get("/app/api/coach/athletes/friend/rabbit")).status_code == 200
            # Plan edit permission can be taken away.
            await a.patch(f"/app/api/coaches/{COACH}", headers=h, json={"can_edit_plan": False})
            r = await c.patch(f"/app/api/coach/athletes/friend/plan/sessions/{sess['id']}", headers=h,
                              json={"minutes": 60})
            assert r.status_code == 400
            # Notes: shared ones are visible to the athlete.
            await c.post("/app/api/coach/athletes/friend/notes", headers=h, json={"text": "Sleep 8h", "shared": True})
            await c.post("/app/api/coach/athletes/friend/notes", headers=h, json={"text": "Private", "shared": False})
            assert [n["text"] for n in (await a.get("/app/api/coachnotes")).json()["notes"]] == ["Sleep 8h"]
            # Removing the coach ends access.
            await a.request("DELETE", f"/app/api/coaches/{COACH}", headers=h, json={})
            assert (await c.get("/app/api/coach/athletes/friend")).status_code == 400
    asyncio.run(go_())
