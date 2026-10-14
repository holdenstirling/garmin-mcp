"""Where the athlete is, for Explore (races near you, local activities).

Resolution order (``resolve``):

1. the saved location: "Use my location" (``source: "device"``; the browser's coordinates are
   rounded to 2 decimals (~1 km) *before* anything else happens and reverse-geocoded
   server-side via OpenStreetMap Nominatim) or a zip typed into Explore (``"manual"``). Stored
   as the profile field ``location`` = ``{lat, lon, city, state, zip, source, updated}`` (a
   sibling of the athlete record in the profile doc, so it never reaches Rabbit's context, a
   coach's view or friends). Precise coordinates are never stored or logged.
2. ``interests.home_zip``
3. a 5-digit zip in ``athlete.home_location``
4. a city/state in ``athlete.home_location`` -> a state code ("Denver, CO", "Leadville, Colorado")
5. nothing. The athlete's timezone is deliberately *not* used to guess a state (Mountain time
   spans many states); callers fall back to a nationwide search labelled as such.

"Use my location for local picks" (profile ``location_use``, default on) gates the Near you
places/activities; "Forget my location" clears ``location``.

Nominatim usage policy: an identifying User-Agent, at most 1 request per second across the
whole process (``Throttle``), and results cached by rounded coordinates / zip for 30 days
(memory + an encrypted global doc, so restarts don't re-ask).
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import httpx2

REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
SEARCH_URL = "https://nominatim.openstreetmap.org/search"
CACHE_S = 30 * 86400
CACHE_MAX = 5000  # in memory
DOC_MAX = 300     # in the encrypted global doc (it's rewritten whole on every put)
MAX_WAIT_S = 5.0  # longest queue for a Nominatim/Overpass slot before "try again"
MIN_INTERVAL_S = 1.0
LOC_KEYS = ("lat", "lon", "city", "state", "zip", "source", "updated")
SOURCES = ("device", "manual")
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
    return f"RabbitTraining/1.0 (+{contact or 'unknown'})"


# --------------------------------------------------------------- throttle --
class Busy(Exception):
    """The shared request queue is too long right now."""


BUSY_MESSAGE = "Lots of people are looking right now. Try again in a few seconds."


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

    async def wait(self, max_wait: float | None = MAX_WAIT_S) -> None:
        """Wait for our slot. Raises ``Busy`` (without taking a slot) when the queue is
        longer than ``max_wait`` seconds, so a burst gets a friendly "try again"."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            if max_wait is not None and slot - now > max_wait:
                raise Busy()
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
            saved: dict[str, Any] | None) -> dict[str, Any]:
    """{"source", "zip", "state", "city", "lat", "lon"}; source is None when nothing usable is
    known (then the caller searches nationwide). ``lat``/``lon`` (2 decimals) only come with a
    saved location; the caller geocodes a zip/city when it needs coordinates."""
    interests, athlete = interests or {}, athlete or {}
    a = saved or {}
    if a.get("zip") or (a.get("state") in US_STATES):
        return {"source": a.get("source") if a.get("source") in SOURCES else "device",
                "zip": a.get("zip") or "", "state": a.get("state") or "", "city": a.get("city") or "",
                "lat": a.get("lat"), "lon": a.get("lon")}
    home = parse_home(athlete.get("home_location"))
    none = {"lat": None, "lon": None}
    if interests.get("home_zip"):
        same_zip = home["zip"] == interests["home_zip"]
        return {"source": "home_zip", "zip": interests["home_zip"], "state": home["state"] if same_zip else "",
                "city": home["city"] if same_zip else "", **none}
    if home["zip"]:
        return {"source": "profile_zip", **home, **none}
    if home["state"]:
        return {"source": "profile_city", **home, **none}
    # Step 5: no timezone guess. A saved place outside the US isn't usable for RunSignup but
    # still gives a city (and coordinates) for local activities.
    return {"source": None, "zip": "", "state": str(a.get("state") or ""), "city": str(a.get("city") or ""),
            "lat": a.get("lat"), "lon": a.get("lon")}


