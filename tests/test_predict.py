"""Race finish-time estimates (predict.py): Riegel anchors that prefer hard efforts, trail
climbing/altitude/ultra fatigue, 100-mile cutoffs, triathlon splits, the plan projection,
and the athlete/generic/coach APIs."""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

import httpx2

from garmin_mcp import predict
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _athlete
from tests.test_profile import BASE, COACH, _apps

TODAY = date(2026, 10, 14)
GARMIN = {"time5K": 1290, "time10K": 2710, "timeHalfMarathon": 6020, "timeMarathon": 12780}
H = {"origin": BASE}


def run(day: str, km: float, dur: str, **kw) -> dict:
    return {"sport": "running", "date": f"{day} 07:00:00", "distance_km": km, "duration": dur} | kw


ACTS = [
    run("2026-09-21", 10.0, "0:47:30", event="race", name="Fall 10K"),
    run("2026-10-08", 8.0, "0:46:00", name="Easy run", avg_hr=128),  # easy: discounted, not preferred
    run("2026-10-02", 10.0, "1:20:00", elevation_gain_m=900, sport="trail_running"),  # too hilly
    run("2025-01-01", 10.0, "0:35:00"),  # too old
    {"sport": "cycling", "date": "2026-10-03", "distance_km": 60.0, "duration": "2:00:00", "elevation_gain_m": 300},
    {"sport": "lap_swimming", "date": "2026-10-05", "distance_km": 2.0, "duration": "0:38:00"},
]


# ------------------------------------------------------------------ math --
def test_riegel_and_formatting() -> None:
    assert round(predict.riegel(1200, 5, 10)) == 2502
    assert round(predict.riegel(2850, 10, 21.0975)) == round(2850 * 2.10975 ** 1.06)
    assert predict.fmt(1290) == "21:30" and predict.fmt(3725) == "1:02" and predict.fmt_full(6021) == "1:40:21"
    assert predict.dur(4420) == "1 h 14 min" and predict.dur(840) == "14 min"
    assert predict.garmin_points([{"time5K": 1500}, {"time5K": 1290}]) == [(5.0, 1290.0)]
    assert predict.garmin_points({"time5K": 5}) == []


def test_anchor_selection_prefers_hard_efforts() -> None:
    b = predict.make_basis(acts=ACTS, athlete={"threshold_hr": 170}, today=TODAY)
    assert [e["km"] for e in b["efforts"]] == [10.0]  # the easy 8K is > 8% off once adjusted; hilly/old dropped
    assert b["efforts"][0]["race"] and b["efforts"][0]["hard"] == 1.0
    assert predict.hardness({"name": "Tempo 3x10"}, None) > predict.hardness({"name": "Morning Run"}, None)
    assert predict.hardness({"avg_hr": 166}, 170) == 1.0 and predict.hardness({"avg_hr": 130}, 170) == 0.3
    r = predict.predict(b, distance_km=21.0975, type_="running")
    assert r["basis"] == ["Based on your 10K race in 47:30 on Sep 21"]
    assert r["estimate"]["mid_s"] == round(predict.riegel(2850, 10, 21.0975))
    assert r["confidence"] == "high" and r["kind"] == "run"
    lo, mid, hi = (r["estimate"][k] for k in ("low_s", "mid_s", "high_s"))
    assert abs(lo - mid * 0.97) <= 1 and abs(hi - mid * 1.04) <= 1 and r["text"] == predict.text_range(r)
    # Only easy runs: counted a bit faster, flagged, lower confidence.
    easy = predict.make_basis(acts=[ACTS[1]], athlete={"threshold_hr": 170}, today=TODAY)
    e = predict.predict(easy, distance_km=10, type_="road")
    assert e["confidence"] == "low" and any("Easy runs" in a for a in e["assumptions"])
    assert e["estimate"]["mid_s"] < predict.riegel(2760, 8, 10)
    # Two good anchors blend by recency + distance.
    two = predict.make_basis(acts=[ACTS[0], run("2026-08-01", 21.1, "1:46:00", name="Half marathon")], today=TODAY)
    blend = predict.predict(two, distance_km=21.0975, type_="road")["estimate"]["mid_s"]
    assert min(predict.riegel(2850, 10, 21.0975), 6360 * 0.982) - 5 < blend < max(predict.riegel(2850, 10, 21.0975), 6360)
    assert len(predict.predict(two, distance_km=21.0975, type_="road")["basis"]) == 2


