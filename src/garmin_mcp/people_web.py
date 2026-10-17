"""HTTP routes for connected screens (people.py), on the community guard (session, Host, Origin
+ JSON on mutating calls; coach accounts 403, athletes only).

    GET    /app/api/people/{uid}                 profile (404 unless you may already see them)
    POST   /app/api/people/{uid}/follow          follow (or request) them
    DELETE /app/api/people/{uid}/follow          unfollow / cancel the request
    POST   /app/api/people/{uid}/block           block (hides them everywhere)
    POST   /app/api/people/{uid}/report          {reason}
    GET    /app/api/notifications                {items, unread}
    POST   /app/api/notifications/read           {keys?} (no keys: everything shown is read)
    GET    /app/api/friends/today                {today, trained, racing}
    GET    /app/api/people/also?sport&date&event_name&event_date   {same_sport, same_event}
    POST   /app/api/clubs/{club_id}/chat         the club's group chat -> {conv}
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .people import People, PeopleError

Handler = Callable[[Request, str], Awaitable[Response]]
_UID = re.compile(r"^[A-Za-z0-9_.@+-]{1,80}$")
_SPORT = re.compile(r"^[a-z_]{2,20}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def make_routes(*, people: People, wrap: Callable[..., Any], read_json: Callable[[Request], Awaitable[Any]],
                club_chat: Callable[[str, str], dict[str, Any]] | None = None,
                on_follow: Callable[[str, str, dict[str, Any]], None] | None = None) -> list[BaseRoute]:
    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except PeopleError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
            except Exception as e:  # SocialError / DMError / ClubError carry message + status
                status = getattr(e, "status", None)
                msg = getattr(e, "message", None)
                if isinstance(status, int) and isinstance(msg, str):
                    return JSONResponse({"error": msg}, status_code=status)
                raise
        return wrap(inner, mutating=mutating)

    def uid_of(request: Request) -> str:
        uid = str(request.path_params["uid"])
        if not _UID.fullmatch(uid):
            raise PeopleError("Person not found.", 404)
        return uid

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def profile(request: Request, me: str) -> Response:
        uid = uid_of(request)
        return JSONResponse(await run(lambda: people.profile(me, uid)))

    async def follow(request: Request, me: str) -> Response:
        uid = uid_of(request)
        if request.method == "DELETE":
            await run(lambda: people.unfollow(me, uid))
        else:
            res = await run(lambda: people.follow(me, uid))
            if on_follow is not None:
                on_follow(me, uid, res)
        ok = await run(lambda: people.can_see(me, uid))
        return JSONResponse(await run(lambda: people.profile(me, uid)) if ok else {"ok": True, "gone": True})

    async def block(request: Request, me: str) -> Response:
        uid = uid_of(request)
        await run(lambda: people.block(me, uid))
        return JSONResponse({"ok": True})

    async def report(request: Request, me: str) -> Response:
        uid = uid_of(request)
        body = await read_json(request)
        reason = body.get("reason") if isinstance(body, dict) else None
        await run(lambda: people.report(me, uid, reason))
        return JSONResponse({"ok": True})

    async def inbox(request: Request, me: str) -> Response:
        return JSONResponse(await run(lambda: people.inbox(me)))

    async def read(request: Request, me: str) -> Response:
        body = await read_json(request)
        keys = body.get("keys") if isinstance(body, dict) else None
        if keys is not None and (not isinstance(keys, list) or len(keys) > 200):
            raise PeopleError("bad request")
        await run(lambda: people.mark_read(me, keys))
        return JSONResponse(await run(lambda: people.inbox(me)))

    async def friends_today(request: Request, me: str) -> Response:
        return JSONResponse(await run(lambda: people.friends_today(me)))

    async def also(request: Request, me: str) -> Response:
        q = request.query_params
        sport = q.get("sport") or None
        day = q.get("date") or None
        ev_name = (q.get("event_name") or "")[:120] or None
        ev_date = q.get("event_date") or None
        if (sport and not _SPORT.fullmatch(sport)) or (day and not _DAY.fullmatch(day)) \
                or (ev_date and not _DAY.fullmatch(ev_date)):
            raise PeopleError("bad request")
        return JSONResponse(await run(lambda: people.also(me, sport=sport, day=day, event_name=ev_name,
                                                          event_date=ev_date)))

    async def club_chat_post(request: Request, me: str) -> Response:
        if club_chat is None:
            raise PeopleError("Club chats aren't available here.", 503)
        cid = str(request.path_params["club_id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", cid):
            raise PeopleError("Club not found.", 404)
        return JSONResponse({"conv": await run(lambda: club_chat(me, cid))})

    return [
        Route("/app/api/notifications", guarded(inbox, mutating=False), methods=["GET"]),
        Route("/app/api/notifications/read", guarded(read, mutating=True), methods=["POST"]),
        Route("/app/api/friends/today", guarded(friends_today, mutating=False), methods=["GET"]),
        Route("/app/api/people/also", guarded(also, mutating=False), methods=["GET"]),
        Route("/app/api/people/{uid}", guarded(profile, mutating=False), methods=["GET"]),
        Route("/app/api/people/{uid}/follow", guarded(follow, mutating=True), methods=["POST", "DELETE"]),
        Route("/app/api/people/{uid}/block", guarded(block, mutating=True), methods=["POST"]),
        Route("/app/api/people/{uid}/report", guarded(report, mutating=True), methods=["POST"]),
        Route("/app/api/clubs/{club_id}/chat", guarded(club_chat_post, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
