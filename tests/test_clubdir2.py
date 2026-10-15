"""Clubs & leagues v2: meet-spot geocoding (public places within the metro radius, cached),
"Add to calendar" .ics (weekly RRULE, TZID + VTIMEZONE, RFC 5545 escaping and folding),
"I'm going" per occurrence (counts, friends only, blocks, weekly reset, evening-before
reminder) and the HTTP shapes. No network, no wall clock in the unit parts."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx2
import pytest

from garmin_mcp import clubdir as cd
from garmin_mcp import clubics, geo
from garmin_mcp.appstore import AppStore
from garmin_mcp.clubdir import Directory, DirectoryError
from garmin_mcp.clubgoing import Going, reminder_line
from garmin_mcp.coaches import coach_user_id
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_clubdir import T0, TUESDAY, _apps, crawler, make_dir, Web
from tests.test_social import H

DENVER = ZoneInfo("America/Denver")
LID = cd.listing_id("wash park runners|washpark.example")


def listing(**kw):
    base = {"id": LID, "name": "Wash Park Runners", "kind": "run_club", "kind_label": "Run club",
            "sessions": [{"weekday": "tue", "time": "18:00", "note": ""}], "meet_spot": "Wash Park boathouse",
            "pace": "All paces", "cost": "free", "join_url": "https://washpark.example/join",
            "source": "washpark.example", "description": ""}
    return base | kw


# ------------------------------------------------------------------- ics --
def test_ics_weekly_rrule_tzid_and_vtimezone() -> None:
    now = TUESDAY.replace(tzinfo=DENVER)  # Tue 2026-10-13 12:00
    text = clubics.listing_ics(listing(sessions=[{"weekday": "tue", "time": "18:00"}, {"weekday": "sat", "time": "07:30"},
                                                 {"weekday": "sun", "time": ""}]), now, host="r.example")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    lines = text.split("\r\n")
    assert "DTSTART;TZID=America/Denver:20261013T180000" in lines      # tonight
    assert "DTSTART;TZID=America/Denver:20261017T073000" in lines      # Saturday
    assert lines.count("RRULE:FREQ=WEEKLY;BYDAY=TU") == 1 and "RRULE:FREQ=WEEKLY;BYDAY=SA" in lines
    assert text.count("BEGIN:VEVENT") == 2                              # no time -> no event
    assert "TZID:America/Denver" in lines and "LOCATION:Wash Park boathouse" in lines
    assert "URL:https://washpark.example/join" in lines and f"UID:{LID}-tue1800@r.example" in lines
    # US DST rules from zoneinfo: 2nd Sunday of March 02:00 / 1st Sunday of November 02:00.
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU" in lines and "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU" in lines
    i = lines.index("BEGIN:DAYLIGHT")
    assert lines[i + 1].endswith("T020000") and lines[i + 3:i + 5] == ["TZOFFSETFROM:-0700", "TZOFFSETTO:-0600"]
    assert "DTSTAMP:20261013T180000Z" in lines
    # A session earlier today has passed: it starts next week.
    late = clubics.listing_ics(listing(sessions=[{"weekday": "tue", "time": "06:00"}]), now)
    assert "DTSTART;TZID=America/Denver:20261020T060000" in late.split("\r\n")
    # No DST (Phoenix): one STANDARD block.
    az = clubics.listing_ics(listing(), TUESDAY.replace(tzinfo=ZoneInfo("America/Phoenix")))
    assert "BEGIN:DAYLIGHT" not in az and "TZOFFSETTO:-0700" in az
    with pytest.raises(ValueError):
        clubics.listing_ics(listing(sessions=[{"weekday": "tue", "time": ""}]), now)


def test_ics_escaping_and_folding() -> None:
    assert clubics.escape("a\\b;c,d\ne\r\nf") == "a\\\\b\\;c\\,d\\ne\\nf"
    now = TUESDAY.replace(tzinfo=DENVER)
    text = clubics.listing_ics(listing(name="Runners, Walkers; & \\ friends", meet_spot="Café Olé, Wash Park",
                                       description="Line one\nLine two " + "é" * 60), now)
    assert "SUMMARY:Runners\\, Walkers\\; & \\\\ friends" in text
    assert "LOCATION:Café Olé\\, Wash Park" in text
    for ln in text.split("\r\n"):
        assert len(ln.encode("utf-8")) <= 75
    unfolded = text.replace("\r\n ", "")
    assert "Line one\\nLine two " + "é" * 60 in unfolded and "\n" not in text.replace("\r\n", "")
    assert clubics.filename("Wash Park Runners!") == "wash-park-runners.ics"


# --------------------------------------------------------------- geocode --
def geo_transport(calls: list[str]) -> httpx2.MockTransport:
    def handler(req: httpx2.Request) -> httpx2.Response:
        q = dict(req.url.params)
        calls.append(q.get("q") or q.get("city") or "")
        if "city" in q:
            return httpx2.Response(200, json=[{"lat": "39.7392", "lon": "-104.9903", "address": {"city": "Denver", "state": "Colorado",
                                                                                              "country_code": "us"}}])
        assert q["bounded"] == "1" and q["countrycodes"] == "us" and q["viewbox"]
        if q["q"].startswith("Wash Park boathouse"):
            return httpx2.Response(200, json=[
                {"lat": "39.70123", "lon": "-104.96789", "category": "building", "type": "house"},   # someone's home
                {"lat": "39.70049", "lon": "-104.96551", "category": "leisure", "type": "park"}])
        if q["q"].startswith("City Park"):  # only a match ~100 km away
            return httpx2.Response(200, json=[{"lat": "38.8339", "lon": "-104.8214", "category": "leisure", "type": "park"}])
        return httpx2.Response(200, json=[])
    return httpx2.MockTransport(handler)


def test_geocode_public_spots_within_radius_and_cached(tmp_path, fernet_key) -> None:
    calls: list[str] = []
    x = make_dir(tmp_path, fernet_key)

    async def no_sleep(s: float) -> None:
        pass

    def geocoder() -> geo.Geocoder:
        return geo.Geocoder(contact="t@example.com", store=x.store, transport=geo_transport(calls),
                            throttle=geo.Throttle(clock=lambda: 0.0, sleep=no_sleep), clock=lambda: x.clock.t)
    x.d._geocoder = geocoder()
    s = asyncio.run(x.d.refresh(x.m))
    assert s["geocoded"] == 2                      # boathouse + City Park; listings without a spot skipped
    v = x.d.view(x.m, now_local=TUESDAY)
    assert v["center"] == {"lat": 39.74, "lon": -104.99}
    by = {r["name"]: r for r in v["listings"]}
    assert (by["Wash Park Runners"]["lat"], by["Wash Park Runners"]["lon"]) == (39.7, -104.966)  # park, 3 decimals
    assert by["Volo Kickball League"]["lat"] is None                     # outside 50 km: not mapped
    assert by["Denver Trail Crew"]["lat"] is None                         # link-only: never geocoded
    doc = x.store.global_doc("clubdir-denver-co").load()
    assert doc["spots"]["city park"]["miss"] is True
    n = len(calls)
    # Cached: a new geocoder (empty memory) asks nothing more; nor does another refresh pass.
    x.d._geocoder = geocoder()
    assert asyncio.run(x.d.geocode(x.m)) == 0 and len(calls) == n
    # After the cache TTL the spots are looked up again.
    x.clock.t += cd.GEO_TTL_S + 1
    for lid, row in doc["listings"].items():
        row["last_verified"] = x.clock.t
    x.store.global_doc("clubdir-denver-co").save(doc)
    assert asyncio.run(x.d.geocode(x.m)) == 2


def test_geocode_helpers() -> None:
    assert geo.public_place({"category": "leisure", "type": "park"})
    assert geo.public_place({"category": "highway", "type": "trailhead"})
    assert not geo.public_place({"category": "highway", "type": "residential"})
    assert not geo.public_place({"category": "place", "type": "house"})
    assert not geo.public_place({"category": "shop", "type": "x", "addresstype": "house"})
    assert 95 < geo.km_between((39.7392, -104.9903), (38.8339, -104.8214)) < 105


def test_geocode_busy_stops_quietly(tmp_path, fernet_key) -> None:
    x = make_dir(tmp_path, fernet_key)

    class BusyGeo:
        async def city_place(self, city, state):
            return {"lat": 39.74, "lon": -104.99}

        async def spot(self, *a, **k):
            raise geo.Busy()
    x.d._geocoder = BusyGeo()
    s = asyncio.run(x.d.refresh(x.m))
    assert s["geocoded"] == 0 and s["listings"] > 0


# ----------------------------------------------------------------- going --
def going_env(tmp_path, fernet_key):
    clock = SimpleNamespace(t=T0)
    store = AppStore(tmp_path / "g", fernet_key)
    lv = clock.t
    store.global_doc("clubdir-denver-co").save({"refreshed": lv, "listings": {LID: {
        **listing(), "key": "wash park runners|washpark.example", "sports": [], "source_url": "https://washpark.example/runs",
        "link_only": None, "first_seen": lv, "last_verified": lv, "reports": []}}})
    d = Directory(store, research=None, extract=None, crawler=crawler(Web({})), clock=lambda: clock.t)
    follows = {("ann", "bob"), ("ann", "dan")}
    blocks = {frozenset(("ann", "cat"))}
    local = SimpleNamespace(now=TUESDAY.replace(tzinfo=DENVER))
    posted: list[tuple[str, dict]] = []
    g = Going(store, follows=lambda a, b: (a, b) in follows, blocked=lambda a, b: frozenset((a, b)) in blocks,
              is_athlete=lambda u: not u.startswith("coach_"), person=lambda u: {"id": u, "name": u.title()},
              moment=lambda u, m: posted.append((u, m)), now=lambda u: local.now, clock=lambda: clock.t)
    return SimpleNamespace(d=d, g=g, m=cd.metro("Denver", "CO"), clock=clock, local=local, posted=posted, store=store)


def test_going_counts_friends_blocks_and_weekly_reset(tmp_path, fernet_key) -> None:
    e = going_env(tmp_path, fernet_key)
    row = e.d.get(e.m, LID, now_local=e.local.now)
    assert row["next"] == {"weekday": "tue", "time": "18:00", "in_days": 0, "date": "2026-10-13"} and row["calendar"]
    out = e.g.set("ann", e.m, row, True, day="2026-10-13", today=e.local.now.date())
    assert out == {"date": "2026-10-13", "count": 1, "me": True, "friends": [], "more_friends": 0}
    for u in ("bob", "cat", "eve"):
        e.g.set(u, e.m, row, True, today=e.local.now.date())
    ann = e.g.summary("ann", e.m, row)
    assert ann["count"] == 3 and ann["me"] and [p["id"] for p in ann["friends"]] == ["bob"]   # cat blocked, eve not followed
    bob = e.g.summary("bob", e.m, row)
    assert bob["count"] == 4 and bob["friends"] == []        # bob doesn't follow ann (one-way)
    assert e.g.summary("cat", e.m, row)["count"] == 3        # cat can't see ann either
    e.g.set("ann", e.m, row, False, today=e.local.now.date())
    assert e.g.summary("ann", e.m, row) | {"friends": None} == {"date": "2026-10-13", "count": 2, "me": False,
                                                               "friends": None, "more_friends": 0}
    with pytest.raises(DirectoryError) as ex:
        e.g.set("ann", e.m, row, True, day="2026-10-06", today=e.local.now.date())
    assert ex.value.status == 409
    with pytest.raises(DirectoryError) as ex:
        e.g.set(coach_user_id("c@x.com"), e.m, row, True, today=e.local.now.date())
    assert ex.value.status == 403
    with pytest.raises(DirectoryError):
        e.g.set("ann", e.m, row, "yes", today=e.local.now.date())
    # After tonight's run the next occurrence is next Tuesday: a fresh, empty list.
    later = TUESDAY.replace(hour=19, tzinfo=DENVER)
    row2 = e.d.get(e.m, LID, now_local=later)
    assert row2["next"]["date"] == "2026-10-20"
    assert e.g.summary("bob", e.m, row2)["count"] == 0
    rows = e.g.attach("bob", e.m, [dict(row), dict(row2), {**row, "next": None}])
    assert [r["going"] and r["going"]["count"] for r in rows] == [3, 0, None]
    # Writing a week later prunes the old occurrence.
    e.g.set("bob", e.m, row2, True, today=later.date().replace(day=20))
    assert list(e.store.global_doc("clubgoing").load()["k"]) == [f"denver-co|{LID}|2026-10-20"]


def test_going_reminder_the_evening_before(tmp_path, fernet_key) -> None:
    e = going_env(tmp_path, fernet_key)
    mon = datetime(2026, 10, 12, 12, 0, tzinfo=DENVER)
    row = e.d.get(e.m, LID, now_local=mon)
    assert row["next"]["date"] == "2026-10-13"
    e.g.set("ann", e.m, row, True, today=mon.date())
    e.g.set("bob", e.m, row, True, today=mon.date())
    e.local.now = mon.replace(hour=17)
    assert e.g.remind("ann") == 0                              # not evening yet
    e.clock.t += 700
    e.local.now = mon.replace(hour=18, minute=30)
    assert e.g.remind("ann") == 1
    uid, m = e.posted[-1]
    assert uid == "ann" and m["type"] == "meetup" and m["key"] == f"going:denver-co|{LID}|2026-10-13"
    assert m["text"] == "🏃 Tomorrow 18:00: Wash Park Runners at Wash Park boathouse · 2 going." and len(m["text"]) <= 140
    assert e.g.remind("ann") == 0                              # throttled (dedupe by key is Moments.post's job)
    assert e.g.remind(coach_user_id("c@x.com")) == 0
    e.local.now = mon.replace(day=13, hour=19)                 # the day of: no "tomorrow" reminder
    e.clock.t += 700
    assert e.g.remind("ann") == 0
    assert reminder_line({"name": "X" * 200, "time": "", "spot": ""}, 1).endswith("…")


def test_going_reminder_respects_quiet_hours_via_moments(env, tmp_path, fernet_key) -> None:  # noqa: F811
    """The moment goes through Moments.post, which queues it in quiet hours (21:00-07:00)."""
    agent, _ = env.agent([])
    e = going_env(tmp_path, fernet_key)
    late = datetime(2026, 10, 12, 22, 0, tzinfo=DENVER)
    agent._now = lambda uid: late  # type: ignore[method-assign]
    agent.moments._now = lambda uid: late
    e.g.moment = agent.moments.post
    e.local.now = late
    row = e.d.get(e.m, LID, now_local=late)
    e.g.set("ann", e.m, row, True, today=late.date())
    assert e.g.remind("ann") == 1
    assert agent.moments._doc("ann").load().get("queue")      # queued, not posted


# ------------------------------------------------------------------ http --
def test_http_going_calendar_and_shapes(env, tmp_path) -> None:  # noqa: F811
    c, lid, _ = _apps(env, tmp_path)

    async def go() -> None:
        ann, bob = c["ann"], c["bob"]
        body = (await ann.get("/app/api/community/directory")).json()
        assert "center" in body
        (row,) = body["listings"]
        assert {"lat", "lon", "calendar", "going"} <= set(row) and row["calendar"] is True and row["lat"] is None
        assert row["going"] == {"date": row["next"]["date"], "count": 0, "me": False, "friends": [], "more_friends": 0}
        url = f"/app/api/community/directory/{lid}/going"
        assert (await ann.post(url, json={"going": True})).status_code == 403          # no Origin
        r = await ann.post(url, headers=H, json={"going": True, "date": row["next"]["date"]})
        assert r.status_code == 200 and r.json()["going"]["count"] == 1 and r.json()["going"]["me"]
        assert (await ann.post(url, headers=H, json={"going": True, "date": "1999-01-01"})).status_code == 409
        assert (await ann.post(url, headers=H, json={"going": "maybe"})).status_code == 400
        assert (await ann.post("/app/api/community/directory/lnope/going", headers=H, json={"going": True})).status_code == 404
        b = (await bob.get("/app/api/community/directory")).json()["listings"][0]["going"]
        assert b["count"] == 1 and not b["me"] and b["friends"] == []                  # bob doesn't follow ann
        r = await ann.get(f"/app/api/community/directory/{lid}/calendar.ics")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
        assert r.headers["content-disposition"] == 'attachment; filename="wash-park-runners.ics"'
        assert "RRULE:FREQ=WEEKLY;BYDAY=TU" in r.text and "DTSTART;TZID=" in r.text
        assert (await ann.get("/app/api/community/directory/lnope/calendar.ics")).status_code == 404
        coach = c[coach_user_id("c@x.com")]
        assert (await coach.post(url, headers=H, json={"going": True})).status_code == 403
        assert (await coach.get(f"/app/api/community/directory/{lid}/calendar.ics")).status_code == 403
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_csp_allows_only_the_osm_embed() -> None:
    from garmin_mcp.webapp import CSP
    assert "frame-src https://www.openstreetmap.org" in CSP and "frame-ancestors 'none'" in CSP
    assert "connect-src 'self'" in CSP and "img-src 'self' data: blob: https://lh3.googleusercontent.com" in CSP
