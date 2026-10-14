"""Where the athlete is, for Explore (races near you, local activities).

Resolution order (``resolve``):

1. device location: the athlete tapped "Use my location"; the browser's coordinates are
   rounded to 2 decimals (~1 km) *before* anything else happens, reverse-geocoded
   server-side (OpenStreetMap Nominatim) and only ``{zip, city, state, lat2, lon2, ts}`` is
   stored, in the profile doc as ``location_auto`` (a sibling of ``athlete``, so it never
   reaches Rabbit's context or a coach's view). Precise coordinates are never stored.
2. ``interests.home_zip``
3. a 5-digit zip in ``athlete.home_location``
4. a city/state in ``athlete.home_location`` -> a state code ("Denver, CO", "Leadville, Colorado")
5. nothing: the app asks inline (zip field + "Use my location").

Nominatim usage policy: an identifying User-Agent, at most 1 request per second across the
whole process (``Throttle``), and results cached by rounded coordinates for 30 days (memory +
an encrypted global doc, so restarts don't re-ask).
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
SEARCH_URL = "https://nominatim.openstreetmap.org/search"
CACHE_S = 30 * 86400
CACHE_MAX = 5000
MIN_INTERVAL_S = 1.0
AUTO_KEYS = ("zip", "city", "state", "lat2", "lon2", "ts")
# Tests swap this for an httpx2.MockTransport.
TRANSPORT: httpx2.AsyncBaseTransport | None = None

STATE_CODES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR",
}
US_STATES = frozenset(STATE_CODES.values())
_ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_NAME_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, STATE_CODES), key=len, reverse=True)) + r")\b", re.IGNORECASE)


class LocationError(ValueError):
    """A message that goes to the app as-is."""


# ------------------------------------------------------------- coordinates --
def round2(lat: Any, lon: Any) -> tuple[float, float]:
    """Validate and round to 2 decimals (~1 km). Everything downstream sees only these."""
    ok = all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lon))
    if not ok or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LocationError("That location doesn't look right.")
    return round(float(lat), 2), round(float(lon), 2)


def user_agent(contact: str) -> str:
    return f"RabbitTraining/1.0 (contact: {contact or 'unknown'})"


# --------------------------------------------------------------- throttle --
class Throttle:
    """At most one request per ``interval`` seconds, process-wide. Each caller reserves the
    next slot under a thread lock, then sleeps until it (works across event loops)."""

    def __init__(self, interval: float = MIN_INTERVAL_S, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    async def wait(self) -> None:
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            await self._sleep(slot - now)


_THROTTLE = Throttle()


# ---------------------------------------------------------------- parsing --
def state_code(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if s.upper() in US_STATES and len(s) == 2:
        return s.upper()
    return STATE_CODES.get(s.lower(), "")


def parse_place(body: Any) -> dict[str, str]:
    """Nominatim jsonv2 -> {"zip", "city", "state", "country"} (state is a US code when US)."""
    addr = body.get("address") if isinstance(body, dict) else None
    if not isinstance(addr, dict):
        return {"zip": "", "city": "", "state": "", "country": ""}
    country = str(addr.get("country_code") or "").lower()[:2]
    m = _ZIP.match(str(addr.get("postcode") or "").strip())
    zip_ = m.group(1) if m and country in ("us", "") else ""
    city = next((str(addr[k]) for k in ("city", "town", "village", "hamlet", "municipality", "suburb")
                 if isinstance(addr.get(k), str) and addr[k].strip()), "")
    if not city and isinstance(addr.get("county"), str):
        city = re.sub(r"\s+County$", "", addr["county"])
    iso = str(addr.get("ISO3166-2-lvl4") or "")
    st = iso[3:] if iso.startswith("US-") else state_code(addr.get("state"))
    if not st and country not in ("us", ""):
        st = str(addr.get("state") or "")[:40]
    return {"zip": zip_, "city": " ".join(city.split())[:60], "state": st[:40], "country": country}


def parse_home(home_location: Any) -> dict[str, str]:
    """Free-text home location -> {"zip", "city", "state"} (best effort, US-focused)."""
    out = {"zip": "", "city": "", "state": ""}
    if not isinstance(home_location, str) or not home_location.strip():
        return out
    text = " ".join(home_location.split())
    m = _ZIP.search(text)
    if m:
        out["zip"] = m.group(1)
        text = (text[:m.start()] + text[m.end():]).strip(" ,")
    st, cut = "", None
    # A capitalised two-letter code as its own word ("Denver, CO"); lower-case "in"/"or" aren't states.
    for mm in re.finditer(r"\b([A-Z]{2})\b", text):
        if mm.group(1) in US_STATES:
            st, cut = mm.group(1), mm
    if not st:
        mm2 = None
        for mm2 in _STATE_NAME_RE.finditer(text):
            pass
        if mm2:
            st, cut = STATE_CODES[mm2.group(1).lower()], mm2
    if st and cut is not None:
        out["state"] = st
        before = text[:cut.start()].strip(" ,")
        out["city"] = before.split(",")[-1].strip()[:60] if before else ""
    return out


# ---------------------------------------------------------------- resolve --
def resolve(interests: dict[str, Any] | None, athlete: dict[str, Any] | None,
            auto: dict[str, Any] | None) -> dict[str, Any]:
    """{"source", "zip", "state", "city"}; source is None when nothing is known."""
    interests, athlete = interests or {}, athlete or {}
    a = auto or {}
    if a.get("zip") or (a.get("state") in US_STATES):
        return {"source": "device", "zip": a.get("zip") or "", "state": a.get("state") or "",
                "city": a.get("city") or ""}
    home = parse_home(athlete.get("home_location"))
    if interests.get("home_zip"):
        same_zip = home["zip"] == interests["home_zip"]
        return {"source": "home_zip", "zip": interests["home_zip"], "state": home["state"] if same_zip else "",
                "city": home["city"] if same_zip else ""}
    if home["zip"]:
        return {"source": "profile_zip", **home}
    if home["state"]:
        return {"source": "profile_city", **home}
    # Not usable for races (e.g. outside the US) but still a city for local activities.
    return {"source": None, "zip": "", "state": str(a.get("state") or ""), "city": str(a.get("city") or "")}


def label(loc: dict[str, Any]) -> str:
    """"Denver, CO" / "80204" / "CO" / ""."""
    if loc.get("city") and loc.get("state"):
        return f"{loc['city']}, {loc['state']}"
    return loc.get("zip") or loc.get("state") or loc.get("city") or ""


# ------------------------------------------------------------- the store --
def load_auto(store: Any, uid: str) -> dict[str, Any] | None:
    if store is None:
        return None
    v = store.user_doc(uid, "profile").load().get("location_auto")
    return v if isinstance(v, dict) else None


def save_auto(store: Any, uid: str, place: dict[str, Any], lat2: float, lon2: float, now: float) -> dict[str, Any]:
    entry = {"zip": str(place.get("zip") or "")[:5], "city": str(place.get("city") or "")[:60],
             "state": str(place.get("state") or "")[:40], "lat2": round(float(lat2), 2),
             "lon2": round(float(lon2), 2), "ts": int(now)}
    assert set(entry) == set(AUTO_KEYS)

    def put(p: dict[str, Any]) -> None:
        p["location_auto"] = entry
    store.user_doc(uid, "profile").update(put)
    return entry


def forget(store: Any, uid: str) -> None:
    if store is not None:
        store.user_doc(uid, "profile").update(lambda p: p.pop("location_auto", None))


# --------------------------------------------------------------- geocoder --
class Geocoder:
    """Nominatim reverse (rounded coords -> place) and zip -> city/state, cached 30 days."""

    def __init__(self, *, contact: str, store: Any = None, transport: httpx2.AsyncBaseTransport | None = None,
                 throttle: Throttle | None = None, clock: Callable[[], float] = time.time,
                 timeout: float = 8.0) -> None:
        self.ua = user_agent(contact)
        self._store = store
        self._transport = transport
        self._throttle = throttle or _THROTTLE
        self._clock = clock
        self._timeout = timeout
        self._mem: dict[str, tuple[float, dict[str, str]]] = {}
        self._lock = threading.Lock()
        self.requests = 0

    # cache ------------------------------------------------------------
    def _cached(self, key: str) -> dict[str, str] | None:
        now = self._clock()
        with self._lock:
            hit = self._mem.get(key)
        if hit is None and self._store is not None:
            raw = self._store.global_doc("geocache").load().get(key)
            if isinstance(raw, dict) and isinstance(raw.get("v"), dict):
                hit = (float(raw.get("ts", 0)), raw["v"])
        if hit and now - hit[0] < CACHE_S:
            with self._lock:
                self._mem[key] = hit
            return dict(hit[1])
        return None

    def _put(self, key: str, value: dict[str, str]) -> None:
        now = self._clock()
        with self._lock:
            self._mem[key] = (now, value)
            if len(self._mem) > CACHE_MAX:
                for k in sorted(self._mem, key=lambda k: self._mem[k][0])[: len(self._mem) - CACHE_MAX]:
                    del self._mem[k]
        if self._store is not None:
            def put(d: dict[str, Any]) -> None:
                d[key] = {"ts": now, "v": value}
                stale = [k for k, v in d.items() if not isinstance(v, dict) or now - float(v.get("ts", 0)) >= CACHE_S]
                for k in stale:
                    d.pop(k, None)
                if len(d) > CACHE_MAX:
                    for k in sorted(d, key=lambda k: float(d[k].get("ts", 0)))[: len(d) - CACHE_MAX]:
                        d.pop(k, None)
            self._store.global_doc("geocache").update(put)

    async def _get(self, url: str, params: dict[str, str]) -> Any:
        await self._throttle.wait()
        self.requests += 1
        transport = self._transport or TRANSPORT
        client = httpx2.AsyncClient(timeout=self._timeout, transport=transport) if transport is not None \
            else httpx2.AsyncClient(timeout=self._timeout)
        async with client:
            r = await client.get(url, params=params, headers={"User-Agent": self.ua, "Accept": "application/json",
                                                             "Accept-Language": "en"})
            r.raise_for_status()
            return r.json()

    # lookups ------------------------------------------------------------
    async def reverse(self, lat2: float, lon2: float) -> dict[str, str]:
        lat2, lon2 = round2(lat2, lon2)
        key = f"r:{lat2:.2f},{lon2:.2f}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        try:
            body = await self._get(REVERSE_URL, {"format": "jsonv2", "lat": f"{lat2:.2f}", "lon": f"{lon2:.2f}",
                                                 "zoom": "10", "addressdetails": "1"})
        except Exception:
            raise LocationError("Couldn't look up that location right now. Try again, or enter a zip.") from None
        place = parse_place(body)
        if not (place["city"] or place["state"] or place["zip"]):
            raise LocationError("Couldn't find a town there. Enter a zip instead.")
        self._put(key, place)
        return place

    async def zip_place(self, zip_: str) -> dict[str, str]:
        """"80204" -> {"zip", "city", "state", "country"} ({} when unknown or upstream trouble)."""
        if not isinstance(zip_, str) or not re.fullmatch(r"\d{5}", zip_):
            return {}
        key = f"z:{zip_}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        try:
            body = await self._get(SEARCH_URL, {"format": "jsonv2", "postalcode": zip_, "countrycodes": "us",
                                                "addressdetails": "1", "limit": "1"})
        except Exception:
            return {}
        first = body[0] if isinstance(body, list) and body else {}
        place = parse_place(first)
        place["zip"] = zip_
        if place["city"] or place["state"]:
            self._put(key, place)
        return place


__all__ = [
    "STATE_CODES",
    "US_STATES",
    "Geocoder",
    "LocationError",
    "Throttle",
    "forget",
    "label",
    "load_auto",
    "parse_home",
    "parse_place",
    "resolve",
    "round2",
    "save_auto",
    "state_code",
    "user_agent",
]
