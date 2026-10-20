"""Usage counts (usage.py): validation, rate limits, daily aggregation, rolling actives,
retention, salt rotation, opt-outs, owner-only summary. Clock-independent: every test pins
its own clock."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx2
import pytest
from starlette.applications import Starlette

from garmin_mcp import legal, usage
from garmin_mcp.appstore import AppStore
from garmin_mcp.coaches import coach_user_id
from garmin_mcp.config import Settings
from garmin_mcp.tokens import generate_key
from garmin_mcp.webapp import build_app_routes
from garmin_mcp.webauth import WebAuth
from garmin_mcp.webchat import ChatRunner
from tests.test_agent import env  # noqa: F401  (fixture)

BASE = "http://localhost:8001"
H = {"origin": BASE}
DAY0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC).timestamp()


class Clock:
    def __init__(self, t: float = DAY0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def days(self, n: float) -> None:
        self.t += n * 86400


def ev(name: str, clock: Clock, **props: object) -> dict:
    return {"name": name, "props": props, "ts": int(clock() * 1000)}


@pytest.fixture
def svc(tmp_path):
    clock = Clock()
    salts = iter(f"salt{i}" for i in range(1000))
    return usage.Usage(AppStore(tmp_path, generate_key()), clock=clock, salt=lambda: next(salts)), clock


# ------------------------------------------------------------- validation --
def test_unknown_names_keys_and_values_dropped() -> None:
    now = DAY0
    ts = int(now * 1000)
    body = {"events": [
        {"name": "card_tap", "props": {"card": "upnext", "hr": "150", "note": "free text"}, "ts": ts},
        {"name": "heart_rate", "props": {"bpm": "150"}, "ts": ts},          # unknown name
        {"name": "card_tap", "props": {"card": "Anything I typed"}, "ts": ts},  # value not whitelisted
        {"name": "tab_view", "props": {"tab": 3}, "ts": ts},                # non-string value
        {"name": "rsvp", "props": {"lat": "39.7"}, "ts": ts},                # location key
        {"name": "app_open", "ts": "now"},                                   # bad ts
        {"name": "app_open", "ts": ts - 3 * 86400 * 1000},                   # too old
        {"name": "app_open", "ts": ts + 3600 * 1000},                        # too far ahead
        {"name": "app_open", "ts": True},
        "app_open", None,
    ]}
    assert usage.clean_batch(body, now) == [
        ("card_tap", {"card": "upnext"}), ("card_tap", {}), ("tab_view", {}), ("rsvp", {})]
    for bad in (None, [], {"events": "x"}, {"e": []}):
        with pytest.raises(ValueError):
            usage.clean_batch(bad, now)


def test_batch_size_cap() -> None:
    body = {"events": [{"name": "app_open", "ts": int(DAY0 * 1000)}] * 500}
    assert len(usage.clean_batch(body, DAY0)) == usage.MAX_BATCH


def test_no_free_text_health_or_location_in_whitelist() -> None:
    for name, keys in usage.EVENTS.items():
        assert name.isidentifier()
        for k, values in keys.items():
            assert k not in {"lat", "lon", "hr", "text", "note", "city", "zip", "sleep", "weight"}
            assert values and all(v.isidentifier() for v in values)


def test_rate_limit_per_minute_and_day(svc) -> None:
    s, clock = svc
    batch = {"events": [ev("app_open", clock)] * usage.MAX_BATCH}
    counted = [s.record("friend", batch) for _ in range(4)]
    assert counted == [50, 50, 20, 0]  # PER_MINUTE = 120
    assert s.record("holden", batch) == 50  # per person
    clock.t += 61
    assert s.record("friend", {"events": [ev("app_open", clock)] * 50}) == 50
    lim = usage.RateLimit(clock)
    total = 0
    for _ in range(200):
        clock.t += 61
        total += lim.take("x", 120)
    assert datetime.fromtimestamp(clock(), UTC).date() == date(2026, 3, 2)
    assert total == usage.PER_DAY


# ------------------------------------------------------------ aggregation --
def test_daily_counts_and_unique_users(svc, tmp_path) -> None:
    s, clock = svc
    s.record("friend", {"events": [ev("card_tap", clock, card="upnext"), ev("card_tap", clock, card="upnext"),
                                   ev("tab_view", clock, tab="plan")]})
    s.record("holden", {"events": [ev("card_tap", clock, card="upnext"), ev("card_tap", clock, card="ring")]})
    s.record("friend", {"events": [ev("app_open", clock)]})
    sm = s.summary()
    assert sm["now"] == {"date": "2026-03-02", "dau": 2, "wau": 2, "mau": 2}
    assert sm["cards"] == [{"id": "upnext", "taps": 3, "users": 2}, {"id": "ring", "taps": 1, "users": 1}]
    assert sm["tabs"] == [{"id": "plan", "taps": 1, "users": 1}]
    assert sm["events"]["card_tap"] == 4 and sm["events"]["app_open"] == 1
    assert sm["new_users"] == 2 and len(sm["series"]) == 30
    # nothing per event, no user ids in the global doc
    raw = s._store.global_doc("usage").load()
    text = str(raw)
    assert "friend" not in text and "holden" not in text
    assert set(raw) == {"salt", "seen", "days"}
    assert s._store.user_doc("friend", "usage").load() == {"first": "2026-03-02", "last": "2026-03-02"}


def test_covered_days() -> None:
    d = date(2026, 3, 10)
    assert len(usage.covered_days(d, None, 7)) == 7 and usage.covered_days(d, None, 7)[0] == d
    assert usage.covered_days(d, d - timedelta(days=2), 7) == [d + timedelta(days=5), d + timedelta(days=6)]
    assert usage.covered_days(d, d - timedelta(days=9), 7) == [d + timedelta(days=i) for i in range(7)]


def test_rolling_actives_and_retention(svc) -> None:
    s, clock = svc
    a = lambda uid: s.record(uid, {"events": [ev("app_open", clock)]})  # noqa: E731
    a("friend"); a("holden")                       # day 0: both new
    clock.days(1); a("friend")                     # day 1: friend back (d1)
    clock.days(6); a("holden")                     # day 7: holden back (d7)
    clock.days(1); a("carol")                      # day 8: carol new
    clock.days(2)                                  # day 10: nobody
    sm = s.summary()
    by = {r["date"]: r for r in sm["series"]}
    assert by["2026-03-02"]["dau"] == 2 and by["2026-03-03"]["dau"] == 1
    # WAU on day 7 (Mar 9) = holden (today) + friend (day 1): 2; day 8 (Mar 10) = holden, carol (friend's day 1 aged out)
    assert by["2026-03-09"]["wau"] == 2 and by["2026-03-10"]["wau"] == 2
    assert by["2026-03-08"]["wau"] == 2  # friend (Mar 3) + holden (Mar 2)
    assert by["2026-03-12"]["dau"] == 0 and by["2026-03-12"]["wau"] == 2 and by["2026-03-12"]["mau"] == 3
    r = sm["retention"]
    assert r["d1"] == {"cohort": 3, "returned": 1, "pct": 33}  # Mar 2 (2 new, 1 back) + carol (Mar 10, complete)
    assert r["d7"] == {"cohort": 2, "returned": 1, "pct": 50}  # only Mar 2's cohort is 7+ days old
    assert usage.retention({}, date(2026, 3, 1), 7) == {"cohort": 0, "returned": 0, "pct": None}


def test_salt_rotates_daily_and_old_hashes_go(svc) -> None:
    s, clock = svc
    s.record("friend", {"events": [ev("app_open", clock)]})
    d1 = s._store.global_doc("usage").load()
    s.record("friend", {"events": [ev("app_open", clock)]})  # same day: same salt, same hashes
    assert s._store.global_doc("usage").load()["salt"] == d1["salt"]
    assert s._store.global_doc("usage").load()["seen"] == d1["seen"]
    clock.days(1)
    s.record("friend", {"events": [ev("app_open", clock)]})
    d2 = s._store.global_doc("usage").load()
    assert d2["salt"]["day"] == "2026-03-03" and d2["salt"]["v"] != d1["salt"]["v"]
    assert not set(d1["seen"]) & set(d2["seen"])  # can't be linked across days
    assert len(d2["seen"]) == len(d1["seen"])
    # old counters are pruned after KEEP_DAYS
    clock.days(usage.KEEP_DAYS + 5)
    s.record("holden", {"events": [ev("app_open", clock)]})
    assert "2026-03-02" not in s._store.global_doc("usage").load()["days"]


def test_funnel(svc) -> None:
    s, clock = svc
    for uid, steps in (("a1", 7), ("a2", 3), ("a3", 1)):
        s.record(uid, {"events": [ev("setup_step", clock, step=x) for x in usage.SETUP_STEPS[:steps]]
                       + [ev("setup_step", clock, step="intro")]})
    s.record("a1", {"events": [ev("setup_complete", clock)]})
    f = {x["step"]: (x["users"], x["pct"]) for x in s.summary()["funnel"]}
    assert f["intro"] == (3, 100) and f["race"] == (2, 67) and f["goal"] == (2, 67)
    assert f["you"] == (1, 33) and f["complete"] == (1, 33)


# -------------------------------------------------------------------- API --
def _app(env, tmp_path, user: str):  # noqa: F811
    agent, _ = env.agent([])
    settings = Settings(public_base_url=BASE, data_dir=tmp_path, app_enabled=True, mcp_enabled=False,
                        owner_user_ids=("friend",))
    return Starlette(routes=build_app_routes(settings, WebAuth(settings, env.store, "", dev_user=user),
                                             env.tokens, None, None, ChatRunner(agent)))


def test_api_owner_only_coach_403_and_opt_outs(env, tmp_path) -> None:  # noqa: F811
    owner, other = _app(env, tmp_path, "friend"), _app(env, tmp_path, "holden")
    coach = _app(env, tmp_path, coach_user_id("coach@example.com"))
    now = int(datetime.now(UTC).timestamp() * 1000)
    body = {"events": [{"name": "card_tap", "props": {"card": "upnext"}, "ts": now},
                       {"name": "bogus", "ts": now}]}

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=owner), base_url=BASE) as o, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other), base_url=BASE) as n, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach), base_url=BASE) as c:
            assert (await o.get("/app/api/me")).json()["owner"] is True
            assert (await n.get("/app/api/me")).json()["owner"] is False
            r = await n.post("/app/api/usage", headers=H, json=body)
            assert r.status_code == 200 and r.json() == {"counted": 1}
            assert (await n.post("/app/api/usage", json=body)).status_code == 403  # origin
            assert (await n.post("/app/api/usage", headers=H, json={"x": 1})).status_code == 400
            big = {"events": [{"name": "app_open", "ts": now, "props": {"pad": "x" * 400}}] * 60}
            assert (await n.post("/app/api/usage", headers=H, json=big)).status_code == 413
            # Do Not Track / GPC
            assert (await n.post("/app/api/usage", headers={**H, "DNT": "1"}, json=body)).json() == {"counted": 0}
            assert (await n.post("/app/api/usage", headers={**H, "Sec-GPC": "1"}, json=body)).json() == {"counted": 0}
            # owner-only summary
            assert (await n.get("/app/api/usage/summary")).status_code == 403
            sm = await o.get("/app/api/usage/summary")
            assert sm.status_code == 200 and sm.json()["cards"][0] == {"id": "upnext", "taps": 1, "users": 1}
            # coach accounts: 403 both ways
            assert (await c.post("/app/api/usage", headers=H, json=body)).status_code == 403
            assert (await c.get("/app/api/usage/summary")).status_code == 403
            # "Don't count my usage": nothing counted, own dates forgotten
            assert env.store.user_doc("holden", "usage").load()
            r = await n.put("/app/api/settings", headers=H, json={"usage_off": True})
            assert r.json()["usage_off"] is True
            assert env.store.user_doc("holden", "usage").load() == {}
            assert (await n.post("/app/api/usage", headers=H, json=body)).json() == {"counted": 0}
            assert (await o.get("/app/api/usage/summary")).json()["cards"][0]["taps"] == 1
    asyncio.run(go())


def test_privacy_page_says_what_is_counted() -> None:
    p = legal.privacy()
    assert "Usage counts" in p and "Don't count my usage" in p and "Do Not Track" in p
    assert "never free text, health or training data, or location" in p
