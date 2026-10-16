"""Training paces (paces.py): threshold detection, evidence rules, outliers, cooldown, easing,
accept/undo re-targeting only future sessions, and the coach 403."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import httpx2

from garmin_mcp import paces as pc
from garmin_mcp.appstore import AppStore
from garmin_mcp.planbuilder import make_session
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

TODAY = date(2026, 10, 16)  # fixed so nothing depends on the clock
ATH = {"run_threshold_pace": 270, "threshold_hr": 172, "units": "metric", "home_elevation_m": 1600}


def run(aid: int, ago: int, km: float, secs: float, *, name: str = "Run", hr: float | None = None,
        event: str | None = None, sport: str = "running", **kw) -> dict:
    a = {"activity_id": aid, "date": f"{(TODAY - timedelta(days=ago)).isoformat()} 07:00:00", "name": name,
         "sport": sport, "distance_km": km, "moving_duration": secs}
    if hr:
        a["avg_hr"] = hr
    if event:
        a["event"] = event
    return a | kw


def lap(m: float, s: float, hr: float | None = None, gain: float = 0.0) -> dict:
    x = {"d": m, "s": s, "gain": gain}
    if hr:
        x["hr"] = hr
    return x


def tempo_laps(pace: float, hr: float = 168, reps: int = 4, rec: bool = False) -> list[dict]:
    """Warm-up, ``reps`` x 5 min at ``pace`` s/km (with 2-min jogs when ``rec``), cool-down."""
    m = 300 / pace * 1000
    out = [lap(2000, 660, 140)]
    for _ in range(reps):
        out.append(lap(m, 300, hr))
        if rec:
            out.append(lap(300, 120, 145))
    return out + [lap(1500, 500, 145)]


# ------------------------------------------------------------- estimation --
def test_threshold_from_tempo_laps_intervals_and_race() -> None:
    acts = [run(1, 2, 8, 2600, name="Tempo Tuesday", hr=160), run(2, 5, 8, 2700, name="Track reps", hr=158)]
    laps = {"1": tempo_laps(262), "2": tempo_laps(258, rec=True)}
    efforts, skipped = pc.run_efforts(acts, laps, TODAY, ATH)
    by = {e["activity_id"]: e for e in efforts}
    assert not skipped
    assert by[1]["kind"] == "tempo" and abs(by[1]["value"] - 262) < 0.6          # 20 min at HR 98% = threshold
    assert by[2]["kind"] == "intervals" and abs(by[2]["value"] - 258 * 1.01) < 0.6
    # A race: 10K in 45:00 is a bit faster than threshold (one-hour pace).
    (r,), _ = pc.run_efforts([run(3, 3, 10, 2700, event="race")], {}, TODAY, ATH)
    assert r["kind"] == "race" and 273 < r["value"] < 276
    # Without a threshold HR: only a hard-named run whose laps are clearly faster counts.
    no_hr = {k: v for k, v in ATH.items() if k != "threshold_hr"}
    e, _ = pc.run_efforts(acts, laps, TODAY, no_hr)
    assert {x["activity_id"] for x in e} == {1, 2}
    e, _ = pc.run_efforts([run(1, 2, 8, 2600, name="Morning Run")], laps, TODAY, no_hr)
    assert e == []
    # A tempo below threshold HR (90%) counts as faster than it was run.
    (t,), _ = pc.run_efforts([run(1, 2, 8, 2600)], {"1": tempo_laps(270, hr=0.93 * 172)}, TODAY, ATH)
    assert t["value"] < 270
    # Splits come in as Garmin lapDTOs.
    assert pc.laps_from_splits({"lapDTOs": [{"distance": 1000.0, "duration": 262.0, "averageHR": 168,
                                             "elevationGain": 3.0}, {"distance": 0}]}) == \
        [{"d": 1000.0, "s": 262.0, "hr": 168, "gain": 3.0}]


def test_evidence_threshold_and_meaningful_change() -> None:
    one = [run(1, 2, 8, 2600, hr=160)]
    laps = {"1": tempo_laps(262), "2": tempo_laps(263)}
    assert pc.estimate("run", one, laps, TODAY, ATH) is None                      # one effort isn't enough
    two = one + [run(2, 9, 8, 2600, hr=160)]
    s = pc.estimate("run", two, laps, TODAY, ATH)
    assert s and s["direction"] == "faster" and s["old"] == 270 and s["new"] in (262, 263)
    assert {e["activity_id"] for e in s["efforts"]} == {1, 2}
    # Older than 21 days: doesn't count; a race alone does (28 days).
    assert pc.estimate("run", [run(1, 25, 8, 2600, hr=160)], laps, TODAY, ATH) is None
    race = pc.estimate("run", [run(5, 20, 10, 2600, event="race")], {}, TODAY, ATH)
    assert race and race["direction"] == "faster"
    # Garmin's predictor helps but never counts alone.
    assert pc.estimate("run", one, laps, TODAY, ATH, garmin_10k_s=2550) is None
    # Too small: 2 s/km (~3 s/mi, < 2%) -> nothing; 5 s/mi is enough even under 2%.
    assert pc.estimate("run", two, {"1": tempo_laps(268), "2": tempo_laps(268)}, TODAY, ATH) is None
    assert pc.meaningful("run", 270, 266.8) and not pc.meaningful("run", 270, 268)
    assert pc.meaningful("bike", 250, 255) and not pc.meaningful("bike", 250, 254)
    # A huge jump is capped at 6% per step.
    big = pc.estimate("run", two, {"1": tempo_laps(230), "2": tempo_laps(231)}, TODAY, ATH)
    assert big["capped"] and big["new"] == round(270 * 0.94)
    # Nothing set yet: suggest setting it.
    s = pc.estimate("run", two, laps, TODAY, {"threshold_hr": 172})
    assert s["direction"] == "set" and s["old"] is None


def test_outliers_heat_altitude_hills_and_far_off() -> None:
    laps = {str(i): tempo_laps(262) for i in range(1, 6)}
    acts = [run(1, 2, 8, 2600, max_temp_c=31), run(2, 3, 8, 2600, max_elev_m=3400),
            run(3, 4, 8, 2600, elevation_gain_m=200), run(4, 5, 8, 2600, sport="treadmill_running")]
    efforts, skipped = pc.run_efforts(acts, laps, TODAY, ATH)
    assert efforts == [] and sorted(x["reason"] for x in skipped) == ["at altitude", "hilly", "hot"]
    assert pc.estimate("run", acts, laps, TODAY, ATH) is None
    # Home at altitude: a run at 2,000 m is normal there.
    _, sk = pc.run_efforts([run(2, 3, 8, 2600, max_elev_m=2000)], laps, TODAY, ATH)
    assert sk == []
    _, sk = pc.run_efforts([run(2, 3, 8, 2600, max_elev_m=2000)], laps, TODAY, {"threshold_hr": 172})
    assert sk == []                                                                 # under 2,000 m with no home
    # With 3+ efforts, one far from the median is dropped (and listed).
    laps = {"1": tempo_laps(262), "2": tempo_laps(263), "3": tempo_laps(240)}
    s = pc.estimate("run", [run(1, 2, 8, 2600), run(2, 5, 8, 2600), run(3, 8, 8, 2600)], laps, TODAY, ATH)
    assert {e["activity_id"] for e in s["efforts"]} == {1, 2}
    assert any(x["reason"] == "far off your other efforts" for x in s["skipped"])


def test_ease_off_when_missing_targets_with_high_hr() -> None:
    acts = [run(i, d, 8, 2900) for i, d in ((1, 2), (2, 6), (3, 10))]
    slow = {str(i): tempo_laps(282, hr=170) for i in (1, 2, 3)}
    s = pc.estimate("run", acts, slow, TODAY, ATH)
    assert s and s["direction"] == "slower" and s["new"] > 270 and len(s["efforts"]) == 3
    assert "slower than target with a high heart rate" in pc.headline(s, TODAY, False)
    # Only two such efforts, or one at a modest HR, or one on target -> keep the threshold.
    assert pc.estimate("run", acts[:2], slow, TODAY, ATH) is None
    mixed = dict(slow, **{"3": tempo_laps(282, hr=160)})
    assert pc.estimate("run", acts, mixed, TODAY, ATH) is None
    ok = dict(slow, **{"3": tempo_laps(270, hr=170)})
    s = pc.estimate("run", acts, ok, TODAY, ATH)
    assert s is None or s["direction"] != "slower"
    # Bike: three hard rides whose 20-min power says a lower FTP.
    rides = [{"activity_id": i, "date": f"{(TODAY - timedelta(days=d)).isoformat()} 08:00:00", "sport": "road_biking",
              "moving_duration": 3600, "max_20min_power_w": 240, "avg_hr": 162} for i, d in ((1, 1), (2, 5), (3, 9))]
    s = pc.estimate("bike", rides, {}, TODAY, ATH | {"ftp_w": 260})
    assert s["direction"] == "slower" and s["new"] == 247
    assert pc.estimate("bike", [r | {"avg_hr": 140} for r in rides], {}, TODAY, ATH | {"ftp_w": 260}) is None


def test_bike_ftp_and_swim_css() -> None:
    rides = [{"activity_id": 1, "date": "2026-10-14 08:00:00", "sport": "road_biking", "moving_duration": "1:10:00",
              "max_20min_power_w": 290}, {"activity_id": 2, "date": "2026-10-11 08:00:00",
                                          "sport": "virtual_ride", "moving_duration": 3000, "max_20min_power_w": 280}]
    s = pc.estimate("bike", rides, {}, TODAY, {"ftp_w": 268})
    assert s["direction"] == "faster" and s["new"] == round(0.95 * 290) and s["efforts"][0]["kind"] == "ride"
    assert pc.estimate("bike", rides, {}, TODAY, {"ftp_w": 250})["new"] == round(250 * 1.06)   # capped step
    assert pc.estimate("bike", rides[:1], {}, TODAY, {"ftp_w": 268}) is None
    swims = [{"activity_id": i, "date": f"{(TODAY - timedelta(days=d)).isoformat()} 06:00:00", "sport": "lap_swimming"}
             for i, d in ((7, 1), (8, 4))]
    reps = [lap(200, 200)] * 6 + [lap(200, 230)] * 2 + [lap(50, 60)]
    s = pc.estimate("swim", swims, {"7": reps, "8": reps}, TODAY, {"swim_css": 104})
    assert s["direction"] == "faster" and s["new"] == 100
    assert "sec/100m faster" in pc.headline(s, TODAY, False)


def test_wording_units_and_moment_length() -> None:
    acts = [run(1, 0, 8, 2600, hr=160), run(2, 3, 10, 2650, event="race")]
    s = pc.estimate("run", acts, {"1": tempo_laps(262)}, TODAY, ATH | {"units": "imperial"})
    h = pc.headline(s, TODAY, True)
    assert h.startswith("Your threshold looks ") and "/mi" in h and "today's tempo" in h and "Tuesday's 10K" in h
    m = pc.moment_text(s, TODAY, True)
    assert len(m) <= 140 and "→" in m
    z = pc.zones("run", 270)
    assert [x["zone"] for x in z] == [1, 2, 3, 4, 5] and all(x["lo"] <= x["hi"] for x in z)
    assert pc.zones("bike", 250)[1] == {"zone": 2, "name": "aerobic", "lo": 140, "hi": 188}


# ------------------------------------------------------------- service --
class Rig:
    def __init__(self, store: AppStore, athlete: dict, acts: list, plan: dict | None = None) -> None:
        self.athlete, self.acts, self.plan, self.posted, self.splits = dict(athlete), acts, plan, [], []
        self.t = datetime(2026, 10, 16, 9, 0)
        self.clock = 1_000_000.0

        def edit(uid, fn):
            if self.plan is None:
                raise ValueError("no plan")
            fn(self.plan, self.t.date())
            return self.plan

        def split(uid, aid):
            self.splits.append(aid)
            return {"lapDTOs": [{"distance": 1145.0, "duration": 300.0, "averageHR": 168}] * 4}
        self.svc = pc.Paces(store, athlete=lambda u: dict(self.athlete), set_athlete=lambda u, p: self.athlete.update(p),
                            activities=lambda u: self.acts, now=lambda u: self.t, clock=lambda: self.clock,
                            splits=split, edit_plan=edit, post=lambda u, m: self.posted.append(m) or "posted")


def test_cooldown_never_and_after_workouts_fetch(env) -> None:
    acts = [run(11, 0, 8, 2600, name="Tempo"), run(12, 4, 10, 2650, name="City 10K race", event="race")]
    rig = Rig(env.store, ATH, acts)
    assert rig.svc.after_workouts("u1") == ["run"]          # laps fetched for the fresh run only
    assert rig.splits == [11]
    rig.svc.fill_laps("u1", acts, TODAY, days=21, limit=3)  # the older hard-named run, once
    rig.svc.fill_laps("u1", acts, TODAY, days=21, limit=3)
    assert rig.splits == [11, 12]
    m = rig.posted[-1]
    assert m["type"] == "pace" and [a["id"] for a in m["actions"]] == ["pace_accept", "pace", "pace_later"]
    assert m["key"].startswith("pace:p") and len(m["text"]) <= 140
    assert rig.svc.check("u1") == []                        # 14-day cooldown

    def fresh(base: int) -> list[dict]:
        """Two tempo runs on the rig's current day and two days before."""
        out = []
        for i, back in ((base, 0), (base + 1, 2)):
            d = rig.t.date() - timedelta(days=back)
            out.append(run(i, (TODAY - d).days, 8, 2600, name="Tempo"))
        rig.svc.fill_laps("u1", out, rig.t.date(), days=21, limit=3)
        return out
    rig.t += timedelta(days=13)
    rig.acts = fresh(20)
    assert rig.svc.check("u1") == []
    rig.t += timedelta(days=1)
    assert rig.svc.check("u1") == ["run"]
    (p,) = rig.svc.view("u1")["pending"]
    rig.svc.dismiss("u1", p["id"], never=True)              # Never for this
    assert rig.svc.view("u1")["pending"] == []
    rig.t += timedelta(days=20)
    rig.acts = fresh(30)
    assert rig.svc.check("u1") == [] and rig.svc.view("u1")["run"]["suggestions"] is False
    rig.svc.set_suggestions("u1", "run", True)
    assert rig.svc.check("u1") == ["run"]
    (p,) = rig.svc.view("u1")["pending"]
    rig.svc.dismiss("u1", p["id"])                          # Not now: gone, cooldown applies
    assert rig.svc.view("u1")["pending"] == [] and rig.svc.check("u1") == []
    assert rig.svc.check("coach_x") == [] and rig.svc.after_workouts("coach_x") == []
    # Weekly check runs once per 7 days.
    rig2 = Rig(env.store, ATH, acts)
    assert rig2.svc.weekly("u2") == ["run"]
    rig2.t += timedelta(days=3)
    assert rig2.svc.weekly("u2") == []


