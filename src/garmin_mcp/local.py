"""Explore "Near you": places to play within 8 km, from OpenStreetMap (Overpass API).

Volleyball / beach volleyball courts, running tracks, public pools, climbing gyms and crags,
bike parks and pump tracks, trailheads, outdoor fitness stations, pickleball and tennis
courts. One POST to Overpass per rounded location (2 decimals, ~1 km), polite (identifying
User-Agent, one request at a time process-wide, 25 s server timeout), cached 7 days in memory
and in the encrypted ``overpass`` global doc, so the same neighbourhood is asked about at most
once a week no matter how many athletes live there.

Only the rounded coordinates ever leave the server (to Overpass, never to the AI model), and
they are never logged. Everything from OSM is normalised to
``{id, name, kind, kind_label, lat, lon, distance_km, osm_url, tags: {lit, surface, access}}``.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx2

from . import geo

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIUS_M = 8000
TIMEOUT_S = 25
CACHE_S = 7 * 86400
CACHE_MAX = 2000
MAX_PLACES = 40
PER_KIND = 6
UNNAMED_PER_KIND = 2
# Tests swap this for an httpx2.MockTransport.
TRANSPORT: httpx2.AsyncBaseTransport | None = None

KINDS: dict[str, str] = {
    "volleyball": "Volleyball court", "track": "Running track", "pool": "Public pool",
    "climbing": "Climbing", "bike_park": "Bike park", "trailhead": "Trailhead",
    "fitness": "Fitness station", "pickleball": "Pickleball court", "tennis": "Tennis court",
}
_PRIVATE = {"private", "no", "customers", "members", "permit"}


def query(lat: float, lon: float, radius_m: int = RADIUS_M) -> str:
    """The Overpass QL for everything we show, around one (rounded) point."""
    a = f"(around:{int(radius_m)},{lat:.2f},{lon:.2f})"
    parts = [
        f'nwr["sport"~"^(beachvolleyball|volleyball)$"]{a};',
        f'nwr["leisure"="track"]["sport"~"athletics|running"]{a};',
        f'nwr["leisure"~"^(swimming_pool|sports_centre|water_park)$"]["sport"="swimming"]["access"!~"private|customers|members"]{a};',
        f'nwr["leisure"="swimming_pool"]["access"~"^(yes|public|permissive)$"]{a};',
        f'nwr["sport"="climbing"]{a};',
        f'nwr["sport"~"^(bmx|mtb)$"]{a};',
        f'nwr["cycling"="pump_track"]{a};',
        f'nwr["leisure"="track"]["sport"="cycling"]["bicycle"!="no"]{a};',
        f'node["highway"="trailhead"]{a};',
        f'nwr["leisure"="fitness_station"]{a};',
        f'nwr["leisure"="pitch"]["sport"~"pickleball|tennis"]{a};',
    ]
    return f"[out:json][timeout:{TIMEOUT_S}];\n(\n  " + "\n  ".join(parts) + "\n);\nout center tags 300;"


def kind_of(tags: dict[str, Any]) -> str | None:
    sport = str(tags.get("sport") or "").lower()
    sports = {x.strip() for x in sport.replace(",", ";").split(";") if x.strip()}
    leisure = str(tags.get("leisure") or "")
    if sports & {"beachvolleyball", "volleyball"}:
        return "volleyball"
    if leisure == "track" and sports & {"athletics", "running"}:
        return "track"
    if "climbing" in sports:
        return "climbing"
    if sports & {"bmx", "mtb"} or tags.get("cycling") == "pump_track" or (leisure == "track" and "cycling" in sports):
        return "bike_park"
    if leisure in ("swimming_pool", "sports_centre", "water_park") and (
            "swimming" in sports or leisure == "swimming_pool"):
        return "pool"
    if tags.get("highway") == "trailhead":
        return "trailhead"
    if leisure == "fitness_station":
        return "fitness"
    if "pickleball" in sports:
        return "pickleball"
    if "tennis" in sports:
        return "tennis"
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _short(v: Any, n: int) -> str:
    return " ".join(str(v).split())[:n] if isinstance(v, str | int | float) and not isinstance(v, bool) else ""


def parse(body: Any, lat: float, lon: float) -> list[dict[str, Any]]:
    """Overpass JSON -> our places, nearest first, a few per kind (unnamed ones capped)."""
    els = body.get("elements") if isinstance(body, dict) else None
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for el in els if isinstance(els, list) else []:
        if not isinstance(el, dict) or el.get("type") not in ("node", "way", "relation"):
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        kind = kind_of(tags)
        if kind is None or str(tags.get("access") or "").lower() in _PRIVATE:
            continue
        c = el if el.get("type") == "node" else (el.get("center") or {})
        try:
            plat, plon = float(c["lat"]), float(c["lon"])
            oid = int(el["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= plat <= 90 and -180 <= plon <= 180):
            continue
        name = _short(tags.get("name"), 80)
        key = (kind, name.lower() or f"#{oid}")
        if key in seen:
            continue
        seen.add(key)
        extra = {k: _short(tags.get(k), 30) for k in ("lit", "surface", "access") if tags.get(k)}
        out.append({"id": f"osm:{el['type']}/{oid}", "name": name or KINDS[kind], "named": bool(name),
                    "kind": kind, "kind_label": KINDS[kind], "lat": round(plat, 5), "lon": round(plon, 5),
                    "distance_km": round(distance_km(lat, lon, plat, plon), 1),
                    "osm_url": f"https://www.openstreetmap.org/{el['type']}/{oid}", "tags": extra})
    out.sort(key=lambda p: (p["distance_km"], p["name"].lower()))
    kept: list[dict[str, Any]] = []
    per: dict[str, int] = {}
    unnamed: dict[str, int] = {}
    for p in out:
        k = p["kind"]
        if per.get(k, 0) >= PER_KIND:
            continue
        if not p["named"]:
            if unnamed.get(k, 0) >= UNNAMED_PER_KIND:
                continue
            unnamed[k] = unnamed.get(k, 0) + 1
        per[k] = per.get(k, 0) + 1
        kept.append(p)
        if len(kept) >= MAX_PLACES:
            break
    return kept


class OverpassError(Exception):
    """Overpass didn't answer (rate limited, timed out, down)."""


