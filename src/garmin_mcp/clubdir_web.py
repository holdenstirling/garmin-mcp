"""HTTP routes for Community -> "Clubs & leagues near you" (``clubdir``). Athletes only (built on
``community_web``'s guards: session, Host, Origin + JSON on mutating calls, coach accounts 403,
allowlisted athlete).

    GET  /app/api/community/directory?activity=run|trail|...|other&weekday=mon..sun&when=morning|midday|evening
         (older clients: kind=run|trail|tri|ride|swim|leagues)
         -> {metro, status: ready|refreshing|queued|needs_location|unavailable|limit|busy,
             listings, counts, refreshed, fallback, area, activities, farther}: only listings inside
             my area (``area.py``: my saved spot or the city centre + my radius), nearest first, each
             with ``distance_km`` (null = no mapped spot, shown as "in your city"), ``activity``,
             ``type``/``type_label`` (Club | League | Meetup); ``activities`` counts per activity in
             the area (filter chips), ``farther`` = left out for being outside the radius.
         The first request for a metro that's due
             starts a background refresh and returns Explore's cached local groups meanwhile.
    POST /app/api/community/directory/suggest        {name, url, city?, state?}
    POST /app/api/community/directory/{lid}/report
    POST /app/api/community/directory/{lid}/link     {club_id} (you own/admin that club)
    POST /app/api/community/directory/refresh        {city?, state?} owners only: force a refresh
    POST /app/api/community/directory/{lid}/going    {going: bool, date?} -> {going: {date, count, me,
         friends, more_friends}} for the listing's next occurrence (409 when ``date`` moved on)
    GET  /app/api/community/directory/{lid}/calendar.ics   weekly .ics (text/calendar, attachment)
    GET  /app/api/community/directory/search?q=&activity=&weekday=&when=
         -> {q, metro, partners, listings, can_look_up, area, farther} (same area rules)
         fuzzy name match ("5280 run club" finds "5280 Runners"); partners pinned, labelled
    POST /app/api/community/directory/lookup         {q} -> {status: found|none|limit|unavailable,
         listings}: one targeted web search for that name in my metro, read safely, added here

Partners (partners.py), labelled "Partner" wherever they show; the directory view carries
``partners`` (live partners for my metro):
    GET    /app/api/partners/{pid}                    one partner (only if it serves my metro)
    POST   /app/api/partners/{pid}/count              {what: view|website|instagram|signup|interested}
    GET    /app/api/partners/admin                    owner only: all partners + 30-day counts
    POST   /app/api/partners/admin                    owner only: add
    PUT    /app/api/partners/admin/{pid}              owner only: edit
    DELETE /app/api/partners/admin/{pid}              owner only: remove

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

from . import activity as _activity, area as _area, clubics
from .clubdir import CHIPS, Directory, DirectoryError, Metro, metro, weekday_of
from .partners import PartnerError, Partners

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, directory: Directory, wrap: Callable[..., Any], home: Callable[[str], dict[str, str]],
                now: Callable[[str], datetime], today: Callable[[str], date],
                local_groups: Callable[[str, str, date], list[dict[str, Any]] | None],
                is_owner: Callable[[str], bool], club_role: Callable[[str, str], str | None],
                read_json: Callable[[Request], Awaitable[Any]], going: Any = None,
                partners: Partners | None = None,
                area: Callable[[str], dict[str, Any]] | None = None) -> list[BaseRoute]:
    """``wrap(handler, mutating=)`` is community_web's guard; ``club_role(uid, cid)`` the
    athlete's role in a club or None."""

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except (DirectoryError, PartnerError) as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return wrap(inner, mutating=mutating)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise DirectoryError("bad request")
        return b

    async def my_area(uid: str, m: Metro, metro_center: Any) -> tuple[dict[str, Any], tuple[float, float] | None]:
        """(the response's ``area`` block, centre point): the saved spot when there is one, else
        the metro centre; the athlete's radius (default 10 mi)."""
        a = await run(lambda: area(uid)) if area is not None else {}
        c = a.get("center")
        source = a.get("source")
        if not (isinstance(c, tuple | list) and len(c) == 2):
            c = (metro_center["lat"], metro_center["lon"]) if isinstance(metro_center, dict) else None
            source = "city" if c else None
        center = (float(c[0]), float(c[1])) if c else None
        radius = int(a.get("radius_mi") or _area.DEFAULT_MI)
        label = str(a.get("label") or "") or m.label
        return _area.view(label=label, radius=radius, center=center, source=source), center

    def filters(request: Request) -> tuple[str | None, str | None, str | None]:
        act = request.query_params.get("activity") or None
        if act is not None and act not in _activity.IDS:
            raise DirectoryError("bad activity")
        when = request.query_params.get("when") or None
        if when is not None and when not in _area.WHEN:
            raise DirectoryError("bad time of day")
        return act, weekday_of(request.query_params.get("weekday")), when

    async def my_metro(uid: str) -> Metro | None:
        loc = await run(lambda: home(uid))
        return metro(loc.get("city"), loc.get("state"))

    async def listing(request: Request, user_id: str) -> Response:
        chip = request.query_params.get("kind") or None
        if chip is not None and chip not in CHIPS:
            raise DirectoryError("bad kind")
        act, wd, when = filters(request)
        m = await my_metro(user_id)
        if m is None:
            return JSONResponse({"metro": None, "status": "needs_location", "listings": [], "counts": {},
                                 "refreshed": None, "fallback": [], "area": None, "activities": {}, "farther": 0})
        local_now = await run(lambda: now(user_id))
        v = await run(lambda: directory.view(m, now_local=local_now, chip=chip, uid=user_id))
        # My area: the radius around my spot (else the city centre), then activity / day / time.
        area_view, center = await my_area(user_id, m, v.get("center"))
        radius_km = area_view["radius_mi"] * _area.KM_PER_MI
        in_area, _ = _area.filter_rows(v["listings"], center=center, radius_km=radius_km)
        v["activities"] = _area.counts(in_area)
        v["listings"], v["farther"] = _area.filter_rows(v["listings"], center=center, radius_km=radius_km,
                                                        activity=act, weekday=wd, when=when)
        v["area"] = area_view
        if going is not None:
            await run(lambda: going.attach(user_id, m, v["listings"]))
        status = v.pop("state")
        due = v.pop("due")
        if status == "idle":
            status = directory.kick(m, uid=user_id) if due else "ready"
        if status == "queued" and v["listings"]:
            status = "refreshing"
        fallback: list[dict[str, Any]] = []
        if not v["listings"] and not chip and not wd and not act and not when:
            try:
                raw = await run(lambda: local_groups(m.city, m.state, today(user_id))) or []
            except Exception:
                raw = []
            fallback = [{k: g.get(k) for k in ("id", "name", "category", "organizer", "when", "where", "url")}
                        for g in raw if isinstance(g, dict)][:8]
        near = await run(lambda: partners.near(m.city, m.state)) if partners is not None and not wd else []
        return JSONResponse({**v, "status": status, "fallback": fallback, "partners": near})

    async def search(request: Request, user_id: str) -> Response:
        q = " ".join((request.query_params.get("q") or "").split())[:60]
        act, wd, when = filters(request)
        m = await my_metro(user_id)
        if m is None:
            return JSONResponse({"q": q, "metro": None, "partners": [], "listings": [], "can_look_up": False,
                                 "area": None, "farther": 0})
        local_now = await run(lambda: now(user_id))
        rows = await run(lambda: directory.search(m, q, now_local=local_now, uid=user_id))
        center_doc = await run(lambda: directory.load(m).get("center"))
        area_view, center = await my_area(user_id, m, center_doc)
        rows, farther = _area.filter_rows(rows, center=center, radius_km=area_view["radius_mi"] * _area.KM_PER_MI,
                                          activity=act, weekday=wd, when=when)
        if going is not None and rows:
            await run(lambda: going.attach(user_id, m, rows))
        near = await run(lambda: partners.near(m.city, m.state, query=q)) if partners is not None and len(q) >= 2 else []
        return JSONResponse({"q": q, "metro": {"city": m.city, "state": m.state, "label": m.label},
                             "partners": near, "listings": rows, "area": area_view, "farther": farther,
                             "can_look_up": len(q) >= 3 and directory.can_look_up(user_id)})

    async def lookup(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        m = await my_metro(user_id)
        if m is None:
            raise DirectoryError("Add your home city in your training profile first.")
        local_now = await run(lambda: now(user_id))
        out = await directory.look_up(m, b.get("q"), uid=user_id, now_local=local_now)
        if going is not None and out["listings"]:
            await run(lambda: going.attach(user_id, m, out["listings"]))
        return JSONResponse(out)

    # ---------------------------------------------------------- partners --
    def need_partners() -> Partners:
        if partners is None:
            raise PartnerError("not found", 404)
        return partners

    async def partner_get(request: Request, user_id: str) -> Response:
        p = need_partners()
        m = await my_metro(user_id)
        if m is None:
            raise PartnerError("not found", 404)
        return JSONResponse(await run(lambda: p.get(request.path_params["pid"], m.city, m.state)))

    async def partner_count(request: Request, user_id: str) -> Response:
        p = need_partners()
        b = await body_of(request)
        m = await my_metro(user_id)
        if m is None:
            raise PartnerError("not found", 404)
        ok = await run(lambda: p.count(user_id, request.path_params["pid"], b.get("what"), m.city, m.state))
        return JSONResponse({"counted": ok})

    async def partner_admin(request: Request, user_id: str) -> Response:
        p = need_partners()
        return JSONResponse(await run(lambda: p.admin_list(user_id)))

    async def partner_add(request: Request, user_id: str) -> Response:
        p = need_partners()
        p.require_owner(user_id)
        b = await body_of(request)
        return JSONResponse(await run(lambda: p.save(user_id, b)), status_code=201)

    async def partner_edit(request: Request, user_id: str) -> Response:
        p = need_partners()
        p.require_owner(user_id)
        b = await body_of(request)
        return JSONResponse(await run(lambda: p.save(user_id, b, request.path_params["pid"])))

    async def partner_delete(request: Request, user_id: str) -> Response:
        p = need_partners()
        return JSONResponse(await run(lambda: p.remove(user_id, request.path_params["pid"])))

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
    A = "/app/api/partners"
    return [
        Route(P, guarded(listing, mutating=False), methods=["GET"]),
        Route(f"{P}/search", guarded(search, mutating=False), methods=["GET"]),
        Route(f"{P}/lookup", guarded(lookup, mutating=True), methods=["POST"]),
        Route(f"{A}/admin", guarded(partner_admin, mutating=False), methods=["GET"]),
        Route(f"{A}/admin", guarded(partner_add, mutating=True), methods=["POST"]),
        Route(f"{A}/admin/{{pid}}", guarded(partner_edit, mutating=True), methods=["PUT"]),
        Route(f"{A}/admin/{{pid}}", guarded(partner_delete, mutating=True), methods=["DELETE"]),
        Route(f"{A}/{{pid}}", guarded(partner_get, mutating=False), methods=["GET"]),
        Route(f"{A}/{{pid}}/count", guarded(partner_count, mutating=True), methods=["POST"]),
        Route(f"{P}/suggest", guarded(suggest, mutating=True), methods=["POST"]),
        Route(f"{P}/refresh", guarded(refresh, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/report", guarded(report, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/link", guarded(link, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/going", guarded(mark_going, mutating=True), methods=["POST"]),
        Route(f"{P}/{{listing_id}}/calendar.ics", guarded(ics, mutating=False), methods=["GET"]),
    ]


__all__ = ["make_routes"]
