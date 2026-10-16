"""HTTP routes for Community v2: the home view, featured clubs, friends' latest and feed groups.
Built by ``webapp.build_app_routes`` on community_web's guard (session, Host, Origin + JSON on
mutating calls, coach accounts 403, allowlisted athlete).

    GET    /app/api/community/home                  {view: feed|clubs, featured, groups}
    GET    /app/api/community/latest                {items}: friends' last 3 posts (Rabbit home)
    GET    /app/api/community/featured?where=community|explore     {items} for me
    GET    /app/api/community/featured/manage?club=<cid> | ?listing=<lid>
                                                    {owner, featured, until, tagline, online, slots_left}
    PUT    /app/api/community/featured              {club_id | listing_id, on, until?, tagline?, online?}
                                                    app owner only (403), <= 3 live (409)
    GET    /app/api/community/groups                {groups, max}
    POST   /app/api/community/groups                {name, emoji?, members: [uid]}  mutual friends
    GET    /app/api/community/groups/friends        mutual friends to add
    GET    /app/api/community/groups/{gid}          {group: members as people}
    PATCH  /app/api/community/groups/{gid}          owner: {name?, emoji?}
    DELETE /app/api/community/groups/{gid}          owner
    POST   /app/api/community/groups/{gid}/members  {user_ids}  any member, their mutual friends
    DELETE /app/api/community/groups/{gid}/members/{uid}   owner
    POST   /app/api/community/groups/{gid}/leave

The feed itself (``?group=<gid>``, ``scope=clubs``, ``pinned``) stays in community_web.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .community import Community
from .featured import FeatureError, Featured
from .feedgroups import MAX_GROUPS, FeedGroups, GroupError, valid_gid

Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, cm: Community, groups: FeedGroups, featured: Featured, wrap: Callable[..., Any],
                read_json: Callable[[Request], Awaitable[Any]], person: Callable[[str], dict[str, Any] | None],
                first_name: Callable[[str], str], today: Callable[[str], date],
                home: Callable[[str], dict[str, str]], sports: Callable[[str], set[str]],
                listing_ref: Callable[[str, str], dict[str, str] | None],
                notify: Callable[[str, str, str, str], None]) -> list[BaseRoute]:
    """``wrap``: community_web's guard; ``listing_ref(uid,
    lid)``: ``{city, state, listing_id}`` of a listing in the viewer's metro (else None);
    ``notify(to, key, title, body)``: a rate-limited push outside quiet hours."""

    def guarded(h: Handler, *, mutating: bool) -> Any:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                return await h(request, user_id)
            except (GroupError, FeatureError) as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return wrap(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise GroupError("bad request")
        return b

    def deco(p: dict[str, Any]) -> dict[str, Any]:
        return {**p, "user": person(p["author"]),
                "comments": [{**c, "by": {"id": c["by"], "name": first_name(c["by"])}} for c in p.get("comments") or []]}

    def group_out(g: dict[str, Any]) -> dict[str, Any]:
        return {**g, "members": [person(m) for m in g["members"]]}

    def featured_for(uid: str, limit: int = 3) -> list[dict[str, Any]]:
        loc = home(uid)
        return featured.for_viewer(uid, city=loc.get("city") or "", state=loc.get("state") or "",
                                   sports=sports(uid), today=today(uid), limit=limit)

    # ------------------------------------------------------------- home --
    async def home_view(request: Request, user_id: str) -> Response:
        s = await run(lambda: cm.settings(user_id))
        feat = await run(lambda: featured_for(user_id))
        gs = await run(lambda: groups.mine(user_id))
        return JSONResponse({"view": s.get("default_view") or "feed", "featured": feat,
                             "groups": [{k: g[k] for k in ("id", "name", "emoji", "count", "owner")} for g in gs]})

    async def latest(request: Request, user_id: str) -> Response:
        items = await run(lambda: cm.latest(user_id))
        return JSONResponse({"items": [deco(p) for p in items]})

    # --------------------------------------------------------- featured --
    async def featured_list(request: Request, user_id: str) -> Response:
        where = request.query_params.get("where") or "community"
        n = 1 if where == "explore" else 3
        return JSONResponse({"items": await run(lambda: featured_for(user_id, n))})

    def ref_of(uid: str, club: Any, listing: Any) -> tuple[str, dict[str, str]]:
        if isinstance(club, str) and club:
            return "club", {"club_id": club[:40]}
        if isinstance(listing, str) and listing:
            ref = listing_ref(uid, listing[:20])
            if ref is None:
                raise FeatureError("club not found", 404)
            return "listing", ref
        raise FeatureError("Pick a club.")

    async def manage(request: Request, user_id: str) -> Response:
        q = request.query_params
        kind, ref = await run(lambda: ref_of(user_id, q.get("club"), q.get("listing")))
        return JSONResponse(await run(lambda: featured.state(user_id, kind, ref, today(user_id))))

    async def feature_put(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        kind, ref = await run(lambda: ref_of(user_id, b.get("club_id"), b.get("listing_id")))
        return JSONResponse(await run(lambda: featured.set(user_id, kind, ref, b, today(user_id))))

    # ----------------------------------------------------------- groups --
    async def groups_list(request: Request, user_id: str) -> Response:
        gs = await run(lambda: groups.mine(user_id))
        return JSONResponse({"groups": [group_out(g) for g in gs], "max": MAX_GROUPS})

    def _tell(adder: str, g: dict[str, Any], new: list[str]) -> None:
        for u in new:
            notify(u, f"group-add:{u}:{g['id']}", "New group",
                   f"You're in {g['emoji']} {g['name']}. Posts there are only for the group.")

    async def group_create(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        g = await run(lambda: groups.create(user_id, b))
        _tell(user_id, g, [m for m in g["members"] if m != user_id])
        return JSONResponse({"group": group_out(g)}, status_code=201)

    async def group_friends(request: Request, user_id: str) -> Response:
        groups.require(user_id)
        ids = await run(lambda: [u for u in cm.social.following_ids(user_id, limit=500) if groups.mutual(user_id, u)])
        return JSONResponse({"people": [person(u) for u in ids]})

    async def group_get(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        return JSONResponse({"group": group_out(await run(lambda: groups.get(user_id, gid)))})

    async def group_patch(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        b = await body_of(request)
        return JSONResponse({"group": group_out(await run(lambda: groups.update(user_id, gid, b)))})

    async def group_delete(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        await run(lambda: groups.delete(user_id, gid))
        return JSONResponse({"ok": True})

    async def members_add(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        b = await body_of(request)
        g, new = await run(lambda: groups.add(user_id, gid, b.get("user_ids")))
        _tell(user_id, g, new)
        return JSONResponse({"group": group_out(g), "added": len(new)})

    async def member_remove(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        mid = str(request.path_params["member_id"])[:80]
        return JSONResponse({"group": group_out(await run(lambda: groups.remove(user_id, gid, mid)))})

    async def group_leave(request: Request, user_id: str) -> Response:
        gid = valid_gid(request.path_params["group_id"])
        await run(lambda: groups.leave(user_id, gid))
        return JSONResponse({"ok": True})

    P = "/app/api/community"
    G = f"{P}/groups/{{group_id}}"
    return [
        Route(f"{P}/home", guarded(home_view, mutating=False), methods=["GET"]),
        Route(f"{P}/latest", guarded(latest, mutating=False), methods=["GET"]),
        Route(f"{P}/featured", guarded(featured_list, mutating=False), methods=["GET"]),
        Route(f"{P}/featured", guarded(feature_put, mutating=True), methods=["PUT"]),
        Route(f"{P}/featured/manage", guarded(manage, mutating=False), methods=["GET"]),
        Route(f"{P}/groups", guarded(groups_list, mutating=False), methods=["GET"]),
        Route(f"{P}/groups", guarded(group_create, mutating=True), methods=["POST"]),
        Route(f"{P}/groups/friends", guarded(group_friends, mutating=False), methods=["GET"]),
        Route(G, guarded(group_get, mutating=False), methods=["GET"]),
        Route(G, guarded(group_patch, mutating=True), methods=["PATCH"]),
        Route(G, guarded(group_delete, mutating=True), methods=["DELETE"]),
        Route(f"{G}/members", guarded(members_add, mutating=True), methods=["POST"]),
        Route(f"{G}/members/{{member_id}}", guarded(member_remove, mutating=True), methods=["DELETE"]),
        Route(f"{G}/leave", guarded(group_leave, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
