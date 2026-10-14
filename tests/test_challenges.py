"""Weekly/monthly challenges: target scaling, periods in the athlete's zone, progress per
metric, join limits, XP idempotency, friend invites and coach access."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import challenges as ch
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.progress import Progress
from garmin_mcp.recap import build as recap_build, push_text
from garmin_mcp.social import Social
from garmin_mcp.stats import _rows
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

TODAY = date(2026, 10, 14)  # a Wednesday
BASE = "http://localhost:8001"
H = {"origin": BASE}
ALLOW = {"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat"}


def act(d: date, aid: int, *, sport="running", minutes=45, km=8.0, climb=100, hour=8):
    h, m = divmod(minutes, 60)
    return {"activity_id": aid, "date": f"{d.isoformat()} {hour:02d}:15:00", "name": f"Act {aid}", "sport": sport,
            "duration": f"{h}:{m:02d}:00", "distance_km": km, "elevation_gain_m": climb}


def history(today: date = TODAY, per_week: int = 4) -> list[dict]:
    """Six steady baseline weeks: ``per_week`` 45' runs (8 km, 100 m) a week."""
    out, aid = [], 1000
    monday = today - timedelta(days=today.weekday())
    for w in range(1, 7):
        for i in range(per_week):
            out.append(act(monday - timedelta(weeks=w) + timedelta(days=i), aid))
            aid += 1
    return out


