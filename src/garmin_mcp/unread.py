"""Unread counts for the app icon badge (Badging API) and the push payload's ``badge``.

Four sources, athletes only (coach accounts get 403 on the route and no badge in pushes):

* ``cheers``: new reactions/comments on my Community posts (``Community.unread_count``),
  cleared per post when opened and all at once when Community is opened.
* ``requests``: pending follow requests newer than the last time I looked at People.
* ``invites``: open club invites newer than the last time I looked at Clubs.
* ``coach``: unread messages from my human coach (``CoachChat.unread``), cleared by
  opening the thread (as before).

"Seen" times for requests/invites live in the per-user ``unread_seen`` doc.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore
from .logs import log_event

logger = logging.getLogger(__name__)

KINDS = ("cheers", "requests", "invites", "coach")


class Unread:
    def __init__(self, store: AppStore, *, community: Any = None, social: Any = None, clubs: Any = None,
                 coach_chat: Any = None, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self.community = community
        self.social = social
        self.clubs = clubs
        self.coach_chat = coach_chat
        self._clock = clock

    def _seen(self, uid: str) -> dict[str, Any]:
        return self._s.user_doc(uid, "unread_seen").load()

    def counts(self, uid: str) -> dict[str, int]:
        """``{cheers, requests, invites, coach, total}``. Each source is best effort."""
        seen = self._seen(uid)
        out = {k: 0 for k in KINDS}
        if uid.startswith("coach_"):
            return {**out, "total": 0}
        parts: dict[str, Callable[[], int]] = {}
        if self.community is not None:
            parts["cheers"] = lambda: self.community.unread_count(uid)
        if self.social is not None:
            parts["requests"] = lambda: self.social.requests_since(uid, float(seen.get("requests") or 0))
        if self.clubs is not None:
            parts["invites"] = lambda: self.clubs.invites_since(uid, float(seen.get("invites") or 0))
        if self.coach_chat is not None:
            parts["coach"] = lambda: self.coach_chat.unread(uid, "athlete")
        for k, fn in parts.items():
            try:
                out[k] = max(0, int(fn()))
            except Exception as e:
                log_event(logger, logging.WARNING, "unread_count_failed", kind=k, error=type(e).__name__)
        return {**out, "total": sum(out.values())}

    def total(self, uid: str) -> int | None:
        """For the push payload: None for coach accounts (no badge field)."""
        if uid.startswith("coach_"):
            return None
        return self.counts(uid)["total"]

    def seen(self, uid: str, kind: Any) -> dict[str, int]:
        """Mark ``cheers`` | ``requests`` | ``invites`` as viewed (``coach`` clears by opening
        the thread). Returns the new counts."""
        if kind not in KINDS:
            raise ValueError("kind")
        if kind == "cheers" and self.community is not None:
            self.community.mark_seen(uid)
        elif kind in ("requests", "invites"):
            now = self._clock()
            self._s.user_doc(uid, "unread_seen").update(lambda d: d.__setitem__(kind, now))
        return self.counts(uid)


__all__ = ["KINDS", "Unread"]
