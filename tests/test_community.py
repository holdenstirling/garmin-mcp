"""Community: milestone drafts + consent, audiences, reactions/comments (threaded), photos,
rate limits, hide/report/block, clubs (join/approve/leave/admin), meetups + RSVP + reminders,
club challenges, feed pagination, push coalescing, coach 403, no health data in posts."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import challenges as chm
from garmin_mcp import community as cmod
from garmin_mcp.appstore import AppStore
from garmin_mcp.clubs import ClubError, Clubs, next_occurrence
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.coaching import CoachStore
from garmin_mcp.community import (
    Community,
    CommunityError,
    event_class,
    image_size,
    workout_card,
)
from garmin_mcp.config import Settings
from garmin_mcp.moments import Moments, streak_milestone
from garmin_mcp.social import Social
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_challenges import history
from tests.test_social import BASE, FakePush, H, act

TZ = ZoneInfo("America/Denver")
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat", "dan@x.com": "dan"}


def jpeg(w: int = 800, h: int = 600, pad: int = 64) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\x00" * pad


def _follow(s: Social, a: str, b: str) -> None:
    """a follows b (accepted)."""
    s.follow(a, email=f"{b}@x.com")
    edge = next(e for e in s.people(b)["pending_in"] if e["user_id"] == a)
    s.accept(b, edge["edge_id"])


@pytest.fixture
def cx(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    clock = SimpleNamespace(t=1_800_000_000.0, at=NOON, quiet=False)
    soc = Social(store, athletes=lambda: dict(ALLOW), clock=lambda: clock.t)
    races: dict[str, list] = {}
    grp = Clubs(store, is_athlete=soc.is_athlete, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                blocked=soc.blocked_between, race_groups=lambda u: races.get(u, []), clock=lambda: clock.t)
    moments: list[tuple] = []
    pushes: list[tuple] = []
    cm = Community(store, social=soc, clubs=grp, now=lambda u: clock.at, clock=lambda: clock.t,
                   moment=lambda u, m: moments.append((u, m)), push=lambda to, t, b: pushes.append((to, t, b)),
                   quiet=lambda u: clock.quiet, name=lambda u: u.title())
    _follow(soc, "bob", "ann")  # bob follows ann
    return SimpleNamespace(store=store, clock=clock, soc=soc, grp=grp, cm=cm, races=races, moments=moments,
                           pushes=pushes)


def ids(feed: dict) -> list[str]:
    return [p["id"] for p in feed["items"]]


# ------------------------------------------------------------ milestones --
def test_milestone_drafts_need_consent_and_auto_share(cx) -> None:
    cm = cx.cm
    out = cm.milestone("ann", "pb", "pb:longest_run_km:1", "New personal best: longest run this year, 21.1 km.")
    d = out["draft"]
    assert cm.feed("bob")["items"] == [] and cm.feed("ann")["items"] == []  # nothing posted without consent
    assert [x["id"] for x in cm.drafts("ann")] == [d["id"]]
    u, m = cx.moments[-1]
    assert u == "ann" and m["type"] == "milestone" and "Share it with your people?" in m["text"] and len(m["text"]) <= 140
    assert [a["id"] for a in m["actions"]] == ["community_share", "community_later"]
    assert cm.milestone("ann", "pb", "pb:longest_run_km:1", "again") is None  # deduped
    post = cm.share("ann", d["id"], {"feeling": "💪"})
    assert post["milestone"]["type"] == "pb" and post["category"] == "pb" and post["feeling"] == "💪"
    assert ids(cm.feed("bob")) == [post["id"]] and cm.drafts("ann") == []
    with pytest.raises(CommunityError):
        cm.share("ann", d["id"])  # already shared
    # Not now: dismissed, never posted.
    d2 = cm.milestone("ann", "level", "level:7", "Reached level 7")["draft"]
    cm.dismiss("ann", d2["id"])
    assert cm.drafts("ann") == [] and len(cm.feed("bob")["items"]) == 1
    # Auto-share per type; types can be off.
    cm.put_settings("ann", {"auto_share": {"race": True}, "milestones": {"streak": False}})
    s = cm.settings("ann")
    assert s["auto_share"]["race"] and not s["auto_share"]["pb"] and not s["milestones"]["streak"]
    got = cm.milestone("ann", "race", "race:e1", "Finished Leadville!")
    assert "post" in got and "Shared in Community." in cx.moments[-1][1]["text"]
    assert cm.milestone("ann", "streak", "streak:7", "7-day streak") is None
    with pytest.raises(CommunityError):
        cm.put_settings("ann", {"auto_share": {"nope": True}})
    assert cm.milestone("coach_x", "race", "race:z", "x") is None


def test_moments_hook_turns_milestone_moments_into_drafts(cx) -> None:
    coach = CoachStore(cx.store, clock=lambda: cx.clock.t)
    m = Moments(cx.store, coach, now=lambda u: NOON, clock=lambda: cx.clock.t)
    m.on_milestone = cx.cm.from_moment
    assert m.post("ann", streak_milestone(7)) == "posted"
    turn = [t for t in coach.turns("ann", coach.coach_thread("ann")["id"]) if t["kind"] == "moment"][-1]
    acts = [a["id"] for a in turn["parts"][0]["actions"]]
    assert acts == ["progress", "community_share", "community_later"]
    (d,) = cx.cm.drafts("ann")
    assert d["type"] == "streak" and d["text"].startswith("7-day streak")
    assert m.post("ann", streak_milestone(7)) == "duplicate" and len(cx.cm.drafts("ann")) == 1
    # A failing hook never blocks the moment.
    m.on_milestone = lambda u, mm: 1 / 0
    assert m.post("ann", streak_milestone(14)) == "posted"


def test_scan_events_race_finished_and_firsts(cx) -> None:
    today = NOON.date()
    evs = [{"id": "e1", "name": "Leadville 100", "type": "trail", "distance": "ultra", "date": (today - timedelta(days=1)).isoformat(),
            "result": "27:41:02", "notes": "private", "debrief": {"learnings": ["x"]}},
           {"id": "e2", "name": "Boulder 70.3", "type": "triathlon", "distance": "70.3", "date": (today - timedelta(days=2)).isoformat()},
           {"id": "e3", "name": "Future", "type": "running", "distance": "marathon", "date": (today + timedelta(days=9)).isoformat()}]
    acts = [act(today - timedelta(days=2), 77, sport="cycling")]
    assert cx.cm.scan_events("ann", evs, today, acts) == 4  # 2 races + first ultra + first 70.3
    drafts = {d["key"]: d for d in cx.cm.drafts("ann")}
    assert set(drafts) == {"race:e1", "race:e2", "first:ultra", "first:70.3"}
    assert drafts["race:e1"]["text"] == "Finished Leadville 100! 27:41:02."
    assert drafts["race:e1"]["event"] == {"id": "e1", "name": "Leadville 100", "date": evs[0]["date"], "type": "trail",
                                          "distance": "ultra"}  # no notes/debrief
    assert cx.cm.scan_events("ann", evs, today, acts) == 0
    assert event_class({"distance": "century ride"}) == "century" and event_class({"distance": "5k"}) is None
    assert event_class({"type": "running", "distance": "50K"}) == "ultra"


def test_scan_bests(cx) -> None:
    today = NOON.date()
    acts = [act(today - timedelta(days=20), 1, km=10), act(today, 2, km=21.1)]
    assert cx.cm.scan_bests("ann", acts, today, imperial=False) == 1
    (d,) = cx.cm.drafts("ann")
    assert d["type"] == "pb" and "21.1 km" in d["text"]
    assert cx.cm.scan_bests("ann", acts, today, imperial=False) == 0


# ------------------------------------------------------------- audiences --
def test_audiences_friends_club_public_private_and_blocked(cx) -> None:
    cm, soc, grp = cx.cm, cx.soc, cx.grp
    pub = cm.create("ann", {"text": "Engaged!", "category": "life"})
    assert pub["audience"] == "friends"
    cx.clock.t += 1
    journal = cm.create("ann", {"text": "Rough day", "category": "other", "audience": "private"})
    g = grp.create("ann", {"name": "Dawn patrol", "emoji": "🌅", "sport": "running", "city": "Denver", "state": "CO"})
    grp.join("cat", g["id"])  # open club
    cx.clock.t += 1
    gpost = cm.create("ann", {"text": "Group run Sat", "category": "other", "audience": f"club:{g['id']}"})
    with pytest.raises(CommunityError):
        cm.create("bob", {"text": "x", "audience": f"club:{g['id']}"})  # not a member
    with pytest.raises(CommunityError):
        cm.create("bob", {"text": "x", "audience": "everyone"})
    assert ids(cm.feed("ann")) == [gpost["id"], journal["id"], pub["id"]]
    assert ids(cm.feed("bob")) == [pub["id"]]  # friend: no journal, no club post
    assert ids(cm.feed("cat")) == [gpost["id"]]  # club member, not a follower
    assert ids(cm.feed("cat", club=g["id"])) == [gpost["id"]]
    assert ids(cm.feed("dan")) == []
    for who, pid in (("dan", pub["id"]), ("bob", journal["id"]), ("bob", gpost["id"])):
        with pytest.raises(CommunityError) as e:
            cm.get(who, pid)
        assert e.value.status == 404
    with pytest.raises(CommunityError):
        cm.feed("bob", club=g["id"])
    # Public: every athlete on Rabbit, not only friends; the "friends" scope leaves it out
    # unless they follow the author.
    cx.clock.t += 1
    everyone = cm.create("dan", {"text": "Ran my first 5K!", "category": "pb", "audience": "public"})
    assert ids(cm.feed("cat"))[0] == everyone["id"] and everyone["id"] in ids(cm.feed("bob"))
    assert everyone["id"] not in ids(cm.feed("bob", scope="friends"))
    assert cm.related("bob", "dan")  # public posters' photos show
    cm.update("dan", everyone["id"], {"audience": "private"})
    assert everyone["id"] not in ids(cm.feed("cat"))
    # Blocking: no view, no comment, either direction, public posts too.
    cm.update("dan", everyone["id"], {"audience": "public"})
    soc.block("dan", "cat")
    assert everyone["id"] not in ids(cm.feed("cat"))
    with pytest.raises(CommunityError):
        cm.react("cat", everyone["id"], "party")
    soc.block("ann", "bob")
    _follow(soc, "dan", "ann")
    assert pub["id"] not in ids(cm.feed("bob")) and pub["id"] in ids(cm.feed("dan"))
    with pytest.raises(CommunityError):
        cm.comment("bob", pub["id"], "hi")
    with pytest.raises(CommunityError):
        cm.create("coach_x", {"text": "x"})
    # Older names still work.
    assert cm.create("ann", {"text": "old", "visibility": "followers"})["audience"] == "friends"


def test_reactions_comments_threads_permissions_and_limits(cx, monkeypatch) -> None:
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    p = cm.create("ann", {"text": "First ultra done", "category": "race"})
    v = cm.react("bob", p["id"], "party")
    assert v["reactions"]["party"] == 1 and v["my_reaction"] == "party"
    v = cm.react("bob", p["id"], "rabbit")  # switch, still one
    assert v["reactions"] == {"party": 0, "strong": 0, "heart": 0, "rabbit": 1} and v["reaction_total"] == 1
    with pytest.raises(CommunityError):
        cm.react("bob", p["id"], "poop")
    with pytest.raises(CommunityError):
        cm.react("dan", p["id"], "heart")  # can't see it
    assert cm.unreact("bob", p["id"])["reaction_total"] == 0
    c = cm.comment("bob", p["id"], "  Huge!  ")
    assert c["text"] == "Huge!" and c["parent"] is None
    with pytest.raises(CommunityError):
        cm.comment("bob", p["id"], "x" * 281)
    with pytest.raises(CommunityError):
        cm.comment("bob", p["id"], "   ")
    # Threads are one level deep: a reply to a reply joins the same thread.
    r1 = cm.comment("ann", p["id"], "Thanks!", reply_to=c["id"])
    assert cx.pushes[-1][:2] == ("bob", "Ann replied")  # the parent's author hears about replies
    r2 = cm.comment("cat", p["id"], "Same!", reply_to=r1["id"])
    assert r1["parent"] == c["id"] and r2["parent"] == c["id"]
    with pytest.raises(CommunityError):
        cm.comment("cat", p["id"], "x", reply_to="cnope")
    with pytest.raises(CommunityError):
        cm.delete_comment("cat", p["id"], c["id"])  # not yours, not your post
    cm.delete_comment("ann", p["id"], c["id"])  # owner deletes any comment, replies go with it
    full = cm.get("ann", p["id"])
    assert full["comments"] == [] and full["comment_count"] == 0
    c2 = cm.comment("bob", p["id"], "again")
    monkeypatch.setattr(cmod, "MAX_COMMENTS", 2)
    cm.comment("bob", p["id"], "two")
    with pytest.raises(CommunityError):
        cm.comment("bob", p["id"], "three")
    # Blocked commenters disappear for the blocker.
    cx.soc.block("ann", "bob")
    assert all(x["by"] != "bob" for x in cm.get("ann", p["id"])["comments"])
    cx.soc.unblock("ann", "bob")
    _follow(cx.soc, "bob", "ann")
    assert c2["id"] in [x["id"] for x in cm.get("ann", p["id"])["comments"]]
    # Hide: gone for me only. Report: hidden + logged for the operator.
    with pytest.raises(CommunityError):
        cm.hide("ann", p["id"])
    cm.hide("cat", p["id"])
    assert p["id"] not in ids(cm.feed("cat")) and p["id"] in ids(cm.feed("bob"))
    with pytest.raises(CommunityError):
        cm.report("ann", p["id"])
    cm.report("bob", p["id"], "spam")
    assert cm.feed("bob")["items"] == []
    assert cx.store.global_doc("community").load()["reports"][-1]["post"] == p["id"]
    # Edit/delete own posts only.
    with pytest.raises(CommunityError):
        cm.update("bob", p["id"], {"text": "hacked"})
    assert cm.update("ann", p["id"], {"text": "First ultra!"})["edited"]
    with pytest.raises(CommunityError):
        cm.delete("bob", p["id"])
    cm.delete("ann", p["id"])
    with pytest.raises(CommunityError):
        cm.get("ann", p["id"])


def test_rate_limits(cx, monkeypatch) -> None:
    cm = cx.cm
    monkeypatch.setattr(cmod, "POSTS_PER_DAY", 2)
    monkeypatch.setattr(cmod, "COMMENTS_PER_DAY", 2)
    p = cm.create("ann", {"text": "one"})
    cm.create("ann", {"text": "two"})
    with pytest.raises(CommunityError) as e:
        cm.create("ann", {"text": "three"})
    assert e.value.status == 429
    assert cm.milestone("ann", "race", "race:x", "Finished!", announce=False) is not None  # drafts aren't posts
    cm.put_settings("ann", {"auto_share": {"pb": True}})
    assert "post" in cm.milestone("ann", "pb", "pb:x", "PB", announce=False)  # auto-share isn't limited
    cm.comment("bob", p["id"], "a")
    cm.comment("bob", p["id"], "b")
    with pytest.raises(CommunityError) as e:
        cm.comment("bob", p["id"], "c")
    assert e.value.status == 429
    cx.clock.at = NOON + timedelta(days=1)  # a new local day
    cm.create("ann", {"text": "next day"})
    cm.comment("bob", p["id"], "next day")


def test_push_coalescing_and_quiet_hours(cx) -> None:
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    p = cm.create("ann", {"text": "PR!", "category": "pb"})
    cm.react("bob", p["id"], "party")
    cm.react("cat", p["id"], "heart")
    cm.comment("bob", p["id"], "Wow")
    assert [x[0] for x in cx.pushes] == ["ann"]  # one per post per hour
    cm.comment("ann", p["id"], "ty")  # own comment: never a push
    cx.clock.t += 3601
    cx.clock.quiet = True
    cm.comment("cat", p["id"], "late")
    assert len(cx.pushes) == 1  # quiet hours
    cx.clock.quiet = False
    cm.comment("cat", p["id"], "morning")
    assert len(cx.pushes) == 2 and cx.pushes[-1][1] == "Cat commented"


def test_feed_pagination(cx) -> None:
    for i in range(25):
        cx.clock.t += 10
        cx.cm.create("ann", {"text": f"post {i}", "category": "other"}, limited=False)
    page = cx.cm.feed("bob")
    assert len(page["items"]) == 20 and page["next"]
    assert page["items"][0]["text"] == "post 24"
    rest = cx.cm.feed("bob", page["next"])
    assert [p["text"] for p in rest["items"]] == [f"post {i}" for i in range(4, -1, -1)] and rest["next"] is None
    with pytest.raises(CommunityError):
        cx.cm.feed("bob", "garbage")


# ---------------------------------------------------------------- photos --
def test_photo_validation_quota_and_audience(cx, monkeypatch) -> None:
    cm = cx.cm
    assert image_size(jpeg(1200, 900)) == (1200, 900)
    webp = b"RIFF" + (30).to_bytes(4, "little") + b"WEBPVP8X" + b"\x00" * 8 + (1599).to_bytes(3, "little") + (99).to_bytes(3, "little")
    assert image_size(webp) == (1600, 100)
    for bad, why in ((b"", "empty"), (b"GIF89a" + b"\x00" * 40, "JPEG or WebP"),
                     (jpeg(2000, 1000), "max 1600"), (b"\xff\xd8\xff" + b"\x00" * 40, "couldn't read"),
                     (jpeg(pad=cmod.PHOTO_MAX), "too large")):
        with pytest.raises(CommunityError) as e:
            cm.save_photo("ann", bad)
        assert why in e.value.message, why
    phs = [cm.save_photo("ann", jpeg(800, 600 + i))["photo_id"] for i in range(5)]
    with pytest.raises(CommunityError):
        cm.create("bob", {"text": "steal", "photo_ids": phs[:1]})  # not bob's photo
    with pytest.raises(CommunityError):
        cm.create("ann", {"text": "too many", "photo_ids": phs})  # at most 4
    post = cm.create("ann", {"text": "", "category": "life", "photo_ids": phs[:2]})
    assert len(post["photos"]) == 2
    mime, data = cm.photo("bob", post["id"], 1)
    assert mime == "image/jpeg" and data == jpeg(800, 601)
    assert cm.photo("bob", post["id"], 2) is None
    with pytest.raises(CommunityError):
        cm.photo("cat", post["id"])  # not in the audience
    with pytest.raises(CommunityError):
        cm.create("ann", {"text": "again", "photo_ids": [phs[0]]})  # already attached
    # Edit: keep one, add one; the dropped one is freed.
    assert len(cm.update("ann", post["id"], {"photo_ids": [phs[1], phs[2]]})["photos"]) == 2
    assert cm.usage("ann")["photos"] == 4
    monkeypatch.setattr(cmod, "PHOTO_QUOTA_COUNT", 5)
    cm.save_photo("ann", jpeg())
    with pytest.raises(CommunityError) as e:
        cm.save_photo("ann", jpeg())
    assert e.value.status == 413
    cm.delete("ann", post["id"])  # frees its photos
    assert cm.usage("ann")["photos"] == 3
    with pytest.raises(CommunityError):
        cm.save_photo("coach_x", jpeg())


# ---------------------------------------------------------- health data --
def test_no_health_data_in_posts(cx) -> None:
    today = NOON.date()
    acts = [act(today - timedelta(days=30), 1, km=5), act(today, 2, km=12)]
    acts[1].update(avg_power_w=230, sleep_score=80, lat=39.7, lon=-105.0)
    card = workout_card(acts, 2, today)
    assert set(card) == {"activity_id", "source", "sport", "title", "date", "km", "minutes", "climb_m", "highlight",
                         "pace_s_km"}  # pace from distance + time only
    assert card["highlight"] == "New longest run this year!"
    post = cx.cm.create("ann", {"text": "Long one", "avg_hr": 150, "hrv": 70, "readiness": 80}, workout={**card, "avg_hr": 151})
    blob = json.dumps(cx.cm.get("bob", post["id"]))
    for k in ("avg_hr", "max_hr", "hrv", "readiness", "sleep", "power", "lat", "oura"):
        assert k not in blob, k
    assert post["kind"] == "workout" and post["workout"]["km"] == 12


# ----------------------------------------------------------------- clubs --
def test_clubs_join_approve_leave_admin_and_race_groups(cx, monkeypatch) -> None:
    grp, soc = cx.grp, cx.soc
    for bad in ({"name": ""}, {"name": "x" * 41}, {"name": "ok", "description": "d" * 301},
                {"name": "ok", "emoji": "abc"}, {"name": "ok", "sport": "darts"}, {"name": "ok", "privacy": "secret"}):
        with pytest.raises(ClubError):
            grp.create("ann", bad)
    with pytest.raises(ClubError) as e:
        grp.create("coach_x", {"name": "ok"})
    assert e.value.status == 403
    g = grp.create("ann", {"name": "Trail crew", "sport": "trail", "city": "Denver", "state": "CO",
                           "description": "Saturday long runs", "emoji": "⛰️", "privacy": "approval"})
    assert g["role"] == "owner" and g["privacy"] == "approval" and g["code"]
    # Discover near you: same city first, then same state; never one I'm in.
    o = grp.create("cat", {"name": "Boulder Roadies", "sport": "cycling", "city": "Boulder", "state": "CO"})
    disc = grp.discover("dan", city="denver", state="CO")
    assert [(x["id"], x["near"]) for x in disc] == [(g["id"], "city"), (o["id"], "state")]
    assert "code" not in disc[0] and grp.discover("dan", city="Austin", state="TX") == []
    assert [x["id"] for x in grp.discover("dan", q="roadies")] == [o["id"]]
    # Approval club: a request, then an admin approves or declines.
    v = grp.join("dan", g["id"])
    assert v["requested"] and v["role"] is None and not grp.is_member(g["id"], "dan")
    assert grp.get("dan", g["id"])["people"] == []  # a non-member sees the card only
    assert grp.get("ann", g["id"])["pending"] == ["dan"]
    with pytest.raises(ClubError):
        grp.decide("dan", g["id"], "dan", True)
    grp.decide("ann", g["id"], "dan", True)
    assert grp.is_member(g["id"], "dan") and grp.get("ann", g["id"])["pending"] == []
    grp.join("bob", g["id"])
    grp.decide("ann", g["id"], "bob", False)
    assert not grp.is_member(g["id"], "bob")
    # Open club: straight in. Code: skips approval.
    grp.join("ann", o["id"])
    grp.join("bob", code=g["code"].lower())
    assert grp.is_member(g["id"], "bob")
    # Invites need a follow edge; members of an approval club can't invite.
    with pytest.raises(ClubError):
        grp.invite("ann", g["id"], "cat")
    _follow(soc, "cat", "ann")
    assert grp.invite("ann", g["id"], "cat")["notify"] == "cat"
    assert grp.invite("ann", g["id"], "cat")["notify"] is None
    assert [x["id"] for x in grp.overview("cat")["invites"]] == [g["id"]]
    with pytest.raises(ClubError):
        grp.invite("bob", g["id"], "ann")
    grp.respond("cat", g["id"], True)
    # Admin roles: owner promotes; admins edit and approve but can't remove admins/owner.
    with pytest.raises(ClubError):
        grp.update("bob", g["id"], {"name": "Mine now"})
    grp.set_role("ann", g["id"], "bob", "admin")
    assert grp.update("bob", g["id"], {"name": "Trail crew 2"})["name"] == "Trail crew 2"
    with pytest.raises(ClubError):
        grp.set_role("bob", g["id"], "cat", "admin")
    with pytest.raises(ClubError):
        grp.remove("bob", g["id"], "ann")
    with pytest.raises(ClubError):
        grp.delete("bob", g["id"])
    grp.remove("bob", g["id"], "cat")
    assert not grp.is_member(g["id"], "cat")
    # Blocked people vanish from member lists.
    soc.block("dan", "bob")
    assert "bob" not in [p["user_id"] for p in grp.get("dan", g["id"])["people"]]
    # Owner leaves: an admin takes over; last one out deletes it.
    grp.leave("ann", g["id"])
    assert grp.get("bob", g["id"])["role"] == "owner"
    grp.leave("dan", g["id"])
    grp.leave("bob", g["id"])
    with pytest.raises(ClubError):
        grp.get("bob", g["id"])
    monkeypatch.setattr("garmin_mcp.clubs.MAX_MEMBERS", 2)
    with pytest.raises(ClubError):
        grp.join("dan", o["id"])
    monkeypatch.setattr("garmin_mcp.clubs.MAX_CLUBS", 1)
    with pytest.raises(ClubError):
        grp.create("cat", {"name": "Third"})
    # Race groups from racepeople show up automatically and carry club posts.
    cx.races["ann"] = [{"id": "rg1", "members": ["ann", "dan"], "name": "Leadville 100", "date": "2027-08-21", "event_id": "e1"}]
    cx.races["dan"] = [{"id": "rg1", "members": ["ann", "dan"], "name": "Leadville 100", "date": "2027-08-21", "event_id": "e9"}]
    assert grp.overview("ann")["clubs"][0]["name"] == "Leadville 100 · 2027"
    post = cx.cm.create("ann", {"text": "See you at the start", "audience": "club:r-rg1"})
    assert post["club"]["name"] == "Leadville 100 · 2027"
    assert ids(cx.cm.feed("dan")) == [post["id"]]
    with pytest.raises(ClubError):
        grp.leave("ann", "r-rg1")
    ups = grp.upcoming("dan", "r-rg1", events=lambda u: [{"id": "e1", "name": "Leadville 100", "date": "2027-08-21"}]
                       if u == "ann" else [{"id": "e9", "name": "Leadville 100", "date": "2027-08-21"}],
                       shares_races=lambda u: False, today=date(2027, 6, 1))
    assert len(ups) == 1 and sorted(ups[0]["user_ids"]) == ["ann", "dan"]
    # Suggestions: club mates and followers I don't follow back; never blocked.
    sug = {s["user_id"]: s["reason"] for s in cx.cm.suggestions("ann")}
    assert sug["dan"] == "In Leadville 100 · 2027" and sug["bob"] == "Follows you"
    soc.block("ann", "dan")
    assert "dan" not in {s["user_id"] for s in cx.cm.suggestions("ann")}


def test_meetups_rsvp_and_reminders(cx) -> None:
    grp, cm = cx.grp, cx.cm
    now = NOON  # Wed 2026-10-14 12:00
    g = grp.create("ann", {"name": "Dawn patrol", "city": "Denver", "state": "CO"})
    grp.join("bob", g["id"])
    m = {"title": "Saturday long run", "start": "2026-10-17T07:00", "repeat": "weekly", "where": "Wash Park boathouse",
         "pace": "9:30/mi", "level": "easy"}
    with pytest.raises(ClubError):
        grp.add_meetup("bob", g["id"], m, now)  # members don't plan meetups
    for bad in ({**m, "start": "Saturday"}, {**m, "where": ""}, {**m, "level": "elite"}, {**m, "repeat": "daily"},
                {**m, "start": "2026-10-01T07:00"}):
        with pytest.raises(ClubError):
            grp.add_meetup("ann", g["id"], bad, now)
    mt = grp.add_meetup("ann", g["id"], m, now)
    assert mt["next"] == "2026-10-17T07:00" and mt["going"] == []
    v = grp.rsvp("bob", g["id"], mt["id"], "going", now)
    assert v["going"] == ["bob"] and v["my_rsvp"] == "going"
    assert grp.rsvp("ann", g["id"], mt["id"], "maybe", now)["maybe"] == 1
    with pytest.raises(ClubError):
        grp.rsvp("cat", g["id"], mt["id"], "going", now)  # not a member
    with pytest.raises(ClubError):
        grp.rsvp("bob", g["id"], mt["id"], "yes", now)
    assert [x["id"] for x in grp.my_meetups("bob", now)] == [mt["id"]]
    # Reminder: a Rabbit moment within 18 hours of the start, once.
    assert cm.meetup_reminders("bob") == 0  # Wednesday: too early
    cx.clock.at = datetime(2026, 10, 16, 18, 0, tzinfo=TZ)
    cx.clock.t += 700
    assert cm.meetup_reminders("bob") == 1
    u, mo = cx.moments[-1]
    assert u == "bob" and mo["type"] == "meetup" and mo["text"].startswith("📍 Tomorrow 7:00: Saturday long run")
    assert cm.meetup_reminders("bob") == 0  # throttled
    assert cm.meetup_reminders("ann") == 0  # maybe: no reminder
    # Weekly: after this Saturday, the next one, with fresh RSVPs.
    later = datetime(2026, 10, 17, 10, 0, tzinfo=TZ)
    nxt = grp.meetups("bob", g["id"], later)[0]
    assert nxt["next"] == "2026-10-24T07:00" and nxt["going"] == [] and nxt["my_rsvp"] is None
    assert next_occurrence({"start": "2026-10-17T07:00"}, later.replace(tzinfo=None)) is None
    # Cancel: admins or the planner; going/maybe people are returned to tell them.
    grp.rsvp("bob", g["id"], mt["id"], "going", later)
    with pytest.raises(ClubError):
        grp.delete_meetup("bob", g["id"], mt["id"])
    assert grp.delete_meetup("ann", g["id"], mt["id"]) == ["bob"]
    assert grp.meetups("bob", g["id"], later) == []


def test_club_challenges(cx) -> None:
    store, soc, grp = cx.store, cx.soc, cx.grp
    now = datetime(2026, 10, 14, 9, 0, tzinfo=TZ)
    chal = chm.Challenges(store, now=lambda u: now, activities=lambda u: (now.date(), history()),
                          athlete=lambda u: {"favorite_sports": ["run"]}, names=lambda u: u.title())
    g = grp.create("ann", {"name": "Crew"})
    grp.join("cat", g["id"])
    sug = chal.get("ann")["periods"]["week"]["suggestions"][0]
    grp.can_start_challenge("ann", g["id"])
    with pytest.raises(ClubError):
        grp.can_start_challenge("cat", g["id"])
    gid = chal.start_club("ann", sug["template"], "week", g["id"], max_people=500)["id"]
    grp.add_challenge("ann", g["id"], gid)
    assert grp.get("cat", g["id"])["challenges"] == [gid]
    (view,) = chal.club_view("cat", [gid], g["id"])
    assert view["participants"] == 1 and not view["joined"] and view["name"] == sug["name"]
    c = chal.join_club("cat", gid, g["id"])  # no invite, no follow edge needed
    assert c["target"] == sug["target"] and c["group"] == gid
    assert chal.club_view("cat", [gid], g["id"])[0]["joined"]
    with pytest.raises(chm.ChallengeError):
        chal.join_club("cat", gid, g["id"])
    with pytest.raises(chm.ChallengeError):
        chal.join_club("bob", gid, "gother")  # another club's id
    assert soc.follows("cat", "ann") is False


# ------------------------------------------------------------------ http --
def _setup(env, tmp_path):
    agent, _ = env.agent([])
    today = agent._now("ann").date()
    acts = {"ann": [act(today - timedelta(days=40), 10, km=5), act(today, 11, km=15)]}
    agent.stats.activities = lambda uid, fresh=False: (today, acts.get(uid, []))
    agent.moments.quiet = lambda local: False  # pushes are asserted; don't depend on the hour the suite runs
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={k: v for k, v in ALLOW.items() if v != "dan"})
    push = FakePush()

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, push, None, ChatRunner(agent)))
    return {u: app(u) for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}, push, agent


def _clients(apps):
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}


def test_http_flow(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        # Photo upload: raw body, origin checked, content checked.
        r = await ann.post("/app/api/community/photos", headers={"origin": "https://evil", "content-type": "image/jpeg"}, content=jpeg())
        assert r.status_code == 403
        r = await ann.post("/app/api/community/photos", headers={"origin": BASE, "content-type": "image/jpeg"}, content=b"GIF89a....")
        assert r.status_code == 400
        ph = (await ann.post("/app/api/community/photos", headers={"origin": BASE, "content-type": "image/jpeg"},
                             content=jpeg())).json()["photo_id"]
        r = await ann.post("/app/api/community/posts", headers=H,
                           json={"text": "Got married! 💍", "category": "life", "feeling": "🥹", "photo_ids": [ph]})
        assert r.status_code == 201
        post = r.json()["post"]
        assert post["user"]["name"] == "Ann" and len(post["photos"]) == 1
        feed = (await bob.get("/app/api/community/feed")).json()
        assert [p["id"] for p in feed["items"]] == [post["id"]] and feed["next"] is None
        r = await bob.get(f"/app/api/community/posts/{post['id']}/photos/0")
        assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
        assert (await cat.get(f"/app/api/community/posts/{post['id']}/photos/0")).status_code == 404
        assert (await cat.get(f"/app/api/community/posts/{post['id']}")).status_code == 404
        # Reactions and comments push once per post per hour.
        r = await bob.post(f"/app/api/community/posts/{post['id']}/reactions", headers=H, json={"kind": "party"})
        assert r.json()["post"]["my_reaction"] == "party"
        r = await bob.post(f"/app/api/community/posts/{post['id']}/comments", headers=H, json={"text": "Congrats!!"})
        assert r.status_code == 201 and r.json()["comment"]["by"]["name"] == "Bob"
        assert [p[0] for p in push.sent].count("ann") == 2  # follow request + one coalesced community push
        full = (await ann.get(f"/app/api/community/posts/{post['id']}")).json()["post"]
        assert full["comments"][0]["can_delete"] and full["comments"][0]["by"]["name"] == "Bob"
        # Share a workout: compact card, no HR.
        r = await ann.post("/app/api/community/posts", headers=H, json={"workout_id": 11, "text": "Long one"})
        w = r.json()["post"]
        assert r.status_code == 201 and w["workout"]["highlight"] and "avg_hr" not in json.dumps(w)
        assert (await ann.post("/app/api/community/posts", headers=H, json={"workout_id": 999})).status_code == 404
        # Drafts: a debrief result makes a race draft; sharing posts it.
        ev = agent.events.create("ann", {"name": "Bolder Boulder", "type": "running", "distance": "10k",
                                         "date": (agent._now("ann").date() - timedelta(days=1)).isoformat()})
        agent.events.update("ann", ev["id"], {"result": "44:10"})
        drafts = (await ann.get("/app/api/community/drafts")).json()["drafts"]
        assert [d["key"] for d in drafts] == [f"race:{ev['id']}"]
        assert (await ann.get("/app/api/community/feed")).json()["drafts"] == 1
        r = await ann.post(f"/app/api/community/drafts/{drafts[0]['id']}/share", headers=H, json={})
        assert r.status_code == 201 and r.json()["post"]["event"]["name"] == "Bolder Boulder"
        s = (await ann.put("/app/api/community/settings", headers=H, json={"auto_share": {"pb": True}})).json()
        assert s["settings"]["auto_share"]["pb"] and s["usage"]["photos"] == 1
        # Clubs: approval, meetups, RSVP.
        g = (await ann.post("/app/api/community/clubs", headers=H,
                            json={"name": "Crew", "emoji": "🐇", "privacy": "approval", "city": "Denver"})).json()["club"]
        r = await bob.post(f"/app/api/community/clubs/{g['id']}/join", headers=H, json={})
        assert r.json()["club"]["requested"] and any(p[1] == "Join request" for p in push.sent)
        view = (await ann.get(f"/app/api/community/clubs/{g['id']}")).json()["club"]
        assert [u["name"] for u in view["pending"]] == ["Bob"]
        r = await ann.post(f"/app/api/community/clubs/{g['id']}/requests/bob/approve", headers=H, json={})
        assert {p["user"]["name"] for p in r.json()["club"]["people"]} == {"Ann", "Bob"}
        start = (agent._now("ann") + timedelta(days=2)).strftime("%Y-%m-%dT07:00")
        r = await ann.post(f"/app/api/community/clubs/{g['id']}/meetups", headers=H,
                           json={"title": "Long run", "start": start, "repeat": "weekly", "where": "City Park"})
        assert r.status_code == 201
        mid = r.json()["meetup"]["id"]
        r = await bob.post(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/rsvp", headers=H, json={"status": "going"})
        assert [u["name"] for u in r.json()["meetup"]["going"]] == ["Bob"]
        mine = (await bob.get("/app/api/community/meetups")).json()["meetups"]
        assert mine[0]["club"]["name"] == "Crew"
        view = (await bob.get(f"/app/api/community/clubs/{g['id']}")).json()["club"]
        assert view["meetups"][0]["id"] == mid and view["upcoming"] == [] and not view["can_challenge"]
        assert (await cat.get(f"/app/api/community/clubs/{g['id']}")).json()["club"]["people"] == []
        assert (await cat.post(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/rsvp", headers=H,
                               json={"status": "going"})).status_code == 404
        lst = (await cat.get("/app/api/community/clubs")).json()
        assert lst["clubs"] == [] and "discover" in lst and "local" in lst
        r = await bob.post("/app/api/community/posts", headers=H, json={"text": "Club news", "audience": f"club:{g['id']}"})
        assert r.status_code == 201
        assert (await cat.get(f"/app/api/community/posts/{r.json()['post']['id']}")).status_code == 404
        sug = (await cat.get("/app/api/community/people/suggested")).json()["people"]
        assert sug == []
        assert (await bob.get("/app/api/community/people/ann/photo")).status_code == 404  # ann has no photo
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_http_coach_accounts_get_403(env, tmp_path) -> None:
    apps, _, _ = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        coach = c[coach_user_id("c@x.com")]
        for path in ("/app/api/community/feed", "/app/api/community/drafts", "/app/api/community/settings",
                     "/app/api/community/clubs", "/app/api/community/people/suggested", "/app/api/community/meetups"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.post("/app/api/community/posts", headers=H, json={"text": "hi"})).status_code == 403
        assert (await coach.post("/app/api/community/clubs", headers=H, json={"name": "x"})).status_code == 403
        assert (await coach.post("/app/api/community/photos", headers={"origin": BASE, "content-type": "image/jpeg"},
                                 content=jpeg())).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
