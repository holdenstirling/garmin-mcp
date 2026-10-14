"""Oura Ring (API v2, OAuth2): readiness, sleep and HRV for the app's recovery views.

Oura's API agreement (section 4(d)) forbids sending Oura API data to an AI model except
through Oura's own MCP server. So data read here is **only** shown in the app and used by
deterministic rules (stats, plan adjustment); it is never put in Rabbit's model context.
If ``OURA_MCP_URL`` is configured, the coach model can reach Oura through Oura's MCP
server instead (see ``agent.py``), with the athlete's own token.

Tokens are stored encrypted per user (``oura`` doc). Connecting needs an Oura developer
app (client id + secret) whose redirect URI is ``<PUBLIC_BASE_URL>/app/auth/oura/callback``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx2

from .appstore import AppStore
from .logs import log_event
from .providers import GarminError

logger = logging.getLogger(__name__)

AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
API = "https://api.ouraring.com/v2/usercollection"
# No "workout": Oura workouts are never imported (Garmin is the only workout source, so
# nothing is double counted; see sources.py). "session" is unused too.
SCOPES = "personal daily heartrate"
CACHE_S = 900


class OuraError(GarminError):
    """Message safe to show the athlete."""


class OuraNotConnected(OuraError):
    pass


def merge_days(readiness: list[dict[str, Any]], daily_sleep: list[dict[str, Any]],
               sleeps: list[dict[str, Any]], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per day: readiness and sleep scores, HRV, resting HR, sleep hours, steps."""
    days: dict[str, dict[str, Any]] = {}

    def row(d: str) -> dict[str, Any]:
        return days.setdefault(d, {"date": d})
    for r in readiness:
        if r.get("day"):
            x = row(r["day"])
            x["readiness"] = r.get("score")
            x["temp_deviation"] = (r.get("temperature_deviation") if isinstance(r.get("temperature_deviation"), int | float) else None)
    for r in daily_sleep:
        if r.get("day"):
            row(r["day"])["sleep_score"] = r.get("score")
    for r in sleeps:  # the main sleep period of each day
        if r.get("day") and r.get("type") in (None, "long_sleep"):
            x = row(r["day"])
            if isinstance(r.get("average_hrv"), int | float):
                x["hrv"] = round(r["average_hrv"])
            if isinstance(r.get("lowest_heart_rate"), int | float):
                x["resting_hr"] = round(r["lowest_heart_rate"])
            if isinstance(r.get("total_sleep_duration"), int | float):
                x["sleep_hours"] = round(r["total_sleep_duration"] / 3600, 1)
    for r in activity:
        if r.get("day"):
            x = row(r["day"])
            x["activity_score"] = r.get("score")
            x["steps"] = r.get("steps")
    return [{k: v for k, v in days[d].items() if v is not None} for d in sorted(days)]


def baseline(days: list[dict[str, Any]], key: str, upto: int = 28) -> float | None:
    vals = [d[key] for d in days[-upto:] if isinstance(d.get(key), int | float)]
    return round(sum(vals) / len(vals), 1) if len(vals) >= 5 else None


