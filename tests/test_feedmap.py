"""Friends' workouts in the Feed (one sharing consent for the Feed and friends' lists), and route
maps: trimmed and simplified GPS lines, shown to the owner, to friends only after the owner says
yes, never for routes that start in the owner's hidden area."""

from __future__ import annotations

import math
from datetime import date, timedelta

from garmin_mcp import routes as rt
from garmin_mcp.social import SocialFeed
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _follow
from tests.test_friends_share import NOON, _acts, fx  # noqa: F401  (fixture)
from tests.test_social import act

DENVER = (39.7392, -104.9903)


def _line(n: int = 400, step_m: float = 10.0, start=DENVER) -> list[dict[str, float]]:
    """A straight-ish line north-east, ``n`` points ``step_m`` apart, with a little wiggle."""
    out = []
    lat, lon = start
    for i in range(n):
        out.append({"lat": lat + i * step_m / 111_320, "lon": lon + i * step_m / 85_000 + 0.00002 * math.sin(i / 3)})
    return out


def _details(n: int = 400, start=DENVER) -> dict:
    return {"geoPolylineDTO": {"polyline": _line(n, start=start)}}


# ------------------------------------------------------------------ routes --
def test_route_trims_simplifies_and_hides_start() -> None:
    pts = rt.points_of(_details(400))
    assert len(pts) == 400
    total = sum(rt.dist_m(a, b) for a, b in zip(pts, pts[1:], strict=False))
    kept = rt.trim(pts, 200)
    assert rt.dist_m(pts[0], kept[0]) >= 199 and rt.dist_m(pts[-1], kept[-1]) >= 199
    assert rt.trim(pts[:20], 200) == []  # too short to show anything
    r = rt.from_details(_details(2000), trim_m=400)
    assert r is not None and 2 <= len(r["line"]) <= rt.MAX_POINTS
    assert rt.dist_m(tuple(r["line"][0]), pts[0]) >= 390  # the start is never on the line
    assert r["start_cell"] == [round(DENVER[0], 3), round(DENVER[1], 3)]
    assert rt.public(r) == r["line"] and "start_cell" not in str(rt.public(r))
    assert total > 3000
    assert rt.from_details({"geoPolylineDTO": {"polyline": [{"lat": 0, "lon": 0}] * 10}}) is None  # no GPS
    assert rt.from_details(None) is None


def test_route_families_and_home_area() -> None:
    assert rt.has_route("run") and rt.has_route("ride") and rt.has_route("hike")
    assert not rt.has_route("indoor_ride") and not rt.has_route("strength") and not rt.has_route("yoga")
    assert not rt.has_route("run", "treadmill_running") and not rt.has_route("swim", "lap_swimming")
    assert rt.has_route("swim", "open_water_swimming")
    r = rt.from_details(_details())
    assert rt.near_home(r, {"lat": DENVER[0], "lon": DENVER[1], "radius_m": 400})
    assert not rt.near_home(r, {"lat": DENVER[0] + 0.05, "lon": DENVER[1], "radius_m": 400})
    assert not rt.near_home(r, None) and not rt.near_home(None, {"lat": 1, "lon": 1, "radius_m": 400})


# ---------------------------------------------------- consent and the Feed --
def test_earlier_friends_setting_counts_as_consent_but_a_no_wins(fx) -> None:
    cm, soc, today = fx.cm, fx.soc, NOON.date()
    acts = _acts(today)
    assert cm.auto_share_workouts("ann", acts, today) == []  # default friends settings are not a yes
    assert cm.settings("ann")["sharing_source"] == "unanswered"
    soc.put_settings("ann", {"workouts": True})  # Ann saved "share my workouts" in friends settings
    s = cm.settings("ann")
    assert s["sharing_effective"] and s["sharing_source"] == "earlier"
    posted = cm.auto_share_workouts("ann", acts, today)
    assert len(posted) == 2 and sorted(p["id"] for p in cm.feed("bob")["items"]) == sorted(posted)
    cm.put_settings("ann", {"share_workouts": False})  # an explicit no here wins
    assert not cm.settings("ann")["sharing_effective"] and cm.settings("ann")["sharing_source"] == "off"
    acts.append(act(today, 9, km=4))
    assert cm.auto_share_workouts("ann", acts, today) == []


def test_friends_list_follows_the_same_consent(fx) -> None:
    cm, soc, today = fx.cm, fx.soc, NOON.date()
    feed = SocialFeed(soc, activities=lambda u: (today, _acts(today)), meta=lambda u: {"name": u.title()},
                      consent=cm.sharing_consent)
    assert feed.visible_items("bob", "ann") == []  # Ann never said yes: Bob sees none of her workouts
    assert len(feed.visible_items("ann", "ann")) == 2  # her own list (last 2 weeks) is always hers
    cm.put_settings("ann", {"share_workouts": True})
    assert {it["id"] for it in feed.visible_items("bob", "ann")} == {"2", "3"}
    assert feed.has_item("bob", "ann", "3")
    cm.put_settings("ann", {"share_workouts": False})
    assert feed.visible_items("bob", "ann") == [] and not feed.has_item("bob", "ann", "3")


