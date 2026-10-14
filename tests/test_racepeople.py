"""Race people: invites per role, racing together, follow-edge rule, share link, clean-up, access."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.coaching import CoachStore
from garmin_mcp.config import Settings
from garmin_mcp.events import EventStore
from garmin_mcp.racepeople import GENERIC_SENT, RaceError, RacePeople, pace_rows, render
from garmin_mcp.racepeople_web import invite_text, week_rows
from garmin_mcp.social import Social
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_social import ALLOW, BASE, FakePush, H, act

RACE_DAY = (date.today() + timedelta(days=60)).isoformat()


def _follow(s: Social, a: str, b: str) -> None:
    """a follows b (accepted)."""
    s.follow(a, email=f"{b}@x.com")
    edge = next(e for e in s.people(b)["pending_in"] if e["user_id"] == a)
    s.accept(b, edge["edge_id"])


@pytest.fixture
def rp(tmp_path, fernet_key):
    store = AppStore(tmp_path / "app", fernet_key)
    allow = dict(ALLOW) | {"dan@x.com": "dan"}
    soc = Social(store, athletes=lambda: allow)
    events = EventStore(store, CoachStore(store))
    coaches = {"ann": {"coach@x.com"}}
    r = RacePeople(store, create_event=events.create, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                   is_athlete=soc.is_athlete, athletes=lambda: allow, code_owner=soc.code_owner,
                   coach_emails=lambda u: coaches.get(u, set()), first_name=lambda u: u.title())
    store.on_user_write(lambda uid, name: r.sync(uid) if name == "events" else None)
    ev = events.create("ann", {"name": "Leadville 100", "type": "trail", "distance": "ultra", "date": RACE_DAY,
                               "location": "Leadville, CO", "url": "https://leadville.example/race"})
    _follow(soc, "bob", "ann")   # bob follows ann
    _follow(soc, "ann", "cat")   # ann follows cat
    return SimpleNamespace(r=r, soc=soc, events=events, ev=ev, store=store, coaches=coaches)


def test_invite_requires_follow_edge_and_valid_role(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    with pytest.raises(RaceError) as e:
        r.invite("ann", eid, role="racing", user_id="dan")  # no edge either way
    assert e.value.status == 404
    with pytest.raises(RaceError):
        r.invite("ann", eid, role="boss", user_id="bob")
    with pytest.raises(RaceError) as e:
        r.invite("ann", eid, role="crew", code=rp.soc.invite_code("dan"))
    assert e.value.status == 403
    assert r.invite("ann", eid, role="crew", code=rp.soc.invite_code("cat"))["notify"] == "cat"
    with pytest.raises(RaceError):
        r.invite("ann", "nope", role="crew", user_id="bob")  # not my event
    with pytest.raises(RaceError):
        r.invite("bob", eid, role="crew", user_id="ann")  # bob doesn't own that event id
    # Coaches only via existing links.
    with pytest.raises(RaceError):
        r.invite("ann", eid, role="coach", coach_email="other@x.com")
    p = r.invite("ann", eid, role="coach", coach_email="Coach@x.com")["person"]
    assert p["status"] == "accepted" and p["user_id"] is None
    assert [x["role"] for x in r.view("ann", eid)["people"]] == ["coach", "crew"]
    rp.coaches["ann"] = set()  # coach link removed -> gone from the list
    assert [x["role"] for x in r.view("ann", eid)["people"]] == ["crew"]


def test_email_invites_are_enumeration_safe(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    real = r.invite("ann", eid, role="crew", email="Bob@x.com")
    ghost = r.invite("ann", eid, role="crew", email="nobody@x.com")
    stranger = r.invite("ann", eid, role="crew", email="dan@x.com")  # on Rabbit, not a friend
    assert real["by_email"] and ghost["by_email"] and stranger["by_email"]
    assert real["notify"] == "bob" and ghost["notify"] is None and stranger["notify"] is None
    rows = r.view("ann", eid)["people"]
    # The inviter only ever sees the typed email for email invites while pending.
    assert sorted(x["email"] for x in rows) == ["bob@x.com", "dan@x.com", "nobody@x.com"]
    assert all(x["user_id"] is None for x in rows)
    assert r.inbox("dan") == [] and len(r.inbox("bob")) == 1
    # Duplicate: no second notification.
    assert r.invite("ann", eid, role="pacer", email="bob@x.com")["notify"] is None
    assert r.inbox("bob")[0]["role"] == "pacer"


def test_accept_racing_copies_event_and_links_group(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    pid = r.invite("ann", eid, role="racing", user_id="bob")["person"]["id"]
    inv = r.inbox("bob")
    assert inv[0]["event"]["name"] == "Leadville 100" and inv[0]["from"] == "ann"
    with pytest.raises(RaceError):
        r.respond("cat", pid, True)  # not theirs
    res = r.respond("bob", pid, True)
    mine = rp.events.get("bob", res["event_id"])
    assert (mine["name"], mine["date"], mine["location"], mine["url"], mine["priority"], mine["notes"]) == \
        ("Leadville 100", RACE_DAY, "Leadville, CO", "https://leadville.example/race", "B", "Racing with Ann")
    ta, tb = r.team("ann", eid), r.team("bob", res["event_id"])
    assert ta["group"] == tb["group"]
    assert [m["user_id"] for m in ta["members"]] == ["bob"] and [m["user_id"] for m in tb["members"]] == ["ann"]
    assert r.inbox("bob") == [] and r.following("bob") == []  # racing isn't "following"
    assert r.related_people("ann", "bob") and not r.related_people("ann", "dan")
    # Re-inviting a teammate is a no-op (no second push).
    assert r.invite("ann", eid, role="racing", user_id="bob")["notify"] is None
    assert r.summary("ann")[eid]["racing"] == 1


def test_accept_racing_reuses_matching_event(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    own = rp.events.create("cat", {"name": "leadville 100", "date": RACE_DAY})
    pid = r.invite("ann", eid, role="racing", user_id="cat")["person"]["id"]
    assert r.respond("cat", pid, True)["event_id"] == own["id"]
    assert len(rp.events.list("cat")) == 1


def test_crew_pacer_spectator_follow_and_decline(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    r.put_settings("ann", eid, {"crew_notes": "Meet at Twin Lakes 10am", "tracking_url": "https://track.example/x"})
    p1 = r.invite("ann", eid, role="crew", user_id="bob")["person"]["id"]
    p2 = r.invite("ann", eid, role="spectator", user_id="cat")["person"]["id"]
    before = len(rp.events.list("bob"))
    r.respond("bob", p1, True)
    assert len(rp.events.list("bob")) == before  # nothing added to their calendar / plan
    f = r.following("bob")
    assert f[0]["role"] == "crew" and f[0]["crew_notes"] == "Meet at Twin Lakes 10am"
    assert f[0]["tracking_url"] == "https://track.example/x" and f[0]["owner"] == "ann"
    assert r.respond("cat", p2, False)["role"] == "spectator"
    assert r.following("cat") == [] and all(p["id"] != p2 for p in r.view("ann", eid)["people"])
    # Guest stops following.
    r.leave("bob", p1)
    assert r.following("bob") == []
    # Unfollowing ends access to an accepted race too.
    p3 = r.invite("ann", eid, role="pacer", user_id="bob")["person"]["id"]
    r.respond("bob", p3, True)
    edge = rp.soc.people("bob")["following"][0]["edge_id"]
    rp.soc.unfollow("bob", edge)
    assert r.following("bob") == []
    with pytest.raises(RaceError):
        r.put_settings("ann", eid, {"tracking_url": "javascript:alert(1)"})
    with pytest.raises(RaceError):
        r.put_settings("ann", eid, {"crew_notes": "x" * 1001})


def test_remove_person_revokes_and_event_delete_cleans_up(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    pid = r.invite("ann", eid, role="racing", user_id="bob")["person"]["id"]
    bob_eid = r.respond("bob", pid, True)["event_id"]
    r.remove("ann", eid, pid)
    assert r.team("ann", eid) is None and r.team("bob", bob_eid) is None
    with pytest.raises(RaceError):
        r.messages("bob", bob_eid)
    assert rp.events.get("bob", bob_eid)["name"] == "Leadville 100"  # their copy stays
    # Event deletion drops people, the share link and the group.
    pid = r.invite("ann", eid, role="racing", user_id="bob")["person"]["id"]
    r.respond("bob", pid, True)
    c = r.invite("ann", eid, role="crew", user_id="cat")["person"]["id"]
    r.respond("cat", c, True)
    token = r.share_create("ann", eid)
    assert r.resolve(token) is not None
    rp.events.delete("ann", eid)
    assert r.resolve(token) is None and r.following("cat") == []
    assert r.summary("ann") == {}
    assert rp.store.global_doc("racepeople").load().get("groups") == {}


def test_group_chat_participants_only(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    pid = r.invite("ann", eid, role="racing", user_id="bob")["person"]["id"]
    bob_eid = r.respond("bob", pid, True)["event_id"]
    m, others = r.post("ann", eid, "See you at the start!")
    assert others == ["bob"] and m["by"] == "ann"
    assert [x["text"] for x in r.messages("bob", bob_eid)] == ["See you at the start!"]
    cheer, _ = r.post("bob", bob_eid, None, kind="cheer")
    assert cheer["kind"] == "cheer"
    # cat crews: not a participant of the chat.
    c = r.invite("ann", eid, role="crew", user_id="cat")["person"]["id"]
    r.respond("cat", c, True)
    with pytest.raises(RaceError):
        r.messages("cat", eid)
    with pytest.raises(RaceError):
        r.post("ann", eid, " ")
    for i in range(505):
        r.post("ann", eid, f"m{i}")
    assert len(r.messages("ann", eid)) == 500


def test_share_link_render_escaped_and_toggles() -> None:
    ev = {"id": "e1", "name": "<script>x</script> 100", "date": "2026-10-20", "location": "Leadville",
          "type": "trail", "url": "https://race.example", "notes": "my private notes"}
    s = {"show_finish": False, "show_grade": False, "show_week": False, "crew_notes": "<b>Aid</b> at mile 40",
         "tracking_url": "", "team_grade": False, "team_finish": False}
    finish = {"estimate": {"mid_s": 36000, "low_s": 34000, "high_s": 39000, "text": "9:26–10:50"}}
    page = render("Ann Smith", ev, s, date(2026, 10, 14), grade="B+", finish=finish, distance_km=100,
                  week=[("Mon Oct 12", "Easy run · 40 min")])
    assert "<script>" not in page and "&lt;script&gt;" in page and "&lt;b&gt;Aid" in page
    assert "noindex" in page and "Ann is racing" in page and "6 days to go" in page
    assert "B+" not in page and "9:26" not in page and "Easy run" not in page  # toggles off
    assert "my private notes" not in page and "Smith" not in page
    assert "Crew essentials" in page
    on = render("Ann", ev, s | {"show_finish": True, "show_grade": True, "show_week": True}, date(2026, 10, 14),
                grade="B+", finish=finish, distance_km=100, week=[("Mon Oct 12", "Easy run · 40 min")])
    assert "B+" in on and "9:26" in on and "Easy run" in on and "50.0 km" in on
    day = render("Ann", ev, s | {"tracking_url": "https://track.example"}, date(2026, 10, 20))
    assert "Race day" in day and "no live tracking" in day and "https://track.example" in day
    assert pace_rows({"estimate": {"mid_s": 3600}}, 10, True)[-1][0] == "Finish (6.2 mi)"
    tri = {"estimate": {"mid_s": 20000}, "splits": [{"leg": "swim", "mid_s": 2000}, {"leg": "t1", "mid_s": 200},
                                                     {"leg": "bike", "mid_s": 10000}, {"leg": "t2", "mid_s": 100},
                                                     {"leg": "run", "mid_s": 7700}]}
    assert [a for a, _ in pace_rows(tri, None, False)] == ["Out of the swim", "Off the bike", "Finish"]
    assert invite_text("Bill", "crew", "Leadville 100") == "Bill invited you to crew at Leadville 100"
    plan = {"weeks": []}
    assert week_rows(None, date(2026, 10, 14)) == [] and week_rows(plan, date(2026, 10, 14)) == []


def test_share_link_revoke_and_regenerate(rp) -> None:
    r, eid = rp.r, rp.ev["id"]
    t1 = r.share_create("ann", eid)
    t2 = r.share_create("ann", eid)
    assert r.resolve(t1) is None and r.resolve(t2)[0] == "ann"
    r.share_revoke("ann", eid)
    assert r.resolve(t2) is None and r.resolve("x" * 30) is None and r.resolve(None) is None


# ------------------------------------------------------------------- http --
def _setup(env, tmp_path):
    agent, _ = env.agent([])
    today = agent._now("ann").date()
    agent.stats.activities = lambda uid, fresh=False: (today, [act(today, 11)])
    for uid in ("ann", "bob", "cat"):
        env.store.user_doc(uid, "account").save({"name": f"{uid.title()} Smith", "picture": ""})
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users=dict(ALLOW))
    push = FakePush()

    def app(uid):
        auth = WebAuth(settings, env.store, "", dev_user=uid)
        return Starlette(routes=build_app_routes(settings, auth, env.tokens, push, None, ChatRunner(agent)))
    return {u: app(u) for u in ("ann", "bob", "cat", coach_user_id("c@x.com"))}, push, agent


def _clients(apps):
    return {u: httpx2.AsyncClient(transport=httpx2.ASGITransport(app=a), base_url=BASE) for u, a in apps.items()}


def test_http_invite_accept_together_share_and_delete(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)
    race_day = (agent._now("ann").date() + timedelta(days=10)).isoformat()

    async def go() -> None:
        c = _clients(apps)
        ann, bob, cat = c["ann"], c["bob"], c["cat"]
        ev = (await ann.post("/app/api/events", headers=H, json={
            "name": "Boulder 70.3", "type": "triathlon", "distance": "70.3", "date": race_day,
            "location": "Boulder, CO"})).json()["event"]
        eid = ev["id"]
        # bob follows ann
        await bob.post("/app/api/social/follow", headers=H, json={"email": "ann@x.com"})
        e = (await ann.get("/app/api/social")).json()["pending_in"][0]["edge_id"]
        await ann.post(f"/app/api/social/requests/{e}/accept", headers=H, json={})
        # Not a friend: same answer for email; friend list pick is 404.
        r1 = await ann.post(f"/app/api/events/{eid}/people", headers=H, json={"role": "crew", "email": "cat@x.com"})
        r2 = await ann.post(f"/app/api/events/{eid}/people", headers=H, json={"role": "crew", "email": "zz@x.com"})
        assert r1.status_code == r2.status_code == 200 and r1.json()["message"] == r2.json()["message"] == GENERIC_SENT
        assert (await ann.post(f"/app/api/events/{eid}/people", headers=H,
                               json={"role": "crew", "user_id": "cat"})).status_code == 404
        assert (await cat.get("/app/api/races/invites")).json()["invites"] == []
        n = len(push.sent)
        r = await ann.post(f"/app/api/events/{eid}/people", headers=H, json={"role": "racing", "user_id": "bob"})
        assert r.status_code == 200 and r.json()["message"] == "Invite sent to Bob."
        assert push.sent[n][0] == "bob" and "invited you to race at Boulder 70.3" in push.sent[n][2]
        # Rabbit log moment with a "View invite" chip.
        turns = agent.history("bob", agent.coach.coach_thread("bob")["id"])
        mom = [t for t in turns if t.get("kind") == "moment"]
        assert mom and mom[-1]["parts"][0]["actions"][0]["id"] == "race_invite"
        inv = (await bob.get("/app/api/races/invites")).json()["invites"]
        assert inv[0]["from"]["name"] == "Ann" and inv[0]["role"] == "racing"
        acc = (await bob.post(f"/app/api/races/invites/{inv[0]['id']}/accept", headers=H, json={})).json()
        bob_eid = acc["event_id"]
        assert any(x["id"] == bob_eid for x in (await bob.get("/app/api/events")).json()["events"])
        # Racing together: no grade/finish unless opted in.
        t = (await ann.get(f"/app/api/events/{eid}/together")).json()
        assert t["members"][0]["user"]["name"] == "Bob" and t["members"][0]["grade"] is None
        assert t["members"][0]["finish"] is None
        msg = await bob.post(f"/app/api/events/{bob_eid}/together/messages", headers=H, json={"text": "Ready?"})
        assert msg.status_code == 201
        n = len(push.sent)
        await bob.post(f"/app/api/events/{bob_eid}/together/messages", headers=H, json={"text": "Again"})
        await bob.post(f"/app/api/events/{bob_eid}/together/cheer", headers=H, json={})
        assert len(push.sent) == n  # coalesced to 1/min per person per group
        got = (await ann.get(f"/app/api/events/{eid}/together/messages")).json()["messages"]
        assert [m["text"] for m in got][:2] == ["Ready?", "Again"] and got[0]["by"]["name"] == "Bob"
        assert (await cat.get(f"/app/api/events/{eid}/together/messages")).status_code == 404
        # Photos: race contacts only.
        assert (await bob.get("/app/api/races/people/ann/photo")).status_code == 404  # no photo yet, but allowed
        assert (await cat.get("/app/api/races/people/ann/photo")).status_code == 404
        # Summary for the People row.
        s = (await ann.get("/app/api/races/people")).json()["events"][eid]
        assert s["racing"] == 1 and s["people"][0]["name"] == "Bob"
        # Share link: toggles, escaped page, CSP, revoke.
        await ann.put(f"/app/api/events/{eid}/crew", headers=H, json={"crew_notes": "<i>T2</i> by the lake"})
        url = (await ann.post(f"/app/api/events/{eid}/crew/link", headers=H, json={})).json()["url"]
        path = url.replace(BASE, "")
        assert path.startswith("/app/r/")
        page = await cat.get(path)
        assert page.status_code == 200 and "&lt;i&gt;T2" in page.text and "Ann is racing" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        for leak in ("avg_hr", "151", "Readiness", "Estimated finish", "Training this week", "Smith"):
            assert leak not in page.text, leak
        assert (await ann.request("DELETE", f"/app/api/events/{eid}/crew/link", headers=H, json={})).status_code == 200
        assert (await cat.get(path)).status_code == 404
        # Deleting the event removes its people and links.
        url = (await ann.post(f"/app/api/events/{eid}/crew/link", headers=H, json={})).json()["url"]
        assert (await ann.request("DELETE", f"/app/api/events/{eid}", headers=H, json={})).status_code == 200
        assert (await cat.get(url.replace(BASE, ""))).status_code == 404
        assert (await bob.get(f"/app/api/events/{bob_eid}/together")).json()["members"] == []
        assert (await ann.get("/app/api/races/people")).json()["events"] == {}
        for x in c.values():
            await x.aclose()
    asyncio.run(go())


def test_http_coach_accounts_get_403(env, tmp_path) -> None:
    apps, _, _ = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        coach = c[coach_user_id("c@x.com")]
        for path in ("/app/api/races/invites", "/app/api/races/following", "/app/api/races/people",
                     "/app/api/events/e1/people", "/app/api/events/e1/together", "/app/api/races/people/ann/photo"):
            assert (await coach.get(path)).status_code == 403, path
        assert (await coach.post("/app/api/events/e1/people", headers=H,
                                 json={"role": "crew", "user_id": "ann"})).status_code == 403
        # The coach route needs a link to that athlete.
        assert (await coach.get("/app/api/coach/athletes/ann/events/e1/people")).status_code in (403, 404)
        for x in c.values():
            await x.aclose()
    asyncio.run(go())
