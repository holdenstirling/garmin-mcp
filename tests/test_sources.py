"""Data-source preferences: Garmin vs Oura for recovery/sleep; workouts always Garmin."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import pytest

from garmin_mcp import oura as oura_mod
from garmin_mcp.adjust import _recovery_flags
from garmin_mcp.sources import (
    context_line,
    effective,
    garmin_day,
    garmin_recovery,
    prefs_for,
    recovery_for,
    resolve,
    validate,
)
from garmin_mcp.today import TodayService, recommend
from tests.test_agent import env  # noqa: F401  (fixture)


class FakeOura:
    def __init__(self, connected: bool = True, readiness: int = 73) -> None:
        self._c = connected
        self.calls = 0
        self.readiness = readiness

    def connected(self, user_id: str) -> bool:
        return self._c

    async def recovery(self, user_id: str, today: date, days: int = 28) -> dict[str, Any]:
        self.calls += 1
        rows = [{"date": (today - timedelta(days=i)).isoformat(), "readiness": self.readiness, "hrv": 50}
                for i in range(2, -1, -1)]
        return {"connected": True, "window": days, "days": rows, "latest": rows[-1],
                "baseline": {"readiness": None, "hrv": None, "resting_hr": None, "sleep_hours": None}}


# ------------------------------------------------------------ prefs --------
def test_defaults_with_and_without_oura() -> None:
    assert resolve({}, False) == {"workouts": "garmin", "recovery": "garmin", "sleep": "garmin", "show_both": False}
    assert resolve({}, True) == {"workouts": "garmin", "recovery": "oura", "sleep": "oura", "show_both": False}
    # sleep follows recovery unless set; junk falls back to defaults
    assert resolve({"data_sources": {"recovery": "garmin"}}, True)["sleep"] == "garmin"
    p = resolve({"data_sources": {"recovery": "oura", "sleep": "garmin", "show_both": True}}, True)
    assert p == {"workouts": "garmin", "recovery": "oura", "sleep": "garmin", "show_both": True}
    assert resolve({"data_sources": {"recovery": "fitbit", "show_both": "yes"}}, False) == resolve({}, False)
    # an Oura choice without Oura connected uses Garmin
    assert effective(resolve({"data_sources": {"recovery": "oura"}}, False), False) == "garmin"
    assert effective(resolve({}, True), True) == "oura"


@pytest.mark.parametrize("bad", [None, [], {}, "oura", {"recovery": "fitbit"}, {"sleep": 1},
                                 {"show_both": "true"}, {"workouts": "oura"}, {"extra": True}])
def test_validate_rejects(bad: Any) -> None:
    with pytest.raises(ValueError):
        validate(bad)


def test_validate_accepts() -> None:
    assert validate({"recovery": "oura", "sleep": "garmin", "show_both": True, "workouts": "garmin"}) == \
        {"recovery": "oura", "sleep": "garmin", "show_both": True}


def test_context_line_never_has_numbers() -> None:
    oura = context_line(resolve({}, True), True)
    assert oura.startswith("Recovery source: Oura") and "avoid quoting Garmin" in oura
    assert context_line(resolve({}, False), False).startswith("Recovery source: Garmin")
    assert context_line(resolve({"data_sources": {"recovery": "oura"}}, False), False).startswith("Recovery source: Garmin")
    assert not any(ch.isdigit() for ch in oura)


def test_context_block_has_source_line(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "Recovery source: Garmin." in ctx
    env.store.user_doc("friend", "oura").save({"refresh_token": "r", "access_token": "a"})
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "Recovery source: Oura (the athlete reads recovery in Oura" in ctx
    env.store.user_doc("friend", "profile").update(lambda p: p.update({"data_sources": {"recovery": "garmin"}}))
    assert "Recovery source: Garmin." in agent.coach.context_block("friend", agent._now("friend"), None)


def test_oura_scopes_include_workout_for_display_only_imports() -> None:
    # workouts.py imports Oura workouts Garmin missed, display-only (tests/test_workouts.py).
    assert oura_mod.SCOPES.split() == ["personal", "daily", "heartrate", "workout"]


# ------------------------------------------------------------ Garmin reads --
def test_garmin_day_parsing() -> None:
    row = garmin_day([{"calendarDate": "2026-10-14", "score": 94, "sleepScore": 80, "hrvWeeklyAverage": 60}],
                     {"dailySleepDTO": {"sleepTimeSeconds": 27000, "sleepScores": {"overall": {"value": 82}}},
                      "restingHeartRate": 48, "avgOvernightHrv": 61}, "2026-10-14")
    assert row == {"date": "2026-10-14", "readiness": 94, "sleep_score": 82, "hrv_week": 60,
                   "sleep_hours": 7.5, "hrv": 61, "resting_hr": 48}
    assert garmin_day(None, None, "2026-10-14") == {"date": "2026-10-14"}


def test_garmin_recovery_from_service() -> None:
    class Svc:
        def execute(self, user_id: str, method: str, args: dict) -> dict:
            if user_id != "friend":
                raise RuntimeError("Garmin not connected")
            if method == "get_training_readiness":
                return {"result": [{"calendarDate": args["cdate"], "score": 80}]}
            return {"result": {"dailySleepDTO": {"sleepTimeSeconds": 27000}, "restingHeartRate": 50}}
    today = date(2026, 10, 14)
    rec = garmin_recovery(Svc(), "friend", today)
    assert rec and rec["source"] == "garmin" and len(rec["days"]) == 3
    assert rec["latest"]["date"] == "2026-10-14" and rec["latest"]["readiness"] == 80
    assert garmin_recovery(Svc(), "holden", today) is None  # Garmin not connected


# ------------------------------------------------------------ selection ----
def test_recovery_for_follows_choice(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    today = date(2026, 10, 14)
    o = FakeOura()
    rec, src = asyncio.run(recovery_for(agent, o, "friend", today))
    assert src == "oura" and rec and rec["source"] == "oura" and o.calls == 1
    env.store.user_doc("friend", "profile").update(lambda p: p.update({"data_sources": {"recovery": "garmin"}}))
    rec, src = asyncio.run(recovery_for(agent, o, "friend", today))
    assert src == "garmin" and rec and rec["source"] == "garmin" and o.calls == 1
    # chose Oura but it isn't connected -> Garmin
    env.store.user_doc("friend", "profile").update(lambda p: p.update({"data_sources": {"recovery": "oura"}}))
    _, src = asyncio.run(recovery_for(agent, FakeOura(connected=False), "friend", today))
    assert src == "garmin"


def test_today_labels_source(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    o = FakeOura(readiness=73)
    card = asyncio.run(TodayService(agent, o).get("friend"))
    assert card["recovery_source"] == "oura"
    labels = [s["label"] for s in card["signals"]]
    assert "Oura readiness" in labels and "Garmin readiness" not in labels
    assert next(s for s in card["signals"] if s["label"] == "Oura readiness")["value"] == "73"
    env.store.user_doc("friend", "profile").update(lambda p: p.update({"data_sources": {"recovery": "garmin"}}))
    card = asyncio.run(TodayService(agent, o).get("friend"))
    assert card["recovery_source"] == "garmin"
    labels = [s["label"] for s in card["signals"]]
    assert "Oura readiness" not in labels and "Garmin readiness" in labels
    # no Oura client at all
    assert asyncio.run(TodayService(agent, None).get("friend"))["recovery_source"] == "garmin"


def test_recommend_signal_label() -> None:
    c = recommend(today=date(2026, 10, 14), days=None, has_plan=False, readiness=94, readiness_source="garmin")
    assert [s["label"] for s in c["signals"]] == ["Garmin readiness"]
    c = recommend(today=date(2026, 10, 14), days=None, has_plan=False, readiness=73)
    assert [s["label"] for s in c["signals"]] == ["Oura readiness"]


def test_adjust_uses_chosen_source_label() -> None:
    days = [{"date": f"2026-10-1{i}", "readiness": 60} for i in range(3)]
    reasons, _ = _recovery_flags({"source": "garmin", "days": days, "baseline": {}}, None)
    assert reasons[0].startswith("Garmin readiness has been low")
    reasons, _ = _recovery_flags({"source": "oura", "days": days, "baseline": {}}, None)
    assert reasons[0].startswith("Oura readiness has been low")


def test_proposal_reads_chosen_source(env, monkeypatch, tmp_path) -> None:  # noqa: F811
    """/plan/adjust: with recovery=garmin the Oura client is never read."""
    from garmin_mcp import webapp
    seen: list[str] = []

    async def fake_for(agent, oura, user_id, today):
        seen.append(user_id)
        return None, "garmin"
    monkeypatch.setattr(webapp, "recovery_for", fake_for)
    from tests.test_plans import _setup
    _setup(env)
    o = FakeOura()
    app, _ = _app(env, tmp_path, o)

    async def go_() -> None:
        import httpx2
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8001") as c:
            r = await c.get("/app/api/plan/adjust")
            assert r.status_code == 200, r.text
    asyncio.run(go_())
    assert seen == ["friend"] and o.calls == 0  # through recovery_for, never straight to Oura


# ------------------------------------------------------------ settings API --
def _app(env, tmp_path, oura: Any = None):  # noqa: F811
    from starlette.applications import Starlette

    from garmin_mcp.config import Settings
    from garmin_mcp.webapp import build_app_routes
    from garmin_mcp.webauth import WebAuth
    from garmin_mcp.webchat import ChatRunner
    agent, _ = env.agent([])
    settings = Settings(public_base_url="http://localhost:8001", data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    auth.oura = oura
    return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent))), agent


def test_settings_api_and_asked_flag(env, tmp_path) -> None:  # noqa: F811
    import httpx2
    app, _ = _app(env, tmp_path, FakeOura())
    hdr = {"content-type": "application/json", "origin": "http://localhost:8001"}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8001") as c:
            s = (await c.get("/app/api/me")).json()["settings"]
            assert s["data_sources"] == {"workouts": "garmin", "recovery": "oura", "sleep": "oura", "show_both": False}
            assert s["data_sources_asked"] is False
            r = await c.put("/app/api/settings", json={"data_sources": {"recovery": "fitbit"}}, headers=hdr)
            assert r.status_code == 400
            r = await c.put("/app/api/settings", json={"data_sources": {"workouts": "oura"}}, headers=hdr)
            assert r.status_code == 400 and "Garmin" in r.json()["error"]
            r = await c.put("/app/api/settings", json={"data_sources_asked": "yes"}, headers=hdr)
            assert r.status_code == 400
            r = await c.put("/app/api/settings", json={"data_sources": {"recovery": "garmin", "show_both": True},
                                                       "data_sources_asked": True}, headers=hdr)
            assert r.status_code == 200, r.text
            s = r.json()
            assert s["data_sources"] == {"workouts": "garmin", "recovery": "garmin", "sleep": "garmin", "show_both": True}
            assert s["data_sources_asked"] is True
            # partial patch keeps the rest
            s = (await c.put("/app/api/settings", json={"data_sources": {"sleep": "oura"}}, headers=hdr)).json()
            assert s["data_sources"]["recovery"] == "garmin" and s["data_sources"]["sleep"] == "oura"
            assert s["data_sources"]["show_both"] is True
            rec = (await c.get("/app/api/recovery")).json()
            assert rec["sources"]["show_both"] is True and rec["oura"] and rec["garmin"]
    asyncio.run(go_())
    prefs, connected = prefs_for(env.store, "friend", True)
    assert connected and prefs["recovery"] == "garmin"
