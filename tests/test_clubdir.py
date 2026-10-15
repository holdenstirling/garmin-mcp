"""Clubs & leagues directory: robots.txt, link-only domains never fetched, SSRF guard, size/type
limits, per-host pacing, extraction validation, dedupe, monthly refresh gating + stale hiding,
suggest/report flows, one crawl at a time, Rabbit's local_clubs tool, HTTP shape + coach 403.
No network: MockTransport + a fake resolver + stub research/extract backends; no wall clock."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from types import SimpleNamespace

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import clubdir as cd
from garmin_mcp.appstore import AppStore
from garmin_mcp.clubdir import Crawler, Directory, DirectoryError, Page
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.providers.base import GarminError
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_social import BASE, FakePush, H

T0 = 1_800_000_000.0
DAY = 86400.0
PUBLIC_IP = "93.184.216.34"
TUESDAY = datetime(2026, 10, 13, 12, 0)  # a Tuesday, noon

CLUB_HTML = """<html><head><title>Wash Park Runners</title><script>var x = "ignore me";</script></head>
<body><h1>Wash Park Runners</h1><p>Free group run every Tuesday at 6:00 pm from Wash Park boathouse.
All paces welcome. Email captain@washpark.example or call 303-555-1234.</p>
<a href="/join?utm_source=x">Join us</a> <a href="https://www.meetup.com/wash-park-runners/">Meetup</a></body></html>"""


def html(body: str, status: int = 200, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
    return httpx2.Response(status, content=body.encode(), headers={"content-type": ctype, **(headers or {})})


class Web:
    """A tiny fake internet: url -> response factory; records every request."""

    def __init__(self, pages: dict[str, httpx2.Response | str]) -> None:
        self.pages = pages
        self.seen: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.seen.append(url)
        assert request.headers["user-agent"].startswith("RabbitBot/1.0 (+")
        got = self.pages.get(url)
        if got is None:
            return httpx2.Response(404, content=b"")
        return html(got) if isinstance(got, str) else got

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


def resolver(private: dict[str, str] | None = None):
    async def res(host: str) -> list[str]:
        return [(private or {}).get(host, PUBLIC_IP)]
    return res


class FakeTime:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(round(s, 3))
        self.t += s


def crawler(web: Web, private: dict[str, str] | None = None, ft: FakeTime | None = None) -> Crawler:
    ft = ft or FakeTime()
    return Crawler(user_agent=cd.user_agent("https://rabbit.example"), transport=web.transport(),
                   resolver=resolver(private), clock=ft.clock, sleep=ft.sleep)


async def fetch(c: Crawler, url: str) -> Page | None:
    async with c.client() as client:
        return await c.fetch(client, url)


# ---------------------------------------------------------------- crawler --
def test_robots_txt_is_obeyed_and_cached_per_host() -> None:
    web = Web({"https://club.example/robots.txt": httpx2.Response(200, content=b"User-agent: RabbitBot\nDisallow: /private\n"
                                                                    b"\nUser-agent: *\nAllow: /\n",
                                                                    headers={"content-type": "text/plain"}),
               "https://club.example/private/roster": CLUB_HTML, "https://club.example/runs": CLUB_HTML,
               "https://club.example/about": CLUB_HTML,
               "https://shy.example/robots.txt": httpx2.Response(200, content=b"User-agent: *\nDisallow: /\n"),
               "https://shy.example/": CLUB_HTML,
               "https://down.example/robots.txt": httpx2.Response(503, content=b""), "https://down.example/x": CLUB_HTML})
    c = crawler(web)

    async def go() -> None:
        assert await fetch(c, "https://club.example/private/roster") is None
        assert (await fetch(c, "https://club.example/runs")).title == "Wash Park Runners"
        assert await fetch(c, "https://club.example/about") is not None
        assert await fetch(c, "https://shy.example/") is None            # Disallow: / for everyone
        assert await fetch(c, "https://down.example/x") is None          # 5xx robots = assume disallowed
        assert await fetch(c, "https://nobots.example/x") is None        # 404 robots = allowed (page 404s too)
    asyncio.run(go())
    assert "https://club.example/private/roster" not in web.seen
    assert "https://shy.example/" not in web.seen and "https://down.example/x" not in web.seen
    assert web.seen.count("https://club.example/robots.txt") == 1        # cached per host
    assert "https://nobots.example/x" in web.seen


def test_link_only_and_unsafe_urls_are_never_fetched() -> None:
    web = Web({"https://club.example/go": httpx2.Response(302, headers={"location": "https://www.meetup.com/x/"}),
               "https://club.example/plain": httpx2.Response(302, headers={"location": "http://club.example/runs"})})
    c = crawler(web)
    blocked = ["https://www.meetup.com/denver-runners/", "https://facebook.com/groups/x", "https://m.facebook.com/x",
               "https://www.strava.com/clubs/1", "https://instagram.com/runclub", "https://x.com/runclub",
               "https://twitter.com/runclub", "https://www.tiktok.com/@club", "https://www.linkedin.com/company/x",
               "https://www.eventbrite.com/e/1", "https://www.eventbrite.co.uk/e/1", "https://www.eventbrite.de/e/1",
               "http://club.example/runs", "https://127.0.0.1/", "https://[::1]/", "https://localhost/x",
               "https://club.example:8443/x", "https://user:pw@club.example/x", "https://printer.local/x"]

    async def go() -> None:
        for u in blocked:
            assert await fetch(c, u) is None, u
        assert await fetch(c, "https://club.example/go") is None      # redirect to Meetup: not followed
        assert await fetch(c, "https://club.example/plain") is None   # redirect to http: not followed
    asyncio.run(go())
    assert not any(re.search(r"meetup|facebook|strava|instagram|x\.com|twitter|tiktok|linkedin|eventbrite|127\.0|::1|"
                             r"localhost|8443|printer|http://", u) for u in web.seen), web.seen
    for u in blocked[:12]:
        assert cd.link_only_label(httpx2.URL(u).host) is not None, u
    assert cd.link_only_label("club.example") is None and cd.link_only_label("notfacebook.com") is None


def test_ssrf_guard_rejects_private_and_reserved_addresses() -> None:
    for bad in ("127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1",
                "::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "224.0.0.1", "240.0.0.1", "nonsense"):
        assert not cd.ip_ok(bad), bad
    assert cd.ip_ok(PUBLIC_IP) and cd.ip_ok("2606:4700:4700::1111")
    web = Web({"https://evil.example/x": CLUB_HTML,
               "https://club.example/hop": httpx2.Response(301, headers={"location": "https://evil.example/x"}),
               "https://club.example/runs": CLUB_HTML})
    c = crawler(web, private={"evil.example": "169.254.169.254"})

    async def go() -> None:
        assert await fetch(c, "https://evil.example/x") is None
        assert await fetch(c, "https://club.example/hop") is None     # redirect into a private address
        assert await fetch(c, "https://club.example/runs") is not None

    async def failing(host: str) -> list[str]:
        raise OSError("dns")
    asyncio.run(go())
    assert not any("evil.example" in u for u in web.seen)
    c2 = Crawler(user_agent="RabbitBot/1.0 (+x)", transport=web.transport(), resolver=failing)
    assert asyncio.run(fetch(c2, "https://club.example/runs")) is None   # unresolvable = refused


def test_html_only_size_cap_and_readable_text() -> None:
    big = "x" * (cd.MAX_BYTES + 10)
    web = Web({"https://club.example/pdf": httpx2.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
               "https://club.example/big": html(big),
               "https://club.example/claims-small": httpx2.Response(200, content=big.encode(),
                                                                    headers={"content-type": "text/html"}),
               "https://club.example/runs": CLUB_HTML})
    c = crawler(web)
    assert asyncio.run(fetch(c, "https://club.example/pdf")) is None
    assert asyncio.run(fetch(c, "https://club.example/big")) is None
    assert asyncio.run(fetch(c, "https://club.example/claims-small")) is None
    p = asyncio.run(fetch(c, "https://club.example/runs"))
    assert p is not None and "ignore me" not in p.text and "Tuesday at 6:00 pm" in p.text
    assert "captain@" not in p.text and "555-1234" not in p.text       # contact details scrubbed
    assert "https://club.example/join" in p.links                       # tracking params stripped
    assert "https://www.meetup.com/wash-park-runners/" in p.links


def test_one_request_per_second_per_host() -> None:
    web = Web({f"https://club.example/p{i}": CLUB_HTML for i in range(3)} | {"https://other.example/a": CLUB_HTML})
    ft = FakeTime()
    c = crawler(web, ft=ft)

    async def go() -> None:
        async with c.client() as client:
            for i in range(3):
                await c.fetch(client, f"https://club.example/p{i}")
            await c.fetch(client, "https://other.example/a")
    asyncio.run(go())
    # robots + 3 pages on club.example: 1 s apart; other.example's first requests don't wait on it.
    assert ft.slept == [1.0, 1.0, 1.0, 1.0]
    assert ft.t == 4.0


# ------------------------------------------------------------- validation --
def page(text: str = "Wash Park Runners meet Tuesdays. Highlands Track Club runs Thursdays.",
         links: set[str] | None = None) -> Page:
    return Page(url="https://washpark.example/runs", title="Group runs", text=text,
                links=links or {"https://washpark.example/join"})


def test_model_output_is_validated() -> None:
    raw = {"listings": [
        {"name": "Wash Park Runners", "kind": "run_club", "sports": ["running", "<b>x</b>", 5, "Trail"],
         "sessions": [{"weekday": "tue", "time": "18:00"}, {"weekday": "tue", "time": "18:00"},
                      {"weekday": "thu", "time": "25:00"}, {"weekday": "funday", "time": "07:00"}],
         "meet_spot": "1234 Elm Street", "pace": "all paces", "cost": "cheap",
         "join_url": "https://washpark.example/join", "description": "x" * 400 + " mail me@a.co"},
        {"name": "Invented Club", "kind": "ride", "join_url": "https://washpark.example/join"},   # not on the page
        {"name": "Highlands Track Club", "kind": "rocket", "meet_spot": "Highlands Park track",
         "join_url": "https://evil.example/phish", "cost": "free"},
        "junk", {"name": "wash park runners!", "kind": "run_club"},                                # duplicate
    ]}
    out = cd.clean_listings(raw, page())
    assert [x["name"] for x in out] == ["Wash Park Runners", "Highlands Track Club"]
    a, b = out
    assert a["sessions"] == [{"weekday": "tue", "time": "18:00", "note": ""}, {"weekday": "thu", "time": "", "note": ""}]
    assert a["sports"] == ["running", "trail"] and a["cost"] == "unknown" and a["meet_spot"] == ""  # home address dropped
    assert len(a["description"]) <= 160 and "@" not in a["description"]
    assert a["source"] == "washpark.example" and re.fullmatch(r"l[0-9a-f]{12}", a["id"])
    assert b["kind"] == "other" and b["meet_spot"] == "Highlands Park track" and b["cost"] == "free"
    assert b["join_url"] == "https://washpark.example/runs"   # a link not on the page falls back to the page
    assert cd.clean_listings("nope", page()) == [] and cd.clean_listings({"listings": "x"}, page()) == []
    cands = cd.clean_candidates({"candidates": [{"name": "A", "url": "http://a.example"}, {"name": "B", "url": "https://b.example/?utm_source=z"},
                                                {"name": "B2", "url": "https://b.example/"}, {"name": "", "url": "https://c.example"}]})
    assert cands == [{"name": "B", "url": "https://b.example/", "kind": "other"}]


def test_dedupe_by_normalized_name_and_registrable_domain() -> None:
    k = cd.dedupe_key
    assert k("The Wash Park Runners", "https://www.washpark.example/a") == k("wash park runners!", "https://runs.washpark.example/b")
    assert k("Wash Park Runners", "https://washpark.example/") != k("Wash Park Runners", "https://other.example/")
    assert cd.registrable("www.club.co.uk") == "club.co.uk" and cd.registrable("a.b.example.com") == "example.com"
    assert cd.metro("denver", "Colorado").label == "Denver, CO" and cd.metro("Denver", "Narnia") is None
    assert cd.metro("Denver", "CO").doc_name == "clubdir-denver-co"


def test_next_session() -> None:
    s = [{"weekday": "tue", "time": "06:00", "note": ""}, {"weekday": "thu", "time": "18:00", "note": ""}]
    assert cd.next_session(s, TUESDAY) == {"weekday": "thu", "time": "18:00", "in_days": 2}
    assert cd.next_session(s, TUESDAY.replace(hour=5)) == {"weekday": "tue", "time": "06:00", "in_days": 0}
    assert cd.next_session([], TUESDAY) is None


# -------------------------------------------------------------- directory --
SITES = {
    "https://washpark.example/robots.txt": httpx2.Response(404),
    "https://washpark.example/runs": CLUB_HTML,
    "https://washpark.example/join": CLUB_HTML,
    "https://volo.example/denver": "<title>Volo Denver</title><p>Volo Kickball League: Wednesdays 19:00 at City Park. Paid.</p>",
    "https://suggested.example/": "<title>Sloan Lake Striders</title><p>Sloan Lake Striders run Saturdays 8:00 am, free.</p>",
}


def make_dir(tmp_path, fernet_key, web: Web | None = None, clock: SimpleNamespace | None = None):
    clock = clock or SimpleNamespace(t=T0)
    web = web or Web(dict(SITES))
    calls = SimpleNamespace(research=[], extract=[])

    async def research(system, prompt, *, max_searches, report_tool):
        assert "Denver, CO" in prompt and report_tool["name"] == "report_candidates" and max_searches <= 4
        calls.research.append(prompt)
        if "running clubs" in prompt:
            return {"candidates": [{"name": "Wash Park Runners", "url": "https://washpark.example/runs", "kind": "run_club"},
                                   {"name": "Denver Trail Crew", "url": "https://www.meetup.com/denver-trail/", "kind": "trail"},
                                   {"name": "Strava Club", "url": "https://www.strava.com/clubs/9", "kind": "run_club"}]}
        if "leagues" in prompt:
            return {"candidates": [{"name": "Volo", "url": "https://volo.example/denver", "kind": "league"}]}
        return {"candidates": []}

    async def extract(system, prompt, tool, *, max_tokens):
        assert tool["name"] == "report_listings" and "<page_text>" in prompt and len(prompt) < cd.PAGE_TEXT_MAX + 500
        calls.extract.append(prompt)
        if "washpark.example" in prompt:
            return {"listings": [{"name": "Wash Park Runners", "kind": "run_club", "sessions": [{"weekday": "tue", "time": "18:00"}],
                                  "meet_spot": "Wash Park boathouse", "pace": "All paces", "cost": "free",
                                  "join_url": "https://washpark.example/join", "description": "Free Tuesday group run."}]}
        if "volo.example" in prompt:
            return {"listings": [{"name": "Volo Kickball League", "kind": "league", "sports": ["kickball"],
                                  "sessions": [{"weekday": "wed", "time": "19:00"}], "meet_spot": "City Park", "cost": "paid"}]}
        if "suggested.example" in prompt:
            return {"listings": [{"name": "Sloan Lake Striders", "kind": "run_club",
                                  "sessions": [{"weekday": "sat", "time": "08:00"}], "cost": "free"}]}
        return {"listings": []}

    store = AppStore(tmp_path / "app", fernet_key)
    d = Directory(store, research=research, extract=extract, crawler=crawler(web), clock=lambda: clock.t)
    return SimpleNamespace(d=d, web=web, clock=clock, calls=calls, store=store, m=cd.metro("Denver", "CO"))


def test_refresh_discovers_crawls_extracts_and_gates_monthly(tmp_path, fernet_key) -> None:
    x = make_dir(tmp_path, fernet_key)
    s = asyncio.run(x.d.refresh(x.m))
    assert s["candidates"] == 4 and s["pages"] == 2 and len(x.calls.research) == len(cd.QUERIES)
    v = x.d.view(x.m, now_local=TUESDAY)
    names = [r["name"] for r in v["listings"]]
    assert names[:2] == ["Wash Park Runners", "Volo Kickball League"]   # soonest session first (tonight, then Wed)
    wp = next(r for r in v["listings"] if r["name"] == "Wash Park Runners")
    assert wp["next"] == {"weekday": "tue", "time": "18:00", "in_days": 0} and wp["source"] == "washpark.example"
    assert wp["join_url"] == "https://washpark.example/join" and wp["cost"] == "free"
    meet = next(r for r in v["listings"] if r["link_only"] == "Meetup")
    assert meet["name"] == "Denver Trail Crew" and meet["sessions"] == []
    assert {r["link_only"] for r in v["listings"]} == {None, "Meetup", "Strava"}
    assert not any("meetup" in u or "strava" in u for u in x.web.seen)
    assert v["counts"]["leagues"] == 1 and v["counts"]["trail"] == 1 and v["state"] == "idle" and not v["due"]
    assert [r["name"] for r in x.d.view(x.m, now_local=TUESDAY, chip="leagues")["listings"]] == ["Volo Kickball League"]
    assert [r["name"] for r in x.d.view(x.m, now_local=TUESDAY, weekday="tue")["listings"]] == ["Wash Park Runners"]
    # Monthly: a second refresh is skipped; 31 days later it runs and re-verifies (no duplicates).
    seen = len(x.web.seen)
    assert asyncio.run(x.d.refresh(x.m)) == {"skipped": "fresh"} and len(x.web.seen) == seen
    x.clock.t += 31 * DAY
    asyncio.run(x.d.refresh(x.m))
    doc = x.d.load(x.m)
    assert len(doc["listings"]) == 4
    wp2 = next(v for v in doc["listings"].values() if v["name"] == "Wash Park Runners")
    assert wp2["first_seen"] == T0 and wp2["last_verified"] == T0 + 31 * DAY
    # Forced refresh ignores the month.
    assert "skipped" not in asyncio.run(x.d.refresh(x.m, force=True))


def test_failed_runs_retry_after_a_day_and_stale_listings_hide(tmp_path, fernet_key) -> None:
    x = make_dir(tmp_path, fernet_key, web=Web({}))   # every page 404s, nothing found

    async def nothing(*a, **k):
        return {"candidates": []}
    x.d._research = nothing
    asyncio.run(x.d.refresh(x.m))
    assert x.d.due(x.m) is False                      # attempted just now
    x.clock.t += DAY + 1
    assert x.d.due(x.m) is True                       # empty run: retry after a day, not a month
    # Stale: a listing not re-verified for 90+ days disappears.
    x.d._doc(x.m).save({"refreshed": x.clock.t, "listings": {"l000000000001": {
        "id": "l000000000001", "key": "a|b.example", "name": "Old Club", "kind": "run_club",
        "last_verified": x.clock.t - 91 * DAY}, "l000000000002": {
        "id": "l000000000002", "key": "n|b.example", "name": "New Club", "kind": "run_club", "last_verified": x.clock.t}}})
    assert [r["name"] for r in x.d.view(x.m, now_local=TUESDAY)["listings"]] == ["New Club"]


def test_suggest_and_report_flows(tmp_path, fernet_key) -> None:
    x = make_dir(tmp_path, fernet_key)
    with pytest.raises(DirectoryError, match="Meetup"):
        x.d.suggest("ann", "Trail crew", "https://www.meetup.com/x/", "Denver", "CO")
    with pytest.raises(DirectoryError):
        x.d.suggest("ann", "Club", "http://insecure.example/", "Denver", "CO")
    with pytest.raises(DirectoryError):
        x.d.suggest("ann", "Club", "https://ok.example/", "Atlantis", "")
    with pytest.raises(DirectoryError):
        x.d.suggest("ann", "Club", "https://10.0.0.1/", "Denver", "CO")
    assert x.d.suggest("ann", "Sloan Lake Striders", "https://suggested.example/", "Denver", "CO")["ok"]
    for i in range(cd.SUGGEST_PER_DAY - 1):
        x.d.suggest("ann", f"Club {i}", f"https://c{i}.example/", "Denver", "CO")
    with pytest.raises(DirectoryError) as e:
        x.d.suggest("ann", "One more", "https://more.example/", "Denver", "CO")
    assert e.value.status == 429
    x.clock.t += DAY
    x.d.suggest("ann", "Next day", "https://next.example/", "Denver", "CO")   # a new day, a new allowance
    # The suggestion is crawled first on the next refresh and leaves the queue.
    asyncio.run(x.d.refresh(x.m))
    pages = [u for u in x.web.seen if not u.endswith("robots.txt")]
    assert pages[0] == "https://suggested.example/"
    doc = x.d.load(x.m)
    assert all(s["url"] != "https://suggested.example/" for s in doc["suggestions"])
    v = x.d.view(x.m, now_local=TUESDAY)
    sloan = next(r for r in v["listings"] if r["name"] == "Sloan Lake Striders")
    # Reports: one is not enough, the same person twice is still one, two people hide it.
    assert x.d.report("ann", x.m, sloan["id"])["hidden"] is False
    assert x.d.report("ann", x.m, sloan["id"])["hidden"] is False
    assert any(r["id"] == sloan["id"] and r["reported"] for r in x.d.view(x.m, now_local=TUESDAY, uid="ann")["listings"])
    assert x.d.report("bob", x.m, sloan["id"])["hidden"] is True
    assert all(r["id"] != sloan["id"] for r in x.d.view(x.m, now_local=TUESDAY)["listings"])
    with pytest.raises(DirectoryError):
        x.d.report("bob", x.m, "l" + "0" * 12)
    with pytest.raises(DirectoryError):
        x.d.report("bob", x.m, "../etc")
    # Re-verified on the next refresh (its page is re-crawled first after suggestions): visible again.
    x.clock.t += 31 * DAY
    x.web.seen.clear()
    asyncio.run(x.d.refresh(x.m))
    assert [u for u in x.web.seen if not u.endswith("robots.txt")][0] == "https://suggested.example/"
    assert any(r["id"] == sloan["id"] for r in x.d.view(x.m, now_local=TUESDAY)["listings"])


def test_plan_urls_caps_pages_and_domains() -> None:
    many = [f"https://site{i}.example/" for i in range(40)]
    same = [f"https://one.example/p{i}" for i in range(5)]
    out = Directory.plan_urls(["https://s.example/"], [], same + many, ["https://www.meetup.com/x"])
    assert out[0] == "https://s.example/" and len(out) == cd.MAX_PAGES
    assert sum(1 for u in out if "one.example" in u) == cd.PER_DOMAIN_PAGES and not any("meetup" in u for u in out)


def test_one_crawl_at_a_time(tmp_path, fernet_key) -> None:
    x = make_dir(tmp_path, fernet_key)
    active = SimpleNamespace(now=0, peak=0)
    real = x.d.refresh

    async def tracked(m, *, force=False):
        active.now += 1
        active.peak = max(active.peak, active.now)
        await asyncio.sleep(0)
        try:
            return await real(m, force=force)
        finally:
            active.now -= 1
    x.d.refresh = tracked
    boulder = cd.metro("Boulder", "CO")

    async def go() -> None:
        assert x.d.kick(x.m, uid="ann") == "queued"
        assert x.d.kick(x.m, uid="ann") in ("queued", "refreshing")   # already in line: not twice
        assert x.d.kick(boulder, uid="ann") == "queued"
        await x.d.idle()
    asyncio.run(go())
    assert active.peak == 1 and x.d.refreshes == 2
    assert x.d.state(x.m) == "idle"
    # Per-user cap on starting refreshes.
    for i in range(cd.KICKS_PER_DAY - 2):
        x.d._take(x.d._kicks, "ann", cd.KICKS_PER_DAY)

    async def again() -> str:
        return x.d.kick(cd.metro("Aurora", "CO"), uid="ann")
    assert asyncio.run(again()) == "limit"
    nobody = Directory(x.store, research=None, extract=None, crawler=x.d.crawler)
    assert nobody.kick(x.m) == "unavailable"


# ------------------------------------------------------------ agent tool --
def test_local_clubs_tool(env, tmp_path, fernet_key) -> None:  # noqa: F811
    agent, _ = env.agent([])
    with pytest.raises(GarminError):
        agent._dispatch("ann", "local_clubs", {})
    seen = []
    agent.club_directory = lambda uid, kind, day: seen.append((uid, kind, day)) or {"listings": []}
    assert agent._dispatch("ann", "local_clubs", {"kind": "run", "weekday": "tue"}) == {"listings": []}
    agent._dispatch("ann", "local_clubs", {"kind": "rocket", "weekday": "someday"})
    assert seen == [("ann", "run", "tue"), ("ann", None, None)]
    x = make_dir(tmp_path, fernet_key)
    asyncio.run(x.d.refresh(x.m))
    out = x.d.lookup(x.m, now_local=TUESDAY, kind="run", weekday="tue")
    assert [r["name"] for r in out["listings"]] == ["Wash Park Runners"] and out["city"] == "Denver, CO"
    assert out["listings"][0]["sessions"][0]["time"] == "18:00" and "check the link" in out["source"]
    assert x.d.lookup(cd.metro("Boulder", "CO"), now_local=TUESDAY, kind=None, weekday=None)["note"]


# ------------------------------------------------------------------ http --
def _apps(env, tmp_path):  # noqa: F811
    agent, _ = env.agent([])
    for uid in ("ann", "bob"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
        agent.coach.update_athlete(uid, {"home_location": "Denver, CO"})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"ann@x.com": "ann", "bob@x.com": "bob", "cat@x.com": "cat"},
                        owner_user_ids=("ann",))
    lid = cd.listing_id("wash park runners|washpark.example")
    now = time.time()  # the server's directory runs on the wall clock; the listing was verified "just now"
    env.store.global_doc("clubdir-denver-co").save({"refreshed": now, "listings": {lid: {
        "id": lid, "key": "wash park runners|washpark.example", "name": "Wash Park Runners", "kind": "run_club",
        "sports": ["running"], "sessions": [{"weekday": "tue", "time": "18:00", "note": ""}],
        "meet_spot": "Wash Park boathouse", "pace": "All paces", "cost": "free",
        "join_url": "https://washpark.example/join", "source_url": "https://washpark.example/runs",
        "source": "washpark.example", "description": "", "link_only": None,
        "first_seen": now, "last_verified": now, "reports": []}}})

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, FakePush(), None, ChatRunner(agent)))
    apps = {u: app(u) for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}, lid, agent


def test_http_directory(env, tmp_path) -> None:  # noqa: F811
    c, lid, agent = _apps(env, tmp_path)

    async def go() -> None:
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        r = await ann.get("/app/api/community/directory")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"metro", "status", "listings", "counts", "refreshed", "fallback"}
        assert body["metro"]["label"] == "Denver, CO" and body["status"] == "ready"
        (row,) = body["listings"]
        assert set(row) >= {"id", "name", "kind", "kind_label", "next", "meet_spot", "pace", "cost", "join_url",
                            "source", "last_verified", "link_only", "linked_club", "reported"}
        assert row["kind_label"] == "Run club" and row["next"]["weekday"] == "tue"
        assert (await ann.get("/app/api/community/directory?kind=leagues")).json()["listings"] == []
        assert (await ann.get("/app/api/community/directory?kind=rocket")).status_code == 400
        assert (await cat.get("/app/api/community/directory")).json()["status"] == "needs_location"
        # Suggest: Origin required, validated, queued.
        assert (await ann.post("/app/api/community/directory/suggest", json={"name": "X", "url": "https://x.example/"})).status_code == 403
        r = await ann.post("/app/api/community/directory/suggest", headers=H, json={"name": "Sloan Lake Striders", "url": "https://sloan.example/"})
        assert r.status_code == 202 and r.json()["metro"] == "Denver, CO"
        r = await ann.post("/app/api/community/directory/suggest", headers=H, json={"name": "X", "url": "https://facebook.com/x"})
        assert r.status_code == 400 and "Facebook" in r.json()["error"]
        # Report: two different people hide it.
        assert (await ann.post(f"/app/api/community/directory/{lid}/report", headers=H, json={})).json()["hidden"] is False
        assert (await bob.post(f"/app/api/community/directory/{lid}/report", headers=H, json={})).json()["hidden"] is True
        assert (await bob.get("/app/api/community/directory")).json()["listings"] == []
        assert (await bob.post("/app/api/community/directory/nope/report", headers=H, json={})).status_code == 404
        # Link to a club: only the club's owner/admin.
        club = (await ann.post("/app/api/community/clubs", headers=H, json={"name": "Wash Park Runners", "sport": "running",
                                                                              "city": "Denver", "state": "CO"})).json()["club"]
        assert (await bob.post(f"/app/api/community/directory/{lid}/link", headers=H, json={"club_id": club["id"]})).status_code == 403
        assert (await ann.post(f"/app/api/community/directory/{lid}/link", headers=H, json={"club_id": club["id"]})).json()["ok"]
        assert env.store.global_doc("clubdir-denver-co").load()["listings"][lid]["linked_club"] == club["id"]
        # Owner-only force refresh (no research backend here -> unavailable, but allowed).
        assert (await bob.post("/app/api/community/directory/refresh", headers=H, json={})).status_code == 403
        r = await ann.post("/app/api/community/directory/refresh", headers=H, json={"city": "Boulder", "state": "CO"})
        assert r.status_code == 202 and r.json() == {"status": "unavailable", "metro": "Boulder, CO"}
        # Rabbit's tool reads the same directory for the athlete's city.
        assert agent.club_directory is not None
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_http_coach_gets_403(env, tmp_path) -> None:  # noqa: F811
    c, lid, _ = _apps(env, tmp_path)

    async def go() -> None:
        coach = c[coach_user_id("c@x.com")]
        assert (await coach.get("/app/api/community/directory")).status_code == 403
        for p in ("suggest", "refresh", f"{lid}/report", f"{lid}/link"):
            assert (await coach.post(f"/app/api/community/directory/{p}", headers=H, json={})).status_code == 403, p
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_privacy_and_bot_pages_mention_the_crawler() -> None:
    from garmin_mcp import legal
    assert "RabbitBot" in legal.privacy() and "robots.txt" in legal.privacy()
    assert "User-agent: RabbitBot" in legal.about() and json.dumps(cd.user_agent("https://r.example/")) == \
        '"RabbitBot/1.0 (+https://r.example/app/about)"'
