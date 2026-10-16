"""Race-week mode: the 7 days before an A/B race (or the main event) and race day itself.

Deterministic, no model call. Builds on ``racepack`` (effort targets, weather, gear list),
``predict`` (finish estimate and triathlon splits) and ``gear.for_race``; adds:

* **Window** (``race_week``): the nearest race (kind ``race``) that is the main event or
  priority A/B, 0-7 days out. The Rabbit home swaps in a race-week card.
* **Taper line** (``taper``): "Day 3 of taper: keep it short and sharp" from the plan's
  taper weeks (else the last 7 days).
* **Pacing plan** (``pacing_plan``): a target finish (the athlete's own, else the event's
  goal time, else the estimate) split per leg (triathlon: swim/T1/bike/T2/run, legs scaled
  from the estimate, transitions kept) or per km/mile band (runs, rides), a slightly easy
  first segment, the rest even; the splits add up to the target exactly.
* **Packing list** (``packing_defaults``): defaults by sport and distance + the athlete's own
  race gear, checkable, with custom items, stored per event in the encrypted ``raceweek`` doc.
* **Nutrition** (``nutrition_plan``): carbs/fluids/sodium per hour by expected duration;
  labelled general guidance.
* **Logistics**: start time, address, and reminders the athlete adds.
* **Tracking** (``RaceWeek.track``): an opt-in "Track me" toggle. Mutual followers (both
  follow each other, no block either way, athletes only) see not started / racing (elapsed
  since the planned start) / finished (the Garmin result once it syncs). There is no live
  location: the copy says "Live times when your watch syncs". Optional pushes to those
  friends at the planned start and when the finish syncs, never in the friend's quiet hours.
* **Moments** (``moment_due``): T-7 "Race week! Here's your plan" (replaces the generic
  race-week countdown), T-2 packing reminder, T-1 evening "lay out your kit" (replaces the
  morning race-eve line), race morning good luck. They go through ``Moments.post`` (dedupe,
  quiet hours queue, daily cap, push cap, ``moments_push``).

Never reads Oura; nothing here goes into Rabbit's context.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Callable
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from .appstore import AppStore
from .gear import for_race
from .logs import log_event
from .planbuilder import iter_sessions
from .racepack import GEAR, pacing as effort_targets

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
KM_MI = 1.609344
MAX_CUSTOM = 30
MAX_REMINDERS = 20
ITEM_CHARS = 80
START_EASY = 0.02          # first segment this much slower than even pace
BAND = 0.02                # +- around the target pace
MAX_ROWS = 14
TRACK_DAYS_AFTER = 1       # a finished race stays visible to friends the day after
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class RaceWeekError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- window --
def is_race(ev: dict[str, Any] | None) -> bool:
    return (ev or {}).get("kind") in (None, "", "race")


def eligible(ev: dict[str, Any]) -> bool:
    """A race that gets race-week mode: the main event or an A/B race."""
    return is_race(ev) and (bool(ev.get("main")) or ev.get("priority") in ("A", "B"))


def days_to(ev: dict[str, Any], today: date) -> int | None:
    try:
        return (date.fromisoformat(str(ev.get("date"))[:10]) - today).days
    except ValueError:
        return None


def race_week(events: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """The race whose week it is: nearest eligible race 0-7 days out (the main event wins a
    tie). ``{"event", "days"}`` or None."""
    best: tuple[int, int, dict[str, Any]] | None = None
    for ev in events or []:
        n = days_to(ev, today)
        if n is None or not 0 <= n <= WINDOW_DAYS or not eligible(ev):
            continue
        cand = (n, 0 if ev.get("main") else 1, ev)
        if best is None or cand[:2] < best[:2]:
            best = cand
    return {"event": best[2], "days": best[0]} if best else None


def taper(plan: dict[str, Any] | None, race_day: date, today: date) -> dict[str, Any]:
    """``{"day", "of", "text"}``: which day of the taper today is, with one line of advice."""
    days = (race_day - today).days
    start = race_day - timedelta(days=WINDOW_DAYS)
    for w in (plan or {}).get("weeks") or []:
        if w.get("phase") == "taper":
            try:
                ws = date.fromisoformat(w["start"])
            except (KeyError, ValueError):
                continue
            if ws < race_day:
                start = min(start, ws)
    total = (race_day - start).days
    n = max(1, min(total, (today - start).days + 1))
    if days <= 0:
        return {"day": total, "of": total, "text": "Race day. The work is done: start easy, fuel early, enjoy it."}
    if days == 1:
        line = "keep it to a short shakeout and lay out your kit"
    elif days == 2:
        line = "easy and short, carbs up, feet up"
    elif days <= 4:
        line = "keep it short and sharp"
    else:
        line = "less volume, a little intensity, lots of sleep"
    return {"day": n, "of": total, "text": f"Day {n} of taper: {line}."}


def today_sessions(plan: dict[str, Any] | None, today: date) -> list[dict[str, Any]]:
    out = []
    for _, d, s in iter_sessions(plan or {}):
        if d == today.isoformat() and s.get("sport") != "rest":
            out.append({"id": s.get("id"), "title": s.get("title") or "Session", "minutes": s.get("minutes"),
                        "sport": s.get("sport")})
    return out


# --------------------------------------------------------------- pacing --
def fmt_hms(s: float) -> str:
    s = int(round(max(0.0, s)))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_pace(sec_per_unit: float, unit: str) -> str:
    s = int(round(sec_per_unit))
    return f"{s // 60}:{s % 60:02d}/{unit}"


def parse_target(text: Any, ref_s: float | None = None) -> int | None:
    """"4:30" / "4:30:00" / "22:30" -> seconds. Two parts are h:mm or m:ss, whichever is
    nearer the reference (the estimate), else h:mm when it's at least 1 hour long."""
    m = re.match(r"^\s*(\d{1,2}):([0-5]\d)(?::([0-5]\d))?\s*$", str(text or ""))
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
    if c is not None:
        return a * 3600 + b * 60 + int(c)
    hm, ms = a * 3600 + b * 60, a * 60 + b
    if ref_s and ref_s > 0:
        import math
        return hm if abs(math.log(max(hm, 1) / ref_s)) <= abs(math.log(max(ms, 1) / ref_s)) else ms
    return hm if a <= 9 else ms


