"""Progress trends: three small charts for the Progress tab. Deterministic, no model call.

``GET /app/api/progress/trends`` (athletes; coach accounts 403 via ``_api``):

* ``distance``: km per Monday-start week for the last ``WEEKS`` weeks, per distance sport
  (run, bike, swim) the athlete did or planned, with the plan's goal for weeks the built plan
  covers (``plancal.week_mileage``: the athlete's own week goal override or the sessions' sum).
  Takeaway: the last 4 weeks' average vs the 4 before.
* ``pace``: pace at the same effort on easy runs. Easy = runs >= 20 min and >= 3 km with an
  average heart rate at or under the median of the window's runs (the easier half). Each
  run's efficiency is speed per heartbeat (m/s / bpm); a week's value is the median; it's
  shown as the pace at the athlete's typical easy heart rate (``ref_hr`` = median of those
  runs). Needs ``MIN_PACE_WEEKS`` weeks with an easy run, else ``points: []`` + a reason.
* ``sleep``: nightly sleep hours vs that day's training load (Garmin ``activityTrainingLoad``,
  else minutes) for the last ``SLEEP_DAYS`` days, from the athlete's chosen sleep source.
  Garmin nights are kept in the per-user ``sleeplog`` doc (only date + hours) because the app
  reads 3 nights at a time (Garmin rate limit), so the chart fills in as days go by. Oura
  nights come straight from Oura's 28-day read and are never stored or sent to the model.
  Takeaway: average sleep the night after the hardest quarter of days vs the rest.

Nothing here goes into Rabbit's context.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .plancal import DIST_SPORTS, acts_km_by_day, threshold_pace, week_mileage
from .stats import category
from .weekplan import _seconds

if TYPE_CHECKING:
    from .appstore import AppStore

WEEKS = 16
MIN_PACE_WEEKS = 4
SLEEP_DAYS = 28
MIN_SLEEP_NIGHTS = 7
KEEP_NIGHTS = 60
CACHE_S = 600
KM_PER_MI = 1.609344


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _day(a: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(a.get("date") or "")[:10])
    except ValueError:
        return None


def _pct(a: float, b: float) -> int | None:
    return round((a - b) / b * 100) if b > 0 else None


# ------------------------------------------------------------- distance ---
def distance(acts: list[dict[str, Any]], today: date, *, plan: dict[str, Any] | None,
             athlete: dict[str, Any], imperial: bool) -> dict[str, Any]:
    first = _monday(today) - timedelta(weeks=WEEKS - 1)
    mondays = [first + timedelta(weeks=i) for i in range(WEEKS)]
    by_day = acts_km_by_day(acts)
    done: dict[str, list[float]] = {sp: [0.0] * WEEKS for sp in DIST_SPORTS}
    for d, kms in by_day.items():
        try:
            day = date.fromisoformat(d)
        except ValueError:
            continue
        i = (_monday(day) - first).days // 7
        if 0 <= i < WEEKS and day <= today:
            for sp, km in kms.items():
                done[sp][i] += km
    goal: dict[str, list[float | None]] = {sp: [None] * WEEKS for sp in DIST_SPORTS}
    if plan:
        thr, _ = threshold_pace(athlete, acts)
        weeks = {w.get("start"): w for w in plan.get("weeks") or [] if isinstance(w, dict)}
        for i, m in enumerate(mondays):
            w = weeks.get(m.isoformat())
            if w is None:
                continue
            for sp, row in week_mileage(plan, w, by_day, today, thr).items():
                if row.get("goal"):
                    goal[sp][i] = float(row["goal"])
    sports = []
    for sp in DIST_SPORTS:
        if not any(done[sp]) and not any(g for g in goal[sp] if g):
            continue
        last4, prev4 = sum(done[sp][-4:]) / 4, sum(done[sp][-8:-4]) / 4
        # the current week is still going: compare finished weeks when it's early in the week
        if today.weekday() < 6:
            last4, prev4 = sum(done[sp][-5:-1]) / 4, sum(done[sp][-9:-5]) / 4
        sports.append({
            "sport": sp,
            "weeks": [{"start": m.isoformat(), "km": round(done[sp][i], 1),
                       "goal": None if goal[sp][i] is None else round(goal[sp][i] or 0.0, 1)}
                      for i, m in enumerate(mondays)],
            "avg4_km": round(last4, 1), "prev4_km": round(prev4, 1), "change_pct": _pct(last4, prev4),
        })
    sports.sort(key=lambda s: -sum(w["km"] for w in s["weeks"]))
    return {"sports": sports, "current_week": _monday(today).isoformat(), "imperial": imperial}


# ----------------------------------------------------------------- pace ---
def _run_rows(acts: list[dict[str, Any]], first: date, today: date) -> list[dict[str, Any]]:
    rows = []
    for a in acts or []:
        if category(a.get("sport")) != "run" or (a.get("multisport") or {}).get("is_parent"):
            continue
        d = _day(a)
        hr, km = _num(a.get("avg_hr")), _num(a.get("distance_km"))
        sec = _seconds(a.get("moving_duration")) or _seconds(a.get("duration"))
        if d is None or not (first <= d <= today) or not hr or not km or km < 3 or sec < 20 * 60 or hr < 80:
            continue
        rows.append({"date": d, "hr": hr, "ef": (km * 1000 / sec) / hr, "te": _num(a.get("aerobic_te"))})
    return rows


def pace(acts: list[dict[str, Any]], today: date, *, imperial: bool) -> dict[str, Any]:
    first = _monday(today) - timedelta(weeks=WEEKS - 1)
    rows = _run_rows(acts, first, today)
    out: dict[str, Any] = {"points": [], "ref_hr": None, "change_s": None, "imperial": imperial, "reason": None}
    if not rows:
        out["reason"] = "No runs with heart rate in the last 16 weeks."
        return out
    cut = statistics.median(r["hr"] for r in rows)
    easy = [r for r in rows if r["hr"] <= cut and (r["te"] is None or r["te"] < 4.0)]
    ref = round(statistics.median(r["hr"] for r in easy)) if easy else None
    weeks: dict[date, list[float]] = {}
    for r in easy:
        weeks.setdefault(_monday(r["date"]), []).append(r["ef"])
    if ref is None or len(weeks) < MIN_PACE_WEEKS:
        out["reason"] = f"Needs easy runs with heart rate in {MIN_PACE_WEEKS} different weeks."
        return out
    unit = KM_PER_MI if imperial else 1.0
    pts = []
    for m in sorted(weeks):
        ef = statistics.median(weeks[m])
        pts.append({"start": m.isoformat(), "sec": round(1000 / (ef * ref) * unit), "runs": len(weeks[m])})
    out["points"], out["ref_hr"] = pts, ref
    k = min(4, len(pts) // 2)
    early, late = statistics.mean(p["sec"] for p in pts[:k]), statistics.mean(p["sec"] for p in pts[-k:])
    out["change_s"] = round(late - early)  # negative = faster at the same heart rate
    out["since"] = pts[0]["start"]
    return out


# ---------------------------------------------------------------- sleep ---
def day_load(acts: list[dict[str, Any]]) -> tuple[dict[str, float], str]:
    """{day: load}: Garmin training load when every workout has one, else minutes."""
    rows = [a for a in acts or [] if not (a.get("multisport") or {}).get("is_parent")]
    use_load = bool(rows) and all(_num(a.get("training_load")) for a in rows[-30:])
    out: dict[str, float] = {}
    for a in rows:
        d = str(a.get("date") or "")[:10]
        v = _num(a.get("training_load")) if use_load else _seconds(a.get("duration")) / 60
        if d and v:
            out[d] = out.get(d, 0.0) + v
    return out, "load" if use_load else "minutes"


def sleep(nights: dict[str, float], acts: list[dict[str, Any]], today: date, *, source: str | None) -> dict[str, Any]:
    """``nights``: {date: hours} where the date is the morning the night ended."""
    load, measure = day_load(acts)
    days = [(today - timedelta(days=i)) for i in range(SLEEP_DAYS - 1, -1, -1)]
    pts = [{"date": d.isoformat(), "load": round(load.get(d.isoformat(), 0.0)),
            "sleep_h": nights.get((d + timedelta(days=1)).isoformat())} for d in days]
    have = [p for p in pts if p["sleep_h"] is not None]
    out: dict[str, Any] = {"points": pts, "measure": measure, "source": source, "nights": len(have),
                           "hard_h": None, "other_h": None, "reason": None}
    if source is None:
        out["reason"] = "Connect Garmin or Oura sleep to see this."
    elif len(have) < MIN_SLEEP_NIGHTS:
        out["reason"] = f"{len(have)} of {MIN_SLEEP_NIGHTS} nights so far. This fills in as you sleep with your watch or ring."
        return out
    if not have:
        return out
    loads = sorted(p["load"] for p in have if p["load"] > 0)
    if len(loads) < 3:
        return out
    hard_cut = loads[int(len(loads) * 0.75)]
    hard = [p["sleep_h"] for p in have if p["load"] >= hard_cut and p["load"] > 0]
    other = [p["sleep_h"] for p in have if p["load"] < hard_cut]
    if hard and other:
        out["hard_h"], out["other_h"] = round(statistics.mean(hard), 1), round(statistics.mean(other), 1)
    return out


class SleepLog:
    """Garmin nights only ({date: hours}, last ``KEEP_NIGHTS``) in the per-user ``sleeplog`` doc."""

    def __init__(self, store: "AppStore") -> None:
        self._s = store

    def merge(self, uid: str, rows: list[dict[str, Any]] | None) -> dict[str, float]:
        new = {str(r["date"])[:10]: float(r["sleep_hours"]) for r in rows or []
               if isinstance(r, dict) and r.get("date") and _num(r.get("sleep_hours"))}
        doc = self._s.user_doc(uid, "sleeplog")
        cur = doc.load().get("nights") or {}
        if new and any(cur.get(k) != v for k, v in new.items()):
            def apply(d: dict[str, Any]) -> None:
                n = d.setdefault("nights", {})
                n.update(new)
                for k in sorted(n)[:-KEEP_NIGHTS]:
                    del n[k]
            doc.update(apply)
            cur = {**cur, **new}
        return {k: float(v) for k, v in cur.items() if _num(v)}


def build(*, acts: list[dict[str, Any]], today: date, plan: dict[str, Any] | None, athlete: dict[str, Any],
          nights: dict[str, float], sleep_source: str | None) -> dict[str, Any]:
    imperial = athlete.get("units") != "metric"
    return {"today": today.isoformat(), "units": "imperial" if imperial else "metric",
            "distance": distance(acts, today, plan=plan, athlete=athlete, imperial=imperial),
            "pace": pace(acts, today, imperial=imperial),
            "sleep": sleep(nights, acts, today, source=sleep_source)}


class TrendsService:
    """Caches the trends per user for ``CACHE_S`` (``fresh`` skips it)."""

    def __init__(self, gather: Callable[[str], dict[str, Any]], clock: Callable[[], float] = time.monotonic) -> None:
        self._gather = gather
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, uid: str, *, fresh: bool = False) -> dict[str, Any]:
        with self._lock:
            hit = self._cache.get(uid)
        if hit and not fresh and self._clock() - hit[0] < CACHE_S:
            return hit[1]
        out = build(**self._gather(uid))
        with self._lock:
            self._cache[uid] = (self._clock(), out)
        return out

    def forget(self, uid: str) -> None:
        with self._lock:
            self._cache.pop(uid, None)
