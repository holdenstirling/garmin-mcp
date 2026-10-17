"""Apple Watch via the athlete's iPhone Shortcut (applehealth.py): lenient parsing of what
Shortcuts sends (dates, durations, distances, workout types), the import key (hash only, rotate,
revoke), the public import endpoint (Bearer only, rate and size limits), storage as display-only
external workouts (deduped against Garmin), the Connected apps row, and that nothing of it can
reach Rabbit's AI."""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx2

from garmin_mcp import applehealth as ah
from garmin_mcp import workouts as wo
from garmin_mcp.account import DROP_DOCS
from garmin_mcp.appstore import AppStore
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

SRC = Path(__file__).resolve().parents[1] / "src" / "garmin_mcp"
NOW = datetime(2026, 10, 17, 12, 0)


def test_dates_in_the_shapes_shortcuts_sends() -> None:
    want = datetime(2026, 10, 17, 7, 2)
    for s in ("Oct 17, 2026 at 7:02 AM", "Oct 17, 2026 at 7:02 AM", "October 17, 2026 at 7:02 AM",
              "17 Oct 2026 at 07:02", "10/17/26, 7:02 AM", "17.10.26, 07:02", "2026-10-17T07:02:00-06:00",
              "2026-10-17T07:02:00Z", "2026-10-17 07:02", "Today at 7:02 AM"):
        assert ah.parse_when(s, today=NOW) == want, s
    assert ah.parse_when("Oct 17, 2026 at 7:02:55 PM") == datetime(2026, 10, 17, 19, 2, 55)
    for bad in ("", "soon", "Oct 32, 2026 at 7:02 AM", "13:99", None, 5, "x" * 100):
        assert ah.parse_when(bad, today=NOW) is None, bad


def test_durations_distances_and_types() -> None:
    for v, mins in ((45, 45), ("45", 45), ("45 min", 45), ("1 hr 5 min", 65), ("1h 5m", 65),
                    ("1:05:00", 65), ("3720 s", 62), ("44.5", 44.5)):
        assert ah.parse_minutes(v) == mins, v
    assert ah.parse_minutes("0") is None and ah.parse_minutes(True) is None and ah.parse_minutes("lots") is None
    assert ah.parse_km("8.4 km") == 8.4 and ah.parse_km("5.2 mi") == 8.37 and ah.parse_km("1,500 m") == 1.5
    assert ah.parse_km("5,2 km") == 5.2
    assert ah.parse_km(5.2, imperial=False) == 5.2 and ah.parse_km(5.2, imperial=True) == 8.37
    assert ah.parse_km(3.1, "mi", imperial=False) == 4.99
    assert ah.parse_km("0 mi") is None and ah.parse_km("far") is None and ah.parse_km("3 parsecs") is None
    cases = {"Running": "run", "Outdoor Run": "run", "HKWorkoutActivityTypeCycling": "bike", "Indoor Cycle": "bike",
             "Pool Swim": "swim", "Open Water Swim": "swim", "Walking": "walk", "Hiking": "hike",
             "Traditional Strength Training": "strength", "Functional Strength Training": "strength",
             "Yoga": "other", "High Intensity Interval Training": "other", "Rowing": "other", "": "other"}
    for k, sport in cases.items():
        assert ah.sport_of(k) == sport, k


def test_payload_shapes_keep_only_safe_fields() -> None:
    one = {"type": "Running", "start": "Oct 17, 2026 at 7:02 AM", "end": "Oct 17, 2026 at 7:48 AM",
           "distance": "5.2 mi", "heartRate": 151, "activeEnergy": "520 kcal", "source": "Holden's Apple Watch"}
    yoga = {"Workout Type": "Yoga", "Start Date": "Oct 16, 2026 at 6:00 PM", "Duration": "30 min", "Distance": "0 mi"}
    lift = {"type": "Traditional Strength Training", "start": "2026-10-15T06:00:00", "duration": 40, "distance": "1 mi"}
    for body in ([one, yoga, lift], {"workouts": [one, yoga, lift]},
                 "\n".join(json.dumps(x) for x in (one, yoga, lift)),          # Combine Text output
                 {"workouts": [json.dumps(one), json.dumps(yoga), json.dumps(lift)]},  # a list of Text items
                 json.dumps({"workouts": [one, yoga, lift]}).encode()):
        got, skipped = ah.parse_payload(body, now=NOW)
        assert skipped == 0 and len(got) == 3, body
        by = {w["sport"]: w for w in got}
        run = by["run"]
        assert run == {"key": "apple:20261017T0702-run", "source": "apple", "id": "20261017T0702-run", "sport": "run",
                       "name": "Running", "start": "2026-10-17T07:02:00", "minutes": 46, "km": 8.37,
                       "avg_hr": None, "calories": None}
        assert by["other"]["minutes"] == 30 and by["other"]["km"] is None and by["other"]["name"] == "Yoga"
        assert by["strength"]["km"] is None and by["strength"]["minutes"] == 40
    # Same workout twice -> once; unplaceable, future or very old -> skipped.
    got, skipped = ah.parse_payload([one, one, {"type": "Run"}, {**one, "start": "Oct 19, 2026 at 7:02 AM"},
                                     {**one, "start": "Jan 2, 2026 at 7:02 AM"}, "junk", 7], now=NOW)
    assert len(got) == 1 and skipped == 5
    assert ah.parse_payload("not json at all", now=NOW) == ([], 0)
    assert ah.parse_payload(None, now=NOW) == ([], 0)
    assert len(ah.parse_payload([one] * (ah.MAX_ITEMS + 50), now=NOW)[0]) == 1
    # The key is safe for /app/api/activity/<key>.
    import re
    assert re.fullmatch(r"[a-z]{2,12}:[A-Za-z0-9_.-]{1,64}", got[0]["key"])


