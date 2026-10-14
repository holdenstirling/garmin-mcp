"""Finish-time estimates: "Est. 1:52-1:58".

Deterministic and honest about its basis. Inputs (never Oura): the athlete's Garmin
activities, Garmin's race predictor (fallback), and profile thresholds (FTP, CSS, threshold
pace and HR, weight, home elevation, altitude acclimatization, heat tolerance).

Running (road): anchors are recent (120 days) runs of 3 km+ that are fairly flat. Hard
efforts are preferred: Garmin "race" events, names like race/tempo/interval, average HR
close to threshold HR. Easier runs count a little faster than they were run (they weren't
races) and lower the confidence. The 2-3 best anchors are each projected with Riegel
(T2 = T1 x (D2/D1)^1.06) and blended, weighted by hardness, recency and how close their
distance is to the race. No efforts -> Garmin's race predictor -> threshold pace (~ a
one-hour race effort).

Trail/ultra: flat time (ultras: from the marathon equivalent with exponent 1.08-1.15) x a
surface factor, plus climbing time per 100 m that scales with the runner's pace (about 1.5 x
flat pace per km, 4-10 min per 100 m; road climbs 0.8 x), altitude (+3-8% above 2,000 m,
mostly offset when acclimatized or living >= 1,500 m), heat. 100-milers get a wide range,
a hiking-share note and the cutoff margin.

Triathlon: swim from CSS (or recent swims), bike from FTP x an intensity factor by
distance through a power-speed model (CdA 0.30, Crr 0.004, athlete + 9 kg, air density by
elevation, climbing work), run = running prediction x an off-the-bike penalty (+5-12%),
plus T1/T2. Cycling events: same power model with an IF by duration, else recent ride speeds.

``predict()`` returns ``{"kind", "estimate": {"low_s", "mid_s", "high_s"}, "splits"?,
"confidence", "basis", "assumptions", "label"?, "cutoff"?, "text"}``; ``add_projection``
adds ``"projection": {"mid_s", "note"}`` from the plan's forecast fitness. ``estimate`` /
``for_event`` / ``for_race`` keep the compact shape Explore uses (``low/likely/high``).
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

RIEGEL = 1.06
EFFORT_DAYS = 120
BASIS_TTL_S = 3600
MARATHON = 42.195
KM_MI = 1.609344
GARMIN_KEYS = {"time5K": 5.0, "time10K": 10.0, "timeHalfMarathon": 21.0975, "timeMarathon": MARATHON}
NAMED_KM = ((5.0, "5K"), (10.0, "10K"), (21.0975, "half marathon"), (MARATHON, "marathon"))
TRAIL_X = {"road": 1.0, "trail": 1.07, "technical": 1.15}
# Range around the middle estimate by confidence: (below, above).
RANGE = {"high": (0.03, 0.04), "medium": (0.05, 0.06), "low": (0.07, 0.08)}
# Triathlon: (swim km, bike km, run km, T1 s, T2 s, bike IF, run off-the-bike penalty, swim +s/100 m)
TRI = {
    "sprint": (0.75, 20.0, 5.0, 120, 90, 0.90, 1.05, 3),
    "olympic": (1.5, 40.0, 10.0, 150, 105, 0.855, 1.07, 5),
    "70.3": (1.9, 90.0, 21.1, 210, 150, 0.775, 1.10, 7),
    "140.6": (3.8, 180.0, 42.2, 360, 240, 0.705, 1.12, 9),
}
TRI_NAMES = {"sprint": "sprint", "olympic": "Olympic", "70.3": "70.3", "140.6": "full-distance"}
DEFAULT_CSS = 125.0       # s/100 m, a steady age-group swimmer
DEFAULT_FTP_WKG = 2.6     # W/kg, a conservative age-group rider
DEFAULT_WEIGHT = 75.0
BIKE_KIT = 9.0            # bike + kit, kg
RUN_KINDS = {"road", "trail", "ultra", "running", "other", "obstacle", "hike", "mountaineering", "run"}
TRAIL_KINDS = {"trail", "ultra", "hike", "mountaineering"}
TRI_KINDS = {"triathlon", "tri"}
BIKE_KINDS = {"cycling", "gravel", "mtb", "bike", "road_cycling"}
SWIM_KINDS = {"swim", "swimming"}
# Climbing per km assumed from a course profile when there's no climbing total (run, bike).
PROFILE_CLIMB = {"flat": (3, 3), "rolling": (10, 8), "hilly": (20, 15), "mountainous": (40, 25)}
# Known overall cutoffs (hours) by name words, when the race info doesn't list one.
KNOWN_CUTOFFS = ((("leadville", "100"), 30.0), (("western states",), 30.0), (("hardrock",), 48.0),
                 (("wasatch", "100"), 36.0), (("ironman",), 17.0))
HARD_WORDS = re.compile(r"\b(race|racing|tempo|intervals?|threshold|tt|time ?trial|parkrun|track|fartlek|"
                        r"5k|10k|half|marathon|pr|pb|reps|cruise)\b", re.I)
EASY_WORDS = re.compile(r"\b(easy|recovery|shake ?out|jog|long run|z2|zone 2|base)\b", re.I)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --------------------------------------------------------------- helpers --
def riegel(t1: float, d1: float, d2: float, exponent: float = RIEGEL) -> float:
    return t1 * (d2 / d1) ** exponent


def _secs(v: Any) -> float | None:
    """"1:02:03" / "45:10" / 3723 -> seconds."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v) if v > 0 else None
    if isinstance(v, str):
        parts = v.strip().split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        s = 0.0
        for n in nums:
            s = s * 60 + n
        return s if s > 0 else None
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v):
        return float(v)
    return None