def test_fallbacks_and_missing_data() -> None:
    g = predict.predict(predict.make_basis(garmin=GARMIN), distance_km=21.0975, type_="road")
    assert g["estimate"]["mid_s"] == 6020 and g["confidence"] == "medium"
    assert g["basis"] == ["Based on Garmin's race predictor (half marathon 1:40:20)"]
    t = predict.predict(predict.make_basis(athlete={"run_threshold_pace": 270, "units": "metric"}), distance_km=10, type_="running")
    assert t["confidence"] == "low" and t["basis"] == ["Based on your threshold pace (4:30/km)"]
    imp = predict.make_basis(athlete={"run_threshold_pace": 270, "units": "imperial"})
    assert "/mi" in predict.predict(imp, distance_km=10, type_="running")["basis"][0]
    none = predict.make_basis()
    assert not predict.has_data(none) and predict.predict(none, distance_km=10, type_="road") is None
    assert predict.predict(predict.make_basis(garmin=GARMIN), distance_km=10, type_="skydiving") is None
    assert predict.predict(predict.make_basis(garmin=GARMIN), distance_km=0, type_="road") is None


# ----------------------------------------------------------------- trail --
def test_trail_climbing_altitude_and_heat() -> None:
    b = predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 10, "units": "metric"})
    road = predict.predict(b, distance_km=21.1, type_="road")["estimate"]["mid_s"]
    trail = predict.predict(b, distance_km=21.1, type_="trail")
    assert trail["estimate"]["mid_s"] == round(road * 1.07) and trail["kind"] == "trail"
    tech = predict.predict(b, distance_km=21.1, type_="trail", terrain="technical")["estimate"]["mid_s"]
    assert tech > trail["estimate"]["mid_s"]
    # Climbing: trail ~1.5 x flat pace per 100 m (4-10 min), road gentler.
    hilly = predict.predict(b, distance_km=21.1, type_="trail", climb_m=1000)
    per100 = min(600, max(240, 1.5 * predict.riegel(6020, 21.0975, 21.1) / 21.1))
    assert abs(hilly["estimate"]["mid_s"] - (trail["estimate"]["mid_s"] + 10 * per100)) < 3
    assert any(a.startswith("Climbing: +1,000 m adds about") for a in hilly["assumptions"])
    assert any("hike" in a for a in hilly["assumptions"]) and hilly["confidence"] == "medium"
    road_hill = predict.predict(b, distance_km=21.1, type_="road", climb_m=1000)["estimate"]["mid_s"]
    assert road < road_hill < hilly["estimate"]["mid_s"]
    # Altitude: +3% at 2,000 m to +8% at 3,500 m; none below 2,000 m; mostly offset when living high.
    assert predict.altitude_factor(1900, b) == (1.0, None)
    assert abs(predict.altitude_factor(2000, b)[0] - 1.03) < 1e-9 and abs(predict.altitude_factor(4000, b)[0] - 1.08) < 1e-9
    high = predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 1609})
    assert abs(predict.altitude_factor(3500, high)[0] - (1 + 0.08 * 0.35)) < 1e-9
    acc = predict.make_basis(garmin=GARMIN, athlete={"altitude_acclimatized": True})
    assert predict.altitude_factor(3000, acc)[0] < predict.altitude_factor(3000, b)[0]
    assert predict.altitude_factor(2800, predict.make_basis(athlete={"home_elevation_m": 2700}))[0] == 1.0
    up = predict.predict(b, distance_km=10, type_="road", elevation_m=2800)
    assert up["estimate"]["mid_s"] > predict.predict(b, distance_km=10, type_="road")["estimate"]["mid_s"] * 1.05
    hot = predict.predict(b, distance_km=10, type_="road", hot=True)
    assert any(a.startswith("Heat") for a in hot["assumptions"])


