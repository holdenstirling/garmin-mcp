"""TrainingPeaks client/service: auth exchange, calendar reads, workout writes, uploads.

TrainingPeaks is mocked with httpx2.MockTransport; nothing touches the network.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import zipfile
from datetime import date
from typing import Any

import httpx2

from garmin_mcp.providers import NotFound, RateLimited
from garmin_mcp.resilience import RateLimiter
from garmin_mcp.tokens import TokenStore
from garmin_mcp.tp_login_cli import clean_cookie
from garmin_mcp.trainingpeaks import (
    TPReauthRequired,
    TPWritesDisabled,
    TrainingPeaksClient,
    TrainingPeaksError,
    TrainingPeaksService,
    build_structure,
    fit_from_garmin_download,
    sport_for_garmin,
    sport_id,
)

ATHLETE = 4242
COOKIE = "c" * 40


class MemStore(TokenStore):
    def __init__(self, data: dict[str, str] | None = None) -> None:
        self.data = dict(data or {})

    def load(self, user_id: str) -> str | None:
        return self.data.get(user_id)

    def save(self, user_id: str, blob: str) -> None:
        self.data[user_id] = blob

    def delete(self, user_id: str) -> None:
        self.data.pop(user_id, None)


class FakeTP:
    """Just enough of tpapi.trainingpeaks.com."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.token_status = 200
        self.reject_bearer_once = False
        self.workouts: dict[int, dict[str, Any]] = {
            7: {"workoutId": 7, "workoutDay": "2026-10-12T00:00:00", "workoutTypeValueId": 3,
                "title": "Easy run", "totalTimePlanned": 0.75, "totalTime": 0.8,
                "distance": 8100.0, "tssActual": 45},
            8: {"workoutId": 8, "workoutDay": "2026-10-15T00:00:00", "workoutTypeValueId": 2,
                "title": "Sweet spot", "totalTimePlanned": 1.25, "tssPlanned": 80},
        }
        self.next_id = 100
        self.tokens_issued = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path == "/users/v3/token":
            assert request.headers.get("cookie") == f"Production_tpAuth={COOKIE}"
            if self.token_status != 200:
                return httpx2.Response(self.token_status)
            self.tokens_issued += 1
            return httpx2.Response(200, json={"success": True, "token": {
                "access_token": f"tok{self.tokens_issued}", "expires_in": 3600}})
        auth = request.headers.get("authorization", "")
        assert auth.startswith("Bearer tok"), auth
        assert "cookie" not in request.headers
        if self.reject_bearer_once:
            self.reject_bearer_once = False
            return httpx2.Response(401)
        if path == "/users/v3/user":
            return httpx2.Response(200, json={"user": {
                "personId": ATHLETE, "firstName": "Holden", "lastName": "O",
                "athletes": [{"athleteId": ATHLETE}]}})
        prefix = f"/fitness/v6/athletes/{ATHLETE}/workouts"
        if path.startswith(prefix + "/") and path.count("/") == 7 and request.method == "GET":
            return httpx2.Response(200, json=list(self.workouts.values()))
        if path == prefix and request.method == "POST":
            wid = self.next_id
            self.next_id += 1
            self.workouts[wid] = {**body, "workoutId": wid}
            return httpx2.Response(200, json=self.workouts[wid])
        if path.endswith("/filedata") and request.method == "POST":
            return httpx2.Response(200, json={"ok": True})
        if path.startswith(prefix + "/"):
            wid = int(path.rsplit("/", 1)[1])
            if wid not in self.workouts:
                return httpx2.Response(404)
            if request.method == "GET":
                return httpx2.Response(200, json=self.workouts[wid])
            if request.method == "DELETE":
                del self.workouts[wid]
                return httpx2.Response(204)
        return httpx2.Response(500)


def make(allow_writes: bool = True, store: TokenStore | None = None,
         garmin: dict[str, Any] | None = None, fit: bytes = b"FITDATA" * 10,
         limit: int = 100) -> tuple[TrainingPeaksService, FakeTP]:
    fake = FakeTP()
    client = TrainingPeaksClient(store or MemStore({"holden": COOKIE}),
                                 transport=httpx2.MockTransport(fake))
    svc = TrainingPeaksService(
        client, allow_writes=allow_writes, limiter=RateLimiter(limit),
        garmin_activity=lambda u, a: garmin or {
            "activityName": "Morning Ride", "startTimeLocal": "2026-10-13 06:30:00",
            "activityType": {"typeKey": "road_biking"}},
        garmin_file=lambda u, a: fit,
        today=lambda: date(2026, 10, 13),
    )
    return svc, fake


