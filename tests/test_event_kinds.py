"""Event kinds (race, group activity, trip, challenge, life event, other) in the store and the
plan, plus Find a coach "Near you | Anywhere" and coaches from the web."""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp import coachweb, geo
from garmin_mcp.coachdir import (
    SEED_COACHES,
    CoachDirectory,
    distance_label,
    public_view,
)
from garmin_mcp.coaching import CoachError
from garmin_mcp.events import EventStore, context_label, is_race, kind_of
from garmin_mcp.moments import race_moment
from garmin_mcp.planbuilder import build_plan, iter_sessions
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_coachdir import _apps

BASE = "http://localhost:8001"
H = {"origin": BASE}
TODAY = date(2026, 10, 14)
GOAL = {"title": "Boulder 70.3", "date": "2027-06-26", "distance": "70.3"}


def _athlete():
    return {"weekly_hours": 8, "level": "intermediate",
            "available_days": ["tue", "wed", "thu", "sat", "sun"], "long_day": "sat"}


def _days(plan):
    return {d: ss for w in plan["weeks"] for d, ss in w["days"].items()}


# ------------------------------------------------------------------ store --
def test_kinds_validate_and_old_events_are_races(env) -> None:
    agent, _ = env.agent([])
    ev: EventStore = agent.events
    old = ev.create("u", {"name": "Bolder Boulder", "date": "2027-05-31", "type": "running"})
    assert old["kind"] == "race" and is_race(old)
    # An event saved before kinds existed has no "kind" at all: still a race.
    env.store.user_doc("u", "events").update(lambda d: d["events"][old["id"]].pop("kind"))
    assert ev.get("u", old["id"])["kind"] == "race" and kind_of({}) == "race"
    with pytest.raises(CoachError, match="kind"):
        ev.create("u", {"name": "X", "date": "2027-01-01", "kind": "party"})
    with pytest.raises(CoachError, match="time"):
        ev.create("u", {"name": "X", "date": "2027-01-01", "kind": "group_activity", "time": "6pm"})
    with pytest.raises(CoachError, match="end date"):
        ev.create("u", {"name": "Hut trip", "date": "2027-02-10", "end_date": "2027-02-08", "kind": "trip"})
    with pytest.raises(CoachError, match="30 days"):
        ev.create("u", {"name": "Long trip", "date": "2027-02-10", "end_date": "2027-04-10", "kind": "trip"})
    with pytest.raises(CoachError, match="weekday"):
        ev.create("u", {"name": "League", "date": "2027-01-05", "kind": "group_activity",
                        "recurring": {"weekday": "someday", "until": "2027-03-01"}})
    with pytest.raises(CoachError, match="duration"):
        ev.create("u", {"name": "Ride", "date": "2027-01-05", "kind": "group_activity", "duration_min": 5})
    long = ev.create("u", {"name": "Ride", "date": "2027-01-05", "kind": "group_activity", "with": "x" * 200})
    assert len(long["with"]) == 80  # capped like every other text field
    ev.delete("u", long["id"])
    g = ev.create("u", {"name": "Tuesday group ride", "date": "2027-01-05", "kind": "group_activity",
                        "type": "cycling", "time": "18:00", "duration_min": 90, "with": "Golden Cyclery",
                        "at": "Golden", "recurring": {"weekday": "tue", "until": "2027-03-30"}})
    assert g["recurring"] == {"weekday": "tue", "until": "2027-03-30"} and not is_race(g)
    assert context_label(g, None) == "group activity, weekly on tue until 2027-03-30"
    assert context_label(old, None) == "B race" and context_label(old, old["id"]) == "MAIN goal"
    # Only races and challenges can be the main event.
    with pytest.raises(CoachError, match="main event"):
        ev.set_main("u", g["id"])
    ev.set_main("u", old["id"])
    with pytest.raises(CoachError, match="main event"):
        ev.update("u", old["id"], {"kind": "milestone"})
    ch = ev.create("u", {"name": "Longs Peak", "date": "2027-08-01", "kind": "challenge", "type": "mountaineering"})
    assert ev.set_main("u", ch["id"])["main"] is True


