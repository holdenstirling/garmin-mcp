"""Repeating events (recur.py), calendar export and the subscribe feed (calsub.py), the
event <-> plan links, and their API."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx2
import pytest

from garmin_mcp import recur
from garmin_mcp.calsub import CalSub, event_ics, feed_ics, google_url
from garmin_mcp.coaching import CoachError
from garmin_mcp.events import plan_links
from garmin_mcp.planbuilder import occurrences
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

D = date.fromisoformat


def test_rules_validate_and_expand() -> None:
    start = D("2026-10-20")  # a Tuesday
    r = recur.clean_rule({"freq": "weekly", "weekdays": ["thu", "tue"]}, start)
    assert r["weekdays"] == ["tue", "thu"] and r["until"] is None and r["interval"] == 1
    assert [d.isoformat() for d in recur.dates(r, start, start, D("2026-10-31"))] == [
        "2026-10-20", "2026-10-22", "2026-10-27", "2026-10-29"]
    bi = recur.clean_rule({"freq": "weekly", "interval": 2, "weekdays": ["sat"], "count": 3}, start)
    assert [d.isoformat() for d in recur.dates(bi, start, start, D("2027-12-31"))] == [
        "2026-10-24", "2026-11-07", "2026-11-21"]
    mo = recur.clean_rule({"freq": "monthly"}, start)  # 3rd Tuesday, from the first date
    assert mo["setpos"] == 3 and mo["weekdays"] == ["tue"]
    assert [d.isoformat() for d in recur.dates(mo, start, start, D("2027-01-31"))] == [
        "2026-10-20", "2026-11-17", "2026-12-15", "2027-01-19"]
    last = recur.clean_rule({"freq": "monthly", "weekdays": ["fri"], "setpos": -1}, start)
    assert recur.dates(last, start, start, D("2026-12-31"))[0].isoformat() == "2026-10-30"
    ex = recur.clean_rule({"weekdays": ["tue"], "until": "2026-11-10", "except": ["2026-10-27"]}, start)
    assert [d.isoformat() for d in recur.dates(ex, start, start, D("2027-01-01"))] == [
        "2026-10-20", "2026-11-03", "2026-11-10"]
    assert recur.rrule(bi, timed=True) == "FREQ=WEEKLY;INTERVAL=2;BYDAY=SA;COUNT=3"
    assert recur.rrule(mo, timed=False) == "FREQ=MONTHLY;BYDAY=3TU"
    assert recur.rrule(ex, timed=True) == "FREQ=WEEKLY;BYDAY=TU;UNTIL=20261110T235959"
    assert recur.describe(r) == "Every Tuesday and Thursday" and recur.describe(mo) == "Monthly on the 3rd Tuesday"
    for bad, msg in [({"freq": "daily"}, "weekly"), ({"weekdays": ["xyz"]}, "weekday"),
                     ({"interval": 3}, "1 or 2"), ({"count": 0}, "times"),
                     ({"until": "2026-11-01", "count": 3}, "not both"), ({"until": "2026-10-01"}, "after"),
                     ({"freq": "monthly", "weekdays": ["tue", "thu"]}, "one weekday"), ({"nope": 1}, "unknown")]:
        with pytest.raises(recur.RuleError, match=msg):
            recur.clean_rule(bad, start)
    # Simple weekly rules keep the older stored shape (plans built from them don't change).
    assert recur.stored(recur.clean_rule({"weekday": "tue", "until": "2027-01-01"}, start)) == {
        "weekday": "tue", "until": "2027-01-01"}


def test_plan_builder_uses_every_date() -> None:
    ev = {"date": "2026-10-20", "recurring": {"freq": "weekly", "interval": 2, "weekdays": ["tue"],
                                              "except": ["2026-11-03"]}}
    assert [d.isoformat() for d in occurrences(ev, D("2026-12-01"))] == ["2026-10-20", "2026-11-17"]
    assert [d.isoformat() for d in occurrences({"date": "2026-10-20", "recurring": {"weekday": "thu", "until": "2026-11-01"}},
                                               D("2027-01-01"))] == ["2026-10-22", "2026-10-29"]


def test_series_edit_one_date_and_days(env) -> None:
    agent, _ = env.agent([])
    ev = agent.events
    vb = ev.create("u", {"name": "Community volleyball", "date": "2026-10-20", "kind": "group_activity",
                         "type": "team_sport", "time": "18:30", "duration_min": 90, "location": "Baker Park",
                         "neighborhood": "Baker, Denver", "in_plan": False,
                         "recurring": {"freq": "weekly", "weekdays": ["tue"]}})
    assert vb["recurring"]["freq"] == "weekly" and vb["in_plan"] is False
    with pytest.raises(CoachError, match="end date"):
        ev.create("u", {"name": "x", "date": "2026-10-20", "end_date": "2026-10-21", "recurring": {"weekdays": ["tue"]}})
    with pytest.raises(CoachError, match="isn't one of"):
        ev.edit_occurrence("u", vb["id"], "2026-10-21", {"skip": True})
    out = ev.edit_occurrence("u", vb["id"], "2026-10-27", {"skip": True})
    assert out["series"]["recurring"]["except"] == ["2026-10-27"] and out["series"]["seq"] == 1
    out = ev.edit_occurrence("u", vb["id"], "2026-11-03", {"time": "19:00"})
    one = out["event"]
    assert one["date"] == "2026-11-03" and one["time"] == "19:00" and one["series_id"] == vb["id"]
    days = ev.days("u", D("2026-10-19"), D("2026-11-10"))
    assert sorted(days) == ["2026-10-20", "2026-11-03", "2026-11-10"]
    assert days["2026-11-03"][0]["time"] == "19:00" and days["2026-10-20"][0]["repeats"] is True
    assert ev.edit_occurrence("u", vb["id"], "2026-10-27", {"skip": False})["series"]["recurring"]["except"] == ["2026-11-03"]
    ended = ev.end_series("u", vb["id"], "2026-12-01")
    assert ended["recurring"]["until"] == "2026-12-01"
    dec = ev.decorate(ev.get("u", vb["id"]), D("2026-10-21"))
    assert dec["repeat_text"].startswith("Every Tuesday") and dec["next_dates"][:2] == ["2026-10-27", "2026-11-10"]
    assert dec["rrule"].startswith("FREQ=WEEKLY;BYDAY=TU;UNTIL=20261201T235959")


def test_ics_and_google_link() -> None:
    ev = {"id": "e1", "name": "Volleyball; Baker, Denver", "date": "2026-10-20", "time": "18:30",
          "duration_min": 90, "at": "Baker Park", "neighborhood": "Baker, Denver", "notes": "Bring\nwater", "seq": 3,
          "recurring": {"freq": "weekly", "weekdays": ["tue"], "except": ["2026-10-27"]}}
    ics = event_ics(ev)
    assert "UID:ev-e1@rabbit" in ics and "SEQUENCE:3" in ics
    assert "DTSTART:20261020T183000" in ics and "DTEND:20261020T200000" in ics
    assert "RRULE:FREQ=WEEKLY;BYDAY=TU" in ics and "EXDATE:20261027T183000" in ics
    assert "SUMMARY:Volleyball\\; Baker\\, Denver" in ics and "Bring\\nwater" in ics
    assert "LOCATION:Baker Park\\, Baker\\, Denver" in ics and ics.endswith("END:VCALENDAR\r\n")
    allday = event_ics({"id": "e2", "name": "Trip", "date": "2026-11-01", "end_date": "2026-11-03"})
    assert "DTSTART;VALUE=DATE:20261101" in allday and "DTEND;VALUE=DATE:20261104" in allday
    g = google_url(ev)
    assert g and g.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")
    assert "recur=RRULE%3AFREQ%3DWEEKLY%3BBYDAY%3DTU" in g and "dates=20261020T183000%2F20261020T200000" in g
    plan = {"weeks": [{"days": {"2026-10-21": [{"id": "s1", "sport": "run", "title": "Easy run", "minutes": 40,
                                               "time": "07:00"}],
                                "2027-06-01": [{"id": "s2", "sport": "run", "title": "Far away", "minutes": 40}]}}]}
    feed = feed_ics([ev], plan, D("2026-10-20"))
    assert "UID:ev-e1@rabbit" in feed and "UID:s1@rabbit" in feed and "s2@rabbit" not in feed


def test_feed_tokens(env) -> None:
    subs = CalSub(env.store)
    assert subs.status("u") is None and subs.lookup("x" * 32) is None
    t1 = subs.create("u")
    assert subs.lookup(t1) == "u" and subs.status("u")
    t2 = subs.create("u")  # rotate: the old link stops working
    assert subs.lookup(t1) is None and subs.lookup(t2) == "u"
    subs.revoke("u")
    assert subs.lookup(t2) is None and subs.status("u") is None


def test_plan_links() -> None:
    today = D("2026-10-20")
    evs = [{"id": "m", "main": True, "date": "2027-06-01"},
           {"id": "g", "kind": "group_activity", "type": "cycling", "date": "2026-10-22"},
           {"id": "c", "kind": "group_activity", "type": "team_sport", "date": "2026-10-22", "in_plan": False},
           {"id": "p", "kind": "race", "date": "2026-01-01"},
           {"id": "n", "kind": "race", "date": "2027-01-10"}]
    plan = {"weeks": [{"days": {"2026-10-22": [{"id": "s", "sport": "bike", "event_id": "g"}]}}],
            "events": [{"id": "g"}], "events_changed": False}
    links = plan_links(evs, plan, today)
    assert links["m"]["status"] == "main" and links["p"]["status"] == "past"
    assert links["g"]["status"] == "in_plan" and links["g"]["days"] == ["2026-10-22"] and "ride" in links["g"]["line"]
    assert links["c"]["status"] == "calendar_only" and links["n"]["status"] == "outside"
    plan["events_changed"] = True
    assert plan_links(evs, plan, today)["n"]["action"] == "update_plan"
    assert plan_links(evs, None, today)["g"]["action"] == "build_plan"


def test_api(env, tmp_path) -> None:
    agent, _ = env.agent([])
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}
    first = (agent._now("friend").date() + timedelta(days=1)).isoformat()

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            r = await a.post("/app/api/events", headers=h, json={
                "name": "Volleyball", "date": first, "kind": "group_activity", "type": "team_sport", "time": "18:30",
                "recurring": {"freq": "weekly", "weekdays": ["tue", "thu"]}})
            assert r.status_code == 201, r.text
            e = r.json()["event"]
            assert e["repeat_text"].startswith("Every") and e["rrule"].startswith("FREQ=WEEKLY")
            assert e["google_url"].startswith("https://calendar.google.com/") and e["plan"]["status"] == "no_plan"
            r = await a.get("/app/api/events/days")
            assert r.status_code == 200 and len(r.json()["days"]) >= 10
            assert (await a.get("/app/api/events/days?from=2026-01-01&to=2027-01-01")).status_code == 400
            day = e["next_dates"][1]
            r = await a.post(f"/app/api/events/{e['id']}/occurrences/{day}", headers=h, json={"skip": True})
            assert r.status_code == 200 and day in r.json()["event"]["recurring"]["except"]
            r = await a.get(f"/app/api/events/{e['id']}/calendar.ics")
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
            assert "RRULE:FREQ=WEEKLY" in r.text and "EXDATE" in r.text
            r = await a.post("/app/api/calendar/feed", headers=h, json={})
            assert r.status_code == 200, r.text
            url = r.json()["url"]
            assert url.startswith(f"{BASE}/app/cal/") and r.json()["webcal"].startswith("webcal://")
            r = await a.get(url[len(BASE):])
            assert r.status_code == 200 and "Volleyball" in r.text
            assert (await a.get("/app/cal/" + "x" * 32 + ".ics")).status_code == 404
            assert (await a.get("/app/api/calendar/feed")).json()["on"] is True
            await a.request("DELETE", "/app/api/calendar/feed", headers=h, json={})
            assert (await a.get(url[len(BASE):])).status_code == 404
            assert (await c.get("/app/api/calendar/feed")).status_code == 403
            assert (await c.post("/app/api/calendar/feed", headers=h, json={})).status_code == 403
            assert (await c.get("/app/api/events/days")).status_code == 403
    asyncio.run(go_())
