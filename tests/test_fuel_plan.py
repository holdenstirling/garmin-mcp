"""Per-workout fueling (nutrition.fuel_plan): before / during / after, preferences, payloads, AI context."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from garmin_mcp.coaching import CoachError
from garmin_mcp.nutrition import fuel_plan
from garmin_mcp.planbuilder import build_plan, make_session, week_for
from garmin_mcp.plans import public_plan
from garmin_mcp.workoutday import _later_today, session_view
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_stats import TODAY

D = TODAY.isoformat()


def sess(sport: str, kind: str, minutes: int, time: str | None = None) -> dict[str, Any]:
    s = make_session(sport, kind, minutes)
    s["id"] = f"{sport}-{kind}"
    if time:
        s["time"] = time
    return s


def test_short_easy_run_water_only_optional_snack_normal_meal_after() -> None:
    p = fuel_plan(sess("run", "easy", 40), D, {})
    assert p["before"]["optional"] is True and "nothing" in p["before"]["headline"]
    assert p["during"]["headline"] == "Water is enough" and p["during"]["carbs_g_per_h"] == 0
    assert p["after"]["headline"] == "your next normal meal is fine" and p["after"]["optional"] is True
    assert p["hint"] is None and p["night_before"] is None and p["caffeine"] is None


def test_long_ride_real_food_during_recovery_after_and_meal_before_for_late_start() -> None:
    p = fuel_plan(sess("bike", "long", 120, "10:00"), D, {"units": "metric"})
    assert p["before"]["when"] == "2-3 h before" and "carb-rich meal" in p["before"]["headline"]
    assert p["during"]["carbs_g_per_h"] >= 30 and "drink mix" in p["during"]["plan"]
    assert any("banana" in x for x in p["during"]["items"])  # bike: real food is easy to eat
    assert p["during"]["fluids"].endswith("ml an hour") and "sodium" in p["during"]["sodium"]
    assert p["after"]["when"] == "Within 30-60 min" and "protein" in p["after"]["headline"]
    assert "chocolate milk" in p["after"]["items"]
    assert p["night_before"] is None  # a 10am start: breakfast does the job
    assert p["hint"].startswith("Fuel: ") and "recovery snack after" in p["hint"]


def test_early_intervals_get_a_small_snack_and_recovery() -> None:
    p = fuel_plan(sess("run", "vo2", 55, "06:00"), D, {"units": "imperial"})
    assert p["before"]["when"] == "30-60 min before" and p["before"]["optional"] is False
    assert p["before"]["hydration"].endswith("oz in the 2 hours before.")
    assert "protein" in p["after"]["headline"]
    assert p["hint"] == "Fuel: small snack before · recovery snack after"


def test_long_early_run_gets_gels_and_dinner_the_night_before() -> None:
    p = fuel_plan(sess("run", "long", 110, "07:00"), D, {})
    assert p["during"]["plan"].startswith("1 gel every ") and p["during"]["items"][0].startswith("a gel")
    assert p["night_before"].startswith("Carb-rich dinner")
    assert p["hint"].startswith("Fuel: 1 gel every ")
    assert "oz an hour" in p["during"]["fluids"]  # miles/oz by default


def test_swim_nothing_during_and_strength_protein_after() -> None:
    p = fuel_plan(sess("swim", "css", 60), D, {})
    assert p["during"]["headline"] == "Nothing during" and "bottle" in p["during"]["plan"]
    assert "fluids" not in p["during"] and p["hint"] is None
    st = fuel_plan(sess("strength", "strength", 40), D, {})
    assert st["after"]["headline"].startswith("20-30 g protein") and st["during"]["headline"] == "Water is enough"
    assert fuel_plan({"sport": "rest", "kind": "rest"}, D, {}) is None


def test_race_and_gut_training_note() -> None:
    plan = {"race_date": (TODAY + timedelta(weeks=6)).isoformat(), "distance": "70.3"}
    p = fuel_plan(sess("bike", "long", 180, "07:00"), D, {}, plan)
    assert p["during"]["note"].startswith("Gut training") and p["during"]["carbs_g_per_h"] > 45
    race = {"sport": "run", "kind": "race", "minutes": 200, "title": "Marathon"}
    r = fuel_plan(race, D, {}, {"distance": "marathon"})
    assert r["during"]["carbs_g_per_h"] == 70 and r["night_before"] and r["before"]["optional"] is False


def test_double_day_refuels_right_away() -> None:
    p = fuel_plan(sess("run", "tempo", 50, "06:30"), D, {}, later_today=True)
    assert p["after"]["when"] == "Right away" and "later today" in p["after"]["tip"]


def test_preferences_filter_examples_style_and_caffeine() -> None:
    vegan = fuel_plan(sess("bike", "long", 120, "11:00"), D, {"diet": ["vegan"]})
    words = set(" ".join(vegan["after"]["items"] + vegan["before"]["items"]).lower().split())
    assert not words & {"milk", "yogurt", "eggs", "honey", "chicken"}
    assert vegan["after"]["items"]
    gf = fuel_plan(sess("run", "long", 120, "11:00"), D, {"diet": ["gluten_free"]})
    assert not any(w in " ".join(gf["before"]["items"]).lower() for w in ("bagel", "toast", "oats"))
    gels = fuel_plan(sess("bike", "long", 120), D, {"fuel_style": "gels"})
    assert gels["during"]["plan"].startswith("1 gel every ")
    food = fuel_plan(sess("run", "long", 120), D, {"fuel_style": "real_food"})
    assert "dates" in food["during"]["plan"]
    assert fuel_plan(sess("run", "long", 120), D, {"caffeine": True})["caffeine"].startswith("Caffeine:")
    assert fuel_plan(sess("run", "long", 120), D, {"caffeine": False})["caffeine"] is None
    assert fuel_plan(sess("run", "long", 120), D, {})["caffeine"].startswith("Optional:")


def test_weight_gives_per_kg_numbers_and_heat_raises_fluids() -> None:
    p = fuel_plan(sess("run", "threshold", 70, "17:00"), D, {"weight_kg": 70, "units": "metric"})
    assert "70-140 g carbs" in p["before"]["headline"]
    assert p["after"]["headline"] == "about 70 g carbs + 21 g protein"
    hot = fuel_plan(sess("run", "long", 100), D, {"units": "metric"}, hot=True)
    assert hot["during"]["fluids"].startswith("500-1000") and hot["during"]["heat"].startswith("It's hot")
    assert hot["during"]["sodium"].startswith("500-1000")


def test_athlete_preferences_validate(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    a = agent.coach.update_athlete("friend", {"fuel_style": "gels", "caffeine": True, "diet": ["vegan", "gluten_free"]})
    assert a["fuel_style"] == "gels" and a["caffeine"] is True and a["diet"] == ["vegan", "gluten_free"]
    with pytest.raises(CoachError):
        agent.coach.update_athlete("friend", {"fuel_style": "pizza"})
    with pytest.raises(CoachError):
        agent.coach.update_athlete("friend", {"diet": ["keto"]})
    with pytest.raises(CoachError):
        agent.coach.update_athlete("friend", {"caffeine": "yes"})


def _plan() -> dict[str, Any]:
    return build_plan({"weekly_hours": 8}, {"title": "Half", "date": (TODAY + timedelta(weeks=12)).isoformat(),
                                             "distance": "half marathon"}, today=TODAY)


def test_payloads_include_fuel_plan_and_hint() -> None:
    plan = _plan()
    w = week_for(plan, TODAY) or plan["weeks"][0]
    d, ss = next((d, ss) for d, ss in sorted(w["days"].items()) if any(s["sport"] != "rest" for s in ss))
    s = next(x for x in ss if x["sport"] != "rest")
    v = session_view(s, d, {}, plan=plan)
    assert v["fuel_plan"] and {"before", "during", "after", "hint"} <= set(v["fuel_plan"])
    pub = public_plan(plan, TODAY)
    sessions = [x for wk in pub["weeks"] for day in wk["days"] for x in day["sessions"]]
    assert all("fuel_hint" in x for x in sessions)
    assert any(x["fuel_hint"] for x in sessions if x["kind"] == "long")


def test_later_today_detects_a_second_session() -> None:
    plan = _plan()
    w = plan["weeks"][0]
    day = sorted(w["days"])[0]
    a, b = sess("run", "easy", 40, "06:00"), sess("strength", "strength", 30, "18:00")
    w["days"][day] = [a, b]
    assert _later_today(a, day, plan) is True and _later_today(b, day, plan) is False


def test_rabbit_context_includes_the_same_fueling(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    now = agent._now("friend")
    plan = _plan()
    long_run = sess("run", "long", 110, "07:00")
    long_run["title"] = "Long run"
    w = week_for(plan, now.date() + timedelta(days=1))
    if w is None:
        w = plan["weeks"][0]
        w["start"] = (now.date() - timedelta(days=now.weekday())).isoformat()
    w["days"][(now.date() + timedelta(days=1)).isoformat()] = [long_run]
    agent.plans.get = lambda uid: plan  # type: ignore[method-assign]
    lines = agent._fuel_lines("friend", now)
    assert any(x.startswith("Tomorrow: Fueling the app shows for Long run") and "Carb-rich dinner" in x for x in lines)


def test_home_card_says_tonight_dinner_before_an_early_long_run(env, monkeypatch) -> None:  # noqa: F811
    import asyncio
    from datetime import datetime

    from garmin_mcp import today as today_mod
    from garmin_mcp.upnext import UpNextService
    agent, _ = env.agent([])
    plan = _plan()
    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=18).astimezone()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    w = week_for(plan, TODAY + timedelta(days=1)) or plan["weeks"][0]
    long_run = sess("run", "long", 110, "07:00")
    long_run["title"] = "Long run"
    w["days"][tomorrow] = [long_run]
    agent.plans.get = lambda uid: plan  # type: ignore[method-assign]
    agent._now = lambda uid: now  # type: ignore[method-assign]

    async def no_card(self, uid):  # noqa: ANN001
        return {"tone": "rest", "headline": "Rest day", "detail": "", "action": {}}
    monkeypatch.setattr(today_mod.TodayService, "get", no_card)
    out = asyncio.run(UpNextService(agent, None, garmin=lambda u: True).get("friend"))
    assert out["fuel"] == "Tonight: a carb-rich dinner for tomorrow's long run"