def test_signature_is_unchanged_for_old_events(env) -> None:
    agent, _ = env.agent([])
    ev: EventStore = agent.events
    a = ev.create("u", {"name": "Tune-up 10K", "date": "2027-03-06", "type": "running", "priority": "C"})
    pe = ev.plan_events("u")
    assert pe == [{"id": a["id"], "name": "Tune-up 10K", "type": "running", "date": "2027-03-06",
                   "priority": "C", "distance": ""}]
    import hashlib
    import json
    legacy = hashlib.sha256(json.dumps(sorted([(a["id"], "2027-03-06", "C", "running")])).encode()).hexdigest()[:16]
    assert EventStore.signature(pe) == legacy  # plans built before kinds don't ask for a rebuild
    ev.update("u", a["id"], {"kind": "challenge"})
    assert EventStore.signature(ev.plan_events("u")) != legacy


# ------------------------------------------------------------------- plan --
def test_group_activity_occurrences_become_sessions() -> None:
    events = [{"id": "g1", "name": "Tuesday group ride", "type": "cycling", "date": "2027-03-02",
               "kind": "group_activity", "duration_min": 90, "with": "Golden Cyclery", "time": "18:00",
               "recurring": {"weekday": "tue", "until": "2027-03-23"}}]
    plan = build_plan(_athlete(), GOAL, today=TODAY, events=events)
    days = _days(plan)
    for d in ("2027-03-02", "2027-03-09", "2027-03-16", "2027-03-23"):
        g = [s for s in days[d] if s.get("event_id") == "g1"]
        assert len(g) == 1, d
        s = g[0]
        assert s["sport"] == "bike" and s["minutes"] == 90 and s["title"] == "Group: Tuesday group ride"
        assert s["steps"] == [{"type": "steady", "minutes": 90, "zone": 3}]  # moderate by default
        assert "Golden Cyclery" in s["detail"] and "Moderate effort" in s["detail"]
        assert not any(x["sport"] in ("rest", "bike") and x is not s for x in days[d])
    assert not any(s.get("event_id") == "g1" for s in days["2027-03-30"])
    assert plan["events"] == [{"id": "g1", "name": "Tuesday group ride", "date": "2027-03-02",
                               "kind": "group_activity", "priority": None, "occurrences": 4}]
    # No race taper around it and the A race is untouched.
    assert sum(1 for _, _, s in iter_sessions(plan) if s.get("kind") == "race") == 1


def test_trip_reduces_volume_and_milestone_rests() -> None:
    base = build_plan(_athlete(), GOAL, today=TODAY)
    events = [{"id": "t1", "name": "Hut trip", "type": "other", "date": "2027-02-12", "end_date": "2027-02-14",
               "kind": "trip"},
              {"id": "m1", "name": "Wedding", "type": "other", "date": "2027-04-10", "kind": "milestone"}]
    plan = build_plan(_athlete(), GOAL, today=TODAY, events=events)
    before, after = _days(base), _days(plan)
    for d in ("2027-02-12", "2027-02-13", "2027-02-14"):
        mins = sum(s.get("minutes") or 0 for s in after[d] if s["sport"] != "rest")
        assert mins <= 45 * len(after[d]) and mins <= sum(s.get("minutes") or 0 for s in before[d] if s["sport"] != "rest")
        assert all(s["sport"] == "rest" or s.get("kind") in ("easy", "strength", "mobility") for s in after[d])
    assert sum(s.get("minutes") or 0 for d in ("2027-02-12", "2027-02-13", "2027-02-14") for s in after[d]) < \
        sum(s.get("minutes") or 0 for d in ("2027-02-12", "2027-02-13", "2027-02-14") for s in before[d])
    w = after["2027-04-10"]
    assert len(w) == 1 and w[0]["sport"] == "rest" and w[0]["title"] == "Rest: Wedding"
    for d in ("2027-04-09", "2027-04-11"):
        assert len(after[d]) == 1 and (after[d][0]["sport"] == "rest" or (after[d][0].get("minutes") or 0) <= 30)
    kinds = {e["id"]: (e["kind"], e.get("end_date")) for e in plan["events"]}
    assert kinds == {"t1": ("trip", "2027-02-14"), "m1": ("milestone", "2027-04-10")}


