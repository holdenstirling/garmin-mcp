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
