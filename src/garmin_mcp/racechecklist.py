"""Race checklist: what to do before (and after) a race, on a timeline counted back from race day.

Deterministic. Items depend on the race (road run, trail/ultra, triathlon, cycling, swim, other;
long races get carb-loading and drop-bag items; altitude races get an arrival item) and reuse the
race pack's knowledge: its gear lists (``racepack.GEAR``), its altitude check, the race fueling
target (``nutrition.race_target``) and the athlete's own gear warnings (``gear.for_race``).
Trips and challenges get a shorter list. Item ids are stable slugs, so what someone ticked stays
ticked when the list is rebuilt.

Buckets (days relative to race day; ``due`` is the last day of the window):

    early      12+ weeks out      due race - 57
    build      8 to 3 weeks out   due race - 15
    two_weeks  2 weeks out        due race - 8
    race_week  race week          due race - 2
    eve        the day before     due race - 1
    morning    race morning       due race day
    after      after the race     due race + 7

Per-user state lives in the encrypted ``racechecklist`` doc: ``{event_id: {checked: {item: ts},
hidden: {item: ts}, custom: [{id, text, bucket, created}]}}``.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from .nutrition import race_target
from .racepack import GEAR, RUN, TRI, _altitude

DOC = "racechecklist"
MAX_CUSTOM = 60
MAX_TEXT = 120
# Checklists make sense for these event kinds (races fully; trips and challenges get a short list).
KINDS = ("race", "challenge", "trip")
# (id, label, first day of the window, last day = due), in days relative to race day.
BUCKETS: tuple[tuple[str, str, int | None, int], ...] = (
    ("early", "12+ weeks out", None, -57),
    ("build", "8 to 3 weeks out", -56, -15),
    ("two_weeks", "2 weeks out", -14, -8),
    ("race_week", "Race week", -7, -2),
    ("eve", "The day before", -1, -1),
    ("morning", "Race morning", 0, 0),
    ("after", "After the race", 1, 7),
)
BUCKET_IDS = tuple(b[0] for b in BUCKETS)
LONG_RUN_HOURS = 1.5


class ChecklistError(ValueError):
    """Bad input from the user (shown as a 400)."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def category(event: dict[str, Any]) -> str:
    """tri | ultra | trail | run | bike | swim | trip | other."""
    if event.get("kind") == "trip":
        return "trip"
    etype = (event.get("type") or "other").lower()
    dist = (event.get("distance") or "").lower()
    if etype in ("triathlon", "duathlon") or dist in TRI:
        return "tri"
    if dist == "ultra" or etype == "mountaineering" or re.search(r"\b(ultra|100\s?(mi|mile|k)|50\s?(mi|mile|k))\b",
                                                                  str(event.get("name") or ""), re.I):
        return "ultra"
    if etype == "trail":
        return "trail"
    if etype == "running" or dist in RUN:
        return "run"
    if etype == "cycling":
        return "bike"
    if etype == "swimming":
        return "swim"
    return "other"


def expected_hours(event: dict[str, Any], cat: str) -> float:
    dist = (event.get("distance") or "").lower()
    if dist in TRI:
        return float(TRI[dist][3])
    if dist in RUN:
        return float(RUN[dist][2])
    return {"ultra": 12.0, "bike": 5.0, "trail": 3.0}.get(cat, 2.0)


def _gear_list(cat: str) -> list[str]:
    key = {"tri": "triathlon", "ultra": "trail", "trail": "trail", "run": "running", "bike": "cycling"}.get(cat, "other")
    return list(GEAR.get(key, GEAR["other"]))


