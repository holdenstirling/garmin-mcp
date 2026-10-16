"""TrainingPeaks two-way sync in the Rabbit app (tpsync.py, tp_web.py): connect + encrypted
storage, pull + dedupe against the Rabbit plan, push create/update/delete of our own workouts
only, source-of-truth switching, move sync, expiry -> needs attention, TrainingPeaks 403,
coach accounts 403. TrainingPeaks is a MockTransport fake; nothing touches the network."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any

import httpx2

from garmin_mcp import connections as conn
from garmin_mcp import legal, tpsync
from garmin_mcp.appstore import AppStore
from garmin_mcp.tpsync import TPSync, TPUserError, compact, structure_lines
from tests.test_agent import env  # noqa: F401  (fixture)
from tests.test_profile import BASE, _apps

ATHLETE = 777
COOKIE = "tpauth-" + "x" * 60
TODAY = date(2026, 10, 16)


def d(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


class FakeTP:
    """Just enough of tpapi.trainingpeaks.com for the app: token, user, range, CRUD."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.token_status = 200
        self.status_override: int | None = None
        self.next_id = 500
        self.workouts: dict[int, dict[str, Any]] = {
            # coach's run, matches Rabbit's 50' run on day +1
            11: {"workoutId": 11, "workoutDay": f"{d(1)}T00:00:00", "workoutTypeValueId": 3,
                 "title": "Aerobic run", "totalTimePlanned": 0.75, "description": "Easy, flat.",
                 "coachComments": "Keep HR under 150."},
            # coach's bike with structure, nothing in Rabbit that day
            12: {"workoutId": 12, "workoutDay": f"{d(3)}T00:00:00", "workoutTypeValueId": 2,
                 "title": "Sweet spot", "totalTimePlanned": 1.0, "structure": json.dumps({
                     "primaryIntensityMetric": "percentOfFtp", "structure": [
                         {"type": "repetition", "length": {"value": 3, "unit": "repetition"},
                          "steps": [{"name": "On", "length": {"value": 600, "unit": "second"},
                                     "targets": [{"minValue": 88, "maxValue": 93}]}]}]})},
            # completed, never planned: Garmin's job, skipped
            13: {"workoutId": 13, "workoutDay": f"{d(-1)}T00:00:00", "workoutTypeValueId": 3,
                 "title": "Run", "totalTime": 0.5, "distance": 5000.0},
            # past planned swim (for the Garmin link)
            14: {"workoutId": 14, "workoutDay": f"{d(-2)}T00:00:00", "workoutTypeValueId": 1,
                 "title": "CSS swim", "totalTimePlanned": 0.75},
        }

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path == "/users/v3/token":
            if request.headers.get("cookie") != f"Production_tpAuth={COOKIE}" or self.token_status != 200:
                return httpx2.Response(401)
            return httpx2.Response(200, json={"success": True, "token": {"access_token": "bear", "expires_in": 3600}})
        assert request.headers.get("authorization") == "Bearer bear"
        if self.status_override:
            return httpx2.Response(self.status_override)
        if path == "/users/v3/user":
            return httpx2.Response(200, json={"user": {"personId": ATHLETE, "firstName": "Sam",
                                                       "athletes": [{"athleteId": ATHLETE}]}})
        prefix = f"/fitness/v6/athletes/{ATHLETE}/workouts"
        parts = path[len(prefix) + 1:].split("/") if path.startswith(prefix + "/") else []
        if len(parts) == 2 and request.method == "GET":
            s, e = parts
            return httpx2.Response(200, json=[w for w in self.workouts.values()
                                              if s <= w["workoutDay"][:10] <= e])
        if path == prefix and request.method == "POST":
            wid, self.next_id = self.next_id, self.next_id + 1
            self.workouts[wid] = {**body, "workoutId": wid}
            return httpx2.Response(200, json=self.workouts[wid])
        if len(parts) == 1:
            wid = int(parts[0])
            if wid not in self.workouts:
                return httpx2.Response(404)
            if request.method == "GET":
                return httpx2.Response(200, json=self.workouts[wid])
            if request.method == "PUT":
                self.workouts[wid] = body
                return httpx2.Response(200, json=body)
            if request.method == "DELETE":
                del self.workouts[wid]
                return httpx2.Response(204)
        return httpx2.Response(500)

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls if m in ("POST", "PUT", "DELETE")]


