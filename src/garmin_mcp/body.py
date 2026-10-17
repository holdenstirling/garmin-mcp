"""Body logs the athlete keeps: a fueling & hydration log for long sessions, and a niggle
(ache / small injury) tracker. Both are athlete-entered, stored in encrypted per-user docs,
deterministic (no model call), and never read from Oura.

**Fueling** (``fuel-log`` doc): one entry per planned session or recorded activity (key
``s:<session id>`` or ``a:<activity id>``) with carbs (g, from quick product chips or typed),
fluids (ml), sodium (mg), how often they fuelled, GI comfort and late-session energy.
``learnings`` turns the entries into plain lessons: the carbs/hour band where they felt strong
with a happy gut, where problems start, and how far that is from the race target; the
learned rate also feeds the race pack.

**Niggles** (``niggles`` doc): area, side, pain 0-10, type, which sports it affects, daily
updates (better / same / worse + pain). ``assess`` applies conservative rules:

* **ease** when pain is 4+, the type is sharp, or the last update says worse: the affected
  sport's hard or long sessions over the next few days become easy and shorter (3 days, or
  5 when pain is 6+; at pain 6+ running sessions are swapped to an easy ride or swim when that
  sport isn't affected), proposed as a diff the athlete accepts (``ease_proposal``, same
  id-checked flow as ``adjust``);
* **stop and see a professional** (red flag) when pain is 7+, sharp at 5+, swollen at 5+,
  worse on 3 updates in a row, or still 4+ after 21 days;
* prehab exercises for the area come from ``strength.care_plan``.

Not medical advice: every niggle view carries ``CARE_NOTE``. Active niggles reach Rabbit's
coach context the way the athlete's own injury notes and check-ins do (their own words, as
data); Oura data is never involved.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .planbuilder import KINDS_BY_SPORT, QUALITY, iter_sessions
from .strength import CARE_NOTE, MOBILITY, care_plan

FUEL_DOC = "fuel-log"
NIGGLE_DOC = "niggles"
FUEL_KEEP = 200
NIGGLE_KEEP = 40
UPDATES_KEEP = 60
NOTE_MAX = 300

# Quick chips: typical carbs per item (g). The athlete can edit the grams.
PRODUCTS: dict[str, dict[str, Any]] = {
    "gel": {"label": "Gel", "g": 23},
    "chew": {"label": "Chews (pack)", "g": 24},
    "drink": {"label": "Drink mix (bottle)", "g": 40},
    "bar": {"label": "Bar", "g": 30},
    "banana": {"label": "Banana", "g": 25},
    "food": {"label": "Real food", "g": 20},
}
GI = ("great", "ok", "issues")
ENERGY = ("strong", "faded", "bonked")

AREAS: dict[str, str] = {
    "foot": "Foot", "ankle": "Ankle", "achilles": "Achilles", "calf": "Calf", "shin": "Shin",
    "knee": "Knee", "it_band": "IT band", "hamstring": "Hamstring", "quad": "Quad", "hip": "Hip",
    "glute": "Glute", "lower_back": "Lower back", "shoulder": "Shoulder", "other": "Other",
}
SIDES = ("left", "right", "both", "none")
TYPES = ("ache", "sharp", "tight", "swollen")
SPORTS = ("run", "bike", "swim")
TRENDS = ("better", "same", "worse")

EASE_PAIN = 4
SWAP_PAIN = 6
RED_PAIN = 7
LONG_DAYS = 21


class BodyError(ValueError):
    pass


def _int(v: Any, lo: int, hi: int, name: str, *, required: bool = False) -> int | None:
    if v is None or v == "":
        if required:
            raise BodyError(f"Add {name}.")
        return None
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise BodyError(f"{name.capitalize()} must be a number.")
    n = int(round(v))
    if not lo <= n <= hi:
        raise BodyError(f"{name.capitalize()} must be between {lo} and {hi}.")
    return n


def _enum(v: Any, allowed: tuple[str, ...], name: str, *, required: bool = False) -> str | None:
    if v in (None, ""):
        if required:
            raise BodyError(f"Pick {name}.")
        return None
    if v not in allowed:
        raise BodyError(f"Unknown {name}.")
    return v


def _note(v: Any) -> str:
    return " ".join(str(v or "").split())[:NOTE_MAX]


# ------------------------------------------------------------------ fueling --
def clean_fuel(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a fueling entry; carbs from ``items`` ([{product, count, g?}]) or ``carbs_g``."""
    minutes = _int(body.get("minutes"), 1, 1440, "duration", required=True)
    items_in = body.get("items") or []
    if not isinstance(items_in, list) or len(items_in) > 12:
        raise BodyError("Too many fuel items.")
    items: list[dict[str, Any]] = []
    for it in items_in:
        if not isinstance(it, dict) or it.get("product") not in PRODUCTS:
            raise BodyError("Unknown fuel item.")
        count = _int(it.get("count", 1), 1, 40, "count") or 1
        g = _int(it.get("g", PRODUCTS[it["product"]]["g"]), 0, 150, "grams per item") or 0
        items.append({"product": it["product"], "count": count, "g": g})
    carbs = _int(body.get("carbs_g"), 0, 2000, "carbs")
    if carbs is None:
        carbs = sum(i["count"] * i["g"] for i in items)
    return {
        "minutes": minutes, "items": items, "carbs_g": carbs,
        "fluids_ml": _int(body.get("fluids_ml"), 0, 10000, "fluids"),
        "sodium_mg": _int(body.get("sodium_mg"), 0, 10000, "sodium"),
        "every_min": _int(body.get("every_min"), 5, 120, "how often"),
        "gi": _enum(body.get("gi"), GI, "how your gut felt"),
        "energy": _enum(body.get("energy"), ENERGY, "your energy late on"),
        "note": _note(body.get("note")),
        "sport": _enum(body.get("sport"), ("run", "bike", "swim", "brick", "other"), "sport") or "other",
        "title": _note(body.get("title"))[:80],
        "date": str(body.get("date") or "")[:10],
    }


