"""HTTP routes for TrainingPeaks in the Rabbit app (``tpsync.py``). Built by
``webapp.build_app_routes`` with its ``_api`` guard (session, Host, Origin + JSON on mutating
calls, coach accounts 403).

    GET  /app/api/trainingpeaks                       plan-calendar view (items, hide_sessions, source)
    POST /app/api/trainingpeaks/connect               {cookie}  checked once, stored encrypted
    POST /app/api/trainingpeaks/disconnect            forget the sign-in (workouts stay in TP)
    PUT  /app/api/trainingpeaks/settings              {source: trainingpeaks|rabbit}
    POST /app/api/trainingpeaks/sync                  Sync now (push if Rabbit is the source, then pull)
    POST /app/api/trainingpeaks/workouts/{wid}/move   {date}
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .tpsync import TPSync, TPUserError

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, tp: TPSync, api: Callable[..., Any],
                read_json: Callable[[Request], Awaitable[Any]]) -> list[BaseRoute]:
    def wrap(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await handler(request, user_id)
            except TPUserError as e:
                body: dict[str, Any] = {"error": str(e)}
                if e.code:
                    body["code"] = e.code
                return JSONResponse(body, status_code=e.status)
        return api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise TPUserError("bad request")
        return b

    async def view(request: Request, uid: str) -> Response:
        return JSONResponse(await run(lambda: tp.view(uid)))

    async def connect(request: Request, uid: str) -> Response:
        b = await body_of(request)
        raw = b.get("cookie")
        if not isinstance(raw, str):
            raise TPUserError("Paste your Production_tpAuth value.")
        who = await run(lambda: tp.connect(uid, raw))
        await run(lambda: tp.sync(uid))  # first read; a failure shows on the row, not here
        return JSONResponse({"connected": True, "name": who.get("name"), "view": await run(lambda: tp.view(uid))})

    async def disconnect(request: Request, uid: str) -> Response:
        await run(lambda: tp.disconnect(uid))
        return JSONResponse({"connected": False})

    async def settings(request: Request, uid: str) -> Response:
        b = await body_of(request)
        src = b.get("source")
        if not isinstance(src, str):
            raise TPUserError("Pick TrainingPeaks or Rabbit.")
        return JSONResponse(await run(lambda: tp.set_source(uid, src)))

    async def sync(request: Request, uid: str) -> Response:
        if not await run(lambda: tp.connected(uid)):
            raise TPUserError("TrainingPeaks isn't connected.", 409)
        res = await run(lambda: tp.sync(uid))
        return JSONResponse({"result": res, "view": await run(lambda: tp.view(uid))})

    async def move(request: Request, uid: str) -> Response:
        raw = request.path_params["wid"]
        if not raw.isdigit() or len(raw) > 15:
            raise TPUserError("bad workout id")
        b = await body_of(request)
        day = b.get("date")
        if not isinstance(day, str):
            raise TPUserError("date must be YYYY-MM-DD")
        if not await run(lambda: tp.connected(uid)):
            raise TPUserError("TrainingPeaks isn't connected.", 409)
        return JSONResponse(await run(lambda: tp.move(uid, int(raw), day)))

    base = "/app/api/trainingpeaks"
    return [
        Route(base, wrap(view, mutating=False), methods=["GET"]),
        Route(f"{base}/connect", wrap(connect, mutating=True), methods=["POST"]),
        Route(f"{base}/disconnect", wrap(disconnect, mutating=True), methods=["POST"]),
        Route(f"{base}/settings", wrap(settings, mutating=True), methods=["PUT"]),
        Route(f"{base}/sync", wrap(sync, mutating=True), methods=["POST"]),
        Route(f"{base}/workouts/{{wid}}/move", wrap(move, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
