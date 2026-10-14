"""TrainingPeaks integration: read the calendar, plan workouts, push Garmin activities.

TrainingPeaks' official API is partner-only, so this talks to the same private
API (``tpapi.trainingpeaks.com``) the TrainingPeaks web app uses. Like the
Garmin side, that is unofficial and can break without notice.

Auth: the user's ``Production_tpAuth`` session cookie (copied from a signed-in
browser) is stored Fernet-encrypted per user, exactly like Garmin tokens, by
``garmin-mcp-trainingpeaks-login``. It is exchanged for a short-lived bearer
token (``GET /users/v3/token``) that lives only in memory. The cookie lasts a
few weeks; when TrainingPeaks rejects it, callers get ``TPReauthRequired``
telling them to re-run the login CLI. Nothing re-authenticates automatically.

Safety posture, matching the rest of the server:
- Every write needs ``TRAININGPEAKS_ALLOW_WRITES=true``.
- Only a fixed set of endpoints is ever called; no tool accepts a raw path.
- Deleting is limited to *planned* workouts. A workout with completed data
  (time, distance or a file) is refused, so a mistake can't erase history.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import logging
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx2

from .logs import log_event
from .providers import GarminError, NotFound, RateLimited
from .resilience import RateLimiter
from .tokens import TokenStore

logger = logging.getLogger(__name__)

TP_API = "https://tpapi.trainingpeaks.com"
COOKIE_NAME = "Production_tpAuth"
TOKEN_REFRESH_MARGIN = 60  # seconds before expiry to fetch a new bearer token
MAX_RANGE_DAYS = 90
UPLOAD_CLIENT = "garmin-mcp"
MAX_FIT_BYTES = 25 * 1024 * 1024


# ---------------------------------------------------------------- errors ---
class TrainingPeaksError(GarminError):
    """Caller-safe TrainingPeaks failure (shown to the MCP client as-is)."""

    user_message = "TrainingPeaks request failed."


class TPReauthRequired(TrainingPeaksError):
    def __init__(self, user_id: str, reason: str = "cookie missing or rejected") -> None:
        super().__init__(
            f"TrainingPeaks authorization for user '{user_id}' is not usable ({reason}). "
            f"Re-run on the server: sudo garmin-mcp-trainingpeaks-login --user {user_id}"
        )


class TPWritesDisabled(TrainingPeaksError):
    user_message = (
        "TrainingPeaks writes are disabled on this server (set TRAININGPEAKS_ALLOW_WRITES=true)."
    )


# ----------------------------------------------------------------- sports ---
# workoutTypeValueId (== workoutTypeFamilyId) from GET /fitness/v6/workouttypes
SPORT_IDS: dict[str, int] = {
    "swim": 1, "bike": 2, "run": 3, "brick": 4, "crosstrain": 5, "race": 6,
    "dayoff": 7, "mtb": 8, "strength": 9, "custom": 10, "xcski": 11,
    "rowing": 12, "walk": 13, "other": 100,
}
SPORT_ALIASES: dict[str, str] = {
    "swimming": "swim", "pool": "swim", "open_water": "swim",
    "cycling": "bike", "ride": "bike", "road": "bike", "indoor_cycling": "bike",
    "virtual_ride": "bike", "trainer": "bike",
    "running": "run", "treadmill": "run", "trail_run": "run", "track": "run",
    "multisport": "brick", "multi_sport": "brick", "triathlon": "brick",
    "mountain_bike": "mtb", "mountain_biking": "mtb", "gravel": "bike",
    "gym": "strength", "weights": "strength", "fitness_equipment": "strength",
    "strength_training": "strength",
    "ski": "xcski", "cross_country_skiing": "xcski",
    "row": "rowing", "indoor_rowing": "rowing",
    "walking": "walk", "hike": "walk", "hiking": "walk",
    "rest": "dayoff", "day_off": "dayoff", "off": "dayoff",
    "cross_training": "crosstrain", "yoga": "crosstrain",
}
SPORT_NAMES = {v: k for k, v in SPORT_IDS.items()}


def sport_id(sport: str) -> int:
    key = (sport or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = SPORT_ALIASES.get(key, key)
    if key not in SPORT_IDS:
        raise TrainingPeaksError(
            f"Unknown sport {sport!r}; use one of {sorted(SPORT_IDS)}")
    return SPORT_IDS[key]


def sport_for_garmin(type_key: str | None) -> int:
    """Map a Garmin activityType.typeKey onto a TrainingPeaks sport (default other)."""
    key = (type_key or "").lower()
    if "swim" in key:
        return SPORT_IDS["swim"]
    if "mountain" in key:
        return SPORT_IDS["mtb"]
    if "cycl" in key or "bik" in key or "ride" in key:
        return SPORT_IDS["bike"]
    if "run" in key:
        return SPORT_IDS["run"]
    if "multi" in key or "triathlon" in key:
        return SPORT_IDS["brick"]
    if "strength" in key or "fitness_equipment" in key:
        return SPORT_IDS["strength"]
    if "row" in key:
        return SPORT_IDS["rowing"]
    if "ski" in key:
        return SPORT_IDS["xcski"]
    if "walk" in key or "hik" in key:
        return SPORT_IDS["walk"]
    return SPORT_IDS["other"]


# -------------------------------------------------------------- structure ---
METRICS = {
    "ftp": "percentOfFtp", "power": "percentOfFtp", "percentOfFtp": "percentOfFtp",
    "hr": "percentOfThresholdHr", "heart_rate": "percentOfThresholdHr",
    "percentOfThresholdHr": "percentOfThresholdHr",
    "pace": "percentOfThresholdPace", "percentOfThresholdPace": "percentOfThresholdPace",
}
KINDS = {
    "warmup": "warmUp", "warm_up": "warmUp", "warmUp": "warmUp",
    "active": "active", "work": "active", "interval": "active", "main": "active",
    "rest": "rest", "recovery": "rest", "recover": "rest",
    "cooldown": "coolDown", "cool_down": "coolDown", "coolDown": "coolDown",
    "other": "other",
}
MAX_STEPS = 200
MAX_STEP_SECONDS = 6 * 3600


@dataclass(frozen=True)
class BuiltStructure:
    wire: dict[str, Any]          # TrainingPeaks' structure JSON (sent as a string)
    seconds: int                  # total planned duration
    intensity_factor: float | None
    tss: float | None


def _num(v: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise TrainingPeaksError(f"structure: {name} must be a number")
    if not lo <= v <= hi:
        raise TrainingPeaksError(f"structure: {name} must be between {lo} and {hi}")
    return float(v)


def _step(raw: Any) -> tuple[dict[str, Any], int, float, float]:
    if not isinstance(raw, dict):
        raise TrainingPeaksError("structure: each step must be an object")
    if "seconds" in raw:
        secs = _num(raw["seconds"], "seconds", 1, MAX_STEP_SECONDS)
    elif "minutes" in raw:
        secs = _num(raw["minutes"], "minutes", 1 / 60, MAX_STEP_SECONDS / 60) * 60
    else:
        raise TrainingPeaksError("structure: each step needs minutes or seconds")
    secs = int(round(secs))
    low = _num(raw.get("low"), "low", 0, 300)
    high = _num(raw.get("high", raw.get("low")), "high", 0, 300)
    if low > high:
        raise TrainingPeaksError("structure: low must be <= high")
    kind = KINDS.get(str(raw.get("kind", "active")))
    if kind is None:
        raise TrainingPeaksError(f"structure: kind must be one of {sorted(set(KINDS))}")
    name = str(raw.get("name") or {"warmUp": "Warm up", "coolDown": "Cool down",
                                   "rest": "Recover"}.get(kind, "Work"))[:100]
    targets: list[dict[str, Any]] = [{"minValue": low, "maxValue": high}]
    if raw.get("cadence_low") is not None or raw.get("cadence_high") is not None:
        c_lo = _num(raw.get("cadence_low", raw.get("cadence_high")), "cadence_low", 0, 300)
        c_hi = _num(raw.get("cadence_high", raw.get("cadence_low")), "cadence_high", 0, 300)
        targets.append({"minValue": c_lo, "maxValue": c_hi, "unit": "roundOrStridePerMinute"})
    wire = {"name": name, "type": "step", "length": {"value": secs, "unit": "second"},
            "targets": targets, "intensityClass": kind, "openDuration": False}
    return wire, secs, low, high


def build_structure(raw: Any) -> BuiltStructure:
    """Turn the tools' simple step list into TrainingPeaks' structured-workout JSON.

    Input: {"metric": "ftp"|"hr"|"pace", "steps": [step | {"repeat": n, "steps": [step...]}]}
    step:  {"name"?, "minutes"|"seconds", "low", "high"?, "kind"?, "cadence_low"?, "cadence_high"?}
    low/high are % of threshold (FTP, threshold HR or threshold pace).
    """
    if not isinstance(raw, dict):
        raise TrainingPeaksError("structure must be an object with metric and steps")
    metric = METRICS.get(str(raw.get("metric", "ftp")))
    if metric is None:
        raise TrainingPeaksError("structure: metric must be ftp, hr or pace")
    blocks_in = raw.get("steps")
    if not isinstance(blocks_in, list) or not blocks_in:
        raise TrainingPeaksError("structure: steps must be a non-empty list")

    blocks: list[dict[str, Any]] = []
    bars: list[tuple[int, float]] = []  # (seconds, % high) per executed step, for the polyline
    weighted = 0.0  # time-weighted 4th power of midpoint intensity (NP-style)
    t = 0
    count = 0
    for b in blocks_in:
        if isinstance(b, dict) and "repeat" in b:
            reps = int(_num(b["repeat"], "repeat", 1, 100))
            inner = b.get("steps")
            if not isinstance(inner, list) or not inner:
                raise TrainingPeaksError("structure: a repeat needs a non-empty steps list")
            parsed = [_step(s) for s in inner]
            count += reps * len(parsed)
            dur = reps * sum(p[1] for p in parsed)
            blocks.append({"type": "repetition", "length": {"value": reps, "unit": "repetition"},
                           "steps": [p[0] for p in parsed], "begin": t, "end": t + dur})
            for _ in range(reps):
                for _w, secs, lo, hi in parsed:
                    bars.append((secs, hi))
                    weighted += secs * ((lo + hi) / 2) ** 4
            t += dur
        else:
            w, secs, lo, hi = _step(b)
            count += 1
            blocks.append({"type": "step", "length": {"value": 1, "unit": "repetition"},
                           "steps": [w], "begin": t, "end": t + secs})
            bars.append((secs, hi))
            weighted += secs * ((lo + hi) / 2) ** 4
            t += secs
        if count > MAX_STEPS:
            raise TrainingPeaksError(f"structure: at most {MAX_STEPS} steps in total")

    polyline: list[list[float]] = []
    elapsed = 0
    for secs, hi in bars:
        x0, elapsed = elapsed / t, elapsed + secs
        x1 = elapsed / t
        y = round(hi / 100, 4)
        polyline += [[round(x0, 4), 0], [round(x0, 4), y], [round(x1, 4), y], [round(x1, 4), 0]]

    wire = {"structure": blocks, "polyline": polyline, "primaryLengthMetric": "duration",
            "primaryIntensityMetric": metric, "primaryIntensityTargetOrRange": "range"}
    if_ = tss = None
    if metric != "percentOfThresholdPace":  # pace-based TSS uses a different model
        if_ = round((weighted / t) ** 0.25 / 100, 3)
        tss = round(t * if_ ** 2 * 100 / 3600, 1)
    return BuiltStructure(wire, t, if_, tss)


# ----------------------------------------------------------------- client ---
class TrainingPeaksClient:
    """Thread-safe, per-user client. Bearer tokens and athlete ids live in memory only."""

    def __init__(self, cookie_store: TokenStore, *, base_url: str = TP_API,
                 transport: httpx2.BaseTransport | None = None, timeout: float = 30.0,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = cookie_store
        self._clock = clock
        self._http = httpx2.Client(base_url=base_url, timeout=timeout, transport=transport,
                                   headers={"Accept": "application/json"})
        self._tokens: dict[str, tuple[str, float]] = {}
        self._athletes: dict[str, int] = {}
        self._lock = threading.Lock()

    # -- auth --
    def invalidate(self, user_id: str) -> None:
        with self._lock:
            self._tokens.pop(user_id, None)
            self._athletes.pop(user_id, None)

    def _exchange(self, user_id: str, cookie: str) -> tuple[str, float]:
        try:
            r = self._http.get("/users/v3/token", headers={"Cookie": f"{COOKIE_NAME}={cookie}"})
        except httpx2.HTTPError as e:
            raise TrainingPeaksError(f"Could not reach TrainingPeaks ({type(e).__name__}).") from None
        if r.status_code in (401, 403):
            raise TPReauthRequired(user_id, "session cookie expired or invalid")
        if r.status_code != 200:
            raise TrainingPeaksError(f"TrainingPeaks token exchange failed (HTTP {r.status_code}).")
        try:
            body = r.json()
            tok = body["token"]
            access = tok["access_token"]
            expires_in = float(tok.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError):
            raise TPReauthRequired(user_id, "unexpected token response") from None
        if not access or body.get("success") is False:
            raise TPReauthRequired(user_id, "token exchange refused")
        return access, self._clock() + expires_in

    def _bearer(self, user_id: str) -> str:
        with self._lock:
            cached = self._tokens.get(user_id)
            if cached and self._clock() < cached[1] - TOKEN_REFRESH_MARGIN:
                return cached[0]
            cookie = self._store.load(user_id)
            if not cookie:
                raise TPReauthRequired(user_id, "not connected")
            access, exp = self._exchange(user_id, cookie)
            self._tokens[user_id] = (access, exp)
            return access

    def request(self, user_id: str, method: str, path: str, *,
                body: Any = None) -> Any:
        for attempt in (1, 2):
            token = self._bearer(user_id)
            try:
                r = self._http.request(method, path, json=body,
                                       headers={"Authorization": f"Bearer {token}"})
            except httpx2.HTTPError as e:
                raise TrainingPeaksError(
                    f"Could not reach TrainingPeaks ({type(e).__name__}).") from None
            if r.status_code == 401 and attempt == 1:
                with self._lock:  # bearer expired early: get a fresh one once
                    self._tokens.pop(user_id, None)
                continue
            break
        log_event(logger, logging.INFO, "tp_request", user_id=user_id, method=method,
                  status=r.status_code)
        if r.status_code == 401:
            self.invalidate(user_id)
            raise TPReauthRequired(user_id, "TrainingPeaks rejected the session")
        if r.status_code == 403:
            raise TrainingPeaksError(
                "TrainingPeaks refused this request (HTTP 403). Some features need Premium.")
        if r.status_code == 404:
            raise NotFound("TrainingPeaks says that workout or resource does not exist.")
        if r.status_code == 429:
            raise RateLimited("TrainingPeaks is rate limiting; wait a minute and retry.")
        if r.status_code >= 400:
            detail = ""
            try:
                j = r.json()
                if isinstance(j, dict):
                    detail = str(j.get("message") or j.get("Message") or "")[:200]
            except ValueError:
                pass
            raise TrainingPeaksError(
                f"TrainingPeaks returned HTTP {r.status_code}" + (f": {detail}" if detail else "."))
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def user(self, user_id: str) -> dict[str, Any]:
        data = self.request(user_id, "GET", "/users/v3/user")
        if isinstance(data, dict) and isinstance(data.get("user"), dict):
            data = data["user"]
        if not isinstance(data, dict):
            raise TrainingPeaksError("Unexpected TrainingPeaks user response.")
        return data

    def athlete_id(self, user_id: str) -> int:
        with self._lock:
            if user_id in self._athletes:
                return self._athletes[user_id]
        u = self.user(user_id)
        person = u.get("personId") or u.get("userId")
        athletes = [a for a in (u.get("athletes") or []) if isinstance(a, dict)]
        aid = None
        email = str(u.get("email") or u.get("username") or "").lower()
        for a in athletes:  # coach accounts list many athletes; pick the user's own
            if a.get("athleteId") == person or (
                    email and str(a.get("email") or "").lower() == email):
                aid = a.get("athleteId")
                break
        if aid is None:
            aid = person if person else (athletes[0].get("athleteId") if athletes else None)
        if not isinstance(aid, int):
            raise TrainingPeaksError("Could not determine your TrainingPeaks athlete id.")
        with self._lock:
            self._athletes[user_id] = aid
        return aid


# ------------------------------------------------------------- formatting ---
def _hours_to_hms(hours: Any) -> str | None:
    if not isinstance(hours, int | float) or hours <= 0:
        return None
    s = int(round(hours * 3600))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def _km(meters: Any) -> float | None:
    return round(meters / 1000, 2) if isinstance(meters, int | float) and meters > 0 else None


def is_completed(w: dict[str, Any]) -> bool:
    return bool(w.get("completed")) or any(
        isinstance(w.get(k), int | float) and w.get(k) > 0
        for k in ("totalTime", "distance", "tssActual"))


def compact_workout(w: dict[str, Any]) -> dict[str, Any]:
    out = {
        "workout_id": w.get("workoutId"),
        "date": str(w.get("workoutDay") or "")[:10] or None,
        "start_planned": w.get("startTimePlanned"),
        "sport": SPORT_NAMES.get(w.get("workoutTypeValueId"), w.get("workoutTypeValueId")),
        "title": w.get("title"),
        "completed": is_completed(w),
        "planned_duration": _hours_to_hms(w.get("totalTimePlanned")),
        "planned_distance_km": _km(w.get("distancePlanned")),
        "planned_tss": w.get("tssPlanned"),
        "actual_duration": _hours_to_hms(w.get("totalTime")),
        "actual_distance_km": _km(w.get("distance")),
        "actual_tss": w.get("tssActual"),
        "structured": bool(w.get("structure")),
        "description": (str(w.get("description"))[:300] if w.get("description") else None),
    }
    return {k: v for k, v in out.items() if v is not None and v is not False or k == "completed"}


def _parse_day(value: str, name: str = "date") -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise TrainingPeaksError(f"{name} must be YYYY-MM-DD") from None


def fit_from_garmin_download(blob: bytes) -> tuple[bytes, str]:
    """Garmin's ORIGINAL download is a zip holding the .fit; return (bytes, filename)."""
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            fits = [n for n in names if n.lower().endswith(".fit")] or names
            if not fits:
                raise TrainingPeaksError("Garmin's download was an empty archive.")
            info = z.getinfo(fits[0])
            if info.file_size > MAX_FIT_BYTES:
                raise TrainingPeaksError("Activity file is too large to upload.")
            return z.read(info), fits[0].rsplit("/", 1)[-1]
    if len(blob) > MAX_FIT_BYTES:
        raise TrainingPeaksError("Activity file is too large to upload.")
    return blob, "activity.fit"


