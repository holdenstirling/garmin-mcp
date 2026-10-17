""""My area" for Local (clubs, leagues, meetups) and Schedule > Discover: a centre (the athlete's
saved "Use my location" / zip spot, else the metro centre) and a radius they pick (2-50 mi).

``filter_rows`` keeps the rows inside the radius, sorted nearest first. A row without a mapped
spot can't be measured: it stays (it's in the athlete's city) with ``distance_km: None`` so the
app can say "in your city" instead of a distance. Filters for activity (``activity.classify``),
weekday and time of day apply on top.

The radius lives in the athlete's ``profile`` doc as ``local_radius_mi``.
"""

from __future__ import annotations

from typing import Any

from .geo import km_between

RADII_MI = (2, 5, 10, 25, 50)
DEFAULT_MI = 10
KM_PER_MI = 1.609344
WHEN = ("morning", "midday", "evening")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def clean_radius(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float) or int(v) not in RADII_MI:
        raise ValueError(f"radius_mi must be one of {', '.join(map(str, RADII_MI))}")
    return int(v)


def radius_mi(store: Any, uid: str) -> int:
    if store is None:
        return DEFAULT_MI
    v = store.user_doc(uid, "profile").load().get("local_radius_mi")
    return int(v) if isinstance(v, int) and v in RADII_MI else DEFAULT_MI


def set_radius(store: Any, uid: str, mi: Any) -> int:
    r = clean_radius(mi)

    def put(p: dict[str, Any]) -> None:
        p["local_radius_mi"] = r
    store.user_doc(uid, "profile").update(put)
    return r


def part_of_day(hhmm: Any) -> str | None:
    """"06:30" -> morning (before 11), midday (11-16), evening (16 on); None without a time."""
    if not isinstance(hhmm, str) or len(hhmm) < 4 or ":" not in hhmm:
        return None
    try:
        h = int(hhmm.split(":")[0])
    except ValueError:
        return None
    return "morning" if h < 11 else "midday" if h < 16 else "evening"


def _point(row: dict[str, Any]) -> tuple[float, float] | None:
    lat, lon = row.get("lat"), row.get("lon")
    if isinstance(lat, int | float) and isinstance(lon, int | float) and not isinstance(lat, bool):
        return float(lat), float(lon)
    return None


def filter_rows(rows: list[dict[str, Any]], *, center: tuple[float, float] | None, radius_km: float,
                activity: str | None = None, weekday: str | None = None, when: str | None = None
                ) -> tuple[list[dict[str, Any]], int]:
    """(kept rows with ``distance_km`` set, number left out for being farther than the radius).

    Rows keep their order among the unmeasured; measured rows come first, nearest first."""
    near: list[tuple[float, dict[str, Any]]] = []
    unmeasured: list[dict[str, Any]] = []
    farther = 0
    for r in rows:
        if activity and r.get("activity") != activity:
            continue
        sessions = [s for s in r.get("sessions") or [] if isinstance(s, dict)]
        if weekday in WEEKDAYS and not any(s.get("weekday") == weekday for s in sessions):
            continue
        if when in WHEN and not any(part_of_day(s.get("time")) == when for s in sessions):
            continue
        p = _point(r)
        if center is None or p is None:
            unmeasured.append({**r, "distance_km": None})
            continue
        d = km_between(center, p)
        if d > radius_km:
            farther += 1
            continue
        near.append((d, {**r, "distance_km": round(d, 1)}))
    near.sort(key=lambda t: t[0])
    return [r for _, r in near] + unmeasured, farther


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """{activity id: rows} for the filter chips (only activities that have rows)."""
    out: dict[str, int] = {}
    for r in rows:
        a = r.get("activity")
        if isinstance(a, str):
            out[a] = out.get(a, 0) + 1
    return out


def view(*, label: str, radius: int, center: tuple[float, float] | None, source: str | None) -> dict[str, Any]:
    """The ``area`` block every Local / Discover response carries."""
    return {"label": label, "radius_mi": radius, "radii_mi": list(RADII_MI),
            "has_point": center is not None, "source": source}


__all__ = ["DEFAULT_MI", "KM_PER_MI", "RADII_MI", "WHEN", "clean_radius", "counts", "filter_rows", "part_of_day",
           "radius_mi", "set_radius", "view"]