def test_ultra_fatigue_and_100_mile_cutoff() -> None:
    b = predict.make_basis(garmin=GARMIN, athlete={"home_elevation_m": 1609})
    lv = {"name": "Leadville Trail 100 Run", "type": "trail", "distance": "ultra", "location": "Leadville, CO",
          "date": "2027-08-21", "info": {"distances": "100 miles", "elevation_gain": "15,600 ft"}}
    r = predict.predict_event(b, lv, today=TODAY)
    e = r["estimate"]
    assert r["confidence"] == "low" and r["label"] == "rough guide" and r["text"].endswith(" h")
    assert e["high_s"] / e["low_s"] > 1.45 and 20 * 3600 < e["mid_s"] < 30 * 3600
    assert any("exponent 1.15" in a for a in r["assumptions"]) and any("hike about" in a for a in r["assumptions"])
    assert r["cutoff"]["s"] == 30 * 3600 and r["cutoff"]["margin_s"] == 30 * 3600 - e["mid_s"]
    assert r["cutoff"]["status"] in ("safe", "tight")
    # Cutoff from the looked-up info wins; a slow runner lands over it.
    slow = predict.make_basis(athlete={"run_threshold_pace": 420})
    over = predict.predict_event(slow, {**lv, "info": {**lv["info"], "cutoffs": "Overall cutoff 25 hours"}}, today=TODAY)
    assert over["cutoff"]["s"] == 25 * 3600 and over["cutoff"]["margin_s"] < 0 and over["cutoff"]["status"] == "over"
    assert predict.cutoff_hours({"name": "X", "info": {"cutoffs": "Finish by 34:00 (Sunday 10 am)"}}) == 34
    assert predict.cutoff_hours({"name": "City Half"}) is None
    # 50K: steeper than Riegel's 1.06, but a narrower range than a 100.
    fifty = predict.predict(b, distance_km=50, type_="ultra")
    assert fifty["estimate"]["mid_s"] > predict.riegel(12780, 42.195, 50) * 1.07
    assert fifty["estimate"]["high_s"] / fifty["estimate"]["low_s"] < e["high_s"] / e["low_s"]
    # An ultra with no distance looked up yet: assumed 80 km, said so, low confidence.
    guess = predict.predict_event(b, {"name": "Mystery Ultra", "type": "trail", "distance": "ultra"}, today=TODAY)
    assert guess["assumptions"][0].startswith("No distance on this race yet")


# ------------------------------------------------------------- tri/bike --
def test_triathlon_splits_from_ftp_and_css() -> None:
    full = predict.make_basis(athlete={"ftp_w": 250, "swim_css": 100, "run_threshold_pace": 270, "weight_kg": 72})
    r = predict.predict(full, distance_km=51.5, type_="triathlon")
    sp = {s["leg"]: s["mid_s"] for s in r["splits"]}
    assert [s["leg"] for s in r["splits"]] == ["swim", "t1", "bike", "t2", "run"]
    assert r["estimate"]["mid_s"] == sum(sp.values()) and r["confidence"] == "medium" and r["format"] == "olympic"
    assert sp["swim"] == (100 + 5) * 15 and sp["t1"] == 150 and sp["t2"] == 105
    assert sp["run"] == round(predict.riegel(3600, 3600 / 270, 10) * 1.07)
    assert 3600 < sp["bike"] < 4800  # ~33-38 km/h at 214 W
    assert r["basis"][:2] == ["Based on your CSS (1:40/100 m)", "Bike: your FTP (250 W)"]
    weak = predict.make_basis(athlete={"ftp_w": 180, "swim_css": 100, "run_threshold_pace": 270, "weight_kg": 72})
    assert {s["leg"]: s["mid_s"] for s in predict.predict(weak, distance_km=51.5, type_="triathlon")["splits"]}["bike"] > sp["bike"]
    # 70.3 vs Olympic: lower IF, bigger off-the-bike penalty.
    half = predict.predict(full, distance_km=113, type_="triathlon")
    assert any("+10%" in a for a in half["assumptions"]) and any("78% of FTP" in a for a in half["assumptions"])
    # Air density: same power is faster up high (flat), slower with more drag.
    assert predict.bike_speed(250, 81, elevation_m=2000) > predict.bike_speed(250, 81) > predict.bike_speed(250, 81, cda=0.40)
    # Missing FTP/CSS: defaults, said plainly, low confidence; recent swims stand in for CSS.
    g = predict.predict(predict.make_basis(garmin=GARMIN, acts=ACTS, athlete={"units": "metric"}, today=TODAY), distance_km=113, type_="triathlon")
    assert g["confidence"] == "low" and g["label"] == "rough guide"
    assert g["basis"][0].startswith("Based on your recent swims") and g["basis"][1].startswith("Bike: your 60 km ride")
    assert predict.predict(full, distance_km=80, type_="triathlon") is None  # not a standard format
    assert predict.predict(predict.make_basis(), distance_km=51.5, type_="triathlon") is None
    ev = predict.predict_event(full, {"name": "Boulder 70.3", "type": "triathlon", "distance": "70.3"}, today=TODAY)
    assert ev["format"] == "70.3" and len(ev["splits"]) == 5