def _step(units: float) -> float:
    for st in (1.0, 2.0, 5.0, 10.0, 20.0, 25.0, 50.0):
        if units / st <= MAX_ROWS:
            return st
    return units / MAX_ROWS


def splits(total_s: float, km: float, *, imperial: bool, mode: str = "pace") -> dict[str, Any]:
    """Even splits per km (or mile) band for ``total_s`` over ``km``. The first segment runs
    ``START_EASY`` slower; the rest share the difference, so the last cumulative time is the
    target exactly. ``mode``: ``pace`` (runs) or ``speed`` (rides)."""
    unit, f = ("mi", KM_MI) if imperial else ("km", 1.0)
    units = km / f
    if total_s <= 0 or units <= 0:
        return {"unit": unit, "step": 0, "rows": [], "pace_s": None}
    step = _step(units)
    marks: list[float] = []
    x = step
    while x < units - 1e-6:
        marks.append(round(x, 3))
        x += step
    marks.append(round(units, 3))
    even = total_s / units
    lens = [marks[0]] + [marks[i] - marks[i - 1] for i in range(1, len(marks))]
    if len(lens) > 1:
        first = even * (1 + START_EASY)
        rest_units = units - lens[0]
        rest = (total_s - first * lens[0]) / rest_units
        paces = [first] + [rest] * (len(lens) - 1)
    else:
        paces = [even]
    rows, cum = [], 0.0
    for i, (mk, ln, p) in enumerate(zip(marks, lens, paces)):
        seg = p * ln
        cum = total_s if i == len(marks) - 1 else cum + seg
        row = {"at": round(mk, 2), "label": f"{mk:g} {unit}" if i < len(marks) - 1 else "Finish",
               "split_s": round(seg), "cum_s": round(cum), "cum": fmt_hms(cum)}
        if mode == "speed":
            row["speed"] = f"{3600 / p:.1f} {'mph' if imperial else 'km/h'}"
        else:
            row["pace"] = fmt_pace(p, unit)
        rows.append(row)
    out: dict[str, Any] = {"unit": unit, "step": step, "rows": rows, "pace_s": round(even, 1)}
    if mode == "speed":
        out["speed"] = f"{3600 / even:.1f} {'mph' if imperial else 'km/h'}"
    else:
        out["pace"] = fmt_pace(even, unit)
        out["band"] = f"{fmt_pace(even * (1 - BAND), unit)}–{fmt_pace(even * (1 + BAND), unit)}".replace(f"/{unit}–", "–")
    return out


