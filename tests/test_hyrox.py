"""HYROX: the goal (distance, division), a plan of runs, compromised running, station work,
simulations and a taper; station work without the strength opt-in; weekly rhythm placement
(lifting days take station work); the pacing estimate adds up; other plans are unchanged."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_mcp import hyrox
from garmin_mcp.coaching import CoachError
from garmin_mcp.nutrition import fuel
from garmin_mcp.planbuilder import DAYS, build_plan, garmin_workouts, race_key
from tests.test_agent import env  # noqa: F401  (fixture)

TODAY = date(2026, 10, 26)  # a Monday
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _goal(weeks=14, **kw):
    g = {"title": "HYROX Denver", "distance": "hyrox", "date": (TODAY + timedelta(weeks=weeks, days=5)).isoformat()}
    g.update(kw)
    return g


def _ath(**kw):
    a = {"weekly_hours": 6, "level": "intermediate", "available_days": list(ALL), "long_day": "sat"}
    a.update(kw)
    return a


def _sessions(plan):
    return [s for w in plan["weeks"] for ss in w["days"].values() for s in ss]


def _variants(plan, phase=None):
    return [s.get("variant") for w in plan["weeks"] if phase in (None, w["phase"])
            for ss in w["days"].values() for s in ss if s.get("kind") == "hyrox"]


def test_goal_accepts_hyrox_and_division(env) -> None:
    agent, _ = env.agent([])
    g = agent.coach.create_goal("friend", {"title": "HYROX Denver", "distance": "hyrox", "division": "doubles",
                                           "target_time": "1:15:00", "date": "2027-03-14"})
    assert g["distance"] == "hyrox" and g["division"] == "doubles"
    with pytest.raises(CoachError):
        agent.coach.update_goal("friend", g["id"], {"division": "elite"})
    assert race_key("HYROX Denver") == "hyrox" and race_key("hyrox") == "hyrox"


def test_plan_has_runs_compromised_stations_sims_and_taper() -> None:
    plan = build_plan(_ath(), _goal(target_time="1:15:00", division="open"), today=TODAY)
    assert plan["race_kind"] == "hyrox"
    ss = _sessions(plan)
    runs = [s for s in ss if s["sport"] == "run" and s.get("kind") != "race"]
    assert any(s["kind"] == "long" for s in runs) and any(s["title"] == "1 km repeats" for s in runs)
    v = _variants(plan)
    assert "stations" in v and "compromised" in v and "half_sim" in v and "full_sim" in v
    assert v.count("full_sim") == 1
    assert _variants(plan, "taper") and set(_variants(plan, "taper")) <= {"compromised"}
    st = next(s for s in ss if s.get("variant") == "stations")
    assert st["sport"] == "strength" and st["exercises"] and all(
        {"name", "sets", "reps", "rest_s", "cue"} <= set(e) for e in st["exercises"])
    assert hyrox.WEIGHTS_NOTE in st["detail"] and "kg" not in st["detail"] and "lb" not in st["detail"]
    race = next(s for s in ss if s.get("kind") == "race")
    assert "HYROX" in race["detail"]
    assert any(s.get("variant") == "primer" for s in ss)
    assert plan["hyrox"]["division"] == "open" and plan["hyrox"]["pacing"]["total"] == "1:15:00"
    # Station sessions go to Garmin as a timed workout with the exercises in the description.
    wo = garmin_workouts(st, {})
    assert len(wo) == 1 and wo[0]["sportType"]["sportTypeKey"] == "other"
    assert any(e["name"] in wo[0]["description"] for e in st["exercises"])


def test_station_work_without_strength_opt_in() -> None:
    # Station work is race training: it's there with strength explicitly off.
    plan = build_plan(_ath(strength_opt_in=False), _goal(), today=TODAY)
    assert _variants(plan)
    assert not [s for s in _sessions(plan) if s["sport"] == "strength" and s.get("kind") != "hyrox"
                and s.get("kind") != "mobility"]


def test_rhythm_lift_days_take_station_work() -> None:
    rh = {"mon": ["strength"], "thu": ["strength"], "tue": ["run"], "wed": ["run"], "sat": ["run"]}
    plan = build_plan(_ath(strength_opt_in=False, week_rhythm=rh), _goal(), today=TODAY)
    assert not plan["needs_strength_opt_in"]
    for w in plan["weeks"]:
        if w["phase"] == "race":
            continue
        for d, ss in w["days"].items():
            wd = DAYS[date.fromisoformat(d).weekday()]
            for s in ss:
                if s.get("kind") == "hyrox":
                    assert wd in ("mon", "thu", "fri", "sun"), (d, s["variant"])  # lift days, else open days
    hx_days = {DAYS[date.fromisoformat(d).weekday()] for w in plan["weeks"] for d, ss in w["days"].items()
               for s in ss if s.get("kind") == "hyrox"}
    assert {"mon", "thu"} <= hx_days


def test_rhythm_no_lift_days_uses_open_days() -> None:
    rh = {"tue": ["run"], "wed": ["run"], "sat": ["run"]}
    plan = build_plan(_ath(week_rhythm=rh), _goal(), today=TODAY)
    for w in plan["weeks"]:
        for d, ss in w["days"].items():
            for s in ss:
                if s.get("kind") == "hyrox" and w["phase"] != "race":
                    assert DAYS[date.fromisoformat(d).weekday()] in ("mon", "thu", "fri", "sun")


def test_pacing_adds_up_and_is_an_estimate() -> None:
    for t, div in (("1:15:00", "open"), ("58:30", "pro"), ("1:42:10", "doubles")):
        p = hyrox.pacing(t, div)
        assert p["estimate"] is True
        parts = sum(x["run_s"] + x["station_s"] for x in p["legs"]) + p["roxzone_s"]
        assert parts == hyrox.parse_time(t) and len(p["legs"]) == 8
        assert [x["station"].split(" ")[0] for x in p["legs"]][:2] == ["SkiErg", "Sled"]
    assert hyrox.pacing(None) is None and hyrox.pacing("5:00") is None


def test_race_fueling_note() -> None:
    f = fuel({"sport": "run", "kind": "race"}, "2027-03-14", race_date="2027-03-14", distance="hyrox")
    assert f["carbs_g_per_h"] == 30 and "gel" in f["note"]


def test_other_plans_unchanged_by_hyrox() -> None:
    a = build_plan(_ath(), {"title": "R", "distance": "half marathon",
                            "date": (TODAY + timedelta(weeks=14)).isoformat()}, today=TODAY)
    assert "hyrox" not in a and not any(s.get("kind") == "hyrox" for s in _sessions(a))


def test_rhythmfit_keeps_station_work_with_strength_off(env) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", {"weekly_hours": 6, "level": "intermediate", "available_days": list(ALL),
                                          "long_day": "sat", "strength_opt_in": False})
    agent.coach.create_goal("friend", {"title": "HYROX", "distance": "hyrox",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    n0 = sum(1 for w in agent.plans.get("friend")["weeks"] for ss in w["days"].values() for s in ss
             if s.get("kind") == "hyrox")
    agent.coach.update_athlete("friend", {"week_rhythm": {"mon": ["strength"], "wed": ["strength"]}})
    plan = agent.plans.apply_rhythm("friend")
    n1 = sum(1 for w in plan["weeks"] for ss in w["days"].values() for s in ss if s.get("kind") == "hyrox")
    assert n1 == n0 and not plan["needs_strength_opt_in"]
