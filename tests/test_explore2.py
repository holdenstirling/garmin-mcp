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

from garmin_mcp import explore, foryou, geo, localacts, rabbitexplore
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
            return httpx2.Response(200, json=[{"address": {"city": "Denver", "state": "Colorado",
                                                           "ISO3166-2-lvl4": "US-CO", "country_code": "us"}}])
        return httpx2.Response(200, json=body)
    return httpx2.MockTransport(handler)


# -------------------------------------------------------------- location --
def test_location_resolution_order() -> None:
    auto = {"zip": "80461", "city": "Leadville", "state": "CO", "lat2": 39.25, "lon2": -106.29, "ts": 1}
    athlete = {"home_location": "Baker, Denver CO 80204"}
    assert geo.resolve({"home_zip": "80302"}, athlete, auto)["source"] == "device"
    assert geo.resolve({"home_zip": "80302"}, athlete, auto)["zip"] == "80461"
    r = geo.resolve({"home_zip": "80302"}, athlete, None)
    assert r["source"] == "home_zip" and r["zip"] == "80302" and r["city"] == ""
    r = geo.resolve({}, athlete, None)
    assert r == {"source": "profile_zip", "zip": "80204", "state": "CO", "city": "Denver"}
    r = geo.resolve({}, {"home_location": "Leadville, Colorado"}, None)
    assert r["source"] == "profile_city" and r["state"] == "CO" and r["city"] == "Leadville" and r["zip"] == ""
    assert geo.resolve({}, {"home_location": "Kansas City, MO"}, None)["state"] == "MO"
    # Lower-case words aren't state codes; unknown text resolves to nothing.
    assert geo.resolve({}, {"home_location": "out in the hills or me"}, None)["source"] is None
    assert geo.resolve(None, None, None)["source"] is None
    # A device place outside the US keeps the city (for local activities) but isn't searchable.
    r = geo.resolve({}, {}, {"zip": "", "city": "Chamonix", "state": "Auvergne-Rhône-Alpes"})
    assert r["source"] is None and r["city"] == "Chamonix"
    assert geo.label({"city": "Denver", "state": "CO"}) == "Denver, CO" and geo.label({"zip": "80204"}) == "80204"


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
    assert all(c["ua"] == "RabbitTraining/1.0 (contact: me@example.com)" for c in calls)
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
    assert blank["race_types"] == ["road", "trail"] and blank["distances"]
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


# predict: see tests/test_predict.py


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

    async def go() -> None:
        c = _clients(apps)
        ann = c["ann"]
        r = await ann.get("/app/api/location")
        assert r.status_code == 200 and r.json()["device"] is None and r.json()["resolved"]["source"] is None
        assert (await ann.post("/app/api/location", json={"lat": 39.739154, "lon": -104.984703})).status_code == 403
        r = await ann.post("/app/api/location", headers=H, json={"lat": 39.739154, "lon": -104.984703})
        assert r.status_code == 200, r.text
        assert r.json()["device"]["city"] == "Denver" and r.json()["resolved"]["label"] == "Denver, CO"
        assert r.json()["resolved"]["source"] == "device" and r.json()["resolved"]["searchable"]
        assert calls[0]["q"]["lat"] == "39.74" and calls[0]["q"]["lon"] == "-104.98"
        assert calls[0]["ua"] == "RabbitTraining/1.0 (contact: ops@example.com)"
        prof = env.store.user_doc("ann", "profile").load()
        assert set(prof["location_auto"]) == set(geo.AUTO_KEYS)
        assert prof["location_auto"]["lat2"] == 39.74 and prof["location_auto"]["lon2"] == -104.98
        dumped = json.dumps(prof)
        assert "39.739" not in dumped and "104.984" not in dumped and "athlete" not in prof
        # Never in Rabbit's context.
        from datetime import datetime
        ctx = agent.coach.context_block("ann", datetime(2026, 10, 14, tzinfo=UTC), None)
        assert "Denver" not in ctx and "80204" not in ctx
        assert (await ann.post("/app/api/location", headers=H, json={"lat": 300, "lon": 0})).status_code == 400
        # Forget.
        r = await ann.request("DELETE", "/app/api/location", headers=H, json={})
        assert r.status_code == 200 and r.json()["device"] is None
        assert "location_auto" not in env.store.user_doc("ann", "profile").load()
    asyncio.run(go())


