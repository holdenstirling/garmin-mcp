"""Training load: CTL/ATL/TSB from activities and the plan forecast."""

from __future__ import annotations

from datetime import date, timedelta

from garmin_mcp.load import activity_load, advice, compute, session_load
from garmin_mcp.planbuilder import build_plan
from tests.test_stats import act

TODAY = date(2026, 10, 14)


def test_activity_and_session_load() -> None:
    a = act(TODAY, minutes=60) | {"avg_hr": 150}
    assert activity_load(a, 160) == round(1 * (150 / 160) ** 2 * 100, 1)
    assert activity_load(act(TODAY, minutes=60), None) == round(0.75 ** 2 * 100, 1)
    assert session_load({"sport": "run", "kind": "threshold", "minutes": 60}) == round(0.92 ** 2 * 100, 1)
    assert session_load({"sport": "rest"}) == 0
    assert session_load({"sport": "run", "kind": "race"}, "marathon") > 200


def test_fitness_builds_and_plan_forecasts_race_day() -> None:
    acts = [act(TODAY - timedelta(days=i), minutes=60, aid=i) for i in range(1, 120)]
    out = compute(acts, TODAY)
    now = out["now"]
    assert 40 < now["ctl"] < 60 and abs(now["tsb"]) < 15
    assert out["race_day"] is None and len(out["series"]) >= 90
    plan = build_plan({"weekly_hours": 7, "level": "intermediate"},
                      {"title": "M", "date": (TODAY + timedelta(weeks=10)).isoformat(), "distance": "marathon"}, today=TODAY)
    out = compute(acts, TODAY, plan=plan)
    assert out["race_day"]["date"] == plan["race_date"] and out["series"][-1]["planned"]
    assert out["race_day"]["tsb"] > now["tsb"] - 20  # the taper lifts form
    assert "race day" in out["advice"].lower()


def test_advice_text() -> None:
    assert "fatigue" in advice({"tsb": -35, "ctl": 50}, None)
    assert "zone" in advice({"tsb": 0, "ctl": 50}, {"tsb": 12, "ctl": 55, "date": "x"})
