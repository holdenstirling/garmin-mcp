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
from datetime import date, datetime, timedelta
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
from .idempotency import Idempotency, InFlight, Mismatch, valid_key as idem_key_ok
from .attachments import MAX_UPLOAD, AttachmentError, AttachmentStore
from .coaching import CoachError
from .config import Settings
from .garminlogin import Busy, Cooldown, LoginManager
from .logs import log_event
from .planbuilder import PlanError, build_plan
from .plans import public_plan
from . import planimport_web
from .planimport import ImportService
from .weekplan import MAX_PLAN_FILES_READ
from .events import KINDS, TYPE_DISTANCES, TYPES
from .events import MAIN_KINDS as _EV_MAIN_KINDS
from .events import is_race as _ev_is_race
from .events import EventStore as _EventStore
from .events import plan_links as _ev_plan_links
from . import calsub as _calsub
from . import area as _area
from . import body as _body_mod
from .coaches import CoachChat, CoachNotes
from .gcalendar import CalendarError, CalendarNotConnected
from .oura import OuraError, OuraNotConnected
from .whoop import WhoopError, WhoopNotConnected
from .sources import garmin_recovery, prefs_for, recovery_for, validate as validate_sources
from .adjust import propose as propose_adjustment
from . import planflow as _pf
from . import calinsights as _ci
from .races import RaceDesk as _RaceDesk
from . import racefit, racepack
from . import racechecklist as _rcl
from .profilephoto import MAX_PHOTO, PhotoError, PhotoStore
from .share import Shares
from .share import render as render_share
from . import legal
from . import account as _account
from . import consent as _consent
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
COACH_PATHS = ("/app/api/me", "/app/api/coach/", "/app/api/push/", "/app/api/consent", "/app/api/legal/",
               "/app/api/account/")
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
    "frame-src https://www.openstreetmap.org",  # Community -> clubs map: one OSM embed, on tap
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

    # Optional Idempotency-Key on mutating calls (idempotency.py): the app's outbox retries
    # a save with the same key, and the first 2xx answer is replayed instead of running twice.
    idem = Idempotency(auth._store)
    # Me -> Privacy & legal (account.py, consent.py): export / delete hooks, terms consent.
    acct = _account.AccountData(auth._store)
    consents = _consent.Consent(auth._store)

    async def _idem_settle(user_id: str, slot: str, raw: bytes, resp: Response | None) -> None:
        body = getattr(resp, "body", None)  # streamed responses have none: never replayed
        if resp is None or not isinstance(body, bytes) or "set-cookie" in resp.headers:
            idem.abort(user_id, slot)
            return
        status, media = resp.status_code, resp.media_type
        await anyio.to_thread.run_sync(lambda: idem.finish(user_id, slot, raw, status, body, media))

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
            key = request.headers.get("idempotency-key") if mutating else None
            slot: str | None = None
            raw = b""
            if key is not None:
                if not idem_key_ok(key):
                    return _err(400, "bad Idempotency-Key")
                raw = await request.body()
                try:
                    slot, cached = await anyio.to_thread.run_sync(
                        lambda: idem.begin(user_id, request.method, request.url.path, key, raw))
                except InFlight:
                    return JSONResponse({"error": "Still saving that. Try again in a moment.", "code": "in_flight"},
                                        status_code=409, headers={"Cache-Control": "no-store"})
                except Mismatch:
                    return _err(422, "That Idempotency-Key was already used for a different request.")
                if cached is not None:
                    return Response(Idempotency.replay_body(cached), status_code=int(cached["status"]),
                                    media_type=str(cached.get("type") or "application/json"),
                                    headers={"Cache-Control": "no-store", "Idempotent-Replayed": "true"})
            resp: Response | None = None
            try:
                resp = await handler(request, user_id)
            except (ValueError, json.JSONDecodeError):
                return _err(400, "bad request")
            except Exception as e:
                log_event(logger, logging.ERROR, "app_unexpected_error",
                          path=request.url.path, error=type(e).__name__)
                return _err(500, f"Internal error ({type(e).__name__})")
            finally:
                if slot is not None:
                    await _idem_settle(user_id, slot, raw, resp)
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
            "consent": consents.view(user_id),
            "role": "coach" if user_id.startswith("coach_") else "athlete",
            "can_invite": auth.can_invite(user_id),
            "owner": auth.is_owner(user_id),
            "coaching": len(auth.coach_links.athletes_of(user_id)),
            "coaches": len(auth.coach_links.coaches_of(user_id)),
            "oura": {"available": auth.oura is not None,
                     "connected": bool(auth.oura and auth.oura.connected(user_id))},
            "calendar": {"available": auth.calendar is not None,
                         "connected": bool(auth.calendar and auth.calendar.connected(user_id))},
            "whoop": {"available": auth.whoop is not None,
                      "connected": bool(auth.whoop and auth.whoop.connected(user_id))},
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
                "usage_off": p.get("usage_off") is True,  # usage.py: "Don't count my usage"
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
        for key in ("brief_enabled", "workout_feedback", "recap_enabled", "data_sources_asked", "moments_push", "usage_off"):
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
        if upd.get("usage_off") is True:
            store.user_doc(user_id, "usage").delete()  # usage.py: forget your first/last dates too
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
        if not any(str(body.get(k) or "").strip() for k in ("title", "event", "distance", "date")):
            return _err(400, "Give the goal a name, a distance or a date.")  # an empty body never replaces your goal
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
            same = coach.find_same_race(user_id, goal_in) if new_goal and cur is not None else None
            if same is not None and same["id"] == cur["id"]:
                coach.update_goal(user_id, cur["id"], goal_in)  # the same race again: no copy
            elif same is not None:
                plans.switch_goal(user_id, lambda: coach.activate_goal(user_id, same["id"]))
                coach.update_goal(user_id, same["id"], goal_in)
            elif new_goal:
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

    def _ev_view(evs: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
        """Events as the screens use them: repeat text / next dates / RRULE, Google's add link,
        and how each one shows up in the plan (events.plan_links)."""
        today = plans.today(user_id) if plans is not None else date.today()
        plan = plans.get(user_id) if plans is not None else None
        links = _ev_plan_links(evs, plan, today)
        return [_EventStore.decorate(e, today) | {"plan": links.get(e.get("id")), "google_url": _calsub.google_url(e)}
                for e in evs]

    def _events_resp(user_id: str, status: int = 200, **extra: Any) -> JSONResponse:
        evs = _ev_view(_events().list(user_id), user_id)
        if isinstance(extra.get("event"), dict):
            extra["event"] = next((e for e in evs if e.get("id") == extra["event"].get("id")), extra["event"])
        return JSONResponse({"events": evs,
                             "types": {t: list(TYPE_DISTANCES[t]) for t in TYPES}, "kinds": list(KINDS), **extra},
                            status_code=status)

    # Repeating events, calendar files and the private subscribe feed (recur.py, calsub.py).
    _cal_sub = _calsub.CalSub(store) if store is not None else None
    if _cal_sub is not None:
        acct.on_delete("calendar feed", _cal_sub.revoke)

    async def events_days(request: Request, user_id: str) -> Response:
        """{days: {YYYY-MM-DD: [event, ...]}} for ?from=&to= (at most 120 days; default the next 6 weeks)."""
        today = plans.today(user_id) if plans is not None else date.today()
        try:
            frm = date.fromisoformat(request.query_params.get("from") or today.isoformat())
            to = date.fromisoformat(request.query_params.get("to") or (frm + timedelta(days=41)).isoformat())
        except ValueError:
            raise _UserError("from and to must be YYYY-MM-DD") from None
        if to < frm or (to - frm).days > 120:
            raise _UserError("Ask for up to 120 days at a time.")
        days = await _plan_call(lambda: _events().days(user_id, frm, to))
        return JSONResponse({"from": frm.isoformat(), "to": to.isoformat(), "days": days})

    async def event_occurrence(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        eid, day = request.path_params["event_id"], request.path_params["day"]
        out = await _plan_call(lambda: _events().edit_occurrence(user_id, eid, day, body))
        return _events_resp(user_id, event=out["series"], one_off=out["event"])

    async def event_end(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        ev = await _plan_call(lambda: _events().end_series(user_id, request.path_params["event_id"], str(body.get("after") or "")))
        return _events_resp(user_id, event=ev)

    async def event_ics(request: Request, user_id: str) -> Response:
        ev = await _plan_call(lambda: _events().get(user_id, request.path_params["event_id"]))
        return Response(_calsub.event_ics(ev).encode("utf-8"), media_type="text/calendar; charset=utf-8", headers={
            "Content-Disposition": 'attachment; filename="rabbit-event.ics"', "Cache-Control": "no-store"})

    def _feed_url(token: str) -> dict[str, str]:
        base = settings.public_base_url.rstrip("/")
        https = f"{base}/app/cal/{token}.ics"
        return {"url": https, "webcal": "webcal://" + https.split("://", 1)[1]}

    async def cal_feed_get(request: Request, user_id: str) -> Response:
        if _cal_sub is None:
            raise _UserError("Calendar links aren't available on this server.", 503)
        st = await anyio.to_thread.run_sync(lambda: _cal_sub.status(user_id))
        return JSONResponse({"on": bool(st), "created": (st or {}).get("created")})

    async def cal_feed_post(request: Request, user_id: str) -> Response:
        if _cal_sub is None:
            raise _UserError("Calendar links aren't available on this server.", 503)
        token = await anyio.to_thread.run_sync(lambda: _cal_sub.create(user_id))
        return JSONResponse({"on": True, **_feed_url(token)})

    async def cal_feed_delete(request: Request, user_id: str) -> Response:
        if _cal_sub is not None:
            await anyio.to_thread.run_sync(lambda: _cal_sub.revoke(user_id))
        return JSONResponse({"on": False})

    async def cal_feed_public(request: Request) -> Response:
        """The subscribe feed itself: no sign-in (calendar apps can't), the secret token is the key."""
        raw = request.path_params["token"]
        token = raw[:-4] if raw.endswith(".ics") else raw
        uid = await anyio.to_thread.run_sync(lambda: _cal_sub.lookup(token)) if _cal_sub is not None else None
        if not uid or plans is None:
            return Response("Not found", status_code=404, media_type="text/plain")

        def build() -> str:
            today = plans.today(uid)
            return _calsub.feed_ics(_events().list(uid), plans.get(uid), today)
        body = await anyio.to_thread.run_sync(build)
        return Response(body.encode("utf-8"), media_type="text/calendar; charset=utf-8",
                        headers={"Cache-Control": "private, max-age=900", "X-Robots-Tag": "noindex"})

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
                activity_id=body.get("activity_id"), day=body.get("date"), feel=body.get("feel"),
                rpe=body.get("rpe"), pain=body.get("pain"))
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

    def _goal_plan_files(uid: str) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
        """The active race and its plan files (the newest few, as the weekly reader uses them)."""
        assert chat is not None
        goal = chat.agent.coach.active_goal(uid) or {}
        parts: list[tuple[str, bytes]] = []
        for f in (goal.get("plan_files") or [])[-MAX_PLAN_FILES_READ:]:
            got = chat.agent.attachments.load(uid, f.get("id")) if isinstance(f, dict) else None
            if got is not None:  # a removed file is skipped; the rest still convert
                meta, data = got
                parts.append((str(meta.get("name") or f.get("name") or "plan")[:120], data))
        return goal, parts

    if plans is not None and store is not None and chat is not None:
        import_routes = planimport_web.make_routes(
            importer=ImportService(store, plans, chat.agent.coach), plans=plans, coach=chat.agent.coach,
            links=links, auth=auth, settings=settings, host_ok=host_ok, plan_api=_plan_api,
            plan_call=_plan_call, user_error=_UserError, public_plan=public_plan, notify=_notify,
            coach_chat=coach_chat, structured=getattr(chat.agent._backend, "structured", None),
            now=chat.agent._now, moment=chat.agent.moments.coach_plan, goal_files=_goal_plan_files)

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

    # Calendar insights (calinsights.py): the next 14 days of plan vs Google Calendar, with
    # one-tap recommendations. Titles only show in travel recs, to the athlete; the AI's view of
    # the calendar is unchanged. Every applied change keeps an undo snapshot.
    async def _cal_insights(user_id: str) -> dict[str, Any]:
        cal = auth.calendar
        if cal is None:
            return {"connected": False, "available": False, "days": [], "recs": []}
        if not cal.connected(user_id):
            return {"connected": False, "available": True, "days": [], "recs": []}
        today = plans.today(user_id) if plans else date.today()
        prof = store.user_doc(user_id, "profile").load() if store else {}
        try:
            summ = await cal.summary(user_id, today, 42, prof.get("timezone") or default_tz)
        except CalendarNotConnected:
            return {"connected": False, "available": True, "days": [], "recs": []}
        except Exception as e:
            log_event(logger, logging.INFO, "cal_insights_read_failed", error=type(e).__name__)
            return {"connected": True, "available": True, "error": "Google Calendar didn't answer just now.",
                    "days": [], "recs": []}

        def run() -> dict[str, Any]:
            plan = plans.get(user_id) if plans else None
            status: dict[str, str] = {}
            if plan and chat is not None:
                try:
                    from .plancal import statuses as _sts
                    acts = chat.agent.stats.activities(user_id)[1]
                    status = {k: v.get("status", "planned") for k, v in _sts(plan, acts, today).items()}
                except Exception:
                    status = {}
            doc = store.user_doc(user_id, "calinsights").load() if store else {}
            dismissed = set((doc.get("dismissed") or {}).keys())
            return _ci.analyze(plan, summ, today, status=status, dismissed=dismissed)
        out = await anyio.to_thread.run_sync(run)
        return {"connected": True, "available": True, "today": today.isoformat(), **out}

    async def cal_insights_get(request: Request, user_id: str) -> Response:
        return JSONResponse(await _cal_insights(user_id))

    async def cal_insights_post(request: Request, user_id: str) -> Response:
        """{action: apply|dismiss|undo, id? | undo?}: apply re-finds the recommendation by id
        (409 when it no longer applies) and keeps the replaced plan for undo."""
        assert plans is not None and store is not None
        body = await read_json(request)
        if not isinstance(body, dict) or body.get("action") not in ("apply", "dismiss", "undo"):
            raise ValueError("body")
        doc = store.user_doc(user_id, "calinsights")
        if body["action"] == "dismiss":
            rid = str(body.get("id") or "")[:20]
            if not rid:
                raise ValueError("id")
            today = plans.today(user_id).isoformat()

            def put(d: dict[str, Any]) -> None:
                keep = {k: v for k, v in (d.get("dismissed") or {}).items()
                        if v >= (plans.today(user_id) - timedelta(days=21)).isoformat()}
                keep[rid] = today
                d["dismissed"] = dict(sorted(keep.items(), key=lambda kv: kv[1])[-200:])
            await anyio.to_thread.run_sync(lambda: doc.update(put))
            return JSONResponse({"ok": True})
        if body["action"] == "undo":
            snap = await anyio.to_thread.run_sync(lambda: store.user_doc(user_id, "calinsights-undo").load())
            goal = chat.agent.coach.active_goal(user_id) if chat is not None else None
            if not snap or snap.get("id") != body.get("undo") or not goal or snap.get("goal_id") != goal.get("id"):
                raise _UserError("That change can't be undone any more.", 409)
            plan = await _plan_call(lambda: plans.install(user_id, goal, snap["plan"]))
            await anyio.to_thread.run_sync(lambda: store.user_doc(user_id, "calinsights-undo").update(lambda d: d.clear()))
            return JSONResponse({"undone": True, "plan": public_plan(plan, plans.today(user_id))})
        rid = str(body.get("id") or "")
        res = await _cal_insights(user_id)
        rec = next((r for r in res.get("recs", []) if r["id"] == rid), None)
        if rec is None:
            raise _UserError("That suggestion doesn't apply any more. Take another look.", 409)
        act = rec["action"]
        if act["type"] not in ("time", "move", "ease"):
            raise _UserError("Open that one from the card.", 400)
        goal = chat.agent.coach.active_goal(user_id) if chat is not None else None
        before = plans.get(user_id)
        undo_id = f"ci{int(time.time() * 1000):x}"
        if before and goal:
            await anyio.to_thread.run_sync(lambda: store.user_doc(user_id, "calinsights-undo").update(
                lambda d: (d.clear(), d.update({"id": undo_id, "goal_id": goal["id"], "plan": before}))))
        if act["type"] == "time":
            plan = await _plan_call(lambda: plans.update_session(user_id, act["session_id"], {"time": act["time"]}))
        elif act["type"] == "move":
            patch = {"date": act["date"]} | ({"time": act["time"]} if act.get("time") else {})
            plan = await _plan_call(lambda: plans.update_session(user_id, act["session_id"], patch))
        else:
            plan = await _plan_call(lambda: plans.apply_adjustment(user_id, [{
                "action": "ease", "session_id": act["session_id"],
                "to": {"kind": "easy", "minutes": int(act.get("minutes") or 30)},
                "why": "Packed day on your calendar"}]))
        return JSONResponse({"applied": rec["kind"], "undo": undo_id if before and goal else None,
                             "plan": public_plan(plan, plans.today(user_id))})

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

    async def whoop_delete(request: Request, user_id: str) -> Response:
        if auth.whoop is not None:
            await auth.whoop.disconnect(user_id)
        return JSONResponse({"connected": False})

    async def whoop_start(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        if _is_coach_account(auth.user_for(request)):
            return _err(403, "Coach accounts can only use the coach view.")
        return await auth.start_whoop(request)

    async def whoop_callback(request: Request) -> Response:
        if not host_ok(request):
            return _err(400, "bad host")
        if _is_coach_account(auth.user_for(request)):
            return _err(403, "Coach accounts can only use the coach view.")
        return await auth.whoop_callback(request)

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

    # ------------------------------------------------- races / levers / check-in --
    # races.py: which race the plan trains for (each goal keeps its plan); planflow.py: the
    # Review / Adjust summaries and diffs, and the weekly "How was this week?" check-in.
    def _races() -> Any:
        assert chat is not None and plans is not None
        return _RaceDesk(_coach(), plans, chat.agent.events)

    async def races_get(request: Request, user_id: str) -> Response:
        assert plans is not None
        return JSONResponse(await _plan_call(lambda: _races().list(user_id, plans.today(user_id))))

    async def races_train(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise ValueError("body")
        out = await _plan_call(lambda: _races().train_for(user_id, body["id"]))
        return _plan_resp(user_id, plans.get(user_id), goal=out["goal"], has_plan=out["has_plan"],
                          races=await _plan_call(lambda: _races().list(user_id, plans.today(user_id))))

    async def races_tuneup(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("event_id"), str):
            raise ValueError("body")
        await _plan_call(lambda: _races().tune_up(user_id, body["event_id"]))
        return JSONResponse(await _plan_call(lambda: _races().list(user_id, plans.today(user_id))))

    async def plan_preview(request: Request, user_id: str) -> Response:
        """{athlete?, goal?, start_date?, new_goal?} -> {summary, diff?}: nothing is saved."""
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        a, g = body.get("athlete") or {}, body.get("goal") or None
        start = body.get("start_date")
        if not isinstance(a, dict) or (g is not None and not isinstance(g, dict)) or (start is not None and not isinstance(start, str)):
            raise ValueError("body")
        new_goal = body.get("new_goal") is True

        def run() -> dict[str, Any]:
            today = plans.today(user_id)
            new = plans.preview(user_id, a, g, start=start or None, new_goal=new_goal)
            out: dict[str, Any] = {"summary": _pf.plan_summary(new, today)}
            cur = None if new_goal else plans.get(user_id)
            if cur:
                out["diff"] = _pf.plan_diff(cur, new, today)
            return out
        return JSONResponse(await _plan_call(run))

    async def plan_levers(request: Request, user_id: str) -> Response:
        """{levers: {available_days?, long_day?, weekly_hours?, plan_intensity?}, start_date?}."""
        assert plans is not None
        body = await read_json(request)
        lv = body.get("levers") if isinstance(body, dict) else None
        start = body.get("start_date") if isinstance(body, dict) else None
        if not isinstance(lv, dict) or (start is not None and not isinstance(start, str)):
            raise ValueError("body")
        plan, undo = await _plan_call(lambda: plans.apply_levers(user_id, lv, start or None))
        return _plan_resp(user_id, plan, undo=undo)

    async def plan_levers_undo(request: Request, user_id: str) -> Response:
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise ValueError("body")
        return _plan_resp(user_id, await _plan_call(lambda: plans.undo_levers(user_id, body["id"])))

    async def weekcheck_get(request: Request, user_id: str) -> Response:
        assert plans is not None
        return JSONResponse(await _plan_call(lambda: _pf.checkin_due(
            plans.get(user_id), plans.today(user_id), plans.checkin_answered(user_id))))

    async def weekcheck_post(request: Request, user_id: str) -> Response:
        """{answers, action: preview|apply|skip, id?}: preview proposes next week's changes;
        apply re-checks the id (409 when the plan changed) and applies; skip just records."""
        assert plans is not None
        body = await read_json(request)
        if not isinstance(body, dict) or body.get("action") not in ("preview", "apply", "skip"):
            raise ValueError("body")
        try:
            answers = _pf.clean_answers(body.get("answers") or {})
        except ValueError as e:
            raise _UserError(f"Check your answer for {str(e).replace('_', ' ')}.") from None

        ci = await _cal_insights(user_id) if body["action"] == "preview" else {}

        def run() -> dict[str, Any] | JSONResponse:
            plan = plans.get(user_id)
            today = plans.today(user_id)
            prop = _pf.checkin_proposal(plan, today, answers)
            due = _pf.checkin_due(plan, today, plans.checkin_answered(user_id))
            week = due.get("week_start") or prop.get("week_start") or today.isoformat()
            if body["action"] == "preview":
                nxt = _pf.next_week(plan, today) if plan else None
                hint = _ci.week_hint(ci, nxt["start"]) if nxt and ci.get("recs") is not None else None
                return {"proposal": prop, "calendar_hint": hint}
            if body["action"] == "skip" or prop.get("status") != "suggest":
                plans.mark_checkin(user_id, week, answers)
                return {"proposal": prop, "applied": 0, "plan": public_plan(plan, today)}
            if prop.get("id") != body.get("id"):
                return _err(409, "Your plan changed since these suggestions. Take another look.")
            new = plans.apply_adjustment(user_id, prop["changes"])
            plans.mark_checkin(user_id, week, answers)
            return {"proposal": prop, "applied": len(prop["changes"]), "plan": public_plan(new, today)}
        out = await _plan_call(run)
        return out if isinstance(out, JSONResponse) else JSONResponse(out)

    # Body logs (body.py): fueling log + niggle tracker, athlete-entered, encrypted per user.
    _body = (_body_mod.BodyStore(store, today=lambda uid: chat.agent._now(uid).date())
             if store is not None and chat is not None else None)

    def _fuel_learned(user_id: str, distance: str | None) -> int | None:
        if _body is None:
            return None
        from .nutrition import race_target as _rt
        return _body_mod.learnings(_body.fuel_entries(user_id), _rt(distance))["learned_rate"]

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
        learned = await anyio.to_thread.run_sync(lambda: _fuel_learned(user_id, event.get("distance")))
        return JSONResponse(racepack.build(event, athlete, plans.get(user_id) if event.get("main") else None, today, wx,
                                           gear=gear, fuel_learned=learned))

    # ------------------------------------------------------------ race checklist --
    # racechecklist.py: a timeline checklist for each race / challenge / trip (12+ weeks out to
    # after the race); ticks, hidden items and your own items in the encrypted ``racechecklist``
    # doc. Athletes only (coach accounts get 403 through _api); only your own events.
    _checklists = _rcl.Checklists(store) if store is not None else None

    def _cl_event(user_id: str, event_id: str) -> dict[str, Any]:
        try:
            ev = _events().get(user_id, event_id)
        except CoachError:
            raise _UserError("That event isn't in your calendar.", 404) from None
        if not _rcl.applies(ev):
            raise _UserError("Checklists are for races, challenges and trips.")
        return ev

    def _cl_gear(user_id: str, ev: dict[str, Any]) -> list[dict[str, Any]]:
        """Worn-out / brand-new shoe warnings for the race's sport (best effort, never blocks)."""
        if gear_store is None or ev.get("kind") not in (None, "race"):
            return []
        try:
            views = _gear_items(user_id)[0]
            imperial = _coach().athlete(user_id).get("units") != "metric"
            from .gear import for_race
            return [g for g in for_race(views, ev.get("type") or "other", imperial=imperial) if g.get("warning")]
        except Exception:
            return []

    def _cl_view(user_id: str, ev: dict[str, Any]) -> dict[str, Any]:
        assert _checklists is not None and plans is not None
        return _rcl.view(ev, _checklists.state(user_id, ev["id"]), plans.today(user_id),
                         gear_warnings=_cl_gear(user_id, ev))

    async def checklist_get(request: Request, user_id: str) -> Response:
        if _checklists is None:
            raise _UserError("Checklists aren't available on this server.", 503)
        eid = request.path_params["event_id"]
        out = await anyio.to_thread.run_sync(lambda: _cl_view(user_id, _cl_event(user_id, eid)))
        return JSONResponse(out)

    async def checklist_post(request: Request, user_id: str) -> Response:
        if _checklists is None:
            raise _UserError("Checklists aren't available on this server.", 503)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("body")
        eid = request.path_params["event_id"]

        def run() -> dict[str, Any]:
            assert _checklists is not None
            ev = _cl_event(user_id, eid)
            try:
                _checklists.act(user_id, ev, body, gear_warnings=_cl_gear(user_id, ev))
            except _rcl.ChecklistError as e:
                raise _UserError(str(e)) from None
            return _cl_view(user_id, ev)
        return JSONResponse(await anyio.to_thread.run_sync(run))

    def _cl_upcoming(user_id: str) -> list[dict[str, Any]]:
        assert plans is not None
        today = plans.today(user_id).isoformat()
        week_ago = (plans.today(user_id) - timedelta(days=7)).isoformat()
        return [e for e in _events().list(user_id) if _rcl.applies(e) and (e.get("date") or "") >= week_ago
                and (e.get("date") or "") >= (today if e.get("kind") == "trip" else week_ago)]

    async def checklist_summary(request: Request, user_id: str) -> Response:
        """{event_id: {done, total}} for upcoming races, challenges and trips (race cards)."""
        if _checklists is None:
            return JSONResponse({"events": {}})

        def run() -> dict[str, Any]:
            out = {}
            for e in _cl_upcoming(user_id):
                v = _rcl.view(e, _checklists.state(user_id, e["id"]), plans.today(user_id))  # type: ignore[union-attr]
                out[e["id"]] = {"done": v["done"], "total": v["total"]}
            return {"events": out}
        return JSONResponse(await anyio.to_thread.run_sync(run))

    async def checklist_next(request: Request, user_id: str) -> Response:
        """Home: the next A/B race within 12 weeks, this window's progress and the next 2 items."""
        if _checklists is None:
            return JSONResponse({"next": None})

        def run() -> dict[str, Any]:
            assert plans is not None
            today = plans.today(user_id)
            races = [e for e in _cl_upcoming(user_id)
                     if (e.get("kind") or "race") == "race" and (e.get("main") or e.get("priority") in ("A", "B"))
                     and 0 <= (date.fromisoformat(e["date"]) - today).days <= 84]
            if not races:
                return {"next": None}
            ev = min(races, key=lambda e: (e["date"], not e.get("main")))
            return {"next": _rcl.summary(_cl_view(user_id, ev))}
        return JSONResponse(await anyio.to_thread.run_sync(run))

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
    if shares is not None:
        acct.on_delete("plan share link", shares.revoke)

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
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        page = legal.about(settings.contact_email) if slug == "about" else legal.page(
            slug if slug in legal.DOCS else "terms", settings.contact_email)
        return HTMLResponse(page, headers=headers)

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
    if soc is not None:
        acct.on_delete("follows", soc.forget_user)
        acct.add_extra("follows", soc.export_user)

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
        radius = await anyio.to_thread.run_sync(lambda: _area.radius_mi(store, uid))
        return JSONResponse({"saved": view, "device": view, "resolved": _x2_loc_view(r["loc"]),
                             "use_for_local": use, "radius_mi": radius, "radii_mi": list(_area.RADII_MI)})

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
        """{use_for_local?: bool, radius_mi?: 2|5|10|25|50} (at least one): Local's area radius
        lives here too (area.py)."""
        body = await read_json(request)
        if not isinstance(body, dict) or not ({"use_for_local", "radius_mi"} & set(body)) \
                or set(body) - {"use_for_local", "radius_mi"}:
            raise ValueError("body")
        if "use_for_local" in body and not isinstance(body["use_for_local"], bool):
            raise ValueError("body")
        if store is None:
            raise _UserError("Location isn't available on this server.", 503)
        if "radius_mi" in body:
            try:
                _area.clean_radius(body["radius_mi"])
            except ValueError as e:
                raise _UserError(str(e)) from None
            await anyio.to_thread.run_sync(lambda: _area.set_radius(store, user_id, body["radius_mi"]))
        if "use_for_local" in body:
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
            imperial=lambda u: chat.agent.coach.athlete(u).get("units") != "metric",
            photo_resp=_photo_resp, photo_cache=_photo_cache, read_json=read_json)

    # ---------------------------------------------------------- community --
    # Community (community.py + clubs.py, routes in community_web.py): a calm feed of what people
    # choose to share (milestones are drafts until they tap Share), audiences friends / club /
    # public / only me, reactions + one-level comments, photos; clubs with meetups (RSVP,
    # reminder moments) and club challenges (challenges.py groups). Athletes only.
    from . import clubs as _clubs, community as _cmm, community_web as _cmw
    community_routes: list[BaseRoute] = []
    directory_routes: list[BaseRoute] = []
    friends_routes: list[BaseRoute] = []
    from . import workouts as _workouts
    _ext_w = _workouts.ExternalWorkouts(store) if store is not None else None  # Oura etc. (display-only)
    _ext_feed: dict[str, Any] = {}  # workouts.py imports -> community auto-share (set below)
    from . import applehealth as _ah
    # Apple Watch: the athlete's iPhone Shortcut posts workouts with a personal import key.
    _ah_keys = _ah.ImportKeys(store) if store is not None else None
    if _ah_keys is not None:
        acct.on_delete("apple health key", _ah_keys.revoke)
    if soc is not None and chat is not None and plans is not None and store is not None:
        _ag = chat.agent
        clb = _clubs.Clubs(store, is_athlete=soc.is_athlete, related=lambda a, b: soc.follows(a, b) or soc.follows(b, a),
                           blocked=soc.blocked_between, race_groups=rp.groups_of if race_routes else None)
        acct.on_delete("clubs", lambda u: [clb.leave(u, c) for c in clb.ids_of(u) if not str(c).startswith("r-")])
        acct.add_extra("clubs", lambda u: [{"id": c, "name": clb.name_of(c, u)} for c in clb.ids_of(u)])
        cm = _cmm.Community(store, social=soc, clubs=clb, now=_ag._now, moment=_ag.moments.post, name=_soc_name,
                            quiet=lambda u: _ag.moments.quiet(_ag._now(u)),
                            push=(lambda to, t, b: push.send(to, t, b, url="/app/?open=community")) if push else None)
        _ext_feed["share"] = cm.auto_share_external

        def _cm_workouts(uid: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            """Garmin activities and other sources' workouts, for the share-on backfill."""
            acts = _ag.stats.activities(uid)[1] if _garmin_connected(uid) else []
            ext = _ext_w.visible(uid, acts) if _ext_w is not None else []
            return acts, ext
        cm.workouts_of = _cm_workouts

        def _cm_scan(uid: str, *, workouts: bool) -> None:
            today = _ag._now(uid).date()
            acts: list[dict[str, Any]] = []
            if workouts:
                _, acts = _ag.stats.activities(uid)
                cm.auto_share_workouts(uid, acts, today)  # "Share my workouts with friends"
                cm.backfill(uid)  # only if sharing just turned on and the first try failed
                cm.scan_bests(uid, acts, today, imperial=_ag.coach.athlete(uid).get("units") != "metric")
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

        def _cm_wants_share(uid: str) -> bool:
            try:
                return _garmin_connected(uid) and cm.sharing_workouts(cm.settings(uid))
            except Exception:
                return False

        def _cm_share_scan(uid: str) -> None:
            if _cm_wants_share(uid):
                _cm_scan(uid, workouts=True)
        _ag.moments.wants_share = _cm_wants_share
        _ag.moments.share_scan = _cm_share_scan
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

        # App icon badge + one-tap home actions (unread.py, quickactions.py, friends_web.py):
        # every push carries the unread total as `badge` (sw.js sets the app badge).
        from . import friends_web as _fw, quickactions as _qa, unread as _unr
        _unread = _unr.Unread(store, community=cm, social=soc, clubs=clb, coach_chat=coach_chat)
        if push is not None:
            push.badge_for = _unread.total
        _quick = _qa.QuickActions(
            now=_ag._now, clock=time.time, activities=lambda u: _ag.stats.activities(u),
            checkins=lambda u: _ag.checkins.list(u, 3), meetups=lambda u, n: clb.my_meetups(u, n, days=7),
            friend_posts=lambda u: cm.feed(u, scope="friends")["items"], name=_soc_name,
            plan=plans.get, garmin=_garmin_connected)
        friends_routes = _fw.make_routes(unread=_unread, quick=_quick, api=_api, read_json=read_json)

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
                                  crawler=_cd.Crawler(user_agent=_cd.user_agent(settings.public_base_url)),
                                  geocoder=_geocoder)
        # "I'm going" per listing occurrence (clubgoing.py) + its evening-before Rabbit moment.
        from . import clubgoing as _cgo
        _cd_going = _cgo.Going(store, follows=soc.follows, blocked=soc.blocked_between, is_athlete=soc.is_athlete,
                               person=_soc_person, moment=_ag.moments.post, now=_ag._now)
        _cd_tick_prev = _ag.moments.on_tick

        def _cd_tick(uid: str) -> None:
            if _cd_tick_prev is not None:
                _cd_tick_prev(uid)
            _cd_going.remind(uid)
        _ag.moments.on_tick = _cd_tick

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
        # Partners (partners.py): owner-curated clubs/shops promoted, labelled "Partner", to people
        # in their metros (Clubs near you, club search, Search everywhere). Routes in clubdir_web.
        from . import partners as _pt
        partners = _pt.Partners(store, is_owner=auth.is_owner)
        def _cd_area(uid: str) -> dict[str, Any]:
            """My area for Local / Discover (area.py): my saved spot ("Use my location" or a zip)
            when location is on for local picks, plus my radius."""
            saved = _geo.load_saved(store, uid) if _geo.use_for_local(store, uid) else None
            lat, lon = (saved or {}).get("lat"), (saved or {}).get("lon")
            point = isinstance(lat, int | float) and isinstance(lon, int | float)
            return {"center": (float(lat), float(lon)) if point else None,  # type: ignore[arg-type]
                    "label": _geo.label(saved) if point and saved else "",
                    "source": (saved or {}).get("source") if point else None,
                    "radius_mi": _area.radius_mi(store, uid)}

        directory_routes = _cdw.make_routes(
            directory=directory, wrap=_cd_wrap, home=_cm_home, now=_ag._now, today=lambda u: _ag._now(u).date(),
            local_groups=_local_finder.cached, is_owner=auth.is_owner, club_role=_cd_role, read_json=read_json,
            going=_cd_going, partners=partners, area=_cd_area,
            zips=lambda uid: [z for z in [(_geo.load_saved(store, uid) or {}).get("zip")] if z])

        # Search everywhere (search.py): GET /app/api/search?q= -> people / clubs / events /
        # sessions / workouts, from stored and cached data only (no Garmin call per keystroke).
        from . import search as _srch

        def _srch_dir(uid: str) -> list[dict[str, Any]]:
            m = _cd.metro(**_cm_home(uid))
            return directory.view(m, now_local=_ag._now(uid), uid=uid)["listings"] if m else []
        def _srch_partners(uid: str, q: str) -> list[dict[str, Any]]:
            loc = _cm_home(uid)
            m = _cd.metro(loc.get("city"), loc.get("state"))
            qz = q.strip()
            if _pt.zip_metro(qz):  # a Denver-area zip: the sponsored partner for that area
                card = partners.sponsored(uid, "search", "", "", [qz])
                return [card] if card else []
            rows = partners.near(m.city, m.state, query=q) if m else []
            if not rows:
                return []
            # Promoted in search: disclosed as sponsored (unless hidden here for 30 days).
            card = partners.sponsored(uid, "search", m.city, m.state) if m else None
            out = []
            for r in rows:
                if r.get("sponsored"):
                    if card is None or card["id"] != r["id"]:
                        continue
                    r = card
                out.append(r)
            return out
        # Public events (publicevents.py): events their owner marked Public, findable by people in
        # the same area (Local, search), with "I'm going". Re-synced on every events write.
        from . import publicevents as _pev
        _pubev = _pev.PublicEvents(store, blocked=soc.blocked_between)
        acct.on_delete("public events", lambda u: _pubev.sync(u, [], {}))

        def _pubev_sync(uid: str) -> None:
            try:
                evs = list((store.user_doc(uid, "events").load().get("events") or {}).values())
                _pubev.sync(uid, evs, _cm_home(uid))
            except Exception as e:  # never break the event save
                log_event(logger, logging.WARNING, "public_events_sync_failed", error=type(e).__name__)
        _ag._store.on_user_write(lambda uid, name: _pubev_sync(uid) if name == "events" and soc.is_athlete(uid) else None)

        def _pubev_near(uid: str, q: str = "", activity: str = "") -> list[dict[str, Any]]:
            return _pubev.nearby(uid, _cm_home(uid), _ag._now(uid).date(), q=q, activity=activity,
                                 name=lambda o: (_soc_person(o) or {}).get("name"))

        async def public_events_get(request: Request, user_id: str) -> Response:
            q = (request.query_params.get("q") or "")[:60]
            act = request.query_params.get("activity") or ""
            if act and act not in _pev.sports.IDS:
                return _err(400, "Unknown sport.")
            home = await anyio.to_thread.run_sync(_cm_home, user_id)
            rows = await anyio.to_thread.run_sync(lambda: _pubev_near(user_id, q, act))
            label = ", ".join(x for x in (home.get("city"), home.get("state")) if x)
            return JSONResponse({"events": rows, "area": label})

        async def public_events_going(request: Request, user_id: str) -> Response:
            body = await read_json(request)
            if not isinstance(body, dict) or not isinstance(body.get("key"), str) or not isinstance(body.get("going"), bool):
                return _err(400, "Send {key, going}.")
            key, going = body["key"][:120], body["going"]
            try:
                out = await anyio.to_thread.run_sync(lambda: _pubev.set_going(user_id, key, going, _cm_home(user_id)))
            except _pev.PublicEventError as e:
                return _err(e.status, str(e))
            return JSONResponse(out)
        friends_routes += [
            Route("/app/api/events/public", _api(public_events_get, mutating=False), methods=["GET"]),
            Route("/app/api/events/public/going", _api(public_events_going, mutating=True), methods=["POST"]),
        ]

        _search = _srch.Search(
            today=lambda u: _ag._now(u).date(), partners=_srch_partners, public_events=_pubev_near,
            people=lambda u: {"following": [{"user_id": x} for x in soc.following_ids(u)],
                              "followers": [{"user_id": x} for x in soc.follower_ids(u)]},
            person=_soc_person, clubs=lambda u, q: clb.overview(u, q=q), directory=_srch_dir,
            events=_ag.events.list, plan=plans.get, activities=lambda u: _ag.stats.activities(u)[1])

        async def search_get(request: Request, user_id: str) -> Response:
            q = request.query_params.get("q", "")
            return JSONResponse(await anyio.to_thread.run_sync(_search.run, user_id, q))
        friends_routes.append(Route("/app/api/search", _api(search_get, mutating=False), methods=["GET"]))

        # Community v2 (featured.py, feedgroups.py, routes in feed2_web.py): owner-featured clubs,
        # feed groups (audience grp:<gid>), friends' latest for Rabbit home, richer auto-shared
        # workout cards (lap shape + reward headline). Athletes only.
        from . import featured as _ft, feed2_web as _f2w, feedgroups as _fg, foryou as _f2fy
        _groups = _fg.FeedGroups(store, is_athlete=soc.is_athlete, follows=soc.follows, blocked=soc.blocked_between)
        cm.groups = _groups

        def _f2_splits(uid: str, aid: int) -> list[dict[str, Any]]:
            return _cmm.splits_from(_ag._service.read_uncached(uid, "get_activity_splits", {"activity_id": str(aid)}))

        def _f2_headline(uid: str, aid: int) -> str | None:
            rw = getattr(_ag, "rewards", None)
            r = rw.get(uid, aid) if rw is not None else None
            return ((r or {}).get("headline") or {}).get("text")
        cm.splits, cm.headline = _f2_splits, _f2_headline

        def _f2_listing(city: str, state: str, lid: str, viewer: str) -> dict[str, Any] | None:
            m = _cd.metro(city, state)
            if m is None:
                return None
            try:
                row = directory.get(m, lid, now_local=_ag._now(viewer), uid=viewer)
            except _cd.DirectoryError:
                return None
            _cd_going.attach(viewer, m, [row])
            return {"listing_id": row["id"], "name": row["name"], "listing_kind": row["kind"],
                    "kind_label": row["kind_label"], "city": m.city, "state": m.state,
                    "description": row["description"], "next": row["next"], "going": row.get("going"),
                    "join_url": row["join_url"], "link_only": row["link_only"], "members": None,
                    "same_metro": _cd.metro(**_cm_home(viewer)) == m}

        def _f2_listing_ref(uid: str, lid: str) -> dict[str, str] | None:
            m = _cd.metro(**_cm_home(uid))
            return {"city": m.city, "state": m.state, "listing_id": lid} if m is not None else None

        def _f2_sports(uid: str) -> set[str]:
            main = _f2fy.main_race(_ag.events.list(uid), _ag._now(uid).date())
            return _ft.athlete_sports(_ag.coach.athlete(uid), (main or {}).get("type"))

        def _f2_notify(to: str, key: str, title: str, body: str) -> None:
            if not _ag.moments.quiet(_ag._now(to)):
                _cm_push(to, key, 3600, title, body)
        # Direct messages (messages.py, routes in messages_web.py): 1:1 and small group chats
        # between athletes; mutual follows and club / group mates write freely, anyone else sends
        # a request. Shared workouts and events are snapshots from the sender's own data (sport,
        # title, date, distance, time, pace; never heart rate, location or Oura).
        from . import messages as _dmm, messages_web as _dmw
        from .plancal import _dur_min as _dm_min, sport_of as _dm_sport

        def _dm_circle(a: str, b: str) -> bool:
            if set(_groups.ids_of(a)) & set(_groups.ids_of(b)):
                return True
            return bool(set(clb.ids_of(a)) & set(clb.ids_of(b)))

        def _dm_card(uid: str, ref: dict[str, Any]) -> dict[str, Any] | None:
            kind, rid = ref.get("kind"), ref.get("id")
            if ref.get("type") == "event":
                ev = next((e for e in _ag.events.list(uid) if e.get("id") == rid), None) if isinstance(rid, str) else None
                if ev is None:
                    return None
                return {"name": str(ev.get("name") or "Event")[:120], "date": ev.get("date"), "time": ev.get("time"),
                        "neighborhood": ev.get("neighborhood") or "", "event_type": ev.get("type"),
                        "activity": ev.get("activity"), "repeat_text": ev.get("repeat_text") or ""}
            if kind == "session" and isinstance(rid, str):
                plan = plans.get(uid)
                hit = next(((d, x) for _, d, x in iter_sessions(plan or {}) if x.get("id") == rid), None) if plan else None
                if hit is None:
                    return None
                d, x = hit
                return {"title": str(x.get("title") or "Workout")[:80], "sport": x.get("sport"), "date": d,
                        "minutes": x.get("minutes"), "km": None, "pace": None, "planned": True}
            if kind == "activity" and rid is not None:
                _, acts = _ag.stats.activities(uid)
                a = next((x for x in acts if str(x.get("activity_id")) == str(rid)), None)
                if a is None:
                    return None
                km = a.get("distance_km") if isinstance(a.get("distance_km"), int | float) else None
                mins = _dm_min(a.get("duration"))
                pace = round(mins * 60 / km) if km and mins and km > 0.2 else None
                return {"title": str(a.get("name") or "Workout")[:80], "sport": _dm_sport(a.get("sport")),
                        "date": str(a.get("date") or "")[:10], "minutes": mins, "km": km, "pace": pace, "planned": False}
            return None

        def _dm_candidates(uid: str) -> list[str]:
            ids = list(soc.following_ids(uid, limit=200)) + soc.follower_ids(uid)
            for cid in clb.ids_of(uid):
                try:
                    ids += clb.member_ids(cid, uid)
                except Exception:
                    pass
            for gid in _groups.ids_of(uid):
                ids += _groups.member_ids(gid, uid)
            return ids

        def _dm_notify(to: str, key: str, title: str, body: str, url: str) -> None:
            if push is None or _ag.moments.quiet(_ag._now(to)) or not push_allowed(key, 1, 60):
                return
            try:
                push.send(to, title, body[:140], url=url)
            except Exception as e:  # best effort
                log_event(logger, logging.WARNING, "dm_push_failed", error=type(e).__name__)
        dms = _dmm.Messages(store, is_athlete=soc.is_athlete, follows=soc.follows, blocked=soc.blocked_between,
                            shared_circle=_dm_circle, card_for=_dm_card)
        acct.on_delete("messages", dms.forget_user)
        acct.add_extra("messages", dms.export_user)
        community_routes += _dmw.make_routes(dm=dms, wrap=_cd_wrap, read_json=read_json, person=_soc_person,
                                             candidates=_dm_candidates, notify=_dm_notify, first_name=_soc_name)

        # Training buddies (buddies.py, routes in buddies_web.py): opt-in matching by area, easy
        # pace band and usual times; "Say hi" opens a DM (a request unless already connected).
        # Others see a pace band, slots, race, note, city and a rounded distance: never
        # coordinates, heart rate or single workouts.
        from . import buddies as _bud, buddies_web as _budw

        def _bud_say(uid: str, other: str, text: str) -> dict[str, Any]:
            conv = dms.start(uid, [other])
            msg, to = dms.send(uid, conv["id"], text)
            for p in to:
                _dm_notify(p, f"dm:{p}:{conv['id']}", _soc_name(uid), (msg.get("text") or "")[:140],
                           f"/app/?open=dm&c={conv['id']}")
            return {"id": conv["id"]}
        buddies = _bud.Buddies(store, is_athlete=soc.is_athlete, blocked=soc.blocked_between, follows=soc.follows,
                               activities=lambda u: _ag.stats.activities(u), area=_cd_area, home=_cm_home,
                               person=_soc_person, first_name=_soc_name, say=_bud_say)
        acct.on_delete("buddy profile", buddies.delete)
        community_routes += _budw.make_routes(buddies=buddies, wrap=_cd_wrap, read_json=read_json)

        featured = _ft.Featured(store, is_owner=auth.is_owner,
                                club_card=lambda c, u: clb.featured_card(c, u, _ag._now(u)), listing_card=_f2_listing)
        community_routes += _f2w.make_routes(
            cm=cm, groups=_groups, featured=featured, wrap=_cd_wrap, read_json=read_json, person=_soc_person,
            first_name=_soc_name, today=lambda u: _ag._now(u).date(), home=_cm_home, sports=_f2_sports,
            listing_ref=_f2_listing_ref, notify=_f2_notify)

        # Connected screens (people.py, routes in people_web.py): person profiles (only people you
        # may already see; workouts per their sharing settings), the notifications inbox, the
        # Home "Friends today" strip, "Who else is doing this?" and each club's group chat.
        from . import people as _ppl, people_web as _pplw

        def _ppl_club_chat(uid: str, cid: str) -> dict[str, Any]:
            if not clb.is_member(cid, uid):
                raise _ppl.PeopleError("Join the club to see its chat.", 404)
            return dms.club_chat(uid, cid, clb.name_of(cid, uid) or "Club chat", clb.member_ids(cid, uid))

        def _ppl_on_follow(uid: str, other: str, res: dict[str, Any]) -> None:
            if res.get("notify"):
                title = "New follower" if res.get("status") == "active" else "Follow request"
                verb = "is now following" if res.get("status") == "active" else "wants to follow"
                _social_push(res["notify"], f"social-follow:{res['notify']}:{uid}", 86400, title,
                             f"{_soc_name(uid)} {verb} your training on Rabbit.")
        people_svc = _ppl.People(
            store, soc=soc, feed=soc_feed, clubs=clb, dms=dms, related=cm.related, person=_soc_person,
            name=_soc_name, home=_cm_home, today=lambda u: _ag._now(u).date(),
            public_events=lambda: (_pubev._doc.load().get("items") or {}),
            events=lambda u: _ag.events.list(u), post_unread=lambda u: (cm._mine(u).load().get("unread") or {}))
        community_routes += _pplw.make_routes(people=people_svc, wrap=_cd_wrap, read_json=read_json,
                                              club_chat=_ppl_club_chat, on_follow=_ppl_on_follow)

    # ------------------------------------------------- shared training blocks --
    # blocks.py (routes in blocks_web.py): friends or a club start the same N-week block. Each
    # member gets their OWN plan from the plan builder on the same weeks (replacing a goal only
    # with confirm_replace); the block page shows done/planned per member, a group ring, the
    # block feed (Community posts to club:b-<id> via clubs.block_groups) and the Sunday check-in;
    # Monday recap moments and coalesced cheers. Moments.on_tick chain. Athletes only.
    from . import blocks as _blk, blocks_web as _blkw
    block_routes: list[BaseRoute] = []
    if community_routes and chat is not None and plans is not None and soc is not None:
        from . import weekring as _blk_wr
        _bag = chat.agent

        def _blk_week(uid: str, day: date) -> tuple[int, int]:
            _, acts = _bag.stats.activities(uid)
            r = _blk_wr.ring(plans.get(uid), acts, day)
            return int(r["done"]), int(r["target"])

        def _blk_admin(cid: str, uid: str) -> bool:
            try:
                clb.can_start_challenge(uid, cid)
                return isinstance(cid, str) and cid.startswith("g")
            except _clubs.ClubError:
                return False
        blocks = _blk.Blocks(
            store, now=_bag._now, is_athlete=soc.is_athlete, follows=soc.follows, blocked=soc.blocked_between,
            names=_soc_name, week=_blk_week, events=_bag.events.list,
            plan=_blk.PlanHooks(coach=_bag.coach, plans=plans, events=_bag.events, now=_bag._now),
            club_member=clb.is_member, club_admin=_blk_admin, club_name=lambda c, u: clb.name_of(c, u),
            moment=_bag.moments.post)
        clb.block_groups = blocks.groups_of
        _blk_tick_prev = _bag.moments.on_tick

        def _blk_tick(uid: str) -> None:
            if _blk_tick_prev is not None:
                _blk_tick_prev(uid)
            blocks.tick(uid)
        _bag.moments.on_tick = _blk_tick
        block_routes = _blkw.make_routes(
            blocks=blocks, plan_api=_plan_api, read_json=read_json, person=_soc_person,
            friends=lambda u: [x for x in soc.following_ids(u, limit=200) if blocks.mutual(u, x)],
            admin_clubs=lambda u: [{"id": c, "name": clb.name_of(c, u) or "Club"} for c in clb.ids_of(u)
                                   if _blk_admin(c, u)],
            push=_social_push)

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

    # ------------------------------------------- progress trends + celebrations --
    # trends.py: Progress charts (weekly distance vs plan goal, pace at easy effort, sleep vs
    # load; Garmin nights kept in the "sleeplog" doc, Oura nights read live and never stored).
    # celebrate.py: full-screen moments for race finishes and finished blocks, once per
    # achievement across devices. Routes in bloom_web.py. Never in Rabbit's context.
    from . import bloom_web as _bloomw, celebrate as _cel, trends as _trends
    bloom_routes: list[BaseRoute] = []
    if chat is not None and store is not None:
        _tg = chat.agent
        _sleeplog = _trends.SleepLog(store)

        def _trend_inputs(uid: str) -> dict[str, Any]:
            today, acts = _tg.stats.activities(uid)
            athlete = _tg.coach.athlete(uid)
            connected = bool(auth.oura is not None and auth.oura.connected(uid))
            prefs, _ = prefs_for(store, uid, connected)
            src = _src_effective(prefs, connected, "sleep")
            nights: dict[str, float] = {}
            if src == "oura" and auth.oura is not None:
                try:
                    rec = anyio.from_thread.run(auth.oura.recovery, uid, today, _trends.SLEEP_DAYS)
                    nights = {str(r["date"])[:10]: float(r["sleep_hours"]) for r in (rec or {}).get("days") or []
                              if isinstance(r, dict) and isinstance(r.get("sleep_hours"), int | float)}
                except Exception:
                    nights = {}
            else:
                try:
                    rec = garmin_recovery(_tg._service, uid, today)
                except Exception:
                    rec = None
                nights = _sleeplog.merge(uid, (rec or {}).get("days"))
            return {"acts": acts, "today": today, "plan": plans.get(uid) if plans is not None else None,
                    "athlete": athlete, "nights": nights, "sleep_source": src if nights or src else None}

        def _cel_acts(uid: str) -> list[dict[str, Any]]:
            return _tg.stats.activities(uid)[1]
        bloom_routes = _bloomw.make_routes(
            trends=_trends.TrendsService(_trend_inputs),
            celebrations=_cel.Celebrations(store, now=_tg._now, events=_tg.events.list, acts=_cel_acts,
                                           imperial=lambda u: _tg.coach.athlete(u).get("units") != "metric"),
            api=_api, no_garmin=_no_garmin)

    # ------------------------------------------------------- race-week mode --
    # raceweek.py (routes in raceweek_web.py): the 7 days before an A/B/main race take over the
    # Rabbit home; pacing plan, course, packing (stored per event), nutrition, logistics, an
    # opt-in "Track me" for mutual followers (status only, no location), race-week moments
    # (replacing the countdown's week/eve lines) and friend pushes at start/finish. Athletes only.
    from . import raceweek as _rwk, raceweek_web as _rwkw
    raceweek_routes: list[BaseRoute] = []
    if soc is not None and chat is not None and plans is not None and store is not None:
        _rk = chat.agent

        def _rk_push(to: str, title: str, body: str, url: str) -> None:
            if push is not None and push_allowed(f"raceweek:{to}:{title}:{body[:40]}", 1, 6 * 3600):
                push.send(to, title, body, url=url)
        rk = _rwk.RaceWeek(store, events=_rk.events.list, now=_rk._now, follows=soc.follows,
                           blocked=soc.blocked_between, is_athlete=soc.is_athlete, followers=soc.follower_ids,
                           activities=lambda u: _rk.stats.activities(u)[1], push=_rk_push,
                           quiet=lambda u: _rk.moments.quiet(_rk._now(u)), name=_soc_name)
        _rk.moments.skip_steps = _rwk.RaceWeek.skip_countdown
        _rk_tick_prev, _rk_after_prev = _rk.moments.on_tick, _rk.moments.after_workouts

        def _rk_gear(uid: str) -> list[dict[str, Any]]:
            return _gear_items(uid)[0] if gear_store is not None else []

        def _rk_counts(uid: str, ev: dict[str, Any]) -> tuple[int, int]:
            v = _rwk.packing_view(_rwk.packing_defaults(ev, _rk_gear(uid),
                                                        imperial=_coach().athlete(uid).get("units") != "metric"),
                                  rk.saved(uid, ev["id"]).get("packing"))
            return v["done"], v["total"]

        def _rk_tick(uid: str) -> None:
            if _rk_tick_prev is not None:
                _rk_tick_prev(uid)
            rk.check_moments(uid, _rk.moments, packing=_rk_counts)
            rk.check_start(uid)

        def _rk_after(uid: str) -> None:
            if _rk_after_prev is not None:
                _rk_after_prev(uid)
            rk.check_finish(uid)
        _rk.moments.on_tick, _rk.moments.after_workouts = _rk_tick, _rk_after
        raceweek_routes = _rwkw.make_routes(
            svc=rk, plan_api=_plan_api, read_json=read_json, now=_rk._now, athlete=_coach().athlete,
            plan_of=plans.get, gear=_rk_gear, basis=_pred_basis,
            grade=lambda u, e: _readiness.get(u, e) if _readiness is not None else None, person=_soc_person)

    home_routes: list[BaseRoute] = [
        Route("/app/api/upnext", _plan_api(upnext_get, mutating=False), methods=["GET"]),
        Route("/app/api/firstvisit", _api(firstvisit_get, mutating=False), methods=["GET"]),
    ]

    # ------------------------------------------ weekly ring + live race grade --
    # weekring.py: this week's sessions (plan, else active-week workouts) + the Friday nudge
    # (a Moments.tick hook); gradetrend.py: the main race's grade with a weekly snapshot,
    # delta and reasons (also recorded by the daily grade check). Athletes only (coach 403 in _api).
    if chat is not None and store is not None:
        from . import gradetrend as _gt
        from . import weekring as _wr
        _hg = chat.agent
        _ring = _wr.WeekRing(plan=lambda u: plans.get(u) if plans is not None else None,
                             activities=_hg.stats.activities, checkins=lambda u: _hg.checkins.list(u, 7),
                             profile=lambda u: store.user_doc(u, "profile").load(), now=_hg._now,
                             moments=_hg.moments)
        _grades = _gt.GradeTrend(store, readiness=(_readiness.get if _readiness is not None
                                                   else lambda u, e: {}),
                                 events=_hg.events.list, today=lambda u: _hg._now(u).date())
        _hg.moments.grade = _grades.grade
        _ring_tick_prev = _hg.moments.on_tick

        def _ring_tick(uid: str) -> None:
            if _ring_tick_prev is not None:
                _ring_tick_prev(uid)
            _ring.check_nudge(uid)
        _hg.moments.on_tick = _ring_tick

        async def weekring_get(request: Request, user_id: str) -> Response:
            return JSONResponse({"ring": await anyio.to_thread.run_sync(lambda: _ring.get(user_id))})

        async def racegrade_live(request: Request, user_id: str) -> Response:
            try:
                live = await anyio.to_thread.run_sync(lambda: _grades.live(user_id))
            except Exception as e:  # Garmin busy or a bad event: the home simply hides the card
                log_event(logger, logging.INFO, "racegrade_live_failed", user_id=user_id, error=type(e).__name__)
                live = None
            return JSONResponse({"race": live})

        home_routes += [
            Route("/app/api/weekring", _api(weekring_get, mutating=False), methods=["GET"]),
            Route("/app/api/racegrade/live", _api(racegrade_live, mutating=False), methods=["GET"]),
        ]

    # ------------------------------------------------------------- plan calendar --
    # plancal.py: week/month calendar data (status, distance, pace, notes, mileage), move / swap /
    # missed-session fixes with a deterministic re-balance and undo, weekly mileage goals, the
    # weekring `miles` field and the morning-after-a-miss moment (Moments.on_tick chain).
    # Athletes only (coach 403 in _api). Writes go through PlanService._edit (change hook fires).
    if chat is not None and store is not None and plans is not None:
        from . import plancal as _pc
        _pcal = _pc.PlanCal(plans, chat.agent.coach, activities=chat.agent.stats.activities,
                            now=chat.agent._now, moments=chat.agent.moments)
        _ring.miles = _pcal.week_miles
        _pc_tick_prev = chat.agent.moments.on_tick

        def _pc_tick(uid: str) -> None:
            if _pc_tick_prev is not None:
                _pc_tick_prev(uid)
            _pcal.check_missed(uid)
        chat.agent.moments.on_tick = _pc_tick

        def _cal_with_imports(uid: str) -> Any:
            # Workouts other sources recorded and Garmin didn't (workouts.py, display-only) join
            # the Day view's "extra" list; this is UI data only, never the coach's context.
            cal = _pcal.view(uid)
            if cal is not None and _ext_w is not None:
                try:
                    acts = chat.agent.stats.activities(uid)[1] if _garmin_connected(uid) else []
                    for day, rows in _ext_w.by_day(uid, acts).items():
                        cal.setdefault("extra", {}).setdefault(day, []).extend(rows)
                except Exception as e:
                    log_event(logger, logging.INFO, "ext_workouts_view_failed", error=type(e).__name__)
            return cal

        async def plancal_get(request: Request, user_id: str) -> Response:
            return JSONResponse({"cal": await _plan_call(lambda: _cal_with_imports(user_id))})

        def _pc_op(kind: str) -> Handler:
            async def handler(request: Request, user_id: str) -> Response:
                body = await read_json(request)
                if not isinstance(body, dict):
                    raise ValueError("body")
                out = await _plan_call(lambda: _pcal.op(user_id, kind, body))
                return JSONResponse({"plan": public_plan(out["plan"], plans.today(user_id)),
                                     "cal": out["cal"], "change": out.get("change")})
            return handler

        async def session_ics(request: Request, user_id: str) -> Response:
            # Day view "Add to calendar": one session as .ics (timed when it has a start time).
            # Stable UID per session, so importing again after a move updates the same event.
            from .planformats import export_ics as _export_ics
            sid = request.path_params["sid"]
            plan = await _plan_call(lambda: plans.get(user_id))
            if plan is None or not any(s.get("id") == sid for _, _, s in _pc.iter_sessions(plan)):
                raise _UserError("That session isn't in your plan anymore.", 404)
            body = _export_ics(plan, name="Rabbit", only=sid)
            return Response(body.encode("utf-8"), media_type="text/calendar; charset=utf-8", headers={
                "Content-Disposition": 'attachment; filename="rabbit-workout.ics"', "Cache-Control": "no-store"})

        async def workout_feedback_get(request: Request, user_id: str) -> Response:
            # The workout page's "Rabbit's feedback": the session's plan intent, Garmin vs targets
            # (calendar view `went`) and the latest check-in for it. Deterministic, no model.
            from .workoutday import coach_feedback as _coach_fb
            sid = request.query_params.get("session_id") or ""
            if not sid or len(sid) > 40 or not sid.isalnum():
                raise ValueError("session_id")
            plan = await _plan_call(lambda: plans.get(user_id))
            sess = next((s for _, _, s in _pc.iter_sessions(plan or {}) if s.get("id") == sid), None)
            if sess is None:
                raise _UserError("That session isn't in your plan anymore.", 404)
            cal = await _plan_call(lambda: _pcal.view(user_id)) or {}
            item = (cal.get("sessions") or {}).get(sid) or {}
            cks = await anyio.to_thread.run_sync(lambda: chat.agent.checkins.list(user_id, 120, session_id=sid))
            last = max(cks, key=lambda c: c.get("ts") or 0) if cks else None
            return JSONResponse({"checkin": last, "feedback": _coach_fb(sess, item.get("went"), last)})

        # One recorded workout (activitypage.py; web ActivityScreen): Garmin summary, laps and
        # time in zones, the plan session it counted for, the athlete's check-in and Rabbit's
        # deterministic feedback. Laps + get_activity are read once per activity (cached 30 min,
        # bounded). Imported workouts (workouts.py, display-only) come from the import doc here.
        from . import activitypage as _ap
        from .paces import laps_from_splits as _laps_from_splits
        _ap_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]], dict[str, Any]]] = {}

        def _ap_detail(uid: str, aid: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            hit = _ap_cache.get((uid, aid))
            if hit and time.time() - hit[0] < 1800:
                return hit[1], hit[2]
            laps: list[dict[str, Any]] = []
            extra: dict[str, Any] = {}
            try:
                laps = _laps_from_splits(chat.agent._service.read_uncached(uid, "get_activity_splits", {"activity_id": str(aid)}))
            except Exception as e:
                log_event(logger, logging.INFO, "activity_splits_failed", error=type(e).__name__)
            try:
                extra = _ap.extra_from(chat.agent._service.read_uncached(uid, "get_activity", {"activity_id": str(aid)}))
            except Exception as e:
                log_event(logger, logging.INFO, "activity_summary_failed", error=type(e).__name__)
            if len(_ap_cache) > 300:
                for k in sorted(_ap_cache, key=lambda k: _ap_cache[k][0])[:100]:
                    _ap_cache.pop(k, None)
            _ap_cache[(uid, aid)] = (time.time(), laps, extra)
            return laps, extra

        def _ap_last_checkin(uid: str, ref: str, sid: str | None) -> dict[str, Any] | None:
            cks = [c for c in chat.agent.checkins.list(uid, 120)
                   if c.get("activity_id") == ref or (sid and c.get("session_id") == sid)]
            return max(cks, key=lambda c: c.get("ts") or 0) if cks else None

        def _ap_view(uid: str, raw: str) -> dict[str, Any]:
            from .workoutday import coach_feedback as _coach_fb
            if raw.isdigit() and len(raw) <= 20:
                aid = int(raw)
                try:
                    _, acts = chat.agent.stats.activities(uid)
                except Exception:
                    raise _UserError("Garmin isn't reachable right now. Try again in a minute.", 503) from None
                act = next((a for a in acts if a.get("activity_id") == aid), None)
                if act is None:
                    raise _UserError("That workout isn't in your Garmin history.", 404)
                laps, extra = _ap_detail(uid, aid)
                athlete, _est = _pc.hr_estimate(chat.agent.coach.athlete(uid) or {}, acts)
                planned, sess = None, None
                plan = plans.get(uid)
                if plan is not None:
                    cal = _pcal.view(uid) or {}
                    for sid, item in (cal.get("sessions") or {}).items():
                        if (item.get("activity") or {}).get("id") == aid:
                            for _, d, s0 in _pc.iter_sessions(plan):
                                if s0.get("id") == sid:
                                    sess = s0
                                    planned = {"id": sid, "date": d, "title": s0.get("title"), "kind": s0.get("kind"),
                                               "went": item.get("went")}
                                    break
                            break
                ck = _ap_last_checkin(uid, raw, planned["id"] if planned else None)
                fb = _coach_fb(sess or {"kind": "", "sport": _ap.sport_of(act.get("sport"))},
                               (planned or {}).get("went"), ck)
                return _ap.build_view(act, laps=laps, extra=extra, athlete=athlete, planned=planned, checkin=ck, feedback=fb)
            if re.fullmatch(r"[a-z]{2,12}:[A-Za-z0-9_.-]{1,64}", raw) and _ext_w is not None:
                w = next((x for x in _ext_w.all(uid) if x.get("key") == raw), None)
                if w is None:
                    raise _UserError("That workout isn't in your history anymore.", 404)
                ck = _ap_last_checkin(uid, _ap.checkin_ref(raw), None)
                return _ap.build_imported(w, checkin=ck, feedback=_coach_fb({"kind": ""}, None, ck))
            raise ValueError("activity id")

        async def activity_get(request: Request, user_id: str) -> Response:
            raw = request.path_params["aid"]
            return JSONResponse(await anyio.to_thread.run_sync(lambda: _ap_view(user_id, raw)))

        home_routes += [
            Route("/app/api/activity/{aid}", _plan_api(activity_get, mutating=False), methods=["GET"]),
            Route("/app/api/workout/feedback", _plan_api(workout_feedback_get, mutating=False), methods=["GET"]),
            Route("/app/api/plan/sessions/{sid}/calendar.ics", _plan_api(session_ics, mutating=False), methods=["GET"]),
            Route("/app/api/plan/calendar", _plan_api(plancal_get, mutating=False), methods=["GET"]),
            *[Route(f"/app/api/plan/calendar/{k}", _plan_api(_pc_op(k), mutating=True), methods=["POST"])
              for k in ("move", "swap", "fix", "undo", "goal")],
        ]

        # Share by text (sharelinks.py): public read-only links (/app/l/<token>) for a planned
        # workout, a recorded workout, an event, a club or an invite, opened from Messages etc.
        # A snapshot of safe fields is frozen at share time (no heart rate unless the sharer
        # includes it; never location). Only token hashes are stored; revoking 404s at once.
        from . import sharelinks as _sl
        _slinks = _sl.ShareLinks(store)
        acct.on_delete("share links", _slinks.revoke_all)
        _sl_clb = locals().get("clb")
        _sl_base = settings.public_base_url.rstrip("/")

        def _sl_snap(uid: str, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
            kind = body.get("kind")
            ref = str(body.get("ref") or "")[:80]
            hr = body.get("include_hr") is True
            who = auth.profile(uid).get("name") or ""
            athlete = chat.agent.coach.athlete(uid) or {}
            imperial = athlete.get("units") != "metric"
            if kind == "workout":
                plan = plans.get(uid)
                hit = next(((d, s0) for _, d, s0 in _pc.iter_sessions(plan or {}) if s0.get("id") == ref), None) if plan else None
                if hit is None:
                    raise _UserError("That workout isn't in your plan anymore.", 404)
                item = ((_pcal.view(uid) or {}).get("sessions") or {}).get(ref)
                return kind, ref, _sl.planned_snap(hit[1], hit[0], item, who=who, imperial=imperial, include_hr=hr)
            if kind == "activity":
                view = _ap_view(uid, ref)
                return kind, ref, _sl.activity_snap(view, who=who, imperial=imperial, include_hr=hr)
            if kind == "event":
                ev = next((e for e in chat.agent.events.list(uid) if e.get("id") == ref), None)
                if ev is None:
                    raise _UserError("That event isn't on your calendar anymore.", 404)
                today = plans.today(uid)
                ev = chat.agent.events.decorate(ev, today)
                if ev.get("next_dates"):
                    ev = ev | {"date": ev["next_dates"][0]}
                return kind, ref, _sl.event_snap(ev, who=who)
            if kind == "club":
                if _sl_clb is None:
                    raise _UserError("Clubs aren't available here.", 404)
                try:
                    c = _sl_clb.get(uid, ref)
                except Exception:
                    raise _UserError("Club not found.", 404) from None
                admin = c.get("role") in ("owner", "admin")
                if c.get("visibility") == "private" and not admin:
                    raise _UserError("Only the club's organizers can share a private club.", 403)
                code = c.get("code") if (c.get("visibility") == "private" or body.get("include_code") is True) and admin else None
                return kind, ref, _sl.club_snap(c, who=who, code=code)
            if kind == "invite":
                return kind, "invite", _sl.invite_snap(who=who)
            raise ValueError("kind")

        def _sl_cta(uid: str, snap: dict[str, Any]) -> tuple[str, str]:
            """Join link when the sharer can invite (a reusable access invite), else the app."""
            if auth.can_invite(uid) and auth.access is not None:
                def make() -> tuple[str, int]:
                    tok, _iid = auth.access.create_invite(uid, max_uses=25, days=60)
                    return tok, int(time.time()) + 60 * 86400
                try:
                    tok = _slinks.invite_token(uid, make)
                    label = "Join Rabbit" if snap.get("kind") in ("invite", "club", "event") else "Train with me on Rabbit"
                    return f"{_sl_base}/app/join/{tok}", label
                except Exception as e:  # too many invites etc.: the page still works
                    log_event(logger, logging.INFO, "share_invite_failed", error=type(e).__name__)
            return f"{_sl_base}/app/", "Open Rabbit"

        async def sharelink_create(request: Request, user_id: str) -> Response:
            body = await read_json(request)
            if not isinstance(body, dict) or body.get("kind") not in _sl.KINDS:
                raise ValueError("kind")
            kind, ref, snap = await anyio.to_thread.run_sync(lambda: _sl_snap(user_id, body))
            try:
                token, lid = _slinks.create(user_id, kind, ref, snap)
            except _sl.ShareError as e:
                raise _UserError(str(e), e.status) from None
            return JSONResponse({"id": lid, "url": f"{_sl_base}/app/l/{token}", "title": snap.get("title"),
                                 "text": _sl.default_text(snap)}, status_code=201)

        async def sharelink_list(request: Request, user_id: str) -> Response:
            return JSONResponse({"links": _slinks.list(user_id)})

        async def sharelink_delete(request: Request, user_id: str) -> Response:
            lid = request.path_params["lid"]
            if not re.fullmatch(r"[0-9a-f]{12}", lid):
                raise ValueError("link id")
            if not _slinks.revoke(user_id, lid):
                raise _UserError("That link is already off.", 404)
            return JSONResponse({"ok": True})

        async def sharelink_page(request: Request) -> Response:
            headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
                       "X-Content-Type-Options": "nosniff",
                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
                                                  "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}
            if not host_ok(request):
                return HTMLResponse("Not found", status_code=404, headers=headers)
            token = request.path_params["token"]
            got = await anyio.to_thread.run_sync(lambda: _slinks.resolve(token))
            if got is None:
                return HTMLResponse("This link isn't active anymore.", status_code=404, headers=headers)
            uid, rec = got
            snap = rec.get("snap") or {}
            cta_url, cta_label = await anyio.to_thread.run_sync(lambda: _sl_cta(uid, snap))
            page = _sl.render(snap, url=f"{_sl_base}/app/l/{token}", og_image=f"{_sl_base}/app/og-image.png",
                              cta_url=cta_url, cta_label=cta_label)
            return HTMLResponse(page, headers=headers)

        home_routes += [
            Route("/app/api/sharelinks", _plan_api(sharelink_list, mutating=False), methods=["GET"]),
            Route("/app/api/sharelinks", _plan_api(sharelink_create, mutating=True), methods=["POST"]),
            Route("/app/api/sharelinks/{lid}", _plan_api(sharelink_delete, mutating=True), methods=["DELETE"]),
            Route("/app/l/{token}", sharelink_page, methods=["GET"]),
        ]

        # Weather-aware workouts (weather.py rules, weather_web.py): Home's next 3 days and one
        # session's hourly strip, adjusted paces and best time to go. Display only.
        from .weather_web import WeatherService as _WxSvc
        _wxs = _WxSvc(plans=plans, pcal=_pcal, coach=chat.agent.coach, store=store)

        async def weather_next_get(request: Request, user_id: str) -> Response:
            return JSONResponse(await _wxs.next_days(user_id))

        async def weather_session_get(request: Request, user_id: str) -> Response:
            sid = request.query_params.get("session_id") or ""
            if not sid or len(sid) > 40 or not sid.isalnum():
                raise ValueError("session_id")
            try:
                return JSONResponse(await _wxs.session(user_id, sid))
            except LookupError:
                raise _UserError("That session isn't in your plan anymore.", 404) from None

        home_routes += [
            Route("/app/api/weather/next", _plan_api(weather_next_get, mutating=False), methods=["GET"]),
            Route("/app/api/weather/session", _plan_api(weather_session_get, mutating=False), methods=["GET"]),
        ]

    # ------------------------------------------------------------- body logs --
    # body.py: fueling & hydration log (per session/activity) with learnings vs the race target,
    # and the niggle tracker with conservative easing proposals (adjust-style, id-checked).
    if _body is not None and plans is not None:
        _FUEL_KEY = re.compile(r"^(s:[A-Za-z0-9]{1,40}|a:[A-Za-z0-9:_.-]{1,80})$")

        def _fuel_key(v: Any) -> str:
            if not isinstance(v, str) or not _FUEL_KEY.fullmatch(v):
                raise ValueError("key")
            return v

        def _race_target(user_id: str) -> int:
            from .nutrition import race_target as _rt
            g = _coach().active_goal(user_id) or {}
            return _rt(g.get("distance"))

        async def fuel_get(request: Request, user_id: str) -> Response:
            key = _fuel_key(request.query_params.get("key"))
            entry = await anyio.to_thread.run_sync(lambda: _body.fuel_get(user_id, key))
            return JSONResponse({"entry": entry, "products": _body_mod.PRODUCTS, "target": _race_target(user_id)})

        async def fuel_post(request: Request, user_id: str) -> Response:
            body = await read_json(request)
            if not isinstance(body, dict):
                raise ValueError("body")
            key = _fuel_key(body.get("key"))
            if body.get("delete") is True:
                await anyio.to_thread.run_sync(lambda: _body.fuel_delete(user_id, key))
                return JSONResponse({"entry": None})
            try:
                entry = await anyio.to_thread.run_sync(lambda: _body.fuel_save(user_id, key, body))
            except _body_mod.BodyError as e:
                raise _UserError(str(e)) from None
            target = _race_target(user_id)
            learned = _body_mod.learnings(_body.fuel_entries(user_id), target)
            return JSONResponse({"entry": entry, "learnings": learned}, status_code=201)

        async def fueling_get(request: Request, user_id: str) -> Response:
            target = _race_target(user_id)
            entries = await anyio.to_thread.run_sync(lambda: _body.fuel_entries(user_id))
            return JSONResponse({"learnings": _body_mod.learnings(entries, target), "target": target,
                                 "entries": [dict(e, **_body_mod.rates(e)) for e in entries[:30]],
                                 "products": _body_mod.PRODUCTS})

        def _niggle_proposal(user_id: str) -> dict[str, Any] | None:
            return _body_mod.ease_proposal(plans.get(user_id), _body.niggles(user_id), plans.today(user_id))

        def _niggles_payload(user_id: str) -> dict[str, Any]:
            today = plans.today(user_id)
            items = [_body.view(n, today) for n in _body.niggles(user_id)]
            dismissed = _body_mod_dismissed(user_id)
            prop = _niggle_proposal(user_id)
            return {"active": [n for n in items if n["status"] == "active"],
                    "resolved": [n for n in items if n["status"] != "active"][:10],
                    "areas": _body_mod.AREAS, "care_note": _body_mod.CARE_NOTE,
                    "proposal": prop if prop and prop["id"] != dismissed else None}

        def _body_mod_dismissed(user_id: str) -> str | None:
            return store.user_doc(user_id, "niggles").load().get("dismissed")

        async def niggles_get(request: Request, user_id: str) -> Response:
            return JSONResponse(await anyio.to_thread.run_sync(lambda: _niggles_payload(user_id)))

        async def niggle_add(request: Request, user_id: str) -> Response:
            body = await read_json(request)
            if not isinstance(body, dict):
                raise ValueError("body")
            try:
                await anyio.to_thread.run_sync(lambda: _body.add_niggle(user_id, body))
            except _body_mod.BodyError as e:
                raise _UserError(str(e)) from None
            return JSONResponse(await anyio.to_thread.run_sync(lambda: _niggles_payload(user_id)), status_code=201)

        async def niggle_post(request: Request, user_id: str) -> Response:
            nid = request.path_params["nid"]
            if not re.fullmatch(r"n[0-9a-f]{10}", nid):
                raise ValueError("id")
            body = await read_json(request)
            if not isinstance(body, dict):
                raise ValueError("body")

            def run() -> dict[str, Any]:
                if body.get("delete") is True:
                    _body.delete_niggle(user_id, nid)
                else:
                    _body.update_niggle(user_id, nid, body)
                return _niggles_payload(user_id)
            try:
                out = await anyio.to_thread.run_sync(run)
            except KeyError:
                raise _UserError("That niggle isn't here anymore.", 404) from None
            except _body_mod.BodyError as e:
                raise _UserError(str(e)) from None
            return JSONResponse(out)

        async def niggle_ease(request: Request, user_id: str) -> Response:
            body = await read_json(request)
            if not isinstance(body, dict) or body.get("action") not in ("apply", "dismiss"):
                raise ValueError("body")
            prop = await _plan_call(lambda: _niggle_proposal(user_id))
            if prop is None or prop["id"] != body.get("id"):
                return _err(409, "Your plan changed since this suggestion. Take another look.")
            if body["action"] == "dismiss":
                await anyio.to_thread.run_sync(lambda: store.user_doc(user_id, "niggles").update(
                    lambda d: d.__setitem__("dismissed", prop["id"])))
                return JSONResponse(await anyio.to_thread.run_sync(lambda: _niggles_payload(user_id)))
            plan = await _plan_call(lambda: plans.apply_adjustment(user_id, prop["changes"]))
            return _plan_resp(user_id, plan, applied=len(prop["changes"]))

        home_routes += [
            Route("/app/api/body/fuel", _plan_api(fuel_get, mutating=False), methods=["GET"]),
            Route("/app/api/body/fuel", _plan_api(fuel_post, mutating=True), methods=["POST"]),
            Route("/app/api/body/fueling", _plan_api(fueling_get, mutating=False), methods=["GET"]),
            Route("/app/api/body/niggles", _plan_api(niggles_get, mutating=False), methods=["GET"]),
            Route("/app/api/body/niggles", _plan_api(niggle_add, mutating=True), methods=["POST"]),
            Route("/app/api/body/niggles/ease", _plan_api(niggle_ease, mutating=True), methods=["POST"]),
            Route("/app/api/body/niggles/{nid}", _plan_api(niggle_post, mutating=True), methods=["POST"]),
        ]

    # ------------------------------------------------------- training paces --
    # paces.py (routes in paces_web.py): deterministic threshold pace / FTP / CSS detection after
    # each synced workout (Moments.after_workouts) and weekly (Moments.on_tick); a "pace" moment
    # with one-tap Update; accept re-targets future plan sessions, undo for 24 h. Athletes only.
    if chat is not None and store is not None:
        from . import paces as _pcs, paces_web as _pcw
        _pa = chat.agent

        def _pcs_g10(uid: str) -> float | None:
            return next((t for km, t in (_pred_basis(uid).get("garmin") or []) if km == 10.0), None)
        pace_svc = _pcs.Paces(
            store, athlete=_pa.coach.athlete, set_athlete=_pa.coach.update_athlete,
            activities=lambda u: _pa.stats.activities(u)[1], now=_pa._now, clock=time.time,
            splits=lambda u, aid: _pa._service.read_uncached(u, "get_activity_splits", {"activity_id": aid}),
            predictor=_pcs_g10, edit_plan=(plans._edit if plans is not None else None), post=_pa.moments.post)
        _pcs_tick_prev, _pcs_after_prev = _pa.moments.on_tick, _pa.moments.after_workouts

        def _pcs_tick(uid: str) -> None:
            if _pcs_tick_prev is not None:
                _pcs_tick_prev(uid)
            pace_svc.weekly(uid)

        def _pcs_after(uid: str) -> None:
            if _pcs_after_prev is not None:
                _pcs_after_prev(uid)
            pace_svc.after_workouts(uid)
        _pa.moments.on_tick, _pa.moments.after_workouts = _pcs_tick, _pcs_after
        home_routes += _pcw.make_routes(svc=pace_svc, api=_api, read_json=read_json)

    # ---------------------------------------------------------- trainingpeaks --
    # tpsync.py (routes in tp_web.py): the athlete's own TrainingPeaks, two-way. Pull planned
    # workouts onto the plan calendar, push Rabbit sessions when Rabbit is the source, move TP
    # workouts. Session value pasted in the connect sheet, stored encrypted per user. Refresh via
    # Moments.on_tick; Rabbit plan writes push (debounced). Athletes only (coach 403 in _api).
    from . import tp_web as _tpw, tpsync as _tps
    tp_sync: Any = None
    tp_routes: list[BaseRoute] = []
    if settings.app_trainingpeaks and store is not None:
        _tp_agent = chat.agent if chat is not None else None

        def _tp_today(uid: str) -> date:
            return plans.today(uid) if plans is not None else date.today()

        def _tp_acts(uid: str) -> list[dict[str, Any]]:
            return _tp_agent.stats.activities(uid)[1] if _tp_agent is not None and _garmin_connected(uid) else []
        tp_sync = _tps.TPSync(store, plan=lambda u: plans.get(u) if plans is not None else None,
                              today=_tp_today, activities=_tp_acts, transport=_tps.TRANSPORT)
        acct.on_delete("trainingpeaks", tp_sync.disconnect)
        store.on_user_write(tp_sync.on_plan_write)
        if _tp_agent is not None:
            _tp_tick_prev = _tp_agent.moments.on_tick

            def _tp_tick(uid: str) -> None:
                if _tp_tick_prev is not None:
                    _tp_tick_prev(uid)
                tp_sync.tick(uid)
            _tp_agent.moments.on_tick = _tp_tick
        tp_routes = _tpw.make_routes(tp=tp_sync, api=_api, read_json=read_json)

    # ------------------------------------------------------- connected apps --
    # connections.py: one status row per integration (Garmin, Oura, Google Calendar) for the
    # Me -> Connected apps hub and its connect popups, without calling any provider: Garmin's
    # last sync/attention come from LiveSync's in-memory result, Oura/Calendar from their read
    # caches. POST .../{app}/sync re-reads Oura or Calendar now (Garmin uses /app/api/sync).
    # Athletes only (coach 403 in _api).
    from . import connections as _conn
    _conn_errors: dict[tuple[str, str], str] = {}  # (user, app) -> last "Sync now" problem

    def _conn_rows(uid: str) -> dict[str, Any]:
        g_on = _garmin_connected(uid)
        last = live_sync.last(uid) if live_sync is not None else None
        g_doc = store.user_doc(uid, "sync").load() if store is not None else {}
        g_err = (last or {}).get("error") if g_on else None
        o, cal = auth.oura, auth.calendar
        o_on = bool(o and o.connected(uid))
        c_on = bool(cal and cal.connected(uid))
        return {
            "garmin": _conn.status(
                "garmin", available=logins is not None, connected=g_on,
                last_sync=(last or {}).get("checked_at") if last and not g_err else g_doc.get("checked_at"),
                error=g_err, attention=bool(g_on and last and last.get("code") == "reauth")),
            "oura": _conn.status(
                "oura", available=o is not None, connected=o_on,
                last_sync=(o.last_read(uid) if o is not None else None),
                error=_conn_errors.get((uid, "oura")), attention=(uid, "oura") in _conn_errors),
            "calendar": _conn.status(
                "calendar", available=cal is not None, connected=c_on,
                last_sync=(cal.last_read(uid) if cal is not None else None),
                error=_conn_errors.get((uid, "calendar")), attention=(uid, "calendar") in _conn_errors),
        } | ({"whoop": _conn.status(
            "whoop", available=True, connected=bool(auth.whoop and auth.whoop.connected(uid)),
            last_sync=(auth.whoop.last_read(uid) if auth.whoop is not None else None),
            error=_conn_errors.get((uid, "whoop")), attention=(uid, "whoop") in _conn_errors)}
            if auth.whoop is not None else {}) | ({"apple": _conn.status(
                "apple", available=True, connected=(ah := _ah_keys.status(uid)) is not None,
                last_sync=(ah or {}).get("last_import"))} if _ah_keys is not None and _ext_w is not None else {}
        ) | ({"trainingpeaks": _conn.status(
            "trainingpeaks", available=True, connected=(tps := tp_sync.status(uid))["connected"],
            last_sync=tps["last_sync"], error=tps["error"], attention=tps["attention"])}
            if tp_sync is not None else {})

    def _conn_sources(uid: str) -> dict[str, Any] | None:
        if store is None:
            return None
        return prefs_for(store, uid, bool(auth.oura and auth.oura.connected(uid)))[0]

    # Workouts from other sources (workouts.py): Oura's are imported every EXT_EVERY_S from the
    # minute tick (and on "Sync now"), matched against Garmin so nothing counts twice, shown in
    # the Day view and auto-shared like Garmin workouts when the athlete shares workouts.
    # Display-only: never in Stats.activities, plan matching or anything the coach sees.
    from . import demand as _dem
    from .oura import OuraWorkoutsScope
    EXT_EVERY_S = 1800
    _ext_notes: dict[str, str] = {}  # user -> "Connect Oura again to import its workouts."
    _demand = _dem.Demand(store) if store is not None else None

    async def _import_oura(uid: str, *, force: bool = False) -> int:
        o = auth.oura
        if _ext_w is None or o is None or not o.connected(uid):
            return 0
        last = _ext_w.imported_at(uid, "oura")
        if not force and last is not None and time.time() - last < EXT_EVERY_S:
            return 0
        today = plans.today(uid) if plans else date.today()
        try:
            items = await o.workouts(uid, today - timedelta(days=14), today)
            _ext_notes.pop(uid, None)
        except OuraWorkoutsScope as e:
            _ext_notes[uid] = str(e)
            _ext_w.save(uid, "oura", [], today)  # remember the attempt (no retry storm)
            return 0
        return await _ext_store(uid, "oura", items, today)

    async def _import_whoop(uid: str, *, force: bool = False) -> int:
        w = auth.whoop
        if _ext_w is None or w is None or not w.connected(uid):
            return 0
        last = _ext_w.imported_at(uid, "whoop")
        if not force and last is not None and time.time() - last < EXT_EVERY_S:
            return 0
        today = plans.today(uid) if plans else date.today()
        try:
            items = await w.workouts(uid, today - timedelta(days=14), today)
            _conn_errors.pop((uid, "whoop"), None)
        except WhoopNotConnected:
            return 0
        except WhoopError as e:
            _conn_errors[(uid, "whoop")] = str(e)
            _ext_w.save(uid, "whoop", [], today)  # remember the attempt (no retry storm)
            return 0
        return await _ext_store(uid, "whoop", items, today)

    async def _ext_store(uid: str, source: str, items: list[dict[str, Any]], today: date) -> int:
        """Save one source's import; new workouts Garmin doesn't have go to the feed (when the
        athlete shares workouts)."""
        assert _ext_w is not None
        new = set(await anyio.to_thread.run_sync(lambda: _ext_w.save(uid, source, items, today)))
        if new and "share" in _ext_feed:
            def share() -> None:
                acts = chat.agent.stats.activities(uid)[1] if chat is not None and _garmin_connected(uid) else []
                fresh = [w for w in _ext_w.visible(uid, acts) if w["key"] in new]
                if fresh:
                    _ext_feed["share"](uid, fresh, today)
            try:
                await anyio.to_thread.run_sync(share)
            except Exception as e:
                log_event(logger, logging.INFO, "ext_workouts_share_failed", error=type(e).__name__)
        log_event(logger, logging.INFO, "ext_workouts_import", user_id=uid, source=source, new=len(new))
        return len(new)

    if chat is not None and _ext_w is not None:
        _ext_tick_prev = chat.agent.moments.on_tick

        def _ext_tick(uid: str) -> None:
            if _ext_tick_prev is not None:
                _ext_tick_prev(uid)
            for src, client, run in (("oura", auth.oura, _import_oura), ("whoop", auth.whoop, _import_whoop)):
                if client is None or not client.connected(uid):
                    continue
                last = _ext_w.imported_at(uid, src)
                if last is not None and time.time() - last < EXT_EVERY_S:
                    continue
                try:
                    asyncio.run(run(uid))  # the proactive thread has no event loop of its own
                except Exception as e:  # one source failing never blocks the other
                    log_event(logger, logging.INFO, "ext_workouts_tick_failed", source=src, error=type(e).__name__)
        chat.agent.moments.on_tick = _ext_tick

    async def connections_get(request: Request, user_id: str) -> Response:
        rows = await anyio.to_thread.run_sync(lambda: _conn_rows(user_id))
        out = _conn.view(rows, _conn_sources(user_id))
        if _demand is not None:
            owner = auth.is_owner(user_id)
            live = {"whoop"} if auth.whoop is not None else set()  # connectable now: not "coming soon"
            out["soon"] = await anyio.to_thread.run_sync(lambda: _demand.rows(user_id, owner=owner, skip=live))
        if user_id in _ext_notes:
            for a in out["apps"]:
                if a["id"] == "oura" and a["connected"]:
                    a["note"] = _ext_notes[user_id]
        return JSONResponse(out)

    async def connections_want(request: Request, user_id: str) -> Response:
        """``{want: bool}``: "I want this" for a coming-soon app (demand.py)."""
        if _demand is None:
            return _err(503, "Not available on this server.")
        body = await read_json(request)
        if not isinstance(body, dict) or not isinstance(body.get("want"), bool):
            return _err(400, "Send want: true or false.")
        app_id = request.path_params["app"]
        try:
            on = await anyio.to_thread.run_sync(lambda: _demand.vote(user_id, app_id, body["want"]))
        except _dem.DemandError as e:
            return _err(400, str(e))
        out: dict[str, Any] = {"app": app_id, "wanted": on}
        if auth.is_owner(user_id):
            out["wanted_by"] = (await anyio.to_thread.run_sync(_demand.counts)).get(app_id, 0)
        return JSONResponse(out)

    async def connections_sync(request: Request, user_id: str) -> Response:
        app_id = request.path_params["app"]
        if app_id == "trainingpeaks" and tp_sync is not None:
            if not await anyio.to_thread.run_sync(lambda: tp_sync.connected(user_id)):
                return _err(409, "TrainingPeaks isn't connected.")
            await anyio.to_thread.run_sync(lambda: tp_sync.sync(user_id))
            rows = await anyio.to_thread.run_sync(lambda: _conn_rows(user_id))
            return JSONResponse({"app": rows[app_id]})
        if app_id == "whoop":
            if auth.whoop is None or not auth.whoop.connected(user_id):
                return _err(409, "WHOOP isn't connected.")
            auth.whoop.forget(user_id)
            try:
                await _import_whoop(user_id, force=True)
            except Exception as e:
                log_event(logger, logging.WARNING, "connection_sync_failed", app=app_id, error=type(e).__name__)
                _conn_errors[(user_id, "whoop")] = "Didn't answer just now. Try again later."
            rows = await anyio.to_thread.run_sync(lambda: _conn_rows(user_id))
            return JSONResponse({"app": rows[app_id]})
        if app_id not in ("oura", "calendar"):
            return _err(400, "Use /app/api/sync for Garmin.")
        today = plans.today(user_id) if plans else date.today()
        key = (user_id, app_id)
        try:
            if app_id == "oura":
                if auth.oura is None or not auth.oura.connected(user_id):
                    return _err(409, "Oura isn't connected.")
                auth.oura.forget(user_id)
                await auth.oura.recovery(user_id, today, 28)
                await _import_oura(user_id, force=True)
            else:
                cal = auth.calendar
                if cal is None or not cal.connected(user_id):
                    return _err(409, "Google Calendar isn't connected.")
                prof = store.user_doc(user_id, "profile").load() if store else {}
                cal.forget(user_id)
                await cal.summary(user_id, today, 42, prof.get("timezone") or default_tz)
            _conn_errors.pop(key, None)
        except (OuraNotConnected, CalendarNotConnected):
            _conn_errors.pop(key, None)  # the token is gone: the row says "Not connected"
        except (OuraError, CalendarError) as e:
            _conn_errors[key] = str(e)
        except Exception as e:
            log_event(logger, logging.WARNING, "connection_sync_failed", app=app_id, error=type(e).__name__)
            _conn_errors[key] = "Didn't answer just now. Try again later."
        rows = await anyio.to_thread.run_sync(lambda: _conn_rows(user_id))
        return JSONResponse({"app": rows[app_id]})

    # Apple Watch via the athlete's iPhone Shortcut (applehealth.py). The import endpoint has no
    # session or Origin (a Shortcut can't send them): the Bearer import key is the only way in,
    # it can only add workouts to its own account, and it is rate- and size-limited.
    def _ah_view(uid: str) -> dict[str, Any]:
        st = _ah_keys.status(uid) if _ah_keys is not None else None
        n = sum(1 for w in (_ext_w.all(uid) if _ext_w is not None else []) if w.get("source") == _ah.SOURCE)
        return {"on": st is not None, "available": _ah_keys is not None and _ext_w is not None,
                "created": (st or {}).get("created"), "last_import": (st or {}).get("last_import"),
                "last_received": (st or {}).get("last_received"), "last_new": (st or {}).get("last_new"),
                "workouts": n, "endpoint": settings.public_base_url.rstrip("/") + "/app/api/import/apple-health"}

    async def apple_get(request: Request, user_id: str) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(lambda: _ah_view(user_id)))

    async def apple_key(request: Request, user_id: str) -> Response:
        if _ah_keys is None or _ext_w is None:
            return _err(503, "Apple Watch import isn't available on this server.")
        if not push_allowed(f"ah-key:{user_id}", 10, 3600):
            return _err(429, "That's a lot of new keys. Try again in a bit.")
        key = await anyio.to_thread.run_sync(lambda: _ah_keys.create(user_id))
        view = await anyio.to_thread.run_sync(lambda: _ah_view(user_id))
        return JSONResponse({**view, "key": key})

    async def apple_disconnect(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        remove = bool(isinstance(body, dict) and body.get("remove") is True)
        if _ah_keys is not None:
            await anyio.to_thread.run_sync(lambda: _ah_keys.revoke(user_id))
        if remove and store is not None:
            await anyio.to_thread.run_sync(lambda: _workouts.drop_source(store, user_id, _ah.SOURCE))
        return JSONResponse(await anyio.to_thread.run_sync(lambda: _ah_view(user_id)))

    async def apple_import(request: Request) -> Response:
        def no(status: int, msg: str) -> Response:
            return JSONResponse({"ok": False, "error": msg}, status_code=status, headers={"Cache-Control": "no-store"})
        if not host_ok(request):
            return no(400, "bad host")
        if _ah_keys is None or _ext_w is None:
            return no(503, "Apple Watch import isn't available on this server.")
        ip = request.client.host if request.client else "?"
        if not push_allowed(f"ah-ip:{ip}", 60, 600):
            return no(429, "Too many tries. Wait a few minutes and run the Shortcut again.")
        token = _ah.bearer(request.headers.get("authorization"))
        uid = await anyio.to_thread.run_sync(lambda: _ah_keys.lookup(token)) if token else None
        if not uid:
            return no(401, "Rabbit doesn't recognise this import key. In Rabbit, open Me, Connected apps, "
                           "Apple Watch and copy your key into the Shortcut again.")
        if not push_allowed(f"ah-user:{uid}", 30, 3600):
            return no(429, "Rabbit already got several imports this hour. Try again later.")
        try:
            size = int(request.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        if size > _ah.MAX_BODY:
            return no(413, "That's too much at once. Send the last 7 days of workouts.")
        raw = await request.body()
        if len(raw) > _ah.MAX_BODY:
            return no(413, "That's too much at once. Send the last 7 days of workouts.")

        def run() -> dict[str, Any]:
            imperial, now = True, datetime.now()
            if chat is not None:
                _a = chat.agent
                imperial = _a.coach.athlete(uid).get("units") != "metric"
                now = _a._now(uid).replace(tzinfo=None)
            items, skipped = _ah.parse_payload(raw, imperial=imperial, now=now)
            today = plans.today(uid) if plans else now.date()
            new = set(_ext_w.save(uid, _ah.SOURCE, items, today)) if items else set()
            _ah_keys.note_import(uid, len(items), len(new))
            if new and "share" in _ext_feed:
                try:
                    acts = chat.agent.stats.activities(uid)[1] if chat is not None and _garmin_connected(uid) else []
                    fresh = [w for w in _ext_w.visible(uid, acts) if w["key"] in new]
                    if fresh:
                        _ext_feed["share"](uid, fresh, today)
                except Exception as e:
                    log_event(logger, logging.INFO, "ext_workouts_share_failed", error=type(e).__name__)
            log_event(logger, logging.INFO, "ext_workouts_import", user_id=uid, source=_ah.SOURCE, new=len(new))
            return {"received": len(items), "new": len(new), "skipped": skipped}
        try:
            r = await anyio.to_thread.run_sync(run)
        except Exception as e:
            log_event(logger, logging.WARNING, "apple_import_failed", error=type(e).__name__)
            return no(500, "Rabbit couldn't save that just now. Try again later.")
        if r["received"] == 0:
            msg = ("Rabbit didn't find any workouts in that. Check the Shortcut's steps in Rabbit: "
                   "Me, Connected apps, Apple Watch.")
        else:
            msg = (f"Rabbit got {r['received']} workout{'s' if r['received'] != 1 else ''}"
                   f" ({r['new']} new).")
        return JSONResponse({"ok": True, **r, "message": msg}, headers={"Cache-Control": "no-store"})

    home_routes += [
        Route("/app/api/apple-health", _api(apple_get, mutating=False), methods=["GET"]),
        Route("/app/api/apple-health/key", _api(apple_key, mutating=True), methods=["POST"]),
        Route("/app/api/apple-health/disconnect", _api(apple_disconnect, mutating=True), methods=["POST"]),
        Route("/app/api/import/apple-health", apple_import, methods=["POST"]),
    ]

    home_routes += [
        Route("/app/api/connections", _api(connections_get, mutating=False), methods=["GET"]),
        Route("/app/api/connections/{app}/sync", _api(connections_sync, mutating=True), methods=["POST"]),
        Route("/app/api/connections/{app}/want", _api(connections_want, mutating=True), methods=["POST"]),
    ]

    # ---------------------------------------- workout reward + month recap --
    # reward.py: one headline insight per new workout (records, streak, week closed, plan
    # nailed), shown once on the next open / from the workout note's push; the monthly recap
    # totals the app draws as a share image, plus a moment on the 1st. Athletes only (_api).
    from . import reward as _rw
    rewards: Any = None
    if chat is not None and store is not None:
        _rw_agent = chat.agent
        rewards = _rw.Rewards(store, now=_rw_agent._now,
                              context=lambda u, aid: _rw.agent_context(_rw_agent, u, aid))
        _rw_agent.rewards = rewards  # proactive.AgentDelivery: the workout push's title + link
        _rw_agent.moments.on_workouts = rewards.on_workouts
        _rw_tick_prev = _rw_agent.moments.on_tick

        def _rw_tick(uid: str) -> None:
            if _rw_tick_prev is not None:
                _rw_tick_prev(uid)
            rewards.check_month(uid, acts=_rw_agent.stats.activities, post=_rw_agent.moments.post)
        _rw_agent.moments.on_tick = _rw_tick

    async def reward_get(request: Request, user_id: str) -> Response:
        if rewards is None:
            return _err(503, "Rewards aren't configured on this server.")
        raw = request.query_params.get("activity_id")
        if raw:
            if not raw.isdigit():
                raise ValueError("activity_id")
            return JSONResponse({"reward": await anyio.to_thread.run_sync(lambda: rewards.get(user_id, int(raw)))})
        return JSONResponse({"reward": await anyio.to_thread.run_sync(lambda: rewards.pending(user_id))})

    async def reward_seen(request: Request, user_id: str) -> Response:
        if rewards is None:
            return _err(503, "Rewards aren't configured on this server.")
        raw = str(request.path_params["activity_id"])
        if not raw.isdigit():
            raise ValueError("activity_id")
        await anyio.to_thread.run_sync(lambda: rewards.seen(user_id, int(raw)))
        return JSONResponse({"ok": True})

    async def month_recap_get(request: Request, user_id: str) -> Response:
        assert chat is not None
        if (empty := _no_garmin(user_id)) is not None:
            return empty
        agent = chat.agent
        try:
            start = _rw.parse_month(request.query_params.get("month"), agent._now(user_id).date())
        except ValueError as e:
            return _err(400, str(e))

        def build() -> dict[str, Any]:
            today, acts = agent.stats.activities(user_id)
            club = _rw.top_club_of(store, clb, user_id, start, _rw.month_end(start)) if community_routes else None
            return _rw.month_recap(acts, start, today, imperial=agent.coach.athlete(user_id).get("units") != "metric",
                                   top_club=club)
        return JSONResponse(await _plan_call(build))

    reward_routes: list[BaseRoute] = [
        Route("/app/api/reward", _plan_api(reward_get, mutating=False), methods=["GET"]),
        Route("/app/api/reward/{activity_id}/seen", _plan_api(reward_seen, mutating=True), methods=["POST"]),
        Route("/app/api/recap/month", _plan_api(month_recap_get, mutating=False), methods=["GET"]),
    ]

    # ------------------------------------------------------------ usage --
    # usage.py: privacy-first usage counts. POST /app/api/usage batches whitelisted events
    # (daily counters only; DNT / GPC / "Don't count my usage" drop them); GET
    # /app/api/usage/summary is owners only (access owners), last 30 days.
    from . import usage as _usage
    usage_svc = _usage.Usage(store) if store is not None else None
    if usage_svc is not None:
        acct.on_delete("usage counts", usage_svc.forget)

    async def usage_post(request: Request, user_id: str) -> Response:
        if usage_svc is None or store is None:
            return JSONResponse({"counted": 0})
        raw = await request.body()
        if len(raw) > _usage.MAX_BODY:
            return _err(413, "too many events")
        if request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1" \
                or store.user_doc(user_id, "profile").load().get("usage_off") is True:
            return JSONResponse({"counted": 0})
        body = json.loads(raw or b"null")
        n = await anyio.to_thread.run_sync(lambda: usage_svc.record(user_id, body))
        return JSONResponse({"counted": n})

    async def usage_summary(request: Request, user_id: str) -> Response:
        if not auth.is_owner(user_id):
            return _err(403, "Only the app's owners can see usage.")
        if usage_svc is None:
            return _err(503, "Usage isn't available on this server.")
        return JSONResponse(await anyio.to_thread.run_sync(usage_svc.summary))

    home_routes += [
        Route("/app/api/usage", _api(usage_post, mutating=True), methods=["POST"]),
        Route("/app/api/usage/summary", _api(usage_summary, mutating=False), methods=["GET"]),
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

    # ------------------------------------------------- privacy & legal --
    # legal.py documents (also served in-app), consent.py (terms / privacy / 16+ / health
    # opt-in, re-asked when legal.VERSION changes), account.py (download my data, delete my
    # account). Coaches can use all of these too (COACH_PATHS).
    def _core_delete_hooks() -> None:
        if logins is not None:
            acct.on_delete("garmin", lambda u: logins.disconnect(u, token_store))
        elif token_store is not None:
            acct.on_delete("garmin", token_store.delete)
        if auth.oura is not None:
            acct.on_delete("oura", lambda u: auth.oura.disconnect(u))  # type: ignore[union-attr]
        if auth.whoop is not None:
            acct.on_delete("whoop", lambda u: auth.whoop.forget_tokens(u))  # type: ignore[union-attr]
        if auth.calendar is not None:
            acct.on_delete("google calendar", lambda u: auth.calendar.disconnect(u))  # type: ignore[union-attr]  # revokes the Google token
        acct.on_delete("coach links", auth.coach_links.forget_user)
        acct.on_delete("membership and passkeys", auth.access.forget_user)
    _core_delete_hooks()

    async def legal_doc(request: Request, user_id: str) -> Response:
        slug = request.path_params["doc"]
        if slug not in legal.DOCS:
            return _err(404, "not found")
        return JSONResponse({"slug": slug, "title": legal.DOCS[slug][0], "version": legal.VERSION,
                             "updated": legal.UPDATED, "operator": legal.OPERATOR,
                             "html": legal.body_html(slug, settings.contact_email)})

    async def consent_get(request: Request, user_id: str) -> Response:
        v = await anyio.to_thread.run_sync(lambda: consents.view(user_id))
        return JSONResponse(dict(v, contact=legal.contact_email(settings.contact_email)))

    async def consent_post(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        try:
            v = await anyio.to_thread.run_sync(lambda: consents.accept(user_id, body))
        except _consent.ConsentError as e:
            return _err(400, str(e))
        log_event(logger, logging.INFO, "terms_accepted", user_id=user_id, version=legal.VERSION)
        return JSONResponse(v)

    async def account_export(request: Request, user_id: str) -> Response:
        try:
            blob = await anyio.to_thread.run_sync(lambda: acct.export_zip(user_id, settings.contact_email))
        except _account.RateLimited:
            return _err(429, "You've downloaded your data a few times already. Try again in an hour.")
        log_event(logger, logging.INFO, "account_exported", user_id=user_id)
        day = (plans.today(user_id) if plans else date.today()).isoformat()
        return Response(blob, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="rabbit-data-{day}.zip"'})

    async def account_delete(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict) or body.get("confirm") != "DELETE":
            return _err(400, "Type DELETE to confirm.")
        if auth.is_owner(user_id):
            return _err(409, "The owner account can't be deleted from the app.")
        out = await acct.delete(user_id, final=auth.revoke_user)
        log_event(logger, logging.WARNING, "account_deleted", user_id=user_id,
                  files=out["files"], failed=",".join(out["failed"]))
        resp = JSONResponse({"ok": True, "failed": out["failed"]})
        auth.logout(request, resp)
        return resp

    legal_routes: list[BaseRoute] = [
        Route("/app/api/legal/{doc}", _api(legal_doc, mutating=False), methods=["GET"]),
        Route("/app/api/consent", _api(consent_get, mutating=False), methods=["GET"]),
        Route("/app/api/consent", _api(consent_post, mutating=True), methods=["POST"]),
        Route("/app/api/account/export", _api(account_export, mutating=False), methods=["GET"]),
        Route("/app/api/account/delete", _api(account_delete, mutating=True), methods=["POST"]),
        Route("/app/security", legal_page, methods=["GET"]),
        Route("/app/guidelines", legal_page, methods=["GET"]),
    ]

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
        *legal_routes,
        *reward_routes,
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
        Route("/app/api/events/days", _plan_api(events_days, mutating=False), methods=["GET"]),
        Route("/app/api/events/{event_id}/occurrences/{day}", _plan_api(event_occurrence, mutating=True),
              methods=["POST"]),
        Route("/app/api/events/{event_id}/end", _plan_api(event_end, mutating=True), methods=["POST"]),
        Route("/app/api/events/{event_id}/calendar.ics", _plan_api(event_ics, mutating=False), methods=["GET"]),
        Route("/app/api/calendar/feed", _plan_api(cal_feed_get, mutating=False), methods=["GET"]),
        Route("/app/api/calendar/feed", _plan_api(cal_feed_post, mutating=True), methods=["POST"]),
        Route("/app/api/calendar/feed", _plan_api(cal_feed_delete, mutating=True), methods=["DELETE"]),
        Route("/app/cal/{token}", cal_feed_public, methods=["GET", "HEAD"]),
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
        Route("/app/api/calendar/insights", _plan_api(cal_insights_get, mutating=False), methods=["GET"]),
        Route("/app/api/calendar/insights", _plan_api(cal_insights_post, mutating=True), methods=["POST"]),
        Route("/app/auth/calendar/start", calendar_start, methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_get, mutating=False), methods=["GET"]),
        Route("/app/api/oura", _plan_api(oura_delete, mutating=True), methods=["DELETE"]),
        Route("/app/api/recovery", _plan_api(recovery_get, mutating=False), methods=["GET"]),
        Route("/app/api/whoop", _plan_api(whoop_delete, mutating=True), methods=["DELETE"]),
        Route("/app/auth/whoop/start", whoop_start, methods=["GET"]),
        Route("/app/auth/whoop/callback", whoop_callback, methods=["GET"]),
        Route("/app/auth/oura/start", oura_start, methods=["GET"]),
        Route("/app/auth/oura/callback", oura_callback, methods=["GET"]),
        Route("/app/api/plan/travel", _plan_api(travel_add, mutating=True), methods=["POST"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_get, mutating=False), methods=["GET"]),
        Route("/app/api/racepack", _plan_api(racepack_get, mutating=False), methods=["GET"]),
        Route("/app/api/events/{event_id}/checklist", _plan_api(checklist_get, mutating=False), methods=["GET"]),
        Route("/app/api/events/{event_id}/checklist", _plan_api(checklist_post, mutating=True), methods=["POST"]),
        Route("/app/api/checklist/summary", _plan_api(checklist_summary, mutating=False), methods=["GET"]),
        Route("/app/api/checklist/next", _plan_api(checklist_next, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_get, mutating=False), methods=["GET"]),
        Route("/app/api/share", _plan_api(share_create, mutating=True), methods=["POST"]),
        Route("/app/api/share", _plan_api(share_delete, mutating=True), methods=["DELETE"]),
        Route("/app/s/{token}", share_page, methods=["GET"]),
        *race_routes,
        *raceweek_routes,
        *directory_routes,
        *community_routes,
        *block_routes,
        *bloom_routes,
        *tp_routes,
        *friends_routes,
        Route("/app/privacy", legal_page, methods=["GET"]),
        Route("/app/about", legal_page, methods=["GET"]),
        Route("/app/terms", legal_page, methods=["GET"]),
        Route("/app/api/plan/adjust", _plan_api(adjust_post, mutating=True), methods=["POST"]),
        Route("/app/api/races", _plan_api(races_get, mutating=False), methods=["GET"]),
        Route("/app/api/races/train", _plan_api(races_train, mutating=True), methods=["POST"]),
        Route("/app/api/races/tuneup", _plan_api(races_tuneup, mutating=True), methods=["POST"]),
        Route("/app/api/plan/preview", _plan_api(plan_preview, mutating=True), methods=["POST"]),
        Route("/app/api/plan/levers", _plan_api(plan_levers, mutating=True), methods=["POST"]),
        Route("/app/api/plan/levers/undo", _plan_api(plan_levers_undo, mutating=True), methods=["POST"]),
        Route("/app/api/plan/weekcheck", _plan_api(weekcheck_get, mutating=False), methods=["GET"]),
        Route("/app/api/plan/weekcheck", _plan_api(weekcheck_post, mutating=True), methods=["POST"]),
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
