"""Comment likes, replies and edits: idempotent likes, one batched bell item per comment,
at most one push an hour, never for your own likes, blocked people hidden, replies thread one
level deep without double pushes, and only the author edits ("Edited" marker)."""

from __future__ import annotations

import pytest

from garmin_mcp.community import CommunityError
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _follow, cx  # noqa: F401  (fixture)


def _post(cx):  # noqa: ANN001, ANN202
    for u in ("bob", "cat", "dan"):
        if not cx.soc.follows(u, "ann"):
            _follow(cx.soc, u, "ann")
    return cx.cm.create("ann", {"text": "Long run done", "audience": "public"})


def test_like_is_idempotent_and_counts(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice work")
    v = cm.like_comment("cat", p["id"], c["id"])
    assert v["like_count"] == 1 and v["liked"] is True
    v = cm.like_comment("cat", p["id"], c["id"])  # again: still one
    assert v["like_count"] == 1
    v = cm.like_comment("dan", p["id"], c["id"])
    assert v["like_count"] == 2 and cm.comment_likers("ann", p["id"], c["id"]) == ["dan", "cat"]
    v = cm.like_comment("cat", p["id"], c["id"], on=False)
    assert v["like_count"] == 1 and v["liked"] is False
    view = cm.get("ann", p["id"])["comments"][0]
    assert view["like_count"] == 1 and view["liked"] is False


def test_like_bell_item_batches_and_push_once(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice work")
    cx.pushes.clear()
    cm.like_comment("cat", p["id"], c["id"])
    cm.like_comment("dan", p["id"], c["id"])
    # one push to bob within the hour, none to the likers or the post owner
    assert [to for to, _, _ in cx.pushes] == ["bob"]
    assert cx.pushes[0][1] == "Cat liked your comment"
    items = cm.likes_for("bob")
    assert len(items) == 1 and items[0]["by"] == "dan" and items[0]["others"] == 1
    # unliking takes them out of the item; nobody left -> no item
    cm.like_comment("dan", p["id"], c["id"], on=False)
    cm.like_comment("cat", p["id"], c["id"], on=False)
    assert cm.likes_for("bob") == []


def test_own_like_never_notifies(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice work")
    cx.pushes.clear()
    cm.like_comment("bob", p["id"], c["id"])
    assert cx.pushes == [] and cm.likes_for("bob") == []


def test_blocked_people_hidden_and_cannot_like(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice work")
    cm.like_comment("cat", p["id"], c["id"])
    cx.soc.block("bob", "cat")
    assert cm.likes_for("bob") == []
    assert cm.comment_likers("dan", p["id"], c["id"]) == ["cat"]
    with pytest.raises(CommunityError):
        cm.like_comment("cat", p["id"], c["id"])


def test_likes_follow_post_visibility(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = cm.create("ann", {"text": "just me", "audience": "private"})
    c = cm.comment("ann", p["id"], "note to self")
    with pytest.raises(CommunityError):
        cm.like_comment("bob", p["id"], c["id"])


def test_replies_thread_one_level_without_double_push(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c1 = cm.comment("bob", p["id"], "Nice work")
    cx.pushes.clear()
    cx.clock.t += 3601  # past the one-push-per-post-per-hour window
    r1 = cm.comment("cat", p["id"], "Agreed", reply_to=c1["id"])
    assert r1["parent"] == c1["id"]
    # bob (parent author) and ann (post owner) each get exactly one push
    who = sorted(to for to, _, _ in cx.pushes)
    assert who == ["ann", "bob"]
    r2 = cm.comment("dan", p["id"], "Me too", reply_to=r1["id"])  # reply to a reply joins the thread
    assert r2["parent"] == c1["id"]


def test_edit_only_by_author_marks_edited(cx) -> None:  # noqa: F811
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice wrok")
    with pytest.raises(CommunityError):
        cm.edit_comment("ann", p["id"], c["id"], "hijack")
    v = cm.edit_comment("bob", p["id"], c["id"], "Nice work")
    assert v["text"] == "Nice work" and v["edited"] and v["can_edit"] is True
    view = cm.get("ann", p["id"])["comments"][0]
    assert view["edited"] and view["can_edit"] is False and view["can_delete"] is True
    with pytest.raises(CommunityError, match="Write a comment"):
        cm.edit_comment("bob", p["id"], c["id"], "   ")


def test_people_inbox_shows_batched_like(cx) -> None:  # noqa: F811
    from garmin_mcp.people import People
    from datetime import date
    cm = cx.cm
    p = _post(cx)
    c = cm.comment("bob", p["id"], "Nice work")
    cm.like_comment("cat", p["id"], c["id"])
    cm.like_comment("dan", p["id"], c["id"])
    ppl = People(cx.store, soc=cx.soc, feed=None, related=lambda a, b: True, person=lambda u: {"id": u, "name": u.title()},
                 name=lambda u: u.title(), home=lambda u: {"city": "", "state": ""}, today=lambda u: date(2026, 10, 18),
                 comment_likes=cm.likes_for)
    items = [i for i in ppl.inbox("bob")["items"] if i["kind"] == "comment_like"]
    assert len(items) == 1 and items[0]["title"] == "Dan and 1 other liked your comment"
    assert items[0]["open"] == {"k": "post", "id": p["id"], "comment": c["id"]}
