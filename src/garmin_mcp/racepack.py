"""Race-week pack: pacing by leg, a fueling plan, a gear checklist, weather, and the
final-week timeline, built from the event, the athlete's numbers and the plan.

Deterministic; pacing uses common rules of thumb (fractions of FTP, threshold pace or
threshold heart rate by race distance). Weather comes from Open-Meteo (no key) when the
race is within 14 days and the event has a location.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import httpx2

from .gear import for_race
from .nutrition import race_target
from .planbuilder import iter_sessions

KM_MI = 1.609344
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL = "https://api.open-meteo.com/v1/forecast"

# distance -> (bike IF range, run pace factor range vs threshold, swim +s/100m vs CSS, hours estimate)
TRI = {"sprint triathlon": ((0.88, 0.92), (1.00, 1.03), 2, 1.3), "olympic triathlon": ((0.83, 0.88), (1.03, 1.06), 4, 2.5),
       "70.3": ((0.75, 0.80), (1.08, 1.13), 8, 5.5), "140.6": ((0.68, 0.73), (1.18, 1.28), 10, 12.0)}
RUN = {"5k": (0.94, 0.97, 0.4), "10k": (0.98, 1.01, 0.8), "half marathon": (1.02, 1.05, 1.8),
       "marathon": (1.07, 1.10, 3.8)}
GEAR = {
    "triathlon": ["Wetsuit (check water temp rules)", "Goggles ×2 (clear and tinted)", "Swim cap from the race",
                  "Bike tuned, tyres checked, spare tube + CO2", "Helmet, bike shoes, sunglasses",
                  "Race belt with number", "Run shoes with elastic laces", "Nutrition for bike and run, bottles",
                  "Sunscreen and anti-chafe", "Timing chip", "Transition towel"],
    "running": ["Race shoes you've run long in", "Bib + pins or race belt", "Watch charged, course loaded",
                "Gels/drink you trained with", "Anti-chafe, sunscreen", "Throwaway layer for the start"],
    "trail": ["Trail shoes + spare pair in a drop bag", "Hydration vest, 2 soft flasks", "Headlamp + spare batteries",
              "Poles (practise with them)", "Waterproof jacket, warm layer, gloves, hat", "Drop bags labelled by aid station",
              "Nutrition you trained with + backup", "Anti-chafe, blister kit, sunscreen", "Mandatory kit list from the race",
              "Crew/pacer plan and timings"],
    "cycling": ["Bike serviced, new chain/tyres checked", "2 tubes, CO2/pump, multitool", "Bottles + fuel", "Helmet, glasses, gloves",
                "Lights if any dark hours", "Rain jacket", "Head unit charged, route loaded"],
    "other": ["Shoes and kit you've trained in", "Fuel and fluids you've practised with", "Layers for the conditions",
              "Phone, ID, emergency contact", "Watch charged"],
}


def _pace(sec_per_km: float, imperial: bool) -> str:
    s = sec_per_km * (KM_MI if imperial else 1)
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}/{'mi' if imperial else 'km'}"


def _altitude(event: dict[str, Any]) -> bool:
    blob = " ".join(str(x) for x in [event.get("name"), event.get("location"), event.get("course"),
                                     *(event.get("info") or {}).values()])
    if re.search(r"leadville|altitude|high country|hope pass", blob, re.I):
        return True
    for m in re.finditer(r"(\d{1,2}),?(\d{3})\s*(ft|feet|')", blob):
        if int(m.group(1) + m.group(2)) >= 7000:
            return True
    return False


def pacing(event: dict[str, Any], athlete: dict[str, Any]) -> list[dict[str, str]]:
    dist = (event.get("distance") or "other").lower()
    etype = event.get("type") or "other"
    imp = athlete.get("units") != "metric"
    ftp, thr_pace, css, lthr = (athlete.get("ftp_w"), athlete.get("run_threshold_pace"),
                                athlete.get("swim_css"), athlete.get("threshold_hr"))
    out: list[dict[str, str]] = []
    if dist in TRI:
        (b0, b1), (r0, r1), sw, _ = TRI[dist]
        out.append({"leg": "Swim", "target": f"{_pace_100(css + sw)}–{_pace_100(css + sw + 4)} /100m" if css else "Steady, RPE 6/10",
                    "detail": "Start wide or behind if the start is rough; settle your breathing in the first 200 m."})
        if ftp:
            out.append({"leg": "Bike", "target": f"{int(ftp * b0)}–{int(ftp * b1)} W",
                        "detail": f"{int(b0 * 100)}–{int(b1 * 100)}% of FTP. Cap surges on climbs at threshold; the run decides the race."})
        else:
            out.append({"leg": "Bike", "target": f"{int(lthr * 0.80)}–{int(lthr * 0.87)} bpm" if lthr else "Comfortably hard, RPE 6-7/10",
                        "detail": "Ride conservative for the first 20 minutes, then settle in."})
        if thr_pace:
            out.append({"leg": "Run", "target": f"{_pace(thr_pace * r0, imp)}–{_pace(thr_pace * r1, imp)}",
                        "detail": "First 2 km slower than target while your legs adjust; walk the aid stations if it helps you fuel."})
        else:
            out.append({"leg": "Run", "target": "Controlled, RPE 7/10", "detail": "Hold back for the first third; build if you feel good."})
    elif dist in RUN and etype != "trail":
        p0, p1, _ = RUN[dist]
        out.append({"leg": "Run", "target": f"{_pace(thr_pace * p0, imp)}–{_pace(thr_pace * p1, imp)}" if thr_pace else
                    (f"{int(lthr * 0.92)}–{int(lthr * 0.98)} bpm" if lthr else "Even effort"),
                    "detail": "Even or slightly negative split. Bank nothing in the first mile."})
    else:  # ultras, trail, mountain, other
        out.append({"leg": "Overall", "target": f"Under {int(lthr * 0.85)} bpm on climbs, easy talk pace on flats" if lthr else
                    "Conversational effort; hike anything you can't run comfortably",
                    "detail": "Effort, not pace: start slower than feels right. Power-hike steep grades with poles."})
    if _altitude(event):
        out.append({"leg": "Altitude", "target": "Go by effort/HR, not pace",
                    "detail": "Expect 5-15% slower above 8,000 ft, more on climbs. Drink more, eat early, and arrive 2+ weeks before or within 24 hours."})
    blob = " ".join(str(x) for x in [event.get("name"), event.get("course"), *(event.get("info") or {}).values()])
    if re.search(r"hope pass", blob, re.I):
        out.append({"leg": "Hope Pass", "target": "Hike it, twice",
                    "detail": "~3,400 ft climbs to 12,600 ft each way. Eat before you start climbing, poles out, layers for the top, and descend controlled to save your quads for Powerline."})
    return out


def _pace_100(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def fueling(event: dict[str, Any], athlete: dict[str, Any]) -> dict[str, Any]:
    dist = (event.get("distance") or "other").lower()
    hours = TRI.get(dist, (None, None, None, None))[3] or (RUN.get(dist) or (0, 0, None))[2] \
        or {"ultra": 24.0, "century ride": 6.0}.get(dist, 3.0)
    target = race_target(dist)
    kg = athlete.get("weight_kg")
    plan = {"carbs_g_per_h": target, "expected_hours": hours, "total_carbs_g": int(target * max(0, hours - 0.3)),
            "fluid_ml_per_h": "500-800 (more in heat)", "sodium_mg_per_h": "400-800 (more if you're a salty sweater)",
            "steps": []}
    if hours >= 1.5:
        plan["steps"].append(f"Two days out: carb-load at 8-10 g/kg/day{f' (about {int(kg * 8)}-{int(kg * 10)} g)' if kg else ''}; keep fibre low.")
    plan["steps"].append(f"Breakfast 3 hours before: 1-3 g/kg of carbs{f' ({int(kg)}-{int(kg * 3)} g)' if kg else ''}, familiar foods.")
    if target:
        plan["steps"].append(f"During: {target} g carbs per hour from the start, little and often; only products you've trained with.")
    plan["steps"].append("Caffeine is optional: about 3 mg/kg late in the race if you've practised it.")
    return plan


async def forecast(location: str, race_day: date, today: date, http: httpx2.AsyncClient | None = None) -> dict[str, Any] | None:
    """Daily forecast for race day via Open-Meteo, when it's within 14 days."""
    if not location or not (0 <= (race_day - today).days <= 14):
        return None
    client = http or httpx2.AsyncClient(timeout=10)
    try:
        g = await client.get(GEO_URL, params={"name": location.split(",")[0].strip(), "count": 1})
        g.raise_for_status()
        res = (g.json().get("results") or [None])[0]
        if not res:
            return None
        w = await client.get(WX_URL, params={
            "latitude": res["latitude"], "longitude": res["longitude"], "timezone": "auto",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "start_date": race_day.isoformat(), "end_date": race_day.isoformat()})
        w.raise_for_status()
        d = w.json().get("daily") or {}
        pick = lambda k: (d.get(k) or [None])[0]  # noqa: E731
        return {"place": f"{res.get('name')}, {res.get('admin1') or res.get('country') or ''}".strip(", "),
                "high_c": pick("temperature_2m_max"), "low_c": pick("temperature_2m_min"),
                "rain_pct": pick("precipitation_probability_max"), "wind_kmh": pick("wind_speed_10m_max")}
    except Exception:
        return None
    finally:
        if http is None:
            await client.aclose()


