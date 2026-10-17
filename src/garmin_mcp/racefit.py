"""Race fit: how an athlete's traits match one event, as a short list of factors.

Deterministic (no model, no Garmin call): it reads the event (its own fields plus the
looked-up ``info`` text) and the athlete's profile, and returns factors like::

    {"id": "altitude", "title": "Altitude", "impact": "helps"|"neutral"|"watch"|"risk",
     "detail": "...", "tip": "..."}

ordered risk, watch, helps, neutral, with a one-line summary. The output is athlete-entered
data plus fixed rules, so it may go to the model (race strategy); it never reads Oura.

Wording rule for body mass: power-to-weight is described neutrally (which courses favor
lighter or heavier riders); there is never weight-loss advice.
"""

from __future__ import annotations

import re
from typing import Any

FT_M = 0.3048
KM_MI = 1.609344
# Altitude (m) of places that host well-known high races: (town/start, high point or None).
KNOWN_PLACES: dict[str, tuple[int, int | None]] = {
    "leadville": (3094, 3840),        # 10,152 ft town; Hope Pass 12,600 ft
    "hope pass": (3094, 3840),
    "pikes peak": (1950, 4302),
    "breckenridge": (2926, None), "silverton": (2836, None), "telluride": (2667, None),
    "vail": (2484, None), "aspen": (2438, None), "mammoth": (2400, None), "park city": (2134, None),
    "flagstaff": (2106, None), "steamboat": (2051, None), "estes park": (2293, None),
    "crested butte": (2700, None), "winter park": (2743, None), "lake tahoe": (1897, None),
    "boulder": (1655, None), "denver": (1609, None), "colorado springs": (1839, None),
    "santa fe": (2134, None), "st. moritz": (1822, None), "st moritz": (1822, None),
    "chamonix": (1035, 4808), "zermatt": (1608, None), "mexico city": (2240, None),
    "bogota": (2640, None), "quito": (2850, None), "cusco": (3400, None), "la paz": (3640, None),
    "iten": (2400, None), "addis ababa": (2355, None),
}
# Rough race duration in hours by distance, for the experience factor.
HOURS = {"sprint triathlon": 1.3, "olympic triathlon": 2.5, "70.3": 5.5, "140.6": 12.0, "5k": 0.4,
         "10k": 0.8, "half marathon": 1.8, "marathon": 3.8, "ultra": 20.0, "century ride": 6.0}
KM = {"5k": 5, "10k": 10, "half marathon": 21.1, "marathon": 42.2, "ultra": 80, "century ride": 161,
      "sprint triathlon": 20, "olympic triathlon": 40, "70.3": 90, "140.6": 180}
ORDER = {"risk": 0, "watch": 1, "helps": 2, "neutral": 3}


