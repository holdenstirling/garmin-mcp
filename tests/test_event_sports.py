"""Event sports (sports.py), public / private events (publicevents.py) and private clubs."""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from pathlib import Path

import httpx2
import pytest

from garmin_mcp import sports
from garmin_mcp.coaching import CoachError
from garmin_mcp.planbuilder import group_session
from garmin_mcp.publicevents import PublicEventError, PublicEvents, next_dates
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import cx  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

ROOT = Path(__file__).resolve().parent.parent
D = date.fromisoformat


def test_catalog_is_mirrored_in_the_web_app() -> None:
    ts = (ROOT / "web" / "src" / "lib" / "sports.ts").read_text()
    ids = re.findall(r"\['([a-z_]+)', '[^']+', '[^']+'\]", ts)
    assert ids == list(sports.IDS)
    assert len(sports.IDS) >= 45 and len(set(sports.IDS)) == len(sports.IDS)
    from garmin_mcp.events import TYPES
    assert all(sports.event_type(i) in TYPES for i in sports.IDS)
    assert {sports.plan_sport(i) for i in sports.IDS} <= {"run", "bike", "swim", "strength", "other"}


def test_event_activity_sets_type_and_validates(env) -> None:
    agent, _ = env.agent([])
    ev = agent.events
    day = (agent._now("friend").date() + timedelta(days=3)).isoformat()
    e = ev.create("friend", {"name": "Baker volleyball", "date": day, "kind": "group_activity",
                             "activity": "volleyball", "time": "18:30", "duration_min": 90})
    assert e["type"] == "team_sport" and e["activity"] == "volleyball"
    assert ev.get("friend", e["id"]).get("visibility") in (None, "private")  # private unless chosen
    e2 = ev.update("friend", e["id"], {"activity": "spin"})
    assert e2["type"] == "cycling"  # the coarse type follows the sport
    e3 = ev.update("friend", e["id"], {"activity": "other", "activity_other": "Cornhole"})
    assert e3["activity_other"] == "Cornhole"
    assert ev.update("friend", e["id"], {"activity": "yoga"})["activity_other"] == ""
    with pytest.raises(CoachError):
        ev.create("friend", {"name": "X", "date": day, "activity": "quidditch"})
    with pytest.raises(CoachError):
        ev.update("friend", e["id"], {"visibility": "friends"})
    assert ev.update("friend", e["id"], {"visibility": "public"})["visibility"] == "public"
    # old events (no activity) keep working
    old = ev.create("friend", {"name": "Old 10K", "date": day, "type": "running", "distance": "10k"})
    assert old.get("activity") is None and old["type"] == "running"


def test_group_session_uses_the_specific_sport() -> None:
    assert group_session({"type": "other", "activity": "hiit", "duration_min": 45})["sport"] == "strength"
    assert group_session({"type": "cycling", "activity": "spin", "duration_min": 45})["sport"] == "bike"
    assert group_session({"type": "team_sport", "activity": "volleyball"})["sport"] == "other"
    assert group_session({"type": "running"})["sport"] == "run"  # no activity: the type as before


class _Store:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def global_doc(self, name: str):
        docs = self.docs

        class Doc:
            def load(self) -> dict:
                return docs.setdefault(name, {})

            def update(self, fn):
                return fn(docs.setdefault(name, {}))
        return Doc()


DEN = {"city": "Denver", "state": "CO"}


