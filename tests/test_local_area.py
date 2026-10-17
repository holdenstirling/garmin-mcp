"""Local (clubs, leagues, meetups): what each listing is for (activity -> icon / filter), whether
it's a Club, League or Meetup, and "my area" (my spot or the city centre + my radius) with
activity / weekday / time-of-day filters, over HTTP too (coach 403, bad filters 400)."""

from __future__ import annotations

import asyncio
import time

from garmin_mcp import area, geo
from garmin_mcp import clubdir as cd
from garmin_mcp.activity import IDS, classify, group_type
from garmin_mcp.coaches import coach_user_id
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_clubdir import _apps
from tests.test_social import H


def test_classify_listing_activity() -> None:
    assert classify("Wash Park Runners", kind="run_club") == "run"
    assert classify("Baker Beach Volleyball League") == "volleyball"
    assert classify("Thursday pickup", sports=["Pickleball"]) == "pickleball"
    assert classify("Mile High Masters", "Masters swim at the rec center pool") == "swim"
    assert classify("Green Mountain Trail Crew") == "trail"
    assert classify("Saturday Shop Ride", kind="other") == "ride"
    assert classify("Denver Tri Club") == "tri"
    assert classify("Front Range Futsal") == "soccer"
    assert classify("Hoops at Congress Park") == "basketball"
    assert classify("Movement Climbing Meetup") == "climbing"
    assert classify("Boulder Running Company group run") == "run"  # the city name isn't bouldering
    assert classify("Sunrise yoga in the park") == "yoga"
    assert classify("Board games night") == "other"
    assert classify("", kind="trail") == "trail"
    assert set(IDS) >= {"run", "trail", "ride", "swim", "tri", "volleyball", "pickleball", "soccer",
                        "basketball", "climbing", "yoga", "other"}


def test_club_league_or_meetup() -> None:
    assert group_type("Denver Rec Volleyball League") == "league"
    assert group_type("Anything", kind="league") == "league"
    assert group_type("Wash Park Runners") == "club"
    assert group_type("Denver Tri Club") == "club"
    assert group_type("Tuesday shop run at RunCo") == "meetup"
    assert group_type("Pickup soccer", description="Spring league season starts in April") == "league"


