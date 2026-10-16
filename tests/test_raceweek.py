"""Race-week mode (raceweek.py): window, taper, pacing splits, packing, tracking, moments."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time as dtime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import raceweek as rw
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.moments import race_step
from garmin_mcp.social import Social
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_moments import Clock, feed, make
from tests.test_social import ALLOW, BASE, H, FakePush

DAY = date(2031, 6, 1)  # fixed: nothing here reads the real clock


def ev(i: str, days: int, *, priority: str = "B", main: bool = False, kind: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"id": i, "name": f"Race {i}", "date": (DAY + timedelta(days=days)).isoformat(), "priority": priority,
            "main": main, "kind": kind or "race", "type": "running", "distance": "half marathon", **kw}


# ------------------------------------------------------------- window --
def test_race_week_window_detection() -> None:
    assert rw.race_week([ev("a", 8, priority="A")], DAY) is None            # too far
    assert rw.race_week([ev("a", -1, priority="A")], DAY) is None           # past
    assert rw.race_week([ev("c", 3, priority="C")], DAY) is None            # C race
    assert rw.race_week([ev("t", 3, priority="A", kind="trip")], DAY) is None  # not a race
    hit = rw.race_week([ev("c", 2, priority="C", main=True)], DAY)          # main counts whatever the priority
    assert hit and hit["event"]["id"] == "c" and hit["days"] == 2
    for d in (0, 7):
        assert rw.race_week([ev("a", d, priority="A")], DAY)["days"] == d
    # nearest wins; a tie goes to the main event
    evs = [ev("b", 5), ev("a", 3, priority="A"), ev("m", 3, main=True)]
    assert rw.race_week(evs, DAY)["event"]["id"] == "m"


def test_taper_line_from_plan_or_last_week() -> None:
    race = DAY + timedelta(days=4)
    t = rw.taper(None, race, DAY)
    assert (t["day"], t["of"]) == (4, 7) and t["text"] == "Day 4 of taper: keep it short and sharp."
    plan = {"weeks": [{"phase": "taper", "start": (race - timedelta(days=14)).isoformat(), "days": {}}]}
    assert rw.taper(plan, race, DAY)["day"] == 11
    assert "lay out your kit" in rw.taper(None, race, race - timedelta(days=1))["text"]
    assert rw.taper(None, race, race)["text"].startswith("Race day")


# ------------------------------------------------------------- pacing --
def test_run_splits_add_up_and_start_easy() -> None:
    s = rw.splits(5400, 21.0975, imperial=False)
    rows = s["rows"]
    assert s["step"] == 2 and rows[-1]["label"] == "Finish" and rows[-1]["cum_s"] == 5400
    assert abs(sum(r["split_s"] for r in rows) - 5400) <= len(rows)       # rounding only
    # first band a touch slower than the rest, the rest even
    p0 = rows[0]["split_s"] / 2
    p1 = rows[1]["split_s"] / 2
    assert p0 > p1 and rows[1]["split_s"] == rows[2]["split_s"]
    assert s["pace"] == "4:16/km" and "–" in s["band"]
    mi = rw.splits(3 * 3600, 42.195, imperial=True)
    assert mi["unit"] == "mi" and mi["step"] == 2 and len(mi["rows"]) <= rw.MAX_ROWS and mi["rows"][-1]["cum"] == "3:00:00"
    short = rw.splits(1500, 5.0, imperial=False)
    assert short["step"] == 1 and len(short["rows"]) == 5
    bike = rw.splits(4 * 3600, 160.0, imperial=False, mode="speed")
    assert bike["speed"] == "40.0 km/h" and "speed" in bike["rows"][0]
    assert rw.splits(0, 10, imperial=False)["rows"] == []


def test_tri_splits_scale_legs_keep_transitions() -> None:
    est = [{"leg": "swim", "mid_s": 2400}, {"leg": "t1", "mid_s": 210}, {"leg": "bike", "mid_s": 10800},
           {"leg": "t2", "mid_s": 150}, {"leg": "run", "mid_s": 7200}]
    legs = rw.tri_splits(19000, est, (1.9, 90.0, 21.1), imperial=False)
    assert [x["leg"] for x in legs] == ["swim", "t1", "bike", "t2", "run"]
    assert sum(x["s"] for x in legs) == 19000 and legs[-1]["cum"] == "5:16:40"
    assert legs[1]["s"] == 210 and legs[3]["s"] == 150
    assert legs[0]["pace"].endswith("/100m") and legs[2]["pace"].endswith("km/h") and legs[4]["pace"].endswith("/km")


def test_target_parsing_and_source() -> None:
    assert rw.parse_target("1:45:00") == 6300
    assert rw.parse_target("4:30") == 16200                 # h:mm without a reference
    assert rw.parse_target("22:30", ref_s=1400) == 1350     # m:ss near a 5K estimate
    assert rw.parse_target("4:30", ref_s=16000) == 16200
    assert rw.parse_target("fast") is None
    e = ev("a", 3, target_time="1:50:00")
    est = {"estimate": {"low_s": 6200, "mid_s": 6500, "high_s": 6900}, "text": "1:43–1:55", "confidence": "medium"}
    inp = {"distance_km": 21.0975}
    assert rw.pacing_plan(e, {}, est, inp, None)["source"] == "goal"
    p = rw.pacing_plan(e, {}, est, inp, 6000)
    assert p["source"] == "you" and p["target"] == "1:40:00" and p["splits"]["rows"][-1]["cum_s"] == 6000
    p = rw.pacing_plan(ev("b", 3), {}, est, inp, None)
    assert p["source"] == "estimate" and p["target_s"] == 6500
    p = rw.pacing_plan(ev("b", 3), {}, None, inp, None)
    assert p["target_s"] is None and p["splits"] is None and p["effort"]  # effort guidance still there


# ------------------------------------------------------------ packing --
def test_packing_defaults_by_sport_and_distance() -> None:
    tri = rw.packing_defaults({"type": "triathlon", "distance": "140.6"})
    texts = [x["text"] for x in tri]
    assert any("Wetsuit" in t for t in texts) and any("Special-needs" in t for t in texts)
    assert len({x["id"] for x in tri}) == len(tri)
    five = [x["text"] for x in rw.packing_defaults({"type": "running", "distance": "5k"})]
    mara = [x["text"] for x in rw.packing_defaults({"type": "running", "distance": "marathon"})]
    assert not any(t.startswith("Gels") for t in five) and any("Gels" in t for t in mara)
    gear = [{"id": "g1", "kind": "shoes", "brand": "Nike", "model": "Pegasus", "nickname": "", "total_km": 120.0,
             "pct_of_alert": 20, "status": "ok", "default_for": ["run"]},
            {"id": "g2", "kind": "bike", "brand": "Trek", "model": "Domane", "total_km": 1, "status": "ok"}]
    run = rw.packing_defaults({"type": "running", "distance": "10k"}, gear)
    assert run[0] == {"id": "gear-g1", "text": "Nike Pegasus", "group": "Your gear"}
    assert not any(x["id"] == "gear-g2" for x in run)       # a bike isn't race gear for a run


def _svc(tmp_path, fernet_key, events: dict[str, list[dict[str, Any]]], **kw: Any):
    store = AppStore(tmp_path / "app", fernet_key)
    allow = dict(ALLOW) | {"dan@x.com": "dan"}
    soc = Social(store, athletes=lambda: allow)
    clock = kw.pop("clock", None) or Clock(datetime.combine(DAY, dtime(9, 0)))
    svc = rw.RaceWeek(store, events=lambda u: events.get(u, []), now=clock.now, follows=soc.follows,
                      blocked=soc.blocked_between, is_athlete=soc.is_athlete, followers=soc.follower_ids, **kw)
    return SimpleNamespace(svc=svc, soc=soc, store=store, clock=clock)


def _follow(s: Social, a: str, b: str) -> None:
    s.follow(a, email=f"{b}@x.com")
    edge = next(e for e in s.people(b)["pending_in"] if e["user_id"] == a)
    s.accept(b, edge["edge_id"])


def test_packing_persists_per_event(tmp_path, fernet_key) -> None:
    e1, e2 = ev("e1", 3, priority="A"), ev("e2", 5)
    t = _svc(tmp_path, fernet_key, {"ann": [e1, e2]})
    d = rw.packing_defaults(e1)
    first = d[0]["id"]
    v = t.svc.packing("ann", "e1", {"toggle": first}, d)
    assert v["done"] == 1 and v["items"][0]["done"]
    v = t.svc.packing("ann", "e1", {"add": "  Lucky   socks  "}, d)
    mine = next(x for x in v["items"] if x["custom"])
    assert mine["text"] == "Lucky socks" and v["total"] == len(d) + 1
    t.svc.packing("ann", "e1", {"toggle": mine["id"]}, d)
    # stored: a fresh read sees it; the other race has its own list
    assert rw.packing_view(d, t.svc.saved("ann", "e1")["packing"])["done"] == 2
    assert rw.packing_view(d, t.svc.saved("ann", "e2").get("packing"))["done"] == 0
    v = t.svc.packing("ann", "e1", {"remove": mine["id"]}, d)
    assert v["done"] == 1 and not any(x["custom"] for x in v["items"])
    with pytest.raises(rw.RaceWeekError) as err:
        t.svc.packing("ann", "e1", {"remove": first}, d)       # defaults can't be removed
    assert err.value.status == 404
    with pytest.raises(rw.RaceWeekError):
        t.svc.packing("ann", "e1", {"toggle": "nope"}, d)
    with pytest.raises(rw.RaceWeekError) as err:
        t.svc.packing("ann", "zz", {"toggle": first}, d)
    assert err.value.status == 404
    with pytest.raises(rw.RaceWeekError) as err:
        t.svc.packing(coach_user_id("c@x.com"), "e1", {"toggle": first}, d)
    assert err.value.status == 403


def test_nutrition_by_duration_is_labelled_guidance() -> None:
    assert rw.nutrition_plan(0.4)["carbs_g_per_h"] == [0, 0]
    assert rw.nutrition_plan(1.8)["carbs_g_per_h"] == [30, 60]
    long = rw.nutrition_plan(5, hot=True, weight_kg=70)
    assert long["carbs_g_per_h"] == [60, 90] and long["total_carbs_g"] == [300, 450]
    assert long["fluid_ml_per_h"] == [600, 1000] and "not medical advice" in long["label"]
    assert any("560-700 g" in s for s in long["steps"])


# ----------------------------------------------------------- tracking --
def test_status_states_from_start_time_and_garmin() -> None:
    race = ev("e", 0, time="07:00")
    at = lambda h, m=0: datetime.combine(DAY, dtime(h, m))  # noqa: E731
    assert rw.status(race, {}, at(6), [])["state"] == "not_started"
    s = rw.status(race, {}, at(8, 30), [])
    assert s["state"] == "racing" and s["elapsed_s"] == 5400
    assert rw.status(race, {"start_time": "09:00"}, at(8, 30), [])["state"] == "not_started"
    acts = [{"activity_id": 1, "date": f"{DAY} 05:00:00", "name": "Warm-up", "duration": "0:40:00"},   # before start-2h? no
            {"activity_id": 2, "date": f"{DAY} 07:01:00", "name": "Half", "duration": "1:41:07", "distance_km": 21.1},
            {"activity_id": 3, "date": f"{DAY} 07:01:00", "name": "leg", "duration": "2:00:00",
             "multisport": {"parent_id": 9}}]
    s = rw.status(race, {}, at(9), acts)
    assert s["state"] == "finished" and s["result"]["activity_id"] == 2 and s["result"]["time"] == "1:41:07"
    assert rw.status(dict(race, time=None), {}, at(9), [])["state"] == "race_day"
    assert rw.start_time({"info": {"start_time": "Gun at 6:30 am"}}, {}) == "06:30"


def test_tracking_visible_to_mutuals_only(tmp_path, fernet_key) -> None:
    race = ev("e", 0, time="07:00")
    t = _svc(tmp_path, fernet_key, {"ann": [race]},
             clock=Clock(datetime.combine(DAY, dtime(8, 0))))
    soc, svc = t.soc, t.svc
    _follow(soc, "bob", "ann")
    _follow(soc, "ann", "bob")    # bob <-> ann mutual
    _follow(soc, "cat", "ann")    # cat follows ann only
    with pytest.raises(rw.RaceWeekError) as e:
        svc.track("bob", "ann")   # tracking off
    assert e.value.status == 404
    svc.put("ann", "e", {"tracking": True})
    row = svc.track("bob", "ann")
    assert row["state"] == "racing" and row["elapsed_s"] == 3600 and "watch syncs" in row["note"]
    assert [r["user_id"] for r in svc.friends_racing("bob")] == ["ann"]
    for viewer in ("cat", "dan"):
        with pytest.raises(rw.RaceWeekError) as e:
            svc.track(viewer, "ann")
        assert e.value.status == 403
    assert svc.friends_racing("cat") == []
    with pytest.raises(rw.RaceWeekError) as e:
        svc.track(coach_user_id("c@x.com"), "ann")
    assert e.value.status == 403
    assert svc.audience("ann") == ["bob"]
    soc.block("ann", "bob")
    with pytest.raises(rw.RaceWeekError) as e:
        svc.track("bob", "ann")
    assert e.value.status == 403
    assert svc.audience("ann") == []


def test_friend_pushes_at_start_and_finish_once(tmp_path, fernet_key) -> None:
    race = ev("e", 0, time="07:00")
    sent: list[tuple[str, str]] = []
    acts: list[dict[str, Any]] = []
    quiet = {"bob": False}
    t = _svc(tmp_path, fernet_key, {"ann": [race]}, clock=Clock(datetime.combine(DAY, dtime(6, 50))),
             push=lambda to, title, body, url: sent.append((to, title)), activities=lambda u: acts,
             quiet=lambda u: quiet.get(u, False), name=lambda u: u.title())
    _follow(t.soc, "bob", "ann")
    _follow(t.soc, "ann", "bob")
    t.svc.put("ann", "e", {"tracking": True})
    t.clock.at = datetime.combine(DAY, dtime(7, 5))
    assert t.svc.check_start("ann") == "off"            # friends pushes are their own opt-in
    t.svc.put("ann", "e", {"notify_friends": True})
    t.clock.at = datetime.combine(DAY, dtime(6, 50))
    assert t.svc.check_start("ann") == "not_now"
    t.clock.at = datetime.combine(DAY, dtime(7, 5))
    assert t.svc.check_start("ann") == "sent" and sent == [("bob", "Race day")]
    assert t.svc.check_start("ann") == "off"            # once
    assert t.svc.check_finish("ann") == "not_yet"
    acts.append({"activity_id": 7, "date": f"{DAY} 07:00:30", "name": "Half", "duration": "1:50:00"})
    quiet["bob"] = True                                 # bob's quiet hours: no push, still claimed once
    assert t.svc.check_finish("ann") == "sent" and len(sent) == 1
    assert t.svc.check_finish("ann") == "claimed"
    t.svc.put("ann", "e", {"tracking": False})
    assert t.svc.saved("ann", "e")["notify_friends"] is False


# ------------------------------------------------------------ moments --
def test_moment_schedule() -> None:
    at = lambda h, m=0: dtime(h, m)  # noqa: E731
    assert rw.moment_due(7, at(7, 59)) is None and rw.moment_due(7, at(8)) == "week"
    assert rw.moment_due(5, at(12)) == "week" and rw.moment_due(4, at(12)) is None
    assert rw.moment_due(3, at(12)) is None
    assert rw.moment_due(2, at(8)) == "pack"
    assert rw.moment_due(1, at(17, 59)) is None and rw.moment_due(1, at(18)) == "kit"
    assert rw.moment_due(0, at(6, 59)) is None and rw.moment_due(0, at(7)) == "go" and rw.moment_due(0, at(12)) is None
    e = {"id": "e1", "name": "Boston", "main": True, "kind": "race"}
    assert rw.week_moment("kit", e, 1)["key"] == "race:e1:eve" and rw.week_moment("week", e, 6)["key"] == "race:e1:week"
    assert "3/20 packed" in rw.week_moment("pack", e, 2, (3, 20))["text"]
    assert all(len(rw.week_moment(s, e, 1)["text"]) <= 140 for s in ("week", "pack", "kit", "go"))
    # the countdown's week/eve lines are replaced for race-week races only
    assert {race_step(6), race_step(1)} == rw.RaceWeek.skip_countdown(e)
    assert rw.RaceWeek.skip_countdown({"id": "x", "priority": "C", "kind": "race"}) == set()


def test_moments_post_once_with_quiet_hours_and_toggle(env, tmp_path, fernet_key) -> None:
    race = {"id": "e1", "name": "Boston", "date": (DAY + timedelta(days=1)).isoformat(), "main": True,
            "kind": "race", "priority": "A", "type": "running", "distance": "marathon"}
    m, clock, coach, pushes = make(env, datetime.combine(DAY, dtime(17, 0)), events=lambda u: [race])
    m.skip_steps = rw.RaceWeek.skip_countdown
    svc = rw.RaceWeek(env.store, events=lambda u: [race], now=clock.now, follows=lambda a, b: False,
                      blocked=lambda a, b: False, is_athlete=lambda u: True, followers=lambda u: [])
    assert svc.check_moments("friend", m) == "not_now"        # T-1 waits for the evening
    assert m.check_race("friend", DAY) == "skipped"           # the morning race-eve line is replaced
    clock.at = datetime.combine(DAY, dtime(18, 30))
    assert svc.check_moments("friend", m) == "posted"
    assert svc.check_moments("friend", m) == "claimed"
    texts = [t["assistant"] for t in feed(coach)]
    assert len(texts) == 1 and "Lay out your kit" in texts[0]
    assert pushes and pushes[0][1] == "Race eve"
    # race morning: posted, but pushes off when the athlete turned nudges off
    env.store.user_doc("friend", "profile").update(lambda d: d.update(moments_push=False))
    clock.at = datetime.combine(DAY + timedelta(days=1), dtime(7, 30))
    assert svc.check_moments("friend", m) == "posted" and len(pushes) == 1
    # quiet hours queue (Moments.post)
    race2 = dict(race, id="e2", date=(DAY + timedelta(days=12)).isoformat())
    m2, clock2, _, _ = make(env, datetime.combine(DAY + timedelta(days=5), dtime(22, 0)))
    assert m2.post("friend", rw.week_moment("week", race2, 7)) == "queued"


# ---------------------------------------------------------------- http --
def _apps(env, tmp_path):
    agent, _ = env.agent([])
    agent.stats.activities = lambda uid, fresh=False: (agent._now(uid).date(), [])
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW))
    push = FakePush()

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, push, None, ChatRunner(agent)))
    return {u: app(u) for u in ("ann", "bob", coach_user_id("c@x.com"))}, agent


def test_http_card_page_packing_and_coach_403(env, tmp_path) -> None:
    apps, agent = _apps(env, tmp_path)
    today = agent._now("ann").date()
    e = agent.events.create("ann", {"name": "City Half", "type": "running", "distance": "half marathon",
                                    "date": (today + timedelta(days=3)).isoformat(), "priority": "A",
                                    "location": "", "target_time": "1:45:00"})

    async def go() -> None:
        c = {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}
        ann, coach = c["ann"], c[coach_user_id("c@x.com")]
        card = (await ann.get("/app/api/raceweek")).json()["raceweek"]
        assert card["event"]["id"] == e["id"] and card["days"] == 3 and card["packing"]["done"] == 0
        assert (await c["bob"].get("/app/api/raceweek")).json()["raceweek"] is None
        page = (await ann.get(f"/app/api/raceweek/{e['id']}")).json()
        assert page["pacing"]["target"] == "1:45:00" and page["pacing"]["source"] == "goal"
        assert page["pacing"]["splits"]["rows"][-1]["cum_s"] == 6300
        assert page["nutrition"]["carbs_g_per_h"] == [30, 60] and page["tracking"]["on"] is False
        item = page["packing"]["items"][0]["id"]
        r = await ann.post(f"/app/api/raceweek/{e['id']}/packing", headers=H, json={"toggle": item})
        assert r.status_code == 200 and r.json()["done"] == 1
        r = await ann.put(f"/app/api/raceweek/{e['id']}", headers=H, json={"target_s": 6000, "tracking": True})
        assert r.json()["saved"]["target_s"] == 6000
        assert (await ann.put(f"/app/api/raceweek/{e['id']}", headers=H, json={"start_time": "7am"})).status_code == 400
        r = await ann.post(f"/app/api/raceweek/{e['id']}/reminders", headers=H,
                           json={"add": {"text": "Pick up bib", "when": (today + timedelta(days=2)).isoformat()}})
        assert r.json()["reminders"][0]["text"] == "Pick up bib"
        page = (await ann.get(f"/app/api/raceweek/{e['id']}")).json()
        assert page["pacing"]["source"] == "you" and page["packing"]["done"] == 1 and page["tracking"]["on"]
        assert (await c["bob"].get(f"/app/api/raceweek/{e['id']}")).status_code == 404   # not bob's race
        assert (await c["bob"].get("/app/api/raceweek/track/ann")).status_code == 403    # not mutual
        for path in ("/app/api/raceweek", "/app/api/raceweek/friends", "/app/api/raceweek/track/ann",
                     f"/app/api/raceweek/{e['id']}"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.post(f"/app/api/raceweek/{e['id']}/packing", headers=H,
                                 json={"toggle": item})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