def test_cycling_from_ftp_or_ride_speed() -> None:
    full = predict.make_basis(athlete={"ftp_w": 250, "weight_kg": 72})
    road = predict.predict(full, distance_km=160, type_="cycling", climb_m=1500)
    assert road["kind"] == "bike" and 5 * 3600 < road["estimate"]["mid_s"] < 8 * 3600
    gravel = predict.predict(full, distance_km=160, type_="gravel", climb_m=1500)
    assert gravel["estimate"]["mid_s"] > road["estimate"]["mid_s"] and any("Gravel" in a for a in gravel["assumptions"])
    rides = predict.make_basis(acts=ACTS, athlete={"units": "metric"}, today=TODAY)
    r = predict.predict(rides, distance_km=100, type_="cycling")
    assert r["confidence"] == "low" and r["basis"][0].startswith("Based on your 60 km ride at 30.0 km/h on Oct 3")
    assert predict.predict(predict.make_basis(athlete={"swim_css": 100}), distance_km=3.8, type_="swim")[
        "estimate"]["mid_s"] == (100 + 8) * 38


# ------------------------------------------------------------ projection --
def test_projection_from_plan_forecast() -> None:
    b = predict.make_basis(garmin=GARMIN)
    race_day = (TODAY + timedelta(weeks=12)).isoformat()
    load = {"has_plan": True, "now": {"ctl": 40.0},
            "series": [{"date": race_day, "ctl": 55.0, "planned": True}]}
    r = predict.predict(b, distance_km=42.195, type_="road")
    predict.add_projection(r, load, race_day, TODAY)
    assert r["projection"]["mid_s"] == round(12780 * (1 - 0.05)) and r["projection"]["gain_pct"] == 5.0
    assert "If you follow your plan" in r["projection"]["note"] and "projection" in r["projection"]["note"]
    capped = predict.predict(b, distance_km=42.195, type_="road")
    predict.add_projection(capped, {**load, "series": [{"date": race_day, "ctl": 90.0, "planned": True}]}, race_day, TODAY)
    assert capped["projection"]["gain_pct"] == 8.0
    soon = (TODAY + timedelta(weeks=3)).isoformat()
    s = predict.predict(b, distance_km=42.195, type_="road")
    predict.add_projection(s, {**load, "series": [{"date": soon, "ctl": 55.0, "planned": True}]}, soon, TODAY)
    assert "projection" not in s  # 4 weeks or less: no projection
    flat = predict.predict(b, distance_km=42.195, type_="road")
    predict.add_projection(flat, {**load, "series": [{"date": race_day, "ctl": 40.5, "planned": True}]}, race_day, TODAY)
    assert "projection" not in flat


def test_compact_shape_for_explore() -> None:
    from tests.test_explore2 import race
    b = predict.make_basis(garmin=GARMIN)
    est = predict.estimate(b, distance_km=21.0975, type_="road")
    assert est["likely"] == 6020 and est["low"] < 6020 < est["high"] and predict.text(est) == "1:35–1:46"
    r = race(1, "Golden Half", TODAY + timedelta(days=60), dist="13.1 Miles")
    got = predict.for_race(b, r, {"half"})
    assert got["text"] == predict.text(got) and got["event"] == "13.1 Miles"
    assert predict.for_race(b, {"events": []}) is None
    full = predict.make_basis(athlete={"ftp_w": 250, "swim_css": 100, "run_threshold_pace": 270, "weight_kg": 72})
    tri = predict.estimate(full, distance_km=51.5, type_="triathlon")
    assert tri["kind"] == "tri" and tri["likely"] == sum(tri["splits"].values())


