"""Training buddies (buddies.py, buddies_web.py): opt-in only, area / radius, pace overlap,
schedule, blocking, privacy of what others see, Say hi -> DM request, coach 403."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from garmin_mcp.appstore import AppStore
from garmin_mcp.buddies import BuddyError, Buddies, match, pace_overlap, suggest
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_community import _clients, _setup
from tests.test_social import H

TODAY = date(2026, 10, 17)


def run(d: date, hhmm: str, km: float, minutes: int, sport: str = "running") -> dict:
    return {"date": f"{d.isoformat()} {hhmm}:00", "sport": sport, "distance_km": km,
            "duration": f"{minutes // 60}:{minutes % 60:02d}:00", "avg_hr": 150, "activity_id": hash((d, hhmm)) % 10_000}


def test_suggest_easy_band_and_usual_times() -> None:
    acts = []
    for wk in range(5):
        tue = TODAY - timedelta(days=TODAY.weekday() - 1 + 7 * (wk + 1))
        acts += [run(tue, "18:10", 8, 48), run(tue + timedelta(days=2), "18:30", 6, 34),
                 run(tue + timedelta(days=4), "07:00", 16, 100)]
    s = suggest(acts, TODAY)
    assert s["sports"] == ["run"]
    lo, hi = s["pace"]["run"]
    assert 330 <= lo <= hi <= 380 and lo % 5 == 0  # s/km, the easier half, rounded
    assert {"tue-evening", "thu-evening", "sat-morning"} <= set(s["slots"])
    # Too few workouts: no band, no sport.
    assert suggest(acts[:2], TODAY)["pace"] == {}


def test_match_rules_pace_schedule_distance() -> None:
    me = {"sports": ["run"], "pace": {"run": [330, 360]}, "slots": ["tue-evening", "thu-evening"],
          "center": [39.72, -104.99], "radius_mi": 10, "metro": "denver|CO", "race": "Denver Half"}
    near = {"sports": ["run", "ride"], "pace": {"run": [345, 375]}, "slots": ["tue-evening", "thu-evening"],
            "center": [39.74, -104.98], "radius_mi": 10, "metro": "denver|CO", "city": "Denver, CO", "race": "denver half"}
    m = match(me, near)
    assert m and m["sport"] == "run" and m["chips"][0] == "Similar easy pace"
    assert "Both run Tue and Thu evenings" in m["chips"] and "Both training for denver half" in m["chips"]
    assert m["distance_mi"] in (0, 1, 2) and any("mi away" in c for c in m["chips"])
    # Much faster runner, no shared time: no match. Faster but same evenings: still no (pace clashes).
    fast = {**near, "pace": {"run": [220, 240]}}
    assert match(me, fast) is None
    # Outside the smaller of the two radii.
    far = {**near, "center": [39.30, -104.99], "radius_mi": 50}
    assert match(me, far) is None
    # No point for one of them: same city only.
    assert match({**me, "center": None}, {**near, "center": None}) is not None
    assert match({**me, "center": None}, {**near, "center": None, "metro": "boulder|CO"}) is None
    # No sport in common.
    assert match(me, {**near, "sports": ["swim"]}) is None
    assert pace_overlap([330, 360], None) is None and pace_overlap([330, 360], [390, 420]) is True  # within 10 %


class World:
    def __init__(self) -> None:
        self.blocks: set[frozenset] = set()
        self.follows: set[tuple[str, str]] = set()
        self.where = {u: (39.72 + i * 0.01, -104.99) for i, u in enumerate(["ann", "bob", "cat", "dan"])}
        self.said: list[tuple[str, str, str]] = []


@pytest.fixture
def bud(tmp_path, fernet_key):
    w = World()
    acts = [run(TODAY - timedelta(days=d), "18:00", 8, 48) for d in range(1, 30, 3)]
    b = Buddies(AppStore(tmp_path, fernet_key), is_athlete=lambda u: not u.startswith("coach_"),
                blocked=lambda a, c: frozenset((a, c)) in w.blocks, follows=lambda a, c: (a, c) in w.follows,
                activities=lambda u: (TODAY, acts), area=lambda u: {"center": w.where.get(u), "radius_mi": 10},
                home=lambda u: {"city": "Denver", "state": "CO"}, person=lambda u: {"id": u, "name": u.title()},
                first_name=lambda u: u.title(), say=lambda u, o, t: (w.said.append((u, o, t)) or {"id": "c1"}))
    return b, w


PROFILE = {"sports": ["run"], "pace": {"run": [330, 360]}, "slots": ["tue-evening"], "race": "", "note": "Easy miles"}


def test_opt_in_only_pause_delete_and_privacy(bud) -> None:
    b, w = bud
    assert b.get("ann")["profile"] is None and b.get("ann")["suggested"]["sports"] == ["run"]
    assert b.matches("ann") == {"matches": [], "reason": "off"}
    b.save("ann", PROFILE)
    assert b.matches("ann")["matches"] == []  # nobody else opted in
    b.save("bob", {**PROFILE, "pace": {"run": [340, 370]}})
    ms = b.matches("ann")["matches"]
    assert [m["person"]["id"] for m in ms] == ["bob"]
    blob = json.dumps(ms)
    assert "39.7" not in blob and "-104" not in blob and "center" not in blob and "avg_hr" not in blob and "150" not in blob
    assert ms[0]["city"] == "Denver, CO" and ms[0]["note"] == "Easy miles"
    # Paused people don't show, and can't browse.
    b.save("bob", {**PROFILE, "paused": True})
    assert b.matches("ann")["matches"] == [] and b.matches("bob")["reason"] == "paused"
    b.save("bob", PROFILE)
    b.delete("bob")
    assert b.matches("ann")["matches"] == [] and b.get("bob")["profile"] is None


def test_blocking_hiding_say_hi_limits_and_coach(bud) -> None:
    b, w = bud
    for u in ("ann", "bob", "cat"):
        b.save(u, PROFILE)
    w.follows.add(("ann", "cat"))
    ms = {m["person"]["id"]: m for m in b.matches("ann")["matches"]}
    assert set(ms) == {"bob", "cat"} and ms["cat"]["following"] and not ms["bob"]["following"]
    w.blocks.add(frozenset(("ann", "bob")))
    assert [m["person"]["id"] for m in b.matches("ann")["matches"]] == ["cat"]
    assert [m["person"]["id"] for m in b.matches("bob")["matches"]] == ["cat"]
    b.hide("ann", "cat")
    assert b.matches("ann")["matches"] == []
    with pytest.raises(BuddyError) as e:
        b.say_hi("ann", "cat")
    assert e.value.status == 404  # hidden -> not a current match
    with pytest.raises(BuddyError) as e:
        b.say_hi("ann", "bob")
    assert e.value.status == 404  # blocked
    b.save("dan", PROFILE)
    assert b.say_hi("ann", "dan") == {"id": "c1"}
    assert w.said[-1][:2] == ("ann", "dan") and w.said[-1][2].startswith("Hi Dan! rabbt matched us")
    for _ in range(9):
        b.say_hi("ann", "dan", "again")
    with pytest.raises(BuddyError) as e:
        b.say_hi("ann", "dan")
    assert e.value.status == 429
    with pytest.raises(BuddyError) as e:
        b.get("coach_x")
    assert e.value.status == 403
    with pytest.raises(BuddyError):
        b.save("ann", {**PROFILE, "pace": {"run": [10, 20]}})  # nonsense band
    with pytest.raises(BuddyError):
        b.save("ann", {**PROFILE, "sports": []})


def test_http_profile_matches_hi_opens_dm_request_and_coach_403(env, tmp_path) -> None:
    apps, push, agent = _setup(env, tmp_path)

    async def go() -> None:
        c = _clients(apps)
        for u in ("ann", "bob"):
            r = await c[u].put("/app/api/athlete", headers=H, json={"home_location": "Denver, CO"})
            assert r.status_code == 200, r.text
        g = (await c["ann"].get("/app/api/buddies")).json()
        assert g["profile"] is None and g["area"]["city"] == "Denver, CO"
        assert (await c["ann"].get("/app/api/buddies/matches")).json()["reason"] == "off"
        for u in ("ann", "bob"):
            r = await c[u].put("/app/api/buddies", headers=H, json=PROFILE)
            assert r.status_code == 200, r.text
        ms = (await c["ann"].get("/app/api/buddies/matches")).json()["matches"]
        assert [m["person"]["id"] for m in ms] == ["bob"] and ms[0]["chips"][-1] == "In Denver, CO"
        r = await c["ann"].post("/app/api/buddies/bob/hi", headers=H, json={})
        assert r.status_code == 201, r.text
        req = (await c["bob"].get("/app/api/dm")).json()["requests"]
        assert len(req) == 1  # not connected: a message request
        r = await c["ann"].post("/app/api/buddies/bob/hide", headers=H, json={})
        assert r.status_code == 200 and (await c["ann"].get("/app/api/buddies/matches")).json()["matches"] == []
        assert (await c["ann"].put("/app/api/buddies", headers={}, json=PROFILE)).status_code == 403  # origin
        coach = next(k for k in c if k.startswith("coach_"))
        assert (await c[coach].get("/app/api/buddies")).status_code == 403
        r = await c["bob"].request("DELETE", "/app/api/buddies", headers=H, json={})
        assert r.status_code == 200 and (await c["bob"].get("/app/api/buddies")).json()["profile"] is None
    asyncio.run(go())
