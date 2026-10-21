"""Ask a friend to share their workouts (community.Community.ask_friend) and the Feed's
"haven't shared yet" row (``waiting``): only people I follow who never answered, weekly at
most per pair, never someone who said no or already shares. Asking shares nothing."""

from __future__ import annotations

import pytest

from garmin_mcp.community import ASK_EVERY_S, CommunityError
from tests.test_friends_share import NOON, fx  # noqa: F401  (fixture)


def test_ask_once_a_week_and_only_the_undecided(fx) -> None:
    fx.clock.at = NOON
    cm = fx.cm  # bob follows ann
    assert cm.ask_status("bob", "ann") == {"can_ask": True}
    r = cm.ask_friend("bob", "ann")
    assert r["asked"] is True
    assert any(to == "ann" and t.startswith("Bob wants to see your workouts") for to, t, _ in fx.pushes)
    again = cm.ask_friend("bob", "ann")
    assert again["asked"] is False and again["reason"] == "asked_recently"
    fx.clock.t += ASK_EVERY_S + 1
    assert cm.ask_friend("bob", "ann")["asked"] is True
    assert cm.settings("ann")["sharing_effective"] is False  # asking never shares


def test_never_ask_a_no_a_yes_or_a_stranger(fx) -> None:
    cm = fx.cm
    cm.put_settings("ann", {"share_workouts": False})
    assert cm.ask_friend("bob", "ann") == {"asked": False, "reason": "said_no"}
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.ask_friend("bob", "ann")["reason"] == "shares"
    with pytest.raises(CommunityError):
        cm.ask_friend("ann", "bob")  # Ann doesn't follow Bob
    with pytest.raises(CommunityError):
        cm.ask_friend("bob", "bob")


def test_feed_waiting_row(fx) -> None:
    cm = fx.cm
    w = cm.feed("bob")["waiting"]
    assert [x["id"] for x in w] == ["ann"] and w[0]["asked_recently"] is False
    cm.ask_friend("bob", "ann")
    assert cm.feed("bob")["waiting"][0]["asked_recently"] is True
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.feed("bob")["waiting"] == []
    assert "waiting" not in cm.feed("bob", scope="clubs")


def test_waiting_row_rechecks_cached_people(fx) -> None:
    cm = fx.cm  # the followee scan is cached per viewer; blocks and unfollows still apply at once
    assert [x["id"] for x in cm.waiting("bob")] == ["ann"]
    cm.put_settings("ann", {"share_workouts": False})  # a no: never in the row
    assert cm.waiting("bob") == []
    cm._mine("ann").update(lambda d: d["settings"].pop("share_workouts"))  # undecided again
    assert [x["id"] for x in cm.waiting("bob")] == ["ann"]
    fx.soc.block("ann", "bob")
    assert cm.waiting("bob") == []


def test_share_ask_runs_once_without_rereading(fx) -> None:
    from tests.test_community import _follow
    fx.clock.at = NOON
    cm = fx.cm
    _follow(fx.soc, "cat", "bob")  # someone follows Bob, who never answered
    assert cm.ask_to_share("bob") is True
    assert any(to == "bob" and "want" in t for to, t, _ in fx.pushes)

    def boom(uid):
        raise AssertionError("asked already: no follower lookup or write each minute")
    cm._follower_names = boom  # type: ignore[method-assign]
    assert cm.ask_to_share("bob") is False


def test_feed_doctor_lists_no_workouts_for_someone_not_sharing(fx) -> None:
    from tests.test_friends_share import _acts
    acts = _acts(NOON.date())
    cm = fx.cm
    cm.workouts_of = lambda uid: (acts, [])
    d = cm.diagnose("ann")
    assert d["sharing"] == "unanswered" and d["workouts"] == []  # no dates or sources without consent
    assert cm.diagnose("ann", own=True)["workouts"]  # the owner looking at their own
    cm.put_settings("ann", {"share_workouts": True})
    assert cm.diagnose("ann")["workouts"]
