"""Live sync, the Today card and the weekly recap."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx2
from starlette.applications import Starlette

from garmin_mcp.config import Settings
from garmin_mcp.planbuilder import build_plan, week_for
from garmin_mcp.progress import Progress, week_key, workout_xp
from garmin_mcp.providers import ReauthRequired
from garmin_mcp.providers import fake as fake_mod
from garmin_mcp.providers.fake import simulate_activity
from garmin_mcp.recap import RecapError, build as recap_build, default_week, parse_week, push_text
from garmin_mcp.stats import compute
from garmin_mcp.sync import THROTTLE_S, LiveSync
from garmin_mcp.today import recommend
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_stats import TODAY, act

BASE = "http://localhost:8001"


# ------------------------------------------------------------------ sync ---
class Fetch:
    def __init__(self) -> None:
        self.acts: list[dict[str, Any]] = []
        self.calls = 0
        self.error: Exception | None = None

    def __call__(self, user_id: str) -> list[dict[str, Any]]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.acts


def garmin_act(aid: int, name: str = "Morning Run", minutes: int = 42, km: float = 8.4, parent: int | None = None):
    a = {"activityId": aid, "activityName": name, "activityType": {"typeKey": "running"},
         "duration": minutes * 60.0, "distance": km * 1000}
    if parent:
        a["parentId"] = parent
    return a


def test_sync_baseline_throttle_and_new_activity(env) -> None:
    t = {"now": 1000.0}
    fetch, invalidated = Fetch(), []
    s = LiveSync(env.store, fetch, connected=lambda u: True, on_new=invalidated.append, clock=lambda: t["now"])
    fetch.acts = [garmin_act(100), garmin_act(99)]
    first = s.check("friend")
    assert first["changed"] is False and first["new"] == [] and "checked_at" in first  # baseline only
    assert env.store.user_doc("friend", "sync").load()["last_seen"] == 100
    # A new activity inside the throttle window: no Garmin call, cached result, no repeat toast.
    fetch.acts = [garmin_act(101, "Lunch Ride"), *fetch.acts]
    t["now"] += 10
    again = s.check("friend")
    assert fetch.calls == 1 and again["cached"] and again["changed"] is False
    # After the window: detected once, caches invalidated, multisport children left out.
    fetch.acts = [garmin_act(102, parent=101), *fetch.acts]
    t["now"] += THROTTLE_S
    got = s.check("friend")
    assert got["changed"] is True and invalidated == ["friend"]
    assert got["new"] == [{"id": 101, "name": "Lunch Ride", "sport": "run", "minutes": 42, "km": 8.4}]
    t["now"] += THROTTLE_S
    assert s.check("friend")["changed"] is False and invalidated == ["friend"]


def test_sync_errors_are_friendly(env) -> None:
    fetch = Fetch()
    s = LiveSync(env.store, fetch, connected=lambda u: u == "friend", on_new=lambda u: None, clock=lambda: 0.0)
    assert "error" in s.check("andrew") and fetch.calls == 0  # not connected: no Garmin call
    fetch.error = ReauthRequired("expired")
    out = s.check("friend")
    assert out["changed"] is False and "Reconnect" in out["error"]
    fetch.error = RuntimeError("boom")
    s2 = LiveSync(env.store, fetch, connected=lambda u: True, on_new=lambda u: None, clock=lambda: 0.0)
    assert "error" in s2.check("friend")


def test_stats_invalidate_drops_activity_cache(env) -> None:
    agent, _ = env.agent([])
    fake_mod._SIMULATED.clear()
    try:
        _, before = agent.stats.activities("friend")
        agent.stats.get("friend")
        simulate_activity()
        assert agent.stats.activities("friend")[1] is before  # still cached
        agent.stats.invalidate("friend", activities=True)
        _, after = agent.stats.activities("friend")
        assert len(after) == len(before) + 1
    finally:
        fake_mod._SIMULATED.clear()


# ----------------------------------------------------------------- today ---
D = date(2026, 10, 14)  # Wednesday


def week(today_sessions: list[dict[str, Any]], extra: list[dict[str, Any]] | None = None,
         missed: bool = False) -> list[dict[str, Any]]:
    mon = D - timedelta(days=D.weekday())
    out = []
    for i in range(7):
        d = mon + timedelta(days=i)
        ss: list[dict[str, Any]] = []
        if d == D:
            ss = today_sessions
        elif d == D - timedelta(days=1) and missed:
            ss = [{"sport": "run", "title": "Easy run", "minutes": 40, "status": "missed", "id": "m1"}]
        out.append({"date": d.isoformat(), "sessions": ss, "extra": extra if d == D else []})
    return out


INTERVALS = {"sport": "run", "title": "6x3' intervals", "minutes": 55, "kind": "vo2", "status": "planned", "id": "s1"}


def test_today_go_with_signals() -> None:
    c = recommend(today=D, days=week([INTERVALS]), has_plan=True, form=20, readiness=88,
                  streak={"current": 9, "at_risk": False, "today_done": False})
    assert c["tone"] == "go" and c["session"]["id"] == "s1"
    assert c["action"]["kind"] == "open_session"
    assert "Form +20 and readiness 88: you're fresh" in c["detail"]
    assert [s["label"] for s in c["signals"]] == ["Form", "Oura readiness", "Streak"]
    assert len(c["headline"]) <= 60 and len(c["detail"]) <= 160


def test_today_race_beats_everything() -> None:
    c = recommend(today=D, days=week([INTERVALS]), has_plan=True, form=-40,
                  adjust={"status": "suggest", "reasons": ["x"], "changes": [{}]},
                  race={"name": "Leadville 100", "days": 5})
    assert c["tone"] == "race" and c["headline"].startswith("Race week: Leadville 100 in 5 days")
    assert c["action"]["kind"] == "open_racepack"
    assert recommend(today=D, days=None, has_plan=False, race={"name": "R", "days": 0})["headline"] == "Race day: R"


def test_today_adjust_then_done_then_recovery() -> None:
    adj = {"status": "suggest", "reasons": ["You missed Long run."], "changes": [{}, {}]}
    c = recommend(today=D, days=week([INTERVALS]), has_plan=True, adjust=adj)
    assert c["tone"] == "plan" and c["action"]["kind"] == "review_adjust" and "2 changes" in c["detail"]
    done = dict(INTERVALS, status="done", activity={"name": "Track", "minutes": 52})
    c = recommend(today=D, days=week([done]), has_plan=True, form=-40, streak={"current": 4, "today_done": True})
    assert c["tone"] == "done" and "Track (52')" in c["detail"] and "4-day streak" in c["detail"]
    c = recommend(today=D, days=week([INTERVALS]), has_plan=True, form=-28, readiness=66, readiness_baseline=80)
    assert c["tone"] == "easy" and "swap 6x3' intervals for 40' easy" in c["detail"]
    assert c["detail"].startswith("Readiness 66 and form -28")
    c = recommend(today=D, days=week([INTERVALS]), has_plan=True, readiness=55)
    assert c["tone"] == "rest" and c["action"]["kind"] == "open_session"
    # Readiness that's normal for this athlete isn't flagged.
    assert recommend(today=D, days=week([INTERVALS]), has_plan=True, readiness=68,
                     readiness_baseline=70)["tone"] == "go"


def test_today_rest_day_and_no_plan() -> None:
    rest = [{"sport": "rest", "title": "Rest", "minutes": None, "status": "rest"}]
    c = recommend(today=D, days=week(rest), has_plan=True, streak={"current": 3})
    assert c["tone"] == "rest" and c["action"]["kind"] == "log_rest"
    c = recommend(today=D, days=week([]), has_plan=False, streak={"current": 6, "at_risk": True})
    assert c["tone"] == "go" and "6-day streak" in c["headline"]
    c = recommend(today=D, days=week([]), has_plan=False, form=12)
    assert c["tone"] == "go" and c["action"]["kind"] == "build_plan"
    c = recommend(today=D, days=None, has_plan=False)
    assert c["tone"] == "easy" and c["signals"] == [] and c["session"] is None
    # Missed work is not stacked onto today.
    assert "Skip making up" in recommend(today=D, days=week([INTERVALS], missed=True), has_plan=True)["detail"]


# ----------------------------------------------------------------- recap ---
def test_xp_by_week_and_badge_dates(env) -> None:
    p = Progress(env.store, clock=lambda: 0.0)
    last_week = [act(TODAY - timedelta(days=7 + i)) for i in range(3)]
    stats = compute(last_week, TODAY)
    p.update("u", acts=last_week, today=TODAY, stats=stats, plan_key=None, quests={})
    led = p.ledger("u")
    lw = week_key(TODAY - timedelta(days=7))
    assert led["xp_by_week"] == {lw: 3 * workout_xp(45)}
    assert led["badge_dates"] == {}  # back-fill: no dates for old badges
    # This week: a long workout earns XP in this week, plus a badge dated today.
    acts2 = last_week + [act(TODAY, minutes=200, aid=5)]
    p.update("u", acts=acts2, today=TODAY, stats=compute(acts2, TODAY), plan_key=None, quests={"garmin": True})
    led = p.ledger("u")
    tw = week_key(TODAY)
    assert led["xp_by_week"][tw] == workout_xp(200) + 100 + 100  # workout + long3h badge + Garmin quest
    assert led["badge_dates"]["long3h"] == TODAY.isoformat()
    # Only the last 26 weeks are kept.
    old = [act(TODAY - timedelta(weeks=w), aid=1000 + w) for w in range(30, 40)]
    p.update("u", acts=acts2 + old, today=TODAY, stats=compute(acts2 + old, TODAY), plan_key=None, quests={})
    assert len(p.ledger("u")["xp_by_week"]) <= 26


def test_recap_numbers_and_next_week() -> None:
    mon = TODAY - timedelta(days=TODAY.weekday())
    lw = mon - timedelta(days=7)
    acts = [act(lw + timedelta(days=i), minutes=30 + 10 * i, aid=500 + i) for i in range(5)]
    acts.append(act(lw + timedelta(days=1), sport="cycling", minutes=90, km=40, hour=17, aid=600))
    acts.append(act(lw - timedelta(days=1), aid=700))  # Sunday before: streak, not this week
    ledger = {"xp": 1234, "xp_by_week": {lw.isoformat(): 312}, "badge_dates": {"streak7": (lw + timedelta(days=6)).isoformat(),
                                                                                 "first": "2025-01-01"}}
    r = recap_build(start=lw, today=TODAY, acts=acts, plan=None, ledger=ledger)
    assert r["xp"] == 312 and r["workouts"] == 6 and r["active_days"] == 5
    assert r["hours"] == round((30 + 40 + 50 + 60 + 70 + 90) / 60, 1)
    assert r["best"]["minutes"] == 90 and r["best"]["sport"] == "bike"
    assert [b["id"] for b in r["badges"]] == ["streak7"]
    assert r["streak"] == 6 and r["adherence"] is None and not r["current"]
    assert r["next_week"]["sessions"] == [] and "workouts next week" in r["next_week"]["target"]
    assert r["level"]["xp"] == 1234 and r["summary"] == "6 workouts · +312 XP · 6-day streak"
    assert push_text({**r, "workouts": 0}) == "A quiet week. Tap for next week's focus."


def test_recap_with_plan_adherence_and_key_sessions() -> None:
    athlete = {"weekly_hours": 6, "level": "intermediate", "available_days": ["mon", "wed", "fri", "sat"],
               "long_day": "sat"}
    plan = build_plan(athlete, {"title": "10K", "date": (TODAY + timedelta(weeks=10)).isoformat(),
                                "distance": "10k"}, today=TODAY - timedelta(days=21))
    mon = TODAY - timedelta(days=TODAY.weekday())
    lw = mon - timedelta(days=7)
    w = week_for(plan, lw)
    assert w is not None
    day, ss = next((d, x) for d, x in sorted(w["days"].items()) if any(s["sport"] == "run" for s in x))
    acts = [act(date.fromisoformat(day), aid=1)]
    r = recap_build(start=lw, today=TODAY, acts=acts, plan=plan, ledger={})
    ad = r["adherence"]
    assert ad["done"] == 1 and ad["planned"] >= 3 and ad["phase"] == w["phase"]
    nw = r["next_week"]
    assert nw["start"] == mon.isoformat() and 2 <= len(nw["sessions"]) <= 3 and nw["target"] is None


def test_recap_week_parsing() -> None:
    assert default_week(date(2026, 10, 18)) == date(2026, 10, 12)   # Sunday: this week
    assert default_week(date(2026, 10, 19)) == date(2026, 10, 12)   # Monday: last week
    assert parse_week("2026-10-08", TODAY) == date(2026, 10, 5)
    for bad in ("2026-10-20", "2026-08-01", "nope"):
        try:
            parse_week(bad, TODAY)
            raise AssertionError(bad)
        except RecapError:
            pass


# ------------------------------------------------------------------- api ---
def test_live_api_routes(env, tmp_path) -> None:
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    auth = WebAuth(settings, env.store, "", dev_user="friend")
    app = Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    fake_mod._SIMULATED.clear()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as c:
            r = await c.get("/app/api/today")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["tone"] in {"go", "easy", "rest", "race", "done", "plan"} and body["garmin"] is True
            assert len(body["headline"]) <= 60 and len(body["signals"]) <= 3
            r = await c.get("/app/api/recap")
            assert r.status_code == 200, r.text
            assert {"xp", "workouts", "streak", "next_week", "level", "summary"} <= set(r.json())
            assert (await c.get("/app/api/recap?week=1999-01-04")).status_code == 400
            assert (await c.post("/app/api/sync", json={})).status_code == 403  # origin required
            r = await c.post("/app/api/sync", headers={"origin": BASE}, json={})
            assert r.status_code == 200 and r.json()["changed"] is False  # baseline
            s = (await c.put("/app/api/settings", headers={"origin": BASE}, json={"recap_enabled": False})).json()
            assert s["recap_enabled"] is False
    try:
        asyncio.run(go_())
    finally:
        fake_mod._SIMULATED.clear()