def fmt(seconds: float) -> str:
    """3725 -> "1:02", 1290 -> "21:30" (h:mm at or above an hour, m:ss under)."""
    s = int(round(seconds))
    if s >= 3600:
        h, rem = divmod(s, 3600)
        return f"{h}:{rem // 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def fmt_full(seconds: float) -> str:
    """2850 -> "47:30", 6021 -> "1:40:21"."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


def dur(seconds: float) -> str:
    """4420 -> "1 h 14 min", 840 -> "14 min"."""
    m = int(round(seconds / 60))
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _pace(s_per_km: float, imperial: bool) -> str:
    v = s_per_km * KM_MI if imperial else s_per_km
    return f"{int(v) // 60}:{int(v) % 60:02d}/{'mi' if imperial else 'km'}"


def _day(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month - 1]} {d.day}"


def dist_word(km: float, imperial: bool = False) -> str:
    for k, name in NAMED_KM:
        if abs(km - k) <= max(0.3, k * 0.03):
            return name
    if imperial:
        mi = km / KM_MI
        return f"{mi:.0f} mi" if mi >= 10 else f"{mi:.1f} mi"
    return f"{km:.0f} km" if km >= 10 else f"{km:.1f} km"


def _m(v: float, imperial: bool) -> str:
    return f"{int(round(v * 3.28084, -1)):,} ft" if imperial else f"{int(round(v, -1)):,} m"


def _confidence(*cs: str) -> str:
    order = ["high", "medium", "low"]
    return max(cs, key=order.index)


def _down(c: str) -> str:
    return {"high": "medium", "medium": "low", "low": "low"}[c]


# ----------------------------------------------------------------- basis --
def garmin_points(raw: Any) -> list[tuple[float, float]]:
    """``get_race_predictions`` (latest dict, or a daily/monthly list: newest wins)."""
    if isinstance(raw, dict) and isinstance(raw.get("result"), dict | list):
        raw = raw["result"]
    if isinstance(raw, list):
        raw = next((x for x in reversed(raw) if isinstance(x, dict)), {})
    if not isinstance(raw, dict):
        return []
    out = []
    for k, km in GARMIN_KEYS.items():
        t = _num(raw.get(k))
        if t and 0.5 * km * 120 < t < km * 900:  # 2:00/km .. 15:00/km sanity window
            out.append((km, t))
    return out


def hardness(a: dict[str, Any], threshold_hr: float | None) -> float:
    """0..1: how close to a race effort an activity was (race tag, name, HR vs threshold)."""
    if a.get("event") == "race":
        return 1.0
    got: list[float] = []
    hr = _num(a.get("avg_hr"))
    if hr and threshold_hr:
        r = hr / threshold_hr
        got.append(1.0 if r >= 0.97 else 0.85 if r >= 0.92 else 0.6 if r >= 0.87 else 0.3)
    name = str(a.get("name") or "")
    if HARD_WORDS.search(name):
        got.append(0.85)
    elif EASY_WORDS.search(name):
        got.append(0.25)
    return max(got) if got else 0.6


def best_efforts(acts: list[dict[str, Any]], today: date, limit: int = 3,
                 threshold_hr: float | None = None) -> list[dict[str, Any]]:
    """Recent, fairly flat runs of 3 km+, best first by their (hardness-adjusted) Riegel 10K
    equivalent. Easy runs count a little faster than they were run; anchors more than 8%
    off the best are dropped."""
    out = []
    since = today - timedelta(days=EFFORT_DAYS)
    for a in acts or []:
        sport = str(a.get("sport") or "").lower()
        if "run" not in sport or "treadmill" in sport or "virtual" in sport or "indoor" in sport:
            continue
        try:
            d = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        km = _num(a.get("distance_km"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d < since or d > today or not km or km < 3 or km > 60 or not t:
            continue
        pace = t / km
        if not 150 <= pace <= 600:
            continue
        climb = _num(a.get("elevation_gain_m")) or 0.0
        if climb / km > 15:  # hilly runs undersell flat speed
            continue
        flat_t = t * km / (km + 0.008 * climb)  # road climbs ~ 0.8 x pace per 100 m
        h = hardness(a, threshold_hr)
        adj = flat_t * (1 - 0.12 * (1 - h))
        out.append({"km": km, "s": t, "adj_s": adj, "date": d.isoformat(), "race": a.get("event") == "race",
                    "hard": round(h, 2), "name": str(a.get("name") or "")[:60],
                    "eq10": riegel(adj, km, 10.0)})
    out.sort(key=lambda e: e["eq10"])
    if out:
        out = [e for e in out if e["eq10"] <= out[0]["eq10"] * 1.08]
    return out[:limit]


def _swim_paces(acts: list[dict[str, Any]], today: date) -> list[float]:
    """Recent swim paces (s/100 m, whole activity) of 400 m+, best 3."""
    since, out = today - timedelta(days=EFFORT_DAYS), []
    for a in acts or []:
        if "swim" not in str(a.get("sport") or "").lower():
            continue
        try:
            d = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        km = _num(a.get("distance_km"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d < since or d > today or not km or km < 0.4 or not t:
            continue
        p = t / (km * 10)
        if 60 <= p <= 300:
            out.append(p)
    return sorted(out)[:3]


def _rides(acts: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Recent outdoor rides of 20 km+, best 3 by climbing-adjusted speed."""
    since, out = today - timedelta(days=EFFORT_DAYS), []
    for a in acts or []:
        sport = str(a.get("sport") or "").lower()
        if not any(w in sport for w in ("cycl", "bik", "ride", "gravel")) or any(
                w in sport for w in ("virtual", "indoor", "spin", "e_bike", "ebike")):
            continue
        try:
            d = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        km = _num(a.get("distance_km"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d < since or d > today or not km or km < 20 or not t:
            continue
        climb = _num(a.get("elevation_gain_m")) or 0.0
        eff = km + climb / 100 * 1.5
        kmh = eff / (t / 3600)
        if not 10 <= kmh <= 55:
            continue
        out.append({"km": km, "s": t, "eff_km": eff, "kmh": kmh, "date": d.isoformat(),
                    "gravel": "gravel" in sport or "mountain" in sport})
    out.sort(key=lambda r: -r["kmh"])
    return out[:3]


def make_basis(*, garmin: Any = None, acts: list[dict[str, Any]] | None = None,
               athlete: dict[str, Any] | None = None, today: date | None = None) -> dict[str, Any]:
    a = athlete or {}
    today = today or date.today()
    thr = _num(a.get("threshold_hr"))
    return {
        "today": today.isoformat(),
        "garmin": garmin_points(garmin),
        "efforts": best_efforts(acts or [], today, threshold_hr=thr),
        "swims": _swim_paces(acts or [], today),
        "rides": _rides(acts or [], today),
        "threshold_hr": thr,
        "run_threshold_pace": _num(a.get("run_threshold_pace")),
        "ftp_w": _num(a.get("ftp_w")), "swim_css": _num(a.get("swim_css")),
        "weight_kg": _num(a.get("weight_kg")), "home_elevation_m": _num(a.get("home_elevation_m")),
        "altitude_acclimatized": a.get("altitude_acclimatized") is True,
        "heat_tolerance": a.get("heat_tolerance"),
        "imperial": a.get("units") == "imperial",
    }


def has_data(basis: dict[str, Any]) -> bool:
    return bool(basis.get("garmin") or basis.get("efforts") or basis.get("run_threshold_pace")
                or basis.get("ftp_w") or basis.get("swim_css") or basis.get("swims") or basis.get("rides"))


# -------------------------------------------------------------- running --
def _effort_line(e: dict[str, Any], imperial: bool, first: bool) -> str:
    word = dist_word(e["km"], imperial)
    named = word in ("5K", "10K", "half marathon", "marathon")
    what = f"{word} race" if e["race"] else word if named else f"{word} run"
    return f"{'Based on' if first else 'Also'} your {what} in {fmt_full(e['s'])} on {_day(e['date'])}"


def flat_run(basis: dict[str, Any], km: float) -> dict[str, Any] | None:
    """Flat-road running time for ``km``: {"s", "confidence", "basis", "assumptions"}."""
    imperial = bool(basis.get("imperial"))
    efforts = basis.get("efforts") or []
    if efforts:
        try:
            today = date.fromisoformat(basis.get("today") or "")
        except ValueError:
            today = date.today()
        ws = []
        for e in efforts[:3]:
            age = max(0, (today - date.fromisoformat(e["date"])).days)
            w = (0.5 + e["hard"]) * 0.5 ** (age / 60) / (1 + 1.5 * abs(math.log(km / e["km"])))
            ws.append((w, e))
        ws.sort(key=lambda x: -x[0])
        total = sum(w for w, _ in ws)
        t = sum(w * riegel(e["adj_s"], e["km"], km) for w, e in ws) / total
        top = ws[0][1]
        age = (today - date.fromisoformat(top["date"])).days
        ratio = max(km / top["km"], top["km"] / km)
        conf = "high" if top["hard"] >= 0.8 and ratio <= 2.5 and age <= 60 else \
            "medium" if top["hard"] >= 0.6 else "low"
        if ratio > 4.5:
            conf = _down(conf)
        lines = [_effort_line(e, imperial, i == 0) for i, (_, e) in enumerate(ws)]
        assumptions = ["Even pacing on a fair day, Riegel's formula from your effort to this distance"]
        if any(e["hard"] < 0.6 for _, e in ws):
            assumptions.append("Easy runs count a little faster than you ran them, since you weren't racing")
        return {"s": t, "confidence": conf, "basis": lines, "assumptions": assumptions}
    pts = basis.get("garmin") or []
    if pts:
        d1, t1 = min(pts, key=lambda p: abs(math.log(km / p[0])))
        return {"s": riegel(t1, d1, km), "confidence": "medium",
                "basis": [f"Based on Garmin's race predictor ({dist_word(d1)} {fmt_full(t1)})"],
                "assumptions": ["No recent hard runs found, so this leans on your watch's prediction"]}
    pace = basis.get("run_threshold_pace")
    if pace:
        d1 = 3600.0 / pace  # threshold ~ an hour's race effort
        return {"s": riegel(3600.0, d1, km), "confidence": "low",
                "basis": [f"Based on your threshold pace ({_pace(pace, imperial)})"],
                "assumptions": ["Threshold pace is treated as about a one-hour race effort"]}
    return None


def altitude_factor(race_m: float | None, basis: dict[str, Any]) -> tuple[float, str | None]:
    """+3% at 2,000 m rising to +8% at 3,500 m; mostly offset (x0.35) when acclimatized or
    living at 1,500 m+, none when home is within 300 m of the race."""
    if race_m is None or race_m < 2000:
        return 1.0, None
    home = basis.get("home_elevation_m") or 0.0
    if race_m - home < 300:
        return 1.0, None
    pct = 0.03 + 0.05 * min(1.0, (race_m - 2000) / 1500)
    if basis.get("altitude_acclimatized") or home >= 1500:
        pct *= 0.35
    return 1.0 + pct, f"altitude: {int(round(race_m, -1)):,} m"


def heat_factor(hot: bool, basis: dict[str, Any]) -> tuple[float, str | None]:
    if not hot:
        return 1.0, None
    pct = {"low": 0.05, "high": 0.015}.get(str(basis.get("heat_tolerance") or ""), 0.03)
    return 1.0 + pct, "heat"


def _result(kind: str, mid: float, conf: str, basis: list[str], assumptions: list[str], *,
            wide: tuple[float, float] | None = None, label: str | None = None) -> dict[str, Any]:
    lo, hi = wide or RANGE[conf]
    out: dict[str, Any] = {"kind": kind, "estimate": {"low_s": round(mid * (1 - lo)), "mid_s": round(mid),
                                                      "high_s": round(mid * (1 + hi))},
                           "confidence": conf, "basis": basis, "assumptions": assumptions}
    if label:
        out["label"] = label
    out["text"] = text_range(out)
    return out


def predict_run(basis: dict[str, Any], km: float, *, climb_m: float | None = None,
                elevation_m: float | None = None, terrain: str = "road", hot: bool = False,
                trail: bool | None = None) -> dict[str, Any] | None:
    imperial = bool(basis.get("imperial"))
    climb = max(0.0, climb_m or 0.0)
    trail = terrain != "road" if trail is None else trail
    ultra = km > MARATHON + 1
    if ultra:
        base = flat_run(basis, MARATHON)
        if base is None:
            return None
        exp = 1.08 + 0.07 * min(1.0, (km - MARATHON) / 118.0)
        flat = base["s"] * (km / MARATHON) ** exp
        conf = "low" if km > 60 else _down(base["confidence"])
        assumptions = list(base["assumptions"]) + [
            f"Ultra fatigue: marathon equivalent stretched with exponent {exp:.2f}"]
    else:
        base = flat_run(basis, km)
        if base is None:
            return None
        flat, conf, assumptions = base["s"], base["confidence"], list(base["assumptions"])
    lines = list(base["basis"])
    tx = TRAIL_X.get(terrain, 1.0)
    t = flat * tx
    if tx > 1:
        assumptions.append("Technical trail: about 15% slower than road" if terrain == "technical"
                           else "Trail surface: about 7% slower than road")
        conf = _confidence(conf, "medium")
    if climb >= 30:
        p = flat / km
        per100 = min(600.0, max(240.0, 1.5 * p)) if trail or ultra else min(420.0, max(120.0, 0.8 * p))
        add = climb / 100 * per100
        t += add
        assumptions.append(f"Climbing: +{_m(climb, imperial)} adds about {dur(add)} "
                           f"(~{per100 / 60:.0f} min per 100 m, descents included)")
        if climb / km > 20:
            conf = _confidence(conf, "medium")
    af, al = altitude_factor(elevation_m, basis)
    if al:
        t *= af
        offset = basis.get("altitude_acclimatized") or (basis.get("home_elevation_m") or 0) >= 1500
        assumptions.append(f"Altitude ({_m(elevation_m or 0, imperial)}): +{(af - 1) * 100:.0f}%"
                           + (", mostly offset by living/training high" if offset else ""))
        conf = _confidence(conf, "medium")
    hf, hl = heat_factor(hot, basis)
    if hl:
        t *= hf
        assumptions.append(f"Heat: +{(hf - 1) * 100:.0f}%")
    per_km = climb / km
    if trail and (per_km >= 20 or km > 80):
        share = min(0.6, per_km / 100 + (0.15 if km > 80 else 0.05))
        if share >= 0.15:
            assumptions.append(f"Expect to hike about {round(share * 10) * 10}% of the time (steep climbs"
                               f"{', late miles' if km > 80 else ''}); power-hiking well matters as much as running")
    wide = None
    label = None
    if ultra:
        wide = (0.15, 0.30) if km >= 150 else (0.12, 0.25)
        label = "rough guide"
        conf = "low" if km > 60 else conf
    elif trail and climb / km > 25:
        wide = (0.08, 0.12)
    return _result("trail" if trail or ultra else "run", t, conf, lines, assumptions, wide=wide, label=label)


# ------------------------------------------------------------------ bike --
def air_density(elevation_m: float) -> float:
    return 1.225 * math.exp(-max(0.0, elevation_m) / 8500.0)


def bike_speed(power_w: float, mass_kg: float, *, elevation_m: float = 0.0, cda: float = 0.30,
               crr: float = 0.004) -> float:
    """Steady flat-road speed (m/s) for ``power_w`` (3% drivetrain loss):
    P = 0.5 rho CdA v^3 + Crr m g v."""
    rho = air_density(elevation_m)
    p_wheel = power_w * 0.97
    lo, hi = 0.5, 25.0
    for _ in range(60):
        v = (lo + hi) / 2
        p = 0.5 * rho * cda * v ** 3 + crr * mass_kg * 9.81 * v
        lo, hi = (v, hi) if p < p_wheel else (lo, v)
    return (lo + hi) / 2


def bike_time(power_w: float, km: float, climb_m: float, mass_kg: float, elevation_m: float = 0.0,
              cda: float = 0.30, crr: float = 0.004) -> float:
    flat = km * 1000 / bike_speed(power_w, mass_kg, elevation_m=elevation_m, cda=cda, crr=crr)
    # Climbing work, partly paid back on the descents.
    return flat + 0.6 * mass_kg * 9.81 * max(0.0, climb_m) / power_w


def _bike_if(hours: float) -> float:
    return 0.90 if hours < 1 else 0.85 if hours < 2 else 0.78 if hours < 4 else 0.72 if hours < 6 else 0.66


def _surface(kind_word: str) -> tuple[float, float, str | None]:
    """(CdA, Crr, note) by surface."""
    if kind_word == "mtb":
        return 0.42, 0.012, "Mountain bike: upright position and dirt rolling resistance"
    if kind_word == "gravel":
        return 0.36, 0.008, "Gravel: hoods position and loose-surface rolling resistance"
    return 0.32, 0.004, None


def predict_bike(basis: dict[str, Any], km: float, *, climb_m: float | None = None,
                 elevation_m: float | None = None, surface: str = "road", hot: bool = False) -> dict[str, Any] | None:
    imperial = bool(basis.get("imperial"))
    climb = max(0.0, climb_m or 0.0)
    elev = elevation_m or 0.0
    cda, crr, note = _surface(surface)
    assumptions: list[str] = []
    if basis.get("ftp_w"):
        ftp = float(basis["ftp_w"])
        weight = basis.get("weight_kg")
        mass = (weight or DEFAULT_WEIGHT) + BIKE_KIT
        t, intensity = 0.0, 0.9
        for _ in range(4):  # IF depends on duration; settles in a couple of passes
            t = bike_time(ftp * intensity, km, climb, mass, elev, cda=cda, crr=crr)
            intensity = _bike_if(t / 3600)
        t = bike_time(ftp * intensity, km, climb, mass, elev, cda=cda, crr=crr)
        lines = [f"Based on your FTP ({ftp:.0f} W)"]
        assumptions.append(f"Riding at about {intensity * 100:.0f}% of FTP ({ftp * intensity:.0f} W) "
                           f"with CdA {cda:.2f}, Crr {crr:.3f}")
        if not weight:
            assumptions.append(f"No weight in your profile: assumed {DEFAULT_WEIGHT:.0f} kg")
        conf = "medium" if weight else "low"
    elif basis.get("rides"):
        rides = basis["rides"]
        eff_d = km + climb / 100 * 1.5
        r = min(rides, key=lambda x: abs(math.log(eff_d / x["eff_km"])) - x["kmh"] / 100)
        t = r["s"] * (eff_d / r["eff_km"]) ** 1.05 * 0.97
        if surface in ("gravel", "mtb") and not r["gravel"]:
            t *= 1.12 if surface == "gravel" else 1.25
            assumptions.append("Your rides were on the road: dirt adds roughly 12-25%")
        spd = r["km"] / (r["s"] / 3600)
        unit = f"{spd / KM_MI:.1f} mph" if imperial else f"{spd:.1f} km/h"
        lines = [f"Based on your {dist_word(r['km'], imperial)} ride at {unit} on {_day(r['date'])}"]
        assumptions.append("Recent ride speed, slightly faster on race day; drafting and stops make this rough")
        conf = "low"
        note = None if surface == "road" else note
    else:
        return None
    if note:
        assumptions.append(note)
    if climb >= 100:
        assumptions.append(f"Climbing: +{_m(climb, imperial)} (partly paid back on descents)")
    af, al = altitude_factor(elevation_m, basis)
    if al:
        t *= 1 + (af - 1) * 0.6  # thinner air helps aero a little
        assumptions.append(f"Altitude ({_m(elev, imperial)}): less oxygen, partly offset by thinner air")
    hf, hl = heat_factor(hot, basis)
    if hl:
        t *= 1 + (hf - 1) * 0.6
        assumptions.append("Heat: a little slower")
    return _result("bike", t, conf, lines, assumptions)


# ------------------------------------------------------------------ swim --
def _swim_pace(basis: dict[str, Any], add: float) -> tuple[float, str, str]:
    """(s/100 m, basis line, confidence)."""
    imperial = bool(basis.get("imperial"))
    css = basis.get("swim_css")
    if css:
        return css + add, f"Based on your CSS ({int(css) // 60}:{int(css) % 60:02d}/100 m)", "medium"
    swims = basis.get("swims") or []
    if swims:
        p = swims[len(swims) // 2]
        unit = "/100 yd" if imperial else "/100 m"
        return p + add / 2, f"Based on your recent swims (~{int(p) // 60}:{int(p) % 60:02d}{unit} average)", "low"
    return DEFAULT_CSS + add, "Swim: a typical age-group pace (add your CSS for a real number)", "low"


def predict_swim(basis: dict[str, Any], km: float) -> dict[str, Any] | None:
    if not basis.get("swim_css") and not basis.get("swims"):
        return None
    add = 4 if km <= 1.5 else 8 if km <= 4 else 12
    pace, line, conf = _swim_pace(basis, add)
    return _result("swim", pace * km * 10, conf, [line], ["Steady open-water pace with sighting"])


# ------------------------------------------------------------- triathlon --
def tri_format(km: float) -> str | None:
    for name, (lo, hi) in (("sprint", (15, 35)), ("olympic", (45, 60)), ("70.3", (100, 125)), ("140.6", (200, 240))):
        if lo <= km <= hi:
            return name
    return None


def tri_total_km(fmt_: str) -> float:
    s, b, r = TRI[fmt_][:3]
    return s + b + r


def predict_tri(basis: dict[str, Any], fmt_: str, *, climb_m: float | None = None,
                elevation_m: float | None = None, hot: bool = False) -> dict[str, Any] | None:
    if fmt_ not in TRI or not has_data(basis):
        return None
    imperial = bool(basis.get("imperial"))
    swim_km, bike_km, run_km, t1, t2, intensity, penalty, swim_add = TRI[fmt_]
    lines: list[str] = []
    assumptions: list[str] = []
    confs: list[str] = []
    # Swim
    pace, line, c = _swim_pace(basis, swim_add)
    swim = pace * swim_km * 10
    lines.append(line)
    confs.append(c)
    # Bike
    climb = max(0.0, climb_m or 0.0)
    elev = elevation_m or 0.0
    weight = basis.get("weight_kg")
    mass = (weight or DEFAULT_WEIGHT) + BIKE_KIT
    if basis.get("ftp_w"):
        ftp = float(basis["ftp_w"])
        bike = bike_time(ftp * intensity, bike_km, climb, mass, elev, cda=0.30, crr=0.004)
        lines.append(f"Bike: your FTP ({ftp:.0f} W)")
        assumptions.append(f"Bike at {intensity * 100:.0f}% of FTP ({ftp * intensity:.0f} W), "
                           "CdA 0.30, Crr 0.004, flat to rolling")
        confs.append("medium" if weight else "low")
        if not weight:
            assumptions.append(f"No weight in your profile: assumed {DEFAULT_WEIGHT:.0f} kg")
    elif basis.get("rides"):
        b = predict_bike(basis, bike_km, climb_m=climb, elevation_m=None)
        bike = (b or {}).get("estimate", {}).get("mid_s") or bike_km / 28 * 3600
        lines.append("Bike: " + ((b or {}).get("basis") or ["your recent rides"])[0].replace("Based on your", "your"))
        confs.append("low")
    else:
        bike = bike_time(DEFAULT_FTP_WKG * (weight or DEFAULT_WEIGHT) * intensity, bike_km, climb, mass, elev)
        lines.append("Bike: a conservative power guess (add your FTP for a real number)")
        confs.append("low")
    if climb >= 200:
        assumptions.append(f"Bike climbing: +{_m(climb, imperial)}")
    # Run
    base = flat_run(basis, run_km)
    if base:
        run = base["s"] * penalty
        lines.append("Run: " + base["basis"][0].replace("Based on ", ""))
        confs.append("medium")  # threshold pace is how triathletes pace the run anyway
    else:
        run = 390.0 * run_km * penalty  # 6:30/km fallback
        lines.append("Run: a typical age-group pace")
        confs.append("low")
    assumptions.append(f"Run off the bike: +{(penalty - 1) * 100:.0f}% vs a fresh {dist_word(run_km)}")
    assumptions.append(f"Transitions: T1 {fmt(t1)}, T2 {fmt(t2)}")
    x = 1.0
    af, al = altitude_factor(elevation_m, basis)
    if al:
        x *= af
        assumptions.append(f"Altitude ({_m(elev, imperial)}): +{(af - 1) * 100:.0f}%")
    hf, hl = heat_factor(hot, basis)
    if hl:
        x *= hf
        assumptions.append(f"Heat: +{(hf - 1) * 100:.0f}%")
    legs = [("swim", swim * x), ("t1", float(t1)), ("bike", bike * x), ("t2", float(t2)), ("run", run * x)]
    splits = [{"leg": leg, "mid_s": round(s)} for leg, s in legs]
    mid = sum(s["mid_s"] for s in splits)
    conf = "low" if "low" in confs else "medium"
    if fmt_ == "140.6":
        assumptions.append("Full-distance marathons often fade further if the bike is paced too hard")
    out = _result("tri", mid, conf, lines, assumptions, wide=(0.06, 0.10) if conf == "medium" else (0.08, 0.15),
                  label="rough guide" if fmt_ == "140.6" or conf == "low" else None)
    out["splits"] = splits
    out["format"] = fmt_
    return out


# --------------------------------------------------------------- dispatch --
def kind_of(type_: Any) -> str | None:
    t = str(type_ or "").strip().lower()
    if t in TRI_KINDS:
        return "tri"
    if t in BIKE_KINDS:
        return "bike"
    if t in SWIM_KINDS:
        return "swim"
    if t in RUN_KINDS or not t:
        return "run"
    return None


def predict(basis: dict[str, Any], *, distance_km: float | None, type_: Any = None, climb_m: float | None = None,
            elevation_m: float | None = None, terrain: str | None = None, hot: bool = False,
            tri: str | None = None) -> dict[str, Any] | None:
    """The full estimate (see module doc), or None when it can't be made."""
    kind = kind_of(type_)
    t = str(type_ or "").lower()
    if kind == "tri":
        fmt_ = tri or (tri_format(distance_km) if distance_km else None)
        return predict_tri(basis, fmt_, climb_m=climb_m, elevation_m=elevation_m, hot=hot) if fmt_ else None
    if not distance_km or distance_km <= 0 or distance_km > 1000:
        return None
    if kind == "bike":
        surface = t if t in ("gravel", "mtb") else "road"
        return predict_bike(basis, distance_km, climb_m=climb_m, elevation_m=elevation_m, surface=surface, hot=hot)
    if kind == "swim":
        return predict_swim(basis, distance_km)
    if kind == "run":
        if distance_km < 1:
            return None
        trail = t in TRAIL_KINDS or terrain in ("trail", "technical")
        ter = terrain or ("trail" if trail else "road")
        return predict_run(basis, distance_km, climb_m=climb_m, elevation_m=elevation_m, terrain=ter, hot=hot,
                           trail=trail)
    return None


def text_range(res: dict[str, Any] | None) -> str:
    """"1:52–1:58" (long rough guides: "22–28 h")."""
    if not res:
        return ""
    e = res["estimate"]
    if res.get("label") == "rough guide" and e["mid_s"] >= 6 * 3600:
        return f"{e['low_s'] / 3600:.0f}–{e['high_s'] / 3600:.0f} h"
    return f"{fmt(e['low_s'])}–{fmt(e['high_s'])}"


# ----------------------------------------------------------- events/cutoff --
_TRI_WORDS = (("140.6", "140.6"), ("full ironman", "140.6"), ("70.3", "70.3"), ("half ironman", "70.3"),
              ("half-ironman", "70.3"), ("olympic", "olympic"), ("sprint", "sprint"), ("ironman", "140.6"))
_RUN_NAMED = {"5k": 5.0, "10k": 10.0, "half marathon": 21.0975, "marathon": MARATHON}


def event_tri_format(event: dict[str, Any]) -> str | None:
    key = str(event.get("distance") or "").lower()
    blob = " ".join(str(x) for x in (key, event.get("name"), (event.get("info") or {}).get("distances")) if x).lower()
    for word, f in _TRI_WORDS:
        if word in blob:
            return f
    return None


def cutoff_hours(event: dict[str, Any], km: float | None = None) -> float | None:
    """The overall cutoff in hours from the looked-up info ("30 hours", "30:00"), else a
    known race by name."""
    txt = str((event.get("info") or {}).get("cutoffs") or "")
    hours = [float(m.group(1)) for m in re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*-?\s*(?:h\b|hrs?\b|hours?\b)", txt, re.I)]
    hours += [int(m.group(1)) + int(m.group(2)) / 60 for m in re.finditer(r"\b(\d{1,2}):(\d{2})\b(?!\s*[ap]\.?m)", txt, re.I)
              if int(m.group(1)) >= 2]
    hours = [h for h in hours if 0.5 <= h <= 200]
    if hours:
        return max(hours)
    name = str(event.get("name") or "").lower()
    for words, h in KNOWN_CUTOFFS:
        if all(w in name for w in words):
            if words == ("ironman",) and ("70.3" in name or (km and km < 200)):
                continue
            return h
    return None


def event_inputs(event: dict[str, Any]) -> dict[str, Any]:
    """Event (events.py shape + looked-up ``info``) -> predict() kwargs + extra assumptions."""
    from . import racefit
    etype = str(event.get("type") or "").lower()
    key = str(event.get("distance") or "").lower()
    notes: list[str] = []
    out: dict[str, Any] = {"type_": etype}
    tri = event_tri_format(event) if etype in ("triathlon", "tri") else None
    if tri:
        out["tri"] = tri
        km: float | None = tri_total_km(tri)
    elif key in _RUN_NAMED and etype in ("running", "road", "trail", "run", ""):
        km = _RUN_NAMED[key]
    else:
        def parsed(text: Any) -> float | None:
            vals = [float(m.group(1)) * (KM_MI if m.group(2).lower().startswith("mi") else 1)
                    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(km|k|mi|miles?)\b", str(text or ""), re.I)]
            return max(vals) if vals else None
        # The athlete's own event distance wins; the looked-up info often lists several
        # distances (a 50K race page that also has a 100-miler) so its longest is a last resort.
        own = _num(event.get("distance_km")) or parsed(event.get("distance"))
        info_km = parsed((event.get("info") or {}).get("distances"))
        km = own or info_km or racefit._distance_km(event)
        if not own and not info_km and key == "ultra":
            notes.append("No distance on this race yet: assumed 80 km (look it up to sharpen this)")
    out["distance_km"] = km
    gain = racefit._gain_m(event)
    if gain is None and km and event.get("course_profile") in PROFILE_CLIMB:
        run_c, bike_c = PROFILE_CLIMB[event["course_profile"]]
        leg_km = TRI[tri][1] if tri else km
        gain = (bike_c if etype in ("cycling", "triathlon") else run_c) * leg_km
        if gain >= 30:
            notes.append(f"Climbing guessed from a {event['course_profile']} course")
    out["climb_m"] = gain
    elev = racefit.race_elevation(event)
    out["elevation_m"] = (elev or {}).get("m")
    out["hot"] = racefit._hot_cold(event)[0]
    blob = " ".join(str(x) for x in (event.get("course"), (event.get("info") or {}).get("terrain")) if x).lower()
    if re.search(r"technical|scree|scrambl|rocky|rooty", blob):
        out["terrain"] = "technical"
    elif etype == "cycling" and re.search(r"gravel|unbound|dirt", blob + " " + str(event.get("name") or "").lower()):
        out["type_"] = "gravel"
    return {"kwargs": out, "notes": notes}


def predict_event(basis: dict[str, Any], event: dict[str, Any], *, load: dict[str, Any] | None = None,
                  today: date | None = None) -> dict[str, Any] | None:
    """A calendar event -> the full estimate (+ cutoff and the plan projection)."""
    got = event_inputs(event)
    res = predict(basis, **got["kwargs"])
    if res is None:
        return None
    if got["notes"]:
        res["assumptions"] = got["notes"] + res["assumptions"]
        res["confidence"] = "low"
    cut = cutoff_hours(event, got["kwargs"].get("distance_km"))
    if cut:
        add_cutoff(res, cut * 3600)
    if load is not None and event.get("date"):
        add_projection(res, load, event["date"], today or date.today())
    return res


def add_cutoff(res: dict[str, Any], cutoff_s: float) -> dict[str, Any]:
    e = res["estimate"]
    margin = cutoff_s - e["mid_s"]
    res["cutoff"] = {"s": round(cutoff_s), "margin_s": round(margin),
                     "status": "safe" if e["high_s"] <= cutoff_s else "tight" if margin > 0 else "over"}
    return res


def add_projection(res: dict[str, Any], load: dict[str, Any], race_date: str, today: date) -> dict[str, Any]:
    """"If you follow your plan": +1% speed per +3 fitness (CTL) by race day, capped at 8%.
    Only for races more than 4 weeks away with a plan forecast on that day."""
    try:
        days = (date.fromisoformat(race_date) - today).days
    except ValueError:
        return res
    if days <= 28 or not load.get("has_plan"):
        return res
    now = (load.get("now") or {}).get("ctl")
    point = next((p for p in load.get("series") or [] if p.get("date") == race_date and p.get("planned")), None)
    if now is None or point is None:
        return res
    delta = float(point["ctl"]) - float(now)
    if delta < 1.5:
        return res
    gain = min(0.08, delta / 3 * 0.01)
    mid = round(res["estimate"]["mid_s"] * (1 - gain))
    res["projection"] = {
        "mid_s": mid, "ctl_now": round(float(now)), "ctl_race": round(float(point["ctl"])),
        "gain_pct": round(gain * 100, 1),
        "note": (f"If you follow your plan, fitness goes from {float(now):.0f} to {float(point['ctl']):.0f} by "
                 f"race day: worth about {gain * 100:.0f}%, so ~{fmt(mid)}. A projection, not a promise."),
    }
    return res


# ------------------------------------------------------- compact (Explore) --
def compact(res: dict[str, Any] | None) -> dict[str, Any] | None:
    """The compact shape Explore cards use: low/likely/high + basis (+ legacy splits dict)."""
    if not res:
        return None
    e = res["estimate"]
    out: dict[str, Any] = {"kind": "run" if res["kind"] == "trail" else res["kind"], "likely": e["mid_s"],
                           "low": e["low_s"], "high": e["high_s"], "basis": res["basis"],
                           "confidence": res["confidence"]}
    if res.get("label"):
        out["label"] = res["label"]
    if res.get("splits"):
        sp = {s["leg"]: s["mid_s"] for s in res["splits"]}
        out["splits"] = {"swim": sp["swim"], "bike": sp["bike"], "run": sp["run"], "transitions": sp["t1"] + sp["t2"]}
    return out


def response(res: dict[str, Any]) -> dict[str, Any]:
    """API body: the full estimate, with the compact keys inside ``estimate`` too."""
    c = compact(res) or {}
    return {**res, "estimate": {**c, **res["estimate"], "text": res["text"]}}


def estimate(basis: dict[str, Any], *, distance_km: float | None, type_: Any = None, climb_m: float | None = None,
             elevation_m: float | None = None, terrain: str | None = None, hot: bool = False) -> dict[str, Any] | None:
    return compact(predict(basis, distance_km=distance_km, type_=type_, climb_m=climb_m, elevation_m=elevation_m,
                           terrain=terrain, hot=hot))


def text(est: dict[str, Any] | None) -> str:
    """Compact estimate -> "1:52–2:01" (long rough guides: "22–28 h")."""
    if not est:
        return ""
    if est.get("label") == "rough guide" and est["likely"] >= 6 * 3600:
        return f"{est['low'] / 3600:.0f}–{est['high'] / 3600:.0f} h"
    return f"{fmt(est['low'])}–{fmt(est['high'])}"


def for_event(basis: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    """A calendar event -> the compact estimate."""
    return compact(predict_event(basis, event))


def for_race(basis: dict[str, Any], race: dict[str, Any], prefer: set[str] | None = None) -> dict[str, Any] | None:
    """An Explore race (picks the event that matches ``prefer`` buckets, else the first with a
    distance) -> the compact estimate plus its ``text`` and ``event`` label."""
    from .foryou import event_bucket
    evs = [e for e in race.get("events") or [] if isinstance(e.get("distance_km"), int | float)]
    if not evs:
        return None
    ev = next((e for e in evs if prefer and event_bucket(e) in prefer), evs[0])
    from .racefit import KNOWN_PLACES
    alt = KNOWN_PLACES.get(str(race.get("city") or "").strip().lower())
    est = estimate(basis, distance_km=float(ev["distance_km"]), type_=ev.get("type"),
                   elevation_m=alt[0] if alt else None)
    if not est:
        return None
    return {**est, "text": text(est), "event": str(ev.get("distance_label") or ev.get("name") or "")[:30]}


# ----------------------------------------------------------------- cache --
CACHE_MAX = 2000


class BasisCache:
    """Per-user basis for an hour (one Garmin predictor read + the cached activity year)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._d: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, uid: str, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            hit = self._d.get(uid)
        if hit and now - hit[0] < BASIS_TTL_S:
            return hit[1]
        b = build()
        with self._lock:
            self._d.pop(uid, None)
            self._d[uid] = (now, b)
            while len(self._d) > CACHE_MAX:  # oldest written first
                self._d.pop(next(iter(self._d)))
        return b

    def drop(self, uid: str) -> None:
        with self._lock:
            self._d.pop(uid, None)


__all__ = ["BasisCache", "add_cutoff", "add_projection", "best_efforts", "bike_speed", "compact", "cutoff_hours",
           "estimate", "flat_run", "fmt", "for_event", "for_race", "garmin_points", "hardness", "has_data",
           "kind_of", "make_basis", "predict", "predict_event", "predict_run", "predict_tri", "response",
           "riegel", "text", "text_range"]
