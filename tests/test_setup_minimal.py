"""The four-step setup sends only the goal, experience and the week: no age, body, heart rate,
FTP or paces. Every race kind must still build a full plan from just that."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_mcp.planbuilder import build_plan

TODAY = date(2026, 11, 3)
WEEK = {"weekly_hours": 5, "available_days": ["tue", "thu", "sat", "sun"], "long_day": "sat"}


@pytest.mark.parametrize("distance", ["5k", "half marathon", "marathon", "olympic triathlon", "70.3",
                                      "century ride", "hyrox", "other"])
@pytest.mark.parametrize("level", [None, "new", "advanced"])
def test_builds_without_body_or_numbers(distance: str, level: str | None) -> None:
    athlete = dict(WEEK, level=level)
    goal = {"title": "Goal", "distance": distance, "date": (TODAY + timedelta(weeks=16)).isoformat(),
            "goal_type": "finish"}
    plan = build_plan(athlete, goal, today=TODAY)
    sessions = [s for w in plan["weeks"] for day in w["days"].values() for s in day if s["sport"] != "rest"]
    assert plan["weeks"] and sessions
    assert all(s.get("minutes") for s in sessions if s.get("kind") != "race")


def test_no_race_block_builds_without_body_or_numbers() -> None:
    goal = {"title": "12-week running block", "distance": "10k", "no_race": True, "goal_type": "finish",
            "date": (TODAY + timedelta(weeks=12) - timedelta(days=1)).isoformat()}
    plan = build_plan(dict(WEEK), goal, today=TODAY)
    assert plan["weeks"]
