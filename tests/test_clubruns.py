"""Club runs: posting with pace groups/capacity/waiver/visibility, RSVP + waitlist promotion,
waiver gating, the public club page (counts only, never names), guest RSVP + cancel, organizer
tools (roster, check-in, skip a week, duplicate, dashboard), nearby runs, the plan swap
("count this club run as today's run") and its undo, why_changed, the check-in buddy, the
daily chat cap and the proactive model default."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from garmin_mcp import clubpage
from garmin_mcp.appstore import AppStore
from garmin_mcp.buddycheck import BuddyCheck, BuddyError
from garmin_mcp.chatcap import ChatCap
from garmin_mcp.clubs import ClubError
from garmin_mcp.config import Settings
from garmin_mcp.plans import public_plan, why_changed
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import NOON, cx  # noqa: F401  (fixture)
from tests.test_plans import _setup

RUN = {"title": "Tuesday social 5k", "start": "2026-10-20T18:00", "repeat": "weekly", "where": "Wash Park boathouse",
       "pace": "", "level": "all", "notes": "", "see": "public",
       "groups": [{"label": "Chatty", "pace": "11:00/mi"}, {"label": "Steady", "pace": "9:00/mi"}],
       "walk": True, "beginner": True, "lat": 39.7, "lng": -104.97}


def _club(cx, **kw):
    g = cx.grp.create("ann", {"name": "Wash Park Runners", "city": "Denver", "state": "CO", **kw})
    return g["id"]


# --------------------------------------------------------- post + RSVP --
def test_post_run_fields_and_visibility(cx) -> None:
    cid = _club(cx)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "capacity": 2, "paid": "$5 at the door / Venmo"}, NOON)
    assert m["groups"][0] == {"label": "Chatty", "pace": "11:00/mi"} and m["walk"] and m["beginner"]
    assert m["capacity"] == 2 and m["spots_left"] == 2 and m["see"] == "public" and m["token"]
    assert m["paid"] == "$5 at the door / Venmo" and m["lat"] == 39.7
    for bad in ({**RUN, "capacity": 0.5}, {**RUN, "see": "everyone"}, {**RUN, "walk": "yes"},
                {**RUN, "lat": 200, "lng": 0}, {**RUN, "groups": [{"label": "x"}] * 5}):
        with pytest.raises(ClubError):
            cx.grp.add_meetup("ann", cid, bad, NOON)
    # Public runs are visible to signed-in non-members; club runs aren't.
    cx.grp.add_meetup("ann", cid, {**RUN, "title": "Members only", "see": "club"}, NOON)
    titles = [x["title"] for x in cx.grp.meetups("cat", cid, NOON)]
    assert titles == ["Tuesday social 5k"]
    # A private club's runs never go public.
    pc = cx.grp.create("ann", {"name": "Secret squad", "visibility": "private"})["id"]
    assert cx.grp.add_meetup("ann", pc, RUN, NOON)["see"] == "club"


def test_capacity_waitlist_and_promotion(cx) -> None:
    cid = _club(cx)
    for u in ("bob", "cat"):
        cx.grp.join(u, cid)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "capacity": 1}, NOON)
    assert cx.grp.rsvp("bob", cid, m["id"], "going", NOON)["my_rsvp"] == "going"
    v = cx.grp.rsvp("cat", cid, m["id"], "going", NOON)
    assert v["my_rsvp"] == "waitlist" and v["wait_pos"] == 1 and v["spots_left"] == 0
    v = cx.grp.rsvp("dan", cid, m["id"], "going", NOON)  # a non-member, public run
    assert v["my_rsvp"] == "waitlist" and v["wait_pos"] == 2
    out = cx.grp.rsvp("bob", cid, m["id"], "none", NOON)
    assert out["promoted"] == "cat"
    assert cx.grp.meetups("cat", cid, NOON)[0]["my_rsvp"] == "going"
    # dan's public RSVP shows in his upcoming runs.
    assert [x["id"] for x in cx.grp.my_meetups("dan", NOON)] == [m["id"]]


def test_waiver_must_be_accepted_and_is_exportable(cx) -> None:
    cid = _club(cx)
    cx.grp.join("bob", cid)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "waiver": "I run at my own risk.\nNo refunds."}, NOON)
    with pytest.raises(ClubError) as e:
        cx.grp.rsvp("bob", cid, m["id"], "going", NOON)
    assert e.value.status == 409
    v = cx.grp.rsvp("bob", cid, m["id"], "going", NOON, accept_waiver=True)
    assert v["waiver_signed"] and v["my_rsvp"] == "going"
    rows = cx.grp.waiver_rows("ann", cid, m["id"])
    assert [r["id"] for r in rows] == ["bob"] and rows[0]["at"] == int(cx.clock.t)
    with pytest.raises(ClubError):
        cx.grp.waiver_rows("bob", cid, m["id"])  # organizers only
    # A changed waiver needs accepting again.
    cx.grp.update_meetup("ann", cid, m["id"], {"waiver": "New terms."}, NOON)
    cx.grp.rsvp("bob", cid, m["id"], "none", NOON)
    with pytest.raises(ClubError):
        cx.grp.rsvp("bob", cid, m["id"], "going", NOON)


def test_change_of_time_or_spot_tells_rsvps(cx) -> None:
    cid = _club(cx)
    cx.grp.join("bob", cid)
    m = cx.grp.add_meetup("ann", cid, RUN, NOON)
    cx.grp.rsvp("bob", cid, m["id"], "going", NOON)
    assert cx.grp.update_meetup("ann", cid, m["id"], {"notes": "Bring a light"}, NOON)["tell"] == []
    assert cx.grp.update_meetup("ann", cid, m["id"], {"where": "Smith Lake"}, NOON)["tell"] == ["bob"]


# ------------------------------------------------------ public page --
def test_public_page_counts_only_and_guest_rsvp(cx) -> None:
    cid = _club(cx)
    cx.grp.join("bob", cid)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "capacity": 2}, NOON)
    hidden = cx.grp.add_meetup("ann", cid, {**RUN, "title": "Track night", "see": "private"}, NOON)
    cx.grp.rsvp("bob", cid, m["id"], "going", NOON)
    slug = cx.grp.share_link("ann", cid).removeprefix("/c/")
    assert slug == "wash-park-runners"
    page = cx.grp.public_page(slug, NOON)
    assert [r["title"] for r in page["runs"]] == ["Tuesday social 5k"] and page["runs"][0]["count"] == 1
    html = clubpage.render_page(page, base="https://rabbt.example")
    assert "Bob" not in html and "bob" not in html and "Track night" not in html
    assert 'og:title' in html and "Wash Park Runners" in html
    # The private run's own link shows just that run.
    one = cx.grp.public_page(slug, NOON, token=hidden["token"], mid=hidden["id"])
    assert [r["title"] for r in one["runs"]] == ["Track night"]
    with pytest.raises(ClubError):
        cx.grp.guest_rsvp(slug, hidden["id"], "Eve", "eve@x.com", False, NOON)
    with pytest.raises(ClubError):
        cx.grp.guest_rsvp(slug, m["id"], "Eve", "not-an-email", False, NOON)
    g1 = cx.grp.guest_rsvp(slug, m["id"], "Eve", "Eve@X.com", False, NOON)
    assert g1["status"] == "going" and g1["cancel"]
    assert cx.grp.guest_rsvp(slug, m["id"], "Eve", "eve@x.com", False, NOON)["cancel"] is None  # once per email
    g2 = cx.grp.guest_rsvp(slug, m["id"], "Fay", "fay@x.com", False, NOON)
    assert g2["status"] == "waitlist"
    roster = cx.grp.roster("ann", cid, m["id"], NOON)
    assert {r.get("email") for r in roster["rows"] if r["kind"] == "guest"} == {"eve@x.com", "fay@x.com"}
    with pytest.raises(ClubError):
        cx.grp.guest_cancel(slug, m["id"], g1["cancel"].split(".")[0] + ".wrong")
    promoted = cx.grp.guest_cancel(slug, m["id"], g1["cancel"])
    assert promoted and promoted.startswith("g:")
    assert cx.grp.public_page(slug, NOON)["runs"][0]["count"] == 2
    # Private clubs have no page.
    pc = cx.grp.create("ann", {"name": "Secret squad", "visibility": "private"})["id"]
    with pytest.raises(ClubError):
        cx.grp.share_link("ann", pc)
    assert cx.grp.public_page("secret-squad", NOON) is None
    assert cx.grp.public_page("../etc", NOON) is None


def test_public_page_ics_and_escaping(cx) -> None:
    cid = _club(cx)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "title": "<script>x</script>"}, NOON)
    page = cx.grp.public_page(cx.grp.share_link("ann", cid).removeprefix("/c/"), NOON)
    out = clubpage.render_page(page, base="https://rabbt.example")
    assert "<script>x" not in out and "&lt;script&gt;" in out
    cal = clubpage.ics(page["runs"][0], page["name"], "https://rabbt.example/app/c/x")
    assert cal.startswith("BEGIN:VCALENDAR") and "DTSTART" in cal and m["id"]


# ---------------------------------------------------- organizer tools --
def test_roster_checkin_skip_duplicate_dashboard(cx) -> None:
    cid = _club(cx)
    cx.grp.join("bob", cid)
    m = cx.grp.add_meetup("ann", cid, RUN, NOON)
    cx.grp.rsvp("bob", cid, m["id"], "going", NOON)
    r = cx.grp.checkin("ann", cid, m["id"], "bob", True, NOON)
    assert r["checked_in"] == 1 and r["rows"][0]["checked_in"]
    with pytest.raises(ClubError):
        cx.grp.checkin("ann", cid, m["id"], "cat", True, NOON)  # not on the list
    with pytest.raises(ClubError):
        cx.grp.checkin("bob", cid, m["id"], "bob", True, NOON)  # organizers only
    # Skip next Tuesday: the next one is the week after; bob is told.
    v, tell = cx.grp.skip_week("ann", cid, m["id"], "2026-10-20", True, NOON)
    assert v["next"] == "2026-10-27T18:00" and tell == ["bob"]
    with pytest.raises(ClubError):
        cx.grp.skip_week("ann", cid, m["id"], "2026-10-21", True, NOON)  # a Wednesday
    v, _ = cx.grp.skip_week("ann", cid, m["id"], "2026-10-20", False, NOON)
    assert v["next"] == "2026-10-20T18:00"
    dup = cx.grp.duplicate("ann", cid, m["id"], NOON)
    assert dup["next"] == "2026-10-27T18:00" and dup["id"] != m["id"] and dup["walk"]
    msg, to = cx.grp.message_targets("ann", cid, m["id"], "Meet at the north lot", NOON)
    assert msg == "Meet at the north lot" and to == ["bob"]
    # The run happens; next week the dashboard shows attendance.
    later = datetime(2026, 10, 22, 9, 0, tzinfo=NOON.tzinfo)
    cx.grp.rsvp("bob", cid, m["id"], "going", later)  # prunes last week into history
    dash = cx.grp.dashboard("ann", cid, later)
    assert dash["members"] == 2 and dash["link"] == "/c/wash-park-runners"
    assert dash["attendance"] == [{"date": "2026-10-20", "going": 1, "checkins": 1}]
    assert len(dash["runs"]) == 2
    with pytest.raises(ClubError):
        cx.grp.dashboard("bob", cid, later)


def test_report_and_block_hide_runs(cx) -> None:
    cid = _club(cx)
    m = cx.grp.add_meetup("ann", cid, RUN, NOON)
    cx.grp.report_run("cat", cid, m["id"], "spam")
    assert cx.grp._doc.load()["reports"][-1]["by"] == "cat"
    cx.soc.block("cat", "ann")
    assert cx.grp.meetups("cat", cid, NOON) == []


def test_nearby_runs(cx) -> None:
    cid = _club(cx)
    m = cx.grp.add_meetup("ann", cid, {**RUN, "start": "2026-10-14T18:00", "repeat": "none"}, NOON)
    cx.grp.add_meetup("ann", cid, {**RUN, "start": "2026-10-14T19:00", "repeat": "none", "see": "club"}, NOON)
    got = cx.grp.nearby_runs("dan", NOON, city="Denver", state="CO", hours=12)
    assert [x["id"] for x in got] == [m["id"]] and got[0]["club"]["member"] is False
    assert cx.grp.nearby_runs("dan", NOON, city="Boulder", state="CO", hours=12) == []
    assert len(cx.grp.nearby_runs("ann", NOON, city="", state="", hours=12)) == 2


# ---------------------------------------------------------- plan swap --
def test_swap_replaces_a_planned_run_and_undoes(env) -> None:
    agent, plan, today = _setup(env)
    w = plan["weeks"][1]
    day = next(d for d in sorted(w["days"]) if any(s["sport"] == "run" and s.get("kind") != "race"
                                                      for s in w["days"][d]))
    before = next(s for s in w["days"][day] if s["sport"] == "run")
    p = agent.plans.swap_for_club_run("friend", day, {"club_id": "gabc", "meetup_id": "m1", "title": "Social 5k",
                                                      "club": "Wash Park"})
    s = next(x for x in p["weeks"][1]["days"][day] if x.get("club_run"))
    assert s["id"] == before["id"] and s["title"] == "Club run: Social 5k" and s["club_run"]["label"] == "Social 5k with Wash Park"
    assert s["kind"] in ("easy", "long") and s["minutes"] == before["minutes"]
    assert why_changed(s, p)["kind"] == "club"
    pub = public_plan(p, today)
    ps = next(x for wk in pub["weeks"] for dd in wk["days"] for x in dd["sessions"] if x["id"] == s["id"])
    assert ps["club_run"]["meetup_id"] == "m1" and ps["why"]["kind"] == "club"
    # Counting it twice is a no-op; undo puts the original back.
    agent.plans.swap_for_club_run("friend", day, {"club_id": "gabc", "meetup_id": "m1", "title": "x", "club": "y"})
    p = agent.plans.undo_club_run("friend", s["id"])
    back = next(x for x in p["weeks"][1]["days"][day] if x["id"] == s["id"])
    assert back["title"] == before["title"] and not back.get("club_run")


def test_swap_adds_and_drops_a_later_easy_run(env) -> None:
    agent, plan, today = _setup(env)
    w = plan["weeks"][1]
    days = sorted(w["days"])

    def easy_after(d: str) -> bool:
        return any(s["sport"] == "run" and s.get("kind") in ("easy", "recovery")
                   for dd in days if dd > d for s in w["days"][dd])
    day = next((d for d in days if not any(s["sport"] == "run" for s in w["days"][d]) and easy_after(d)), None)
    if day is None:
        pytest.skip("no run-free day before an easy run in this plan shape")
    runs_before = sum(1 for dd in days for s in w["days"][dd] if s["sport"] == "run")
    p = agent.plans.swap_for_club_run("friend", day, {"club_id": "gabc", "meetup_id": "m2", "title": "Hill reps",
                                                      "club": "Wash Park", "minutes": 50})
    w2 = p["weeks"][1]
    club = next(s for s in w2["days"][day] if s.get("club_run"))
    assert club["minutes"] == 50 and club["club_dropped"]
    rest = next(s for s in w2["days"][club["club_dropped"]] if s.get("club_drop"))
    assert rest["sport"] == "rest" and why_changed(rest, p)["kind"] == "club"
    assert sum(1 for dd in w2["days"] for s in w2["days"][dd] if s["sport"] == "run") == runs_before
    p = agent.plans.undo_club_run("friend", club["id"])
    w3 = p["weeks"][1]
    assert not any(s.get("club_run") or s.get("club_drop") for dd in w3["days"] for s in w3["days"][dd])
    assert sum(1 for dd in w3["days"] for s in w3["days"][dd] if s["sport"] == "run") == runs_before


def test_why_changed_kinds() -> None:
    plan = {"trips": [{"id": "t1", "label": "Chicago"}]}
    assert why_changed({}, plan) is None
    assert why_changed({"edited": True}, plan)["kind"] == "you"
    assert why_changed({"travel": "t1"}, plan)["text"] == "Changed to fit your trip for Chicago."
    assert why_changed({"sick": True}, plan)["kind"] == "sick"
    assert why_changed({"adjusted": True, "adjust_why": "Low sleep"}, plan)["text"] == "Low sleep"


# ------------------------------------------------------- check-in buddy --
def test_buddy_check_timing(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    clock = SimpleNamespace(t=1_800_000_000.0)
    sent: list[tuple] = []
    friends = {("ann", "bob"), ("bob", "ann")}
    b = BuddyCheck(store, mutual=lambda x, y: (x, y) in friends, notify=lambda *a: sent.append(a),
                   name=lambda u: u.title(), clock=lambda: clock.t)
    with pytest.raises(BuddyError):
        b.start("ann", 30)  # no buddy yet
    with pytest.raises(BuddyError):
        b.set_buddy("ann", "cat")  # not mutual
    assert b.set_buddy("ann", "bob")["buddy"] == "bob"
    with pytest.raises(BuddyError):
        b.start("ann", 2)
    v = b.start("ann", 30)
    assert v["active"]["back_by"] == int(clock.t) + 1800
    assert sent[-1][0] == "bob" and sent[-1][2] == "Ann is heading out" and "30 minutes" in sent[-1][3]
    clock.t += 1800 + 14 * 60
    assert b.tick("ann") == []
    clock.t += 60
    assert b.tick("ann") == ["runner"] and sent[-1][0] == "ann"
    assert b.tick("ann") == []  # once
    clock.t += 15 * 60
    assert b.tick("ann") == ["buddy"] and sent[-1][0] == "bob" and "hasn't checked in" in sent[-1][2]
    b.back("ann")
    assert sent[-1][2] == "Ann is back" and b.view("ann")["active"] is None
    doc = store.user_doc("ann", "buddycheck").load()
    assert doc["log"][-1]["late"] is True and set(doc) == {"buddy", "active", "log"}  # no location
    friends.clear()
    assert b.view("ann")["buddy"] is None  # unfollowed: no longer a buddy
    b.forget("ann")
    assert store.user_doc("ann", "buddycheck").load() == {}


# ------------------------------------------------------------- costs --
def test_daily_chat_cap(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    cap = ChatCap(store, 2)
    d = date(2026, 10, 14)
    assert cap.allowed("ann", d)
    cap.count("ann", d)
    cap.count("ann", d)
    assert not cap.allowed("ann", d) and cap.used("ann", d) == 2
    assert "2 messages today" in cap.message()
    assert cap.allowed("ann", d + timedelta(days=1)) and cap.allowed("bob", d)
    assert ChatCap(store, 0).allowed("ann", d)  # 0 = no cap
    cap.forget("ann")
    assert cap.used("ann", d) == 0


def test_proactive_model_defaults_to_haiku(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8001")
    monkeypatch.delenv("AGENT_PROACTIVE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_DAILY_MESSAGES", raising=False)
    s = Settings.from_env()
    assert s.agent_proactive_model == "claude-haiku-5-5" and s.agent_daily_messages == 40
    monkeypatch.setenv("AGENT_PROACTIVE_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("AGENT_DAILY_MESSAGES", "10")
    s = Settings.from_env()
    assert s.agent_proactive_model == "claude-sonnet-5-5" and s.agent_daily_messages == 10
    assert Settings.__dataclass_fields__["agent_proactive_model"].default == "claude-haiku-5-5"


# --------------------------------------------------------------- http --
def test_http_club_run_flow(env, tmp_path) -> None:
    import asyncio

    import httpx2

    from tests.test_community import _clients
    from tests.test_community import _setup as _http_setup
    from tests.test_social import BASE, H
    apps, push, agent = _http_setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        # ann and bob follow each other (buddy needs mutual).
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        eid = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})
        await ann.post("/app/api/social/follow", headers=H, json={"email": "bob@x.com"})
        eid = (await bob.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await bob.post(f"/app/api/social/requests/{eid}/accept", headers=H, json={})

        g = (await ann.post("/app/api/community/clubs", headers=H,
                            json={"name": "Wash Park Runners", "city": "Denver"})).json()["club"]
        start = (agent._now("ann") + timedelta(days=2)).strftime("%Y-%m-%dT18:00")
        r = await ann.post(f"/app/api/community/clubs/{g['id']}/meetups", headers=H,
                           json={**RUN, "start": start, "capacity": 1, "waiver": "At my own risk."})
        assert r.status_code == 201
        mid = r.json()["meetup"]["id"]
        link = (await ann.post(f"/app/api/community/clubs/{g['id']}/link", headers=H, json={})).json()
        assert link["path"] == "/app/c/wash-park-runners" and link["url"].startswith(BASE)
        assert (await bob.post(f"/app/api/community/clubs/{g['id']}/link", headers=H, json={})).status_code in (403, 404)

        # The public page: no sign-in needed, strict CSP, counts only.
        anon = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=apps["cat"]), base_url=BASE)
        page = await anon.get("/app/c/wash-park-runners")
        assert page.status_code == 200 and "Tuesday social 5k" in page.text
        assert "form-action 'self'" in page.headers["content-security-policy"]
        assert (await anon.get("/app/c/nope")).status_code == 404
        # Guest RSVP: waiver required, honeypot ignored, then going; the next guest waits.
        url = f"/app/c/wash-park-runners/r/{mid}/rsvp"
        r = await anon.post(url, data={"name": "Eve", "email": "eve@x.com"})
        assert r.status_code == 400 and "waiver" in r.text.lower()
        r = await anon.post(url, data={"name": "Bot", "email": "bot@x.com", "waiver": "yes", "website": "spam"})
        assert r.status_code == 200
        r = await anon.post(url, data={"name": "Eve", "email": "eve@x.com", "waiver": "yes"})
        assert r.status_code == 200 and ".ics" in r.text and "cancel?s=" in r.text
        cancel = r.text.split("cancel?s=")[1].split('"')[0]
        r = await anon.post(url, data={"name": "Fay", "email": "fay@x.com", "waiver": "yes"})
        assert r.status_code == 200 and "waitlist" in r.text.lower()
        ics = await anon.get(f"/app/c/wash-park-runners/r/{mid}.ics")
        assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
        assert (await anon.get(f"/app/c/wash-park-runners/r/{mid}/cancel?s={cancel}")).status_code == 200
        assert (await anon.post(f"/app/c/wash-park-runners/r/{mid}/cancel?s={cancel}")).status_code == 200
        roster = (await ann.get(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/roster")).json()["roster"]
        assert [r_["name"] for r_ in roster["rows"] if r_["status"] == "going"] == ["Fay"]
        csv = await ann.get(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/waivers?format=csv")
        assert csv.status_code == 200 and "fay@x.com" in csv.text
        assert (await bob.get(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/roster")).status_code in (403, 404)

        # Signed-in RSVP from a non-member to a public run: waiver first (409), then the waitlist.
        r = await cat.post(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/rsvp", headers=H, json={"status": "going"})
        assert r.status_code == 409
        r = await cat.post(f"/app/api/community/clubs/{g['id']}/meetups/{mid}/rsvp", headers=H,
                           json={"status": "going", "accept_waiver": True})
        assert r.json()["meetup"]["my_rsvp"] == "waitlist"
        dash = (await ann.get(f"/app/api/community/clubs/{g['id']}/dashboard")).json()
        assert dash["dashboard"]["runs"][0]["waitlist"] == 1

        # Check-in buddy.
        assert (await ann.post("/app/api/buddy", headers=H, json={"action": "set", "buddy": "cat"})).status_code == 400
        r = await ann.post("/app/api/buddy", headers=H, json={"action": "set", "buddy": "bob"})
        assert r.status_code == 200 and r.json()["buddy_user"]["name"].startswith("Bob")
        r = await ann.post("/app/api/buddy", headers=H, json={"action": "start", "minutes": 45})
        assert r.json()["active"] and any(p[0] == "bob" and "heading out" in p[1] for p in push.sent)
        r = await ann.post("/app/api/buddy", headers=H, json={"action": "back"})
        assert r.json()["active"] is None and any(p[0] == "bob" and "is back" in p[1] for p in push.sent)
        for x in [*c.values(), anon]:
            await x.aclose()
    asyncio.run(go())


def test_leaderboards_are_opt_in_scoped_and_hide_blocked(cx) -> None:
    from garmin_mcp import challenges as chm
    from tests.test_challenges import history
    now = datetime(2026, 10, 14, 9, 0, tzinfo=NOON.tzinfo)
    chal = chm.Challenges(cx.store, now=lambda u: now, activities=lambda u: (now.date(), history()),
                          athlete=lambda u: {"favorite_sports": ["run"]}, names=lambda u: u.title(),
                          blocked=cx.soc.blocked_between)
    g = cx.grp.create("ann", {"name": "Crew"})
    for u in ("cat", "dan"):
        cx.grp.join(u, g["id"])
    sug = chal.get("ann")["periods"]["week"]["suggestions"][0]
    gid = chal.start_club("ann", sug["template"], "week", g["id"], max_people=500)["id"]
    # Only people who joined are on the board (dan is a member but didn't join).
    chal.join_club("cat", gid, g["id"])
    names = {r["user_id"] for r in chal.club_view("dan", [gid], g["id"])[0]["leaders"]}
    assert names == {"ann", "cat"}
    cx.soc.block("cat", "ann")
    assert {r["user_id"] for r in chal.club_view("cat", [gid], g["id"])[0]["leaders"]} == {"cat"}
    assert {r["user_id"] for r in chal.club_view("ann", [gid], g["id"])[0]["leaders"]} == {"ann"}
