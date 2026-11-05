"""Workouts logged by hand (worklog.py): validation, the stored record, counting like a Garmin
workout (plan "done", stats) with Garmin winning a tie, exercise history, the coach's
log_workout tool, the HTTP API and the Feed card that never shows sets or weights."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp import community as cmm
from garmin_mcp.stats import StatsService
from garmin_mcp.weekplan import merge
from garmin_mcp.worklog import Worklog, WorklogError, clean, compact, dedupe, summary
from tests.test_agent import env, go, tool_block  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

TODAY = date(2026, 11, 5)
LIFT = {"sport": "strength", "date": "2026-11-05", "title": "Lower body", "minutes": 50, "rpe": 7,
        "exercises": [{"name": "Back squat", "sets": [{"reps": 5, "weight": 185}] * 3},
                      {"name": "Plank", "sets": [{"reps": "30s"}, {"reps": "30s"}]}]}


@pytest.fixture
def wl(tmp_path, fernet_key):
    from garmin_mcp.appstore import AppStore
    return Worklog(AppStore(tmp_path / "app", fernet_key), today=lambda u: TODAY, clock=lambda: 1_800_000_000.0)


def test_clean_validates_and_caps() -> None:
    f = clean(LIFT, today=TODAY)
    assert f["sport"] == "strength" and f["exercises"][0]["sets"][0] == {"reps": "5", "weight": 185, "unit": "lb"}
    assert f["exercises"][1]["sets"][0]["weight"] is None and f["time"] is None
    assert clean({"sport": "lifting"}, today=TODAY)["sport"] == "strength"
    bad = [
        {"sport": "chess"},
        {"sport": "run", "date": "2026-11-06"},  # tomorrow
        {"sport": "run", "minutes": 0},
        {"sport": "run", "rpe": 11},
        {"sport": "strength", "exercises": [{"name": "x", "sets": [{"reps": "lots"}]}]},
        {"sport": "strength", "exercises": [{"name": "x", "sets": [{"reps": 5, "weight": 5000}]}]},
        {"sport": "strength", "exercises": [{"name": f"e{i}", "sets": []} for i in range(31)]},
        {"sport": "strength", "exercises": [{"name": "x", "sets": [{"reps": 1}] * 21}]},
        {"sport": "run", "time": "25:00"},
    ]
    for b in bad:
        with pytest.raises(WorklogError):
            clean(b, today=TODAY)
    assert clean({"sport": "strength", "exercises": [{"name": "Squat", "sets": [{"reps": 5, "weight": 100}]}]},
                 today=TODAY, default_unit="kg")["exercises"][0]["sets"][0]["unit"] == "kg"


def test_crud_history_and_summary(wl) -> None:
    w = wl.add("ann", LIFT)
    assert w["key"] == f"manual:{w['id']}" and w["source"] == "manual"
    assert summary(w) == "Back squat 3 x 5 @ 185 lb; Plank 2 x 30s"
    w2 = wl.add("ann", {**LIFT, "date": "2026-11-03",
                        "exercises": [{"name": "back squat", "sets": [{"reps": 5, "weight": 175}, {"reps": 5, "weight": 180}]}]})
    h = wl.history("ann", "BACK SQUAT")
    assert [x["date"] for x in h] == ["2026-11-05", "2026-11-03"] and h[1]["line"] == "5 @ 175, 5 @ 180 lb"
    up = wl.update("ann", w["id"], {"rpe": 9, "notes": "Felt strong"})
    assert up["rpe"] == 9 and up["exercises"] == w["exercises"] and up["notes"] == "Felt strong"
    wl.delete("ann", w2["key"])
    assert [x["id"] for x in wl.all("ann")] == [w["id"]]
    with pytest.raises(WorklogError):
        wl.get("ann", w2["id"])
    assert wl.all("bob") == []  # per person
    assert wl.between("ann", TODAY - timedelta(days=1), TODAY)[0]["id"] == w["id"]


def test_counts_like_garmin_and_garmin_wins(wl) -> None:
    w = wl.add("ann", LIFT)
    row = compact(w)
    assert row["activity_id"] == w["key"] and row["sport"] == "strength_training" and row["duration"] == "50:00"
    # A planned strength session that day is done by the logged lift.
    days = merge(TODAY - timedelta(days=TODAY.weekday()), TODAY,
                 {TODAY.isoformat(): [{"id": "s1", "sport": "strength", "title": "Strength", "minutes": 45}]}, [row])
    s = next(d for d in days if d["date"] == TODAY.isoformat())["sessions"][0]
    assert s["status"] == "done" and s["activity"]["id"] == w["key"]
    # Garmin recorded a strength session that day: the untimed log steps aside (no double count).
    g = {"activity_id": 99, "date": "2026-11-05 18:00:00", "sport": "strength_training", "duration": "45:00"}
    assert dedupe([g], [row]) == []
    assert dedupe([{**g, "sport": "running"}], [row]) == [row]  # different family: both count
    timed = compact(wl.add("ann", {**LIFT, "time": "07:00"}))
    assert dedupe([g], [timed]) == [timed]  # 11 hours apart: a second session


class _Svc:
    def __init__(self, acts=None, fail=False):
        self.acts, self.fail = acts or [], fail

    def activities_between(self, uid, start, end):
        if self.fail:
            raise RuntimeError("Garmin not connected")
        return list(self.acts)


def _stats(svc, wl) -> StatsService:
    from datetime import datetime
    st = StatsService(svc, now=lambda u: datetime(2026, 11, 5, 12), athlete=lambda u: {}, plan=lambda u: None)
    st.extra = wl.compact
    return st


def test_stats_merge_and_no_garmin(wl) -> None:
    run = {"activity_id": 7, "date": "2026-11-04 07:00:00", "sport": "running", "duration": "30:00", "distance_km": 5.0}
    w = wl.add("ann", LIFT)
    _, acts = _stats(_Svc([run]), wl).activities("ann")
    assert [a["activity_id"] for a in acts] == [w["key"], 7]  # newest first
    _, only = _stats(_Svc(fail=True), wl).activities("ann")  # no Garmin: the logged ones still count
    assert [a["activity_id"] for a in only] == [w["key"]]
    with pytest.raises(RuntimeError):  # no Garmin and nothing logged: the error as before
        _stats(_Svc(fail=True), wl).activities("bob")


def test_feed_card_never_shows_sets_or_weights(wl) -> None:
    row = compact(wl.add("ann", LIFT))
    card = cmm.workout_card([row], row["activity_id"], TODAY)
    assert card is not None and card["source"] == "manual"
    blob = str(card)
    assert "sets" not in card and "reps" not in card and "185" not in blob and "Back squat" not in blob


def test_agent_log_workout_tool_and_recent(env) -> None:
    agent, backend = env.agent([
        ([], [tool_block("log_workout", {"sport": "strength", "title": "Push",
                                          "exercises": [{"name": "Bench press", "sets": [{"reps": "8", "weight": 135}] * 3}]})], "tool_use"),
        (["Logged: bench 3 x 8 @ 135 lb."], [], "end_turn"),
        ([], [tool_block("recent_activities", {"days": 3})], "tool_use"),
        (["You benched Thursday."], [], "end_turn"),
    ])
    go(agent, "friend", "yes, log it")
    logged = agent.worklog.all("friend")
    assert len(logged) == 1 and summary(logged[0]) == "Bench press 3 x 8 @ 135 lb"
    result = str(backend.calls[1][-1]["content"])
    assert "ok" in result and "Bench press" in result
    go(agent, "friend", "what did I do?")
    recent = str(backend.calls[3][-1]["content"])
    assert "Bench press 3 x 8 @ 135 lb" in recent and "manual" in recent


def test_http_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}
    today = agent._now("friend").date().isoformat()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a:
            r = await a.post("/app/api/workouts/manual", headers=h, json={**LIFT, "date": today})
            assert r.status_code == 201, r.text
            w = r.json()["item"]
            assert (await a.post("/app/api/workouts/manual", headers=h, json={"sport": "chess"})).status_code == 400
            r = await a.get("/app/api/workouts/manual")
            assert [x["id"] for x in r.json()["items"]] == [w["id"]] and r.json()["unit"] in ("lb", "kg")
            r = await a.patch(f"/app/api/workouts/manual/{w['id']}", headers=h, json={"rpe": 5})
            assert r.status_code == 200 and r.json()["item"]["rpe"] == 5
            r = await a.get("/app/api/workouts/exercise-history?name=back%20squat")
            assert r.json()["items"][0]["line"] == "3 x 5 @ 185 lb"
            r = await a.get(f"/app/api/activity/{w['key']}")
            assert r.status_code == 200, r.text
            v = r.json()
            assert v["source"] == "manual" and v["logged"]["id"] == w["id"]
            assert (await a.request("DELETE", f"/app/api/workouts/manual/{w['id']}", headers=h, json={})).status_code == 200
            assert (await a.get(f"/app/api/activity/{w['key']}")).status_code == 404
            assert (await a.request("DELETE", "/app/api/workouts/manual/0123456789", headers=h, json={})).status_code == 404
    asyncio.run(go_())