# ------------------------------------------------------------------- API --
def _fixed_clock(agent) -> None:
    # Noon of the real today: the fake Garmin data is generated relative to the real date, so a
    # fixed calendar day here stopped matching it a few weeks later (no "recent runs" any more).
    noon = datetime.combine(date.today(), datetime.min.time()).replace(hour=12).timestamp()
    agent._clock = lambda: noon  # type: ignore[method-assign]


def test_event_and_generic_api_and_coach_access(env, tmp_path) -> None:
    agent, _ = env.agent([])
    _fixed_clock(agent)
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", _athlete(threshold_hr=165, units="metric"))
    race_day = (today + timedelta(weeks=16)).isoformat()
    agent.coach.create_goal("friend", {"title": "Spring Half", "distance": "half marathon", "date": race_day})
    agent.plans.build("friend")
    ev = agent.events.create("friend", {"name": "Spring Half", "date": race_day, "type": "running",
                                        "distance": "half marathon", "priority": "A"})
    vague = agent.events.create("friend", {"name": "Something", "date": race_day, "type": "other",
                                           "distance": "other", "priority": "C"})
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            r = await a.get(f"/app/api/events/{ev['id']}/predict")
            assert r.status_code == 200, r.text
            body = r.json()
            # Anchored on friend's recent (fake) Garmin runs, in plain words.
            assert re.fullmatch(r"Based on your .+ in \d+:\d\d(:\d\d)? on [A-Z][a-z]{2} \d{1,2}", body["basis"][0]), body
            assert set(body["estimate"]) >= {"low_s", "mid_s", "high_s", "likely", "text"}
            assert body["confidence"] in ("high", "medium") and body["assumptions"]
            assert body["projection"]["mid_s"] < body["estimate"]["mid_s"]
            assert "If you follow your plan" in body["projection"]["note"]
            assert (await a.get(f"/app/api/events/{vague['id']}/predict")).status_code == 400
            assert (await a.get("/app/api/events/nope/predict")).status_code == 400
            # Generic endpoint (Explore race detail): validated params.
            r = await a.get("/app/api/predict", params={"type": "trail", "distance_km": "42.2", "climb_m": "2400",
                                                        "elevation_m": "2900"})
            assert r.status_code == 200 and r.json()["kind"] == "trail"
            assert any(x.startswith("Climbing: +2,400 m") for x in r.json()["assumptions"])
            assert any(x.startswith("Altitude (2,900 m)") for x in r.json()["assumptions"])
            r = await a.get("/app/api/predict", params={"type": "running", "distance_km": "21.0975", "date": race_day})
            assert r.status_code == 200 and "projection" in r.json()
            for bad in ({"distance_km": "abc"}, {"distance_km": "nan"}, {"distance_km": "5000"}, {},
                        {"distance_km": "10", "climb_m": "-5"}, {"distance_km": "10", "date": "soon"},
                        {"distance_km": "10", "type": "<script>"}):
                assert (await a.get("/app/api/predict", params=bad)).status_code == 400, bad
            r = await a.get("/app/api/predict", params={"distance_km": "10", "type": "duathlon"})
            assert r.status_code == 200 and r.json()["estimate"] is None and r.json()["reason"]
            r = await a.get("/app/api/predict", params={"event_id": ev["id"]})
            assert r.json()["estimate"]["mid_s"] == body["estimate"]["mid_s"]
            # No Garmin, no profile numbers: a friendly reason, not a made-up time.
            r = await o.get("/app/api/predict", params={"distance_km": "10", "type": "road"})
            assert r.status_code == 200 and r.json()["estimate"] is None and "Connect Garmin" in r.json()["reason"]
            # Coach: athlete routes 403; coach route only once linked.
            assert (await c.get(f"/app/api/events/{ev['id']}/predict")).status_code == 403
            assert (await c.get("/app/api/predict", params={"distance_km": "10"})).status_code == 403
            url = f"/app/api/coach/athletes/friend/events/{ev['id']}/predict"
            assert (await c.get(url)).status_code == 400
            await a.post("/app/api/coaches", headers=H, json={"email": COACH})
            r = await c.get(url)
            assert r.status_code == 200 and r.json()["estimate"]["mid_s"] == body["estimate"]["mid_s"]
            assert (await o.get(url)).status_code == 400
    asyncio.run(go_())