def build(event: dict[str, Any], athlete: dict[str, Any], plan: dict[str, Any] | None, today: date,
          wx: dict[str, Any] | None = None, gear: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """``gear`` is the athlete's garage with mileage (``gear.usage``); the relevant active
    items go into ``your_gear`` with worn-out / brand-new shoe warnings."""
    race_day = date.fromisoformat(event["date"])
    etype = event.get("type") or "other"
    week: list[dict[str, Any]] = []
    if plan:
        start = (race_day - timedelta(days=7)).isoformat()
        for _, d, s in iter_sessions(plan):
            if start <= d <= event["date"] and s["sport"] != "rest":
                week.append({"date": d, "title": s["title"], "minutes": s.get("minutes")})
    tips = []
    if wx and isinstance(wx.get("high_c"), int | float) and wx["high_c"] >= 25:
        tips.append("Hot forecast: pre-load sodium, drink to thirst plus a little, ice in hats/sleeves, slow your target pace.")
    if wx and isinstance(wx.get("low_c"), int | float) and wx["low_c"] <= 5:
        tips.append("Cold start: warm layers you can drop, gloves, and a hot drink before the start.")
    return {
        "event": {k: event.get(k) for k in ("id", "name", "type", "distance", "date", "location", "url", "priority", "kind")},
        "days_out": (race_day - today).days,
        "info": event.get("info") or {},
        "pacing": pacing(event, athlete),
        "fueling": fueling(event, athlete),
        "your_gear": for_race(gear or [], etype, imperial=athlete.get("units") != "metric"),
        "gear": GEAR.get(etype if etype in GEAR else ("trail" if etype in ("trail", "mountaineering") else "other"), GEAR["other"]),
        "weather": wx, "weather_tips": tips,
        "week": week,
        "timeline": [
            {"when": "7 days out", "what": "Taper: shorter sessions, keep a little intensity. Confirm logistics and travel."},
            {"when": "3 days out", "what": "Pack using the gear list; test anything new (you shouldn't have anything new)."},
            {"when": "2 days out", "what": "Carb-load, extra sleep, drop bags/bike check-in if the race has them."},
            {"when": "Day before", "what": "Short shakeout with a few pickups, lay out kit, early dinner, set two alarms."},
            {"when": "Race morning", "what": "Breakfast 3 hours before, arrive early, warm up briefly, start conservative."},
        ],
    }


__all__ = ["build", "pacing", "fueling", "forecast"]
