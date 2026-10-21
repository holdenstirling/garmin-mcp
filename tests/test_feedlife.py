"""The Feed stays alive on rest days (feedlife.py): club runs and friends' shared races coming
up, new club members, and the Monday crew recap built only from shared workout posts.
Clock-independent: NOON is a fixed Wednesday."""

from __future__ import annotations

from datetime import timedelta

from garmin_mcp.feedlife import FeedLife, week_of
from tests.test_community import _follow
from tests.test_friends_share import NOON, fx  # noqa: F401  (fixture)

EVENTS: dict[str, list[dict]] = {}


def _life(fx) -> FeedLife:
    fx.clock.at = NOON
    return FeedLife(community=fx.cm, clubs=fx.grp, social=fx.soc, now=lambda u: fx.clock.at,
                    events=lambda u: EVENTS.get(u, []), store=fx.store, clock=lambda: fx.clock.t)


def _workout(fx, uid: str, day, *, km: float, minutes: int, title: str = "Run") -> None:
    card = {"activity_id": None, "source": "garmin", "sport": "running", "family": "run", "title": title,
            "date": day.isoformat(), "km": km, "minutes": minutes, "climb_m": None, "highlight": ""}
    fx.cm.create(uid, {"text": "", "category": "other", "audience": "friends"}, workout=card, limited=False)


def test_recap_counts_only_shared_posts_i_can_see(fx) -> None:
    life = _life(fx)
    last_mon = week_of(NOON.date()) - timedelta(days=7)
    _workout(fx, "ann", last_mon + timedelta(days=1), km=10, minutes=50)
    _workout(fx, "ann", last_mon + timedelta(days=3), km=21.1, minutes=110, title="Long run")
    _workout(fx, "bob", last_mon + timedelta(days=2), km=5, minutes=30)
    _workout(fx, "ann", NOON.date(), km=8, minutes=40)  # this week: not in last week's recap
    _workout(fx, "cat", last_mon + timedelta(days=2), km=99, minutes=500)  # Bob doesn't follow Cat
    r = life.recap("bob")
    assert r is not None and r["workouts"] == 3 and r["people"] == 2 and r["km"] == 36.1
    kinds = {s["kind"]: s for s in r["shoutouts"]}
    assert kinds["most"]["person"]["name"] == "Ann" and kinds["most"]["workouts"] == 2
    assert kinds["longest"]["minutes"] == 110 and kinds["longest"]["title"] == "Long run"
    assert "farthest" not in kinds  # same workout as the longest: one shout-out, not two
    # Cached for the week: a later post doesn't change Monday's card.
    _workout(fx, "bob", last_mon + timedelta(days=4), km=5, minutes=30)
    assert life.recap("bob")["workouts"] == 3
    # Thursday on: no recap card.
    fx.clock.at = NOON + timedelta(days=1)
    assert life.recap("bob") is None


def test_recap_hides_blocked_and_empty_weeks(fx) -> None:
    life = _life(fx)
    assert life.recap("bob") is None  # nobody shared anything
    last_mon = week_of(NOON.date()) - timedelta(days=7)
    _workout(fx, "ann", last_mon, km=10, minutes=50)
    fx.soc.block("bob", "ann")
    assert life.build_recap("bob", last_mon) is None


def test_club_runs_and_new_members(fx) -> None:
    life = _life(fx)
    cid = fx.grp.create("ann", {"name": "Wash Park Runners", "city": "Denver", "state": "CO"})["id"]
    fx.grp.add_meetup("ann", cid, {"title": "Tuesday social 5k", "start": "2026-10-20T18:00", "repeat": "weekly",
                                   "where": "Wash Park boathouse"}, NOON)
    fx.grp.join("bob", cid)
    up = life.upcoming("bob")
    assert up and up[0]["kind"] == "meetup" and up[0]["club"]["name"] == "Wash Park Runners"
    j = life.joined("ann")
    assert j and j[0]["people"][0]["name"] == "Bob" and j[0]["count"] == 1
    assert life.joined("bob") == []  # your own joining isn't news to you
    fx.soc.block("ann", "bob")
    assert life.joined("ann") == []


def test_friends_races_only_when_they_share_races(fx) -> None:
    life = _life(fx)
    EVENTS["ann"] = [{"name": "Turkey Trot", "date": (NOON.date() + timedelta(days=14)).isoformat(),
                      "distance": "10k", "kind": "race"}]
    try:
        assert [u for u in life.upcoming("bob") if u["kind"] == "race"] == []  # races sharing is off by default
        fx.soc.put_settings("ann", {"races": True})
        races = [u for u in life.upcoming("bob") if u["kind"] == "race"]
        assert races and races[0]["title"] == "Turkey Trot" and races[0]["people"][0]["name"] == "Ann"
        _follow(fx.soc, "cat", "ann")
        assert life.extras("cat")["upcoming"][0]["title"] == "Turkey Trot"
    finally:
        EVENTS.clear()