def tri_splits(total_s: float, est_splits: list[dict[str, Any]], legs_km: tuple[float, float, float],
               *, imperial: bool) -> list[dict[str, Any]]:
    """Scale the estimate's swim/bike/run to ``total_s`` (transitions kept as estimated)."""
    by = {s["leg"]: float(s["mid_s"]) for s in est_splits}
    t = by.get("t1", 0.0) + by.get("t2", 0.0)
    moving = sum(by.get(k, 0.0) for k in ("swim", "bike", "run"))
    if moving <= 0:
        return []
    f = max(0.3, (total_s - t) / moving)
    swim_km, bike_km, run_km = legs_km
    unit = "mi" if imperial else "km"
    rows, cum = [], 0.0
    order = [("swim", "Swim"), ("t1", "T1"), ("bike", "Bike"), ("t2", "T2"), ("run", "Run")]
    for i, (k, label) in enumerate(order):
        s = by.get(k, 0.0) * (1 if k in ("t1", "t2") else f)
        cum = total_s if i == len(order) - 1 else cum + s
        if i == len(order) - 1:
            s = total_s - sum(r["s"] for r in rows)
        row: dict[str, Any] = {"leg": k, "label": label, "s": round(s), "time": fmt_hms(s), "cum": fmt_hms(cum)}
        if k == "swim" and swim_km:
            row["pace"] = f"{fmt_pace(s / (swim_km * 10), '100m')}"
        elif k == "bike" and bike_km and s > 0:
            kmh = bike_km / (s / 3600)
            row["pace"] = f"{kmh / (KM_MI if imperial else 1):.1f} {'mph' if imperial else 'km/h'}"
        elif k == "run" and run_km and s > 0:
            row["pace"] = fmt_pace(s / (run_km / (KM_MI if imperial else 1)), unit)
        rows.append(row)
    return rows


def pacing_plan(event: dict[str, Any], athlete: dict[str, Any], estimate: dict[str, Any] | None,
                inputs: dict[str, Any], saved_target: int | None) -> dict[str, Any]:
    """Target + splits. ``estimate``: ``predict.predict_event`` output (or None);
    ``inputs``: ``predict.event_inputs(event)["kwargs"]``."""
    from .predict import TRI
    imperial = athlete.get("units") == "imperial"
    est_mid = ((estimate or {}).get("estimate") or {}).get("mid_s")
    goal = parse_target(event.get("target_time"), est_mid)
    if saved_target:
        target, source = int(saved_target), "you"
    elif goal:
        target, source = goal, "goal"
    elif est_mid:
        target, source = int(est_mid), "estimate"
    else:
        target, source = None, None
    out: dict[str, Any] = {"target_s": target, "target": fmt_hms(target) if target else None, "source": source,
                           "estimate": ({"low_s": estimate["estimate"]["low_s"], "mid_s": est_mid,
                                         "high_s": estimate["estimate"]["high_s"], "text": estimate.get("text"),
                                         "confidence": estimate.get("confidence")} if est_mid else None),
                           "goal_s": goal, "mode": None, "legs": [], "splits": None, "notes": [],
                           "effort": effort_targets(event, athlete)}
    km = inputs.get("distance_km")
    tri = inputs.get("tri")
    etype = str(event.get("type") or "").lower()
    climb = inputs.get("climb_m") or 0
    if target and tri and (estimate or {}).get("splits"):
        sw, bk, rn = TRI[tri][0], TRI[tri][1], TRI[tri][2]
        out["mode"] = "tri"
        out["legs"] = tri_splits(target, estimate["splits"], (sw, bk, rn), imperial=imperial)
        out["notes"].append("Legs scale with your target; transitions stay as estimated.")
    elif target and km:
        mode = "speed" if etype == "cycling" else "pace"
        out["mode"] = mode
        out["splits"] = splits(target, float(km), imperial=imperial, mode=mode)
        out["notes"].append("First segment a touch easy, then even. Bank nothing early.")
    if climb and km and climb / max(km, 1) >= 10:
        out["notes"].append("Hilly course: go by effort on the climbs. Splits are averages, so expect slow uphill "
                            "segments and quick downhill ones.")
    if source == "estimate":
        out["notes"].append("Target = your estimated finish. Set your own if you have one.")
    return out


