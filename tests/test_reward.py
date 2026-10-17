"""Post-workout reward + monthly recap (reward.py). Clock-independent: dates are relative
to a fixed day or to the agent's own "today"."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
from starlette.applications import Starlette

from garmin_mcp import reward as rw
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.moments import Moments
from garmin_mcp.coaching import CoachStore
from garmin_mcp.progress import level_floor
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
TZ = ZoneInfo("America/Denver")
DAY = date(2026, 10, 14)


def act(aid: int, day: date, *, sport: str = "running", minutes: float = 50, km: float = 10.0,
        climb: float = 0, split5: float | None = None, split10: float | None = None, te: float | None = None,
        name: str = "Morning Run") -> dict[str, Any]:
    """A compact activity (tools.compact_activity shape)."""
    m = int(minutes)
    a: dict[str, Any] = {"activity_id": aid, "date": f"{day.isoformat()} 07:00:00", "name": name, "sport": sport,
                         "duration": f"{m // 60}:{m % 60:02d}:00" if m >= 60 else f"{m}:00", "distance_km": km,
                         "elevation_gain_m": climb}
    if split5 is not None:
        a["fastest_5k_s"] = split5
    if split10 is not None:
        a["fastest_10k_s"] = split10
    if te is not None:
        a["aerobic_te"] = te
    return a


def head(me: dict[str, Any], hist: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return rw.pick_headline(me, hist + [me], imperial=kw.pop("imperial", False), **kw)


# ------------------------------------------------------------- insights ---
def test_fastest_5k_since_last_as_fast() -> None:
    hist = [act(1, DAY - timedelta(weeks=6), split5=1440),       # as fast, 6 weeks ago
            act(2, DAY - timedelta(weeks=3), split5=1500),       # slower since
            act(3, DAY - timedelta(weeks=10), split5=1400)]      # faster, longer ago
    h = head(act(9, DAY, split5=1452), hist)
    assert h == {"kind": "split_5k", "text": "Fastest 5K in 6 weeks: 24:12", "value": "24:12", "weeks": 6}
    assert head(act(9, DAY, split5=1439), hist)["text"] == "Fastest 5K in 10 weeks: 23:59"
    # The split record outranks a same-age distance record (priority order).
    h = head(act(9, DAY, split5=1439, km=13), hist + [act(4, DAY - timedelta(weeks=10), km=14)])
    assert h["kind"] == "split_5k"


def test_ties_and_recent_equals_are_not_records() -> None:
    hist = [act(1, DAY - timedelta(weeks=2), split5=1452, km=10.0), act(2, DAY - timedelta(weeks=20), km=5)]
    h = head(act(9, DAY, split5=1452, km=10.0), hist)   # equal 5K two weeks ago, equal distance too
    assert h["kind"] not in ("split_5k", "distance")
    # A same-day equal never makes a record either.
    h = head(act(9, DAY, km=12.0), [act(1, DAY, km=12.0), act(2, DAY - timedelta(weeks=9), km=6)])
    assert h["kind"] != "distance"


def test_year_and_on_record_scope_and_ranking() -> None:
    old = [act(1, DAY - timedelta(days=320), km=8), act(2, DAY - timedelta(weeks=5), km=9, climb=400)]
    h = head(act(9, DAY, km=15, climb=300), old)
    assert h["text"] == "Longest run in 12 months: 15.0 km"
    # Short history: "on record" needs at least two earlier ones.
    h = head(act(9, DAY, km=15), [act(1, DAY - timedelta(weeks=6), km=8)])
    assert h["kind"] != "distance"
    h = head(act(9, DAY, km=15), [act(1, DAY - timedelta(weeks=6), km=8), act(2, DAY - timedelta(weeks=5), km=9)])
    assert h["text"] == "Longest run on record: 15.0 km"
    # Longer "since" wins; at equal rank the order is split > distance > climb > duration > effect.
    recs = rw.records(rw._row(act(9, DAY, km=11, climb=500, minutes=70)),
                      [rw._row(a) for a in [act(1, DAY - timedelta(weeks=5), km=12, climb=100, minutes=60),
                                            act(2, DAY - timedelta(weeks=8), km=13, climb=600, minutes=80),
                                            act(3, DAY - timedelta(weeks=30), km=20, climb=50, minutes=200)]],
                      imperial=False)
    assert [(r["kind"], r["weeks"]) for r in recs] == [("climb", 8), ("duration", 8), ("distance", 5)]


def test_ride_units_and_effect() -> None:
    hist = [act(1, DAY - timedelta(weeks=7), sport="cycling", km=60), act(2, DAY - timedelta(weeks=12), sport="cycling", km=80)]
    h = head(act(9, DAY, sport="cycling", km=70.0), hist, imperial=True)
    assert h["text"] == "Longest ride in 12 weeks: 43.5 mi"
    h = head(act(9, DAY, km=5, te=4.6), [act(1, DAY - timedelta(weeks=9), km=6, te=4.6), act(2, DAY - timedelta(weeks=2), km=6, te=3.0)])
    assert h["text"] == "Biggest training effect in 9 weeks: 4.6"


def test_fallbacks_streak_ring_nailed_and_no_data() -> None:
    first = act(9, DAY, km=5)
    assert head(first, [], streak={"current": 14, "today_done": True})["text"] == "14-day streak! A new milestone"
    assert head(first, [], streak={"current": 13})["kind"] == "logged"
    ring = {"kind": "plan", "done": 4, "target": 4, "label": "sessions"}
    assert head(first, [], ring=ring)["text"] == "Week closed: 4 of 4 planned sessions"
    assert head(first, [], verdict="nailed", planned_title="Tempo 3x10")["text"] == "Nailed it: Tempo 3x10, right on target"
    assert head(first, [])["text"] == "Logged: Morning Run"
    # No usable data at all.
    bare = {"activity_id": 5, "date": "", "name": None}
    assert rw.pick_headline(bare, [], imperial=False) == {"kind": "logged", "text": "Logged: Workout", "value": None}
    assert rw.chips(bare, imperial=False) == []
    assert [c["label"] for c in rw.chips(act(9, DAY, km=10, minutes=50), imperial=False)] == ["Distance", "Time", "Pace"]
    assert rw.chips(act(9, DAY, km=10, minutes=50), imperial=False)[2]["value"] == "5:00 /km"
    assert rw.chips(act(9, DAY, sport="strength_training", km=0, minutes=40), imperial=False) == [{"label": "Time", "value": "40:00"}]


def test_build_reward_xp_and_level() -> None:
    me = act(9, DAY, minutes=60)
    r = rw.build_reward(me, [me], today=DAY, imperial=False, streak={"current": 3}, ring=None, verdict="nailed",
                        planned_title="Easy", session_id="s1", plan_xp=15, ledger_xp=level_floor(3) - 20,
                        counted=False, created=1)
    assert r["xp"] == {"gained": 55, "workout": 40, "plan": 15}
    assert r["level"]["before"]["level"] == 2 and r["level"]["after"]["level"] == 3 and r["level"]["level_up"]
    assert r["headline"]["kind"] == "nailed" and r["session_id"] == "s1" and r["streak"] == 3
    assert "name" in r and "avg_hr" not in str(r)
    # Already in the ledger: the bar ends at the ledger total.
    r = rw.build_reward(me, [me], today=DAY, imperial=False, streak=None, ring=None, verdict=None, planned_title=None,
                        session_id=None, plan_xp=0, ledger_xp=500, counted=True, created=1)
    assert r["level"]["after"]["xp"] == 500 and r["level"]["before"]["xp"] == 460


def test_ring_closed_only_by_this_week_and_exactly() -> None:
    stats = {"plan": None, "totals": {"week": {"workouts": 3}}}
    assert rw.ring_closed(stats, DAY, DAY, False)["done"] == 3
    assert rw.ring_closed(stats, DAY - timedelta(days=9), DAY, False) is None
    assert rw.ring_closed({"plan": None, "totals": {"week": {"workouts": 4}}}, DAY, DAY, False) is None
    plan = {"plan": {"week": {"planned": 4, "done": 4}}, "totals": {"week": {"workouts": 5}}}
    assert rw.ring_closed(plan, DAY, DAY, True)["kind"] == "plan"
    assert rw.ring_closed(plan, DAY, DAY, False) is None


# -------------------------------------------------------- once per workout --
def _rewards(tmp_path: Path, fernet_key: str, today: date = DAY) -> tuple[rw.Rewards, AppStore, list[int]]:
    store = AppStore(tmp_path / "app", fernet_key)
    calls: list[int] = []
    hist = {7: act(7, today - timedelta(days=5)), 8: act(8, today - timedelta(days=1)), 9: act(9, today, km=12)}

    def ctx(uid: str, aid: int) -> dict[str, Any] | None:
        calls.append(aid)
        if aid not in hist:
            return None
        return {"act": hist[aid], "acts": list(hist.values()), "today": today, "imperial": False, "streak": {"current": 2},
                "ring": None, "verdict": "bonus", "planned_title": None, "session_id": None, "plan_xp": 0}
    return rw.Rewards(store, now=lambda u: datetime.combine(today, datetime.min.time(), TZ), context=ctx,
                      clock=lambda: 1000.0), store, calls


def raw(aid: int, **kw: Any) -> dict[str, Any]:
    return {"activityId": aid, **kw}


def test_reward_once_per_workout_and_dismiss_persists(tmp_path, fernet_key) -> None:
    r, store, calls = _rewards(tmp_path, fernet_key)
    assert r.pending("friend") is None
    assert r.on_workouts("friend", [raw(8), raw(9), raw(10, parentId=9)])["activity_id"] == 9  # newest, legs skipped
    assert r.on_workouts("friend", [raw(9)]) is None and calls == [9]  # built once
    assert r.pending("friend")["activity_id"] == 9
    assert r.on_workouts("friend", [raw(8)])["activity_id"] == 8
    assert r.pending("friend")["activity_id"] == 9  # newest unseen first
    assert r.claim_push("friend") == ("Longest run on record: 12.0 km", "/app/?open=reward&activity=9")
    assert r.claim_push("friend") is None  # once per activity
    r.seen("friend", 9)
    assert r.pending("friend") is None  # 9 and the older 8 are both done
    assert r.get("friend", 9)["seen"] is True and r.get("friend", 123) is None
    # Persisted: a fresh service on the same store agrees, and a re-sync never rebuilds it.
    r2 = rw.Rewards(store, now=lambda u: datetime.combine(DAY, datetime.min.time(), TZ), context=lambda u, a: None)
    assert r2.pending("friend") is None and r2.on_workouts("friend", [raw(9)]) is None
    assert r.on_workouts("coach_x", [raw(9)]) is None


def test_old_rewards_do_not_pop_up(tmp_path, fernet_key) -> None:
    r, _store, _ = _rewards(tmp_path, fernet_key)
    assert r.on_workouts("friend", [raw(7)])["activity_id"] == 7  # 5 days old
    assert r.pending("friend") is None and r.get("friend", 7)["seen"] is False
    assert r.claim_push("friend") is None


def test_moments_hand_fresh_workouts_to_reward_hook(env) -> None:
    clock_at = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    coach = CoachStore(env.store, clock=lambda: clock_at.timestamp())
    m = Moments(env.store, coach, now=lambda u: clock_at, clock=lambda: clock_at.timestamp())
    got: list[tuple[str, list[int]]] = []
    m.on_workouts = lambda uid, acts: got.append((uid, [a["activityId"] for a in acts]))
    g = {"activityName": "Run", "activityType": {"typeKey": "running"}, "duration": 1800, "distance": 5000}
    m.workouts("friend", [{"activityId": 5, "startTimeLocal": "2026-10-14 07:00:00", **g},
                          {"activityId": 4, "startTimeLocal": "2026-10-01 07:00:00", **g}], ai_note=False)
    assert got == [("friend", [5])]
    m.on_workouts = lambda uid, acts: 1 / 0  # a broken hook never breaks the moment
    m.workouts("friend", [{"activityId": 6, "startTimeLocal": "2026-10-14 08:00:00", **g}], ai_note=False)


# ------------------------------------------------------------ month recap --
def test_month_recap_totals_and_weeks() -> None:
    sep = date(2026, 9, 1)
    acts = [act(1, date(2026, 8, 31), minutes=600),                        # August: out
            act(2, date(2026, 9, 1), minutes=60), act(3, date(2026, 9, 2), minutes=30),
            act(4, date(2026, 9, 3), sport="cycling", minutes=150, km=60),
            act(5, date(2026, 9, 20), sport="cycling", minutes=90, km=40, name="Ride past my house"),
            act(6, date(2026, 10, 1), minutes=45)]                         # October: out
    rec = rw.month_recap(acts, sep, DAY, imperial=False, top_club="Trail Hares")
    assert rec["month"] == "2026-09" and rec["label"] == "September" and not rec["partial"]
    assert rec["hours"] == 5.5 and rec["sessions"] == 4 and rec["active_days"] == 4
    assert rec["longest"] == {"sport": "bike", "minutes": 150}  # sport + time only, never the name
    assert rec["best_streak"] == 3 and rec["top_sport"] == {"sport": "bike", "hours": 4.0}
    assert rec["top_club"] == "Trail Hares"
    assert [w["start"] for w in rec["weeks"]] == ["2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
    assert [w["hours"] for w in rec["weeks"]] == [4.0, 0.0, 1.5, 0.0, 0.0]  # Aug 31 itself doesn't count
    assert "Ride past" not in str(rec)
    empty = rw.month_recap([], sep, DAY, imperial=False)
    assert empty["sessions"] == 0 and empty["longest"] is None and empty["top_sport"] is None and empty["best_streak"] == 0
    assert rw.month_recap(acts, date(2026, 10, 1), DAY, imperial=False)["partial"] is True


def test_parse_month_bounds() -> None:
    assert rw.parse_month(None, DAY) == date(2026, 9, 1)
    assert rw.parse_month(None, date(2026, 1, 3)) == date(2025, 12, 1)
    assert rw.parse_month("2026-10", DAY) == date(2026, 10, 1)
    assert rw.parse_month("2025-10", DAY) == date(2025, 10, 1)
    for bad in ("2025-09", "2026-11", "2026-13", "x"):
        try:
            rw.parse_month(bad, DAY)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_month_moment_on_the_first_once(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    at = {"d": date(2026, 10, 1)}
    r = rw.Rewards(store, now=lambda u: datetime.combine(at["d"], datetime.min.time(), TZ), context=lambda u, a: None)
    posted: list[dict[str, Any]] = []
    sept = [act(1, date(2026, 9, 5), minutes=90), act(2, date(2026, 9, 6), minutes=30)]

    def post(uid: str, m: dict[str, Any]) -> str:
        posted.append(m)
        return "posted"
    acts = lambda u: (at["d"], sept)  # noqa: E731
    assert r.check_month("friend", acts=acts, post=post) == "posted"
    assert posted[0]["key"] == "month:2026-09" and posted[0]["type"] == "month"
    assert posted[0]["text"].startswith("📅 Your September: 2 sessions, 2 hours.")
    assert posted[0]["actions"] == [{"id": "month_recap", "label": "See your September", "month": "2026-09"}]
    at["d"] = date(2026, 10, 2)
    assert r.check_month("friend", acts=acts, post=post) == "skipped" and len(posted) == 1
    at["d"] = date(2026, 11, 5)  # too late in the month
    assert r.check_month("friend", acts=acts, post=post) == "skipped"
    at["d"] = date(2026, 11, 1)  # October had nothing
    assert r.check_month("friend", acts=acts, post=post) == "empty" and len(posted) == 1
    assert r.check_month("coach_x", acts=acts, post=post) == "skipped"


def test_top_club_by_posts_then_name(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)

    class Clubs:
        def ids_of(self, uid: str) -> list[str]:
            return ["c1", "c2", "r-race"]

        def name_of(self, cid: str, uid: str) -> str:
            return {"c1": "Zeta Runners", "c2": "Alpha Riders"}[cid]
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    assert rw.top_club_of(store, Clubs(), "friend", start, end) == "Alpha Riders"
    ts = datetime(2026, 9, 10).timestamp()
    store.user_doc("friend", "posts").update(lambda d: d.setdefault("posts", {}).update(
        {"p1": {"audience": "club:c1", "created": ts}, "p2": {"audience": "club:c1", "created": ts},
         "p3": {"audience": "club:c2", "created": datetime(2026, 8, 10).timestamp()}}))
    assert rw.top_club_of(store, Clubs(), "friend", start, end) == "Zeta Runners"


# ------------------------------------------------------------------ API ---
def test_api_shapes_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    acts = [act(101, today - timedelta(weeks=8), km=14), act(102, today - timedelta(weeks=2), km=9),
            act(103, today, km=16, minutes=80)]
    agent.stats.activities = lambda uid, fresh=False: (today, acts)  # type: ignore[method-assign]
    agent.coach.update_athlete("friend", {"units": "metric"})  # the headline below is in km
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
            r = await a.get("/app/api/reward")
            assert r.status_code == 200, r.text
            assert r.json() == {"reward": None}
            # A sync hands the new workout to Moments -> the reward hook (wired by the app).
            agent.moments.workouts("friend", [{"activityId": 103, "activityName": "Morning Run",
                                               "activityType": {"typeKey": "running"}, "duration": 4800,
                                               "distance": 16000, "startTimeLocal": f"{today.isoformat()} 07:00:00"}])
            rew = (await a.get("/app/api/reward")).json()["reward"]
            assert rew["activity_id"] == 103 and rew["headline"]["text"] == "Longest run on record: 16.0 km"
            assert set(rew) >= {"headline", "chips", "xp", "level", "streak", "verdict", "session_id", "date"}
            assert 2 <= len(rew["chips"]) <= 3 and set(rew["level"]) == {"before", "after", "level_up"}
            one = (await a.get("/app/api/reward?activity_id=103")).json()["reward"]
            assert one["activity_id"] == 103 and one["seen"] is False
            assert (await a.get("/app/api/reward?activity_id=abc")).status_code == 400
            assert (await a.post("/app/api/reward/103/seen", headers=h, json={})).json() == {"ok": True}
            assert (await a.get("/app/api/reward")).json() == {"reward": None}
            assert (await a.get("/app/api/reward?activity_id=103")).json()["reward"]["seen"] is True
            m = await a.get("/app/api/recap/month")
            assert m.status_code == 200, m.text
            body = m.json()
            assert set(body) >= {"month", "label", "hours", "sessions", "longest", "best_streak", "top_sport",
                                 "top_club", "weeks"}
            assert (await a.get("/app/api/recap/month?month=1999-01")).status_code == 400
            # Coach accounts: athlete-only routes.
            assert (await c.get("/app/api/reward")).status_code == 403
            assert (await c.post("/app/api/reward/103/seen", headers=h, json={})).status_code == 403
            assert (await c.get("/app/api/recap/month")).status_code == 403
    asyncio.run(go())
    # The workout note's push takes the headline once (proactive.AgentDelivery).
    assert agent.rewards.claim_push("friend") is None  # already seen


def test_workout_note_push_uses_headline(env) -> None:
    from garmin_mcp import proactive as pr

    sent: list[tuple] = []

    class Push:
        def send(self, uid: str, title: str, body: str, url: str = "/app/") -> None:
            sent.append((title, url))

    class Rewards:
        def __init__(self) -> None:
            self.n = 0

        def claim_push(self, uid: str) -> tuple[str, str] | None:
            self.n += 1
            return ("Fastest 5K in 6 weeks: 24:12", "/app/?open=reward&activity=9") if self.n == 1 else None

    class Turn:
        async def wait(self) -> dict[str, Any]:
            return {"assistant": "Great tempo today."}

    class Agent:
        rewards = Rewards()
        coach = type("C", (), {"coach_thread": staticmethod(lambda uid: {"id": "t"})})()
        planner = type("P", (), {"ensure": staticmethod(lambda uid: asyncio.sleep(0))})()

    class Runner:
        agent = Agent()

        def start(self, *a: Any, **k: Any) -> Turn:
            return Turn()

    loop = asyncio.new_event_loop()
    import threading
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        d = pr.AgentDelivery(Runner(), Push(), lambda: loop)  # type: ignore[arg-type]
        d("friend", "workout", "x")
        d("friend", "workout", "x")
        d("friend", "brief", "x")
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(2)
    assert sent == [("Fastest 5K in 6 weeks: 24:12", "/app/?open=reward&activity=9"),
                    ("Rabbit", "/app/?open=coach"), ("Morning brief", "/app/?open=coach")]