def _text(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _to_m(value: float, unit: str) -> float:
    return value * FT_M if unit.lower().startswith(("f", "'")) else value


_ALT_NUM = r"(\d{1,2},\d{3}|\d{3,5})\s*(ft|feet|foot|'|m|meters|metres)\b"
_GAIN_WORDS = re.compile(r"(gain|climb|climbing|ascent|vert|elevation change|up and down|descent)", re.I)


def race_elevation(event: dict[str, Any]) -> dict[str, Any] | None:
    """{"m", "high_m", "source"} for the race's altitude, or None when it's unknown.

    Order: the athlete's own ``elevation_m``, then a lookup suggestion, then a known place,
    then altitude numbers in the text (never the climbing total)."""
    info = event.get("info") or {}
    own = event.get("elevation_m")
    if isinstance(own, int | float) and not isinstance(own, bool):
        return {"m": int(own), "high_m": None, "source": "you"}
    blob = _text(event.get("name"), event.get("location"), event.get("course"), info.get("location"),
                 info.get("terrain"), info.get("summary"))
    low = blob.lower()
    for place, (m, high) in KNOWN_PLACES.items():
        if place in low:
            return {"m": m, "high_m": high, "source": "place"}
    sug = info.get("suggested_elevation_m")
    if isinstance(sug, int) and 0 <= sug <= 6000:
        return {"m": sug, "high_m": None, "source": "lookup"}
    found = []
    for m in re.finditer(_ALT_NUM, blob, re.I):
        before = blob[max(0, m.start() - 30):m.start()]
        after = blob[m.end():m.end() + 25]
        if _GAIN_WORDS.search(before) or _GAIN_WORDS.search(after):
            continue
        if re.search(r"(altitude|elevation|above sea level|asl|summit|high point|highest|tops out|peak)",
                     before + " " + after, re.I):
            found.append(_to_m(_num(m.group(1)), m.group(2)))
    if found:
        return {"m": int(min(found)), "high_m": int(max(found)) if max(found) > min(found) else None,
                "source": "text"}
    return None


def _distance_km(event: dict[str, Any]) -> float | None:
    info = event.get("info") or {}
    nums = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(km|k|mi|miles?)\b", _text(info.get("distances"), event.get("distance")), re.I):
        v = float(m.group(1))
        nums.append(v * KM_MI if m.group(2).lower().startswith("mi") else v)
    if nums:
        return max(nums)
    return KM.get((event.get("distance") or "").lower())


def _gain_m(event: dict[str, Any]) -> float | None:
    info = event.get("info") or {}
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(ft|feet|m|meters|metres)\b", str(info.get("elevation_gain") or ""), re.I)
    return _to_m(_num(m.group(1)), m.group(2)) if m else None


def course_profile(event: dict[str, Any]) -> tuple[str | None, float | None]:
    """(profile, metres of climbing per km). The athlete's own pick wins."""
    gain, km = _gain_m(event), _distance_km(event)
    per_km = gain / km if gain is not None and km else None
    own = event.get("course_profile")
    if own:
        return own, per_km
    if per_km is None:
        txt = _text(event.get("course"), (event.get("info") or {}).get("terrain")).lower()
        if re.search(r"\bflat\b|pancake|fast course", txt):
            return "flat", None
        if re.search(r"mountain|alpine|pass\b|summit", txt):
            return "mountainous", None
        if re.search(r"hilly|hills|climb", txt):
            return "hilly", None
        if "rolling" in txt:
            return "rolling", None
        return None, None
    bike = (event.get("type") or "") in ("cycling", "triathlon", "duathlon")
    cuts = (5, 10, 20) if bike else (5, 15, 30)
    prof = "flat" if per_km < cuts[0] else "rolling" if per_km < cuts[1] else "hilly" if per_km < cuts[2] else "mountainous"
    return prof, per_km


def _hot_cold(event: dict[str, Any]) -> tuple[bool, bool]:
    txt = _text((event.get("info") or {}).get("typical_weather"), event.get("course"))
    temps = []
    for m in re.finditer(r"(-?\d{1,3})\s*°?\s*([FC])\b", txt):
        v = float(m.group(1))
        temps.append((v - 32) * 5 / 9 if m.group(2) == "F" else v)
    hot = bool(re.search(r"\b(hot|heat|humid|humidity|tropical|scorching|desert)\b", txt, re.I)) or any(t >= 27 for t in temps)
    cold = bool(re.search(r"\b(cold|freezing|snow|frost|hypotherm)\w*", txt, re.I)) or any(t <= 5 for t in temps)
    return hot, cold


def _f(id_: str, title: str, impact: str, detail: str, tip: str = "") -> dict[str, str]:
    return {"id": id_, "title": title, "impact": impact, "detail": detail, "tip": tip}


def _alt_str(m: float, imperial: bool) -> str:
    return f"{round(m / FT_M / 10) * 10:,.0f} ft" if imperial else f"{round(m / 10) * 10:,.0f} m"


def analyze(event: dict[str, Any], athlete: dict[str, Any]) -> dict[str, Any]:
    a = athlete or {}
    imperial = a.get("units") != "metric"
    strengths, limiters = set(a.get("strengths") or []), set(a.get("limiters") or [])
    terrain = set(a.get("terrain_access") or []) | {"open_water" for e in (a.get("equipment") or []) if e == "open_water"}
    etype = event.get("type") or "other"
    dist = (event.get("distance") or "").lower()
    out: list[dict[str, str]] = []

    # ---- altitude
    alt = race_elevation(event)
    home = a.get("home_elevation_m")
    home = home if isinstance(home, int | float) and not isinstance(home, bool) else None
    acclim = a.get("altitude_acclimatized") is True or (home is not None and home >= 1500)
    if alt and alt["m"] >= 1500:
        race_m = alt["m"]
        high = f" (high point about {_alt_str(alt['high_m'], imperial)})" if alt.get("high_m") else ""
        where = f"The race sits at about {_alt_str(race_m, imperial)}{high}"
        slow_lo = max(1, round((race_m - 1000) / 300 * (0.5 if acclim else 1)))
        slow = f"Expect roughly {slow_lo}-{slow_lo * 2}% slower at the same effort; pace by heart rate and feel, not your sea-level pace."
        if home is not None and home >= race_m - 500:
            out.append(_f("altitude", "Altitude", "helps", f"{where}; you live at about {_alt_str(home, imperial)}, so it's close to home.",
                          "Keep drinking more than you think: dry air at altitude dehydrates you faster."))
        elif acclim:
            out.append(_f("altitude", "Altitude", "watch", f"{where}, higher than where you live and train. You're partly adapted already.",
                          "Arrive a few days early if you can, or spend some long sessions higher up in the last month. " + slow))
        else:
            impact = "risk" if race_m >= 2500 else "watch"
            out.append(_f("altitude", "Altitude", impact,
                          f"{where}{', well above' if home is None or home < 1000 else ', above'} where you live"
                          f"{f' (about {_alt_str(home, imperial)})' if home is not None else ''}.",
                          "Arrive 14 or more days early to adapt, or within 24 hours of the start so you race before "
                          "altitude symptoms build; avoid arriving 2-7 days out. " + slow))
    elif alt and home is not None and home >= 1500 and alt["m"] < 1000:
        out.append(_f("altitude", "Altitude", "helps", "You train at altitude and race low: more oxygen than you're used to.",
                      "Don't let the easy breathing tempt you into starting too fast."))

    # ---- climbing / course profile
    prof, per_km = course_profile(event)
    bike = etype in ("cycling", "triathlon", "duathlon")
    wkg = ""
    if bike and isinstance(a.get("ftp_w"), int | float) and isinstance(a.get("weight_kg"), int | float) and a["weight_kg"]:
        wkg = (f" Your FTP is {a['ftp_w'] / a['weight_kg']:.1f} W/kg. On long climbs power-to-weight decides speed; "
               "on flat courses absolute power and aerodynamics matter more, which tends to suit bigger riders.")
    grade = ""
    if per_km is not None:
        grade = (f" About {per_km * KM_MI / FT_M:,.0f} ft of climbing per mile." if imperial
                 else f" About {per_km:.0f} m of climbing per km.")
    if prof in ("hilly", "mountainous"):
        hill_access = terrain & {"hills", "mountains", "trails"}
        if "climbing" in limiters:
            impact = "risk" if prof == "mountainous" else "watch"
        elif "climbing" in strengths:
            impact = "helps"
        elif terrain and not hill_access:
            impact = "watch"
        else:
            impact = "neutral"
        detail = f"A {prof} course.{grade}"
        if "climbing" in strengths:
            detail += " Climbing is one of your strengths."
        elif "climbing" in limiters:
            detail += " You listed climbing as a limiter."
        if terrain and not hill_access:
            detail += " You don't have hills to train on."
        tip = ("Weekly hill work at race effort: long climbs or repeats" +
               (", or a treadmill incline / trainer climbs if you're stuck on the flat" if terrain and not hill_access else "") + ".")
        if prof == "mountainous" and etype in ("trail", "running", "mountaineering"):
            tip += " Practise power-hiking with poles."
        if "descending" in limiters and etype in ("trail", "mountaineering", "running", "cycling"):
            tip += " Add downhill running or descending practice: it's where races are often lost."
        out.append(_f("climbing", "Climbing", impact, detail + wkg, tip))
    elif prof == "flat":
        if "flats" in strengths or "speed" in strengths:
            impact, extra = "helps", " Fast, steady terrain suits you."
        elif "flats" in limiters:
            impact, extra = "watch", " You listed flat, steady efforts as a limiter."
        else:
            impact, extra = "neutral", ""
        out.append(_f("course", "Flat course", impact, f"A flat course: steady, unbroken effort the whole way.{grade}{extra}{wkg}",
                      "Practise long blocks at race effort without breaks" +
                      (" and time in the aero position" if bike else "") + "; a flat course punishes a fast start."))
    elif prof == "rolling":
        out.append(_f("course", "Rolling course", "helps" if "climbing" in strengths or "pacing" in strengths else "neutral",
                      f"Rolling terrain.{grade}{wkg}",
                      "Keep effort even over the rollers: ease up on the climbs, keep pedalling or running over the tops."))

    # ---- heat / cold
    hot, cold = _hot_cold(event)
    sweat = a.get("sweat")
    if hot:
        if a.get("heat_tolerance") == "high" or "heat" in strengths:
            impact = "helps"
        elif a.get("heat_tolerance") == "low" or "heat" in limiters:
            impact = "risk"
        else:
            impact = "watch"
        tip = "10-14 days of heat exposure in the last month (hot-weather sessions, extra layers, or sauna/hot bath after training) builds adaptation."
        if sweat in ("heavy", "salty"):
            tip += " As a heavy or salty sweater, aim for 500-1,000 mg sodium per hour and practise it in training."
        else:
            tip += " Take in sodium with your fluids and start drinking early."
        out.append(_f("heat", "Heat", impact, "Race-day weather is often hot." +
                      (" You handle heat well." if impact == "helps" else " Heat is a limiter for you." if impact == "risk" else ""), tip))
    if cold:
        impact = "helps" if "cold" in strengths else "watch" if "cold" in limiters else "neutral"
        out.append(_f("cold", "Cold", impact, "Cold conditions are likely at some point in the race.",
                      "Pack layers you can shed, gloves and a hat; cold blunts appetite, so keep eating on schedule."))

    # ---- terrain / technicality
    tech_txt = _text(event.get("course"), (event.get("info") or {}).get("terrain")).lower()
    technical = etype in ("trail", "mountaineering") or bool(re.search(r"technical|rocky|singletrack|scree|roots|talus", tech_txt))
    if technical:
        trail_access = terrain & {"trails", "mountains"}
        if "technical_terrain" in limiters:
            impact = "risk"
        elif "technical_terrain" in strengths:
            impact = "helps"
        elif terrain and not trail_access:
            impact = "watch"
        else:
            impact = "neutral"
        out.append(_f("terrain", "Trail terrain", impact,
                      "Expect trail or technical footing." + (" You don't have trails to train on." if terrain and not trail_access else ""),
                      "Get time on similar ground: technical sections at easy effort, plus ankle and balance strength work."))

    # ---- open water
    if etype == "triathlon" or (etype == "swimming" and re.search(r"open water|lake|sea|ocean|river", tech_txt + " " + str(event.get("name") or ""), re.I)):
        if "open_water" in limiters:
            impact = "risk"
        elif "open_water" in strengths:
            impact = "helps"
        elif "open_water" not in terrain:
            impact = "watch"
        else:
            impact = "neutral"
        out.append(_f("open_water", "Open-water swim", impact,
                      "The swim is in open water." + (" You haven't listed open-water access." if "open_water" not in terrain else ""),
                      "Do at least 3-4 open-water swims before race day: sighting every 6-8 strokes, swimming in a group, and your wetsuit."))

    # ---- distance vs experience
    hours = HOURS.get(dist)
    years = a.get("years_training")
    if hours:
        dur = f"about {hours:.0f} hours" if hours >= 2 else f"about {round(hours * 60)} minutes"
        if "endurance" in limiters and hours >= 3:
            out.append(_f("duration", "Race length", "watch", f"A long day ({dur}), and you listed endurance as a limiter.",
                          "Build the long session steadily and practise race fueling on every one."))
        elif isinstance(years, int) and years < 2 and hours >= 10:
            out.append(_f("duration", "Race length", "risk", f"A very long day ({dur}) with under two years of training behind you.",
                          "Prioritise consistency and long sessions over intensity; consider a shorter race first if the plan feels too steep."))
        elif isinstance(years, int) and years < 1 and hours >= 4:
            out.append(_f("duration", "Race length", "watch", f"A long day ({dur}) for your first year of training.",
                          "Keep most training easy and grow the long session gradually."))
        elif "endurance" in strengths and hours >= 3:
            out.append(_f("duration", "Race length", "helps", f"A long day ({dur}); endurance is one of your strengths.",
                          "Your edge is late in the race: be patient early."))
        if hours >= 18:
            impact = "helps" if "night" in strengths else "watch" if "night" in limiters else "neutral"
            out.append(_f("night", "Night hours", impact, "You'll likely be out through the night.",
                          "Do a few runs in the dark with your race headlamp, and plan caffeine for the low hours."))

    out.sort(key=lambda f: ORDER[f["impact"]])
    return {"factors": out, "summary": _summary(out), "elevation": alt,
            "course_profile": prof, "climb_m_per_km": round(per_km, 1) if per_km is not None else None}


def _summary(factors: list[dict[str, str]]) -> str:
    if not factors:
        return "Nothing stands out about this race for you. Add details (elevation, course, weather) or your strengths to get more."
    bad = [f["title"].lower() for f in factors if f["impact"] in ("risk", "watch")]
    good = [f["title"].lower() for f in factors if f["impact"] == "helps"]
    parts = []
    if bad:
        parts.append(f"Prepare for {_join(bad)}.")
    if good:
        parts.append(f"In your favor: {_join(good)}.")
    if not parts:
        return "A fair fit: nothing here works strongly for or against you."
    return " ".join(parts)


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


__all__ = ["analyze", "race_elevation", "course_profile"]
