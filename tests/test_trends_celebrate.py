"""Progress trends (trends.py) and celebrations (celebrate.py). Clock-independent: dates are
relative to a fixed day or to the agent's own "today"."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from starlette.applications import Starlette

from garmin_mcp import celebrate as cel, trends as tr
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TZ = ZoneInfo("America/Denver")
DAY = date(2026, 10, 14)  # a Wednesday


def run(aid: int, day: date, *, km: float = 8.0, minutes: int = 45, hr: float | None = 140,
        sport: str = "running", load: float | None = None, te: float | None = 2.5) -> dict[str, Any]:
    a: dict[str, Any] = {"activity_id": aid, "date": f"{day.isoformat()} 07:00:00", "name": "Run", "sport": sport,
                         "duration": f"{minutes // 60}:{minutes % 60:02d}:00" if minutes >= 60 else f"{minutes}:00",
                         "distance_km": km, "avg_hr": hr, "aerobic_te": te}
    if load is not None:
        a["training_load"] = load
    return a


# ------------------------------------------------------------ distance ---
def test_weekly_distance_and_plan_goal() -> None:
    mon = DAY - timedelta(days=DAY.weekday())
    acts = [run(i, mon - timedelta(weeks=w), km=10 + w) for i, w in enumerate(range(10), start=1)]
    acts.append(run(99, mon - timedelta(weeks=1), sport="cycling", km=40, hr=None))
    plan = {"weeks": [{"start": mon.isoformat(), "days": {mon.isoformat(): [
        {"id": "s1", "sport": "run", "kind": "easy", "minutes": 60, "title": "Easy", "steps": []}]}}]}
    out = tr.distance(acts, DAY, plan=plan, athlete={"run_threshold_pace": 300}, imperial=False)
    sports = {s["sport"]: s for s in out["sports"]}
    assert set(sports) == {"run", "bike"}
    weeks = sports["run"]["weeks"]
    assert len(weeks) == tr.WEEKS and weeks[-1]["start"] == mon.isoformat()
    assert weeks[-1]["km"] == 10 and weeks[-2]["km"] == 11 and weeks[0]["km"] == 0
    assert weeks[-1]["goal"] and weeks[-1]["goal"] > 0 and weeks[-2]["goal"] is None
    # Mid-week: finished weeks compare (weeks -2..-5 = 11..14 vs -6..-9 = 15..18).
    assert sports["run"]["avg4_km"] == 12.5 and sports["run"]["prev4_km"] == 16.5
    assert sports["run"]["change_pct"] == -24
    assert out["sports"][0]["sport"] == "bike" or sum(w["km"] for w in weeks) > 40


# ---------------------------------------------------------------- pace ---
def test_pace_at_easy_effort_gets_faster() -> None:
    mon = DAY - timedelta(days=DAY.weekday())
    acts = []
    for w in range(8):  # older weeks slower at the same heart rate
        day = mon - timedelta(weeks=7 - w)
        acts.append(run(w * 10 + 1, day, km=8.0 + w * 0.2, minutes=48, hr=140))   # easy
        acts.append(run(w * 10 + 2, day + timedelta(days=2), km=10, minutes=45, hr=170, te=4.2))  # hard
    out = tr.pace(acts, DAY, imperial=False)
    assert out["ref_hr"] == 140 and len(out["points"]) == 8
    assert out["points"][0]["sec"] > out["points"][-1]["sec"]
    assert out["change_s"] < 0
    mi = tr.pace(acts, DAY, imperial=True)
    assert mi["points"][0]["sec"] == round(out["points"][0]["sec"] * tr.KM_PER_MI, 0) or \
        abs(mi["points"][0]["sec"] - out["points"][0]["sec"] * tr.KM_PER_MI) <= 1
    few = tr.pace(acts[:4], DAY, imperial=False)
    assert few["points"] == [] and "4 different weeks" in few["reason"]
    assert tr.pace([], DAY, imperial=False)["reason"].startswith("No runs")


# --------------------------------------------------------------- sleep ---
def test_sleep_vs_load_and_collecting(tmp_path, fernet_key) -> None:
    acts = [run(i, DAY - timedelta(days=i), load=200 if i % 4 == 0 else 50) for i in range(1, 25)]
    nights = {(DAY - timedelta(days=i) + timedelta(days=1)).isoformat(): (6.0 if i % 4 == 0 else 7.5)
              for i in range(1, 25)}
    out = tr.sleep(nights, acts, DAY, source="garmin")
    assert out["measure"] == "load" and len(out["points"]) == tr.SLEEP_DAYS
    assert out["hard_h"] == 6.0 and out["other_h"] == 7.5 and out["reason"] is None
    few = tr.sleep(dict(list(nights.items())[:3]), acts, DAY, source="garmin")
    assert few["nights"] == 3 and "3 of 7 nights" in few["reason"] and few["hard_h"] is None
    # Garmin nights are kept (date + hours only) and merged as days go by.
    store = AppStore(tmp_path / "app", fernet_key)
    log = tr.SleepLog(store)
    assert log.merge("u", [{"date": "2026-10-10", "sleep_hours": 7.2, "hrv": 50}]) == {"2026-10-10": 7.2}
    assert log.merge("u", [{"date": "2026-10-11", "sleep_hours": 6.4}, {"date": "x"}]) == \
        {"2026-10-10": 7.2, "2026-10-11": 6.4}
    assert store.user_doc("u", "sleeplog").load() == {"nights": {"2026-10-10": 7.2, "2026-10-11": 6.4}}


def test_service_caches(monkeypatch) -> None:
    calls = []

    def gather(uid: str) -> dict[str, Any]:
        calls.append(uid)
        return {"acts": [], "today": DAY, "plan": None, "athlete": {}, "nights": {}, "sleep_source": None}
    t = [0.0]
    svc = tr.TrendsService(gather, clock=lambda: t[0])
    a = svc.get("u")
    assert set(a) == {"today", "units", "distance", "pace", "sleep"} and calls == ["u"]
    svc.get("u")
    t[0] = tr.CACHE_S + 1
    svc.get("u")
    svc.get("u", fresh=True)
    assert calls == ["u", "u", "u"]


# -------------------------------------------------------- celebrations ---
def test_race_and_block_items_once(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    events = [{"id": "e1", "name": "Boulder Half", "kind": "race", "date": (DAY - timedelta(days=3)).isoformat(),
               "distance": "half marathon", "result": ""},
              {"id": "e2", "name": "Old race", "kind": "race", "date": (DAY - timedelta(days=40)).isoformat(),
               "result": "1:40:00"},
              {"id": "e3", "name": "Future", "kind": "race", "date": (DAY + timedelta(days=3)).isoformat()},
              {"id": "e4", "name": "No proof", "kind": "race", "date": (DAY - timedelta(days=1)).isoformat()},
              {"id": "e5", "name": "Group ride", "kind": "group_activity", "date": (DAY - timedelta(days=1)).isoformat(),
               "result": "fun"}]
    acts = [run(1, DAY - timedelta(days=3), km=21.2, minutes=105)]
    store.global_doc("blocks").update(lambda d: d.setdefault("blocks", {}).update({
        "b1": {"id": "b1", "name": "8-week 5K build", "weeks": 8, "end": (DAY - timedelta(days=2)).isoformat(),
               "status": "active", "members": {"u": {}, "f": {}},
               "progress": {"2026-09-28": {"u": [4, 4]}, "2026-10-05": {"u": [3, 4]}}},
        "b2": {"id": "b2", "name": "Stopped", "weeks": 6, "end": (DAY - timedelta(days=2)).isoformat(),
               "status": "ended", "ended_on": (DAY - timedelta(days=20)).isoformat(), "members": {"u": {}}},
        "b3": {"id": "b3", "name": "Not mine", "weeks": 6, "end": (DAY - timedelta(days=2)).isoformat(),
               "status": "active", "members": {"x": {}}},
        "b4": {"id": "b4", "name": "Still going", "weeks": 6, "end": (DAY + timedelta(days=5)).isoformat(),
               "status": "active", "members": {"u": {}}}}))
    c = cel.Celebrations(store, now=lambda u: datetime.combine(DAY, datetime.min.time(), TZ),
                         events=lambda u: events, acts=lambda u: acts, imperial=lambda u: True)
    items = c.pending("u")
    assert [i["id"] for i in items] == ["race:e1", "block:b1"]
    race = items[0]
    assert race["title"] == "You finished!" and race["subtitle"] == "Boulder Half"
    assert {"label": "Time", "value": "1:45:00"} in race["stats"]
    assert {"label": "Distance", "value": "13.2 mi"} in race["stats"]
    block = items[1]
    assert {"label": "Weeks closed", "value": "1 of 2 (last)"} in block["stats"]
    assert "1 friend" in block["line"]
    c.seen("u", "race:e1")
    assert [i["id"] for i in c.pending("u")] == ["block:b1"]
    assert c.pending("coach_x") == []
    assert cel.valid_id("pr:123") and cel.valid_id("block:b-1") and not cel.valid_id("x:1") and not cel.valid_id("race:a/b")
    assert cel.big_record({"kind": "split_5k", "weeks": None}) and not cel.big_record({"kind": "split_5k", "weeks": 6})
    assert not cel.big_record({"kind": "effect", "weeks": None})


def test_api_shapes_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    acts = [run(i, today - timedelta(days=i * 3)) for i in range(1, 30)]
    agent.stats.activities = lambda uid, fresh=False: (today, acts)  # type: ignore[method-assign]
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    from garmin_mcp.webchat import ChatRunner
    runner = ChatRunner(agent)
    a_app = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user="friend"),
                                              env.tokens, None, None, runner))
    c_app = Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=coach_user_id("c@x.com")),
                                              env.tokens, None, None, runner))
    h = {"origin": BASE}

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=c_app), base_url=BASE) as c:
            r = await a.get("/app/api/progress/trends")
            assert r.status_code == 200, r.text
            if r.status_code == 200:
                assert set(r.json()) == {"today", "units", "distance", "pace", "sleep"}
            r = await a.get("/app/api/celebrations")
            assert r.status_code == 200 and r.json() == {"items": []}
            assert (await a.post("/app/api/celebrations/pr:103/seen", headers=h, json={})).json() == {"ok": True}
            assert (await a.post("/app/api/celebrations/nope/seen", headers=h, json={})).status_code == 404
            assert (await c.get("/app/api/progress/trends")).status_code == 403
            assert (await c.get("/app/api/celebrations")).status_code == 403
            assert (await c.post("/app/api/celebrations/pr:1/seen", headers=h, json={})).status_code == 403
    asyncio.run(go())
    assert env.store.user_doc("friend", "celebrations").load()["seen"].get("pr:103")