# ------------------------------------------------------------------ periods --
def test_period_bounds_week_and_month() -> None:
    assert ch.period_bounds("week", TODAY) == (date(2026, 10, 12), date(2026, 10, 18))
    assert ch.period_bounds("week", date(2026, 10, 18)) == (date(2026, 10, 12), date(2026, 10, 18))
    assert ch.period_bounds("month", TODAY) == (date(2026, 10, 1), date(2026, 10, 31))
    assert ch.period_bounds("month", date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
    with pytest.raises(ch.ChallengeError):
        ch.period_bounds("year", TODAY)


def test_period_boundaries_follow_the_athletes_zone() -> None:
    # Monday 03:00 UTC is still Sunday evening in Denver: last week's challenge is current.
    utc = datetime(2026, 10, 19, 3, 0, tzinfo=ZoneInfo("UTC"))
    denver = ch.local_today(utc.astimezone(ZoneInfo("America/Denver")))
    assert denver == date(2026, 10, 18)
    assert ch.period_bounds("week", denver)[0] == date(2026, 10, 12)
    assert ch.period_bounds("week", ch.local_today(utc))[0] == date(2026, 10, 19)
    # Nov 1 01:00 UTC is still October in Denver.
    utc = datetime(2026, 11, 1, 1, 0, tzinfo=ZoneInfo("UTC"))
    assert ch.period_bounds("month", ch.local_today(utc.astimezone(ZoneInfo("America/Denver"))))[0] == date(2026, 10, 1)


# ------------------------------------------------------------------ targets --
def test_target_scaling_stretch_but_achievable() -> None:
    rows = _rows(history())
    assert ch.baseline("workouts", "week", rows, TODAY) == 4
    assert ch.scale_target("workouts", "week", 4, 1.1) == 5          # always above baseline
    assert ch.scale_target("workouts", "week", 4, 1.25) == 5
    assert ch.scale_target("minutes", "week", 180, 1.25) == 225      # 15-min steps
    assert ch.scale_target("minutes", "week", 181, 1.1) == 210
    assert ch.scale_target("climb_m", "week", 1210, 1.25) == 1600     # 100 m steps
    assert ch.scale_target("distance_km", "week", 32, 1.25) == 40
    assert ch.scale_target("distance_km", "week", 8, 1.1) == 9       # 1 km steps when small
    assert ch.scale_target("active_days", "week", 7, 1.25) == 7       # caps
    assert ch.scale_target("workouts", "week", 0, 1.25) == 2          # starter floor
    assert ch.scale_target("long_session", "week", 120, 1.25) == 150  # +15% (138), then 15-min steps
    assert ch.scale_target("sports_variety", "month", 2, 1.15) == 3
    assert ch.scale_target("plan_adherence", "week", 0, 1.1) == 90
    # Monthly additive targets scale the weekly median by the month's days.
    base_m = ch.baseline("workouts", "month", rows, TODAY)
    assert round(base_m, 1) == round(4 * 31 / 7, 1)
    assert ch.scale_target("workouts", "month", base_m, 1.1) == 20
    # Everest month when the monthly climb lands near 8,848 m.
    big = [act(TODAY - timedelta(days=d), 5000 + d, climb=250) for d in range(3, 50)]
    s = ch.suggest("month", TODAY, _rows(big), athlete={"interests": ["mountains"]})
    climb = [x for x in s["items"] if x["metric"] == "climb_m"]
    assert climb and climb[0]["target"] == ch.EVEREST_M and climb[0]["name"] == "Everest month"


def test_suggestions_easy_stretch_fun_and_personalized() -> None:
    rows = _rows(history())
    s = ch.suggest("week", TODAY, rows, athlete={"favorite_sports": ["run"]})
    kinds = [x["kind"] for x in s["items"]]
    assert kinds == ["easy", "stretch", "fun"] and s["notice"] is None
    assert all(x["why"] == "Based on your last 6 weeks" or x["metric"] == "plan_adherence" or x["baseline"] == 0
               or x["why"] == "A starter target" for x in s["items"])
    assert all(x["xp"] == 75 for x in s["items"])
    # Interests steer the fun pick; distance follows the favorite sport.
    s2 = ch.suggest("week", TODAY, rows, athlete={"interests": ["strength training"], "favorite_sports": ["run"]})
    assert next(x for x in s2["items"] if x["kind"] == "fun")["metric"] == "strength_sessions"
    for wk in range(4):  # rotation still only picks from eligible pools
        d = TODAY + timedelta(weeks=wk)
        s3 = ch.suggest("week", d, _rows(history(d)), athlete={"favorite_sports": ["run"]})
        dist = [x for x in s3["items"] if x["metric"] == "distance_km"]
        assert all(x["sport"] == "run" and x["name"] == "Run week" for x in dist)
    # No history: starter targets.
    s4 = ch.suggest("week", TODAY, [], athlete={})
    assert s4["items"] and all(x["why"] == "A starter target" for x in s4["items"])


def test_calm_mode_pain_and_taper_skip_volume() -> None:
    rows = _rows(history())
    s = ch.suggest("week", TODAY, rows, pain=True)
    assert s["items"] == [] and "hurt" in s["notice"]
    plan = {"weeks": [{"start": "2026-10-12", "phase": "taper", "days": {"2026-10-13": [
        {"sport": "run", "title": "Easy run", "minutes": 30}]}}]}
    s = ch.suggest("week", TODAY, rows, plan=plan)
    assert {x["metric"] for x in s["items"]} <= {"plan_adherence", "strength_sessions"}
    assert s["items"][0]["name"] == "Stick to the taper" and "taper" in s["notice"].lower()
    s = ch.suggest("month", TODAY, rows, race_soon=True)
    assert all(x["metric"] not in ch.VOLUME for x in s["items"])


# ----------------------------------------------------------------- progress --
def test_progress_per_metric() -> None:
    mon = date(2026, 10, 12)
    acts = [act(mon, 1, minutes=120, km=20, climb=800, hour=6),
            act(mon + timedelta(days=1), 2, sport="cycling", minutes=60, km=30, climb=300, hour=6),
            act(mon + timedelta(days=1), 3, sport="strength_training", minutes=30, km=0, climb=0),
            act(mon + timedelta(days=2), 4, sport="lap_swimming", minutes=40, km=2, climb=0, hour=19),
            act(mon - timedelta(days=1), 5, minutes=300)]  # last week: never counts
    rows = _rows(acts)
    end = mon + timedelta(days=6)
    v = lambda m, **kw: ch.value(m, rows, mon, end, **kw)  # noqa: E731
    assert v("workouts") == 4 and v("active_days") == 3 and v("minutes") == 250
    assert v("distance_km") == 52 and v("distance_km", sport="bike") == 30
    assert v("climb_m") == 1100 and v("long_session") == 120 and v("early_sessions") == 2
    assert v("sports_variety") == 4 and v("streak_days") == 3 and v("strength_sessions") == 1
    plan = {"weeks": [{"start": mon.isoformat(), "days": {
        mon.isoformat(): [{"sport": "run", "title": "Run", "minutes": 60}],
        (mon + timedelta(days=3)).isoformat(): [{"sport": "run", "title": "Run", "minutes": 60}],
        (mon + timedelta(days=4)).isoformat(): [{"sport": "rest", "title": "Rest"}]}}]}
    assert ch.value("plan_adherence", rows, mon, end, plan=plan, acts=acts, today=TODAY) == 50.0
    assert ch.value("plan_adherence", rows, mon, end, plan=None, acts=acts, today=TODAY) == 0.0


# ---------------------------------------------------------------- the store --
@pytest.fixture
def svc(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    state = SimpleNamespace(now=datetime(2026, 10, 14, 9, 0, tzinfo=ZoneInfo("America/Denver")),
                            acts={"ann": history(), "bob": history(), "cat": history()},
                            follows={("ann", "bob")}, checkins=[])
    c = ch.Challenges(store, now=lambda uid: state.now,
                      activities=lambda uid: (state.now.date(), state.acts.get(uid, [])),
                      athlete=lambda uid: {"favorite_sports": ["run"]},
                      checkins=lambda uid: state.checkins,
                      follows=lambda a, b: (a, b) in state.follows,
                      names=lambda uid: uid.title())
    return SimpleNamespace(c=c, s=state, store=store)


def test_join_limits_and_leave(svc) -> None:
    c = svc.c
    view = c.get("ann")
    sug = view["periods"]["week"]["suggestions"]
    assert len(sug) == 3 and view["joined"] == []
    a = c.join("ann", sug[0]["template"], "week")
    assert a["target"] == sug[0]["target"] and a["period_start"] == "2026-10-12"
    with pytest.raises(ch.ChallengeError) as e:
        c.join("ann", sug[0]["template"], "week")
    assert e.value.status == 409
    c.join("ann", sug[1]["template"], "week")
    with pytest.raises(ch.ChallengeError, match="2 weekly"):
        c.join("ann", sug[2]["template"], "week")
    with pytest.raises(ch.ChallengeError):
        c.join("ann", "m_workouts", "week")  # template/period mismatch
    with pytest.raises(ch.ChallengeError):
        c.join("ann", "nope", "week")
    m = c.get("ann")["periods"]["month"]["suggestions"]
    c.join("ann", m[0]["template"], "month")
    view = c.get("ann")
    assert view["periods"]["week"]["joined"] == 2 and len(view["joined"]) == 3
    assert all(x["template"] not in {j["template"] for j in view["joined"]} for x in view["periods"]["week"]["suggestions"])
    c.leave("ann", a["id"])
    assert len(c.get("ann")["joined"]) == 2
    with pytest.raises(ch.ChallengeError) as e:
        c.leave("ann", a["id"])
    assert e.value.status == 404
    with pytest.raises(ch.ChallengeError) as e:
        c.join(coach_user_id("c@x.com"), sug[0]["template"], "week")
    assert e.value.status == 403


def test_completion_xp_idempotent_streak_and_history(svc, tmp_path) -> None:
    c, st = svc.c, svc.s
    sug = c.get("ann")["periods"]["week"]["suggestions"]
    easy = next(x for x in sug if x["metric"] == "workouts")
    j = c.join("ann", easy["template"], "week")
    assert c.refresh("ann") == {}
    mon = date(2026, 10, 12)
    st.acts["ann"] = history() + [act(mon, 9000 + i) for i in range(int(easy["target"]))]
    view = c.get("ann")
    mine = view["joined"][0]
    assert mine["done"] and mine["pct"] == 100 and mine["completed_at"] and view["streak"]["week"] == 1
    bonus = c.refresh("ann")
    assert bonus == {f"challenge:{j['template']}:{j['period_start']}": 75}
    # The ledger awards the key once, however often it's passed.
    prog = Progress(svc.store, clock=lambda: 0)
    stats = {"badges": [], "plan": None}
    first = prog.update("ann", acts=[], today=TODAY, stats=stats, plan_key=None, quests={}, bonus={"seed": 1})
    a = prog.update("ann", acts=[], today=TODAY, stats=stats, plan_key=None, quests={}, bonus=bonus)
    b = prog.update("ann", acts=[], today=TODAY, stats=stats, plan_key=None, quests={}, bonus=c.refresh("ann"))
    assert a["xp"] - first["xp"] == 75 and b["gained"] == 0
    # Recap line for this week.
    summary = c.week_summary("ann", mon)
    assert summary == {"done": 1, "joined": 1, "items": [{"name": j["name"], "period": "week", "done": True}], "xp": 75}
    r = recap_build(start=mon, today=TODAY, acts=st.acts["ann"], plan=None, ledger={}, challenges=summary)
    assert r["challenges"]["done"] == 1 and push_text(r).endswith("1/1 challenges done")
    # Next week: it moves to history, keeps its XP key, and the streak still counts last week.
    st.now = st.now + timedelta(days=7)
    view = c.get("ann")
    assert view["joined"] == [] and view["recent"][0]["id"] == j["id"]
    assert view["streak"]["week"] == 1
    assert f"challenge:{j['template']}:{j['period_start']}" in c.refresh("ann")
    with pytest.raises(ch.ChallengeError) as e:  # completed: can't leave (and re-join to farm XP)
        c.leave("ann", j["id"])
    assert e.value.status == 404  # already in history



def test_invites_need_follow_edge_and_leaderboard(svc) -> None:
    c, st = svc.c, svc.s
    sug = c.get("ann")["periods"]["week"]["suggestions"]
    j = c.join("ann", sug[0]["template"], "week")
    # ann follows bob, not cat.
    with pytest.raises(ch.ChallengeError) as e:
        c.invite("ann", j["id"], ["cat"])
    assert e.value.status == 403
    with pytest.raises(ch.ChallengeError):
        c.invite("ann", j["id"], [coach_user_id("c@x.com")])
    with pytest.raises(ch.ChallengeError):
        c.invite("bob", j["id"], ["ann"])  # not bob's challenge
    res = c.invite("ann", j["id"], ["bob"])
    assert res["invited"] == ["bob"]
    inv = c.get("bob")["invites"]
    assert len(inv) == 1 and inv[0]["from"]["name"] == "Ann" and inv[0]["target"] == j["target"]
    assert c.get("cat")["invites"] == []
    with pytest.raises(ch.ChallengeError):
        c.accept("cat", res["group"])  # not invited
    joined = c.accept("bob", res["group"])
    assert joined["target"] == j["target"] and joined["template"] == j["template"]
    board = c.get("bob")["joined"][0]["leaderboard"]
    assert {r["user_id"] for r in board} == {"ann", "bob"} and next(r for r in board if r["me"])["user_id"] == "bob"
    assert c.get("ann")["joined"][0]["leaderboard"] is not None
    assert c.get("bob")["invites"] == []
    # Leaving drops you from the board; an unfollowed friend can't accept.
    c.leave("bob", joined["id"])
    assert [r["user_id"] for r in c.get("ann")["joined"][0]["leaderboard"]] == ["ann"]
    c.invite("ann", j["id"], ["bob"])
    st.follows.clear()
    with pytest.raises(ch.ChallengeError):
        c.accept("bob", res["group"])
    c.decline("bob", res["group"])
    assert c.get("bob")["invites"] == []


def test_late_sync_completes_a_closed_week_within_48h(svc) -> None:
    c, st = svc.c, svc.s
    easy = next(x for x in c.get("ann")["periods"]["week"]["suggestions"] if x["metric"] == "workouts")
    j = c.join("ann", easy["template"], "week")
    st.now = st.now + timedelta(days=6)  # Tuesday next week: the week closed
    assert c.get("ann")["joined"] == [] and c.refresh("ann") == {}
    # Garmin finally syncs last week's workouts.
    st.acts["ann"] = history() + [act(date(2026, 10, 12), 9000 + i) for i in range(int(easy["target"]))]
    assert c.refresh("ann") == {f"challenge:{j['template']}:{j['period_start']}": 75}
    assert c.get("ann")["recent"][0]["id"] == j["id"]


def test_late_sync_after_grace_earns_nothing(svc) -> None:
    c, st = svc.c, svc.s
    easy = next(x for x in c.get("ann")["periods"]["week"]["suggestions"] if x["metric"] == "workouts")
    c.join("ann", easy["template"], "week")
    st.now = st.now + timedelta(days=9)  # Friday next week: > 48 h after Sunday
    c.get("ann")
    st.acts["ann"] = history() + [act(date(2026, 10, 12), 9000 + i) for i in range(int(easy["target"]))]
    assert c.refresh("ann") == {}


def test_completed_challenge_cant_be_left_or_farmed(svc) -> None:
    c, st = svc.c, svc.s
    easy = next(x for x in c.get("ann")["periods"]["week"]["suggestions"] if x["metric"] == "workouts")
    j = c.join("ann", easy["template"], "week")
    st.acts["ann"] = history() + [act(date(2026, 10, 12), 9000 + i) for i in range(int(easy["target"]))]
    assert c.get("ann")["joined"][0]["done"]
    with pytest.raises(ch.ChallengeError) as e:
        c.leave("ann", j["id"])
    assert e.value.status == 409


def test_leaderboard_uses_stored_progress_not_friends_garmin(svc) -> None:
    c, st = svc.c, svc.s
    j = c.join("ann", c.get("ann")["periods"]["week"]["suggestions"][0]["template"], "week")
    g = c.invite("ann", j["id"], ["bob"])["group"]
    c.accept("bob", g)
    c.get("bob")  # bob's own refresh publishes his %
    reads: list[str] = []
    real = c._acts
    c._acts = lambda uid: (reads.append(uid), real(uid))[1]
    board = c.get("ann")["joined"][0]["leaderboard"]
    assert reads == ["ann"]  # never bob's Garmin
    assert next(r for r in board if r["user_id"] == "bob")["pct"] is not None


# --------------------------------------------------------------------- http --
def _apps(env, tmp_path):
    agent, _ = env.agent([])
    today = agent._now("ann").date()
    acts = {u: history(today) for u in ("ann", "bob", "cat")}
    agent.stats.activities = lambda uid, fresh=False: (today, acts.get(uid, []))
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW))

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, None, None, ChatRunner(agent)))
    apps = {u: app(u) for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}, \
        env.store, acts, today


