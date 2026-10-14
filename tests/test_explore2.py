"""Explore v2: location resolution + Nominatim, inferred interests, popular races, "Let Rabbit
explore", local activities, finish-time estimates, and coach 403s."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
from starlette.applications import Starlette

from garmin_mcp import explore, foryou, geo, local, localacts, predict, rabbitexplore
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.explore import RaceSearch, WebFinder, normalize
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_explore import _mock, rsu_race

BASE = "http://localhost:8001"
H = {"origin": BASE}
TODAY = date(2026, 10, 14)
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "friend@example.com": "friend"}
GARMIN = {"time5K": 1290, "time10K": 2710, "timeHalfMarathon": 6020, "timeMarathon": 12780}


def race(rid: int, name: str, when: date, **kw) -> dict:
    r = normalize(rsu_race(rid, name, when.strftime("%m/%d/%Y"), **kw))
    assert r is not None
    return r


class Clock:
    def __init__(self) -> None:
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(round(s, 3))
        self.t += s


NOMINATIM_DENVER = {"address": {"city": "Denver", "state": "Colorado", "ISO3166-2-lvl4": "US-CO",
                                "postcode": "80204", "country_code": "us"}}


def nominatim(calls: list, body=NOMINATIM_DENVER, status: int = 200) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append({"url": str(request.url), "ua": request.headers.get("user-agent"),
                      "q": {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}})
        if status != 200:
            return httpx2.Response(status, text="nope")
        if "/search" in str(request.url):
            return httpx2.Response(200, json=[{"lat": "39.7392", "lon": "-104.9849",
                                               "address": {"city": "Denver", "state": "Colorado",
                                                           "ISO3166-2-lvl4": "US-CO", "country_code": "us"}}])
        return httpx2.Response(200, json=body)
    return httpx2.MockTransport(handler)


OVERPASS_BODY = {"elements": [
    {"type": "way", "id": 11, "center": {"lat": 39.751, "lon": -104.981},
     "tags": {"leisure": "pitch", "sport": "beachvolleyball", "name": "Washington Park Sand Courts", "lit": "yes",
              "surface": "sand"}},
    {"type": "way", "id": 12, "center": {"lat": 39.70, "lon": -104.96},
     "tags": {"leisure": "track", "sport": "athletics", "surface": "tartan"}},
    {"type": "node", "id": 13, "lat": 39.74, "lon": -104.99, "tags": {"highway": "trailhead", "name": "Cherry Creek Trailhead"}},
    {"type": "node", "id": 14, "lat": 39.741, "lon": -104.981, "tags": {"leisure": "fitness_station"}},
    {"type": "way", "id": 15, "center": {"lat": 39.73, "lon": -104.97},
     "tags": {"leisure": "pitch", "sport": "tennis;pickleball", "name": "Congress Park Courts"}},
    {"type": "way", "id": 16, "center": {"lat": 39.76, "lon": -105.0},
     "tags": {"leisure": "swimming_pool", "access": "private", "name": "Condo Pool"}},
    {"type": "node", "id": 17, "lat": 39.76, "lon": -104.99, "tags": {"sport": "climbing", "name": "Movement RiNo"}},
    {"type": "node", "id": 18, "lat": 39.0, "lon": -104.0, "tags": {"amenity": "bench"}},
    {"type": "node", "id": 19, "tags": {"sport": "climbing"}},  # no coordinates
]}


def overpass(calls: list, body=OVERPASS_BODY, status: int = 200) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append({"url": str(request.url), "ua": request.headers.get("user-agent"),
                      "query": parse_qs(request.content.decode()).get("data", [""])[0]})
        if status != 200:
            return httpx2.Response(status, text="busy")
        return httpx2.Response(200, json=body)
    return httpx2.MockTransport(handler)


# -------------------------------------------------------------- location --
def test_location_resolution_order() -> None:
    saved = {"lat": 39.25, "lon": -106.29, "zip": "80461", "city": "Leadville", "state": "CO", "source": "device",
             "updated": 1}
    athlete = {"home_location": "Baker, Denver CO 80204"}
    # (a) the saved location (device or manual) wins, and only it carries coordinates.
    r = geo.resolve({"home_zip": "80302"}, athlete, saved)
    assert r["source"] == "device" and r["zip"] == "80461" and (r["lat"], r["lon"]) == (39.25, -106.29)
    assert geo.resolve({}, athlete, {**saved, "source": "manual"})["source"] == "manual"
    # (b) home zip from interests, then the profile's home_location (zip, then city/state).
    r = geo.resolve({"home_zip": "80302"}, athlete, None)
    assert r["source"] == "home_zip" and r["zip"] == "80302" and r["city"] == "" and r["lat"] is None
    r = geo.resolve({}, athlete, None)
    assert r == {"source": "profile_zip", "zip": "80204", "state": "CO", "city": "Denver", "lat": None, "lon": None}
    r = geo.resolve({}, {"home_location": "Leadville, Colorado"}, None)
    assert r["source"] == "profile_city" and r["state"] == "CO" and r["city"] == "Leadville" and r["zip"] == ""
    assert geo.resolve({}, {"home_location": "Kansas City, MO"}, None)["state"] == "MO"
    # (c) a timezone alone never guesses a state: nothing usable -> nationwide.
    r = geo.resolve({}, {"timezone": "America/Denver", "home_location": ""}, None)
    assert r["source"] is None and r["state"] == "" and not geo.searchable(r)
    assert geo.resolve({}, {"home_location": "out in the hills or me"}, None)["source"] is None
    assert geo.resolve(None, None, None)["source"] is None
    # A saved place outside the US keeps the city (for local activities) but isn't searchable.
    r = geo.resolve({}, {}, {"zip": "", "city": "Chamonix", "state": "Auvergne-Rhône-Alpes", "lat": 45.92, "lon": 6.87})
    assert r["source"] is None and r["city"] == "Chamonix" and r["lat"] == 45.92 and not geo.searchable(r)
    assert geo.label({"city": "Denver", "state": "CO"}) == "Denver, CO" and geo.label({"zip": "80204"}) == "80204"


def test_saved_location_store_and_legacy(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    # Pre-v2 "location_auto" is read as a device location.
    store.user_doc("ann", "profile").update(lambda p: p.update(location_auto={
        "zip": "80204", "city": "Denver", "state": "CO", "lat2": 39.74, "lon2": -104.98, "ts": 5}))
    old = geo.load_saved(store, "ann")
    assert old == {"lat": 39.74, "lon": -104.98, "city": "Denver", "state": "CO", "zip": "80204",
                   "source": "device", "updated": 5}
    e = geo.save_location(store, "ann", {"city": "Golden", "state": "CO", "zip": "80401", "country": "us"},
                          39.755123, -105.221987, "manual", 1000.9)
    assert e == {"lat": 39.76, "lon": -105.22, "city": "Golden", "state": "CO", "zip": "80401",
                 "source": "manual", "updated": 1000}
    prof = store.user_doc("ann", "profile").load()
    assert "location_auto" not in prof and tuple(prof["location"]) == geo.LOC_KEYS
    assert "39.755" not in json.dumps(prof)
    assert geo.use_for_local(store, "ann") is True
    geo.set_use_for_local(store, "ann", False)
    assert geo.use_for_local(store, "ann") is False
    geo.forget(store, "ann")
    assert geo.load_saved(store, "ann") is None


def test_rounding_and_parse() -> None:
    assert geo.round2(39.739154, -104.984703) == (39.74, -104.98)
    for bad in ((91, 0), (0, 181), ("39.7", -104.9), (True, 1), (None, None)):
        try:
            geo.round2(*bad)
            raise AssertionError(bad)
        except geo.LocationError:
            pass
    p = geo.parse_place(NOMINATIM_DENVER)
    assert p == {"zip": "80204", "city": "Denver", "state": "CO", "country": "us"}
    p = geo.parse_place({"address": {"town": "Leadville", "state": "Colorado", "country_code": "us",
                                     "postcode": "80461-1234"}})
    assert p["zip"] == "80461" and p["state"] == "CO"
    assert geo.parse_place({"address": {"county": "Lake County", "state": "Colorado"}})["city"] == "Lake"
    assert geo.parse_place("junk")["city"] == ""


def test_nominatim_client_ua_throttle_and_cache(tmp_path, fernet_key) -> None:
    calls: list = []
    clock = Clock()
    store = AppStore(tmp_path / "app", fernet_key)
    th = geo.Throttle(1.0, clock=clock, sleep=clock.sleep)
    g = geo.Geocoder(contact="me@example.com", store=store, transport=nominatim(calls), throttle=th)

    async def go() -> None:
        assert (await g.reverse(39.74, -104.98))["city"] == "Denver"
        assert (await g.reverse(39.7449, -104.9849))["city"] == "Denver"  # same rounded key: cached
        await g.reverse(40.02, -105.27)
        await g.zip_place("80204")
    asyncio.run(go())
    assert len(calls) == 3
    assert all(c["ua"] == "RabbitTraining/1.0 (+me@example.com)" for c in calls)
    assert calls[0]["q"] == {"format": "jsonv2", "lat": "39.74", "lon": "-104.98", "zoom": "10", "addressdetails": "1"}
    assert calls[2]["q"]["postalcode"] == "80204" and calls[2]["q"]["countrycodes"] == "us"
    assert clock.slept == [1.0, 1.0]  # 1 request per second
    # Persisted: a fresh geocoder (restart) reuses the 30-day cache; after 30 days it asks again.
    g3 = geo.Geocoder(contact="x", store=store, transport=nominatim(calls), throttle=th)
    asyncio.run(g3.reverse(40.02, -105.27))
    assert len(calls) == 3
    later = time.time() + 31 * 86400
    g2 = geo.Geocoder(contact="x", store=store, transport=nominatim(calls), throttle=th, clock=lambda: later)
    asyncio.run(g2.reverse(39.74, -104.98))
    assert len(calls) == 4
    assert list(store.global_doc("geocache").load()) == ["r:39.74,-104.98"]  # stale entries pruned
    # Upstream trouble is a friendly error, and a missing zip lookup is just {}.
    bad = geo.Geocoder(contact="x", transport=nominatim([], status=500), throttle=th)
    try:
        asyncio.run(bad.reverse(1.0, 1.0))
        raise AssertionError("expected LocationError")
    except geo.LocationError as e:
        assert "zip" in str(e)
    assert asyncio.run(bad.zip_place("12345")) == {} and asyncio.run(bad.zip_place("abc")) == {}


# ------------------------------------------------------------- inference --
def test_inferred_defaults() -> None:
    main = {"name": "Leadville 100", "date": "2027-08-21", "main": True, "type": "trail", "distance": "ultra"}
    i = foryou.infer_interests({"favorite_sports": ["bike"]}, [{"sport": "run", "hours": 80}, {"sport": "swim", "hours": 9}],
                               [main], TODAY)
    assert i["race_types"][:2] == ["trail", "ultra"] and "road_cycling" in i["race_types"]
    assert i["distances"][:2] == ["marathon", "ultra_50k"] and i["travel"] == "regional"
    tri = foryou.infer_interests({}, [{"sport": "bike", "hours": 50}, {"sport": "run", "hours": 40},
                                      {"sport": "swim", "hours": 20}], [], TODAY)
    assert tri["race_types"][0] == "triathlon" and "sprint" in tri["distances"]
    blank = foryou.infer_interests({}, None, [], TODAY)
    assert blank["race_types"] == ["road", "trail", "triathlon", "road_cycling"] and blank["distances"]
    # No race, no Garmin: favorite sports, then the active goal's type, choose the types.
    fav = foryou.infer_interests({"favorite_sports": ["gravel"]}, None, [], TODAY)
    assert fav["race_types"] == ["gravel"]
    g = foryou.infer_interests({}, None, [], TODAY, {"title": "My goal", "event": "Boulder 70.3"})
    assert g["race_types"] == ["triathlon"] and {"sprint", "olympic"} & set(g["distances"])
    assert foryou.goal_types({"event": "first ultra marathon"}) == ["ultra"]
    assert foryou.goal_types({"event": "Moab trail half marathon"}) == ["trail", "road"]
    assert foryou.goal_types(None) == []
    # Own race types/distances win; a zip alone is not "interests".
    eff, inferred = foryou.effective_interests({"home_zip": "80204", "months_avoid": [8]}, lambda: blank)
    assert inferred and eff["home_zip"] == "80204" and eff["months_avoid"] == [8] and eff["race_types"]
    own = {"race_types": ["swim"]}
    assert foryou.effective_interests(own, lambda: blank) == (own, False)
    assert not foryou.has_own_interests({"home_zip": "80204"}) and foryou.has_own_interests(own)


def test_popular_races_fallback() -> None:
    pops = foryou.popular_races({"race_types": ["trail"]}, TODAY)
    assert pops and all(p.get("check_dates") and p["date"] == "" and p["usual_month"] for p in pops)
    assert pops[0]["types"] == ["trail"] and all(p["url"].startswith("https://") for p in pops)
    raw = rsu_race(1, "2027 Bank of America Chicago Marathon", "10/10/2027", etype="running_race", dist="26.2 Miles")
    ok = normalize(raw)
    pops = foryou.popular_races({}, TODAY, {"Chicago Marathon": ok})
    chi = next(p for p in pops if "Chicago" in p["name"])
    assert chi["date"] == "2027-10-10" and not chi.get("check_dates") and chi["why"]
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {None: [raw]}))
    got = asyncio.run(foryou.verify_popular(rs, TODAY))
    assert list(got) == ["Chicago Marathon"] and len(calls) == len(foryou.POPULAR)
    assert {c["name"] for c in calls} == {p["name"] for p in foryou.POPULAR}


# ------------------------------------------------------- Let Rabbit explore --
def test_rabbit_explore_merge_rank_and_intro() -> None:
    main = {"id": "m", "name": "Leadville Trail 100 Run", "date": "2027-08-21", "main": True, "priority": "A",
            "type": "trail", "distance": "ultra"}
    tune = race(1, "Golden Gate Trail Half", date(2027, 7, 10), dist="13.1 Miles")
    later = race(2, "Spring Trail 50K", date(2027, 3, 6), dist="50K")
    taper = race(3, "Taper Breaker", date(2027, 8, 14), dist="10K")
    web_dup = {**race(9, "Golden Gate Trail Half", date(2027, 7, 11), dist="13.1 Miles"),
               "id": "web:abc", "source": "web", "summary": "From the web"}
    web_new = {**race(10, "Mountain Classic", date(2027, 6, 5), etype="running_race", dist="10K"),
               "id": "web:def", "source": "web", "summary": "Big"}
    merged = rabbitexplore.dedupe([[tune, later, taper], [web_dup, web_new]])
    assert [r["id"] for r in merged] == ["rsu:1", "rsu:2", "rsu:3", "web:def"]
    interests = {"race_types": ["trail"], "distances": ["half"]}
    ranked, tunes = rabbitexplore.rank(merged, interests=interests, events=[main], today=TODAY)
    ids = [r["id"] for r in ranked]
    assert "rsu:3" not in ids and ids[0] == "rsu:1" and tunes == 1  # taper week dropped; tune-up first
    assert ranked[0]["why"].startswith("Half-marathon tune-up") and all(r["why"] for r in ranked)
    web = next(r for r in ranked if r["id"] == "web:def")
    assert web["why"] == "A notable race Rabbit found on the web"
    s = rabbitexplore.intro(14, zip_="80204", state="", radius=120, tunes=3, main=main)
    assert s == "Found 14 races within 120 mi in the next 6 months; 3 are great tune-ups for Leadville Trail 100 Run."
    assert rabbitexplore.intro(1, zip_="", state="CO", radius=50, tunes=1, main=main).startswith("Found 1 race in CO")
    assert "is a great tune-up" in rabbitexplore.intro(2, zip_="1", state="", radius=50, tunes=1, main=main)
    assert rabbitexplore.intro(0, zip_="", state="", radius=50, tunes=0, main=None).startswith("No races turned up")


# --------------------------------------------------------------- predict --
def test_predict_riegel_and_garmin_path() -> None:
    assert round(predict.riegel(1200, 5, 10)) == 2502
    b = predict.make_basis(garmin=GARMIN)
    e = predict.estimate(b, distance_km=21.0975, type_="road")
    assert e["likely"] == 6020 and e["confidence"] == "high" and e["basis"] == ["Garmin race predictor"]
    assert e["low"] < e["likely"] < e["high"] and predict.text(e) == "1:37–1:44"
    # Daily list shape: newest wins.
    assert predict.garmin_points([{"time5K": 1500}, {"time5K": 1290}]) == [(5.0, 1290.0)]
    assert predict.garmin_points({"time5K": 5}) == []  # nonsense filtered
    assert predict.fmt(1290) == "21:30" and predict.fmt(3725) == "1:02"


def test_predict_efforts_and_threshold_fallbacks() -> None:
    acts = [
        {"sport": "running", "date": "2026-09-20 08:00:00", "distance_km": 10.0, "duration": "0:44:00",
         "elevation_gain_m": 40, "event": "race"},
        {"sport": "running", "date": "2026-10-01 07:00:00", "distance_km": 8.0, "duration": "0:48:00"},
        {"sport": "trail_running", "date": "2026-10-02 07:00:00", "distance_km": 10.0, "duration": "1:20:00",
         "elevation_gain_m": 900},  # too hilly to judge flat speed
        {"sport": "running", "date": "2025-01-01 07:00:00", "distance_km": 10.0, "duration": "0:35:00"},  # too old
        {"sport": "cycling", "date": "2026-10-03", "distance_km": 50.0, "duration": "1:30:00"},
    ]
    b = predict.make_basis(acts=acts, today=TODAY)
    assert [x["km"] for x in b["efforts"]] == [10.0, 8.0]
    e = predict.estimate(b, distance_km=21.1, type_="road")
    assert "your recent 10K" in e["basis"] and e["confidence"] == "medium"
    assert abs(e["likely"] - predict.riegel(2640, 10, 21.1)) < 2
    t = predict.estimate(predict.make_basis(athlete={"run_threshold_pace": 270}), distance_km=10, type_="running")
    assert t["basis"] == ["your threshold pace"] and t["confidence"] == "low"
    none = predict.make_basis()
    assert predict.estimate(none, distance_km=10, type_="road") is None and not predict.has_data(none)
    assert predict.estimate(predict.make_basis(garmin=GARMIN), distance_km=10, type_="skydiving") is None


def test_predict_course_adjustments() -> None:
    b = predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 10})
    flat = predict.estimate(b, distance_km=42.195, type_="road")
    hilly = predict.estimate(b, distance_km=42.195, type_="road", climb_m=1000)
    assert hilly["likely"] > flat["likely"] * 1.15 and "course: +1,000 m climbing" in hilly["basis"]
    trail = predict.estimate(b, distance_km=21.1, type_="trail")
    road = predict.estimate(b, distance_km=21.1, type_="road")
    tech = predict.estimate(b, distance_km=21.1, type_="trail", terrain="technical")
    assert road["likely"] < trail["likely"] < tech["likely"] and "trail surface" in trail["basis"]
    high = predict.estimate(b, distance_km=10, type_="road", elevation_m=2800)
    assert high["likely"] > predict.estimate(b, distance_km=10, type_="road")["likely"] * 1.06
    assert "altitude: 2,800 m" in high["basis"]
    # Living up high (or acclimatized) shrinks the altitude cost; under 1,500 m there's none.
    local = predict.estimate(predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 2700}),
                             distance_km=10, type_="road", elevation_m=2800)
    assert local["likely"] == predict.estimate(b, distance_km=10, type_="road")["likely"]
    assert predict.altitude_factor(1400, b) == (1.0, None)
    acc = predict.make_basis(garmin=GARMIN, athlete={"altitude_acclimatized": True})
    assert predict.altitude_factor(2800, acc)[0] < predict.altitude_factor(2800, b)[0]
    hot = predict.estimate(b, distance_km=10, type_="road", hot=True)
    assert hot["likely"] > predict.estimate(b, distance_km=10, type_="road")["likely"] and "heat" in hot["basis"]


def test_predict_ultra_is_a_rough_guide() -> None:
    b = predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 1609})
    e = predict.estimate(b, distance_km=161, type_="trail", climb_m=4800, elevation_m=3094)
    assert e["confidence"] == "low" and e["label"] == "rough guide"
    assert e["high"] / e["low"] > 1.35 and 18 * 3600 < e["likely"] < 32 * 3600
    assert "Garmin race predictor (marathon equivalent)" in e["basis"] and "altitude: 3,090 m" in e["basis"]
    assert predict.text(e).endswith(" h")
    fifty = predict.estimate(b, distance_km=50, type_="ultra", climb_m=2400)
    assert fifty["label"] == "rough guide" and fifty["likely"] > predict.estimate(b, distance_km=50, type_="ultra")["likely"]


def test_predict_triathlon_composite() -> None:
    full = predict.make_basis(athlete={"ftp_w": 250, "swim_css": 100, "run_threshold_pace": 270, "weight_kg": 72})
    e = predict.estimate(full, distance_km=51.5, type_="triathlon")
    sp = e["splits"]
    assert e["kind"] == "tri" and e["confidence"] == "medium"
    assert e["likely"] == sp["swim"] + sp["bike"] + sp["run"] + sp["transitions"]
    assert sp["swim"] == ((100 + 6) * 15) and sp["run"] == round(270 * 10 * 1.06)
    assert 3000 < sp["bike"] < 5400 and e["basis"][:3] == ["swim: your CSS", "bike: your FTP", "run: your threshold pace"]
    weak = predict.make_basis(athlete={"ftp_w": 180, "swim_css": 100, "run_threshold_pace": 270, "weight_kg": 72})
    assert predict.estimate(weak, distance_km=51.5, type_="triathlon")["splits"]["bike"] > sp["bike"]
    guess = predict.estimate(predict.make_basis(garmin=GARMIN), distance_km=113, type_="triathlon")
    assert guess["confidence"] == "low" and guess["label"] == "rough guide"
    assert "swim: typical age-group pace" in guess["basis"] and "run: Garmin race predictor" in guess["basis"]
    assert predict.estimate(full, distance_km=80, type_="triathlon") is None  # not a standard format
    assert predict.bike_speed(250, 81) > predict.bike_speed(250, 81, elevation_m=0, cda=0.40)
    bike = predict.estimate(full, distance_km=160, type_="cycling", climb_m=1500)
    assert bike["kind"] == "bike" and 4 * 3600 < bike["likely"] < 8 * 3600
    assert predict.estimate(full, distance_km=3.8, type_="swim")["likely"] == ((100 + 8) * 38)


def test_predict_for_event_and_race() -> None:
    b = predict.make_basis(garmin=GARMIN)
    ev = {"name": "Leadville Trail 100 Run", "type": "trail", "distance": "ultra", "location": "Leadville, CO",
          "info": {"distances": "100 miles", "elevation_gain": "15,600 ft", "typical_weather": "cold nights"}}
    e = predict.for_event(b, ev)
    assert e["label"] == "rough guide" and any("climbing" in x for x in e["basis"])
    r = race(1, "Golden Half", TODAY + timedelta(days=60), dist="13.1 Miles")
    est = predict.for_race(b, r, {"half"})
    assert est["text"] == predict.text(est) and est["event"] == "13.1 Miles"
    assert predict.for_race(b, {"events": []}) is None


# ---------------------------------------------------------- local activities --
def test_local_activities_clean_and_validate() -> None:
    items = [{"name": f"Club {i}", "category": "run", "url": f"https://club{i}.example.org"} for i in range(20)]
    assert len(localacts.clean({"activities": items})) == 15
    out = localacts.clean({"activities": [
        {"name": "Wash Park Runners", "category": "run", "organizer": "<b>Wash Park</b> RC", "when": "Tuesdays 6:30 pm",
         "where": "Washington Park boathouse", "cost": "Free!",
         "url": "https://washparkrunners.org/join?utm_source=x&fbclid=abc&day=tue#top", "why_relevant": "Easy social miles"},
        {"name": "Http Only", "category": "ride", "url": "http://example.com"},
        {"name": "Js", "category": "ride", "url": "javascript:alert(1)"},
        {"name": "Creds", "category": "ride", "url": "https://user:pw@example.com"},
        {"name": "Volo Kickball", "category": "social_sports", "where": "1234 Elm Street", "cost": "$$",
         "url": "https://www.volosports.com/denver"},
        {"name": "Wash Park Runners", "category": "run", "url": "https://dup.example.org"},
        {"name": "Mystery", "category": "parkour", "url": "https://mystery.example.org"},
    ]})
    assert [a["name"] for a in out] == ["Wash Park Runners", "Volo Kickball", "Mystery"]
    w = out[0]
    assert w["url"] == "https://washparkrunners.org/join?day=tue" and w["cost"] == "free"
    assert w["organizer"] == "Wash Park RC" and w["when"] == "Tuesdays 6:30 pm" and w["why"] == "Easy social miles"
    assert out[1]["where"] == "" and out[1]["cost"] == "$$"  # private-looking street address dropped
    assert out[2]["category"] == "other"
    assert localacts.clean("no json here") == [] and localacts.clean({"activities": "x"}) == []
    assert localacts.relevant({"favorite_sports": ["swim", "yoga"]}, [{"sport": "bike"}]) == ["swim", "yoga", "ride"]
    assert localacts.relevant({}, None) == ["run", "ride"]
    ordered = localacts.order(out, ["social_sports"])
    assert ordered[0]["name"] == "Volo Kickball" and ordered[-1]["category"] == "other"
    p = localacts.prompt("Denver", "CO")
    assert '"Denver, CO"' in p and "80204" not in p


def test_local_cache_is_shared_per_city_and_week(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    calls: list = []

    async def research(system, prompt, **kw):
        calls.append(prompt)
        assert kw["report_tool"]["name"] == "report_activities"
        return {"activities": [{"name": "Denver Run Club", "category": "run", "url": "https://drc.example.org"}]}
    f = localacts.LocalFinder(store)
    assert f.cached("Denver", "CO", TODAY) is None
    asyncio.run(f.find(research, "Denver", "CO", TODAY))
    # Another process (fresh finder) on the same week shares it; next week is a new search.
    f2 = localacts.LocalFinder(store)
    assert f2.cached("denver", "co", TODAY + timedelta(days=1))[0]["name"] == "Denver Run Club"
    assert f2.cached("Denver", "CO", TODAY + timedelta(days=7)) is None
    assert localacts.week_key(TODAY) == "2026-W42" and len(calls) == 1
    # Old weeks are pruned when a new week is stored.
    asyncio.run(f2.find(research, "Boulder", "CO", TODAY + timedelta(weeks=5)))
    keys = list(store.global_doc("localacts").load())
    assert keys == ["boulder|CO|2026-W47"]


# ------------------------------------------------------------------- API --
def _apps(env, tmp_path, monkeypatch, users=("ann", "bob", "friend")):
    monkeypatch.setattr(geo, "_THROTTLE", geo.Throttle(0.0))
    monkeypatch.setattr(local, "_THROTTLE", geo.Throttle(0.0))
    # Never the real network: Nominatim / Overpass answer 503 unless a test mocks them.
    if geo.TRANSPORT is None:
        monkeypatch.setattr(geo, "TRANSPORT", nominatim([], status=503))
    if local.TRANSPORT is None:
        monkeypatch.setattr(local, "TRANSPORT", overpass([], status=503))
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW), contact_email="ops@example.com")

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    return agent, {u: app(u) for u in (*users, coach_user_id("c@x.com"))}


def _clients(apps):
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}


def test_location_api_stores_only_rounded_place(env, tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(geo, "TRANSPORT", nominatim(calls))
    agent, apps = _apps(env, tmp_path, monkeypatch)
    logged: list = []
    import garmin_mcp.webapp as webapp_mod
    real_log = webapp_mod.log_event
    monkeypatch.setattr(webapp_mod, "log_event", lambda *a, **kw: (logged.append(kw), real_log(*a, **kw)))

    async def go() -> None:
        c = _clients(apps)
        ann = c["ann"]
        r = await ann.get("/app/api/location")
        assert r.status_code == 200 and r.json()["saved"] is None and r.json()["resolved"]["source"] is None
        assert r.json()["resolved"]["nationwide"] is True and r.json()["use_for_local"] is True
        assert (await ann.post("/app/api/location", json={"lat": 39.739154, "lon": -104.984703})).status_code == 403
        r = await ann.post("/app/api/location", headers=H, json={"lat": 39.739154, "lon": -104.984703})
        assert r.status_code == 200, r.text
        assert r.json()["saved"]["city"] == "Denver" and r.json()["resolved"]["label"] == "Denver, CO"
        assert r.json()["resolved"]["source"] == "device" and r.json()["resolved"]["searchable"]
        assert "lat" not in r.json()["saved"] and "39.74" not in r.text  # the app never gets coordinates back
        assert calls[0]["q"]["lat"] == "39.74" and calls[0]["q"]["lon"] == "-104.98"
        assert calls[0]["ua"] == "RabbitTraining/1.0 (+ops@example.com)"
        prof = env.store.user_doc("ann", "profile").load()
        assert tuple(prof["location"]) == geo.LOC_KEYS and prof["location"]["source"] == "device"
        assert prof["location"]["lat"] == 39.74 and prof["location"]["lon"] == -104.98
        dumped = json.dumps(prof)
        assert "39.739" not in dumped and "104.984" not in dumped and "athlete" not in prof
        # Never logged, never in Rabbit's context.
        assert "39.7" not in json.dumps(logged) and "104.9" not in json.dumps(logged)
        from datetime import datetime
        ctx = agent.coach.context_block("ann", datetime(2026, 10, 14, tzinfo=UTC), None)
        assert "Denver" not in ctx and "80204" not in ctx
        assert (await ann.post("/app/api/location", headers=H, json={"lat": 300, "lon": 0})).status_code == 400
        # A typed zip is a "manual" location (geocoded, rounded).
        r = await ann.post("/app/api/location", headers=H, json={"zip": "80204"})
        assert r.status_code == 200, r.text
        assert r.json()["saved"]["source"] == "manual" and r.json()["resolved"]["source"] == "manual"
        assert env.store.user_doc("ann", "profile").load()["location"]["lat"] == 39.74
        assert (await ann.post("/app/api/location", headers=H, json={"zip": "8020"})).status_code == 400
        # The local-picks toggle.
        r = await ann.post("/app/api/location/prefs", headers=H, json={"use_for_local": False})
        assert r.status_code == 200 and r.json()["use_for_local"] is False
        r = await ann.post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200 and r.json()["disabled"] is True and r.json()["places"] == []
        assert (await ann.post("/app/api/location/prefs", headers=H, json={"use_for_local": "no"})).status_code == 400
        # Forget.
        r = await ann.request("DELETE", "/app/api/location", headers=H, json={})
        assert r.status_code == 200 and r.json()["saved"] is None
        assert "location" not in env.store.user_doc("ann", "profile").load()
    asyncio.run(go())


def test_foryou_never_empty(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path, monkeypatch)
    today = agent._now("ann").date()
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {
        "running_race": [rsu_race(1, "Denver Half", (today + timedelta(days=70)).strftime("%m/%d/%Y"),
                                  etype="running_race", dist="13.1 Miles")],
        "trail_race": [rsu_race(2, "Golden Trail Half", (today + timedelta(days=60)).strftime("%m/%d/%Y"),
                                dist="13.1 Miles")],
        None: [rsu_race(3, "Anywhere 10K", (today + timedelta(days=20)).strftime("%m/%d/%Y"), dist="10K")]}))
    monkeypatch.setattr(foryou, "_default", foryou.ForYou(search=lambda: rs))
    monkeypatch.setattr(explore, "_default", rs)

    async def go() -> None:
        c = _clients(apps)
        # No interests, no location, only a timezone: a nationwide "Coming up" search over a
        # balanced mix of types, labelled honestly.
        body = (await c["ann"].get("/app/api/explore/foryou")).json()
        assert body["has_interests"] is False and body["inferred"] is True and body["nationwide"] is True
        assert body["location"]["source"] is None and not body["location"]["searchable"]
        assert body["location"]["note"] == explore.NATIONWIDE_NOTE
        assert body["effective"]["race_types"] == foryou.BALANCED_TYPES
        sec = body["sections"][0]
        assert sec["id"] == "nationwide" and sec["note"] == explore.NATIONWIDE_NOTE
        assert [r["name"] for r in sec["races"]] == ["Golden Trail Half", "Denver Half"]  # by date
        assert all("zipcode" not in cl and "state" not in cl for cl in calls)
        assert {cl.get("event_type") for cl in calls} >= {"running_race", "trail_race", "triathlon", "bike_race"}
        assert "popular" not in [s["id"] for s in body["sections"]]
        # Search with no filters: defaults to all types; with no location it's nationwide too.
        d = (await c["ann"].get("/app/api/explore/defaults")).json()
        assert d["near"] == "" and d["types"] == [] and d["radius"] == 50 and d["location"]["nationwide"]
        r = (await c["ann"].get("/app/api/explore", params={"months": "6"})).json()
        assert r["nationwide"] is True and r["note"] == explore.NATIONWIDE_NOTE and r["races"]
        # A city/state in the profile is enough: inferred interests rank real picks.
        agent.coach.update_athlete("bob", {"home_location": "Denver, CO", "favorite_sports": ["run"]})
        calls.clear()
        body = (await c["bob"].get("/app/api/explore/foryou")).json()
        assert body["inferred"] is True and body["location"]["source"] == "profile_city" and not body["nationwide"]
        assert all(cl.get("state") == "CO" for cl in calls) and {cl.get("event_type") for cl in calls} == {"running_race"}
        picks = next(s for s in body["sections"] if s["id"] == "picks")
        assert picks["races"][0]["name"] == "Denver Half" and picks["races"][0]["why"]
        assert body["effective"]["travel"] == "regional" and "road" in body["effective"]["race_types"]
        d = (await c["bob"].get("/app/api/explore/defaults")).json()
        assert d["near"] == "CO" and d["types"] == [] and not d["location"]["nationwide"]
    asyncio.run(go())


def test_foryou_popular_only_when_nationwide_is_empty(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path, monkeypatch)
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {}))
    monkeypatch.setattr(foryou, "_default", foryou.ForYou(search=lambda: rs))
    monkeypatch.setattr(explore, "_default", rs)

    async def go() -> None:
        body = (await _clients(apps)["ann"].get("/app/api/explore/foryou")).json()
        assert [s["id"] for s in body["sections"]] == ["popular"]
    asyncio.run(go())


def test_let_rabbit_explore_api(env, tmp_path, monkeypatch) -> None:
    ncalls: list = []
    ocalls: list = []
    monkeypatch.setattr(geo, "TRANSPORT", nominatim(ncalls))
    monkeypatch.setattr(local, "TRANSPORT", overpass(ocalls))
    agent, apps = _apps(env, tmp_path, monkeypatch)
    today = agent._now("ann").date()
    a_race = today + timedelta(weeks=20)
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {"trail_race": [
        rsu_race(1, "Tune Trail Half", (a_race - timedelta(weeks=5)).strftime("%m/%d/%Y"), dist="13.1 Miles"),
        rsu_race(2, "Winter Trail 50K", (today + timedelta(days=40)).strftime("%m/%d/%Y"), dist="50K")]}))
    monkeypatch.setattr(explore, "_default", rs)
    monkeypatch.setattr(foryou, "_default", foryou.ForYou(search=lambda: rs))
    agent.events.create("ann", {"name": "Big Trail 100", "date": a_race.isoformat(), "type": "trail",
                                "distance": "ultra", "priority": "A"})
    agent.coach.update_athlete("ann", {"home_location": "Golden, CO 80401", "interests": {"race_types": ["trail"]}})
    prompts: list = []

    async def research(system, prompt, **kw):
        prompts.append((system, prompt))
        if kw["report_tool"]["name"] == "report_activities":
            return {"activities": [
                {"name": "Golden Group Run", "category": "run", "organizer": "Runners Roost", "when": "Wed 6 pm",
                 "where": "Clear Creek", "url": "https://roost.example.org/group-run"},
                {"name": "Made Up League", "category": "social_sports", "when": "Mondays"}]}  # no URL: dropped
        return {"races": [
            {"name": "Tune Trail Half", "date": (a_race - timedelta(weeks=5)).isoformat(), "type": "trail",
             "location": "Golden, CO", "distances": "13.1 Miles", "url": "https://dup.example.org"},
            {"name": "Famous Mountain 50", "date": (today + timedelta(days=120)).isoformat(), "type": "ultra",
             "location": "Silverton, CO", "distances": "50 Miles", "url": "https://famous.example.org"}]}
    agent._backend.research = research  # type: ignore[attr-defined]

    async def go() -> None:
        c = _clients(apps)
        assert (await c["ann"].post("/app/api/explore/rabbit", json={})).status_code == 403  # origin
        r = await c["ann"].post("/app/api/explore/rabbit", headers=H, json={})
        assert r.status_code == 200, r.text
        body = r.json()
        names = [x["name"] for x in body["races"]]
        assert names.count("Tune Trail Half") == 1 and "Famous Mountain 50" in names and "Winter Trail 50K" in names
        assert body["races"][0]["name"] == "Tune Trail Half" and body["races"][0]["source"] == "runsignup"
        assert body["web"] == "ok" and all(x["why"] for x in body["races"])
        assert [g["name"] for g in body["groups"]] == ["Golden Group Run"] and body["groups"][0]["source"] == "web"
        assert body["places"] and body["places_state"] == "ok"
        assert body["count"] == len(body["races"]) + len(body["places"]) + len(body["groups"])
        assert body["summary"] == f"Rabbit found {body['count']} things for you"
        assert calls[0]["zipcode"] == "80401"
        # Privacy: the model sees "Golden, CO" and race interests only.
        scout = prompts[0][1]
        assert '"Golden, CO"' in scout and "Big Trail 100" in scout and "trail running" in scout
        everything = json.dumps(prompts)
        assert "80401" not in everything and "39." not in everything and "-105" not in everything
        assert "oura" not in everything.lower()
        # Overpass got only the rounded point of the zip.
        assert "(around:8000,39.74,-104.98)" in ocalls[0]["query"] and ocalls[0]["ua"].startswith("RabbitTraining/1.0")
        # Second tap: scout, groups and places are cached (no new searches).
        r = await c["ann"].post("/app/api/explore/rabbit", headers=H, json={})
        assert r.status_code == 200 and len(prompts) == 2 and len(ocalls) == 1
    asyncio.run(go())


def test_local_api_shares_city_cache_and_sends_only_city(env, tmp_path, monkeypatch) -> None:
    calls: list = []
    ocalls: list = []
    monkeypatch.setattr(geo, "TRANSPORT", nominatim(calls))
    monkeypatch.setattr(local, "TRANSPORT", overpass(ocalls))
    agent, apps = _apps(env, tmp_path, monkeypatch)
    prompts: list = []

    async def research(system, prompt, **kw):
        prompts.append(prompt)
        return {"activities": [
            {"name": "City Park Run Club", "category": "run", "when": "Thursdays 6 pm", "where": "City Park",
             "cost": "free", "url": "https://cprc.example.org/?utm_campaign=x", "why_relevant": "Easy group miles"},
            {"name": "Volo Volleyball", "category": "social_sports", "url": "https://www.volosports.com/denver"}]}
    agent._backend.research = research  # type: ignore[attr-defined]
    agent.coach.update_athlete("bob", {"home_location": "Denver CO 80204", "favorite_sports": ["run"]})

    async def go() -> None:
        c = _clients(apps)
        r = await c["ann"].get("/app/api/explore/nearby")
        assert r.status_code == 200 and r.json()["needs_location"] is True and r.json()["items"] == []
        r = await c["ann"].post("/app/api/location", headers=H, json={"lat": 39.7392, "lon": -104.9849})
        assert r.status_code == 200
        # GET nearby never spends a web search; places come from OpenStreetMap.
        r = await c["ann"].get("/app/api/explore/nearby")
        assert r.status_code == 200 and r.json()["items"] == [] and r.json()["groups_state"] == "cached_only"
        assert r.json()["places"][0]["kind"] in local.KINDS and not prompts
        r = await c["ann"].post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["city"] == "Denver" and body["state"] == "CO" and body["items"][0]["name"] == "City Park Run Club"
        it = body["items"][0]
        assert it["url"] == "https://cprc.example.org/" and it["kind"] == "run" and it["schedule"] == "Thursdays 6 pm"
        assert it["area"] == "City Park" and it["source"] == "web" and body["chips"]["social_sports"] == "Social sports"
        assert prompts == [localacts.prompt("Denver", "CO")]
        assert "39.7" not in prompts[0] and "104.9" not in prompts[0] and "80204" not in prompts[0]
        # Bob (same city, from his profile) shares the cached search; his zip is geocoded for places.
        r = await c["bob"].post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200 and r.json()["items"] and len(prompts) == 1
        assert r.json()["suggested"][0] == "run" and r.json()["places"]
        assert len(ocalls) == 1  # same rounded spot (39.74,-104.98 and the zip's 39.74,-104.98): cached
    asyncio.run(go())


def test_predict_api(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path, monkeypatch)

    async def go() -> None:
        c = _clients(apps)
        fr = c["friend"]  # Garmin connected (fake): the race predictor answers
        r = await fr.get("/app/api/predict", params={"distance_km": "21.0975", "type": "road"})
        assert r.status_code == 200, r.text
        est = r.json()["estimate"]
        assert est["basis"] == ["Garmin race predictor"] and est["likely"] == 6020 and est["text"] == "1:37–1:44"
        r = await fr.get("/app/api/predict", params={"distance_km": "42.2", "type": "trail", "climb_m": "2400",
                                                     "elevation_m": "2900"})
        b = r.json()["estimate"]["basis"]
        assert "course: +2,400 m climbing" in b and "altitude: 2,900 m" in b
        assert (await fr.get("/app/api/predict", params={"distance_km": "abc"})).status_code == 400
        assert (await fr.get("/app/api/predict", params={"distance_km": "nan"})).status_code == 400
        ev = agent.events.create("friend", {"name": "Spring Half", "date": "2027-04-10", "type": "running",
                                            "distance": "half marathon", "priority": "B"})
        r = await fr.get("/app/api/predict", params={"event_id": ev["id"]})
        assert r.json()["estimate"]["likely"] > 6000
        # Explore cards carry the estimate too.
        r = await c["ann"].get("/app/api/predict", params={"distance_km": "10", "type": "road"})
        assert r.status_code == 200 and r.json()["estimate"] is None and "Connect Garmin" in r.json()["reason"]
    asyncio.run(go())


def test_new_routes_are_athlete_only(env, tmp_path, monkeypatch) -> None:
    _, apps = _apps(env, tmp_path, monkeypatch)

    async def go() -> None:
        coach = _clients(apps)[coach_user_id("c@x.com")]
        assert (await coach.get("/app/api/location")).status_code == 403
        assert (await coach.post("/app/api/location", headers=H, json={"lat": 1, "lon": 1})).status_code == 403
        assert (await coach.request("DELETE", "/app/api/location", headers=H, json={})).status_code == 403
        assert (await coach.post("/app/api/explore/rabbit", headers=H, json={})).status_code == 403
        assert (await coach.post("/app/api/explore/local", headers=H, json={})).status_code == 403
        assert (await coach.get("/app/api/predict", params={"distance_km": "10"})).status_code == 403
        assert (await coach.get("/app/api/explore/nearby")).status_code == 403
        assert (await coach.post("/app/api/location/prefs", headers=H, json={"use_for_local": False})).status_code == 403
        assert (await coach.post("/app/api/location", headers=H, json={"zip": "80204"})).status_code == 403
    asyncio.run(go())


# ----------------------------------------------------- RunSignup next_date --
def test_next_date_series_and_past_filtering() -> None:
    today = date(2026, 10, 14)
    # A series: next_date is the series start (past), next_end_date ahead -> ongoing from today.
    series = rsu_race(70, "Tuesday Night Track", "11/10/2025")
    series["race"]["next_end_date"] = "12/31/2026"
    r = normalize(series, today)
    assert r is not None and r["date"] == "2026-10-14" and r["ongoing"] is True and r["end_date"] == "2026-12-31"
    assert all(e["date"] >= "2026-10-14" for e in r["events"])
    # Without today the raw dates pass through (callers that don't filter).
    assert normalize(series)["date"] == "2025-11-10"
    # A past race whose next occurrence is past is dropped.
    assert normalize(rsu_race(71, "Old Race", "05/01/2026"), today) is None
    # A series with a future event start uses that event.
    multi = rsu_race(72, "Fall Series", "09/01/2026")
    multi["race"]["next_end_date"] = "11/30/2026"
    multi["race"]["events"].append({**multi["race"]["events"][0], "start_time": "10/20/2026 18:00", "name": "Race 3"})
    r = normalize(multi, today)
    assert r["date"] == "2026-10-20" and r["ongoing"] is False
    # Future races are untouched.
    r = normalize(rsu_race(73, "Future", "11/01/2026"), today)
    assert r["date"] == "2026-11-01" and r["ongoing"] is False
    # RaceSearch filters with the window start.
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {None: [series, rsu_race(71, "Old Race", "05/01/2026"),
                                                   rsu_race(73, "Future", "11/01/2026")]}))
    res = asyncio.run(rs.search(explore.parse_filters({}, today)))
    assert [x["name"] for x in res["races"]] == ["Tuesday Night Track", "Future"]
    assert res["races"][0]["date"] == "2026-10-14"


def test_nationwide_labelling_and_open_only() -> None:
    f = explore.parse_filters({}, TODAY)
    assert explore.nationwide(f) and not explore.nationwide(explore.parse_filters({"near": "CO"}, TODAY))
    p = explore.rsu_params(f, None)
    assert "zipcode" not in p and "state" not in p and p["sort"] == "date ASC"
    closed = {**race(1, "A", date(2026, 11, 1)), "registration_open": False}
    opened = race(2, "B", date(2026, 11, 2))
    assert explore.open_only([closed, opened]) == [opened]
    assert "across the US" in explore.NATIONWIDE_NOTE and "add your location" in explore.NATIONWIDE_NOTE


# -------------------------------------------------------------- Overpass --
def test_overpass_query_and_parse() -> None:
    q = local.query(39.74, -104.98)
    assert q.startswith("[out:json][timeout:25];") and "(around:8000,39.74,-104.98)" in q
    for frag in ('"sport"~"^(beachvolleyball|volleyball)$"', '"leisure"="track"', '"sport"="climbing"',
                 '"highway"="trailhead"', '"leisure"="fitness_station"', 'pickleball|tennis', 'pump_track',
                 '"leisure"="swimming_pool"'):
        assert frag in q, frag
    places = local.parse(OVERPASS_BODY, 39.74, -104.98)
    kinds = {p["kind"] for p in places}
    assert kinds == {"volleyball", "track", "trailhead", "fitness", "pickleball", "climbing"}
    assert all(p["name"] != "Condo Pool" for p in places)  # private access dropped
    assert [p["distance_km"] for p in places] == sorted(p["distance_km"] for p in places)
    v = next(p for p in places if p["kind"] == "volleyball")
    assert v["name"] == "Washington Park Sand Courts" and v["osm_url"] == "https://www.openstreetmap.org/way/11"
    assert v["tags"] == {"lit": "yes", "surface": "sand"} and v["lat"] == 39.751
    t = next(p for p in places if p["kind"] == "track")
    assert t["name"] == "Running track" and not t["named"]  # unnamed: the type label
    assert next(p for p in places if p["kind"] == "pickleball")["name"] == "Congress Park Courts"
    assert local.parse("junk", 0, 0) == [] and local.parse({"elements": "x"}, 0, 0) == []
    assert round(local.distance_km(39.74, -104.98, 39.75, -104.98), 2) == 1.11


def test_overpass_client_cache_throttle_and_failure(tmp_path, fernet_key) -> None:
    calls: list = []
    clock = Clock()
    store = AppStore(tmp_path / "app", fernet_key)
    th = geo.Throttle(1.0, clock=clock, sleep=clock.sleep)
    pl = local.Places(contact="ops@example.com", store=store, transport=overpass(calls), throttle=th, clock=clock)

    async def go() -> None:
        a = await pl.near(39.7392, -104.9849)
        b = await pl.near(39.741, -104.981)  # same rounded spot
        assert a == b and len(calls) == 1
        await pl.near(40.02, -105.27)
    asyncio.run(go())
    assert len(calls) == 2 and clock.slept == [1.0]
    assert calls[0]["ua"] == "RabbitTraining/1.0 (+ops@example.com)" and calls[0]["url"] == local.OVERPASS_URL
    # Persisted 7 days: a restart reuses it; a week later it asks again.
    pl2 = local.Places(contact="x", store=store, transport=overpass(calls), throttle=th, clock=clock)
    asyncio.run(pl2.near(39.74, -104.98))
    assert len(calls) == 2
    clock.t += 7 * 86400 + 1
    asyncio.run(pl2.near(39.74, -104.98))
    assert len(calls) == 3
    bad = local.Places(contact="x", transport=overpass([], status=429), throttle=th)
    try:
        asyncio.run(bad.near(1.0, 1.0))
        raise AssertionError("expected OverpassError")
    except local.OverpassError:
        pass


# ----------------------------------------------------------- web scouting --
def test_web_scout_requires_urls_and_prompt_privacy() -> None:
    raw = {"races": [
        {"name": "Linked Race", "date": "2027-03-01", "url": "https://linked.example.org", "type": "trail"},
        {"name": "No Link Race", "date": "2027-03-02", "type": "trail"},
        {"name": "Bad Link", "date": "2027-03-03", "url": "javascript:alert(1)"}]}
    assert [r["name"] for r in explore.clean_web(raw, TODAY)] == ["Linked Race"]
    groups = localacts.clean({"activities": [
        {"name": "Volo Kickball", "category": "social_sports", "url": "https://www.volosports.com/x"},
        {"name": "Invented Club", "category": "run", "url": ""},
        {"name": "Http Club", "category": "run", "url": "http://insecure.example.org"}]})
    assert [g["name"] for g in groups] == ["Volo Kickball"] and groups[0]["source"] == "web"
    assert "Never invent" in localacts.SYSTEM
    assert explore.report_obj('text {"races": []} more') == {"races": []} and explore.report_obj("none") == {}
    main = {"name": "Leadville 100", "date": "2027-08-21", "distance": "ultra"}
    p = rabbitexplore.scout_prompt({"race_types": ["trail"], "distances": ["ultra_50k"], "travel": "regional",
                                    "home_zip": "80204", "months_avoid": [1]},
                                   area="Denver, CO", main=main, goal=None, readiness="behind", today=TODAY)
    assert '"Denver, CO"' in p and "Leadville 100" in p and "a bit behind" in p and "January" in p
    assert "80204" not in p and "oura" not in p.lower() and "zip" not in p.lower()
    p2 = rabbitexplore.scout_prompt({}, area="", main=None, goal={"event": "Boulder 70.3"}, readiness=None, today=TODAY)
    assert "Anywhere in the US" in p2 and "Boulder 70.3" in p2
    # Find more with Rabbit: a zip filter reaches the model as a city/state.
    f = explore.parse_filters({"near": "80204", "radius": "50"}, TODAY)
    assert "80204" not in explore.web_prompt(f)
    assert '"Denver, CO" (within about 50 miles)' in explore.web_prompt(dict(f, area="Denver, CO"))
    assert rabbitexplore.summary(3, 6, 3) == "Rabbit found 12 things for you"
    assert rabbitexplore.summary(1, 0, 0) == "Rabbit found 1 thing for you"


def test_explore_ai_sends_city_not_zip(env, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(geo, "TRANSPORT", nominatim([]))
    agent, apps = _apps(env, tmp_path, monkeypatch)
    monkeypatch.setattr(explore, "_web", WebFinder())
    prompts: list = []

    async def research(system, prompt, **kw):
        prompts.append(prompt)
        return {"races": []}
    agent._backend.research = research  # type: ignore[attr-defined]

    async def go() -> None:
        r = await _clients(apps)["ann"].post("/app/api/explore/ai", headers=H, json={"near": "80204", "radius": 50})
        assert r.status_code == 200, r.text
        assert '"Denver, CO"' in prompts[0] and "80204" not in prompts[0]
    asyncio.run(go())