def sess(sid: str, sport: str, minutes: int, title: str = "", **kw: Any) -> dict[str, Any]:
    return {"id": sid, "sport": sport, "kind": kw.pop("kind", "easy"), "title": title or f"{sport} {minutes}'",
            "minutes": minutes, "detail": "", "steps": kw.pop("steps", []), **kw}


def make(tmp_path, fernet_key, plan: dict[str, Any] | None = None, acts: list | None = None,
         spawn=None) -> tuple[TPSync, FakeTP, dict[str, Any], AppStore]:
    fake = FakeTP()
    store = AppStore(tmp_path / "app", fernet_key)
    box = {"plan": plan, "clock": 1_000_000.0}
    tp = TPSync(store, plan=lambda u: box["plan"], today=lambda u: TODAY,
                activities=(lambda u: acts or []), transport=httpx2.MockTransport(fake),
                clock=lambda: box["clock"], spawn=spawn or (lambda fn: fn()))
    return tp, fake, box, store


def plan_of(days: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"weeks": [{"index": 1, "days": days}]}


BIKE_STEPS = [{"type": "warmup", "minutes": 10, "zone": 1},
              {"type": "repeat", "reps": 3, "steps": [{"type": "work", "minutes": 8, "zone": 4},
                                                      {"type": "recover", "minutes": 4, "zone": 1}]},
              {"type": "cooldown", "minutes": 10, "zone": 1}]


# ----------------------------------------------------------------- connect --
def test_connect_stores_cookie_encrypted_never_logged(tmp_path, fernet_key) -> None:
    tp, fake, _, store = make(tmp_path, fernet_key)
    records: list[str] = []
    h = logging.Handler()
    h.emit = lambda r: records.append(r.getMessage() + json.dumps(getattr(r, "__dict__", {}), default=str))
    logging.getLogger("garmin_mcp").addHandler(h)
    try:
        # A bad paste is refused without calling TrainingPeaks; a rejected one stores nothing.
        try:
            tp.connect("friend", "short")
            raise AssertionError("expected TPUserError")
        except TPUserError:
            pass
        try:
            tp.connect("friend", "Production_tpAuth=" + "y" * 50)
            raise AssertionError("expected TPUserError")
        except TPUserError as e:
            assert "didn't accept" in str(e)
        assert not tp.connected("friend")
        # The whole cookie header form works (tp_login_cli.clean_cookie).
        out = tp.connect("friend", f"foo=1; Production_tpAuth={COOKIE}; bar=2")
    finally:
        logging.getLogger("garmin_mcp").removeHandler(h)
    assert out["name"] == "Sam" and tp.connected("friend")
    raw = (tmp_path / "app" / "users" / "friend" / "trainingpeaks.fernet").read_bytes()
    assert COOKIE.encode() not in raw  # Fernet-encrypted at rest
    assert store.user_doc("friend", "trainingpeaks").load()["cookie"] == COOKIE
    assert not any(COOKIE in r for r in records)
    assert "cookie" not in json.dumps(tp.view("friend"))
    tp.disconnect("friend")
    assert not tp.connected("friend") and tp.view("friend")["state"] == "not_connected"


