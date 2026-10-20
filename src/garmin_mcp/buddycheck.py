"""Check-in buddy: a simple safety ping for runs alone (no GPS, no location stored).

An athlete picks a buddy (someone they follow who follows them back), taps "I'm starting" with
when they expect to be back, then "I'm back". The buddy gets a push for each. If the runner
isn't back by the expected time plus ``GRACE_MIN``, the runner gets a nudge ("Back yet?"); if
still not back ``BUDDY_AFTER_MIN`` after that, the buddy gets "<name> hasn't checked in yet".
Nothing about where they ran is stored or sent: only the times and the two taps.

Storage: per-user ``buddycheck`` doc ``{"buddy": uid | None, "active": {started, back_by,
nudged_runner, nudged_buddy} | None, "log": [{started, back, late}] (last 20)}``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore

GRACE_MIN = 15
BUDDY_AFTER_MIN = 15
MAX_MINUTES = 8 * 60
LOG_KEEP = 20


class BuddyError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class BuddyCheck:
    def __init__(self, store: AppStore, *, mutual: Callable[[str, str], bool],
                 notify: Callable[[str, str, str, str], None], name: Callable[[str], str],
                 clock: Callable[[], float] = time.time) -> None:
        """``mutual(a, b)``: they follow each other; ``notify(uid, key, title, body)`` sends a
        push (rate-limited by key) and a bell item."""
        self._store = store
        self._mutual = mutual
        self._notify = notify
        self._name = name
        self._clock = clock

    def _doc(self, uid: str) -> Any:
        return self._store.user_doc(uid, "buddycheck")

    def view(self, uid: str) -> dict[str, Any]:
        d = self._doc(uid).load()
        buddy = d.get("buddy")
        if buddy and not self._mutual(uid, buddy):
            buddy = None
        a = d.get("active")
        return {"buddy": buddy, "active": {"started": a["started"], "back_by": a["back_by"]} if a else None}

    def set_buddy(self, uid: str, buddy: Any) -> dict[str, Any]:
        if buddy is not None:
            if not isinstance(buddy, str) or buddy == uid or not self._mutual(uid, buddy):
                raise BuddyError("Pick a friend who follows you back.")

        def apply(d: dict[str, Any]) -> None:
            d["buddy"] = buddy
            if buddy is None:
                d["active"] = None
        self._doc(uid).update(apply)
        return self.view(uid)

    def start(self, uid: str, minutes: Any) -> dict[str, Any]:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= MAX_MINUTES:
            raise BuddyError("How long will you be out? 5 minutes to 8 hours.")
        d = self._doc(uid).load()
        buddy = d.get("buddy")
        if not buddy or not self._mutual(uid, buddy):
            raise BuddyError("Pick a check-in buddy first.")
        now = int(self._clock())
        back_by = now + minutes * 60

        def apply(doc: dict[str, Any]) -> None:
            doc["active"] = {"started": now, "back_by": back_by, "nudged_runner": False, "nudged_buddy": False}
        self._doc(uid).update(apply)
        span = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} h {minutes % 60:02d} min"
        self._notify(buddy, f"buddy-start:{buddy}:{uid}:{now}", f"{self._name(uid)} is heading out",
                     f"Back in about {span}. You'll hear when they're back.")
        return self.view(uid)

    def back(self, uid: str) -> dict[str, Any]:
        d = self._doc(uid).load()
        a = d.get("active")
        if not a:
            return self.view(uid)
        now = int(self._clock())

        def apply(doc: dict[str, Any]) -> None:
            log = doc.setdefault("log", [])
            log.append({"started": a["started"], "back": now, "late": now > a["back_by"]})
            del log[: max(0, len(log) - LOG_KEEP)]
            doc["active"] = None
        self._doc(uid).update(apply)
        buddy = d.get("buddy")
        if buddy and self._mutual(uid, buddy):
            self._notify(buddy, f"buddy-back:{buddy}:{uid}:{a['started']}", f"{self._name(uid)} is back",
                         "They checked in safe. Nothing else to do.")
        return self.view(uid)

    def tick(self, uid: str) -> list[str]:
        """Late nudges: the runner at ``back_by + GRACE_MIN``, the buddy ``BUDDY_AFTER_MIN``
        later. Returns what was sent (for tests/logs)."""
        d = self._doc(uid).load()
        a = d.get("active")
        if not a:
            return []
        now = self._clock()
        sent: list[str] = []
        if not a.get("nudged_runner") and now >= a["back_by"] + GRACE_MIN * 60:
            self._notify(uid, f"buddy-late:{uid}:{a['started']}", "Back yet?",
                         "Tap I'm back so your buddy knows you're safe.")
            sent.append("runner")
            a["nudged_runner"] = True
        buddy = d.get("buddy")
        if (buddy and not a.get("nudged_buddy") and self._mutual(uid, buddy)
                and now >= a["back_by"] + (GRACE_MIN + BUDDY_AFTER_MIN) * 60):
            self._notify(buddy, f"buddy-late:{buddy}:{uid}:{a['started']}",
                         f"{self._name(uid)} hasn't checked in yet",
                         "They were due back a while ago. Give them a call or a text.")
            sent.append("buddy")
            a["nudged_buddy"] = True
        if sent:
            def apply(doc: dict[str, Any]) -> None:
                if doc.get("active") and doc["active"].get("started") == a["started"]:
                    doc["active"].update({k: a[k] for k in ("nudged_runner", "nudged_buddy")})
            self._doc(uid).update(apply)
        return sent

    def forget(self, uid: str) -> None:
        self._doc(uid).update(lambda d: d.clear())


__all__ = ["BuddyCheck", "BuddyError", "GRACE_MIN", "BUDDY_AFTER_MIN"]