def test_part_of_day_and_radius_validation() -> None:
    assert area.part_of_day("06:30") == "morning" and area.part_of_day("12:15") == "midday"
    assert area.part_of_day("18:00") == "evening" and area.part_of_day("") is None and area.part_of_day(None) is None
    for bad in (3, "10", True, 100, None):
        try:
            area.clean_radius(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert area.clean_radius(25) == 25


def test_filter_rows_radius_order_and_filters() -> None:
    baker = (39.72, -104.99)
    rows = [
        {"name": "far", "activity": "run", "lat": 39.99, "lon": -105.27, "sessions": [{"weekday": "sat", "time": "07:00"}]},
        {"name": "near", "activity": "volleyball", "lat": 39.73, "lon": -104.99, "sessions": [{"weekday": "tue", "time": "18:30"}]},
        {"name": "nearer", "activity": "run", "lat": 39.721, "lon": -104.991, "sessions": [{"weekday": "tue", "time": "06:00"}]},
        {"name": "unmapped", "activity": "run", "lat": None, "lon": None, "sessions": []},
    ]
    kept, farther = area.filter_rows(rows, center=baker, radius_km=10 * area.KM_PER_MI)
    assert [r["name"] for r in kept] == ["nearer", "near", "unmapped"] and farther == 1
    assert kept[0]["distance_km"] < kept[1]["distance_km"] and kept[2]["distance_km"] is None
    # Boulder is ~40 km away: inside 50 mi.
    kept, farther = area.filter_rows(rows, center=baker, radius_km=50 * area.KM_PER_MI)
    assert farther == 0 and len(kept) == 4
    assert [r["name"] for r in area.filter_rows(rows, center=baker, radius_km=80, activity="volleyball")[0]] == ["near"]
    assert [r["name"] for r in area.filter_rows(rows, center=baker, radius_km=80, weekday="tue", when="morning")[0]] == ["nearer"]
    # No centre: nothing can be measured, so nothing is left out.
    kept, farther = area.filter_rows(rows, center=None, radius_km=3)
    assert farther == 0 and all(r["distance_km"] is None for r in kept)
    assert area.counts(rows) == {"run": 3, "volleyball": 1}


def _add_listings(env) -> None:  # noqa: F811
    now = time.time()
    doc = env.store.global_doc("clubdir-denver-co")

    def put(d):
        d["center"] = {"lat": 39.74, "lon": -104.99, "ts": now}
        d["spots"] = {cd.spot_key("Baker Park courts"): {"lat": 39.716, "lon": -104.989, "ts": now},
                      cd.spot_key("Chautauqua Park"): {"lat": 39.999, "lon": -105.281, "ts": now}}
        for name, spot, sessions, kind in (
                ("Baker Volleyball League", "Baker Park courts", [{"weekday": "wed", "time": "19:00", "note": ""}], "league"),
                ("Boulder Trail Crew", "Chautauqua Park", [{"weekday": "sat", "time": "07:00", "note": ""}], "trail")):
            key = f"{name.lower()}|x.example"
            lid = cd.listing_id(key)
            d["listings"][lid] = {"id": lid, "key": key, "name": name, "kind": kind, "sports": [], "sessions": sessions,
                                  "meet_spot": spot, "pace": "", "cost": "free", "join_url": "https://x.example/",
                                  "source_url": "https://x.example/", "source": "x.example", "description": "",
                                  "link_only": None, "first_seen": now, "last_verified": now, "reports": []}
    doc.update(put)


def test_http_area_filters_and_radius(env, tmp_path) -> None:  # noqa: F811
    c, _lid, _agent = _apps(env, tmp_path)
    _add_listings(env)
    # Bob shared his spot in Baker (rounded to 2 decimals, as "Use my location" stores it).
    geo.save_location(env.store, "bob", {"city": "Denver", "state": "CO", "zip": "80223"}, 39.72, -104.99, "device", time.time())

    async def go() -> None:
        ann, bob = c["ann"], c["bob"]
        coach = c[coach_user_id("c@x.com")]
        b = (await bob.get("/app/api/community/directory")).json()
        assert b["area"]["label"] == "Denver, CO" and b["area"]["radius_mi"] == 10 and b["area"]["source"] == "device"
        names = [x["name"] for x in b["listings"]]
        # Boulder (~45 km) is outside 10 mi; the unmapped Wash Park Runners stay ("in your city").
        assert names[0] == "Baker Volleyball League" and "Boulder Trail Crew" not in names and b["farther"] == 1
        vb = b["listings"][0]
        assert vb["activity"] == "volleyball" and vb["type"] == "league" and vb["type_label"] == "League"
        assert vb["distance_km"] is not None and vb["distance_km"] < 2
        wash = next(x for x in b["listings"] if x["name"] == "Wash Park Runners")
        assert wash["distance_km"] is None and wash["activity"] == "run" and wash["type_label"] == "Club"
        assert b["activities"] == {"volleyball": 1, "run": 1}
        # Activity, weekday and time-of-day filters
        assert [x["name"] for x in (await bob.get("/app/api/community/directory?activity=volleyball")).json()["listings"]] == ["Baker Volleyball League"]
        assert [x["name"] for x in (await bob.get("/app/api/community/directory?when=evening&weekday=wed")).json()["listings"]] == ["Baker Volleyball League"]
        assert (await bob.get("/app/api/community/directory?activity=rocket")).status_code == 400
        assert (await bob.get("/app/api/community/directory?when=noonish")).status_code == 400
        # Widen to 50 mi: Boulder shows, farther away than Baker.
        r = await bob.post("/app/api/location/prefs", headers=H, json={"radius_mi": 50})
        assert r.status_code == 200 and r.json()["radius_mi"] == 50
        b = (await bob.get("/app/api/community/directory")).json()
        assert "Boulder Trail Crew" in [x["name"] for x in b["listings"]] and b["farther"] == 0
        assert (await bob.post("/app/api/location/prefs", headers=H, json={"radius_mi": 7})).status_code == 400
        assert (await bob.post("/app/api/location/prefs", headers=H, json={})).status_code == 400
        assert (await bob.post("/app/api/location/prefs", headers=H, json={"radius_mi": 5, "use_for_local": True})).json()["radius_mi"] == 5
        # Search respects the area and filters too
        s = (await bob.get("/app/api/community/directory/search?q=trail")).json()
        assert s["listings"] == [] and s["farther"] == 1 and s["area"]["radius_mi"] == 5
        # Ann has no saved spot: the city centre is the middle, labelled as the city.
        a = (await ann.get("/app/api/community/directory")).json()
        assert a["area"]["source"] == "city" and a["area"]["has_point"] is True
        # Coach accounts can't use Local.
        assert (await coach.get("/app/api/community/directory")).status_code == 403
        assert (await coach.post("/app/api/location/prefs", headers=H, json={"radius_mi": 5})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
