"""Following friends: follow requests, privacy, feed visibility, kudos, pushes, access."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.social import GENERIC_SENT, Social, SocialError, SocialFeed, normalize, visible
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
H = {"origin": BASE}
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat"}
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def act(d: date, aid: int, *, sport="running", minutes=45, km=8.2, event=None):
    h, m = divmod(minutes, 60)
    return {"activity_id": aid, "date": f"{d.isoformat()} 07:15:00", "name": f"Run {aid}", "sport": sport,
            "duration": f"{h}:{m:02d}:00", "distance_km": km, "elevation_gain_m": 120, "avg_hr": 151,
            "max_hr": 180, "event": event}


@pytest.fixture
def soc(tmp_path, fernet_key):
    clock = SimpleNamespace(t=1_800_000_000.0)
    allow = dict(ALLOW)
    s = Social(AppStore(tmp_path / "app", fernet_key), athletes=lambda: allow, clock=lambda: clock.t)
    return SimpleNamespace(s=s, clock=clock, allow=allow)


def _edge(people, key):
    return people[key][0]["edge_id"]


def test_follow_accept_decline_unfollow_remove(soc) -> None:
    s = soc.s
    r = s.follow("bob", email="Ann@X.com")
    assert r["status"] == "pending" and r["notify"] == "ann" and r["by_email"]
    assert s.follow("bob", email="ann@x.com")["notify"] is None  # dedupe, no second push
    ann = s.people("ann")
    assert len(ann["pending_in"]) == 1 and ann["pending_in"][0]["user_id"] == "bob"
    # Requests made by email only ever show the email that was typed.
    assert s.people("bob")["pending_out"][0] == {**s.people("bob")["pending_out"][0], "email": "ann@x.com", "user_id": None}
    assert not s.follows("bob", "ann")
    with pytest.raises(SocialError):
        s.accept("bob", _edge(ann, "pending_in"))  # only the target can accept
    assert s.accept("ann", _edge(ann, "pending_in")) == "bob"
    assert s.follows("bob", "ann") and not s.follows("ann", "bob")  # one-way
    assert s.ever_followed("bob") and s.following_ids("bob") == ["ann"]
    s.unfollow("bob", _edge(s.people("bob"), "following"))
    assert not s.follows("bob", "ann")
    # decline
    s.follow("cat", email="ann@x.com")
    s.decline("ann", _edge(s.people("ann"), "pending_in"))
    assert s.people("ann")["pending_in"] == [] and s.people("cat")["pending_out"] == []
    # remove follower
    s.follow("cat", email="ann@x.com")
    s.accept("ann", _edge(s.people("ann"), "pending_in"))
    s.remove_follower("ann", _edge(s.people("ann"), "followers"))
    assert not s.follows("cat", "ann")
    with pytest.raises(SocialError, match="you"):
        s.follow("ann", email="ann@x.com")


def test_email_requests_do_not_reveal_accounts(soc) -> None:
    s = soc.s
    real = s.follow("bob", email="ann@x.com")
    ghost = s.follow("bob", email="nobody@x.com")
    assert real["by_email"] and ghost["by_email"] and ghost["notify"] is None
    out = s.people("bob")["pending_out"]
    assert sorted(o["email"] for o in out) == ["ann@x.com", "nobody@x.com"]
    assert all(o["user_id"] is None for o in out)
    # The ghost becomes a real request when that person gets a Rabbit invite.
    soc.allow["nobody@x.com"] = "nobody"
    assert [p["user_id"] for p in s.people("nobody")["pending_in"]] == ["bob"]
    # Coaches and coach-only accounts can't be followed or follow.
    soc.allow["coach@x.com"] = coach_user_id("coach@x.com")
    assert s.follow("bob", email="coach@x.com")["notify"] is None
    with pytest.raises(SocialError) as e:
        s.follow(coach_user_id("coach@x.com"), email="ann@x.com")
    assert e.value.status == 403


def test_invite_code_and_auto_accept_and_block(soc) -> None:
    s = soc.s
    code = s.invite_code("ann")
    assert len(code) == 8 and s.invite_code("ann") == code
    with pytest.raises(SocialError):
        s.follow("bob", code="ZZZZZZZZ")
    r = s.follow("bob", code=code.lower())
    assert r["status"] == "pending" and not r["by_email"] and r["target"] == "ann"
    new = s.regenerate_code("ann")
    assert new != code
    with pytest.raises(SocialError):
        s.follow("cat", code=code)  # old code is dead
    # auto-accept only from people I follow
    s.put_settings("bob", {"auto_accept": True})
    s.accept("ann", _edge(s.people("ann"), "pending_in"))  # bob follows ann
    assert s.follow("ann", email="bob@x.com")["status"] == "active"
    assert s.follow("cat", email="bob@x.com")["status"] == "pending"  # bob doesn't follow cat
    # block: edges go both ways, new requests are hidden from the blocker
    s.block("bob", "cat")
    assert s.people("bob")["pending_in"] == []
    r = s.follow("cat", email="bob@x.com")
    assert r["notify"] is None and r["by_email"]
    assert s.people("bob")["pending_in"] == [] and len(s.people("cat")["pending_out"]) == 1
    assert s.badge("bob")["pending"] == 0
    s.unblock("bob", "cat")
    assert len(s.people("bob")["pending_in"]) == 1
    with pytest.raises(SocialError):
        s.put_settings("ann", {"workouts": "yes"})


def test_visibility_filtering() -> None:
    today = date(2026, 10, 14)
    acts = [act(today, 1), act(today - timedelta(days=2), 2, event="race"), act(today - timedelta(days=20), 3)]
    items = normalize(acts, today)
    assert [i["id"] for i in items] == ["1", "2"]  # 14 days only
    assert set(items[0]) == {"id", "date", "time", "sport", "title", "minutes", "km", "climb_m", "xp", "race"}
    base = {"workouts": True, "distance": True, "times": True, "streak": True, "races": False, "auto_accept": False}
    assert visible(items[1], base) is None  # races are off by default
    assert visible(items[1], base | {"races": True})["race"] is True
    v = visible(items[0], base | {"distance": False, "times": False})
    assert v["km"] is None and v["climb_m"] is None and v["minutes"] is None and v["xp"] is None and v["title"]
    assert visible(items[0], base | {"workouts": False}) is None


def test_feed_respects_settings_and_follow(soc) -> None:
    s = soc.s
    today = date(2026, 10, 14)
    acts = {"ann": [act(today, 11), act(today - timedelta(days=1), 12, event="race")], "bob": [act(today, 21)], "cat": []}
    feed = SocialFeed(s, activities=lambda u: (today, acts[u]),
                      meta=lambda u: {"name": u.title(), "photo": None, "picture": "", "level": 3, "streak": 4})
    assert [i["id"] for i in feed.feed("bob", str.title)] == ["21"]  # own only
    s.follow("bob", email="ann@x.com")
    assert [i["id"] for i in feed.feed("bob", str.title)] == ["21"]  # pending isn't enough
    s.accept("ann", _edge(s.people("ann"), "pending_in"))
    items = feed.feed("bob", str.title)
    assert sorted(i["id"] for i in items) == ["11", "21"]
    a = next(i for i in items if i["id"] == "11")
    assert a["user"]["name"] == "Ann" and a["user"]["level"] == 3 and not a["mine"]
    assert "avg_hr" not in a and "hr" not in str(sorted(a))
    s.put_settings("ann", {"streak": False, "distance": False, "races": True})
    items = [i for i in feed.feed("bob", str.title) if i["user"]["id"] == "ann"]
    assert [i["id"] for i in items] == ["11", "12"] and items[0]["km"] is None and items[0]["user"]["level"] is None
    card = feed.card("bob", "ann", str.title)
    assert card["week"]["workouts"] >= 1 and len(card["recent"]) == 2
    with pytest.raises(SocialError):
        feed.card("cat", "ann", str.title)


def test_kudos_permission_dedupe_cheers_and_xp(soc) -> None:
    s = soc.s
    with pytest.raises(SocialError):
        s.give_kudos("bob", "ann", "11")  # not following
    s.follow("bob", email="ann@x.com")
    s.accept("ann", _edge(s.people("ann"), "pending_in"))
    assert s.give_kudos("bob", "ann", "11") == {"count": 1, "you_kudoed": True, "new": True}
    assert s.give_kudos("bob", "ann", "11")["new"] is False  # dedupe
    assert s.kudos_of("ann")["11"]["by"].keys() == {"bob"}
    with pytest.raises(SocialError):
        s.give_kudos("bob", "ann", "../x")
    with pytest.raises(SocialError):
        s.give_kudos("ann", "ann", "11")
    c = s.cheer("bob", "ann", "11", "  Great   run!  " + "x" * 300)
    assert len(c["text"]) == 140 and c["text"].startswith("Great run!")
    with pytest.raises(SocialError):
        s.delete_cheer("cat", "ann", "11", c["id"])
    s.delete_cheer("ann", "ann", "11", c["id"])  # the owner may delete
    assert s.kudos_of("ann")["11"]["cheers"] == []
    assert s.badge("ann")["new_kudos"] == 1
    s.mark_seen("ann")
    assert s.badge("ann")["new_kudos"] == 0
    # XP: +5 per kudos, at most 10 a day
    today = date.fromtimestamp(soc.clock.t)
    assert list(s.kudos_bonus("ann", today).values()) == [5]
    for i in range(15):  # more givers on one day: XP caps at 10 kudos
        soc.allow[f"p{i}@x.com"] = f"p{i}"
        s.follow(f"p{i}", email="ann@x.com")
    s.put_settings("ann", {"auto_accept": True})
    for e in s.people("ann")["pending_in"]:
        s.accept("ann", e["edge_id"])
    for i in range(15):
        s.give_kudos(f"p{i}", "ann", "12")
    assert sum(s.kudos_bonus("ann", today).values()) == 50
    assert s.remove_kudos("bob", "ann", "11")["count"] == 0


# ------------------------------------------------------------------- http --
class FakePush:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, user_id, title, body, url="/app/", ttl=0):
        self.sent.append((user_id, title, body))
        return []

    def count(self, user_id):
        return 0

    def public_key(self):
        return "x"


def _setup(env, tmp_path):
    agent, _ = env.agent([])
    today = agent._now("ann").date()
    acts = {"ann": [act(today, 11), act(today - timedelta(days=1), 12)], "bob": [act(today, 21)], "cat": []}
    agent.stats.activities = lambda uid, fresh=False: (today, acts.get(uid, []))
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW))
    push = FakePush()

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, push, None, ChatRunner(agent)))
    return {u: app(u) for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}, push


def _clients(apps):
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}


def test_http_flow_push_coalescing_and_photo(env, tmp_path) -> None:
    apps, push = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        # Same answer for a real and a made-up email.
        r1 = await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        r2 = await bob.post("/app/api/social/follow", headers=H, json={"email": "ghost@x.com"})
        assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json() == {"ok": True, "message": GENERIC_SENT}
        assert [p[0] for p in push.sent] == ["ann"]
        # Re-requesting the same day doesn't push again.
        out = (await bob.get("/app/api/social")).json()["pending_out"]
        mine = next(o for o in out if o["email"] == "ann@x.com")
        assert (await bob.request("DELETE", f"/app/api/social/following/{mine['edge_id']}", headers=H, json={})).status_code == 200
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        assert len(push.sent) == 1
        assert (await ann.get("/app/api/social/badge")).json()["pending"] == 1
        # Not following yet: no feed items, card, kudos or photo.
        assert (await bob.get("/app/api/social/people/ann")).status_code == 404
        assert (await bob.post("/app/api/social/kudos/ann/11", headers=H, json={})).status_code == 404
        assert (await ann.post("/app/api/profile/photo", headers={"origin": BASE, "content-type": "image/jpeg"},
                               content=JPEG)).status_code == 201
        assert (await bob.get("/app/api/social/people/ann/photo")).status_code == 404
        ppl = (await ann.get("/app/api/social")).json()
        assert ppl["pending_in"][0]["user"]["name"] == "Bob" and len(ppl["invite_code"]) == 8
        eid = ppl["pending_in"][0]["edge_id"]
        assert (await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})).status_code == 200
        r = await bob.get("/app/api/social/people/ann/photo")
        assert r.status_code == 200 and r.content == JPEG
        assert (await cat.get("/app/api/social/people/ann/photo")).status_code == 404
        feed = (await bob.get("/app/api/social/feed")).json()["items"]
        a = [i for i in feed if i["user"]["id"] == "ann"]
        assert len(a) == 2 and a[0]["user"]["name"] == "Ann" and a[0]["kudos"] == 0
        assert "avg_hr" not in a[0] and "max_hr" not in a[0]
        card = (await bob.get("/app/api/social/people/ann")).json()
        assert card["user"]["name"] == "Ann" and len(card["recent"]) == 2
        # Kudos: deduped, and pushes coalesce per workout per hour.
        n = len(push.sent)
        assert (await bob.post("/app/api/social/kudos/ann/11", headers=H, json={})).json()["count"] == 1
        assert (await bob.post("/app/api/social/kudos/ann/11", headers=H, json={})).json()["count"] == 1
        await bob.request("DELETE", "/app/api/social/kudos/ann/11", headers=H, json={})
        await bob.post("/app/api/social/kudos/ann/11", headers=H, json={})
        r = await bob.post("/app/api/social/cheers/ann/11", headers=H, json={"text": "Nice!"})
        assert r.status_code == 201
        assert len(push.sent) == n + 1
        await bob.post("/app/api/social/kudos/ann/12", headers=H, json={})
        assert len(push.sent) == n + 2
        # Not a workout the viewer can see.
        assert (await bob.post("/app/api/social/kudos/ann/999", headers=H, json={})).status_code == 404
        # The owner can delete a cheer on their workout.
        cheer = r.json()["cheer"]["id"]
        assert (await cat.request("DELETE", f"/app/api/social/cheers/ann/11/{cheer}", headers=H, json={})).status_code == 404
        assert (await ann.request("DELETE", f"/app/api/social/cheers/ann/11/{cheer}", headers=H, json={})).status_code == 200
        assert (await ann.get("/app/api/social/badge")).json()["new_kudos"] >= 2
        # Kudos earn XP through the progress ledger; following earns the friend quest.
        p_ann = (await ann.get("/app/api/progress")).json()
        p_bob = (await bob.get("/app/api/progress")).json()
        assert next(q for q in p_bob["quests"] if q["id"] == "friend")["done"]
        assert p_ann["xp"] >= 10
        # Settings hide distance from followers.
        assert (await ann.put("/app/api/social/settings", headers=H, json={"distance": False})).json()["settings"]["distance"] is False
        apps_feed = (await bob.get("/app/api/social/feed")).json()["items"]
        assert all(i["km"] is None for i in apps_feed if i["user"]["id"] == "ann")
        new = (await ann.post("/app/api/social/code", headers=H, json={})).json()["invite_code"]
        assert new != ppl["invite_code"]
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_coach_accounts_get_403(env, tmp_path) -> None:
    apps, _ = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        coach = c[coach_user_id("c@x.com")]
        for path in ("/app/api/social", "/app/api/social/feed", "/app/api/social/badge",
                     "/app/api/social/people/ann", "/app/api/social/people/ann/photo"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
