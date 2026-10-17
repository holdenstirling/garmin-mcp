"""HTTP routes for training buddies (buddies.py), on the community guard (session, Host, Origin
+ JSON on mutating calls; coach accounts 403, athletes only).

    GET    /app/api/buddies                 {profile | null, suggested, area}
    PUT    /app/api/buddies                 {sports, pace?, slots, race?, note?, paused?} -> same as GET
    DELETE /app/api/buddies                 turn it off and forget the profile
    GET    /app/api/buddies/matches         {matches: [...], reason: off | paused | none | null}
    POST   /app/api/buddies/{uid}/hi        {text?} -> {conv} (201): a DM (request unless connected)
    POST   /app/api/buddies/{uid}/hide      "Not now"
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .buddies import BuddyError, Buddies

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, buddies: Buddies, wrap: Callable[..., Any],
                read_json: Callable[[Request], Awaitable[Any]]) -> list[BaseRoute]:
    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except BuddyError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return wrap(inner, mutating=mutating)

    async def get(request: Request, uid: str) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(lambda: buddies.get(uid)))

    async def put(request: Request, uid: str) -> Response:
        body = await read_json(request)
        return JSONResponse(await anyio.to_thread.run_sync(lambda: buddies.save(uid, body)))

    async def delete(request: Request, uid: str) -> Response:
        await anyio.to_thread.run_sync(lambda: buddies.delete(uid))
        return JSONResponse({"ok": True})

    async def matches(request: Request, uid: str) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(lambda: buddies.matches(uid)))

    async def hi(request: Request, uid: str) -> Response:
        body = await read_json(request)
        text = body.get("text") if isinstance(body, dict) else None
        other = request.path_params["other"]
        conv = await anyio.to_thread.run_sync(lambda: buddies.say_hi(uid, other, text))
        return JSONResponse({"conv": conv}, status_code=201)

    async def hide(request: Request, uid: str) -> Response:
        await read_json(request)
        other = request.path_params["other"]
        await anyio.to_thread.run_sync(lambda: buddies.hide(uid, other))
        return JSONResponse({"ok": True})

    return [
        Route("/app/api/buddies", guarded(get, mutating=False), methods=["GET"]),
        Route("/app/api/buddies", guarded(put, mutating=True), methods=["PUT"]),
        Route("/app/api/buddies", guarded(delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/buddies/matches", guarded(matches, mutating=False), methods=["GET"]),
        Route("/app/api/buddies/{other}/hi", guarded(hi, mutating=True), methods=["POST"]),
        Route("/app/api/buddies/{other}/hide", guarded(hide, mutating=True), methods=["POST"]),
    ]
