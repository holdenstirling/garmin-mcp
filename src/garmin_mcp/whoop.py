"""WHOOP (developer API v2, OAuth2): workouts for the Day view and the friends feed.

Like Oura (``oura.py``), WHOOP data is **display-only**: imported workouts are stored with the
other sources' (``workouts.py``, ``extworkouts`` doc), shown on their day and, when the
athlete shares workouts, posted as the compact feed card (sport, distance, time). They never
enter ``Stats.activities``, plan matching or anything Rabbit's AI sees, and strain, heart rate
and calories are never shared.

Tokens are stored encrypted per user (``whoop`` doc). Connecting needs a WHOOP developer app
(client id + secret, developer.whoop.com) whose redirect URI is
``<PUBLIC_BASE_URL>/app/auth/whoop/callback``. Until WHOOP approves the app, only 10 WHOOP
members can connect it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, time as dtime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx2

from .appstore import AppStore
from .logs import log_event
from .providers import GarminError

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API = "https://api.prod.whoop.com/developer"
WORKOUTS = f"{API}/v2/activity/workout"
REVOKE = f"{API}/v2/user/access"
# "offline" is what makes WHOOP return a refresh token.
SCOPES = "read:workout offline"
PAGE = 25          # WHOOP's maximum page size
MAX_PAGES = 8      # 200 workouts per import is plenty for a 14-day window


class WhoopError(GarminError):
    """Message safe to show the athlete."""


class WhoopNotConnected(WhoopError):
    pass


class WhoopClient:
    def __init__(self, store: AppStore, client_id: str, client_secret: str, redirect_uri: str, *,
                 http: httpx2.AsyncClient | None = None, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http
        self._clock = clock
        self._read: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "whoop")

    def connected(self, user_id: str) -> bool:
        return bool(self._doc(user_id).load().get("refresh_token"))

    def authorize_url(self, state: str) -> str:
        return f"{AUTH_URL}?" + urlencode({"response_type": "code", "client_id": self._id,
                                           "redirect_uri": self.redirect_uri, "scope": SCOPES,
                                           "state": state})

    def last_read(self, user_id: str) -> float | None:
        """When workouts were last read for this user (in memory, None after a restart)."""
        return self._read.get(user_id)

    def forget(self, user_id: str) -> None:
        self._read.pop(user_id, None)

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
            raise WhoopNotConnected("WHOOP access was revoked or expired. Connect it again in Connected apps.")
        r.raise_for_status()
        return r.json()

    async def exchange(self, user_id: str, code: str) -> None:
        tok = await self._token({"grant_type": "authorization_code", "code": code,
                                 "redirect_uri": self.redirect_uri})
        self._save(user_id, tok)

    def _save(self, user_id: str, tok: dict[str, Any]) -> None:
        if not tok.get("refresh_token") or not tok.get("access_token"):
            raise WhoopError("WHOOP didn't return tokens. Try connecting again.")
        prev = self._doc(user_id).load()
        self._doc(user_id).save({"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
                                 "expires": int(self._clock()) + int(tok.get("expires_in", 3600)) - 120,
                                 "connected_at": prev.get("connected_at") or int(self._clock())})

    async def access_token(self, user_id: str) -> str:
        d = self._doc(user_id).load()
        if not d.get("refresh_token"):
            raise WhoopNotConnected("WHOOP isn't connected.")
        if d.get("expires", 0) > self._clock():
            return str(d["access_token"])
        # WHOOP rotates refresh tokens (each one works once): serialize refreshes per user and
        # re-read inside the lock so a concurrent request reuses the token another just saved.
        async with self._locks.setdefault(user_id, asyncio.Lock()):
            d = self._doc(user_id).load()
            if not d.get("refresh_token"):
                raise WhoopNotConnected("WHOOP isn't connected.")
            if d.get("expires", 0) > self._clock():
                return str(d["access_token"])
            used = d["refresh_token"]
            try:
                tok = await self._token({"grant_type": "refresh_token", "refresh_token": used, "scope": "offline"})
            except WhoopNotConnected:
                if self._doc(user_id).load().get("refresh_token") == used:
                    self._doc(user_id).delete()
                raise
            self._save(user_id, tok)
            return str(tok["access_token"])

    async def disconnect(self, user_id: str) -> None:
        """Revoke Rabbit's access at WHOOP (best effort), then delete the tokens and the
        workouts imported from WHOOP."""
        d = self._doc(user_id).load()
        if d.get("access_token"):
            client = self._client()
            try:
                token = d["access_token"] if d.get("expires", 0) > self._clock() else await self.access_token(user_id)
                await client.delete(REVOKE, headers={"Authorization": f"Bearer {token}"})
            except Exception as e:  # the local delete below is what matters
                log_event(logger, logging.INFO, "whoop_revoke_failed", error=type(e).__name__)
            finally:
                if self._http is None:
                    await client.aclose()
        self.forget_tokens(user_id)

    def forget_tokens(self, user_id: str) -> None:
        """The synchronous part of ``disconnect`` (account deletion)."""
        self._doc(user_id).delete()
        self._read.pop(user_id, None)
        from .workouts import drop_source
        drop_source(self._s, user_id, "whoop")

    async def workouts(self, user_id: str, start: date, end: date) -> list[dict[str, Any]]:
        """WHOOP workouts between ``start`` and ``end`` (inclusive) as ``workouts.from_whoop`` rows."""
        from .workouts import from_whoop
        token = await self.access_token(user_id)
        lo = datetime.combine(start - timedelta(days=1), dtime.min, UTC)  # local days vs UTC: pad a day
        hi = datetime.combine(end + timedelta(days=2), dtime.min, UTC)
        out: list[dict[str, Any]] = []
        nxt: str | None = None
        client = self._client()
        try:
            for _ in range(MAX_PAGES):
                params = {"start": lo.isoformat().replace("+00:00", "Z"),
                          "end": hi.isoformat().replace("+00:00", "Z"), "limit": str(PAGE)}
                if nxt:
                    params["nextToken"] = nxt
                r = await client.get(WORKOUTS, params=params, headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 401:
                    raise WhoopNotConnected("WHOOP access expired. Connect it again in Connected apps.")
                if r.status_code == 403:
                    raise WhoopError("WHOOP refused this data. Connect WHOOP again and allow workouts.")
                if r.status_code == 429:
                    raise WhoopError("WHOOP is rate limiting requests. Try again in a few minutes.")
                if r.status_code >= 500:
                    raise WhoopError("WHOOP is having trouble right now. Try again later.")
                r.raise_for_status()
                body = r.json() if r.content else {}
                for rec in body.get("records") or []:
                    if isinstance(rec, dict) and (w := from_whoop(rec)):
                        day = w["start"][:10]
                        if start.isoformat() <= day <= end.isoformat():
                            out.append(w)
                nxt = body.get("next_token") or body.get("nextToken")
                if not nxt:
                    break
        finally:
            if self._http is None:
                await client.aclose()
        self._read[user_id] = self._clock()
        log_event(logger, logging.INFO, "whoop_read", user_id=user_id, workouts=len(out))
        return out


__all__ = ["WhoopClient", "WhoopError", "WhoopNotConnected", "SCOPES"]
