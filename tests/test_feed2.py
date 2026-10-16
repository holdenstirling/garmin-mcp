"""Community v2: owner-featured clubs (cap, fair rotation, expiry, owner only, local/sport/online
matching), Community opens on Feed, friends' latest (Rabbit home), feed groups (create, add,
leave, owner rename/remove, caps), group-only audiences, blocks, coach 403, and richer
auto-shared workout cards (pace, lap shape, reward headline) pinned for the author for an hour.
Clock-independent: every time is injected; quiet hours never matter here (push quiet is off)."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.clubs import Clubs
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.community import PIN_S, Community, CommunityError, splits_from
from garmin_mcp.featured import MAX_FEATURED, FeatureError, Featured, athlete_sports, matches, rotate
from garmin_mcp.feedgroups import MAX_GROUPS, MAX_MEMBERS, FeedGroups, GroupError
from garmin_mcp.social import Social
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _follow, _setup
from tests.test_social import H, act

TZ = ZoneInfo("America/Denver")
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
TODAY = NOON.date()
ALLOW = {f"{u}@x.com": u for u in ("ann", "bob", "cat", "dan", "eve", "owner")}


@pytest.fixture
def fx(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    clock = SimpleNamespace(t=1_800_000_000.0, at=NOON)
    soc = Social(store, athletes=lambda: dict(ALLOW), clock=lambda: clock.t)
    clubs = Clubs(store, is_athlete=soc.is_athlete, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                  blocked=soc.blocked_between, race_groups=lambda u: [], clock=lambda: clock.t)
    groups = FeedGroups(store, is_athlete=soc.is_athlete, follows=soc.follows, blocked=soc.blocked_between,
                        clock=lambda: clock.t)
    cm = Community(store, social=soc, clubs=clubs, now=lambda u: clock.at, clock=lambda: clock.t,
                   quiet=lambda u: False, name=lambda u: u.title())
    cm.groups = groups
    listings: dict[str, dict] = {}
    ft = Featured(store, is_owner=lambda u: u == "owner", club_card=lambda c, u: clubs.featured_card(c, u, clock.at),
                  listing_card=lambda city, st, lid, u: listings.get(lid), clock=lambda: clock.t)
    return SimpleNamespace(store=store, clock=clock, soc=soc, clubs=clubs, groups=groups, cm=cm, ft=ft,
                           listings=listings)


def mutual(soc: Social, a: str, b: str) -> None:
    _follow(soc, a, b)
    _follow(soc, b, a)


def club(fx, owner: str, name: str, **kw) -> str:
    return fx.clubs.create(owner, {"name": name, "sport": kw.get("sport", "running"), "city": kw.get("city", "Denver"),
                                   "state": kw.get("state", "CO"), "description": kw.get("description", "")})["id"]


def feature(fx, cid: str, **body):
    return fx.ft.set("owner", "club", {"club_id": cid}, {"on": True, **body}, TODAY)


def shown(fx, viewer: str, *, city="Denver", state="CO", sports=frozenset({"run"}), today=TODAY) -> list[str]:
    return [x["name"] for x in fx.ft.for_viewer(viewer, city=city, state=state, sports=set(sports), today=today)]


# ---------------------------------------------------------------- featured --
def test_featured_owner_only_cap_and_off(fx) -> None:
    a, b, c, d = (club(fx, "ann", n) for n in ("A Crew", "B Crew", "C Crew", "D Crew"))
    with pytest.raises(FeatureError) as e:
        fx.ft.set("ann", "club", {"club_id": a}, {"on": True}, TODAY)  # a club owner isn't the app owner
    assert e.value.status == 403
    with pytest.raises(FeatureError) as e:
        fx.ft.set("coach_x", "club", {"club_id": a}, {"on": True}, TODAY)
    assert e.value.status == 403
    assert fx.ft.state("ann", "club", {"club_id": a}, TODAY) == {"owner": False}
    for cid in (a, b, c):
        st = feature(fx, cid, tagline="Saturday long runs, all paces")
        assert st["featured"] and st["tagline"] == "Saturday long runs, all paces"
    assert st["slots_left"] == 1  # its own slot counts as free for edits
    with pytest.raises(FeatureError) as e:
        feature(fx, d)
    assert e.value.status == 409
    feature(fx, a, tagline="Edited")  # updating a live one is fine at the cap
    fx.ft.set("owner", "club", {"club_id": b}, {"on": False}, TODAY)
    assert feature(fx, d)["featured"]
    with pytest.raises(FeatureError):
        feature(fx, a, tagline="x" * 81)
    with pytest.raises(FeatureError):
        feature(fx, a, until=(TODAY - timedelta(days=1)).isoformat())
    with pytest.raises(FeatureError) as e:
        fx.ft.set("owner", "club", {"club_id": "g000000000000"}, {"on": True}, TODAY)
    assert e.value.status == 404
    assert MAX_FEATURED == 3


def test_featured_expiry_frees_the_slot(fx) -> None:
    a, b, c, d = (club(fx, "ann", n) for n in ("A", "B", "C", "D"))
    feature(fx, a, until=(TODAY + timedelta(days=2)).isoformat())
    feature(fx, b)
    feature(fx, c)
    assert set(shown(fx, "bob")) == {"A", "B", "C"}
    later = TODAY + timedelta(days=3)
    assert set(shown(fx, "bob", today=later)) == {"B", "C"}  # gone after its end date
    fx.ft.set("owner", "club", {"club_id": d}, {"on": True}, later)  # and its slot is free again
    assert set(shown(fx, "bob", today=later)) == {"B", "C", "D"}


def test_featured_rotation_is_fair(fx) -> None:
    names = ["A", "B", "C"]
    for n in names:
        feature(fx, club(fx, "ann", n))
        fx.clock.t += 10
    leads = [shown(fx, "bob", today=TODAY + timedelta(days=i))[0] for i in range(3)]
    assert sorted(leads) == names  # each one leads exactly once in three days
    for i in range(3):
        assert sorted(shown(fx, "bob", today=TODAY + timedelta(days=i))) == names
    items = [{"id": str(i), "created": i} for i in range(3)]
    assert [x["id"] for x in rotate(items, date(2026, 1, 1), n=2)] != [x["id"] for x in rotate(items, date(2026, 1, 2), n=2)]


def test_featured_local_sport_online_matching(fx) -> None:
    run_denver = club(fx, "ann", "Denver Runners", city="Denver", state="CO", sport="running")
    ride_boulder = club(fx, "ann", "Boulder Spin", city="Boulder", state="CO", sport="cycling")
    zwift = club(fx, "ann", "Zwift Crew", city="", state="", sport="cycling", description="Virtual rides on Zwift")
    for c in (run_denver, ride_boulder, zwift):
        feature(fx, c)
    # Local runner in Denver: the Denver club (local + sport) and the online one; not Boulder rides.
    assert set(shown(fx, "bob", city="Denver", sports={"run"})) == {"Denver Runners", "Zwift Crew"}
    # A cyclist in Austin: the rides (sport match) and the online one, not the Denver run club.
    assert set(shown(fx, "bob", city="Austin", state="TX", sports={"bike"})) == {"Boulder Spin", "Zwift Crew"}
    # Non-local, no matching sport: only online/virtual.
    assert shown(fx, "bob", city="Austin", state="TX", sports=set()) == ["Zwift Crew"]
    # Same city name, other state: not local.
    assert "Denver Runners" not in shown(fx, "bob", city="Denver", state="IA", sports={"swim"})
    # Owner can force online off.
    fx.ft.set("owner", "club", {"club_id": zwift}, {"on": True, "online": False}, TODAY)
    assert shown(fx, "bob", city="Austin", state="TX", sports=set()) == []
    # Profile sports: favorites, race interests, main race type; triathletes match all three.
    assert athlete_sports({"favorite_sports": ["gravel"]}) == {"bike"}
    assert athlete_sports({"interests": {"race_types": ["triathlon"]}}) >= {"tri", "run", "bike", "swim"}
    assert athlete_sports({}, "trail") == {"trail", "run"}
    assert not matches({"family": "other", "city": "X"}, city="Y", state="", sports={"run"})


def test_featured_card_and_blocks(fx) -> None:
    cid = club(fx, "ann", "Crew")
    start = (NOON + timedelta(days=1)).strftime("%Y-%m-%dT07:00")
    m = fx.clubs.add_meetup("ann", cid, {"title": "Long run", "start": start, "where": "City Park"}, NOON)
    fx.clubs.rsvp("ann", cid, m["id"], "going", NOON)
    feature(fx, cid, tagline="All paces")
    card = fx.ft.for_viewer("bob", city="Denver", state="CO", sports=set(), today=TODAY)[0]
    assert card["label"] == "Featured" and card["tagline"] == "All paces" and card["members"] == 1
    assert card["role"] is None and card["next_meetup"]["title"] == "Long run" and card["next_meetup"]["going"] == 1
    assert card["next_meetup"]["where"] == "City Park" and card["local"]
    fx.soc.block("ann", "bob")  # the club owner blocked bob: never shown to him
    assert fx.ft.for_viewer("bob", city="Denver", state="CO", sports={"run"}, today=TODAY) == []
    # Directory listings can be featured too (card from the directory).
    fx.listings["l0123456789ab"] = {"listing_id": "l0123456789ab", "name": "Wash Park Run Club", "listing_kind": "run_club",
                                    "city": "Denver", "state": "CO", "members": None}
    fx.ft.set("owner", "listing", {"city": "Denver", "state": "CO", "listing_id": "l0123456789ab"}, {"on": True}, TODAY)
    assert "Wash Park Run Club" in shown(fx, "cat", city="Austin", state="TX", sports={"run"})
    assert "Wash Park Run Club" not in shown(fx, "cat", city="Austin", state="TX", sports={"swim"})


# ------------------------------------------------------------------ groups --
def test_group_create_add_leave_and_owner_powers(fx) -> None:
    g, soc = fx.groups, fx.soc
    mutual(soc, "ann", "bob")
    mutual(soc, "ann", "cat")
    _follow(soc, "dan", "ann")  # one way only: not a mutual friend
    grp = g.create("ann", {"name": "Saturday long run crew", "emoji": "🏃", "members": ["bob"]})
    assert grp["members"] == ["ann", "bob"] and grp["owner"]
    with pytest.raises(GroupError):
        g.create("ann", {"name": "x", "members": ["dan"]})  # not mutual
    with pytest.raises(GroupError):
        g.create("ann", {"name": "", "members": []})
    with pytest.raises(GroupError):
        g.create("ann", {"name": "ok", "emoji": "abc"})
    # Any member adds their own mutual friends ("invite more"); bob isn't friends with cat.
    with pytest.raises(GroupError):
        g.add("bob", grp["id"], ["cat"])
    grp2, new = g.add("ann", grp["id"], ["cat", "bob"])
    assert new == ["cat"] and grp2["count"] == 3
    # Only the owner renames/removes.
    with pytest.raises(GroupError) as e:
        g.update("bob", grp["id"], {"name": "Mine now"})
    assert e.value.status == 403
    assert g.update("ann", grp["id"], {"name": "Sat crew", "emoji": "🌅"})["name"] == "Sat crew"
    with pytest.raises(GroupError):
        g.remove("bob", grp["id"], "cat")
    assert g.remove("ann", grp["id"], "cat")["members"] == ["ann", "bob"]
    # Non-members see nothing.
    with pytest.raises(GroupError) as e:
        g.get("cat", grp["id"])
    assert e.value.status == 404
    # Owner leaves: bob takes over; last one out deletes it.
    g.leave("ann", grp["id"])
    assert g.get("bob", grp["id"])["owner"]
    g.leave("bob", grp["id"])
    assert g.mine("bob") == []
    with pytest.raises(GroupError) as e:
        g.mine("coach_x")
    assert e.value.status == 403


def test_group_caps(fx) -> None:
    g, soc = fx.groups, fx.soc
    mutual(soc, "ann", "bob")
    for i in range(MAX_GROUPS):
        g.create("ann", {"name": f"G{i}", "members": []})
    with pytest.raises(GroupError) as e:
        g.create("ann", {"name": "one too many"})
    assert e.value.status == 409
    with pytest.raises(GroupError) as e:  # bob can't be added to an 11th group of his either
        for i in range(MAX_GROUPS):
            g.create("bob", {"name": f"B{i}", "members": []})
        g.add("ann", g.mine("ann")[0]["id"], ["bob"])
    assert MAX_MEMBERS == 50


# ---------------------------------------------------------------- audience --
def test_group_only_posts_hidden_from_non_members_and_blocks(fx) -> None:
    cm, g, soc = fx.cm, fx.groups, fx.soc
    mutual(soc, "ann", "bob")
    mutual(soc, "ann", "cat")
    _follow(soc, "dan", "ann")  # a friend, not in the group
    grp = g.create("ann", {"name": "Crew", "members": ["bob", "cat"]})
    post = cm.create("ann", {"text": "Saturday 7am, usual spot", "audience": f"grp:{grp['id']}"})
    assert post["audience"] == f"grp:{grp['id']}" and post["groups"][0]["name"] == "Crew"
    assert [p["id"] for p in cm.feed("bob")["items"]] == [post["id"]]
    assert [p["id"] for p in cm.feed("bob", group=grp["id"])["items"]] == [post["id"]]
    assert cm.feed("dan")["items"] == []  # friend, but not in the group
    with pytest.raises(CommunityError):
        cm.get("dan", post["id"])
    with pytest.raises(CommunityError):
        cm.feed("dan", group=grp["id"])
    # Friends posts don't show under the group chip; groups list form works too.
    fpost = cm.create("ann", {"text": "Hi friends", "audience": "friends"})
    assert [p["id"] for p in cm.feed("bob", group=grp["id"])["items"]] == [post["id"]]
    assert cm.create("ann", {"text": "two", "audience": "groups", "groups": [grp["id"]]})["audience"].startswith("grp:")
    with pytest.raises(CommunityError):  # dan can't post to a group he's not in
        cm.create("dan", {"text": "x", "audience": f"grp:{grp['id']}"})
    # Blocks win over group membership.
    soc.block("cat", "ann")
    assert cm.feed("cat", group=grp["id"])["items"] == []
    with pytest.raises(CommunityError):
        cm.get("cat", post["id"])
    # Leaving the group hides group posts.
    g.leave("bob", grp["id"])
    assert post["id"] not in [p["id"] for p in cm.feed("bob")["items"]]
    assert fpost["id"] in [p["id"] for p in cm.feed("bob")["items"]]
    # Clubs chip: only club posts.
    cid = club(fx, "ann", "Club")
    fx.clubs.join("bob", cid)
    cpost = cm.create("ann", {"text": "club news", "audience": f"club:{cid}"})
    assert [p["id"] for p in cm.feed("bob", scope="clubs")["items"]] == [cpost["id"]]


# ------------------------------------------------------- auto-share + pin --
def _acts(today: date) -> list[dict]:
    a = [act(today - timedelta(days=20), 1, km=5), act(today, 2, km=10)]
    for x in a:
        x.update(name="Denver Running", lat=39.7392, lon=-104.9903)
    return a


def test_auto_share_card_pinned_for_an_hour_with_group_audience(fx) -> None:
    cm, soc, g = fx.cm, fx.soc, fx.groups
    mutual(soc, "ann", "bob")
    _follow(soc, "cat", "ann")
    laps = {"lapDTOs": [{"distance": 1000.0, "duration": 290.0, "averageHR": 150, "startLatitude": 39.7},
                        {"distance": 1000.0, "duration": 280.5}, {"distance": 40.0, "duration": 12.0}]}
    cm.splits = lambda u, a: splits_from(laps)
    cm.headline = lambda u, a: "Longest run in 6 weeks"
    grp = g.create("ann", {"name": "Crew", "members": ["bob"]})
    cm.put_settings("ann", {"share_workouts": True, "share_audience": f"grp:{grp['id']}"})
    pid = cm.auto_share_workouts("ann", _acts(TODAY), TODAY)[0]
    w = cm.get("bob", pid)["workout"]
    assert w["title"] == "Run" and w["pace_s_km"] == 270 and w["headline"] == "Longest run in 6 weeks"
    assert w["splits"] == [{"km": 1.0, "s": 290}, {"km": 1.0, "s": 280}] and w["auto"]
    blob = json.dumps(w).lower()
    for k in ("hr", "lat", "39.7", "denver"):
        assert k not in blob, k
    assert cm.feed("cat")["items"] == []  # group-only: a follower outside the group doesn't see it
    # The author's own feed pins it with a caption prompt for an hour, then it's a normal post.
    out = cm.feed("ann")
    assert out["pinned"]["id"] == pid and out["pinned"]["prompt"] == "Add a photo or caption"
    assert pid not in [p["id"] for p in out["items"]]
    assert cm.feed("bob")["pinned"] is None
    cm.update("ann", pid, {"text": "Felt great"})
    assert cm.feed("ann")["pinned"]["prompt"] is None
    fx.clock.t += PIN_S + 1
    out = cm.feed("ann")
    assert out["pinned"] is None and out["items"][0]["id"] == pid
    # Left every chosen group: stays private rather than going wider.
    g.leave("ann", grp["id"])
    acts = _acts(TODAY) + [act(TODAY, 3, km=4)]
    pid2 = cm.auto_share_workouts("ann", acts, TODAY)[0]
    assert cm.get("ann", pid2)["audience"] == "private"
    with pytest.raises(CommunityError):
        cm.put_settings("ann", {"share_audience": "grp:f000000000000"})
    assert splits_from({"lapDTOs": [{"distance": 1000, "duration": 300}]}) == []  # one lap: no shape


def test_friends_latest_and_default_view(fx) -> None:
    cm, soc = fx.cm, fx.soc
    _follow(soc, "ann", "bob")
    _follow(soc, "ann", "cat")
    _follow(soc, "ann", "dan")
    ids = []
    for who in ("bob", "cat", "dan", "bob"):
        ids.append(cm.create(who, {"text": f"hi from {who}", "audience": "friends"})["id"])
        fx.clock.t += 60
    cm.create("ann", {"text": "mine", "audience": "friends"})
    cm.create("eve", {"text": "public stranger", "audience": "public"})
    assert [p["id"] for p in cm.latest("ann")] == ids[::-1][:3]  # 3 newest friends' posts, not mine
    soc.block("ann", "dan")
    assert ids[2] not in [p["id"] for p in cm.latest("ann")]
    fx.clock.t += 8 * 86400
    assert cm.latest("ann") == []
    assert cm.settings("ann")["default_view"] == "feed"
    assert cm.put_settings("ann", {"default_view": "clubs"})["default_view"] == "clubs"
    with pytest.raises(CommunityError):
        cm.put_settings("ann", {"default_view": "people"})
    with pytest.raises(CommunityError):
        cm.latest("coach_x")


# -------------------------------------------------------------------- HTTP --
def test_http_home_latest_groups_featured(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        coach = c[coach_user_id("c@x.com")]
        for a, b in (("ann", "bob"), ("bob", "ann")):
            await c[a].post("/app/api/social/follow", headers=H, json={"email": f"{b}@x.com"})
            eid = (await c[b].get("/app/api/social")).json()["pending_in"][0]["edge_id"]
            await c[b].post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        # Community opens on Feed by default.
        home = (await ann.get("/app/api/community/home")).json()
        assert home["view"] == "feed" and home["featured"] == [] and home["groups"] == []
        # Groups over HTTP: mutual friends only, page, invite, leave.
        friends = (await ann.get("/app/api/community/groups/friends")).json()["people"]
        assert [p["id"] for p in friends] == ["bob"]
        r = await ann.post("/app/api/community/groups", headers=H, json={"name": "Sat crew", "emoji": "🏃", "members": ["bob"]})
        assert r.status_code == 201
        gid = r.json()["group"]["id"]
        assert any(p[0] == "bob" and p[1] == "New group" for p in push.sent)
        assert (await ann.post("/app/api/community/groups", headers=H, json={"name": "x", "members": ["cat"]})).status_code == 404
        assert (await cat.get(f"/app/api/community/groups/{gid}")).status_code == 404
        r = await ann.post("/app/api/community/posts", headers=H, json={"text": "7am Sat", "audience": f"grp:{gid}"})
        pid = r.json()["post"]["id"]
        feed = (await bob.get(f"/app/api/community/feed?group={gid}")).json()
        assert [p["id"] for p in feed["items"]] == [pid] and feed["items"][0]["user"]["name"] == "Ann"
        assert (await cat.get(f"/app/api/community/posts/{pid}")).status_code == 404
        # Friends' latest for the Rabbit home.
        latest = (await bob.get("/app/api/community/latest")).json()["items"]
        assert [p["id"] for p in latest] == [pid] and latest[0]["user"]["name"] == "Ann"
        assert (await bob.patch(f"/app/api/community/groups/{gid}", headers=H, json={"name": "nope"})).status_code == 403
        assert (await bob.post(f"/app/api/community/groups/{gid}/leave", headers=H, json={})).status_code == 200
        assert (await bob.get(f"/app/api/community/feed?group={gid}")).status_code == 404
        # Featured: every allowlisted athlete is an owner here (no OWNER_USER_IDS); coaches 403.
        cl = (await ann.post("/app/api/community/clubs", headers=H, json={"name": "Crew", "city": "", "description": "Virtual"})).json()["club"]
        st = (await ann.get(f"/app/api/community/featured/manage?club={cl['id']}")).json()
        assert st["owner"] and not st["featured"]
        r = await ann.put("/app/api/community/featured", headers=H, json={"club_id": cl["id"], "on": True, "tagline": "Join us", "online": True})
        assert r.status_code == 200 and r.json()["featured"]
        items = (await cat.get("/app/api/community/featured?where=explore")).json()["items"]
        assert [x["name"] for x in items] == ["Crew"] and items[0]["label"] == "Featured"
        assert (await cat.get("/app/api/community/home")).json()["featured"][0]["tagline"] == "Join us"
        for path in ("/app/api/community/home", "/app/api/community/latest", "/app/api/community/groups",
                     "/app/api/community/featured"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.put("/app/api/community/featured", headers=H, json={"club_id": cl["id"], "on": False})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