def test_keys_hash_only_rotate_and_revoke(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    k = ah.ImportKeys(store, clock=lambda: 100.0)
    assert k.status("ann") is None and k.lookup("rbt_" + "x" * 30) is None
    t1 = k.create("ann")
    assert t1.startswith("rbt_") and k.lookup(t1) == "ann"
    assert t1 not in json.dumps(store.user_doc("ann", "applehealth").load())  # only the hash is kept
    assert t1 not in json.dumps(store.global_doc("applehealth-index").load())
    k.note_import("ann", 3, 2)
    t2 = k.create("ann")
    assert k.lookup(t1) is None and k.lookup(t2) == "ann"
    assert k.status("ann") == {"created": 100, "last_import": 100, "last_received": 3, "last_new": 2}
    k.revoke("ann")
    assert k.lookup(t2) is None and k.status("ann") is None
    for bad in (None, "", "short", t2[4:], "rbt_" + "y" * 200, 12):
        assert k.lookup(bad) is None
    assert ah.bearer("Bearer abc") == "abc" and ah.bearer("bearer  abc ") == "abc"
    assert ah.bearer("Basic abc") is None and ah.bearer(None) is None
    assert "applehealth" in DROP_DOCS  # never in the data export


def test_dedupes_against_garmin(tmp_path, fernet_key) -> None:
    store = AppStore(tmp_path / "app", fernet_key)
    ext = wo.ExternalWorkouts(store)
    w, _ = ah.parse_payload([{"type": "Running", "start": "2026-10-13T07:03:00", "duration": "44 min"},
                             {"type": "Hiking", "start": "2026-10-13T15:00:00", "duration": "2:00:00"}], now=NOW)
    ext.save("ann", "apple", w, NOW.date())
    garmin = [{"activity_id": 11, "date": "2026-10-13 07:00:00", "name": "Denver Running", "sport": "running",
               "duration": "0:45:00", "distance_km": 8.0}]
    assert [x["sport"] for x in ext.visible("ann", garmin)] == ["hike"]  # Garmin's run wins
    wo.drop_source(store, "ann", "apple")
    assert ext.all("ann") == []


def test_never_reaches_the_ai() -> None:
    """Only the route module touches applehealth.py; it never imports agent-side code."""
    for f in SRC.glob("*.py"):
        if f.name in ("applehealth.py", "webapp.py"):
            continue
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("applehealth"):
                raise AssertionError(f"{f.name} imports applehealth.py")
            if isinstance(node, ast.ImportFrom) and node.level and any(a.name == "applehealth" for a in node.names):
                raise AssertionError(f"{f.name} imports applehealth.py")
    tree = ast.parse((SRC / "applehealth.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert mods <= {"__future__", "hashlib", "json", "re", "secrets", "time", "collections.abc", "datetime", "typing"}


def test_api_key_import_status_and_disconnect(env, tmp_path) -> None:  # noqa: F811
    agent, _ = env.agent([])
    athlete_app, coach_app, other_app = _apps(env, tmp_path, agent)
    h = {"origin": BASE}
    day = datetime.now() - timedelta(days=1)
    stamp = day.strftime("%b %d, %Y at %I:%M %p")
    payload = "\n".join(json.dumps(x) for x in (
        {"type": "Running", "start": stamp, "duration": "30 min", "distance": "3 mi", "heartRate": 160},
        {"type": "Yoga", "start": (day - timedelta(hours=5)).isoformat(timespec="minutes"), "duration": "20 min"}))

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=other_app), base_url=BASE) as o:
            r = await a.get("/app/api/apple-health")
            assert r.status_code == 200 and r.json()["on"] is False and r.json()["available"] is True
            assert r.json()["endpoint"].endswith("/app/api/import/apple-health")
            assert (await a.post("/app/api/apple-health/key", json={})).status_code == 403  # no origin
            assert (await c.post("/app/api/apple-health/key", headers=h, json={})).status_code == 403  # coach
            r = await a.post("/app/api/apple-health/key", headers=h, json={})
            key = r.json()["key"]
            assert r.status_code == 200 and r.json()["on"] is True and key.startswith("rbt_")
            row = {x["id"]: x for x in (await a.get("/app/api/connections")).json()["apps"]}["apple"]
            assert row["connected"] is True and row["kind"] == "shortcut" and row["last_sync"] is None
            # The import: Bearer key only (no cookie, no Origin needed), never in the URL.
            url = "/app/api/import/apple-health"
            assert (await o.post(url, content=payload)).status_code == 401
            assert (await o.post(url, content=payload, headers={"authorization": "Bearer rbt_" + "z" * 30})).status_code == 401
            r = await o.post(url, content=payload, headers={"authorization": f"Bearer {key}"})
            assert r.status_code == 200, r.text
            assert r.json()["received"] == 2 and r.json()["new"] == 2 and "Rabbit got 2 workouts" in r.json()["message"]
            r = await o.post(url, content=payload, headers={"authorization": f"Bearer {key}"})
            assert r.json()["new"] == 0  # same workouts again: nothing new
            stored = [w for w in env.store.user_doc("friend", "extworkouts").load()["items"].values()]
            assert {w["source"] for w in stored} == {"apple"} and all(w["avg_hr"] is None for w in stored)
            assert "160" not in json.dumps(stored)
            st = (await a.get("/app/api/apple-health")).json()
            assert st["workouts"] == 2 and st["last_received"] == 2 and st["last_new"] == 0 and st["last_import"]
            # Its own activity page, display-only (not for the AI).
            run = next(w for w in stored if w["sport"] == "run")
            r = await a.get(f"/app/api/activity/{run['key']}")
            assert r.status_code == 200 and r.json()["source"] == "apple" and r.json()["ai"] is False
            # Nothing found -> a helpful message, not an error.
            r = await o.post(url, content="[]", headers={"authorization": f"Bearer {key}"})
            assert r.status_code == 200 and r.json()["received"] == 0 and "didn't find any workouts" in r.json()["message"]
            # Too big.
            big = "[" + ",".join(['{"type":"Running"}'] * 20000) + "]"
            r = await o.post(url, content=big, headers={"authorization": f"Bearer {key}"})
            assert r.status_code == 413
            # A new key stops the old one.
            key2 = (await a.post("/app/api/apple-health/key", headers=h, json={})).json()["key"]
            assert (await o.post(url, content="[]", headers={"authorization": f"Bearer {key}"})).status_code == 401
            # Turn off, keeping the workouts; then again, removing them.
            r = await a.post("/app/api/apple-health/disconnect", headers=h, json={})
            assert r.json()["on"] is False and r.json()["workouts"] == 2
            assert (await o.post(url, content="[]", headers={"authorization": f"Bearer {key2}"})).status_code == 401
            await a.post("/app/api/apple-health/key", headers=h, json={})
            r = await a.post("/app/api/apple-health/disconnect", headers=h, json={"remove": True})
            assert r.json()["workouts"] == 0
    asyncio.run(go_())


def test_import_is_rate_limited(env, tmp_path) -> None:  # noqa: F811
    agent, _ = env.agent([])
    athlete_app, _, _ = _apps(env, tmp_path, agent)

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a:
            key = (await a.post("/app/api/apple-health/key", headers={"origin": BASE}, json={})).json()["key"]
            codes = [(await a.post("/app/api/import/apple-health", content="[]",
                                   headers={"authorization": f"Bearer {key}"})).status_code for _ in range(32)]
            assert codes[:30] == [200] * 30 and codes[-1] == 429
            # Guessing keys from one address runs out too.
            bad = [(await a.post("/app/api/import/apple-health", content="[]",
                                 headers={"authorization": "Bearer rbt_" + "q" * 30})).status_code for _ in range(40)]
            assert 429 in bad
    asyncio.run(go_())