def test_public_events_index() -> None:
    blocked = {("cat", "ann"), ("ann", "cat")}
    pe = PublicEvents(_Store(), blocked=lambda a, b: (a, b) in blocked)
    today = D("2026-10-20")
    evs = [
        {"id": "e1", "name": "Baker volleyball", "date": "2026-10-20", "time": "18:30", "activity": "volleyball",
         "recurring": {"freq": "weekly", "weekdays": ["tue"]}, "visibility": "public", "notes": "door code 1234"},
        {"id": "e2", "name": "My secret long run", "date": "2026-10-25", "visibility": "private"},
        {"id": "e3", "name": "Old meetup", "date": "2026-09-01", "visibility": "public"},
        {"id": "e4", "name": "No visibility set", "date": "2026-10-25"},
    ]
    assert pe.sync("ann", evs, DEN) == 2
    rows = pe.nearby("bob", {"city": "denver", "state": "co"}, today)
    assert [r["name"] for r in rows] == ["Baker volleyball"]  # private, unset and past ones never show
    r = rows[0]
    assert r["repeat_text"] and r["next_date"] == "2026-10-20" and r["activity_label"] == "Volleyball"
    assert "notes" not in r and "door code" not in str(r)  # notes stay private
    assert pe.nearby("ann", DEN, today) == []  # not my own
    assert pe.nearby("cat", DEN, today) == []  # blocked either way
    assert pe.nearby("bob", {"city": "Boulder", "state": "CO"}, today) == []  # other city
    assert pe.nearby("bob", DEN, today, q="volley")[0]["key"] == "ann:e1"
    assert pe.nearby("bob", DEN, today, q="pickleball") == []
    assert pe.nearby("bob", DEN, today, activity="soccer") == []
    out = pe.set_going("bob", "ann:e1", True, DEN)
    assert out["going"] == 1 and pe.nearby("bob", DEN, today)[0]["my_going"] is True
    with pytest.raises(PublicEventError):
        pe.set_going("bob", "ann:e2", True, DEN)  # private: not found
    with pytest.raises(PublicEventError):
        pe.set_going("cat", "ann:e1", True, DEN)  # blocked: not found
    # made private again: gone, going cleared
    evs[0]["visibility"] = "private"
    assert pe.sync("ann", evs, DEN) == 1  # only the past one is left, and it never shows
    assert pe.nearby("bob", DEN, today) == []
    assert next_dates({"date": "2026-10-18", "end_date": "2026-10-21"}, today) == ["2026-10-20"]


def test_private_clubs_hidden_from_everyone_but_members(cx) -> None:
    g = cx.grp
    pub = g.create("ann", {"name": "Wash Park Runners", "city": "Denver", "state": "CO"})
    priv = g.create("ann", {"name": "Secret Crew", "city": "Denver", "state": "CO", "visibility": "private"})
    assert pub["visibility"] == "public" and priv["visibility"] == "private"
    names = [c["name"] for c in g.discover("cat", city="Denver", state="CO")]
    assert "Wash Park Runners" in names and "Secret Crew" not in names
    assert [c["name"] for c in g.discover("cat", q="secret")] == []
    with pytest.raises(Exception) as e:
        g.get("cat", priv["id"])
    assert getattr(e.value, "status", None) == 404
    with pytest.raises(Exception):
        g.join("cat", priv["id"])  # no request to join a private club
    assert g.featured_card(priv["id"], "cat", cx.clock.at) is None
    # the club code still works (invite only)
    code = g.get("ann", priv["id"])["code"]
    assert g.join("cat", code=code)["role"] == "member"
    assert g.get("cat", priv["id"])["name"] == "Secret Crew"
    with pytest.raises(Exception):
        g.update("ann", priv["id"], {"visibility": "hidden"})


def test_public_events_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    friend_app, coach_app, other_app = _apps(env, tmp_path, agent)
    h = {"origin": BASE}
    day = (agent._now("friend").date() + timedelta(days=2)).isoformat()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=friend_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            for cl in (a, o):
                r = await cl.put("/app/api/athlete", headers=h, json={"home_location": "Denver, CO"})
                assert r.status_code == 200, r.text
            r = await a.post("/app/api/events", headers=h, json={
                "name": "Baker volleyball", "date": day, "kind": "group_activity", "activity": "volleyball",
                "time": "18:30", "visibility": "public", "neighborhood": "Baker, Denver",
                "recurring": {"freq": "weekly", "weekdays": [D(day).strftime("%a").lower()[:3]]}})
            assert r.status_code == 201, r.text
            r = await a.post("/app/api/events", headers=h, json={"name": "Private tempo", "date": day})
            assert r.status_code == 201
            r = await o.get("/app/api/events/public")
            assert r.status_code == 200, r.text
            rows = r.json()["events"]
            assert [x["name"] for x in rows] == ["Baker volleyball"] and r.json()["area"] == "Denver, CO"
            key = rows[0]["key"]
            assert (await a.get("/app/api/events/public")).json()["events"] == []  # not my own
            r = await o.get("/app/api/events/public?activity=nope")
            assert r.status_code == 400, (r.status_code, r.text)
            r = await o.post("/app/api/events/public/going", headers=h, json={"key": key, "going": True})
            assert r.status_code == 200 and r.json()["going"] == 1
            r = await o.post("/app/api/events/public/going", headers=h, json={"key": "friend:nope", "going": True})
            assert r.status_code == 404
            r = await o.get("/app/api/search?q=volleyball")
            assert any(e.get("public") for e in r.json()["events"])
            r = await o.get("/app/api/search?q=tempo")
            assert not any("tempo" in (e.get("title") or "").lower() for e in r.json()["events"])
            assert (await c.get("/app/api/events/public")).status_code == 403
    asyncio.run(go_())
