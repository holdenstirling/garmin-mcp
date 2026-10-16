"""Search everywhere (search.py, GET /app/api/search)."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from garmin_mcp.coaches import coach_user_id
from garmin_mcp.search import PER_GROUP, Search, matches, norm
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _setup
from tests.test_social import H

TODAY = date(2026, 10, 14)


def _plan():
    days = {}
    for i in range(14):
        d = (TODAY + timedelta(days=i - 7)).isoformat()
        days[d] = [{"id": f"s{i}", "sport": "run", "kind": "tempo" if i % 2 else "easy",
                    "title": "Tempo run" if i % 2 else "Easy run", "minutes": 40}]
    days[TODAY.isoformat()].append({"id": "r", "sport": "rest", "kind": "rest", "title": "Rest"})
    return {"weeks": [{"start": (TODAY - timedelta(days=7)).isoformat(), "days": days}]}


def _search(**kw):
    base = dict(
        today=lambda u: TODAY,
        people=lambda u: {"following": [{"user_id": "bob"}, {"user_id": "zed"}], "followers": [{"user_id": "bob"}]},
        person=lambda o: {"id": o, "name": o.title()},
        clubs=lambda u, q: {"clubs": [{"id": "c1", "name": "Boulder Track Club", "city": "Boulder", "members": 4}],
                            "discover": [{"id": "c2", "name": "Denver Trail Runners", "city": "Denver", "members": 9}]},
        directory=lambda u: [{"id": "L1", "name": "Track Tuesdays", "kind_label": "Run club", "meet_spot": "CU track"}],
        events=lambda u: [{"id": "e1", "name": "Boulder 70.3", "date": "2027-06-06", "location": "Boulder, CO"},
                          {"id": "e2", "name": "Bolder Boulder 10K", "date": "2026-05-25", "location": "Boulder"},
                          {"id": "e3", "name": "Boulder Marathon", "date": "2026-11-01", "location": "Boulder"}],
        plan=lambda u: _plan(),
        activities=lambda u: [{"activity_id": 1, "date": "2026-10-10 07:00:00", "sport": "running", "name": "Morning Run",
                               "duration": 3600, "distance_km": 10},
                              {"activity_id": 2, "date": "2026-10-12", "sport": "cycling", "name": "Canyon ride",
                               "duration": 7200, "distance_km": 50}],
    )
    base.update(kw)
    return Search(**base)


def test_helpers() -> None:
    assert norm("  Tempo   RUN ") == "tempo run"
    assert matches(["tempo", "run"], "Tempo run", None) and not matches(["tempo", "swim"], "Tempo run")


def test_too_short_returns_empty_groups() -> None:
    r = _search().run("ann", " t ")
    assert r["q"] == "t" and all(r[g] == [] for g in ("people", "clubs", "events", "sessions", "workouts"))


def test_groups_match_case_insensitive() -> None:
    s = _search()
    r = s.run("ann", "BOB")
    assert [p["id"] for p in r["people"]] == ["bob"] and r["people"][0]["relation"] == "following"
    r = s.run("ann", "track")
    assert [(c["id"], c["source"], c["mine"]) for c in r["clubs"]] == [("c1", "club", True), ("L1", "directory", False)]
    r = s.run("ann", "boulder")
    assert [e["id"] for e in r["events"]] == ["e3", "e1", "e2"]  # upcoming soonest, then past
    assert r["events"][2]["past"] is True
    r = s.run("ann", "tempo")
    assert len(r["sessions"]) == PER_GROUP and r["sessions"][0]["title"] == "Tempo run"
    gaps = [abs((date.fromisoformat(x["date"]) - TODAY).days) for x in r["sessions"]]
    assert gaps == sorted(gaps)
    assert s.run("ann", "rest")["sessions"] == []  # rest days aren't sessions to find
    r = s.run("ann", "ride")
    assert [w["id"] for w in r["workouts"]] == [2] and r["workouts"][0]["km"] == 50
    assert [w["id"] for w in s.run("ann", "run")["workouts"]] == [1]


def test_failing_source_only_empties_its_group() -> None:
    def boom(u):
        raise RuntimeError("garmin down")
    r = _search(activities=boom, people=boom).run("ann", "run")
    assert r["workouts"] == [] and r["people"] == [] and r["sessions"]


def test_http_search_and_coach_403(env, tmp_path) -> None:  # noqa: F811
    apps, _push, _agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob = c["ann"], c["bob"]
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        r = (await bob.get("/app/api/search", params={"q": "an"})).json()
        assert [p["name"] for p in r["people"]] == ["Ann"]
        assert (await ann.get("/app/api/search", params={"q": "zzz"})).json()["people"] == []
        r = (await ann.get("/app/api/search", params={"q": "run"})).json()
        assert set(r) >= {"people", "clubs", "events", "sessions", "workouts"}
        assert (await c[coach_user_id("c@x.com")].get("/app/api/search", params={"q": "ann"})).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
