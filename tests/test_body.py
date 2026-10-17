"""Body logs (body.py): fueling log + learnings, niggle tracker rules and easing proposals,
storage privacy, the coach context line and the /app/api/body routes."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp import body as B
from garmin_mcp.planbuilder import build_plan, iter_sessions
from garmin_mcp.racepack import fueling
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plancal import ATHLETE
from tests.test_profile import BASE, _apps

TODAY = date(2026, 10, 19)  # a Monday


def _entry(gh: int, *, gi: str = "great", energy: str = "strong", minutes: int = 120, day: str = "2026-10-01") -> dict:
    return {"minutes": minutes, "carbs_g": gh * minutes // 60, "gi": gi, "energy": energy, "date": day, "sport": "bike"}


def test_clean_fuel_counts_product_chips_and_validates() -> None:
    e = B.clean_fuel({"minutes": 120, "items": [{"product": "gel", "count": 3}, {"product": "drink", "count": 2, "g": 45}],
                      "fluids_ml": 1200, "gi": "ok", "energy": "faded"})
    assert e["carbs_g"] == 3 * 23 + 2 * 45 and B.rates(e) == {"g_per_h": 80, "ml_per_h": 600, "mg_per_h": None}
    for bad in ({"minutes": 0}, {"minutes": 60, "gi": "meh"}, {"minutes": 60, "items": [{"product": "pizza"}]},
                {"minutes": 60, "carbs_g": -5}):
        with pytest.raises(B.BodyError):
            B.clean_fuel(bad)


def test_fuel_learnings_find_the_good_band_problems_and_the_gap_to_target() -> None:
    entries = [_entry(60), _entry(70), _entry(95, gi="issues"), _entry(40, energy="bonked")]
    out = B.learnings(entries, 80)
    assert out["learned_rate"] == 70 and out["sessions"] == 4
    text = " ".join(out["lines"])
    assert "**strong** at 60-70 g/h" in text and "issues from about 95 g/h" in text and "bonked" in text
    assert "practise 2 more long sessions" in text
    assert B.learnings([], 80)["learned_rate"] is None and "Log what you take" in B.learnings([], 80)["lines"][0]
    assert B.learnings([_entry(30, minutes=45)], 80)["sessions"] == 0  # short sessions don't count
    assert "practised your race target" in " ".join(B.learnings([_entry(80), _entry(85)], 80)["lines"])


def test_race_pack_uses_the_learned_rate() -> None:
    ev = {"distance": "70.3"}
    assert fueling(ev, {})["carbs_g_per_h"] == 80
    near = fueling(ev, {}, learned=75)
    assert near["carbs_g_per_h"] == 75 and near["practised_g_per_h"] == 75 and "practised well" in near["steps"][-2]
    far = fueling(ev, {}, learned=45)
    assert far["carbs_g_per_h"] == 80 and any("only practised 45 g/h" in s for s in far["steps"])


def _niggle(**kw) -> dict:
    n = B.clean_niggle({"area": "knee", "side": "left", "pain": 3, "type": "ache", "affects": ["run"]} | kw)
    return n | {"id": "n0000000001", "status": "active", "created": "2026-10-18", "updates": [], "resolved": None}


def test_niggle_rules_are_conservative() -> None:
    mild = B.assess(_niggle(), TODAY)
    assert not mild["ease"] and not mild["red_flag"]
    assert B.assess(_niggle(pain=4), TODAY)["ease"] and B.assess(_niggle(type="sharp", pain=2), TODAY)["ease"]
    worse = _niggle() | {"updates": [{"date": "2026-10-19", "trend": "worse", "pain": 3}]}
    assert B.assess(worse, TODAY)["ease"]
    assert B.assess(_niggle(pain=7), TODAY)["red_flag"] and B.assess(_niggle(type="swollen", pain=5), TODAY)["red_flag"]
    three = _niggle() | {"updates": [{"date": f"2026-10-1{i}", "trend": "worse", "pain": 3} for i in (7, 8, 9)]}
    assert any("worse 3 updates" in r for r in B.assess(three, TODAY)["red_flag"])
    old = _niggle(pain=4) | {"created": "2026-09-20"}
    assert any("after 29 days" in r for r in B.assess(old, TODAY)["red_flag"])
    assert B.assess(_niggle(pain=6), TODAY)["swap"] and B.assess(_niggle(pain=6), TODAY)["days"] == 5
    assert B.prehab("knee")[0]["name"].startswith("Spanish squat") and B.prehab("quad") and B.prehab("other")
    with pytest.raises(B.BodyError):
        B.clean_niggle({"area": "elbow", "pain": 3})
    with pytest.raises(B.BodyError):
        B.clean_niggle({"area": "knee", "pain": 11})


def _plan() -> dict:
    return build_plan({"weekly_hours": 8, "level": "intermediate"},
                      {"title": "70.3", "distance": "70.3", "date": (TODAY + timedelta(weeks=20)).isoformat()},
                      today=TODAY)


def test_ease_proposal_eases_the_affected_sport_only() -> None:
    plan = _plan()
    day = TODAY + timedelta(days=2)  # the window then holds an easy 40' run (Thu) and the long run (Sun)
    assert B.ease_proposal(plan, [_niggle()], day) is None  # mild: nothing to change
    prop = B.ease_proposal(plan, [_niggle(pain=5)], day)
    assert prop and prop["days"] == 3 and "Left knee" in prop["why"]
    end = (day + timedelta(days=2)).isoformat()
    for c in prop["changes"]:
        assert day.isoformat() <= c["date"] <= end and c["from"]["sport"] in ("run", "brick")
        assert c["to"]["minutes"] < c["from"]["minutes"] and c["action"] in ("ease", "shorten")
    swap = B.ease_proposal(plan, [_niggle(pain=6)], day)
    runs = [c for c in swap["changes"] if c["from"]["sport"] == "run"]
    assert len(runs) == 2 and all(c["action"] == "swap_sport" and c["to"]["sport"] == "bike" for c in runs)
    assert not [c for c in swap["changes"] if c["from"]["sport"] in ("bike", "swim")]  # unaffected sports kept
    assert B.ease_proposal(plan, [_niggle(pain=6) | {"status": "resolved"}], day) is None


def test_context_lines_only_active_niggles_with_red_flag() -> None:
    lines = B.context_lines([_niggle(pain=7), _niggle(pain=2) | {"status": "resolved"}], TODAY)
    assert len(lines) == 1 and "Left knee: 7/10" in lines[0] and "RED FLAG" in lines[0]


def test_body_routes_end_to_end_and_private(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.post("/app/api/body/fuel", headers=h, json={"key": "s:abc123", "minutes": 90,
                                                                     "items": [{"product": "gel", "count": 3}], "gi": "great",
                                                                     "energy": "strong"})
            assert r.status_code == 201, r.text
            assert r.json()["entry"]["g_per_h"] == 46
            assert (await a.get("/app/api/body/fuel?key=s:abc123")).json()["entry"]["carbs_g"] == 69
            assert (await a.get("/app/api/body/fuel?key=../x")).status_code == 400
            f = (await a.get("/app/api/body/fueling")).json()
            assert f["target"] == 40 and f["learnings"]["sessions"] == 1
            r = await a.post("/app/api/body/niggles", headers=h, json={"area": "calf", "side": "right", "pain": 6,
                                                                        "type": "tight", "affects": ["run"]})
            assert r.status_code == 201, r.text
            body = r.json()
            n = body["active"][0]
            assert n["label"] == "Right calf" and n["assess"]["ease"] and n["prehab"] and n["care_note"]
            prop = body["proposal"]
            if prop:  # depends on the plan having runs in the next few days
                bad = await a.post("/app/api/body/niggles/ease", headers=h, json={"action": "apply", "id": "nope"})
                assert bad.status_code == 409
                ok = await a.post("/app/api/body/niggles/ease", headers=h, json={"action": "apply", "id": prop["id"]})
                assert ok.status_code == 200, ok.text
            r = await a.post(f"/app/api/body/niggles/{n['id']}", headers=h, json={"trend": "better", "pain": 3})
            assert r.json()["active"][0]["history"][-1]["pain"] == 3
            r = await a.post(f"/app/api/body/niggles/{n['id']}", headers=h, json={"resolve": True})
            assert not r.json()["active"] and r.json()["resolved"][0]["status"] == "resolved"
            assert (await a.post("/app/api/body/niggles/n0123456789", headers=h, json={"resolve": True})).status_code == 404
            assert (await c.get("/app/api/body/niggles")).status_code == 403
            assert (await c.get("/app/api/body/fueling")).status_code == 403
    asyncio.run(go_())
    # stored encrypted like every user doc: no plain text on disk
    raw = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    assert b"Right calf" not in raw and b"calf" not in raw


def test_niggles_reach_the_coach_context(env) -> None:
    agent, _ = env.agent([])
    store = agent.coach._s
    bs = B.BodyStore(store, today=lambda _u: agent._now("friend").date())
    bs.add_niggle("friend", {"area": "achilles", "side": "left", "pain": 5, "affects": ["run"]})
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert "Niggles they're tracking" in ctx and "Left achilles: 5/10" in ctx


def test_swap_sport_change_applies_to_the_plan(env) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    plan = agent.plans.get("friend")
    d, s = next((d, s) for _, d, s in iter_sessions(plan) if s["sport"] == "run" and d > today.isoformat())
    agent.plans.apply_adjustment("friend", [{"session_id": s["id"], "date": d, "action": "swap_sport",
                                            "to": {"sport": "bike", "kind": "easy", "minutes": 35}, "why": "Easing for your calf."}])
    after = agent.plans.get("friend")
    assert not any(x["id"] == s["id"] for _, _, x in iter_sessions(after))
    new = [x for _, dd, x in iter_sessions(after) if dd == d and x["sport"] == "bike" and x.get("adjusted")]
    assert new and new[0]["minutes"] == 35 and new[0]["adjust_why"] == "Easing for your calf."
