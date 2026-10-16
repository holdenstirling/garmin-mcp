"""Celebrations that feel earned: a full-screen moment, once per achievement, on any device.

``GET /app/api/celebrations`` lists the athlete's unseen ones (newest first, at most 3);
``POST /app/api/celebrations/{id}/seen`` dismisses one for good (per-user ``celebrations``
doc, so a phone and a laptop don't both celebrate). Deterministic, no model call, no Oura.

* ``race:<event id>``: a race on the athlete's calendar (``events.is_race``) dated in the
  last ``RACE_DAYS`` days, with either a result typed in or a Garmin activity that day
  (the longest one gives the time and distance when there's no result).
* ``block:<block id>``: a shared training block the athlete was still in when its last
  week finished (``end`` in the last ``BLOCK_DAYS`` days, not ended early), with how many
  of the kept weeks they closed.
* ``pr:<activity id>``: a big personal record from the post-workout reward (``reward.py``
  headline): fastest 5K/10K or longest run/ride/swim/hike that's the best in 12 months or
  ever. Celebrated from the reward sheet itself (the app opens it full screen first), so it
  is not listed here; ``seen`` still records it so other devices skip it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .events import is_race
from .moments import fmt_distance, fmt_duration
from .stats import category
from .weekplan import _seconds

if TYPE_CHECKING:
    from .appstore import AppStore

RACE_DAYS = 14
BLOCK_DAYS = 14
MAX_ITEMS = 3
KEEP_SEEN = 200
BIG_RECORDS = ("split_5k", "split_10k", "distance")


def big_record(headline: dict[str, Any] | None) -> bool:
    """A reward headline worth a full-screen moment: best in 12 months or ever."""
    h = headline or {}
    return h.get("kind") in BIG_RECORDS and h.get("weeks") is None


def _d(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def race_items(events: list[dict[str, Any]], acts: list[dict[str, Any]], today: date,
               *, imperial: bool) -> list[dict[str, Any]]:
    out = []
    for e in events or []:
        d = _d(e.get("date"))
        if not is_race(e) or d is None or not (today - timedelta(days=RACE_DAYS) <= d <= today):
            continue
        day = [a for a in acts or [] if str(a.get("date") or "")[:10] == d.isoformat()
               and not (a.get("multisport") or {}).get("parent_id")]
        best = max(day, key=lambda a: _seconds(a.get("duration")), default=None)
        result = str(e.get("result") or "").strip()[:60]
        if not result and best is None:
            continue
        stats: list[dict[str, str]] = []
        if result:
            stats.append({"label": "Result", "value": result})
        elif best is not None and _seconds(best.get("duration")):
            stats.append({"label": "Time", "value": fmt_duration(_seconds(best.get("duration")))})
        if best is not None and best.get("distance_km"):
            stats.append({"label": "Distance",
                          "value": fmt_distance(float(best["distance_km"]) * 1000, category(best.get("sport")), imperial) or ""})
        if e.get("distance") and len(stats) < 3 and not any(s["label"] == "Distance" for s in stats):
            stats.append({"label": "Race", "value": str(e["distance"])[:30]})
        name = str(e.get("name") or "Your race")[:80]
        out.append({"id": f"race:{e.get('id')}", "kind": "race", "date": d.isoformat(),
                    "title": "You finished!", "subtitle": name,
                    "line": f"{name} is in the books. All those weeks of training, done.",
                    "stats": [s for s in stats if s["value"]][:3], "activity_id": (best or {}).get("activity_id")})
    return out


def block_items(blocks: dict[str, dict[str, Any]], uid: str, today: date) -> list[dict[str, Any]]:
    out = []
    for b in (blocks or {}).values():
        if uid not in (b.get("members") or {}):
            continue
        end = _d(b.get("end"))
        if end is None or not (today - timedelta(days=BLOCK_DAYS) <= end < today):
            continue
        if b.get("status") == "ended" and (b.get("ended_on") or "") < end.isoformat():
            continue  # stopped early: not a finish
        rows = [w.get(uid) for w in (b.get("progress") or {}).values()]
        rows = [r for r in rows if isinstance(r, list) and len(r) == 2]
        closed = sum(1 for r in rows if r[1] > 0 and r[0] >= r[1])
        sessions = sum(int(r[0]) for r in rows)
        stats = [{"label": "Weeks", "value": str(b.get("weeks") or "")}]
        if rows:
            stats.append({"label": "Weeks closed", "value": f"{closed} of {len(rows)}" + (" (last)" if len(rows) < int(b.get("weeks") or 0) else "")})
            stats.append({"label": "Sessions", "value": str(sessions)})
        members = len(b.get("members") or {})
        name = str(b.get("name") or "Training block")[:80]
        out.append({"id": f"block:{b.get('id')}", "kind": "block", "date": end.isoformat(),
                    "title": "Block complete", "subtitle": name,
                    "line": (f"You and {members - 1} {'friend' if members == 2 else 'friends'} saw it through." if members > 1
                             else "You saw it through, week after week."),
                    "stats": [s for s in stats if s["value"]][:3], "block_id": b.get("id")})
    return out


class Celebrations:
    def __init__(self, store: "AppStore", *, now: Callable[[str], datetime],
                 events: Callable[[str], list[dict[str, Any]]],
                 acts: Callable[[str], list[dict[str, Any]]],
                 imperial: Callable[[str], bool]) -> None:
        self._s = store
        self._now = now
        self._events = events
        self._acts = acts
        self._imperial = imperial

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "celebrations")

    def pending(self, uid: str) -> list[dict[str, Any]]:
        if uid.startswith("coach_"):
            return []
        today = self._now(uid).date()
        seen = self._doc(uid).load().get("seen") or {}
        items: list[dict[str, Any]] = []
        races = [e for e in self._events(uid) or [] if is_race(e)]
        if any(f"race:{e.get('id')}" not in seen and _d(e.get("date")) and
               today - timedelta(days=RACE_DAYS) <= (_d(e.get("date")) or today) <= today for e in races):
            try:
                acts = self._acts(uid)
            except Exception:  # Garmin down: races with a typed result still count
                acts = []
            items += race_items(races, acts, today, imperial=self._imperial(uid))
        items += block_items(self._s.global_doc("blocks").load().get("blocks") or {}, uid, today)
        items = [i for i in items if i["id"] not in seen]
        items.sort(key=lambda i: (i["kind"] == "race", i["date"]), reverse=True)
        return items[:MAX_ITEMS]

    def seen(self, uid: str, cid: str) -> None:
        stamp = self._now(uid).date().isoformat()

        def apply(d: dict[str, Any]) -> None:
            s = d.setdefault("seen", {})
            s[cid] = stamp
            for k in sorted(s, key=lambda k: s[k])[:-KEEP_SEEN]:
                del s[k]
        self._doc(uid).update(apply)

    def was_seen(self, uid: str, cid: str) -> bool:
        return cid in (self._doc(uid).load().get("seen") or {})


def valid_id(cid: str) -> bool:
    kind, _, rest = cid.partition(":")
    return kind in ("race", "block", "pr") and 0 < len(rest) <= 64 and all(c.isalnum() or c in "-_" for c in rest)