def test_challenge_is_like_a_c_race_and_group_skips_milestone_days() -> None:
    events = [{"id": "c1", "name": "Longs Peak", "type": "mountaineering", "date": "2027-03-13", "kind": "challenge",
               "priority": "A"},
              {"id": "m1", "name": "Moving day", "type": "other", "date": "2027-03-16", "kind": "milestone"},
              {"id": "g1", "name": "Track night", "type": "running", "date": "2027-03-16", "kind": "group_activity",
               "intensity": "hard", "duration_min": 60}]
    plan = build_plan(_athlete(), GOAL, today=TODAY, events=events)
    days = _days(plan)
    c = days["2027-03-13"][0]
    assert c["kind"] == "race" and c["title"] == "Challenge: Longs Peak" and "challenge" in c["detail"]
    assert days["2027-03-12"][0]["kind"] == "easy"  # C-race prep, no taper
    assert days["2027-03-16"][0]["sport"] == "rest"  # the move wins over track night
    assert {e["id"] for e in plan["events"]} == {"c1", "m1"}
    assert next(e for e in plan["events"] if e["id"] == "c1")["priority"] == "C"


def test_challenge_main_moment_has_no_race_actions() -> None:
    m = race_moment({"id": "e", "name": "Longs Peak", "kind": "challenge"}, 6)
    assert m["actions"] == [] and "Race week" not in m["text"]
    assert [a["id"] for a in race_moment({"id": "e", "name": "Boston"}, 6)["actions"]] == ["readiness", "racepack"]


