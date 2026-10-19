"""HTTP routes for Community (``community``, ``clubs``). Built by ``webapp.build_app_routes``
with its guards (``plan_api``: session, Host, Origin + JSON on mutating calls, coach accounts
403). Every route also requires an allowlisted athlete.

    GET    /app/api/community/feed?cursor=&club=&group=&scope=all|friends|clubs   20 per page, newest
           first; ``pinned``: my fresh auto-shared workout (first page of the main feed)
    POST   /app/api/community/posts                  {text, category, feeling?, photo_ids?, event_id?,
                                                      audience?} | {workout_id, text?, audience?}
    GET    /app/api/community/posts/{pid}            with all comments
    PATCH  /app/api/community/posts/{pid}            own post
    DELETE /app/api/community/posts/{pid}            own post
    GET    /app/api/community/posts/{pid}/photos/{n}
    POST   /app/api/community/posts/{pid}/reactions  {kind: party|strong|heart|rabbit}
    DELETE /app/api/community/posts/{pid}/reactions
    POST   /app/api/community/posts/{pid}/comments   {text, reply_to?} (text may hold @[Name](uid) mentions)
    GET    /app/api/community/mentionable?pid=|audience=  people the viewer can @mention there
    DELETE /app/api/community/posts/{pid}/comments/{cid}
    PATCH  /app/api/community/posts/{pid}/comments/{cid}           {text}  (the comment's author)
    POST   /app/api/community/posts/{pid}/comments/{cid}/like      like (idempotent)
    DELETE /app/api/community/posts/{pid}/comments/{cid}/like      unlike
    GET    /app/api/community/posts/{pid}/comments/{cid}/likes     who liked it
    POST   /app/api/community/posts/{pid}/hide
    POST   /app/api/community/posts/{pid}/report     {reason?}
    POST   /app/api/community/photos                 raw JPEG/WebP body -> {photo_id}
    GET    /app/api/community/drafts
    GET    /app/api/community/workouts/{wid}/post    {post_id|null}: is my workout on the feed
    POST   /app/api/community/drafts/{did}/share     {text?, audience?, photo_ids?, feeling?}
    DELETE /app/api/community/drafts/{did}
    GET    /app/api/community/settings               + photo usage
    PUT    /app/api/community/settings               {milestones?, auto_share?, audience?}
    GET    /app/api/community/people/suggested
    POST   /app/api/community/people/{uid}/follow    only someone in Suggested
    GET    /app/api/community/people/{uid}/photo     related (follow edge, shared club, public poster)
    GET    /app/api/community/meetups                my upcoming meetups (14 days)
    GET    /app/api/community/clubs?q=               mine (+ race groups), invites, discover near me,
                                                      local groups from Explore's web scout (cached)
    POST   /app/api/community/clubs                  {name, sport, city?, state?, description?, emoji?, privacy?}
    POST   /app/api/community/clubs/join             {code}
    GET    /app/api/community/clubs/{cid}            members, requests, meetups, challenges, upcoming races
    PATCH  /app/api/community/clubs/{cid}
    DELETE /app/api/community/clubs/{cid}
    POST   /app/api/community/clubs/{cid}/join       open: member; approval: request (admins pushed)
    DELETE /app/api/community/clubs/{cid}/join       cancel my request
    POST   /app/api/community/clubs/{cid}/leave
    POST   /app/api/community/clubs/{cid}/invite     {user_id}
    POST   /app/api/community/clubs/{cid}/invite/accept|decline
    POST   /app/api/community/clubs/{cid}/requests/{uid}/approve|decline
    POST   /app/api/community/clubs/{cid}/code       new club code
    PUT    /app/api/community/clubs/{cid}/members/{uid} {role: admin|member}
    DELETE /app/api/community/clubs/{cid}/members/{uid}
    POST   /app/api/community/clubs/{cid}/meetups    {title, start, repeat, where, pace?, level?, notes?}
    PATCH  /app/api/community/clubs/{cid}/meetups/{mid}
    DELETE /app/api/community/clubs/{cid}/meetups/{mid}
    POST   /app/api/community/clubs/{cid}/meetups/{mid}/rsvp {status: going|maybe|none}
    POST   /app/api/community/clubs/{cid}/challenges {template, period}  admins: start a club challenge
    POST   /app/api/community/clubs/{cid}/challenges/{gid}/join
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .clubs import MAX_MEMBERS, ClubError, Clubs, valid_cid, valid_mid
from .community import PHOTO_MAX, Community, CommunityError, activity_key, valid_pid, workout_card
from .logs import log_event
from .social import SocialError

logger = logging.getLogger(__name__)
Handler = Callable[[Request, str], Awaitable[Response]]


def make_routes(*, cm: Community, clubs: Clubs, plan_api: Callable[..., Any],
                person: Callable[[str], dict[str, Any] | None], first_name: Callable[[str], str],
                push: Callable[[str, str, float, str, str], None],
                activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                events: Callable[[str], list[dict[str, Any]]], shares_races: Callable[[str], bool],
                today: Callable[[str], date], now: Callable[[str], datetime],
                home: Callable[[str], dict[str, str]],
                local_groups: Callable[[str, str, date], list[dict[str, Any]]],
                chal: Any, chal_error: type[Exception] | None,
                photo_resp: Callable[[str], Awaitable[Response]],
                photo_cache: Callable[[Any], Any], read_json: Callable[[Request], Awaitable[Any]],
                user_for: Callable[[Request], str | None], host_ok: Callable[[Request], bool],
                origin: str) -> list[BaseRoute]:
    """``home(uid)``: ``{city, state}`` from the athlete's location (never coordinates);
    ``local_groups(city, state, today)``: Explore's cached web-scout groups (no new search);
    ``chal``: ``challenges.Challenges`` or None."""
    errors: tuple[type[Exception], ...] = (CommunityError, ClubError, SocialError) + ((chal_error,) if chal_error else ())

    def wrap(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                cm.require(user_id)
                return await handler(request, user_id)
            except errors as e:
                return JSONResponse({"error": e.message}, status_code=e.status)  # type: ignore[attr-defined]
        return plan_api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise CommunityError("bad request")
        return b

    def pid_of(request: Request) -> str:
        return valid_pid(request.path_params["post_id"])

    def cid_of(request: Request) -> str:
        return valid_cid(request.path_params["club_id"])

    def by_of(uid: str, cache: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        if cache is not None and uid in cache:
            return cache[uid]
        u = person(uid) or {}
        out = {**u, "id": uid, "name": first_name(uid)}
        if cache is not None:
            cache[uid] = out
        return out

    def deco(p: dict[str, Any]) -> dict[str, Any]:
        seen: dict[str, dict[str, Any]] = {}
        return {**p, "user": person(p["author"]),
                "comments": [{**c, "by": by_of(c["by"], seen)} for c in p.get("comments") or []]}

    # ------------------------------------------------------------- feed --
    async def feed(request: Request, user_id: str) -> Response:
        cursor = request.query_params.get("cursor") or None
        club = request.query_params.get("club") or None
        scope = request.query_params.get("scope") or "all"
        group = request.query_params.get("group") or None
        if club is not None:
            club = valid_cid(club)
        if group is not None and (len(group) > 20 or not group.isalnum()):
            raise CommunityError("group not found", 404)
        out = await run(lambda: cm.feed(user_id, cursor, club=club, scope=scope, group=group))
        drafts = await run(lambda: len(cm.drafts(user_id))) if cursor is None else None
        pinned = out.get("pinned")
        return JSONResponse({"items": [deco(p) for p in out["items"]], "next": out["next"], "drafts": drafts,
                             "following": len(cm.social.following_ids(user_id)),
                             "pinned": deco(pinned) if pinned else None})

    async def post_create(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        wid = b.get("workout_id")
        card = None
        if wid is not None:
            if activity_key(wid) is None or (isinstance(wid, int) and wid <= 0):  # Garmin int or "<source>:<id>"
                raise CommunityError("workout not found", 404)
            day, acts = await run(lambda: activities(user_id))
            card = workout_card(acts, wid, day)
            if card is None:
                raise CommunityError("That workout hasn't synced yet.", 404)
            b.setdefault("category", "other")
            have = await run(lambda: cm.workout_post(user_id, wid))
            if have is not None:  # already on the feed (auto-shared or shared before): no copy
                return JSONResponse({"post": deco(await run(lambda: cm.get(user_id, have))), "already": True})
        post = await run(lambda: cm.create(user_id, b, workout=card))
        if wid is not None:
            await run(lambda: cm.claim_workout(user_id, wid))
        return JSONResponse({"post": deco(post)}, status_code=201)

    async def workout_post(request: Request, user_id: str) -> Response:
        """Is this workout of mine on the feed? ``{post_id}`` or null (for "Post to feed")."""
        raw = str(request.path_params["workout_id"])[:80]
        wid: Any = int(raw) if raw.isdigit() else raw
        return JSONResponse({"post_id": await run(lambda: cm.workout_post(user_id, wid))})

    async def post_get(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        return JSONResponse({"post": deco(await run(lambda: cm.get(user_id, pid)))})

    async def post_patch(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        b = await body_of(request)
        return JSONResponse({"post": deco(await run(lambda: cm.update(user_id, pid, b)))})

    async def post_delete(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        await run(lambda: cm.delete(user_id, pid))
        return JSONResponse({"ok": True})

    async def post_photo(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        try:
            n = int(request.path_params["n"])
        except ValueError:
            n = -1
        got = await run(lambda: cm.photo(user_id, pid, n))
        if got is None:
            return JSONResponse({"error": "no photo"}, status_code=404)
        mime, data = got
        return Response(data, media_type=mime, headers={
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'",
            "Content-Disposition": "inline"})

    async def reactions(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        if request.method == "DELETE":
            return JSONResponse({"post": deco(await run(lambda: cm.unreact(user_id, pid)))})
        b = await body_of(request)
        return JSONResponse({"post": deco(await run(lambda: cm.react(user_id, pid, b.get("kind"))))})

    async def comment_add(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        b = await body_of(request)
        c = await run(lambda: cm.comment(user_id, pid, b.get("text"), b.get("reply_to")))
        return JSONResponse({"comment": {**c, "by": by_of(user_id)}}, status_code=201)

    def comment_id(request: Request) -> str:
        cid = str(request.path_params["comment_id"])[:40]
        if not cid.startswith("c"):
            raise CommunityError("comment not found", 404)
        return cid

    async def comment_edit(request: Request, user_id: str) -> Response:
        pid, cid = pid_of(request), comment_id(request)
        b = await body_of(request)
        c = await run(lambda: cm.edit_comment(user_id, pid, cid, b.get("text")))
        return JSONResponse({"comment": {**c, "by": by_of(user_id)}})

    async def comment_like(request: Request, user_id: str) -> Response:
        pid, cid = pid_of(request), comment_id(request)
        on = request.method == "POST"
        c = await run(lambda: cm.like_comment(user_id, pid, cid, on))
        return JSONResponse({"comment": {**c, "by": by_of(c["by"])}})

    async def comment_likers(request: Request, user_id: str) -> Response:
        pid, cid = pid_of(request), comment_id(request)
        ids = await run(lambda: cm.comment_likers(user_id, pid, cid))
        people = [u for u in (person(i) for i in ids[:200]) if u]
        return JSONResponse({"people": people})

    async def mentionable(request: Request, user_id: str) -> Response:
        """People the viewer can @mention on a post (``pid``) or in a new post (``audience``)."""
        raw = request.query_params.get("pid") or None
        pid = valid_pid(raw) if raw else None
        aud = (request.query_params.get("audience") or "")[:80] or None
        rows = await run(lambda: cm.mentionable(user_id, pid, aud))
        out = []
        for r in rows:
            u = person(r["id"])
            if u:
                out.append({**u, "can_see": r["can_see"]})
        return JSONResponse({"people": out})

    async def comment_delete(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        cid = str(request.path_params["comment_id"])[:40]
        await run(lambda: cm.delete_comment(user_id, pid, cid))
        return JSONResponse({"ok": True})

    async def hide(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        await run(lambda: cm.hide(user_id, pid))
        return JSONResponse({"ok": True, "message": "Hidden from your feed."})

    async def report(request: Request, user_id: str) -> Response:
        pid = pid_of(request)
        b = await body_of(request)
        await run(lambda: cm.report(user_id, pid, b.get("reason")))
        return JSONResponse({"ok": True, "message": "Thanks. We've hidden it for you and let the team know."})

    async def photo_upload(request: Request) -> Response:
        """Raw-body upload (no JSON): same guards as the API, by hand."""
        if not host_ok(request):
            return JSONResponse({"error": "bad host"}, status_code=400)
        user_id = user_for(request)
        if user_id is None:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        if request.headers.get("origin", "") != origin:
            return JSONResponse({"error": "bad origin"}, status_code=403)
        try:
            cm.require(user_id)
            declared = int(request.headers.get("content-length") or 0)
        except CommunityError as e:
            return JSONResponse({"error": e.message}, status_code=e.status)
        except ValueError:
            return JSONResponse({"error": "bad request"}, status_code=400)
        too_big = JSONResponse({"error": "That photo is too large (max 800 KB)."}, status_code=413)
        if declared > PHOTO_MAX:
            return too_big
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > PHOTO_MAX:
                return too_big
        try:
            out = await run(lambda: cm.save_photo(user_id, bytes(buf)))
        except CommunityError as e:
            return JSONResponse({"error": e.message}, status_code=e.status)
        except Exception as e:
            log_event(logger, logging.ERROR, "app_unexpected_error", path=request.url.path, error=type(e).__name__)
            return JSONResponse({"error": f"Internal error ({type(e).__name__})"}, status_code=500)
        resp = JSONResponse(out, status_code=201)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ----------------------------------------------------------- drafts --
    async def drafts_get(request: Request, user_id: str) -> Response:
        return JSONResponse({"drafts": await run(lambda: cm.drafts(user_id))})

    async def draft_share(request: Request, user_id: str) -> Response:
        did = str(request.path_params["draft_id"])[:40]
        b = await read_json(request)
        post = await run(lambda: cm.share(user_id, did, b if isinstance(b, dict) else {}))
        return JSONResponse({"post": deco(post), "message": "Shared to your Feed."}, status_code=201)

    async def draft_dismiss(request: Request, user_id: str) -> Response:
        did = str(request.path_params["draft_id"])[:40]
        await run(lambda: cm.dismiss(user_id, did))
        return JSONResponse({"ok": True})

    async def settings_route(request: Request, user_id: str) -> Response:
        if request.method == "PUT":
            b = await body_of(request)
            s = await run(lambda: cm.put_settings(user_id, b))
        else:
            s = await run(lambda: cm.settings(user_id))
        return JSONResponse({"settings": s, "usage": await run(lambda: cm.usage(user_id))})

    # ----------------------------------------------------------- people --
    async def suggested(request: Request, user_id: str) -> Response:
        rows = await run(lambda: cm.suggestions(user_id))
        return JSONResponse({"people": [{"user": person(r["user_id"]), "reason": r["reason"]} for r in rows]})

    async def people_follow(request: Request, user_id: str) -> Response:
        """Follow someone from Suggested (only people Community suggests: no enumeration)."""
        pid = str(request.path_params["person_id"])[:80]
        if pid not in {r["user_id"] for r in await run(lambda: cm.suggestions(user_id, limit=500))}:
            raise CommunityError("person not found", 404)
        res = await run(lambda: cm.social.follow(user_id, code=cm.social.invite_code(pid)))
        if res["notify"]:
            title = "New follower" if res["status"] == "active" else "Follow request"
            verb = "is now following" if res["status"] == "active" else "wants to follow"
            push(res["notify"], f"social-follow:{res['notify']}:{user_id}", 86400, title,
                 f"{first_name(user_id)} {verb} your training on rabbt.")
        msg = f"You're following {first_name(pid)}." if res["status"] == "active" else f"Request sent to {first_name(pid)}."
        return JSONResponse({"ok": True, "status": res["status"], "message": msg})

    async def people_photo(request: Request, user_id: str) -> Response:
        pid = str(request.path_params["person_id"])[:80]
        if not await run(lambda: cm.related(user_id, pid)):
            return JSONResponse({"error": "no photo"}, status_code=404)
        return await photo_resp(pid)

    # ------------------------------------------------------------ clubs --
    async def meetups_mine(request: Request, user_id: str) -> Response:
        rows = await run(lambda: clubs.my_meetups(user_id, now(user_id)))
        return JSONResponse({"meetups": [{**m, "going": [person(u) for u in m["going"]]} for m in rows]})

    async def clubs_list(request: Request, user_id: str) -> Response:
        q = (request.query_params.get("q") or "")[:40]
        loc = await run(lambda: home(user_id))
        city, state = loc.get("city") or "", loc.get("state") or ""
        out = await run(lambda: clubs.overview(user_id, city=city, state=state, q=q))
        for c in out["invites"]:
            c["invited_by"] = person(c["invited_by"])
        local: list[dict[str, Any]] = []
        if city and not q:
            try:
                raw = await run(lambda: local_groups(city, state, today(user_id)))
            except Exception:
                raw = []
            local = [{k: g.get(k) for k in ("id", "name", "category", "organizer", "when", "where", "url")}
                     for g in raw or [] if g.get("category") in ("run", "ride", "swim", "other")][:6]
        return JSONResponse({**out, "home": {"city": city, "state": state}, "local": local})

    async def club_create(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        return JSONResponse({"club": await run(lambda: clubs.create(user_id, b))}, status_code=201)

    async def club_join_code(request: Request, user_id: str) -> Response:
        b = await body_of(request)
        return JSONResponse({"club": await run(lambda: clubs.join(user_id, code=b.get("code")))})

    def _club_view(uid: str, cid: str) -> dict[str, Any]:
        c = clubs.get(uid, cid)
        c["people"] = [{**p, "user": person(p["user_id"])} for p in c["people"]]
        c["pending"] = [person(u) for u in c.get("pending") or []]
        c["invited"] = [person(u) for u in c.get("invited") or []]
        if c["role"] is None:  # a non-member sees the card only
            c["upcoming"], c["challenges"] = [], []
            return c
        c["meetups"] = [{**m, "going": [person(u) for u in m["going"]]} for m in clubs.meetups(uid, cid, now(uid))]
        ups = clubs.upcoming(uid, cid, events=events, shares_races=shares_races, today=today(uid))
        c["upcoming"] = [{**u, "people": [person(x) for x in u.pop("user_ids")]} for u in ups]
        c["challenges"] = chal.club_view(uid, c["challenges"], cid) if chal is not None and c["challenges"] else []
        c["can_challenge"] = chal is not None and c["kind"] == "club" and c["role"] in ("owner", "admin")
        return c

    async def club_get(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        return JSONResponse({"club": await run(lambda: _club_view(user_id, cid))})

    async def club_patch(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        b = await body_of(request)
        return JSONResponse({"club": await run(lambda: clubs.update(user_id, cid, b))})

    async def club_delete(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        await run(lambda: clubs.delete(user_id, cid))
        return JSONResponse({"ok": True})

    async def club_join(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        if request.method == "DELETE":
            await run(lambda: clubs.cancel_request(user_id, cid))
            return JSONResponse({"ok": True})
        c = await run(lambda: clubs.join(user_id, cid))
        if c["requested"]:
            for a in await run(lambda: clubs.admins_of(cid)):
                push(a, f"club-request:{a}:{cid}", 3600, "Join request",
                     f"{first_name(user_id)} asked to join {c['name']}.")
            return JSONResponse({"club": c, "message": "Request sent. An admin will let you in."})
        return JSONResponse({"club": c, "message": f"Welcome to {c['name']}!"})

    async def club_leave(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        await run(lambda: clubs.leave(user_id, cid))
        return JSONResponse({"ok": True})

    async def club_invite(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        b = await body_of(request)
        res = await run(lambda: clubs.invite(user_id, cid, b.get("user_id")))
        if res["notify"]:
            name = await run(lambda: clubs.name_of(cid, user_id)) or "a club"
            push(res["notify"], f"club-invite:{res['notify']}:{cid}", 86400, "Club invite",
                 f"{first_name(user_id)} invited you to {name} on rabbt.")
        return JSONResponse({"ok": True, "message": "Invite sent."})

    def _respond(accept: bool) -> Handler:
        async def h(request: Request, user_id: str) -> Response:
            cid = cid_of(request)
            return JSONResponse({"club": await run(lambda: clubs.respond(user_id, cid, accept))})
        return h

    def _decide(approve: bool) -> Handler:
        async def h(request: Request, user_id: str) -> Response:
            cid = cid_of(request)
            mid = str(request.path_params["member_id"])[:80]
            await run(lambda: clubs.decide(user_id, cid, mid, approve))
            if approve:
                name = await run(lambda: clubs.name_of(cid, user_id)) or "the club"
                push(mid, f"club-approved:{mid}:{cid}", 3600, "You're in", f"Welcome to {name} on rabbt.")
            return JSONResponse({"club": await run(lambda: _club_view(user_id, cid))})
        return h

    async def club_code(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        return JSONResponse({"code": await run(lambda: clubs.new_code(user_id, cid))})

    async def club_member(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        mid = str(request.path_params["member_id"])[:80]
        if request.method == "DELETE":
            await run(lambda: clubs.remove(user_id, cid, mid))
        else:
            b = await body_of(request)
            await run(lambda: clubs.set_role(user_id, cid, mid, b.get("role")))
        return JSONResponse({"club": await run(lambda: _club_view(user_id, cid))})

    # ---------------------------------------------------------- meetups --
    def _meetup_out(m: dict[str, Any]) -> dict[str, Any]:
        return {**m, "going": [person(u) for u in m["going"]]}

    async def meetup_add(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        b = await body_of(request)
        m = await run(lambda: clubs.add_meetup(user_id, cid, b, now(user_id)))
        return JSONResponse({"meetup": _meetup_out(m)}, status_code=201)

    async def meetup_one(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        mid = valid_mid(request.path_params["meetup_id"])
        if request.method == "DELETE":
            told = await run(lambda: clubs.delete_meetup(user_id, cid, mid))
            name = await run(lambda: clubs.name_of(cid, user_id)) or "your club"
            for u in told:
                push(u, f"meetup-cancel:{u}:{mid}", 3600, "Meetup cancelled", f"A {name} meetup you planned to join was cancelled.")
            return JSONResponse({"ok": True})
        b = await body_of(request)
        return JSONResponse({"meetup": _meetup_out(await run(lambda: clubs.update_meetup(user_id, cid, mid, b, now(user_id))))})

    async def meetup_rsvp(request: Request, user_id: str) -> Response:
        cid = cid_of(request)
        mid = valid_mid(request.path_params["meetup_id"])
        b = await body_of(request)
        m = await run(lambda: clubs.rsvp(user_id, cid, mid, b.get("status"), now(user_id)))
        return JSONResponse({"meetup": _meetup_out(m)})

    # ------------------------------------------------------- challenges --
    async def challenge_start(request: Request, user_id: str) -> Response:
        if chal is None:
            raise CommunityError("Challenges aren't configured on this server.", 503)
        cid = cid_of(request)
        b = await body_of(request)
        await run(lambda: clubs.can_start_challenge(user_id, cid))
        g = await run(lambda: chal.start_club(user_id, b.get("template"), b.get("period"), cid, max_people=MAX_MEMBERS))
        await run(lambda: clubs.add_challenge(user_id, cid, g["id"]))
        return JSONResponse({"club": await run(lambda: _club_view(user_id, cid))}, status_code=201)

    async def challenge_join(request: Request, user_id: str) -> Response:
        if chal is None:
            raise CommunityError("Challenges aren't configured on this server.", 503)
        cid = cid_of(request)
        gid = str(request.path_params["challenge_id"])[:20]
        if not await run(lambda: clubs.is_member(cid, user_id)) or cid.startswith("r-"):
            raise ClubError("club not found", 404)
        await run(lambda: chal.join_club(user_id, gid, cid))
        return JSONResponse({"club": await run(lambda: _club_view(user_id, cid))})

    P = "/app/api/community"
    C = f"{P}/clubs/{{club_id}}"
    return [
        Route(f"{P}/feed", wrap(feed, mutating=False), methods=["GET"]),
        Route(f"{P}/posts", wrap(post_create, mutating=True), methods=["POST"]),
        Route(f"{P}/workouts/{{workout_id}}/post", wrap(workout_post, mutating=False), methods=["GET"]),
        Route(f"{P}/posts/{{post_id}}", wrap(post_get, mutating=False), methods=["GET"]),
        Route(f"{P}/posts/{{post_id}}", wrap(post_patch, mutating=True), methods=["PATCH"]),
        Route(f"{P}/posts/{{post_id}}", wrap(post_delete, mutating=True), methods=["DELETE"]),
        Route(f"{P}/posts/{{post_id}}/photos/{{n}}", photo_cache(wrap(post_photo, mutating=False)), methods=["GET"]),
        Route(f"{P}/posts/{{post_id}}/reactions", wrap(reactions, mutating=True), methods=["POST", "DELETE"]),
        Route(f"{P}/posts/{{post_id}}/comments", wrap(comment_add, mutating=True), methods=["POST"]),
        Route(f"{P}/mentionable", wrap(mentionable, mutating=False), methods=["GET"]),
        Route(f"{P}/posts/{{post_id}}/comments/{{comment_id}}", wrap(comment_delete, mutating=True), methods=["DELETE"]),
        Route(f"{P}/posts/{{post_id}}/comments/{{comment_id}}", wrap(comment_edit, mutating=True), methods=["PATCH"]),
        Route(f"{P}/posts/{{post_id}}/comments/{{comment_id}}/like", wrap(comment_like, mutating=True), methods=["POST", "DELETE"]),
        Route(f"{P}/posts/{{post_id}}/comments/{{comment_id}}/likes", wrap(comment_likers, mutating=False), methods=["GET"]),
        Route(f"{P}/posts/{{post_id}}/hide", wrap(hide, mutating=True), methods=["POST"]),
        Route(f"{P}/posts/{{post_id}}/report", wrap(report, mutating=True), methods=["POST"]),
        Route(f"{P}/photos", photo_upload, methods=["POST"]),
        Route(f"{P}/drafts", wrap(drafts_get, mutating=False), methods=["GET"]),
        Route(f"{P}/drafts/{{draft_id}}/share", wrap(draft_share, mutating=True), methods=["POST"]),
        Route(f"{P}/drafts/{{draft_id}}", wrap(draft_dismiss, mutating=True), methods=["DELETE"]),
        Route(f"{P}/settings", wrap(settings_route, mutating=False), methods=["GET"]),
        Route(f"{P}/settings", wrap(settings_route, mutating=True), methods=["PUT"]),
        Route(f"{P}/people/suggested", wrap(suggested, mutating=False), methods=["GET"]),
        Route(f"{P}/people/{{person_id}}/follow", wrap(people_follow, mutating=True), methods=["POST"]),
        Route(f"{P}/people/{{person_id}}/photo", photo_cache(wrap(people_photo, mutating=False)), methods=["GET"]),
        Route(f"{P}/meetups", wrap(meetups_mine, mutating=False), methods=["GET"]),
        Route(f"{P}/clubs", wrap(clubs_list, mutating=False), methods=["GET"]),
        Route(f"{P}/clubs", wrap(club_create, mutating=True), methods=["POST"]),
        Route(f"{P}/clubs/join", wrap(club_join_code, mutating=True), methods=["POST"]),
        Route(C, wrap(club_get, mutating=False), methods=["GET"]),
        Route(C, wrap(club_patch, mutating=True), methods=["PATCH"]),
        Route(C, wrap(club_delete, mutating=True), methods=["DELETE"]),
        Route(f"{C}/join", wrap(club_join, mutating=True), methods=["POST", "DELETE"]),
        Route(f"{C}/leave", wrap(club_leave, mutating=True), methods=["POST"]),
        Route(f"{C}/invite", wrap(club_invite, mutating=True), methods=["POST"]),
        Route(f"{C}/invite/accept", wrap(_respond(True), mutating=True), methods=["POST"]),
        Route(f"{C}/invite/decline", wrap(_respond(False), mutating=True), methods=["POST"]),
        Route(f"{C}/requests/{{member_id}}/approve", wrap(_decide(True), mutating=True), methods=["POST"]),
        Route(f"{C}/requests/{{member_id}}/decline", wrap(_decide(False), mutating=True), methods=["POST"]),
        Route(f"{C}/code", wrap(club_code, mutating=True), methods=["POST"]),
        Route(f"{C}/members/{{member_id}}", wrap(club_member, mutating=True), methods=["PUT", "DELETE"]),
        Route(f"{C}/meetups", wrap(meetup_add, mutating=True), methods=["POST"]),
        Route(f"{C}/meetups/{{meetup_id}}", wrap(meetup_one, mutating=True), methods=["PATCH", "DELETE"]),
        Route(f"{C}/meetups/{{meetup_id}}/rsvp", wrap(meetup_rsvp, mutating=True), methods=["POST"]),
        Route(f"{C}/challenges", wrap(challenge_start, mutating=True), methods=["POST"]),
        Route(f"{C}/challenges/{{challenge_id}}/join", wrap(challenge_join, mutating=True), methods=["POST"]),
    ]


__all__ = ["make_routes"]
