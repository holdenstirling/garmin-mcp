"""What brings you to Rabbit: intents (validation, order), context line, quests, welcome flags, API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import intent
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.coaching import CoachError
from garmin_mcp.config import Settings
from garmin_mcp.progress import quests_view
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
H = {"origin": BASE}


# ------------------------------------------------------------- validation --
def test_validate_keeps_tap_order_and_dedupes() -> None:
    assert intent.validate_intents(["community", "train", "community", "events"]) == ["community", "train", "events"]
    assert intent.validate_intents(None) == [] and intent.validate_intents([]) == []
    assert intent.INTENT_IDS == ("train", "consistent", "community", "events", "coach", "explore")


@pytest.mark.parametrize("bad", ["train", {"train": 1}, ["race"], [1], ["train", None]])
def test_validate_rejects(bad) -> None:
    with pytest.raises(CoachError):
        intent.validate_intents(bad)


def test_athlete_field_validated_and_ordered(env) -> None:  # noqa: F811
    agent, _ = env.agent([])
    a = agent.coach.update_athlete("friend", {"intents": ["events", "train"]})
    assert a["intents"] == ["events", "train"]
    with pytest.raises(CoachError):
        agent.coach.update_athlete("friend", {"intents": ["races"]})
    with pytest.raises(CoachError):  # server-written only
        agent.coach.update_athlete("friend", {"welcomed_at": "2026-01-01"})
    assert intent.primary(a["intents"]) == "events" and intent.primary([]) is None


# ------------------------------------------------------------ context line --
def test_context_line(env) -> None:  # noqa: F811
    assert intent.context_line([]) == ""
    line = intent.context_line(["community", "events"])
    assert line.startswith("Uses rabbt mainly for") and line.index("friends, clubs") < line.index("events, races")
    assert "don't push a race plan" in line
    assert "don't push" not in intent.context_line(["train", "community"])
    assert "—" not in line
    agent, _ = env.agent([])
    agent.coach.update_athlete("friend", {"intents": ["consistent"]})
    intent.save(env.store, "friend", ["consistent"])
    ctx = agent.coach.context_block("friend", agent._now("friend"), None)
    assert ctx.count("Uses rabbt mainly for") == 1 and "staying active and consistent" in ctx
    assert "welcomed_at" not in ctx and "intents:" not in ctx


# ------------------------------------------------------------------ quests --
def _core(qs) -> list[str]:
    return [q["id"] for q in qs if not q["optional"]]


def test_quests_by_intent() -> None:
    base = quests_view({}, {})
    assert _core(base) == ["garmin", "sports", "goal", "plan", "sync", "notify"]  # no intents: unchanged
    assert quests_view({}, {}, []) == base
    train = quests_view({}, {}, ["train"])
    assert {"plan", "sync"} <= set(_core(train)) and train[0]["id"] == "garmin"
    community = quests_view({}, {}, ["community"])
    assert "plan" not in _core(community) and "sync" not in _core(community)
    assert "friend" in _core(community) and [q["id"] for q in community][:2] == ["garmin", "friend"]
    ev = quests_view({}, {}, ["events", "coach"])
    ids = [q["id"] for q in ev]
    assert ids.index("interests") < ids.index("coach_status") < ids.index("plan")
    assert {"interests", "coach_status"} <= set(_core(ev))
    both = quests_view({}, {}, ["community", "train"])
    assert {"plan", "sync", "friend"} <= set(_core(both))
    explore = quests_view({}, {}, ["explore"])
    assert _core(explore) == ["garmin", "sports", "goal", "notify"]


# ---------------------------------------------------------------- welcome --
def test_welcome_mode_first_run_vs_existing() -> None:
    assert intent.welcome_mode({}, existing=False) == "full"
    assert intent.welcome_mode({"units": "metric"}, existing=True) == "lite"
    assert intent.welcome_mode({"welcomed_at": "2026-10-14T00:00:00+00:00"}, existing=False) is None
    assert not intent.is_existing({"intents": ["train"]}, garmin_connected=False, has_goal=False)
    assert intent.is_existing({}, garmin_connected=True, has_goal=False)
    assert intent.is_existing({}, garmin_connected=False, has_goal=True)
    assert intent.is_existing({"weekly_hours": 6}, garmin_connected=False, has_goal=False)


def test_save_and_skip(env) -> None:  # noqa: F811
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    a = intent.save(env.store, "holden", ["train", "community"], now=now)
    assert a["intents"] == ["train", "community"] and a["welcomed_at"] == "2026-10-14T12:00:00+00:00"
    a = intent.save(env.store, "holden", None, skip=True)
    assert a["intents"] == ["train", "community"]  # skip keeps the earlier answer
    with pytest.raises(CoachError):
        intent.save(env.store, "holden", ["nope"])


# -------------------------------------------------------------------- API --
def _app(env, tmp_path, user: str):  # noqa: F811
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False)
    return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=user),
                                             env.tokens, None, None, ChatRunner(agent))), agent


def test_api_first_run_existing_and_coach(env, tmp_path) -> None:  # noqa: F811
    new_app, _ = _app(env, tmp_path, "holden")  # no Garmin, nothing set up
    old_app, agent = _app(env, tmp_path, "friend")  # Garmin connected: an existing user
    coach_app, _ = _app(env, tmp_path, coach_user_id("coach@example.com"))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=new_app), base_url=BASE) as n, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=old_app), base_url=BASE) as o, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            assert (await n.get("/app/api/me")).json()["welcome"] == "full"
            assert (await o.get("/app/api/me")).json()["welcome"] == "lite"
            g = (await n.get("/app/api/intent")).json()
            assert g["intents"] == [] and g["welcome"] == "full" and len(g["options"]) == 6
            assert all("—" not in x["title"] + x["help"] for x in g["options"])
            # bad input
            assert (await n.post("/app/api/intent", headers=H, json={"intents": ["nope"]})).status_code == 400
            assert (await n.post("/app/api/intent", headers=H, json={})).status_code == 400
            assert (await n.post("/app/api/intent", headers=H, json={"intents": [], "x": 1})).status_code == 400
            assert (await n.get("/app/api/me")).json()["welcome"] == "full"  # nothing saved
            # answer: saved in tap order, never shown again
            r = await n.post("/app/api/intent", headers=H, json={"intents": ["community", "events"]})
            assert r.status_code == 200, r.text
            assert r.json()["intents"] == ["community", "events"] and r.json()["welcome"] is None
            me = (await n.get("/app/api/me")).json()
            assert me["welcome"] is None and me["athlete"]["intents"] == ["community", "events"]
            p = (await n.get("/app/api/progress")).json()
            core = [q["id"] for q in p["quests"] if not q["optional"]]
            assert "plan" not in core and "friend" in core and "interests" in core
            assert p["setup"]["total"] == len(core)
            # existing user skips: welcomed, no intents
            r = await o.post("/app/api/intent", headers=H, json={"skip": True})
            assert r.status_code == 200 and r.json()["intents"] == [] and r.json()["welcomed_at"]
            assert (await o.get("/app/api/me")).json()["welcome"] is None
            # re-opened from Settings later: a new answer replaces the old one
            r = await o.post("/app/api/intent", headers=H, json={"intents": ["train"]})
            assert r.json()["intents"] == ["train"]
            # coach accounts: athlete-only
            assert (await c.get("/app/api/intent")).status_code == 403
            assert (await c.post("/app/api/intent", headers=H, json={"skip": True})).status_code == 403
            assert (await c.get("/app/api/me")).json()["welcome"] is None
            # mutating calls need the origin
            assert (await n.post("/app/api/intent", json={"skip": True})).status_code == 403
    asyncio.run(go_())
    assert "Uses rabbt mainly for" in agent.coach.context_block("friend", agent._now("friend"), None)
