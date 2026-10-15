"""Routes for the app icon badge and the Rabbit home's one-tap actions. Built by
``webapp.build_app_routes`` with its guards (session, Host, Origin + JSON on mutating calls;
coach accounts get 403 since these aren't coach paths).

    GET  /app/api/unread          {cheers, requests, invites, coach, total}
    POST /app/api/unread/seen     {kind: cheers|requests|invites} -> new counts
    GET  /app/api/home/quick      {actions: [...]} (quickactions.py)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .quickactions import QuickActions
from .unread import Unread

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, unread: Unread, quick: QuickActions | None, api: Callable[..., Any],
                read_json: Callable[[Request], Awaitable[Any]]) -> list[BaseRoute]:
    async def counts(request: Request, user_id: str) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(unread.counts, user_id))

    async def seen(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        kind = body.get("kind") if isinstance(body, dict) else None
        if kind not in ("cheers", "requests", "invites"):
            return JSONResponse({"error": "kind must be cheers, requests or invites"}, status_code=400)
        return JSONResponse(await anyio.to_thread.run_sync(lambda: unread.seen(user_id, kind)))

    async def home_quick(request: Request, user_id: str) -> Response:
        if quick is None:
            return JSONResponse({"actions": []})
        return JSONResponse({"actions": await anyio.to_thread.run_sync(quick.get, user_id)})

    return [
        Route("/app/api/unread", api(counts, mutating=False), methods=["GET"]),
        Route("/app/api/unread/seen", api(seen, mutating=True), methods=["POST"]),
        Route("/app/api/home/quick", api(home_quick, mutating=False), methods=["GET"]),
    ]


__all__ = ["make_routes"]
