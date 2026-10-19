"""HTTP routes for shared training blocks (``blocks.py``). Built by ``webapp.build_app_routes``
with its guards (``plan_api``: session, Host, Origin + JSON on mutating calls, coach accounts
403); every route also requires an allowlisted athlete (``Blocks.require``).

    GET    /app/api/blocks                    my blocks, invites, blocks open to my clubs
    GET    /app/api/blocks/new                templates, my races ("our race"), start Mondays,
                                              mutual friends to invite, clubs I admin
    POST   /app/api/blocks                    {template, start, event_id?, name?, invite?, club?,
                                               plan?: new|keep, confirm_replace?}
    GET    /app/api/blocks/{bid}              the block page (members: done/planned only)
    POST   /app/api/blocks/{bid}/join         {plan?, confirm_replace?}  409 code=confirm_plan
    POST   /app/api/blocks/{bid}/decline
    POST   /app/api/blocks/{bid}/invite       {user_ids}
    POST   /app/api/blocks/{bid}/leave        your plan stays yours
    POST   /app/api/blocks/{bid}/end          owner
    POST   /app/api/blocks/{bid}/checkin      {feel: strong|okay|tough, note?}
    PUT    /app/api/blocks/{bid}/checkins     {on}   the Sunday check-in moment
    POST   /app/api/blocks/{bid}/nudge        {user_id}  once a day per pair
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .blocks import BlockError, Blocks

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, blocks: Blocks, plan_api: Callable[..., Any], read_json: Callable[[Request], Awaitable[Any]],
                person: Callable[[str], dict[str, Any] | None],
                friends: Callable[[str], list[str]], admin_clubs: Callable[[str], list[dict[str, Any]]],
                push: Callable[[str, str, float, str, str], None]) -> list[BaseRoute]:
    """``friends(uid)``: mutual friends; ``admin_clubs(uid)``: ``[{id, name}]`` clubs ``uid``
    admins; ``push(to, key, window, title, body)``: rate-limited push (quiet hours are the
    caller's to check for invites; cheers come back from ``Blocks`` already coalesced)."""

    def wrap(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                blocks.require(user_id)
                return await handler(request, user_id)
            except BlockError as e:
                return JSONResponse(e.body(), status_code=e.status)
        return plan_api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise BlockError("bad request")
        return b

    def bid_of(request: Request) -> str:
        return str(request.path_params["bid"])

    def deco(view: dict[str, Any]) -> dict[str, Any]:
        out = dict(view)
        for p in out.get("people") or []:
            p["user"] = person(p["user_id"])
        for c in (out.get("checkins") or []) + (out.get("last_checkins") or []):
            c["user"] = person(c["user_id"])
        if out.get("invited_by"):
            out["invited_by"] = person(out["invited_by"])
        if "invited" in out:
            out["invited"] = [person(x) for x in out["invited"]]
        return out

    async def overview(request: Request, user_id: str) -> Response:
        o = await run(lambda: blocks.overview(user_id))
        return JSONResponse({**o, "invites": [deco(x) for x in o["invites"]]})

    async def new_info(request: Request, user_id: str) -> Response:
        t = await run(lambda: blocks.templates(user_id))
        mates = await run(lambda: friends(user_id))
        clubs = await run(lambda: admin_clubs(user_id))
        cur = await run(lambda: blocks.plan.current(user_id))
        return JSONResponse({**t, "friends": [p for p in (person(x) for x in mates) if p], "clubs": clubs,
                             "current": cur})

    def _invite_push(by: str, to: list[str], name: str) -> None:
        who = (person(by) or {}).get("name") or "A friend"
        for x in to:
            push(x, f"block-invite:{x}:{by}", 86400, "Training block invite",
                 f"{who} invited you to {name} on rabbt.")

    async def create(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        out = await run(lambda: blocks.create(user_id, b))
        _invite_push(user_id, out["invited"], out["block"]["name"])
        return JSONResponse({**out, "block": deco(out["block"])}, status_code=201)

    async def get(request: Request, user_id: str) -> Response:
        v = await run(lambda: blocks.view(user_id, bid_of(request)))
        return JSONResponse({"block": deco(v)})

    async def join(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        out = await run(lambda: blocks.join(user_id, bid_of(request), b))
        return JSONResponse({**out, "block": deco(out["block"])}, status_code=201)

    async def decline(request: Request, user_id: str) -> Response:
        await run(lambda: blocks.decline(user_id, bid_of(request)))
        return JSONResponse({"ok": True})

    async def invite(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        new = await run(lambda: blocks.invite(user_id, bid_of(request), b.get("user_ids")))
        v = await run(lambda: blocks.view(user_id, bid_of(request)))
        _invite_push(user_id, new, v["name"])
        return JSONResponse({"invited": new, "block": deco(v)})

    async def leave(request: Request, user_id: str) -> Response:
        await run(lambda: blocks.leave(user_id, bid_of(request)))
        return JSONResponse({"ok": True})

    async def end(request: Request, user_id: str) -> Response:
        await run(lambda: blocks.end(user_id, bid_of(request)))
        return JSONResponse({"ok": True})

    async def checkin(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        c = await run(lambda: blocks.checkin(user_id, bid_of(request), b.get("feel"), b.get("note")))
        v = await run(lambda: blocks.view(user_id, bid_of(request)))
        return JSONResponse({"checkin": c, "block": deco(v)})

    async def checkins_toggle(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        await run(lambda: blocks.set_checkins(user_id, bid_of(request), b.get("on")))
        return JSONResponse({"ok": True})

    async def nudge(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        other = b.get("user_id")
        out = await run(lambda: blocks.nudge(user_id, bid_of(request), other))
        if out.get("push") and isinstance(other, str):
            push(other, f"block-cheer:{other}", 1, "rabbt", out["push"])  # Blocks already coalesced it
        return JSONResponse({"ok": True})

    p = "/app/api/blocks"
    return [
        Route(p, wrap(overview, mutating=False), methods=["GET"]),
        Route(p, wrap(create, mutating=True), methods=["POST"]),
        Route(f"{p}/new", wrap(new_info, mutating=False), methods=["GET"]),
        Route(p + "/{bid}", wrap(get, mutating=False), methods=["GET"]),
        Route(p + "/{bid}/join", wrap(join, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/decline", wrap(decline, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/invite", wrap(invite, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/leave", wrap(leave, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/end", wrap(end, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/checkin", wrap(checkin, mutating=True), methods=["POST"]),
        Route(p + "/{bid}/checkins", wrap(checkins_toggle, mutating=True), methods=["PUT"]),
        Route(p + "/{bid}/nudge", wrap(nudge, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