class OuraClient:
    def __init__(self, store: AppStore, client_id: str, client_secret: str, redirect_uri: str, *,
                 http: httpx2.AsyncClient | None = None, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "oura")

    def connected(self, user_id: str) -> bool:
        return bool(self._doc(user_id).load().get("refresh_token"))

    def authorize_url(self, state: str) -> str:
        return f"{AUTH_URL}?" + urlencode({"response_type": "code", "client_id": self._id,
                                           "redirect_uri": self.redirect_uri, "scope": SCOPES,
                                           "state": state})

    def _client(self) -> httpx2.AsyncClient:
        return self._http or httpx2.AsyncClient(timeout=15)

    async def _token(self, data: dict[str, str]) -> dict[str, Any]:
        client = self._client()
        try:
            r = await client.post(TOKEN_URL, data=data | {"client_id": self._id, "client_secret": self._secret})
        finally:
            if self._http is None:
                await client.aclose()
        if r.status_code in (400, 401):
            raise OuraNotConnected("Oura access was revoked or expired. Connect it again in settings.")
        r.raise_for_status()
        return r.json()

    async def exchange(self, user_id: str, code: str) -> None:
        tok = await self._token({"grant_type": "authorization_code", "code": code,
                                 "redirect_uri": self.redirect_uri})
        self._save(user_id, tok)

    def _save(self, user_id: str, tok: dict[str, Any]) -> None:
        if not tok.get("refresh_token") or not tok.get("access_token"):
            raise OuraError("Oura didn't return tokens. Try connecting again.")
        self._doc(user_id).save({"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
                                 "expires": int(self._clock()) + int(tok.get("expires_in", 86400)) - 120,
                                 "connected_at": int(self._clock())})
        self._cache.pop(user_id, None)

    async def access_token(self, user_id: str) -> str:
        d = self._doc(user_id).load()
        if not d.get("refresh_token"):
            raise OuraNotConnected("Oura isn't connected.")
        if d.get("expires", 0) > self._clock():
            return str(d["access_token"])
        # Oura refresh tokens are single use: serialize refreshes per user and re-read
        # inside the lock so a concurrent request reuses the token another one just saved.
        async with self._locks.setdefault(user_id, asyncio.Lock()):
            d = self._doc(user_id).load()
            if not d.get("refresh_token"):
                raise OuraNotConnected("Oura isn't connected.")
            if d.get("expires", 0) > self._clock():
                return str(d["access_token"])
            used = d["refresh_token"]
            try:
                tok = await self._token({"grant_type": "refresh_token", "refresh_token": used})
            except OuraNotConnected:
                if self._doc(user_id).load().get("refresh_token") == used:
                    self._doc(user_id).delete()
                raise
            self._save(user_id, tok)  # Oura rotates the refresh token
            return str(tok["access_token"])

    def disconnect(self, user_id: str) -> None:
        self._doc(user_id).delete()
        self._cache.pop(user_id, None)

    async def _get(self, token: str, path: str, start: date, end: date) -> list[dict[str, Any]]:
        client = self._client()
        try:
            r = await client.get(f"{API}/{path}", params={"start_date": start.isoformat(),
                                                          "end_date": (end + timedelta(days=1)).isoformat()},
                                 headers={"Authorization": f"Bearer {token}"})
        finally:
            if self._http is None:
                await client.aclose()
        if r.status_code == 401:
            raise OuraNotConnected("Oura access expired. Connect it again in settings.")
        if r.status_code == 403:
            raise OuraError("Oura refused this data (an active Oura Membership is required for the API).")
        if r.status_code == 429:
            raise OuraError("Oura is rate limiting requests. Try again in a few minutes.")
        if r.status_code >= 500:
            raise OuraError("Oura is having trouble right now. Try again later.")
        r.raise_for_status()
        return list(r.json().get("data") or [])

    async def recovery(self, user_id: str, today: date, days: int = 28) -> dict[str, Any]:
        days = max(7, min(90, days))
        hit = self._cache.get(user_id)
        if hit and self._clock() - hit[0] < CACHE_S and hit[1]["window"] == days:
            return hit[1]
        token = await self.access_token(user_id)
        start = today - timedelta(days=days - 1)
        parts = [await self._get(token, p, start, today) for p in ("daily_readiness", "daily_sleep", "sleep", "daily_activity")]
        rows = merge_days(*parts)
        out = {"connected": True, "window": days, "days": rows,
               "baseline": {k: baseline(rows[:-1], k) for k in ("hrv", "resting_hr", "readiness", "sleep_hours")},
               "latest": rows[-1] if rows else None}
        self._cache[user_id] = (self._clock(), out)
        log_event(logger, logging.INFO, "oura_read", user_id=user_id, days=len(rows))
        return out


__all__ = ["OuraClient", "OuraError", "OuraNotConnected", "merge_days", "baseline"]