# ---------------------------------------------------------------- service ---
GarminActivity = Callable[[str, int], dict[str, Any]]
GarminFile = Callable[[str, int], bytes]


class TrainingPeaksService:
    """Transport-independent TrainingPeaks tools (what the MCP server calls)."""

    def __init__(self, client: TrainingPeaksClient, *, allow_writes: bool,
                 limiter: RateLimiter, garmin_activity: GarminActivity | None = None,
                 garmin_file: GarminFile | None = None,
                 today: Callable[[], date] = date.today) -> None:
        self.client = client
        self.allow_writes = allow_writes
        self.limiter = limiter
        self.garmin_activity = garmin_activity
        self.garmin_file = garmin_file
        self.today = today

    def _guard(self, user_id: str, *, write: bool) -> None:
        if write and not self.allow_writes:
            raise TPWritesDisabled()
        if not self.limiter.allow(user_id):
            raise RateLimited("Per-user rate limit reached for this server; wait a minute.")

    def _call(self, user_id: str, method: str, path: str, body: Any = None) -> Any:
        return self.client.request(user_id, method, path, body=body)

    # -- reads --
    def workouts(self, user_id: str, start: str | None = None,
                 end: str | None = None) -> dict[str, Any]:
        self._guard(user_id, write=False)
        today = self.today()
        s = _parse_day(start, "start") if start else today - timedelta(days=7)
        e = _parse_day(end, "end") if end else today + timedelta(days=7)
        if e < s:
            raise TrainingPeaksError("end must be on or after start")
        if (e - s).days + 1 > MAX_RANGE_DAYS:
            raise TrainingPeaksError(f"Ask for at most {MAX_RANGE_DAYS} days at a time.")
        aid = self.client.athlete_id(user_id)
        raw = self._call(user_id, "GET",
                         f"/fitness/v6/athletes/{aid}/workouts/{s.isoformat()}/{e.isoformat()}")
        items = [compact_workout(w) for w in (raw or []) if isinstance(w, dict)]
        items.sort(key=lambda w: (w.get("date") or "", w.get("start_planned") or ""))
        return {"from": s.isoformat(), "to": e.isoformat(), "count": len(items),
                "writes_enabled": self.allow_writes, "workouts": items}

    # -- writes --
    def create_workout(self, user_id: str, *, date_: str, sport: str, title: str,
                       description: str | None = None, start_time: str | None = None,
                       duration_minutes: float | None = None,
                       distance_km: float | None = None, tss: float | None = None,
                       structure: Any = None) -> dict[str, Any]:
        self._guard(user_id, write=True)
        day = _parse_day(date_)
        title = (title or "").strip()
        if not title or len(title) > 200:
            raise TrainingPeaksError("title is required (max 200 characters)")
        type_id = sport_id(sport)
        built = build_structure(structure) if structure is not None else None

        payload: dict[str, Any] = {
            "workoutDay": f"{day.isoformat()}T00:00:00",
            "workoutTypeFamilyId": type_id,
            "workoutTypeValueId": type_id,
            "title": title,
            "isHidden": False,
        }
        if start_time:
            try:
                hh, mm = (int(x) for x in str(start_time).split(":")[:2])
                payload["startTimePlanned"] = datetime(day.year, day.month, day.day,
                                                       hh, mm).isoformat(timespec="seconds")
            except (ValueError, TypeError):
                raise TrainingPeaksError("start_time must be HH:MM (24h)") from None
        if description:
            payload["description"] = str(description)[:5000]
        minutes = duration_minutes
        if minutes is None and built is not None:
            minutes = built.seconds / 60
        if minutes is not None:
            payload["totalTimePlanned"] = round(_num(minutes, "duration_minutes", 1, 24 * 60) / 60, 4)
        if distance_km is not None:
            payload["distancePlanned"] = round(_num(distance_km, "distance_km", 0.01, 1000) * 1000, 1)
        if tss is not None:
            payload["tssPlanned"] = _num(tss, "tss", 0, 2000)
        elif built is not None and built.tss is not None:
            payload["tssPlanned"] = built.tss
            payload["ifPlanned"] = built.intensity_factor
        if built is not None:
            payload["structure"] = json.dumps(built.wire, separators=(",", ":"))

        aid = self.client.athlete_id(user_id)
        payload["athleteId"] = aid
        created = self._call(user_id, "POST", f"/fitness/v6/athletes/{aid}/workouts", payload)
        if not isinstance(created, dict) or not created.get("workoutId"):
            raise TrainingPeaksError("TrainingPeaks did not return the new workout.")
        log_event(logger, logging.INFO, "tp_workout_created", user_id=user_id,
                  workout_id=created.get("workoutId"), structured=built is not None)
        return {"created": compact_workout(created)}

    def delete_workout(self, user_id: str, workout_id: int) -> dict[str, Any]:
        self._guard(user_id, write=True)
        wid = int(workout_id)
        aid = self.client.athlete_id(user_id)
        path = f"/fitness/v6/athletes/{aid}/workouts/{wid}"
        existing = self._call(user_id, "GET", path)
        if not isinstance(existing, dict):
            raise NotFound("TrainingPeaks says that workout does not exist.")
        if is_completed(existing):
            raise TrainingPeaksError(
                "Refusing to delete a workout that has completed data; delete it in "
                "TrainingPeaks itself if you really mean to.")
        self._call(user_id, "DELETE", path)
        log_event(logger, logging.INFO, "tp_workout_deleted", user_id=user_id, workout_id=wid)
        return {"deleted": compact_workout(existing)}

    def upload_garmin_activity(self, user_id: str, activity_id: int,
                               title: str | None = None) -> dict[str, Any]:
        """Copy one completed Garmin activity (original FIT) into TrainingPeaks."""
        self._guard(user_id, write=True)
        if self.garmin_activity is None or self.garmin_file is None:
            raise TrainingPeaksError("Garmin activity upload is not available on this server.")
        act_id = int(activity_id)
        summary = self.garmin_activity(user_id, act_id) or {}
        start = str(summary.get("startTimeLocal") or summary.get("summaryDTO", {}).get(
            "startTimeLocal") or "")
        day = _parse_day(start, "Garmin activity start") if start else self.today()
        atype = summary.get("activityType") or summary.get("activityTypeDTO") or {}
        type_id = sport_for_garmin(atype.get("typeKey") if isinstance(atype, dict) else None)
        fit, fname = fit_from_garmin_download(self.garmin_file(user_id, act_id))

        aid = self.client.athlete_id(user_id)
        name = (title or summary.get("activityName") or "Garmin activity").strip()[:200]
        created = self._call(user_id, "POST", f"/fitness/v6/athletes/{aid}/workouts", {
            "athleteId": aid, "workoutDay": f"{day.isoformat()}T00:00:00",
            "workoutTypeFamilyId": type_id, "workoutTypeValueId": type_id,
            "title": name, "isHidden": False,
        })
        if not isinstance(created, dict) or not created.get("workoutId"):
            raise TrainingPeaksError("TrainingPeaks did not return the new workout.")
        wid = created["workoutId"]
        data = fit if fit[:2] == b"\x1f\x8b" else gzip.compress(fit)
        self._call(user_id, "POST", f"/fitness/v6/athletes/{aid}/workouts/{wid}/filedata", {
            "workoutDay": f"{day.isoformat()}T00:00:00",
            "data": base64.b64encode(data).decode("ascii"),
            "fileName": fname,
            "uploadClient": UPLOAD_CLIENT,
        })
        log_event(logger, logging.INFO, "tp_activity_uploaded", user_id=user_id,
                  garmin_activity_id=act_id, workout_id=wid, bytes=len(fit))
        return {"uploaded": {"garmin_activity_id": act_id, "workout_id": wid,
                             "date": day.isoformat(), "sport": SPORT_NAMES.get(type_id),
                             "title": name, "file": fname},
                "note": "TrainingPeaks processes the file in the background; metrics "
                        "appear on the workout within a minute or so."}
