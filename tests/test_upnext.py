"""Rabbit home "Up next" (upnext.py), invite-join auto-follow and the first visit without Garmin."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings, _parse_email_map
from garmin_mcp.moments import friend_joined_moment
from garmin_mcp.server import build_app
from garmin_mcp.social import Social
from garmin_mcp.upnext import NO_GARMIN, choose, first_visit, pick_group
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_passkeys import Authenticator, join, make_invite
from tests.test_webapp import BASE, HOST, Google, run, sign_in

NOON = datetime(2026, 10, 14, 12, 0)  # a Wednesday; fixed so nothing depends on the clock


def card(tone="go", headline="Today: Tempo (50')", detail="Form +3: good to go. Hit Tempo as planned.",
         action=("open_session", "Open session"), session=True):
    return {"date": "2026-10-14", "tone": tone, "headline": headline, "detail": detail,
            "session": {"id": "s1", "title": "Tempo", "minutes": 50, "sport": "run"} if session else None,
            "action": {"kind": action[0], "label": action[1]}, "signals": [], "garmin": True}


# ------------------------------------------------------------------ choose --
def test_session_first_with_start_and_send_to_watch() -> None:
    u = choose(card=card(), has_plan=True, goal={"title": "Marathon"},
               session={"target": "5:00–5:10 /km", "on_watch": False, "syncable": True})
    assert u["kind"] == "session" and u["primary"] == {"kind": "start", "label": "Start"}
    assert u["secondary"] == {"kind": "send_to_watch", "label": "Send to watch"}
    assert u["session"]["target"] == "5:00–5:10 /km" and u["headline"] == "Tempo · 50 min"
    assert u["detail"].startswith("Form +3") and u["today"]["tone"] == "go"  # Today's advice, shown once
    synced = choose(card=card(), has_plan=True, goal=None, session={"on_watch": True, "syncable": True})
    assert synced["secondary"] is None
    no_garmin = choose(card=card(), has_plan=True, goal=None, session={"on_watch": False, "syncable": True}, garmin=False)
    assert no_garmin["secondary"] is None
    # Race week with a session: the race pack rides along as an extra link.
    race = choose(card=card(tone="race", headline="Race week: Boston in 5 days", action=("open_racepack", "Open race pack")),
                  has_plan=True, goal=None)
    assert race["kind"] == "session" and race["extra"] == {"kind": "today", "label": "Open race pack"}


def test_rest_day_previews_tomorrow_and_today_calls() -> None:
    tomorrow = {"date": "2026-10-15", "rest": False, "title": "Long run", "sport": "run", "minutes": 90, "id": "s2"}
    rest = choose(card=card(tone="rest", headline="Rest day", action=("log_rest", "Enjoy the rest"), session=False),
                  has_plan=True, goal={"title": "x"}, tomorrow=tomorrow)
    assert rest["kind"] == "rest" and rest["tomorrow"]["title"] == "Long run"
    adj = choose(card=card(tone="plan", headline="rabbt suggests adjusting your week",
                           action=("review_adjust", "Review changes"), session=False), has_plan=True, goal=None)
    assert adj["kind"] == "today" and adj["primary"]["kind"] == "review_adjust"
    done = choose(card=card(tone="done", headline="Done for today. Nice work", action=("ask", "How did it go?")),
                  has_plan=True, goal=None, tomorrow=tomorrow)
    assert done["kind"] == "today" and done["tomorrow"] is not None and done["session"] is None


def test_no_plan_goal_group_then_set_goal() -> None:
    free = card(tone="easy", headline="Active recovery day", action=("build_plan", "Build a plan"), session=False)
    assert choose(card=free, has_plan=False, goal={"title": "Denver Half"})["primary"]["kind"] == "build_plan"
    g = {"name": "Wash Park Runners", "when": "Tonight 18:00", "where": "Boathouse", "source": "directory"}
    run_ = choose(card=free, has_plan=False, goal=None, group=g)
    assert run_["kind"] == "group_run" and run_["primary"] == {"kind": "group", "label": "Find a group run tonight"}
    assert run_["detail"] == "Tonight 18:00 · Boathouse"
    assert choose(card=None, has_plan=False, goal=None)["kind"] == "set_goal"
    assert choose(card=free, has_plan=False, goal=None)["kind"] == "set_goal"


def test_pick_group_prefers_rsvped_meetup_then_directory() -> None:
    meetups = [{"id": "m1", "title": "Tempo Tuesday", "next": "2026-10-15T18:30", "where": "Track",
                "my_rsvp": None, "club": {"id": "c1", "name": "Run Crew"}},
               {"id": "m2", "title": "Hill reps", "next": "2026-10-15T06:00", "where": "Hill",
                "my_rsvp": "going", "club": {"id": "c1", "name": "Run Crew"}},
               {"id": "m3", "title": "Too far", "next": "2026-10-20T06:00", "my_rsvp": "going", "club": {}}]
    listings = [{"id": "l1", "name": "Ride", "kind": "ride", "next": {"in_days": 0, "time": "18:00"}},
                {"id": "l2", "name": "Wash Park Runners", "kind": "run_club", "next": {"in_days": 0, "time": "18:00"},
                 "meet_spot": "Boathouse", "join_url": "https://x.org"},
                {"id": "l3", "name": "Trail Tribe", "kind": "trail", "next": {"in_days": 1, "time": "07:00"}}]
    g = pick_group(meetups, listings, NOON)
    assert g["source"] == "club" and g["meetup_id"] == "m2" and g["when"] == "Tomorrow 06:00" and g["club_id"] == "c1"
    d = pick_group([], listings, NOON)
    assert d["source"] == "directory" and d["listing_id"] == "l2" and d["when"] == "Tonight 18:00"
    assert d["where"] == "Boathouse" and d["url"] == "https://x.org"
    assert pick_group([], [listings[0]], NOON) is None  # rides aren't runs
    assert pick_group(meetups[2:], [], NOON) is None    # beyond tomorrow


def test_first_visit_and_no_garmin_shapes() -> None:
    fv = first_visit(garmin=False, inviter="Alex")
    assert fv["show"] and fv["inviter"] == "Alex" and "Alex" in fv["title"]
    assert [i["id"] for i in fv["items"]] == ["clubs", "events", "feed", "friends"]
    assert fv["primary"]["kind"] == "connect_garmin"
    assert first_visit(garmin=True, inviter=None) | {"primary": None} == {
        "show": False, "garmin": True, "inviter": None, "title": "Welcome to rabbt", "items": [], "primary": None}
    assert NO_GARMIN["code"] == "garmin_not_connected" and NO_GARMIN["action"]["kind"] == "connect_garmin"


# ---------------------------------------------------------- auto-follow --
@pytest.fixture
def soc(tmp_path, fernet_key):
    allow = {"ann@x.com": "ann", "u@x.com": "u_new", "cat@x.com": "cat"}
    return SimpleNamespace(s=Social(AppStore(tmp_path / "app", fernet_key), athletes=lambda: allow), allow=allow)


def test_connect_invited_is_mutual(soc) -> None:
    s = soc.s
    s.follow("u_new", email="ann@x.com")  # an earlier pending request becomes active, no duplicate
    assert s.connect_invited("ann", "u_new") is True
    assert s.follows("ann", "u_new") and s.follows("u_new", "ann")
    edges = [e for e in s._doc.load()["edges"].values() if {e["follower"], e["followee"]} == {"ann", "u_new"}]
    assert len(edges) == 2 and all(e["via"] == "invite" and e["status"] == "active" for e in edges)
    assert s.ever_followed("ann") and s.ever_followed("u_new")
    assert s.connect_invited("ann", "u_new") is True  # idempotent
    assert len([e for e in s._doc.load()["edges"].values() if {e["follower"], e["followee"]} == {"ann", "u_new"}]) == 2


def test_connect_invited_respects_blocks(soc) -> None:
    s = soc.s
    s.block("ann", "u_new")
    assert s.connect_invited("ann", "u_new") is False
    assert not s.follows("ann", "u_new") and not s.follows("u_new", "ann")
    s.unblock("ann", "u_new")
    s.block("u_new", "ann")  # the other way round too
    assert s.connect_invited("ann", "u_new") is False and not s.follows("ann", "u_new")


def test_connect_invited_leaves_coaches_alone(soc) -> None:
    s = soc.s
    coach = coach_user_id("coach@x.com")
    soc.allow["coach@x.com"] = coach
    assert s.connect_invited(coach, "u_new") is False
    assert s.connect_invited("u_new", coach) is False
    assert s.connect_invited("ann", "ann") is False and s.connect_invited("", "u_new") is False
    assert s.connect_invited("ann", "nobody") is False  # not an athlete (yet)
    assert not (s._doc.load().get("edges") or {})


def test_friend_joined_moment_posts_once(env) -> None:
    agent, _ = env.agent([])
    m = friend_joined_moment("Sam Lee", "u_1")
    assert m["text"].startswith("🎉 Sam Lee joined rabbt") and len(m["text"]) <= 140
    assert m["actions"] == [{"id": "community", "label": "See friends", "view": "people"}]
    agent.moments._now = lambda uid: NOON
    assert agent.moments.friend_joined("friend", "Sam", "u_1") == "posted"
    assert agent.moments.friend_joined("friend", "Sam", "u_1") == "duplicate"
    agent.moments._now = lambda uid: NOON.replace(hour=22)
    assert agent.moments.friend_joined("friend", "Kim", "u_2") == "queued"  # quiet hours
    assert agent.moments.friend_joined(coach_user_id("c@x.com"), "Sam", "u_3") == "skipped"


# ------------------------------------------------------------------ http --
class Harness:
    """Passkey join through the real app, with the chat agent (social, moments) wired in."""

    def __init__(self, env, tmp_path) -> None:
        self.settings = Settings(
            public_base_url=BASE, data_dir=tmp_path, app_enabled=True, google_client_id="g-client",
            allowed_google_users=_parse_email_map(["friend@example.com:friend", "andrew@example.com:andrew"]))
        self.google = Google()
        self.agent, _ = env.agent([])
        self.auth = WebAuth(self.settings, env.store, "g-secret", http=self.google.client())
        routes = build_app_routes(self.settings, self.auth, env.tokens, None, None, ChatRunner(self.agent))
        self.app = build_app(self.settings, env.service, None, None, routes)

    def client(self, host: str = HOST):
        import httpx2
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url=BASE,
                                  headers={"host": host})


@pytest.fixture
def hh(env, tmp_path) -> Harness:
    return Harness(env, tmp_path)


@run
async def test_invite_join_auto_follows_and_first_visit(hh: Harness) -> None:
    async with hh.client() as owner:
        await sign_in(hh, owner)  # "friend" (Garmin connected in the env fixture)
        token = await make_invite(owner)
        c, v = await join(hh, token, Authenticator(), name="Sam Lee")
        assert v.status_code == 200, v.text
        uid = (await c.get("/app/api/me")).json()["user_id"]
        # The invite use records the inviter.
        uses = next(iter(hh.auth.access._invites.load().values()))["uses"]
        assert uses[0]["user_id"] == uid and uses[0]["inviter"] == "friend"
        # Mutual follow, both ways.
        mine = (await c.get("/app/api/social")).json()
        theirs = (await owner.get("/app/api/social")).json()
        assert [p["user_id"] for p in mine["following"]] == ["friend"]
        assert [p["user_id"] for p in mine["followers"]] == ["friend"]
        assert [p["user_id"] for p in theirs["following"]] == [uid]
        # The inviter's Rabbit moment (posted now or queued for 07:00: either way it's recorded once).
        keys = hh.agent._store.user_doc("friend", "moments").load().get("keys") or {}
        assert f"joined:{uid}" in keys
        # First visit without Garmin: welcome card + friendly empty states, not errors.
        fv = (await c.get("/app/api/firstvisit")).json()
        assert fv["show"] and fv["inviter"] == "Friend" and fv["primary"]["kind"] == "connect_garmin"
        for path in ("/app/api/stats", "/app/api/load"):
            r = await c.get(path)
            assert r.status_code == 409 and r.json()["code"] == "garmin_not_connected", path
        up = (await c.get("/app/api/upnext")).json()
        assert up["garmin"] is False and up["kind"] == "set_goal" and up["primary"]["kind"] == "set_goal"
        wd = (await c.get("/app/api/workout/today")).json()
        assert wd["garmin_connected"] is False and wd["state"] == "free"
        today = (await c.get("/app/api/today")).json()
        assert today["garmin"] is False
        # The inviter has Garmin: no welcome card, stats work.
        assert (await owner.get("/app/api/firstvisit")).json()["show"] is False
        assert (await owner.get("/app/api/stats")).status_code == 200
        assert (await owner.get("/app/api/upnext")).json()["garmin"] is True
