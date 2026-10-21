"""Traction counts (traction.py): firsts once per person, activation within 7 days, week-4
retention of activated people, sources, referrals, the day-7 recommend pulse, organizer health,
Denver share, and the API (owner-only summary, opt-outs, city/zip area)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx2
import pytest

from garmin_mcp import traction, usage
from garmin_mcp.appstore import AppStore
from garmin_mcp.tokens import generate_key
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_usage import BASE, DAY0, H, Clock, _app


@pytest.fixture
def tr(tmp_path):
    clock = Clock()
    store = AppStore(tmp_path, generate_key())
    area: dict[str, tuple[float, float]] = {}
    return traction.Traction(store, clock=clock, area_of=area.get), clock, store, area


def test_firsts_count_once_and_activation(tr) -> None:
    t, clock, _, _ = tr
    assert t.first("a", "area_set") is True
    assert t.first("a", "area_set") is False          # once per person
    assert t.first("a", "bogus") is False
    t.first("a", "rsvp")
    t.first("a", "plan_built")
    t.active("b")                                     # signed up, did nothing
    clock.days(8)
    t.first("b", "plan_built")                        # core job, but after day 7
    s = t.summary()
    f = {x["id"]: x["users"] for x in s["activation"]["funnel"]}
    assert f == {"signup": 2, "area_set": 1, "job": 1, "plan_built": 2}
    assert s["activation"]["core7"] == {"cohort": 2, "users": 1, "pct": 50}
    assert s["activation"]["firsts"]["rsvp"] == 1


def test_joined_uses_usage_first_day(tmp_path) -> None:
    clock = Clock()
    store = AppStore(tmp_path, generate_key())
    t = traction.Traction(store, clock=clock)
    store.user_doc("old", "usage").save({"first": (date(2026, 3, 2) - timedelta(days=40)).isoformat(), "last": "x"})
    t.first("old", "rsvp")
    g = store.global_doc("traction").load()["cohorts"]
    assert list(g) == ["2026-01-21"] and g["2026-01-21"]["core"] == 1 and "core7" not in g["2026-01-21"]


def test_week4_retention_of_activated(tr) -> None:
    t, clock, _, _ = tr
    t.first("a", "rsvp")
    t.first("b", "run_posted")
    t.active("c")
    clock.days(22)
    t.active("a")                                     # back in week 4
    t.active("c")                                     # not activated: not counted
    clock.days(10)
    s = t.summary()
    assert s["retention"]["w4"] == {"cohort": 2, "users": 1, "pct": 50}


def test_events_map_to_firsts_and_refs(tr) -> None:
    t, clock, store, _ = tr
    t.active("n", ref="club:mile-high-run-club")
    t.active("n", ref="club:mile-high-run-club")      # once
    t.from_events("n", [("rsvp", {"kind": "group"}), ("share", {"what": "post"}),
                        ("milestone", {"what": "follow"}), ("setup_complete", {})])
    s = t.summary()
    assert s["growth"]["club_refs"] == [{"slug": "mile-high-run-club", "users": 1}]
    assert s["activation"]["firsts"]["rsvp"] == 1 and s["activation"]["firsts"]["post"] == 1
    assert s["activation"]["firsts"]["follow"] == 1 and s["activation"]["firsts"]["plan_built"] == 1
    mine = store.user_doc("n", "traction").load()
    assert set(mine) <= {"joined", "firsts", "job", "core", "w4", "week", "src", "pulse", "ref"}


def test_sources_and_pulse(tr) -> None:
    t, clock, store, _ = tr
    t.set_source("a", "instagram")
    t.set_source("a", "friend")                       # own answer changes, tally doesn't double
    with pytest.raises(ValueError):
        t.set_source("a", "my cousin Bob")
    s = t.summary()["growth"]
    assert {x["id"]: x["users"] for x in s["sources"]}["instagram"] == 1 and s["answered"] == 1
    t.active("a")
    assert t.pulse_due("a") is False
    clock.days(7)
    assert t.pulse_due("a") is True
    t.pulse("a", 9, "  Love the club runs  ", name="Ana Smith")
    assert t.pulse_due("a") is False
    t.pulse("a", 0)                                   # asked once
    t.active("b")
    clock.days(7)
    t.pulse("b", None)                                # dismissed
    assert t.pulse_due("b") is False
    with pytest.raises(ValueError):
        t.pulse("c", 11)
    n = t.summary()["nps"]
    assert n["answers"] == 1 and n["score"] == 100 and n["hist"][9] == 1
    assert t.summary()["notes"] == [{"name": "Ana", "score": 9, "note": "Love the club runs", "date": "2026-03-09"}]
    t.forget("a")
    assert t.summary()["notes"] == [] and store.user_doc("a", "traction").load() == {}


def test_nps_math() -> None:
    assert traction.nps_of({"10": 3, "8": 1, "2": 1})["score"] == 40
    assert traction.nps_of({})["score"] is None


def test_denver_share(tr) -> None:
    t, clock, _, area = tr
    area["d"] = (39.68, -104.94)      # Denver
    area["b"] = (40.02, -105.27)      # Boulder: inside the 48 km metro
    area["s"] = (39.19, -106.82)      # Aspen
    for u in ("d", "b", "s", "x"):
        t.active(u)
    clock.days(7)
    s = t.summary()["denver"]
    assert s["active"] == 2 and s["runners"] == 94_000 and s["known_clubs"] == 26
    assert traction.in_denver(39.74, -104.99) and not traction.in_denver("x", None)


def test_organizers_weekly() -> None:
    today = date(2026, 3, 18)  # Wednesday
    last_mon = date(2026, 3, 9)
    ts = datetime(2026, 3, 10, tzinfo=UTC).timestamp()
    hist = {(last_mon + timedelta(days=1)).isoformat(): {"going": 10, "checkins": 8},
            (last_mon + timedelta(days=3)).isoformat(): {"going": 8, "checkins": 4}}
    clubs = {"clubs": {
        "c1": {"created": ts, "city": "Denver", "state": "CO", "slug": "c1",
               "meetups": {"m": {"created": ts, "history": hist, "regulars": {"u1": 2, "u2": 1, "g:x": 3}}}},
        "c2": {"created": ts - 60 * 86400, "city": "Austin", "state": "TX",
               "meetups": {"m": {"created": ts, "history": {"2026-03-12": {"going": 3, "checkins": 3}}}}},
    }}
    o = traction.organizers(clubs, today)
    w = o["weeks"][-1]
    assert w["clubs_created"] == 1 and w["runs_posted"] == 2 and w["runs_held"] == 3
    assert w["rsvps_per_run"] == 7.0 and w["checkin_pct"] == 71
    assert o["healthy_clubs"] == 1 and o["repeat_attendees"] == 2
    assert traction.denver_clubs(clubs) == 1


def test_milestone_event_whitelisted() -> None:
    ts = int(DAY0 * 1000)
    assert usage.clean_event({"name": "milestone", "props": {"what": "area_set"}, "ts": ts}, DAY0) == \
        ("milestone", {"what": "area_set"})
    assert usage.clean_event({"name": "milestone", "props": {"what": "Denver"}, "ts": ts}, DAY0) == ("milestone", {})


def test_api_traction_heard_pulse(env, tmp_path) -> None:  # noqa: F811
    owner, me = _app(env, tmp_path, "friend"), _app(env, tmp_path, "holden")
    now = int(datetime.now(UTC).timestamp() * 1000)
    body = {"events": [{"name": "milestone", "props": {"what": "area_set"}, "ts": now},
                       {"name": "rsvp", "props": {"kind": "meetup"}, "ts": now}]}

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=owner), base_url=BASE) as o, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=me), base_url=BASE) as n:
            # DNT: nothing reaches traction either
            await n.post("/app/api/usage", headers={**H, "DNT": "1"}, json=body)
            assert env.store.user_doc("holden", "traction").load() == {}
            n.cookies.set("rb_ref", "club:mile-high", domain="localhost", path="/app")
            assert (await n.post("/app/api/usage", headers=H, json=body)).json()["counted"] == 2
            assert set(env.store.user_doc("holden", "traction").load()["firsts"]) == {"area_set", "rsvp"}
            assert (await n.post("/app/api/heard", headers=H, json={"source": "nope"})).status_code == 400
            assert (await n.post("/app/api/heard", headers=H, json={"source": "club"})).json() == {"ok": True}
            assert (await n.get("/app/api/pulse")).json() == {"ask": False}   # day 0
            assert (await n.get("/app/api/usage/traction")).status_code == 403
            s = (await o.get("/app/api/usage/traction")).json()
            assert s["activation"]["firsts"]["area_set"] == 1
            assert {x["id"]: x["users"] for x in s["growth"]["sources"]}["club"] == 1
            assert s["growth"]["club_refs"] == [{"slug": "mile-high", "users": 1}]
            assert s["targets"]["core7_pct"] == 40
            assert (await n.post("/app/api/pulse", headers=H, json={"dismiss": True})).json() == {"ok": True}
            assert (await n.post("/app/api/pulse", headers=H, json={"score": "ten"})).status_code == 400
            # "Don't count my usage": the source answer isn't tallied
            await n.put("/app/api/settings", headers=H, json={"usage_off": True})
            await n.post("/app/api/heard", headers=H, json={"source": "strava"})
            s = (await o.get("/app/api/usage/traction")).json()
            assert {x["id"]: x["users"] for x in s["growth"]["sources"]}["strava"] == 0
            # a city needs its state
            r = await n.post("/app/api/location", headers=H, json={"place": "Denver"})
            assert r.status_code == 400 and "state" in r.json()["error"]
    asyncio.run(go())


def test_club_page_sets_ref_cookie_only_for_valid_slug() -> None:
    import re
    assert re.fullmatch(r"club:[a-z0-9-]{1,60}", "club:mile-high-run-club")
    assert not re.fullmatch(r"club:[a-z0-9-]{1,60}", "club:<script>")


def test_api_newcomer_checklist_tips_and_first_week(env, tmp_path) -> None:  # noqa: F811
    me = _app(env, tmp_path, "holden")

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=me), base_url=BASE) as n:
            nc = (await n.get("/app/api/me")).json()["newcomer"]
            assert nc["steps"] == {"area": False, "job": False, "plan": False}
            assert nc["since"] and nc["tips"] == [] and nc["show_all"] is False
            if nc["since"] != "existing":
                assert nc["first_week"] is True and nc["days"] == 0
            assert (await n.post("/app/api/newcomer", headers=H, json={"tip": "bogus"})).status_code == 400
            assert (await n.post("/app/api/newcomer", headers=H, json={"done": "plan"})).status_code == 400
            r = (await n.post("/app/api/newcomer", headers=H, json={"tip": "near_me"})).json()
            r = (await n.post("/app/api/newcomer", headers=H, json={"tip": "near_me", "done": "job"})).json()
            assert r["tips"] == ["near_me"] and r["steps"]["job"] is True
            r = (await n.post("/app/api/newcomer", headers=H, json={"show_all": True})).json()
            assert r["show_all"] is True and r["first_week"] is False
            assert (await n.get("/app/api/me")).json()["newcomer"]["since"] == nc["since"]  # stamped once
    asyncio.run(go())
