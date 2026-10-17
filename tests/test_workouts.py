"""Workouts from every source (workouts.py) and coming-soon demand (demand.py): one model,
the no-double-counting rule (Garmin first), the per-user import store, Oura workouts kept
display-only (never in Stats/plan/AI inputs), auto-share cards, "I want this" votes counted
once per person, owner-only counts, coach 403."""

from __future__ import annotations

import ast
import asyncio
from datetime import date, timedelta
from pathlib import Path

import httpx2
from starlette.applications import Starlette

from garmin_mcp import workouts as wo
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.community import Community
from garmin_mcp.config import Settings
from garmin_mcp.demand import Demand, DemandError
from garmin_mcp.oura import OuraClient
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_friends_share import fx  # noqa: F401  (fixture)
from tests.test_plancal import ATHLETE
from tests.test_profile import BASE, COACH, _apps

SRC = Path(__file__).resolve().parents[1] / "src" / "garmin_mcp"
G_RUN = {"activity_id": 11, "date": "2026-10-13 07:00:00", "name": "Denver Running", "sport": "running",
         "duration": "0:45:00", "distance_km": 8.0, "avg_hr": 150}
O_RUN = {"id": "o-run", "activity": "running", "start_datetime": "2026-10-13T07:04:00-06:00",
         "end_datetime": "2026-10-13T07:48:00-06:00", "distance": 7900, "calories": 520, "label": None}
O_YOGA = {"id": "o-yoga", "activity": "yoga", "start_datetime": "2026-10-13T18:00:00-06:00",
          "end_datetime": "2026-10-13T18:40:00-06:00", "distance": None, "calories": 120}


def test_model_from_oura_and_garmin() -> None:
    o = wo.from_oura(O_RUN)
    assert o == {"key": "oura:o-run", "source": "oura", "id": "o-run", "sport": "run", "name": "Run",
                 "start": "2026-10-13T07:04:00", "minutes": 44, "km": 7.9, "avg_hr": None, "calories": 520.0}
    assert wo.from_oura({"activity": "running"}) is None  # no id / time: can't place it
    g = wo.from_garmin(G_RUN)
    assert g["sport"] == "run" and g["minutes"] == 45 and g["start"] == "2026-10-13T07:00:00"
    assert wo.garmin_sport("virtual_ride") == "bike" and wo.garmin_sport("lap_swimming") == "swim"


def test_same_workout_counts_once_garmin_first() -> None:
    g, o, y = wo.from_garmin(G_RUN), wo.from_oura(O_RUN), wo.from_oura(O_YOGA)
    assert wo.same_workout(g, o) and wo.same_workout(o, g)
    assert not wo.same_workout(g, y)  # different sport and time
    late = {**o, "start": "2026-10-13T07:20:00"}
    assert not wo.same_workout(g, late)  # starts > 10 min apart
    walk = {**o, "sport": "walk"}
    assert not wo.same_workout(g, walk)
    assert wo.merge([g], [o, y]) == [y]  # the Oura run is Garmin's run
    # Two extra sources with the same workout: the richer one (by PRIORITY) is kept.
    whoop = {**o, "key": "whoop:1", "source": "whoop"}
    assert [w["source"] for w in wo.merge([], [o, whoop])] == ["whoop"]


