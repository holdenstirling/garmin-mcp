"""HTTP routes for the Rabbit web app, mounted under /app on the MCP server's app.

Every /app/api route goes through ``_api``: Host check, session -> user_id
(never from the request body), Origin + JSON content-type check on mutating
calls, a body size cap, and a generic error for anything unexpected.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from collections.abc import AsyncIterator, Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .appstore import AppStore
from .attachments import MAX_UPLOAD, AttachmentError, AttachmentStore
from .coaching import CoachError
from .config import Settings
from .garminlogin import Busy, Cooldown, LoginManager
from .logs import log_event
from .planbuilder import PlanError, build_plan
from .plans import public_plan
from .events import TYPE_DISTANCES, TYPES
from .coaches import CoachChat, CoachNotes
from .gcalendar import CalendarError, CalendarNotConnected
from .oura import OuraError, OuraNotConnected
from .adjust import propose as propose_adjustment
from . import racepack
from .share import Shares
from .share import render as render_share
from .planbuilder import iter_sessions
from .providers import GarminError, ReauthRequired
from .tokens import TokenStore, TokenStoreError
from .webauth import WebAuth
from .webchat import ChatRunner, Turn, TurnBusy
from .webpush import WebPush, parse_subscription

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).parent / "web_dist"
MAX_BODY = 16 * 1024

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",  # React/Radix set inline style attributes
    "img-src 'self' data: blob: https://lh3.googleusercontent.com",  # blob: composer previews
    "font-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

Handler = Callable[[Request, str], Awaitable[Response]]


class _Static(StaticFiles):
    """Built frontend: hashed assets cache forever, everything else revalidates."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        resp = await super().get_response(path, scope)
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Content-Security-Policy"] = CSP
        return resp


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class _UserError(Exception):
    """An error whose message goes to the app as-is (not a ValueError, so _api's generic
    "bad request" handling doesn't swallow it)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


async def read_json(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ValueError("body too large")
    return json.loads(raw or b"null")


def build_app_routes(settings: Settings, auth: WebAuth, token_store: TokenStore,
                     push: WebPush | None, logins: LoginManager | None = None,
                     chat: ChatRunner | None = None,
                     *, fake_garmin: bool = False,
                     dev: dict[str, Callable[[str], Any]] | None = None,
                     default_tz: str = "America/Denver") -> list[BaseRoute]:
    local = settings.public_host.split(":")[0] in {"localhost", "127.0.0.1"}

    def host_ok(request: Request) -> bool:
        host = request.headers.get("host", "")
        if host == settings.public_host:
            return True
        return local and host.split(":")[0] in {"localhost", "127.0.0.1"}

    def _api(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            if not host_ok(request):
                return _err(400, "bad host")
            user_id = auth.user_for(request)
            if user_id is None:
                return _err(401, "not signed in")
            if mutating and not auth.check_origin(request):
                return _err(403, "bad origin")
            try:
                resp = await handler(request, user_id)
            except (ValueError, json.JSONDecodeError):
                return _err(400, "bad request")
            except Exception as e:
                log_event(logger, logging.ERROR, "app_unexpected_error",
                          path=request.url.path, error=type(e).__name__)
                return _err(500, f"Internal error ({type(e).__name__})")
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return endpoint

    # ---------------------------------------------------------------- api --
    async def me(request: Request, user_id: str) -> Response:
        try:
            connected = token_store.load(user_id) is not None
        except TokenStoreError:
            connected = False
        cd = logins.cooldown(user_id) if logins else None
        return JSONResponse({
            "user_id": user_id,
            "role": "coach" if user_id.startswith("coach_") else "athlete",
            "coaching": len(auth.coach_links.athletes_of(user_id)),
            "coaches": len(auth.coach_links.coaches_of(user_id)),
            "oura": {"available": auth.oura is not None,
                     "connected": bool(auth.oura and auth.oura.connected(user_id))},
            "calendar": {"available": auth.calendar is not None,
                         "connected": bool(auth.calendar and auth.calendar.connected(user_id))},
            "coach_unread": coach_chat.unread(user_id, "athlete")
            if coach_chat is not None and not user_id.startswith("coach_") else 0,
            "profile": auth.profile(user_id),
            "settings": _settings_view(user_id),
            "dev": {"fake_garmin": fake_garmin, "tools": sorted(dev) if dev else []},
            "athlete": chat.agent.coach.athlete(user_id) if chat else {},
            "goal": chat.agent.coach.active_goal(user_id) if chat else None,
            "chat": {"available": chat is not None,
                     "active_turn": (t.id if chat and (t := chat.active(user_id)) else None)},
            "garmin_connected": connected,
            "garmin": {
                "connected": connected,
                "can_connect": logins is not None,
                "cooldown_until": int(cd[0]) if cd else None,
                "cooldown_scope": cd[1] if cd else None,
                "fake": fake_garmin,
            },
            "push": {
                "available": push is not None,
                "public_key": push.public_key if push else None,
                "subscriptions": push.count(user_id) if push else 0,
            },
        })

    async def push_subscribe(request: Request, user_id: str) -> Response:
        if push is None:
            return _err(503, "push not configured")
        sub = parse_subscription(await read_json(request))
        if sub is None:
            return _err(400, "invalid subscription")
        n = push.subscribe(user_id, sub)
        return JSONResponse({"ok": True, "subscriptions": n})

    async def push_unsubscribe(request: Request, user_id: str) -> Response:
        if push is None:
            return _err(503, "push not configured")
        body = await read_json(request)
        endpoint = body.get("endpoint") if isinstance(body, dict) else None
        if not isinstance(endpoint, str):
            return _err(400, "endpoint required")
        push.unsubscribe(user_id, endpoint)
        return JSONResponse({"ok": True})

    async def push_test(request: Request, user_id: str) -> Response:
        if push is None:
            return _err(503, "push not configured")
        results = await anyio.to_thread.run_sync(
            lambda: push.send(user_id, "Rabbit", "Notifications are working.")
        )
        return JSONResponse({"results": [
            {"host": r.endpoint_host, "status": r.status, "removed": r.removed} for r in results
        ]})

    # ------------------------------------------------------- Garmin login --
    def _str(body: Any, key: str, max_len: int) -> str:
        v = body.get(key) if isinstance(body, dict) else None
        if not isinstance(v, str) or not v.strip() or len(v) > max_len:
            raise ValueError(key)
        return v

    def _cooldown_resp(e: Cooldown) -> JSONResponse:
        return JSONResponse({"state": "cooldown", "cooldown_until": int(e.until),
                             "cooldown_scope": e.scope}, status_code=429)

    async def garmin_login(request: Request, user_id: str) -> Response:
        if logins is None:
            return _err(503, "Garmin connect not available")
        body = await read_json(request)
        email = _str(body, "email", 254).strip()
        password = _str(body, "password", 256)
        del body
        try:
            job = logins.start(user_id, email, password)
        except Cooldown as e:
            return _cooldown_resp(e)
        except Busy:
            return _err(409, "Another Garmin login is in progress. Try again in a minute.")
        finally:
            del password
        return JSONResponse(job.public(), status_code=202)

    async def garmin_mfa(request: Request, user_id: str) -> Response:
        if logins is None:
            return _err(503, "Garmin connect not available")
        body = await read_json(request)
        job_id = _str(body, "job_id", 64)
        code = _str(body, "code", 12).strip()
        if not code.isdigit():
            raise ValueError("code")
        try:
            job = logins.submit_mfa(user_id, job_id, code)
        except KeyError:
            return _err(404, "login not found")
        except Busy:
            return _err(409, "Another Garmin login is in progress. Try again in a minute.")
        return JSONResponse(job.public(), status_code=202)

    async def garmin_login_status(request: Request, user_id: str) -> Response:
        if logins is None:
            return _err(503, "Garmin connect not available")
        try:
            job = logins.status(user_id, request.path_params["job_id"])
        except KeyError:
            return _err(404, "login not found")
        out = job.public()
        if job.state == "error":
            cd = logins.cooldown(user_id)
            out["cooldown_until"] = int(cd[0]) if cd else None
            out["cooldown_scope"] = cd[1] if cd else None
        return JSONResponse(out)

    async def garmin_disconnect(request: Request, user_id: str) -> Response:
        if logins is None:
            return _err(503, "Garmin connect not available")
        logins.disconnect(user_id, token_store)
        return JSONResponse({"ok": True})

    async def attachment_upload(request: Request) -> Response:
        """Raw-body upload (?name=...). Same guards as _api, minus the JSON content type."""
        if not host_ok(request):
            return _err(400, "bad host")
        user_id = auth.user_for(request)
        if user_id is None:
            return _err(401, "not signed in")
        if request.headers.get("origin", "") != settings.public_base_url:
            return _err(403, "bad origin")
        if atts is None:
            return _err(503, "Chat isn't configured on this server.")
        declared = int(request.headers.get("content-length") or 0)
        if declared > MAX_UPLOAD:
            return _err(413, "File too large.")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > MAX_UPLOAD:
                return _err(413, "File too large.")
        try:
            meta = await anyio.to_thread.run_sync(
                atts.save, user_id, request.query_params.get("name", ""), bytes(buf))
        except AttachmentError as e:
            return _err(400, str(e))
        except Exception as e:
            log_event(logger, logging.ERROR, "app_unexpected_error", path=request.url.path,
                      error=type(e).__name__)
            return _err(500, f"Internal error ({type(e).__name__})")
        return JSONResponse(meta, status_code=201)

    # ------------------------------------------------------------ settings --
    store: AppStore | None = chat.agent._store if chat is not None else None

    def _settings_view(user_id: str) -> dict[str, Any]:
        p = store.user_doc(user_id, "profile").load() if store else {}
        return {"timezone": p.get("timezone") or default_tz, "timezone_set": bool(p.get("timezone")),
                "brief_time": p.get("brief_time") or "06:30",
                "brief_enabled": p.get("brief_enabled", True),
                "workout_feedback": p.get("workout_feedback", True),
                "has_notes": bool(p.get("notes"))}

    async def put_settings(request: Request, user_id: str) -> Response:
        if store is None:
            return _err(503, "Settings aren't available on this server.")
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        upd: dict[str, Any] = {}
        if "timezone" in body:
            tz = body["timezone"]
            try:
                if not isinstance(tz, str) or len(tz) > 64:
                    raise ValueError
                ZoneInfo(tz)
            except (ValueError, ZoneInfoNotFoundError):
                return _err(400, "unknown timezone")
            upd["timezone"] = tz
        if "brief_time" in body:
            bt = body["brief_time"]
            if not isinstance(bt, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", bt):
                return _err(400, "brief_time must be HH:MM")
            upd["brief_time"] = bt
        for key in ("brief_enabled", "workout_feedback"):
            if key in body:
                if not isinstance(body[key], bool):
                    return _err(400, f"{key} must be true or false")
                upd[key] = body[key]
        store.user_doc(user_id, "profile").update(lambda p: p.update(upd))
        return JSONResponse(_settings_view(user_id))

    async def dev_action(request: Request, user_id: str) -> Response:
        name = request.path_params["name"]
        if not dev or name not in dev:
            return _err(404, "not found")
        out = await anyio.to_thread.run_sync(dev[name], user_id)
        return JSONResponse({"ok": True, "result": out})

    # ---------------------------------------------------------------- chat --
    def _ndjson(turn: Turn, start: int) -> StreamingResponse:
        assert chat is not None

        async def gen() -> AsyncIterator[bytes]:
            async for e in chat.events(turn, start):
                yield b"\n" if e is None else (json.dumps(e, default=str) + "\n").encode()
        return StreamingResponse(gen(), media_type="application/x-ndjson",
                                 headers={"X-Accel-Buffering": "no", "X-Turn-Id": turn.id})

    def _coach():
        assert chat is not None
        return chat.agent.coach

    def _thread_or_404(user_id: str, thread_id: Any) -> dict[str, Any] | None:
        return _coach().get_thread(user_id, thread_id) if isinstance(thread_id, str) else None

    atts: AttachmentStore | None = AttachmentStore(store) if store is not None else None

    async def chat_send(request: Request, user_id: str) -> Response:
        if chat is None or atts is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        try:
            metas, blocks = atts.for_message(user_id, body.get("attachments"))
        except AttachmentError as e:
            return _err(400, str(e))
        raw = body.get("message")
        if not isinstance(raw, str) or len(raw) > 4000 or not (raw.strip() or metas):
            raise ValueError("message")
        message = raw.strip() or "(see attached)"
        thread = _thread_or_404(user_id, body.get("thread_id"))
        if thread is None:
            return _err(404, "thread not found")
        if thread["kind"] == "topic" and not thread.get("title"):
            words = " ".join(message.split())
            _coach().rename_thread(user_id, thread["id"],
                                   words if len(words) <= 60 else words[:57].rstrip() + "...")
        try:
            turn = chat.start(user_id, message, thread_id=thread["id"],
                              attachments=metas or None, content_blocks=blocks or None)
        except TurnBusy as e:
            return JSONResponse({"error": "A reply is already in progress.",
                                 "turn_id": e.turn_id}, status_code=409)
        return _ndjson(turn, 0)

    async def chat_approval(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        approval_id = _str(body, "approval_id", 64)
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise ValueError("approved")
        reason = body.get("reason")
        reason = reason.strip()[:300] if isinstance(reason, str) and reason.strip() else None
        ok = chat.resolve(user_id, request.path_params["turn_id"], approval_id, approved, reason)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 409)

    async def chat_cancel(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        return JSONResponse({"ok": chat.cancel(user_id, request.path_params["turn_id"])})

    async def attachment_get(request: Request, user_id: str) -> Response:
        got = atts.load(user_id, request.path_params["att_id"]) if atts else None
        if got is None:
            return _err(404, "not found")
        meta, data = got
        headers = {"Cache-Control": "private, max-age=86400", "Content-Disposition": "inline",
                   "X-Content-Type-Options": "nosniff"}
        if meta["kind"] == "text":  # user text opened in a tab can't run anything
            headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        mime = "text/plain; charset=utf-8" if meta["kind"] == "text" else meta["mime"]
        return Response(data, media_type=mime, headers=headers)

    async def chat_events(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        turn = chat.get(user_id, request.path_params["turn_id"])
        if turn is None:
            return _err(404, "turn not found")
        try:
            start = max(0, int(request.query_params.get("from", "0")))
        except ValueError:
            start = 0
        return _ndjson(turn, start)

    def _thread_view(t: dict[str, Any]) -> dict[str, Any]:
        return {k: t.get(k) for k in ("id", "kind", "title", "goal_id", "created", "updated", "seed")}

    async def threads_list(request: Request, user_id: str) -> Response:
        if chat is None:
            return JSONResponse({"threads": [], "goal": None})
        coach = _coach()
        coach.migrate_legacy(user_id)
        return JSONResponse({"goal": coach.active_goal(user_id),
                             "threads": [_thread_view(t) for t in coach.threads(user_id)]})

    async def thread_create(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        seed = body.get("from")
        if seed is not None and not (isinstance(seed, dict) and isinstance(seed.get("thread_id"), str)
                                     and isinstance(seed.get("turn_id"), str)):
            raise ValueError("from")
        title = body.get("title")
        try:
            t = _coach().create_thread(user_id, title=title if isinstance(title, str) else None,
                                       seed=seed)
        except CoachError as e:
            return _err(400, str(e))
        return JSONResponse(_thread_view(t), status_code=201)

    async def thread_update(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        try:
            t = _coach().rename_thread(user_id, request.path_params["thread_id"],
                                       _str(body, "title", 80))
        except CoachError as e:
            return _err(404, str(e))
        return JSONResponse(_thread_view(t))

    async def thread_delete(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        thread = _thread_or_404(user_id, request.path_params["thread_id"])
        if thread is None:
            return _err(404, "thread not found")
        active = chat.active(user_id)
        if active is not None and not active.done and active.thread_id == thread["id"]:
            return _err(409, "Wait for the current reply to finish.")
        try:
            if thread["kind"] == "coach":
                _coach().clear_thread(user_id, thread["id"])
            else:
                _coach().delete_thread(user_id, thread["id"])
        except CoachError as e:
            return _err(400, str(e))
        return JSONResponse({"ok": True})

    async def messages(request: Request, user_id: str) -> Response:
        if chat is None:
            return JSONResponse({"turns": []})
        thread = _thread_or_404(user_id, request.path_params["thread_id"])
        if thread is None:
            return _err(404, "thread not found")
        try:
            limit = min(100, max(1, int(request.query_params.get("limit", "60"))))
        except ValueError:
            limit = 60
        turns = _coach().turns(user_id, thread["id"])
        before = request.query_params.get("before")
        if before:
            idx = next((i for i, t in enumerate(turns) if t.get("id") == before), len(turns))
            turns = turns[:idx]
        # ?from=start: the opening turns (the coach log's peek at a chat), else the newest.
        page = turns[:limit] if request.query_params.get("from") == "start" else turns[-limit:]
        keys = ("id", "ts", "kind", "label", "user", "parts", "attachments", "seed_from")
        return JSONResponse({"thread": _thread_view(thread),
                             "turns": [{k: t.get(k) for k in keys if k in t} for t in page],
                             "has_more": len(turns) > len(page)})

    planner = chat.agent.planner if chat is not None else None

    async def plan_week_get(request: Request, user_id: str) -> Response:
        if planner is None:
            return _err(503, "Chat isn't configured on this server.")
        return JSONResponse(await planner.week(user_id))

    # ------------------------------------------------------ goal / athlete --
    async def goals_get(request: Request, user_id: str) -> Response:
        if chat is None:
            return JSONResponse({"active": None, "goals": []})
        return JSONResponse(_coach().goals(user_id))

    async def goal_create(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        try:
            return JSONResponse(_coach().create_goal(user_id, body), status_code=201)
        except CoachError as e:
            return _err(400, str(e))

    async def goal_update(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        try:
            return JSONResponse(_coach().update_goal(user_id, request.path_params["goal_id"], body))
        except CoachError as e:
            return _err(400, str(e))

    async def goal_archive(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        try:
            _coach().archive_goal(user_id, request.path_params["goal_id"])
        except CoachError as e:
            return _err(404, str(e))
        return JSONResponse({"ok": True})

    async def athlete_put(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        try:
            return JSONResponse(_coach().update_athlete(user_id, body))
        except CoachError as e:
            return _err(400, str(e))

    # ------------------------------------------------------- plan builder --
    plans = chat.agent.plans if chat is not None else None
    coach_chat = CoachChat(store) if store is not None else None
    coach_notes = CoachNotes(store) if store is not None else None

    def _plan_resp(user_id: str, plan: dict[str, Any] | None, status: int = 200,
                   **extra: Any) -> JSONResponse:
        assert plans is not None
        return JSONResponse({"plan": public_plan(plan, plans.today(user_id)), **extra},
                            status_code=status)

    async def _plan_call(fn: Callable[[], Any]) -> Any:
        """Run a PlanService call off the event loop; its validation errors become 400s
        with their message (they're ValueErrors, which _api would turn into "bad request")."""
        try:
            return await anyio.to_thread.run_sync(fn)
        except (PlanError, CoachError) as e:
            raise _UserError(str(e)) from None
        except ReauthRequired:
            raise _UserError("Reconnect Garmin in settings, then try again.", 409) from None
        except GarminError as e:
            raise _UserError(str(e), 502) from None

    def _plan_api(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            if plans is None:
                return _err(503, "The plan builder isn't configured on this server.")
            try:
                return await handler(request, user_id)
            except _UserError as e:
                return _err(e.status, e.message)
        return _api(inner, mutating=mutating)

    async def plan_get(request: Request, user_id: str) -> Response:
        assert plans is not None
        return _plan_resp(user_id, plans.get(user_id))

    async def plan_setup(request: Request, user_id: str) -> Response:
        """The setup wizard's one save: profile, then the goal (new or updated), then
        build the plan. Each step validates before anything later runs."""
        assert plans is not None and chat is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        athlete, goal_in = body.get("athlete") or {}, body.get("goal") or {}
        if not isinstance(athlete, dict) or not isinstance(goal_in, dict):
            raise ValueError("body")
        coach = _coach()

        def run() -> tuple[dict[str, Any], dict[str, Any]]:
            start = body.get("start_date")
            if start is not None and not isinstance(start, str):
                raise PlanError("start_date must be YYYY-MM-DD")
            cur = coach.active_goal(user_id)
            new_goal = cur is None or body.get("new_goal") is True
            # Dry run first: validate everything and build the plan in memory, so a bad
            # answer saves nothing (no half-saved profile, no orphaned new goal).
            a_upd = coach.validate_athlete(athlete)
            g_upd = coach._validate_goal(goal_in, partial=not new_goal)
            try:
                first = date.fromisoformat(start) if start else None
            except ValueError:
                raise PlanError("Start date must be YYYY-MM-DD.") from None
            build_plan(coach.athlete(user_id) | a_upd, ({} if new_goal else dict(cur or {})) | g_upd,
                       today=plans.today(user_id), start=first)
            if athlete:
                coach.update_athlete(user_id, athlete)
            carried: list[int] = []
            if new_goal:
                if cur is not None:
                    carried = plans.release_garmin(user_id, cur["id"])
                coach.create_goal(user_id, goal_in)
            elif goal_in:
                coach.update_goal(user_id, cur["id"], goal_in)
            ev = body.get("event")
            chat.agent.events.upsert_from_goal(user_id, ev if isinstance(ev, dict) else None)
            plan = plans.build(user_id, start or None)
            plans.adopt_orphans(user_id, carried)
            return plans.get(user_id) or plan, coach.active_goal(user_id) or {}
        plan, goal = await _plan_call(run)
        return _plan_resp(user_id, plan, 201, goal=goal, athlete=coach.athlete(user_id))

    async def plan_rebuild(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        start = body.get("start_date") if isinstance(body, dict) else None
        plan = await _plan_call(lambda: plans.build(user_id, start if isinstance(start, str) else None))
        return _plan_resp(user_id, plan)

    async def plan_delete(request: Request, user_id: str) -> Response:
        assert plans is not None
        out = await _plan_call(lambda: plans.delete(user_id))
        return JSONResponse({"ok": True, **out})

    async def session_add(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        return _plan_resp(user_id, await _plan_call(lambda: plans.add_session(user_id, body)), 201)

    async def session_update(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        sid = request.path_params["session_id"]
        return _plan_resp(user_id, await _plan_call(lambda: plans.update_session(user_id, sid, body)))

    async def session_delete(request: Request, user_id: str) -> Response:
        assert plans is not None
        sid = request.path_params["session_id"]
        return _plan_resp(user_id, await _plan_call(lambda: plans.delete_session(user_id, sid)))

    async def plan_sync(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        days = body.get("days", 14) if isinstance(body, dict) else 14
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValueError("days")
        result = await _plan_call(lambda: plans.sync(user_id, days))
        return _plan_resp(user_id, plans.get(user_id), result=result)

    async def plan_unsync(request: Request, user_id: str) -> Response:
        assert plans is not None
        result = await _plan_call(lambda: plans.unsync(user_id))
        return _plan_resp(user_id, plans.get(user_id), result=result)

    # ------------------------------------------------------------- events --
    def _events():
        assert chat is not None
        return chat.agent.events

    def _events_resp(user_id: str, status: int = 200, **extra: Any) -> JSONResponse:
        return JSONResponse({"events": _events().list(user_id),
                             "types": {t: list(TYPE_DISTANCES[t]) for t in TYPES}, **extra},
                            status_code=status)

    async def events_list(request: Request, user_id: str) -> Response:
        await _plan_call(lambda: _events().list(user_id))
        return _events_resp(user_id)

    async def event_create(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        main = body.pop("main", False) is True

        def run() -> dict[str, Any]:
            ev = _events().create(user_id, body)
            return _events().set_main(user_id, ev["id"]) if main else ev
        ev = await _plan_call(run)
        return _events_resp(user_id, 201, event=ev)

    async def event_update(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        eid = request.path_params["event_id"]
        ev = await _plan_call(lambda: _events().update(user_id, eid, body))
        return _events_resp(user_id, event=ev)

    async def event_delete(request: Request, user_id: str) -> Response:
        eid = request.path_params["event_id"]
        await _plan_call(lambda: _events().delete(user_id, eid))
        return _events_resp(user_id)

    async def event_main(request: Request, user_id: str) -> Response:
        eid = request.path_params["event_id"]
        ev = await _plan_call(lambda: _events().set_main(user_id, eid))
        return _events_resp(user_id, event=ev)

    async def event_debrief(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        feel = body.get("feel")
        try:
            out = await chat.agent.debrief(
                user_id, request.path_params["event_id"],
                result=body.get("result") if isinstance(body.get("result"), str) else None,
                feel=feel if isinstance(feel, int) and not isinstance(feel, bool) else None,
                notes=body.get("notes") if isinstance(body.get("notes"), str) else None)
        except CoachError as e:
            raise _UserError(str(e)) from None
        except Exception as e:
            log_event(logger, logging.WARNING, "debrief_failed", user_id=user_id, error=type(e).__name__)
            raise _UserError("The debrief didn't work just now. Try again in a minute.", 502) from None
        return _events_resp(user_id, debrief=out)

    async def event_lookup(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        args = {k: body.get(k) if isinstance(body.get(k), str) else None
                for k in ("name", "type", "date", "location")}
        try:
            info = await chat.agent.lookup_event(user_id, args["name"] or "", args["type"],
                                                 args["date"], args["location"])
        except CoachError as e:
            raise _UserError(str(e)) from None
        except Exception as e:  # model/API trouble: say so plainly
            log_event(logger, logging.WARNING, "event_lookup_failed", user_id=user_id,
                      error=type(e).__name__)
            raise _UserError("The lookup didn't work just now. Try again in a minute.", 502) from None
        eid = body.get("event_id")
        if isinstance(eid, str) and eid:
            await _plan_call(lambda: _events().update(user_id, eid, {"info": info}))
        return JSONResponse({"info": info})

    async def load_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.load(user_id)))

    async def coach_athlete_load(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.load(aid)))

    async def stats_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        fresh = request.query_params.get("fresh") == "1"
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.get(user_id, fresh=fresh)))

    # ------------------------------------------------------------- coaches --
    links = auth.coach_links

    def _session_ref(aid: str, sid: Any) -> dict[str, Any] | None:
        if not isinstance(sid, str) or not sid or plans is None:
            return None
        plan = plans.get(aid)
        for _, day, x in iter_sessions(plan) if plan else []:
            if x["id"] == sid:
                return {"id": sid, "date": day, "title": x["title"]}
        raise CoachError("That session isn't in the plan anymore.")

    def _notify(to_user: str | None, title: str, body: str) -> None:
        if push is None or not to_user:
            return
        try:
            push.send(to_user, title, body[:140], url="/app/")
        except Exception as e:  # notifications are best effort
            log_event(logger, logging.WARNING, "coach_push_failed", error=type(e).__name__)

    def _coach_view(link: dict[str, Any]) -> dict[str, Any]:
        return {k: link.get(k) for k in ("email", "status", "can_edit_plan", "can_see_rabbit_chats",
                                         "invited_at", "accepted_at")}

    # Athlete side: manage coaches, message them, read shared notes.
    async def coaches_get(request: Request, user_id: str) -> Response:
        return JSONResponse({"coaches": [_coach_view(c) for c in links.coaches_of(user_id)],
                             "unread": coach_chat.unread(user_id, "athlete")})

    async def coach_invite(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        await _plan_call(lambda: links.invite(user_id, body.get("email", ""),
                                              can_edit_plan=body.get("can_edit_plan", True) is True,
                                              can_see_rabbit_chats=body.get("can_see_rabbit_chats") is True))
        return JSONResponse({"coaches": [_coach_view(c) for c in links.coaches_of(user_id)]}, status_code=201)

    async def coach_patch(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        await _plan_call(lambda: links.update(user_id, request.path_params["email"], body))
        return JSONResponse({"coaches": [_coach_view(c) for c in links.coaches_of(user_id)]})

    async def coach_remove(request: Request, user_id: str) -> Response:
        await _plan_call(lambda: links.remove(user_id, request.path_params["email"]))
        return JSONResponse({"coaches": [_coach_view(c) for c in links.coaches_of(user_id)]})

    def _my_coach(user_id: str, email: Any) -> dict[str, Any]:
        e = str(email or "").strip().lower()
        for c in links.coaches_of(user_id):
            if c["email"] == e:
                return c
        raise CoachError("coach not found")

    async def athlete_threads(request: Request, user_id: str) -> Response:
        return JSONResponse({"threads": coach_chat.threads(user_id),
                             "coaches": [_coach_view(c) for c in links.coaches_of(user_id)]})

    async def athlete_thread_open(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            c = _my_coach(user_id, body.get("coach"))
            return coach_chat.open_thread(user_id, c["email"], session=_session_ref(user_id, body.get("session_id")))
        return JSONResponse({"thread": await _plan_call(run)}, status_code=201)

    async def athlete_thread_get(request: Request, user_id: str) -> Response:
        tid = request.path_params["thread_id"]

        def run() -> dict[str, Any]:
            t = coach_chat.thread(user_id, tid)
            coach_chat.mark_read(user_id, tid, "athlete")
            return t
        return JSONResponse({"thread": await _plan_call(run)})

    async def athlete_thread_post(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        tid = request.path_params["thread_id"]
        msg = await _plan_call(lambda: coach_chat.post(user_id, tid, sender="athlete", text=body.get("text")))
        t = coach_chat.thread(user_id, tid)
        link = next((c for c in links.coaches_of(user_id) if c["email"] == t["coach"]), None)
        _notify((link or {}).get("coach_user_id"), f"{auth.profile(user_id).get('name') or 'Your athlete'}",
                msg["text"])
        return JSONResponse({"message": msg}, status_code=201)

    async def athlete_notes(request: Request, user_id: str) -> Response:
        return JSONResponse({"notes": coach_notes.list(user_id, shared_only=True)})

    # Coach side: everything goes through links.require(coach, athlete).
    def _aid(request: Request) -> str:
        return str(request.path_params["athlete_id"])

    async def coach_athletes(request: Request, user_id: str) -> Response:
        out = []
        for link in links.athletes_of(user_id):
            aid = link["athlete_id"]
            goal = _coach().active_goal(aid) if chat else None
            out.append({"athlete_id": aid, "profile": auth.profile(aid), **_coach_view(link),
                        "goal": {k: goal.get(k) for k in ("title", "date", "distance")} if goal else None,
                        "unread": coach_chat.unread(aid, "coach", coach=link["email"])})
        return JSONResponse({"athletes": out})

    async def coach_athlete(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        link = await _plan_call(lambda: links.require(user_id, aid))
        coach = _coach()
        return JSONResponse({
            "athlete_id": aid, "profile": auth.profile(aid), "link": _coach_view(link),
            "athlete": coach.athlete(aid), "goal": coach.active_goal(aid),
            "events": chat.agent.events.list(aid) if chat else [],
            "notes": coach_notes.list(aid, coach=link["email"]),
            "unread": coach_chat.unread(aid, "coach", coach=link["email"]),
        })

    async def coach_athlete_stats(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.get(aid)))

    async def coach_plan_get(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        assert plans is not None
        return JSONResponse({"plan": public_plan(plans.get(aid), plans.today(aid))})

    async def coach_session_add(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        assert plans is not None

        def run() -> dict[str, Any]:
            links.require(user_id, aid, perm="can_edit_plan")
            return plans.add_session(aid, body)
        plan = await _plan_call(run)
        return JSONResponse({"plan": public_plan(plan, plans.today(aid))}, status_code=201)

    async def coach_session_update(request: Request, user_id: str) -> Response:
        aid, sid = _aid(request), request.path_params["session_id"]
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        assert plans is not None

        def run() -> dict[str, Any]:
            links.require(user_id, aid, perm="can_edit_plan")
            return plans.update_session(aid, sid, body)
        return JSONResponse({"plan": public_plan(await _plan_call(run), plans.today(aid))})

    async def coach_session_delete(request: Request, user_id: str) -> Response:
        aid, sid = _aid(request), request.path_params["session_id"]
        assert plans is not None

        def run() -> dict[str, Any]:
            links.require(user_id, aid, perm="can_edit_plan")
            return plans.delete_session(aid, sid)
        return JSONResponse({"plan": public_plan(await _plan_call(run), plans.today(aid))})

    async def coach_threads(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        link = await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse({"threads": coach_chat.threads(aid, coach=link["email"])})

    async def coach_thread_open(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            return coach_chat.open_thread(aid, link["email"], session=_session_ref(aid, body.get("session_id")))
        return JSONResponse({"thread": await _plan_call(run)}, status_code=201)

    async def coach_thread_get(request: Request, user_id: str) -> Response:
        aid, tid = _aid(request), request.path_params["thread_id"]

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            t = coach_chat.thread(aid, tid, coach=link["email"])
            coach_chat.mark_read(aid, tid, "coach", coach=link["email"])
            return t
        return JSONResponse({"thread": await _plan_call(run)})

    async def coach_thread_post(request: Request, user_id: str) -> Response:
        aid, tid = _aid(request), request.path_params["thread_id"]
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            return coach_chat.post(aid, tid, sender="coach", text=body.get("text"), coach=link["email"])
        msg = await _plan_call(run)
        _notify(aid, f"{auth.profile(user_id).get('name') or 'Your coach'}", msg["text"])
        return JSONResponse({"message": msg}, status_code=201)

    async def coach_note_add(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            return coach_notes.add(aid, link["email"], body.get("text"), shared=body.get("shared", True) is True,
                                   pinned=body.get("pinned") is True)
        return JSONResponse({"note": await _plan_call(run)}, status_code=201)

    async def coach_note_update(request: Request, user_id: str) -> Response:
        aid, nid = _aid(request), request.path_params["note_id"]
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            return coach_notes.update(aid, link["email"], nid, body)
        return JSONResponse({"note": await _plan_call(run)})

    async def coach_note_delete(request: Request, user_id: str) -> Response:
        aid, nid = _aid(request), request.path_params["note_id"]

        def run() -> None:
            link = links.require(user_id, aid)
            coach_notes.delete(aid, link["email"], nid)
        await _plan_call(run)
        return JSONResponse({"ok": True})

    async def coach_rabbit_threads(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid, perm="can_see_rabbit_chats"))
        return JSONResponse({"threads": [_thread_view(t) for t in _coach().threads(aid)]})

    async def coach_rabbit_messages(request: Request, user_id: str) -> Response:
        aid, tid = _aid(request), request.path_params["thread_id"]
        await _plan_call(lambda: links.require(user_id, aid, perm="can_see_rabbit_chats"))
        thread = _coach().get_thread(aid, tid)
        if thread is None:
            return _err(404, "thread not found")
        keys = ("id", "ts", "kind", "label", "user", "parts")
        turns = _coach().turns(aid, tid)[-60:]
        return JSONResponse({"thread": _thread_view(thread),
                             "turns": [{k: t.get(k) for k in keys if k in t} for t in turns]})

    # ------------------------------------------------- calendar / travel --
    async def calendar_get(request: Request, user_id: str) -> Response:
        cal = auth.calendar
        if cal is None or not cal.connected(user_id):
            return JSONResponse({"connected": False, "available": cal is not None})
        try:
            days = int(request.query_params.get("days", "42"))
        except ValueError:
            days = 42
        today = plans.today(user_id) if plans else date.today()
        prof = store.user_doc(user_id, "profile").load() if store else {}
        tz = prof.get("timezone") or default_tz
        try:
            return JSONResponse(await cal.summary(user_id, today, days, tz) | {"available": True})
        except CalendarNotConnected as e:
            return JSONResponse({"connected": False, "available": True, "error": str(e)})
        except CalendarError as e:
            return _err(502, str(e))

    async def calendar_delete(request: Request, user_id: str) -> Response:
        if auth.calendar is not None:
            await auth.calendar.disconnect(user_id)
        return JSONResponse({"connected": False})

    async def calendar_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        return await auth.start_calendar(request)

    async def oura_get(request: Request, user_id: str) -> Response:
        o = auth.oura
        if o is None or not o.connected(user_id):
            return JSONResponse({"connected": False, "available": o is not None})
        try:
            days = int(request.query_params.get("days", "28"))
        except ValueError:
            days = 28
        today = plans.today(user_id) if plans else date.today()
        try:
            return JSONResponse(await o.recovery(user_id, today, days) | {"available": True})
        except OuraNotConnected as e:
            return JSONResponse({"connected": False, "available": True, "error": str(e)})
        except OuraError as e:
            return _err(502, str(e))

    async def oura_delete(request: Request, user_id: str) -> Response:
        if auth.oura is not None:
            auth.oura.disconnect(user_id)
        return JSONResponse({"connected": False})

    async def oura_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        return await auth.start_oura(request)

    async def oura_callback(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        return await auth.oura_callback(request)

    async def _proposal(user_id: str) -> dict[str, Any]:
        assert plans is not None and chat is not None
        plan = plans.get(user_id)
        if plan is None:
            return {"status": "none"}
        today, acts = await _plan_call(lambda: chat.agent.stats.activities(user_id))
        recovery = None
        if auth.oura is not None and auth.oura.connected(user_id):
            try:
                recovery = await auth.oura.recovery(user_id, today, 28)
            except OuraError:
                recovery = None
        load_now = (await _plan_call(lambda: chat.agent.stats.load(user_id))).get("now") or {}
        return propose_adjustment(plan, acts, today, recovery=recovery, tsb=load_now.get("tsb"),
                                  dismissed=plan.get("adjust_dismissed"))

    async def adjust_get(request: Request, user_id: str) -> Response:
        return JSONResponse(await _proposal(user_id))

    async def adjust_post(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict) or body.get("action") not in ("apply", "dismiss"):
            raise ValueError("body")
        prop = await _proposal(user_id)
        if prop.get("id") != body.get("id"):
            return _err(409, "Your plan changed since this suggestion. Take another look.")
        if body["action"] == "dismiss":
            await _plan_call(lambda: plans.dismiss_adjustment(user_id, prop["id"]))
            return _plan_resp(user_id, plans.get(user_id), applied=0)
        plan = await _plan_call(lambda: plans.apply_adjustment(user_id, prop["changes"]))
        return _plan_resp(user_id, plan, applied=len(prop["changes"]))

    async def racepack_get(request: Request, user_id: str) -> Response:
        assert chat is not None and plans is not None
        eid = request.query_params.get("event_id") or None

        def pick() -> dict[str, Any]:
            ev = chat.agent.events
            if eid:
                return ev.get(user_id, eid)
            main = next((e for e in ev.list(user_id) if e["main"]), None)
            if main is None:
                raise CoachError("Add your race in Events first.")
            return main
        event = await _plan_call(pick)
        today = plans.today(user_id)
        wx = await racepack.forecast(event.get("location") or "", date.fromisoformat(event["date"]), today)
        athlete = _coach().athlete(user_id)
        return JSONResponse(racepack.build(event, athlete, plans.get(user_id) if event.get("main") else None, today, wx))

    async def travel_add(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        return _plan_resp(user_id, await _plan_call(lambda: plans.add_travel(user_id, body)), 201)

    async def travel_remove(request: Request, user_id: str) -> Response:
        assert plans is not None
        tid = request.path_params["trip_id"]
        return _plan_resp(user_id, await _plan_call(lambda: plans.remove_travel(user_id, tid)))

    # -------------------------------------------------------------- share --
    shares = Shares(store) if store is not None else None

    def _share_url(token: str | None) -> str | None:
        return f"{settings.public_base_url.rstrip('/')}/app/s/{token}" if token else None

    async def share_get(request: Request, user_id: str) -> Response:
        assert shares is not None
        return JSONResponse({"url": _share_url(shares.current(user_id))})

    async def share_create(request: Request, user_id: str) -> Response:
        assert shares is not None
        return JSONResponse({"url": _share_url(shares.create(user_id))}, status_code=201)

    async def share_delete(request: Request, user_id: str) -> Response:
        assert shares is not None
        shares.revoke(user_id)
        return JSONResponse({"url": None})

    async def share_page(request: Request) -> Response:
        headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
                   "Referrer-Policy": "no-referrer",
                   "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}
        if not host_ok(request) or shares is None or chat is None or plans is None:
            return HTMLResponse("Not found", status_code=404, headers=headers)
        uid = shares.resolve(request.path_params["token"])
        if uid is None:
            return HTMLResponse("This link isn't active anymore.", status_code=404, headers=headers)
        page = render_share(auth.profile(uid).get("name", ""), _coach().active_goal(uid),
                            chat.agent.events.list(uid), plans.get(uid), plans.today(uid))
        return HTMLResponse(page, headers=headers)

    async def garmin_numbers(request: Request, user_id: str) -> Response:
        assert plans is not None
        return JSONResponse({"numbers": await _plan_call(lambda: plans.garmin_numbers(user_id))})

    # --------------------------------------------------------------- auth --
    async def google_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        return await auth.start(request)

    async def google_callback(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        return await auth.callback(request)

    async def logout(request: Request) -> Response:
        if not host_ok(request) or not auth.check_origin(request):
            return _err(403, "bad origin")
        resp = JSONResponse({"ok": True})
        auth.logout(request, resp)
        return resp

    async def app_root(request: Request) -> Response:
        return RedirectResponse("/app/", status_code=308)

    async def not_built(request: Request) -> Response:
        return Response("Frontend not built: run `bun run build` in web/.", status_code=503,
                        media_type="text/plain")

    routes: list[BaseRoute] = [
        Route("/app", app_root, methods=["GET"]),
        Route("/app/auth/google/start", google_start, methods=["GET"]),
        Route("/app/auth/google/callback", google_callback, methods=["GET"]),
        Route("/app/auth/logout", logout, methods=["POST"]),
        Route("/app/api/me", _api(me, mutating=False), methods=["GET"]),
        Route("/app/api/push/subscribe", _api(push_subscribe, mutating=True), methods=["POST"]),
        Route("/app/api/push/unsubscribe", _api(push_unsubscribe, mutating=True),
              methods=["POST"]),
        Route("/app/api/push/test", _api(push_test, mutating=True), methods=["POST"]),
        Route("/app/api/settings", _api(put_settings, mutating=True), methods=["PUT"]),
        Route("/app/api/dev/{name}", _api(dev_action, mutating=True), methods=["POST"]),
        Route("/app/api/chat", _api(chat_send, mutating=True), methods=["POST"]),
        Route("/app/api/chat/{turn_id}/events", _api(chat_events, mutating=False),
              methods=["GET"]),
        Route("/app/api/chat/{turn_id}/cancel", _api(chat_cancel, mutating=True),
              methods=["POST"]),
        Route("/app/api/chat/{turn_id}/approval", _api(chat_approval, mutating=True),
              methods=["POST"]),
        Route("/app/api/attachments", attachment_upload, methods=["POST"]),
        Route("/app/api/attachments/{att_id}", _api(attachment_get, mutating=False),
              methods=["GET"]),
        Route("/app/api/threads", _api(threads_list, mutating=False), methods=["GET"]),
        Route("/app/api/threads", _api(thread_create, mutating=True), methods=["POST"]),
        Route("/app/api/threads/{thread_id}", _api(thread_update, mutating=True),
              methods=["PATCH"]),
        Route("/app/api/threads/{thread_id}", _api(thread_delete, mutating=True),
              methods=["DELETE"]),
        Route("/app/api/threads/{thread_id}/messages", _api(messages, mutating=False),
              methods=["GET"]),
        Route("/app/api/goals", _api(goals_get, mutating=False), methods=["GET"]),
        Route("/app/api/goals", _api(goal_create, mutating=True), methods=["POST"]),
        Route("/app/api/goals/{goal_id}", _api(goal_update, mutating=True), methods=["PATCH"]),
        Route("/app/api/goals/{goal_id}/archive", _api(goal_archive, mutating=True),
              methods=["POST"]),
        Route("/app/api/plan/week", _api(plan_week_get, mutating=False), methods=["GET"]),
        Route("/app/api/athlete", _api(athlete_put, mutating=True), methods=["PUT"]),
        Route("/app/api/plan", _plan_api(plan_get, mutating=False), methods=["GET"]),
        Route("/app/api/plan", _plan_api(plan_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/plan/setup", _plan_api(plan_setup, mutating=True), methods=["POST"]),
        Route("/app/api/plan/rebuild", _plan_api(plan_rebuild, mutating=True), methods=["POST"]),
        Route("/app/api/plan/sessions", _plan_api(session_add, mutating=True), methods=["POST"]),
        Route("/app/api/plan/sessions/{session_id}", _plan_api(session_update, mutating=True),
              methods=["PATCH"]),
        Route("/app/api/plan/sessions/{session_id}", _plan_api(session_delete, mutating=True),
              methods=["DELETE"]),
        Route("/app/api/plan/garmin/sync", _plan_api(plan_sync, mutating=True), methods=["POST"]),
        Route("/app/api/plan/garmin/remove", _plan_api(plan_unsync, mutating=True),
              methods=["POST"]),
        Route("/app/api/events", _plan_api(events_list, mutating=False), methods=["GET"]),
        Route("/app/api/events", _plan_api(event_create, mutating=True), methods=["POST"]),
        Route("/app/api/events/lookup", _plan_api(event_lookup, mutating=True), methods=["POST"]),
        Route("/app/api/events/{event_id}", _plan_api(event_update, mutating=True),
              methods=["PATCH"]),
        Route("/app/api/events/{event_id}", _plan_api(event_delete, mutating=True),
              methods=["DELETE"]),
        Route("/app/api/events/{event_id}/debrief", _plan_api(event_debrief, mutating=True),
              methods=["POST"]),
        Route("/app/api/events/{event_id}/main", _plan_api(event_main, mutating=True),
              methods=["POST"]),
        Route("/app/api/stats", _plan_api(stats_get, mutating=False), methods=["GET"]),
        Route("/app/api/load", _plan_api(load_get, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/load", _plan_api(coach_athlete_load, mutating=False),
              methods=["GET"]),
        Route("/app/api/calendar", _plan_api(calendar_get, mutating=False), methods=["GET"]),
        Route("/app/api/calendar", _plan_api(calendar_delete, mutating=True), methods=["DELETE"]),
        Route("/app/auth/calendar/start", calendar_start, methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_get, mutating=False), methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_delete, mutating=True), methods=["DELETE"]),
        Route("/app/auth/oura/start", oura_start, methods=["GET"]),
        Route("/app/auth/oura/callback", oura_callback, methods=["GET"]),
        Route("/app/api/plan/travel", _plan_api(travel_add, mutating=True), methods=["POST"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_get, mutating=False), methods=["GET"]),
        Route("/app/api/racepack", _plan_api(racepack_get, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_get, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_create, mutating=True), methods=["POST"]),
        Route("/app/api/share", _plan_api(share_delete, mutating=True), methods=["DELETE"]),
        Route("/app/s/{token}", share_page, methods=["GET"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_post, mutating=True), methods=["POST"]),
        Route("/app/api/plan/travel/{trip_id}", _plan_api(travel_remove, mutating=True), methods=["DELETE"]),
        Route("/app/api/coaches", _plan_api(coaches_get, mutating=False), methods=["GET"]),
        Route("/app/api/coaches", _plan_api(coach_invite, mutating=True), methods=["POST"]),
        Route("/app/api/coaches/{email}", _plan_api(coach_patch, mutating=True), methods=["PATCH"]),
        Route("/app/api/coaches/{email}", _plan_api(coach_remove, mutating=True), methods=["DELETE"]),
        Route("/app/api/coachchat", _plan_api(athlete_threads, mutating=False), methods=["GET"]),
        Route("/app/api/coachchat", _plan_api(athlete_thread_open, mutating=True), methods=["POST"]),
        Route("/app/api/coachchat/{thread_id}", _plan_api(athlete_thread_get, mutating=False), methods=["GET"]),
        Route("/app/api/coachchat/{thread_id}/messages", _plan_api(athlete_thread_post, mutating=True),
              methods=["POST"]),
        Route("/app/api/coachnotes", _plan_api(athlete_notes, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes", _plan_api(coach_athletes, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}", _plan_api(coach_athlete, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/stats", _plan_api(coach_athlete_stats, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/plan", _plan_api(coach_plan_get, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/plan/sessions", _plan_api(coach_session_add, mutating=True), methods=["POST"]),
        Route("/app/api/coach/athletes/{athlete_id}/plan/sessions/{session_id}", _plan_api(coach_session_update, mutating=True),
              methods=["PATCH"]),
        Route("/app/api/coach/athletes/{athlete_id}/plan/sessions/{session_id}", _plan_api(coach_session_delete, mutating=True),
              methods=["DELETE"]),
        Route("/app/api/coach/athletes/{athlete_id}/chat", _plan_api(coach_threads, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/chat", _plan_api(coach_thread_open, mutating=True), methods=["POST"]),
        Route("/app/api/coach/athletes/{athlete_id}/chat/{thread_id}", _plan_api(coach_thread_get, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/chat/{thread_id}/messages", _plan_api(coach_thread_post, mutating=True), methods=["POST"]),
        Route("/app/api/coach/athletes/{athlete_id}/notes", _plan_api(coach_note_add, mutating=True), methods=["POST"]),
        Route("/app/api/coach/athletes/{athlete_id}/notes/{note_id}", _plan_api(coach_note_update, mutating=True), methods=["PATCH"]),
        Route("/app/api/coach/athletes/{athlete_id}/notes/{note_id}", _plan_api(coach_note_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/coach/athletes/{athlete_id}/rabbit", _plan_api(coach_rabbit_threads, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/rabbit/{thread_id}", _plan_api(coach_rabbit_messages, mutating=False), methods=["GET"]),
        Route("/app/api/garmin/numbers", _plan_api(garmin_numbers, mutating=False),
              methods=["GET"]),
        Route("/app/api/garmin/login", _api(garmin_login, mutating=True), methods=["POST"]),
        Route("/app/api/garmin/login/{job_id}", _api(garmin_login_status, mutating=False),
              methods=["GET"]),
        Route("/app/api/garmin/mfa", _api(garmin_mfa, mutating=True), methods=["POST"]),
        Route("/app/api/garmin/disconnect", _api(garmin_disconnect, mutating=True),
              methods=["POST"]),
    ]
    if (WEB_DIST / "index.html").is_file():
        async def index(request: Request) -> Response:
            # Read per request: the dev build rewrites it on save.
            html = (WEB_DIST / "index.html").read_text().replace(
                "__RABBIT_ORIGIN__", settings.public_base_url)
            return HTMLResponse(html, headers={"Cache-Control": "no-cache",
                                               "Content-Security-Policy": CSP})
        routes += [Route("/app/", index, methods=["GET", "HEAD"]),
                   Route("/app/index.html", index, methods=["GET", "HEAD"]),
                   Mount("/app", app=_Static(directory=WEB_DIST, html=True))]
    else:
        routes.append(Route("/app/{path:path}", not_built, methods=["GET"]))
    return routes
