"""HTTP routes for training paces (``paces``). Built by ``webapp.build_app_routes`` with its
guards (``api``: session, Host, Origin + JSON on mutating calls, coach accounts 403).

    GET  /app/api/paces                     current thresholds + zones, provenance, pending suggestions, undo
    POST /app/api/paces/{sid}/accept        update the profile and re-target future sessions
    POST /app/api/paces/{sid}/dismiss       {never?: bool}  Not now / Never for this
    POST /app/api/paces/undo                {id}  within 24 h
    POST /app/api/paces/suggestions         {sport, on}  turn suggestions for a sport back on/off
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .paces import SPORTS, PaceError, Paces

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, svc: Paces, api: Callable[..., Any],
                read_json: Callable[[Request], Awaitable[Any]]) -> list[BaseRoute]:

    def wrap(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await handler(request, user_id)
            except PaceError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    def sid_of(request: Request) -> str:
        sid = str(request.path_params["sid"])
        if not (sid.startswith("p") and 2 <= len(sid) <= 24 and sid[1:].isalnum()):
            raise PaceError("Unknown suggestion.", 404)
        return sid

    async def get(request: Request, user_id: str) -> Response:
        return JSONResponse(await run(lambda: svc.view(user_id)))

    async def accept(request: Request, user_id: str) -> Response:
        sid = sid_of(request)
        return JSONResponse(await run(lambda: svc.accept(user_id, sid)))

    async def dismiss(request: Request, user_id: str) -> Response:
        sid = sid_of(request)
        body = await read_json(request)
        never = isinstance(body, dict) and body.get("never") is True
        await run(lambda: svc.dismiss(user_id, sid, never=never))
        return JSONResponse({"ok": True})

    async def undo(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        uid_ = body.get("id") if isinstance(body, dict) else None
        if not isinstance(uid_, str) or len(uid_) > 24:
            raise PaceError("Nothing to undo.", 409)
        return JSONResponse(await run(lambda: svc.undo(user_id, uid_)))

    async def suggestions(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict) or body.get("sport") not in SPORTS or not isinstance(body.get("on"), bool):
            raise PaceError("Send {sport, on}.")
        await run(lambda: svc.set_suggestions(user_id, body["sport"], body["on"]))
        return JSONResponse({"ok": True})

    return [
        Route("/app/api/paces", wrap(get, mutating=False), methods=["GET"]),
        Route("/app/api/paces/undo", wrap(undo, mutating=True), methods=["POST"]),
        Route("/app/api/paces/suggestions", wrap(suggestions, mutating=True), methods=["POST"]),
        Route("/app/api/paces/{sid}/accept", wrap(accept, mutating=True), methods=["POST"]),
        Route("/app/api/paces/{sid}/dismiss", wrap(dismiss, mutating=True), methods=["POST"]),
    ]
