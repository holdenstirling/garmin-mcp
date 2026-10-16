"""HTTP routes for progress trends (``trends.py``) and celebrations (``celebrate.py``). Built by
``webapp.build_app_routes`` with its guards (``api``: session, Host, Origin on mutating calls,
coach accounts 403).

    GET  /app/api/progress/trends[?fresh=1]   weekly distance vs goal, pace at easy effort, sleep vs load
    GET  /app/api/celebrations                unseen celebrations (races, finished blocks)
    POST /app/api/celebrations/{cid}/seen     dismiss one for good (also pr:<activity id>)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .celebrate import Celebrations, valid_id
from .trends import TrendsService


def make_routes(*, trends: TrendsService | None, celebrations: Celebrations | None,
                api: Callable[..., Any], no_garmin: Callable[[str], Response | None]) -> list[BaseRoute]:

    async def trends_get(request: Request, user_id: str) -> Response:
        if trends is None:
            return JSONResponse({"error": "Trends aren't available on this server."}, status_code=503)
        if (empty := no_garmin(user_id)) is not None:
            return empty
        fresh = request.query_params.get("fresh") == "1"
        return JSONResponse(await anyio.to_thread.run_sync(lambda: trends.get(user_id, fresh=fresh)))

    async def cel_list(request: Request, user_id: str) -> Response:
        if celebrations is None:
            return JSONResponse({"items": []})
        return JSONResponse({"items": await anyio.to_thread.run_sync(lambda: celebrations.pending(user_id))})

    async def cel_seen(request: Request, user_id: str) -> Response:
        cid = str(request.path_params["cid"])
        if not valid_id(cid):
            return JSONResponse({"error": "Unknown celebration."}, status_code=404)
        if celebrations is not None:
            await anyio.to_thread.run_sync(lambda: celebrations.seen(user_id, cid))
        return JSONResponse({"ok": True})

    return [
        Route("/app/api/progress/trends", api(trends_get, mutating=False), methods=["GET"]),
        Route("/app/api/celebrations", api(cel_list, mutating=False), methods=["GET"]),
        Route("/app/api/celebrations/{cid}/seen", api(cel_seen, mutating=True), methods=["POST"]),
    ]
