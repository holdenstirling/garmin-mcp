"""HTTP routes for race people (``racepeople``). Built by ``webapp.build_app_routes`` from its
own helpers so the same guards apply (``plan_api``: session, Host, Origin + JSON on mutating
calls, coach accounts 403 outside coach paths). Athlete routes also require an allowlisted
athlete (``social.require``).

    GET    /app/api/events/{eid}/people              people, settings, share link, linked coaches
    POST   /app/api/events/{eid}/people              {role, user_id | email | code | coach_email}
    DELETE /app/api/events/{eid}/people/{pid}        remove (access ends)
    PUT    /app/api/events/{eid}/crew                share/teammate toggles, crew notes, tracking link
    POST   /app/api/events/{eid}/crew/link           make (or remake) the share link
    DELETE /app/api/events/{eid}/crew/link           turn it off
    GET    /app/api/events/{eid}/together            racing together: teammates (+ opted-in grade/finish)
    GET    /app/api/events/{eid}/together/messages   ?after=
    POST   /app/api/events/{eid}/together/messages   {text}
    POST   /app/api/events/{eid}/together/cheer      {text?}
    GET    /app/api/races/people                     per-event summary for the People row on cards
    GET    /app/api/races/invites                    invites to me
    POST   /app/api/races/invites/{pid}/accept|decline
    GET    /app/api/races/following                  races I crew / pace / cheer at
    DELETE /app/api/races/following/{pid}            stop following (or stop racing together)
    GET    /app/api/races/people/{uid}/photo         a race contact's photo
    GET    /app/api/coach/athletes/{aid}/events/{eid}/people   linked coach, read-only
    GET    /app/r/{token}                            crew page (no login)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Route

from . import predict as _predict
from .logs import log_event
from .planbuilder import iter_sessions
from .racepeople import GENERIC_SENT, RaceError, RacePeople, render
from .social import SocialError

logger = logging.getLogger(__name__)
Handler = Callable[[Request, str], Awaitable[Response]]
PAGE_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                                           "form-action 'none'; frame-ancestors 'none'"}
ROLE_VERB = {"racing": "race", "crew": "crew", "pacer": "pace", "spectator": "cheer"}


def invite_text(name: str, role: str, race: str) -> str:
    """'Bill invited you to crew at Leadville 100' (<= 140 chars)."""
    s = f"{name} invited you to {ROLE_VERB.get(role, 'join')} at {race}"
    return s if len(s) <= 120 else s[:119].rstrip() + "…"


def week_rows(plan: dict[str, Any] | None, today: date) -> list[tuple[str, str]]:
    """This week's planned sessions (Mon-Sun): titles and minutes only."""
    if not plan:
        return []
    mon = today - timedelta(days=today.weekday())
    end = (mon + timedelta(days=6)).isoformat()
    by_day: dict[str, list[dict[str, Any]]] = {}
    for _, d, s in iter_sessions(plan):
        if mon.isoformat() <= d <= end:
            by_day.setdefault(d, []).append(s)
    out = []
    for d in sorted(by_day):
        items = ", ".join(f"{s.get('title') or 'Session'}{f' · {s['minutes']} min' if s.get('minutes') else ''}"
                          for s in by_day[d] if s.get("sport") != "rest") or "Rest"
        out.append((date.fromisoformat(d).strftime("%a %b %-d"), items[:200]))
    return out


