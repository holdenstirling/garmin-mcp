"""Route maps for workouts: a small, privacy-trimmed line of a GPS workout.

Garmin's ``get_activity_details`` carries ``geoPolylineDTO.polyline`` (a point every few seconds).
``from_details`` turns it into what the app stores with a workout post and draws on the card:

* only outdoor families (run, walk, hike, ride, open-water swim) get a route; indoor, pool and
  gym sessions never do (``has_route``);
* the first and last ``trim_m`` metres are cut off (default 200 m; 200 / 400 / 800 are the
  choices), so the line never shows where someone starts or finishes, typically their door;
* the line is simplified (Douglas-Peucker, then a hard cap of ``MAX_POINTS``) and rounded to
  5 decimals (about a metre), so a post stores a few kilobytes, fetched once when it's made;
* ``start_cell`` is the start rounded to 3 decimals (about 100 m). It never leaves the server:
  it's only compared with the owner's "hide routes that start near here" spot (``near_home``).

Who sees a route is decided when a post is viewed (``community.view``): the owner always (if
"Show route maps" is on), others only when the owner turned on "Share route maps", and never when
the start is inside the owner's hidden area.
"""

from __future__ import annotations

import math
from typing import Any

MAX_POINTS = 150
TRIM_CHOICES = (200, 400, 800)
DEFAULT_TRIM_M = 200
HOME_RADIUS_CHOICES = (200, 400, 800, 1600)
OUTDOOR = {"run", "walk", "hike", "ride"}
_R = 6371000.0


def has_route(family: str | None, kind: str | None = None) -> bool:
    """Outdoor GPS workouts only: never indoor rides/runs, pool swims or gym sessions."""
    f, k = (family or "").lower(), (kind or "").lower()
    if any(w in k for w in ("indoor", "treadmill", "virtual", "trainer", "pool", "lap_swim")):
        return False
    if f == "swim":
        return "open" in k
    return f in OUTDOOR


def dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _R * math.asin(min(1.0, math.sqrt(h)))


def points_of(details: Any) -> list[tuple[float, float]]:
    """``(lat, lon)`` pairs from a ``get_activity_details`` response (bad points dropped)."""
    if not isinstance(details, dict):
        return []
    poly = (details.get("geoPolylineDTO") or {}).get("polyline") if isinstance(details.get("geoPolylineDTO"), dict) else None
    out: list[tuple[float, float]] = []
    for p in poly or []:
        if not isinstance(p, dict):
            continue
        lat, lon = p.get("lat"), p.get("lon")
        if isinstance(lat, int | float) and isinstance(lon, int | float) and -90 <= lat <= 90 and -180 <= lon <= 180 \
                and not (lat == 0 and lon == 0):
            out.append((float(lat), float(lon)))
    return out


def trim(points: list[tuple[float, float]], meters: float) -> list[tuple[float, float]]:
    """Drop the first and last ``meters`` of the path. Too short to keep anything: []."""
    if len(points) < 2 or meters <= 0:
        return list(points)
    cum = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        cum.append(cum[-1] + dist_m(a, b))
    total = cum[-1]
    if total <= 2 * meters + 50:
        return []
    return [p for p, c in zip(points, cum, strict=False) if meters <= c <= total - meters]


def _perp_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    # local equirectangular projection around a: good to well under a metre at route scale
    k = math.cos(math.radians(a[0]))
    ax, ay = 0.0, 0.0
    bx, by = (b[1] - a[1]) * k, b[0] - a[0]
    px, py = (p[1] - a[1]) * k, p[0] - a[0]
    seg = bx * bx + by * by
    if seg == 0:
        return math.hypot(px, py) * 111_320
    t = max(0.0, min(1.0, (px * bx + py * by) / seg))
    return math.hypot(px - (ax + t * bx), py - (ay + t * by)) * 111_320


def _dp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp_m(points[k], points[i], points[j])
            if d > best:
                best, idx = d, k
        if idx >= 0 and best > eps:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(points, keep, strict=False) if k]


def simplify(points: list[tuple[float, float]], max_points: int = MAX_POINTS) -> list[tuple[float, float]]:
    """Douglas-Peucker with a growing tolerance until it fits ``max_points``, then every n-th."""
    if len(points) <= max_points:
        return list(points)
    eps = 3.0
    out = _dp(points, eps)
    while len(out) > max_points and eps < 500:
        eps *= 1.6
        out = _dp(points, eps)
    if len(out) > max_points:
        step = math.ceil(len(out) / max_points)
        out = out[::step] + ([out[-1]] if (len(out) - 1) % step else [])
    return out


def from_details(details: Any, *, trim_m: int = DEFAULT_TRIM_M) -> dict[str, Any] | None:
    """``{"line": [[lat, lon], ...], "start_cell": [lat3, lon3]}`` or None (no usable GPS)."""
    pts = points_of(details)
    if len(pts) < 5:
        return None
    start = pts[0]
    kept = trim(pts, trim_m if trim_m in TRIM_CHOICES else DEFAULT_TRIM_M)
    if len(kept) < 2:
        return None
    line = [[round(a, 5), round(b, 5)] for a, b in simplify(kept)]
    return {"line": line, "start_cell": [round(start[0], 3), round(start[1], 3)]}


def near_home(route: dict[str, Any] | None, home: Any) -> bool:
    """Does this route start inside the owner's hidden area ``{lat, lon, radius_m}``?"""
    if not route or not isinstance(home, dict):
        return False
    cell = route.get("start_cell")
    try:
        lat, lon, r = float(home["lat"]), float(home["lon"]), float(home.get("radius_m") or 0)
    except (KeyError, TypeError, ValueError):
        return False
    if r <= 0 or not (isinstance(cell, list) and len(cell) == 2):
        return False
    # start_cell is rounded to ~100 m: widen by that so a start just outside never slips through
    return dist_m((float(cell[0]), float(cell[1])), (lat, lon)) <= r + 120


def public(route: dict[str, Any] | None) -> list[list[float]] | None:
    """What leaves the server: the trimmed line only, never the start cell."""
    if not route or not isinstance(route.get("line"), list) or len(route["line"]) < 2:
        return None
    return route["line"]


__all__ = ["from_details", "has_route", "near_home", "public", "simplify", "trim", "points_of",
           "TRIM_CHOICES", "HOME_RADIUS_CHOICES", "DEFAULT_TRIM_M", "MAX_POINTS"]
