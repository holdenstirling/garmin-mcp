"""A daily cap on chat messages to rabbt, per person (cost control).

``AGENT_DAILY_MESSAGES`` (default 40) messages per local day; 0 turns the cap off. Counted only
when a reply actually starts. Storage: per-user ``chatcap`` doc ``{"day": "YYYY-MM-DD", "n": int,
"days": {date: n}}`` (the last 30 days, for usage numbers).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .appstore import AppStore

KEEP_DAYS = 30
LIMIT_MESSAGE = ("You've sent rabbt {cap} messages today, the daily limit. It resets at midnight. "
                 "Your plan, feed and everything else still work.")


class ChatCap:
    def __init__(self, store: AppStore, cap: int) -> None:
        self._store = store
        self.cap = max(0, int(cap))

    def _doc(self, uid: str) -> Any:
        return self._store.user_doc(uid, "chatcap")

    def used(self, uid: str, today: date) -> int:
        d = self._doc(uid).load()
        return int(d.get("n") or 0) if d.get("day") == today.isoformat() else 0

    def allowed(self, uid: str, today: date) -> bool:
        return not self.cap or self.used(uid, today) < self.cap

    def count(self, uid: str, today: date) -> int:
        key = today.isoformat()

        def apply(d: dict[str, Any]) -> int:
            if d.get("day") != key:
                d["day"], d["n"] = key, 0
            d["n"] = int(d.get("n") or 0) + 1
            days = d.setdefault("days", {})
            days[key] = d["n"]
            for k in sorted(days)[:-KEEP_DAYS]:
                del days[k]
            return int(d["n"])
        return int(self._doc(uid).update(apply))

    def forget(self, uid: str) -> None:
        self._doc(uid).update(lambda d: d.clear())

    def message(self) -> str:
        return LIMIT_MESSAGE.format(cap=self.cap)


__all__ = ["ChatCap", "LIMIT_MESSAGE"]
