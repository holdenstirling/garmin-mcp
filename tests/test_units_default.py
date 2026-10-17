"""Miles by default: an athlete who never picked units sees miles / yards / °F; "metric" keeps km."""

from __future__ import annotations

from datetime import date, datetime, timezone

from garmin_mcp.coaching import is_imperial
from garmin_mcp.plancal import calendar_view
from garmin_mcp.racepack import pacing
from garmin_mcp.workoutday import targets
from tests.test_workoutday import ATHLETE


def test_is_imperial_defaults_to_miles() -> None:
    assert is_imperial({}) and is_imperial(None) and is_imperial({"units": "imperial"})
    assert not is_imperial({"units": "metric"})


def test_formatting_defaults_to_miles_and_metric_stays_km() -> None:
    base = {k: v for k, v in ATHLETE.items() if k != "units"}
    assert targets("run", 4, base)[0]["label"].endswith("/mi")
    assert targets("swim", 4, base)[0]["label"].endswith("/100yd")
    assert targets("run", 4, base | {"units": "metric"})[0]["label"].endswith("/km")
    ev = {"name": "Half", "type": "running", "distance": "half marathon", "date": "2027-04-18"}
    assert pacing(ev, {"run_threshold_pace": 270})[0]["target"].endswith("/mi")
    plan = {"weeks": [], "race_date": "2027-06-06", "start": "2026-10-12"}
    v = calendar_view(plan, [], date(2026, 10, 16), athlete={}, thr=300.0, pace_source="default",
                      imperial=is_imperial({}))
    assert v["imperial"] is True


def test_rabbit_context_states_the_units(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    now = datetime(2026, 10, 16, 8, tzinfo=timezone.utc)
    assert "Units: imperial (miles" in agent.coach.context_block("friend", now, None)
    agent.coach.update_athlete("friend", {"units": "metric"})
    assert "Units: metric (km" in agent.coach.context_block("friend", now, None)


from tests.test_agent import env  # noqa: E402,F401  (fixture)