# ------------------------------------------------------------ pull + dedupe --
def test_pull_dedupes_against_rabbit_plan_and_links_garmin(tmp_path, fernet_key) -> None:
    plan = plan_of({d(1): [sess("r1", "run", 50)], d(2): [sess("b2", "bike", 60)]})
    acts = [{"activity_id": 9001, "date": f"{d(-2)} 06:00:00", "sport": "lap_swimming", "duration": "0:44:00"}]
    tp, fake, box, _ = make(tmp_path, fernet_key, plan, acts)
    tp.connect("friend", COOKIE)
    assert tp.sync("friend")["ok"]
    v = tp.view("friend")
    ids = {i["id"]: i for i in v["items"]}
    assert set(ids) == {11, 12, 14}  # the completed-only entry (13) comes from Garmin, not TP
    run = ids[11]
    assert run["sport"] == "run" and run["minutes"] == 45 and run["coach_notes"] == "Keep HR under 150."
    assert run["session_id"] == "r1"  # same day + sport + similar duration
    assert ids[12]["session_id"] is None and ids[12]["structure"][0].startswith("3x: On 10' 88-93%")
    assert ids[14]["garmin_activity_id"] == 9001  # linked, not copied
    # Default source = TrainingPeaks (coach): the TP run shows, Rabbit's twin is hidden.
    assert v["source"] == "trainingpeaks" and v["hide_sessions"] == ["r1"] and run["show"]
    assert not fake.writes()  # nothing written to TrainingPeaks unasked
    # Range: 14 days back, 42 ahead.
    gets = [p for m, p, _ in fake.calls if m == "GET" and p.count("/") == 7]
    assert gets[-1].endswith(f"/{d(-14)}/{d(42)}")


def test_compact_and_structure_lines() -> None:
    assert compact({"workoutId": 1, "workoutDay": "2026-10-20T00:00:00", "workoutTypeValueId": 7}) is None  # day off
    assert structure_lines("not json") == [] and structure_lines({"structure": "x"}) == []


# --------------------------------------------------------------------- push --
def test_push_creates_updates_moves_deletes_only_ours(tmp_path, fernet_key) -> None:
    days = {d(0): [sess("b0", "bike", 54, "Threshold bike", kind="threshold", steps=BIKE_STEPS)],
            d(1): [sess("r1", "run", 50)],
            d(5): [sess("s5", "swim", 45, meters=2000)],
            d(20): [sess("far", "run", 30)]}  # beyond the 14-day window
    tp, fake, box, store = make(tmp_path, fernet_key, plan_of(days))
    tp.connect("friend", COOKIE)
    tp.set_source("friend", "rabbit")
    pushed = store.user_doc("friend", "tp_sync").load()["pushed"]
    assert set(pushed) == {"b0", "r1", "s5"}  # next 14 days only
    bike = fake.workouts[pushed["b0"]["wid"]]
    assert bike["workoutTypeValueId"] == 2 and "structure" in bike and bike["description"].endswith("Planned in Rabbit.")
    assert json.loads(bike["structure"])["primaryIntensityMetric"] == "percentOfFtp"
    assert fake.workouts[pushed["s5"]["wid"]]["distancePlanned"] == 2000.0 and "structure" not in fake.workouts[pushed["s5"]["wid"]]
    # Rabbit is the source: our pushed run and the coach's run both match r1 -> one shown.
    v = tp.view("friend")
    assert v["hide_sessions"] == []
    shown = [i for i in v["items"] if i["show"]]
    assert {i["id"] for i in shown} == {12, 14}  # unmatched coach workouts still show
    # Nothing changed -> a second push writes nothing.
    n = len(fake.writes())
    tp.sync("friend")
    assert len(fake.writes()) == n
    # Edit, move and delete in Rabbit.
    days[d(1)][0]["minutes"] = 70
    days[d(3)] = [days.pop(d(5))[0]]  # swim moved to day +3
    del days[d(0)]                     # bike deleted
    tp.sync("friend")
    after = store.user_doc("friend", "tp_sync").load()["pushed"]
    assert fake.workouts[after["r1"]["wid"]]["totalTimePlanned"] == round(70 / 60, 4)
    assert fake.workouts[after["s5"]["wid"]]["workoutDay"].startswith(d(3))
    assert pushed["b0"]["wid"] not in fake.workouts and "b0" not in after
    # Never touched workouts we didn't create.
    assert {11, 12, 13, 14} <= set(fake.workouts)
    touched = {int(p.rsplit("/", 1)[1]) for m, p in fake.writes() if m in ("PUT", "DELETE")}
    assert touched <= {r["wid"] for r in pushed.values()}
    # A pushed workout that got completed data is never deleted.
    fake.workouts[after["r1"]["wid"]]["totalTime"] = 1.1
    days.pop(d(1))
    tp.sync("friend")
    assert after["r1"]["wid"] in fake.workouts


