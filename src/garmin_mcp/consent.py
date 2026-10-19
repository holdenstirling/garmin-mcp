"""Agreeing to the terms: shown on first sign-in / join and again whenever ``legal.VERSION`` changes.

Per-user ``consent`` doc: ``{"version", "ts", "age16", "health", "share", "share_ts", "history": [{version, ts}]}``.
``share`` is the separate, optional consent to share workouts (health data) with friends the
person chooses (My Health My Data Act: sharing needs its own consent); webapp applies it to the
community ``share_workouts`` setting.
Accepting needs all four: terms, privacy, 16 or older, and explicit consent to processing health
and fitness data (Colorado Privacy Act / GDPR art. 9 style opt-in). Coaches agree too.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import legal
from .appstore import AppStore

REQUIRED = ("terms", "privacy", "age16", "health")
HISTORY = 20


class ConsentError(ValueError):
    pass


class Consent:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def get(self, uid: str) -> dict[str, Any]:
        return self._s.user_doc(uid, "consent").load()

    def needed(self, uid: str) -> bool:
        return self.get(uid).get("version") != legal.VERSION

    def view(self, uid: str) -> dict[str, Any]:
        d = self.get(uid)
        return {"needed": d.get("version") != legal.VERSION, "version": legal.VERSION,
                "accepted_version": d.get("version"), "accepted_at": d.get("ts"),
                "first": not d.get("version"),
                "share": d.get("share") if isinstance(d.get("share"), bool) else None}

    def accept(self, uid: str, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ConsentError("bad request")
        missing = [k for k in REQUIRED if body.get(k) is not True]
        if missing:
            raise ConsentError("Please tick every box to continue: " + ", ".join(missing) + ".")
        share = body.get("share")
        if share is not None and not isinstance(share, bool):
            raise ConsentError("share must be true or false")
        if body.get("version") not in (None, legal.VERSION):
            raise ConsentError("The terms changed while you were reading. Please review them again.")
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            hist = [h for h in d.get("history", []) if isinstance(h, dict)]
            hist.append({"version": legal.VERSION, "ts": now})
            d.update(version=legal.VERSION, ts=now, age16=True, health=True, history=hist[-HISTORY:])
            if isinstance(share, bool):
                d.update(share=share, share_ts=now)
        self._s.user_doc(uid, "consent").update(apply)
        return self.view(uid)


__all__ = ["Consent", "ConsentError", "REQUIRED"]
