"""Strength routines, injury prehab, mobility, and fueling guidance."""

from __future__ import annotations

from datetime import date

from garmin_mcp.nutrition import fuel
from garmin_mcp.planbuilder import build_plan, iter_sessions
from garmin_mcp.strength import care_plan, routine

TODAY = date(2026, 10, 14)


def test_routine_by_phase_and_care() -> None:
    r = routine("base", "run", "Achilles gets cranky above 40 km; old IT band issue")
    names = [e["name"] for e in r["exercises"]]
    assert "Goblet squat" in names and "Pogo hops" in names
    assert any("heel drops" in p["name"].lower() for p in r["prehab"])
    assert "Prehab (Achilles/calf, Knee/IT band)" in r["detail"]
    assert routine("taper", "tri")["exercises"][0]["name"] == "Glute bridge"
    assert care_plan("") == [] and care_plan("sore shoulder")[0]["area"] == "Shoulder"


def test_builder_adds_routines_and_mobility() -> None:
    a = {"weekly_hours": 8, "level": "intermediate", "injuries": "achilles", "available_days": ["tue", "wed", "thu", "sat", "sun"]}
    plan = build_plan(a, {"title": "M", "date": "2027-04-18", "distance": "marathon"}, today=TODAY)
    strength = [s for _, _, s in iter_sessions(plan) if s["sport"] == "strength"]
    assert any(s["kind"] == "mobility" for s in strength)
    assert all(s.get("exercises") for s in strength)


def test_fuel_ramp() -> None:
    long_run = {"sport": "run", "kind": "long", "minutes": 150}
    early = fuel(long_run, "2026-11-01", race_date="2027-08-21", distance="ultra")
    late = fuel(long_run, "2027-07-20", race_date="2027-08-21", distance="ultra")
    assert early["carbs_g_per_h"] == 45 and late["carbs_g_per_h"] == 80 and "Gut training" in late["note"]
    assert fuel({"sport": "run", "kind": "easy", "minutes": 45}, "2027-07-20", race_date=None, distance=None) is None
    assert fuel({"sport": "run", "kind": "race"}, "2027-08-21", race_date="2027-08-21", distance="5k")["carbs_g_per_h"] == 0
