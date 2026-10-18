"""Find friends routes (friendfind.py). Athletes only (the wrapper checks).

    GET    /app/api/friends/search?q=          people by @handle, name, exact email or phone
    POST   /app/api/friends/match              {contacts: [{emails, phones}]} -> who's on Rabbit
    GET    /app/api/friends/suggested          People you may know
    POST   /app/api/friends/suggested/{uid}/dismiss
    POST   /app/api/friends/follow             {user_id} (someone search/suggestions can show)
    GET    /app/api/friends/code/{code}        who a QR / follow link belongs to (they shared it)
    GET    /app/api/friends/me                 my @handle, phone, who can find me
    PUT    /app/api/friends/me                 {handle?, phone?, find?: {name, email, phone}}
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .friendfind import FindError, FriendFinder

_UID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, finder: FriendFinder, wrap: Callable[..., Any], read_json: Callable[[Request], Awaitable[Any]],
                person: Callable[[str], dict[str, Any] | None], invite_link: Callable[[str], str],
                on_follow: Callable[[str, str, dict[str, Any]], None] | None = None) -> list[BaseRoute]:
    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except FindError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
            except Exception as e:  # SocialError carries message + status
                status, msg = getattr(e, "status", None), getattr(e, "message", None)
                if isinstance(status, int) and isinstance(msg, str):
                    return JSONResponse({"error": msg}, status_code=status)
                raise
        return wrap(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    def rows(rs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rs:
            u = person(r["user_id"])
            if u is not None:
                out.append({**{k: v for k, v in r.items() if k != "user_id"}, "user": u})
        return out

    async def search(request: Request, user_id: str) -> Response:
        q = request.query_params.get("q", "")
        return JSONResponse({"people": rows(await run(lambda: finder.search(user_id, q)))})

    async def match(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        contacts = body.get("contacts") if isinstance(body, dict) else None
        res = await run(lambda: finder.match(user_id, contacts))
        found = []
        for r in res["on_rabbit"]:
            u = person(r["user_id"])
            if u is not None:
                found.append({"index": r["index"], "status": r["status"], "follows_you": r["follows_you"], "user": u})
        return JSONResponse({"on_rabbit": found, "checked": res["checked"],
                             "invite_link": await run(lambda: invite_link(user_id))})

    async def suggested(request: Request, user_id: str) -> Response:
        return JSONResponse({"people": rows(await run(lambda: finder.suggestions(user_id)))})

    async def dismiss(request: Request, user_id: str) -> Response:
        uid = str(request.path_params["uid"])
        if not _UID.fullmatch(uid):
            raise FindError("person not found", 404)
        await run(lambda: finder.dismiss(user_id, uid))
        return JSONResponse({"ok": True})

    async def follow(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        uid = body.get("user_id") if isinstance(body, dict) else None
        if not isinstance(uid, str) or not _UID.fullmatch(uid):
            raise FindError("person not found", 404)

        def go() -> dict[str, Any]:
            if not finder.can_follow(user_id, uid):
                raise FindError("person not found", 404)
            soc = finder.soc
            return soc.follow(user_id, code=soc.invite_code(uid))
        res = await run(go)
        if on_follow is not None:
            on_follow(user_id, uid, res)
        u = person(uid) or {"name": "them"}
        msg = f"You're following {u['name']}." if res["status"] == "active" else f"Request sent to {u['name']}."
        return JSONResponse({"ok": True, "status": "following" if res["status"] == "active" else "requested",
                             "message": msg})

    async def by_code(request: Request, user_id: str) -> Response:
        code = str(request.path_params["code"]).strip().upper()
        soc = finder.soc

        def look() -> str | None:
            uid = soc.code_owner(code) if re.fullmatch(r"[A-Z2-9]{8}", code) else None
            if not uid or not soc.is_athlete(uid) or soc.blocked_between(user_id, uid):
                return None
            return uid
        uid = await run(look)
        if uid is None:
            raise FindError("That code doesn't match anyone on Rabbit.", 404)
        if uid == user_id:
            return JSONResponse({"user": person(uid), "status": "self", "follows_you": False})
        return JSONResponse({"user": person(uid), "status": await run(lambda: finder.status(user_id, uid)),
                             "follows_you": await run(lambda: soc.follows(uid, user_id))})

    async def me_get(request: Request, user_id: str) -> Response:
        return JSONResponse({**await run(lambda: finder.prefs(user_id)),
                             "invite_link": await run(lambda: invite_link(user_id))})

    async def me_put(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        return JSONResponse({**await run(lambda: finder.put_prefs(user_id, body)),
                             "invite_link": await run(lambda: invite_link(user_id))})

    P = "/app/api/friends"
    return [
        Route(f"{P}/search", guarded(search, mutating=False), methods=["GET"]),
        Route(f"{P}/match", guarded(match, mutating=True), methods=["POST"]),
        Route(f"{P}/suggested", guarded(suggested, mutating=False), methods=["GET"]),
        Route(f"{P}/suggested/{{uid}}/dismiss", guarded(dismiss, mutating=True), methods=["POST"]),
        Route(f"{P}/follow", guarded(follow, mutating=True), methods=["POST"]),
        Route(f"{P}/code/{{code}}", guarded(by_code, mutating=False), methods=["GET"]),
        Route(f"{P}/me", guarded(me_get, mutating=False), methods=["GET"]),
        Route(f"{P}/me", guarded(me_put, mutating=True), methods=["PUT"]),
    ]


__all__ = ["make_routes"]
