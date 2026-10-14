"""Insights ("What your data says"): each rule with synthetic data (fires / stays quiet),
ranking and the cap, snooze, Oura exclusion from Rabbit's context and the coach view, APIs."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2

from garmin_mcp import insights as ins_mod
from garmin_mcp.insights import (EXPLAIN_MAX, MAX_ACTIVE, TITLE_MAX, WHY_MAX, InsightsService, compute,
                                 context_lines, mark_seen, rank, stored_context, text_hash)
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, COACH, _apps
from tests.test_stats import act

TODAY = date(2026, 10, 14)  # a Wednesday
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def one(items: list[dict], prefix: str) -> dict | None:
    hits = [i for i in items if i["id"] == prefix or i["id"].startswith(prefix + ":")]
    assert len(hits) <= 1
    return hits[0] if hits else None


def check_shape(i: dict) -> None:
    assert len(i["title"]) <= TITLE_MAX and len(i["explanation"]) <= EXPLAIN_MAX and len(i["why"]) <= WHY_MAX
    assert i["impact"] in ("positive", "watch", "action") and i["confidence"] in ("low", "medium", "high")
    assert i["action"]["kind"] in ins_mod.ACTION_KINDS
    assert any(ch.isdigit() for ch in i["explanation"])  # numbers in the explanation


def runs(days: range, minutes: int, **kw) -> list[dict]:
    return [act(ago(d), minutes=minutes, aid=10_000 + d * 10 + kw.pop("off", 0), **kw) for d in days]


# ------------------------------------------------------------------ 1 ramp --
def test_ramp_fires_on_a_big_jump_and_reuses_the_adjust_proposal() -> None:
    acts = runs(range(7, 60), 45) + runs(range(0, 7), 100)
    i = one(compute(today=TODAY, acts=acts), "ramp")
    assert i and i["impact"] == "action" and "Training load (time × intensity)" in i["explanation"]
    assert i["action"]["kind"] == "ask_rabbit" and i["evidence"]["kind"] == "bars" and len(i["evidence"]["values"]) == 5
    check_shape(i)
    prop = {"status": "suggest", "id": "p123", "changes": [{"session_id": "a"}, {"session_id": "b"}]}
    i = one(compute(today=TODAY, acts=acts, proposal=prop), "ramp")
    assert i["action"] == {"kind": "apply_adjust", "label": "Ease the next days (2 changes)", "payload": {"id": "p123"}}
    # Negative: steady training, or too little history to judge.
    assert one(compute(today=TODAY, acts=runs(range(0, 60), 45)), "ramp") is None
    assert one(compute(today=TODAY, acts=runs(range(0, 7), 100)), "ramp") is None


# ------------------------------------------------------------- 2 long run --
def marathon(weeks: int = 10, **kw) -> dict:
    return {"id": "e1", "name": "City Marathon", "type": "running", "distance": "marathon", "priority": "A",
            "main": True, "date": (TODAY + timedelta(weeks=weeks)).isoformat()} | kw


def weekly_long(long: int) -> list[dict]:
    out = runs(range(1, 60), 45)
    out += [act(ago(d), minutes=long, km=25, aid=50_000 + d, hour=8) for d in range(3, 60, 7)]
    return out


def test_long_session_vs_race_needs() -> None:
    i = one(compute(today=TODAY, acts=weekly_long(170), events=[marathon()]), "long")
    assert i and i["impact"] == "positive" and "Long runs on track" in i["title"]
    check_shape(i)
    i = one(compute(today=TODAY, acts=weekly_long(60), events=[marathon()]), "long")
    assert i and i["impact"] == "action" and "City Marathon" in i["explanation"]
    assert i["action"]["kind"] == "ask_rabbit" and i["evidence"]["target"] > 60
    # Negative: no race, or the race is too far out to judge.
    assert one(compute(today=TODAY, acts=weekly_long(60)), "long") is None
    assert one(compute(today=TODAY, acts=weekly_long(60), events=[marathon(40)]), "long") is None


# ------------------------------------------------------------ 3 intensity --
def hr_runs(hard: int, easy: int) -> list[dict]:
    out = []
    for k in range(hard + easy):
        a = act(ago(1 + 2 * k), minutes=60, aid=70_000 + k)
        a["avg_hr"] = 160 if k < hard else 130
        out.append(a)
    return out


def test_intensity_balance_by_heart_rate() -> None:
    athlete = {"threshold_hr": 170}
    i = one(compute(today=TODAY, acts=hr_runs(4, 6), athlete=athlete), "intensity")
    assert i and i["impact"] == "watch" and "40%" in i["title"] and "80/20" in i["explanation"]
    assert "by heart rate" in i["explanation"] and i["confidence"] == "high"
    check_shape(i)
    i = one(compute(today=TODAY, acts=hr_runs(1, 7), athlete=athlete), "intensity")
    assert i and i["impact"] == "positive"
    # Negative: too few sessions, or nothing to classify them by.
    assert one(compute(today=TODAY, acts=hr_runs(2, 2), athlete=athlete), "intensity") is None
    assert one(compute(today=TODAY, acts=hr_runs(4, 6)), "intensity") is None


def test_intensity_falls_back_to_garmin_training_effect() -> None:
    acts = hr_runs(4, 6)
    for k, a in enumerate(acts):
        a.pop("avg_hr")
        a["training_effect_label"] = "VO2MAX" if k < 4 else "AEROBIC_BASE"
    i = one(compute(today=TODAY, acts=acts), "intensity")
    assert i and i["impact"] == "watch" and "training effect" in i["explanation"] and i["confidence"] == "medium"


# ------------------------------------------------------------- 4 recovery --
BIG = (4, 9, 14, 19)


def recovery_days(dips: tuple[int, int, int]) -> dict:
    rows = {ago(d).isoformat(): 80 for d in range(0, 28)}
    for b in BIG:
        for k, v in enumerate(dips, start=1):
            rows[ago(b - k).isoformat()] = v
    return {"days": [{"date": d, "readiness": v} for d, v in sorted(rows.items())]}


def big_day_acts() -> list[dict]:
    return [act(ago(d), minutes=180 if d in BIG else 45, aid=80_000 + d) for d in range(1, 40)]


def test_recovery_after_big_days() -> None:
    items = compute(today=TODAY, acts=big_day_acts(), recovery=recovery_days((60, 65, 80)), recovery_source="oura")
    i = one(items, "recovery")
    assert i and i["impact"] == "watch" and "3 days" in i["title"] and "48 h" in i["why"]
    assert i["uses_oura"] and "oura" in i["sources"] and "Oura readiness" in i["explanation"]
    check_shape(i)
    i = one(compute(today=TODAY, acts=big_day_acts(), recovery=recovery_days((79, 80, 80)), recovery_source="garmin"),
            "recovery")
    assert i and i["impact"] == "positive" and not i["uses_oura"]
    # Negative: no recovery data, or no big days.
    assert one(compute(today=TODAY, acts=big_day_acts()), "recovery") is None
    assert one(compute(today=TODAY, acts=runs(range(1, 40), 45), recovery=recovery_days((60, 65, 80))),
               "recovery") is None


# ---------------------------------------------------------------- 5 sleep --
def sleep_checkins(low_feel: int, ok_feel: int) -> tuple[list[dict], dict]:
    cis, days = [], []
    for k in range(1, 9):
        short = k % 2 == 0
        cis.append({"date": ago(k).isoformat(), "feel": low_feel if short else ok_feel,
                    "sleep": "poor" if short else "good"})
        days.append({"date": ago(k).isoformat(), "sleep_hours": 5.6 if short else 7.6})
    return cis, {"days": days}


def test_sleep_vs_how_sessions_felt() -> None:
    cis, sleep = sleep_checkins(2, 4)
    i = one(compute(today=TODAY, acts=[], checkins=cis, sleep=sleep, sleep_source="oura"), "sleep")
    assert i and i["impact"] == "watch" and "2.0 points harder" in i["title"] and i["uses_oura"]
    check_shape(i)
    # Without sleep hours: the athlete's own check-in sleep (never Oura).
    i = one(compute(today=TODAY, acts=[], checkins=cis), "sleep")
    assert i and not i["uses_oura"] and i["sources"] == ["checkins"]
    # Negative: no difference, or too few check-ins (n < 6).
    cis2, sleep2 = sleep_checkins(3, 3)
    assert one(compute(today=TODAY, acts=[], checkins=cis2, sleep=sleep2, sleep_source="garmin"), "sleep") is None
    assert one(compute(today=TODAY, acts=[], checkins=cis[:4], sleep=sleep, sleep_source="garmin"), "sleep") is None


# ----------------------------------------------------- plan-based rules --
def plan(weeks: int = 9, extra: dict | None = None) -> dict:
    out = []
    for w in range(weeks):
        start = MONDAY - timedelta(weeks=weeks - 1 - w)
        days = {}
        for off, kind, mins in ((1, "easy", 60), (3, "easy", 60), (5, "long", 90)):
            d = (start + timedelta(days=off)).isoformat()
            days[d] = [{"id": f"s{w}{off}", "sport": "run", "kind": kind, "title": "Run", "minutes": mins}]
        out.append({"start": start.isoformat(), "phase": "build", "days": days})
    p = {"weeks": out, "race_date": None}
    if extra:
        out[-1]["days"].setdefault(extra["date"], []).append(extra["session"])
    return p


def plan_acts(thu_minutes: int | None, thu_hour: int = 18) -> list[dict]:
    out = []
    for w in range(9):
        start = MONDAY - timedelta(weeks=8 - w)
        for off, mins, hour in ((1, 60, 6), (3, thu_minutes, thu_hour), (5, 90, 7)):
            d = start + timedelta(days=off)
            if d < TODAY and mins:
                out.append(act(d, minutes=mins, hour=hour, aid=90_000 + w * 10 + off))
    return out


def test_time_of_day_completion() -> None:
    i = one(compute(today=TODAY, acts=plan_acts(40), plan=plan()), "time_of_day")
    assert i and "Morning sessions go best" in i["title"] and "100%" in i["explanation"]
    assert i["action"]["kind"] == "open_plan"
    check_shape(i)
    # Negative: evening sessions done in full too.
    assert one(compute(today=TODAY, acts=plan_acts(60), plan=plan()), "time_of_day") is None
    assert one(compute(today=TODAY, acts=plan_acts(40)), "time_of_day") is None


def test_missed_weekday() -> None:
    i = one(compute(today=TODAY, acts=plan_acts(None), plan=plan()), "missed_day")
    assert i and i["id"] == "missed_day:3" and i["impact"] == "action" and "Thursday" in i["title"]
    assert i["action"] == {"kind": "open_plan", "label": "Move Thursday sessions", "payload": {}}
    check_shape(i)
    assert one(compute(today=TODAY, acts=plan_acts(60), plan=plan()), "missed_day") is None


def test_soreness_pattern_links_strength_session() -> None:
    cis = [{"date": ago(d).isoformat(), "soreness": [{"area": "calf", "side": "left", "level": 2}]} for d in (2, 9, 16)]
    i = one(compute(today=TODAY, acts=[], checkins=cis), "sore")
    assert i and i["id"] == "sore:calf" and i["impact"] == "action" and "calf raises" in i["explanation"]
    assert i["action"]["kind"] == "ask_rabbit" and "not a diagnosis" in i["why"]
    check_shape(i)
    strength = {"date": (TODAY + timedelta(days=2)).isoformat(),
                "session": {"id": "st1", "sport": "strength", "kind": "strength", "title": "Strength", "minutes": 30}}
    cis[0]["pain_flag"] = True
    i = one(compute(today=TODAY, acts=[], checkins=cis, plan=plan(extra=strength)), "sore")
    assert i["action"]["kind"] == "open_session" and i["action"]["payload"]["session_id"] == "st1"
    assert "checked" in i["explanation"]
    assert one(compute(today=TODAY, acts=[], checkins=cis[:2]), "sore") is None


# ----------------------------------------------------------------- 9 gear --
SHOE = {"id": "g1", "kind": "shoes", "brand": "Nike", "model": "Pegasus", "retired": False, "status": "soon",
        "alert_km": 700, "total_km": 640, "pct_of_alert": 91}


def test_shoes_near_retirement_before_key_race() -> None:
    i = one(compute(today=TODAY, acts=[], gear=[SHOE], events=[marathon(4)]), "gear")
    assert i and i["impact"] == "action" and "640 of 700 km" in i["explanation"] and "4 weeks" in i["explanation"]
    assert i["action"] == {"kind": "open_gear", "label": "Open your gear", "payload": {"gear_id": "g1"}}
    check_shape(i)
    i = one(compute(today=TODAY, acts=[], gear=[SHOE], events=[marathon(4)], athlete={"units": "imperial"}), "gear")
    assert "398 of 435 mi" in i["explanation"]
    assert one(compute(today=TODAY, acts=[], gear=[SHOE]), "gear") is None
    assert one(compute(today=TODAY, acts=[], gear=[SHOE], events=[marathon(20)]), "gear") is None
    i = one(compute(today=TODAY, acts=[], gear=[SHOE | {"status": "retire", "total_km": 720}]), "gear")
    assert i and i["impact"] == "watch"


# -------------------------------------------------------------- 10 fitness --
def test_fitness_trend_in_plain_words() -> None:
    up = runs(range(29, 120), 30) + runs(range(0, 29), 70)
    i = one(compute(today=TODAY, acts=up), "fitness")
    assert i and i["impact"] == "positive" and i["title"].startswith("Fitness up")
    assert "Fitness (your 6-week training average)" in i["explanation"] and len(i["evidence"]["values"]) == 9
    check_shape(i)
    down = runs(range(29, 120), 70) + runs(range(0, 29), 20)
    i = one(compute(today=TODAY, acts=down), "fitness")
    assert i and i["impact"] == "watch" and i["title"].startswith("Fitness down")
    raced = {"id": "r", "name": "Fall 10K", "date": ago(10).isoformat()}
    i = one(compute(today=TODAY, acts=down, events=[raced]), "fitness")
    assert i["impact"] == "positive" and "planned rest" in i["title"]
    assert one(compute(today=TODAY, acts=runs(range(0, 180), 45)), "fitness") is None
    assert one(compute(today=TODAY, acts=[]), "fitness") is None


def test_a_broken_rule_never_hides_the_rest(monkeypatch) -> None:
    def boom(**_):
        raise KeyError("x")
    monkeypatch.setattr(ins_mod, "RULES", (boom, ins_mod.rule_gear))
    assert [i["id"] for i in compute(today=TODAY, acts=[], gear=[SHOE], events=[marathon(4)])] == ["gear:g1"]


# ------------------------------------------------------- ranking + state --
def fake(id_: str, impact: str, priority: int = 5, oura: bool = False) -> dict:
    return ins_mod._insight(id_, title=f"T {id_}", explanation=f"E {id_} 1", why="W", impact=impact, confidence="low",
                            evidence=None, action=None, sources=["oura" if oura else "garmin"], priority=priority)


def test_rank_orders_by_impact_freshness_and_caps() -> None:
    items = [fake("p1", "positive", 1), fake("w1", "watch", 3), fake("a1", "action", 2), fake("a2", "action", 1),
             fake("w2", "watch", 1), fake("p2", "positive", 2), fake("w3", "watch", 9)]
    out = rank(items, None, TODAY)
    assert len(out) == MAX_ACTIVE and [i["id"] for i in out] == ["a2", "a1", "w2", "w1", "w3"]
    # Seen with identical text for 3+ days: stale, ranks after fresh ones of the same impact.
    state = {"seen": {"a2": {"h": text_hash(items[3]), "first": ago(3).isoformat()}}}
    out = rank(items, state, TODAY)
    assert [i["id"] for i in out][:2] == ["a1", "a2"] and out[1]["fresh"] is False
    # Changed text = fresh again.
    state = {"seen": {"a2": {"h": "other", "first": ago(10).isoformat()}}}
    assert rank(items, state, TODAY)[0]["id"] == "a2"
    # An unchanged positive drops out after 7 days.
    state = {"seen": {"p1": {"h": text_hash(items[0]), "first": ago(7).isoformat()}}}
    assert "p1" not in [i["id"] for i in rank(items, state, TODAY, cap=10)]
    seen = mark_seen({"seen": {"old": {"h": "x", "first": ago(40).isoformat()}}}, out, TODAY)
    assert "old" not in seen and seen["a2"]["first"] == TODAY.isoformat()


def test_snooze_hides_for_seven_days() -> None:
    items = [fake("a1", "action"), fake("w1", "watch")]
    state = {"dismissed": {"a1": (TODAY + timedelta(days=7)).isoformat()}}
    assert [i["id"] for i in rank(items, state, TODAY)] == ["w1"]
    assert [i["id"] for i in rank(items, state, TODAY + timedelta(days=7))] == ["a1", "w1"]


def test_context_lines_exclude_oura() -> None:
    items = [fake("a1", "action", oura=True), fake("a2", "action"), fake("w1", "watch"), fake("w2", "watch"),
             fake("p1", "positive")]
    lines = context_lines(items)
    assert lines == ["- T a2: E a2 1", "- T w1: E w1 1", "- T w2: E w2 1"]
    assert not any("a1" in ln for ln in lines)
    doc = {"context_date": TODAY.isoformat(), "context": [{"id": "x", "line": "- Oura thing", "oura": True},
                                                          {"id": "y", "line": "- Garmin thing", "oura": False}]}
    assert stored_context(doc, TODAY) == ["- Garmin thing"]
    assert stored_context(doc, TODAY + timedelta(days=3)) == []


def test_service_saves_oura_free_context_and_coach_view(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    oura_ins = ins_mod._insight("recovery", title="You recover in about 3 days after big days",
                                explanation="Oura readiness dipped 15 points", why="w", impact="watch",
                                confidence="low", evidence=None, action=None, sources=["garmin", "oura"], priority=1)
    calls = []

    async def gather(uid):
        calls.append(uid)
        return {"today": today, "acts": [], "gear": [SHOE], "events": [marathon(4) | {"date": (today + timedelta(weeks=4)).isoformat()}]}

    svc = InsightsService(env.store, gather=gather, today=lambda uid: today)
    orig = ins_mod.compute
    try:
        ins_mod.compute = lambda **kw: orig(**kw) + [oura_ins]
        out = asyncio.run(svc.for_athlete("friend"))
        ids = [i["id"] for i in out["insights"]]
        assert ids == ["gear:g1", "recovery"] and out["insights"][1]["uses_oura"]
        asyncio.run(svc.for_athlete("friend"))
        assert calls == ["friend"]  # cached
        ctx = agent.coach.context_block("friend", agent._now("friend"), None)
        assert "Fresh shoes before City Marathon" in ctx and "Oura readiness dipped" not in ctx
        coach = asyncio.run(svc.for_coach("friend"))
        assert [i["id"] for i in coach["insights"]] == ["gear:g1"]
        assert coach["insights"][0]["action"]["kind"] == "none"
        svc.dismiss("friend", "gear:g1")
        out = asyncio.run(svc.for_athlete("friend"))
        assert [i["id"] for i in out["insights"]] == ["recovery"]
        assert "Fresh shoes" not in agent.coach.context_block("friend", agent._now("friend"), None)
    finally:
        ins_mod.compute = orig


def test_insights_api_and_coach_access(env, tmp_path, monkeypatch) -> None:
    agent, _ = env.agent([])
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)
    oura_ins = ins_mod._insight("sleep", title="Short sleep makes sessions feel 1.0 points harder",
                                explanation="On under 6.5 h (3 sessions)", why="w", impact="watch", confidence="low",
                                evidence=None, action=None, sources=["checkins", "oura"], priority=1)
    garmin_ins = ins_mod._insight("fitness", title="Fitness up 12% in 4 weeks", explanation="From 40 to 45",
                                  why="w", impact="positive", confidence="high", evidence=None, action=None,
                                  sources=["garmin"], priority=9)
    seen: list[dict] = []

    def fake_compute(**kw):
        seen.append(kw)
        return [oura_ins, garmin_ins]
    monkeypatch.setattr(ins_mod, "compute", fake_compute)
    h = {"origin": BASE, "content-type": "application/json"}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            r = await a.get("/app/api/insights")
            assert r.status_code == 200 and [i["id"] for i in r.json()["insights"]] == ["sleep", "fitness"]
            kw = seen[-1]
            assert kw["recovery_source"] == "garmin" and set(kw) >= {"acts", "plan", "load", "checkins", "gear", "events"}
            assert (await a.post("/app/api/insights/fitness/dismiss", json={})).status_code == 403  # no origin
            assert (await a.post("/app/api/insights/BAD%20ID/dismiss", headers=h, json={})).status_code == 400
            assert (await a.post("/app/api/insights/fitness/dismiss", headers=h, json={"days": "x"})).status_code == 400
            r = await a.post("/app/api/insights/fitness/dismiss", headers=h, json={})
            assert r.status_code == 200 and r.json()["until"] > TODAY.isoformat()[:4]
            assert [i["id"] for i in (await a.get("/app/api/insights")).json()["insights"]] == ["sleep"]
            # Coach accounts: athlete routes refused; coach route only once linked, and never Oura.
            assert (await c.get("/app/api/insights")).status_code == 403
            assert (await c.post("/app/api/insights/sleep/dismiss", headers=h, json={})).status_code == 403
            assert (await c.get("/app/api/coach/athletes/friend/insights")).status_code == 400
            await a.post("/app/api/coaches", headers=h, json={"email": COACH})
            r = await c.get("/app/api/coach/athletes/friend/insights")
            assert r.status_code == 200 and [i["id"] for i in r.json()["insights"]] == ["fitness"]
            assert (await o.get("/app/api/coach/athletes/friend/insights")).status_code == 400
            ctx = agent.coach.context_block("friend", agent._now("friend"), None)
            assert "Short sleep" not in ctx
    asyncio.run(go_())
