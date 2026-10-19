"""Explore "For you": interests validation, ranking and why lines, sections, friends, bucket, API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import explore, foryou
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.coaching import CoachError, CoachStore, interests_line, validate_interests
from garmin_mcp.config import Settings
from garmin_mcp.explore import RaceSearch, normalize
from garmin_mcp.foryou import ForYou, compute, friend_races, score
from garmin_mcp.progress import QUESTS, quests_view
from garmin_mcp.social import Social
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_explore import _mock, rsu_race

BASE = "http://localhost:8001"
H = {"origin": BASE}
TODAY = date(2026, 10, 14)
LEADVILLE = date(2027, 8, 21)
MAIN = {"id": "e1", "name": "Leadville 100", "date": LEADVILLE.isoformat(), "distance": "ultra", "type": "trail",
        "priority": "A", "main": True}


def race(rid: int, name: str, when: date, **kw) -> dict:
    r = normalize(rsu_race(rid, name, when.strftime("%m/%d/%Y"), **kw))
    assert r is not None
    return r


# ------------------------------------------------------------- interests --
def test_interests_validation_and_context(tmp_path, fernet_key) -> None:
    ok = validate_interests({"race_types": ["ultra", "trail", "trail"], "distances": ["half", "ultra_100k_plus"],
                             "travel": "regional", "race_vibe": ["bucket_list", "scenic"],
                             "goals_next_12mo": ["first_ultra"], "months_avoid": [8, 1, 8], "home_zip": " 80204 "})
    assert ok["race_types"] == ["trail", "ultra"] and ok["race_vibe"] == ["scenic", "bucket_list"]
    assert ok["months_avoid"] == [1, 8] and ok["home_zip"] == "80204"
    assert validate_interests(None) == {} and validate_interests({"race_types": [], "home_zip": ""}) == {}
    for bad in ({"race_types": ["skydiving"]}, {"distances": "half"}, {"travel": "moon"},
                {"months_avoid": [13]}, {"months_avoid": [True]}, {"home_zip": "8020"}, {"home_zip": 80204},
                {"color": "red"}, "trail"):
        with pytest.raises(CoachError):
            validate_interests(bad)
    coach = CoachStore(AppStore(tmp_path / "app", fernet_key))
    coach.update_athlete("u", {"interests": ok, "experience": "5 years"})
    with pytest.raises(CoachError):
        coach.update_athlete("u", {"interests": {"race_vibe": ["angry"]}})
    assert coach.athlete("u")["interests"] == ok
    from datetime import datetime, timezone
    ctx = coach.context_block("u", datetime(2026, 10, 14, 8, tzinfo=timezone.utc), None)
    line = next(x for x in ctx.splitlines() if x.startswith("Race interests"))
    assert "types trail, ultra" in line and "avoids Jan, Aug" in line and "travel regional" in line
    assert "80204" not in ctx and "interests:" not in ctx  # compact line only, never the zip
    assert interests_line({}) == ""


# --------------------------------------------------------------- ranking --
def test_ranking_why_lines_and_exclusions() -> None:
    interests = {"race_types": ["trail"], "distances": ["half"], "months_avoid": [5]}
    tune = race(1, "Golden Gate Half", LEADVILLE - timedelta(weeks=6), dist="13.1 Miles")
    taper = race(2, "Too Close Trail", LEADVILLE - timedelta(days=10), dist="13.1 Miles")
    may = race(3, "May Trail Half", date(2027, 5, 15), dist="Half Marathon")
    on_cal = race(4, "Already Mine", date(2027, 3, 6), dist="10K")
    plain = race(5, "Spring Trail 10K", date(2027, 3, 13), dist="10K")
    road = race(6, "Road 5K", date(2027, 3, 20), etype="running_race", dist="5K")
    soon = race(7, "Next Week Trail", TODAY + timedelta(days=5), dist="13.1 Miles")
    events = [MAIN, {"id": "e2", "name": "Already Mine", "date": "2027-03-06", "priority": "C"}]

    s = score(tune, interests=interests, main=MAIN, a_dates=[LEADVILLE])
    assert s["why"] == "Half-marathon tune-up 6 weeks before Leadville 100"
    assert s["score"] == 3 + 3 + 4 + 1 and s["fit"]["label"] == "Great fit"
    assert s["reasons"] == ["Trail race", "Half-marathon", "6 weeks before Leadville 100", "Registration open"]
    assert foryou.blocked(taper, interests=interests, a_dates=[LEADVILLE], calendar=set()) == "taper"
    assert foryou.blocked(may, interests=interests, a_dates=[], calendar=set()) == "month"

    secs = compute([tune, taper, may, on_cal, plain, road, soon, tune], interests=interests, events=events,
                   today=TODAY, near_ok=True, readiness_status="behind")
    by = {x["id"]: x for x in secs}
    picks = [r["name"] for r in by["picks"]["races"]]
    assert picks[0] == "Golden Gate Half"
    assert "Too Close Trail" not in picks and "May Trail Half" not in picks and "Already Mine" not in picks
    assert "Road 5K" not in picks  # no type or distance match: below the bar
    assert "Next Week Trail" not in picks  # too soon to be a pick
    assert by["picks"]["races"][1]["why"].startswith("A trail race in March")
    assert by["tuneups"]["title"] == "Tune-ups for Leadville 100" and "behind" in by["tuneups"]["note"]
    assert [r["name"] for r in by["tuneups"]["races"]] == ["Golden Gate Half"]
    near = [r["name"] for r in by["near"]["races"]]
    assert near == ["Next Week Trail"] and by["near"]["title"] == "Coming up near you"
    # No zip -> no "near" section; no interests matching -> no picks; empty sections are dropped.
    secs = compute([road], interests={"race_types": ["swim"]}, events=[], today=TODAY, near_ok=False)
    assert secs == []


def test_first_ultra_goal_and_after_a_race_penalty() -> None:
    interests = {"race_types": ["trail"], "goals_next_12mo": ["first_ultra"]}
    ultra = race(1, "Fall 50K", LEADVILLE + timedelta(days=10), dist="50K")
    s = score(ultra, interests=interests, main=None, a_dates=[LEADVILLE])
    assert s["why"] == "Could be your first ultra" and "Soon after your A race" in s["reasons"]
    assert s["score"] == 3 + 1 + 2 - 2


def test_friend_races_merge_and_shape() -> None:
    ev = {"id": "x", "name": "Pikes Peak Marathon", "date": "2027-08-29", "distance": "marathon",
          "type": "trail", "location": "Manitou Springs, CO", "notes": "secret", "priority": "A"}
    old = dict(ev, name="Done Race", date="2026-01-01")
    out = friend_races([("Ann", [ev, old]), ("Bob", [dict(ev, id="y")])], TODAY)
    assert len(out) == 1 and out[0]["why"] == "Ann and Bob are racing" and out[0]["source"] == "friend"
    assert out[0]["city"] == "Manitou Springs" and "notes" not in out[0] and "secret" not in str(out[0])
    assert out[0]["events"][0]["distance_km"] == 42.2


def test_service_windows_partial_and_cache() -> None:
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {"trail_race": [rsu_race(1, "Golden Gate Half", (LEADVILLE - timedelta(weeks=6)).strftime("%m/%d/%Y"), dist="13.1 Miles")]}))
    fy = ForYou(search=lambda: rs)
    interests = {"race_types": ["trail", "road_cycling"], "travel": "local", "home_zip": "80204"}
    out = asyncio.run(fy.sections("u", interests=interests, athlete={}, events=[MAIN], today=TODAY))
    assert out["zip"] == "80204" and out["radius"] == 50 and not out["partial"]
    assert {c["event_type"] for c in calls} == {"trail_race", "bike_race"} and all(c["radius"] == "50" for c in calls)
    assert len(calls) == 6  # soon, later, tune-up window x 2 types
    assert [s["id"] for s in out["sections"]] == ["picks", "tuneups"]
    asyncio.run(fy.sections("u", interests=interests, athlete={}, events=[MAIN], today=TODAY))
    assert len(calls) == 6  # cached
    # RunSignup down: empty but graceful, and not cached.
    down = ForYou(search=lambda: RaceSearch(transport=_mock([], status=500)))
    out = asyncio.run(down.sections("u", interests=interests, athlete={}, events=[], today=TODAY))
    assert out["sections"] == [] and out["partial"] and out["failed"]


# ------------------------------------------------------------------- API --
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob"}


def _apps(env, tmp_path):
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW))

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    return agent, {u: app(u) for u in ("ann", "bob", coach_user_id("c@x.com"))}


def test_foryou_api_friends_bucket_and_quest(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path)
    today = agent._now("ann").date()
    a_race = today + timedelta(weeks=20)
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {"trail_race": [
        rsu_race(1, "Tune Half", (a_race - timedelta(weeks=5)).strftime("%m/%d/%Y"), dist="13.1 Miles")]}))
    monkeypatch.setattr(foryou, "_default", ForYou(search=lambda: rs))
    monkeypatch.setattr(explore, "_default", rs)
    agent.events.create("ann", {"name": "Big Trail 100", "date": a_race.isoformat(), "type": "trail",
                                "distance": "ultra", "priority": "A"})
    agent.events.create("bob", {"name": "Bob's Marathon", "date": (today + timedelta(days=50)).isoformat(),
                                "type": "running", "distance": "marathon", "location": "Boulder, CO",
                                "notes": "private note", "priority": "B"})
    for uid in ("ann", "bob"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    soc = Social(env.store, athletes=lambda: dict(ALLOW))
    soc.follow("ann", code=soc.invite_code("bob"))
    soc.accept("bob", soc.people("bob")["pending_in"][0]["edge_id"])
    research: list = []

    async def fake_research(system, prompt, **kw):
        research.append(prompt)
        assert "oura" not in prompt.lower() and "80204" not in prompt
        return {"races": [{"name": "UTMB", "date": (today + timedelta(days=300)).isoformat(), "type": "ultra",
                           "location": "Chamonix, France", "distances": "171K", "url": "https://utmb.world"}]}
    agent._backend.research = fake_research  # type: ignore[attr-defined]

    async def go() -> None:
        c = {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}
        ann = c["ann"]
        r = await ann.get("/app/api/explore/foryou")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_interests"] is False and body["bucket"]["eligible"] is False
        q = next(x for x in (await ann.get("/app/api/progress")).json()["quests"] if x["id"] == "interests")
        assert q["done"] is False and q["optional"] is True
        r = await ann.put("/app/api/athlete", headers=H, json={"interests": {
            "race_types": ["trail"], "distances": ["half"], "travel": "local", "home_zip": "80204",
            "race_vibe": ["bucket_list"]}})
        assert r.status_code == 200, r.text
        assert (await ann.put("/app/api/athlete", headers=H, json={"interests": {"travel": "mars"}})).status_code == 400
        body = (await ann.get("/app/api/explore/foryou")).json()
        ids = [s["id"] for s in body["sections"]]
        assert ids[:2] == ["picks", "tuneups"] and "friends" not in ids  # bob shares no races yet
        pick = body["sections"][0]["races"][0]
        assert pick["why"] == "Half-marathon tune-up 5 weeks before Big Trail 100" and "hints" in pick
        assert body["bucket"] == {"eligible": True, "due": True}
        soc.put_settings("bob", {"races": True})
        body = (await ann.get("/app/api/explore/foryou")).json()
        fr = next(s for s in body["sections"] if s["id"] == "friends")
        assert fr["races"][0]["name"] == "Bob's Marathon" and fr["races"][0]["why"] == "Bob is racing"
        assert "private note" not in str(fr)
        # Bob doesn't follow Ann: he never sees her races.
        assert "friends" not in [s["id"] for s in (await c["bob"].get("/app/api/explore/foryou")).json()["sections"]]
        # Bucket list: once a week, stored.
        assert (await ann.post("/app/api/explore/foryou/bucket", json={})).status_code == 403  # origin
        r = await ann.post("/app/api/explore/foryou/bucket", headers=H, json={})
        assert r.status_code == 200, r.text
        assert r.json()["section"]["races"][0]["name"] == "UTMB" and r.json()["section"]["races"][0]["source"] == "web"
        await ann.post("/app/api/explore/foryou/bucket", headers=H, json={})
        assert len(research) == 1
        body = (await ann.get("/app/api/explore/foryou")).json()
        assert body["sections"][-1]["id"] == "bucket" and body["bucket"]["due"] is False
        r = await c["bob"].post("/app/api/explore/foryou/bucket", headers=H, json={})
        assert r.status_code == 400  # no bucket-list interest
        q = next(x for x in (await ann.get("/app/api/progress")).json()["quests"] if x["id"] == "interests")
        assert q["done"] is True
        coach = c[coach_user_id("c@x.com")]
        assert (await coach.get("/app/api/explore/foryou")).status_code == 403
        assert (await coach.post("/app/api/explore/foryou/bucket", headers=H, json={})).status_code == 403
    asyncio.run(go())


def test_interests_quest_is_optional() -> None:
    q = next(x for x in QUESTS if x[0] == "interests")
    assert q == ("interests", "Tell rabbt what you're into", "Personal race picks", 50, True)
    v = next(x for x in quests_view({"interests": True}, {}) if x["id"] == "interests")
    assert v["done"] and v["optional"]