# ------------------------------------------------------------- route maps --
def _with_route(fx, trim=200):
    cm = fx.cm
    cm.route_of = lambda uid, aid, trim_m: rt.from_details(_details(), trim_m=trim_m)
    cm.put_settings("ann", {"share_workouts": True, "routes_trim_m": trim})
    return cm.auto_share_workouts("ann", _acts(NOON.date()), NOON.date())


def test_route_on_post_owner_sees_friends_only_after_yes(fx) -> None:
    cm = fx.cm
    pid = _with_route(fx)[-1]
    mine = cm.get("ann", pid)["workout"]
    assert isinstance(mine["route"], list) and len(mine["route"]) >= 2
    assert "start_cell" not in str(cm.get("ann", pid))  # never leaves the server, not even to the owner
    assert "route" not in cm.get("bob", pid)["workout"]  # not shared until Ann says yes
    assert cm.settings("ann")["routes_share"] is None
    cm.put_settings("ann", {"routes_share": True})
    assert cm.get("bob", pid)["workout"]["route"] == mine["route"]
    cm.put_settings("ann", {"routes_own": False})  # Ann hides maps for herself; friends unaffected
    assert "route" not in cm.get("ann", pid)["workout"] and cm.get("ann", pid)["workout"]["route_hidden"]
    assert "route" in cm.get("bob", pid)["workout"]


def test_hidden_area_hides_routes_from_others(fx) -> None:
    cm = fx.cm
    pid = _with_route(fx)[-1]
    cm.put_settings("ann", {"routes_share": True})
    s = cm.put_settings("ann", {"routes_home": {"post_id": pid, "radius_m": 400}})
    assert s["routes_home"] == {"radius_m": 400}  # where it is never leaves the server
    assert "route" not in cm.get("bob", pid)["workout"]  # starts in Ann's hidden area
    assert "route" in cm.get("ann", pid)["workout"]  # still hers to see
    cm.put_settings("ann", {"routes_home": None})
    assert "route" in cm.get("bob", pid)["workout"]


def test_route_settings_validated_and_not_for_indoor(fx) -> None:
    import pytest

    from garmin_mcp.community import CommunityError
    cm, today = fx.cm, NOON.date()
    for bad in ({"routes_share": "yes"}, {"routes_trim_m": 300}, {"routes_home": {"post_id": "x", "radius_m": 999}}):
        with pytest.raises(CommunityError):
            cm.put_settings("ann", bad)
    cm.route_of = lambda uid, aid, trim_m: rt.from_details(_details())
    cm.put_settings("ann", {"share_workouts": True, "routes_share": True})
    a = act(today, 50, sport="indoor_cycling", km=20)
    pid = cm.auto_share_workouts("ann", [a], today)[0]
    assert "route" not in cm.get("bob", pid)["workout"]


def test_feed_follow_needed_for_friend_posts(fx) -> None:
    cm, soc, today = fx.cm, fx.soc, NOON.date()
    _follow(soc, "cat", "bob")
    cm.put_settings("ann", {"share_workouts": True})
    cm.auto_share_workouts("ann", _acts(today), today)
    assert cm.feed("cat")["items"] == []  # cat doesn't follow ann
    assert date.fromisoformat(cm.settings("ann")["share_since"]) == today - timedelta(days=2)


# --------------------------------------------------- a friend's workout page --
def test_friend_workout_page_needs_consent_and_hides_health(env, tmp_path) -> None:
    import asyncio

    from tests.test_community import _clients, _setup
    from tests.test_social import H
    apps, _push, _agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        assert (await bob.get("/app/api/activity/11?of=ann")).status_code == 404  # Ann hasn't said yes
        s = (await ann.get("/app/api/community/settings")).json()["settings"]
        assert s["sharing_effective"] is False and s["sharing_source"] == "unanswered"
        await ann.put("/app/api/community/settings", headers=H, json={"share_workouts": True})
        r = await bob.get("/app/api/activity/11?of=ann")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["owner"]["id"] == "ann" and v["ai"] is False and v["garmin_url"] is None
        assert v["checkin"] is None and v["feedback"] is None and v["zones"] is None
        for k in ("avg_hr", "max_hr", "calories", "training_load", "avg_power_w"):
            assert k not in v["numbers"]
        assert "Run 11" not in r.text  # Garmin's own name (often a place) stays private
        assert v["numbers"].get("km") == 15
        assert (await cat.get("/app/api/activity/11?of=ann")).status_code == 404  # not a follower
        assert (await bob.get("/app/api/activity/10?of=ann")).status_code == 404  # too old to be listed
        await ann.put("/app/api/social/settings", headers=H, json={"distance": False})
        v = (await bob.get("/app/api/activity/11?of=ann")).json()
        assert "km" not in v["numbers"] and v["laps"] == []

    asyncio.run(go())
