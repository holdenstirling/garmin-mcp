"""Friends bring people back: auto-shared workouts (opt-in with a one-time prompt), cheers
with coalesced pushes and quiet hours, unread counts for the app icon badge (and the push
payload's ``badge``), one-tap home actions, coach 403. Clock-independent: every time is
injected; quiet hours are ``Moments.quiet`` (21:00-07:00) on a fixed local time."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.clubs import Clubs
from garmin_mcp.coaches import CoachChat, coach_user_id
from garmin_mcp.community import Community, CommunityError, workout_card, workout_label
from garmin_mcp.moments import Moments
from garmin_mcp.quickactions import QuickActions, pick_cheer, pick_feel, pick_rsvp, pick_watch
from garmin_mcp.social import Social
from garmin_mcp.unread import Unread
from garmin_mcp.webpush import WebPush
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _follow, _setup
from tests.test_social import H, act

TZ = ZoneInfo("America/Denver")
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat"}


@pytest.fixture
def fx(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    clock = SimpleNamespace(t=1_800_000_000.0, at=NOON)
    soc = Social(store, athletes=lambda: dict(ALLOW), clock=lambda: clock.t)
    grp = Clubs(store, is_athlete=soc.is_athlete, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                blocked=soc.blocked_between, race_groups=lambda u: [], clock=lambda: clock.t)
    pushes: list[tuple] = []
    cm = Community(store, social=soc, clubs=grp, now=lambda u: clock.at, clock=lambda: clock.t,
                   push=lambda to, t, b: pushes.append((to, t, b)),
                   quiet=lambda u: Moments.quiet(clock.at), name=lambda u: u.title())
    chat = CoachChat(store, clock=lambda: clock.t)
    unread = Unread(store, community=cm, social=soc, clubs=grp, coach_chat=chat, clock=lambda: clock.t)
    _follow(soc, "bob", "ann")  # bob follows ann
    return SimpleNamespace(store=store, clock=clock, soc=soc, grp=grp, cm=cm, pushes=pushes, chat=chat, unread=unread)


def _acts(today):
    a = [act(today - timedelta(days=30), 1, km=5), act(today - timedelta(days=1), 2, km=8), act(today, 3, km=10)]
    for x in a:  # Garmin names carry the city; HR and GPS must never reach a card
        x.update(name="Denver Running", lat=39.7392, lon=-104.9903, start_latitude=39.7, avg_power_w=230)
    return a


# -------------------------------------------------------------- auto-share --
def test_auto_share_needs_a_yes_and_is_declinable(fx) -> None:
    cm, today = fx.cm, NOON.date()
    acts = _acts(today)
    assert cm.settings("ann")["share_workouts"] is None
    assert cm.auto_share_workouts("ann", acts, today) == []  # never asked: nothing leaves
    cm.put_settings("ann", {"share_prompted": True})  # the prompt was shown but not answered: still off
    assert not Community.sharing_workouts(cm.settings("ann"))
    assert cm.auto_share_workouts("ann", acts, today) == []
    cm.put_settings("ann", {"share_workouts": True})  # a clear yes (opt-in consent to share)
    s = cm.settings("ann")
    # Sharing starts with the last few days (BACKFILL_DAYS), never older.
    assert Community.sharing_workouts(s) and s["share_since"] == (today - timedelta(days=2)).isoformat()
    posted = cm.auto_share_workouts("ann", acts, today)
    assert len(posted) == 2  # today's and yesterday's; the one from a month ago never
    assert cm.auto_share_workouts("ann", acts, today) == []  # once per activity
    feed = cm.feed("bob")["items"]
    assert sorted(p["id"] for p in feed) == sorted(posted) and feed[0]["audience"] == "friends" and feed[0]["kind"] == "workout"
    assert feed[0]["workout"]["title"] == "Run" and {p["workout"]["km"] for p in feed} == {10, 8}
    assert cm.feed("cat")["items"] == []  # not a follower
    # Declined: private.
    cm.put_settings("ann", {"share_workouts": False})
    acts.append(act(today, 4, km=6))
    assert cm.auto_share_workouts("ann", acts, today) == []
    # Off-able and back on from Me settings.
    cm.put_settings("ann", {"share_workouts": True})
    assert len(cm.auto_share_workouts("ann", acts, today)) == 1
    with pytest.raises(CommunityError):
        cm.put_settings("ann", {"share_workouts": "yes"})
    assert cm.auto_share_workouts("coach_x", acts, today) == []


def test_auto_share_respects_blocks(fx) -> None:
    cm, soc, today = fx.cm, fx.soc, NOON.date()
    _follow(soc, "cat", "ann")
    cm.put_settings("ann", {"share_workouts": True})
    soc.block("ann", "cat")
    ids = cm.auto_share_workouts("ann", _acts(today), today)
    pid = ids[-1]
    assert sorted(p["id"] for p in cm.feed("bob")["items"]) == sorted(ids)
    assert cm.feed("cat")["items"] == []
    with pytest.raises(CommunityError):
        cm.get("cat", pid)
    with pytest.raises(CommunityError):
        cm.react("cat", pid, "party")


def test_auto_shared_card_has_no_hr_gps_or_location(fx) -> None:
    cm, today = fx.cm, NOON.date()
    cm.put_settings("ann", {"share_workouts": True})
    pid = cm.auto_share_workouts("ann", _acts(today), today)[-1]
    post = cm.get("bob", pid)
    assert set(post["workout"]) == {"activity_id", "sport", "family", "kind", "title", "date", "km", "minutes",
                                    "climb_m", "highlight", "pace_s_km", "auto", "source"}
    blob = json.dumps(post).lower()
    for k in ("avg_hr", "max_hr", "151", '"lat', '"lon', "latitude", "39.7", "104.9", "denver", "power", "230"):
        assert k not in blob, k


# ------------------------------------------------------------------ cheers --
def test_cheer_push_names_the_workout_coalesces_and_respects_quiet_hours(fx) -> None:
    cm, today = fx.cm, NOON.date()
    _follow(fx.soc, "cat", "ann")
    cm.put_settings("ann", {"share_workouts": True})
    pid = cm.auto_share_workouts("ann", _acts(today), today)[-1]  # today's 10K (oldest first)
    cm.react("bob", pid, "party")
    assert fx.pushes == [("ann", "Bob cheered your 10K", "Tap to see who's cheering.")]
    cm.react("cat", pid, "strong")
    cm.comment("cat", pid, "Nice!")
    assert len(fx.pushes) == 1  # max one per post per hour
    fx.clock.t += 3601
    fx.clock.at = NOON.replace(hour=22)  # quiet hours 21:00-07:00
    cm.comment("bob", pid, "late one")
    assert len(fx.pushes) == 1
    fx.clock.at = NOON.replace(hour=6, minute=59)
    cm.comment("bob", pid, "early")
    assert len(fx.pushes) == 1
    fx.clock.at = NOON.replace(hour=7)
    cm.comment("cat", pid, "morning")
    assert fx.pushes[-1][:2] == ("ann", "Cat commented")
    assert workout_label({"sport": "run", "km": 21.1}) == "half marathon"
    assert workout_label({"sport": "run", "km": 7.6}) == "8 km run"
    assert workout_label({"sport": "bike", "km": 40}) == "ride"


# ------------------------------------------------------------------ unread --
def test_unread_counts_and_clearing(fx) -> None:
    cm, un, soc, grp = fx.cm, fx.unread, fx.soc, fx.grp
    p = cm.create("ann", {"text": "PR!", "category": "pb"})
    q = cm.create("ann", {"text": "Another", "category": "other"})
    assert un.counts("ann")["total"] == 0
    cm.react("bob", p["id"], "party")
    cm.comment("bob", p["id"], "Wow")
    cm.react("bob", q["id"], "heart")
    cm.react("bob", q["id"], "party")  # switching a reaction isn't new
    cm.comment("ann", p["id"], "ty")  # my own comment isn't unread
    assert un.counts("ann")["cheers"] == 3
    cm.get("ann", p["id"])  # opening the post clears it
    assert un.counts("ann")["cheers"] == 1
    # Friend requests (new since I last looked) and club invites.
    soc.follow("cat", email="ann@x.com")
    g = grp.create("bob", {"name": "Crew", "city": "Denver", "state": "CO"})
    grp.invite("bob", g["id"], "ann")
    c = un.counts("ann")
    assert (c["requests"], c["invites"], c["total"]) == (1, 1, 3)
    # Coach messages.
    t = fx.chat.open_thread("ann", "coach@x.com")
    fx.chat.post("ann", t["id"], sender="coach", text="Nice week", coach="coach@x.com")
    assert un.counts("ann")["coach"] == 1 and un.total("ann") == 4
    fx.clock.t += 1
    assert un.seen("ann", "requests")["requests"] == 0
    assert un.seen("ann", "invites")["invites"] == 0
    assert un.seen("ann", "cheers")["cheers"] == 0
    fx.chat.mark_read("ann", t["id"], "athlete")
    assert un.counts("ann")["total"] == 0
    fx.clock.t += 1
    soc.follow("bob", email="cat@x.com")  # someone else's request: not mine
    assert un.total("ann") == 0
    assert un.total(coach_user_id("c@x.com")) is None
    with pytest.raises(ValueError):
        un.seen("ann", "everything")


def test_push_payload_carries_badge(fx) -> None:
    sent: list[bytes] = []
    wp = WebPush.__new__(WebPush)  # no VAPID key needed: _post is stubbed
    wp._store = fx.store
    wp.badge_for = fx.unread.total
    wp._post = lambda sub, payload, ttl: sent.append(payload) or 201  # type: ignore[method-assign]
    fx.store.user_doc("ann", "push").save({"subs": [{"endpoint": "https://fcm.googleapis.com/fcm/send/x",
                                                     "p256dh": "x", "auth": "y"}]})
    p = fx.cm.create("ann", {"text": "PR!", "category": "pb"})
    fx.cm.react("bob", p["id"], "party")
    wp.send("ann", "Bob cheered your post", "PR!")
    assert json.loads(sent[-1])["badge"] == 1
    wp.badge_for = lambda u: None  # coach accounts: no badge field
    wp.send("ann", "t", "b")
    assert "badge" not in json.loads(sent[-1])


# ----------------------------------------------------------- quick actions --
def test_quick_actions_pickers() -> None:
    today = NOON.date()
    acts = [act(today - timedelta(days=3), 1), act(today, 5, km=10)]
    feel = pick_feel(acts, [], today)
    assert feel and feel["activity_id"] == 5 and feel["title"] == "Run"
    assert pick_feel(acts, [{"activity_id": "5", "date": today.isoformat()}], today) is None
    assert pick_feel(acts, [{"activity_id": None, "date": today.isoformat()}], today) is None
    assert pick_feel([act(today - timedelta(days=3), 1)], [], today) is None
    meet = [{"id": "m1", "title": "Long run", "next": "2026-10-15T07:00", "my_rsvp": "going", "club": {"id": "g1", "name": "Crew"}},
            {"id": "m2", "title": "Track", "next": "2026-10-16T18:00", "my_rsvp": None, "club": {"id": "g1", "name": "Crew"}},
            {"id": "m3", "title": "Far", "next": "2026-11-30T18:00", "my_rsvp": None, "club": {"id": "g1", "name": "Crew"}}]
    r = pick_rsvp(meet, NOON)
    assert r and r["meetup_id"] == "m2" and r["club_id"] == "g1"
    assert pick_rsvp(meet[2:], NOON) is None
    now = 1_800_000_000.0
    posts = [{"id": "p1", "author": "me", "mine": True, "kind": "workout", "created": now},
             {"id": "p2", "author": "bob", "kind": "workout", "my_reaction": "party", "created": now},
             {"id": "p3", "author": "cat", "kind": "moment", "created": now},
             {"id": "p4", "author": "bob", "kind": "workout", "workout": {"sport": "run", "km": 5}, "created": now - 3600},
             {"id": "p5", "author": "dan", "kind": "workout", "created": now - 4 * 86400}]
    c = pick_cheer(posts, now, lambda u: u.title())
    assert c and c["post_id"] == "p4" and c["name"] == "Bob" and c["what"] == "5K"
    assert pick_cheer(posts[4:], now, lambda u: u) is None
    d0, d1, d9 = today.isoformat(), (today + timedelta(days=1)).isoformat(), (today + timedelta(days=9)).isoformat()
    plan = {"weeks": [{"start": d0, "days": {
        d0: [{"id": "s0", "sport": "run", "title": "Easy", "garmin": {"workout_ids": [1]}}],
        d1: [{"id": "s1", "sport": "rest"}, {"id": "s2", "sport": "bike", "title": "Tempo"}],
        d9: [{"id": "s9", "sport": "run", "title": "Later"}]}}]}
    w = pick_watch(plan, today, True)
    assert w and w["session_id"] == "s2" and w["date"] == d1
    assert pick_watch(plan, today, False) is None  # no Garmin: hidden
    assert pick_watch(None, today, True) is None
    qa = QuickActions(now=lambda u: NOON, clock=lambda: now, activities=lambda u: (today, acts),
                      checkins=lambda u: [], meetups=lambda u, n: meet, friend_posts=lambda u: 1 / 0,
                      plan=lambda u: plan, garmin=lambda u: True)
    assert [a["kind"] for a in qa.get("ann")] == ["feel", "rsvp", "watch"]  # a failing source just hides


# -------------------------------------------------------------------- http --
def test_http_unread_quick_and_coach_403(env, tmp_path) -> None:  # noqa: F811
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob = c["ann"], c["bob"]
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        assert (await ann.get("/app/api/unread")).json()["requests"] == 1
        assert (await ann.post("/app/api/unread/seen", headers=H, json={"kind": "requests"})).json()["requests"] == 0
        assert (await ann.post("/app/api/unread/seen", headers=H, json={"kind": "nope"})).status_code == 400
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        # Sharing needs a yes: the consent screen's separate sharing box gives it (and can take it back).
        ok = {"terms": True, "privacy": True, "age16": True, "health": True}
        assert (await ann.post("/app/api/consent", headers=H, json=dict(ok, share=False))).status_code == 200
        assert (await ann.get("/app/api/community/settings")).json()["settings"]["share_workouts"] is False
        assert (await ann.post("/app/api/consent", headers=H, json=dict(ok, share=True))).status_code == 200
        s = (await ann.get("/app/api/community/settings")).json()["settings"]
        assert s["share_workouts"] is True and s["share_prompted"]
        agent.moments.after_workouts("ann")
        feed = (await bob.get("/app/api/community/feed")).json()["items"]
        assert len(feed) == 1 and feed[0]["workout"]["title"] == "Run" and "avg_hr" not in json.dumps(feed[0])
        quick = (await bob.get("/app/api/home/quick")).json()["actions"]
        assert [a["kind"] for a in quick] == ["cheer"] and quick[0]["name"] == "Ann"
        r = await bob.post(f"/app/api/community/posts/{feed[0]['id']}/reactions", headers=H, json={"kind": "party"})
        assert r.status_code == 200
        assert push.sent[-1][:2] == ("ann", "Bob cheered your 15 km run")
        assert (await ann.get("/app/api/unread")).json()["cheers"] == 1
        assert (await bob.get("/app/api/home/quick")).json()["actions"] == []
        assert (await ann.post("/app/api/unread/seen", headers=H, json={"kind": "cheers"})).json()["total"] == 0
        # Ann's own workout today has no check-in yet.
        assert [a["kind"] for a in (await ann.get("/app/api/home/quick")).json()["actions"]] == ["feel"]
        coach = c[coach_user_id("c@x.com")]
        for path in ("/app/api/unread", "/app/api/home/quick"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.post("/app/api/unread/seen", headers=H, json={"kind": "cheers"})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_auto_share_any_source_with_label_and_once_per_activity(fx) -> None:
    """Workouts from other sources ("<source>:<id>") auto-post too, labelled with where they came
    from; Garmin stays the default label; unknown sources fall back to Garmin; odd ids are skipped."""
    from garmin_mcp.community import activity_key, source_of
    cm, today = fx.cm, NOON.date()
    cm.put_settings("ann", {"share_workouts": True})
    g = act(today, 11, km=5)
    o = act(today, 12, km=7)
    o.update(activity_id="oura:abc123", source="oura")
    bad = act(today, 13, km=3)
    bad.update(activity_id="../etc")
    posted = cm.auto_share_workouts("ann", [g, o, bad], today)
    assert len(posted) == 2
    srcs = sorted(p["workout"]["source"] for p in cm.feed("bob")["items"])
    assert srcs == ["garmin", "oura"]
    assert cm.auto_share_workouts("ann", [g, o, bad], today) == []  # once per activity, any source
    assert activity_key(5) == "5" and activity_key("whoop:x1") == "whoop:x1" and activity_key(True) is None
    assert source_of({"source": "nope"}) == "garmin" and source_of(None) == "garmin"


# -------------------------------------------------------------- backfill --
def test_turning_sharing_on_posts_the_last_few_days_once(fx) -> None:
    from garmin_mcp import workouts as wo
    from tests.test_workouts import O_RUN
    cm, today = fx.cm, NOON.date()
    acts = _acts(today) + [act(today - timedelta(days=2), 5, km=12), act(today - timedelta(days=3), 6, km=4)]
    ext = [{**wo.from_oura(O_RUN), "start": f"{(today - timedelta(days=1)).isoformat()}T07:04:00"}]
    calls: list[str] = []

    def workouts_of(uid: str):
        calls.append(uid)
        return acts, ext
    cm.workouts_of = workouts_of
    cm.put_settings("ann", {"audience": "friends"})  # an unrelated change: nothing posts
    assert calls == [] and cm.feed("bob")["items"] == []
    cm.put_settings("ann", {"share_workouts": True})
    feed = cm.feed("bob")["items"]
    # Today, yesterday, 2 days ago from Garmin plus yesterday's Oura run; not 3 days or a month ago.
    assert sorted(p["workout"]["km"] for p in feed) == sorted([10, 8, 12, 7.9])
    assert {p["workout"]["source"] for p in feed} >= {"oura"}
    assert all("avg_hr" not in p["workout"] for p in feed)
    # Once: saving again, or the regular sync, posts nothing new.
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.auto_share_workouts("ann", acts, today) == [] and cm.auto_share_external("ann", ext, today) == []
    assert cm.backfill("ann") == [] and len(cm.feed("bob")["items"]) == 4


def test_backfill_capped_and_only_when_sharing_turns_on(fx) -> None:
    cm, today = fx.cm, NOON.date()
    many = [act(today - timedelta(days=i % 3), 100 + i, km=3 + i) for i in range(9)]
    cm.workouts_of = lambda uid: (many, [])
    cm.put_settings("ann", {"share_workouts": False})  # declined: nothing
    assert cm.feed("bob")["items"] == []
    cm.put_settings("ann", {"share_workouts": True})
    assert len(cm.feed("bob")["items"]) == 5  # BACKFILL_MAX


def test_backfill_retries_when_workouts_unavailable(fx) -> None:
    cm, today = fx.cm, NOON.date()

    def boom(uid: str):
        raise RuntimeError("garmin down")
    cm.workouts_of = boom
    cm.spawn = lambda fn: None  # no background Feed catch-up here: this tests backfill on its own
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.feed("bob")["items"] == []
    cm.workouts_of = lambda uid: (_acts(today), [])
    assert len(cm.backfill("ann")) == 2  # still due: posts on the next sync
    assert cm.backfill("ann") == []


def test_late_synced_workout_from_two_days_ago_is_shared(fx) -> None:
    cm, today = fx.cm, NOON.date()
    cm.put_settings("ann", {"share_workouts": True})
    late = [act(today - timedelta(days=2), 7, km=15)]
    assert len(cm.auto_share_workouts("ann", late, today)) == 1  # uploaded by hand or synced late
    assert cm.auto_share_workouts("ann", [act(today - timedelta(days=3), 8, km=5)], today) == []  # older: never


def test_sharing_status_and_manual_share_has_no_duplicates(fx) -> None:
    cm, today = fx.cm, NOON.date()
    assert cm.settings("ann")["last_shared_at"] is None
    cm.put_settings("ann", {"share_workouts": True})
    ids = cm.auto_share_workouts("ann", _acts(today), today)
    assert cm.settings("ann")["last_shared_at"] == int(fx.clock.t)
    assert cm.workout_post("ann", 3) in ids and cm.workout_post("ann", 999) is None
    # Shared by hand (sharing off): auto-share later never posts a second copy.
    cm.put_settings("bob", {"share_workouts": False})
    card = workout_card(_acts(today), 3, today)
    cm.create("bob", {"text": "", "category": "other"}, workout=card)
    cm.claim_workout("bob", 3)
    cm.put_settings("bob", {"share_workouts": True})
    assert cm.auto_share_workouts("bob", _acts(today), today) and cm.workout_post("bob", 3) is not None
    mine = [p for p in (fx.store.user_doc("bob", "posts").load().get("posts") or {}).values()
            if (p.get("workout") or {}).get("activity_id") == 3]
    assert len(mine) == 1
