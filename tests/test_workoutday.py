"""Workout day: the pre-workout screen and the post-workout reaction card."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import build_plan, make_session, week_for
from garmin_mcp.progress import PLAN_SESSION_XP, workout_xp
from garmin_mcp.providers import fake as fake_mod
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from garmin_mcp.weekplan import merge
from garmin_mcp.workoutday import (
    _WX,
    build_reaction,
    gear_for,
    new_bests,
    purpose,
    readiness_line,
    session_view,
    targets,
    verdict,
    weather_now,
)
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_stats import TODAY, act

BASE = "http://localhost:8001"
ATHLETE = {"threshold_hr": 170, "run_threshold_pace": 270, "ftp_w": 250, "swim_css": 100}


def easy_run(minutes: int = 50) -> dict[str, Any]:
    s = make_session("run", "easy", minutes)
    s["id"] = "s1"
    return s


def ract(minutes: int, hr: int | None = None, km: float = 9.0, aid: int = 7, d: date = TODAY, sport: str = "running"):
    a = act(d, sport=sport, minutes=minutes, km=km, aid=aid)
    if hr is not None:
        a["avg_hr"] = hr
    return a


# ---------------------------------------------------------------- targets --
def test_targets_in_athlete_units() -> None:
    assert targets("run", 4, ATHLETE)[0] == {"kind": "pace", "label": "4:27–4:44 /km"}
    assert targets("run", 4, ATHLETE)[1]["label"] == "160–170 bpm"
    mi = targets("run", 2, ATHLETE | {"units": "imperial"})[0]["label"]
    assert mi.endswith("/mi") and mi.startswith("8:")
    assert targets("bike", 2, ATHLETE)[0]["label"] == "140–188 W"
    assert targets("swim", 4, ATHLETE) == [{"kind": "pace", "label": "1:38–1:42 /100m"}]
    assert targets("run", 2, {}) == [{"kind": "rpe", "label": "RPE 3-4 · conversational"}]


def test_session_view_sections_purpose_fuel_and_garmin() -> None:
    s = make_session("run", "threshold", 60)
    s["id"], s["garmin"] = "s9", {"workout_ids": [1]}
    v = session_view(s, TODAY.isoformat(), ATHLETE, phase="build")
    assert [x["kind"] for x in v["sections"]] == ["warmup", "main", "cooldown"]
    rep = v["sections"][1]["steps"][0]
    assert rep["type"] == "repeat" and rep["steps"][0]["targets"][0]["kind"] == "pace"
    assert v["warmup_min"] == 15 and v["purpose"].startswith("Build phase: threshold")
    assert v["garmin"]["on_watch"] is True and v["cue"] and v["fuel"] is None
    long = make_session("bike", "long", 150)
    assert session_view(long, TODAY.isoformat(), ATHLETE)["fuel"]["carbs_g_per_h"] >= 30
    brick = make_session("brick", "brick", 90)
    names = [x["name"] for x in session_view(brick, TODAY.isoformat(), ATHLETE)["sections"]]
    assert "Run leg" in names and any(n.startswith("Bike leg") for n in names)
    assert purpose("long", "base", recovery=True).startswith("Recovery week:")


def test_readiness_line() -> None:
    assert readiness_line(None) is None
    card = {"tone": "go", "signals": [{"label": "Form", "value": "+4", "good": True},
                                      {"label": "Readiness", "value": "82", "good": True}]}
    assert readiness_line(card)["line"] == "Form +4 · Readiness 82: good to go."
    assert readiness_line({"tone": "easy", "detail": "Swap it.", "signals": []})["line"] == "Swap it."


# ---------------------------------------------------------------- verdict --
def test_verdict_rules() -> None:
    s = easy_run(50)
    # Within ±10% and in zone (Z2 = 138-151 bpm at LTHR 170).
    assert verdict(s, ract(52, hr=145), ATHLETE)["verdict"] == "nailed"
    # Duration fine, no HR known: can't judge the zone, so it doesn't count against.
    assert verdict(s, ract(47), {})["verdict"] == "nailed"
    short = verdict(s, ract(30, hr=145), ATHLETE)
    assert short["verdict"] == "close" and "30' of 50'" in short["line"]
    hard = verdict(s, ract(50, hr=165), ATHLETE)
    assert hard["verdict"] == "close" and hard["effort"]["direction"] == "harder"
    # Pace fallback when there's no HR: 5:00/km is far quicker than Z2 at 4:30 threshold.
    fast = verdict(s, ract(50, km=10.0), {"run_threshold_pace": 270})
    assert fast["verdict"] == "close" and fast["effort"]["basis"] == "pace"
    # Intervals: duration decides, avg HR isn't judged.
    vo2 = make_session("run", "vo2", 50)
    assert verdict(vo2, ract(vo2["minutes"], hr=175), ATHLETE)["verdict"] == "nailed"
    other = verdict(None, ract(40, sport="cycling"), ATHLETE, planned_other=[s])
    assert other["verdict"] == "different" and "Easy run" in other["line"]
    assert verdict(None, ract(40), ATHLETE)["verdict"] == "bonus"


def test_reaction_matches_plan_like_the_week_view() -> None:
    athlete = {"weekly_hours": 6, "level": "intermediate", "available_days": ["mon", "wed", "fri", "sat"],
               "long_day": "sat"}
    plan = build_plan(athlete, {"title": "10K", "date": (TODAY + timedelta(weeks=10)).isoformat(),
                                "distance": "10k"}, today=TODAY - timedelta(days=21))
    w = week_for(plan, TODAY)
    assert w is not None
    day, ss = next((d, x) for d, x in sorted(w["days"].items()) if d <= TODAY.isoformat()
                   and any(s["sport"] == "run" for s in x))
    s = next(x for x in ss if x["sport"] == "run")
    d = date.fromisoformat(day)
    hist = [act(d - timedelta(days=i), km=5.0, aid=100 + i) for i in range(1, 20)]
    a = act(d, minutes=s["minutes"], km=12.0, aid=1)
    acts = [a, *hist]
    planned = {k: [{"sport": x["sport"], "title": x["title"], "minutes": x.get("minutes"), "kind": x.get("kind"),
                    "id": x["id"]} for x in v] for k, v in w["days"].items()}
    dview = next(x for x in merge(date.fromisoformat(w["start"]), TODAY, planned, acts) if x["date"] == day)
    gear = [{"id": "g1", "kind": "shoes", "brand": "Hoka", "model": "Speedgoat 6", "default_for": ["run"],
             "retired": False, "total_km": 700.0, "status": "retire", "pct_of_alert": 110}]
    r = build_reaction(a, acts, dview, plan=plan, athlete={"units": "imperial"}, today=TODAY,
                       streak={"current": 4, "best": 9}, gear=gear, tomorrow=None)
    assert r["verdict"] == "nailed" and r["session_id"] == s["id"]
    assert r["xp"] == {"workout": workout_xp(s["minutes"]), "plan": PLAN_SESSION_XP,
                       "total": workout_xp(s["minutes"]) + PLAN_SESSION_XP}
    assert r["gear"]["label"] == "+7.5 mi on Hoka Speedgoat 6" and r["gear"]["warning"]
    assert r["streak"]["current"] == 4 and r["planned"]["minutes"] == s["minutes"]
    assert [b["key"] for b in r["bests"]][:1] == ["longest_run_km"]
    # An unplanned ride the same day is a bonus with no plan XP.
    ride = act(d, sport="cycling", minutes=60, km=25, aid=2, hour=18)
    dview2 = next(x for x in merge(date.fromisoformat(w["start"]), TODAY, planned, [*acts, ride]) if x["date"] == day)
    r2 = build_reaction(ride, [*acts, ride], dview2, plan=plan, athlete={}, today=TODAY, streak={}, gear=[], tomorrow=None)
    assert r2["verdict"] in ("bonus", "different") and r2["xp"]["plan"] == 0 and r2["gear"] is None


def test_new_bests() -> None:
    base = [act(TODAY - timedelta(days=i), km=10.0, minutes=60, climb=100, aid=10 + i) for i in range(1, 10)]
    big = act(TODAY, km=21.1, minutes=120, climb=50, aid=1)
    keys = [b["key"] for b in new_bests([big, *base], 1, TODAY)]
    assert keys == ["longest_run_km", "longest_workout_min"]
    assert new_bests([act(TODAY, km=5, aid=1), *base], 1, TODAY) == []
    assert new_bests([big], 1, TODAY) == []  # first-ever activity isn't a "best"
    old = act(TODAY - timedelta(days=400), km=50.0, aid=99)  # beyond 12 months: ignored
    assert "longest_run_km" in [b["key"] for b in new_bests([big, old, *base], 1, TODAY)]
    swim = act(TODAY, sport="lap_swimming", km=3.0, minutes=30, climb=0, aid=2)
    assert new_bests([swim, *base], 2, TODAY) == []  # no earlier swim to beat


def test_gear_for_defaults_and_tags() -> None:
    views = [{"id": "a", "kind": "shoes", "brand": "Nike", "model": "Pegasus", "default_for": ["run"], "retired": False,
              "total_km": 100.0, "status": "ok"},
             {"id": "b", "kind": "shoes", "nickname": "Trail pair", "default_for": [], "activity_ids": [5],
              "retired": False, "total_km": 520.0, "status": "soon", "pct_of_alert": 81}]
    assert gear_for(views, "run")["name"] == "Nike Pegasus"
    tagged = gear_for(views, "running", activity_id=5)
    assert tagged["name"] == "Trail pair" and "81%" in tagged["warning"]
    assert gear_for(views, "bike") is None


def test_weather_now_cached() -> None:
    calls: list[str] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        calls.append(req.url.path)
        if "search" in req.url.path:
            return httpx2.Response(200, json={"results": [{"name": "Denver", "admin1": "Colorado",
                                                           "latitude": 39.7, "longitude": -105.0}]})
        return httpx2.Response(200, json={
            "current": {"temperature_2m": 12.5, "apparent_temperature": 11.0, "weather_code": 2, "wind_speed_10m": 9},
            "hourly": {"time": ["2026-10-14T08:00", "2026-10-14T09:00", "2026-10-14T10:00", "2026-10-14T11:00"],
                       "temperature_2m": [12, 13, 15, 16], "precipitation_probability": [0, 10, 40, 5],
                       "weather_code": [2, 2, 61, 3]}})
    _WX.clear()

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
            w = await weather_now("Denver, CO", http=c, clock=lambda: 1000.0)
            assert w and w["place"] == "Denver, Colorado" and w["summary"] == "Partly cloudy"
            assert w["rain_pct"] == 40 and [h["time"] for h in w["next"]] == ["09:00", "10:00", "11:00"]
            again = await weather_now("denver,  co", http=c, clock=lambda: 1500.0)
            assert again == w and len(calls) == 2
            assert await weather_now("", http=c) is None
    asyncio.run(go())
    _WX.clear()


# ------------------------------------------------------------------- api ---
def test_workout_api_routes(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    fake_mod._SIMULATED.clear()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/workout/today")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["state"] in {"free", "rest", "session"} and body["weather"] is None
            if body["state"] == "free":
                assert "30-45 min easy" in body["free"]["purpose"]
            assert (await c.get("/app/api/workout/today?session_id=../x")).status_code == 400
            assert (await c.get("/app/api/workout/reaction?activity_id=abc")).status_code == 400
            assert (await c.get("/app/api/workout/reaction?activity_id=1")).status_code == 404
            _, acts = agent.stats.activities("friend")
            aid = next(a["activity_id"] for a in acts if not a.get("multisport"))
            r = await c.get(f"/app/api/workout/reaction?activity_id={aid}")
            assert r.status_code == 200, r.text
            rb = r.json()
            assert rb["verdict"] in {"nailed", "close", "different", "bonus"} and rb["xp"]["total"] >= 10
            assert rb["activity"]["id"] == aid and isinstance(rb["line"], str)
    try:
        asyncio.run(go_())
    finally:
        fake_mod._SIMULATED.clear()
