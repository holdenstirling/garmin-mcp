"""HTTP routes for the Rabbit web app, mounted under /app on the MCP server's app.

Every /app/api route goes through ``_api``: Host check, session -> user_id
(never from the request body), Origin + JSON content-type check on mutating
calls, a body size cap, and a generic error for anything unexpected.
"""

from __future__ import annotations

import json
import logging
import re
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
from .planbuilder import PlanError
from .plans import public_plan
from .events import TYPE_DISTANCES, TYPES
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
            if athlete:
                coach.update_athlete(user_id, athlete)
            cur = coach.active_goal(user_id)
            if cur is None or body.get("new_goal") is True:
                coach.create_goal(user_id, goal_in)
            elif goal_in:
                coach.update_goal(user_id, cur["id"], goal_in)
            start = body.get("start_date")
            if start is not None and not isinstance(start, str):
                raise PlanError("start_date must be YYYY-MM-DD")
            ev = body.get("event")
            chat.agent.events.upsert_from_goal(user_id, ev if isinstance(ev, dict) else None)
            return plans.build(user_id, start or None), coach.active_goal(user_id) or {}
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
        Route("/app/api/events/{event_id}/main", _plan_api(event_main, mutating=True),
              methods=["POST"]),
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