def template(event: dict[str, Any], *, gear_warnings: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """[{id, text, bucket, note?}] for this event (stable ids, no dates yet)."""
    cat = category(event)
    hours = expected_hours(event, cat)
    carbs = race_target((event.get("distance") or "other").lower())
    out: list[dict[str, str]] = []

    def add(bucket: str, text: str, note: str = "") -> None:
        item = {"id": f"{bucket}:{_slug(text)}", "text": text, "bucket": bucket}
        if note:
            item["note"] = note
        if all(x["id"] != item["id"] for x in out):
            out.append(item)

    if cat == "trip":
        add("early", "Book travel and a place to stay")
        add("build", "Plan training while you're away", "Turn on Travel mode for those days so the plan fits.")
        add("race_week", "Pack training kit for the trip")
        add("eve", "Charge your watch and phone")
        add("after", "Ease back into your plan")
        return out

    # 12+ weeks out
    add("early", "Register (and save the confirmation)")
    add("early", "Book travel and a place to stay")
    add("early", "Ask for the time off you need")
    if cat == "ultra":
        add("early", "Check the cutoffs and any qualifying or lottery rules")
        add("early", "Line up your crew and pacers")
        add("early", "Read the mandatory kit list")
    if event.get("location") or event.get("name"):
        if _altitude(event):
            add("early", "Plan your altitude arrival",
                "Arrive 2+ weeks early to adapt, or within 24 hours of the start.")

    # 8 to 3 weeks out
    add("build", "Test race-day shoes and kit on a long session")
    if carbs:
        add("build", f"Practise race fueling: about {carbs} g carbs an hour on long sessions",
            "Use exactly the gels and drink you'll race with.")
    add("build", "Learn the course: map, hills, aid stations")
    if cat in ("tri", "bike"):
        add("build", "Get the bike serviced and fitted")
    if cat == "tri":
        add("build", "Practise open-water swimming in your wetsuit")
        add("build", "Rehearse transitions (T1 and T2)")
    if cat in ("ultra", "trail"):
        add("build", "Train with your vest, poles and headlamp")
    if cat == "ultra":
        add("build", "Plan drop bags and what goes in each")
        add("build", "Write a crew sheet: aid stations, times, what you'll need")
    for g in gear_warnings or []:
        if g.get("warning"):
            add("build", f"{g.get('name') or 'Shoes'}: {g['warning']}")

    # 2 weeks out
    add("two_weeks", "Taper: keep sessions short, sleep more")
    add("two_weeks", "Confirm travel, lodging and how you'll get to the start")
    add("two_weeks", "Find packet pickup times and what ID you need")
    add("two_weeks", "Check the long-range forecast and plan layers")

    # Race week: the pack list plus the week's habits
    for g in _gear_list(cat):
        add("race_week", f"Pack: {g}")
    add("race_week", "Pack: ID, race confirmation, payment card")
    add("race_week", "Pack: watch and phone chargers")
    add("race_week", "Pick up your bib and timing chip")
    add("race_week", "Sleep 8+ hours most nights")
    if hours >= LONG_RUN_HOURS:
        add("race_week", "Carb-load the last 2 days (8-10 g per kg body weight)")
    if cat == "tri":
        add("race_week", "Pack transition bags (swim, bike, run)")
    if cat == "ultra":
        add("race_week", "Pack and label drop bags")

    # The day before
    add("eve", "Lay out everything you'll wear and carry")
    add("eve", "Pin your bib (or set up the race belt)")
    add("eve", "Charge your watch, load the course")
    add("eve", "Set two alarms")
    add("eve", "Plan transport and parking for the morning")
    add("eve", "Check the forecast one last time")
    if cat in ("tri", "bike"):
        add("eve", "Rack your bike if the race asks you to")

    # Race morning
    add("morning", f"Breakfast about {3 if hours >= LONG_RUN_HOURS else 2} hours before the start")
    add("morning", "Arrive early: aim for 60-90 minutes before your start")
    add("morning", "Warm up briefly: easy jog and a few pickups")
    add("morning", "Bathroom stop, then head to the start")
    add("morning", "Start slower than you want to")

    # After
    add("after", "Eat and drink within an hour")
    add("after", "Easy days only for a few days")
    add("after", "Log how it went in rabbt (race debrief)")
    add("after", "Thank your crew and support")
    return out


def bucket_window(bucket: str, race_day: date) -> tuple[date | None, date]:
    _, _, start, due = next(b for b in BUCKETS if b[0] == bucket)
    return (race_day + timedelta(days=start) if start is not None else None), race_day + timedelta(days=due)


def current_bucket(race_day: date, today: date) -> str:
    """The window today falls in (before 12 weeks out: early; long after: after)."""
    for bid, _, start, due in BUCKETS:
        if today <= race_day + timedelta(days=due) and (start is None or today >= race_day + timedelta(days=start)):
            return bid
    return "early" if today < race_day else "after"


def view(event: dict[str, Any], state: dict[str, Any] | None, today: date, *,
         gear_warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The checklist for one event: buckets with items (checked, due), counts, hidden items."""
    race_day = date.fromisoformat(event["date"])
    st = state or {}
    checked, hidden = st.get("checked") or {}, st.get("hidden") or {}
    items = template(event, gear_warnings=gear_warnings) + [
        {"id": c["id"], "text": c["text"], "bucket": c["bucket"], "custom": True} for c in st.get("custom") or []]
    cur = current_bucket(race_day, today)
    buckets: list[dict[str, Any]] = []
    hidden_items: list[dict[str, Any]] = []
    for bid, label, _, _ in BUCKETS:
        start, due = bucket_window(bid, race_day)
        rows = []
        for it in items:
            if it["bucket"] != bid:
                continue
            row = dict(it, checked=it["id"] in checked, due=due.isoformat())
            (hidden_items if it["id"] in hidden else rows).append(row)
        buckets.append({"id": bid, "label": label, "start": start.isoformat() if start else None,
                        "due": due.isoformat(), "current": bid == cur,
                        "past": today > due, "done": sum(r["checked"] for r in rows), "total": len(rows), "items": rows})
    total = sum(b["total"] for b in buckets)
    done = sum(b["done"] for b in buckets)
    return {"event": {k: event.get(k) for k in ("id", "name", "date", "kind", "type", "distance", "priority", "location")},
            "days_out": (race_day - today).days, "current": cur, "category": category(event),
            "done": done, "total": total, "buckets": buckets, "hidden": hidden_items}


def summary(v: dict[str, Any]) -> dict[str, Any]:
    """{done, total, window: {id, label, done, total}, next: [2 unchecked items, current window first]}."""
    cur = next(b for b in v["buckets"] if b["current"])
    order = [cur] + [b for b in v["buckets"] if b["past"] and b is not cur] + \
        [b for b in v["buckets"] if not b["past"] and b is not cur]
    nxt = [dict(i, bucket_label=b["label"]) for b in order for i in b["items"] if not i["checked"]][:2]
    return {"event": v["event"], "days_out": v["days_out"], "done": v["done"], "total": v["total"],
            "window": {k: cur[k] for k in ("id", "label", "done", "total", "due")}, "next": nxt}


def applies(event: dict[str, Any]) -> bool:
    return (event.get("kind") or "race") in KINDS and bool(event.get("date"))


class Checklists:
    """Per-user checklist state (encrypted ``racechecklist`` doc)."""

    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, DOC)

    def state(self, uid: str, event_id: str) -> dict[str, Any]:
        return dict((self._doc(uid).load().get(event_id) or {}))

    def act(self, uid: str, event: dict[str, Any], body: dict[str, Any], *,
            gear_warnings: list[dict[str, Any]] | None = None) -> None:
        """check | uncheck | hide | unhide (``item``), add (``text``, ``bucket``), delete (``item``)."""
        action = body.get("action")
        eid = event["id"]
        known = {i["id"] for i in template(event, gear_warnings=gear_warnings)}
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            st = d.setdefault(eid, {})
            custom: list[dict[str, Any]] = st.setdefault("custom", [])
            ids = known | {c["id"] for c in custom}
            item = body.get("item")
            if action in ("check", "uncheck", "hide", "unhide", "delete"):
                if not isinstance(item, str) or item not in ids:
                    raise ChecklistError("That item isn't on this checklist.")
            if action == "check":
                st.setdefault("checked", {})[item] = now
            elif action == "uncheck":
                st.setdefault("checked", {}).pop(item, None)
            elif action == "hide":
                st.setdefault("hidden", {})[item] = now
            elif action == "unhide":
                st.setdefault("hidden", {}).pop(item, None)
            elif action == "delete":
                if not any(c["id"] == item for c in custom):
                    raise ChecklistError("Only items you added can be deleted; hide the others.")
                st["custom"] = [c for c in custom if c["id"] != item]
                st.setdefault("checked", {}).pop(item, None)
            elif action == "add":
                text = body.get("text")
                bucket = body.get("bucket")
                if not isinstance(text, str) or not " ".join(text.split()):
                    raise ChecklistError("Write what you need to do.")
                if bucket not in BUCKET_IDS:
                    raise ChecklistError("Pick when it's due.")
                if len(custom) >= MAX_CUSTOM:
                    raise ChecklistError(f"That's {MAX_CUSTOM} of your own items already.")
                custom.append({"id": f"c:{secrets.token_hex(5)}", "text": " ".join(text.split())[:MAX_TEXT],
                               "bucket": bucket, "created": now})
            else:
                raise ChecklistError("Unknown action.")
        self._doc(uid).update(apply)

    def forget(self, uid: str, event_id: str) -> None:
        self._doc(uid).update(lambda d: d.pop(event_id, None))


__all__ = ["BUCKETS", "BUCKET_IDS", "Checklists", "ChecklistError", "applies", "category", "current_bucket",
           "summary", "template", "view"]
