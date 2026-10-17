"""Direct messages (messages.py, messages_web.py): who can message whom, requests, blocks,
privacy of shared workout cards, unread counts, paging, group limits and the HTTP routes."""

from __future__ import annotations

import asyncio

import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.messages import MAX_GROUP, PAGE, DMError, Messages
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _setup
from tests.test_social import H


class World:
    def __init__(self) -> None:
        self.athletes = {"ann", "bob", "cat", "dan", *[f"u{i}" for i in range(20)]}
        self.edges: set[tuple[str, str]] = set()
        self.blocks: set[tuple[str, str]] = set()
        self.circle: set[frozenset[str]] = set()
        self.t = 1000.0

    def mutual(self, a: str, b: str) -> None:
        self.edges |= {(a, b), (b, a)}


@pytest.fixture
def dm(tmp_path, fernet_key):
    w = World()

    def card(uid: str, ref: dict) -> dict | None:
        if ref.get("type") == "workout" and ref.get("kind") == "activity" and ref.get("id") == "7" and uid == "ann":
            return {"title": "Lunch Run", "sport": "run", "date": "2026-10-16", "minutes": 40, "km": 8.0, "pace": 300}
        return None

    def clock() -> float:
        w.t += 1
        return w.t
    m = Messages(AppStore(tmp_path, fernet_key), is_athlete=lambda u: u in w.athletes,
                 follows=lambda a, b: (a, b) in w.edges, blocked=lambda a, b: (a, b) in w.blocks or (b, a) in w.blocks,
                 shared_circle=lambda a, b: frozenset((a, b)) in w.circle, card_for=card, clock=clock)
    return m, w


def test_mutual_friends_chat_freely_and_unread_counts(dm) -> None:
    m, w = dm
    w.mutual("ann", "bob")
    c = m.start("ann", ["bob"])
    assert c["kind"] == "direct" and c["status"] == "active"
    msg, notify = m.send("ann", c["id"], "Long run Sunday?")
    assert notify == ["bob"] and msg["mine"]
    assert m.unread("bob") == 1 and m.unread("ann") == 0
    lst = m.list("bob")
    assert [x["id"] for x in lst["convs"]] == [c["id"]] and lst["convs"][0]["unread"] and not lst["requests"]
    page = m.messages("bob", c["id"])
    assert page["msgs"][0]["text"] == "Long run Sunday?" and not page["msgs"][0]["mine"]
    assert m.unread("bob") == 0  # opening marks it read
    # Starting again with the same person reuses the chat.
    assert m.start("bob", ["ann"])["id"] == c["id"]


def test_strangers_get_a_request_they_can_accept_or_decline(dm) -> None:
    m, w = dm
    c = m.start("ann", ["cat"])
    m.send("ann", c["id"], "Hi from the track!")
    lst = m.list("cat")
    assert not lst["convs"] and [x["id"] for x in lst["requests"]] == [c["id"]] and lst["unread"] == 1
    with pytest.raises(DMError) as e:
        m.send("cat", c["id"], "hey")
    assert e.value.status == 409  # accept first
    m.accept("cat", c["id"])
    m.send("cat", c["id"], "hey!")
    assert m.list("cat")["convs"][0]["id"] == c["id"]
    # A declined request disappears for them; the sender isn't told and nobody gets notified.
    c2 = m.start("dan", ["cat"])
    m.decline("cat", c2["id"])
    _, notify = m.send("dan", c2["id"], "still there?")
    assert notify == [] and all(x["id"] != c2["id"] for x in m.list("cat")["requests"] + m.list("cat")["convs"])
    # Club mates don't need a request.
    w.circle.add(frozenset(("dan", "bob")))
    assert m.start("dan", ["bob"])["waiting_on"] == []


def test_blocked_people_cant_message_and_chats_disappear(dm) -> None:
    m, w = dm
    w.mutual("ann", "bob")
    c = m.start("ann", ["bob"])
    w.blocks.add(("bob", "ann"))
    with pytest.raises(DMError) as e:
        m.messages("ann", c["id"])
    assert e.value.status == 404
    with pytest.raises(DMError):
        m.send("ann", c["id"], "hello?")
    with pytest.raises(DMError) as e:
        m.start("ann", ["bob"])
    assert e.value.status == 404
    assert m.list("bob")["convs"] == []
    with pytest.raises(DMError) as e:
        m.start("coach_x", ["ann"])
    assert e.value.status == 403


