"""Regression tests for the data audit: Garmin workouts across goal switches, atomic setup,
unsync bookkeeping, travel undo, per-day caps, B/C race load, calendar paging, chat limits,
legacy migration and planner failure memory."""

from __future__ import annotations

import asyncio
import threading
from datetime import date, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import gcalendar
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import CoachChat
from garmin_mcp.coaching import CoachError, CoachStore
from garmin_mcp.config import Settings
from garmin_mcp.gcalendar import GoogleCalendar
from garmin_mcp.load import session_load
from garmin_mcp.planbuilder import PlanError, build_plan, iter_sessions
from garmin_mcp.plans import MAX_SESSIONS_PER_DAY
from garmin_mcp.providers import GarminError
from garmin_mcp.providers.fake import FAKE_WORKOUTS
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from garmin_mcp.weekplan import RETRY_AFTER_FAILURE_S, WeekPlanner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _athlete, _setup

BASE = "http://localhost:8001"
TODAY = date(2026, 10, 14)


def _reset():
    FAKE_WORKOUTS.update({"next": 0, "uploaded": {}, "scheduled": {}, "deleted": []})


def _app(env, agent, tmp_path):
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))


def _synced_ids(agent) -> list[int]:
    return [i for _, _, x in iter_sessions(agent.plans.get("friend"))
            for i in (x.get("garmin") or {}).get("workout_ids", [])]


# ------------------------------------------------------- 1. goal switches --
def test_goal_create_and_archive_hand_over_garmin_workouts(env, tmp_path) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    old_ids = _synced_ids(agent)
    assert old_ids
    app = _app(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/goals", headers={"origin": BASE}, json={
                "title": "New", "distance": "10k", "date": (today + timedelta(weeks=12)).isoformat()})
            assert r.status_code == 201, r.text
    asyncio.run(go_())
    agent.plans.build("friend")  # the new goal's first plan picks the parked workouts up
    assert set(old_ids) <= set(agent.plans.get("friend")["garmin_orphans"])
    agent.plans.sync("friend", 7)
    assert set(old_ids) <= set(FAKE_WORKOUTS["deleted"])

    # Archiving the active goal parks its workouts for whatever plan comes next.
    new_ids = _synced_ids(agent)
    gid = agent.coach.active_goal("friend")["id"]

    async def archive() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post(f"/app/api/goals/{gid}/archive", headers={"origin": BASE}, json={})
            assert r.status_code == 200, r.text
    asyncio.run(archive())
    agent.coach.create_goal("friend", {"title": "Next", "distance": "5k",
                                       "date": (today + timedelta(weeks=10)).isoformat()})
    agent.plans.build("friend")
    assert set(new_ids) <= set(agent.plans.get("friend")["garmin_orphans"])


def test_save_goal_replace_current_hands_over_garmin_workouts(env) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    old_ids = _synced_ids(agent)
    out = agent._dispatch("friend", "save_goal", {"replace_current": True, "title": "Boise",
                                                  "distance": "70.3",
                                                  "date": (today + timedelta(weeks=30)).isoformat()})
    assert out["replaced_previous"] is True
    agent.plans.build("friend")
    assert set(old_ids) <= set(agent.plans.get("friend")["garmin_orphans"])


# ------------------------------------------------------ 2. setup is atomic --
def test_setup_with_bad_event_url_changes_nothing(env, tmp_path) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    old_goal = agent.coach.active_goal("friend")
    old_ids = _synced_ids(agent)
    app = _app(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/plan/setup", headers={"origin": BASE}, json={
                "new_goal": True, "athlete": {"weekly_hours": 11},
                "goal": {"title": "New", "distance": "10k", "date": (today + timedelta(weeks=12)).isoformat()},
                "event": {"url": "javascript:alert(1)"}})
            assert r.status_code == 400 and "http" in r.json()["error"]
    asyncio.run(go_())
    assert agent.coach.active_goal("friend")["id"] == old_goal["id"]
    assert agent.coach.athlete("friend")["weekly_hours"] == 8
    assert _synced_ids(agent) == old_ids  # nothing released


def test_setup_failing_after_the_switch_keeps_workouts(env, tmp_path, monkeypatch) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    old_ids = _synced_ids(agent)

    def boom(*a, **kw):
        raise PlanError("build failed")
    real_build = agent.plans.build
    monkeypatch.setattr(agent.plans, "build", boom)
    app = _app(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/plan/setup", headers={"origin": BASE}, json={
                "new_goal": True,
                "goal": {"title": "New", "distance": "10k", "date": (today + timedelta(weeks=12)).isoformat()}})
            assert r.status_code == 400
    asyncio.run(go_())
    monkeypatch.setattr(agent.plans, "build", real_build)
    agent.plans.build("friend")
    assert set(old_ids) <= set(agent.plans.get("friend")["garmin_orphans"])


