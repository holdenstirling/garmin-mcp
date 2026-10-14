"""Explore races: RunSignup query building, normalizing, caching, fit hints, add, AI search, API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
from starlette.applications import Starlette

from garmin_mcp import explore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.explore import (
    ExploreError, RaceSearch, WebFinder, clean_web, defaults, event_fields, fit_hints, merge, normalize,
    parse_distance_km, parse_filters, plain_text, rsu_params, rsu_types,
)
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
H = {"origin": BASE}
TODAY = date(2026, 10, 14)


def _raises(fn, text: str) -> None:
    try:
        fn()
    except ExploreError as e:
        assert text in e.message, e.message
    else:
        raise AssertionError("expected ExploreError")


def rsu_race(rid: int, name: str, when: str, *, etype: str = "trail_race", dist: str | None = "50K",
             city: str = "Golden", desc: str = "<p>Fun <b>race</b></p>") -> dict:
    return {"race": {
        "race_id": rid, "name": name, "next_date": when, "next_end_date": when, "is_registration_open": "T",
        "description": desc, "url": f"https://runsignup.com/Race/CO/Golden/R{rid}",
        "external_race_url": "https://example.org/race", "logo_url": "https://d368g9lw5ileu7.cloudfront.net/x.png",
        "timezone": "America/Denver", "address": {"city": city, "state": "CO", "zipcode": "80401", "country_code": "US"},
        "events": [{"event_id": rid * 10, "name": "Long one", "start_time": f"{when} 07:00", "event_type": etype,
                    "distance": dist, "registration_periods": [
                        {"registration_opens": "1/1/2026 00:00", "registration_closes": "5/1/2027 23:59",
                         "race_fee": "$80.00", "processing_fee": "$5.00"},
                        {"race_fee": "$65.00", "processing_fee": "$4.00"}]}]}}


# ------------------------------------------------------------ pure parts --
def test_query_building_and_type_mapping() -> None:
    f = parse_filters({"near": "80204", "radius": "50", "months": "3", "types": "trail,road",
                       "distance": "half", "q": "  Golden   Gate ", "page": "2"}, TODAY)
    assert f["zip"] == "80204" and f["radius"] == 50 and f["start"] == "2026-10-14" and f["end"] == "2027-01-14"
    assert f["types"] == ["road", "trail"] and f["q"] == "Golden Gate"
    p = rsu_params(f, "trail_race")
    assert p["zipcode"] == "80204" and p["radius"] == "50" and p["event_type"] == "trail_race"
    assert p["min_distance"] == "20.5" and p["max_distance"] == "21.6" and p["distance_units"] == "K"
    assert p["name"] == "Golden Gate" and p["page"] == "2" and p["sort"] == "date ASC" and "state" not in p
    s = parse_filters({"near": "co", "types": ["cycling"], "distance": "ultra"}, TODAY)
    assert s["state"] == "CO" and s["zip"] is None and s["end"] == "2027-04-14"
    ps = rsu_params(s, None)
    assert ps["state"] == "CO" and "zipcode" not in ps and "max_distance" not in ps and "event_type" not in ps
    assert rsu_types(["cycling"]) == (["bike_race", "bike_ride", "gravel_grinder", "mountain_bike_race"], False)
    assert rsu_types(["road", "cycling"])[1] is True and len(rsu_types(["road", "cycling"])[0]) == 4
    assert rsu_types(["gravel", "cycling"])[0][0] == "gravel_grinder"
    assert rsu_types([]) == ([], False)
    _raises(lambda: parse_filters({"near": "Denver"}, TODAY), "zip")
    _raises(lambda: parse_filters({"near": "80204", "radius": "500"}, TODAY), "radius")
    _raises(lambda: parse_filters({"months": "13"}, TODAY), "months")
    _raises(lambda: parse_filters({"types": "road,skydive"}, TODAY), "types")
    _raises(lambda: parse_filters({"distance": "6k"}, TODAY), "distance")
    _raises(lambda: parse_filters({"q": "x" * 61}, TODAY), "60")
    d = parse_filters({"start": "2026-01-01", "end": "2027-03-01"}, TODAY)
    assert d["start"] == "2026-10-14" and d["end"] == "2027-03-01"  # never in the past


def test_distance_parsing() -> None:
    assert parse_distance_km("13.1 Miles") == 21.08
    assert parse_distance_km("26.2 Miles") == 42.16
    assert parse_distance_km("100 Miles") == 160.93
    assert parse_distance_km("50K") == 50 and parse_distance_km("5K") == 5 and parse_distance_km("5k") == 5
    assert parse_distance_km("10 km") == 10 and parse_distance_km("1 Mile") == 1.61
    assert parse_distance_km("1500 m") == 1.5 and parse_distance_km("Sprint") == 25.75
    assert parse_distance_km("Half Marathon") == 21.0975
    assert parse_distance_km(None) is None and parse_distance_km("") is None and parse_distance_km("Kids dash") is None


def test_html_is_stripped_to_plain_text() -> None:
    html = ('<div><h2>About</h2><p>Run&nbsp;the <b>hills</b> &amp; trails.</p>'
            '<script>alert("x")</script><style>p{color:red}</style><img src=x onerror=alert(1)>'
            '&lt;script&gt;bad()&lt;/script&gt; <a href="javascript:alert(1)">link</a></div>')
    t = plain_text(html)
    assert "<" not in t and ">" not in t and "alert(\"x\")" not in t and "color:red" not in t
    assert t.startswith("About Run the hills & trails.") and "link" in t
    long = plain_text("<p>" + "word " * 200 + "</p>")
    assert len(long) <= 400 and long.endswith("…")
    assert plain_text("<p unclosed") == "" or "<" not in plain_text("<p unclosed")
    assert plain_text(None) == ""


def test_normalize_dedupe_and_sort() -> None:
    a = normalize(rsu_race(2, "Bear Chase", "05/22/2027", dist="13.1 Miles"))
    assert a is not None
    assert a["id"] == "rsu:2" and a["date"] == "2027-05-22" and a["city"] == "Golden" and a["state"] == "CO"
    assert a["registration_open"] is True and a["summary"] == "Fun race"
    assert a["url"].startswith("https://runsignup.com") and a["website"] == "https://example.org/race"
    ev = a["events"][0]
    assert ev["distance_km"] == 21.08 and ev["distance_label"] == "13.1 Miles" and ev["type"] == "trail"
    assert ev["start_time"] == "07:00" and ev["fee_from"] == "$65"
    assert normalize({"race": {"race_id": 1, "name": "x", "next_date": "soon"}}) is None
    assert normalize("junk") is None
    b = normalize(rsu_race(1, "Apple Run", "04/01/2027", etype="running_race", dist=None))
    assert b is not None and b["events"][0]["distance_km"] is None and b["types"] == ["road"]
    dup = normalize(rsu_race(2, "Bear Chase", "05/22/2027", etype="ultra"))
    assert dup is not None
    out = merge([[a], [b, dup]])
    assert [r["id"] for r in out] == ["rsu:1", "rsu:2"] and out[1]["types"] == ["trail"] + ["ultra"]


def _mock(calls: list, races_by_type: dict | None = None, status: int = 200):
    def handler(request: httpx2.Request) -> httpx2.Response:
        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(q)
        if status != 200:
            return httpx2.Response(status, text="nope")
        return httpx2.Response(200, json={"races": (races_by_type or {}).get(q.get("event_type"), [])})
    return httpx2.MockTransport(handler)


def test_search_merges_types_and_caches() -> None:
    calls: list = []
    clock = [1000.0]
    s = RaceSearch(transport=_mock(calls, {
        "trail_race": [rsu_race(5, "Later Trail", "06/01/2027"), rsu_race(4, "Shared", "05/01/2027")],
        "running_race": [rsu_race(4, "Shared", "05/01/2027", etype="running_race", dist="10K")],
    }), clock=lambda: clock[0])
    f = parse_filters({"near": "80204", "types": "road,trail"}, TODAY)
    res = asyncio.run(s.search(f))
    assert {c["event_type"] for c in calls} == {"running_race", "trail_race"}
    assert [r["id"] for r in res["races"]] == ["rsu:4", "rsu:5"] and res["has_more"] is False
    asyncio.run(s.search(f))
    assert len(calls) == 2  # cached
    clock[0] += 6 * 3600 + 1
    asyncio.run(s.search(f))
    assert len(calls) == 4  # expired
    for i in range(205):  # bounded
        s.cache.put(str(i), {})
    assert len(s.cache._d) == 200


def test_upstream_errors_are_friendly() -> None:
    s = RaceSearch(transport=_mock([], status=500))
    f = parse_filters({}, TODAY)
    try:
        asyncio.run(s.search(f))
    except ExploreError as e:
        assert e.status == 502 and "Try again" in e.message
    else:
        raise AssertionError("expected ExploreError")

    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow")
    s2 = RaceSearch(transport=httpx2.MockTransport(boom))
    try:
        asyncio.run(s2.search(f))
    except ExploreError as e:
        assert e.status == 502
    else:
        raise AssertionError("expected ExploreError")


def test_fit_hints() -> None:
    main = {"name": "Leadville 100 Run", "date": "2027-08-21", "distance": "ultra"}
    half = {"name": "Mid Half", "date": "2027-07-10", "city": "Boulder",
            "events": [{"distance_km": 21.1}]}
    ids = [h["id"] for h in fit_hints(half, main, {"home_elevation_m": 1609}, TODAY)]
    assert ids == ["tune_up"]  # 6 weeks out, shorter; Boulder isn't higher than home
    close = dict(half, date="2027-08-14")
    assert [h["id"] for h in fit_hints(close, main, {}, TODAY)][0] == "too_close"
    ultra = {"name": "Spring 50", "date": "2027-04-24", "city": "Leadville", "events": [{"distance_km": 80}]}
    hs = fit_hints(ultra, main, {"units": "imperial"}, TODAY)
    assert [h["id"] for h in hs] == ["same_distance", "b_race", "altitude"] and "10,200 ft" in hs[-1]["label"]
    marathon_goal = {"name": "Denver Marathon", "date": "2027-10-17", "distance": "marathon"}
    m = {"name": "Other Marathon", "date": "2027-03-01", "events": [{"distance_km": 42.16}]}
    assert fit_hints(m, marathon_goal, {}, TODAY)[0]["id"] == "same_distance"
    assert fit_hints({"name": "x", "date": "2027-03-01", "events": [{"distance_km": 5}]}, None, {}, TODAY)[0]["id"] == "goal"


def test_add_maps_to_event_fields() -> None:
    race = normalize(rsu_race(9, "Bear Chase", "05/22/2027", dist="13.1 Miles"))
    f = event_fields(race, 0)
    assert f == {"name": "Bear Chase", "date": "2027-05-22", "type": "trail", "distance": "half marathon",
                 "location": "Golden, CO", "url": "https://example.org/race", "priority": "C",
                 "notes": "Found in Explore: Long one, starts 07:00"}
    two = dict(race, events=race["events"] + [dict(race["events"][0], name="5K", distance_km=5.0, type="road")])
    _raises(lambda: event_fields(two, None), "Pick which")
    assert event_fields(two, 1, "B")["distance"] == "5k" and event_fields(two, 1, "B")["type"] == "running"
    tri = dict(race, events=[{"name": "70.3", "distance_km": 113.0, "type": "triathlon"}])
    assert event_fields(tri, 0)["distance"] == "70.3" and event_fields(tri, 0)["type"] == "triathlon"
    ride = dict(race, events=[{"name": "Century", "distance_km": 160.9, "type": "cycling"}], url="javascript:x", website=None)
    rf = event_fields(ride, 0)
    assert rf["distance"] == "century ride" and rf["type"] == "cycling" and rf["url"] == ""
    _raises(lambda: event_fields({"name": ""}, 0), "missing")
    assert defaults({"home_location": "Denver, CO 80204", "favorite_sports": ["run", "trail", "bike", "swim"]}) \
        | {"categories": None, "distances": None} == {"near": "80204", "types": [],
                                                      "radius": 50, "months": 6, "categories": None, "distances": None}
    assert defaults({"home_location": "Leadville"})["near"] == ""


def test_clean_web_is_strict() -> None:
    raw = {"races": [
        {"name": "Leadville Trail 100 Run", "date": "2027-08-21", "location": "Leadville, CO", "type": "ultra",
         "distances": "100 Miles", "url": "https://www.leadvilleraceseries.com", "summary": "<b>High</b> and hard."},
        {"name": "Past race", "date": "2025-01-01", "url": "https://x.org"},
        {"name": "No link", "date": "2027-01-01", "url": "javascript:alert(1)"},
        {"name": "Bad date", "date": "next summer", "url": "https://x.org"},
        {"name": "Ironman 70.3 Boulder", "date": "2027-06-12", "type": "skydive", "distances": "1.9 km / 90 km / 21.1 km",
         "url": "https://www.ironman.com/im703-boulder"},
    ]}
    out = clean_web(raw, TODAY)
    assert [r["name"] for r in out] == ["Ironman 70.3 Boulder", "Leadville Trail 100 Run"]
    lt = out[1]
    assert lt["source"] == "web" and lt["id"].startswith("web:") and lt["city"] == "Leadville" and lt["state"] == "CO"
    assert lt["summary"] == "High and hard." and lt["events"][0]["distance_km"] == 160.93
    assert out[0]["types"] == ["other"] and len(out[0]["events"]) == 3
    assert clean_web("junk", TODAY) == [] and clean_web({"races": "x"}, TODAY) == []


# --------------------------------------------------------------------- API --
def _app(env, tmp_path, user: str = "friend"):
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    auth = WebAuth(settings, env.store, "", dev_user=user)
    return agent, Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))


def test_explore_api(env, tmp_path, monkeypatch) -> None:
    agent, app = _app(env, tmp_path)
    today = agent._now("friend").date()
    soon = (today + timedelta(days=60))
    calls: list = []
    monkeypatch.setattr(explore, "_default", RaceSearch(transport=_mock(calls, {
        None: [rsu_race(7, "Golden Half", soon.strftime("%m/%d/%Y"), dist="13.1 Miles")]})))
    monkeypatch.setattr(explore, "_web", WebFinder())
    agent.coach.update_athlete("friend", {"home_location": "Denver 80204", "favorite_sports": ["trail"]})
    research_calls: list = []

    async def fake_research(system, prompt, **kw):
        research_calls.append(prompt)
        assert kw["report_tool"]["name"] == "report_races" and "oura" not in prompt.lower()
        return {"races": [{"name": "Big Famous 100", "date": (today + timedelta(days=200)).isoformat(),
                           "location": "Leadville, CO", "type": "ultra", "distances": "100 Miles",
                           "url": "https://example.com/big"}]}
    agent._backend.research = fake_research  # type: ignore[attr-defined]

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/explore/defaults")
            assert r.status_code == 200 and r.json()["near"] == "80204" and r.json()["types"] == []
            r = await c.get("/app/api/explore", params={"near": "80204", "radius": "25", "months": "6"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["races"][0]["id"] == "rsu:7" and body["races"][0]["hints"] == []
            assert calls[0]["zipcode"] == "80204" and calls[0]["radius"] == "25"
            r = await c.get("/app/api/explore", params={"near": "nowhere"})
            assert r.status_code == 400 and "zip" in r.json()["error"]
            # add -> event, twice -> same event
            race = body["races"][0]
            assert (await c.post("/app/api/explore/add", json={"race": race, "event_index": 0})).status_code == 403  # origin
            r = await c.post("/app/api/explore/add", headers=H, json={"race": race, "event_index": 0})
            assert r.status_code == 201, r.text
            ev = r.json()["event"]
            assert ev["name"] == "Golden Half" and ev["priority"] == "C" and ev["distance"] == "half marathon"
            assert ev["location"] == "Golden, CO" and ev["notes"].startswith("Found in Explore")
            r = await c.post("/app/api/explore/add", headers=H, json={"race": race, "event_index": 0})
            assert r.status_code == 200 and r.json()["already"] is True and len(r.json()["events"]) == 1
            r = await c.post("/app/api/explore/add", headers=H, json={"race": {"name": "x" * 130, "date": "nope"}})
            assert r.status_code == 400
            # AI search: cached per query, 5 a day
            r = await c.post("/app/api/explore/ai", headers=H, json={"near": "80204", "types": ["ultra"]})
            assert r.status_code == 200, r.text
            assert r.json()["races"][0]["source"] == "web" and r.json()["races"][0]["name"] == "Big Famous 100"
            await c.post("/app/api/explore/ai", headers=H, json={"near": "80204", "types": ["ultra"]})
            assert len(research_calls) == 1
            for i in range(4):
                r = await c.post("/app/api/explore/ai", headers=H, json={"q": f"race {i}"})
                assert r.status_code == 200, r.text
            r = await c.post("/app/api/explore/ai", headers=H, json={"q": "one more"})
            assert r.status_code == 400 and "used up" in r.json()["error"]
    asyncio.run(go_())


def test_explore_ai_failure_is_friendly(env, tmp_path, monkeypatch) -> None:
    agent, app = _app(env, tmp_path)
    monkeypatch.setattr(explore, "_web", WebFinder())

    async def broken(system, prompt, **kw):
        raise RuntimeError("api down")
    agent._backend.research = broken  # type: ignore[attr-defined]

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/explore/ai", headers=H, json={})
            assert r.status_code == 502 and "Try again" in r.json()["error"]
            monkeypatch.setattr(explore, "_default", RaceSearch(transport=_mock([], status=503)))
            r = await c.get("/app/api/explore")
            assert r.status_code == 502 and "Try again" in r.json()["error"]
    asyncio.run(go_())


def test_coach_accounts_cannot_explore(env, tmp_path) -> None:
    _, app = _app(env, tmp_path, user=coach_user_id("coach@example.com"))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            assert (await c.get("/app/api/explore")).status_code == 403
            assert (await c.get("/app/api/explore/defaults")).status_code == 403
            assert (await c.post("/app/api/explore/ai", headers=H, json={})).status_code == 403
            assert (await c.post("/app/api/explore/add", headers=H, json={})).status_code == 403
    asyncio.run(go_())
