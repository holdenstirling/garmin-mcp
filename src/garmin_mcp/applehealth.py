"""Apple Watch / Apple Health workouts, sent by the athlete's own iPhone Shortcut.

Apple Health has no web API: only an app on the iPhone can read it. Rabbit is a web app, so the
athlete builds a Shortcut (Shortcuts app, steps shown in the connect popup) that finds their
recent workouts in Health and POSTs them here with a personal import key:

    POST /app/api/import/apple-health
    Authorization: Bearer <key>
    {"workouts": [{"type": "Running", "start": "Oct 17, 2026 at 7:02 AM",
                   "end": "...", "duration": "45 min", "distance": "5.2 mi"}, ...]}

The key (``ImportKeys``): random, shown once, only its SHA-256 is stored (per-user doc plus a
global hash -> user index, like ``calsub.CalSub``). Re-creating it stops the old one; turning
Apple Watch off revokes it. Possession of the key only lets someone add workouts to that one
account, never read anything.

Parsing (``parse_payload``) is lenient on purpose, because a Shortcut's output depends on the
iPhone's language settings: a JSON list, ``{"workouts": [...]}``, or text with one JSON object
per workout (what "Combine Text" makes); dates as ISO 8601 (with or without offset) or the
iPhone's written style ("Oct 17, 2026 at 7:02 AM", "17 Oct 2026 at 07:02", "10/17/26, 7:02 AM");
durations as minutes, "45 min", "1 hr 5 min", "1:05:00"; distances as "5.2 mi", "8.4 km",
"1,500 m" or a bare number (``distance_unit`` or the athlete's units). Heart rate, energy and
anything else are dropped on the floor and never stored.

Imported workouts are stored by the route with the ``workouts.py`` store as source ``apple``: shown on
their day and, when the athlete shares workouts, as a feed card. Display-only, like Oura: they
never enter Garmin stats, plan matching or anything Rabbit's AI sees. A workout Garmin also has
(Garmin Connect can write to Apple Health) counts once: Garmin's.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

SOURCE = "apple"
LABEL = "Apple Watch"
TOKEN_BYTES = 24
MAX_BODY = 256 * 1024
MAX_ITEMS = 200
MAX_AGE_DAYS = 60       # older workouts in a payload are ignored
DOC = "applehealth"
INDEX = "applehealth-index"

# Apple's HKWorkoutActivityType names (as Shortcuts shows them, in English) -> Rabbit sport.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"triathlon|multisport|swim.?bike.?run"), "other"),
    (re.compile(r"swim"), "swim"),
    (re.compile(r"cycl|bik|ride|spin"), "bike"),
    (re.compile(r"hik"), "hike"),
    (re.compile(r"walk|wheelchair walk"), "walk"),
    (re.compile(r"run|jog"), "run"),
    (re.compile(r"strength|weight|functional|core training|cross training|crossfit"), "strength"),
]


def sport_of(kind: Any) -> str:
    k = re.sub(r"^HKWorkoutActivityType", "", str(kind or "").strip(), flags=re.I)
    k = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", k).lower()
    for rx, sport in _RULES:
        if rx.search(k):
            return sport
    return "other"


def _name_of(kind: Any, sport: str) -> str:
    k = str(kind or "").strip()
    k = re.sub(r"^HKWorkoutActivityType", "", k)
    k = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", k).strip()
    if k and len(k) <= 60 and re.fullmatch(r"[\w .,'&()/+-]+", k):
        return k[:1].upper() + k[1:]
    return {"run": "Run", "bike": "Ride", "swim": "Swim", "walk": "Walk", "hike": "Hike",
            "strength": "Strength", "other": "Workout"}[sport]


# ----------------------------------------------------------------- dates --
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_SPACES = re.compile(r"[   \s]+")


def _clock(t: str) -> tuple[int, int, int] | None:
    """'7:02 AM', '19:02', '7:02:13 pm' -> (h, m, s)."""
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*([ap]\.?\s?m\.?)?", t.strip(), re.I)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    ap = (m.group(4) or "").lower().replace(".", "").replace(" ", "")
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59 or s > 59:
        return None
    return h, mi, s


def parse_when(v: Any, *, today: datetime | None = None) -> datetime | None:
    """A Shortcuts date -> naive local wall time (the iPhone's clock), or None."""
    if not isinstance(v, str):
        return None
    s = _SPACES.sub(" ", v).strip()
    if not s or len(s) > 60:
        return None
    # ISO 8601 (with or without seconds/offset).
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?", s)
    if m:
        try:
            return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
        except ValueError:
            return None
    s = re.sub(r"\s+at\s+|,\s*|\s+um\s+|\s+à\s+", " ", s, flags=re.I).strip()
    parts = s.split(" ")
    # Find the time (the part with a colon, plus an AM/PM that follows).
    ti = next((i for i, p in enumerate(parts) if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?([ap]m)?", p, re.I)), None)
    if ti is None:  # 07.02 style clocks, only when nothing has a colon
        ti = next((i for i, p in enumerate(parts) if re.fullmatch(r"\d{1,2}\.\d{2}([ap]m)?", p, re.I)), None)
    if ti is None:
        return None
    tstr = parts[ti]
    rest = parts[:ti] + parts[ti + 1:]
    if ti + 1 < len(parts) and re.fullmatch(r"[ap]\.?m\.?", parts[ti + 1], re.I):
        tstr += " " + parts[ti + 1]
        rest = parts[:ti] + parts[ti + 2:]
    hms = _clock(tstr)
    if hms is None:
        return None
    d = " ".join(rest).strip(" ,")
    y = mo = dd = None
    if (m := re.fullmatch(r"([A-Za-z]{3,})\.? (\d{1,2}) (\d{4})", d)):        # Oct 17 2026
        mo, dd, y = _MONTHS.get(m.group(1)[:3].lower()), int(m.group(2)), int(m.group(3))
    elif (m := re.fullmatch(r"(\d{1,2})\.? ([A-Za-z]{3,})\.? (\d{4})", d)):   # 17 Oct 2026
        dd, mo, y = int(m.group(1)), _MONTHS.get(m.group(2)[:3].lower()), int(m.group(3))
    elif (m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", d)):            # 10/17/26 (US)
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mo, dd = (a, b) if a <= 12 else (b, a)
    elif (m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", d)):          # 17.10.26
        dd, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif (m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", d)):
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif d.lower() in ("today", "yesterday") and today is not None:
        base = today - timedelta(days=1 if d.lower() == "yesterday" else 0)
        y, mo, dd = base.year, base.month, base.day
    if y is None or mo is None or dd is None:
        return None
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, dd, *hms)
    except ValueError:
        return None


# --------------------------------------------------- duration and distance --
def parse_minutes(v: Any) -> float | None:
    """45 / "45" (minutes), "45 min", "1 hr 5 min", "1h 5m", "1:05:00", "3720 s"."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v) if 0 < v < 24 * 60 else None
    if not isinstance(v, str):
        return None
    s = _SPACES.sub(" ", v).strip().lower().replace(",", " ")
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        n = float(s)
        return n if 0 < n < 24 * 60 else None
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s):
        p = [int(x) for x in s.split(":")]
        mins = p[0] * 60 + p[1] + p[2] / 60 if len(p) == 3 else p[0] + p[1] / 60
        return mins if mins > 0 else None
    total, hit = 0.0, False
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", s):
        hit = True
        x = float(n)
        total += x * 60 if unit.startswith("h") else x / 60 if unit.startswith("s") else x
    return total if hit and 0 < total < 24 * 60 else None


_UNIT_KM = {"km": 1.0, "kilometers": 1.0, "kilometres": 1.0, "mi": 1.609344, "mile": 1.609344, "miles": 1.609344,
            "m": 0.001, "meters": 0.001, "metres": 0.001, "yd": 0.0009144, "yds": 0.0009144, "yards": 0.0009144}


def parse_km(v: Any, unit: Any = None, *, imperial: bool = True) -> float | None:
    """"5.2 mi" / "8.4 km" / "1,500 m" / 5.2 (+ ``unit``, else the athlete's units) -> km."""
    if isinstance(v, bool) or v is None:
        return None
    n: float | None = None
    u = str(unit or "").strip().lower() or None
    if isinstance(v, int | float):
        n = float(v)
    elif isinstance(v, str):
        s = _SPACES.sub(" ", v).strip().lower()
        m = re.fullmatch(r"(\d{1,3}(?:,\d{3})+|\d+)(?:[.,](\d+))?\s*([a-z]*)", s)
        if not m:
            return None
        whole = m.group(1).replace(",", "")
        n = float(f"{whole}.{m.group(2)}" if m.group(2) else whole)
        u = m.group(3) or u
    if n is None or n <= 0:
        return None
    factor = _UNIT_KM.get(u or ("mi" if imperial else "km"))
    if factor is None:
        return None
    km = round(n * factor, 2)
    return km if 0 < km < 1000 else None


# ---------------------------------------------------------------- payload --
def _items(body: Any) -> list[Any]:
    """The workouts in whatever shape the Shortcut sent."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        s = body.strip()
        try:
            return _items(json.loads(s))
        except ValueError:
            pass
        out: list[Any] = []
        dec = json.JSONDecoder()
        i = 0
        while i < len(s) and len(out) <= MAX_ITEMS:
            j = s.find("{", i)
            if j < 0:
                break
            try:
                obj, end = dec.raw_decode(s, j)
            except ValueError:
                i = j + 1
                continue
            if isinstance(obj, dict):
                out.extend(_items(obj) if "workouts" in obj else [obj])
            i = end
        return out
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        w = body.get("workouts", body.get("data"))
        if isinstance(w, str):
            return _items(w)
        if isinstance(w, list):
            # A list of Text items from the Shortcut: each may itself be a JSON string.
            return [x for it in w for x in (_items(it) if isinstance(it, str) else [it])]
        if any(k in body for k in ("start", "startDate", "start_date", "Start Date")):
            return [body]
    return []


def _get(d: dict[str, Any], *names: str) -> Any:
    low = {re.sub(r"[\s_-]", "", str(k)).lower(): v for k, v in d.items()}
    for n in names:
        v = low.get(re.sub(r"[\s_-]", "", n).lower())
        if v not in (None, ""):
            return v
    return None


def from_apple(raw: Any, *, imperial: bool = True, now: datetime | None = None) -> dict[str, Any] | None:
    """One workout from the Shortcut -> ``workouts.py`` model, or None. Keeps only sport,
    start, minutes and distance; heart rate, energy and the rest are dropped."""
    if not isinstance(raw, dict):
        return None
    now = now or datetime.now()
    start = parse_when(_get(raw, "start", "startDate", "start date", "begin"), today=now)
    if start is None or start > now + timedelta(hours=2) or start < now - timedelta(days=MAX_AGE_DAYS):
        return None
    end = parse_when(_get(raw, "end", "endDate", "end date"), today=now)
    mins = parse_minutes(_get(raw, "minutes", "duration", "duration (minutes)", "durationminutes"))
    if mins is None and end is not None and end > start:
        span = (end - start).total_seconds() / 60
        mins = span if span < 24 * 60 else None
    kind = _get(raw, "type", "workout type", "workoutactivitytype", "activity", "activitytype", "name", "sport")
    sport = sport_of(kind)
    km = parse_km(_get(raw, "distance", "totaldistance", "distance (mi)", "distance (km)"),
                  _get(raw, "distance_unit", "unit", "distanceunit"), imperial=imperial)
    if km is None:
        for k, unit in (("distance (mi)", "mi"), ("distance (km)", "km")):
            if (v := _get(raw, k)) is not None:
                km = parse_km(v, unit, imperial=imperial)
    if sport == "strength":
        km = None
    wid = f"{start.strftime('%Y%m%dT%H%M')}-{sport}"
    return {"key": f"{SOURCE}:{wid}", "source": SOURCE, "id": wid, "sport": sport,
            "name": _name_of(kind, sport), "start": start.isoformat(),
            "minutes": round(mins) if mins else None, "km": km, "avg_hr": None, "calories": None}


def parse_payload(body: Any, *, imperial: bool = True, now: datetime | None = None) -> tuple[list[dict[str, Any]], int]:
    """(workouts, how many items were skipped). One per key; at most ``MAX_ITEMS``."""
    items = _items(body)[:MAX_ITEMS]
    out: dict[str, dict[str, Any]] = {}
    skipped = 0
    for it in items:
        w = from_apple(it, imperial=imperial, now=now)
        if w is None:
            skipped += 1
            continue
        out[w["key"]] = w
    return list(out.values()), skipped


# ------------------------------------------------------------- import keys --
class ImportKeys:
    """Per-user secret import keys (only SHA-256 hashes are stored)."""

    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _index(self) -> Any:
        return self._s.global_doc(INDEX)

    def _doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, DOC)

    def status(self, uid: str) -> dict[str, Any] | None:
        d = self._doc(uid).load()
        if not d.get("hash"):
            return None
        return {"created": d.get("created"), "last_import": d.get("last_import"),
                "last_received": d.get("last_received"), "last_new": d.get("last_new")}

    def create(self, uid: str) -> str:
        """A new key; the old one, if any, stops working at once."""
        token = "rbt_" + secrets.token_urlsafe(TOKEN_BYTES)
        h = self._hash(token)
        old: dict[str, Any] = {}

        def put(d: dict[str, Any]) -> None:
            old.update(d)
            keep = {k: d[k] for k in ("last_import", "last_received", "last_new") if k in d}
            d.clear()
            d.update(keep, hash=h, created=int(self._clock()))
        self._doc(uid).update(put)

        def idx(d: dict[str, Any]) -> None:
            if old.get("hash"):
                d.pop(old["hash"], None)
            d[h] = uid
        self._index().update(idx)
        return token

    def revoke(self, uid: str) -> None:
        old: dict[str, Any] = {}

        def drop(d: dict[str, Any]) -> None:
            old.update(d)
            d.clear()
        self._doc(uid).update(drop)
        if old.get("hash"):
            self._index().update(lambda d: d.pop(old["hash"], None))

    def lookup(self, token: Any) -> str | None:
        if not isinstance(token, str) or not 20 <= len(token) <= 80 or not token.startswith("rbt_"):
            return None
        h = self._hash(token)
        uid = self._index().load().get(h)
        if not uid:
            return None
        # The user's own doc must still agree (a revoke that only half finished never works).
        return uid if self._doc(uid).load().get("hash") == h else None

    def note_import(self, uid: str, received: int, new: int) -> None:
        def put(d: dict[str, Any]) -> None:
            if d.get("hash"):
                d.update(last_import=int(self._clock()), last_received=received, last_new=new)
        self._doc(uid).update(put)


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    m = re.fullmatch(r"\s*Bearer\s+(\S+)\s*", header, re.I)
    return m.group(1) if m else None


__all__ = ["ImportKeys", "LABEL", "MAX_BODY", "SOURCE", "bearer", "from_apple", "parse_km", "parse_minutes",
           "parse_payload", "parse_when", "sport_of"]
