""""I'm going" on club directory listings (``clubdir``): per listing *occurrence* (the next
session's date), athletes mark Going. Cards show how many are going and the avatars of people
you follow (active edge; mutuals included); blocked people (either way) are never counted or
shown. A new occurrence starts empty, so the list resets every week. The evening before (from
``REMIND_FROM`` local, checked from ``Moments.tick``, which never runs in quiet hours, and
``Moments.post`` queues anything that lands in them) a Rabbit moment reminds each person going.

Storage: global ``clubgoing`` doc ``{"k": {"<metro>|<lid>|<YYYY-MM-DD>": {"name", "time", "spot",
"date", "users": {uid: ts}}}}``; past occurrences are pruned on write, at most ``MAX_KEYS``
occurrences and ``MAX_PER`` people each. Athletes only (callers 403 coach accounts).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from .clubdir import DirectoryError, Metro

DOC = "clubgoing"
MAX_KEYS = 2000
MAX_PER = 300
FRIENDS_SHOWN = 5
REMIND_FROM = dtime(18, 0)
REMIND_EVERY_S = 600


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def reminder_line(e: dict[str, Any], count: int) -> str:
    """"🏃 Tomorrow 18:00: Wash Park Runners at Wash Park boathouse · 3 going."""
    when = f"Tomorrow {e['time']}" if e.get("time") else "Tomorrow"
    where = f" at {e['spot']}" if e.get("spot") else ""
    tail = f" · {count} going" if count > 1 else ""
    return _clip(f"🏃 {when}: {e.get('name') or 'Group run'}{where}{tail}.", 140)


class Going:
    def __init__(self, store: Any, *, follows: Callable[[str, str], bool], blocked: Callable[[str, str], bool],
                 is_athlete: Callable[[str], bool], person: Callable[[str], dict[str, Any] | None] = lambda u: {"id": u},
                 moment: Callable[[str, dict[str, Any]], Any] | None = None,
                 now: Callable[[str], datetime] | None = None, clock: Callable[[], float] = time.time) -> None:
        """``follows(viewer, other)``: an active follow edge; ``blocked(a, b)``: either way."""
        self._doc = store.global_doc(DOC)
        self._follows = follows
        self._blocked = blocked
        self._is_athlete = is_athlete
        self._person = person
        self.moment = moment
        self._now = now
        self._clock = clock
        self._lock = threading.Lock()
        self._reminded: dict[str, float] = {}

    @staticmethod
    def key(m: Metro, lid: str, day: str) -> str:
        return f"{m.slug}|{lid}|{day}"

    # -------------------------------------------------------------- write --
    def set(self, uid: str, m: Metro, listing: dict[str, Any], going: Any, *, day: Any = None,
            today: date) -> dict[str, Any]:
        """Mark/unmark Going for ``listing``'s next occurrence (``listing`` = public shape with
        ``next.date``). ``day``, when sent, must be that occurrence (else 409: it moved on)."""
        if uid.startswith("coach_"):
            raise DirectoryError("Community is for athletes on Rabbit.", 403)
        if not isinstance(going, bool):
            raise DirectoryError("going must be true or false")
        nxt = listing.get("next") or {}
        occ = nxt.get("date")
        if not occ:
            raise DirectoryError("This group has no weekly session to go to.")
        if day is not None and day != occ:
            raise DirectoryError("That session has passed. Here's the next one.", 409)
        k = self.key(m, listing["id"], occ)
        floor = (today - timedelta(days=1)).isoformat()
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            ks: dict[str, Any] = d.setdefault("k", {})
            for old in [x for x, e in ks.items() if not isinstance(e, dict) or str(e.get("date") or "") < floor]:
                del ks[old]
            e = ks.get(k)
            if e is None:
                if not going:
                    return
                e = ks[k] = {"name": listing.get("name") or "", "time": nxt.get("time") or "",
                             "spot": listing.get("meet_spot") or "", "date": occ, "users": {}}
            users: dict[str, int] = e.setdefault("users", {})
            if going:
                if uid not in users and len(users) >= MAX_PER:
                    raise DirectoryError("Lots of people are going already.", 409)
                users[uid] = now
            else:
                users.pop(uid, None)
                if not users:
                    del ks[k]
            if len(ks) > MAX_KEYS:
                for old in sorted(ks, key=lambda x: str(ks[x].get("date") or ""))[: len(ks) - MAX_KEYS]:
                    del ks[old]
        with self._lock:
            self._doc.update(apply)
        return self.summary(uid, m, listing)

    # --------------------------------------------------------------- read --
    def _view(self, uid: str, e: dict[str, Any] | None, day: str) -> dict[str, Any]:
        users = list(((e or {}).get("users") or {}).items())
        users.sort(key=lambda x: x[1])
        seen = [u for u, _ in users if u == uid or (self._is_athlete(u) and not self._blocked(uid, u))]
        friends = [u for u in seen if u != uid and self._follows(uid, u)]
        people = [p for p in (self._person(u) for u in friends[:FRIENDS_SHOWN]) if p]
        return {"date": day, "count": len(seen), "me": uid in seen, "friends": people,
                "more_friends": max(0, len(friends) - FRIENDS_SHOWN)}

    def summary(self, uid: str, m: Metro, listing: dict[str, Any]) -> dict[str, Any] | None:
        occ = (listing.get("next") or {}).get("date")
        if not occ:
            return None
        e = (self._doc.load().get("k") or {}).get(self.key(m, listing["id"], occ))
        return self._view(uid, e, occ)

    def attach(self, uid: str, m: Metro, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Adds ``going`` to each listing row (one doc read). None when there's no session."""
        ks = self._doc.load().get("k") or {}
        for r in rows:
            occ = (r.get("next") or {}).get("date")
            r["going"] = self._view(uid, ks.get(self.key(m, r["id"], occ)), occ) if occ else None
        return rows

    # ---------------------------------------------------------- reminder --
    def due_reminders(self, uid: str, local: datetime) -> list[dict[str, Any]]:
        """Occurrences tomorrow that ``uid`` is going to, once it's evening (``REMIND_FROM``)."""
        if local.time() < REMIND_FROM:
            return []
        tomorrow = (local.date() + timedelta(days=1)).isoformat()
        out = []
        for k, e in (self._doc.load().get("k") or {}).items():
            if isinstance(e, dict) and e.get("date") == tomorrow and uid in (e.get("users") or {}):
                out.append({**e, "key": k, "count": self._view(uid, e, tomorrow)["count"]})
        return out

    def remind(self, uid: str) -> int:
        """``Moments.tick`` hook: one moment per occurrence (deduped by key), checked at most
        every ``REMIND_EVERY_S`` per person."""
        if uid.startswith("coach_") or self.moment is None or self._now is None:
            return 0
        now = self._clock()
        with self._lock:
            if now - self._reminded.get(uid, 0) < REMIND_EVERY_S:
                return 0
            self._reminded[uid] = now
            if len(self._reminded) > 5000:
                self._reminded.pop(next(iter(self._reminded)))
        n = 0
        for e in self.due_reminders(uid, self._now(uid)):
            self.moment(uid, {"type": "meetup", "key": f"going:{e['key']}", "ttl_days": 3,
                              "text": reminder_line(e, e["count"]),
                              "actions": [{"id": "community", "label": "Open Community"}]})
            n += 1
        return n


__all__ = ["Going", "reminder_line"]