def searchable(loc: dict[str, Any]) -> bool:
    return bool(loc.get("zip") or loc.get("state") in US_STATES)


def label(loc: dict[str, Any]) -> str:
    """"Denver, CO" / "80204" / "CO" / ""."""
    if loc.get("city") and loc.get("state"):
        return f"{loc['city']}, {loc['state']}"
    return loc.get("zip") or loc.get("state") or loc.get("city") or ""


# ------------------------------------------------------------- the store --
def _valid_saved(v: Any) -> dict[str, Any] | None:
    if not isinstance(v, dict):
        return None
    out = {k: v.get(k) for k in LOC_KEYS}
    if out["source"] not in SOURCES:
        out["source"] = "device"
    return out


def load_saved(store: Any, uid: str) -> dict[str, Any] | None:
    """The saved location (``location``), or a pre-v2 ``location_auto`` read as a device one."""
    if store is None:
        return None
    prof = store.user_doc(uid, "profile").load()
    if isinstance(prof.get("location"), dict):
        return _valid_saved(prof["location"])
    old = prof.get("location_auto")
    if isinstance(old, dict):
        return _valid_saved({"lat": old.get("lat2"), "lon": old.get("lon2"), "city": old.get("city"),
                             "state": old.get("state"), "zip": old.get("zip"), "source": "device",
                             "updated": old.get("ts")})
    return None


def save_location(store: Any, uid: str, place: dict[str, Any], lat: Any, lon: Any, source: str,
                  now: float) -> dict[str, Any]:
    """Store only the coarse place: coordinates rounded to 2 decimals, city/state/zip."""
    lat2, lon2 = round2(lat, lon)
    entry = {"lat": lat2, "lon": lon2, "city": str(place.get("city") or "")[:60],
             "state": str(place.get("state") or "")[:40], "zip": str(place.get("zip") or "")[:5],
             "source": source if source in SOURCES else "device", "updated": int(now)}
    assert tuple(entry) == LOC_KEYS

    def put(p: dict[str, Any]) -> None:
        p["location"] = entry
        p.pop("location_auto", None)
    store.user_doc(uid, "profile").update(put)
    return entry


def forget(store: Any, uid: str) -> None:
    if store is not None:
        def put(p: dict[str, Any]) -> None:
            p.pop("location", None)
            p.pop("location_auto", None)
        store.user_doc(uid, "profile").update(put)


def use_for_local(store: Any, uid: str) -> bool:
    """"Use my location for local picks" (on unless the athlete turned it off)."""
    if store is None:
        return True
    return store.user_doc(uid, "profile").load().get("location_use") is not False