def _plan() -> dict:
    """Two weeks around TODAY: past and future run/swim/bike sessions."""
    mon = TODAY - timedelta(days=TODAY.weekday() + 7)
    days: dict = {}
    for i in range(14):
        d = (mon + timedelta(days=i)).isoformat()
        days[d] = [make_session("run", "tempo", 50), make_session("swim", "css", 45)]
        if i % 7 == 5:
            days[d].append(make_session("brick", "endurance", 90))
    weeks = [{"index": w + 1, "start": (mon + timedelta(days=7 * w)).isoformat(), "phase": "build",
              "days": {k: v for k, v in days.items() if k < (mon + timedelta(days=7 * (w + 1))).isoformat()
                       and k >= (mon + timedelta(days=7 * w)).isoformat()}} for w in range(2)]
    return {"weeks": weeks}


def _count(plan: dict, when, pred) -> int:
    return sum(1 for w in plan["weeks"] for d, ss in w["days"].items() for s in ss if when(d) and pred(s))


def test_accept_updates_future_only_and_undo(env) -> None:
    acts = [run(11, 0, 8, 2600, name="Tempo"), run(12, 4, 8, 2600, name="Tempo")]
    plan = _plan()
    rig = Rig(env.store, ATH | {"swim_css": 110}, acts, plan)
    rig.svc.fill_laps("u1", acts, TODAY, days=21, limit=3)
    assert rig.svc.check("u1") == ["run"]
    (p,) = rig.svc.view("u1")["pending"]
    assert p["efforts"] and p["efforts"][0]["detail"].startswith("20 min at")
    out = rig.svc.accept("u1", p["id"])
    new = rig.athlete["run_threshold_pace"]
    assert new < 270 and out["value"] == new
    past = lambda d: d < TODAY.isoformat()  # noqa: E731
    fut = lambda d: d >= TODAY.isoformat()  # noqa: E731
    runs = lambda s: s["sport"] in ("run", "brick")  # noqa: E731
    assert _count(plan, past, lambda s: runs(s) and s.get("targets") == {"run_threshold_pace": 270}) == \
        _count(plan, past, runs)
    assert _count(plan, fut, lambda s: "targets" in s) == 0
    assert out["updated"] == _count(plan, fut, runs) and out["summary"].startswith(f"{out['updated']} workouts updated; easy runs ")
    # A past session's workout view keeps the old pace; a future one gets the new.
    old_s = next(s for w in plan["weeks"] for d, ss in w["days"].items() for s in ss if past(d) and s["sport"] == "run")
    assert pc.athlete_for(rig.athlete, old_s)["run_threshold_pace"] == 270
    view = rig.svc.view("u1")
    assert view["pending"] == [] and view["run"]["value"] == new and view["run"]["source"]["how"] == "suggested"
    assert view["run"]["source"]["label"].startswith("From ") and view["undo"]["sport"] == "run"
    # Undo within 24 h restores everything; afterwards it's refused.
    rig.svc.undo("u1", out["undo"]["id"])
    assert rig.athlete["run_threshold_pace"] == 270 and _count(plan, lambda d: True, lambda s: "targets" in s) == 0
    assert rig.svc.view("u1")["run"]["source"]["how"] == "manual"
    try:
        rig.svc.undo("u1", out["undo"]["id"])
        raise AssertionError("undo twice")
    except pc.PaceError as e:
        assert e.status == 409
    # Swim: future builder swims are rebuilt for the new CSS (past ones untouched), undo puts them back.
    swims = [{"activity_id": i, "date": f"{(TODAY - timedelta(days=d)).isoformat()} 06:00:00", "sport": "lap_swimming"}
             for i, d in ((7, 1), (8, 4))]
    rig.svc._doc("u1").update(lambda d: d.setdefault("laps", {}).update({"7": [lap(200, 190)] * 6, "8": [lap(200, 190)] * 6}))
    rig.acts = swims
    assert rig.svc.check("u1") == ["swim"]
    before = {s["id"]: s.get("meters") for w in plan["weeks"] for d, ss in w["days"].items() for s in ss if s["sport"] == "swim"}
    (p,) = rig.svc.view("u1")["pending"]
    out = rig.svc.accept("u1", p["id"])
    after = {s["id"]: (d, s.get("meters")) for w in plan["weeks"] for d, ss in w["days"].items() for s in ss if s["sport"] == "swim"}
    assert all(m == before[i] for i, (d, m) in after.items() if past(d))
    assert any(m != before[i] for i, (d, m) in after.items() if fut(d))
    rig.clock += 25 * 3600
    assert rig.svc.view("u1")["undo"] is None
    try:
        rig.svc.undo("u1", out["undo"]["id"])
        raise AssertionError("undo after 24 h")
    except pc.PaceError as e:
        assert e.status == 409
    # A suggestion goes stale when the profile value changed by hand.
    rig.t += timedelta(days=15)
    rig.svc._doc("u1").update(lambda d: d.setdefault("laps", {}).update({"21": tempo_laps(262), "22": tempo_laps(262)}))
    rig.acts = [run(21, -15, 8, 2600, name="Tempo"), run(22, -13, 8, 2600, name="Tempo")]
    assert rig.svc.check("u1") == ["run"]
    rig.athlete["run_threshold_pace"] = 265
    assert rig.svc.view("u1")["pending"] == [] and rig.svc.view("u1")["run"]["source"]["label"] == "Set in your profile"