def test_http_flow_and_coach_403(env, tmp_path) -> None:
    c, store, acts, today = _apps(env, tmp_path)
    soc = Social(store, athletes=lambda: dict(ALLOW))

    async def go() -> None:
        ann, bob, coach = c["ann"], c["bob"], c[coach_user_id("c@x.com")]
        r = await ann.get("/app/api/challenges")
        assert r.status_code == 200
        body = r.json()
        sug = body["periods"]["week"]["suggestions"]
        assert len(sug) == 3 and body["xp"] == {"week": 75, "month": 150}
        r = await ann.post("/app/api/challenges/join", headers=H, json={"template": sug[0]["template"], "period": "week"})
        assert r.status_code == 201
        cid = r.json()["challenge"]["id"]
        assert len(r.json()["joined"]) == 1
        assert (await ann.post("/app/api/challenges/join", headers=H,
                               json={"template": sug[0]["template"], "period": "week"})).status_code == 409
        assert (await ann.post("/app/api/challenges/join", json={"template": "w_workouts", "period": "week"})).status_code == 403
        # Invites need an active follow edge.
        assert (await ann.post(f"/app/api/challenges/{cid}/invite", headers=H, json={"user_ids": ["bob"]})).status_code == 403
        soc.follow("ann", email="bob@x.com")
        soc.accept("bob", soc.people("bob")["pending_in"][0]["edge_id"])
        r = await ann.post(f"/app/api/challenges/{cid}/invite", headers=H, json={"user_ids": ["bob"]})
        assert r.status_code == 200
        gid = r.json()["group"]
        inv = (await bob.get("/app/api/challenges")).json()["invites"]
        assert inv and inv[0]["from"]["name"] == "Ann"
        assert (await bob.post(f"/app/api/challenges/{gid}/accept", headers=H, json={})).status_code == 201
        board = (await bob.get("/app/api/challenges")).json()["joined"][0]["leaderboard"]
        assert [x["name"] for x in board if not x["me"]] == ["Ann"]
        assert "value" not in board[0]
        # Coach accounts: 403 everywhere.
        assert (await coach.get("/app/api/challenges")).status_code == 403
        for path in ("/app/api/challenges/join", f"/app/api/challenges/{gid}/accept", f"/app/api/challenges/{cid}/invite"):
            assert (await coach.post(path, headers=H, json={})).status_code == 403, path
        assert (await coach.request("DELETE", f"/app/api/challenges/{cid}", headers=H, json={})).status_code == 403
        # Completing earns XP through /progress exactly once (target lowered to make it certain).
        store.user_doc("ann", "challenges").update(lambda d: [x.update(target=1, metric="workouts", sport=None)
                                                              for x in d["joined"]])
        acts["ann"] = acts["ann"] + [act(today, 7000)]
        view = (await ann.get("/app/api/challenges")).json()
        assert view["joined"][0]["done"] and view["streak"]["week"] == 1
        p1 = (await ann.get("/app/api/progress")).json()
        p2 = (await ann.get("/app/api/progress")).json()
        c0 = store.user_doc("ann", "challenges").load()["joined"][0]
        assert f"challenge:{c0['template']}:{c0['period_start']}" in store.user_doc("ann", "progress").load()["bonus"]
        assert p2["xp"] == p1["xp"] and p2["gained"] == 0
        # A completed challenge can't be left (no re-join XP farming).
        assert (await ann.request("DELETE", f"/app/api/challenges/{cid}", headers=H, json={})).status_code == 409
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
