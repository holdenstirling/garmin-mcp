""""Coming soon" apps (Whoop, Apple Watch / Apple Health, Coros) and how many people want each.

Each app has a short, honest note on why it isn't here yet and what Rabbit would use. Athletes
tap "I want this" (``vote``), which keeps only their user id per app (global ``app-demand``
doc), so each person counts once and can be told when it ships. Owners see the counts.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

DOC = "app-demand"

SOON: dict[str, dict[str, Any]] = {
    "whoop": {
        "name": "Whoop",
        "why": "Whoop shares data only with approved partner apps, so Rabbit can't connect to it yet.",
        "would_use": ["Workouts, so they show up with your plan and your friends' feed",
                      "Recovery, strain and sleep, shown in the app and used by fixed rules"],
    },
    "apple": {
        "name": "Apple Watch",
        "why": "Apple Watch workouts live in Apple Health on your iPhone, which only an iPhone app "
               "can read. Rabbit is a web app today, so this needs a Rabbit iPhone app first.",
        "would_use": ["Workouts recorded on your Apple Watch",
                      "Heart rate and sleep from Apple Health"],
    },
    "coros": {
        "name": "Coros",
        "why": "Coros shares data only with approved partner apps, so Rabbit can't connect to it yet.",
        "would_use": ["Workouts, heart rate and training load",
                      "Sending your planned workouts to your Coros watch"],
    },
}
SOON_ORDER = ("whoop", "apple", "coros")


class DemandError(ValueError):
    pass


class Demand:
    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _doc(self) -> Any:
        return self._s.global_doc(DOC)

    def vote(self, uid: str, app: str, want: bool) -> bool:
        """Turn "I want this" on or off; returns the new state. Idempotent."""
        if app not in SOON:
            raise DemandError("That app isn't on the coming-soon list.")

        def apply(d: dict[str, Any]) -> bool:
            votes: dict[str, Any] = d.setdefault(app, {})
            if want:
                votes.setdefault(uid, int(self._clock()))
            else:
                votes.pop(uid, None)
            return uid in votes
        return bool(self._doc().update(apply))

    def mine(self, uid: str) -> set[str]:
        d = self._doc().load()
        return {a for a in SOON if uid in (d.get(a) or {})}

    def counts(self) -> dict[str, int]:
        d = self._doc().load()
        return {a: len(d.get(a) or {}) for a in SOON_ORDER}

    def voters(self, app: str) -> list[str]:
        """Who to tell when ``app`` ships."""
        return sorted((self._doc().load().get(app) or {}).keys())

    def rows(self, uid: str, *, owner: bool) -> list[dict[str, Any]]:
        """The coming-soon rows for the Connected apps hub (counts for owners only)."""
        mine, counts = self.mine(uid), (self.counts() if owner else None)
        return [{"id": a, "name": SOON[a]["name"], "state": "soon", "why": SOON[a]["why"],
                 "would_use": list(SOON[a]["would_use"]), "wanted": a in mine,
                 **({"wanted_by": counts[a]} if counts is not None else {})} for a in SOON_ORDER]


__all__ = ["SOON", "SOON_ORDER", "Demand", "DemandError"]
