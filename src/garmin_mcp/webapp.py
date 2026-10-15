"""HTTP routes for the Rabbit web app, mounted under /app on the MCP server's app.

Every /app/api route goes through ``_api``: Host check, session -> user_id
(never from the request body), Origin + JSON content-type check on mutating
calls, a body size cap, and a generic error for anything unexpected.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import re
import secrets
import threading
import time
from datetime import date, datetime
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
from . import planimport_web
from .planimport import ImportService
from .events import KINDS, TYPE_DISTANCES, TYPES
from .events import MAIN_KINDS as _EV_MAIN_KINDS
from .events import is_race as _ev_is_race
from .coaches import CoachChat, CoachNotes
from .gcalendar import CalendarError, CalendarNotConnected
from .oura import OuraError, OuraNotConnected
from .sources import garmin_recovery, prefs_for, recovery_for, validate as validate_sources
from .adjust import propose as propose_adjustment
from . import racefit, racepack
from .profilephoto import MAX_PHOTO, PhotoError, PhotoStore
from .share import Shares
from .share import render as render_share
from . import legal
from .planbuilder import iter_sessions
from .checkins import XP as CHECKIN_XP, CheckinError, xp_bonus as checkin_xp_bonus
from .gear import GearStore, catalog as gear_catalog, usage as gear_usage
from . import intent as intent_mod
from .progress import GEAR_XP, quests_view, week_goal
from .stats import compute as stats_compute
from .recap import RecapError, RecapService
from .sync import LiveSync
from .moments import completed_challenges
from .today import TodayService
from .providers import GarminError, ReauthRequired
from .tokens import TokenStore, TokenStoreError
from .webauth import WebAuth
from .webchat import ChatRunner, Turn, TurnBusy
from .webpush import WebPush, parse_subscription

logger = logging.getLogger(__name__)
# The only API paths a coach-only account (not an allowlisted athlete) may call.
COACH_PATHS = ("/app/api/me", "/app/api/coach/", "/app/api/push/")
# Goal fields a coach always sees; the athlete's private notes and Rabbit's plan for the goal
# only with ``can_see_rabbit_chats``.
COACH_GOAL_FIELDS = ("id", "title", "date", "distance", "type", "goal_type", "target_time", "priority",
                     "location", "status", "created")
COACH_GOAL_PRIVATE = ("notes", "plan")
COACH_EVENT_PRIVATE = ("notes", "debrief", "plan", "strategy")  # same rule for events on the calendar
PUSH_THREAD_INTERVAL = 60   # at most one coach-chat push per thread per minute
PUSH_TEST_PER_HOUR = 5


def _is_coach_account(user_id: str | None) -> bool:
    return bool(user_id and user_id.startswith("coach_"))


def coach_goal_view(goal: dict[str, Any] | None, link: dict[str, Any]) -> dict[str, Any] | None:
    if not goal:
        return None
    keys = COACH_GOAL_FIELDS + (COACH_GOAL_PRIVATE if link.get("can_see_rabbit_chats") else ())
    return {k: goal[k] for k in keys if k in goal}


def coach_event_view(event: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
    if link.get("can_see_rabbit_chats"):
        return event
    return {k: v for k, v in event.items() if k not in COACH_EVENT_PRIVATE}

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
    push_times: dict[str, list[float]] = {}  # rate-limit key -> recent push send times

    def push_allowed(key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        recent = [t for t in push_times.get(key, []) if now - t < window]
        if len(recent) >= limit:
            push_times[key] = recent
            return False
        push_times[key] = recent + [now]
        return True

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
            if user_id.startswith("coach_") and not request.url.path.startswith(COACH_PATHS):
                return _err(403, "Coach accounts can only use the coach view.")
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
        active = chat.active(user_id) if chat else None
        return JSONResponse({
            "user_id": user_id,
            "role": "coach" if user_id.startswith("coach_") else "athlete",
            "can_invite": auth.can_invite(user_id),
            "coaching": len(auth.coach_links.athletes_of(user_id)),
            "coaches": len(auth.coach_links.coaches_of(user_id)),
            "oura": {"available": auth.oura is not None,
                     "connected": bool(auth.oura and auth.oura.connected(user_id))},
            "calendar": {"available": auth.calendar is not None,
                         "connected": bool(auth.calendar and auth.calendar.connected(user_id))},
            "coach_unread": coach_chat.unread(user_id, "athlete")
            if coach_chat is not None and not user_id.startswith("coach_") else 0,
            "profile": auth.profile(user_id),
            "photo": _photo_version(user_id),
            "settings": _settings_view(user_id),
            "dev": {"fake_garmin": fake_garmin, "tools": sorted(dev) if dev else []},
            "athlete": chat.agent.coach.athlete(user_id) if chat else {},
            "goal": chat.agent.coach.active_goal(user_id) if chat else None,
            "welcome": _welcome(user_id, connected),  # intent.py: "full" | "lite" | None
            "chat": {"available": chat is not None,
                     "active_turn": active.id if active else None,
                     "active_thread": (active.thread_id or None) if active else None},
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
        if not push_allowed(f"test:{user_id}", PUSH_TEST_PER_HOUR, 3600):
            return _err(429, "Too many test notifications. Try again in an hour.")
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
        if _is_coach_account(user_id):
            return _err(403, "Coach accounts can only use the coach view.")
        if atts is None:
            return _err(503, "Chat isn't configured on this server.")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            return _err(400, "bad request")
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
                "recap_enabled": p.get("recap_enabled", True),
                "moments_push": p.get("moments_push", True) is not False,
                "has_notes": bool(p.get("notes")),
                # sources.py: workouts always Garmin; recovery/sleep Garmin or Oura.
                "data_sources": prefs_for(store, user_id, bool(auth.oura and auth.oura.connected(user_id)))[0]
                if store else {"workouts": "garmin", "recovery": "garmin", "sleep": "garmin", "show_both": False},
                "data_sources_asked": p.get("data_sources_asked", False) is True}

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
        for key in ("brief_enabled", "workout_feedback", "recap_enabled", "data_sources_asked", "moments_push"):
            if key in body:
                if not isinstance(body[key], bool):
                    return _err(400, f"{key} must be true or false")
                upd[key] = body[key]
        sources_patch: dict[str, Any] | None = None
        if "data_sources" in body:
            try:
                sources_patch = validate_sources(body["data_sources"])
            except ValueError as e:
                return _err(400, str(e))

        def apply(p: dict[str, Any]) -> None:
            p.update(upd)
            if sources_patch is not None:
                cur = p.get("data_sources") if isinstance(p.get("data_sources"), dict) else {}
                p["data_sources"] = {**cur, **sources_patch}
        store.user_doc(user_id, "profile").update(apply)
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
            return JSONResponse(chat.agent.plans.switch_goal(user_id, lambda: _coach().create_goal(user_id, body)),
                                status_code=201)
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
            chat.agent.plans.switch_goal(user_id, lambda: _coach().archive_goal(user_id, request.path_params["goal_id"]))
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

    # ------------------------------------------- intent ("What brings you to Rabbit?") --
    # intent.py: athlete.intents (priority order) + welcomed_at (shown once; skip counts).
    def _welcome(uid: str, garmin_connected: bool) -> str | None:
        if chat is None or _is_coach_account(uid):
            return None
        a = chat.agent.coach.athlete(uid)
        return intent_mod.welcome_mode(a, existing=intent_mod.is_existing(
            a, garmin_connected=garmin_connected, has_goal=chat.agent.coach.active_goal(uid) is not None))

    def _intent_view(uid: str, a: dict[str, Any]) -> dict[str, Any]:
        try:
            connected = token_store.load(uid) is not None
        except TokenStoreError:
            connected = False
        return {"intents": intent_mod.clean(a.get("intents")), "welcomed_at": a.get("welcomed_at"),
                "welcome": _welcome(uid, connected), "options": intent_mod.options()}

    async def intent_get(request: Request, user_id: str) -> Response:
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        return JSONResponse(_intent_view(user_id, chat.agent.coach.athlete(user_id)))

    async def intent_post(request: Request, user_id: str) -> Response:
        """{intents: [...]} saves the answer; {skip: true} only marks the welcome as seen."""
        if chat is None or store is None:
            return _err(503, "Chat isn't configured on this server.")
        body = await read_json(request)
        if not isinstance(body, dict) or set(body) - {"intents", "skip"}:
            raise ValueError("body")
        skip = body.get("skip") is True
        if not skip and "intents" not in body:
            return _err(400, "Pick at least one, or skip for now.")
        try:
            a = await anyio.to_thread.run_sync(lambda: intent_mod.save(store, user_id, body.get("intents"), skip=skip))
        except CoachError as e:
            return _err(400, str(e))
        return JSONResponse(_intent_view(user_id, a))

    intent_routes = [
        Route("/app/api/intent", _api(intent_get, mutating=False), methods=["GET"]),
        Route("/app/api/intent", _api(intent_post, mutating=True), methods=["POST"]),
    ]

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
            ev = body.get("event")
            ev = ev if isinstance(ev, dict) else None
            chat.agent.events.validate_extra(ev)
            try:
                first = date.fromisoformat(start) if start else None
            except ValueError:
                raise PlanError("Start date must be YYYY-MM-DD.") from None
            build_plan(coach.athlete(user_id) | a_upd, ({} if new_goal else dict(cur or {})) | g_upd,
                       today=plans.today(user_id), start=first)
            if athlete:
                coach.update_athlete(user_id, athlete)
            if new_goal:
                # The old plan's Garmin workouts are handed over (or parked until the
                # build) right away, so a later failure can't strand them.
                plans.switch_goal(user_id, lambda: coach.create_goal(user_id, goal_in))
            elif goal_in:
                coach.update_goal(user_id, cur["id"], goal_in)
            chat.agent.events.upsert_from_goal(user_id, ev)
            plan = plans.build(user_id, start or None)
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
                             "types": {t: list(TYPE_DISTANCES[t]) for t in TYPES}, "kinds": list(KINDS), **extra},
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
            if main and body.get("kind") not in (None, "", *_EV_MAIN_KINDS):
                raise CoachError("Only a race or a challenge can be your main event.")
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
        if (empty := _no_garmin(user_id)) is not None:
            return empty
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.load(user_id)))

    async def coach_athlete_load(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.load(aid)))

    async def stats_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        if (empty := _no_garmin(user_id)) is not None:
            return empty
        fresh = request.query_params.get("fresh") == "1"
        return JSONResponse(await _plan_call(lambda: chat.agent.stats.get(user_id, fresh=fresh)))

    def _quest_state(user_id: str) -> tuple[dict[str, bool], dict[str, bool]]:
        assert chat is not None
        try:
            garmin = token_store.load(user_id) is not None
        except TokenStoreError:
            garmin = False
        a = chat.agent.coach.athlete(user_id)
        plan = plans.get(user_id) if plans is not None else None
        synced = bool(plan) and any(x.get("garmin") for _, _, x in iter_sessions(plan))
        has_goal = chat.agent.coach.active_goal(user_id) is not None or bool(chat.agent.events.list(user_id))
        state = {
            "garmin": garmin, "sports": bool(a.get("favorite_sports")), "goal": has_goal,
            "plan": plan is not None, "sync": synced,
            "notify": bool(push and push.count(user_id)),
            "calendar": bool(auth.calendar and auth.calendar.connected(user_id)),
            "oura": bool(auth.oura and auth.oura.connected(user_id)),
            "coach": bool(auth.coach_links.coaches_of(user_id)),
            "coach_status": bool(a.get("coach_status") or auth.coach_links.coaches_of(user_id)),
            "gear": bool(gear_store and gear_store.list(user_id)),
            "friend": bool(soc and soc.is_athlete(user_id) and soc.ever_followed(user_id)),
            "interests": bool(a.get("interests")),
        }
        available = {"notify": push is not None, "calendar": auth.calendar is not None, "oura": auth.oura is not None}
        return state, available

    async def progress_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        agent = chat.agent
        state, available = _quest_state(user_id)
        try:
            stats = await _plan_call(lambda: agent.stats.get(user_id))
            _, acts = await _plan_call(lambda: agent.stats.activities(user_id))
            stats_ok = True
        except Exception:  # Garmin not connected or unreachable: quests still work
            today = agent._now(user_id).date()
            stats, acts, stats_ok = stats_compute([], today), [], False
        goal = agent.coach.active_goal(user_id)
        today = date.fromisoformat(stats["today"])
        bonus = {f"gear:{g['id']}": GEAR_XP for g in (gear_store.list(user_id) if gear_store else [])}
        bonus |= checkin_xp_bonus(agent.checkins.list(user_id))
        bonus.update(_social_bonus(user_id))
        bonus.update(await anyio.to_thread.run_sync(lambda: _challenge_bonus(user_id, acts, today)))
        out = await anyio.to_thread.run_sync(lambda: agent.progress.update(
            user_id, acts=acts, today=today, stats=stats,
            plan_key=goal["id"] if goal and plans is not None and plans.get(user_id) else None, quests=state,
            bonus=bonus))
        await anyio.to_thread.run_sync(lambda: _progress_moments(user_id, out))
        quests = quests_view(state, available, agent.coach.athlete(user_id).get("intents"))
        core = [q for q in quests if not q["optional"]]
        return JSONResponse({**out, "quests": quests,
                             "setup": {"done": sum(q["done"] for q in core), "total": len(core)},
                             "week": week_goal(stats), "streak": stats["streak"], "stats_ok": stats_ok})

    # Rabbit moments (moments.py): level up / badge / challenge lines in the Rabbit log.
    def _progress_moments(uid: str, out: dict[str, Any]) -> None:
        assert chat is not None and store is not None
        try:
            done = completed_challenges(store.user_doc(uid, "challenges").load())
            chat.agent.moments.on_progress(uid, out, done)
        except Exception as e:  # moments never break the progress view
            log_event(logger, logging.WARNING, "progress_moments_failed", error=type(e).__name__)

    async def progress_seen(request: Request, user_id: str) -> Response:
        assert chat is not None
        await anyio.to_thread.run_sync(lambda: chat.agent.progress.seen(user_id))
        return JSONResponse({"ok": True})

    # ------------------------------------------- live sync / today / recap --
    # sync.py: on-demand "anything new on Garmin?" (throttled per user, own cursor doc);
    # today.py: the deterministic Today card; recap.py: the weekly recap.
    def _garmin_connected(uid: str) -> bool:
        try:
            return token_store.load(uid) is not None
        except TokenStoreError:
            return False

    live_sync = (LiveSync(store, lambda uid: chat.agent._service.read_uncached(
        uid, "get_activities", {"start": 0, "limit": 5}), connected=_garmin_connected,
        on_new=lambda uid: chat.agent.stats.invalidate(uid, activities=True),
        on_activities=lambda uid, acts: chat.agent.moments.workouts(uid, acts))
        if store is not None and chat is not None else None)
    if chat is not None and push is not None:  # moments push only streak-at-risk + race countdown
        chat.agent.moments.push = lambda u, t, b, url: push.send(u, t, b, url=url)

    async def sync_post(request: Request, user_id: str) -> Response:
        if live_sync is None:
            return _err(503, "Sync isn't configured on this server.")
        return JSONResponse(await anyio.to_thread.run_sync(lambda: live_sync.check(user_id)))

    async def today_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        return JSONResponse(await TodayService(chat.agent, auth.oura).get(user_id))

    async def recap_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        week = request.query_params.get("week") or None
        try:
            return JSONResponse(await _plan_call(lambda: RecapService(chat.agent).get(user_id, week)))
        except RecapError as e:
            return _err(400, str(e))

    # ------------------------------------------------------------ check-ins --
    # Voice check-ins (checkins.py): the athlete's words -> structured entry (forced tool call,
    # deterministic fallback), stored in the encrypted ``checkins`` doc; +10 XP once a day.
    def _checkin_call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except CheckinError as e:
            raise _UserError(str(e)) from None

    async def checkins_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        try:
            days = max(1, min(120, int(request.query_params.get("days") or 30)))
        except ValueError:
            days = 30
        sid = request.query_params.get("session_id") or None
        items = await anyio.to_thread.run_sync(lambda: chat.agent.checkins.list(user_id, days, session_id=sid))
        return JSONResponse({"checkins": items})

    async def checkin_create(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("text", ""), str):
            raise ValueError("body")
        ledger = chat.agent._store.user_doc(user_id, "progress")
        try:
            entry, source = await chat.agent.checkin(
                user_id, body.get("text") or "", session_id=body.get("session_id"),
                activity_id=body.get("activity_id"), day=body.get("date"), feel=body.get("feel"))
        except CheckinError as e:
            raise _UserError(str(e)) from None
        awarded = f"checkin:{entry['date']}" in (ledger.load().get("bonus") or [])
        first = sum(1 for c in chat.agent.checkins.list(user_id) if c.get("date") == entry["date"]) == 1
        return JSONResponse({"checkin": entry, "source": source, "xp": 0 if awarded or not first else CHECKIN_XP},
                            status_code=201)

    async def checkin_update(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        cid = request.path_params["checkin_id"]
        entry = await anyio.to_thread.run_sync(lambda: _checkin_call(lambda: chat.agent.checkins.update(user_id, cid, body)))
        return JSONResponse({"checkin": entry})

    async def checkin_delete(request: Request, user_id: str) -> Response:
        assert chat is not None
        cid = request.path_params["checkin_id"]
        await anyio.to_thread.run_sync(lambda: _checkin_call(lambda: chat.agent.checkins.delete(user_id, cid)))
        return JSONResponse({"ok": True})

    # Workout day (workoutday.py): the "Ready to go" screen and the post-workout reaction.
    def _workout_day() -> Any:
        from .workoutday import WorkoutDay
        assert chat is not None
        return WorkoutDay(chat.agent, auth.oura,
                          gear=(lambda uid: _gear_items(uid)[0]) if gear_store is not None else None)

    async def workout_today_get(request: Request, user_id: str) -> Response:
        sid = request.query_params.get("session_id") or None
        if sid is not None and (len(sid) > 40 or not sid.isalnum()):
            raise ValueError("session_id")
        return JSONResponse({**await _workout_day().today(user_id, sid), "garmin_connected": _garmin_connected(user_id)})

    async def workout_reaction_get(request: Request, user_id: str) -> Response:
        raw = request.query_params.get("activity_id") or ""
        if not raw.isdigit() or len(raw) > 20:
            raise ValueError("activity_id")
        out = await _workout_day().reaction(user_id, int(raw))
        if out is None:
            return _err(404, "That workout hasn't synced yet. Try again in a minute.")
        return JSONResponse(out)

    # ---------------------------------------------------------------- gear --
    # Gear garage (gear.py): items in the encrypted ``gear`` doc, mileage from the cached
    # year of activities, Garmin gear import on request (read-only Garmin calls).
    gear_store = (GearStore(store, today=lambda uid: chat.agent._now(uid).date())
                  if store is not None and chat is not None else None)

    def _gear_items(user_id: str) -> tuple[list[dict[str, Any]], bool]:
        """Items with mileage; works (without activities) when Garmin isn't reachable."""
        assert chat is not None and gear_store is not None
        items = gear_store.list(user_id)
        try:
            _, acts = chat.agent.stats.activities(user_id)
            ok = True
        except Exception:
            acts, ok = [], False
        gstats: dict[str, dict[str, Any]] = {}
        if ok:
            for it in items:
                u = it.get("garmin_uuid")
                if u and not it.get("retired") and len(gstats) < 30:
                    try:
                        gstats[u] = chat.agent._service.gear_stats(user_id, u)
                    except Exception:  # fall back to Rabbit's own count
                        pass
        return gear_usage(items, acts, gstats), ok

    async def _gear_resp(user_id: str, status: int = 200, *, full: bool = False, **extra: Any) -> JSONResponse:
        items, ok = await anyio.to_thread.run_sync(lambda: _gear_items(user_id))
        body: dict[str, Any] = {"items": items, "stats_ok": ok, **extra}
        if full:
            body.update(gear_catalog())
        return JSONResponse(body, status_code=status)

    async def _gear_body(request: Request) -> dict[str, Any]:
        body = await read_json(request)
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise ValueError("body")
        return body

    async def gear_get(request: Request, user_id: str) -> Response:
        if gear_store is None:
            return _err(503, "Gear isn't configured on this server.")
        return await _gear_resp(user_id, full=True)

    async def gear_create(request: Request, user_id: str) -> Response:
        assert gear_store is not None
        body = await _gear_body(request)
        item = await _plan_call(lambda: gear_store.create(user_id, body))
        return await _gear_resp(user_id, 201, item_id=item["id"])

    async def gear_update(request: Request, user_id: str) -> Response:
        assert gear_store is not None
        body = await _gear_body(request)
        gid = request.path_params["gear_id"]
        item = await _plan_call(lambda: gear_store.update(user_id, gid, body))
        return await _gear_resp(user_id, item_id=item["id"])

    async def gear_delete(request: Request, user_id: str) -> Response:
        assert gear_store is not None
        gid = request.path_params["gear_id"]
        await _plan_call(lambda: gear_store.delete(user_id, gid))
        return await _gear_resp(user_id)

    async def gear_retire(request: Request, user_id: str) -> Response:
        assert gear_store is not None
        body = await _gear_body(request)
        retired = body.get("retired", True)
        if not isinstance(retired, bool):
            raise ValueError("retired")
        gid = request.path_params["gear_id"]
        item = await _plan_call(lambda: gear_store.retire(user_id, gid, retired))
        return await _gear_resp(user_id, item_id=item["id"])

    async def gear_import(request: Request, user_id: str) -> Response:
        assert chat is not None and gear_store is not None
        svc = chat.agent._service
        try:
            raw = await anyio.to_thread.run_sync(lambda: svc.gear_list(user_id))
        except ReauthRequired:
            raise _UserError("Reconnect Garmin in settings, then try again.", 409) from None
        except GarminError as e:
            raise _UserError(f"Couldn't read your gear from Garmin: {e}", 502) from None
        except Exception as e:
            log_event(logger, logging.WARNING, "gear_import_failed", user_id=user_id, error=type(e).__name__)
            raise _UserError("Couldn't read your gear from Garmin right now. Try again in a bit.", 502) from None
        res = await _plan_call(lambda: gear_store.import_garmin(user_id, raw.get("gear"), raw.get("defaults")))
        return await _gear_resp(user_id, imported=res)

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

    def _event_ref(aid: str, eid: Any) -> dict[str, Any] | None:
        """A race-strategy thread: the event must be on this athlete's calendar."""
        if eid is None or eid == "":
            return None
        if not isinstance(eid, str) or chat is None:
            raise CoachError("event not found")
        ev = chat.agent.events.get(aid, eid)
        return {"id": eid, "title": f"{ev.get('name') or 'Race'} strategy"}

    def _notify(to_user: str | None, title: str, body: str, *, thread: str = "") -> None:
        if push is None or not to_user:
            return
        if thread and not push_allowed(f"thread:{to_user}:{thread}", 1, PUSH_THREAD_INTERVAL):
            return  # coalesce: the message is saved, the unread badge shows the rest
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
                                              can_edit_plan=body.get("can_edit_plan") is True,
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
            return coach_chat.open_thread(user_id, c["email"], session=_session_ref(user_id, body.get("session_id")),
                                          event=_event_ref(user_id, body.get("event_id")))
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
                msg["text"], thread=tid)
        return JSONResponse({"message": msg}, status_code=201)

    async def athlete_notes(request: Request, user_id: str) -> Response:
        current = links.coach_emails(user_id)
        return JSONResponse({"notes": [n for n in coach_notes.list(user_id, shared_only=True) if n["coach"] in current]})

    # Find a coach (coachdir.py): curated directory, athletes only (coach accounts are 403'd
    # by _api since these paths aren't in COACH_PATHS). The athlete contacts coaches directly.
    from .coachdir import CoachDirectory
    coach_dir = CoachDirectory(store) if store is not None else None

    def _main_race(uid: str) -> dict[str, Any] | None:
        if chat is None:
            return None
        g = chat.agent.coach.active_goal(uid)
        evs = chat.agent.events.list(uid)
        today = chat.agent._now(uid).date().isoformat()
        ev = next((e for e in evs if e.get("main")), None) or \
            next((e for e in evs if (e.get("date") or "") >= today and _ev_is_race(e)), None)
        if ev:
            return {"id": ev["id"], "name": ev.get("name"), "type": ev.get("type"),
                    "distance": ev.get("distance"), "date": ev.get("date")}
        if g:
            return {"id": None, "name": g.get("title"), "type": g.get("type"),
                    "distance": g.get("distance"), "date": g.get("date")}
        return None

    async def coach_directory(request: Request, user_id: str) -> Response:
        assert coach_dir is not None and chat is not None
        athlete = chat.agent.coach.athlete(user_id)
        race = _main_race(user_id)
        qp = request.query_params
        scope, fmt = qp.get("scope") or None, qp.get("format") or None
        try:
            within = int(qp["within"]) if qp.get("within") else None
        except ValueError:
            raise _UserError("distance must be a number of miles") from None
        # Distances only from a location the athlete saved in Explore (never shown back).
        saved = await anyio.to_thread.run_sync(lambda: _geo.load_saved(store, user_id))
        origin = None
        if saved and isinstance(saved.get("lat"), int | float) and isinstance(saved.get("lon"), int | float):
            origin = (float(saved["lat"]), float(saved["lon"]))
        coords: dict[str, tuple[float, float] | None] = {}
        if origin is not None:
            for c in await _plan_call(coach_dir.all):
                if _coachdir.coach_coords(c) is None and c.get("id"):
                    pl = _coachdir.coach_place(c)
                    got = await _geocoder.city_place(pl["city"], pl["state"]) if pl["city"] and pl["state"] else {}
                    if isinstance(got.get("lat"), int | float) and isinstance(got.get("lon"), int | float):
                        coords[c["id"]] = (float(got["lat"]), float(got["lon"]))
        home = _geo.resolve(athlete.get("interests") or {}, athlete, saved)
        found = await _plan_call(lambda: coach_dir.search(
            athlete, race, sport=qp.get("sport"), q=qp.get("q"), scope=scope, fmt=fmt, within_mi=within,
            origin=origin, coords=coords, home_state=str(home.get("state") or "")))
        return JSONResponse({"coaches": found, "race": race, "coach_status": athlete.get("coach_status"),
                             "has_coach": bool(links.coaches_of(user_id)),
                             "has_location": origin is not None, "area": _geo.label(home) if home.get("source") else ""})

    # "Find coaches near me on the web" (coachweb.py): one web search per city + sport, shared
    # and cached 7 days, on the Explore AI daily allowance. The model gets the sport and
    # "City, ST" only; results need an https URL and carry no contact details.
    from . import coachdir as _coachdir
    from . import coachweb as _coachweb
    _coach_web = _coachweb.CoachWebFinder(store)

    async def coach_directory_web(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        sport = str(body.get("sport") or "")
        if sport and sport not in _coachdir.SPORTS:
            raise _UserError(f"sport must be one of {', '.join(_coachdir.SPORTS)}")
        athlete = chat.agent.coach.athlete(user_id)
        saved = await anyio.to_thread.run_sync(lambda: _geo.load_saved(store, user_id))
        city, state = await _x2_area(_geo.resolve(athlete.get("interests") or {}, athlete, saved))
        if not city or not state:
            return JSONResponse({"coaches": [], "state": "needs_location", "area": "", "label": _coachweb.LABEL})
        area = f"{city}, {state}"
        items = await anyio.to_thread.run_sync(lambda: _coach_web.cached(sport, city, state))
        if items is not None:
            return JSONResponse({"coaches": items, "state": "ok", "area": area, "label": _coachweb.LABEL})
        research = getattr(chat.agent._backend, "research", None)
        if research is None:
            return JSONResponse({"coaches": [], "state": "unavailable", "area": area, "label": _coachweb.LABEL})
        today = _explore_today(user_id)
        try:
            await _plan_call(lambda: _events().take_allowance(
                user_id, "explore_ai", today, limit=_explore.AI_PER_DAY,
                message="That's today's web searches used up. Try again tomorrow."))
        except _UserError:
            return JSONResponse({"coaches": [], "state": "limit", "area": area, "label": _coachweb.LABEL})
        try:
            items = await _coach_web.find(research, sport, city, state)
        except Exception as e:
            log_event(logger, logging.WARNING, "coach_web_failed", user_id=user_id, error=type(e).__name__)
            return JSONResponse({"coaches": [], "state": "failed", "area": area, "label": _coachweb.LABEL})
        log_event(logger, logging.INFO, "coach_web", user_id=user_id, found=len(items))
        return JSONResponse({"coaches": items, "state": "ok", "area": area, "label": _coachweb.LABEL})

    async def coach_directory_one(request: Request, user_id: str) -> Response:
        assert coach_dir is not None and chat is not None
        from .coachdir import match, public_view
        c = await _plan_call(lambda: coach_dir.get(str(request.path_params["coach_id"])))
        return JSONResponse({"coach": public_view(c) | {"match": match(c, chat.agent.coach.athlete(user_id),
                                                                       _main_race(user_id))},
                             "race": _main_race(user_id)})

    async def coach_directory_invite(request: Request, user_id: str) -> Response:
        """"Invite as my coach" for a directory coach who has a Rabbit login."""
        assert coach_dir is not None
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        # View-only unless the athlete turned the permissions on in the confirmation sheet.
        perms = {k: body.get(k) is True for k in ("can_edit_plan", "can_see_rabbit_chats")}

        def run() -> None:
            c = coach_dir.get(str(request.path_params["coach_id"]))
            if not c.get("rabbit_user_email"):
                raise CoachError("This coach isn't on Rabbit yet. Contact them directly.")
            links.invite(user_id, c["rabbit_user_email"], **perms)
        await _plan_call(run)
        return JSONResponse({"coaches": [_coach_view(c) for c in links.coaches_of(user_id)]}, status_code=201)

    # Coach side: everything goes through links.require(coach, athlete).
    def _aid(request: Request) -> str:
        return str(request.path_params["athlete_id"])

    async def coach_athletes(request: Request, user_id: str) -> Response:
        out = []
        for link in links.athletes_of(user_id):
            aid = link["athlete_id"]
            goal = _coach().active_goal(aid) if chat else None
            out.append({"athlete_id": aid, "profile": auth.profile(aid), "photo": _photo_version(aid), **_coach_view(link),
                        "goal": {k: goal.get(k) for k in ("title", "date", "distance")} if goal else None,
                        "unread": coach_chat.unread(aid, "coach", coach=link["email"])})
        return JSONResponse({"athletes": out})

    def _coach_athlete_view(a: dict[str, Any]) -> dict[str, Any]:
        """The athlete profile a linked coach sees: no saved location, no home zip."""
        out = {k: v for k, v in a.items() if k not in ("coach_status", "location")}
        if isinstance(out.get("interests"), dict):
            out["interests"] = {k: v for k, v in out["interests"].items() if k != "home_zip"}
        return out

    async def coach_athlete(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        link = await _plan_call(lambda: links.require(user_id, aid))
        coach = _coach()
        return JSONResponse({
            "athlete_id": aid, "profile": auth.profile(aid), "photo": _photo_version(aid), "link": _coach_view(link),
            "athlete": _coach_athlete_view(coach.athlete(aid)),
            "goal": coach_goal_view(coach.active_goal(aid), link),
            "events": [coach_event_view(e, link) for e in chat.agent.events.list(aid)] if chat else [],
            "notes": coach_notes.list(aid, coach=link["email"]),
            "unread": coach_chat.unread(aid, "coach", coach=link["email"]),
            "checkins": chat.agent.checkins.summaries(aid, 5) if chat else [],
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

    # Plan imports (planimport.py, routes in planimport_web.py): coach with can_edit_plan,
    # or the athlete themself; grid, CSV/XLSX/ICS (TrainingPeaks exports) or AI file reads.
    import_routes: list[BaseRoute] = []
    if plans is not None and store is not None and chat is not None:
        import_routes = planimport_web.make_routes(
            importer=ImportService(store, plans, chat.agent.coach), plans=plans, coach=chat.agent.coach,
            links=links, auth=auth, settings=settings, host_ok=host_ok, plan_api=_plan_api,
            plan_call=_plan_call, user_error=_UserError, public_plan=public_plan, notify=_notify,
            coach_chat=coach_chat, structured=getattr(chat.agent._backend, "structured", None),
            now=chat.agent._now, moment=chat.agent.moments.coach_plan)

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
            return coach_chat.open_thread(aid, link["email"], session=_session_ref(aid, body.get("session_id")),
                                          event=_event_ref(aid, body.get("event_id")))
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
        _notify(aid, f"{auth.profile(user_id).get('name') or 'Your coach'}", msg["text"], thread=tid)
        return JSONResponse({"message": msg}, status_code=201)

    async def coach_note_add(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")

        def run() -> dict[str, Any]:
            link = links.require(user_id, aid)
            eid = body.get("event_id")
            if eid not in (None, "") and (not isinstance(eid, str) or chat is None):
                raise CoachError("event not found")
            if eid:
                chat.agent.events.get(aid, eid)  # a race note must be on this athlete's calendar
            return coach_notes.add(aid, link["email"], body.get("text"), shared=body.get("shared", True) is True,
                                   pinned=body.get("pinned") is True, event_id=eid or None)
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

        def view(t: dict[str, Any]) -> dict[str, Any]:
            v = {k: t.get(k) for k in keys if k in t}
            if t.get("kind") == "moment":  # read-only coach view: the moment's line, no actions
                v["parts"] = [{"type": "text", "text": p.get("text", "")} for p in t.get("parts") or []]
                v["label"] = "update"
            return v
        return JSONResponse({"thread": _thread_view(thread), "turns": [view(t) for t in turns]})

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
        except Exception as e:
            log_event(logger, logging.WARNING, "gcal_read_failed", error=type(e).__name__)
            return _err(502, "Google Calendar didn't answer just now. Try again later.")

    async def calendar_delete(request: Request, user_id: str) -> Response:
        if auth.calendar is not None:
            await auth.calendar.disconnect(user_id)
        return JSONResponse({"connected": False})

    async def calendar_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        if _is_coach_account(auth.user_for(request)):
            return _err(403, "Coach accounts can only use the coach view.")
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
        except Exception as e:
            log_event(logger, logging.WARNING, "oura_read_failed", error=type(e).__name__)
            return _err(502, "Oura didn't answer just now. Try again later.")

    async def recovery_get(request: Request, user_id: str) -> Response:
        """Progress recovery: the chosen source's data, plus the other one when ``show_both``."""
        if chat is None:
            return _err(503, "Chat isn't configured on this server.")
        connected = bool(auth.oura and auth.oura.connected(user_id))
        prefs, _ = prefs_for(chat.agent._store, user_id, connected)
        today = plans.today(user_id) if plans else date.today()
        want_oura = connected and (prefs["show_both"] or "oura" in (prefs["recovery"], prefs["sleep"]))
        want_garmin = prefs["show_both"] or not connected or "garmin" in (prefs["recovery"], prefs["sleep"])
        oura_data = garmin_data = None
        if want_oura and auth.oura is not None:
            try:
                oura_data = await auth.oura.recovery(user_id, today, 28)
            except Exception as e:  # shown as unavailable; the Garmin side still renders
                log_event(logger, logging.INFO, "recovery_oura_skip", error=type(e).__name__)
        if want_garmin:
            garmin_data = await anyio.to_thread.run_sync(garmin_recovery, chat.agent._service, user_id, today)
        return JSONResponse({"sources": prefs, "oura_connected": connected,
                             "oura": oura_data, "garmin": garmin_data})

    async def oura_delete(request: Request, user_id: str) -> Response:
        if auth.oura is not None:
            auth.oura.disconnect(user_id)
        return JSONResponse({"connected": False})

    async def oura_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        if _is_coach_account(auth.user_for(request)):
            return _err(403, "Coach accounts can only use the coach view.")
        return await auth.start_oura(request)

    async def oura_callback(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        if _is_coach_account(auth.user_for(request)):
            return _err(403, "Coach accounts can only use the coach view.")
        return await auth.oura_callback(request)

    async def _proposal(user_id: str) -> dict[str, Any]:
        assert plans is not None and chat is not None
        plan = plans.get(user_id)
        if plan is None:
            return {"status": "none"}
        today, acts = await _plan_call(lambda: chat.agent.stats.activities(user_id))
        # The athlete's chosen recovery source (sources.py); down or missing: suggest from the rest.
        try:
            recovery, _ = await recovery_for(chat.agent, auth.oura, user_id, today)
        except Exception:
            recovery = None
        load_now = (await _plan_call(lambda: chat.agent.stats.load(user_id))).get("now") or {}
        return propose_adjustment(plan, acts, today, recovery=recovery, tsb=load_now.get("tsb"),
                                  dismissed=plan.get("adjust_dismissed"), checkins=chat.agent.checkins.list(user_id, 7))

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
        gear = (await anyio.to_thread.run_sync(lambda: _gear_items(user_id)))[0] if gear_store else []
        return JSONResponse(racepack.build(event, athlete, plans.get(user_id) if event.get("main") else None, today, wx,
                                           gear=gear))

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

    async def legal_page(request: Request) -> Response:
        headers = {"Cache-Control": "public, max-age=3600", "Referrer-Policy": "no-referrer",
                   "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}
        if not host_ok(request):
            return HTMLResponse("Not found", status_code=404, headers=headers)
        path = request.url.path
        fn = legal.privacy if path.endswith("/privacy") else legal.about if path.endswith("/about") else legal.terms
        return HTMLResponse(fn(settings.contact_email), headers=headers)

    async def garmin_numbers(request: Request, user_id: str) -> Response:
        assert plans is not None
        return JSONResponse({"numbers": await _plan_call(lambda: plans.garmin_numbers(user_id))})

    # ------------------------------------------- profile photo / race fit --
    photos = PhotoStore(store) if store is not None else None

    def _photo_version(uid: str) -> int | None:
        return photos.version(uid) if photos is not None else None

    async def _photo_resp(uid: str) -> Response:
        got = await anyio.to_thread.run_sync(photos.load, uid) if photos is not None else None
        if got is None:
            return _err(404, "no photo")
        mime, data = got
        return Response(data, media_type=mime, headers={
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'",
            "Content-Disposition": "inline"})

    def _photo_cache(ep: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        """Photo URLs carry a version (?v=), so the browser may keep them (private only)."""
        async def inner(request: Request) -> Response:
            resp = await ep(request)
            if resp.status_code == 200:
                resp.headers["Cache-Control"] = "private, max-age=86400"
            return resp
        return inner

    async def photo_get(request: Request, user_id: str) -> Response:
        return await _photo_resp(user_id)

    async def photo_delete(request: Request, user_id: str) -> Response:
        if photos is None:
            return _err(503, "Photos aren't configured on this server.")
        await anyio.to_thread.run_sync(photos.delete, user_id)
        return JSONResponse({"ok": True, "photo": None})

    async def photo_upload(request: Request) -> Response:
        """Raw-body image upload. Same guards as _api, minus the JSON content type."""
        if not host_ok(request):
            return _err(400, "bad host")
        user_id = auth.user_for(request)
        if user_id is None:
            return _err(401, "not signed in")
        if request.headers.get("origin", "") != settings.public_base_url:
            return _err(403, "bad origin")
        if _is_coach_account(user_id):
            return _err(403, "Coach accounts can only use the coach view.")
        if photos is None:
            return _err(503, "Photos aren't configured on this server.")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            return _err(400, "bad request")
        if declared > MAX_PHOTO:
            return _err(413, "That photo is too large (max 300 KB).")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > MAX_PHOTO:
                return _err(413, "That photo is too large (max 300 KB).")
        try:
            ver = await anyio.to_thread.run_sync(photos.save, user_id, bytes(buf))
        except PhotoError as e:
            return _err(400, str(e))
        except Exception as e:
            log_event(logger, logging.ERROR, "app_unexpected_error", path=request.url.path,
                      error=type(e).__name__)
            return _err(500, f"Internal error ({type(e).__name__})")
        resp = JSONResponse({"ok": True, "photo": ver}, status_code=201)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def coach_athlete_photo(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return await _photo_resp(aid)

    def _race_notes(uid: str, eid: str) -> list[dict[str, Any]]:
        return coach_notes.for_event(uid, eid, links.coach_emails(uid)) if coach_notes is not None else []

    def _race_view(uid: str, eid: str) -> dict[str, Any]:
        ev = _events().get(uid, eid)
        return {"event": {k: ev.get(k) for k in ("id", "name", "type", "distance", "date", "location", "priority",
                                                   "main", "elevation_m", "course_profile", "kind")},
                "racefit": racefit.analyze(ev, _coach().athlete(uid)),
                "strategy": ev.get("strategy"), "coach_notes": _race_notes(uid, eid)}

    async def event_strategy_get(request: Request, user_id: str) -> Response:
        eid = request.path_params["event_id"]
        return JSONResponse(await _plan_call(lambda: _race_view(user_id, eid)))

    async def event_strategy_post(request: Request, user_id: str) -> Response:
        assert chat is not None
        eid = request.path_params["event_id"]
        notes = [n["text"] for n in await _plan_call(lambda: _race_notes(user_id, eid))]
        try:
            await chat.agent.race_strategy(user_id, eid, coach_notes=notes)
        except CoachError as e:
            raise _UserError(str(e)) from None
        except Exception as e:
            log_event(logger, logging.WARNING, "strategy_failed", user_id=user_id, error=type(e).__name__)
            raise _UserError("The strategy didn't work just now. Try again in a minute.", 502) from None
        return JSONResponse(await _plan_call(lambda: _race_view(user_id, eid)))

    # Race readiness (readiness.py): deterministic grade per race, cached 10 min per user+event.
    # Garmin + check-ins + plan only (never Oura), and never put into the model's context.
    from .readiness import ReadinessService
    _readiness = ReadinessService.from_agent(chat.agent) if chat is not None else None

    async def event_readiness(request: Request, user_id: str) -> Response:
        assert _readiness is not None
        eid = request.path_params["event_id"]
        return JSONResponse(await _plan_call(lambda: _readiness.get(user_id, eid)))

    async def readiness_list(request: Request, user_id: str) -> Response:
        assert _readiness is not None
        return JSONResponse({"races": await _plan_call(lambda: _readiness.upcoming(user_id))})

    async def coach_athlete_readiness(request: Request, user_id: str) -> Response:
        assert _readiness is not None
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse({"races": await _plan_call(lambda: _readiness.upcoming(aid))})

    # ----------------------------------------------------------- insights --
    # "What your data says" (insights.py): deterministic patterns over Garmin, load, plan,
    # check-ins, gear and the chosen recovery/sleep source. Oura-derived insights are shown
    # to the athlete only: never to coaches, never in Rabbit's context (context_lines).
    from . import insights as _insights_mod
    from .load import compute as _load_compute
    from .sources import effective as _src_effective
    from .stats import adherence as _adherence

    async def _insight_inputs(uid: str) -> dict[str, Any]:
        assert chat is not None
        agent = chat.agent
        try:
            today, acts = await anyio.to_thread.run_sync(lambda: agent.stats.activities(uid))
        except Exception:  # Garmin not connected or down: the plan/check-in rules still run
            today, acts = agent._now(uid).date(), []
        athlete = agent.coach.athlete(uid)
        plan = plans.get(uid) if plans is not None else None
        connected = bool(auth.oura is not None and auth.oura.connected(uid))
        prefs, _ = prefs_for(store, uid, connected) if store is not None else ({}, False)
        rec_src, sleep_src = _src_effective(prefs, connected), _src_effective(prefs, connected, "sleep")
        recovery = None
        try:
            if rec_src == "oura":
                recovery, _ = await recovery_for(agent, auth.oura, uid, today)
            else:  # the same cached 3-day Garmin read as recovery/today (Garmin rate limit)
                recovery = await anyio.to_thread.run_sync(garmin_recovery, agent._service, uid, today)
        except Exception:
            recovery = None
        try:
            proposal = await _proposal(uid)
        except Exception:
            proposal = None
        try:
            gear = (await anyio.to_thread.run_sync(lambda: _gear_items(uid)))[0] if gear_store is not None else []
        except Exception:
            gear = []
        adh = _adherence(plan, acts, today) if plan else None
        return {"today": today, "acts": acts, "athlete": athlete, "plan": plan,
                "load": _load_compute(acts, today, threshold_hr=athlete.get("threshold_hr"), plan=plan),
                "checkins": agent.checkins.list(uid, 60), "recovery": recovery, "recovery_source": rec_src,
                "sleep": recovery if sleep_src == rec_src else None, "sleep_source": sleep_src,
                "events": agent.events.list(uid), "gear": gear, "proposal": proposal,
                "adherence_pct": ((adh or {}).get("to_date") or {}).get("pct")}

    _insights = (_insights_mod.InsightsService(store, gather=_insight_inputs, today=lambda uid: chat.agent._now(uid).date())
                 if store is not None and chat is not None else None)

    async def insights_get(request: Request, user_id: str) -> Response:
        if _insights is None:
            return _err(503, "Insights aren't available on this server.")
        return JSONResponse(await _insights.for_athlete(user_id, fresh=request.query_params.get("fresh") == "1"))

    async def insight_dismiss(request: Request, user_id: str) -> Response:
        if _insights is None:
            return _err(503, "Insights aren't available on this server.")
        body = await read_json(request)
        days = (body or {}).get("days", _insights_mod.SNOOZE_DAYS) if isinstance(body, dict) else _insights_mod.SNOOZE_DAYS
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValueError("days")
        until = _insights.dismiss(user_id, request.path_params["insight_id"], days)
        return JSONResponse({"ok": True, "until": until})

    async def coach_athlete_insights(request: Request, user_id: str) -> Response:
        if _insights is None:
            return _err(503, "Insights aren't available on this server.")
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        return JSONResponse(await _insights.for_coach(aid))

    # ------------------------------------------------------------ explore --
    # Race discovery (explore.py): RunSignup search with fit hints, "Find more with Rabbit"
    # (web research, daily allowance, never any Oura data), and "Add to my races".
    from . import explore as _explore

    def _explore_today(uid: str) -> date:
        assert chat is not None
        return chat.agent._now(uid).date()

    def _explore_filters(raw: dict[str, Any], uid: str) -> dict[str, Any]:
        try:
            return _explore.parse_filters(raw, _explore_today(uid))
        except _explore.ExploreError as e:
            raise _UserError(e.message, e.status) from None

    def _explore_hinted(uid: str, races: list[dict[str, Any]]) -> list[dict[str, Any]]:
        main = next((e for e in _events().list(uid) if e["main"]), None)
        athlete, today = _coach().athlete(uid), _explore_today(uid)
        basis = _pred_basis(uid)  # finish-time estimates (explore v2 block below)
        prefer = set((athlete.get("interests") or {}).get("distances") or [])
        out = []
        for r in races:
            est = _predict.for_race(basis, r, prefer) if _predict.has_data(basis) else None
            out.append(dict(r, hints=_explore.fit_hints(r, main, athlete, today), **({"estimate": est} if est else {})))
        return out

    async def explore_get(request: Request, user_id: str) -> Response:
        f = _explore_filters(dict(request.query_params), user_id)
        try:
            res = await _explore.default_search().search(f)
        except _explore.ExploreError as e:
            raise _UserError(e.message, e.status) from None
        found = res["races"]
        wide = _explore.nationwide(f)
        if wide and not f.get("q"):  # no location: only races you can still enter, labelled honestly
            found = _explore.open_only(found)
        races = await _plan_call(lambda: _explore_hinted(user_id, found))
        return JSONResponse({**res, "races": races, "query": f, "nationwide": wide,
                             "note": _explore.NATIONWIDE_NOTE if wide else ""})

    async def explore_defaults(request: Request, user_id: str) -> Response:
        athlete = await _plan_call(lambda: _coach().athlete(user_id))
        out = _explore.defaults(athlete)
        # Search with no filters starts where For you looks (saved location, home zip, profile
        # city/state), 50 mi, all types; nothing known -> nationwide (labelled).
        loc = (await _x2_resolved(user_id))["loc"]
        out["near"] = loc.get("zip") or (loc.get("state") if loc.get("state") in _geo.US_STATES else "") or ""
        out["location"] = _x2_loc_view(loc)
        return JSONResponse(out)

    async def explore_ai(request: Request, user_id: str) -> Response:
        assert chat is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        f = _explore_filters(body, user_id)
        finder = _explore.default_web()
        races = finder.cached(f)
        if races is None and f.get("zip"):
            # The model gets a city/state, never the zip.
            place = await _geocoder.zip_place(f["zip"])
            area = ", ".join(x for x in (place.get("city") or "", place.get("state") or "") if x)
            f = dict(f, area=area) if area else dict(f, state=place.get("state") or None)
        if races is None:
            research = getattr(chat.agent._backend, "research", None)
            if research is None:
                raise _UserError("Web search isn't available on this server.", 503)
            today = _explore_today(user_id)
            await _plan_call(lambda: _events().take_allowance(
                user_id, "explore_ai", today, limit=_explore.AI_PER_DAY,
                message="That's today's Rabbit race searches used up. Try again tomorrow."))
            try:
                races = await finder.find(research, f, today)
            except Exception as e:
                log_event(logger, logging.WARNING, "explore_ai_failed", user_id=user_id, error=type(e).__name__)
                raise _UserError("Rabbit's web search didn't work just now. Try again in a minute.", 502) from None
            log_event(logger, logging.INFO, "explore_ai", user_id=user_id, found=len(races))
        found = races
        hinted = await _plan_call(lambda: _explore_hinted(user_id, found))
        return JSONResponse({"races": hinted, "query": f})

    async def explore_add(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        try:
            fields = _explore.event_fields(body.get("race"), body.get("event_index"), body.get("priority"))
        except _explore.ExploreError as e:
            raise _UserError(e.message, e.status) from None

        def run() -> tuple[dict[str, Any], bool]:
            same = next((e for e in _events().list(user_id) if e["date"] == fields["date"]
                         and e["name"].strip().lower() == fields["name"].strip().lower()), None)
            return (same, True) if same else (_events().create(user_id, fields), False)
        ev, already = await _plan_call(run)
        return _events_resp(user_id, 200 if already else 201, event=ev, already=already)

    # ------------------------------------------------------------- social --
    # Following friends (social.py): follow by email or invite code, a feed of followees'
    # recent workouts (their visibility settings, never HR/health/location), kudos + short
    # cheers, friend cards, follower-only photos. Athletes only; coach accounts get 403.
    from . import social as _social
    from .progress import level_of as _level_of

    soc = (_social.Social(store, athletes=auth.athlete_emails)
           if store is not None else None)

    def _soc_name(uid: str) -> str:
        name = (auth.profile(uid).get("name") or "").strip()
        return name.split()[0][:40] if name else "Friend"

    def _soc_meta(uid: str) -> dict[str, Any]:
        assert chat is not None
        try:
            streak = chat.agent.stats.get(uid)["streak"]["current"]
        except Exception:
            streak = None
        return {"name": _soc_name(uid), "photo": _photo_version(uid), "picture": auth.profile(uid).get("picture") or "",
                "level": _level_of(chat.agent.progress.ledger(uid)["xp"]), "streak": streak}

    soc_feed = (_social.SocialFeed(soc, activities=lambda uid: chat.agent.stats.activities(uid), meta=_soc_meta)
                if soc is not None and chat is not None else None)

    def _soc_person(uid: str | None) -> dict[str, Any] | None:
        if not uid:
            return None
        p = auth.profile(uid)
        return {"id": uid, "name": _soc_name(uid), "photo": _photo_version(uid), "picture": p.get("picture") or ""}

    def _social_api(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            if soc is None or soc_feed is None:
                return _err(503, "Friends aren't configured on this server.")
            try:
                soc.require(user_id)
                return await handler(request, user_id)
            except _social.SocialError as e:
                return _err(e.status, e.message)
        return _api(inner, mutating=mutating)

    def _social_bonus(uid: str) -> dict[str, int]:
        """Progress bonus keys: +5 XP per kudos received (10 a day at most)."""
        if soc is None or chat is None or not soc.is_athlete(uid):
            return {}
        return soc.kudos_bonus(uid, chat.agent._now(uid).date())

    def _social_push(to: str, key: str, window: float, title: str, body: str) -> None:
        if push is None or not push_allowed(key, 1, window):
            return
        try:
            push.send(to, title, body[:140], url="/app/")
        except Exception as e:  # best effort
            log_event(logger, logging.WARNING, "social_push_failed", error=type(e).__name__)

    async def social_get(request: Request, user_id: str) -> Response:
        assert soc is not None
        raw = await anyio.to_thread.run_sync(soc.people, user_id)

        def person(x: dict[str, Any]) -> dict[str, Any]:
            return {**x, "user": _soc_person(x.get("user_id"))}
        out = {k: [person(x) for x in raw[k]] for k in ("following", "followers", "pending_in", "pending_out")}
        out["blocked"] = [_soc_person(b) for b in raw["blocked"]]
        return JSONResponse({**out, "invite_code": raw["invite_code"], "settings": raw["settings"]})

    async def social_follow(request: Request, user_id: str) -> Response:
        assert soc is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        res = await anyio.to_thread.run_sync(lambda: soc.follow(user_id, email=body.get("email"), code=body.get("code")))
        me_name = _soc_name(user_id)
        if res["notify"]:
            if res["status"] == "active":
                _social_push(res["notify"], f"social-follow:{res['notify']}:{user_id}", 86400,
                             "New follower", f"{me_name} is now following your training on Rabbit.")
            else:
                _social_push(res["notify"], f"social-follow:{res['notify']}:{user_id}", 86400,
                             "Follow request", f"{me_name} wants to follow your training on Rabbit.")
        if res["by_email"]:  # same answer whether or not the email has an account
            return JSONResponse({"ok": True, "message": _social.GENERIC_SENT})
        name = _soc_name(res["target"])
        msg = f"You're following {name}." if res["status"] == "active" else f"Request sent to {name}."
        return JSONResponse({"ok": True, "message": msg})

    def _edge_route(fn: Callable[[str, Any], Any]) -> Handler:
        async def h(request: Request, user_id: str) -> Response:
            await anyio.to_thread.run_sync(lambda: fn(user_id, request.path_params["edge_id"]))
            return JSONResponse({"ok": True})
        return h

    async def social_block(request: Request, user_id: str) -> Response:
        assert soc is not None
        body = await read_json(request)
        other = body.get("user_id") if isinstance(body, dict) else None
        await anyio.to_thread.run_sync(lambda: soc.block(user_id, other))
        return JSONResponse({"ok": True})

    async def social_unblock(request: Request, user_id: str) -> Response:
        assert soc is not None
        await anyio.to_thread.run_sync(lambda: soc.unblock(user_id, request.path_params["other_id"]))
        return JSONResponse({"ok": True})

    async def social_settings(request: Request, user_id: str) -> Response:
        assert soc is not None
        body = await read_json(request)
        return JSONResponse({"settings": await anyio.to_thread.run_sync(lambda: soc.put_settings(user_id, body))})

    async def social_code(request: Request, user_id: str) -> Response:
        assert soc is not None
        return JSONResponse({"invite_code": await anyio.to_thread.run_sync(soc.regenerate_code, user_id)})

    async def social_feed(request: Request, user_id: str) -> Response:
        assert soc_feed is not None
        items = await anyio.to_thread.run_sync(lambda: soc_feed.feed(user_id, _soc_name))
        return JSONResponse({"items": items, "following": len(soc.following_ids(user_id)) if soc else 0})

    async def social_badge(request: Request, user_id: str) -> Response:
        assert soc is not None
        return JSONResponse(await anyio.to_thread.run_sync(soc.badge, user_id))

    async def social_seen(request: Request, user_id: str) -> Response:
        assert soc is not None
        await anyio.to_thread.run_sync(soc.mark_seen, user_id)
        return JSONResponse({"ok": True})

    def _soc_target(request: Request, user_id: str) -> tuple[str, str]:
        """The owner and activity from the URL; the viewer must see that workout."""
        assert soc is not None and soc_feed is not None
        owner = request.path_params["owner_id"]
        aid = _social.valid_activity_id(request.path_params["activity_id"])
        if owner == user_id or not soc.follows(user_id, owner) or not soc_feed.has_item(user_id, owner, aid):
            raise _social.SocialError("workout not found", 404)
        return owner, aid

    def _title_of(owner: str, aid: str) -> str:
        assert soc_feed is not None
        return next((it["title"] for it in soc_feed.entry(owner)["items"] if it["id"] == aid), "workout")

    async def social_kudos(request: Request, user_id: str) -> Response:
        assert soc is not None
        owner, aid = await anyio.to_thread.run_sync(_soc_target, request, user_id)
        if request.method == "DELETE":
            return JSONResponse(await anyio.to_thread.run_sync(lambda: soc.remove_kudos(user_id, owner, aid)))
        res = await anyio.to_thread.run_sync(lambda: soc.give_kudos(user_id, owner, aid))
        if res.pop("new"):  # coalesced: at most one push per workout per hour
            _social_push(owner, f"social-kudos:{owner}:{aid}", 3600, "Kudos!",
                         f"{_soc_name(user_id)} gave kudos on your {_title_of(owner, aid)}.")
        return JSONResponse(res)

    async def social_cheer(request: Request, user_id: str) -> Response:
        assert soc is not None
        owner, aid = await anyio.to_thread.run_sync(_soc_target, request, user_id)
        body = await read_json(request)
        text = body.get("text") if isinstance(body, dict) else None
        c = await anyio.to_thread.run_sync(lambda: soc.cheer(user_id, owner, aid, text))
        _social_push(owner, f"social-kudos:{owner}:{aid}", 3600, f"{_soc_name(user_id)} cheered you on",
                     c["text"])
        return JSONResponse({"cheer": {**c, "by": {"id": user_id, "name": _soc_name(user_id)}, "mine": True,
                                       "can_delete": True}}, status_code=201)

    async def social_cheer_delete(request: Request, user_id: str) -> Response:
        assert soc is not None
        owner = request.path_params["owner_id"]
        if owner != user_id and not soc.follows(user_id, owner):
            raise _social.SocialError("workout not found", 404)
        await anyio.to_thread.run_sync(lambda: soc.delete_cheer(
            user_id, owner, request.path_params["activity_id"], request.path_params["cheer_id"]))
        return JSONResponse({"ok": True})

    async def social_person(request: Request, user_id: str) -> Response:
        assert soc_feed is not None
        pid = request.path_params["person_id"]
        return JSONResponse(await anyio.to_thread.run_sync(lambda: soc_feed.card(user_id, pid, _soc_name)))

    async def social_photo(request: Request, user_id: str) -> Response:
        assert soc is not None
        pid = request.path_params["person_id"]
        if pid != user_id and not soc.follows(user_id, pid):
            return _err(404, "no photo")
        return await _photo_resp(pid)

    # ------------------------------------------------------ explore: for you --
    # Personal race picks (foryou.py) from the athlete's interests, goal, readiness status and
    # calendar; friends' races only when they share races; bucket list = web research at most
    # once a week per user (stored in the "foryou" doc). Athletes only (coach accounts: 403).
    from . import foryou as _foryou

    def _fy_bucket_doc(uid: str):
        assert store is not None
        return store.user_doc(uid, "foryou")

    def _fy_bucket_stored(uid: str) -> dict[str, Any] | None:
        if store is None:
            return None
        b = _fy_bucket_doc(uid).load().get("bucket")
        return b if isinstance(b, dict) else None

    def _fy_friends(uid: str, today: date) -> list[dict[str, Any]]:
        if soc is None or not soc.is_athlete(uid):
            return []
        friends = [(_soc_name(f), _events().list(f)) for f in soc.following_ids(uid)
                   if soc.settings(f).get("races")]
        return _foryou.friend_races(friends, today)

    def _fy_readiness(uid: str, events: list[dict[str, Any]], today: date) -> str | None:
        main = _foryou.main_race(events, today)
        if main is None or _readiness is None:
            return None
        try:
            return _readiness.get(uid, main["id"]).get("status")
        except Exception:  # Garmin down or no data: no readiness note
            return None

    async def foryou_get(request: Request, user_id: str) -> Response:
        athlete = await _plan_call(lambda: _coach().athlete(user_id))
        interests = athlete.get("interests") or {}
        events = await _plan_call(lambda: _events().list(user_id))
        today = _explore_today(user_id)
        status = await anyio.to_thread.run_sync(lambda: _fy_readiness(user_id, events, today))
        loc, eff, inferred = await anyio.to_thread.run_sync(lambda: _x2_context(user_id, athlete, events, today))
        res = await _foryou.default_foryou().sections(
            user_id, interests=eff, athlete=athlete, events=events, today=today,
            readiness_status=status, fresh=request.query_params.get("fresh") == "1", loc=loc)
        sections = [dict(sec, races=await _plan_call(lambda sec=sec: _explore_hinted(user_id, sec["races"])))
                    for sec in res["sections"]]
        friends = await _plan_call(lambda: _fy_friends(user_id, today))
        if friends:
            sections.append({"id": "friends", "title": "Your friends are racing",
                             "races": await _plan_call(lambda: _explore_hinted(user_id, friends))})
        wants = _foryou.wants_bucket(interests)
        stored = await anyio.to_thread.run_sync(lambda: _fy_bucket_stored(user_id)) if wants else None
        fresh_bucket = bool(stored) and time.time() - float(stored.get("ts", 0)) < _foryou.BUCKET_EVERY_S
        if wants and stored and stored.get("races"):
            sections.append({"id": "bucket", "title": "Bucket list", "source": "web",
                             "races": await _plan_call(lambda: _explore_hinted(user_id, stored["races"]))})
        if not any(s["id"] in ("picks", "tuneups", "near", "nationwide", "bucket") and s["races"] for s in sections):
            sections.append(await _x2_popular(user_id, eff, today, verify=not (res["zip"] or res["state"])))
        eligible = wants and store is not None
        can_web = chat is not None and getattr(chat.agent._backend, "research", None) is not None
        return JSONResponse({
            "interests": interests, "has_interests": _foryou.has_own_interests(interests), "sections": sections,
            "inferred": inferred, "effective": eff, "location": _x2_loc_view(loc),
            "partial": res["partial"], "failed": res["failed"], "zip": res["zip"], "radius": res["radius"],
            "nationwide": bool(res.get("nationwide")),
            "bucket": {"eligible": eligible, "due": eligible and can_web and not fresh_bucket}})

    async def foryou_bucket(request: Request, user_id: str) -> Response:
        assert chat is not None
        athlete = await _plan_call(lambda: _coach().athlete(user_id))
        interests = athlete.get("interests") or {}
        if not _foryou.wants_bucket(interests) or store is None:
            raise _UserError("Pick the bucket-list vibe or a travel-race goal first.")
        stored = await anyio.to_thread.run_sync(lambda: _fy_bucket_stored(user_id))
        if stored and time.time() - float(stored.get("ts", 0)) < _foryou.BUCKET_EVERY_S:
            races = stored.get("races") or []
        else:
            research = getattr(chat.agent._backend, "research", None)
            if research is None:
                raise _UserError("Web search isn't available on this server.", 503)
            today = _explore_today(user_id)
            await _plan_call(lambda: _events().take_allowance(
                user_id, "explore_ai", today, limit=_explore.AI_PER_DAY,
                message="That's today's Rabbit race searches used up. Try again tomorrow."))
            try:
                raw = await research(_explore.WEB_SYSTEM, _foryou.bucket_prompt(interests, today),
                                     max_searches=5, report_tool=_explore.WEB_TOOL)
            except Exception as e:
                log_event(logger, logging.WARNING, "foryou_bucket_failed", user_id=user_id, error=type(e).__name__)
                raise _UserError("Rabbit's web search didn't work just now. Try again in a minute.", 502) from None
            races = _foryou.clean_bucket(raw, interests, today)
            entry = {"ts": time.time(), "races": races}

            def put(d: dict[str, Any]) -> None:
                d["bucket"] = entry
            await anyio.to_thread.run_sync(lambda: _fy_bucket_doc(user_id).update(put))
            log_event(logger, logging.INFO, "foryou_bucket", user_id=user_id, found=len(races))
        found = races
        return JSONResponse({"section": {"id": "bucket", "title": "Bucket list", "source": "web",
                                         "races": await _plan_call(lambda: _explore_hinted(user_id, found))}})

    # ------------------------- explore v2: location, Let Rabbit explore, local, predict --
    # Location (geo.py): saved location first ("Use my location" -> coordinates rounded to 2
    # decimals before anything else, Nominatim reverse with an identifying UA, 1 req/s, cached
    # 30 days; or a typed zip), stored as the profile field "location" = {lat, lon, city, state,
    # zip, source, updated} (never in Rabbit's context, a coach view or friends), then home zip,
    # then the profile's home_location; no timezone guessing. Nothing known -> a nationwide
    # "Coming up" search, labelled as such. For you never comes back empty: inferred interests
    # (main race, goal, favorites, Garmin sports, else a balanced mix). "Let Rabbit explore"
    # (rabbitexplore.py) = For you + an AI web scout (only interests, "City, ST", main race /
    # goal and a readiness word; never Oura) + places nearby (local.py, OpenStreetMap Overpass,
    # 8 km, cached 7 days per rounded spot) + group activities (localacts.py, web, weekly per
    # city). Coordinates are never logged or sent to the model. Athletes only (coach: 403).
    from . import geo as _geo
    from . import local as _osm
    from . import localacts as _local
    from . import predict as _predict
    from . import rabbitexplore as _rx
    _geo_contact = settings.contact_email or settings.public_base_url
    _geocoder = _geo.Geocoder(contact=_geo_contact, store=store)
    _osm_places = _osm.Places(contact=_geo_contact, store=store)
    _local_finder = _local.LocalFinder(store)
    _scout = _rx.ScoutCache()
    _pred_cache = _predict.BasisCache()

    # Readiness grades and finish-time bases go stale when a race, the plan, check-ins, the
    # profile or the activities change. Any write to those docs (web, Rabbit, a coach, an
    # import) drops the user's stats cache, and every stats invalidation (incl. a newly
    # synced workout) drops both derived caches.
    def _drop_derived(uid: str) -> None:
        if _readiness is not None:
            _readiness.invalidate(uid)
        _pred_cache.drop(uid)

    def _doc_written(uid: str, name: str) -> None:
        if chat is not None and (name in ("events", "goals", "checkins", "profile") or name.startswith("plan-")):
            chat.agent.stats.invalidate(uid)
    if chat is not None:
        chat.agent.stats.on_invalidate(_drop_derived)
        chat.agent._store.on_user_write(_doc_written)

    def _x2_by_sport(uid: str) -> list[dict[str, Any]]:
        try:
            return list(chat.agent.stats.get(uid).get("by_sport") or []) if chat is not None else []
        except Exception:  # Garmin not connected or down: favorites and the main race still count
            return []

    def _pred_basis(uid: str) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            if chat is None:
                return _predict.make_basis()
            agent = chat.agent
            garmin, acts = None, []
            try:
                garmin = agent._service.execute(uid, "get_race_predictions", {}).get("result")
            except Exception:  # no predictor on this watch / not connected
                pass
            try:
                _, acts = agent.stats.activities(uid)
            except Exception:
                pass
            return _predict.make_basis(garmin=garmin, acts=acts, athlete=agent.coach.athlete(uid),
                                       today=_explore_today(uid))
        return _pred_cache.get(uid, build)

    def _x2_goal(uid: str) -> dict[str, Any] | None:
        try:
            return _coach().active_goal(uid)
        except Exception:
            return None

    def _x2_context(uid: str, athlete: dict[str, Any], events: list[dict[str, Any]],
                    today: date) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """(resolved location, interests to rank with, inferred?)."""
        interests = athlete.get("interests") or {}
        loc = _geo.resolve(interests, athlete, _geo.load_saved(store, uid))
        eff, inferred = _foryou.effective_interests(
            interests, lambda: _foryou.infer_interests(athlete, _x2_by_sport(uid), events, today, _x2_goal(uid)))
        return loc, eff, inferred

    def _x2_loc_view(loc: dict[str, Any]) -> dict[str, Any]:
        """What the app sees: never coordinates."""
        ok = _geo.searchable(loc)
        return {"source": loc.get("source"), "label": _geo.label(loc), "zip": loc.get("zip") or "",
                "state": loc.get("state") or "", "city": loc.get("city") or "", "searchable": ok,
                "nationwide": not ok, "note": "" if ok else _explore.NATIONWIDE_NOTE}

    def _x2_saved_view(saved: dict[str, Any] | None) -> dict[str, Any] | None:
        return {k: saved.get(k) for k in ("city", "state", "zip", "source", "updated")} if saved else None

    async def _x2_area(loc: dict[str, Any]) -> tuple[str, str]:
        """(city, state) for the model and the group search: never a zip or coordinates."""
        city, state = loc.get("city") or "", loc.get("state") or ""
        if not city and loc.get("zip"):
            place = await _geocoder.zip_place(str(loc["zip"]))
            city, state = place.get("city") or "", place.get("state") or state
        return str(city), str(state)

    async def _x2_places(uid: str, loc: dict[str, Any]) -> dict[str, Any]:
        """{"places", "state": ok|off|needs_location|failed} from OpenStreetMap."""
        if not await anyio.to_thread.run_sync(lambda: _geo.use_for_local(store, uid)):
            return {"places": [], "state": "off"}
        coords = await _geocoder.coords(loc)
        if coords is None:
            return {"places": [], "state": "needs_location"}
        try:
            return {"places": await _osm_places.near(*coords), "state": "ok"}
        except _osm.OverpassError as e:
            log_event(logger, logging.WARNING, "explore_places_failed", user_id=uid, error=str(e)[:40])
            return {"places": [], "state": "busy" if str(e) == "busy" else "failed"}

    async def _x2_groups(uid: str, city: str, state: str, today: date, *, search: bool,
                         charge: Callable[[], Awaitable[bool]] | None = None) -> tuple[list[dict[str, Any]], str]:
        """Group activities for a city: the weekly shared cache, or (``search``) one web search
        on the daily allowance. Returns (items, ok|cached_only|limit|unavailable|failed)."""
        items = await anyio.to_thread.run_sync(lambda: _local_finder.cached(city, state, today))
        if items is not None:
            return items, "ok"
        if not search:
            return [], "cached_only"
        research = getattr(chat.agent._backend, "research", None) if chat is not None else None
        if research is None:
            return [], "unavailable"
        if charge is not None:
            if not await charge():
                return [], "limit"
        else:
            try:
                await _plan_call(lambda: _events().take_allowance(uid, "explore_ai", today, limit=_explore.AI_PER_DAY,
                                                                  message="limit"))
            except _UserError:
                return [], "limit"
        try:
            items = await _local_finder.find(research, city, state, today)
        except Exception as e:
            log_event(logger, logging.WARNING, "explore_local_failed", user_id=uid, error=type(e).__name__)
            return [], "failed"
        log_event(logger, logging.INFO, "explore_local", user_id=uid, found=len(items))
        return items, "ok"

    async def _x2_popular(uid: str, interests: dict[str, Any], today: date, *, verify: bool) -> dict[str, Any]:
        verified: dict[str, Any] = {}
        if verify:
            try:
                verified = await _foryou.verify_popular(_explore.default_search(), today)
            except Exception:
                verified = {}
        races = _foryou.popular_races(interests, today, verified)
        return {"id": "popular", "title": "Popular big races", "source": "curated",
                "races": await _plan_call(lambda: _explore_hinted(uid, races))}

    async def _x2_resolved(uid: str) -> dict[str, Any]:
        athlete = await _plan_call(lambda: _coach().athlete(uid))
        saved = await anyio.to_thread.run_sync(lambda: _geo.load_saved(store, uid))
        return {"saved": saved, "loc": _geo.resolve(athlete.get("interests") or {}, athlete, saved)}

    async def _x2_location_resp(uid: str) -> Response:
        r = await _x2_resolved(uid)
        use = await anyio.to_thread.run_sync(lambda: _geo.use_for_local(store, uid))
        view = _x2_saved_view(r["saved"])
        return JSONResponse({"saved": view, "device": view, "resolved": _x2_loc_view(r["loc"]),
                             "use_for_local": use})

    async def location_get(request: Request, user_id: str) -> Response:
        return await _x2_location_resp(user_id)

    async def location_post(request: Request, user_id: str) -> Response:
        """{lat, lon} from "Use my location" (rounded here, before anything else) or {zip}."""
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        if store is None:
            raise _UserError("Location isn't available on this server.", 503)
        if body.get("zip") is not None:
            zip_ = str(body.get("zip") or "").strip()
            if not re.fullmatch(r"\d{5}", zip_):
                raise _UserError("Enter a 5-digit US zip code.")
            try:
                place = await _geocoder.zip_place(zip_, strict=True)
            except _geo.LocationError as e:
                raise _UserError(str(e), 503) from None
            if place.get("lat") is None:
                raise _UserError("Couldn't find that zip code. Check it and try again.", 502 if not place else 400)
            lat2, lon2, source = place["lat"], place["lon"], "manual"
        else:
            try:
                lat2, lon2 = _geo.round2(body.get("lat"), body.get("lon"))  # precise values stop here
            except _geo.LocationError as e:
                raise _UserError(str(e)) from None
            try:
                place = await _geocoder.reverse(lat2, lon2)
            except _geo.LocationError as e:
                raise _UserError(str(e), 502) from None
            source = "device"
        entry = await anyio.to_thread.run_sync(
            lambda: _geo.save_location(store, user_id, place, lat2, lon2, source, time.time()))
        log_event(logger, logging.INFO, "location_set", user_id=user_id, source=source, has_zip=bool(entry["zip"]))
        return await _x2_location_resp(user_id)

    async def location_prefs(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("use_for_local"), bool):
            raise ValueError("body")
        if store is None:
            raise _UserError("Location isn't available on this server.", 503)
        await anyio.to_thread.run_sync(lambda: _geo.set_use_for_local(store, user_id, body["use_for_local"]))
        return await _x2_location_resp(user_id)

    async def location_delete(request: Request, user_id: str) -> Response:
        await anyio.to_thread.run_sync(lambda: _geo.forget(store, user_id))
        log_event(logger, logging.INFO, "location_forgotten", user_id=user_id)
        return await _x2_location_resp(user_id)

    # One "Let Rabbit explore" tap = one web search against the daily allowance, however
    # many parts (race scout, group search) end up searching. The client sends the same
    # ``tap`` id with its parallel part requests; the first part that searches pays.
    _rx_taps: dict[tuple[str, str], bool] = {}
    _rx_tap_lock = threading.Lock()

    def _rx_charge_sync(uid: str, tap: str, today: date) -> bool:
        with _rx_tap_lock:
            key = (uid, tap)
            if key in _rx_taps:
                return _rx_taps[key]
            try:
                _events().take_allowance(uid, "explore_ai", today, limit=_explore.AI_PER_DAY, message="limit")
                ok = True
            except CoachError:
                ok = False
            _rx_taps[key] = ok
            while len(_rx_taps) > 2000:
                _rx_taps.pop(next(iter(_rx_taps)))
            return ok

    async def _rx_charge(uid: str, tap: str, today: date) -> bool:
        return await anyio.to_thread.run_sync(_rx_charge_sync, uid, tap, today)

    async def _rx_races(user_id: str, athlete: dict[str, Any], events: list[dict[str, Any]], today: date,
                        loc: dict[str, Any], eff: dict[str, Any], city: str, state: str,
                        charge: Callable[[], Awaitable[bool]]) -> dict[str, Any]:
        """For you listings and the AI web scout, run concurrently, then merged and ranked."""
        assert chat is not None
        status = await anyio.to_thread.run_sync(lambda: _fy_readiness(user_id, events, today))
        goal = await anyio.to_thread.run_sync(lambda: _x2_goal(user_id))

        async def listings() -> dict[str, Any]:
            try:
                return await _foryou.default_foryou().sections(
                    user_id, interests=eff, athlete=athlete, events=events, today=today,
                    readiness_status=status, loc=loc)
            except Exception:
                return {"sections": [], "partial": True, "zip": "", "state": "", "radius": None, "nationwide": True}

        area = ", ".join(x for x in (city, state) if x)
        main = _foryou.main_race(events, today)
        prompt = _rx.scout_prompt(eff, area=area, main=main, goal=goal, readiness=status, today=today)

        async def scout() -> tuple[list[dict[str, Any]], str]:
            hit = _scout.get(prompt)
            if hit is not None:
                return hit, "ok"
            research = getattr(chat.agent._backend, "research", None)
            if research is None:
                return [], "unavailable"
            if not await charge():
                return [], "limit"
            try:
                raw = await research(_explore.WEB_SYSTEM, prompt, max_searches=5, report_tool=_explore.WEB_TOOL)
                web = _explore.clean_web(_explore.report_obj(raw), today)
                _scout.put(prompt, web)
                return web, "ok"
            except Exception as e:
                log_event(logger, logging.WARNING, "explore_rabbit_web_failed", user_id=user_id,
                          error=type(e).__name__)
                return [], "failed"

        fy_res, (web, web_state) = await asyncio.gather(listings(), scout())
        fy_races = [r for sec in fy_res["sections"] for r in sec["races"]]
        merged = _rx.dedupe([fy_races, web])
        ranked, tunes = _rx.rank(merged, interests=eff, events=events, today=today)
        shown = ranked[:_rx.LIMIT]
        zip_, st = fy_res.get("zip") or "", fy_res.get("state") or ""
        return {"intro": _rx.intro(len(ranked), zip_=zip_, state=st, radius=fy_res.get("radius") or 0,
                                   tunes=tunes, main=main),
                "races": await _plan_call(lambda: _explore_hinted(user_id, shown)), "total": len(ranked),
                "web": web_state, "partial": bool(fy_res.get("partial")), "nationwide": bool(fy_res.get("nationwide")),
                "fy": len(fy_races), "web_n": len(web)}

    async def _rx_near(user_id: str, athlete: dict[str, Any], today: date, loc: dict[str, Any], city: str,
                       state: str, charge: Callable[[], Awaitable[bool]]) -> dict[str, Any]:
        near = await _x2_places(user_id, loc)
        groups, groups_state = [], "needs_location"
        if near["state"] == "off":
            groups_state = "off"
        elif city:
            groups, groups_state = await _x2_groups(user_id, city, state, today, search=True, charge=charge)
        groups = _local.order(groups, _local.relevant(athlete, await anyio.to_thread.run_sync(
            lambda: _x2_by_sport(user_id))))[:_rx.GROUPS_SHOWN]
        return {"places": near["places"][:_rx.PLACES_SHOWN], "groups": groups,
                "places_state": near["state"], "groups_state": groups_state}

    async def explore_rabbit(request: Request, user_id: str) -> Response:
        """{part?: "races"|"near", tap?: str}. Without ``part`` everything runs concurrently in
        one response; the app asks for both parts in parallel (same ``tap``) and shows each
        section as it lands."""
        assert chat is not None
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        part = body.get("part") if body.get("part") in ("races", "near") else None
        tap = body.get("tap") if isinstance(body.get("tap"), str) and re.fullmatch(r"[A-Za-z0-9_-]{6,40}", body["tap"]) \
            else secrets.token_hex(8)
        athlete = await _plan_call(lambda: _coach().athlete(user_id))
        events = await _plan_call(lambda: _events().list(user_id))
        today = _explore_today(user_id)
        loc, eff, inferred = await anyio.to_thread.run_sync(lambda: _x2_context(user_id, athlete, events, today))
        city, state = await _x2_area(loc)

        async def charge() -> bool:
            return await _rx_charge(user_id, tap, today)

        async def nothing() -> None:
            return None
        races, near = await asyncio.gather(
            _rx_races(user_id, athlete, events, today, loc, eff, city, state, charge) if part != "near" else nothing(),
            _rx_near(user_id, athlete, today, loc, city, state, charge) if part != "races" else nothing())
        n_races = len((races or {}).get("races") or [])
        n_places = len((near or {}).get("places") or [])
        n_groups = len((near or {}).get("groups") or [])
        log_event(logger, logging.INFO, "explore_rabbit", user_id=user_id, part=part or "all",
                  fy=(races or {}).get("fy", 0), web=(races or {}).get("web_n", 0), shown=n_races,
                  places=n_places, groups=n_groups, web_state=(races or {}).get("web"))
        out: dict[str, Any] = {"part": part or "all", "inferred": inferred, "location": _x2_loc_view(loc),
                               "summary": _rx.summary(n_races, n_places, n_groups),
                               "count": n_races + n_places + n_groups}
        if races is not None:
            out.update({k: v for k, v in races.items() if k not in ("fy", "web_n")})
        if near is not None:
            out.update(near)
        return JSONResponse(out)

    async def _x2_local(user_id: str, *, search: bool) -> dict[str, Any]:
        athlete = await _plan_call(lambda: _coach().athlete(user_id))
        today = _explore_today(user_id)
        r = await _x2_resolved(user_id)
        loc = r["loc"]
        cats = _local.relevant(athlete, await anyio.to_thread.run_sync(lambda: _x2_by_sport(user_id)))
        city, state = await _x2_area(loc)
        near = await _x2_places(user_id, loc)
        base = {"city": city, "state": state, "suggested": cats, "chips": _local.CHIPS, "kinds": _osm.KINDS,
                "places": near["places"], "places_state": near["state"], "disabled": near["state"] == "off",
                "location": _x2_loc_view(loc)}
        if near["state"] == "off":
            return {**base, "items": [], "groups_state": "off", "needs_location": False}
        if not city:
            return {**base, "items": [], "groups_state": "needs_location", "needs_location": not near["places"]}
        items, gstate = await _x2_groups(user_id, city, state, today, search=search)
        if search and gstate in ("unavailable", "failed") and not near["places"]:
            raise _UserError("Rabbit's web search didn't work just now. Try again in a minute."
                             if gstate == "failed" else "Web search isn't available on this server.",
                             502 if gstate == "failed" else 503)
        if search and gstate == "limit" and not near["places"]:
            raise _UserError("That's today's Rabbit searches used up. Try again tomorrow.", 429)
        return {**base, "items": _local.order(items, cats), "groups_state": gstate, "needs_location": False}

    async def explore_local(request: Request, user_id: str) -> Response:
        """Near you, with a web search for group activities when this city's week isn't cached."""
        return JSONResponse(await _x2_local(user_id, search=True))

    async def explore_nearby(request: Request, user_id: str) -> Response:
        """Near you without spending a web search (places + already-cached groups)."""
        return JSONResponse(await _x2_local(user_id, search=False))

    async def predict_get(request: Request, user_id: str) -> Response:
        q = request.query_params

        def num(k: str, hi: float = 10_000) -> float | None:
            v = q.get(k)
            if v in (None, ""):
                return None
            try:
                x = float(v)
            except ValueError:
                raise _UserError(f"{k} must be a number") from None
            if not 0 <= x <= hi:  # also rejects nan/inf
                raise _UserError(f"{k} is out of range")
            return x

        type_ = (q.get("type") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_. -]{0,20}", type_):
            raise _UserError("type isn't a race type")
        when = q.get("date") or ""
        if when:
            try:
                date.fromisoformat(when)
            except ValueError:
                raise _UserError("date must be YYYY-MM-DD") from None
        if not q.get("event_id"):
            d_km = num("distance_km", 1000)
            if not d_km:
                raise _UserError("Add a distance (distance_km) to get an estimate.")
            if d_km < 0.4:
                raise _UserError("Distance must be at least 0.4 km.")
            num("climb_m", 15_000)
            num("elevation_m", 6000)

        def run() -> dict[str, Any]:
            basis = _pred_basis(user_id)
            if q.get("event_id"):
                return _pred_event(user_id, str(q["event_id"])[:64])
            res = _predict.predict(basis, distance_km=num("distance_km", 1000), type_=type_,
                                   climb_m=num("climb_m", 15_000), elevation_m=num("elevation_m", 6000),
                                   terrain=q.get("terrain") if q.get("terrain") in _predict.TRAIL_X else None)
            if res and when:
                _pred_projection(user_id, res, when)
            return _pred_body(basis, res)
        return JSONResponse(await _plan_call(run))

    # Race finish-time estimates for calendar events (predict.py): the event's distance, climb,
    # altitude, heat and cutoff (racefit parsing) + the plan's forecast fitness for a labelled
    # "if you follow your plan" projection. Garmin + profile only, never Oura; not AI context.
    def _pred_body(basis: dict[str, Any], res: dict[str, Any] | None) -> dict[str, Any]:
        if not res:
            why = ("Connect Garmin or add a threshold pace, FTP or CSS in your profile to see estimates."
                   if not _predict.has_data(basis) else "No estimate for this kind of race yet.")
            return {"estimate": None, "reason": why}
        return _predict.response(res)

    def _pred_projection(uid: str, res: dict[str, Any], when: str) -> None:
        if chat is None or chat.agent.plans.get(uid) is None:
            return
        try:
            _predict.add_projection(res, chat.agent.stats.load(uid), when, _explore_today(uid))
        except Exception:  # Garmin down: no projection, the estimate still stands
            pass

    def _pred_event(uid: str, eid: str) -> dict[str, Any]:
        ev = _events().get(uid, eid)
        if not _ev_is_race(ev):
            raise _UserError("Finish estimates are for races.")
        basis = _pred_basis(uid)
        inp = _predict.event_inputs(ev)["kwargs"]
        if not inp.get("distance_km") and not inp.get("tri"):
            raise _UserError("Add a distance to this race to see an estimate.")
        res = _predict.predict_event(basis, ev, today=_explore_today(uid))
        if res and ev.get("date"):
            _pred_projection(uid, res, ev["date"])
        return _pred_body(basis, res)

    async def event_predict(request: Request, user_id: str) -> Response:
        eid = str(request.path_params["event_id"])[:64]
        return JSONResponse(await _plan_call(lambda: _pred_event(user_id, eid)))

    async def coach_event_predict(request: Request, user_id: str) -> Response:
        aid = _aid(request)
        await _plan_call(lambda: links.require(user_id, aid))
        eid = str(request.path_params["event_id"])[:64]
        return JSONResponse(await _plan_call(lambda: _pred_event(aid, eid)))

    # --------------------------------------------------------- challenges --
    # Weekly/monthly challenges (challenges.py): personal targets from the Garmin baseline,
    # live progress, XP via progress bonus keys "challenge:<id>", friend invites need an
    # active follow edge (social.py). Athletes only; coach accounts get 403 from _api.
    from . import challenges as _chal
    chal = (_chal.for_agent(chat.agent, follows=(soc.follows if soc is not None else None), names=_soc_name)
            if chat is not None and store is not None else None)

    def _challenge_bonus(uid: str, acts: list[dict[str, Any]], today: date) -> dict[str, int]:
        if chal is None:
            return {}
        try:
            return chal.refresh(uid, acts=acts, today=today)
        except Exception:
            return {}

    def _chal_api(handler: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
        async def inner(request: Request, user_id: str) -> Response:
            if chal is None:
                return _err(503, "Challenges aren't configured on this server.")
            try:
                return await handler(request, user_id)
            except _chal.ChallengeError as e:
                return _err(e.status, e.message)
            except _UserError as e:
                return _err(e.status, e.message)
        return _plan_api(inner, mutating=mutating) if plans is not None else _api(inner, mutating=mutating)

    async def challenges_get(request: Request, user_id: str) -> Response:
        assert chal is not None
        return JSONResponse(await _plan_call(lambda: chal.get(user_id)))

    async def challenges_join(request: Request, user_id: str) -> Response:
        assert chal is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        c = await _plan_call(lambda: chal.join(user_id, body.get("template"), body.get("period")))
        return JSONResponse({"challenge": c, **await _plan_call(lambda: chal.get(user_id))}, status_code=201)

    async def challenges_leave(request: Request, user_id: str) -> Response:
        assert chal is not None
        await anyio.to_thread.run_sync(lambda: chal.leave(user_id, request.path_params["cid"]))
        return JSONResponse({"ok": True})

    async def challenges_invite(request: Request, user_id: str) -> Response:
        assert chal is not None
        body = await read_json(request)
        ids = body.get("user_ids") if isinstance(body, dict) else None
        res = await anyio.to_thread.run_sync(lambda: chal.invite(user_id, request.path_params["cid"], ids))
        for to in ids or []:
            _social_push(to, f"challenge-invite:{to}:{user_id}", 86400, "Challenge invite",
                         f"{_soc_name(user_id)} invited you to a challenge on Rabbit.")
        return JSONResponse(res)

    async def challenges_accept(request: Request, user_id: str) -> Response:
        assert chal is not None
        c = await anyio.to_thread.run_sync(lambda: chal.accept(user_id, request.path_params["cid"]))
        return JSONResponse({"challenge": c}, status_code=201)

    async def challenges_decline(request: Request, user_id: str) -> Response:
        assert chal is not None
        await anyio.to_thread.run_sync(lambda: chal.decline(user_id, request.path_params["cid"]))
        return JSONResponse({"ok": True})

    # -------------------------------------------------------- race people --
    # Per-race people (racepeople.py, routes in racepeople_web.py): racing teammates, crew,
    # pacers, spectators (follow edge either way), linked coaches, a crew share link /app/r/.
    # Athletes only; deleting an event (any writer of the events doc) drops its people.
    from . import racepeople as _rpm, racepeople_web as _rpw
    race_routes: list[BaseRoute] = []
    if soc is not None and chat is not None and plans is not None and store is not None:
        rp = _rpm.RacePeople(
            store, create_event=lambda uid, f: chat.agent.events.create(uid, f),
            related=lambda a, b: soc.follows(a, b) or soc.follows(b, a), is_athlete=soc.is_athlete,
            athletes=auth.athlete_emails, code_owner=soc.code_owner,
            coach_emails=links.coach_emails, first_name=_soc_name)
        chat.agent._store.on_user_write(lambda uid, name: rp.sync(uid) if name == "events" else None)
        race_routes = _rpw.make_routes(
            rp=rp, soc=soc, links=links, plan_api=_plan_api, user_error=_UserError, host_ok=host_ok,
            base_url=settings.public_base_url, person=_soc_person, first_name=_soc_name, push=_social_push,
            moment=chat.agent.moments.post, grade=lambda u, e: (_readiness.get(u, e) if _readiness else {}).get("grade"),
            finish=_pred_event, today=plans.today, plan_of=plans.get,
            imperial=lambda u: chat.agent.coach.athlete(u).get("units") == "imperial",
            photo_resp=_photo_resp, photo_cache=_photo_cache, read_json=read_json)

    # ---------------------------------------------------------- community --
    # Community (community.py + clubs.py, routes in community_web.py): a calm feed of what people
    # choose to share (milestones are drafts until they tap Share), audiences friends / club /
    # public / only me, reactions + one-level comments, photos; clubs with meetups (RSVP,
    # reminder moments) and club challenges (challenges.py groups). Athletes only.
    from . import clubs as _clubs, community as _cmm, community_web as _cmw
    community_routes: list[BaseRoute] = []
    directory_routes: list[BaseRoute] = []
    if soc is not None and chat is not None and plans is not None and store is not None:
        _ag = chat.agent
        clb = _clubs.Clubs(store, is_athlete=soc.is_athlete, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                           blocked=soc.blocked_between, race_groups=rp.groups_of if race_routes else None)
        cm = _cmm.Community(store, social=soc, clubs=clb, now=_ag._now, moment=_ag.moments.post, name=_soc_name,
                            quiet=lambda u: _ag.moments.quiet(_ag._now(u)),
                            push=(lambda to, t, b: push.send(to, t, b, url="/app/?open=community")) if push else None)

        def _cm_scan(uid: str, *, workouts: bool) -> None:
            today = _ag._now(uid).date()
            acts: list[dict[str, Any]] = []
            if workouts:
                _, acts = _ag.stats.activities(uid)
                cm.scan_bests(uid, acts, today, imperial=_ag.coach.athlete(uid).get("units") == "imperial")
            # The raw doc, not events.list: this runs inside an events write (list may write).
            evs = list((store.user_doc(uid, "events").load().get("events") or {}).values())
            cm.scan_events(uid, evs, today, acts)

        def _cm_push(to: str, key: str, window: float, title: str, body: str) -> None:
            if push is None or not push_allowed(key, 1, window):
                return
            try:
                push.send(to, title, body[:140], url="/app/?open=community")
            except Exception as e:  # best effort
                log_event(logger, logging.WARNING, "community_push_failed", error=type(e).__name__)

        def _cm_home(uid: str) -> dict[str, str]:
            athlete = _ag.coach.athlete(uid)
            loc = _geo.resolve(athlete.get("interests") or {}, athlete, _geo.load_saved(store, uid))
            return {"city": str(loc.get("city") or ""), "state": str(loc.get("state") or "")}

        _ag.moments.on_milestone = cm.from_moment
        _ag.moments.after_workouts = lambda uid: _cm_scan(uid, workouts=True)
        _ag.moments.on_tick = cm.meetup_reminders
        _ag._store.on_user_write(lambda uid, name: _cm_scan(uid, workouts=False)
                                 if name == "events" and soc.is_athlete(uid) else None)
        community_routes = _cmw.make_routes(
            cm=cm, clubs=clb, plan_api=_plan_api, person=_soc_person, first_name=_soc_name, push=_cm_push,
            activities=lambda u: _ag.stats.activities(u), events=_ag.events.list,
            shares_races=lambda u: soc.settings(u)["races"], today=lambda u: _ag._now(u).date(), now=_ag._now,
            home=_cm_home, local_groups=_local_finder.cached, chal=chal, chal_error=_chal.ChallengeError,
            photo_resp=_photo_resp, photo_cache=_photo_cache, read_json=read_json, user_for=auth.user_for,
            host_ok=host_ok, origin=settings.public_base_url)

        # Clubs & leagues directory (clubdir.py, routes in clubdir_web.py): per metro ("City, ST"
        # only) web search for candidate pages + our polite RabbitBot crawler (robots.txt, 1 req/s
        # per host, SSRF guard, social sites link-only) + cheap-model extraction; monthly,
        # background, one metro at a time. Rabbit's local_clubs tool reads it.
        from . import clubdir as _cd, clubdir_web as _cdw
        _cd_struct = getattr(_ag._backend, "structured", None)
        _cd_extract = None if _cd_struct is None else (
            functools.partial(_cd_struct, model=settings.directory_model)
            if "model" in inspect.signature(_cd_struct).parameters else _cd_struct)
        directory = _cd.Directory(store, research=getattr(_ag._backend, "research", None), extract=_cd_extract,
                                  crawler=_cd.Crawler(user_agent=_cd.user_agent(settings.public_base_url)))

        def _cd_wrap(h: Handler, *, mutating: bool) -> Callable[[Request], Awaitable[Response]]:
            async def inner(request: Request, user_id: str) -> Response:
                try:
                    cm.require(user_id)
                except _cmm.CommunityError as e:
                    return JSONResponse({"error": e.message}, status_code=e.status)
                return await h(request, user_id)
            return _plan_api(inner, mutating=mutating)

        def _cd_role(uid: str, cid: str) -> str | None:
            try:
                return clb.get(uid, cid).get("role")
            except _clubs.ClubError:
                return None

        def _cd_lookup(uid: str, kind: str | None, weekday: str | None) -> dict[str, Any]:
            m = _cd.metro(**_cm_home(uid))
            if m is None:
                return {"listings": [], "note": "No home city saved. Ask them to add it in their training profile."}
            if directory.state(m) == "idle" and directory.due(m):
                try:  # we're on a worker thread of the turn: start the refresh on the event loop
                    anyio.from_thread.run_sync(lambda: directory.kick(m, uid=uid))
                except Exception:
                    pass
            return directory.lookup(m, now_local=_ag._now(uid), kind=kind, weekday=weekday)
        _ag.club_directory = _cd_lookup
        directory_routes = _cdw.make_routes(
            directory=directory, wrap=_cd_wrap, home=_cm_home, now=_ag._now, today=lambda u: _ag._now(u).date(),
            local_groups=_local_finder.cached, is_owner=auth.is_owner, club_role=_cd_role, read_json=read_json)

    # ------------------------------------------ up next + first visit --
    # upnext.py: the one "Up next" card on Rabbit home (wraps the Today card; a group run from
    # RSVP'd club meetups / the clubs directory for people with no plan or goal). Invite joins:
    # mutual follow with the inviter (social.connect_invited, blocks respected) + their moment
    # and push. First visit without Garmin: /app/api/firstvisit, and Garmin-only reads
    # (stats, load) answer 409 {code: "garmin_not_connected"} for a friendly empty state.
    from . import upnext as _upnext

    def _upnext_group(uid: str, now: datetime) -> dict[str, Any] | None:
        if not community_routes:
            return None
        meetups = clb.my_meetups(uid, now, days=2)
        listings: list[dict[str, Any]] = []
        m = _cd.metro(**_cm_home(uid)) if directory_routes else None
        if m is not None:
            listings = directory.view(m, now_local=now.replace(tzinfo=None), uid=uid)["listings"]
        return _upnext.pick_group(meetups, listings, now)

    async def upnext_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        svc = _upnext.UpNextService(chat.agent, auth.oura, group=_upnext_group, garmin=_garmin_connected)
        return JSONResponse(await svc.get(user_id))

    async def firstvisit_get(request: Request, user_id: str) -> Response:
        inviter = auth.access.inviter_of(user_id)
        connected = _garmin_connected(user_id)
        name = _soc_name(inviter) if inviter and soc is not None and soc.follows(user_id, inviter) else None
        return JSONResponse(_upnext.first_visit(garmin=connected, inviter=name))

    def _no_garmin(user_id: str) -> Response | None:
        """Garmin-only reads: a friendly empty state instead of a reconnect error."""
        if _garmin_connected(user_id):
            return None
        return JSONResponse(_upnext.NO_GARMIN, status_code=409)

    def _invite_joined(new_uid: str, inviter: str, name: str) -> None:
        if soc is None or not soc.connect_invited(inviter, new_uid):
            return
        first = (name.split() or ["A friend"])[0][:30]
        quiet = False
        if chat is not None:
            chat.agent.moments.friend_joined(inviter, first, new_uid)
            quiet = chat.agent.moments.quiet(chat.agent._now(inviter))
        if not quiet:
            _social_push(inviter, f"invite-joined:{inviter}:{new_uid}", 86400, "New friend on Rabbit",
                         f"{first} joined Rabbit from your invite.")

    home_routes: list[BaseRoute] = [
        Route("/app/api/upnext", _plan_api(upnext_get, mutating=False), methods=["GET"]),
        Route("/app/api/firstvisit", _api(firstvisit_get, mutating=False), methods=["GET"]),
    ]

    # ------------------------------------------------- invites + passkeys --
    # Invite links, joining with a passkey, passkey sign-in (access.py, passkey_web.py).
    from . import passkey_web as _pkw
    passkey_routes = _pkw.make_routes(auth=auth, api=_api, host_ok=host_ok, read_json=read_json,
                                      on_join=_invite_joined)

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
        *passkey_routes,
        *home_routes,
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
        *intent_routes,
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
        Route("/app/api/profile/photo", _photo_cache(_api(photo_get, mutating=False)), methods=["GET"]),
        Route("/app/api/profile/photo", photo_upload, methods=["POST"]),
        Route("/app/api/profile/photo", _api(photo_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/coach/athletes/{athlete_id}/photo",
              _photo_cache(_plan_api(coach_athlete_photo, mutating=False)), methods=["GET"]),
        Route("/app/api/explore", _plan_api(explore_get, mutating=False), methods=["GET"]),
        Route("/app/api/explore/defaults", _plan_api(explore_defaults, mutating=False), methods=["GET"]),
        Route("/app/api/explore/ai", _plan_api(explore_ai, mutating=True), methods=["POST"]),
        Route("/app/api/explore/add", _plan_api(explore_add, mutating=True), methods=["POST"]),
        Route("/app/api/explore/foryou", _plan_api(foryou_get, mutating=False), methods=["GET"]),
        Route("/app/api/explore/foryou/bucket", _plan_api(foryou_bucket, mutating=True), methods=["POST"]),
        Route("/app/api/explore/rabbit", _plan_api(explore_rabbit, mutating=True), methods=["POST"]),
        Route("/app/api/explore/local", _plan_api(explore_local, mutating=True), methods=["POST"]),
        Route("/app/api/explore/nearby", _plan_api(explore_nearby, mutating=False), methods=["GET"]),
        Route("/app/api/location", _plan_api(location_get, mutating=False), methods=["GET"]),
        Route("/app/api/location", _plan_api(location_post, mutating=True), methods=["POST"]),
        Route("/app/api/location/prefs", _plan_api(location_prefs, mutating=True), methods=["POST"]),
        Route("/app/api/location", _plan_api(location_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/predict", _plan_api(predict_get, mutating=False), methods=["GET"]),
        Route("/app/api/events/{event_id}/predict", _plan_api(event_predict, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/events/{event_id}/predict",
              _plan_api(coach_event_predict, mutating=False), methods=["GET"]),
        Route("/app/api/social", _social_api(social_get, mutating=False), methods=["GET"]),
        Route("/app/api/social/follow", _social_api(social_follow, mutating=True), methods=["POST"]),
        Route("/app/api/social/requests/{edge_id}/accept", _social_api(_edge_route(lambda u, e: soc.accept(u, e)), mutating=True), methods=["POST"]),
        Route("/app/api/social/requests/{edge_id}/decline", _social_api(_edge_route(lambda u, e: soc.decline(u, e)), mutating=True), methods=["POST"]),
        Route("/app/api/social/following/{edge_id}", _social_api(_edge_route(lambda u, e: soc.unfollow(u, e)), mutating=True), methods=["DELETE"]),
        Route("/app/api/social/followers/{edge_id}", _social_api(_edge_route(lambda u, e: soc.remove_follower(u, e)), mutating=True), methods=["DELETE"]),
        Route("/app/api/social/block", _social_api(social_block, mutating=True), methods=["POST"]),
        Route("/app/api/social/block/{other_id}", _social_api(social_unblock, mutating=True), methods=["DELETE"]),
        Route("/app/api/social/settings", _social_api(social_settings, mutating=True), methods=["PUT"]),
        Route("/app/api/social/code", _social_api(social_code, mutating=True), methods=["POST"]),
        Route("/app/api/social/feed", _social_api(social_feed, mutating=False), methods=["GET"]),
        Route("/app/api/social/badge", _social_api(social_badge, mutating=False), methods=["GET"]),
        Route("/app/api/social/seen", _social_api(social_seen, mutating=True), methods=["POST"]),
        Route("/app/api/social/kudos/{owner_id}/{activity_id}", _social_api(social_kudos, mutating=True), methods=["POST", "DELETE"]),
        Route("/app/api/social/cheers/{owner_id}/{activity_id}", _social_api(social_cheer, mutating=True), methods=["POST"]),
        Route("/app/api/social/cheers/{owner_id}/{activity_id}/{cheer_id}", _social_api(social_cheer_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/social/people/{person_id}", _social_api(social_person, mutating=False), methods=["GET"]),
        Route("/app/api/social/people/{person_id}/photo", _photo_cache(_social_api(social_photo, mutating=False)), methods=["GET"]),
        Route("/app/api/challenges", _chal_api(challenges_get, mutating=False), methods=["GET"]),
        Route("/app/api/challenges/join", _chal_api(challenges_join, mutating=True), methods=["POST"]),
        Route("/app/api/challenges/{cid}", _chal_api(challenges_leave, mutating=True), methods=["DELETE"]),
        Route("/app/api/challenges/{cid}/invite", _chal_api(challenges_invite, mutating=True), methods=["POST"]),
        Route("/app/api/challenges/{cid}/accept", _chal_api(challenges_accept, mutating=True), methods=["POST"]),
        Route("/app/api/challenges/{cid}/decline", _chal_api(challenges_decline, mutating=True), methods=["POST"]),
        Route("/app/api/insights", _plan_api(insights_get, mutating=False), methods=["GET"]),
        Route("/app/api/insights/{insight_id}/dismiss", _plan_api(insight_dismiss, mutating=True), methods=["POST"]),
        Route("/app/api/coach/athletes/{athlete_id}/insights", _plan_api(coach_athlete_insights, mutating=False),
              methods=["GET"]),
        Route("/app/api/events/{event_id}/strategy", _plan_api(event_strategy_get, mutating=False), methods=["GET"]),
        Route("/app/api/events/{event_id}/strategy", _plan_api(event_strategy_post, mutating=True), methods=["POST"]),
        Route("/app/api/events/{event_id}/readiness", _plan_api(event_readiness, mutating=False), methods=["GET"]),
        Route("/app/api/readiness", _plan_api(readiness_list, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/readiness", _plan_api(coach_athlete_readiness, mutating=False),
              methods=["GET"]),
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
        Route("/app/api/progress", _plan_api(progress_get, mutating=False), methods=["GET"]),
        Route("/app/api/progress/seen", _plan_api(progress_seen, mutating=True), methods=["POST"]),
        Route("/app/api/sync", _plan_api(sync_post, mutating=True), methods=["POST"]),
        Route("/app/api/today", _plan_api(today_get, mutating=False), methods=["GET"]),
        Route("/app/api/checkins", _plan_api(checkins_get, mutating=False), methods=["GET"]),
        Route("/app/api/checkins", _plan_api(checkin_create, mutating=True), methods=["POST"]),
        Route("/app/api/checkins/{checkin_id}", _plan_api(checkin_update, mutating=True), methods=["PATCH"]),
        Route("/app/api/checkins/{checkin_id}", _plan_api(checkin_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/recap", _plan_api(recap_get, mutating=False), methods=["GET"]),
        Route("/app/api/workout/today", _plan_api(workout_today_get, mutating=False), methods=["GET"]),
        Route("/app/api/workout/reaction", _plan_api(workout_reaction_get, mutating=False), methods=["GET"]),
        Route("/app/api/gear", _plan_api(gear_get, mutating=False), methods=["GET"]),
        Route("/app/api/gear", _plan_api(gear_create, mutating=True), methods=["POST"]),
        Route("/app/api/gear/import-garmin", _plan_api(gear_import, mutating=True), methods=["POST"]),
        Route("/app/api/gear/{gear_id}", _plan_api(gear_update, mutating=True), methods=["PATCH"]),
        Route("/app/api/gear/{gear_id}", _plan_api(gear_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/gear/{gear_id}/retire", _plan_api(gear_retire, mutating=True), methods=["POST"]),
        Route("/app/api/load", _plan_api(load_get, mutating=False), methods=["GET"]),
        Route("/app/api/coach/athletes/{athlete_id}/load", _plan_api(coach_athlete_load, mutating=False),
              methods=["GET"]),
        Route("/app/api/calendar", _plan_api(calendar_get, mutating=False), methods=["GET"]),
        Route("/app/api/calendar", _plan_api(calendar_delete, mutating=True), methods=["DELETE"]),
        Route("/app/auth/calendar/start", calendar_start, methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_get, mutating=False), methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/recovery", _plan_api(recovery_get, mutating=False), methods=["GET"]),
        Route("/app/auth/oura/start", oura_start, methods=["GET"]),
        Route("/app/auth/oura/callback", oura_callback, methods=["GET"]),
        Route("/app/api/plan/travel", _plan_api(travel_add, mutating=True), methods=["POST"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_get, mutating=False), methods=["GET"]),
        Route("/app/api/racepack", _plan_api(racepack_get, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_get, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_create, mutating=True), methods=["POST"]),
        Route("/app/api/share", _plan_api(share_delete, mutating=True), methods=["DELETE"]),
        Route("/app/s/{token}", share_page, methods=["GET"]),
        *race_routes,
        *directory_routes,
        *community_routes,
        Route("/app/privacy", legal_page, methods=["GET"]),
        Route("/app/about", legal_page, methods=["GET"]),
        Route("/app/terms", legal_page, methods=["GET"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_post, mutating=True), methods=["POST"]),
        Route("/app/api/plan/travel/{trip_id}", _plan_api(travel_remove, mutating=True), methods=["DELETE"]),
        Route("/app/api/coaches", _plan_api(coaches_get, mutating=False), methods=["GET"]),
        Route("/app/api/coaches", _plan_api(coach_invite, mutating=True), methods=["POST"]),
        Route("/app/api/coaches/directory", _plan_api(coach_directory, mutating=False), methods=["GET"]),
        Route("/app/api/coaches/directory/web", _plan_api(coach_directory_web, mutating=True), methods=["POST"]),
        Route("/app/api/coaches/directory/{coach_id}", _plan_api(coach_directory_one, mutating=False), methods=["GET"]),
        Route("/app/api/coaches/directory/{coach_id}/invite", _plan_api(coach_directory_invite, mutating=True),
              methods=["POST"]),
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
        *import_routes,
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
                   Route("/app/join/{token}", index, methods=["GET", "HEAD"]),  # SPA join page
                   Route("/app/index.html", index, methods=["GET", "HEAD"]),
                   Mount("/app", app=_Static(directory=WEB_DIST, html=True))]
    else:
        routes.append(Route("/app/{path:path}", not_built, methods=["GET"]))
    return routes
