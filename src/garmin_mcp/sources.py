"""Data-source preferences: which device Rabbit trusts for what.

Stored in the athlete's ``profile`` doc (next to ``brief_enabled`` etc.):

* ``data_sources`` = ``{"recovery": "garmin"|"oura", "sleep": "garmin"|"oura", "show_both": bool}``
* ``data_sources_asked`` = ``True`` once the athlete answered "How should Rabbit use your data?"

**Workouts always come from Garmin** (fixed ``"workouts": "garmin"``): Oura workouts are never
imported, so nothing is counted twice (streak, XP, stats, gear and plan matching all read
Garmin activities only).

**Recovery** (readiness, HRV, resting HR) picks which numbers the Today card, plan
adjustments and Progress use. Default: ``"oura"`` when Oura is connected, else ``"garmin"``.
**Sleep** defaults to the recovery source. ``show_both`` shows a Garmin vs Oura comparison
in Progress. An Oura choice without an Oura connection falls back to Garmin.

Oura numbers never go to the model (Oura API terms); the coach context only says which
source the athlete reads (``context_line``), so Rabbit doesn't quote a conflicting score.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import anyio

from .logs import log_event

if TYPE_CHECKING:
    from .agent import Agent
    from .appstore import AppStore
    from .oura import OuraClient

logger = logging.getLogger(__name__)

SOURCES = ("garmin", "oura")
KEYS = ("workouts", "recovery", "sleep", "show_both")
GARMIN_DAYS = 3  # readiness + sleep reads per day (cached by GarminService)
LABEL = {"garmin": "Garmin", "oura": "Oura"}


def resolve(profile: dict[str, Any] | None, oura_connected: bool) -> dict[str, Any]:
    """The athlete's stored choice with defaults filled in (what settings show)."""
    raw = (profile or {}).get("data_sources")
    raw = raw if isinstance(raw, dict) else {}
    rec = raw.get("recovery") if raw.get("recovery") in SOURCES else ("oura" if oura_connected else "garmin")
    sleep = raw.get("sleep") if raw.get("sleep") in SOURCES else rec
    return {"workouts": "garmin", "recovery": rec, "sleep": sleep,
            "show_both": raw.get("show_both") is True}


def effective(prefs: dict[str, Any], oura_connected: bool, key: str = "recovery") -> str:
    """The source actually used: Oura only when chosen *and* connected."""
    return "oura" if prefs.get(key) == "oura" and oura_connected else "garmin"


def validate(value: Any) -> dict[str, Any]:
    """A ``data_sources`` patch from PUT /settings. Raises ``ValueError`` with a safe message."""
    if not isinstance(value, dict) or not value:
        raise ValueError("data_sources must be an object")
    out: dict[str, Any] = {}
    for k, v in value.items():
        if k not in KEYS:
            raise ValueError(f"data_sources.{str(k)[:20]} isn't a setting")
        if k == "workouts":
            if v != "garmin":
                raise ValueError("Workouts always come from Garmin")
        elif k == "show_both":
            if not isinstance(v, bool):
                raise ValueError("data_sources.show_both must be true or false")
            out[k] = v
        elif v not in SOURCES:
            raise ValueError(f"data_sources.{k} must be garmin or oura")
        else:
            out[k] = v
    return out


def _oura_connected(store: AppStore, user_id: str) -> bool:
    try:
        return bool(store.user_doc(user_id, "oura").load().get("refresh_token"))
    except Exception:
        return False


def prefs_for(store: AppStore, user_id: str, oura_connected: bool | None = None) -> tuple[dict[str, Any], bool]:
    """(resolved prefs, oura connected) for a user."""
    connected = _oura_connected(store, user_id) if oura_connected is None else oura_connected
    return resolve(store.user_doc(user_id, "profile").load(), connected), connected


def context_line(prefs: dict[str, Any], oura_connected: bool) -> str:
    """One line for the coach context. Never carries Oura numbers."""
    if effective(prefs, oura_connected) == "oura":
        return ("Recovery source: Oura (the athlete reads recovery in Oura; avoid quoting Garmin "
                "readiness/sleep scores, which may differ). Workouts come from Garmin only.")
    return "Recovery source: Garmin. Workouts come from Garmin only."


# ------------------------------------------------------------ Garmin reads --
def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def garmin_day(readiness: Any, sleep: Any, day: str) -> dict[str, Any]:
    """One recovery row (Oura-shaped keys) from Garmin training readiness + sleep data."""
    row: dict[str, Any] = {"date": day}
    entries = readiness if isinstance(readiness, list) else [readiness] if isinstance(readiness, dict) else []
    r = next((e for e in entries if isinstance(e, dict) and _num(e.get("score")) is not None), None)
    if r:
        row["readiness"] = round(_num(r["score"]) or 0)
        if _num(r.get("sleepScore")) is not None:
            row["sleep_score"] = round(_num(r["sleepScore"]) or 0)
        if _num(r.get("hrvWeeklyAverage")) is not None:
            row["hrv_week"] = round(_num(r["hrvWeeklyAverage"]) or 0)
    if isinstance(sleep, dict):
        dto = sleep.get("dailySleepDTO") if isinstance(sleep.get("dailySleepDTO"), dict) else {}
        secs = _num(dto.get("sleepTimeSeconds"))
        if secs:
            row["sleep_hours"] = round(secs / 3600, 1)
        score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value") \
            if isinstance(dto.get("sleepScores"), dict) else None
        if _num(score) is not None:
            row["sleep_score"] = round(_num(score) or 0)
        if _num(sleep.get("avgOvernightHrv")) is not None:
            row["hrv"] = round(_num(sleep["avgOvernightHrv"]) or 0)
        if _num(sleep.get("restingHeartRate")) is not None:
            row["resting_hr"] = round(_num(sleep["restingHeartRate"]) or 0)
    return row


