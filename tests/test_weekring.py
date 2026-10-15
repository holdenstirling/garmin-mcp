"""Rabbit home: weekly ring (weekring.py), Friday nudge, live race grade + weekly delta (gradetrend.py)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import httpx2

from garmin_mcp import gradetrend as gt
from garmin_mcp.weekring import WeekRing, nudge, ring, unwell
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps
from tests.test_stats import act

FRI = date(2026, 10, 16)          # a Friday; fixed so nothing depends on the clock
MON = FRI - timedelta(days=4)
FRI_EVENING = datetime(2026, 10, 16, 17, 30)


def plan(*, recovery=False, phase="build", sessions=5) -> dict:
    days: dict[str, list[dict]] = {}
    sports = [(0, "run", "Easy run"), (1, "bike", "Tempo ride"), (2, "swim", "Swim drills"),
              (3, "rest", "Rest"), (4, "run", "Intervals"), (5, "run", "Long run"), (6, "bike", "Long ride")]
    n = 0
    for i, sport, title in sports:
        if sport != "rest" and n >= sessions:
            continue
        n += sport != "rest"
        days[(MON + timedelta(days=i)).isoformat()] = [{"id": f"s{i}", "sport": sport, "title": title, "minutes": 60}]
    return {"weeks": [{"start": MON.isoformat(), "phase": phase, "recovery": recovery, "days": days}]}


def week_acts(*days: int) -> list[dict]:
    sport = {0: "running", 1: "cycling", 2: "lap_swimming", 4: "running", 5: "running"}
    return [act(MON + timedelta(days=i), sport=sport.get(i, "running"), aid=100 + i) for i in days]


# -------------------------------------------------------------------- ring --
def test_ring_counts_plan_sessions() -> None:
    r = ring(plan(), week_acts(0, 1, 2, 4), FRI)  # Mon-Fri done, Sat long run left (5 sessions)
    assert r["kind"] == "plan" and (r["done"], r["target"], r["remaining"]) == (4, 5, 1)
    assert r["line"] == "4 of 5 · one more closes your week" and not r["closed"]
    assert [d["state"] for d in r["days"]] == ["done", "done", "done", "rest", "done", "planned", "empty"]
    assert [d["today"] for d in r["days"]].index(True) == 4 and r["days_left"] == 2
    assert r["next"]["title"] == "Long run" and r["week_start"] == MON.isoformat()
    missed = ring(plan(), week_acts(0, 4), FRI)
    assert [d["state"] for d in missed["days"]][:3] == ["done", "missed", "missed"]
    assert missed["line"] == "2 of 5 this week"  # three short, one session left: no false promise


def test_ring_active_week_without_plan() -> None:
    r = ring(None, week_acts(0, 2), FRI)
    assert r["kind"] == "active" and (r["done"], r["target"]) == (2, 3) and r["unit"] == "workout"
    assert r["line"] == "2 of 3 · one more closes your week"
    assert [d["state"] for d in r["days"]] == ["done", "empty", "done", "empty", "empty", "empty", "empty"]
    # A plan with nothing this week counts like no plan.
    far = {"weeks": [{"start": (MON + timedelta(weeks=3)).isoformat(), "days": {
        (MON + timedelta(weeks=3)).isoformat(): [{"id": "x", "sport": "run", "title": "Run"}]}}]}
    assert ring(far, week_acts(0), FRI)["kind"] == "active"


def test_ring_closed_state() -> None:
    r = ring(plan(), week_acts(0, 1, 2, 4, 5), FRI + timedelta(days=1))
    assert r["closed"] and r["line"] == "Week closed!" and "+100 XP" in r["sub"]
    a = ring(None, week_acts(0, 1, 2), FRI)
    assert a["closed"] and a["line"] == "Week closed!" and "streak" in a["sub"]


# ------------------------------------------------------------------- nudge --
def test_friday_nudge_rules() -> None:
    r = ring(plan(), week_acts(0, 1, 2, 4), FRI)
    reason, m = nudge(r, local=FRI_EVENING, checkins=[], push_on=True)
    assert reason == "ok" and m["type"] == "week_nudge" and m["key"] == f"weeknudge:{MON.isoformat()}"
    assert m["text"] == "💪 One more session closes your week. Tomorrow's long run would do it."
    assert len(m["text"]) <= 140 and m["actions"][0]["id"] == "plan"
    two = nudge(ring(plan(), week_acts(0, 1, 2), FRI), local=FRI_EVENING, checkins=[], push_on=True)[1]
    assert two["text"].startswith("💪 Two more sessions close your week.")
    active = nudge(ring(None, week_acts(0, 2), FRI), local=FRI_EVENING, checkins=[], push_on=True)[1]
    assert active["text"] == "💪 One more workout closes your week. Even 30 easy minutes this weekend counts."
    # Gates.
    assert nudge(r, local=FRI_EVENING, checkins=[], push_on=False)[0] == "nudges_off"
    assert nudge(r, local=FRI_EVENING - timedelta(days=1), checkins=[], push_on=True)[0] == "not_friday"
    assert nudge(r, local=FRI_EVENING.replace(hour=16, minute=59), checkins=[], push_on=True)[0] == "too_early"
    assert nudge(r, local=FRI_EVENING.replace(hour=21, minute=5), checkins=[], push_on=True)[0] == "quiet"
    assert nudge(ring(plan(), week_acts(0, 1, 2, 4, 5), FRI), local=FRI_EVENING, checkins=[], push_on=True)[0] == "closed"
    assert nudge(ring(plan(), week_acts(0, 4), FRI), local=FRI_EVENING, checkins=[], push_on=True)[0] == "too_far"
    rest = ring(plan(recovery=True), week_acts(0, 1, 2, 4), FRI)
    taper = ring(plan(phase="taper"), week_acts(0, 1, 2, 4), FRI)
    assert nudge(rest, local=FRI_EVENING, checkins=[], push_on=True)[0] == "rest_week"
    assert nudge(taper, local=FRI_EVENING, checkins=[], push_on=True)[0] == "rest_week"
    pain = [{"date": "2026-10-14", "pain_flag": True, "tags": [], "summary": ""}]
    sick = [{"date": "2026-10-11", "pain_flag": False, "tags": ["sick"], "summary": "Felt rough."}]
    assert nudge(r, local=FRI_EVENING, checkins=pain, push_on=True)[0] == "unwell"
    assert nudge(r, local=FRI_EVENING, checkins=sick, push_on=True)[0] == "unwell"
    old = [{"date": "2026-10-01", "pain_flag": True}]
    assert not unwell(old, FRI) and not unwell([{"date": "2026-10-15", "summary": "No pain, legs good"}], FRI)


def test_nudge_service_once_a_week_and_toggle(env) -> None:
    agent, _ = env.agent([])
    pushes: list[tuple] = []
    agent.moments.push = lambda u, t, b, url: pushes.append((u, t, b))
    now = {"t": FRI_EVENING}
    agent.moments._now = lambda uid: now["t"]
    acts = week_acts(0, 1, 2, 4)
    profile: dict = {}
    wr = WeekRing(plan=lambda u: plan(), activities=lambda u: (now["t"].date(), acts), checkins=lambda u: [],
                  profile=lambda u: profile, now=lambda u: now["t"], moments=agent.moments)
    profile["moments_push"] = False
    assert wr.check_nudge("u1") == "nudges_off" and not pushes
    profile.pop("moments_push")
    assert wr.check_nudge("u1") == "posted"
    assert pushes and pushes[0][1] == "Close your week" and pushes[0][2].startswith("One more session")
    assert wr.check_nudge("u1") == "claimed"          # same day: not re-evaluated
    now["t"] = FRI_EVENING.replace(hour=19)
    assert wr.check_nudge("u1") == "claimed"
    now["t"] = FRI_EVENING.replace(hour=22)
    assert wr.check_nudge("u1") == "not_now"          # quiet hours
    now["t"] = FRI_EVENING + timedelta(days=1)
    assert wr.check_nudge("u1") == "not_now"          # Saturday
    assert wr.check_nudge("coach_x") == "skipped"
    # Same week, claim lost (e.g. doc reset): the moment key still dedupes.
    now["t"] = FRI_EVENING
    agent.moments._doc("u1").update(lambda d: d.get("claims", {}).pop("weeknudge", None))
    assert wr.check_nudge("u1") == "duplicate" and len(pushes) == 1
    # Garmin unreadable: no ring, no nudge.
    broken = WeekRing(plan=lambda u: plan(), activities=lambda u: (_ for _ in ()).throw(RuntimeError()),
                      checkins=lambda u: [], profile=lambda u: {}, now=lambda u: now["t"], moments=agent.moments)
    assert broken.get("u2") is None and broken.check_nudge("u2") == "no_ring"


# ------------------------------------------------------------------- grade --
def readiness(score, grade, comps, keys) -> dict:
    return {"grade": grade, "score": score, "status": "on_track", "confidence": "high", "days_to_race": 60,
            "components": [{"id": k, "score": v, "weight": w} for (k, w), v in zip(
                [("fitness", 30), ("key_session", 25), ("consistency", 20), ("race_factors", 15), ("health", 10)], comps)],
            "key_sports": keys}


def test_grade_snapshot_delta_and_reasons() -> None:
    doc: dict = {}
    last = gt.snapshot(readiness(74, "B-", [70, 60, 80, 90, 100], {"bike": 50, "run": 70, "swim": 70}), FRI - timedelta(days=7))
    gt.record(doc, "e1", last)
    cur = gt.snapshot(readiness(80, "B+", [72, 75, 80, 90, 100], {"bike": 92, "run": 70, "swim": 60}), FRI)
    rows = gt.record(doc, "e1", cur)
    again = gt.record(doc, "e1", dict(cur, score=81))    # same week: upserted, not appended
    assert len(rows) == 2 and len(again) == 2 and again[-1]["score"] == 81
    t = gt.trend(rows, cur)
    assert t["delta"] == 6 and t["direction"] == "up" and t["prev_grade"] == "B-"
    assert t["reasons"] == [{"sign": "+", "text": "long rides on target"}, {"sign": "-", "text": "swim volume low"}]
    v = gt.view({"id": "e1", "name": "Boulder 70.3"}, readiness(80, "B+", [72, 75, 80, 90, 100], {}), t, FRI)
    assert v["line"] == "Boulder 70.3 · B+ · on track" and v["weekly"] is True and v["delta"] == 6
    # First week: no delta, no reasons.
    assert gt.trend([cur], cur)["delta"] is None
    # Down week: the drop's reasons come first.
    worse = gt.snapshot(readiness(70, "B-", [60, 75, 70, 90, 100], {"bike": 92, "run": 70, "swim": 60}), FRI + timedelta(days=7))
    rows = gt.record(doc, "e1", worse)
    t2 = gt.trend(rows, worse)
    assert t2["direction"] == "down" and [r["text"] for r in t2["reasons"]] == ["fitness slipping", "sessions missed"]
    # Bounded history.
    for i in range(20):
        gt.record(doc, "e1", dict(cur, week=(MON + timedelta(weeks=i + 2)).isoformat()))
    assert len(doc["events"]["e1"]) == gt.KEEP_WEEKS


def test_pick_race_main_then_next_and_hidden() -> None:
    evs = [{"id": "a", "name": "Old", "date": "2026-09-01", "kind": "race", "main": True},
           {"id": "b", "name": "Tune-up 10k", "date": "2026-11-01", "kind": "race", "main": False},
           {"id": "c", "name": "Boulder 70.3", "date": "2027-06-01", "kind": "race", "main": True},
           {"id": "d", "name": "Trip", "date": "2026-10-20", "kind": "trip", "main": False}]
    assert gt.pick_race(evs, FRI)["id"] == "c"
    assert gt.pick_race([e for e in evs if e["id"] != "c"], FRI)["id"] == "b"
    assert gt.pick_race([evs[0], evs[3]], FRI) is None


def test_service_records_and_moment_hook(env) -> None:
    agent, _ = env.agent([])
    store = agent._store
    scores = iter([70, 78])
    days = iter([FRI - timedelta(days=7), FRI])
    state = {"today": FRI}

    def rd(u, e):
        return readiness(next(scores), "B", [70, 70, 80, 90, 100], {"run": 80})
    evs = [{"id": "e1", "name": "City Marathon", "date": "2027-03-01", "kind": "race", "main": True}]
    svc = gt.GradeTrend(store, readiness=rd, events=lambda u: evs, today=lambda u: state["today"])
    state["today"] = next(days)
    assert svc.grade("u1", "e1") == "B"                 # the daily moment check records a snapshot
    state["today"] = next(days)
    live = svc.live("u1")
    assert live["delta"] == 8 and live["direction"] == "up" and live["event_id"] == "e1"
    assert len(store.user_doc("u1", "grade_history").load()["events"]["e1"]) == 2
    assert gt.GradeTrend(store, readiness=rd, events=lambda u: [], today=lambda u: FRI).live("u1") is None


# --------------------------------------------------------------------- http --
def test_api_shapes_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    ev = agent.events.create("friend", {"name": "Spring 50K", "type": "trail", "distance": "ultra",
                                        "date": (today + timedelta(weeks=8)).isoformat()})
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = (await a.get("/app/api/weekring")).json()["ring"]
            assert r is None or (set(r) >= {"kind", "done", "target", "line", "days", "closed", "week_start"}
                                 and len(r["days"]) == 7)
            g = (await a.get("/app/api/racegrade/live")).json()["race"]
            assert g["event_id"] == ev["id"] and g["grade"] and g["line"].startswith("Spring 50K · ")
            assert set(g) >= {"delta", "direction", "reasons", "status", "weekly"}
            assert (await c.get("/app/api/weekring")).status_code == 403
            assert (await c.get("/app/api/racegrade/live")).status_code == 403
    asyncio.run(go_())
