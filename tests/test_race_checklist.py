"""Race checklist (racechecklist.py): timeline items per race type, stable ids, state and HTTP."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2

from garmin_mcp import racechecklist as rc
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

TODAY = date(2026, 10, 17)


def _ev(**kw):
    base = {"id": "e1", "name": "Race", "date": (TODAY + timedelta(weeks=10)).isoformat(), "kind": "race",
            "type": "running", "distance": "half marathon", "priority": "A"}
    return base | kw


def test_items_match_the_race() -> None:
    tri = rc.template(_ev(type="triathlon", distance="70.3"))
    texts = " ".join(i["text"] for i in tri)
    assert "transition" in texts.lower() and "Wetsuit" in texts and "bike serviced" in texts.lower()
    ultra = rc.template(_ev(name="Leadville Trail 100 Run", type="trail", distance="ultra", location="Leadville, CO"))
    t = " ".join(i["text"] for i in ultra)
    assert "crew" in t.lower() and "drop bags" in t.lower() and "cutoffs" in t.lower()
    assert any("altitude" in i["text"].lower() for i in ultra)  # Leadville is at altitude
    road5k = rc.template(_ev(distance="5k"))
    assert not any("Carb-load" in i["text"] for i in road5k)  # short race: no carb-loading
    assert any("Carb-load" in i["text"] for i in rc.template(_ev(distance="marathon")))
    assert all(i["bucket"] in rc.BUCKET_IDS for i in tri + ultra + road5k)
    ids = [i["id"] for i in tri]
    assert len(ids) == len(set(ids)) and ids == [i["id"] for i in rc.template(_ev(type="triathlon", distance="70.3"))]
    trip = rc.template(_ev(kind="trip", type="other"))
    assert 3 <= len(trip) <= 8 and any("Travel mode" in (i.get("note") or "") for i in trip)
    warn = rc.template(_ev(), gear_warnings=[{"name": "Pegasus 40", "warning": "Race in a fresher pair."}])
    assert any(i["text"].startswith("Pegasus 40:") for i in warn)


def test_windows_and_view() -> None:
    race = TODAY + timedelta(days=70)
    assert rc.current_bucket(race, race - timedelta(days=100)) == "early"
    assert rc.current_bucket(race, race - timedelta(days=30)) == "build"
    assert rc.current_bucket(race, race - timedelta(days=10)) == "two_weeks"
    assert rc.current_bucket(race, race - timedelta(days=5)) == "race_week"
    assert rc.current_bucket(race, race - timedelta(days=1)) == "eve"
    assert rc.current_bucket(race, race) == "morning"
    assert rc.current_bucket(race, race + timedelta(days=3)) == "after"
    ev = _ev(date=(TODAY + timedelta(days=30)).isoformat())  # 30 days out: the build window
    first = rc.template(ev)[0]["id"]
    v = rc.view(ev, {"checked": {first: 1}, "hidden": {}}, TODAY)
    assert v["current"] == "build" and v["done"] == 1 and v["total"] == len(rc.template(ev))
    assert sum(b["current"] for b in v["buckets"]) == 1
    s = rc.summary(v)
    assert s["window"]["id"] == "build" and len(s["next"]) == 2 and not any(i["checked"] for i in s["next"])


def test_state_actions(env) -> None:  # noqa: F811
    cl = rc.Checklists(env.store, clock=lambda: 100)
    ev = _ev()
    item = rc.template(ev)[0]["id"]
    cl.act("friend", ev, {"action": "check", "item": item})
    cl.act("friend", ev, {"action": "add", "text": "  Book  massage ", "bucket": "after"})
    st = cl.state("friend", "e1")
    assert item in st["checked"] and st["custom"][0]["text"] == "Book massage"
    cid = st["custom"][0]["id"]
    cl.act("friend", ev, {"action": "hide", "item": item})
    v = rc.view(ev, cl.state("friend", "e1"), TODAY)
    assert [h["id"] for h in v["hidden"]] == [item] and any(i["id"] == cid for b in v["buckets"] for i in b["items"])
    for bad in ({"action": "check", "item": "nope"}, {"action": "add", "text": "", "bucket": "after"},
                {"action": "add", "text": "x", "bucket": "later"}, {"action": "delete", "item": item},
                {"action": "explode"}):
        try:
            cl.act("friend", ev, bad)
        except rc.ChecklistError:
            continue
        raise AssertionError(bad)
    cl.act("friend", ev, {"action": "delete", "item": cid})
    assert cl.state("friend", "e1")["custom"] == []


def test_http(env, tmp_path) -> None:  # noqa: F811
    agent, _ = env.agent([])
    today = agent._now("friend").date()
    ev = agent.events.create("friend", {"name": "Denver Half", "date": (today + timedelta(weeks=6)).isoformat(),
                                        "type": "running", "distance": "half marathon", "priority": "A"})
    group = agent.events.create("friend", {"name": "Tuesday run", "date": (today + timedelta(days=3)).isoformat(),
                                           "kind": "group_activity", "type": "running"})
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.get(f"/app/api/events/{ev['id']}/checklist")
            assert r.status_code == 200, r.text
            v = r.json()
            assert v["current"] == "build" and v["total"] > 20 and v["done"] == 0
            first = v["buckets"][1]["items"][0]["id"]
            r = await a.post(f"/app/api/events/{ev['id']}/checklist", headers=h, json={"action": "check", "item": first})
            assert r.status_code == 200 and r.json()["done"] == 1
            r = await a.post(f"/app/api/events/{ev['id']}/checklist", headers=h, json={"action": "add", "text": "Buy gels", "bucket": "build"})
            assert r.status_code == 200 and r.json()["total"] == v["total"] + 1
            r = await a.post(f"/app/api/events/{ev['id']}/checklist", headers=h, json={"action": "check", "item": "nope"})
            assert r.status_code == 400
            assert (await a.get("/app/api/events/nope0000/checklist")).status_code == 404
            assert (await a.get(f"/app/api/events/{group['id']}/checklist")).status_code == 400
            s = (await a.get("/app/api/checklist/summary")).json()["events"]
            assert s[ev["id"]]["done"] == 1 and group["id"] not in s
            nxt = (await a.get("/app/api/checklist/next")).json()["next"]
            assert nxt["event"]["id"] == ev["id"] and nxt["window"]["id"] == "build" and len(nxt["next"]) == 2
            assert (await c.get(f"/app/api/events/{ev['id']}/checklist")).status_code == 403
            assert (await c.get("/app/api/checklist/next")).status_code == 403
    asyncio.run(go_())
