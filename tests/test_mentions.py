"""@mentions in feed posts and comments: tokens, who can be mentioned, forging, visibility,
blocks, the cap, one bell item + push per new mention, edits notify only new people, coach
accounts never mentionable, and the people inbox "mentioned you" item."""

from __future__ import annotations

import pytest

from garmin_mcp import mentions as mn
from garmin_mcp.community import CommunityError
from garmin_mcp.people import People
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _follow, cx  # noqa: F401  (fixture)


def tok(uid: str, name: str | None = None) -> str:
    return f"@[{name or uid.title()}]({uid})"


# ------------------------------------------------------------- tokens --
def test_token_helpers() -> None:
    t = f"Nice one {tok('bob')} and {tok('cat', 'Cat C')}! {tok('bob')}"
    assert mn.ids(t) == ["bob", "cat"]
    assert mn.display(t) == "Nice one @Bob and @Cat C! @Bob"
    assert mn.keep(t, ["cat"]) == f"Nice one @Bob and {tok('cat', 'Cat C')}! @Bob"
    assert mn.ids("no @mentions here, @[x]( ) bad") == []


# --------------------------------------------------------- comments --
def test_comment_mention_links_notifies_once_and_renders(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")  # cat follows ann: sees ann's friends posts
    _follow(cx.soc, "cat", "bob")  # and bob, so bob may mention cat
    p = cm.create("ann", {"text": "Long run done", "audience": "friends"})
    cx.pushes.clear()
    c = cm.comment("bob", p["id"], f"Great job, {tok('cat')} you should come next time")
    assert c["mentions"] == [{"id": "cat", "name": "Cat"}] and tok("cat") in c["text"]
    # cat: one bell item + one push that opens the post; ann (owner) got only the "commented" push
    who = [x[0] for x in cx.pushes]
    assert who.count("cat") == 1 and who.count("ann") == 1
    assert next(t for to, t, _ in cx.pushes if to == "cat") == "Bob mentioned you in a comment"
    items = cm.mentions_for("cat")
    assert len(items) == 1 and items[0]["cid"] == c["id"] and items[0]["text"].startswith("Great job, @Cat")
    # the view: the link for everyone who can see it, with the current name
    v = cm.get("ann", p["id"])
    assert v["comments"][-1]["mentions"] == [{"id": "cat", "name": "Cat"}]


def test_forged_and_unrelated_tokens_are_plain_text(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = cm.create("ann", {"text": "hi", "audience": "public"})
    # dan doesn't follow/know bob, isn't on the post: a hand-typed token is just text
    c = cm.comment("bob", p["id"], f"hey {tok('dan')} and {tok('ghost')}")
    assert c["mentions"] == [] and c["text"] == "hey @Dan and @Ghost"
    assert cm.mentions_for("dan") == []
    # a stored token not in the comment's mentions never renders as a link
    assert cm._shown_mentions("ann", {"text": f"x {tok('bob')}", "mentions": []}) == ("x @Bob", [])


def test_cannot_mention_someone_who_cannot_see_the_post(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "ann", "dan")  # ann follows dan, so ann may mention dan, but dan doesn't follow ann
    p = cm.create("ann", {"text": "friends only", "audience": "friends"})
    with pytest.raises(CommunityError, match="Dan can't see this post"):
        cm.comment("ann", p["id"], f"{tok('dan')} look")
    with pytest.raises(CommunityError, match="can't see this post"):
        cm.create("ann", {"text": f"{tok('dan')} hi", "audience": "private"})
    rows = {r["id"]: r["can_see"] for r in cm.mentionable("ann", p["id"])}
    assert rows.get("dan") is False and rows.get("bob") is True


def test_blocked_and_coach_never_mentioned(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    p = cm.create("ann", {"text": "x", "audience": "public"})
    cx.soc.block("cat", "bob")
    c = cm.comment("bob", p["id"], f"{tok('cat')} hi {tok('coach_zed', 'Zed')}")
    assert c["mentions"] == [] and cm.mentions_for("cat") == []
    assert all(r["id"] not in ("cat", "coach_zed") for r in cm.mentionable("bob", p["id"]))


def test_cap_of_mentions(cx, monkeypatch) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    monkeypatch.setattr(mn, "MAX_MENTIONS", 1)
    p = cm.create("ann", {"text": "x", "audience": "public"})
    _follow(cx.soc, "ann", "bob")
    with pytest.raises(CommunityError, match="Mention up to 1"):
        cm.comment("ann", p["id"], f"{tok('bob')} {tok('cat')}")


def test_length_counts_what_people_read(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = cm.create("ann", {"text": "x", "audience": "public"})
    _follow(cx.soc, "ann", "bob")
    body = f"{tok('bob', 'B' * 60)} " + "y" * 200  # > 280 stored, < 280 shown
    assert cm.comment("ann", p["id"], body)["mentions"][0]["id"] == "bob"


# -------------------------------------------------------------- posts --
def test_post_mentions_and_edit_notifies_only_new(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    _follow(cx.soc, "ann", "bob")
    _follow(cx.soc, "ann", "cat")
    cx.pushes.clear()
    p = cm.create("ann", {"text": f"Ride with {tok('bob')}", "audience": "friends"})
    assert [m["id"] for m in p["mentions"]] == ["bob"]
    assert [to for to, *_ in cx.pushes] == ["bob"]
    cx.pushes.clear()
    p2 = cm.update("ann", p["id"], {"text": f"Ride with {tok('bob')} and {tok('cat')}"})
    assert [m["id"] for m in p2["mentions"]] == ["bob", "cat"]
    assert [to for to, *_ in cx.pushes] == ["cat"]  # bob isn't told twice
    assert len(cm.mentions_for("bob")) == 1 and cm.mentions_for("bob")[0]["where"] == "post"
    # removing a mention removes the bell item
    cm.update("ann", p["id"], {"text": "Ride solo"})
    assert cm.mentions_for("bob") == [] and cm.mentions_for("cat") == []


def test_deleted_comment_drops_bell_item(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    p = cm.create("ann", {"text": "x", "audience": "friends"})
    _follow(cx.soc, "ann", "cat")
    c = cm.comment("ann", p["id"], f"{tok('cat')} join?")
    assert len(cm.mentions_for("cat")) == 1
    cm.delete_comment("ann", p["id"], c["id"])
    assert cm.mentions_for("cat") == []


def test_people_inbox_shows_mention(cx) -> None:  # noqa: F811
    cm = cx.cm
    _follow(cx.soc, "cat", "ann")
    _follow(cx.soc, "ann", "cat")
    p = cm.create("ann", {"text": "x", "audience": "friends"})
    c = cm.comment("ann", p["id"], f"{tok('cat')} you in?")
    ppl = People(cx.store, soc=cx.soc, feed=None, related=lambda a, b: True, person=lambda u: {"id": u},
                 name=lambda u: u.title(), home=lambda u: {}, today=lambda u: cx.clock.at.date(), mentions=cm.mentions_for)
    it = next(i for i in ppl.inbox("cat")["items"] if i["kind"] == "mention")
    assert it["title"] == "Ann mentioned you in a comment"
    assert it["open"] == {"k": "post", "id": p["id"], "comment": c["id"]}


# ---------------------------------------------------------------- http --
def test_http_mentionable_comment_bell_and_push_link(env, tmp_path) -> None:  # noqa: F811
    import asyncio

    from tests.test_community import H, _clients, _setup

    apps, push, _ = _setup(env, tmp_path)
    urls: list[str] = []
    orig = push.send

    def send(user_id, title, body, url="/app/", ttl=0):
        urls.append(url)
        return orig(user_id, title, body, url=url, ttl=ttl)
    push.send = send

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        for who, to in ((bob, "ann"), (cat, "ann"), (cat, "bob")):  # bob, cat follow ann; cat follows bob
            await who.post("/app/api/social/follow", headers=H, json={"email": f"{to}@x.com"})
        owner = {"ann": ann, "bob": bob}
        for name, cl in owner.items():
            for e in (await cl.get("/app/api/social")).json()["pending_in"]:
                await cl.post(f"/app/api/social/requests/{e['edge_id']}/accept", headers=H, json={})
        post = (await ann.post("/app/api/community/posts", headers=H, json={"text": "Long run", "audience": "friends"})).json()["post"]
        rows = (await bob.get(f"/app/api/community/mentionable?pid={post['id']}")).json()["people"]
        assert {r["id"]: r["can_see"] for r in rows} == {"ann": True, "cat": True}
        assert rows[0]["name"] == "Ann"
        r = await bob.post(f"/app/api/community/posts/{post['id']}/comments", headers=H,
                           json={"text": "Nice! @[Cat](cat) come along next time"})
        com = r.json()["comment"]
        assert r.status_code == 201 and com["mentions"] == [{"id": "cat", "name": "Cat"}]
        assert any(u.startswith(f"/app/?open=post&id={post['id']}&c={com['id']}") for u in urls)
        inbox = (await cat.get("/app/api/notifications")).json()
        it = next(i for i in inbox["items"] if i["kind"] == "mention")
        assert it["open"] == {"k": "post", "id": post["id"], "comment": com["id"]}
        full = (await cat.get(f"/app/api/community/posts/{post['id']}")).json()["post"]
        assert full["comments"][-1]["mentions"] == [{"id": "cat", "name": "Cat"}]
        # a coach account can't use it
        coach = next(v for k, v in c.items() if k.startswith("coach_"))
        assert (await coach.get("/app/api/community/mentionable")).status_code == 403
    asyncio.run(go())