def test_store_save_visible_by_day_and_drop(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    ext = wo.ExternalWorkouts(store, clock=lambda: 1000.0)
    items = [wo.from_oura(O_RUN), wo.from_oura(O_YOGA)]
    assert sorted(ext.save("ann", "oura", items, date(2026, 10, 14))) == ["oura:o-run", "oura:o-yoga"]
    assert ext.save("ann", "oura", items, date(2026, 10, 14)) == []  # nothing new the second time
    assert ext.imported_at("ann", "oura") == 1000.0
    # Garmin has the run: only the yoga shows; without Garmin both do.
    assert [w["key"] for w in ext.visible("ann", [G_RUN])] == ["oura:o-yoga"]
    assert len(ext.visible("ann", [])) == 2
    day = ext.by_day("ann", [G_RUN])["2026-10-13"]
    assert day == [{"id": None, "name": "Workout", "sport": "other", "km": None, "minutes": 40,
                    "avg_hr": None, "source": "oura"}]
    # Old ones age out.
    assert ext.save("ann", "oura", [], date(2027, 6, 1)) == [] and ext.all("ann") == []
    ext.save("ann", "oura", items, date(2026, 10, 14))
    wo.drop_source(store, "ann", "oura")
    assert ext.all("ann") == [] and ext.imported_at("ann", "oura") is None


def test_oura_disconnect_deletes_imported_workouts(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    wo.ExternalWorkouts(store).save("ann", "oura", [wo.from_oura(O_RUN)], date(2026, 10, 14))
    OuraClient(store, "id", "secret", "https://x/cb").disconnect("ann")
    assert wo.ExternalWorkouts(store).all("ann") == []


def test_oura_workouts_never_reach_ai_inputs() -> None:
    """Imported workouts live in the extworkouts doc and are read only by the Day view merge,
    the import itself and the feed share (webapp.py). Nothing the coach reads touches them."""
    for f in SRC.glob("*.py"):
        if f.name in ("workouts.py", "webapp.py", "oura.py"):
            continue
        text = f.read_text()
        assert "ExternalWorkouts" not in text and '"extworkouts"' not in text, f.name
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("workouts") \
                    and node.module != "workouttargets":
                raise AssertionError(f"{f.name} imports workouts.py")
    web = (SRC / "webapp.py").read_text()
    # The merge happens in the route only, after the calendar view the agent can also use.
    assert "_ext_w.by_day(uid, acts)" in web and "def _cal_with_imports" in web


def test_auto_share_external_card(fx) -> None:  # noqa: F811
    cm, today = fx.cm, fx.clock.at.date()
    w = {**wo.from_oura(O_RUN), "start": f"{today.isoformat()}T07:04:00"}
    assert cm.auto_share_external("ann", [w], today) == []  # sharing not on
    cm.put_settings("ann", {"share_prompted": True})
    posted = cm.auto_share_external("ann", [w], today)
    assert len(posted) == 1 and cm.auto_share_external("ann", [w], today) == []  # once
    card = cm.feed("bob")["items"][0]["workout"]
    assert card["source"] == "oura" and card["title"] == "Run" and card["km"] == 7.9 and card["minutes"] == 44
    assert "avg_hr" not in card and "calories" not in card
    assert Community.sharing_workouts(cm.settings("ann"))


def test_demand_votes_count_each_person_once(tmp_path, fernet_key) -> None:
    d = Demand(AppStore(tmp_path / "app", fernet_key), clock=lambda: 5.0)
    assert d.vote("ann", "whoop", True) is True and d.vote("ann", "whoop", True) is True
    d.vote("bob", "whoop", True)
    d.vote("bob", "coros", True)
    assert d.counts() == {"whoop": 2, "apple": 0, "coros": 1}
    assert d.vote("bob", "whoop", False) is False and d.counts()["whoop"] == 1
    assert d.voters("whoop") == ["ann"] and d.mine("bob") == {"coros"}
    rows = d.rows("ann", owner=False)
    assert [r["id"] for r in rows] == ["whoop", "apple", "coros"] and rows[0]["wanted"] is True
    assert all("wanted_by" not in r for r in rows)
    assert d.rows("ann", owner=True)[0]["wanted_by"] == 1
    try:
        d.vote("ann", "garmin", True)
        raise AssertionError("garmin isn't coming soon")
    except DemandError:
        pass


def test_want_api_owner_counts_and_coach_403(env, tmp_path) -> None:  # noqa: F811
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        allowed_google_users={"friend@example.com": "friend", "other@example.com": "other"},
                        owner_user_ids=("friend",))
    runner = ChatRunner(agent)

    def app(user: str) -> Starlette:
        return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=user),
                                                 env.tokens, None, None, runner))
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app("friend")), base_url=BASE) as owner, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app("other")), base_url=BASE) as member, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app(coach_user_id(COACH))), base_url=BASE) as c:
            r = await member.post("/app/api/connections/whoop/want", headers=h, json={"want": True})
            assert r.status_code == 200 and r.json() == {"app": "whoop", "wanted": True}  # no count for members
            r = await owner.post("/app/api/connections/whoop/want", headers=h, json={"want": True})
            assert r.json()["wanted_by"] == 2
            soon = (await member.get("/app/api/connections")).json()["soon"]
            assert [s["id"] for s in soon] == ["whoop", "apple", "coros"]
            assert soon[0]["wanted"] is True and "wanted_by" not in soon[0]
            assert (await owner.get("/app/api/connections")).json()["soon"][0]["wanted_by"] == 2
            assert (await member.post("/app/api/connections/garmin/want", headers=h, json={"want": True})).status_code == 400
            assert (await member.post("/app/api/connections/whoop/want", headers=h, json={})).status_code == 400
            assert (await member.post("/app/api/connections/whoop/want", json={"want": True})).status_code == 403  # no origin
            assert (await c.post("/app/api/connections/whoop/want", headers=h, json={"want": True})).status_code == 403
    asyncio.run(go_())


def test_calendar_route_merges_imported_workouts(env, tmp_path) -> None:  # noqa: F811
    """GET /app/api/plan/calendar lists an Oura-only workout under "extra" with its source."""
    agent, _ = env.agent([])
    agent.plans._pause = 0
    today = agent._now("friend").date()
    agent.coach.update_athlete("friend", dict(ATHLETE))
    agent.coach.create_goal("friend", {"title": "Half", "distance": "half marathon",
                                       "date": (today + timedelta(weeks=12)).isoformat()})
    agent.plans.build("friend")
    w = {**wo.from_oura(O_YOGA), "start": f"{today.isoformat()}T18:00:00"}
    wo.ExternalWorkouts(env.store).save("friend", "oura", [w], today)
    athlete_app, _, _ = _apps(env, tmp_path, agent)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as c:
            cal = (await c.get("/app/api/plan/calendar")).json()["cal"]
            rows = cal["extra"][today.isoformat()]
            assert [r["source"] for r in rows if r.get("source")] == ["oura"]
    asyncio.run(go_())
