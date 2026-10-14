"""Google Calendar summaries and travel mode."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_mcp.gcalendar import compact_event, summarize
from garmin_mcp.planbuilder import PlanError, iter_sessions
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _setup

D = date(2026, 10, 19)


def test_calendar_summary_busy_and_travel() -> None:
    raw = [
        {"summary": "Standup", "start": {"dateTime": "2026-10-19T09:00:00-06:00"}, "end": {"dateTime": "2026-10-19T10:30:00-06:00"}},
        {"summary": "Lunch (free)", "transparency": "transparent",
         "start": {"dateTime": "2026-10-19T12:00:00-06:00"}, "end": {"dateTime": "2026-10-19T13:00:00-06:00"}},
        {"summary": "Flight to NYC", "start": {"dateTime": "2026-10-22T07:00:00-06:00"}, "end": {"dateTime": "2026-10-22T12:00:00-04:00"}},
        {"summary": "NYC", "start": {"date": "2026-10-22"}, "end": {"date": "2026-10-26"}},
        {"summary": "Birthday", "start": {"date": "2026-10-28"}, "end": {"date": "2026-10-29"}},
        {"summary": "Cancelled", "status": "cancelled", "start": {"date": "2026-10-30"}, "end": {"date": "2026-10-31"}},
    ]
    evs = [e for e in (compact_event(x) for x in raw) if e]
    assert len(evs) == 5
    s = summarize(evs, D, D + timedelta(days=20))
    assert s["busy"]["2026-10-19"] == 90
    assert s["travel"] == [{"start": "2026-10-22", "end": "2026-10-25", "title": "Flight to NYC", "location": ""}]


def test_travel_mode_swaps_moves_and_undoes(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    mon = today + timedelta(days=7 - today.weekday())  # next Monday
    away_start, away_end = mon + timedelta(days=3), mon + timedelta(days=6)  # Thu-Sun
    before = {d: [dict(x) for x in ss] for w in plan["weeks"] for d, ss in w["days"].items()}
    p = agent.plans.add_travel("friend", {"start": away_start.isoformat(), "end": away_end.isoformat(),
                                          "label": "NYC", "treadmill": True})
    assert p["trips"][0]["label"] == "NYC"
    away = {(away_start + timedelta(days=i)).isoformat() for i in range(4)}
    for w in p["weeks"]:
        for d, ss in w["days"].items():
            if d in away:
                assert all(x["sport"] not in ("bike", "swim", "brick") for x in ss)
                assert all(x.get("kind") not in ("long", "brick") for x in ss)
                assert all((x.get("minutes") or 0) <= 75 for x in ss)
    # The long sessions moved to home days that week.
    week = next(w for w in p["weeks"] if w["start"] == mon.isoformat())
    assert any(x.get("travel") and x.get("kind") in ("long", "brick") for d, ss in week["days"].items()
               if d not in away for x in ss)
    with pytest.raises(PlanError, match="overlap"):
        agent.plans.add_travel("friend", {"start": away_end.isoformat(), "end": (away_end + timedelta(days=2)).isoformat()})
    p = agent.plans.remove_travel("friend", p["trips"][0]["id"])
    after = {d: ss for w in p["weeks"] for d, ss in w["days"].items()}
    for d in away:
        assert [x["title"] for x in after[d]] == [x["title"] for x in before[d]]
    assert p.get("trips") == []
