"""HTTP routes for Community -> "Clubs & leagues near you" (``clubdir``). Athletes only (built on
``community_web``'s guards: session, Host, Origin + JSON on mutating calls, coach accounts 403,
allowlisted athlete).

    GET  /app/api/community/directory?kind=run|trail|tri|ride|swim|leagues&weekday=mon..sun
         -> {metro, status: ready|refreshing|queued|needs_location|unavailable|limit|busy,
             listings, counts, refreshed, fallback}; the first request for a metro that's due
             starts a background refresh and returns Explore's cached local groups meanwhile.
    POST /app/api/community/directory/suggest        {name, url, city?, state?}
    POST /app/api/community/directory/{lid}/report
    POST /app/api/community/directory/{lid}/link     {club_id} (you own/admin that club)
    POST /app/api/community/directory/refresh        {city?, state?} owners only: force a refresh
    POST /app/api/community/directory/{lid}/going    {going: bool, date?} -> {going: {date, count, me,
         friends, more_friends}} for the listing's next occurrence (409 when ``date`` moved on)
    GET  /app/api/community/directory/{lid}/calendar.ics   weekly .ics (text/calendar, attachment)

Listing rows also carry ``lat``/``lon`` (geocoded public meet spot or null), ``calendar`` (has a
weekly time), ``next.date`` and ``going`` (null without a session); the view has ``center``.
All additive: older clients ignore them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from . import clubics
from .clubdir import CHIPS, Directory, DirectoryError, Metro, metro, weekday_of

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, directory: Directory, wrap: Callable[..., Any], home: Callable[[str], dict[str, str]],
                now: Callable[[str], datetime], today: Callable[[str], date],
                local_groups: Callable[[str, str, date], list[dict[str, Any]] | None],
                is_owner: Callable[[str], bool], club_role: Callable[[str, str], str | None],
                read_json: Callable[[Request], Awaitable[Any]], going: Any = None) -> list[BaseRoute]:
    """``wrap(handler, mutating=)`` is community_web's guard; ``club_role(uid, cid)`` the
    athlete's role in a club or None."""

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except DirectoryError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return wrap(inner, mutating=mutating)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise DirectoryError("bad request")
        return b

    async def my_metro(uid: str) -> Metro | None:
        loc = await run(lambda: home(uid))
        return metro(loc.get("city"), loc.get("state"))

    async def listing(request: Request, user_id: str) -> Response:
        chip = request.query_params.get("kind") or None
        if chip is not None and chip not in CHIPS:
            raise DirectoryError("bad kind")
        wd = weekday_of(request.query_params.get("weekday"))
        m = await my_metro(user_id)
        if m is None:
            return JSONResponse({"metro": None, "status": "needs_location", "listings": [], "counts": {},
                                 "refreshed": None, "fallback": []})
        local_now = await run(lambda: now(user_id))
        v = await run(lambda: directory.view(m, now_local=local_now, chip=chip, weekday=wd, uid=user_id))
        if going is not None:
            await run(lambda: going.attach(user_id, m, v["listings"]))
        status = v.pop("state")
        due = v.pop("due")
        if status == "idle":
            status = directory.kick(m, uid=user_id) if due else "ready"
        if status == "queued" and v["listings"]:
            status = "refreshing"
        fallback: list[dict[str, Any]] = []
        if not v["listings"] and not chip and not wd:
            try:
                raw = await run(lambda: local_groups(m.city, m.state, today(user_id))) or []
            except Exception:
                raw = []
            fallback = [{k: g.get(k) for k in ("id", "name", "category", "organizer", "when", "where", "url")}
                        for g in raw if isinstance(g, dict)][:8]
        return JSONResponse({**v, "status": status, "fallback": fallback})

    async def suggest(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        city, state = b.get("city"), b.get("state")
        if not city or not state:
            loc = await run(lambda: home(user_id))
            city, state = city or loc.get("city"), state or loc.get("state")
        out = await run(lambda: directory.suggest(user_id, b.get("name"), b.get("url"), city, state))
        return JSONResponse(out, status_code=202)

    async def report(request: Request, user_id: str) -> Response:
        m = await my_metro(user_id)
        if m is None:
            raise DirectoryError("not found", 404)
        lid = request.path_params["listing_id"]
        return JSONResponse(await run(lambda: directory.report(user_id, m, lid)))

    async def link(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        cid = b.get("club_id")
        m = await my_metro(user_id)
        if m is None or not isinstance(cid, str):
            raise DirectoryError("not found", 404)
        role = await run(lambda: club_role(user_id, cid))
        if role not in ("owner", "admin"):
            raise DirectoryError("Only the club's owner or admins can link it.", 403)
        lid = request.path_params["listing_id"]
        await run(lambda: directory.link(m, lid, cid))
        return JSONResponse({"ok": True})

    async def mark_going(request: Request, user_id: str) -> Response:
        if going is None:
            raise DirectoryError("not found", 404)
        b = await body_of(request)
        m = await my_metro(user_id)
        if m is None:
            raise DirectoryError("not found", 404)
        local_now = await run(lambda: now(user_id))
        row = await run(lambda: directory.get(m, request.path_params["listing_id"], now_local=local_now, uid=user_id))
        out = await run(lambda: going.set(user_id, m, row, b.get("going"), day=b.get("date"), today=local_now.date()))
        return JSONResponse({"going": out})

    async def ics(request: Request, user_id: str) -> Response:
        m = await my_metro(user_id)
        if m is None:
            raise DirectoryError("not found", 404)
        local_now = await run(lambda: now(user_id))
        row = await run(lambda: directory.get(m, request.path_params["listing_id"], now_local=local_now, uid=user_id))
        try:
            text = clubics.listing_ics(row, local_now, host=request.url.hostname or "rabbit")
        except ValueError:
            raise DirectoryError("This group has no weekly time to add.", 404) from None
        return Response(text.encode("utf-8"), media_type="text/calendar; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{clubics.filename(row["name"])}"',
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    async def refresh(request: Request, user_id: str) -> Response:
        if not is_owner(user_id):
            raise DirectoryError("Only the app owner can do that.", 403)
        b = await body_of(request)
        m = metro(b.get("city"), b.get("state")) if b.get("city") else await my_metro(user_id)
        if m is None:
            raise DirectoryError("Add a US city and state.")
        return JSONResponse({"status": directory.kick(m, force=True), "metro": m.label}, status_code=202)

    P = "/app/api/community/directory"
    return [
        Route(P, guarded(listing, mutating=False), methods=["GET"]),
        Route(f"{P}/suggest", guarded(suggest, mutating=True), methods=["POST"]),
        Route(f"{P}/refresh", guarded(refresh, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/report", guarded(report, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/link", guarded(link, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/going", guarded(mark_going, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/calendar.ics", guarded(ics, mutating=False), methods=["GET"]),
    ]


__all__ = ["make_routes"]
