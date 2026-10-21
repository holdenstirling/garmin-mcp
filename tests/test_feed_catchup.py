"""Friends' workouts that synced before their sharing took effect still reach the Feed
(community.Community.catch_up), with no duplicates, the same consent and block rules, and
late posts sorted by their own day."""

from __future__ import annotations

from datetime import timedelta

from garmin_mcp.community import feed_ts
from tests.test_community import _follow
from tests.test_friends_share import NOON, _acts, fx  # noqa: F401  (fixture)


def _ready(fx, acts):
    cm = fx.cm
    cm.spawn = lambda fn: fn()  # run the background catch-up inline
    cm.workouts_of = lambda uid: (acts if uid == "ann" else [], [])
    return cm


def test_earlier_consent_workout_synced_before_reaches_the_feed(fx) -> None:
    today = NOON.date()
    acts = _acts(today)
    cm = _ready(fx, acts)
    # The sync saw Ann's workouts while she had no sharing consent: nothing was posted then,
    # and the poller won't call them "new" again.
    assert cm.auto_share_workouts("ann", acts, today) == []
    fx.soc.put_settings("ann", {"workouts": True})  # her earlier friends-settings consent
    items = cm.feed("bob")["items"]  # Bob opens the Feed: the catch-up runs for the people in it
    assert sorted(i["workout"]["date"] for i in items) == sorted([(today - timedelta(days=1)).isoformat(),
                                                                 today.isoformat()])
    # Never older than the catch-up window (the 30-day-old run stays off).
    assert all(i["workout"]["date"] >= (today - timedelta(days=2)).isoformat() for i in items)


def test_catch_up_never_duplicates(fx) -> None:
    acts = _acts(NOON.date())
    cm = _ready(fx, acts)
    cm.put_settings("ann", {"share_workouts": True})
    first = cm.feed("bob")["items"]
    assert cm.catch_up("ann", force=True) == []
    cm.feed("bob")
    again = cm.feed("bob")["items"]
    assert sorted(i["id"] for i in again) == sorted(i["id"] for i in first)
    assert len({i["workout"]["activity_id"] for i in again}) == len(again)


def test_no_consent_or_blocked_stays_out(fx) -> None:
    acts = _acts(NOON.date())
    cm = _ready(fx, acts)
    assert cm.catch_up("ann", force=True) == []  # never said yes
    assert cm.feed("bob")["items"] == []
    cm.put_settings("ann", {"share_workouts": False})
    fx.soc.put_settings("ann", {"workouts": True})  # an explicit no here wins over the old setting
    assert cm.catch_up("ann", force=True) == [] and cm.feed("bob")["items"] == []
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.feed("bob")["items"]
    fx.soc.block("bob", "ann")
    assert cm.feed("bob")["items"] == []


def test_late_posts_sort_by_their_day(fx) -> None:
    today = NOON.date()
    fx.clock.t = NOON.timestamp()
    acts = _acts(today)
    cm = fx.cm
    cm.put_settings("ann", {"share_workouts": True})  # no workout source yet: nothing posted
    # Today's workout posts on its sync; yesterday's arrives two hours later through the catch-up.
    [today_post] = cm.auto_share_workouts("ann", [a for a in acts if a["activity_id"] == 3], today)
    fx.clock.t += 2 * 3600
    cm = _ready(fx, acts)
    late = cm.catch_up("ann", force=True)
    assert len(late) == 1
    items = cm.feed("bob")["items"]
    assert [i["id"] for i in items] == [today_post, late[0]]
    assert items[1]["workout"].get("late") is True and feed_ts({"created": fx.clock.t, "workout": items[1]["workout"]}) < fx.clock.t
    # A late post is never pinned as "just synced".
    assert cm.feed("ann")["pinned"] is None or cm.feed("ann")["pinned"]["id"] == today_post


def test_follow_needed(fx) -> None:
    acts = _acts(NOON.date())
    cm = _ready(fx, acts)
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.feed("cat")["items"] == []  # Cat doesn't follow Ann
    _follow(fx.soc, "cat", "ann")
    assert cm.feed("cat")["items"]


def test_stuck_claim_without_a_post_is_retried(fx) -> None:
    """A share claimed but never posted (an error in between) is retried by the catch-up."""
    acts = _acts(NOON.date())
    cm = _ready(fx, acts)
    cm.put_settings("ann", {"share_workouts": True})
    today = NOON.date()
    cm.auto_share_workouts("ann", acts, today)  # claims and posts today's run

    def lost(d):  # the post never got written (an error between claim and post)
        d["posts"] = {}
    cm._posts("ann").update(lost)
    assert "auto:3" in (cm._mine("ann").load().get("keys") or {})
    assert any(w["status"].startswith("claimed but never posted") for w in cm.diagnose("ann")["workouts"])
    cm.catch_up("ann", force=True)
    assert any(i["workout"]["activity_id"] == 3 for i in cm.feed("bob")["items"])
    assert not any(w["status"].startswith("claimed") for w in cm.diagnose("ann")["workouts"])


def test_deleted_workout_post_is_never_reposted(fx) -> None:
    acts = _acts(NOON.date())
    cm = _ready(fx, acts)
    cm.put_settings("ann", {"share_workouts": True})
    items = cm.feed("bob")["items"]
    assert items
    gone = items[0]
    cm.delete("ann", gone["id"])
    cm.catch_up("ann", force=True)
    after = cm.feed("bob")["items"]
    assert gone["workout"]["activity_id"] not in [i["workout"]["activity_id"] for i in after]
    assert any(w["status"] == "they deleted the post" for w in cm.diagnose("ann")["workouts"])