# --------------------------------------------------------------- 3. unsync --
def test_unsync_keeps_failed_deletes_and_delete_keeps_the_plan(env, monkeypatch) -> None:
    _reset()
    agent, plan, today = _setup(env)
    agent.plans.sync("friend", 7)
    ids = _synced_ids(agent)
    svc = agent.plans._service
    real = svc.workout_delete
    bad = {ids[0]}

    def flaky(user_id, wid):
        if wid in bad:
            raise GarminError("Garmin returned an error.")
        return real(user_id, wid)
    monkeypatch.setattr(svc, "workout_delete", flaky)
    r = agent.plans.unsync("friend")
    assert len(r["errors"]) == 1
    p = agent.plans.get("friend")
    assert p["garmin_orphans"] == [ids[0]] and _synced_ids(agent) == []
    with pytest.raises(PlanError, match="couldn't be removed"):
        agent.plans.delete("friend")
    assert agent.plans.get("friend") is not None
    bad.clear()
    agent.plans.delete("friend")
    assert agent.plans.get("friend") is None and ids[0] in FAKE_WORKOUTS["deleted"]


# --------------------------------------------------------------- 5. travel --
def test_travel_undo_keeps_sessions_added_after_the_trip(env) -> None:
    agent, plan, today = _setup(env, weeks=20)
    mon = today + timedelta(days=7 - today.weekday())
    start, end = mon + timedelta(days=3), mon + timedelta(days=6)
    p = agent.plans.add_travel("friend", {"start": start.isoformat(), "end": end.isoformat()})
    trip = p["trips"][0]
    # A day the trip snapshotted: add a session there after the trip.
    day = next(d for d in sorted(trip["original"]) if
               sum(x["sport"] != "rest" for x in next(w for w in p["weeks"] if d in w["days"])["days"][d])
               < MAX_SESSIONS_PER_DAY)
    p = agent.plans.add_session("friend", {"date": day, "sport": "strength", "title": "Added later"})
    added = next(x for _, d, x in iter_sessions(p) if x.get("title") == "Added later")
    p = agent.plans.remove_travel("friend", trip["id"])
    after = {d: ss for w in p["weeks"] for d, ss in w["days"].items()}
    assert any(x["id"] == added["id"] for x in after[day])
    for d, ss in trip["original"].items():
        if start.isoformat() <= d <= end.isoformat():  # reworked originals are back
            assert {x["id"] for x in ss if x["sport"] != "rest"} <= {x["id"] for x in after[d]}
    assert not any(x.get("travel") for _, _, x in iter_sessions(p))


# ----------------------------------------------------------- 12. day cap --
def test_adjustment_move_respects_the_day_cap(env) -> None:
    agent, plan, today = _setup(env)
    day = next(d for _, d, x in iter_sessions(plan) if d > today.isoformat() and x["sport"] != "rest"
               and x.get("kind") != "race")
    while True:
        try:
            agent.plans.add_session("friend", {"date": day, "sport": "run"})
        except PlanError:
            break
    agent.plans.apply_adjustment("friend", [{"action": "move", "session_id": "missed", "date": day,
                                             "to": {"sport": "run", "kind": "easy", "minutes": 30}}])
    p = agent.plans.get("friend")
    ss = next(w for w in p["weeks"] if day in w["days"])["days"][day]
    assert len(ss) == MAX_SESSIONS_PER_DAY and "missed" not in p.get("made_up", [])


# ------------------------------------------------------- 8. B/C race load --
def test_b_race_load_uses_its_own_distance() -> None:
    plan = build_plan(_athlete(), {"title": "Ironman", "date": "2027-07-26", "distance": "140.6"},
                      today=TODAY, events=[{"id": "e1", "name": "Turkey trot", "type": "running",
                                            "date": "2026-11-26", "priority": "B", "distance": "5k"}])
    race = next(x for _, d, x in iter_sessions(plan) if x.get("event_id") == "e1")
    assert race["race_distance"] == "5k"
    assert session_load(race, plan["distance"]) == session_load(
        {"sport": "run", "kind": "race"}, "5k") < session_load({"sport": "run", "kind": "race"}, "140.6")


