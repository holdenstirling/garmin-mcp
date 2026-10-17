"""Per-step workout targets, "how it went", session start times and the per-session .ics."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from garmin_mcp.planbuilder import PlanError, make_session, rebuild_session
from garmin_mcp.planformats import export_ics
from garmin_mcp.plans import clean_time, public_plan
from garmin_mcp.workouttargets import how_it_went, hr_zones, session_targets
from tests.test_agent import env  # noqa: F401  (fixture)


def _walk(steps):
    for st in steps:
        if st["type"] == "repeat":
            yield from _walk(st["steps"])
        else:
            yield st


# ------------------------------------------------------------- HR zones --
def test_hr_zones_prefer_threshold_then_reserve_then_max() -> None:
    z, src = hr_zones({"threshold_hr": 170, "max_hr": 190, "resting_hr": 50})
    assert src == "threshold" and z[2] == (144, 151) and z[4] == (162, 168) and z[5][1] <= 190
    z, src = hr_zones({"max_hr": 190, "resting_hr": 50})
    assert src == "reserve" and z[2] == (134, 148)
    z, src = hr_zones({"max_hr": 200})
    assert src == "max" and z[1] == (100, 120)
    assert hr_zones({}) == (None, None)
    assert hr_zones({"max_hr": 400}) == (None, None)  # nonsense is ignored


# -------------------------------------------------------------- targets --
def test_run_targets_have_hr_pace_cadence_effort_and_summary() -> None:
    s = make_session("run", "threshold", 60)
    t = session_targets(s, {"threshold_hr": 170}, thr=300.0)
    assert t and t["hr_source"] == "threshold"
    steps = list(_walk(t["steps"]))
    work = [x for x in steps if x["type"] == "work"]
    assert work, steps
    w = work[0]
    assert w["zone"] == 4 and w["pace"] == [297, 315] and w["hr"] == [162, 168]
    assert w["cadence"] == [175, 185] and w["rpe"] == "7-8" and w["talk"]
    warm = next(x for x in steps if x["type"] == "warmup")
    assert warm["cadence"][0] < w["cadence"][0]  # easier steps, lower cadence
    summ = t["summary"]
    assert summ["minutes"] == s["minutes"] and summ["stress"] > 0
    assert summ["run_pace"] and 297 <= summ["run_pace"] <= 450 and summ["avg_hr"]
    assert sum(summ["zones"].values()) == pytest.approx(s["minutes"], abs=2)


def test_targets_without_hr_numbers_still_give_pace_and_effort() -> None:
    t = session_targets(make_session("run", "easy", 45), {}, thr=330.0)
    st = next(_walk(t["steps"]))
    assert t["hr_source"] is None and "hr" not in st and st["pace"] and st["rpe"]
    assert t["summary"]["avg_hr"] is None


def test_bike_power_with_ftp_swim_pace_from_css_and_brick_legs() -> None:
    bike = session_targets(make_session("bike", "tempo", 60), {"ftp_w": 250, "max_hr": 190}, thr=300.0)
    b = next(x for x in _walk(bike["steps"]) if x["type"] in ("work", "steady"))
    assert b["power"][0] < b["power"][1] and b["cadence"][0] >= 80 and "pace" not in b
    assert bike["ftp"] is True
    no_ftp = session_targets(make_session("bike", "easy", 60), {}, thr=300.0)
    assert "power" not in next(_walk(no_ftp["steps"])) and no_ftp["ftp"] is False
    swim = session_targets(make_session("swim", "css", 45), {"swim_css": 100}, thr=300.0)
    sw = [x for x in _walk(swim["steps"]) if x.get("swim")]
    assert sw and all("hr" not in x and x["minutes"] for x in sw)
    hard = max(sw, key=lambda x: x["zone"])
    assert hard["swim"][0] <= 103
    brick = session_targets(make_session("brick", "brick", 90), {"max_hr": 190}, thr=300.0)
    assert [lg["sport"] for lg in brick["legs"]] == ["bike", "run"] and brick["summary"]["minutes"] >= 85


def test_no_targets_for_rest_race_strength() -> None:
    for s in (make_session("rest", "rest", 0), make_session("strength", "strength", 30),
              make_session("run", "race", 60)):
        assert session_targets(s, {"max_hr": 190}, thr=300.0) is None


# ---------------------------------------------------------- how it went --
def _run(kind: str = "easy", minutes: int = 45):
    s = make_session("run", kind, minutes)
    return s, session_targets(s, {"threshold_hr": 170}, thr=300.0)


def test_on_target() -> None:
    s, t = _run()
    pace = t["summary"]["run_pace"]
    w = how_it_went(s, t, {"duration": "0:45:00", "distance_km": round(2700 / pace, 2),
                           "avg_hr": t["summary"]["avg_hr"], "avg_pace_per_km": f"{pace // 60}:{pace % 60:02d}",
                           "avg_cadence": 172})
    assert w["verdict"] == "hit" and w["headline"] == "Right on target" and w["actual"]["pace"] == pace


def test_short_hard_fast_and_slow() -> None:
    s, t = _run()
    assert how_it_went(s, t, {"duration": "0:20:00", "distance_km": 4})["verdict"] == "short"
    hard = how_it_went(s, t, {"duration": "0:45:00", "avg_hr": t["summary"]["avg_hr"] * 1.15})
    assert hard["verdict"] == "hard" and "harder" in " ".join(hard["lines"])
    fast = how_it_went(s, t, {"duration": "0:45:00", "avg_pace_per_km": "4:30"})
    assert fast["verdict"] == "fast" and "Easy days" in " ".join(fast["lines"])
    q, tq = _run("threshold", 60)
    slow = how_it_went(q, tq, {"duration": "1:00:00", "avg_pace_per_km": "8:00"})
    assert slow["verdict"] == "slow"
    # slower on an easy day is fine, not flagged
    assert how_it_went(s, t, {"duration": "0:45:00", "avg_pace_per_km": "8:30"})["verdict"] == "hit"
    low = how_it_went(s, t, {"duration": "0:45:00", "avg_cadence": 150})
    assert any("quicker, shorter steps" in x for x in low["lines"])


def test_how_it_went_without_targets_or_activity() -> None:
    s = make_session("strength", "strength", 30)
    assert how_it_went(s, None, {}) is None
    w = how_it_went(s, None, {"duration": "0:30:00"})
    assert w["verdict"] == "hit"  # 30 of 30 planned minutes


# ------------------------------------------------------------ start time --
def test_clean_time() -> None:
    assert clean_time("6:30") == "06:30" and clean_time("18:05") == "18:05" and clean_time("") == ""
    assert clean_time(None) == ""
    for bad in ("24:00", "6.30", "noon", "12:60", 630):
        with pytest.raises(PlanError):
            clean_time(bad)


def test_time_survives_rebuild_and_orders_the_day() -> None:
    a, b = make_session("run", "easy", 30), make_session("swim", "technique", 30)
    a["time"], b["time"] = "18:00", "06:15"
    assert rebuild_session(dict(a, minutes=40))["time"] == "18:00"
    plain = make_session("bike", "easy", 30)
    plan = {"weeks": [{"index": 1, "start": "2026-10-12", "phase": "base", "recovery": False, "hours": 5,
                       "focus": "", "days": {"2026-10-13": [a, plain, b]}}], "trips": []}
    out = public_plan(plan, date(2026, 10, 12))
    ss = out["weeks"][0]["days"][0]["sessions"]
    assert [x["id"] for x in ss] == [b["id"], a["id"], plain["id"]] and ss[0]["time"] == "06:15"


def test_service_validates_and_stores_time(env) -> None:
    from datetime import timedelta
    agent, _ = env.agent([])
    today = agent.plans.today("friend")
    agent.coach.update_athlete("friend", {"weekly_hours": 6})
    agent.coach.create_goal("friend", {"title": "Race", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    day = (today + timedelta(days=1)).isoformat()
    plan = agent.plans.add_session("friend", {"date": day, "sport": "run", "minutes": 40, "time": "6:45"})
    s = next(s for w in plan["weeks"] for d, ss in w["days"].items() if d == day for s in ss if s.get("time"))
    assert s["time"] == "06:45"
    plan = agent.plans.update_session("friend", s["id"], {"minutes": 50})
    s2 = next(x for w in plan["weeks"] for ss in w["days"].values() for x in ss if x["id"] == s["id"])
    assert s2["time"] == "06:45" and s2["minutes"] == 50
    plan = agent.plans.update_session("friend", s["id"], {"time": ""})
    s3 = next(x for w in plan["weeks"] for ss in w["days"].values() for x in ss if x["id"] == s["id"])
    assert "time" not in s3
    with pytest.raises(PlanError):
        agent.plans.update_session("friend", s["id"], {"time": "25:00"})


# ------------------------------------------------------------------ ics --
def test_single_session_ics_is_timed_and_escaped() -> None:
    a = make_session("run", "easy", 45, title="Easy run, by the river; with Sam")
    a["time"] = "06:30"
    b = make_session("bike", "easy", 60)
    plan = {"weeks": [{"start": "2026-10-12", "days": {"2026-10-13": [a], "2026-10-14": [b]}}]}
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    one = export_ics(plan, name="Rabbit", only=a["id"], now=now)
    assert one.count("BEGIN:VEVENT") == 1 and f"UID:{a['id']}@rabbit" in one
    assert "DTSTART:20261013T063000" in one and "DTEND:20261013T071500" in one
    assert "Easy run\\, by the river\\; with Sam" in one
    later = export_ics(plan, name="Rabbit", only=a["id"], now=datetime(2026, 10, 14, 12, tzinfo=timezone.utc))
    seq = lambda t: int(next(x for x in t.split("\r\n") if x.startswith("SEQUENCE:"))[9:])  # noqa: E731
    assert seq(later) > seq(one)  # re-import updates the same event
    full = export_ics(plan, name="Rabbit", now=now)
    assert full.count("BEGIN:VEVENT") == 2 and "DTSTART;VALUE=DATE:20261014" in full