# -------------------------------------------------------------- packing --
EXTRA = {
    "5k": [], "10k": [],
    "half marathon": ["Gels: 2-3 you've trained with"],
    "marathon": ["Gels/chews for the whole race (one every 30-40 min)", "Blister plasters, tape"],
    "ultra": ["Spare socks in a drop bag", "Cup for aid stations (many ultras are cupless)"],
    "70.3": ["Bike bottles mixed the night before", "Bike computer charged"],
    "140.6": ["Special-needs bags (bike and run)", "Bike bottles mixed the night before", "Bike computer charged",
              "Lights or reflective layer for a late run"],
    "century ride": ["Saddle bag with spares", "Cash/card for stops"],
}
BEFORE_AFTER = ["Race confirmation + ID", "Phone charged", "Breakfast you've tested", "Warm clothes for after",
                "Recovery drink or snack", "Plastic bag for wet kit"]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def packing_defaults(event: dict[str, Any], gear_views: list[dict[str, Any]] | None = None,
                     *, imperial: bool = False) -> list[dict[str, Any]]:
    """Default packing list: race kit by sport (``racepack.GEAR``) + extras by distance +
    before/after basics + the athlete's own race gear. Stable ids (slug of the text)."""
    etype = str(event.get("type") or "other")
    dist = str(event.get("distance") or "").lower()
    base = GEAR.get(etype if etype in GEAR else ("trail" if etype == "mountaineering" else "other"), GEAR["other"])
    if etype in ("running",) and dist in ("5k", "10k"):
        base = [x for x in base if not x.lower().startswith("gels")]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(text: str, group: str, id_: str | None = None) -> None:
        i = id_ or slug(text)
        if i and i not in seen:
            seen.add(i)
            out.append({"id": i, "text": text, "group": group})
    for g in for_race(gear_views or [], etype, imperial=imperial):
        add(f"{g['name']}" + (f" ({g['nickname']})" if g.get("nickname") and g["nickname"] != g["name"] else ""),
            "Your gear", f"gear-{g['id']}")
    for x in base:
        add(x, "Race kit")
    for x in EXTRA.get(dist, []):
        add(x, "Race kit")
    for x in BEFORE_AFTER:
        add(x, "Before and after")
    return out


def packing_view(defaults: list[dict[str, Any]], saved: dict[str, Any] | None) -> dict[str, Any]:
    s = saved or {}
    checked = set(s.get("checked") or [])
    items = [dict(x, done=x["id"] in checked, custom=False) for x in defaults]
    items += [{"id": c["id"], "text": c["text"], "group": "Yours", "done": c["id"] in checked, "custom": True}
              for c in s.get("custom") or []]
    return {"items": items, "done": sum(1 for x in items if x["done"]), "total": len(items)}


# ------------------------------------------------------------ nutrition --
def nutrition_plan(hours: float | None, *, hot: bool = False, weight_kg: float | None = None) -> dict[str, Any]:
    """General race-day fueling by expected duration (no product advice)."""
    h = max(0.0, float(hours or 0))
    if h < 1:
        lo, hi = 0, 0
    elif h < 2.5:
        lo, hi = 30, 60
    else:
        lo, hi = 60, 90
    fl = (600, 1000) if hot else (400, 800)
    na = (500, 1000) if hot else (300, 600)
    steps: list[str] = []
    if h >= 1.5:
        steps.append("Two days out: carb-heavy meals" + (f" (about {int(weight_kg * 8)}-{int(weight_kg * 10)} g carbs a day)"
                                                          if weight_kg else " (8-10 g per kg a day)") + ", low fibre.")
    steps.append("Breakfast 2-4 hours before: familiar, carb-rich, low fat and fibre"
                 + (f" (about {int(weight_kg)}-{int(weight_kg * 3)} g carbs)." if weight_kg else "."))
    if hi:
        per = round((lo + hi) / 2 / 3)
        steps.append(f"During: start in the first 20-30 minutes, then about {per} g carbs every 20 minutes.")
        if hi >= 90:
            steps.append("Only go above 60 g/h if you've practised it in training.")
    else:
        steps.append("During: water to thirst is enough for under an hour.")
    if hot:
        steps.append("Hot day: drink a little more, add salt, and slow your target.")
    return {"hours": round(h, 2), "carbs_g_per_h": [lo, hi], "fluid_ml_per_h": list(fl), "sodium_mg_per_h": list(na),
            "total_carbs_g": [int(lo * h), int(hi * h)], "steps": steps,
            "label": "General guidance, not medical advice. Use only what you've trained with."}


# -------------------------------------------------------------- tracking --
def start_time(event: dict[str, Any], saved: dict[str, Any] | None) -> str | None:
    for v in ((saved or {}).get("start_time"), event.get("time"), (event.get("info") or {}).get("start_time")):
        m = _HHMM.match(str(v or "").strip())
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        m2 = re.search(r"\b(\d{1,2}):([0-5]\d)\s*([ap])\.?m\b", str(v or ""), re.I)
        if m2:
            hh = int(m2.group(1)) % 12 + (12 if m2.group(3).lower() == "p" else 0)
            return f"{hh:02d}:{m2.group(2)}"
    return None


def _dur_s(v: Any) -> float:
    if isinstance(v, int | float):
        return float(v)
    parts = str(v or "").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    s = 0.0
    for n in nums:
        s = s * 60 + n
    return s


