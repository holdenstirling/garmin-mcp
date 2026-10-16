"""Shared training blocks: create/join/leave, each member's own plan on the same weeks (no
overwrite without confirm), visibility (mutual friends / club only, blocks), Sunday check-in and
Monday recap moments, recap counts, nudge rate limit + coalesced push, caps, coach 403.

Clock-independent: every service gets an injected "now" (the agent's clock is pinned), and
quiet hours are part of the schedule assertions."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import blocks as bm
from garmin_mcp.appstore import AppStore
from garmin_mcp.blocks import BlockError, Blocks, PlanHooks
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import iter_sessions
from garmin_mcp.social import Social
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_social import BASE, FakePush, H

TZ = ZoneInfo("America/Denver")
WED = datetime(2026, 10, 14, 9, 0, tzinfo=TZ)        # a Wednesday morning
NEXT_MON = date(2026, 10, 19)
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat", "dan@x.com": "dan"}


class FakePlan:
    """Records installs; ``goals`` = who already has an active goal."""

    def __init__(self) -> None:
        self.goals: set[str] = set()
        self.installed: list[tuple[str, str, str]] = []

    def current(self, uid):
        return {"goal": "Spring marathon" if uid in self.goals else None, "has_plan": uid in self.goals,
                "has_goal": uid in self.goals}

    def install(self, uid, block, mode):
        self.installed.append((uid, block["id"], mode))
        return "built" if mode == "new" else "kept"


@pytest.fixture
def bx(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    s = SimpleNamespace(now=WED, follows=set(), blocked=set(), weeks={}, moments=[], clubs={}, admins=set(),
                        events={}, clock=1_000_000.0)
    athletes = {"ann", "bob", "cat", "dan", "eve", "fay", "gus", "hal", "ivy", "jo", "kim", "lu", "max", "ned"}

    def week(uid, day):
        return s.weeks.get((uid, bm.monday_of(day).isoformat()), (0, 4))

    def moment(uid, m):
        s.moments.append((uid, m))
        return "posted"
    plan = FakePlan()
    b = Blocks(store, now=lambda uid: s.now, is_athlete=lambda u: u in athletes,
               follows=lambda a, b: (a, b) in s.follows, blocked=lambda a, b: (a, b) in s.blocked or (b, a) in s.blocked,
               names=lambda u: u.title(), week=week, plan=plan, events=lambda u: s.events.get(u, []),
               club_member=lambda cid, u: u in s.clubs.get(cid, set()),
               club_admin=lambda cid, u: (cid, u) in s.admins, club_name=lambda cid, u: "Run Crew",
               moment=moment, clock=lambda: s.clock)
    return SimpleNamespace(b=b, s=s, plan=plan, store=store)


def mutual(s, a, b):
    s.follows |= {(a, b), (b, a)}


def make(bx, owner="ann", invite=(), **kw):
    body = {"template": "5k_8", "start": NEXT_MON.isoformat(), "invite": list(invite), **kw}
    return bx.b.create(owner, body)["block"]


# ------------------------------------------------------------- lifecycle --
def test_create_join_leave_and_owner_handoff(bx) -> None:
    mutual(bx.s, "ann", "bob")
    bx.s.follows.add(("ann", "cat"))  # one-way: not a mutual friend
    with pytest.raises(BlockError) as e:
        make(bx, invite=["cat"])
    assert e.value.status == 403
    blk = make(bx, invite=["bob"])
    assert blk["week"] == {"n": 0, "of": 8, "monday": "2026-10-19", "state": "upcoming", "days_to_start": 5}
    assert blk["end"] == "2026-12-13" and blk["owner"] and blk["members"] == 1
    assert ("bob", f"blockinvite:{blk['id']}") in [(u, m["key"]) for u, m in bx.s.moments]
    inv = bx.b.overview("bob")["invites"]
    assert [i["id"] for i in inv] == [blk["id"]] and inv[0]["invited_by"] == "ann"
    assert bx.b.overview("cat")["invites"] == []
    with pytest.raises(BlockError) as e:
        bx.b.join("cat", blk["id"], {"plan": "keep"})
    assert e.value.status == 404
    out = bx.b.join("bob", blk["id"], {"plan": "keep"})
    assert out["plan"] == "kept" and out["block"]["members"] == 2
    with pytest.raises(BlockError) as e:
        bx.b.join("bob", blk["id"], {"plan": "keep"})
    assert e.value.status == 409
    # Leaving never touches the plan (no install/uninstall call); the owner hands the block on.
    n = len(bx.plan.installed)
    bx.b.leave("ann", blk["id"])
    assert len(bx.plan.installed) == n
    v = bx.b.view("bob", blk["id"])
    assert v["owner"] is True and [p["user_id"] for p in v["people"]] == ["bob"]
    with pytest.raises(BlockError):
        bx.b.view("ann", blk["id"])  # no longer a member nor invited
    bx.b.leave("bob", blk["id"])
    assert bx.b.overview("bob")["blocks"] == []


def test_join_needs_explicit_confirm_to_replace_a_goal(bx) -> None:
    mutual(bx.s, "ann", "bob")
    blk = make(bx, invite=["bob"])
    bx.plan.goals.add("bob")
    for body in ({}, {"plan": "new"}, {"plan": "new", "confirm_replace": "yes"}):
        with pytest.raises(BlockError) as e:
            bx.b.join("bob", blk["id"], body)
        assert e.value.status == 409 and e.value.code == "confirm_plan"
        assert e.value.body()["current"]["goal"] == "Spring marathon"
    assert not [x for x in bx.plan.installed if x[0] == "bob"]  # nothing changed
    bx.b.join("bob", blk["id"], {"plan": "new", "confirm_replace": True})
    assert ("bob", blk["id"], "new") in bx.plan.installed
    # The owner too: no plan choice + an existing goal -> confirm first.
    bx.plan.goals.add("cat")
    with pytest.raises(BlockError) as e:
        bx.b.create("cat", {"template": "half_12", "start": NEXT_MON.isoformat()})
    assert e.value.code == "confirm_plan" and bx.b.overview("cat")["blocks"] == []


def test_caps_members_and_active_blocks(bx) -> None:
    for i in range(bm.MAX_ACTIVE):
        make(bx, start=(NEXT_MON + timedelta(weeks=i)).isoformat())
    with pytest.raises(BlockError) as e:
        make(bx)
    assert e.value.status == 409
    people = ["bob", "cat", "dan", "eve", "fay", "gus", "hal", "ivy", "jo", "kim", "lu", "max", "ned"]
    for p in people:
        mutual(bx.s, "bob", p)
    blk = bx.b.create("bob", {"template": "consistency_6", "start": NEXT_MON.isoformat(), "invite": people[1:11],
                              "plan": "keep"})["block"]
    bx.b.invite("bob", blk["id"], people[11:])
    for p in people[1:12]:
        bx.b.join(p, blk["id"], {"plan": "keep"})
    assert bx.b.view("bob", blk["id"])["members"] == bm.MAX_MEMBERS
    with pytest.raises(BlockError) as e:
        bx.b.join("ned", blk["id"], {"plan": "keep"})
    assert e.value.status == 409 and "full" in e.value.message


def test_start_must_be_a_coming_monday_and_owner_ends(bx) -> None:
    for start, msg in (("2026-10-20", "Monday"), ("2026-10-05", "later"), ("2027-03-01", "within")):
        with pytest.raises(BlockError) as e:
            bx.b.create("ann", {"template": "5k_8", "start": start})
        assert msg in e.value.message
    mutual(bx.s, "ann", "bob")
    blk = make(bx, invite=["bob"])
    bx.b.join("bob", blk["id"], {"plan": "keep"})
    with pytest.raises(BlockError) as e:
        bx.b.end("bob", blk["id"])
    assert e.value.status == 403
    bx.b.end("ann", blk["id"])
    assert bx.b.view("bob", blk["id"])["status"] == "ended"
    assert bx.b.overview("ann")["active"] == 0


# ------------------------------------------------------------- visibility --
def test_visibility_mutuals_club_and_blocks(bx) -> None:
    mutual(bx.s, "ann", "bob")
    mutual(bx.s, "ann", "cat")
    bx.s.clubs["gabc123def456"] = {"ann", "dan", "eve"}
    with pytest.raises(BlockError) as e:
        make(bx, club="gabc123def456")
    assert e.value.status == 403  # only club admins open a block to the club
    bx.s.admins.add(("gabc123def456", "ann"))
    blk = make(bx, invite=["bob", "cat"], club="gabc123def456")
    # Club members see it (no invite needed); outsiders don't.
    assert [x["id"] for x in bx.b.overview("dan")["clubs"]] == [blk["id"]]
    assert bx.b.overview("fay")["clubs"] == []
    with pytest.raises(BlockError):
        bx.b.view("fay", blk["id"])
    prev = bx.b.view("dan", blk["id"])
    assert prev["member"] is False and "people" not in prev  # a card, never people or numbers
    bx.b.join("dan", blk["id"], {"plan": "keep"})
    bx.b.join("bob", blk["id"], {"plan": "keep"})
    bx.b.join("cat", blk["id"], {"plan": "keep"})
    # Blocks either way: bob and cat never see each other; eve (blocked by the owner) can't join.
    bx.s.blocked.add(("bob", "cat"))
    assert "cat" not in [p["user_id"] for p in bx.b.view("bob", blk["id"])["people"]]
    assert "bob" not in [p["user_id"] for p in bx.b.view("cat", blk["id"])["people"]]
    with pytest.raises(BlockError):
        bx.b.nudge("bob", blk["id"], "cat")
    bx.s.blocked.add(("ann", "eve"))
    assert bx.b.overview("eve")["clubs"] == []
    with pytest.raises(BlockError):
        bx.b.join("eve", blk["id"], {"plan": "keep"})
    # An invite stops working once the inviter and invitee aren't mutual friends any more.
    mutual(bx.s, "ann", "gus")
    blk2 = make(bx, invite=["gus"], start=(NEXT_MON + timedelta(weeks=1)).isoformat())
    bx.s.follows.discard(("gus", "ann"))
    assert bx.b.overview("gus")["invites"] == []
    with pytest.raises(BlockError):
        bx.b.join("gus", blk2["id"], {"plan": "keep"})
    # Members only see done/planned: no health fields anywhere in a person row.
    row = bx.b.view("ann", blk["id"])["people"][0]
    assert set(row) == {"user_id", "name", "me", "owner", "done", "target", "closed", "behind", "cheered"}


# ------------------------------------------------- progress, check-in, recap --
def _running_block(bx):
    mutual(bx.s, "ann", "bob")
    blk = make(bx, invite=["bob"])
    bx.b.join("bob", blk["id"], {"plan": "keep"})
    return blk


def test_group_ring_from_published_numbers(bx) -> None:
    blk = _running_block(bx)
    bx.s.now = datetime(2026, 10, 21, 12, 0, tzinfo=TZ)  # Wednesday of week 1
    bx.s.weeks[("ann", "2026-10-19")] = (4, 4)
    bx.s.weeks[("bob", "2026-10-19")] = (1, 5)
    bx.b.publish("bob")
    v = bx.b.view("ann", blk["id"])  # publishes ann's own numbers, reads bob's stored ones
    assert v["week"]["n"] == 1 and v["week"]["state"] == "active"
    assert v["group"] == {"done": 5, "target": 9, "pct": 56, "closed": 1, "count": 2}
    bob = next(p for p in v["people"] if p["user_id"] == "bob")
    assert bob["behind"] is True and bob["closed"] is False


def test_sunday_checkin_schedule_respects_time_quiet_hours_and_toggle(bx) -> None:
    blk = _running_block(bx)

    def tick(when, uid="ann"):
        bx.s.now = when
        bx.s.clock += bm.TICK_EVERY_S + 1
        bx.s.moments.clear()
        bx.b.tick(uid)
        return [m for _, m in bx.s.moments if m["type"] == "block_checkin"]
    assert tick(datetime(2026, 10, 25, 14, 0, tzinfo=TZ)) == []        # Sunday, too early
    assert tick(datetime(2026, 10, 25, 22, 0, tzinfo=TZ)) == []        # quiet hours
    assert tick(datetime(2026, 10, 24, 16, 0, tzinfo=TZ)) == []        # Saturday
    got = tick(datetime(2026, 10, 25, 16, 0, tzinfo=TZ))
    assert len(got) == 1 and got[0]["key"] == f"blockcheckin:{blk['id']}:2026-10-19"
    assert "week 1" in got[0]["text"] and len(got[0]["text"]) <= 140
    assert [a["feel"] for a in got[0]["actions"]] == ["strong", "okay", "tough"]
    # A second tick within 10 minutes does nothing; once checked in, no more prompts.
    bx.s.moments.clear()
    bx.b.tick("ann")
    assert bx.s.moments == []
    bx.b.checkin("ann", blk["id"], "strong", "Legs felt good")
    assert tick(datetime(2026, 10, 25, 17, 0, tzinfo=TZ)) == []
    # Toggle off: bob gets none.
    bx.b.set_checkins("bob", blk["id"], False)
    assert tick(datetime(2026, 10, 25, 17, 0, tzinfo=TZ), "bob") == []
    v = bx.b.view("bob", blk["id"])
    assert [(c["user_id"], c["feel"], c["note"]) for c in v["checkins"]] == [("ann", "strong", "Legs felt good")]
    # Before the block starts: no prompt.
    assert tick(datetime(2026, 10, 18, 16, 0, tzinfo=TZ)) == []


def test_monday_recap_counts_and_late_checkin(bx) -> None:
    blk = _running_block(bx)
    bx.s.weeks[("ann", "2026-10-19")] = (4, 4)
    bx.s.weeks[("bob", "2026-10-19")] = (2, 5)

    def tick(when, uid="ann"):
        bx.s.now = when
        bx.s.clock += bm.TICK_EVERY_S + 1
        bx.s.moments.clear()
        bx.b.tick(uid)
        return [m for _, m in bx.s.moments if m["type"] == "block_recap"]
    assert tick(datetime(2026, 10, 26, 7, 30, tzinfo=TZ)) == []        # Monday, before 08:00
    got = tick(datetime(2026, 10, 26, 8, 30, tzinfo=TZ))
    assert len(got) == 1 and got[0]["text"].startswith("🏁 1 of 2 of you closed week 1")
    assert got[0]["key"] == f"blockrecap:{blk['id']}:2026-10-19"
    b = bx.store.global_doc("blocks").load()["blocks"][blk["id"]]
    assert bx.b.recap_counts(b, "2026-10-19") == (1, 2)
    bx.s.weeks[("bob", "2026-10-19")] = (5, 5)
    bx.s.now = datetime(2026, 10, 26, 9, 0, tzinfo=TZ)
    bx.b.publish("bob", date(2026, 10, 25))
    b = bx.store.global_doc("blocks").load()["blocks"][blk["id"]]
    assert bx.b.recap_counts(b, "2026-10-19") == (2, 2)
    # Monday morning still answers last week's question.
    c = bx.b.checkin("bob", blk["id"], "tough")
    assert c["week"] == "2026-10-19"
    with pytest.raises(BlockError):
        bx.b.checkin("bob", blk["id"], "meh")


def test_nudge_once_a_day_per_pair_and_coalesced_push(bx) -> None:
    mutual(bx.s, "ann", "bob")
    mutual(bx.s, "ann", "cat")
    blk = make(bx, invite=["bob", "cat"])
    bx.b.join("bob", blk["id"], {"plan": "keep"})
    bx.b.join("cat", blk["id"], {"plan": "keep"})
    bx.s.now = datetime(2026, 10, 23, 12, 0, tzinfo=TZ)  # Friday of week 1
    out = bx.b.nudge("bob", blk["id"], "ann")
    assert out["push"] == "Bob cheered you on. You've got this!"
    assert any(m["type"] == "block_cheer" for u, m in bx.s.moments if u == "ann")
    with pytest.raises(BlockError) as e:
        bx.b.nudge("bob", blk["id"], "ann")
    assert e.value.status == 429
    bx.s.clock += 60
    assert bx.b.nudge("cat", blk["id"], "ann")["push"] is None  # inside the hour: rides the next push
    bx.s.clock += bm.COALESCE_S
    bx.s.now = datetime(2026, 10, 24, 12, 0, tzinfo=TZ)
    assert bx.b.nudge("bob", blk["id"], "ann")["push"] == "Bob cheered you on (+1 more). You've got this!"
    # Quiet hours: no push at all.
    bx.s.clock += bm.COALESCE_S
    bx.s.now = datetime(2026, 10, 24, 22, 30, tzinfo=TZ)
    assert bx.b.nudge("ann", blk["id"], "cat")["push"] is None
    # Someone who closed their week can't be nudged; nor yourself.
    bx.s.now = datetime(2026, 10, 25, 12, 0, tzinfo=TZ)
    bx.s.weeks[("bob", "2026-10-19")] = (5, 5)
    bx.b.publish("bob")
    with pytest.raises(BlockError) as e:
        bx.b.nudge("cat", blk["id"], "bob")
    assert e.value.status == 409
    with pytest.raises(BlockError):
        bx.b.nudge("cat", blk["id"], "cat")


# --------------------------------------------- real plan builder alignment --
def _agent(env):
    agent, _ = env.agent([])
    agent._clock = lambda: WED.timestamp()
    agent.plans._pause = 0
    return agent


def test_each_member_gets_own_plan_on_the_same_weeks(env, tmp_path) -> None:
    agent = _agent(env)
    store = env.store
    hooks = PlanHooks(coach=agent.coach, plans=agent.plans, events=agent.events, now=lambda u: WED)
    follows = {("ann", "bob"), ("bob", "ann")}
    b = Blocks(store, now=lambda u: WED, is_athlete=lambda u: u in ("ann", "bob"), follows=lambda x, y: (x, y) in follows,
               blocked=lambda x, y: False, names=str.title, week=lambda u, d: (0, 3), plan=hooks,
               events=agent.events.list)
    agent.coach.update_athlete("ann", {"level": "new", "weekly_hours": 3, "available_days": ["tue", "thu", "sat"]})
    agent.coach.update_athlete("bob", {"level": "advanced", "weekly_hours": 7,
                                       "available_days": ["mon", "tue", "wed", "thu", "fri", "sun"], "long_day": "sun"})
    # Bob already has his own goal and plan.
    agent.coach.create_goal("bob", {"title": "Marathon", "distance": "marathon", "date": "2027-04-18"})
    agent.plans.build("bob")
    before = agent.plans.get("bob")
    blk = b.create("ann", {"template": "5k_8", "start": NEXT_MON.isoformat(), "invite": ["bob"]})["block"]
    with pytest.raises(BlockError) as e:
        b.join("bob", blk["id"], {})
    assert e.value.code == "confirm_plan"
    after = agent.plans.get("bob")
    assert after["weeks"] == before["weeks"] and agent.coach.active_goal("bob")["title"] == "Marathon"
    b.join("bob", blk["id"], {"plan": "new", "confirm_replace": True})
    pa, pb = agent.plans.get("ann"), agent.plans.get("bob")
    weeks = [w["start"] for w in pa["weeks"]]
    assert weeks == [w["start"] for w in pb["weeks"]] == [(NEXT_MON + timedelta(weeks=i)).isoformat() for i in range(8)]
    assert pa["origin"]["kind"] == pb["origin"]["kind"] == "block" and pa["race_date"] == "2026-12-13"
    assert not pa.get("race_changed") and not pa.get("events_changed")
    # Personalized: Bob's numbers give him more volume and his own days.
    mins = lambda p: sum(s.get("minutes") or 0 for _, _, s in iter_sessions(p))  # noqa: E731
    assert mins(pb) > mins(pa)
    days_a = {date.fromisoformat(d).weekday() for _, d, s in iter_sessions({"weeks": pa["weeks"][:-1]})
              if s["sport"] not in ("rest", "strength")}  # (race week's short sessions go on any day)
    assert days_a <= {1, 3, 5, 6}
    # His marathon goal is archived, not lost.
    goals = agent.coach.goals("bob")["goals"]
    assert [g["title"] for g in goals if g.get("archived_at")] == ["Marathon"]
    assert agent.coach.active_goal("bob")["title"] == "8-week 5K build"
    # A base template is all base/build: no taper or race week inside the block.
    hooks2 = Blocks(store, now=lambda u: WED, is_athlete=lambda u: u == "cat", follows=lambda x, y: False,
                    blocked=lambda x, y: False, names=str.title, week=lambda u, d: (0, 3), plan=hooks)
    tri = hooks2.create("cat", {"template": "tri_base_12", "start": NEXT_MON.isoformat()})["block"]
    pc = agent.plans.get("cat")
    assert len(pc["weeks"]) == 12 and {w["phase"] for w in pc["weeks"]} <= {"base", "build"}
    assert pc["weeks"][-1]["start"] <= tri["end"] and not any(s.get("kind") == "race" for _, _, s in iter_sessions(pc))


def test_our_race_block_targets_the_same_race_date(env) -> None:
    agent = _agent(env)
    follows = {("ann", "bob"), ("bob", "ann")}
    hooks = PlanHooks(coach=agent.coach, plans=agent.plans, events=agent.events, now=lambda u: WED)
    b = Blocks(env.store, now=lambda u: WED, is_athlete=lambda u: u in ("ann", "bob"),
               follows=lambda x, y: (x, y) in follows, blocked=lambda x, y: False, names=str.title,
               week=lambda u, d: (0, 3), plan=hooks, events=agent.events.list)
    ev = agent.events.create("ann", {"name": "Turkey Trot", "date": "2026-11-26", "type": "running", "distance": "10k"})
    t = b.templates("ann")
    assert [r["id"] for r in t["races"]] == [ev["id"]] and t["starts"][0] == NEXT_MON.isoformat()
    blk = b.create("ann", {"template": "race", "event_id": ev["id"], "start": NEXT_MON.isoformat(), "invite": ["bob"]})["block"]
    assert blk["weeks"] == 6 and blk["end"] == "2026-11-29" and blk["name"] == "Road to Turkey Trot"
    b.join("bob", blk["id"], {})  # no goal yet: no confirm needed
    for uid in ("ann", "bob"):
        p = agent.plans.get(uid)
        assert p["race_date"] == "2026-11-26" and p["weeks"][0]["start"] == NEXT_MON.isoformat()
        assert agent.coach.active_goal(uid)["date"] == "2026-11-26"
    bob_ev = [e for e in agent.events.list("bob") if e["name"] == "Turkey Trot"]
    assert len(bob_ev) == 1 and bob_ev[0]["date"] == "2026-11-26"


# ---------------------------------------------------------------- http --
def test_http_flow_feed_and_coach_403(env, tmp_path) -> None:
    agent = _agent(env)
    agent.stats.activities = lambda uid, fresh=False: (WED.date(), [])
    agent.moments.quiet = lambda local: False
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={k: v for k, v in ALLOW.items() if v != "dan"})
    push = FakePush()

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, push, None, ChatRunner(agent)))
    soc = Social(env.store, athletes=lambda: {k: v for k, v in ALLOW.items() if v != "dan"})
    for a, bb in (("ann", "bob"), ("bob", "ann")):
        soc.follow(a, email=f"{bb}@x.com")
        soc.accept(bb, next(e for e in soc.people(bb)["pending_in"] if e["user_id"] == a)["edge_id"])

    async def go() -> None:
        c = {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app(u)), base_url=BASE)
             for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}
        ann, bob, cat, coach = c["ann"], c["bob"], c["cat"], c[coach_user_id("c@x.com")]
        new = (await ann.get("/app/api/blocks/new")).json()
        assert [f["id"] for f in new["friends"]] == ["bob"] and len(new["templates"]) == 4
        assert (await ann.post("/app/api/blocks", json={"template": "5k_8", "start": new["starts"][0]})).status_code == 403
        r = await ann.post("/app/api/blocks", headers=H, json={"template": "5k_8", "start": new["starts"][0], "invite": ["bob"]})
        assert r.status_code == 201, r.text
        bid = r.json()["block"]["id"]
        assert any(p[0] == "bob" for p in push.sent)
        inv = (await bob.get("/app/api/blocks")).json()["invites"]
        assert inv[0]["invited_by"]["name"] == "Ann"
        assert (await cat.get(f"/app/api/blocks/{bid}")).status_code == 404
        r = await bob.post(f"/app/api/blocks/{bid}/join", headers=H, json={"plan": "keep"})
        assert r.status_code == 201 and [p["user"]["name"] for p in r.json()["block"]["people"]] == ["Ann", "Bob"]
        # Block feed: a Community post to club:b-<id> is seen by members only.
        r = await ann.post("/app/api/community/posts", headers=H,
                           json={"text": "Week 1, let's go", "category": "other", "audience": f"club:b-{bid}"})
        assert r.status_code == 201, r.text
        assert r.json()["post"]["club"]["name"] == "8-week 5K build"
        feed = (await bob.get(f"/app/api/community/feed?club=b-{bid}")).json()["items"]
        assert [p["text"] for p in feed] == ["Week 1, let's go"]
        assert (await cat.get(f"/app/api/community/feed?club=b-{bid}")).status_code == 404
        assert (await cat.post("/app/api/community/posts", headers=H,
                               json={"text": "hi", "audience": f"club:b-{bid}"})).status_code == 400
        # Coach accounts: 403 everywhere.
        assert (await coach.get("/app/api/blocks")).status_code == 403
        assert (await coach.get(f"/app/api/blocks/{bid}")).status_code == 403
        for path in ("/app/api/blocks", f"/app/api/blocks/{bid}/join", f"/app/api/blocks/{bid}/nudge",
                     f"/app/api/blocks/{bid}/checkin", f"/app/api/blocks/{bid}/leave"):
            assert (await coach.post(path, headers=H, json={})).status_code == 403, path
        assert (await bob.post(f"/app/api/blocks/{bid}/leave", headers=H, json={})).status_code == 200
        assert (await bob.get(f"/app/api/blocks/{bid}")).status_code == 404
    asyncio.run(go())
