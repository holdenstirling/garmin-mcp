"""HTTP routes for race-week mode (``raceweek``). Built by ``webapp.build_app_routes`` with its
guards (``plan_api``: session, Host, Origin + JSON on mutating calls, coach accounts 403).

    GET  /app/api/raceweek                       home card: the race whose week it is, or null
    GET  /app/api/raceweek/friends               mutual friends racing today (tracking on)
    GET  /app/api/raceweek/track/{user_id}       one friend's race status (mutuals only, else 403)
    GET  /app/api/raceweek/{event_id}            the race-week page
    PUT  /app/api/raceweek/{event_id}            {target_s?, start_time?, tracking?, notify_friends?}
    POST /app/api/raceweek/{event_id}/packing    {toggle | add | remove}
    POST /app/api/raceweek/{event_id}/reminders  {add | toggle | remove}
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from urllib.parse import quote

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from . import predict as _predict, racepack
from . import raceweek as rw
from .logs import log_event

logger = logging.getLogger(__name__)
Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, svc: rw.RaceWeek, plan_api: Callable[..., Any], read_json: Callable[[Request], Awaitable[Any]],
                now: Callable[[str], Any], athlete: Callable[[str], dict[str, Any]],
                plan_of: Callable[[str], dict[str, Any] | None], gear: Callable[[str], list[dict[str, Any]]],
                basis: Callable[[str], dict[str, Any]], grade: Callable[[str, str], dict[str, Any] | None],
                person: Callable[[str], dict[str, Any] | None],
                forecast: Callable[..., Awaitable[dict[str, Any] | None]] = racepack.forecast) -> list[BaseRoute]:

    def wrap(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await handler(request, user_id)
            except rw.RaceWeekError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return plan_api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    def imperial(uid: str) -> bool:
        return athlete(uid).get("units") != "metric"

    def defaults(uid: str, ev: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            views = gear(uid)
        except Exception:  # the default list stands without the garage
            views = []
        return rw.packing_defaults(ev, views, imperial=imperial(uid))

    def counts(uid: str, ev: dict[str, Any]) -> tuple[int, int]:
        v = rw.packing_view(defaults(uid, ev), (svc.saved(uid, ev["id"]).get("packing")))
        return v["done"], v["total"]

    def card(uid: str) -> dict[str, Any] | None:
        local = now(uid)
        today = local.date()
        hit = rw.race_week(svc._events(uid), today)
        if hit is None:
            return None
        ev, days = hit["event"], hit["days"]
        plan = plan_of(uid) if ev.get("main") else None
        g = None
        try:
            g = grade(uid, ev["id"])
        except Exception as e:  # Garmin busy: the card still shows
            log_event(logger, logging.INFO, "raceweek_grade_failed", user_id=uid, error=type(e).__name__)
        done, total = counts(uid, ev)
        return {"event": {k: ev.get(k) for k in ("id", "name", "type", "distance", "date", "location", "priority", "main")},
                "days": days, "race_day": days == 0,
                "taper": rw.taper(plan, date.fromisoformat(ev["date"]), today),
                "today": rw.today_sessions(plan_of(uid), today),
                "readiness": ({"grade": g.get("grade"), "status": g.get("status"), "headline": g.get("headline")}
                              if g and g.get("grade") else None),
                "packing": {"done": done, "total": total},
                "tracking": bool(svc.saved(uid, ev["id"]).get("tracking"))}

    async def home(request: Request, user_id: str) -> Response:
        return JSONResponse({"raceweek": await run(lambda: card(user_id))})

    async def page(request: Request, user_id: str) -> Response:
        eid = str(request.path_params["event_id"])[:64]
        ev = await run(lambda: svc.event(user_id, eid))
        local = now(user_id)
        today = local.date()
        race_day = date.fromisoformat(ev["date"])
        ath = athlete(user_id)
        saved = svc.saved(user_id, eid)

        def estimate() -> tuple[dict[str, Any] | None, dict[str, Any]]:
            inputs = _predict.event_inputs(ev)["kwargs"]
            try:
                b = basis(user_id)
                res = _predict.predict_event(b, ev, today=today) if _predict.has_data(b) else None
            except Exception as e:  # no Garmin: the goal time still splits
                log_event(logger, logging.INFO, "raceweek_estimate_failed", user_id=user_id, error=type(e).__name__)
                res = None
            return res, inputs
        est, inputs = await run(estimate)
        pacing = rw.pacing_plan(ev, ath, est, inputs, saved.get("target_s"))
        wx = await forecast(ev.get("location") or "", race_day, today)
        hot = bool(inputs.get("hot")) or bool(wx and isinstance(wx.get("high_c"), int | float) and wx["high_c"] >= 25)
        hours = (pacing["target_s"] or 0) / 3600 or racepack.fueling(ev, ath)["expected_hours"]
        plan = await run(lambda: plan_of(user_id) if ev.get("main") else None)
        pack_defaults = await run(lambda: defaults(user_id, ev))
        days = (race_day - today).days
        info = ev.get("info") or {}
        st = None
        if -rw.TRACK_DAYS_AFTER <= days <= 0:
            def status() -> dict[str, Any]:
                return rw.status(ev, saved, local, svc._acts_of(user_id))
            st = await run(status)
        course = {"text": ev.get("course") or "", "profile": ev.get("course_profile"),
                  "climb_m": inputs.get("climb_m"), "elevation_m": inputs.get("elevation_m"),
                  "terrain": info.get("terrain"), "typical_weather": info.get("typical_weather"),
                  "weather": wx, "weather_tips": racepack.build(ev, ath, None, today, wx)["weather_tips"]}
        loc = str(ev.get("location") or "")
        body = {
            "event": {k: ev.get(k) for k in ("id", "name", "type", "distance", "date", "location", "url", "priority",
                                             "main", "target_time")},
            "days": days, "race_day": days == 0, "imperial": ath.get("units") != "metric",
            "taper": rw.taper(plan, race_day, today),
            "today": rw.today_sessions(plan_of(user_id), today) if days >= 0 else [],
            "pacing": pacing,
            "course": course,
            "packing": rw.packing_view(pack_defaults, saved.get("packing")),
            "nutrition": rw.nutrition_plan(hours, hot=hot, weight_kg=ath.get("weight_kg")),
            "logistics": {"start_time": rw.start_time(ev, saved), "start_custom": bool(saved.get("start_time")),
                          "location": loc, "maps_url": (f"https://www.openstreetmap.org/search?query={quote(loc)}"
                                                        if loc else None),
                          "url": ev.get("url") or None, "registration": info.get("registration"),
                          "reminders": sorted(saved.get("reminders") or [],
                                              key=lambda x: (x.get("when") or "9999", x["id"]))},
            "tracking": {"on": bool(saved.get("tracking")), "notify_friends": bool(saved.get("notify_friends")),
                         "status": st, "audience": len(await run(lambda: svc.audience(user_id))),
                         "note": "Friends who follow you back see: not started, racing (time since your planned "
                                 "start) or finished. Live times when your watch syncs; no live location."},
        }
        return JSONResponse(body)

    async def put(request: Request, user_id: str) -> Response:
        eid = str(request.path_params["event_id"])[:64]
        b = await read_json(request)
        saved = await run(lambda: svc.put(user_id, eid, b))
        return JSONResponse({"saved": {k: saved.get(k) for k in ("target_s", "start_time", "tracking", "notify_friends")}})

    async def packing(request: Request, user_id: str) -> Response:
        eid = str(request.path_params["event_id"])[:64]
        b = await read_json(request)

        def go() -> dict[str, Any]:
            ev = svc.event(user_id, eid)
            return svc.packing(user_id, eid, b, defaults(user_id, ev))
        return JSONResponse(await run(go))

    async def reminders(request: Request, user_id: str) -> Response:
        eid = str(request.path_params["event_id"])[:64]
        b = await read_json(request)
        return JSONResponse({"reminders": await run(lambda: svc.reminders(user_id, eid, b))})

    async def friends(request: Request, user_id: str) -> Response:
        rows = await run(lambda: svc.friends_racing(user_id))
        return JSONResponse({"friends": [{**r, "user": person(r.pop("user_id"))} for r in rows]})

    async def track(request: Request, user_id: str) -> Response:
        other = str(request.path_params["user_id"])[:80]
        r = await run(lambda: svc.track(user_id, other))
        return JSONResponse({**r, "user": person(r.pop("user_id"))})

    return [
        Route("/app/api/raceweek", wrap(home, mutating=False), methods=["GET"]),
        Route("/app/api/raceweek/friends", wrap(friends, mutating=False), methods=["GET"]),
        Route("/app/api/raceweek/track/{user_id}", wrap(track, mutating=False), methods=["GET"]),
        Route("/app/api/raceweek/{event_id}", wrap(page, mutating=False), methods=["GET"]),
        Route("/app/api/raceweek/{event_id}", wrap(put, mutating=True), methods=["PUT"]),
        Route("/app/api/raceweek/{event_id}/packing", wrap(packing, mutating=True), methods=["POST"]),
        Route("/app/api/raceweek/{event_id}/reminders", wrap(reminders, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
