"""Calendar insights: the athlete's next two weeks of training against their Google Calendar
(gcalendar.py summary: busy minutes, busy blocks as local [start, end] minutes, travel windows).

Deterministic. Per day: a load (light / normal / heavy / packed) and free windows inside the
training day. Per planned session: conflicts (a start time inside a meeting, a hard or long
session on a heavy day, sessions during a trip that isn't in travel mode). Out come a few
recommendations, each with one action the athlete taps (nothing changes the plan on its own):

* ``time``   set the session's start time to a free slot (same day)
* ``move``   move the session to a lighter day this week (plancal move) at a free slot
* ``ease``   packed day, no better day: make it an easy session of at most 30 min
* ``travel`` open travel mode with the trip's dates filled in
* ``long_day`` long sessions keep landing on busy days: change the long day (Adjust my plan)

Event titles only appear in travel recommendations, shown to the athlete; nothing here goes
to the AI (it keeps seeing busy hours and travel windows as before).
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from .planbuilder import DAYS, QUALITY, iter_sessions

LONG_KINDS = ("long", "brick")
DAY_START, DAY_END = 5 * 60 + 30, 21 * 60  # training day 05:30-21:00
BUFFER = 15  # minutes kept free around meetings
HORIZON = 14
MAX_RECS = 5
WEEKDAY_NAME = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def nice_time(m: int) -> str:
    h, mm = divmod(m, 60)
    suf = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {suf}" if mm else f"{h12} {suf}"


def _mins(s: dict[str, Any]) -> int:
    m = s.get("minutes") or sum(int(lg.get("minutes") or 0) for lg in s.get("legs") or [])
    return int(m or 45)


def _start(s: dict[str, Any]) -> int | None:
    t = s.get("time")
    if not isinstance(t, str) or len(t) != 5 or t[2] != ":":
        return None
    try:
        return int(t[:2]) * 60 + int(t[3:])
    except ValueError:
        return None


def day_load(busy_min: int, blocks: list[list[int]]) -> str:
    early = any(a < 8 * 60 for a, _ in blocks)
    late = any(b > 18 * 60 + 30 for _, b in blocks)
    if busy_min >= 480 or (busy_min >= 360 and early and late):
        return "packed"
    if busy_min >= 300 or (early and late and busy_min >= 120):
        return "heavy"
    if busy_min >= 120:
        return "normal"
    return "light"


def free_windows(blocks: list[list[int]], need: int = 30) -> list[list[int]]:
    """Gaps of at least ``need`` minutes inside the training day, with a buffer around meetings."""
    out: list[list[int]] = []
    cur = DAY_START
    for a, b in sorted(blocks):
        a, b = a - BUFFER, b + BUFFER
        if a - cur >= need:
            out.append([cur, min(a, DAY_END)])
        cur = max(cur, b)
        if cur >= DAY_END:
            break
    if DAY_END - cur >= need:
        out.append([cur, DAY_END])
    return [w for w in out if w[1] - w[0] >= need]


def best_slot(windows: list[list[int]], need: int, prefer: int | None = None) -> int | None:
    """A start time that fits ``need`` minutes: nearest to ``prefer`` (the planned start), else
    early morning (06:00), else lunch, else the earliest that fits."""
    fits = [w for w in windows if w[1] - w[0] >= need]
    if not fits:
        return None
    cands: list[int] = []
    for a, b in fits:
        for t in (prefer, 6 * 60, 12 * 60, 17 * 60 + 30, a, b - need):
            if t is not None and a <= t <= b - need:
                cands.append(t)
        cands.append(a)
    target = prefer if prefer is not None else 6 * 60
    # Round to 5 minutes, then pick the one closest to what they'd planned (or the morning).
    cands = sorted({(c + 4) // 5 * 5 for c in cands if any(a <= (c + 4) // 5 * 5 <= b - need for a, b in fits)})
    return min(cands, key=lambda c: (abs(c - target), c)) if cands else None


def _overlaps(start: int, need: int, blocks: list[list[int]]) -> bool:
    return any(start < b and start + need > a for a, b in blocks)


def _rid(*parts: Any) -> str:
    return "c" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _label(d: str, today: date) -> str:
    dd = date.fromisoformat(d)
    if dd == today:
        return "today"
    if dd == today + timedelta(days=1):
        return "tomorrow"
    return WEEKDAY_NAME[dd.weekday()]


def _fmt_range(a: str, b: str) -> str:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    fa = f"{da:%b} {da.day}"
    if a == b:
        return fa
    return f"{fa}-{db.day}" if da.month == db.month else f"{fa}-{db:%b} {db.day}"


def analyze(plan: dict[str, Any] | None, cal: dict[str, Any] | None, today: date, *,
            status: dict[str, str] | None = None, dismissed: set[str] | None = None) -> dict[str, Any]:
    """{days: [{date, load, busy_min, free, travel}], recs: [...]} for the next 14 days."""
    if not cal or not cal.get("connected", True):
        return {"days": [], "recs": []}
    busy: dict[str, int] = cal.get("busy") or {}
    blocks: dict[str, list[list[int]]] = cal.get("blocks") or {}
    travel = [t for t in cal.get("travel") or [] if isinstance(t, dict) and t.get("start") and t.get("end")]
    status = status or {}
    dismissed = dismissed or set()
    end = today + timedelta(days=HORIZON - 1)
    dates = [(today + timedelta(days=i)).isoformat() for i in range(HORIZON)]

    def in_trip(d: str) -> dict[str, Any] | None:
        return next((t for t in travel if t["start"] <= d <= t["end"]), None)

    days: list[dict[str, Any]] = []
    load: dict[str, str] = {}
    for d in dates:
        bl = blocks.get(d) or []
        ld = day_load(int(busy.get(d) or 0), bl)
        load[d] = ld
        days.append({"date": d, "load": ld, "busy_min": int(busy.get(d) or 0),
                     "free": [[hhmm(a), hhmm(b)] for a, b in free_windows(bl)][:4],
                     "early": sum(1 for a, _ in bl if a < 9 * 60), "travel": in_trip(d) is not None})

    # Planned work in the window.
    work: dict[str, list[dict[str, Any]]] = {d: [] for d in dates}
    trips_in_plan: list[tuple[str, str]] = []
    if plan:
        for t in plan.get("trips") or []:
            trips_in_plan.append((t.get("start", ""), t.get("end", "")))
        for _, d, s in iter_sessions(plan):
            if d in work and s.get("sport") != "rest" and s.get("kind") != "race" and not s.get("skipped") \
                    and status.get(s.get("id", ""), "planned") not in ("done", "skipped"):
                work[d].append(s)

    def hard(s: dict[str, Any]) -> bool:
        return s.get("kind") in QUALITY

    def longish(s: dict[str, Any]) -> bool:
        return s.get("kind") in LONG_KINDS

    recs: list[dict[str, Any]] = []
    used: set[str] = set()

    # 1. Trips that aren't in travel mode yet, with training on those days.
    for t in travel:
        if t["end"] < today.isoformat() or t["start"] > end.isoformat():
            continue
        covered = any(a and b and a <= t["start"] and t["end"] <= b for a, b in trips_in_plan)
        hit = [d for d in dates if t["start"] <= d <= t["end"] and work[d]]
        if covered or not hit:
            continue
        n = sum(len(work[d]) for d in hit)
        title = (t.get("title") or "Trip").split(" · ")[0][:60]
        rid = _rid("travel", t["start"], t["end"])
        recs.append({"id": rid, "kind": "travel", "date": max(t["start"], today.isoformat()),
                     "title": f"Trip {_fmt_range(t['start'], t['end'])}: turn on Travel mode",
                     "body": f"“{title}” is on your calendar and {n} session{'s' if n != 1 else ''} "
                             "fall on those days. Travel mode swaps them for what you'll have there.",
                     "label": "Set up travel mode",
                     "action": {"type": "travel", "start": max(t["start"], today.isoformat()), "end": t["end"],
                                "name": title}})

    # 2. Per session: meeting overlap, then hard / long on a busy day, then packed or early days.
    def lighter_day(s: dict[str, Any], d: str) -> str | None:
        dd = date.fromisoformat(d)
        mon = dd - timedelta(days=dd.weekday())
        heavy_days = {x for x in dates if any(hard(y) or longish(y) for y in work[x])}
        best = None
        for i in range(7):
            c = (mon + timedelta(days=i)).isoformat()
            if c == d or c <= today.isoformat() or c not in load or in_trip(c):
                continue
            if load[c] not in ("light", "normal") or any(hard(y) or longish(y) for y in work[c]) or len(work[c]) >= 2:
                continue
            nb = {(date.fromisoformat(c) + timedelta(days=o)).isoformat() for o in (-1, 1)}
            if (hard(s) or longish(s)) and (nb & (heavy_days - {d})):
                continue
            if best_slot(free_windows(blocks.get(c) or [], _mins(s)), _mins(s)) is None:
                continue
            key = (0 if load[c] == "light" else 1, abs((date.fromisoformat(c) - dd).days))
            if best is None or key < best[0]:
                best = (key, c)
        return best[1] if best else None

    for d in dates:
        if in_trip(d):
            continue
        bl = blocks.get(d) or []
        for s in work[d]:
            sid = s.get("id")
            if not sid:
                continue
            need = _mins(s)
            st = _start(s)
            wins = free_windows(bl, need)
            name = s.get("title") or "Session"
            # a. The planned start is inside a meeting.
            if st is not None and _overlaps(st, need, bl):
                slot = best_slot(wins, need, prefer=st)
                if slot is not None:
                    recs.append({"id": _rid("time", sid, d, slot), "kind": "time", "date": d, "session_id": sid,
                                 "title": f"{name} {_label(d, today)} clashes with a meeting",
                                 "body": f"Your calendar is busy at {nice_time(st)}. {nice_time(slot)} is free for the "
                                         f"whole {need} min.",
                                 "label": f"Move to {nice_time(slot)}", "action": {"type": "time", "session_id": sid,
                                                                                    "time": hhmm(slot)}})
                    used.add(sid)
                    continue
            # b. Hard or long on a heavy / packed day.
            if load[d] in ("heavy", "packed") and (hard(s) or longish(s)):
                alt = lighter_day(s, d)
                if alt:
                    slot = best_slot(free_windows(blocks.get(alt) or [], need), need, prefer=st)
                    at = f" at {nice_time(slot)}" if slot is not None else ""
                    recs.append({"id": _rid("move", sid, d, alt), "kind": "move", "date": d, "session_id": sid,
                                 "title": f"Move {name} to {_label(alt, today)}{at}",
                                 "body": f"{_label(d, today).capitalize()} is {load[d]} on your calendar "
                                         f"({int(busy.get(d) or 0) // 60} h of meetings); {_label(alt, today)} "
                                         f"is {load[alt]}{' and that time is free' if slot is not None else ''}.",
                                 "label": "Move it", "action": {"type": "move", "session_id": sid, "date": alt,
                                                                "time": hhmm(slot) if slot is not None else None}})
                    used.add(sid)
                    continue
                if not longish(s) and load[d] == "packed":
                    recs.append({"id": _rid("ease", sid, d), "kind": "ease", "date": d, "session_id": sid,
                                 "title": f"Packed day {_label(d, today)}: make {name} a 30-min easy session",
                                 "body": "No lighter day this week has room for it. A short easy session keeps the "
                                         "habit without the stress.",
                                 "label": "Make it easy", "action": {"type": "ease", "session_id": sid,
                                                                     "minutes": min(need, 30)}})
                    used.add(sid)
                    continue
            # c. Packed or early-meeting days without a start time: suggest a free slot.
            if st is None and wins and (load[d] in ("heavy", "packed") or days[dates.index(d)]["early"] >= 2):
                early = days[dates.index(d)]["early"]
                prefer = 12 * 60 if early >= 2 else None
                slot = best_slot(wins, need, prefer=prefer)
                if slot is None:
                    continue
                why = (f"{early} early meetings" if early >= 2 else f"{load[d].capitalize()} day")
                recs.append({"id": _rid("slot", sid, d, slot), "kind": "time", "date": d, "session_id": sid,
                             "title": f"{why} {_label(d, today)}: {name} at {nice_time(slot)}",
                             "body": f"{nice_time(slot)}-{nice_time(slot + need)} is free on your calendar.",
                             "label": f"Set {nice_time(slot)}", "action": {"type": "time", "session_id": sid,
                                                                           "time": hhmm(slot)}})
                used.add(sid)

    # 3. Long sessions keep landing on busy days: suggest a different long day.
    busy_longs = [d for d in dates if any(longish(s) for s in work[d]) and load[d] in ("heavy", "packed")]
    if len(busy_longs) >= 2:
        avg: dict[int, list[int]] = {}
        for d in dates:
            avg.setdefault(date.fromisoformat(d).weekday(), []).append(int(busy.get(d) or 0))
        best = min(avg, key=lambda k: (sum(avg[k]) / len(avg[k]), 0 if k >= 5 else 1, -k))
        recs.append({"id": _rid("long_day", DAYS[best], today.isocalendar()[1]), "kind": "long_day",
                     "date": busy_longs[0],
                     "title": f"Your calendar is lightest on {WEEKDAY_NAME[best]}s",
                     "body": f"Your long sessions land on busy days {len(busy_longs)} times in the next two weeks. "
                             f"Make {WEEKDAY_NAME[best]} your long day?",
                     "label": "Change my long day", "action": {"type": "long_day", "day": DAYS[best]}})

    order = {"travel": 0, "time": 1, "move": 2, "ease": 3, "long_day": 4}
    recs = [r for r in recs if r["id"] not in dismissed]
    recs.sort(key=lambda r: (order.get(r["kind"], 9), r["date"]))
    return {"days": days, "recs": recs[:MAX_RECS]}


def week_hint(result: dict[str, Any], week_start: str) -> str | None:
    """One calendar-aware line for the weekly check-in (next week only)."""
    end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    for r in result.get("recs", []):
        if week_start <= r["date"] <= end:
            return r["title"]
    packed = [d for d in result.get("days", []) if week_start <= d["date"] <= end and d["load"] == "packed"]
    if packed:
        names = ", ".join(WEEKDAY_NAME[date.fromisoformat(d["date"]).weekday()] for d in packed[:3])
        return f"Your calendar is packed on {names}: keep those days short and easy."
    return None


__all__ = ["analyze", "day_load", "free_windows", "best_slot", "week_hint"]