def test_readiness_and_predict_are_for_races_only(env, tmp_path) -> None:
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    g = agent.events.create("friend", {"name": "Group ride", "kind": "group_activity", "type": "cycling",
                                       "date": (today + timedelta(days=10)).isoformat()})
    app, _ = _apps(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as a:
            r = await a.get(f"/app/api/events/{g['id']}/readiness")
            assert r.status_code == 400 and "races" in r.json()["error"]
            assert (await a.get("/app/api/readiness")).json()["races"] == []
            r = await a.get(f"/app/api/events/{g['id']}/predict")
            assert r.status_code == 400 and "races" in r.json()["error"]
            lst = (await a.get("/app/api/events")).json()
            assert lst["events"][0]["kind"] == "group_activity" and "milestone" in lst["kinds"]
            r = await a.post("/app/api/events", headers=H, json={"name": "Wedding", "kind": "milestone",
                                                                  "date": (today + timedelta(days=40)).isoformat(),
                                                                  "main": True})
            assert r.status_code == 400
            assert [e["name"] for e in (await a.get("/app/api/events")).json()["events"]] == ["Group ride"]
    asyncio.run(go_())


# ------------------------------------------------------------------ coaches --
def test_distance_labels_are_coarse() -> None:
    assert distance_label(2.2) == "Under 5 mi from you"
    assert distance_label(13.4) == "~15 mi from you"
    assert distance_label(41) == "~40 mi from you"
    assert distance_label(180) == "~175 mi from you"


def test_local_and_remote_scopes(env) -> None:
    d = CoachDirectory(env.store)
    bill = SEED_COACHES[0]
    assert public_view(bill)["remote"] is None  # unknown: never claimed
    remote = dict(bill, id="r-coach", name="Remote Rita", location="Austin, Texas", remote=True)
    inperson = dict(bill, id="p-coach", name="Pat Local", location="Denver, Colorado", remote=False,
                    lat=39.74, lon=-104.99)
    env.store.global_doc("coach_directory").update(lambda x: x.__setitem__("coaches", [bill, remote, inperson]))
    denver = (39.74, -104.99)
    coords = {"bill-ludington": (39.76, -105.22), "r-coach": (30.27, -97.74)}
    near = d.search({}, None, scope="local", within_mi=25, origin=denver, coords=coords)
    assert [c["id"] for c in near] == ["p-coach", "bill-ludington"]
    assert near[0]["distance_label"] == "Under 5 mi from you" and near[1]["distance_label"] == "~10 mi from you"
    assert [c["id"] for c in d.search({}, None, scope="local", within_mi=10, origin=denver, coords=coords)] == ["p-coach"]
    assert [c["id"] for c in d.search({}, None, scope="local", fmt="remote", origin=denver, coords=coords)] == []
    # Anywhere: everyone except coaches recorded as in-person only.
    assert {c["id"] for c in d.search({}, None, scope="remote")} == {"bill-ludington", "r-coach"}
    assert [c["id"] for c in d.search({}, None, scope="remote", fmt="remote")] == ["r-coach"]
    # No saved location: "Near you" falls back to the home state, with no distance claimed.
    st = d.search({}, None, scope="local", home_state="CO")
    assert {c["id"] for c in st} == {"bill-ludington", "p-coach"} and all(c["distance_label"] is None for c in st)
    with pytest.raises(CoachError):
        d.search({}, None, scope="local", within_mi=7)
    with pytest.raises(CoachError):
        d.search({}, None, scope="mars")


def test_web_results_need_https_and_carry_no_contacts() -> None:
    raw = {"coaches": [
        {"name": "Mile High Tri Coaching", "specialty": "70.3 & Ironman", "area": "Denver",
         "url": "https://mhtc.example.com/?utm_source=x"},
        {"name": "No Link Coach", "specialty": "Run"},
        {"name": "Plain HTTP", "url": "http://insecure.example.com"},
        {"name": "Call Carl 303-555-1234", "specialty": "email carl@example.com", "url": "https://carl.example.com"},
    ]}
    out = coachweb.clean(raw)
    assert [c["name"] for c in out] == ["Mile High Tri Coaching", "Call Carl"]
    assert out[0]["url"] == "https://mhtc.example.com/" and out[0]["source"] == "web"
    assert out[0]["label"] == "From the web — not verified by rabbt"
    assert "@" not in out[1]["specialty"] and "555" not in out[1]["name"]
    assert set(out[0]) == {"id", "name", "specialty", "area", "url", "source", "label"}


def test_web_api_privacy_cache_and_coach_403(env, tmp_path) -> None:
    agent, _ = env.agent([])
    prompts: list[tuple[str, str]] = []

    async def research(system: str, prompt: str, **kw):
        prompts.append((system, prompt))
        assert kw["report_tool"]["name"] == "report_coaches"
        return {"coaches": [{"name": "Golden Tri Club", "specialty": "Triathlon", "area": "Golden",
                             "url": "https://goldentri.example.org"}, {"name": "No URL"}]}
    agent._backend.research = research  # type: ignore[attr-defined]
    agent.coach.update_athlete("friend", {"home_location": "Denver, CO 80204", "injuries": "sore knee"})
    geo.save_location(env.store, "friend", {"city": "Denver", "state": "CO", "zip": "80204"},
                      39.7392, -104.9903, "device", time.time())
    # Golden's centroid is already in the geocode cache (no network in tests).
    env.store.global_doc("geocache").update(lambda d: d.__setitem__(
        "c:golden|CO", {"ts": time.time(), "v": {"city": "Golden", "state": "CO", "zip": "", "country": "us",
                                                  "lat": 39.76, "lon": -105.22}}))
    app, coach = _apps(env, agent, tmp_path)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach), base_url=BASE) as c:
            r = (await a.get("/app/api/coaches/directory?scope=local&within=25")).json()
            assert r["has_location"] is True and r["coaches"][0]["distance_label"] == "~10 mi from you"
            assert "39.7" not in str(r) and "-104.9" not in str(r)  # the athlete's spot never comes back
            assert (await a.get("/app/api/coaches/directory?scope=local&within=3")).status_code == 400
            r = await a.post("/app/api/coaches/directory/web", headers=H, json={"sport": "triathlon"})
            body = r.json()
            assert r.status_code == 200 and body["state"] == "ok" and body["area"] == "Denver, CO"
            assert [x["name"] for x in body["coaches"]] == ["Golden Tri Club"]
            # Second ask: the shared cache, no new search.
            await a.post("/app/api/coaches/directory/web", headers=H, json={"sport": "triathlon"})
            assert len(prompts) == 1
            p = prompts[0][1]
            assert "Denver, CO" in p and "triathlon" in p
            for secret in ("80204", "39.7", "104.9", "knee", "Friend", "friend"):
                assert secret not in p
            assert (await a.post("/app/api/coaches/directory/web", headers=H,
                                 json={"sport": "curling"})).status_code == 400
            # Coach accounts can't use it.
            assert (await c.post("/app/api/coaches/directory/web", headers=H, json={})).status_code == 403
            assert (await c.get("/app/api/coaches/directory?scope=remote")).status_code == 403
    asyncio.run(go_())


def test_web_cache_is_seven_days(env) -> None:
    now = [1000.0]
    f = coachweb.CoachWebFinder(env.store, clock=lambda: now[0])

    async def research(system, prompt, **kw):
        return {"coaches": [{"name": "A", "url": "https://a.example.org"}]}
    asyncio.run(f.find(research, "running", "Golden", "CO"))
    assert coachweb.CoachWebFinder(env.store, clock=lambda: now[0]).cached("running", "golden", "co")[0]["name"] == "A"
    assert f.cached("cycling", "Golden", "CO") is None
    now[0] += 7 * 86400 + 1
    assert f.cached("running", "Golden", "CO") is None