def test_real_plan_accept_and_api_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", {"weekly_hours": 8, "level": "intermediate", "run_threshold_pace": 270,
                                          "threshold_hr": 172, "available_days": ["tue", "wed", "thu", "sat", "sun"],
                                          "long_day": "sat"})
    agent.coach.create_goal("friend", {"title": "Race", "distance": "half",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    acts = [run(31, 0, 8, 2600, name="Tempo"), run(32, 3, 8, 2600, name="Tempo")]
    for a in acts:
        a["date"] = f"{(today - (TODAY - date.fromisoformat(a['date'][:10]))).isoformat()} 07:00:00"
    svc = pc.Paces(agent._store, athlete=agent.coach.athlete, set_athlete=agent.coach.update_athlete,
                   activities=lambda u: acts, now=agent._now, clock=lambda: 1.0, edit_plan=agent.plans._edit,
                   post=agent.moments.post)
    agent._store.user_doc("friend", "paces").update(lambda d: d.setdefault("laps", {}).update(
        {"31": tempo_laps(262), "32": tempo_laps(262)}))
    assert svc.check("friend") == ["run"]
    (p,) = svc.view("friend")["pending"]
    out = svc.accept("friend", p["id"])
    assert out["updated"] > 0 and agent.coach.athlete("friend")["run_threshold_pace"] == p["new"]
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            v = (await a.get("/app/api/paces")).json()
            assert set(v) >= {"units", "run", "bike", "swim", "pending", "undo"} and v["run"]["value"] == p["new"]
            assert len(v["run"]["zones"]) == 5
            r = await a.post("/app/api/paces/pdeadbeef/accept", headers=h, json={})
            assert r.status_code == 409
            assert (await a.post("/app/api/paces/suggestions", headers=h, json={"sport": "run", "on": False})).json()["ok"]
            assert (await a.get("/app/api/paces")).json()["run"]["suggestions"] is False
            assert (await a.post("/app/api/paces/undo", headers=h, json={"id": "nope"})).status_code == 409
            assert (await c.get("/app/api/paces")).status_code == 403
            assert (await c.post("/app/api/paces/undo", headers=h, json={"id": "x"})).status_code == 403
    asyncio.run(go_())