RECOVERY_TTL = 600     # a day's readiness + sleep, per user, reused for 10 minutes
RECOVERY_NONE_TTL = 60  # "nothing / Garmin down" is retried sooner
_rec_guard = threading.Lock()
_rec_cache: "weakref.WeakKeyDictionary[Any, dict[str, tuple[float, str, int, dict[str, Any] | None]]]" = \
    weakref.WeakKeyDictionary()
_rec_locks: dict[str, threading.Lock] = {}


def _rec_slot(service: Any) -> dict[str, tuple[float, str, int, dict[str, Any] | None]] | None:
    try:
        with _rec_guard:
            return _rec_cache.setdefault(service, {})
    except TypeError:  # not weak-referenceable (a bare stub): no cache
        return None


def forget_recovery(service: Any, user_id: str) -> None:
    """Drop a user's cached Garmin recovery (new data synced)."""
    slot = _rec_slot(service)
    if slot is not None:
        slot.pop(user_id, None)


def _slice(rec: dict[str, Any] | None, days: int) -> dict[str, Any] | None:
    if rec is None or rec["window"] <= days:
        return rec
    rows = rec["days"][-days:] if days > 0 else []
    if not rows:
        return None
    return {**rec, "window": days, "days": rows}


def garmin_recovery(service: Any, user_id: str, today: date, days: int = GARMIN_DAYS) -> dict[str, Any] | None:
    """Last ``days`` of Garmin readiness + sleep, shaped like ``OuraClient.recovery``.

    Cached per user + day for 10 minutes and single-flight per user, so the Progress tab's
    parallel requests (recovery, today, insights, adjust) share one read: Garmin rate-limits
    at ~30 calls/min and each day here is two calls. A longer cached window serves a
    shorter request. ``None`` when Garmin isn't connected or has nothing. Baselines:
    Garmin's own 7-day HRV average when present; others need more days than we read."""
    slot = _rec_slot(service)
    key = today.isoformat()

    def cached() -> tuple[bool, dict[str, Any] | None]:
        hit = slot.get(user_id) if slot is not None else None
        if hit and hit[1] == key and hit[2] >= days and \
                time.monotonic() - hit[0] < (RECOVERY_TTL if hit[3] is not None else RECOVERY_NONE_TTL):
            return True, _slice(hit[3], days)
        return False, None

    ok, rec = cached()
    if ok:
        return rec
    with _rec_guard:
        lock = _rec_locks.setdefault(user_id, threading.Lock())
    with lock:
        ok, rec = cached()
        if ok:
            return rec
        rec = _garmin_recovery_read(service, user_id, today, days)
        if slot is not None:
            slot[user_id] = (time.monotonic(), key, days, rec)
        return rec


def _garmin_recovery_read(service: Any, user_id: str, today: date, days: int) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        try:
            ready = service.execute(user_id, "get_training_readiness", {"cdate": d}).get("result")
            sleep = service.execute(user_id, "get_sleep_data", {"cdate": d}).get("result")
        except Exception as e:  # not connected, rate limited or Garmin down: use what we have
            log_event(logger, logging.INFO, "garmin_recovery_skip", user_id=user_id, error=type(e).__name__)
            if not rows:
                return None
            break
        row = garmin_day(ready, sleep, d)
        if len(row) > 1:
            rows.append(row)
    if not rows:
        return None
    latest = rows[-1]
    return {"connected": True, "source": "garmin", "window": days, "days": rows, "latest": latest,
            "baseline": {"hrv": latest.get("hrv_week"), "resting_hr": None, "readiness": None,
                         "sleep_hours": None}}


async def recovery_for(agent: Agent, oura: OuraClient | None, user_id: str,
                       today: date) -> tuple[dict[str, Any] | None, str]:
    """(recovery data, source) per the athlete's choice. Oura is used only when chosen and
    connected; an Oura outage gives ``None`` (no silent switch to a conflicting Garmin score)."""
    connected = bool(oura is not None and oura.connected(user_id))
    prefs, _ = prefs_for(agent._store, user_id, connected)
    src = effective(prefs, connected)
    if src == "oura" and oura is not None:
        try:
            return {**await oura.recovery(user_id, today, 28), "source": "oura"}, "oura"
        except Exception:
            return None, "oura"
    rec = await anyio.to_thread.run_sync(garmin_recovery, agent._service, user_id, today)
    return rec, "garmin"


__all__ = [
    "LABEL",
    "SOURCES",
    "context_line",
    "effective",
    "garmin_day",
    "forget_recovery",
    "garmin_recovery",
    "prefs_for",
    "recovery_for",
    "resolve",
    "validate",
]