def _raises(exc: type[BaseException], fn: Any, *a: Any, **kw: Any) -> BaseException:
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}")


# ------------------------------------------------------------------- auth ---
def test_workouts_exchanges_cookie_once_and_reads_calendar() -> None:
    svc, fake = make()
    out = svc.workouts("holden")
    assert out["from"] == "2026-10-06" and out["to"] == "2026-10-20"
    assert out["count"] == 2
    done, planned = out["workouts"]
    assert done["completed"] is True and done["sport"] == "run"
    assert done["actual_distance_km"] == 8.1 and done["actual_duration"] == "0:48:00"
    assert planned["completed"] is False and planned["planned_tss"] == 80
    svc.workouts("holden", "2026-10-01", "2026-10-31")
    assert sum(1 for c in fake.calls if c[1] == "/users/v3/token") == 1
    assert sum(1 for c in fake.calls if c[1] == "/users/v3/user") == 1  # athlete id cached


def test_not_connected_and_expired_cookie_ask_for_login() -> None:
    svc, _ = make(store=MemStore())
    e = _raises(TPReauthRequired, svc.workouts, "holden")
    assert "garmin-mcp-trainingpeaks-login --user holden" in str(e)
    svc, fake = make()
    fake.token_status = 401
    _raises(TPReauthRequired, svc.workouts, "holden")


def test_rejected_bearer_is_refreshed_once() -> None:
    svc, fake = make()
    svc.workouts("holden")
    fake.reject_bearer_once = True
    svc.workouts("holden")
    assert fake.tokens_issued == 2


def test_range_limits_and_rate_limit() -> None:
    svc, _ = make()
    _raises(TrainingPeaksError, svc.workouts, "holden", "2026-01-01", "2026-12-31")
    _raises(TrainingPeaksError, svc.workouts, "holden", "2026-10-10", "2026-10-01")
    _raises(TrainingPeaksError, svc.workouts, "holden", "not-a-date")
    svc, _ = make(limit=1)
    svc.workouts("holden")
    _raises(RateLimited, svc.workouts, "holden")


# ----------------------------------------------------------------- writes ---
def test_writes_need_the_flag_and_make_no_calls() -> None:
    svc, fake = make(allow_writes=False)
    _raises(TPWritesDisabled, svc.create_workout, "holden", date_="2026-10-14", sport="run",
            title="Tempo")
    _raises(TPWritesDisabled, svc.delete_workout, "holden", 8)
    _raises(TPWritesDisabled, svc.upload_garmin_activity, "holden", 123)
    assert fake.calls == []


def test_create_simple_workout() -> None:
    svc, fake = make()
    out = svc.create_workout("holden", date_="2026-10-14", sport="Running", title="Tempo",
                             description="3x10' @ T", start_time="06:15",
                             duration_minutes=60, distance_km=12, tss=70)
    sent = fake.calls[-1][2]
    assert fake.calls[-1][:2] == ("POST", f"/fitness/v6/athletes/{ATHLETE}/workouts")
    assert sent["workoutDay"] == "2026-10-14T00:00:00"
    assert sent["startTimePlanned"] == "2026-10-14T06:15:00"
    assert sent["workoutTypeValueId"] == 3 and sent["athleteId"] == ATHLETE
    assert sent["totalTimePlanned"] == 1.0 and sent["distancePlanned"] == 12000.0
    assert sent["tssPlanned"] == 70 and "structure" not in sent
    assert out["created"]["workout_id"] == 100 and out["created"]["sport"] == "run"


