"""Gear garage: validation, mileage, status, Garmin import, API, race pack warnings."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.gear import (BIKE_BRANDS, MAX_ITEMS, SHOE_BRANDS, SHOE_SIZES, BIKE_SIZES, GearError, GearStore,
                             clean, for_race, from_garmin, garmin_defaults, usage)
from garmin_mcp.progress import GEAR_XP, Progress
from garmin_mcp.racepack import build
from garmin_mcp.stats import compute
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 14)
H = {"origin": BASE}


def act(d: date, sport: str = "running", km: float = 10.0, aid: int | None = None, **extra):
    return {"activity_id": aid or int(d.strftime("%Y%m%d")), "date": f"{d.isoformat()} 07:00:00", "sport": sport,
            "duration": "0:50:00", "distance_km": km, **extra}


def store(env) -> GearStore:
    return GearStore(env.store, today=lambda _u: TODAY)


# ------------------------------------------------------------- validation --
def test_catalogs_are_broad() -> None:
    assert len(SHOE_BRANDS) >= 40 and len(BIKE_BRANDS) >= 40
    assert {"Hoka", "Norda", "361°", "Saysh"} <= set(SHOE_BRANDS) and {"Cervélo", "Quintana Roo", "Chapter2"} <= set(BIKE_BRANDS)
    assert "US 10.5" in SHOE_SIZES and "US 16" in SHOE_SIZES and "EU 50" in SHOE_SIZES
    assert "56 cm" in BIKE_SIZES and "XXL" in BIKE_SIZES


def test_validation() -> None:
    it = clean({"kind": "shoes", "brand": "  Hoka ", "model": "Clifton 9", "size": "US 10.5"}, TODAY)
    assert it["brand"] == "Hoka" and it["alert_km"] == 640 and it["sports"] == ["run"] and it["added"] == TODAY.isoformat()
    bike = clean({"kind": "bike", "brand": "Trek", "bike_type": "gravel", "shoe_type": "trail"}, TODAY)
    assert bike["alert_km"] is None and bike["bike_type"] == "gravel" and bike["shoe_type"] is None
    bad = [
        {"kind": "skis", "brand": "x"},
        {"kind": "shoes"},                                   # needs a name
        {"kind": "shoes", "brand": "x" * 61},
        {"kind": "shoes", "brand": "x", "size": "x" * 21},
        {"kind": "shoes", "brand": "x", "notes": "x" * 301},
        {"kind": "shoes", "brand": "x", "start_km": -1},
        {"kind": "shoes", "brand": "x", "alert_km": 1e9},
        {"kind": "shoes", "brand": "x", "start_km": True},
        {"kind": "shoes", "brand": "x", "shoe_type": "moon"},
        {"kind": "bike", "brand": "x", "bike_type": "tandem"},
        {"kind": "shoes", "brand": "x", "sports": ["run", "fly"]},
        {"kind": "shoes", "brand": "x", "added": "2099-01-01"},
        {"kind": "shoes", "brand": "x", "activity_ids": ["1"]},
    ]
    for b in bad:
        with pytest.raises(GearError):
            clean(b, TODAY)
    # default_for implies the sport is used
    assert clean({"kind": "shoes", "brand": "x", "sports": [], "default_for": ["hike"]}, TODAY)["sports"] == ["hike"]


def test_item_limit_and_one_default_per_sport(env) -> None:
    gs = store(env)
    a = gs.create("u", {"kind": "shoes", "brand": "Hoka", "model": "Speedgoat"})
    assert a["default_for"] == ["run"]  # first shoes become the run default
    b = gs.create("u", {"kind": "shoes", "brand": "Nike", "model": "Pegasus"})
    assert b["default_for"] == []
    gs.update("u", b["id"], {"default_for": ["run"]})
    items = {x["id"]: x for x in gs.list("u")}
    assert items[a["id"]]["default_for"] == [] and items[b["id"]]["default_for"] == ["run"]
    with pytest.raises(GearError):
        gs.update("u", "nope", {"brand": "x"})
    for i in range(MAX_ITEMS - 2):
        gs.create("u", {"kind": "other", "nickname": f"thing {i}"})
    with pytest.raises(GearError, match="full"):
        gs.create("u", {"kind": "other", "nickname": "one too many"})


# ---------------------------------------------------------------- mileage --
def test_mileage_default_tagging_start_km_and_retirement() -> None:
    added = (TODAY - timedelta(days=30)).isoformat()
    road = {**clean({"kind": "shoes", "brand": "Nike", "start_km": 100, "default_for": ["run"]}, TODAY), "id": "road",
            "added": added}
    trail = {**clean({"kind": "shoes", "brand": "Hoka", "activity_ids": [2]}, TODAY), "id": "trail", "added": added}
    bike = {**clean({"kind": "bike", "brand": "Canyon", "default_for": ["bike"]}, TODAY), "id": "bike", "added": added}
    acts = [
        act(TODAY - timedelta(days=60), aid=1),                    # before it was added
        act(TODAY - timedelta(days=5), aid=2, km=20),              # tagged to the trail shoes
        act(TODAY - timedelta(days=3), aid=3, km=8),               # default run
        act(TODAY - timedelta(days=2), sport="trail_running", aid=4, km=12),
        act(TODAY - timedelta(days=1), sport="cycling", aid=5, km=50),
        act(TODAY - timedelta(days=1), sport="multi_sport", aid=6, km=60, multisport={"is_parent": True}),
        act(TODAY - timedelta(days=1), sport="running", aid=7, km=10, multisport={"parent_id": 6}),
    ]
    v = {x["id"]: x for x in usage([road, trail, bike], acts)}
    assert v["road"]["total_km"] == 100 + 8 + 12 + 10 and v["road"]["activities"] == 3
    assert v["road"]["last_used"] == (TODAY - timedelta(days=1)).isoformat()
    assert v["trail"]["total_km"] == 20 and v["trail"]["activities"] == 1
    assert v["bike"]["total_km"] == 50 and v["bike"]["pct_of_alert"] is None and v["bike"]["status"] == "ok"
    # retired items stop counting after retired_on
    road_ret = {**road, "retired": True, "retired_on": (TODAY - timedelta(days=3)).isoformat()}
    assert usage([road_ret, trail], acts)[1]["total_km"] == 108  # retired sorts last
    # Garmin's number wins for linked gear
    linked = {**trail, "garmin_uuid": "abcd-1234-ef"}
    g = usage([linked], acts, {"abcd-1234-ef": {"totalDistance": 321000, "totalActivities": 40}})[0]
    assert g["total_km"] == 321 and g["activities"] == 40 and g["source"] == "garmin"


def test_status_thresholds() -> None:
    base = clean({"kind": "shoes", "brand": "x", "alert_km": 100, "default_for": []}, TODAY)
    for start, status, pct in ((79, "ok", 79), (80, "soon", 80), (99, "soon", 99), (100, "retire", 100), (150, "retire", 150)):
        u = usage([{**base, "start_km": start}], [])[0]
        assert (u["status"], u["pct_of_alert"]) == (status, pct)


# ------------------------------------------------------------ Garmin import --
GARMIN_GEAR = [
    {"uuid": "aaaa-1111", "gearTypeName": "Shoes", "gearMakeName": "Hoka", "gearModelName": "Mach 6",
     "displayName": "Tempo shoes", "gearStatusName": "active", "maximumMeters": 800000, "dateBegin": "2026-05-01T00:00:00.0"},
    {"uuid": "bbbb-2222", "gearTypeName": "Bike", "gearMakeName": "Other", "customMakeModel": "Canyon Speedmax",
     "displayName": "", "gearStatusName": "active"},
    {"uuid": "cccc-3333", "gearTypeName": "Shoes", "gearMakeName": "Nike", "gearModelName": "Vaporfly",
     "gearStatusName": "retired"},
    {"uuid": "../etc", "gearTypeName": "Shoes", "displayName": "bad uuid"},
    "junk",
]


def test_garmin_mapping() -> None:
    p = from_garmin(GARMIN_GEAR[0], {"aaaa-1111": ["run"]})
    assert p and p["kind"] == "shoes" and p["brand"] == "Hoka" and p["model"] == "Mach 6" and p["nickname"] == "Tempo shoes"
    assert p["alert_km"] == 800 and p["added"] == "2026-05-01" and p["default_for"] == ["run"]
    b = from_garmin(GARMIN_GEAR[1], {})
    assert b and b["kind"] == "bike" and b["brand"] == "" and b["model"] == "Canyon Speedmax"
    assert from_garmin(GARMIN_GEAR[3], {}) is None
    assert garmin_defaults([{"uuid": "aaaa-1111", "typeKey": "trail_running"}, {"uuid": "x", "typeKey": "cycling",
                                                                                "defaultGear": False}]) == {"aaaa-1111": ["run"]}


def test_garmin_import_creates_then_updates(env) -> None:
    gs = store(env)
    r = gs.import_garmin("u", GARMIN_GEAR, [{"uuid": "aaaa-1111", "typeKey": "running"}])
    assert r == {"created": 3, "updated": 0, "skipped": 0}
    items = {x["garmin_uuid"]: x for x in gs.list("u")}
    assert items["cccc-3333"]["retired"] and items["cccc-3333"]["default_for"] == []
    assert items["aaaa-1111"]["default_for"] == ["run"] and items["aaaa-1111"]["alert_km"] == 800
    gs.update("u", items["aaaa-1111"]["id"], {"size": "US 10", "nickname": "My tempo pair"})
    again = [dict(GARMIN_GEAR[0], gearModelName="Mach 6 v2"), GARMIN_GEAR[1]]
    assert gs.import_garmin("u", again) == {"created": 0, "updated": 2, "skipped": 0}
    a = next(x for x in gs.list("u") if x["garmin_uuid"] == "aaaa-1111")
    assert a["model"] == "Mach 6 v2" and a["size"] == "US 10" and a["nickname"] == "My tempo pair"
    assert len(gs.list("u")) == 3


# ------------------------------------------------------------ gamification --
def test_gear_xp_is_awarded_once(env) -> None:
    p = Progress(env.store, clock=lambda: 0.0)
    stats = compute([], TODAY)
    p.update("u", acts=[], today=TODAY, stats=stats, plan_key=None, quests={})
    r = p.update("u", acts=[], today=TODAY, stats=stats, plan_key=None, quests={"gear": True},
                 bonus={"gear:g1": GEAR_XP})
    assert r["gained"] == GEAR_XP + 50  # the item plus the optional quest
    r = p.update("u", acts=[], today=TODAY, stats=stats, plan_key=None, quests={"gear": True},
                 bonus={"gear:g1": GEAR_XP, "gear:g2": GEAR_XP})
    assert r["gained"] == GEAR_XP


# --------------------------------------------------------------- race pack --
def test_racepack_gear_warnings() -> None:
    worn = {**clean({"kind": "shoes", "brand": "Nike", "model": "Pegasus", "start_km": 560, "default_for": ["run"]}, TODAY), "id": "worn"}
    fresh = {**clean({"kind": "shoes", "brand": "Saucony", "model": "Endorphin Pro", "default_for": []}, TODAY), "id": "fresh"}
    bike = {**clean({"kind": "bike", "brand": "Cervélo", "model": "P5"}, TODAY), "id": "bike"}
    suit = {**clean({"kind": "wetsuit", "brand": "Roka"}, TODAY), "id": "suit"}
    old = {**clean({"kind": "shoes", "brand": "Old", "retired": True}, TODAY), "id": "old"}
    views = usage([worn, fresh, bike, suit, old], [])
    run = build({"name": "Denver Marathon", "type": "running", "distance": "marathon", "date": "2026-10-20"}, {}, None, TODAY,
                gear=views)
    mine = {g["id"]: g for g in run["your_gear"]}
    assert set(mine) == {"worn", "fresh"} and run["gear"]  # generic checklist kept
    assert "88%" in (mine["worn"]["warning"] or "") and "break them in" in (mine["fresh"]["warning"] or "")
    tri = build({"name": "Boulder 70.3", "type": "triathlon", "distance": "70.3", "date": "2026-10-20"}, {"units": "imperial"},
                None, TODAY, gear=views)
    assert [g["kind"] for g in tri["your_gear"]] == ["shoes", "shoes", "bike", "wetsuit"]
    assert "348 mi" in (tri["your_gear"][0]["warning"] or "")
    assert for_race(views, "cycling")[0]["id"] == "bike"
    assert build({"name": "x", "type": "running", "date": "2026-10-20"}, {}, None, TODAY)["your_gear"] == []


# --------------------------------------------------------------------- API --
def _app(env, tmp_path, user="friend"):
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    auth = WebAuth(settings, env.store, "", dev_user=user)
    return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))


def test_gear_api_end_to_end(env, tmp_path, monkeypatch) -> None:
    app = _app(env, tmp_path)
    monkeypatch.setattr(env.service, "gear_list", lambda uid: {"gear": GARMIN_GEAR[:2], "defaults": None})
    monkeypatch.setattr(env.service, "gear_stats", lambda uid, u: {"totalDistance": 123400.0, "totalActivities": 9})

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/gear")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["items"] == [] and "Hoka" in body["brands"]["shoes"] and "US 10.5" in body["sizes"]["shoes"]
            assert (await c.post("/app/api/gear", json={"kind": "shoes", "brand": "Hoka"})).status_code == 403  # origin
            r = await c.post("/app/api/gear", headers=H, json={"kind": "shoes", "brand": "Hoka", "model": "Clifton",
                                                               "start_km": 5})
            assert r.status_code == 201, r.text
            gid = r.json()["item_id"]
            shoe = next(x for x in r.json()["items"] if x["id"] == gid)
            # FakeGarmin's 10 km run is from before the item was added, so only start_km counts.
            assert shoe["total_km"] == 5 and shoe["status"] == "ok" and shoe["default_for"] == ["run"]
            r = await c.post("/app/api/gear", headers=H, json={"kind": "shoes", "brand": "x" * 61})
            assert r.status_code == 400 and "60" in r.json()["error"]
            r = await c.patch(f"/app/api/gear/{gid}", headers=H, json={"start_km": 600})
            assert next(x for x in r.json()["items"] if x["id"] == gid)["status"] == "soon"
            r = await c.post(f"/app/api/gear/{gid}/retire", headers=H, json={})
            assert next(x for x in r.json()["items"] if x["id"] == gid)["retired"]
            r = await c.post("/app/api/gear/import-garmin", headers=H, json={})
            assert r.status_code == 200, r.text
            assert r.json()["imported"]["created"] == 2
            linked = next(x for x in r.json()["items"] if x.get("garmin_uuid") == "aaaa-1111")
            assert linked["total_km"] == 123.4 and linked["source"] == "garmin"
            p = (await c.get("/app/api/progress")).json()
            assert next(q for q in p["quests"] if q["id"] == "gear")["done"]
            assert (await c.request("DELETE", f"/app/api/gear/{gid}", headers=H, json={})).status_code == 200
            assert (await c.request("DELETE", f"/app/api/gear/{gid}", headers=H, json={})).status_code == 400
            assert len((await c.get("/app/api/gear")).json()["items"]) == 2
    asyncio.run(go_())


def test_garmin_import_errors_are_friendly(env, tmp_path, monkeypatch) -> None:
    from garmin_mcp.providers import GarminError
    app = _app(env, tmp_path)

    def boom(uid):
        raise GarminError("Garmin is having a moment.")

    def crash(uid):
        raise KeyError("profileId")

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            monkeypatch.setattr(env.service, "gear_list", boom)
            r = await c.post("/app/api/gear/import-garmin", headers=H, json={})
            assert r.status_code == 502 and "having a moment" in r.json()["error"]
            monkeypatch.setattr(env.service, "gear_list", crash)
            r = await c.post("/app/api/gear/import-garmin", headers=H, json={})
            assert r.status_code == 502 and "Try again" in r.json()["error"]
    asyncio.run(go_())


def test_coach_accounts_cannot_use_gear(env, tmp_path) -> None:
    app = _app(env, tmp_path, user=coach_user_id("coach@example.com"))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            assert (await c.get("/app/api/gear")).status_code == 403
            assert (await c.post("/app/api/gear", headers=H, json={"kind": "shoes", "brand": "x"})).status_code == 403
            assert (await c.post("/app/api/gear/import-garmin", headers=H, json={})).status_code == 403
            assert (await c.request("DELETE", "/app/api/gear/g1", headers=H, json={})).status_code == 403
    asyncio.run(go_())