def test_plan_write_hook_pushes_only_for_rabbit_source(tmp_path, fernet_key) -> None:
    days = {d(1): [sess("r1", "run", 50)]}
    tp, fake, box, store = make(tmp_path, fernet_key, plan_of(days))
    tp.connect("friend", COOKIE)
    tp.on_plan_write("friend", "plan-g1")  # TrainingPeaks is the source: nothing pushed
    assert not fake.writes()
    tp.set_source("friend", "rabbit")
    n = len(fake.writes())
    days[d(2)] = [sess("b2", "bike", 40)]
    tp.on_plan_write("friend", "profile")  # not a plan doc
    assert len(fake.writes()) == n
    tp.on_plan_write("friend", "plan-g1")
    assert len(fake.writes()) == n + 1


# --------------------------------------------------------- source switching --
def test_source_switching(tmp_path, fernet_key) -> None:
    tp, fake, box, store = make(tmp_path, fernet_key, plan_of({d(1): [sess("r1", "run", 50)]}))
    tp.connect("friend", COOKIE)
    assert tp.push("friend") == {"created": 0, "updated": 0, "deleted": 0}
    v = tp.set_source("friend", "rabbit")
    assert v["source"] == "rabbit" and v["hide_sessions"] == []
    ours = store.user_doc("friend", "tp_sync").load()["pushed"]["r1"]["wid"]
    v = tp.set_source("friend", "trainingpeaks")
    assert "r1" in v["hide_sessions"]  # TP shows; our workout stays in TrainingPeaks
    assert ours in fake.workouts and tp.push("friend")["created"] == 0
    try:
        tp.set_source("friend", "garmin")
        raise AssertionError("expected TPUserError")
    except TPUserError:
        pass


# --------------------------------------------------------------------- move --
def test_move_syncs_date_to_trainingpeaks(tmp_path, fernet_key) -> None:
    tp, fake, box, store = make(tmp_path, fernet_key, plan_of({d(1): [sess("r1", "run", 50)]}))
    tp.connect("friend", COOKIE)
    tp.sync("friend")
    v = tp.move("friend", 12, d(4))
    assert fake.workouts[12]["workoutDay"] == f"{d(4)}T00:00:00" and fake.workouts[12]["title"] == "Sweet spot"
    assert next(i for i in v["items"] if i["id"] == 12)["date"] == d(4)
    for wid, day, status in ((12, d(-1), 400), (999, d(2), 404)):
        try:
            tp.move("friend", wid, day)
            raise AssertionError("expected TPUserError")
        except TPUserError as e:
            assert e.status == status
    # Rabbit source: our own pushed workout follows the Rabbit session instead.
    tp.set_source("friend", "rabbit")
    ours = store.user_doc("friend", "tp_sync").load()["pushed"]["r1"]["wid"]
    try:
        tp.move("friend", ours, d(2))
        raise AssertionError("expected TPUserError")
    except TPUserError as e:
        assert e.status == 409 and "Rabbit" in str(e)


# --------------------------------------------------- expiry, 403, backoff --
def test_expiry_needs_attention_and_403_and_backoff(tmp_path, fernet_key) -> None:
    tp, fake, box, store = make(tmp_path, fernet_key)
    tp.connect("friend", COOKIE)
    tp.sync("friend")
    assert tp.status("friend")["attention"] is False
    # TrainingPeaks refuses: friendly error, not an exception.
    fake.status_override = 403
    tp.client.invalidate("friend")
    r = tp.sync("friend")
    assert not r["ok"] and "Premium" in r["error"]
    # Rate limited: backoff, and the tick doesn't hammer it.
    fake.status_override = 429
    r = tp.sync("friend")
    assert "busy" in r["error"] and tp.in_backoff("friend")
    n = len(fake.calls)
    store.user_doc("friend", "tp_sync").update(lambda st: st.update(pulled_at=0, tried_at=0))  # pull is due
    tp.tick("friend")
    assert len(fake.calls) == n  # ...but backing off
    box["clock"] += 3600 + tpsync.PULL_EVERY_S
    fake.status_override = None
    tp.tick("friend")
    assert len(fake.calls) > n and tp.status("friend")["error"] is None
    # The session expires -> Needs attention, the tick stops, reconnect clears it.
    fake.token_status = 401
    tp.client.invalidate("friend")
    tp.sync("friend")
    st = tp.status("friend")
    assert st["attention"] and "Reconnect" in st["error"]
    row = conn.status("trainingpeaks", available=True, connected=st["connected"], error=st["error"], attention=st["attention"])
    assert row["state"] == "attention"
    n = len(fake.calls)
    box["clock"] += 10 * tpsync.PULL_EVERY_S
    tp.tick("friend")
    assert len(fake.calls) == n
    fake.token_status = 200
    tp.connect("friend", COOKIE)
    assert not tp.status("friend")["attention"]