# ------------------------------------------------------ 9. Google Calendar --
def test_calendar_follows_pages_and_disconnect_closes_its_client(tmp_path, fernet_key, monkeypatch) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    seen: list[str | None] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        if "revoke" in str(req.url):
            return httpx2.Response(200)
        tok = req.url.params.get("pageToken")
        seen.append(tok)
        n = int(tok or 0)
        return httpx2.Response(200, json={"items": [{"summary": f"Flight {n}",
                                                      "start": {"date": f"2026-10-{20 + 3 * n}"},
                                                      "end": {"date": f"2026-10-{21 + 3 * n}"}}],
                                          "nextPageToken": str(n + 1)})

    async def go_() -> dict:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            cal = GoogleCalendar(store, "id", "secret", http=http)
            store.user_doc("friend", "gcal").save({"refresh_token": "r", "access_token": "a",
                                                   "expires": 10 ** 12})
            return await cal.summary("friend", date(2026, 10, 19), days=14)
    out = asyncio.run(go_())
    assert seen == [None, "1", "2", "3"]  # capped at 4 pages
    assert len(out["travel"]) == 4

    closed: list[bool] = []

    class Client(httpx2.AsyncClient):
        async def aclose(self) -> None:
            closed.append(True)
            await super().aclose()
    monkeypatch.setattr(gcalendar.httpx2, "AsyncClient",
                        lambda **kw: Client(transport=httpx2.MockTransport(handler)))
    cal = GoogleCalendar(store, "id", "secret")
    store.user_doc("friend", "gcal").save({"refresh_token": "r"})
    asyncio.run(cal.disconnect("friend"))
    assert closed == [True]


# ------------------------------------------------------ 7. coach threads --
def test_coach_chat_never_evicts_a_conversation(env, monkeypatch) -> None:
    monkeypatch.setattr("garmin_mcp.coaches.MAX_THREADS", 3)
    chat = CoachChat(env.store)
    ts = [chat.open_thread("ath", "c@x.com", session={"id": f"s{i}", "date": "2026-10-20", "title": "T"})
          for i in range(3)]
    for t in ts[1:]:
        chat.post("ath", t["id"], sender="athlete", text="hi")
    # The empty one makes room.
    chat.open_thread("ath", "c@x.com", session={"id": "s9", "date": "2026-10-20", "title": "T"})
    for t in chat._doc("ath").load()["threads"].values():
        if not t["messages"]:
            chat.post("ath", t["id"], sender="athlete", text="hi")
    with pytest.raises(CoachError, match="Too many conversations"):
        chat.open_thread("ath", "c@x.com", session={"id": "s10", "date": "2026-10-20", "title": "T"})
    assert {t["id"] for t in ts[1:]} <= set(chat._doc("ath").load()["threads"])


# --------------------------------------------------- 10. legacy migration --
def test_legacy_migration_runs_once_under_concurrency(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    store.user_doc("friend", "conversation").save({"turns": [
        {"id": "a", "kind": "chat", "user": "hi", "assistant": "hey", "parts": []}]})
    coaches = [CoachStore(store) for _ in range(4)]
    gate = threading.Barrier(4)

    def run(c: CoachStore) -> None:
        gate.wait()
        c.migrate_legacy("friend")
    th = [threading.Thread(target=run, args=(c,)) for c in coaches]
    for t in th:
        t.start()
    for t in th:
        t.join()
    topics = [t for t in coaches[0].threads("friend") if t["kind"] == "topic"]
    assert len(topics) == 1 and store.user_doc("friend", "conversation").load() == {}


# ------------------------------------------------- 15. planner failure memo --
def test_failed_week_entries_are_pruned(env) -> None:
    agent, backend = env.agent([])
    agent.coach.create_goal("friend", {"title": "70.3"})
    agent.coach.set_plan("friend", "plan")
    now = [10_000.0]
    planner = WeekPlanner(agent, clock=lambda: now[0])
    planner._failed["stale"] = now[0] - RETRY_AFTER_FAILURE_S - 1
    backend.steps = [(["no tool"], [], "end_turn")]
    w = asyncio.run(planner.week("friend"))
    assert w["plan_status"] == "error"
    assert "stale" not in planner._failed and len(planner._failed) == 1


# ------------------------------------------------- 13. bad Content-Length --
def test_upload_with_bad_content_length_is_400(env, tmp_path) -> None:
    agent, _ = env.agent([])
    app = _app(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.post("/app/api/attachments?name=x.png", content=b"x",
                             headers={"origin": BASE, "content-length": "abc"})
            assert r.status_code == 400
    asyncio.run(go_())