def test_shared_workout_is_a_privacy_limited_snapshot(dm) -> None:
    m, w = dm
    w.mutual("ann", "bob")
    c = m.start("ann", ["bob"])
    m.send("ann", c["id"], "", {"type": "workout", "ref": {"kind": "activity", "id": "7"}})
    seen = m.messages("bob", c["id"])["msgs"][0]["att"]
    assert seen["title"] == "Lunch Run" and seen["km"] == 8.0 and not seen["mine"] and "ref" not in seen
    assert not {"avg_hr", "max_hr", "lat", "lon", "hr"} & set(seen)
    mine = m.messages("ann", c["id"])["msgs"][0]["att"]
    assert mine["mine"] and mine["ref"] == {"kind": "activity", "id": "7"}
    # You can only share your own things.
    with pytest.raises(DMError) as e:
        m.send("bob", c["id"], "", {"type": "workout", "ref": {"kind": "activity", "id": "7"}})
    assert e.value.status == 404
    assert m.list("bob")["convs"][0]["last"]["preview"].startswith("Shared a workout")


def test_paging_reactions_mute_leave_and_limits(dm) -> None:
    m, w = dm
    w.mutual("ann", "bob")
    c = m.start("ann", ["bob"])
    m._sends.clear()
    for i in range(PAGE + 5):
        m.send("ann", c["id"], f"m{i}")
        m._sends.clear()
    p1 = m.messages("bob", c["id"])
    assert len(p1["msgs"]) == PAGE and p1["more"] and p1["msgs"][-1]["text"] == f"m{PAGE + 4}"
    p2 = m.messages("bob", c["id"], before=p1["msgs"][0]["ts"])
    assert [x["text"] for x in p2["msgs"]] == [f"m{i}" for i in range(5)] and not p2["more"]
    r = m.react("bob", c["id"], p1["msgs"][0]["id"], "🔥")
    assert r["reactions"]["🔥"] == {"n": 1, "mine": True}
    with pytest.raises(DMError):
        m.react("bob", c["id"], p1["msgs"][0]["id"], "<script>")
    m.mute("bob", c["id"], True)
    _, notify = m.send("ann", c["id"], "muted?")
    assert notify == [] and m.unread("bob") == 0
    m.leave("bob", c["id"])
    assert m.list("bob")["convs"] == []
    with pytest.raises(DMError):
        m.start("ann", [f"u{i}" for i in range(MAX_GROUP)])
    g = m.start("ann", [f"u{i}" for i in range(MAX_GROUP - 1)], name="  Saturday   crew ")
    assert g["kind"] == "group" and g["name"] == "Saturday crew"
    with pytest.raises(DMError):
        m.send("ann", c["id"], "x" * 2001)
    m._clock = lambda: w.t  # a burst within one minute
    with pytest.raises(DMError) as e:
        for _ in range(40):
            m.send("ann", g["id"], "spam")
    assert e.value.status == 429


def test_http_flow_list_start_send_read_and_coach_403(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob = c["ann"], c["bob"]
        for a, b in (("ann", "bob"), ("bob", "ann")):
            await c[a].post("/app/api/social/follow", headers=H, json={"email": f"{b}@x.com"})
            eid = (await c[b].get("/app/api/social")).json()["pending_in"][0]["edge_id"]
            await c[b].post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        ppl = (await ann.get("/app/api/dm/people")).json()["people"]
        assert [p["id"] for p in ppl] == ["bob"] and ppl[0]["name"] == "Bob"
        r = await ann.post("/app/api/dm", headers=H, json={"to": ["bob"], "text": "Track at 6?"})
        assert r.status_code == 201, r.text
        cid = r.json()["conv"]["id"]
        assert r.json()["conv"]["members"][0]["name"] == "Bob"
        assert (await bob.get("/app/api/dm/unread")).json()["unread"] == 1
        r = await bob.get(f"/app/api/dm/{cid}")
        assert r.status_code == 200 and r.json()["msgs"][0]["text"] == "Track at 6?"
        r = await bob.post(f"/app/api/dm/{cid}/messages", headers=H, json={"text": "In!"})
        assert r.status_code == 201 and r.json()["msg"]["mine"]
        # Share a recorded workout (ann's activity 11): a snapshot without heart rate.
        r = await ann.post(f"/app/api/dm/{cid}/messages", headers=H,
                           json={"att": {"type": "workout", "ref": {"kind": "activity", "id": "11"}}})
        assert r.status_code == 201, r.text
        att = (await bob.get(f"/app/api/dm/{cid}")).json()["msgs"][-1]["att"]
        assert att["km"] == 15 and "avg_hr" not in att and "ref" not in att
        assert (await c["cat"].get(f"/app/api/dm/{cid}")).status_code == 404
        assert (await ann.post(f"/app/api/dm/{cid}/messages", headers={}, json={"text": "x"})).status_code == 403
        coach = next(k for k in c if k.startswith("coach_"))
        assert (await c[coach].get("/app/api/dm")).status_code == 403
        assert any("Ann" in p[1] for p in push.sent)
    asyncio.run(go())
