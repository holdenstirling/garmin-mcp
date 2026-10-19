"""A plan without a race: a training block (goal ``no_race``) ends on a lighter week, never a race
week, creates no race-day event, and the review summary explains each phase."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_mcp.coaching import CoachError
from garmin_mcp.planbuilder import build_plan
from garmin_mcp.planflow import plan_summary
from tests.test_agent import env  # noqa: F401  (fixture)

TODAY = date(2026, 10, 19)  # a Monday
ATHLETE = {"level": "intermediate", "weekly_hours": 5, "available_days": ["tue", "thu", "sat", "sun"],
           "long_day": "sat"}


def _block(weeks: int, distance: str = "other") -> dict:
    end = TODAY + timedelta(weeks=weeks) - timedelta(days=1)
    return build_plan(ATHLETE, {"title": "Get fitter", "distance": distance, "date": end.isoformat(),
                                "no_race": True}, today=TODAY)


@pytest.mark.parametrize("weeks", [6, 8, 12, 16])
def test_block_has_no_race_week_and_ends_lighter(weeks: int) -> None:
    plan = _block(weeks)
    assert plan["no_race"] is True
    assert all(w["phase"] != "race" for w in plan["weeks"])
    kinds = {s.get("kind") for w in plan["weeks"] for ss in w["days"].values() for s in ss}
    assert "race" not in kinds and "openers" not in kinds
    last, prev_full = plan["weeks"][-1], max(w["hours"] for w in plan["weeks"][:-1] if not w["recovery"])
    assert last["recovery"] and last["hours"] < prev_full * 0.85
    assert "no race needed" in (plan["note"] or "")


def test_block_can_focus_on_a_distance() -> None:
    plan = _block(12, "half marathon")
    assert plan["distance"] == "half marathon" and plan["no_race"] is True
    sports = {s["sport"] for w in plan["weeks"] for ss in w["days"].values() for s in ss}
    assert "run" in sports and "race" not in {s.get("kind") for w in plan["weeks"] for ss in w["days"].values() for s in ss}


def test_race_plans_are_unchanged() -> None:
    end = TODAY + timedelta(weeks=12)
    plan = build_plan(ATHLETE, {"title": "Half", "distance": "half marathon", "date": end.isoformat()}, today=TODAY)
    assert plan["no_race"] is False and plan["weeks"][-1]["phase"] == "race"


def test_summary_explains_phases_and_has_a_calendar() -> None:
    plan = _block(12)
    s = plan_summary(plan, TODAY)
    assert s["no_race"] is True and len(s["calendar"]) == len(plan["weeks"])
    assert all({"start", "phase", "hours", "recovery", "days"} <= set(w) for w in s["calendar"])
    assert all("key_kinds" in p and "longest_minutes" in p for p in s["phases"])
    assert s["calendar"][0]["days"] and isinstance(s["calendar"][0]["days"][0]["sessions"], list)


def test_goal_validation_and_no_event(env) -> None:  # noqa: F811
    coach = env.agent([])[0].coach
    with pytest.raises(CoachError):
        coach._validate_goal({"no_race": "yes"}, partial=True)
    g = coach.create_goal("friend", {"title": "Get fitter", "distance": "other",
                                     "date": (TODAY + timedelta(weeks=8)).isoformat(), "no_race": True})
    assert g["no_race"] is True
    assert env.agent([])[0].events.upsert_from_goal("friend", None) is None
