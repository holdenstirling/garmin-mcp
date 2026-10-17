"""HTTP routes for direct messages (messages.py). Built by ``webapp.build_app_routes`` on the
community guard (session, Host, Origin + JSON on mutating calls, coach accounts 403, athletes).

    GET    /app/api/dm                       {convs, requests, unread}; people as {id, name, photo}
    GET    /app/api/dm/unread                {unread}  (header chat dot)
    GET    /app/api/dm/people?q=             people you can message without a request
    POST   /app/api/dm                       {to: [uid], name?, text?, att?}  -> {conv, msg?} (201)
    GET    /app/api/dm/{cid}?before=ts       {conv, msgs, more}; marks it read
    POST   /app/api/dm/{cid}/messages        {text?, att?: {type: workout|event, ref}} -> {msg} (201)
    POST   /app/api/dm/{cid}/react           {msg_id, emoji}
    POST   /app/api/dm/{cid}/accept | /decline | /leave | /read
    POST   /app/api/dm/{cid}/mute            {muted}
    PATCH  /app/api/dm/{cid}                 {name}  group chats
    POST   /app/api/dm/{cid}/report          {msg_id?, reason?}
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .messages import DMError, Messages

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, dm: Messages, wrap: Callable[..., Any], read_json: Callable[[Request], Awaitable[Any]],
                person: Callable[[str], dict[str, Any] | None], candidates: Callable[[str], list[str]],
                notify: Callable[[str, str, str, str, str], None], first_name: Callable[[str], str]) -> list[BaseRoute]:
    """``candidates(uid)``: people to offer in New message (follows, followers, club mates);
    ``notify(to, key, title, body, url)``: a rate-limited push (respects the person's settings)."""

    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except DMError as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return wrap(inner, mutating=mutating)

    def people_of(ids: list[str]) -> list[dict[str, Any]]:
        return [p for p in (person(u) for u in ids) if p]

    def conv_out(v: dict[str, Any]) -> dict[str, Any]:
        return {**v, "members": people_of(v["members"]), "waiting_on": people_of(v["waiting_on"])}

    async def body(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise DMError("bad request")
        return b

    def push_new(uid: str, conv: dict[str, Any], msg: dict[str, Any], to: list[str]) -> None:
        who = first_name(uid)
        title = f"{who} in {conv['name']}" if conv.get("kind") == "group" and conv.get("name") else who
        text = msg.get("text") or ("Shared a workout" if (msg.get("att") or {}).get("type") == "workout" else "Shared an event")
        for p in to:
            try:
                notify(p, f"dm:{p}:{conv['id']}", title, text[:140], f"/app/?open=dm&c={conv['id']}")
            except Exception:  # best effort
                pass

    async def list_get(request: Request, user_id: str) -> Response:
        out = await anyio.to_thread.run_sync(dm.list, user_id)
        return JSONResponse({"convs": [conv_out(v) for v in out["convs"]],
                             "requests": [conv_out(v) for v in out["requests"]], "unread": out["unread"]})

    async def unread_get(request: Request, user_id: str) -> Response:
        return JSONResponse({"unread": await anyio.to_thread.run_sync(dm.unread, user_id)})

    async def people_get(request: Request, user_id: str) -> Response:
        q = (request.query_params.get("q") or "").strip().lower()[:40]
        ids = await anyio.to_thread.run_sync(lambda: dm.people(user_id, candidates(user_id)))
        ps = people_of(ids)
        if q:
            ps = [p for p in ps if q in str(p.get("name") or "").lower()]
        ps.sort(key=lambda p: str(p.get("name") or "").lower())
        return JSONResponse({"people": ps[:100]})

    async def start_post(request: Request, user_id: str) -> Response:
        b = await body(request)
        conv = await anyio.to_thread.run_sync(lambda: dm.start(user_id, b.get("to"), name=b.get("name")))
        msg = None
        if b.get("text") or b.get("att"):
            msg, to = await anyio.to_thread.run_sync(lambda: dm.send(user_id, conv["id"], b.get("text"), b.get("att")))
            push_new(user_id, conv, msg, to)
            conv = await anyio.to_thread.run_sync(lambda: dm.messages(user_id, conv["id"])["conv"])
        return JSONResponse({"conv": conv_out(conv), "msg": msg}, status_code=201)

    async def conv_get(request: Request, user_id: str) -> Response:
        cid = request.path_params["cid"]
        before = request.query_params.get("before")
        out = await anyio.to_thread.run_sync(lambda: dm.messages(user_id, cid, before=before))
        return JSONResponse({"conv": conv_out(out["conv"]), "msgs": out["msgs"], "more": out["more"]})

    async def send_post(request: Request, user_id: str) -> Response:
        cid = request.path_params["cid"]
        b = await body(request)
        msg, to = await anyio.to_thread.run_sync(lambda: dm.send(user_id, cid, b.get("text"), b.get("att")))
        conv = await anyio.to_thread.run_sync(lambda: dm._view(dm._conv(user_id, cid), user_id))
        push_new(user_id, conv, msg, to)
        return JSONResponse({"msg": msg}, status_code=201)

    async def react_post(request: Request, user_id: str) -> Response:
        b = await body(request)
        m = await anyio.to_thread.run_sync(
            lambda: dm.react(user_id, request.path_params["cid"], b.get("msg_id"), b.get("emoji")))
        return JSONResponse({"msg": m})

    def action(fn: Callable[[str, str], Any]) -> Handler:
        async def h(request: Request, user_id: str) -> Response:
            out = await anyio.to_thread.run_sync(lambda: fn(user_id, request.path_params["cid"]))
            return JSONResponse({"conv": conv_out(out)} if isinstance(out, dict) else {"ok": True})
        return h

    async def mute_post(request: Request, user_id: str) -> Response:
        b = await body(request)
        v = await anyio.to_thread.run_sync(lambda: dm.mute(user_id, request.path_params["cid"], b.get("muted")))
        return JSONResponse({"conv": conv_out(v)})

    async def rename_patch(request: Request, user_id: str) -> Response:
        b = await body(request)
        v = await anyio.to_thread.run_sync(lambda: dm.set_name(user_id, request.path_params["cid"], b.get("name")))
        return JSONResponse({"conv": conv_out(v)})

    async def report_post(request: Request, user_id: str) -> Response:
        b = await body(request)
        await anyio.to_thread.run_sync(
            lambda: dm.report(user_id, request.path_params["cid"], b.get("msg_id"), b.get("reason")))
        return JSONResponse({"ok": True})

    g = guarded
    base = "/app/api/dm"
    return [
        Route(base, g(list_get, mutating=False), methods=["GET"]),
        Route(base, g(start_post, mutating=True), methods=["POST"]),
        Route(f"{base}/unread", g(unread_get, mutating=False), methods=["GET"]),
        Route(f"{base}/people", g(people_get, mutating=False), methods=["GET"]),
        Route(base + "/{cid}", g(conv_get, mutating=False), methods=["GET"]),
        Route(base + "/{cid}", g(rename_patch, mutating=True), methods=["PATCH"]),
        Route(base + "/{cid}/messages", g(send_post, mutating=True), methods=["POST"]),
        Route(base + "/{cid}/react", g(react_post, mutating=True), methods=["POST"]),
        Route(base + "/{cid}/accept", g(action(dm.accept), mutating=True), methods=["POST"]),
        Route(base + "/{cid}/decline", g(action(dm.decline), mutating=True), methods=["POST"]),
        Route(base + "/{cid}/leave", g(action(dm.leave), mutating=True), methods=["POST"]),
        Route(base + "/{cid}/read", g(action(dm.mark_read), mutating=True), methods=["POST"]),
        Route(base + "/{cid}/mute", g(mute_post, mutating=True), methods=["POST"]),
        Route(base + "/{cid}/report", g(report_post, mutating=True), methods=["POST"]),
    ]