def test_create_structured_workout_computes_duration_and_tss() -> None:
    svc, fake = make()
    structure = {"metric": "ftp", "steps": [
        {"minutes": 10, "low": 50, "high": 65, "kind": "warmup"},
        {"repeat": 3, "steps": [
            {"name": "Sweet spot", "minutes": 12, "low": 88, "high": 93},
            {"minutes": 4, "low": 50, "high": 55, "kind": "rest"}]},
        {"minutes": 10, "low": 45, "high": 55, "kind": "cooldown"},
    ]}
    svc.create_workout("holden", date_="2026-10-16", sport="bike", title="SS 3x12",
                       structure=structure)
    sent = fake.calls[-1][2]
    assert sent["totalTimePlanned"] == round(68 / 60, 4)
    wire = json.loads(sent["structure"])
    assert wire["primaryIntensityMetric"] == "percentOfFtp"
    rep = wire["structure"][1]
    assert rep["type"] == "repetition" and rep["length"] == {"value": 3, "unit": "repetition"}
    assert rep["begin"] == 600 and rep["end"] == 600 + 3 * 960
    assert rep["steps"][0]["targets"][0] == {"minValue": 88.0, "maxValue": 93.0}
    assert wire["structure"][0]["steps"][0]["intensityClass"] == "warmUp"
    assert wire["polyline"][0] == [0.0, 0] and wire["polyline"][-1][0] == 1.0
    assert 0.6 < sent["ifPlanned"] < 0.9 and 40 < sent["tssPlanned"] < 80


def test_bad_inputs_are_rejected_before_any_call() -> None:
    svc, fake = make()
    _raises(TrainingPeaksError, svc.create_workout, "holden", date_="2026-10-14",
            sport="curling", title="x")
    _raises(TrainingPeaksError, svc.create_workout, "holden", date_="2026-10-14",
            sport="run", title="")
    _raises(TrainingPeaksError, svc.create_workout, "holden", date_="2026-10-14",
            sport="run", title="x", start_time="6am")
    for bad in ({"steps": []}, {"metric": "watts", "steps": [{"minutes": 5, "low": 50}]},
                {"steps": [{"low": 50}]}, {"steps": [{"minutes": 5, "low": 90, "high": 80}]},
                {"steps": [{"repeat": 1000, "steps": [{"minutes": 1, "low": 50}]}]},
                "nope"):
        _raises(TrainingPeaksError, build_structure, bad)
    assert fake.calls == []


def test_delete_planned_only() -> None:
    svc, fake = make()
    out = svc.delete_workout("holden", 8)
    assert out["deleted"]["workout_id"] == 8 and 8 not in fake.workouts
    e = _raises(TrainingPeaksError, svc.delete_workout, "holden", 7)
    assert "completed data" in str(e) and 7 in fake.workouts
    _raises(NotFound, svc.delete_workout, "holden", 999)


def test_upload_garmin_activity_creates_workout_and_posts_gzipped_fit() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("123_ACTIVITY.fit", b"FIT-BYTES")
    svc, fake = make(fit=buf.getvalue())
    out = svc.upload_garmin_activity("holden", 123)
    create = next(c for c in fake.calls if c[0] == "POST" and c[1].endswith("/workouts"))
    assert create[2]["workoutDay"] == "2026-10-13T00:00:00"
    assert create[2]["workoutTypeValueId"] == 2 and create[2]["title"] == "Morning Ride"
    upload = fake.calls[-1]
    assert upload[1] == f"/fitness/v6/athletes/{ATHLETE}/workouts/100/filedata"
    assert gzip.decompress(base64.b64decode(upload[2]["data"])) == b"FIT-BYTES"
    assert upload[2]["fileName"] == "123_ACTIVITY.fit"
    assert out["uploaded"]["workout_id"] == 100 and out["uploaded"]["sport"] == "bike"


# ---------------------------------------------------------------- helpers ---
def test_sport_mapping() -> None:
    assert sport_id("Swim") == 1 and sport_id("cycling") == 2 and sport_id("day off") == 7
    assert sport_for_garmin("lap_swimming") == 1
    assert sport_for_garmin("mountain_biking") == 8
    assert sport_for_garmin("virtual_ride") == 2
    assert sport_for_garmin("trail_running") == 3
    assert sport_for_garmin("multi_sport") == 4
    assert sport_for_garmin("strength_training") == 9
    assert sport_for_garmin(None) == 100


def test_fit_extraction_passes_bare_files_through() -> None:
    assert fit_from_garmin_download(b"\x0e\x10raw") == (b"\x0e\x10raw", "activity.fit")


def test_clean_cookie_accepts_common_paste_formats() -> None:
    assert clean_cookie(f"  {COOKIE}\n") == COOKIE
    assert clean_cookie(f"Production_tpAuth={COOKIE}") == COOKIE
    assert clean_cookie(f"foo=1; Production_tpAuth={COOKIE}; bar=2") == COOKIE
