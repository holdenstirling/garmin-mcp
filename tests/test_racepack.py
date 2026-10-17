"""Race-week pack: pacing by leg, fueling, gear, altitude notes."""

from __future__ import annotations

from datetime import date

from garmin_mcp.racepack import build, fueling, pacing

TODAY = date(2027, 8, 10)


def test_tri_pacing_uses_numbers() -> None:
    ev = {"name": "IRONMAN 70.3 Boulder", "type": "triathlon", "distance": "70.3", "date": "2027-06-12"}
    legs = {p["leg"]: p for p in pacing(ev, {"ftp_w": 250, "run_threshold_pace": 270, "swim_css": 100, "units": "metric"})}
    assert legs["Bike"]["target"] == "187–200 W"
    assert legs["Swim"]["target"].startswith("1:48")
    assert legs["Run"]["target"].startswith("4:52")


def test_leadville_altitude_and_hope_pass() -> None:
    ev = {"name": "Leadville Trail 100 Run", "type": "trail", "distance": "ultra", "date": "2027-08-21",
          "location": "Leadville, Colorado", "info": {"terrain": "Hope Pass at about 12,500 ft"}}
    legs = [p["leg"] for p in pacing(ev, {"threshold_hr": 170, "units": "imperial"})]
    assert legs == ["Overall", "Altitude", "Hope Pass"]
    pack = build(ev, {"weight_kg": 72}, None, TODAY)
    assert pack["days_out"] == 11 and "Headlamp + spare batteries" in pack["gear"]
    f = fueling(ev, {"weight_kg": 72})
    assert f["carbs_g_per_h"] == 80 and any("576-720" in s for s in f["steps"])


def test_short_race_fueling_is_minimal() -> None:
    f = fueling({"distance": "5k"}, {})
    assert f["carbs_g_per_h"] == 0 and not any("carb-load" in s for s in f["steps"])
