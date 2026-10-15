"""Plan adjusts to real life: low recovery, a missed long session, a missed week."""

from __future__ import annotations

from datetime import date, timedelta

from garmin_mcp.adjust import QUALITY, propose
from garmin_mcp.planbuilder import build_plan, iter_sessions
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _setup
from tests.test_stats import act

ENGINE = {"run": "running", "bike": "cycling", "swim": "lap_swimming", "strength": "strength_training",
          "brick": "multi_sport", "other": "other"}


def _plan(today: date, weeks: int = 12):
    athlete = {"weekly_hours": 8, "level": "intermediate", "available_days": ["tue", "wed", "thu", "sat", "sun"],
               "long_day": "sat"}
    return build_plan(athlete, {"title": "HM", "date": (today + timedelta(weeks=weeks)).isoformat(),
                                "distance": "half marathon"}, today=today - timedelta(days=14))


def _did_everything(plan, today, skip=lambda s: False):
    acts = []
    for w, d, s in iter_sessions(plan):
        if d < today.isoformat() and s["sport"] != "rest" and not skip(s):
            acts.append(act(date.fromisoformat(d), sport=ENGINE.get(s["sport"], "other"),
                            aid=abs(hash((d, s["id"]))) % 10**9))
    return acts


def test_low_recovery_with_easy_days_ahead_is_a_heads_up() -> None:
    today = date(2026, 10, 15)
    plan = _plan(today)
    rec = {"days": [{"readiness": 64}, {"readiness": 58}, {"readiness": 66}], "baseline": {}}
    p = propose(plan, _did_everything(plan, today), today, recovery=rec)
    assert p["status"] in ("watch", "suggest") and p["reasons"]


def test_nothing_to_change_when_on_track() -> None:
    today = date(2026, 10, 15)  # Thursday
    plan = _plan(today)
    assert propose(plan, _did_everything(plan, today), today)["status"] == "ok"


def test_low_recovery_eases_the_next_days() -> None:
    base = date(2026, 10, 13)
    plan = _plan(base, weeks=8)
    q = min(date.fromisoformat(d) for _, d, s in iter_sessions(plan)
            if d >= (base + timedelta(days=7)).isoformat() and s.get("kind") in ("tempo", "threshold", "vo2", "racepace"))
    today = q - timedelta(days=1)
    rec = {"days": [{"date": "x", "readiness": 64, "hrv": 40}, {"date": "y", "readiness": 58, "hrv": 41},
                    {"date": "z", "readiness": 55, "hrv": 39}], "baseline": {"hrv": 55, "resting_hr": 48}}
    p = propose(plan, _did_everything(plan, today), today, recovery=rec)
    assert p["status"] == "suggest" and any("Readiness" in r for r in p["reasons"])
    horizon = (today + timedelta(days=2)).isoformat()
    assert all(c["date"] <= horizon for c in p["changes"])
    assert all(c["action"] in ("ease", "shorten", "rest") for c in p["changes"])
    # Dismissed proposals stay quiet.
    assert propose(plan, _did_everything(plan, today), today, recovery=rec, dismissed=[p["id"]])["status"] == "dismissed"


def test_missed_week_eases_back_in() -> None:
    today = date(2026, 10, 15)
    plan = _plan(today)
    p = propose(plan, [], today)  # did nothing at all
    assert p["status"] == "suggest" and any("ease back in" in r for r in p["reasons"])
    assert all(c["to"]["minutes"] < c["from"]["minutes"] for c in p["changes"] if c["action"] == "shorten")


def test_apply_via_service(env) -> None:
    agent, plan, today = _setup(env, distance="half marathon", weeks=12)
    rec = {"days": [{"readiness": 50}, {"readiness": 52}, {"readiness": 55}], "baseline": {}}
    # Propose on the first day with a session, so the 2-day horizon has something to change
    # whatever weekday the suite runs on.
    day = min(date.fromisoformat(d) for _, d, s in iter_sessions(plan) if date.fromisoformat(d) >= today
              and (s.get("kind") in QUALITY or (s.get("kind") in ("long", "brick") and (s.get("minutes") or 0) > 60)))
    p = propose(plan, [], day, recovery=rec, tsb=-45)
    assert p["status"] == "suggest"
    out = agent.plans.apply_adjustment("friend", p["changes"])
    by_id = {s["id"]: s for _, _, s in iter_sessions(out)}
    for c in p["changes"]:
        if c["action"] in ("ease", "shorten") and c["session_id"] in by_id:
            assert by_id[c["session_id"]]["minutes"] <= c["from"]["minutes"]
