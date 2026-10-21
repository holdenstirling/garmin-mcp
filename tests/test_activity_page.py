"""The page for one recorded workout (activitypage.py) and GET /app/api/activity/{id}."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2

from garmin_mcp import activitypage as ap
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plancal import ATHLETE
from tests.test_profile import BASE, _apps

ZONES_ATH = {"max_hr": 190}


def test_view_shapes_numbers_laps_and_zones() -> None:
    act = {"activity_id": 42, "date": "2026-10-13 07:00:00", "name": "Morning Run", "sport": "running",
           "duration": "0:50:00", "moving_duration": "0:48:00", "distance_km": 10.0, "avg_hr": 150, "max_hr": 172,
           "avg_cadence": 172, "elevation_gain_m": 80, "avg_pace_per_km": "4:48", "training_load": 95}
    laps = [{"d": 1000.0, "s": 290.0, "hr": 120}, {"d": 1000.0, "s": 285.0, "hr": 150}, {"d": 1000.0, "s": 280.0, "hr": 175}]
    v = ap.build_view(act, laps=laps, extra={"calories": 610, "elapsed_s": 3000}, athlete=ZONES_ATH)
    n = v["numbers"]
    assert v["sport"] == "run" and v["ai"] is True and v["garmin_url"].endswith("/42")
    assert n["km"] == 10.0 and n["moving_s"] == 2880 and n["elapsed_s"] == 3000 and n["pace_s_per_km"] == 288
    assert n["cadence"] == 172 and n["cadence_unit"] == "spm" and n["calories"] == 610 and n["training_load"] == 95
    assert [r["n"] for r in v["laps"]] == [1, 2, 3] and v["laps"][2]["hr"] == 175 and v["laps"][0]["pace_s_per_km"] == 290
    z = {x["zone"]: x["s"] for x in v["zones"]["zones"]}
    assert v["zones"]["basis"] == "laps" and z[2] == 290 and z[3] == 285 and z[5] == 280  # % of 190 max: z2 114+, z3 133+, z5 171+
    # No laps: the whole workout in the zone of its average (an estimate); no HR numbers: no zones.
    v2 = ap.build_view(act, athlete=ZONES_ATH)
    assert v2["zones"]["basis"] == "average" and v2["laps"] == []
    assert ap.build_view(act, athlete={})["zones"] is None
    ride = ap.build_view({"activity_id": 7, "sport": "road_biking", "duration": 3600, "distance_km": 30.0,
                          "avg_speed_kmh": 30.0}, extra={"bike_cadence": 88})
    assert ride["sport"] == "bike" and ride["numbers"]["cadence"] == 88 and ride["numbers"]["cadence_unit"] == "rpm"
    assert "pace_s_per_km" not in ride["numbers"] and ride["numbers"]["speed_kmh"] == 30.0


def test_imported_workouts_are_display_only() -> None:
    v = ap.build_imported({"key": "oura:abc", "source": "oura", "sport": "run", "name": "Running",
                           "start": "2026-10-13T07:00:00", "minutes": 40, "km": 8.0, "avg_hr": 150})
    assert v["ai"] is False and v["source"] == "oura" and v["garmin_url"] is None
    assert v["numbers"]["pace_s_per_km"] == 300 and v["laps"] == [] and v["zones"] is None
    assert ap.checkin_ref("oura:a.b") == "oura_a_b"
    assert ap.extra_from({"summaryDTO": {"calories": 501.4, "averageBikeCadence": 90.2, "elapsedDuration": 3700.0}}) \
        == {"calories": 501, "bike_cadence": 90, "elapsed_s": 3700}
    assert ap.extra_from(None) == {}


def test_activity_route(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    _, acts = agent.stats.activities("friend")
    # the synthetic week rotates by weekday: pick one with a distance (not an indoor ride)
    aid = next((a for a in acts if a.get("distance_km") or a.get("distance")), acts[0])["activity_id"]
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get(f"/app/api/activity/{aid}")
            assert r.status_code == 200, r.text
            v = r.json()
            assert v["id"] == aid and v["numbers"].get("km") and v["checkin"] is None and v["ai"] is True
            r = await a.post("/app/api/checkins", headers=h, json={"text": "", "activity_id": aid, "rpe": 8})
            assert r.status_code == 201, r.text
            v = (await a.get(f"/app/api/activity/{aid}")).json()
            assert v["checkin"]["rpe"] == 8 and v["feedback"]["lines"]
            assert (await a.get("/app/api/activity/999999999")).status_code == 404  # not theirs / unknown
            assert (await a.get("/app/api/activity/oura:nothere")).status_code == 404
            bad = await a.get("/app/api/activity/x%20y")
            assert bad.status_code == 400, (bad.status_code, bad.text)
            assert (await c.get(f"/app/api/activity/{aid}")).status_code == 403
    asyncio.run(go_())
