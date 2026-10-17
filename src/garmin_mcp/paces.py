"""Training paces: notice when run threshold pace, bike FTP or swim CSS have moved, and offer
a one-tap update that re-targets the future plan.

Deterministic, no model call, never Oura. Inputs are Garmin only: the year of compact
activities (``StatsService.activities``), lap splits for a few recent runs/swims
(``get_activity_splits``, fetched sparingly and kept in the per-user ``paces`` doc) and,
when the watch has one, Garmin's race predictor (supporting evidence only).

Detection (``check``: after each synced workout via ``Moments.after_workouts`` and weekly via
``Moments.on_tick``)

* **Run threshold pace** (s/km). Efforts in the last 21 days (races 28):
  - races 3-50 km: race pace scaled to a one-hour effort (Riegel 1.06: ``pace * (3600/t)^0.0566``);
  - tempo/threshold laps: laps >= 3 min, not hilly, hard by HR (>= 92% threshold HR) or, with
    no threshold HR, clearly faster than the run's other laps in a run named tempo/threshold/...;
    >= 12 min of such work. Continuous (one block) = tempo, HR-corrected; repeats = intervals
    (pace x 1.01, reps run a touch faster than threshold);
  - sustained 20-60 min runs at >= 92% threshold HR (needs threshold HR), scaled + HR-corrected;
  - Garmin's 10K prediction (weight 0.5; never counts toward the evidence rule).
* **Bike FTP**: 95% of the best 20-min power (Garmin ``max20MinPower``) of rides >= 25 min.
* **Swim CSS** (s/100 m): pool swims with >= 4 repeats of 100-400 m: the faster half's pace
  (+2% when the repeats are mostly 100s).

Rules: enough evidence = 2+ qualifying efforts in 21 days or a race. Outliers are skipped and
shown in "See why": hilly (> 15 m/km), hot (>= 27 °C), high (> 600 m above home elevation, or
> 2,000 m with no home elevation), treadmill/indoor runs, and with 3+ efforts anything > 6%
from the median. A change must be meaningful (>= 2%, or >= 5 s/mi for runs and >= 2 s/100 m for
swims) and is capped at 6% faster / 5% slower per step. One suggestion per sport per 14 days;
"Never for this" turns a sport off (Profile turns it back on). Easing ("consistently missing
target paces with a high HR"): 3+ quality efforts in 21 days at >= 95% threshold HR, every one
>= 2% slower than the current threshold and none faster (run); 3+ hard rides (>= 92% threshold
HR) whose best 20-min power says >= 2% lower FTP (bike). Swims have no HR, so no easing.

Accept (``accept``): updates the athlete profile field, then in the active built plan freezes
the old value on every PAST session of that sport (``session["targets"]``, so its workout view
keeps the targets it was planned with; see ``athlete_for``) and re-targets the future: run and
bike targets are derived from the profile when shown or synced (``session_hash`` changes, so
Garmin re-sync uploads them), and future builder swims are rebuilt for the new CSS. Undo within
24 h restores the profile value, the past markers and the swims. Provenance per field lives in
the doc's ``source`` ("Tuesday's tempo + Saturday's 10K", or "set by you" when the profile value
no longer matches what Rabbit set).
"""

from __future__ import annotations

import logging
import re
import secrets
import statistics
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from .appstore import AppStore
from .logs import log_event
from .planbuilder import KINDS_BY_SPORT, PACE_ZONES, POWER_ZONES, ZONE_NAMES, rebuild_session

logger = logging.getLogger(__name__)

SPORTS = ("run", "bike", "swim")
FIELD = {"run": "run_threshold_pace", "bike": "ftp_w", "swim": "swim_css"}
SPORT_OF = {v: k for k, v in FIELD.items()}
TOUCHES = {"run": ("run", "brick"), "bike": ("bike", "brick"), "swim": ("swim",)}
KM_MI = 1.609344
WINDOW_DAYS = 21
RACE_DAYS = 28
COOLDOWN_DAYS = 14
PENDING_DAYS = 14
WEEKLY_DAYS = 7
UNDO_S = 24 * 3600
MIN_EFFORTS = 2
EASE_EFFORTS = 3
MIN_PCT = 0.02
RUN_MIN_S_KM = 5 / KM_MI          # 5 s/mi
SWIM_MIN_S = 2.0
MAX_FASTER, MAX_SLOWER = 0.06, 0.05
HOT_C = 27.0
ALT_MARGIN_M = 600.0
ALT_NO_HOME_M = 2000.0
HILLY_M_KM = 15.0
LAP_MIN_S = 180
WORK_MIN_S = 12 * 60
OUTLIER_PCT = 0.06
HARD_HR = 0.92
EASE_HR = 0.95
ONE_HOUR_EXP = 0.06 / 1.06
WEIGHT = {"race": 1.0, "tempo": 1.0, "intervals": 0.85, "sustained": 0.7, "garmin": 0.5,
          "ride": 1.0, "swim": 1.0}
KIND_WORD = {"tempo": "tempo", "intervals": "intervals", "sustained": "hard run", "ride": "ride",
             "swim": "swim set", "garmin": "Garmin race predictor"}
MAX_LAP_DOCS = 60
HARD_NAME = re.compile(r"\b(tempo|threshold|intervals?|reps|repeats|cruise|lt|tt|time ?trial|track|"
                       r"fartlek|workout|race|parkrun)\b", re.I)
NAMED_KM = ((5.0, "5K"), (10.0, "10K"), (21.0975, "half marathon"), (42.195, "marathon"))