def make_routes(*, rp: RacePeople, soc: Any, links: Any, plan_api: Callable[..., Any],
                user_error: type[Exception], host_ok: Callable[[Request], bool], base_url: str,
                person: Callable[[str], dict[str, Any] | None], first_name: Callable[[str], str],
                push: Callable[[str, str, float, str, str], None], moment: Callable[[str, dict[str, Any]], Any] | None,
                grade: Callable[[str, str], str | None], finish: Callable[[str, str], dict[str, Any] | None],
                today: Callable[[str], date], plan_of: Callable[[str], dict[str, Any] | None],
                imperial: Callable[[str], bool], photo_resp: Callable[[str], Awaitable[Response]],
                photo_cache: Callable[[Any], Any], read_json: Callable[[Request], Awaitable[Any]]) -> list[BaseRoute]:

    def share_url(token: str | None) -> str | None:
        return f"{base_url.rstrip('/')}/app/r/{token}" if token else None

    def wrap(handler: Handler, *, mutating: bool, athlete: bool = True) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            try:
                if athlete:
                    soc.require(user_id)
                return await handler(request, user_id)
            except (RaceError, SocialError) as e:
                return JSONResponse({"error": e.message}, status_code=e.status)
        return plan_api(inner, mutating=mutating)

    async def run(fn: Callable[[], Any]) -> Any:
        return await anyio.to_thread.run_sync(fn)

    async def body_of(request: Request) -> dict[str, Any]:
        b = await read_json(request)
        if not isinstance(b, dict):
            raise ValueError("body")
        return b

    def eid_of(request: Request) -> str:
        return str(request.path_params["event_id"])[:64]

    def people_view(uid: str, eid: str) -> dict[str, Any]:
        v = rp.view(uid, eid)
        v["people"] = [{**p, "user": person(p["user_id"]) if p.get("user_id") else None} for p in v["people"]]
        v["share_url"] = share_url(v.pop("token"))
        team = rp.team(uid, eid)
        v["racing_together"] = len(team["members"]) if team else 0
        return v

    # ------------------------------------------------------------ owner --
    async def people_get(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        return JSONResponse(await run(lambda: people_view(user_id, eid)))

    async def people_invite(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        b = await body_of(request)
        res = await run(lambda: rp.invite(user_id, eid, role=b.get("role"), user_id=b.get("user_id"),
                                          email=b.get("email"), code=b.get("code"), coach_email=b.get("coach_email")))
        to, p = res["notify"], res["person"]
        if to:
            race = await run(lambda: _event_name(user_id, eid))
            text = invite_text(first_name(user_id), p["role"], race)
            push(to, f"race-invite:{to}:{p['id']}", 86400, "Race invite", text + ".")
            if moment is not None:
                try:
                    await run(lambda: moment(to, {"type": "race_invite", "key": f"raceinvite:{p['id']}",
                                                  "text": f"🏁 {text}.", "ttl_days": 30,
                                                  "actions": [{"id": "race_invite", "label": "View invite"}]}))
                except Exception as e:  # the invite stands without the Rabbit-log line
                    log_event(logger, logging.WARNING, "race_invite_moment_failed", error=type(e).__name__)
        out = await run(lambda: people_view(user_id, eid))
        if res["by_email"]:
            return JSONResponse({**out, "message": GENERIC_SENT})
        msg = ("Coach added." if p["role"] == "coach" else
               f"Invite sent to {first_name(p['user_id'])}." if p.get("user_id") else GENERIC_SENT)
        return JSONResponse({**out, "message": msg})

    def _event_name(uid: str, eid: str) -> str:
        return str(rp._event(uid, eid).get("name") or "a race")

    async def people_remove(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        pid = request.path_params["person_id"]
        await run(lambda: rp.remove(user_id, eid, pid))
        return JSONResponse(await run(lambda: people_view(user_id, eid)))

    async def crew_put(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        b = await body_of(request)
        return JSONResponse({"settings": await run(lambda: rp.put_settings(user_id, eid, b))})

    async def crew_link(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        if request.method == "DELETE":
            await run(lambda: rp.share_revoke(user_id, eid))
            return JSONResponse({"url": None})
        return JSONResponse({"url": share_url(await run(lambda: rp.share_create(user_id, eid)))}, status_code=201)

    # ------------------------------------------------------ racing together --
    def _team_view(uid: str, eid: str) -> dict[str, Any]:
        t = rp.team(uid, eid)
        mine = rp.view(uid, eid)["settings"]
        me = {"team_grade": mine["team_grade"], "team_finish": mine["team_finish"]}
        if t is None:
            return {"members": [], "me": me}
        out = []
        for m in t["members"]:
            s = m["settings"]
            row: dict[str, Any] = {"user": person(m["user_id"]), "date": m["date"], "grade": None, "finish": None}
            if s["team_grade"]:
                try:
                    row["grade"] = grade(m["user_id"], m["event_id"])
                except Exception:
                    pass
            if s["team_finish"]:
                try:
                    f = finish(m["user_id"], m["event_id"])
                    row["finish"] = ((f or {}).get("estimate") or {}).get("text") or None
                except Exception:
                    pass
            out.append(row)
        return {"members": out, "me": me}

    async def together_get(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        return JSONResponse(await run(lambda: _team_view(user_id, eid)))

    def _msg_view(m: dict[str, Any], viewer: str) -> dict[str, Any]:
        return {**m, "mine": m["by"] == viewer, "by": {"id": m["by"], "name": first_name(m["by"])}}

    async def together_messages(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        if request.method == "GET":
            try:
                after = int(request.query_params.get("after") or 0)
            except ValueError:
                after = 0
            msgs = await run(lambda: rp.messages(user_id, eid, after))
            return JSONResponse({"messages": [_msg_view(m, user_id) for m in msgs]})
        b = await body_of(request)
        msg, others = await run(lambda: rp.post(user_id, eid, b.get("text")))
        gid = rp.team(user_id, eid)
        for to in others:  # coalesced: one push per person per group per minute
            push(to, f"race-chat:{to}:{(gid or {}).get('group')}", 60, f"{first_name(user_id)} · race chat",
                 msg["text"])
        return JSONResponse({"message": _msg_view(msg, user_id)}, status_code=201)

    async def together_cheer(request: Request, user_id: str) -> Response:
        eid = eid_of(request)
        b = await read_json(request)
        text = b.get("text") if isinstance(b, dict) else None
        msg, others = await run(lambda: rp.post(user_id, eid, text, kind="cheer"))
        gid = rp.team(user_id, eid)
        for to in others:
            push(to, f"race-chat:{to}:{(gid or {}).get('group')}", 60, f"{first_name(user_id)} cheered you on",
                 msg["text"] or "📣 Let's go!")
        return JSONResponse({"message": _msg_view(msg, user_id)}, status_code=201)

    # ------------------------------------------------------------- guest --
    async def races_summary(request: Request, user_id: str) -> Response:
        s = await run(lambda: rp.summary(user_id))
        return JSONResponse({"events": {eid: {**v, "people": [p for p in (person(u) for u in v.pop("user_ids")) if p]}
                                        for eid, v in s.items()}})

    async def invites_get(request: Request, user_id: str) -> Response:
        inv = await run(lambda: rp.inbox(user_id))
        return JSONResponse({"invites": [{**i, "from": person(i["from"])} for i in inv]})

    async def invite_respond(request: Request, user_id: str) -> Response:
        pid = request.path_params["person_id"]
        accept = request.url.path.endswith("/accept")
        res = await run(lambda: rp.respond(user_id, pid, accept))
        if accept:
            push(res["owner"], f"race-accept:{res['owner']}:{pid}", 86400, "Race invite accepted",
                 f"{first_name(user_id)} is in: {ROLE_VERB.get(res['role'], 'join')}.")
        return JSONResponse({"ok": True, "role": res["role"], "event_id": res.get("event_id")})

    async def following_get(request: Request, user_id: str) -> Response:
        rows = await run(lambda: rp.following(user_id))
        return JSONResponse({"races": [{**r, "athlete": person(r.pop("owner"))} for r in rows]})

    async def following_leave(request: Request, user_id: str) -> Response:
        pid = request.path_params["person_id"]
        await run(lambda: rp.leave(user_id, pid))
        return JSONResponse({"ok": True})

    async def people_photo(request: Request, user_id: str) -> Response:
        pid = str(request.path_params["uid"])
        if not await run(lambda: rp.related_people(user_id, pid)):
            return JSONResponse({"error": "no photo"}, status_code=404)
        return await photo_resp(pid)

    # ------------------------------------------------------------- coach --
    async def coach_people(request: Request, user_id: str) -> Response:
        aid = request.path_params["athlete_id"]
        eid = eid_of(request)
        try:
            await run(lambda: links.require(user_id, aid))
        except ValueError as e:
            raise user_error(str(e), 404) from None
        v = await run(lambda: rp.view(aid, eid))
        return JSONResponse({"people": [{"role": p["role"], "status": p["status"],
                                         "name": first_name(p["user_id"]) if p.get("user_id") else None}
                                        for p in v["people"] if p["status"] == "accepted"],
                             "crew_notes": v["settings"]["crew_notes"]})

    # -------------------------------------------------------------- page --
    async def crew_page(request: Request) -> Response:
        if not host_ok(request):
            return HTMLResponse("Not found", status_code=404, headers=PAGE_HEADERS)
        got = await run(lambda: rp.resolve(request.path_params["token"]))
        if got is None:
            return HTMLResponse("This link isn't active anymore.", status_code=404, headers=PAGE_HEADERS)
        owner, ev, s = got

        def build() -> str:
            g = f = None
            wk: list[tuple[str, str]] | None = None
            km = None
            if s["show_grade"]:
                try:
                    g = grade(owner, ev["id"])
                except Exception:
                    g = None
            if s["show_finish"]:
                try:
                    f = finish(owner, ev["id"])
                    km = _predict.event_inputs(ev)["kwargs"].get("distance_km")
                except Exception:
                    f = None
            if s["show_week"]:
                try:
                    wk = week_rows(plan_of(owner), today(owner))
                except Exception:
                    wk = None
            return render(first_name(owner), ev, s, today(owner), grade=g, finish=f, distance_km=km, week=wk,
                          imperial=imperial(owner))
        return HTMLResponse(await run(build), headers=PAGE_HEADERS)

    E = "/app/api/events/{event_id}"
    return [
        Route(f"{E}/people", wrap(people_get, mutating=False), methods=["GET"]),
        Route(f"{E}/people", wrap(people_invite, mutating=True), methods=["POST"]),
        Route(f"{E}/people/{{person_id}}", wrap(people_remove, mutating=True), methods=["DELETE"]),
        Route(f"{E}/crew", wrap(crew_put, mutating=True), methods=["PUT"]),
        Route(f"{E}/crew/link", wrap(crew_link, mutating=True), methods=["POST", "DELETE"]),
        Route(f"{E}/together", wrap(together_get, mutating=False), methods=["GET"]),
        Route(f"{E}/together/messages", wrap(together_messages, mutating=False), methods=["GET"]),
        Route(f"{E}/together/messages", wrap(together_messages, mutating=True), methods=["POST"]),
        Route(f"{E}/together/cheer", wrap(together_cheer, mutating=True), methods=["POST"]),
        Route("/app/api/races/people", wrap(races_summary, mutating=False), methods=["GET"]),
        Route("/app/api/races/invites", wrap(invites_get, mutating=False), methods=["GET"]),
        Route("/app/api/races/invites/{person_id}/accept", wrap(invite_respond, mutating=True), methods=["POST"]),
        Route("/app/api/races/invites/{person_id}/decline", wrap(invite_respond, mutating=True), methods=["POST"]),
        Route("/app/api/races/following", wrap(following_get, mutating=False), methods=["GET"]),
        Route("/app/api/races/following/{person_id}", wrap(following_leave, mutating=True), methods=["DELETE"]),
        Route("/app/api/races/people/{uid}/photo", photo_cache(wrap(people_photo, mutating=False)), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/events/{event_id}/people",
              wrap(coach_people, mutating=False, athlete=False), methods=["GET"]),
        Route("/app/r/{token}", crew_page, methods=["GET"]),
    ]


__all__ = ["invite_text", "make_routes", "week_rows"]
