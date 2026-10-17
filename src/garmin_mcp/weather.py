"""Weather-aware workouts: a 72-hour hourly forecast for the athlete's area and deterministic
adjustments for heat, cold, wind, altitude, rain/snow/storms and air quality.

Forecast: Open-Meteo (no key). Coordinates come from the athlete's saved location when there is
one, otherwise their home city is geocoded. One call per rounded location is cached for
``CACHE_S``; any failure returns None and the app simply shows no weather. ``RABBIT_FAKE_WEATHER=1``
(dev only) returns a deterministic forecast so screens can be reviewed offline.

Adjustments (rules of thumb, display only; the stored plan never changes):

* Heat: temperature + dew point in °F. Up to 100 nothing; then the run pace slows on a sliding
  scale (110: +0.5%, 120: +1%, 130: +2%, 140: +3%, 150: +4.5%, 160: +6%, 170: +8%, 180: +10%);
  above 180 hard running isn't advised: easy effort by heart rate, or move it.
* Cold: below 0 °C a longer warm-up and layers; below -10 °C (feels-like) +2% and cover skin.
* Wind: from 25 km/h (or gusts from 40) run by effort (+1% from 30 km/h); rides hold power and
  accept a slower speed.
* Altitude: compared with where the athlete normally trains (their home elevation, or the
  forecast location when unknown): +1% per 300 m above that, from 300 m higher, halved when
  acclimatized. At 1500 m and up: heart rate runs higher, so run by effort.
* Rain, snow, freezing rain and thunderstorms: safety notes (storms: wait or go indoors).
* Air quality (US AQI): over 100 easy for sensitive people; over 150 keep it easy or go indoors.

Pool swims and strength sessions aren't adjusted. "Best time to go" scores each daylight hour in
the athlete's window (heat, wind, rain chance, storms) for the session's length and suggests the
best one when it is clearly better than the planned start.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx2

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL = "https://api.open-meteo.com/v1/forecast"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CACHE_S = 45 * 60
MAX_CACHE = 300
HOURS = 72
WINDOW = (5, 21)  # usual training hours when the session has no start time

WX_CODES = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
            51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
            61: "Rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
            71: "Snow", 73: "Snow", 75: "Heavy snow", 77: "Snow", 80: "Showers", 81: "Showers",
            82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms",
            96: "Thunderstorms", 99: "Thunderstorms"}
STORM = {95, 96, 99}
ICY = {56, 57, 66, 67, 71, 73, 75, 77, 85, 86}
WET = {51, 53, 55, 61, 63, 65, 80, 81, 82}

# (temp °F + dew point °F, % slower)
HEAT = [(100, 0.0), (110, 0.5), (120, 1.0), (130, 2.0), (140, 3.0), (150, 4.5), (160, 6.0), (170, 8.0), (180, 10.0)]

_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _f(c: float) -> float:
    return c * 9 / 5 + 32


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


# --------------------------------------------------------------- forecast --
def _shape(body: dict[str, Any], aq: dict[str, Any] | None, place: str) -> dict[str, Any]:
    h = body.get("hourly") or {}
    times = h.get("time") or []

    def pick(src: dict[str, Any], k: str, i: int) -> Any:
        arr = src.get(k) or []
        return arr[i] if i < len(arr) else None
    aqi_by_t: dict[str, Any] = {}
    if aq:
        ah = aq.get("hourly") or {}
        for i, t in enumerate(ah.get("time") or []):
            aqi_by_t[str(t)] = pick(ah, "us_aqi", i)
    hours = []
    for i, t in enumerate(times[:HOURS]):
        code = pick(h, "weather_code", i)
        hours.append({"t": str(t)[:16], "temp_c": pick(h, "temperature_2m", i), "dew_c": pick(h, "dew_point_2m", i),
                      "feels_c": pick(h, "apparent_temperature", i), "rain_pct": pick(h, "precipitation_probability", i),
                      "code": code, "summary": WX_CODES.get(code, ""), "wind_kmh": pick(h, "wind_speed_10m", i),
                      "gust_kmh": pick(h, "wind_gusts_10m", i), "aqi": aqi_by_t.get(str(t)),
                      "day": bool(pick(h, "is_day", i)) if pick(h, "is_day", i) is not None else True})
    d = body.get("daily") or {}
    days = []
    for i, t in enumerate((d.get("time") or [])[:3]):
        code = pick(d, "weather_code", i)
        days.append({"date": str(t)[:10], "hi_c": pick(d, "temperature_2m_max", i), "lo_c": pick(d, "temperature_2m_min", i),
                     "rain_pct": pick(d, "precipitation_probability_max", i), "code": code,
                     "summary": WX_CODES.get(code, ""), "sunrise": str(pick(d, "sunrise", i) or "")[11:16] or None,
                     "sunset": str(pick(d, "sunset", i) or "")[11:16] or None})
    return {"place": place, "elevation_m": _num(body.get("elevation")), "hours": hours, "days": days}


def fake_forecast(today: date, key: str = "") -> dict[str, Any]:
    """Deterministic 3 days for dev review (RABBIT_FAKE_WEATHER=1): a warm humid afternoon on day
    one, a windy cool day two, a stormy evening on day three."""
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:4], 16) % 3
    hours, days = [], []
    for dd in range(3):
        day = date.fromordinal(today.toordinal() + dd)
        temps = []
        for hh in range(24):
            base = [18, 9, 14][dd] + seed
            temp = base + 9 * max(0.0, 1 - abs(hh - 15) / 9)
            dew = [17, 2, 10][dd]
            code = 95 if dd == 2 and 17 <= hh <= 20 else 61 if dd == 2 and hh in (21, 22) else 1 if hh < 18 else 2
            wind = [8, 34, 14][dd] + (6 if 12 <= hh <= 18 else 0)
            hours.append({"t": f"{day.isoformat()}T{hh:02d}:00", "temp_c": round(temp, 1), "dew_c": dew,
                          "feels_c": round(temp - (4 if dd == 1 else 0), 1),
                          "rain_pct": 70 if code in (95, 61) else 10, "code": code, "summary": WX_CODES[code],
                          "wind_kmh": wind, "gust_kmh": wind + 12, "aqi": 42, "day": 6 <= hh <= 19})
            temps.append(temp)
        days.append({"date": day.isoformat(), "hi_c": round(max(temps), 1), "lo_c": round(min(temps), 1),
                     "rain_pct": 70 if dd == 2 else 10, "code": 95 if dd == 2 else 2 if dd == 1 else 1,
                     "summary": "Thunderstorms" if dd == 2 else "Partly cloudy" if dd == 1 else "Mostly clear",
                     "sunrise": "06:55", "sunset": "18:25"})
    return {"place": "Demo weather", "elevation_m": 1600.0, "hours": hours, "days": days}


async def forecast(*, lat: float | None = None, lon: float | None = None, place: str = "",
                   http: httpx2.AsyncClient | None = None, clock: Callable[[], float] = time.time,
                   today: date | None = None) -> dict[str, Any] | None:
    """Hourly (72 h) and daily (3 days) weather for coordinates, or a place name geocoded first.
    Cached per rounded location; None when unknown or unreachable."""
    if lat is not None and lon is not None:
        key = f"{round(lat, 2)},{round(lon, 2)}"
    else:
        key = " ".join((place or "").split()).lower()[:80]
    if not key:
        return None
    if os.environ.get("RABBIT_FAKE_WEATHER") == "1":
        return fake_forecast(today or date.today(), key)
    hit = _CACHE.get(key)
    if hit and clock() - hit[0] < CACHE_S:
        return hit[1]
    client = http or httpx2.AsyncClient(timeout=6)
    out: dict[str, Any] | None = None
    try:
        label = place
        if lat is None or lon is None:
            g = await client.get(GEO_URL, params={"name": place.split(",")[0].strip(), "count": 1})
            g.raise_for_status()
            res = (g.json().get("results") or [None])[0]
            if not res:
                raise LookupError("place")
            lat, lon = res["latitude"], res["longitude"]
            label = f"{res.get('name')}, {res.get('admin1') or res.get('country') or ''}".strip(", ")
        w = await client.get(WX_URL, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "hourly": "temperature_2m,dew_point_2m,apparent_temperature,precipitation_probability,weather_code,"
                      "wind_speed_10m,wind_gusts_10m,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset"})
        w.raise_for_status()
        aq = None
        try:
            a = await client.get(AQ_URL, params={"latitude": lat, "longitude": lon, "timezone": "auto",
                                                 "hourly": "us_aqi", "forecast_days": 3})
            if a.status_code == 200:
                aq = a.json()
        except Exception:
            aq = None
        out = _shape(w.json(), aq, label or "")
    except Exception:
        out = None
    finally:
        if http is None:
            await client.aclose()
    if len(_CACHE) >= MAX_CACHE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (clock(), out)
    return out


# ------------------------------------------------------------ adjustments --
def heat_pct(temp_c: float | None, dew_c: float | None) -> float:
    """% slower for running from temperature + dew point (°F sum), interpolated on ``HEAT``."""
    if temp_c is None:
        return 0.0
    s = _f(temp_c) + _f(dew_c if dew_c is not None else temp_c - 10)
    if s <= HEAT[0][0]:
        return 0.0
    for (a, pa), (b, pb) in zip(HEAT, HEAT[1:]):
        if s <= b:
            return round(pa + (pb - pa) * (s - a) / (b - a), 1)
    return 12.0


def _sport(session: dict[str, Any]) -> str:
    sp = str(session.get("sport") or "")
    if sp == "brick":
        return "run"
    return sp


def adjust(session: dict[str, Any], hours: list[dict[str, Any]], *, elevation_m: float | None = None,
           home_elevation_m: float | None = None, acclimatized: bool = False,
           pace: tuple[float, float] | None = None, imperial: bool = True) -> dict[str, Any]:
    """What the weather means for one session over the hours it runs (usually 1-3 forecast
    hours). ``pace`` is the planned (fast, slow) seconds per km for runs."""
    sport = _sport(session)
    out: dict[str, Any] = {"pct": 0.0, "badges": [], "reasons": [], "safety": [], "pace": None, "note": ""}
    if not hours or sport in ("strength", "rest", "") or (sport == "swim" and not session.get("open_water")):
        if sport == "swim" and hours and any(h.get("code") in STORM for h in hours):
            out["safety"].append("Thunderstorms around: outdoor pools close for lightning, so check first.")
        out["note"] = "Pool swim: the weather won't change this one." if sport == "swim" else ""
        return out
    temp = max((h["temp_c"] for h in hours if _num(h.get("temp_c")) is not None), default=None)
    dew = max((h["dew_c"] for h in hours if _num(h.get("dew_c")) is not None), default=None)
    feels = min((h["feels_c"] for h in hours if _num(h.get("feels_c")) is not None), default=None)
    wind = max((h["wind_kmh"] for h in hours if _num(h.get("wind_kmh")) is not None), default=0.0)
    gust = max((h["gust_kmh"] for h in hours if _num(h.get("gust_kmh")) is not None), default=0.0)
    codes = {h.get("code") for h in hours}
    aqi = max((h["aqi"] for h in hours if _num(h.get("aqi")) is not None), default=None)
    deg = (lambda c: f"{round(_f(c))}°F") if imperial else (lambda c: f"{round(c)}°C")
    pct = 0.0

    hp = heat_pct(temp, dew)
    if hp >= 12.0:
        out["badges"].append("heat")
        out["safety"].append(f"Very hot and humid ({deg(temp)}): skip hard running. Go easy by heart rate, or move it to early morning.")
        pct += hp
        out["reasons"].append(f"heat {deg(temp)}")
    elif hp > 0:
        pct += hp
        out["reasons"].append(f"heat {deg(temp)}")
        if hp >= 1.5:
            out["badges"].append("heat")

    if feels is not None and feels < 0:
        out["badges"].append("cold")
        if feels < -10:
            pct += 2.0
            out["reasons"].append(f"cold {deg(feels)}")
            out["safety"].append("Bitter cold: cover skin, layer up, and warm up indoors first.")
        else:
            out["reasons"].append(f"cold {deg(feels)}")

    if wind >= 25 or gust >= 40:
        out["badges"].append("wind")
        if sport == "run":
            if wind >= 30:
                pct += 1.0
            out["reasons"].append(f"wind {round(wind / 1.609) if imperial else round(wind)} {'mph' if imperial else 'km/h'}")
        else:
            out["reasons"].append("wind")

    here = elevation_m if elevation_m is not None else home_elevation_m
    base = home_elevation_m if home_elevation_m is not None else here
    if here is not None and base is not None and here - base >= 300:
        alt = (here - base) / 300 * 1.0 * (0.5 if acclimatized else 1.0)
        pct += alt
        out["badges"].append("altitude")
        out["reasons"].append(f"altitude {round(here * 3.281):,} ft" if imperial else f"altitude {round(here):,} m")

    if codes & STORM:
        out["badges"].append("storm")
        out["safety"].append("Thunderstorms in the forecast: wait until 30 minutes after the last thunder, or go indoors.")
    if codes & ICY:
        out["badges"].append("ice")
        out["safety"].append("Snow or ice possible: slower pace, traction, and a route you know.")
    elif codes & WET:
        out["badges"].append("rain")
    if aqi is not None and aqi > 150:
        out["badges"].append("air")
        out["safety"].append(f"Unhealthy air (AQI {round(aqi)}): keep it easy or move it indoors.")
    elif aqi is not None and aqi > 100:
        out["badges"].append("air")
        out["reasons"].append(f"air quality {round(aqi)}")

    pct = round(min(pct, 15.0), 1)
    out["pct"] = pct
    if sport == "run" and pace and pct > 0:
        f = 1 + pct / 100
        out["pace"] = (round(pace[0] * f), round(pace[1] * f))
    if sport == "run":
        if pct >= 1:
            why = " and ".join(out["reasons"][:2])
            out["note"] = f"Slow your paces about {pct:g}% for the {why}, and keep the effort where it belongs."
        elif out["badges"] and not out["safety"]:
            out["note"] = "Weather's a factor: run by effort, not the watch."
    elif sport in ("bike", "brick"):
        bits = []
        if "wind" in out["badges"]:
            bits.append("hold your power and let the speed drop into the wind")
        if "heat" in out["badges"]:
            bits.append("drink more and ease power a little on the hard parts")
        if "cold" in out["badges"]:
            bits.append("cover hands, feet and ears; the descents get cold")
        out["note"] = ("Ride smart: " + "; ".join(bits) + ".") if bits else ""
    if "cold" in out["badges"] and sport == "run" and pct < 1:
        out["note"] = "Cold out: take a longer warm-up and dress in layers you can shed."
    if here is not None and here >= 1500 and sport in ("run", "bike", "brick") and not out["note"]:
        out["note"] = "At altitude your heart rate runs higher: go by effort."
    out["badges"] = list(dict.fromkeys(out["badges"]))
    return out


def _penalty(h: dict[str, Any]) -> float:
    p = heat_pct(_num(h.get("temp_c")), _num(h.get("dew_c")))
    feels = _num(h.get("feels_c"))
    if feels is not None and feels < 0:
        p += min(4.0, -feels / 4)
    p += max(0.0, ((_num(h.get("wind_kmh")) or 0) - 15) / 10)
    p += (_num(h.get("rain_pct")) or 0) / 25
    if h.get("code") in STORM:
        p += 20
    if h.get("code") in ICY:
        p += 6
    aqi = _num(h.get("aqi"))
    if aqi is not None and aqi > 100:
        p += (aqi - 100) / 25
    if h.get("day") is False:
        p += 3  # dark
    return p


def best_time(hours: list[dict[str, Any]], day: str, minutes: int | None, planned: str | None = None,
              window: tuple[int, int] = WINDOW) -> dict[str, Any] | None:
    """Best start hour on ``day`` for a session of ``minutes``: the lowest average penalty over
    the hours it covers. Returns {"start", "end", "why", "better"}; ``better`` is True when it
    clearly beats the planned start (or nothing was planned and the day varies)."""
    day_hours = [h for h in hours if h.get("t", "").startswith(day)]
    if len(day_hours) < 3:
        return None
    by_hour = {int(h["t"][11:13]): h for h in day_hours}
    span = max(1, -(-int(minutes or 60) // 60))

    def score(start: int) -> float | None:
        hs = [by_hour.get(start + k) for k in range(span)]
        if any(h is None for h in hs):
            return None
        return sum(_penalty(h) for h in hs if h) / span  # type: ignore[arg-type]
    cands = [(s, sc) for s in range(window[0], window[1] - span + 2) if (sc := score(s)) is not None]
    if not cands:
        return None
    best_s, best_sc = min(cands, key=lambda x: (round(x[1], 2), x[0]))
    worst = max(sc for _, sc in cands)
    planned_h = int(planned[:2]) if planned and len(planned) >= 2 and planned[:2].isdigit() else None
    planned_sc = score(planned_h) if planned_h is not None else None
    better = (planned_sc is not None and planned_sc - best_sc >= 1.0 and best_s != planned_h) or \
             (planned_sc is None and worst - best_sc >= 1.5)
    h = by_hour[best_s]
    heat = lambda x: heat_pct(_num(x.get("temp_c")), _num(x.get("dew_c")))  # noqa: E731
    bits = []
    if heat(h) <= max(heat(x) for x in day_hours) - 1:
        bits.append("cooler")
    if (_num(h.get("wind_kmh")) or 0) <= max((_num(x.get("wind_kmh")) or 0) for x in day_hours) - 10:
        bits.append("calmer")
    if (_num(h.get("rain_pct")) or 0) <= max((_num(x.get("rain_pct")) or 0) for x in day_hours) - 30:
        bits.append("drier")
    end_m = best_s * 60 + int(minutes or 60)
    return {"start": f"{best_s:02d}:00", "end": f"{end_m // 60 % 24:02d}:{end_m % 60:02d}",
            "why": " and ".join(bits) if bits else "the best conditions of the day", "better": better}


def hours_for(hours: list[dict[str, Any]], day: str, start: str | None, minutes: int | None) -> list[dict[str, Any]]:
    """The forecast hours a session covers (its start time, or the hour picked by ``best_time``,
    or mid-morning when the day has nothing better)."""
    day_hours = [h for h in hours if h.get("t", "").startswith(day)]
    if not day_hours:
        return []
    s = int(start[:2]) if start and start[:2].isdigit() else None
    if s is None:
        bt = best_time(hours, day, minutes)
        s = int(bt["start"][:2]) if bt else 8
    span = max(1, -(-int(minutes or 60) // 60))
    return [h for h in day_hours if s <= int(h["t"][11:13]) < s + span]


def strip(hours: list[dict[str, Any]], day: str, center: int, width: int = 6) -> list[dict[str, Any]]:
    """A few hours around the planned time for the hourly strip on the workout page."""
    day_hours = [h for h in hours if h.get("t", "").startswith(day)]
    lo = max(0, center - width // 2)
    return [h for h in day_hours if lo <= int(h["t"][11:13]) < lo + width]


__all__ = ["forecast", "fake_forecast", "adjust", "best_time", "heat_pct", "hours_for", "strip", "WX_CODES"]