class PaceError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


# ------------------------------------------------------------- helpers ---
def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and v == v else None


def _secs(v: Any) -> float | None:
    """Seconds from a number or "h:mm:ss"/"mm:ss" (compact activities format durations)."""
    n = _num(v)
    if n is not None:
        return n
    if isinstance(v, str) and re.fullmatch(r"\d+(:\d{1,2}){1,2}", v.strip()):
        parts = [int(p) for p in v.strip().split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


def _day(a: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(a.get("date") or "")[:10])
    except ValueError:
        return None


def mmss(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def fmt_pace(s_per_km: float, imperial: bool) -> str:
    return f"{mmss(s_per_km * (KM_MI if imperial else 1.0))}/{'mi' if imperial else 'km'}"


def per_unit(s_per_km: float, imperial: bool) -> str:
    """A pace difference in whole seconds per athlete unit: "8 sec/mi"."""
    return f"{int(round(abs(s_per_km) * (KM_MI if imperial else 1.0)))} sec/{'mi' if imperial else 'km'}"


def fmt_value(sport: str, v: float, imperial: bool) -> str:
    if sport == "run":
        return fmt_pace(v, imperial)
    if sport == "bike":
        return f"{int(round(v))} W"
    return f"{mmss(v)}/100m"


def when_label(d: date, today: date) -> str:
    n = (today - d).days
    if n == 0:
        return "today's"
    if n == 1:
        return "yesterday's"
    if n < 7:
        return f"{d.strftime('%A')}'s"
    return f"the {d.strftime('%b')} {d.day}"


def _race_word(km: float) -> str:
    for k, w in NAMED_KM:
        if abs(km - k) / k <= 0.04:
            return w
    return "race"


def effort_label(e: dict[str, Any], today: date) -> str:
    if e["kind"] == "garmin":
        return "Garmin's race predictor"
    try:
        d = date.fromisoformat(e["date"])
    except (KeyError, ValueError):
        return KIND_WORD.get(e["kind"], "workout")
    word = _race_word(e.get("km") or 0) if e["kind"] == "race" else KIND_WORD.get(e["kind"], "workout")
    return f"{when_label(d, today)} {word}"


def outlier_reason(a: dict[str, Any], athlete: dict[str, Any]) -> str | None:
    """Why an activity can't tell us about flat, temperate fitness (None = fine)."""
    km = _num(a.get("distance_km")) or 0.0
    gain = _num(a.get("elevation_gain_m")) or 0.0
    if km > 0 and gain / km > HILLY_M_KM:
        return "hilly"
    t = _num(a.get("max_temp_c"))
    if t is not None and t >= HOT_C:
        return "hot"
    top = _num(a.get("max_elev_m"))
    if top is not None:
        home = _num(athlete.get("home_elevation_m"))
        if top > (home + ALT_MARGIN_M if home is not None else ALT_NO_HOME_M):
            return "at altitude"
    return None


def _is_run(a: dict[str, Any]) -> bool:
    s = str(a.get("sport") or "").lower()
    return "run" in s and not any(w in s for w in ("treadmill", "indoor", "virtual"))


def _is_ride(a: dict[str, Any]) -> bool:
    s = str(a.get("sport") or "").lower()
    return any(w in s for w in ("cycl", "bik", "ride", "gravel")) and "e_bike" not in s and "ebike" not in s


def _is_pool(a: dict[str, Any]) -> bool:
    s = str(a.get("sport") or "").lower()
    return "swim" in s and "open_water" not in s


def one_hour(pace: float, seconds: float) -> float:
    """Pace of a ``seconds``-long all-out effort scaled to a one-hour effort (threshold)."""
    return pace * (3600.0 / seconds) ** ONE_HOUR_EXP


def hr_correct(est: float, hr: float | None, thr_hr: float | None) -> float:
    """A sub-threshold HR means the pace undersells threshold: nudge it faster (<= 4%)."""
    if not hr or not thr_hr:
        return est
    r = hr / thr_hr
    return est * (1 - min(0.04, max(0.0, 0.97 - r) * 0.6))


def laps_from_splits(raw: Any) -> list[dict[str, float]]:
    """``get_activity_splits`` → compact laps ``{d (m), s, hr?, gain?}``."""
    laps = raw.get("lapDTOs") if isinstance(raw, dict) else None
    out = []
    for lp in laps if isinstance(laps, list) else []:
        if not isinstance(lp, dict):
            continue
        d = _num(lp.get("distance"))
        s = _num(lp.get("movingDuration")) or _num(lp.get("duration"))
        if not d or not s or d <= 0 or s <= 0:
            continue
        x: dict[str, float] = {"d": round(d, 1), "s": round(s, 1)}
        if (hr := _num(lp.get("averageHR"))):
            x["hr"] = round(hr)
        if (g := _num(lp.get("elevationGain"))) is not None:
            x["gain"] = round(g, 1)
        out.append(x)
    return out[:80]


# ------------------------------------------------------------ evidence ---
def _work_laps(laps: list[dict[str, float]], name: str, thr_hr: float | None) -> list[tuple[int, dict[str, float]]]:
    ok = []
    for i, lp in enumerate(laps):
        p = lp["s"] / (lp["d"] / 1000)
        if lp["s"] < LAP_MIN_S or not 150 <= p <= 600:
            continue
        if lp["d"] > 0 and (lp.get("gain") or 0) / (lp["d"] / 1000) > HILLY_M_KM:
            continue
        ok.append((i, lp, p))
    if not ok:
        return []
    if thr_hr:
        return [(i, lp) for i, lp, _ in ok if (lp.get("hr") or 0) >= HARD_HR * thr_hr]
    if not HARD_NAME.search(name or ""):
        return []
    dist = sum(lp["d"] for lp in laps)
    avg = sum(lp["s"] for lp in laps) / (dist / 1000) if dist else None  # the whole run's pace
    return [(i, lp) for i, lp, p in ok if avg and p <= 0.93 * avg]


def run_efforts(acts: list[dict[str, Any]], laps: dict[str, list[dict[str, float]]], today: date,
                athlete: dict[str, Any], garmin_10k_s: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(efforts, skipped). Each effort: kind, date, activity_id, name, value (threshold s/km
    implied), pace/minutes/hr shown in "See why"."""
    thr_hr = _num(athlete.get("threshold_hr"))
    out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for a in acts or []:
        if not _is_run(a):
            continue
        d = _day(a)
        km = _num(a.get("distance_km"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d is None or d > today or (today - d).days > RACE_DAYS or not km or not t:
            continue
        race = a.get("event") == "race"
        if not race and (today - d).days > WINDOW_DAYS:
            continue
        aid = a.get("activity_id")
        base = {"date": d.isoformat(), "activity_id": aid, "name": str(a.get("name") or "")[:60], "km": km}
        lps = laps.get(str(aid)) or []
        work = _work_laps(lps, base["name"], thr_hr) if lps and not race else []
        work_s = sum(lp["s"] for _, lp in work)
        hard_hr = bool(thr_hr and (_num(a.get("avg_hr")) or 0) >= HARD_HR * thr_hr)
        quality = race or work_s >= WORK_MIN_S or (hard_hr and 20 * 60 <= t <= 60 * 60)
        if not quality:
            continue
        why = outlier_reason(a, athlete)
        if why:
            skipped.append({**base, "kind": "race" if race else "tempo", "reason": why})
            continue
        if race:
            if not 3 <= km <= 50:
                continue
            pace = t / km
            if not 150 <= pace <= 600:
                continue
            out.append({**base, "kind": "race", "value": one_hour(pace, t), "pace": pace, "minutes": t / 60,
                        "hr": _num(a.get("avg_hr"))})
        elif work_s >= WORK_MIN_S:
            dist = sum(lp["d"] for _, lp in work) / 1000
            pace = work_s / dist
            hr_w = sum((lp.get("hr") or 0) * lp["s"] for _, lp in work)
            hr = hr_w / work_s if all(lp.get("hr") for _, lp in work) else None
            idx = [i for i, _ in work]
            continuous = idx == list(range(idx[0], idx[0] + len(idx)))
            if continuous:
                value = hr_correct(one_hour(pace, work_s) if work_s > 3600 else pace, hr, thr_hr)
                kind = "tempo"
            else:
                value, kind = pace * 1.01, "intervals"
            out.append({**base, "kind": kind, "value": value, "pace": pace, "minutes": work_s / 60, "hr": hr})
        else:
            pace = t / km
            if not 150 <= pace <= 600:
                continue
            hr = _num(a.get("avg_hr"))
            out.append({**base, "kind": "sustained", "value": hr_correct(one_hour(pace, t), hr, thr_hr),
                        "pace": pace, "minutes": t / 60, "hr": hr})
    if garmin_10k_s and 1200 <= garmin_10k_s <= 6000:
        p = garmin_10k_s / 10.0
        out.append({"kind": "garmin", "date": today.isoformat(), "activity_id": None, "name": "Garmin 10K prediction",
                    "km": 10.0, "value": one_hour(p, garmin_10k_s), "pace": p, "minutes": garmin_10k_s / 60, "hr": None})
    return out, skipped


def ride_efforts(acts: list[dict[str, Any]], today: date,
                 athlete: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for a in acts or []:
        if not _is_ride(a):
            continue
        d = _day(a)
        p20 = _num(a.get("max_20min_power_w"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d is None or d > today or (today - d).days > WINDOW_DAYS or not p20 or not t or t < 25 * 60:
            continue
        if not 60 <= p20 <= 700:
            continue
        base = {"date": d.isoformat(), "activity_id": a.get("activity_id"), "name": str(a.get("name") or "")[:60],
                "kind": "ride", "km": _num(a.get("distance_km"))}
        indoor = any(w in str(a.get("sport") or "").lower() for w in ("indoor", "virtual"))
        why = None if indoor else outlier_reason(a, athlete)
        if why == "hilly":
            why = None  # climbing doesn't hurt power numbers
        if why:
            skipped.append({**base, "reason": why})
            continue
        out.append({**base, "value": 0.95 * p20, "p20": p20, "minutes": t / 60, "hr": _num(a.get("avg_hr"))})
    return out, skipped


def swim_efforts(acts: list[dict[str, Any]], laps: dict[str, list[dict[str, float]]],
                 today: date) -> list[dict[str, Any]]:
    out = []
    for a in acts or []:
        if not _is_pool(a):
            continue
        d = _day(a)
        if d is None or d > today or (today - d).days > WINDOW_DAYS:
            continue
        reps = []
        for lp in laps.get(str(a.get("activity_id"))) or []:
            if 100 <= lp["d"] <= 400:
                p = lp["s"] / (lp["d"] / 100)
                if 60 <= p <= 240:
                    reps.append((p, lp))
        if len(reps) < 4:
            continue
        reps.sort(key=lambda x: x[0])
        fast = reps[: max(2, len(reps) // 2)]
        t = sum(lp["s"] for _, lp in fast)
        dist = sum(lp["d"] for _, lp in fast)
        pace = t / (dist / 100)
        mean_d = dist / len(fast)
        out.append({"date": d.isoformat(), "activity_id": a.get("activity_id"), "name": str(a.get("name") or "")[:60],
                    "kind": "swim", "value": pace * (1.02 if mean_d < 150 else 1.0), "pace": pace,
                    "reps": len(fast), "rep_m": int(round(mean_d / 50) * 50)})
    return out


def _weight(e: dict[str, Any], today: date) -> float:
    try:
        age = (today - date.fromisoformat(e["date"])).days
    except (KeyError, ValueError):
        age = 0
    return WEIGHT.get(e["kind"], 0.7) * max(0.3, 1 - age / 42)


def drop_outliers(efforts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(efforts) < 3:
        return efforts
    med = statistics.median(e["value"] for e in efforts)
    return [e for e in efforts if abs(e["value"] - med) / med <= OUTLIER_PCT]


def enough(efforts: list[dict[str, Any]], today: date) -> bool:
    real = [e for e in efforts if e["kind"] != "garmin"]
    recent = [e for e in real if (today - date.fromisoformat(e["date"])).days <= WINDOW_DAYS]
    return len(recent) >= MIN_EFFORTS or any(e["kind"] == "race" for e in real)


def blend(efforts: list[dict[str, Any]], today: date) -> float:
    w = [(_weight(e, today), e["value"]) for e in efforts]
    return sum(a * v for a, v in w) / sum(a for a, _ in w)


def meaningful(sport: str, old: float, new: float) -> bool:
    diff = abs(new - old)
    if old <= 0:
        return True
    if diff / old >= MIN_PCT:
        return True
    if sport == "run":
        return diff >= RUN_MIN_S_KM - 1e-9
    if sport == "swim":
        return diff >= SWIM_MIN_S
    return False


def _rounded(sport: str, v: float) -> int:
    return int(round(v))


def _cap(sport: str, old: float, new: float) -> tuple[float, bool]:
    """Limit one step to 6% better / 5% worse. Pace sports: lower is faster."""
    better = new < old if sport != "bike" else new > old
    cap = MAX_FASTER if better else MAX_SLOWER
    if abs(new - old) / old <= cap:
        return new, False
    sign = (-1 if better else 1) * (1 if sport != "bike" else -1)
    return old * (1 + sign * cap), True


def estimate(sport: str, acts: list[dict[str, Any]], laps: dict[str, list[dict[str, float]]], today: date,
             athlete: dict[str, Any], garmin_10k_s: float | None = None) -> dict[str, Any] | None:
    """Pure. A suggestion body (no id) or None. Keys: sport, field, direction
    (faster|slower|set), old, new, capped, efforts (used), skipped."""
    field = FIELD[sport]
    cur = _num(athlete.get(field))
    thr_hr = _num(athlete.get("threshold_hr"))
    if sport == "run":
        efforts, skipped = run_efforts(acts, laps, today, athlete, garmin_10k_s)
    elif sport == "bike":
        efforts, skipped = ride_efforts(acts, today, athlete)
    else:
        efforts, skipped = swim_efforts(acts, laps, today), []
    if not efforts or not enough(efforts, today):
        return None
    used = drop_outliers(efforts)
    if not enough(used, today):
        return None
    for e in efforts:
        if e not in used:
            skipped.append({**{k: e[k] for k in ("date", "activity_id", "name", "kind", "km") if k in e},
                            "reason": "far off your other efforts"})
    if sport == "bike":
        best = max(used, key=lambda e: e["value"])
        value = best["value"]
    else:
        value = blend(used, today)
    out = {"sport": sport, "field": field, "efforts": used, "skipped": skipped, "capped": False}
    if cur is None:
        return out | {"direction": "set", "old": None, "new": _rounded(sport, value)}
    faster = value < cur if sport != "bike" else value > cur
    if faster:
        if not meaningful(sport, cur, value):
            return None
        new, capped = _cap(sport, cur, value)
        new = _rounded(sport, new)
        if new == int(round(cur)) or not meaningful(sport, cur, new):
            return None
        return out | {"direction": "faster", "old": cur, "new": new, "capped": capped}
    return _ease(sport, cur, used, thr_hr, today, out)


def _ease(sport: str, cur: float, used: list[dict[str, Any]], thr_hr: float | None, today: date,
          out: dict[str, Any]) -> dict[str, Any] | None:
    """Consistently below target with a high heart rate → a gentler threshold."""
    if sport == "swim" or not thr_hr:
        return None
    if sport == "run":
        q = [e for e in used if e["kind"] in ("tempo", "intervals", "sustained", "race")
             and (today - date.fromisoformat(e["date"])).days <= WINDOW_DAYS]
        if len(q) < EASE_EFFORTS:
            return None
        if any((e.get("hr") or 0) < EASE_HR * thr_hr for e in q):
            return None
        if any(e["value"] < cur * (1 + MIN_PCT) for e in q):
            return None  # one on-target effort says the threshold still holds
        value = statistics.median(e["value"] for e in q)
    else:
        q = [e for e in used if (e.get("hr") or 0) >= HARD_HR * thr_hr]
        if len(q) < EASE_EFFORTS:
            return None
        value = max(e["value"] for e in q)
        if value > cur * (1 - MIN_PCT):
            return None
    if not meaningful(sport, cur, value):
        return None
    new, capped = _cap(sport, cur, value)
    return out | {"direction": "slower", "old": cur, "new": _rounded(sport, new), "capped": capped, "efforts": q}


# ------------------------------------------------------------ wording ---
def effort_detail(e: dict[str, Any], sport: str, imperial: bool) -> str:
    if e["kind"] == "garmin":
        return f"10K in {mmss(e['minutes'] * 60)}"
    if sport == "bike":
        return f"{int(round(e['p20']))} W best 20 min"
    if sport == "swim":
        return f"{e['reps']} x {e['rep_m']} m at {mmss(e['pace'])}/100m"
    bits = [f"{int(round(e['minutes']))} min at {fmt_pace(e['pace'], imperial)}"]
    if e.get("hr"):
        bits.append(f"HR {int(round(e['hr']))}")
    return ", ".join(bits)


SKIP_WORD = {"hilly": "hilly", "hot": "hot day", "at altitude": "at altitude", "far off your other efforts": "far off the rest"}


def _names(efforts: list[dict[str, Any]], today: date) -> str:
    real = sorted([e for e in efforts if e["kind"] != "garmin"], key=lambda e: e["date"])
    labels = [effort_label(e, today) for e in real]
    if not labels:
        return "Garmin's race predictor"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{labels[-2]}, {labels[-1]} and {len(labels) - 2} more"


def headline(s: dict[str, Any], today: date, imperial: bool) -> str:
    sport, old, new, d = s["sport"], s.get("old"), s["new"], s["direction"]
    src = _names(s["efforts"], today)
    if d == "set":
        src = src[0].upper() + src[1:]
        what = {"run": f"run threshold at {fmt_pace(new, imperial)}", "bike": f"FTP at {new} W",
                "swim": f"swim CSS at {mmss(new)}/100m"}[sport]
        return f"{src} put your {what}. Use it for your training {'zones' if sport == 'bike' else 'paces'}?"
    if sport == "run":
        diff = per_unit(new - old, imperial)
        arrow = f"({fmt_pace(old, imperial).split('/')[0]} → {fmt_pace(new, imperial)})"
        if d == "faster":
            return f"Your threshold looks {diff} faster {arrow} based on {src}. Update your training paces?"
        n = len([e for e in s["efforts"] if e["kind"] != "garmin"])
        return (f"Your last {n} quality runs came in about {diff} slower than target with a high heart rate. "
                f"Ease your threshold {arrow}?")
    if sport == "bike":
        diff = int(round(abs(new - old)))
        if d == "faster":
            return f"Your FTP looks {diff} W higher ({int(round(old))} → {new} W) based on {src}. Update your power zones?"
        return f"Your hard rides have been about {diff} W short of your zones with a high heart rate. Ease FTP ({int(round(old))} → {new} W)?"
    diff = int(round(abs(new - old)))
    return f"Your swim CSS looks {diff} sec/100m faster ({mmss(old)} → {mmss(new)}/100m) based on {src}. Update your swim paces?"


def moment_text(s: dict[str, Any], today: date, imperial: bool) -> str:
    """One line for the Rabbit log (<= 140 chars, one emoji)."""
    sport, old, new, d = s["sport"], s.get("old"), s["new"], s["direction"]
    if d == "set":
        t = {"run": f"Your recent runs put your threshold at {fmt_pace(new, imperial)}. Use it for your paces?",
             "bike": f"Your recent rides put your FTP at {new} W. Use it for your power zones?",
             "swim": f"Your recent swims put your CSS at {mmss(new)}/100m. Use it for your swim paces?"}[sport]
    elif sport == "run":
        arrow = f"({fmt_pace(old, imperial).split('/')[0]} → {fmt_pace(new, imperial)})"
        t = (f"Your threshold looks {per_unit(new - old, imperial)} faster {arrow}. Update your training paces?"
             if d == "faster" else f"Tempo efforts have felt hard lately. Ease your threshold {arrow}?")
    elif sport == "bike":
        t = (f"Your FTP looks {int(round(new - old))} W higher ({int(round(old))} → {new} W). Update your power zones?"
             if d == "faster" else f"Hard rides have been coming up short. Ease FTP ({int(round(old))} → {new} W)?")
    else:
        t = f"Your swim CSS looks {int(round(old - new))} sec faster ({mmss(old)} → {mmss(new)}/100m). Update swim paces?"
    t = f"{'📈' if d != 'slower' else '🐇'} {t}"
    return t if len(t) <= 140 else t[:139].rstrip() + "…"


def zones(sport: str, v: float | None) -> list[dict[str, Any]]:
    """Zones the plan targets: run s/km, bike W, swim s/100m (``lo`` is always the smaller number)."""
    if v is None:
        return []
    out = []
    for z in range(1, 6):
        if sport == "run":
            lo, hi = PACE_ZONES[z]
            out.append({"zone": z, "name": ZONE_NAMES[z], "lo": round(v * lo), "hi": round(v * hi)})
        elif sport == "bike":
            lo, hi = POWER_ZONES[z]
            out.append({"zone": z, "name": ZONE_NAMES[z], "lo": round(v * lo), "hi": round(v * hi)})
        else:
            slow, fast = SWIM_OFFSETS[z]
            out.append({"zone": z, "name": ZONE_NAMES[z], "lo": round(v + fast), "hi": round(v + slow)})
    return out


SWIM_OFFSETS = {1: (20, 12), 2: (12, 6), 3: (6, 2), 4: (2, -2), 5: (-2, -6)}  # = workoutday.SWIM_ZONES


def preview(sport: str, v: float, imperial: bool) -> str:
    z = zones(sport, v)[1]
    if sport == "run":
        return f"easy runs {fmt_pace(z['lo'], imperial).split('/')[0]}–{fmt_pace(z['hi'], imperial)}"
    if sport == "bike":
        return f"endurance rides {z['lo']}–{z['hi']} W"
    return f"CSS repeats at {mmss(v)}/100m"


def athlete_for(athlete: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """The athlete numbers a session's targets use: a past session keeps the values it was
    planned with when the threshold was updated later (``session["targets"]``)."""
    frozen = session.get("targets")
    if not isinstance(frozen, dict) or not frozen:
        return athlete
    out = dict(athlete)
    for k, v in frozen.items():
        if k in SPORT_OF:
            if v is None:
                out.pop(k, None)
            else:
                out[k] = v
    return out


def _touches(sport: str, s: dict[str, Any]) -> bool:
    return s.get("sport") in TOUCHES[sport] and s.get("kind") not in ("race", "rest") and s.get("sport") != "rest"


def _rebuildable_swim(s: dict[str, Any]) -> bool:
    if s.get("sport") != "swim" or s.get("edited") or s.get("detail_custom"):
        return False
    if s.get("kind") not in KINDS_BY_SPORT.get("swim", ()):
        return False

    def has_pct(steps: list[dict[str, Any]]) -> bool:
        return any(x.get("pct") or (x.get("type") == "repeat" and has_pct(x.get("steps") or [])) for x in steps)
    return bool(s.get("steps")) and not has_pct(s["steps"])


def retarget(plan: dict[str, Any], sport: str, old: float | None, new: float, today: date) -> dict[str, Any]:
    """In place. Freezes ``old`` on past sessions, rebuilds future builder swims for ``new``.
    Returns the undo record ``{past: [ids], swims: {id: old session}, future: n}``."""
    field = FIELD[sport]
    past: list[str] = []
    swims: dict[str, dict[str, Any]] = {}
    future = 0
    for w in plan.get("weeks") or []:
        for day, ss in (w.get("days") or {}).items():
            for i, s in enumerate(ss):
                if not _touches(sport, s):
                    continue
                if day < today.isoformat():
                    t = s.setdefault("targets", {})
                    if field not in t:
                        t[field] = old
                        past.append(s["id"])
                    continue
                future += 1
                if sport == "swim" and _rebuildable_swim(s):
                    swims[s["id"]] = {k: s[k] for k in ("steps", "meters", "minutes", "detail") if k in s}
                    ss[i] = rebuild_session(s, swim_pace=float(new) + 12, phase=w.get("phase") or "base")
    return {"past": past, "swims": swims, "future": future}


def restore(plan: dict[str, Any], sport: str, rec: dict[str, Any]) -> None:
    field = FIELD[sport]
    past, swims = set(rec.get("past") or []), rec.get("swims") or {}
    for w in plan.get("weeks") or []:
        for ss in (w.get("days") or {}).values():
            for s in ss:
                if s.get("id") in past and isinstance(s.get("targets"), dict):
                    s["targets"].pop(field, None)
                    if not s["targets"]:
                        del s["targets"]
                if s.get("id") in swims:
                    for k in ("steps", "meters", "minutes", "detail"):
                        s.pop(k, None)
                    s.update(swims[s["id"]])


# ------------------------------------------------------------- service ---
class Paces:
    """Per-user detection, suggestions, accept/undo. State in the encrypted ``paces`` doc."""

    def __init__(self, store: AppStore, *, athlete: Callable[[str], dict[str, Any]],
                 set_athlete: Callable[[str, dict[str, Any]], Any],
                 activities: Callable[[str], list[dict[str, Any]]],
                 now: Callable[[str], datetime], clock: Callable[[], float],
                 splits: Callable[[str, int], Any] | None = None,
                 predictor: Callable[[str], float | None] | None = None,
                 edit_plan: Callable[[str, Callable[[dict[str, Any], date], Any]], Any] | None = None,
                 post: Callable[[str, dict[str, Any]], str] | None = None) -> None:
        self._s = store
        self._athlete = athlete
        self._set_athlete = set_athlete
        self._acts = activities
        self._now = now
        self._clock = clock
        self._splits = splits
        self._predictor = predictor
        self._edit_plan = edit_plan
        self._post = post

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "paces")

    # ------------------------------------------------------------- laps --
    def fill_laps(self, uid: str, acts: list[dict[str, Any]], today: date, *, days: int, limit: int) -> int:
        """Fetch splits for up to ``limit`` recent runs/pool swims we don't have yet. Failures
        are stored as empty so nothing is retried."""
        if self._splits is None:
            return 0
        have = self._doc(uid).load().get("laps") or {}
        thr = _num(self._athlete(uid).get("threshold_hr"))
        want = []
        for a in sorted(acts or [], key=lambda a: str(a.get("date") or ""), reverse=True):
            aid, d = a.get("activity_id"), _day(a)
            if not isinstance(aid, int) or d is None or (today - d).days > days or str(aid) in have:
                continue
            if _is_pool(a) or (_is_run(a) and (days <= 2 or HARD_NAME.search(str(a.get("name") or ""))
                                                or (thr and (_num(a.get("avg_hr")) or 0) >= 0.88 * thr))):
                want.append(aid)
            if len(want) >= limit:
                break
        got: dict[str, list[dict[str, float]]] = {}
        for aid in want:
            try:
                got[str(aid)] = laps_from_splits(self._splits(uid, aid))
            except Exception as e:  # Garmin busy: try the activity's summary only
                log_event(logger, logging.INFO, "paces_splits_failed", user_id=uid, error=type(e).__name__)
                got[str(aid)] = []
        if got:
            def apply(d: dict[str, Any]) -> None:
                laps = d.setdefault("laps", {})
                laps.update(got)
                for k in sorted(laps, key=lambda k: int(k) if k.isdigit() else 0)[: max(0, len(laps) - MAX_LAP_DOCS)]:
                    del laps[k]
            self._doc(uid).update(apply)
        return len(got)

    # ------------------------------------------------------------ check --
    def after_workouts(self, uid: str) -> list[str]:
        if uid.startswith("coach_"):
            return []
        today = self._now(uid).date()
        acts = self._acts(uid)
        self.fill_laps(uid, acts, today, days=2, limit=3)
        return self.check(uid, acts=acts)

    def weekly(self, uid: str) -> list[str]:
        """From ``Moments.on_tick``: once every 7 days."""
        if uid.startswith("coach_"):
            return []
        today = self._now(uid).date()

        def claim(d: dict[str, Any]) -> bool:
            last = d.get("checked")
            if last and (today - date.fromisoformat(last)).days < WEEKLY_DAYS:
                return False
            d["checked"] = today.isoformat()
            return True
        if not self._doc(uid).update(claim):
            return []
        acts = self._acts(uid)
        self.fill_laps(uid, acts, today, days=WINDOW_DAYS, limit=3)
        return self.check(uid, acts=acts)

    def check(self, uid: str, *, acts: list[dict[str, Any]] | None = None) -> list[str]:
        """Detect and post at most one suggestion per sport. Returns posted sports."""
        if uid.startswith("coach_"):
            return []
        today = self._now(uid).date()
        doc = self._doc(uid).load()
        athlete = self._athlete(uid)
        imperial = athlete.get("units") != "metric"
        acts = self._acts(uid) if acts is None else acts
        g10 = None
        out = []
        for sport in SPORTS:
            if self._blocked(doc, sport, today):
                continue
            if sport == "run" and self._predictor is not None and g10 is None:
                try:
                    g10 = self._predictor(uid)
                except Exception:
                    g10 = None
            s = estimate(sport, acts, doc.get("laps") or {}, today, athlete, g10 if sport == "run" else None)
            if s is None:
                continue
            sug = self._store(uid, s, today, imperial)
            if sug is None:
                continue
            out.append(sport)
            if self._post is not None:
                self._post(uid, {"type": "pace", "key": f"pace:{sug['id']}", "text": moment_text(s, today, imperial),
                                 "push_title": "Training paces",
                                 "actions": [{"id": "pace_accept", "label": "Update", "sport": sport, "sid": sug["id"]},
                                             {"id": "pace", "label": "See why", "sport": sport, "sid": sug["id"]},
                                             {"id": "pace_later", "label": "Not now", "sport": sport, "sid": sug["id"]}]})
        return out

    @staticmethod
    def _blocked(doc: dict[str, Any], sport: str, today: date) -> bool:
        if (doc.get("never") or {}).get(sport):
            return True
        last = (doc.get("last") or {}).get(sport)
        if last:
            try:
                if (today - date.fromisoformat(last)).days < COOLDOWN_DAYS:
                    return True
            except ValueError:
                pass
        return False

    def _store(self, uid: str, s: dict[str, Any], today: date, imperial: bool) -> dict[str, Any] | None:
        sid = "p" + secrets.token_hex(5)
        sug = {"id": sid, "sport": s["sport"], "field": s["field"], "direction": s["direction"],
               "old": s["old"], "new": s["new"], "capped": s["capped"], "created": today.isoformat(),
               "headline": headline(s, today, imperial),
               "efforts": [{"label": effort_label(e, today), "detail": effort_detail(e, s["sport"], imperial),
                            "date": e["date"], "activity_id": e.get("activity_id"), "kind": e["kind"]}
                           for e in sorted(s["efforts"], key=lambda e: e["date"])],
               "skipped": [{"label": effort_label(e, today) if e.get("date") else "A workout",
                            "reason": SKIP_WORD.get(e["reason"], e["reason"])} for e in s["skipped"]][:5]}

        def apply(d: dict[str, Any]) -> bool:
            if self._blocked(d, s["sport"], today):
                return False
            d.setdefault("pending", {})[s["sport"]] = sug
            d.setdefault("last", {})[s["sport"]] = today.isoformat()
            return True
        if not self._doc(uid).update(apply):
            return None
        log_event(logger, logging.INFO, "pace_suggested", user_id=uid, sport=s["sport"], direction=s["direction"])
        return sug

    # ------------------------------------------------------------- view --
    def _fresh_pending(self, doc: dict[str, Any], athlete: dict[str, Any], today: date) -> list[dict[str, Any]]:
        out = []
        for sport, p in (doc.get("pending") or {}).items():
            cur = _num(athlete.get(FIELD[sport]))
            try:
                age = (today - date.fromisoformat(p["created"])).days
            except (KeyError, ValueError):
                continue
            stale = age > PENDING_DAYS or (p.get("old") is None) != (cur is None) or (
                cur is not None and int(round(cur)) != int(round(p["old"])))
            if not stale:
                out.append(p)
        return out

    def view(self, uid: str) -> dict[str, Any]:
        athlete = self._athlete(uid)
        doc = self._doc(uid).load()
        today = self._now(uid).date()
        src = doc.get("source") or {}
        rows = {}
        for sport in SPORTS:
            field = FIELD[sport]
            v = _num(athlete.get(field))
            s = src.get(field)
            if s and v is not None and int(round(s.get("value") or -1)) != int(round(v)):
                s = {"how": "manual", "label": "Set by you"}
            elif s is None and v is not None:
                s = {"how": "manual", "label": "Set in your profile"}
            rows[sport] = {"value": v, "zones": zones(sport, v), "source": s if v is not None else None,
                           "suggestions": not (doc.get("never") or {}).get(sport)}
        undo = doc.get("undo")
        if undo and self._clock() >= float(undo.get("until") or 0):
            undo = None
        return {"units": "imperial" if athlete.get("units") != "metric" else "metric",
                "threshold_hr": athlete.get("threshold_hr"), **rows,
                "pending": self._fresh_pending(doc, athlete, today),
                "undo": {k: undo[k] for k in ("id", "sport", "summary", "until")} if undo else None}

    # ---------------------------------------------------------- actions --
    def _pending(self, uid: str, sid: str) -> dict[str, Any]:
        athlete = self._athlete(uid)
        doc = self._doc(uid).load()
        p = next((p for p in self._fresh_pending(doc, athlete, self._now(uid).date()) if p["id"] == sid), None)
        if p is None:
            raise PaceError("That suggestion is no longer current.", 409)
        return p

    def accept(self, uid: str, sid: str) -> dict[str, Any]:
        p = self._pending(uid, sid)
        sport, field, new, old = p["sport"], p["field"], p["new"], p["old"]
        athlete = self._athlete(uid)
        imperial = athlete.get("units") != "metric"
        today = self._now(uid).date()
        prev_source = (self._doc(uid).load().get("source") or {}).get(field)
        self._set_athlete(uid, {field: new})
        rec: dict[str, Any] = {"past": [], "swims": {}, "future": 0}
        if self._edit_plan is not None:
            def fn(plan: dict[str, Any], day: date) -> None:
                rec.update(retarget(plan, sport, old, new, day))
            try:
                self._edit_plan(uid, fn)
            except Exception as e:  # no built plan: the profile change still stands
                log_event(logger, logging.INFO, "pace_no_plan", user_id=uid, error=type(e).__name__)
        n = rec["future"]
        summary = (f"{n} workout{'s' if n != 1 else ''} updated; {preview(sport, new, imperial)} now."
                   if n else f"Updated. New workouts use {fmt_value(sport, new, imperial)}.")
        until = self._clock() + UNDO_S
        uid_ = "u" + secrets.token_hex(5)
        labels = [e["label"] for e in p["efforts"] if e["kind"] != "garmin"][-2:]
        source = {"value": new, "how": "suggested", "date": today.isoformat(),
                  "label": "From " + (" + ".join(labels) if labels else "Garmin's race predictor"),
                  "activity_ids": [e["activity_id"] for e in p["efforts"] if e.get("activity_id")][:6]}

        def apply(d: dict[str, Any]) -> None:
            (d.get("pending") or {}).pop(sport, None)
            d.setdefault("source", {})[field] = source
            d["undo"] = {"id": uid_, "sport": sport, "field": field, "old": old, "new": new, "until": until,
                         "summary": summary, "past": rec["past"], "swims": rec["swims"], "prev_source": prev_source}
        self._doc(uid).update(apply)
        log_event(logger, logging.INFO, "pace_accepted", user_id=uid, sport=sport, updated=n)
        return {"summary": summary, "updated": n, "undo": {"id": uid_, "until": until, "sport": sport},
                "field": field, "value": new}

    def dismiss(self, uid: str, sid: str, *, never: bool = False) -> None:
        p = self._pending(uid, sid)

        def apply(d: dict[str, Any]) -> None:
            (d.get("pending") or {}).pop(p["sport"], None)
            if never:
                d.setdefault("never", {})[p["sport"]] = True
        self._doc(uid).update(apply)

    def set_suggestions(self, uid: str, sport: str, on: bool) -> None:
        if sport not in SPORTS:
            raise PaceError("Unknown sport.")

        def apply(d: dict[str, Any]) -> None:
            nv = d.setdefault("never", {})
            if on:
                nv.pop(sport, None)
            else:
                nv[sport] = True
        self._doc(uid).update(apply)

    def undo(self, uid: str, undo_id: str) -> dict[str, Any]:
        rec = self._doc(uid).load().get("undo")
        if not rec or rec.get("id") != undo_id or self._clock() >= float(rec.get("until") or 0):
            raise PaceError("This change can't be undone any more.", 409)
        sport, field = rec["sport"], rec["field"]
        self._set_athlete(uid, {field: rec["old"]})
        if self._edit_plan is not None and (rec.get("past") or rec.get("swims")):
            try:
                self._edit_plan(uid, lambda plan, day: restore(plan, sport, rec))
            except Exception as e:
                log_event(logger, logging.INFO, "pace_undo_no_plan", user_id=uid, error=type(e).__name__)

        def apply(d: dict[str, Any]) -> None:
            d.pop("undo", None)
            src = d.setdefault("source", {})
            if rec.get("prev_source"):
                src[field] = rec["prev_source"]
            else:
                src.pop(field, None)
        self._doc(uid).update(apply)
        log_event(logger, logging.INFO, "pace_undone", user_id=uid, sport=sport)
        return {"field": field, "value": rec["old"]}


__all__ = ["Paces", "PaceError", "estimate", "run_efforts", "ride_efforts", "swim_efforts", "laps_from_splits",
           "retarget", "restore", "athlete_for", "zones", "headline", "moment_text", "meaningful", "FIELD"]
