"""Finish-time estimates: "Your estimate: 1:52-2:01".

Deterministic and honest about its basis. Inputs (never Oura):

- Garmin's race predictor (``get_race_predictions``: 5K / 10K / half / marathon), when the
  watch has one;
- else the athlete's recent best running efforts (Garmin activities, last 120 days, fairly
  flat, the best Riegel-equivalent ones; race-tagged efforts preferred);
- else the profile's threshold pace (roughly a one-hour race pace).

Running time = Riegel (t2 = t1 x (d2/d1)^1.06) on an "effort distance" that counts climbing
(ITRA-style: every 100 m of gain ~ 1 flat km), then course multipliers: trail technicality,
altitude (race elevation >= 1,500 m and well above home) and heat. Ultras use a steeper
exponent from the marathon equivalent, a wide range and the label "rough guide".

Triathlon: swim from CSS, bike from FTP via a simple power model (an intensity factor by
distance, flat-road aero + rolling resistance, plus the work of climbing), run from threshold
pace x a fatigue factor (or the running estimate), plus transitions. Missing pieces use
conservative age-group defaults and lower the confidence.

Output: ``{"low", "high", "likely"`` (seconds), ``"basis": [...], "confidence":
"high"|"medium"|"low", "label"?: "rough guide", "kind"}``.
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
GARMIN_KEYS = {"time5K": 5.0, "time10K": 10.0, "timeHalfMarathon": 21.0975, "timeMarathon": MARATHON}
NAMED_KM = ((5.0, "5K"), (10.0, "10K"), (21.0975, "half marathon"), (MARATHON, "marathon"))
TRAIL_X = {"road": 1.0, "trail": 1.07, "technical": 1.15}
# Triathlon formats: (swim km, bike km, run km, transitions s, bike IF, run fatigue factor, swim +s/100m)
TRI = {
    "sprint": (0.75, 20.0, 5.0, 240, 0.90, 1.04, 5),
    "olympic": (1.5, 40.0, 10.0, 300, 0.85, 1.06, 6),
    "70.3": (1.9, 90.0, 21.1, 420, 0.77, 1.12, 8),
    "140.6": (3.8, 180.0, 42.2, 720, 0.70, 1.25, 10),
}
DEFAULT_CSS = 125.0       # s/100 m, a steady age-group swimmer
DEFAULT_FTP_WKG = 2.6     # W/kg, a conservative age-group rider
DEFAULT_WEIGHT = 75.0
RUN_KINDS = {"road", "trail", "ultra", "running", "other", "obstacle", "hike", "mountaineering", "run"}
TRI_KINDS = {"triathlon", "tri"}
BIKE_KINDS = {"cycling", "gravel", "mtb", "bike", "road_cycling"}
SWIM_KINDS = {"swim", "swimming"}


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
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def fmt(seconds: float) -> str:
    """3725 -> "1:02", 1290 -> "21:30" (h:mm at or above an hour, m:ss under)."""
    s = int(round(seconds))
    if s >= 3600:
        h, rem = divmod(s, 3600)
        return f"{h}:{rem // 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def dist_word(km: float) -> str:
    for k, name in NAMED_KM:
        if abs(km - k) <= max(0.3, k * 0.03):
            return name
    return f"{km:.0f} km" if km >= 10 else f"{km:.1f} km"


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


def best_efforts(acts: list[dict[str, Any]], today: date, limit: int = 3) -> list[dict[str, Any]]:
    """Recent, fairly flat runs of 3 km+, best by their Riegel 10K equivalent."""
    out = []
    since = today - timedelta(days=EFFORT_DAYS)
    for a in acts or []:
        sport = str(a.get("sport") or "").lower()
        if "run" not in sport or "treadmill" in sport:
            continue
        try:
            d = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        km = _num(a.get("distance_km"))
        t = _secs(a.get("moving_duration")) or _secs(a.get("duration"))
        if d < since or d > today or not km or km < 3 or not t:
            continue
        pace = t / km
        if not 150 <= pace <= 600:
            continue
        climb = _num(a.get("elevation_gain_m")) or 0.0
        if climb / km > 15:  # hilly runs undersell flat speed
            continue
        eq10 = riegel(t, km, 10.0)
        race = a.get("event") == "race"
        out.append({"km": km, "s": t, "date": d.isoformat(), "race": race, "eq10": eq10 * (0.97 if race else 1.0)})
    out.sort(key=lambda e: e["eq10"])
    return out[:limit]


def make_basis(*, garmin: Any = None, acts: list[dict[str, Any]] | None = None,
               athlete: dict[str, Any] | None = None, today: date | None = None) -> dict[str, Any]:
    a = athlete or {}
    return {
        "garmin": garmin_points(garmin),
        "efforts": best_efforts(acts or [], today or date.today()),
        "run_threshold_pace": _num(a.get("run_threshold_pace")),
        "ftp_w": _num(a.get("ftp_w")), "swim_css": _num(a.get("swim_css")),
        "weight_kg": _num(a.get("weight_kg")), "home_elevation_m": _num(a.get("home_elevation_m")),
        "altitude_acclimatized": a.get("altitude_acclimatized") is True,
        "heat_tolerance": a.get("heat_tolerance"),
    }


# -------------------------------------------------------------- running --
def _flat_run(basis: dict[str, Any], km: float) -> tuple[float, str, str] | None:
    """(seconds, basis line, confidence) on a flat road for ``km``."""
    pts = basis.get("garmin") or []
    if pts:
        d1, t1 = min(pts, key=lambda p: abs(math.log(km / p[0])))
        conf = "high" if km <= MARATHON * 1.02 else "medium"
        return riegel(t1, d1, km), "Garmin race predictor", conf
    efforts = basis.get("efforts") or []
    if efforts:
        e = min(efforts[:3], key=lambda x: abs(math.log(km / x["km"])) + (x["eq10"] / efforts[0]["eq10"] - 1) * 4)
        far = abs(math.log(km / e["km"])) > math.log(3)
        word = dist_word(e["km"])
        line = f"your recent {word}" if word in ("5K", "10K", "half marathon", "marathon") else f"your recent {word} run"
        return riegel(e["s"], e["km"], km), line, "medium" if not far else "low"
    pace = basis.get("run_threshold_pace")
    if pace:
        d1 = 3600.0 / pace  # threshold ~ an hour's race effort
        return riegel(3600.0, d1, km), "your threshold pace", "low"
    return None


def altitude_factor(race_m: float | None, basis: dict[str, Any]) -> tuple[float, str | None]:
    if race_m is None or race_m < 1500:
        return 1.0, None
    home = basis.get("home_elevation_m") or 0.0
    if race_m - home < 300:
        return 1.0, None
    pct = 0.04 * (race_m - max(home, 1000.0)) / 1000.0
    if basis.get("altitude_acclimatized"):
        pct /= 3
    return 1.0 + max(0.0, pct), f"altitude: {int(round(race_m, -1)):,} m"


def heat_factor(hot: bool, basis: dict[str, Any]) -> tuple[float, str | None]:
    if not hot:
        return 1.0, None
    pct = {"low": 0.05, "high": 0.015}.get(str(basis.get("heat_tolerance") or ""), 0.03)
    return 1.0 + pct, "heat"


def _confidence(*cs: str) -> str:
    order = ["high", "medium", "low"]
    return max(cs, key=order.index)


def estimate_run(basis: dict[str, Any], km: float, *, climb_m: float | None = None, elevation_m: float | None = None,
                 terrain: str = "road", hot: bool = False) -> dict[str, Any] | None:
    climb = max(0.0, climb_m or 0.0)
    eff = km + climb / 100.0  # ITRA-style effort distance
    ultra = km > MARATHON + 1 or eff > 55
    if ultra:
        base = _flat_run(basis, MARATHON)
        if base is None:
            return None
        t_mar, line, _ = base
        exp = 1.08 + 0.07 * min(1.0, (eff - MARATHON) / 120.0)
        t = t_mar * (eff / MARATHON) ** exp
        conf = "low"
        line = f"{line} (marathon equivalent)"
    else:
        base = _flat_run(basis, eff)
        if base is None:
            return None
        t, line, conf = base
    lines = [line]
    if climb >= 50:
        lines.append(f"course: +{int(round(climb, -1)):,} m climbing")
        if climb / max(km, 1) > 20 and conf == "high":
            conf = "medium"
    tx = TRAIL_X.get(terrain, 1.0)
    if tx > 1:
        t *= tx
        lines.append("technical trail" if terrain == "technical" else "trail surface")
        conf = _confidence(conf, "medium")
    af, al = altitude_factor(elevation_m, basis)
    if al:
        t *= af
        lines.append(al)
        conf = _confidence(conf, "medium")
    hf, hl = heat_factor(hot, basis)
    if hl:
        t *= hf
        lines.append(hl)
    lo_pct, hi_pct = {"high": (0.03, 0.04), "medium": (0.05, 0.07), "low": (0.10, 0.18)}[conf]
    if ultra:
        lo_pct, hi_pct = 0.12, 0.25
    out = {"kind": "run", "likely": round(t), "low": round(t * (1 - lo_pct)), "high": round(t * (1 + hi_pct)),
           "basis": lines, "confidence": conf}
    if ultra:
        out["label"] = "rough guide"
    return out


# ------------------------------------------------------------------ bike --
def bike_speed(power_w: float, mass_kg: float, *, elevation_m: float = 0.0, cda: float = 0.32,
               crr: float = 0.005) -> float:
    """Steady flat-road speed (m/s) for ``power_w``: P = 0.5 rho CdA v^3 + Crr m g v."""
    rho = 1.225 * math.exp(-max(0.0, elevation_m) / 8500.0)
    lo, hi = 0.5, 25.0
    for _ in range(60):
        v = (lo + hi) / 2
        p = 0.5 * rho * cda * v ** 3 + crr * mass_kg * 9.81 * v
        lo, hi = (v, hi) if p < power_w else (lo, v)
    return (lo + hi) / 2


def bike_time(power_w: float, km: float, climb_m: float, mass_kg: float, elevation_m: float = 0.0,
              cda: float = 0.32) -> float:
    flat = km * 1000 / bike_speed(power_w, mass_kg, elevation_m=elevation_m, cda=cda)
    # Climbing work, partly paid back on the descents.
    return flat + 0.6 * mass_kg * 9.81 * max(0.0, climb_m) / power_w


def _ftp(basis: dict[str, Any]) -> tuple[float, bool]:
    if basis.get("ftp_w"):
        return float(basis["ftp_w"]), True
    return DEFAULT_FTP_WKG * (basis.get("weight_kg") or DEFAULT_WEIGHT), False


def estimate_bike(basis: dict[str, Any], km: float, *, climb_m: float | None = None,
                  elevation_m: float | None = None) -> dict[str, Any] | None:
    if not basis.get("ftp_w"):
        return None
    ftp, _ = _ftp(basis)
    mass = (basis.get("weight_kg") or DEFAULT_WEIGHT) + 9
    t = 0.0
    for intensity in (0.80, 0.75, 0.70, 0.65):  # longer rides, lower intensity
        t = bike_time(ftp * intensity, km, climb_m or 0.0, mass, elevation_m or 0.0)
        if t <= {0.80: 2, 0.75: 4, 0.70: 7, 0.65: 1e9}[intensity] * 3600:
            break
    lines = ["your FTP"]
    if (climb_m or 0) >= 100:
        lines.append(f"course: +{int(round(climb_m or 0, -1)):,} m climbing")
    af, al = altitude_factor(elevation_m, basis)
    if al:
        t *= 1 + (af - 1) * 0.6  # thinner air helps aero a little
        lines.append(al)
    return {"kind": "bike", "likely": round(t), "low": round(t * 0.93), "high": round(t * 1.10),
            "basis": lines, "confidence": "medium"}


# ------------------------------------------------------------------ swim --
def estimate_swim(basis: dict[str, Any], km: float) -> dict[str, Any] | None:
    css = basis.get("swim_css")
    if not css:
        return None
    pace = css + (4 if km <= 1.5 else 8 if km <= 4 else 12)
    t = pace * km * 10
    return {"kind": "swim", "likely": round(t), "low": round(t * 0.95), "high": round(t * 1.08),
            "basis": ["your CSS pace"], "confidence": "medium"}


# ------------------------------------------------------------- triathlon --
def tri_format(km: float) -> str | None:
    for name, (lo, hi) in (("sprint", (15, 35)), ("olympic", (45, 60)), ("70.3", (100, 125)), ("140.6", (200, 240))):
        if lo <= km <= hi:
            return name
    return None


def estimate_tri(basis: dict[str, Any], km: float, *, climb_m: float | None = None,
                 elevation_m: float | None = None, hot: bool = False) -> dict[str, Any] | None:
    fmt_ = tri_format(km)
    if fmt_ is None:
        return None
    swim_km, bike_km, run_km, trans, intensity, run_x, swim_add = TRI[fmt_]
    lines, have = [], 0
    css = basis.get("swim_css")
    swim = ((css or DEFAULT_CSS) + swim_add) * swim_km * 10
    lines.append("swim: your CSS" if css else "swim: typical age-group pace")
    have += bool(css)
    ftp, real_ftp = _ftp(basis)
    mass = (basis.get("weight_kg") or DEFAULT_WEIGHT) + 9
    bike = bike_time(ftp * intensity, bike_km, climb_m or 0.0, mass, elevation_m or 0.0, cda=0.30)
    lines.append("bike: your FTP" if real_ftp else "bike: conservative power guess")
    have += real_ftp
    pace = basis.get("run_threshold_pace")
    if pace:
        run = pace * run_km * run_x
        lines.append("run: your threshold pace")
        have += 1
    else:
        flat = _flat_run(basis, run_km)
        run = (flat[0] * run_x) if flat else 390.0 * run_km * run_x  # 6:30/km fallback
        lines.append(f"run: {flat[1]}" if flat else "run: typical age-group pace")
        have += bool(flat)
    t = swim + bike + run + trans
    af, al = altitude_factor(elevation_m, basis)
    if al:
        t *= af
        lines.append(al)
    hf, hl = heat_factor(hot, basis)
    if hl:
        t *= hf
        lines.append(hl)
    if (climb_m or 0) >= 200:
        lines.append(f"course: +{int(round(climb_m or 0, -1)):,} m climbing")
    conf = "medium" if have == 3 else "low"
    lo_pct, hi_pct = (0.05, 0.08) if conf == "medium" else (0.10, 0.18)
    out = {"kind": "tri", "likely": round(t), "low": round(t * (1 - lo_pct)), "high": round(t * (1 + hi_pct)),
           "basis": lines, "confidence": conf,
           "splits": {"swim": round(swim), "bike": round(bike), "run": round(run), "transitions": trans}}
    if fmt_ == "140.6" or conf == "low":
        out["label"] = "rough guide"
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


def estimate(basis: dict[str, Any], *, distance_km: float | None, type_: Any = None, climb_m: float | None = None,
             elevation_m: float | None = None, terrain: str | None = None, hot: bool = False) -> dict[str, Any] | None:
    if not distance_km or distance_km <= 0 or distance_km > 1000:
        return None
    kind = kind_of(type_)
    if kind == "tri":
        return estimate_tri(basis, distance_km, climb_m=climb_m, elevation_m=elevation_m, hot=hot)
    if kind == "bike":
        return estimate_bike(basis, distance_km, climb_m=climb_m, elevation_m=elevation_m)
    if kind == "swim":
        return estimate_swim(basis, distance_km)
    if kind == "run":
        if distance_km < 1:
            return None
        ter = terrain or ("trail" if str(type_ or "").lower() in ("trail", "ultra", "hike", "mountaineering") else "road")
        return estimate_run(basis, distance_km, climb_m=climb_m, elevation_m=elevation_m, terrain=ter, hot=hot)
    return None


def text(est: dict[str, Any] | None) -> str:
    """"1:52-2:01" (ultras: "22-28 h")."""
    if not est:
        return ""
    if est.get("label") == "rough guide" and est["likely"] >= 6 * 3600:
        return f"{est['low'] / 3600:.0f}–{est['high'] / 3600:.0f} h"
    return f"{fmt(est['low'])}–{fmt(est['high'])}"


def for_event(basis: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    """A calendar event (events.py shape, with looked-up ``info``) -> an estimate."""
    from . import racefit
    km = racefit._distance_km(event)
    if km is None:
        km = _num(event.get("distance_km"))
    climb = racefit._gain_m(event)
    elev = racefit.race_elevation(event)
    hot, _ = racefit._hot_cold(event)
    blob = " ".join(str(x) for x in (event.get("course"), (event.get("info") or {}).get("terrain")) if x).lower()
    terrain = "technical" if re.search(r"technical|scree|scrambl|rocky|rooty", blob) else None
    return estimate(basis, distance_km=km, type_=event.get("type"), climb_m=climb,
                    elevation_m=(elev or {}).get("m"), terrain=terrain, hot=hot)


def for_race(basis: dict[str, Any], race: dict[str, Any], prefer: set[str] | None = None) -> dict[str, Any] | None:
    """An Explore race (picks the event that matches ``prefer`` buckets, else the first with a
    distance) -> the estimate plus its ``text`` and ``event`` label."""
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
            self._d[uid] = (now, b)
            if len(self._d) > 2000:
                self._d.pop(next(iter(self._d)))
        return b

    def drop(self, uid: str) -> None:
        with self._lock:
            self._d.pop(uid, None)


def has_data(basis: dict[str, Any]) -> bool:
    return bool(basis.get("garmin") or basis.get("efforts") or basis.get("run_threshold_pace")
                or basis.get("ftp_w") or basis.get("swim_css"))


__all__ = ["BasisCache", "best_efforts", "bike_speed", "estimate", "estimate_run", "estimate_tri", "fmt",
           "for_event", "for_race", "garmin_points", "has_data", "kind_of", "make_basis", "riegel", "text"]