def rates(e: dict[str, Any]) -> dict[str, int | None]:
    h = (e.get("minutes") or 0) / 60
    if h <= 0:
        return {"g_per_h": None, "ml_per_h": None, "mg_per_h": None}
    per = lambda v: int(round(v / h)) if isinstance(v, int | float) else None  # noqa: E731
    return {"g_per_h": per(e.get("carbs_g")), "ml_per_h": per(e.get("fluids_ml")), "mg_per_h": per(e.get("sodium_mg"))}


def _band(gh: int) -> int:
    return (gh // 15) * 15


def learnings(entries: list[dict[str, Any]], target: int | None, *, sport: str | None = None) -> dict[str, Any]:
    """Plain lessons from logged long sessions (>= 60 min). ``learned_rate`` is the highest
    carbs/hour they've handled well (strong or faded energy, gut great or ok) at least twice,
    or once when it's the only data; None without good sessions."""
    rows = [dict(e, **rates(e)) for e in entries if (e.get("minutes") or 0) >= 60 and rates(e)["g_per_h"] is not None]
    if sport:
        rows = [r for r in rows if r.get("sport") in (sport, "brick")] or rows
    good = [r for r in rows if r.get("gi") in ("great", "ok") and r.get("energy") in ("strong", "faded")]
    strong = [r for r in good if r.get("energy") == "strong"]
    bad_gut = [r for r in rows if r.get("gi") == "issues"]
    bonks = [r for r in rows if r.get("energy") == "bonked"]
    lines: list[str] = []
    learned = None
    if good:
        by_band: dict[int, int] = {}
        for r in good:
            by_band[_band(r["g_per_h"])] = by_band.get(_band(r["g_per_h"]), 0) + 1
        ok_bands = [b for b, n in by_band.items() if n >= 2] or ([max(by_band)] if len(good) == 1 else [])
        if ok_bands:
            learned = max(r["g_per_h"] for r in good if _band(r["g_per_h"]) in ok_bands)
    if strong:
        lo, hi = min(r["g_per_h"] for r in strong), max(r["g_per_h"] for r in strong)
        lines.append(f"You felt **strong** at {lo}-{hi} g/h." if lo != hi else f"You felt **strong** at {lo} g/h.")
    if bad_gut:
        first = min(r["g_per_h"] for r in bad_gut)
        lines.append(f"Your gut had **issues from about {first} g/h**: step up 5-10 g/h at a time, and try a "
                     "different product or more water with it.")
    if bonks:
        top = max(r["g_per_h"] for r in bonks)
        lines.append(f"You **bonked at {top} g/h or less**: start earlier (first 20-30 min) and eat more steadily.")
    if target:
        if learned is None:
            lines.append(f"Race target is **{target} g/h**. Log what you take on your next long session to start learning.")
        elif learned >= target - 5:
            lines.append(f"You've practised your race target of **{target} g/h**. Keep using the same products.")
        else:
            gap = target - learned
            n = 2 if gap <= 15 else 3 if gap <= 30 else 4
            lines.append(f"Race target **{target} g/h**: practise {n} more long sessions, adding 5-10 g/h each time "
                         f"from {learned} g/h.")
    recent = sorted(rows, key=lambda r: r.get("date") or "")[-8:]
    return {"sessions": len(rows), "learned_rate": learned, "target": target, "lines": lines,
            "trend": [{"date": r.get("date"), "title": r.get("title"), "sport": r.get("sport"),
                       "g_per_h": r["g_per_h"], "ml_per_h": r.get("ml_per_h"), "gi": r.get("gi"),
                       "energy": r.get("energy")} for r in recent]}


# ------------------------------------------------------------------ niggles --
def clean_niggle(body: dict[str, Any]) -> dict[str, Any]:
    area = _enum(body.get("area"), tuple(AREAS), "where it hurts", required=True)
    affects = body.get("affects") or []
    if not isinstance(affects, list) or any(a not in SPORTS for a in affects):
        raise BodyError("Unknown sport.")
    return {"area": area, "side": _enum(body.get("side"), SIDES, "a side") or "none",
            "pain": _int(body.get("pain"), 0, 10, "pain", required=True),
            "type": _enum(body.get("type"), TYPES, "what it feels like") or "ache",
            "affects": sorted(set(affects)) or ["run"], "note": _note(body.get("note"))}


def label(n: dict[str, Any]) -> str:
    side = {"left": "Left ", "right": "Right ", "both": "Both "}.get(n.get("side") or "", "")
    area = AREAS.get(n.get("area") or "other", "Other")
    return (side + (area.lower() if side else area)).strip()


def current_pain(n: dict[str, Any]) -> int:
    ups = n.get("updates") or []
    return int(ups[-1]["pain"]) if ups else int(n.get("pain") or 0)


def assess(n: dict[str, Any], today: date) -> dict[str, Any]:
    """{ease, days, swap, red_flag, reasons} for one active niggle (conservative rules)."""
    pain = current_pain(n)
    ups = n.get("updates") or []
    trend = ups[-1]["trend"] if ups else None
    reasons: list[str] = []
    red: list[str] = []
    if pain >= RED_PAIN:
        red.append(f"pain is {pain}/10")
    if n.get("type") == "sharp" and pain >= 5:
        red.append("sharp pain at 5/10 or more")
    if n.get("type") == "swollen" and pain >= 5:
        red.append("swelling with pain at 5/10 or more")
    if len(ups) >= 3 and all(u["trend"] == "worse" for u in ups[-3:]):
        red.append("it's been getting worse 3 updates in a row")
    try:
        age = (today - date.fromisoformat(n["created"][:10])).days
    except (KeyError, ValueError):
        age = 0
    if age >= LONG_DAYS and pain >= EASE_PAIN:
        red.append(f"it's still {pain}/10 after {age} days")
    ease = pain >= EASE_PAIN or n.get("type") == "sharp" or trend == "worse"
    if pain >= EASE_PAIN:
        reasons.append(f"pain {pain}/10")
    if n.get("type") == "sharp":
        reasons.append("sharp")
    if trend == "worse":
        reasons.append("getting worse")
    return {"ease": ease, "days": 5 if pain >= SWAP_PAIN else 3, "swap": pain >= SWAP_PAIN,
            "red_flag": red, "reasons": reasons, "pain": pain, "trend": trend, "age_days": age}


def prehab(area: str) -> list[dict[str, Any]]:
    words = {"it_band": "it band", "lower_back": "lower back", "quad": "knee"}.get(area, area)
    found = care_plan(words)
    if found:
        return [e for c in found for e in c["exercises"]][:4]
    return [{"name": n, "dose": d} for n, d in MOBILITY[:3]]


def needs_update(n: dict[str, Any], today: date) -> bool:
    last = (n.get("updates") or [{}])[-1].get("date") or n.get("created", "")[:10]
    return n.get("status") == "active" and last < today.isoformat()


def _view_session(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ("title", "sport", "kind", "minutes")}


def ease_proposal(plan: dict[str, Any] | None, niggles: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """Changes to the next few days for active niggles that need easing, or None.
    Same change shape as ``adjust.propose`` (plus ``swap_sport``), applied by
    ``PlanService.apply_adjustment`` after the id is checked."""
    if not plan:
        return None
    active = [(n, assess(n, today)) for n in niggles if n.get("status") == "active"]
    active = [(n, a) for n, a in active if a["ease"]]
    if not active:
        return None
    affected = {sp for n, _ in active for sp in n.get("affects") or ["run"]}
    days = max(a["days"] for _, a in active)
    swap = any(a["swap"] for _, a in active)
    end = (today + timedelta(days=days - 1)).isoformat()
    why_bits = sorted({f"{label(n)} ({', '.join(a['reasons'])})" for n, a in active})
    why = "Easing for your " + "; ".join(why_bits) + "."
    alt = next((sp for sp in ("bike", "swim") if sp not in affected), None)
    changes: list[dict[str, Any]] = []
    for _, d, s in iter_sessions(plan):
        hit = s["sport"] in affected or (s["sport"] == "brick" and affected & {"run", "bike"})
        if not (today.isoformat() <= d <= end) or not hit or s.get("kind") == "race":
            continue
        minutes = int(s.get("minutes") or 0)
        if not minutes:
            continue
        short = max(15, int(round(minutes * (0.5 if swap else 0.65) / 5.0) * 5))
        if swap and s["sport"] == "run" and alt:
            kind = "easy" if "easy" in KINDS_BY_SPORT.get(alt, ()) else KINDS_BY_SPORT[alt][0]
            changes.append({"session_id": s["id"], "date": d, "action": "swap_sport", "from": _view_session(s),
                            "to": {"sport": alt, "kind": kind, "minutes": min(short + 10, minutes)},
                            "why": f"{why} An easy {'ride' if alt == 'bike' else 'swim'} keeps your fitness without loading it."})
            continue
        hard = s.get("kind") in QUALITY or s.get("kind") in ("long", "brick")
        if not hard and minutes <= 30:
            continue
        kind = "easy" if "easy" in KINDS_BY_SPORT.get(s["sport"], ()) else s.get("kind")
        changes.append({"session_id": s["id"], "date": d, "action": "ease" if hard and kind != s.get("kind") else "shorten",
                        "from": _view_session(s), "to": {"sport": s["sport"], "kind": kind, "minutes": short},
                        "why": why})
    if not changes:
        return None
    ids = {c["session_id"] for c in changes}
    now = sorted((s["id"], d, s.get("minutes"), s.get("kind"), s["sport"]) for _, d, s in iter_sessions(plan) if s["id"] in ids)
    pid = hashlib.sha256(json.dumps(["niggle", now, changes], sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {"id": pid, "changes": changes, "days": days, "why": why}


def context_lines(niggles: list[dict[str, Any]], today: date) -> list[str]:
    """Active niggles for Rabbit's coach context (the athlete's own entries, as data)."""
    out = []
    for n in niggles:
        if n.get("status") != "active":
            continue
        a = assess(n, today)
        bits = [f"{label(n)}: {a['pain']}/10, {n.get('type') or 'ache'}"]
        if a["trend"]:
            bits.append(a["trend"])
        if n.get("affects"):
            bits.append("affects " + "/".join(n["affects"]))
        if a["red_flag"]:
            bits.append("RED FLAG: suggest seeing a physio/doctor")
        out.append("- " + ", ".join(bits))
    return out[:5]


class BodyStore:
    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time,
                 today: Callable[[str], date] = lambda _uid: date.today()) -> None:
        self._s = store
        self._clock = clock
        self._today = today

    # fueling
    def fuel_entries(self, uid: str) -> list[dict[str, Any]]:
        d = self._s.user_doc(uid, FUEL_DOC).load()
        return sorted((dict(v, key=k) for k, v in (d.get("entries") or {}).items()),
                      key=lambda e: (e.get("date") or "", e.get("ts") or 0), reverse=True)

    def fuel_get(self, uid: str, key: str) -> dict[str, Any] | None:
        e = (self._s.user_doc(uid, FUEL_DOC).load().get("entries") or {}).get(key)
        return dict(e, key=key, **rates(e)) if e else None

    def fuel_save(self, uid: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
        entry = clean_fuel(body)
        entry["date"] = entry["date"] or self._today(uid).isoformat()
        entry["ts"] = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            es = d.setdefault("entries", {})
            es[key] = entry
            if len(es) > FUEL_KEEP:
                for k, _ in sorted(es.items(), key=lambda kv: kv[1].get("ts") or 0)[: len(es) - FUEL_KEEP]:
                    es.pop(k, None)
        self._s.user_doc(uid, FUEL_DOC).update(apply)
        return dict(entry, key=key, **rates(entry))

    def fuel_delete(self, uid: str, key: str) -> None:
        self._s.user_doc(uid, FUEL_DOC).update(lambda d: (d.get("entries") or {}).pop(key, None))

    # niggles
    def niggles(self, uid: str) -> list[dict[str, Any]]:
        d = self._s.user_doc(uid, NIGGLE_DOC).load()
        return sorted((dict(v) for v in (d.get("items") or {}).values()),
                      key=lambda n: (n.get("status") != "active", n.get("created") or ""), reverse=False)

    def niggle(self, uid: str, nid: str) -> dict[str, Any]:
        n = (self._s.user_doc(uid, NIGGLE_DOC).load().get("items") or {}).get(nid)
        if n is None:
            raise KeyError(nid)
        return dict(n)

    def add_niggle(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        n = clean_niggle(body)
        n.update(id="n" + secrets.token_hex(5), status="active",
                 created=self._today(uid).isoformat(), updates=[], resolved=None)

        def apply(d: dict[str, Any]) -> None:
            items = d.setdefault("items", {})
            items[n["id"]] = n
            if len(items) > NIGGLE_KEEP:
                old = sorted((v for v in items.values() if v.get("status") != "active"), key=lambda v: v.get("created") or "")
                for v in old[: len(items) - NIGGLE_KEEP]:
                    items.pop(v["id"], None)
        self._s.user_doc(uid, NIGGLE_DOC).update(apply)
        return n

    def update_niggle(self, uid: str, nid: str, body: dict[str, Any]) -> dict[str, Any]:
        """``{trend, pain, note?}`` adds today's update (replacing an earlier one today);
        ``{resolve: true}`` marks it better; ``{reopen: true}`` brings it back."""
        today = self._today(uid).isoformat()

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            n = (d.get("items") or {}).get(nid)
            if n is None:
                raise KeyError(nid)
            if body.get("resolve") is True:
                n["status"], n["resolved"] = "resolved", today
            elif body.get("reopen") is True:
                n["status"], n["resolved"] = "active", None
            else:
                up = {"date": today, "trend": _enum(body.get("trend"), TRENDS, "better, same or worse", required=True),
                      "pain": _int(body.get("pain"), 0, 10, "pain", required=True), "note": _note(body.get("note"))}
                ups = [u for u in n.get("updates") or [] if u.get("date") != today] + [up]
                n["updates"] = ups[-UPDATES_KEEP:]
            return dict(n)
        return self._s.user_doc(uid, NIGGLE_DOC).update(apply)

    def delete_niggle(self, uid: str, nid: str) -> None:
        self._s.user_doc(uid, NIGGLE_DOC).update(lambda d: (d.get("items") or {}).pop(nid, None))

    def view(self, n: dict[str, Any], today: date) -> dict[str, Any]:
        a = assess(n, today) if n.get("status") == "active" else None
        hist = [{"date": n["created"][:10], "pain": n["pain"]}] + [
            {"date": u["date"], "pain": u["pain"], "trend": u["trend"]} for u in n.get("updates") or []]
        return dict(n, label=label(n), area_label=AREAS.get(n["area"], "Other"), assess=a,
                    needs_update=needs_update(n, today), prehab=prehab(n["area"]), history=hist, care_note=CARE_NOTE)


__all__ = ["AREAS", "BodyError", "BodyStore", "CARE_NOTE", "ENERGY", "GI", "PRODUCTS", "assess", "clean_fuel",
           "clean_niggle", "context_lines", "ease_proposal", "learnings", "prehab", "rates"]
