"""Share by text (sharelinks.py): public read-only links for one workout / event / club / invite.
Token secrecy, revoke -> 404, privacy (no heart rate or location unless chosen), escaping."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx2

from garmin_mcp import sharelinks as sl
from garmin_mcp.appstore import AppStore
from garmin_mcp.planbuilder import iter_sessions
from garmin_mcp.tokens import generate_key
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_plancal import ATHLETE
from tests.test_profile import BASE, _apps


def _store(tmp_path) -> AppStore:
    return AppStore(tmp_path / "app", generate_key())


def test_tokens_are_hashed_revocable_and_capped(tmp_path) -> None:
    s = _store(tmp_path)
    links = sl.ShareLinks(s)
    token, lid = links.create("u1", "invite", "invite", sl.invite_snap(who="Holden Ottolini"))
    raw = s.global_doc("sharelinks-index").load()
    assert token not in str(raw) and token not in str(s.user_doc("u1", "sharelinks").load())  # only hashes
    uid, rec = links.resolve(token)
    assert uid == "u1" and rec["snap"]["who"] == "Holden" and rec["views"] == 1
    assert links.resolve(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert links.resolve("short") is None
    assert [x["id"] for x in links.list("u1")] == [lid]
    assert links.revoke("u1", lid) and links.resolve(token) is None and not links.revoke("u1", lid)
    t2, _ = links.create("u1", "event", "e1", {"title": "A"})
    t3, _ = links.create("u1", "event", "e1", {"title": "A"})
    assert links.revoke_ref("u1", "event", "e1") == 2 and links.resolve(t2) is None and links.resolve(t3) is None


def test_daily_limit(tmp_path) -> None:
    links = sl.ShareLinks(_store(tmp_path), clock=lambda: 1_800_000_000)
    for _ in range(sl.CREATES_PER_DAY):
        links.create("u1", "invite", "invite", {"title": "x"})
    try:
        links.create("u1", "invite", "invite", {"title": "x"})
        raise AssertionError("limit")
    except sl.ShareError as e:
        assert e.status == 429


def test_recorded_workout_hides_heart_rate_unless_chosen_and_imports_never() -> None:
    view = {"name": "Lunch Run", "sport": "run", "source": "garmin", "start": "2026-10-16 12:00:00",
            "numbers": {"km": 8.0, "moving_s": 2400, "pace_s_per_km": 300, "avg_hr": 151, "max_hr": 170,
                        "elevation_gain_m": 40},
            "laps": [{"n": 1, "km": 1.609, "s": 480, "pace_s_per_km": 298, "hr": 149},
                     {"n": 2, "km": 1.609, "s": 470, "pace_s_per_km": 292, "hr": 155}]}
    snap = sl.activity_snap(view, who="Holden", imperial=True)
    assert "bpm" not in str(snap) and snap["facts"][:3] == ["5.0 mi", "40:00", "8:03/mi"] and not snap["hr"]
    assert "131 ft climb" in snap["facts"] and snap["laps"][0]["pace"] == "8:00/mi"
    page = sl.render(snap, url="u", og_image="i", cta_url="c", cta_label="Open")
    assert "bpm" not in page and "No heart rate or location" in page
    with_hr = sl.activity_snap(view, who="Holden", imperial=True, include_hr=True)
    assert "avg 151 bpm" in with_hr["facts"] and with_hr["laps"][1]["hr"] == "155 bpm"
    oura = sl.activity_snap(view | {"source": "oura"}, who="Holden", imperial=False, include_hr=True)
    assert "bpm" not in str(oura) and oura["facts"][0] == "8.0 km"


def test_render_escapes_user_text() -> None:
    snap = sl.event_snap({"name": "<script>alert(1)</script>", "date": "2026-11-01", "time": "18:30",
                          "neighborhood": "Baker\" onload=\"x", "location": "123 Main St, Denver"}, who="<b>Eve</b>")
    assert snap["where"] == 'Baker" onload="x'  # neighborhood wins over the street address
    page = sl.render(snap, url="https://x/app/l/t", og_image="https://x/og.png", cta_url="https://x/app/", cta_label="Join")
    assert "<script>" not in page and "&lt;script&gt;" in page and 'onload="x' not in page
    assert "123 Main" not in page and "Sun Nov 1 · 6:30 PM" in page
    assert '<meta property="og:title" content="&lt;script&gt;alert(1)&lt;/script&gt;">' in page


def test_default_text_reads_naturally() -> None:
    snap = {"kind": "workout", "who": "Holden", "title": "Long run", "when": "Sat Oct 17 · 7:00 AM",
            "facts": ["1h 25m", "10.0 mi"]}
    assert sl.default_text(snap) == "Holden's long run Sat Oct 17: 1h 25m, 10.0 mi. Join me?"
    assert sl.default_text({"kind": "event", "title": "Leadville 100", "when": "Sat Aug 21", "race": True}) \
        == "I'm racing Leadville 100 Sat Aug 21. Follow along!"


def test_share_routes(env, tmp_path) -> None:
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    sid = next(s["id"] for _, d, s in iter_sessions(agent.plans.get("friend"))
               if s["sport"] == "run" and d >= today.isoformat())
    _, acts = agent.stats.activities("friend")
    aid = acts[0]["activity_id"]
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            r = await a.post("/app/api/sharelinks", headers=h, json={"kind": "workout", "ref": sid})
            assert r.status_code == 201, r.text
            w = r.json()
            assert w["url"].startswith(f"{BASE}/app/l/") and w["text"] and w["id"]
            path = w["url"][len(BASE):]
            page = await o.get(path)  # anyone with the link, no login needed for the page
            assert page.status_code == 200 and "noindex" in page.headers["x-robots-tag"]
            assert "og:title" in page.text and "bpm" not in page.text and "The workout" in page.text
            assert page.headers["referrer-policy"] == "no-referrer"
            r = await a.post("/app/api/sharelinks", headers=h, json={"kind": "activity", "ref": str(aid)})
            assert r.status_code == 201, r.text
            act_page = await o.get(r.json()["url"][len(BASE):])
            assert act_page.status_code == 200 and "bpm" not in act_page.text
            r = await a.post("/app/api/sharelinks", headers=h, json={"kind": "activity", "ref": str(aid), "include_hr": True})
            hr_page = await o.get(r.json()["url"][len(BASE):])
            assert "bpm" in hr_page.text or "avg_hr" not in str(acts[0])
            assert (await a.post("/app/api/sharelinks", headers=h, json={"kind": "workout", "ref": "nope"})).status_code == 404
            assert (await a.post("/app/api/sharelinks", headers=h, json={"kind": "spaceship", "ref": "x"})).status_code == 400
            assert (await c.post("/app/api/sharelinks", headers=h, json={"kind": "invite"})).status_code == 403
            assert (await a.post("/app/api/sharelinks", json={"kind": "invite"})).status_code == 403  # no origin
            inv = await a.post("/app/api/sharelinks", headers=h, json={"kind": "invite"})
            assert inv.status_code == 201 and "Rabbit" in inv.json()["text"]
            lst = (await a.get("/app/api/sharelinks")).json()["links"]
            assert {x["kind"] for x in lst} == {"workout", "activity", "invite"} and all("url" not in x for x in lst)
            assert (await a.request("DELETE", f"/app/api/sharelinks/{w['id']}", headers=h, json={})).status_code == 200
            assert (await o.get(path)).status_code == 404
            assert (await a.request("DELETE", f"/app/api/sharelinks/{w['id']}", headers=h, json={})).status_code == 404
            assert (await o.get("/app/l/" + "x" * 32)).status_code == 404
    asyncio.run(go_())