def test_foryou_never_empty(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path, monkeypatch)
    today = agent._now("ann").date()
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {
        "running_race": [rsu_race(1, "Denver Half", (today + timedelta(days=70)).strftime("%m/%d/%Y"),
                                  etype="running_race", dist="13.1 Miles")],
        "trail_race": [rsu_race(2, "Golden Trail Half", (today + timedelta(days=90)).strftime("%m/%d/%Y"),
                                dist="13.1 Miles")]}))
    monkeypatch.setattr(foryou, "_default", foryou.ForYou(search=lambda: rs))
    monkeypatch.setattr(explore, "_default", rs)

    async def go() -> None:
        c = _clients(apps)
        # No interests, no location: popular big races + an inferred-defaults flag.
        body = (await c["ann"].get("/app/api/explore/foryou")).json()
        assert body["has_interests"] is False and body["inferred"] is True
        assert body["location"]["source"] is None and not body["location"]["searchable"]
        pop = next(s for s in body["sections"] if s["id"] == "popular")
        assert pop["races"] and all(r.get("check_dates") for r in pop["races"])
        assert {cl.get("name") for cl in calls} >= {"Boston Marathon"}  # verified on RunSignup by name
        # A city/state in the profile is enough: inferred interests rank real picks (no empty state).
        agent.coach.update_athlete("bob", {"home_location": "Denver, CO", "favorite_sports": ["run"]})
        calls.clear()
        body = (await c["bob"].get("/app/api/explore/foryou")).json()
        assert body["inferred"] is True and body["location"]["source"] == "profile_city"
        assert all(cl.get("state") == "CO" for cl in calls) and {cl.get("event_type") for cl in calls} == {"running_race"}
        picks = next(s for s in body["sections"] if s["id"] == "picks")
        assert picks["races"][0]["name"] == "Denver Half" and picks["races"][0]["why"]
        assert "popular" not in [s["id"] for s in body["sections"]]
        assert body["effective"]["travel"] == "regional" and "road" in body["effective"]["race_types"]
    asyncio.run(go())


def test_let_rabbit_explore_api(env, tmp_path, monkeypatch) -> None:
    agent, apps = _apps(env, tmp_path, monkeypatch)
    today = agent._now("ann").date()
    a_race = today + timedelta(weeks=20)
    calls: list = []
    rs = RaceSearch(transport=_mock(calls, {"trail_race": [
        rsu_race(1, "Tune Trail Half", (a_race - timedelta(weeks=5)).strftime("%m/%d/%Y"), dist="13.1 Miles"),
        rsu_race(2, "Winter Trail 50K", (today + timedelta(days=40)).strftime("%m/%d/%Y"), dist="50K")]}))
    monkeypatch.setattr(explore, "_default", rs)
    monkeypatch.setattr(explore, "_web", WebFinder())
    agent.events.create("ann", {"name": "Big Trail 100", "date": a_race.isoformat(), "type": "trail",
                                "distance": "ultra", "priority": "A"})
    agent.coach.update_athlete("ann", {"home_location": "Golden, CO 80401"})
    prompts: list = []

    async def research(system, prompt, **kw):
        prompts.append(prompt)
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
        assert names.count("Tune Trail Half") == 1 and "Famous Mountain 50" in names
        assert body["races"][0]["name"] == "Tune Trail Half" and body["races"][0]["source"] == "runsignup"
        assert body["intro"] == "Found 3 races within 250 mi in the next 6 months; 1 is a great tune-up for Big Trail 100."
        assert body["web"] == "ok" and body["inferred"] is True and all(x["why"] for x in body["races"])
        assert calls[0]["zipcode"] == "80401" and calls[0]["radius"] == "250"
        assert "80401" in prompts[0] and "Golden" not in prompts[0] and "oura" not in prompts[0].lower()
        # Second tap: the web part is cached (no new research, no allowance).
        r = await c["ann"].post("/app/api/explore/rabbit", headers=H, json={})
        assert r.status_code == 200 and len(prompts) == 1
    asyncio.run(go())


def test_local_api_shares_city_cache_and_sends_only_city(env, tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(geo, "TRANSPORT", nominatim(calls))
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
        r = await c["ann"].post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200 and r.json()["needs_location"] is True and r.json()["items"] == []
        r = await c["ann"].post("/app/api/location", headers=H, json={"lat": 39.7392, "lon": -104.9903})
        assert r.status_code == 200
        r = await c["ann"].post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["city"] == "Denver" and body["state"] == "CO" and body["items"][0]["name"] == "City Park Run Club"
        assert body["items"][0]["url"] == "https://cprc.example.org/" and body["chips"]["social_sports"] == "Social sports"
        assert prompts == [localacts.prompt("Denver", "CO")]
        assert "39.7" not in prompts[0] and "104.9" not in prompts[0] and "80204" not in prompts[0]
        # Bob (same city, from his profile) shares the cached search.
        r = await c["bob"].post("/app/api/explore/local", headers=H, json={})
        assert r.status_code == 200 and r.json()["items"] and len(prompts) == 1
        assert r.json()["suggested"][0] == "run"
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
    asyncio.run(go())
