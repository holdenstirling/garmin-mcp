"""Calendar insights (calinsights.py): day load, free windows, conflicts, recommendations, HTTP."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
from starlette.applications import Starlette

from garmin_mcp import calinsights as ci
from garmin_mcp.config import Settings
from garmin_mcp.gcalendar import compact_event, summarize
from garmin_mcp.planbuilder import iter_sessions
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plans import _setup

BASE = "http://localhost:8001"
T = date(2026, 10, 19)  # a Monday


def _plan(sessions: dict[str, list[dict]]) -> dict:
    days = {(T + timedelta(days=i)).isoformat(): [] for i in range(14)}
    for d, ss in sessions.items():
        days[d] = ss
    return {"weeks": [{"index": 1, "start": T.isoformat(), "phase": "base",
                       "days": {d: ss for d, ss in days.items() if d < (T + timedelta(days=7)).isoformat()}},
                      {"index": 2, "start": (T + timedelta(days=7)).isoformat(), "phase": "base",
                       "days": {d: ss for d, ss in days.items() if d >= (T + timedelta(days=7)).isoformat()}}]}


def _s(sid: str, kind: str, minutes: int = 50, sport: str = "run", **kw) -> dict:
    return {"id": sid, "sport": sport, "kind": kind, "title": f"{kind.title()} {sport}", "minutes": minutes} | kw


def test_day_load_and_free_windows() -> None:
    assert ci.day_load(30, [[600, 630]]) == "light"
    assert ci.day_load(180, [[540, 720]]) == "normal"
    assert ci.day_load(320, [[540, 860]]) == "heavy"
    assert ci.day_load(500, [[480, 980]]) == "packed"
    assert ci.day_load(150, [[450, 500], [1110, 1200]]) == "heavy"  # early and late meetings
    wins = ci.free_windows([[480, 600], [720, 780]], need=30)
    assert wins[0] == [330, 465]  # 05:30 until 15 min before the 08:00 meeting
    assert [615, 705] in wins and wins[-1] == [795, 1260]
    assert ci.free_windows([[300, 1300]], need=30) == []
    assert ci.best_slot(wins, 45) == 360  # 6:00 am
    assert ci.best_slot(wins, 45, prefer=12 * 60) == 660  # the latest start before the 1 pm meeting: nearest noon
    assert ci.best_slot([[330, 360]], 45) is None


def test_no_calendar_means_no_insights() -> None:
    plan = _plan({T.isoformat(): [_s("a", "tempo")]})
    assert ci.analyze(plan, None, T) == {"days": [], "recs": []}
    assert ci.analyze(plan, {"connected": False}, T) == {"days": [], "recs": []}


def test_recommendations_for_conflicts() -> None:
    d = lambda i: (T + timedelta(days=i)).isoformat()  # noqa: E731
    plan = _plan({
        d(1): [_s("clash", "easy", 45, time="12:00")],          # Tue: start inside a meeting
        d(3): [_s("hard", "tempo", 60)],                          # Thu: tempo on a packed day
        d(4): [_s("pack", "vo2", 50)],                            # Fri: packed, no lighter day left
        d(9): [_s("trip", "easy", 40)],                           # next Wed: during a trip
    })
    cal = {"connected": True,
           "busy": {d(1): 60, d(3): 540, d(4): 540, d(2): 30},
           "blocks": {d(1): [[690, 750]], d(3): [[450, 990]], d(4): [[450, 990]], d(2): [[600, 630]]},
           "travel": [{"start": d(8), "end": d(10), "title": "Chicago offsite", "location": ""}]}
    out = ci.analyze(plan, cal, T)
    kinds = {r["kind"]: r for r in out["recs"]}
    assert out["days"][3]["load"] == "packed" and out["days"][2]["load"] == "light"
    trav = kinds["travel"]
    assert trav["action"] == {"type": "travel", "start": d(8), "end": d(10), "name": "Chicago offsite"}
    t = next(r for r in out["recs"] if r.get("session_id") == "clash")
    assert t["kind"] == "time" and t["action"]["time"] not in ("12:00",)
    start = int(t["action"]["time"][:2]) * 60 + int(t["action"]["time"][3:])
    assert not (start < 750 + 15 and start + 45 > 690 - 15)  # the new slot is clear of the meeting
    mv = next(r for r in out["recs"] if r.get("session_id") == "hard")
    assert mv["kind"] == "move" and mv["action"]["date"] in (d(2), d(5), d(6))
    # Friday's VO2 can't go to Thu (packed) or next to Thursday's moved tempo... it either moves or eases.
    fr = next(r for r in out["recs"] if r.get("session_id") == "pack")
    assert fr["kind"] in ("move", "ease")
    assert len(out["recs"]) <= ci.MAX_RECS
    # Dismissed recommendations stay hidden; done sessions raise nothing.
    out2 = ci.analyze(plan, cal, T, dismissed={trav["id"]}, status={"clash": "done"})
    assert all(r["kind"] != "travel" for r in out2["recs"])
    assert all(r.get("session_id") != "clash" for r in out2["recs"])


def test_trip_in_travel_mode_and_long_day_hint() -> None:
    d = lambda i: (T + timedelta(days=i)).isoformat()  # noqa: E731
    plan = _plan({d(5): [_s("l1", "long", 90)], d(12): [_s("l2", "long", 100)], d(9): [_s("e", "easy", 40)]})
    plan["trips"] = [{"id": "t1", "start": d(8), "end": d(10)}]
    cal = {"connected": True, "busy": {d(5): 400, d(12): 420}, "blocks": {d(5): [[540, 940]], d(12): [[540, 960]]},
           "travel": [{"start": d(8), "end": d(10), "title": "Chicago", "location": ""}]}
    out = ci.analyze(plan, cal, T)
    assert all(r["kind"] != "travel" for r in out["recs"])  # already in travel mode
    ld = [r for r in out["recs"] if r["kind"] == "long_day"]
    assert ld and ld[0]["action"]["type"] == "long_day"
    assert ci.week_hint(out, d(7)) is not None


def test_summary_carries_busy_blocks_without_titles() -> None:
    raw = [{"summary": "1:1 with boss", "start": {"dateTime": "2026-10-19T09:00:00-06:00"},
            "end": {"dateTime": "2026-10-19T10:00:00-06:00"}},
           {"summary": "Review", "start": {"dateTime": "2026-10-19T09:30:00-06:00"},
            "end": {"dateTime": "2026-10-19T11:00:00-06:00"}}]
    s = summarize([e for e in (compact_event(x) for x in raw) if e], T, T + timedelta(days=3))
    assert s["blocks"] == {"2026-10-19": [[540, 660]]}
    assert "boss" not in str(s["blocks"])


class _Cal:
    def __init__(self, summ):
        self.summ = summ

    def connected(self, uid):
        return True

    async def summary(self, uid, today, days=42, tz=None):
        return self.summ


def test_http_insights_apply_undo_dismiss_and_coach_403(env, tmp_path) -> None:
    agent, plan, today = _setup(env, weeks=12)
    sess = [(d, s) for _, d, s in iter_sessions(plan)
            if today.isoformat() < d <= (today + timedelta(days=6)).isoformat() and s["sport"] != "rest"
            and s.get("kind") != "race"]
    d0, s0 = sess[0]
    agent.plans.update_session("friend", s0["id"], {"time": "12:00"})
    cal = {"connected": True, "busy": {d0: 60}, "blocks": {d0: [[690, 750]]}, "travel": []}
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend"})
    runner = ChatRunner(agent)

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        auth.calendar = _Cal(cal)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, runner))
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app("friend")), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app(coach_user_id("c@x.com"))), base_url=BASE) as c:
            r = (await a.get("/app/api/calendar/insights")).json()
            assert r["connected"] and len(r["days"]) == 14
            rec = next(x for x in r["recs"] if x.get("session_id") == s0["id"])
            assert rec["kind"] == "time"
            r = await a.post("/app/api/calendar/insights", headers=h, json={"action": "apply", "id": rec["id"]})
            assert r.status_code == 200, r.text
            undo = r.json()["undo"]
            moved = next(s for _, d, s in iter_sessions(agent.plans.get("friend")) if s["id"] == s0["id"])
            assert moved["time"] == rec["action"]["time"]
            # Applying again: the conflict is gone, so it no longer applies.
            r = await a.post("/app/api/calendar/insights", headers=h, json={"action": "apply", "id": rec["id"]})
            assert r.status_code == 409
            r = await a.post("/app/api/calendar/insights", headers=h, json={"action": "undo", "undo": undo})
            assert r.status_code == 200
            back = next(s for _, d, s in iter_sessions(agent.plans.get("friend")) if s["id"] == s0["id"])
            assert back["time"] == "12:00"
            r = await a.post("/app/api/calendar/insights", headers=h, json={"action": "dismiss", "id": rec["id"]})
            assert r.status_code == 200
            r = (await a.get("/app/api/calendar/insights")).json()
            assert all(x["id"] != rec["id"] for x in r["recs"])
            assert (await a.post("/app/api/calendar/insights", headers=h, json={"action": "nope"})).status_code == 400
            assert (await c.get("/app/api/calendar/insights")).status_code == 403
    asyncio.run(go_())
