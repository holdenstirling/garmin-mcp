"""Stats: streaks, totals, weekly volume, bests, badges and plan adherence."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import build_plan
from garmin_mcp.stats import compute, headline
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

TODAY = date(2026, 10, 14)  # Wednesday
BASE = "http://localhost:8001"


def act(d: date, sport="running", minutes=45, km=8.0, climb=50, hour=6, aid=None):
    h, m = divmod(minutes, 60)
    return {"activity_id": aid or int(d.strftime("%Y%m%d")) * 10 + hour, "date": f"{d.isoformat()} {hour:02d}:30:00",
            "name": f"{sport} {d}", "sport": sport, "duration": f"{h}:{m:02d}:00", "distance_km": km,
            "elevation_gain_m": climb}


def test_streaks_and_totals() -> None:
    acts = [act(TODAY - timedelta(days=i)) for i in range(1, 6)]          # 5 days up to yesterday
    acts += [act(TODAY - timedelta(days=i)) for i in range(20, 30)]       # an older 10-day run
    acts.append(act(TODAY - timedelta(days=3), sport="cycling", minutes=200, km=80, climb=900, hour=14, aid=9))
    s = compute(acts, TODAY)
    assert s["streak"]["current"] == 5 and s["streak"]["best"] == 10 and not s["streak"]["today_done"]
    assert "rest day won't break it" in s["headline"] and not s["streak"]["at_risk"]
    assert s["totals"]["week"]["workouts"] == 2  # Mon + Tue of this week
    assert s["totals"]["year"]["workouts"] == 16
    assert s["bests"]["longest_ride_km"]["value"] == 80
    assert len(s["weekly"]) == 12 and s["weekly"][-1]["start"] == "2026-10-12"
    earned = {b["id"] for b in s["badges"] if b["earned"]}
    assert {"first", "streak3", "streak7", "early", "long3h"} <= earned
    assert "streak30" not in earned
    # Trained today: the streak includes today.
    s2 = compute(acts + [act(TODAY, aid=1)], TODAY)
    assert s2["streak"]["current"] == 6 and s2["streak"]["today_done"]


def test_multisport_legs_count_once_and_future_ignored() -> None:
    parent = act(TODAY - timedelta(days=1), sport="multi_sport", minutes=300, aid=100) | {
        "multisport": {"is_parent": True}}
    leg = act(TODAY - timedelta(days=1), sport="cycling", aid=101) | {"multisport": {"parent_id": 100}}
    future = act(TODAY + timedelta(days=2), aid=102)
    s = compute([parent, leg, future], TODAY)
    assert s["totals"]["year"]["workouts"] == 1


def test_plan_adherence() -> None:
    athlete = {"weekly_hours": 6, "level": "intermediate", "available_days": ["mon", "wed", "fri", "sat"],
               "long_day": "sat"}
    start = TODAY - timedelta(days=16)
    plan = build_plan(athlete, {"title": "10K", "date": (TODAY + timedelta(weeks=8)).isoformat(),
                                "distance": "10k"}, today=start)
    # Do every planned session last week, nothing else.
    acts = []
    last_mon = TODAY - timedelta(days=TODAY.weekday() + 7)
    for w in plan["weeks"]:
        for d, ss in w["days"].items():
            dd = date.fromisoformat(d)
            if last_mon <= dd < last_mon + timedelta(days=7):
                for i, x in enumerate(ss):
                    if x["sport"] != "rest":
                        acts.append(act(dd, sport={"run": "running", "bike": "cycling", "strength": "strength_training",
                                                   "swim": "lap_swimming"}.get(x["sport"], "other"), aid=hash((d, i)) % 10**9))
    s = compute(acts, TODAY, plan=plan)
    p = s["plan"]
    assert p["perfect_weeks"] >= 1 and p["week"] is not None
    assert any(b["id"] == "plan_week" and b["earned"] for b in s["badges"])
    assert p["to_date"]["planned"] >= p["to_date"]["done"] > 0


def test_headline_empty() -> None:
    assert "Every streak starts" in headline(0, False, 0, {"workouts": 0}, None, 0)


def test_stats_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/stats")
            assert r.status_code == 200, r.text
            body = r.json()
            assert {"streak", "totals", "weekly", "badges", "calendar", "headline"} <= set(body)
    asyncio.run(go_())
