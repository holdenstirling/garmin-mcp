"""Weather-aware workouts over HTTP (weather.py does the forecast and the rules).

* ``GET /app/api/weather/next``: today and the next 2 days: the day's weather and the planned
  sessions with their weather badges (Home's "Next 3 days" card, Day view chips).
* ``GET /app/api/weather/session?session_id=``: one session within the forecast: the hourly
  strip around it, adjusted run paces (display only), safety notes and the best time to go.

Location: the saved location's coordinates when there is one, else the home city (geocoded).
The stored plan never changes. Athletes only (coach 403 through ``_plan_api``).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import anyio

from . import geo
from .planbuilder import iter_sessions
from .plancal import target_pace
from .weather import adjust, best_time, forecast, hours_for, strip


class WeatherService:
    def __init__(self, *, plans: Any, pcal: Any, coach: Any, store: Any, fetch: Any = None) -> None:
        self._plans = plans
        self._pcal = pcal
        self._coach = coach
        self._store = store
        self._fetch = fetch or forecast

    async def _wx(self, uid: str, today: date) -> dict[str, Any] | None:
        athlete = self._coach.athlete(uid) or {}
        saved = await anyio.to_thread.run_sync(lambda: geo.load_saved(self._store, uid))
        loc = geo.resolve(athlete.get("interests") or {}, athlete, saved)
        place = geo.label(loc) or str(athlete.get("home_location") or "").strip()
        try:
            with anyio.fail_after(10):
                if loc.get("lat") is not None and loc.get("lon") is not None:
                    return await self._fetch(lat=float(loc["lat"]), lon=float(loc["lon"]), place=place, today=today)
                if place:
                    return await self._fetch(place=place, today=today)
        except Exception:
            return None
        return None

    def _ctx(self, uid: str) -> tuple[date, dict[str, Any], float, bool]:
        today, _acts, athlete, thr, _src, imperial = self._pcal._ctx(uid)
        return today, athlete, thr, imperial

    def _hour_now(self, uid: str, day: str, today: date) -> int | None:
        """For today: the next full hour (no suggesting a time that's already gone)."""
        if day != today.isoformat():
            return None
        try:
            now = self._pcal._now(uid)
            return now.hour + (1 if now.minute else 0)
        except Exception:
            return None

    @staticmethod
    def _opts(athlete: dict[str, Any], wx: dict[str, Any]) -> dict[str, Any]:
        home = athlete.get("home_elevation_m")
        return {"elevation_m": wx.get("elevation_m"),
                "home_elevation_m": float(home) if isinstance(home, int | float) else None,
                "acclimatized": bool(athlete.get("altitude_acclimatized"))}

    async def next_days(self, uid: str) -> dict[str, Any]:
        today, athlete, thr, imperial = await anyio.to_thread.run_sync(lambda: self._ctx(uid))
        wx = await self._wx(uid, today)
        plan = await anyio.to_thread.run_sync(lambda: self._plans.get(uid))
        by_day: dict[str, list[dict[str, Any]]] = {}
        if plan:
            for _w, d, s in iter_sessions(plan):
                if s.get("sport") != "rest":
                    by_day.setdefault(d, []).append(s)
        days = []
        for i in range(3):
            d = (today + timedelta(days=i)).isoformat()
            wday = next((x for x in (wx or {}).get("days", []) if x["date"] == d), None)
            sessions = []
            for s in sorted(by_day.get(d, []), key=lambda x: (x.get("time") or "99", x.get("title") or "")):
                item: dict[str, Any] = {"id": s.get("id"), "title": s.get("title"), "sport": s.get("sport"),
                                        "minutes": s.get("minutes"), "time": s.get("time"), "badges": [], "pct": 0.0}
                if wx:
                    hrs = hours_for(wx["hours"], d, s.get("time"), s.get("minutes"), self._hour_now(uid, d, today))
                    pace = target_pace(s, thr)
                    adj = adjust(s, hrs, pace=(pace["fast"], pace["slow"]) if pace else None, imperial=imperial,
                                 **self._opts(athlete, wx))
                    item["badges"], item["pct"] = adj["badges"], adj["pct"]
                sessions.append(item)
            days.append({"date": d, "weather": wday, "sessions": sessions})
        return {"units": "imperial" if imperial else "metric", "place": (wx or {}).get("place"),
                "available": wx is not None, "today": today.isoformat(), "has_plan": bool(plan), "days": days}

    async def session(self, uid: str, sid: str) -> dict[str, Any]:
        today, athlete, thr, imperial = await anyio.to_thread.run_sync(lambda: self._ctx(uid))
        plan = await anyio.to_thread.run_sync(lambda: self._plans.get(uid))
        found = next(((d, s) for _w, d, s in iter_sessions(plan or {}) if s.get("id") == sid), None)
        if found is None:
            raise LookupError("session")
        d, s = found
        units = "imperial" if imperial else "metric"
        if not (today.isoformat() <= d <= (today + timedelta(days=2)).isoformat()):
            return {"available": False, "reason": "range", "date": d, "units": units}
        wx = await self._wx(uid, today)
        if wx is None:
            return {"available": False, "reason": "unreachable", "date": d, "units": units}
        nb = self._hour_now(uid, d, today)
        bt = best_time(wx["hours"], d, s.get("minutes"), s.get("time"), not_before=nb)
        hrs = hours_for(wx["hours"], d, s.get("time"), s.get("minutes"), nb)
        pace = target_pace(s, thr)
        adj = adjust(s, hrs, pace=(pace["fast"], pace["slow"]) if pace else None, imperial=imperial,
                     **self._opts(athlete, wx))
        center = int((s.get("time") or (bt or {}).get("start") or "08:00")[:2])
        return {"available": True, "date": d, "units": units, "place": wx.get("place"),
                "elevation_m": wx.get("elevation_m"), "planned_time": s.get("time"),
                "strip": strip(wx["hours"], d, center), "day": next((x for x in wx["days"] if x["date"] == d), None),
                "adjust": adj, "planned_pace": {"fast": pace["fast"], "slow": pace["slow"]} if pace else None,
                "best": bt}


__all__ = ["WeatherService"]