def race_result(acts: list[dict[str, Any]], race_day: date, start: str | None) -> dict[str, Any] | None:
    """The race's Garmin activity: on race day, from 2 h before the planned start, a race-tagged
    one first, else the longest (multisport legs skipped). Compact activity rows."""
    day = race_day.isoformat()
    earliest = None
    if start:
        hh, mm = (int(x) for x in start.split(":"))
        earliest = (datetime.combine(race_day, dtime(hh, mm)) - timedelta(hours=2)).strftime("%H:%M")
    cands = []
    for a in acts or []:
        when = str(a.get("date") or "")
        if when[:10] != day or (a.get("multisport") or {}).get("parent_id"):
            continue
        if earliest and when[11:16] and when[11:16] < earliest:
            continue
        cands.append(a)
    if not cands:
        return None
    a = max(cands, key=lambda x: (x.get("event") == "race", _dur_s(x.get("duration"))))
    secs = _dur_s(a.get("duration"))
    if secs < 600:
        return None
    return {"activity_id": a.get("activity_id"), "name": str(a.get("name") or "")[:60], "duration_s": round(secs),
            "time": fmt_hms(secs), "distance_km": a.get("distance_km")}


def status(event: dict[str, Any], saved: dict[str, Any] | None, now: datetime,
           acts: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Race status at the athlete's local ``now``: ``not_started`` / ``racing`` / ``finished``
    (``race_day`` when no start time is known), plus the planned start and elapsed seconds."""
    local = now.replace(tzinfo=None)
    race_day = date.fromisoformat(str(event["date"])[:10])
    st = start_time(event, saved)
    res = race_result(acts or [], race_day, st) if local.date() >= race_day else None
    out: dict[str, Any] = {"start": st, "elapsed_s": None, "result": res, "date": race_day.isoformat()}
    if res:
        return {**out, "state": "finished"}
    if local.date() != race_day:
        return {**out, "state": "not_started" if local.date() < race_day else "no_result"}
    if not st:
        return {**out, "state": "race_day"}
    hh, mm = (int(x) for x in st.split(":"))
    begin = datetime.combine(race_day, dtime(hh, mm))
    if local < begin:
        return {**out, "state": "not_started"}
    return {**out, "state": "racing", "elapsed_s": int((local - begin).total_seconds())}


def track_visible(viewer: str, owner: str, *, follows: Callable[[str, str], bool],
                  blocked: Callable[[str, str], bool]) -> bool:
    """Mutual followers only (both directions active), never coaches, never across a block."""
    if viewer == owner or viewer.startswith("coach_") or owner.startswith("coach_"):
        return False
    return follows(viewer, owner) and follows(owner, viewer) and not blocked(viewer, owner)


# --------------------------------------------------------------- moments --
FROM = {"week": dtime(8, 0), "pack": dtime(8, 0), "kit": dtime(18, 0), "go": dtime(7, 0)}
UNTIL_GO = dtime(12, 0)


def moment_due(days: int, t: dtime) -> str | None:
    """Which race-week moment is due ``days`` before the race at local time ``t``."""
    if 5 <= days <= 7 and t >= FROM["week"]:
        return "week"
    if days == 2 and t >= FROM["pack"]:
        return "pack"
    if days == 1 and t >= FROM["kit"]:
        return "kit"
    if days == 0 and FROM["go"] <= t < UNTIL_GO:
        return "go"
    return None


def _name(ev: dict[str, Any]) -> str:
    s = re.sub(r"\s+", " ", str(ev.get("name") or "your race")).strip()
    return s if len(s) <= 40 else s[:39].rstrip() + "…"


def week_moment(step: str, ev: dict[str, Any], days: int, packing: tuple[int, int] | None = None) -> dict[str, Any]:
    """Moments use type ``race`` (pushed like the countdown, same caps). The ``week`` and
    ``kit`` keys are the countdown's ``race:<id>:week|eve`` keys, so the two never double up."""
    eid, name = ev.get("id"), _name(ev)
    act = [{"id": "raceweek", "label": "Race-week plan", "event_id": eid}]
    if step == "week":
        return {"type": "race", "key": f"race:{eid}:week", "push_title": "Race week",
                "text": f"🏁 Race week! {name} in {days} days. Here's your plan: pacing, packing, fuel.", "actions": act}
    if step == "pack":
        done, total = packing or (0, 0)
        tail = f" {done}/{total} packed so far." if total else ""
        return {"type": "race", "key": f"race:{eid}:pack", "push_title": "Time to pack",
                "text": f"🎒 {name} in 2 days. Pack today so tomorrow stays calm.{tail}",
                "actions": [{"id": "raceweek", "label": "Packing list", "event_id": eid, "section": "packing"}]}
    if step == "kit":
        return {"type": "race", "key": f"race:{eid}:eve", "push_title": "Race eve",
                "text": f"🎽 {name} is tomorrow. Lay out your kit tonight, set two alarms, early night.", "actions": act}
    return {"type": "race", "key": f"race:{eid}:go", "push_title": "Race day",
            "text": f"🍀 Race day! Good luck at {name}. Start easier than you want to and fuel early.", "actions": act}


# --------------------------------------------------------------- service --
class RaceWeek:
    """Per-user race-week state in the encrypted ``raceweek`` doc, keyed by event id::

        {"events": {eid: {"target_s", "start_time", "tracking", "notify_friends",
                          "packing": {"checked": [...], "custom": [{id, text}]},
                          "reminders": [{id, text, when, done}],
                          "notified": {"start": bool, "finish": activity_id}}}}
    """

    def __init__(self, store: AppStore, *, events: Callable[[str], list[dict[str, Any]]],
                 now: Callable[[str], datetime], follows: Callable[[str, str], bool],
                 blocked: Callable[[str, str], bool], is_athlete: Callable[[str], bool],
                 followers: Callable[[str], list[str]], activities: Callable[[str], list[dict[str, Any]]] | None = None,
                 push: Callable[[str, str, str, str], None] | None = None,
                 quiet: Callable[[str], bool] | None = None, name: Callable[[str], str] = lambda u: "Your friend") -> None:
        self._s = store
        self._events = events
        self._now = now
        self._follows = follows
        self._blocked = blocked
        self._is_athlete = is_athlete
        self._followers = followers
        self._acts = activities
        self._push = push
        self._quiet = quiet
        self._name = name

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "raceweek")

    def saved(self, uid: str, eid: str) -> dict[str, Any]:
        return dict((self._doc(uid).load().get("events") or {}).get(eid) or {})

    def event(self, uid: str, eid: Any) -> dict[str, Any]:
        if uid.startswith("coach_"):
            raise RaceWeekError("Race week is for athletes.", 403)
        ev = next((e for e in self._events(uid) if e.get("id") == eid), None) if isinstance(eid, str) else None
        if ev is None:
            raise RaceWeekError("event not found", 404)
        if not is_race(ev):
            raise RaceWeekError("Race week is for races.")
        return ev

    def _edit(self, uid: str, eid: str, fn: Callable[[dict[str, Any]], Any]) -> Any:
        def apply(d: dict[str, Any]) -> Any:
            evs = d.setdefault("events", {})
            r = evs.setdefault(eid, {})
            out = fn(r)
            if len(evs) > 40:  # oldest dropped
                for k in list(evs)[: len(evs) - 40]:
                    del evs[k]
            return out
        return self._doc(uid).update(apply)

    # ------------------------------------------------------------ settings --
    def put(self, uid: str, eid: str, patch: Any) -> dict[str, Any]:
        self.event(uid, eid)
        if not isinstance(patch, dict):
            raise RaceWeekError("body")
        clean: dict[str, Any] = {}
        for k, v in patch.items():
            if k == "target_s":
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 300 <= v <= 72 * 3600):
                    raise RaceWeekError("target must be between 5 minutes and 72 hours")
                clean[k] = v
            elif k == "start_time":
                if v not in (None, "") and not (isinstance(v, str) and _HHMM.match(v)):
                    raise RaceWeekError("start time must be HH:MM")
                clean[k] = v or None
            elif k in ("tracking", "notify_friends"):
                if not isinstance(v, bool):
                    raise RaceWeekError(f"{k} must be true or false")
                clean[k] = v
            else:
                raise RaceWeekError(f"unknown field {k}")

        def apply(r: dict[str, Any]) -> dict[str, Any]:
            r.update(clean)
            if clean.get("tracking") is False:
                r["notify_friends"] = False
            return dict(r)
        return self._edit(uid, eid, apply)

    def packing(self, uid: str, eid: str, body: Any, defaults: list[dict[str, Any]]) -> dict[str, Any]:
        """``{"toggle": id}`` | ``{"add": text}`` | ``{"remove": id}`` (custom items only)."""
        self.event(uid, eid)
        if not isinstance(body, dict) or len(body) != 1:
            raise RaceWeekError("body")
        ids = {x["id"] for x in defaults}

        def apply(r: dict[str, Any]) -> dict[str, Any]:
            p = r.setdefault("packing", {})
            checked: list[str] = p.setdefault("checked", [])
            custom: list[dict[str, Any]] = p.setdefault("custom", [])
            mine = {c["id"] for c in custom}
            if "toggle" in body:
                i = body["toggle"]
                if i not in ids and i not in mine:
                    raise RaceWeekError("item not found", 404)
                if i in checked:
                    checked.remove(i)
                else:
                    checked.append(i)
            elif "add" in body:
                text = re.sub(r"\s+", " ", str(body["add"] or "")).strip()[:ITEM_CHARS]
                if not text:
                    raise RaceWeekError("add some text")
                if len(custom) >= MAX_CUSTOM:
                    raise RaceWeekError(f"up to {MAX_CUSTOM} of your own items")
                custom.append({"id": "c" + secrets.token_hex(4), "text": text})
            elif "remove" in body:
                i = body["remove"]
                if i not in mine:
                    raise RaceWeekError("only your own items can be removed", 404)
                p["custom"] = [c for c in custom if c["id"] != i]
                p["checked"] = [c for c in checked if c != i]
            else:
                raise RaceWeekError("body")
            return dict(p)
        saved = self._edit(uid, eid, apply)
        return packing_view(defaults, saved)

    def reminders(self, uid: str, eid: str, body: Any) -> list[dict[str, Any]]:
        """``{"add": {"text", "when"?}}`` | ``{"toggle": id}`` | ``{"remove": id}``."""
        self.event(uid, eid)
        if not isinstance(body, dict) or len(body) != 1:
            raise RaceWeekError("body")

        def apply(r: dict[str, Any]) -> list[dict[str, Any]]:
            rs: list[dict[str, Any]] = r.setdefault("reminders", [])
            if "add" in body:
                a = body["add"] if isinstance(body["add"], dict) else {"text": body["add"]}
                text = re.sub(r"\s+", " ", str(a.get("text") or "")).strip()[:ITEM_CHARS]
                when = str(a.get("when") or "").strip()[:20]
                if not text:
                    raise RaceWeekError("add some text")
                if when and not re.match(r"^\d{4}-\d{2}-\d{2}( ([01]\d|2[0-3]):[0-5]\d)?$", when):
                    raise RaceWeekError("when must be YYYY-MM-DD or YYYY-MM-DD HH:MM")
                if len(rs) >= MAX_REMINDERS:
                    raise RaceWeekError(f"up to {MAX_REMINDERS} reminders")
                rs.append({"id": "r" + secrets.token_hex(4), "text": text, "when": when or None, "done": False})
            elif "toggle" in body or "remove" in body:
                i = body.get("toggle") or body.get("remove")
                hit = next((x for x in rs if x["id"] == i), None)
                if hit is None:
                    raise RaceWeekError("reminder not found", 404)
                if "toggle" in body:
                    hit["done"] = not hit["done"]
                else:
                    rs.remove(hit)
            else:
                raise RaceWeekError("body")
            return sorted((dict(x) for x in rs), key=lambda x: (x["when"] or "9999", x["id"]))
        return self._edit(uid, eid, apply)

    # ------------------------------------------------------------ tracking --
    def _tracked_race(self, owner: str, today: date) -> dict[str, Any] | None:
        """The owner's race with tracking on, today (or finished yesterday)."""
        saved = (self._doc(owner).load().get("events") or {})
        for ev in self._events(owner):
            n = days_to(ev, today)
            if n is None or not -TRACK_DAYS_AFTER <= n <= 0 or not is_race(ev):
                continue
            if (saved.get(ev.get("id")) or {}).get("tracking"):
                return ev
        return None

    def _acts_of(self, uid: str) -> list[dict[str, Any]]:
        if self._acts is None:
            return []
        try:
            return self._acts(uid)
        except Exception:  # Garmin busy: status without a result
            return []

    def track(self, viewer: str, owner: str) -> dict[str, Any]:
        """A friend's race status for ``viewer``. 403 unless they're mutual followers."""
        if viewer.startswith("coach_") or not self._is_athlete(viewer):
            raise RaceWeekError("Race tracking is for athletes.", 403)
        if not self._is_athlete(owner) or not track_visible(viewer, owner, follows=self._follows,
                                                             blocked=self._blocked):
            raise RaceWeekError("Only friends who follow each other can follow a race.", 403)
        now = self._now(owner)
        ev = self._tracked_race(owner, now.date())
        if ev is None:
            raise RaceWeekError("Not racing today.", 404)
        return self._track_row(owner, ev, now)

    def _track_row(self, owner: str, ev: dict[str, Any], now: datetime) -> dict[str, Any]:
        st = status(ev, self.saved(owner, ev["id"]), now, self._acts_of(owner))
        return {"user_id": owner, "event": {"id": ev["id"], "name": str(ev.get("name") or "Race")[:80],
                                            "distance": ev.get("distance") or "", "type": ev.get("type") or ""},
                **st, "note": "Live times when their watch syncs. No live location."}

    def friends_racing(self, viewer: str) -> list[dict[str, Any]]:
        """Mutual friends with tracking on who race today (or finished yesterday)."""
        if viewer.startswith("coach_") or not self._is_athlete(viewer):
            raise RaceWeekError("Race tracking is for athletes.", 403)
        out = []
        for f in self._followers(viewer)[:200]:
            if not track_visible(viewer, f, follows=self._follows, blocked=self._blocked):
                continue
            now = self._now(f)
            ev = self._tracked_race(f, now.date())
            if ev is not None:
                out.append(self._track_row(f, ev, now))
        order = {"racing": 0, "not_started": 1, "race_day": 1, "finished": 2, "no_result": 3}
        out.sort(key=lambda r: (order.get(r["state"], 4), r["event"]["name"]))
        return out

    def audience(self, owner: str) -> list[str]:
        """Who gets the start/finish pushes: mutual followers, no blocks."""
        return [f for f in self._followers(owner)
                if track_visible(f, owner, follows=self._follows, blocked=self._blocked)]

    def _notify(self, owner: str, ev: dict[str, Any], what: str, body: str) -> int:
        if self._push is None:
            return 0
        n = 0
        for f in self.audience(owner):
            if self._quiet is not None and self._quiet(f):
                continue  # respect the friend's quiet hours: no queue for live news
            try:
                self._push(f, "Race day" if what == "start" else "Race finished", body[:140], "/app/?open=raceweek")
                n += 1
            except Exception as e:  # best effort
                log_event(logger, logging.WARNING, "raceweek_push_failed", error=type(e).__name__)
        return n

    def check_start(self, owner: str) -> str:
        """From ``Moments.on_tick``: push mutual friends once at the planned start."""
        if owner.startswith("coach_"):
            return "skipped"
        now = self._now(owner)
        ev = self._tracked_race(owner, now.date())
        if ev is None or days_to(ev, now.date()) != 0:
            return "none"
        saved = self.saved(owner, ev["id"])
        if not saved.get("notify_friends") or (saved.get("notified") or {}).get("start"):
            return "off"
        st = status(ev, saved, now, None)
        if st["state"] != "racing" or (st["elapsed_s"] or 0) > 3 * 3600:
            return "not_now"

        def claim(r: dict[str, Any]) -> bool:
            nt = r.setdefault("notified", {})
            if nt.get("start"):
                return False
            nt["start"] = True
            return True
        if not self._edit(owner, ev["id"], claim):
            return "claimed"
        name = self._name(owner)
        self._notify(owner, ev, "start", f"{name} just started {_name(ev)}. Live times when their watch syncs.")
        return "sent"

    def check_finish(self, owner: str) -> str:
        """After new workouts sync: push mutual friends once when the race result is in."""
        if owner.startswith("coach_"):
            return "skipped"
        now = self._now(owner)
        ev = self._tracked_race(owner, now.date())
        if ev is None:
            return "none"
        saved = self.saved(owner, ev["id"])
        if not saved.get("notify_friends"):
            return "off"
        st = status(ev, saved, now, self._acts_of(owner))
        res = st.get("result")
        if st["state"] != "finished" or not res:
            return "not_yet"

        def claim(r: dict[str, Any]) -> bool:
            nt = r.setdefault("notified", {})
            if nt.get("finish"):
                return False
            nt["finish"] = res.get("activity_id") or True
            return True
        if not self._edit(owner, ev["id"], claim):
            return "claimed"
        self._notify(owner, ev, "finish", f"{self._name(owner)} finished {_name(ev)} in {res['time']}! 🎉")
        return "sent"

    # ------------------------------------------------------------ moments --
    def check_moments(self, uid: str, moments: Any, *, packing: Callable[[str, dict[str, Any]], tuple[int, int]] | None = None) -> str:
        """From ``Moments.on_tick`` (outside quiet hours): the race-week moment due now."""
        if uid.startswith("coach_"):
            return "skipped"
        local = self._now(uid)
        rw = race_week(self._events(uid), local.date())
        if rw is None:
            return "none"
        step = moment_due(rw["days"], local.time())
        if step is None:
            return "not_now"
        if not moments._claim(uid, f"raceweek:{step}", local.date()):
            return "claimed"
        counts = None
        if step == "pack" and packing is not None:
            try:
                counts = packing(uid, rw["event"])
            except Exception:
                counts = None
        return moments.post(uid, week_moment(step, rw["event"], rw["days"], counts))

    @staticmethod
    def skip_countdown(ev: dict[str, Any]) -> set[str]:
        """Countdown steps race-week mode replaces (``Moments.check_race``)."""
        return {"week", "eve"} if eligible(ev) else set()


__all__ = ["RaceWeek", "RaceWeekError", "eligible", "moment_due", "nutrition_plan", "pacing_plan",
           "packing_defaults", "packing_view", "parse_target", "race_result", "race_week", "splits",
           "start_time", "status", "taper", "today_sessions", "track_visible", "tri_splits", "week_moment"]
