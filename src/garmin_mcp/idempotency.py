"""Idempotency-Key replay for mutating Rabbit API calls (``webapp._api``).

The app's outbox (``web/src/lib/outbox.ts``) retries saves that may or may not have reached
the server (offline, timeout, 5xx). Each retry carries the same ``Idempotency-Key`` header,
so a check-in, post or comment is created once however many times it is sent:

* the key is optional; without it nothing changes;
* keys are per user and per ``METHOD path`` (the same key on another route is a different
  slot) and are remembered for 24 h in the user's encrypted ``idempotency`` doc (so a
  retry after a deploy/restart still replays), at most ``MAX_KEYS`` per user;
* only 2xx JSON-ish responses with a body <= ``MAX_BODY`` are remembered; a replay returns
  the stored status and body with ``Idempotent-Replayed: true``;
* the same key with a different body is refused (422), and a second request while the first
  is still running gets 409 ``code: in_flight`` (the client retries it later).
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
TTL_S = 24 * 3600
MAX_KEYS = 300
MAX_BODY = 64 * 1024
DOC = "idempotency"


class InFlight(Exception):
    """The same key is being handled right now."""


class Mismatch(Exception):
    """The key was used before for a different request body."""


def valid_key(key: str) -> bool:
    return bool(KEY_RE.match(key))


def _slot(method: str, path: str, key: str) -> str:
    return hashlib.sha256(f"{method.upper()} {path}\n{key}".encode()).hexdigest()[:32]


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:32]


class Idempotency:
    def __init__(self, store: AppStore, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock
        self._lock = threading.Lock()
        self._inflight: set[tuple[str, str]] = set()

    def begin(self, user_id: str, method: str, path: str, key: str,
              body: bytes) -> tuple[str, dict[str, Any] | None]:
        """Returns ``(slot, cached)``: ``cached`` is the remembered response to replay, or
        None (go ahead, then call ``finish`` or ``abort``). Raises InFlight / Mismatch."""
        slot = _slot(method, path, key)
        now = self._clock()
        rec = self._s.user_doc(user_id, DOC).load().get(slot)
        if rec and now - float(rec.get("at", 0)) < TTL_S:
            if rec.get("req") != _digest(body):
                raise Mismatch()
            return slot, rec
        with self._lock:
            if (user_id, slot) in self._inflight:
                raise InFlight()
            self._inflight.add((user_id, slot))
        return slot, None

    def finish(self, user_id: str, slot: str, body: bytes, status: int, response: bytes,
               media_type: str | None) -> None:
        try:
            if 200 <= status < 300 and len(response) <= MAX_BODY:
                now = self._clock()
                rec = {"at": now, "req": _digest(body), "status": status, "type": media_type or "application/json",
                       "body": base64.b64encode(response).decode("ascii")}

                def put(d: dict[str, Any]) -> None:
                    for k in [k for k, v in d.items() if now - float(v.get("at", 0)) >= TTL_S]:
                        del d[k]
                    d[slot] = rec
                    if len(d) > MAX_KEYS:
                        for k in sorted(d, key=lambda k: float(d[k].get("at", 0)))[:len(d) - MAX_KEYS]:
                            del d[k]
                self._s.user_doc(user_id, DOC).update(put)
        finally:
            self.abort(user_id, slot)

    def abort(self, user_id: str, slot: str) -> None:
        with self._lock:
            self._inflight.discard((user_id, slot))

    @staticmethod
    def replay_body(rec: dict[str, Any]) -> bytes:
        return base64.b64decode(rec.get("body") or "")
