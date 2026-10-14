"""Find a coach: the seeded directory, matching, coach_status, quests, race-strategy coach threads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coachdir import SEED_COACHES, CoachDirectory, match, public_view
from garmin_mcp.coaches import CoachChat, coach_user_id
from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.progress import QUESTS
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
COACH = "coach@example.com"
H = {"origin": BASE}

# Exactly the facts verified from bigdogcoaching.com; nothing else may be claimed.
BILL = {
    "id": "bill-ludington", "name": "Bill Ludington", "business": "Bigdog Coaching",
    "location": "Golden, Colorado", "photo_url": None,
    "sports": ["triathlon", "running", "cycling", "swimming", "strength"],
    "specialties": ["Triathlon", "70.3 & Ironman", "Strength & functional fitness"],
    "credentials": ["Ironman-U certified coach", "ACE certified trainer", "Ironman World Championship qualifier"],
    "bio": ("Golden, Colorado triathlon coach (Ironman-U and ACE certified) building custom training plans "
            "and lifestyle guidance, from first 70.3s to Ironman age-group podiums."),
    "highlights": ["Ironman Texas 2021: 1st AG 25-29, 8th overall, Kona qualifier", "Texas 70.3 2022: 2nd M50-54",
                   "Victoria 70.3 2022: 4th M55-59", "Napa 70.3 2021: two age-group wins"],
    "testimonial": {"quote": "Bill has taken me from nothing to multiple age group wins.", "by": "Ian, Denver, CO"},
    "services": ["Custom training plans and lifestyle advice"], "pricing_note": "Contact for pricing",
    "contact": {"email": "bill.ludington@gmail.com", "phone": "(720) 480-5749", "website": "https://bigdogcoaching.com"},
    "accepting": True, "verified_by_operator": True, "rabbit_user_email": None,
}


def test_seed_is_exactly_the_verified_facts(env) -> None:
    assert SEED_COACHES == [BILL]
    d = CoachDirectory(env.store)
    assert d.all() == [BILL]
    assert env.store.global_doc("coach_directory").load()["coaches"] == [BILL]
    # The operator can edit the doc later; the seed doesn't overwrite it.
    env.store.global_doc("coach_directory").update(lambda x: x["coaches"][0].update(accepting=False))
    assert d.get("bill-ludington")["accepting"] is False
    with pytest.raises(CoachError):
        d.get("nobody")
    pub = public_view(BILL)
    assert "rabbit_user_email" not in pub and pub["can_invite"] is False


def test_matching_and_why(env) -> None:
    m = match(BILL, {}, {"name": "Boulder 70.3", "type": "triathlon", "distance": "70.3"})
    assert m["why"] == "Coaches 70.3 & Ironman: fits your Boulder 70.3" and m["score"] >= 6
    m2 = match(BILL, {}, {"name": "Bolder Boulder", "type": "running", "distance": "10k"})
    assert m2["why"] == "Coaches running: fits your Bolder Boulder" and m2["score"] < m["score"]
    assert match(BILL, {"favorite_sports": ["swim", "bike"]}, None)["why"] == "Coaches cycling and swimming, like you"
    assert match(BILL, {"home_location": "Golden, CO"}, None)["why"] == "Based in Golden, Colorado, near you"
    assert match(BILL, {}, None)["why"].startswith("Coaches triathlon")
    # Filters and ordering: a triathlon goal puts the triathlon coach first.
    d = CoachDirectory(env.store)
    other = dict(BILL, id="z-run", name="Ann Runner", sports=["running"], specialties=["Marathon"])
    env.store.global_doc("coach_directory").update(lambda x: x.setdefault("coaches", [BILL]).append(other))
    race = {"name": "Boulder 70.3", "type": "triathlon", "distance": "70.3"}
    assert [c["id"] for c in d.search({}, race)] == ["bill-ludington", "z-run"]
    assert [c["id"] for c in d.search({}, race, sport="swimming")] == ["bill-ludington"]
    assert [c["id"] for c in d.search({}, race, q="marathon")] == ["z-run"]
    with pytest.raises(CoachError):
        d.search({}, race, sport="curling")


def test_coach_status_validation_and_context(env) -> None:
    agent, _ = env.agent([])
    with pytest.raises(CoachError):
        agent.coach.update_athlete("friend", {"coach_status": "maybe"})
    agent.coach.update_athlete("friend", {"coach_status": "looking"})
    ctx = agent.coach.context_block("friend", datetime(2026, 10, 14, 8, 0).astimezone(), None)
    assert "Athlete is looking for a human coach" in ctx and "coach status" not in ctx
    agent.coach.update_athlete("friend", {"coach_status": "self_coached"})
    ctx = agent.coach.context_block("friend", datetime(2026, 10, 14, 8, 0).astimezone(), None)
    assert "looking for a human coach" not in ctx
    agent.coach.update_athlete("friend", {"coach_status": None})
    assert agent.coach.athlete("friend")["coach_status"] is None
    q = next(q for q in QUESTS if q[0] == "coach_status")
    assert q[1:] == ("Coaching: do you want a coach?", "Find one or go solo", 25, True)


def test_event_threads(env) -> None:
    chat = CoachChat(env.store)
    ev = {"id": "e1", "title": "Boulder 70.3 strategy"}
    t = chat.open_thread("friend", COACH, event=ev)
    assert t["event_id"] == "e1" and t["title"] == "Boulder 70.3 strategy" and t["session_id"] is None
    assert chat.open_thread("friend", COACH, event=ev)["id"] == t["id"]
    general = chat.open_thread("friend", COACH)
    assert general["id"] != t["id"] and general["title"] == "General"
    assert chat.threads("friend")[0]["event_id"] in ("e1", None)
    with pytest.raises(CoachError):
        chat.open_thread("friend", COACH, event=ev, session={"id": "s", "date": "2026-10-20", "title": "Run"})


def _apps(env, agent, tmp_path):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    runner = ChatRunner(agent)
    a = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user="friend"),
                                          env.tokens, None, None, runner))
    c = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=coach_user_id(COACH)),
                                          env.tokens, None, None, runner))
    return a, c


def test_directory_api_and_race_thread(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    ev = agent.events.create("friend", {"name": "Boulder 70.3", "type": "triathlon", "distance": "70.3",
                                        "date": (today + timedelta(weeks=20)).isoformat()})
    agent.events.set_main("friend", ev["id"])
    athlete_app, coach_app = _apps(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = (await a.get("/app/api/coaches/directory")).json()
            assert r["coaches"][0]["id"] == "bill-ludington"
            assert r["coaches"][0]["match"]["why"] == "Coaches 70.3 & Ironman: fits your Boulder 70.3"
            assert "rabbit_user_email" not in r["coaches"][0] and r["race"]["name"] == "Boulder 70.3"
            assert (await a.get("/app/api/coaches/directory?sport=curling")).status_code == 400
            one = (await a.get("/app/api/coaches/directory/bill-ludington")).json()["coach"]
            assert one["contact"]["phone"] == "(720) 480-5749"
            assert (await a.get("/app/api/coaches/directory/nope")).status_code == 400
            # No Rabbit login on file: no in-app invite.
            assert (await a.post("/app/api/coaches/directory/bill-ludington/invite", headers=H, json={})).status_code == 400
            # Quest: answering the coaching question completes it.
            p = (await a.get("/app/api/progress")).json()
            assert not next(q for q in p["quests"] if q["id"] == "coach_status")["done"]
            await a.put("/app/api/athlete", headers=H, json={"coach_status": "looking"})
            p = (await a.get("/app/api/progress")).json()
            assert next(q for q in p["quests"] if q["id"] == "coach_status")["done"]

            # Coach accounts can't use the directory.
            await a.post("/app/api/coaches", headers=H, json={"email": COACH})
            assert (await c.get("/app/api/coaches/directory")).status_code == 403
            assert (await c.get("/app/api/coaches/directory/bill-ludington")).status_code == 403
            # The coach doesn't see the athlete's coach_status.
            assert "coach_status" not in (await c.get("/app/api/coach/athletes/friend")).json()["athlete"]

            # Ask your coach: a race-tied thread, the coach sees the race name.
            r = await a.post("/app/api/coachchat", headers=H, json={"coach": COACH, "event_id": ev["id"]})
            assert r.status_code == 201, r.text
            t = r.json()["thread"]
            assert t["event_id"] == ev["id"] and t["title"] == "Boulder 70.3 strategy"
            r2 = await a.post("/app/api/coachchat", headers=H, json={"coach": COACH, "event_id": ev["id"]})
            assert r2.json()["thread"]["id"] == t["id"]
            assert (await a.post("/app/api/coachchat", headers=H,
                                 json={"coach": COACH, "event_id": "nope"})).status_code == 400
            ct = (await c.get("/app/api/coach/athletes/friend/chat")).json()["threads"]
            assert [x["title"] for x in ct if x["event_id"] == ev["id"]] == ["Boulder 70.3 strategy"]
            r = await c.post("/app/api/coach/athletes/friend/chat", headers=H, json={"event_id": ev["id"]})
            assert r.json()["thread"]["id"] == t["id"]
            # Another athlete's race id is refused; removing the coach ends access.
            assert (await c.post("/app/api/coach/athletes/friend/chat", headers=H,
                                 json={"event_id": "e-other"})).status_code == 400
            await a.request("DELETE", f"/app/api/coaches/{COACH}", headers=H, json={})
            assert (await c.get(f"/app/api/coach/athletes/friend/chat/{t['id']}")).status_code == 400
            # Without a coach the athlete can't open one.
            assert (await a.post("/app/api/coachchat", headers=H,
                                 json={"coach": COACH, "event_id": ev["id"]})).status_code == 400
    asyncio.run(go_())
