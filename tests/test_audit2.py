"""Regression tests for the second October 2026 audit (Garmin rate limit, challenges,
caches, predictions, coach privacy, plan import limits)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any

from garmin_mcp import sources
from garmin_mcp.stats import StatsService

TODAY = date(2026, 10, 14)


class CountingGarmin:
    """A stub GarminService: counts upstream reads, each one slow like Garmin."""

    def __init__(self, delay: float = 0.05) -> None:
        self.calls: list[str] = []
        self.delay = delay
        self._lock = threading.Lock()

    def _hit(self, name: str) -> None:
        with self._lock:
            self.calls.append(name)
        time.sleep(self.delay)

    def activities_between(self, user_id: str, start: date, end: date) -> list[dict[str, Any]]:
        self._hit("get_activities_by_date")
        return [{"activity_id": 1, "date": "2026-10-13 07:00:00", "sport": "running", "name": "Run",
                 "duration": "0:40:00", "distance_km": 8.0}]

    def execute(self, user_id: str, method: str, args: dict[str, Any] | None) -> dict[str, Any]:
        self._hit(method)
        if method == "get_training_readiness":
            return {"result": [{"score": 70}]}
        return {"result": {"dailySleepDTO": {"sleepTimeSeconds": 27000}}}


def test_progress_tab_cold_load_stays_under_the_garmin_rate_limit() -> None:
    svc = CountingGarmin()
    stats = StatsService(svc, now=lambda u: datetime(2026, 10, 14, 9), athlete=lambda u: {},
                         plan=lambda u: None)
    rec = lambda: sources.garmin_recovery(svc, "u", TODAY)  # noqa: E731
    # What each Progress-tab request reads (see webapp: stats, progress, readiness,
    # challenges, recovery, load, insights (acts + recovery + adjust), today).
    routes = {
        "stats": lambda: stats.get("u"),
        "progress": lambda: stats.activities("u"),
        "readiness": lambda: stats.activities("u"),
        "challenges": lambda: stats.activities("u"),
        "recovery": rec,
        "load": lambda: stats.load("u"),
        "insights": lambda: (stats.activities("u"), rec(), rec()),
        "today": lambda: (rec(), stats.activities("u")),
    }
    with ThreadPoolExecutor(len(routes)) as pool:
        for f in [pool.submit(fn) for fn in routes.values()]:
            f.result()
    assert svc.calls.count("get_activities_by_date") == 1
    assert len(svc.calls) <= 10, svc.calls
    # A second load inside 10 minutes reads nothing.
    n = len(svc.calls)
    with ThreadPoolExecutor(len(routes)) as pool:
        for f in [pool.submit(fn) for fn in routes.values()]:
            f.result()
    assert len(svc.calls) == n


def test_recovery_cache_serves_shorter_windows_and_forgets_on_sync() -> None:
    svc = CountingGarmin(delay=0)
    long = sources.garmin_recovery(svc, "u", TODAY, 5)
    n = len(svc.calls)
    short = sources.garmin_recovery(svc, "u", TODAY, 3)
    assert len(svc.calls) == n and short["window"] == 3 and len(short["days"]) == 3
    assert short["latest"] == long["latest"]
    sources.forget_recovery(svc, "u")
    sources.garmin_recovery(svc, "u", TODAY, 3)
    assert len(svc.calls) == n + 6


# ------------------------------------------------------------ app helpers --
import asyncio  # noqa: E402
import copy  # noqa: E402
from datetime import timedelta  # noqa: E402

import httpx2  # noqa: E402
import pytest  # noqa: E402
from starlette.applications import Starlette  # noqa: E402

from garmin_mcp import explore, geo, localacts, predict  # noqa: E402
from garmin_mcp.appstore import AppStore  # noqa: E402
from garmin_mcp.coachdir import SEED_COACHES  # noqa: E402
from garmin_mcp.coaches import coach_user_id  # noqa: E402
from garmin_mcp.config import Settings  # noqa: E402
from garmin_mcp.readiness import ReadinessService  # noqa: E402
from garmin_mcp.webapp import build_app_routes  # noqa: E402
from garmin_mcp.webauth import WebAuth  # noqa: E402
from garmin_mcp.webchat import ChatRunner  # noqa: E402
from tests.test_agent import env  # noqa: E402,F401  (fixture)

BASE = "http://localhost:8001"
H = {"origin": BASE}
COACH = "coach@example.com"


def _app(env, agent, tmp_path, uid="friend"):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=uid),
                                             env.tokens, None, None, ChatRunner(agent)))


def _client(app):
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE)


# ----------------------------------------------------------- 3 / 12 caches --
def test_throttle_queue_is_capped() -> None:
    t = geo.Throttle(1.0, clock=lambda: 100.0, sleep=lambda s: asyncio.sleep(0))

    async def go() -> None:
        for _ in range(6):  # slots at +0..+5 s: all within the 5 s cap
            await t.wait()
        with pytest.raises(geo.Busy):
            await t.wait()
    asyncio.run(go())


def test_local_groups_empty_result_cached_for_an_hour_only(tmp_path, fernet_key) -> None:
    now = [1000.0]
    f = localacts.LocalFinder(AppStore(tmp_path / "app", fernet_key), clock=lambda: now[0])

    async def research(system, prompt, **kw):
        return {"activities": []}
    asyncio.run(f.find(research, "Leadville", "CO", TODAY))
    assert f.cached("Leadville", "CO", TODAY) == []
    now[0] += 3601
    assert f.cached("Leadville", "CO", TODAY) is None  # search again
    f2 = localacts.LocalFinder(AppStore(tmp_path / "app", fernet_key), clock=lambda: now[0])
    assert f2.cached("Leadville", "CO", TODAY) is None  # the stored doc agrees


# ---------------------------------------------------------------- 4 predict --
def test_event_distance_beats_the_longest_info_distance() -> None:
    ev = {"type": "trail", "distance": "50k", "distance_km": 50.0,
          "info": {"distances": "50K, 100K and 100 miles"}}
    assert predict.event_inputs(ev)["kwargs"]["distance_km"] == 50.0
    ev = {"type": "trail", "distance": "50k", "info": {"distances": "50K, 100K and 100 miles"}}
    assert predict.event_inputs(ev)["kwargs"]["distance_km"] == 50.0  # its own "50k" label
    ev2 = {"type": "trail", "distance": "ultra", "info": {"distances": "50K, 100 miles"}}
    km = predict.event_inputs(ev2)["kwargs"]["distance_km"]
    assert round(km, 1) == 160.9  # nothing of its own: the info's longest


def test_generic_predict_minimum_distance(env, tmp_path) -> None:
    agent, _ = env.agent([])
    app = _app(env, agent, tmp_path)

    async def go() -> None:
        async with _client(app) as c:
            r = await c.get("/app/api/predict?type=running&distance_km=0.2")
            assert r.status_code == 400 and "0.4" in r.json()["error"]
            assert (await c.get("/app/api/predict?type=running&distance_km=0.4")).status_code == 200
    asyncio.run(go())


# ------------------------------------------------------ 5 / 9 coach privacy --
def test_directory_invite_is_view_only_by_default_and_coach_view_has_no_location(env, tmp_path) -> None:
    agent, _ = env.agent([])
    seeds = copy.deepcopy(SEED_COACHES)
    seeds[0]["rabbit_user_email"] = COACH
    env.store.global_doc("coach_directory").save({"coaches": seeds, "seed_version": 999})
    agent.coach.update_athlete("friend", {"interests": {"race_types": ["trail"], "home_zip": "80204"}})
    env.store.user_doc("friend", "profile").update(lambda p: p.__setitem__("location", {
        "lat": 39.74, "lon": -104.98, "city": "Denver", "state": "CO", "zip": "80204"}))
    a, c = _app(env, agent, tmp_path), _app(env, agent, tmp_path, coach_user_id(COACH))

    async def go() -> None:
        async with _client(a) as ac, _client(c) as cc:
            r = await ac.post(f"/app/api/coaches/directory/{seeds[0]['id']}/invite", headers=H, json={})
            assert r.status_code == 201, r.text
            link = next(x for x in r.json()["coaches"] if x["email"] == COACH)
            assert link["can_edit_plan"] is False and link["can_see_rabbit_chats"] is False
            body = (await cc.get("/app/api/coach/athletes/friend")).json()
            text = repr(body)
            assert "80204" not in text and "39.74" not in text and "location" not in body["athlete"]
            assert body["athlete"]["interests"] == {"race_types": ["trail"]}
    asyncio.run(go())


# ------------------------------------------------------------ 8 invalidation --
def test_writes_and_syncs_invalidate_readiness_and_predictions(env, tmp_path, monkeypatch) -> None:
    dropped: list[str] = []
    monkeypatch.setattr(ReadinessService, "invalidate", lambda self, uid: dropped.append(uid))
    agent, _ = env.agent([])
    _app(env, agent, tmp_path)
    today = agent._now("friend").date()
    agent.events.create("friend", {"name": "Race", "type": "running", "distance": "10k",
                                   "date": (today + timedelta(weeks=8)).isoformat()})
    assert dropped and set(dropped) == {"friend"}
    dropped.clear()
    env.store.user_doc("friend", "checkins").update(lambda d: d.setdefault("items", []))
    assert dropped == ["friend"]
    dropped.clear()
    agent.stats.invalidate("friend", activities=True)  # new workout synced
    assert dropped == ["friend"]
    dropped.clear()
    env.store.user_doc("friend", "progress").update(lambda d: d.setdefault("xp", 0))  # unrelated doc
    assert dropped == []


# --------------------------------------------------------- 10 plan imports --
def test_plan_import_bodies_are_capped_before_reading(env, tmp_path) -> None:
    agent, _ = env.agent([])
    app = _app(env, agent, tmp_path)

    async def go() -> None:
        async with _client(app) as c:
            big = b'{"rows": [' + b'{"date":"2026-10-20"},' * 40000 + b'{}]}'
            r = await c.post("/app/api/plan/import/rows", headers={**H, "content-type": "application/json"},
                             content=big)
            assert r.status_code == 413
    asyncio.run(go())


# ----------------------------------------------------------------- 11 https --
def test_web_urls_must_be_https() -> None:
    assert explore._url("https://race.example.org/x") == "https://race.example.org/x"
    assert explore._url("http://race.example.org/x") is None