def set_use_for_local(store: Any, uid: str, on: bool) -> None:
    def put(p: dict[str, Any]) -> None:
        p["location_use"] = bool(on)
    store.user_doc(uid, "profile").update(put)


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
                if len(d) > DOC_MAX:
                    for k in sorted(d, key=lambda k: float(d[k].get("ts", 0)))[: len(d) - DOC_MAX]:
                        d.pop(k, None)
            self._store.global_doc("geocache").update(put)

    # File IO stays off the event loop.
    async def _acached(self, key: str) -> dict[str, str] | None:
        with self._lock:
            hit = self._mem.get(key)
        if hit is not None or self._store is None:
            return self._cached(key)
        return await anyio.to_thread.run_sync(self._cached, key)

    async def _aput(self, key: str, value: dict[str, str]) -> None:
        await anyio.to_thread.run_sync(self._put, key, value)

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
        hit = await self._acached(key)
        if hit is not None:
            return hit
        try:
            body = await self._get(REVERSE_URL, {"format": "jsonv2", "lat": f"{lat2:.2f}", "lon": f"{lon2:.2f}",
                                                 "zoom": "10", "addressdetails": "1"})
        except Busy:
            raise LocationError(BUSY_MESSAGE) from None
        except Exception:
            raise LocationError("Couldn't look up that location right now. Try again, or enter a zip.") from None
        place = parse_place(body)
        if not (place["city"] or place["state"] or place["zip"]):
            raise LocationError("Couldn't find a town there. Enter a zip instead.")
        await self._aput(key, place)
        return place

    async def zip_place(self, zip_: str, *, strict: bool = False) -> dict[str, Any]:
        """"80204" -> {"zip", "city", "state", "country", "lat", "lon"} ({} when unknown or upstream
        trouble; ``strict`` raises ``LocationError`` when the shared queue is busy)."""
        if not isinstance(zip_, str) or not re.fullmatch(r"\d{5}", zip_):
            return {}
        key = f"z:{zip_}"
        hit = await self._acached(key)
        if hit is not None:
            return hit
        try:
            body = await self._get(SEARCH_URL, {"format": "jsonv2", "postalcode": zip_, "countrycodes": "us",
                                                "addressdetails": "1", "limit": "1"})
        except Busy:
            if strict:
                raise LocationError(BUSY_MESSAGE) from None
            return {}
        except Exception:
            return {}
        first = body[0] if isinstance(body, list) and body else {}
        place = {**parse_place(first), **_coords(first)}
        place["zip"] = zip_
        if place["city"] or place["state"]:
            await self._aput(key, place)
        return place

    async def city_place(self, city: str, state: str) -> dict[str, Any]:
        """"Denver", "CO" -> {"city", "state", "zip", "country", "lat", "lon"} ({} when unknown)."""
        city, state = " ".join(str(city or "").split())[:60], str(state or "").strip()[:40]
        if not city or not state:
            return {}
        key = f"c:{city.lower()}|{state.upper()}"
        hit = await self._acached(key)
        if hit is not None:
            return hit
        try:
            body = await self._get(SEARCH_URL, {"format": "jsonv2", "city": city, "state": state,
                                                "countrycodes": "us", "addressdetails": "1", "limit": "1"})
        except Exception:
            return {}
        first = body[0] if isinstance(body, list) and body else {}
        place = {**parse_place(first), **_coords(first)}
        if place.get("lat") is not None:
            await self._aput(key, place)
        return place

    async def coords(self, loc: dict[str, Any]) -> tuple[float, float] | None:
        """Rounded coordinates for a resolved location (saved ones carry them; a zip or a
        city/state is geocoded and cached). None when unknown."""
        if isinstance(loc.get("lat"), int | float) and isinstance(loc.get("lon"), int | float):
            try:
                return round2(loc["lat"], loc["lon"])
            except LocationError:
                return None
        place: dict[str, Any] = {}
        if loc.get("zip"):
            place = await self.zip_place(str(loc["zip"]))
        if place.get("lat") is None and loc.get("city") and loc.get("state"):
            place = await self.city_place(str(loc["city"]), str(loc["state"]))
        if isinstance(place.get("lat"), int | float) and isinstance(place.get("lon"), int | float):
            return float(place["lat"]), float(place["lon"])
        return None


def _coords(item: Any) -> dict[str, Any]:
    """Nominatim "lat"/"lon" strings -> rounded floats (or {})."""
    try:
        lat2, lon2 = round2(float(item["lat"]), float(item["lon"]))
    except (KeyError, TypeError, ValueError, LocationError):
        return {}
    return {"lat": lat2, "lon": lon2}


__all__ = [
    "STATE_CODES",
    "US_STATES",
    "BUSY_MESSAGE",
    "Busy",
    "Geocoder",
    "LocationError",
    "Throttle",
    "forget",
    "label",
    "load_saved",
    "parse_home",
    "parse_place",
    "resolve",
    "round2",
    "save_location",
    "searchable",
    "set_use_for_local",
    "state_code",
    "use_for_local",
    "user_agent",
]
