"""Weather-aware workouts: heat/cold/wind/altitude rules, best time to go, and the routes."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2

from garmin_mcp import weather as wx
from garmin_mcp.planbuilder import iter_sessions
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

ATHLETE = {"available_days": ["tue", "wed", "thu", "sat", "sun"], "long_day": "sat",
           "home_location": "Denver, CO", "units": "imperial"}


def _h(t: str, temp: float, dew: float = 5, wind: float = 5, rain: float = 0, code: int = 1,
       feels: float | None = None, aqi: float | None = None, day: bool = True) -> dict:
    return {"t": t, "temp_c": temp, "dew_c": dew, "feels_c": temp if feels is None else feels, "wind_kmh": wind,
            "gust_kmh": wind + 10, "rain_pct": rain, "code": code, "summary": "", "aqi": aqi, "day": day}


def test_heat_scale() -> None:
    assert wx.heat_pct(15, 5) == 0.0                       # 59 + 41 = 100 °F: nothing
    assert wx.heat_pct(30, 22) > 3.0                       # 86 + 72 = 158: about 5.7%
    assert 5.0 < wx.heat_pct(30, 22) < 6.5
    assert wx.heat_pct(38, 27) == 12.0                     # off the chart: easy by heart rate


def test_adjust_run_heat_wind_and_safety() -> None:
    run = {"sport": "run", "kind": "easy", "minutes": 60}
    hot = wx.adjust(run, [_h("2026-07-01T15:00", 31, 22)], pace=(330, 360))
    assert "heat" in hot["badges"] and hot["pct"] > 4 and hot["pace"][0] > 330 and hot["pace"][1] > 360
    assert "°F" in hot["note"] or "heat" in hot["note"]
    windy = wx.adjust(run, [_h("2026-07-01T08:00", 10, 2, wind=35)], pace=(330, 360))
    assert "wind" in windy["badges"] and windy["pct"] == 1.0
    storm = wx.adjust(run, [_h("2026-07-01T18:00", 22, 15, code=95, rain=80)])
    assert "storm" in storm["badges"] and any("thunder" in s.lower() for s in storm["safety"])
    icy = wx.adjust(run, [_h("2026-01-10T07:00", -14, -18, code=71, feels=-20)])
    assert {"cold", "ice"} <= set(icy["badges"]) and icy["pct"] >= 2.0
    smoky = wx.adjust(run, [_h("2026-08-10T07:00", 20, 8, aqi=170)])
    assert "air" in smoky["badges"] and any("AQI" in s for s in smoky["safety"])
    # calm, mild: nothing to change
    calm = wx.adjust(run, [_h("2026-05-01T07:00", 12, 4)], pace=(330, 360))
    assert calm["pct"] == 0.0 and calm["pace"] is None and not calm["safety"]


def test_adjust_bike_pool_and_altitude() -> None:
    ride = wx.adjust({"sport": "bike", "minutes": 90}, [_h("t", 10, 0, wind=40)])
    assert "wind" in ride["badges"] and "power" in ride["note"] and ride["pace"] is None
    pool = wx.adjust({"sport": "swim", "minutes": 45}, [_h("t", 35, 25)])
    assert pool["pct"] == 0.0 and "Pool" in pool["note"]
    assert wx.adjust({"sport": "strength"}, [_h("t", 35, 25)])["pct"] == 0.0
    # travelling 1500 m higher than home: +5%, half when acclimatized
    up = wx.adjust({"sport": "run", "minutes": 40}, [_h("t", 10, 0)], elevation_m=1800, home_elevation_m=300)
    assert "altitude" in up["badges"] and up["pct"] == 5.0
    acc = wx.adjust({"sport": "run", "minutes": 40}, [_h("t", 10, 0)], elevation_m=1800, home_elevation_m=300,
                    acclimatized=True)
    assert acc["pct"] == 2.5
    # living at altitude: paces already reflect it, so no slowdown, just an effort note
    home = wx.adjust({"sport": "run", "minutes": 40}, [_h("t", 10, 0)], elevation_m=3100, home_elevation_m=3100)
    assert home["pct"] == 0.0 and "altitude" in home["note"].lower()


def test_best_time_picks_the_cool_dry_hour() -> None:
    day = "2026-07-01"
    hours = []
    for hh in range(24):
        temp = 18 + 14 * max(0.0, 1 - abs(hh - 15) / 8)  # hot afternoon
        code, rain = (95, 80) if 17 <= hh <= 19 else (1, 0)
        hours.append(_h(f"{day}T{hh:02d}:00", temp, 18, code=code, rain=rain, day=6 <= hh <= 20))
    bt = wx.best_time(hours, day, 60, planned="16:00")
    assert bt is not None and int(bt["start"][:2]) <= 9 and bt["better"] and "cooler" in bt["why"]
    # already at the best hour: no nudge
    same = wx.best_time(hours, day, 60, planned=bt["start"])
    assert same is not None and not same["better"]
    assert wx.best_time([], day, 60) is None


def test_hours_for_and_strip() -> None:
    day = "2026-07-01"
    hours = [_h(f"{day}T{hh:02d}:00", 15) for hh in range(24)]
    assert [h["t"][11:13] for h in wx.hours_for(hours, day, "06:30", 90)] == ["06", "07"]
    assert len(wx.strip(hours, day, 6)) == 6


def test_fake_forecast_shape() -> None:
    f = wx.fake_forecast(date(2026, 10, 17))
    assert len(f["hours"]) == 72 and len(f["days"]) == 3 and f["days"][0]["date"] == "2026-10-17"


def test_routes_next_days_and_session(env, tmp_path, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setenv("RABBIT_FAKE_WEATHER", "1")
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    plan = agent.plans.get("friend")
    soon = next(((d, s) for _, d, s in iter_sessions(plan)
                 if s["sport"] != "rest" and today.isoformat() <= d <= (today + timedelta(days=2)).isoformat()), None)
    later = next((s for _, d, s in iter_sessions(plan)
                  if s["sport"] != "rest" and d > (today + timedelta(days=4)).isoformat()))
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get("/app/api/weather/next")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["available"] and body["units"] == "imperial" and len(body["days"]) == 3
            assert body["days"][0]["date"] == today.isoformat() and body["days"][0]["weather"]["hi_c"] is not None
            if soon:
                r = await a.get(f"/app/api/weather/session?session_id={soon[1]['id']}")
                v = r.json()
                assert r.status_code == 200 and v["available"] and v["strip"] and "badges" in v["adjust"]
            r = await a.get(f"/app/api/weather/session?session_id={later['id']}")
            assert r.status_code == 200 and r.json() == {"available": False, "reason": "range",
                                                         "date": r.json()["date"], "units": "imperial"}
            assert (await a.get("/app/api/weather/session?session_id=nope0")).status_code == 404
            assert (await a.get("/app/api/weather/session?session_id=../x")).status_code == 400
            assert (await c.get("/app/api/weather/next")).status_code == 403
    asyncio.run(go_())