class Places:
    """Cached Overpass lookups per rounded location (7 days)."""

    def __init__(self, *, contact: str, store: Any = None, transport: httpx2.AsyncBaseTransport | None = None,
                 throttle: geo.Throttle | None = None, clock: Callable[[], float] = time.time) -> None:
        self.ua = geo.user_agent(contact)
        self._store = store
        self._transport = transport
        self._throttle = throttle or _THROTTLE
        self._clock = clock
        self._mem: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self.requests = 0

    @staticmethod
    def key(lat: float, lon: float) -> str:
        lat2, lon2 = geo.round2(lat, lon)
        return f"{lat2:.2f},{lon2:.2f}"

    def cached(self, lat: float, lon: float) -> list[dict[str, Any]] | None:
        key, now = self.key(lat, lon), self._clock()
        with self._lock:
            hit = self._mem.get(key)
        if hit is None and self._store is not None:
            raw = self._store.global_doc("overpass").load().get(key)
            if isinstance(raw, dict) and isinstance(raw.get("places"), list):
                hit = (float(raw.get("ts", 0)), raw["places"])
        if hit and now - hit[0] < CACHE_S:
            with self._lock:
                self._mem[key] = hit
            return [dict(p) for p in hit[1]]
        return None

    def _put(self, key: str, places: list[dict[str, Any]]) -> None:
        now = self._clock()
        with self._lock:
            self._mem[key] = (now, places)
            if len(self._mem) > CACHE_MAX:
                for k in sorted(self._mem, key=lambda k: self._mem[k][0])[: len(self._mem) - CACHE_MAX]:
                    del self._mem[k]
        if self._store is None:
            return

        def put(d: dict[str, Any]) -> None:
            d[key] = {"ts": now, "places": places}
            for k in [k for k, v in d.items() if not isinstance(v, dict) or now - float(v.get("ts", 0)) >= CACHE_S]:
                d.pop(k, None)
            while len(d) > CACHE_MAX:
                d.pop(min(d, key=lambda k: float(d[k].get("ts", 0))))
        self._store.global_doc("overpass").update(put)

    async def near(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """Places within ``RADIUS_M`` of the rounded point (cached); OverpassError on trouble."""
        lat2, lon2 = geo.round2(lat, lon)
        hit = self.cached(lat2, lon2)
        if hit is not None:
            return hit
        await self._throttle.wait()
        self.requests += 1
        transport = self._transport or TRANSPORT
        kw: dict[str, Any] = {"timeout": TIMEOUT_S + 5}
        if transport is not None:
            kw["transport"] = transport
        try:
            async with httpx2.AsyncClient(**kw) as client:
                r = await client.post(OVERPASS_URL, data={"data": query(lat2, lon2)},
                                      headers={"User-Agent": self.ua, "Accept": "application/json"})
                r.raise_for_status()
                body = r.json()
        except Exception as e:
            raise OverpassError(type(e).__name__) from None
        places = parse(body, lat2, lon2)
        self._put(self.key(lat2, lon2), places)
        return places


# Overpass asks for a polite pace: one request at a time, at least a second apart.
_THROTTLE = geo.Throttle(1.0)


__all__ = ["KINDS", "OverpassError", "Places", "distance_km", "kind_of", "parse", "query"]