# --------------------------------------------------------- privacy + routes --
def test_privacy_page_and_facts() -> None:
    page = legal.privacy()
    assert "<b>TrainingPeaks</b>" in page and "never changes or deletes ones it didn't create" in page
    assert "never asks for your TrainingPeaks password" in page
    facts = conn.APPS["trainingpeaks"]
    assert any("Garmin only" in s for s in facts["never"]) and "Completed workouts are not imported from TrainingPeaks" in page


def test_routes_connect_view_move_and_coach_403(env, tmp_path, monkeypatch) -> None:
    fake = FakeTP()
    shift = (date.today() - TODAY).days  # the app uses the real date here
    for w in fake.workouts.values():
        w["workoutDay"] = (date.fromisoformat(w["workoutDay"][:10]) + timedelta(days=shift)).isoformat() + "T00:00:00"
    monkeypatch.setattr(tpsync, "TRANSPORT", httpx2.MockTransport(fake))
    agent, _ = env.agent([])
    athlete_app, coach_app, _ = _apps(env, tmp_path, agent)
    h = {"origin": BASE}

    async def go_() -> None:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=athlete_app), base_url=BASE) as a, \
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=coach_app), base_url=BASE) as c:
            rows = (await a.get("/app/api/connections")).json()["apps"]
            tpr = next(x for x in rows if x["id"] == "trainingpeaks")
            assert tpr["state"] == "not_connected" and tpr["kind"] == "cookie"
            assert (await a.post("/app/api/trainingpeaks/connect", json={"cookie": COOKIE})).status_code == 403  # origin
            r = await a.post("/app/api/trainingpeaks/connect", headers=h, json={"cookie": "nope"})
            assert r.status_code == 400
            r = await a.post("/app/api/trainingpeaks/connect", headers=h, json={"cookie": COOKIE})
            assert r.status_code == 200 and r.json()["name"] == "Sam"
            assert COOKIE not in r.text
            v = r.json()["view"]
            assert {i["id"] for i in v["items"]} >= {11, 12}
            rows = (await a.get("/app/api/connections")).json()["apps"]
            assert next(x for x in rows if x["id"] == "trainingpeaks")["state"] == "connected"
            r = await a.post("/app/api/connections/trainingpeaks/sync", headers=h, json={})
            assert r.status_code == 200 and r.json()["app"]["connected"]
            r = await a.post("/app/api/trainingpeaks/workouts/12/move", headers=h, json={"date": "2099-01-05"})
            assert r.status_code == 200 and fake.workouts[12]["workoutDay"].startswith("2099-01-05")
            assert (await a.post("/app/api/trainingpeaks/workouts/x/move", headers=h, json={"date": "2099-01-05"})).status_code == 400
            r = await a.put("/app/api/trainingpeaks/settings", headers=h, json={"source": "rabbit"})
            assert r.status_code == 200 and r.json()["source"] == "rabbit"
            # Coach accounts can't use any of it.
            for m, p in (("GET", "/app/api/trainingpeaks"), ("POST", "/app/api/trainingpeaks/sync"),
                         ("POST", "/app/api/trainingpeaks/connect")):
                assert (await c.request(m, p, headers=h, json={})).status_code == 403
            assert (await a.post("/app/api/trainingpeaks/disconnect", headers=h, json={})).status_code == 200
            assert (await a.post("/app/api/trainingpeaks/sync", headers=h, json={})).status_code == 409
    asyncio.run(go_())
