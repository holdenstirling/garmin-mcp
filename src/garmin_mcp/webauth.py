"""Google sign-in and cookie sessions for the Rabbit web app.

Flow:
  1. ``GET /app/auth/google/start`` stores a random ``state`` + PKCE verifier in
     memory, sets a short-lived cookie holding the same ``state`` (binds the
     login to this browser: login CSRF / session fixation), and redirects to
     Google with ``openid email profile`` (all non-sensitive scopes).
  2. ``GET /app/auth/google/callback`` checks state against both the pending
     entry and the cookie, exchanges the code (server-side, with PKCE), reads
     the OIDC userinfo once and discards Google's tokens. The verified email
     must be allowlisted; Google's ``sub`` is pinned to the user_id on first
     sign-in and must match afterwards (emails can be reassigned, ``sub`` can't).
  3. A random session token goes in a ``__Host-`` cookie (HttpOnly, Secure,
     SameSite=Lax). Only its SHA-256 is stored, encrypted, so sessions survive
     restarts. Every request re-checks the allowlist.

Mutating API calls additionally require ``Origin == PUBLIC_BASE_URL`` and a JSON
content type (see ``guard``).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx2
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from .access import Access
from .appstore import AppStore
from .config import Settings
from .coaches import CoachLinks
from .gcalendar import SCOPE as CALENDAR_SCOPE
from .gcalendar import GoogleCalendar
from .oura import OuraClient
from .whoop import WhoopClient
from .logs import log_event

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

PENDING_TTL = 600
MAX_PENDING = 50  # per table (sign-in vs calendar/Oura connect); when full the oldest is evicted
MAX_SESSION_AGE = 180 * 86400  # absolute session lifetime, however active the session is
LAST_SEEN_WRITE_INTERVAL = 3600  # persist last_seen at most hourly per session


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def _is_google_photo(url: str) -> bool:
    """Profile photos are only ever loaded from Google's image CDN (see the app CSP)."""
    p = urlparse(url)
    return p.scheme == "https" and p.hostname == "lh3.googleusercontent.com" and len(url) < 1024


@dataclass
class _Pending:
    verifier: str
    created: float
    kind: str = "login"            # or "calendar": connecting Google Calendar
    user_id: str | None = None     # who asked (calendar flow)


class WebAuth:
    def __init__(self, settings: Settings, store: AppStore, google_client_secret: str,
                 *, dev_user: str | None = None, http: httpx2.AsyncClient | None = None,
                 clock: Any = time.time) -> None:
        self.s = settings
        self._secret = google_client_secret
        self._dev_user = dev_user
        self._http = http
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}          # sign-in
        self._connect_pending: dict[str, _Pending] = {}  # calendar / Oura connect
        self._store = store
        self._sessions_doc = store.global_doc("sessions")
        self._identities_doc = store.global_doc("identities")
        self._sessions: dict[str, dict[str, Any]] = self._sessions_doc.load()
        # Invite links, invited members and passkeys (access.py; routes in passkey_web.py).
        self.access = Access(store, clock=clock)
        # Human coaches invited by an allowlisted athlete may sign in too (see coaches.py).
        self.calendar: GoogleCalendar | None = (
            GoogleCalendar(store, settings.google_client_id, google_client_secret, http=http, clock=clock)
            if settings.google_client_id else None)
        self.oura: OuraClient | None = None  # set by the server when an Oura app is configured
        self.whoop: WhoopClient | None = None  # set by the server when a WHOOP app is configured
        self.coach_links = CoachLinks(store, athlete_emails=lambda: {
            k.lower(): v for k, v in self.s.allowed_google_users.items()}, clock=clock)
        secure = settings.is_https
        # __Host- requires Secure; plain http is only allowed for localhost dev.
        self.session_cookie = "__Host-rabbit_session" if secure else "rabbit_session"
        self.state_cookie = "__Host-rabbit_oauth" if secure else "rabbit_oauth"
        self._secure = secure

    # ------------------------------------------------------------- helpers --
    def _allowed_user_ids(self) -> set[str]:
        return set(self.s.allowed_google_users.values()) | self.access.member_ids()

    def is_athlete(self, user_id: str) -> bool:
        """Allowlisted Google user or invited member (never a coach-only account)."""
        return not user_id.startswith("coach_") and user_id in self._allowed_user_ids()

    def athlete_emails(self) -> dict[str, str]:
        """Lower-case email -> athlete id: the allowlist plus invited members (whose emails
        are unverified, so this must never decide who may sign in)."""
        out = self.access.member_emails()
        out.update({k.lower(): v for k, v in self.s.allowed_google_users.items()})
        return out

    def is_owner(self, user_id: str) -> bool:
        owners = set(self.s.owner_user_ids) or set(self.s.allowed_google_users.values())
        return user_id in owners and not user_id.startswith("coach_")

    def can_invite(self, user_id: str) -> bool:
        return self.is_owner(user_id) or (self.s.members_can_invite and self.is_athlete(user_id))

    @property
    def rp_id(self) -> str:
        return urlparse(self.s.public_base_url).hostname or ""

    def mint_session(self, user_id: str) -> str:
        """New session for ``user_id`` (Google and passkey sign-in); returns the cookie value."""
        token = secrets.token_urlsafe(32)
        now = int(self._clock())
        rec = {"user_id": user_id, "created": now, "last_seen": now,
               "expires": now + self.s.app_session_ttl_seconds}
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if v["expires"] > now}
            self._sessions[_hash(token)] = rec
            self._sessions_doc.save(self._sessions)
        return token

    def set_session_cookie(self, resp: Response, token: str) -> None:
        self._cookie(resp, self.session_cookie, token, self.s.app_session_ttl_seconds)

    def _cookie(self, resp: Response, name: str, value: str, max_age: int) -> None:
        resp.set_cookie(name, value, max_age=max_age, path="/", secure=self._secure,
                        httponly=True, samesite="lax")

    def _add_pending(self, state: str, pending: _Pending) -> None:
        """Remember a pending OAuth state. Sign-in and connect flows use separate tables, and a
        full table evicts its oldest entry, so nobody can lock others out by spamming /start."""
        table = self._pending if pending.kind == "login" else self._connect_pending
        with self._lock:
            for k in [k for k, v in table.items() if pending.created - v.created >= PENDING_TTL]:
                del table[k]
            while len(table) >= MAX_PENDING:
                del table[min(table, key=lambda k: table[k].created)]
            table[state] = pending

    def _pop_pending(self, state: str) -> _Pending | None:
        if not state:
            return None
        with self._lock:
            return self._pending.pop(state, None) or self._connect_pending.pop(state, None)

    def _fail(self, reason: str) -> RedirectResponse:
        resp = RedirectResponse(f"/app/?auth_error={reason}", status_code=302)
        resp.delete_cookie(self.state_cookie, path="/", secure=self._secure, httponly=True,
                           samesite="lax")
        return resp

    # --------------------------------------------------------------- login --
    async def start(self, request: Request) -> Response:
        state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        self._add_pending(state, _Pending(verifier, self._clock()))
        query = urlencode({
            "client_id": self.s.google_client_id,
            "redirect_uri": self.s.google_callback_url,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })
        resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}", status_code=302)
        self._cookie(resp, self.state_cookie, state, PENDING_TTL)
        return resp

    # ------------------------------------------------------------ calendar --
    async def start_calendar(self, request: Request) -> Response:
        """Connect Google Calendar (read-only) for the signed-in athlete. Same client and
        callback as sign-in; the pending record remembers who asked."""
        user_id = self.user_for(request)
        if user_id is None or self.calendar is None:
            return self._fail("not_allowed")
        state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        self._add_pending(state, _Pending(verifier, self._clock(), kind="calendar", user_id=user_id))
        query = urlencode({
            "client_id": self.s.google_client_id, "redirect_uri": self.s.google_callback_url,
            "response_type": "code", "scope": f"openid email {CALENDAR_SCOPE}", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
        })
        resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}", status_code=302)
        self._cookie(resp, self.state_cookie, state, PENDING_TTL)
        return resp

    async def _finish_calendar(self, request: Request, pending: _Pending, code: str) -> Response:
        if self.user_for(request) != pending.user_id or self.calendar is None:
            return self._fail("not_allowed")
        client = self._http or httpx2.AsyncClient(timeout=10)
        try:
            r = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": self.s.google_client_id, "client_secret": self._secret, "code": code,
                "code_verifier": pending.verifier, "grant_type": "authorization_code",
                "redirect_uri": self.s.google_callback_url}, headers={"Accept": "application/json"})
            r.raise_for_status()
            self.calendar.save_tokens(str(pending.user_id), r.json())
        except Exception as e:
            log_event(logger, logging.WARNING, "gcal_connect_failed", error=type(e).__name__)
            return RedirectResponse("/app/?calendar=failed", status_code=302)
        finally:
            if self._http is None:
                await client.aclose()
        log_event(logger, logging.INFO, "gcal_connected", user_id=pending.user_id)
        resp = RedirectResponse("/app/?calendar=connected", status_code=302)
        resp.delete_cookie(self.state_cookie, path="/", secure=self._secure, httponly=True, samesite="lax")
        return resp

    # ---------------------------------------------------------------- oura --
    async def start_oura(self, request: Request) -> Response:
        user_id = self.user_for(request)
        if user_id is None or self.oura is None:
            return self._fail("not_allowed")
        state = secrets.token_urlsafe(32)
        self._add_pending(state, _Pending("", self._clock(), kind="oura", user_id=user_id))
        resp = RedirectResponse(self.oura.authorize_url(state), status_code=302)
        self._cookie(resp, self.state_cookie, state, PENDING_TTL)
        return resp

    async def oura_callback(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        cookie_state = request.cookies.get(self.state_cookie, "")
        pending = self._pop_pending(state)
        if (pending is None or pending.kind != "oura" or self._clock() - pending.created > PENDING_TTL
                or not secrets.compare_digest(state, cookie_state) or self.oura is None):
            return RedirectResponse("/app/?oura=failed", status_code=302)
        if not code or self.user_for(request) != pending.user_id:
            return RedirectResponse("/app/?oura=failed", status_code=302)
        try:
            await self.oura.exchange(str(pending.user_id), code)
        except Exception as e:
            log_event(logger, logging.WARNING, "oura_connect_failed", error=type(e).__name__)
            return RedirectResponse("/app/?oura=failed", status_code=302)
        log_event(logger, logging.INFO, "oura_connected", user_id=pending.user_id)
        resp = RedirectResponse("/app/?oura=connected", status_code=302)
        resp.delete_cookie(self.state_cookie, path="/", secure=self._secure, httponly=True, samesite="lax")
        return resp

    # --------------------------------------------------------------- whoop --
    async def start_whoop(self, request: Request) -> Response:
        user_id = self.user_for(request)
        if user_id is None or self.whoop is None:
            return self._fail("not_allowed")
        state = secrets.token_urlsafe(32)
        self._add_pending(state, _Pending("", self._clock(), kind="whoop", user_id=user_id))
        resp = RedirectResponse(self.whoop.authorize_url(state), status_code=302)
        self._cookie(resp, self.state_cookie, state, PENDING_TTL)
        return resp

    async def whoop_callback(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        cookie_state = request.cookies.get(self.state_cookie, "")
        pending = self._pop_pending(state)
        if (pending is None or pending.kind != "whoop" or self._clock() - pending.created > PENDING_TTL
                or not secrets.compare_digest(state, cookie_state) or self.whoop is None):
            return RedirectResponse("/app/?whoop=failed", status_code=302)
        if not code or self.user_for(request) != pending.user_id:
            return RedirectResponse("/app/?whoop=failed", status_code=302)
        try:
            await self.whoop.exchange(str(pending.user_id), code)
        except Exception as e:
            log_event(logger, logging.WARNING, "whoop_connect_failed", error=type(e).__name__)
            return RedirectResponse("/app/?whoop=failed", status_code=302)
        log_event(logger, logging.INFO, "whoop_connected", user_id=pending.user_id)
        resp = RedirectResponse("/app/?whoop=connected", status_code=302)
        resp.delete_cookie(self.state_cookie, path="/", secure=self._secure, httponly=True, samesite="lax")
        return resp

    async def callback(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        cookie_state = request.cookies.get(self.state_cookie, "")
        pending = self._pop_pending(state)
        if (pending is None or self._clock() - pending.created > PENDING_TTL
                or not secrets.compare_digest(state, cookie_state)):
            return self._fail("expired")
        if not code:
            return self._fail("cancelled")
        if pending.kind == "calendar":
            return await self._finish_calendar(request, pending, code)
        try:
            sub, email, verified, profile = await self._google_identity(code, pending.verifier)
        except Exception as e:
            log_event(logger, logging.WARNING, "google_exchange_failed", error=type(e).__name__)
            return self._fail("google")

        user_id = None
        if verified:
            user_id = (self.s.allowed_google_users.get(email.lower())
                       or self.coach_links.user_id_for_email(email))
        if user_id is None:
            log_event(logger, logging.WARNING, "google_user_not_allowed", verified=verified)
            return self._fail("not_allowed")
        if not self._bind_identity(sub, user_id):
            log_event(logger, logging.WARNING, "google_identity_mismatch", user_id=user_id)
            return self._fail("not_allowed")

        self._store.user_doc(user_id, "account").save(profile)
        token = self.mint_session(user_id)
        log_event(logger, logging.INFO, "app_login_ok", user_id=user_id)
        resp = RedirectResponse("/app/", status_code=302)
        resp.delete_cookie(self.state_cookie, path="/", secure=self._secure, httponly=True,
                           samesite="lax")
        self.set_session_cookie(resp, token)
        return resp

    def _bind_identity(self, sub: str, user_id: str) -> bool:
        """Pin Google ``sub`` <-> user_id on first sign-in; require a match afterwards."""
        def bind(data: dict[str, Any]) -> bool:
            subs: dict[str, str] = data.setdefault("google_sub", {})
            bound_user = subs.get(sub)
            if bound_user is not None:
                return bound_user == user_id
            if user_id in subs.values():
                return False  # this user already signed in with a different Google account
            subs[sub] = user_id
            return True
        return bool(self._identities_doc.update(bind))

    async def _google_identity(self, code: str,
                               verifier: str) -> tuple[str, str, bool, dict[str, str]]:
        client = self._http or httpx2.AsyncClient(timeout=10)
        try:
            r = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": self.s.google_client_id,
                "client_secret": self._secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.s.google_callback_url,
            }, headers={"Accept": "application/json"})
            r.raise_for_status()
            access = r.json().get("access_token")
            if not access:
                raise RuntimeError("no access_token from Google")
            u = await client.get(GOOGLE_USERINFO_URL,
                                 headers={"Authorization": f"Bearer {access}"})
            u.raise_for_status()
            info = u.json()
            sub, email = str(info["sub"]), str(info.get("email", ""))
            verified = info.get("email_verified") is True
            if not sub or not email:
                raise RuntimeError("incomplete userinfo")
            name = str(info.get("given_name") or info.get("name") or "")[:80]
            picture = str(info.get("picture") or "")
            if not _is_google_photo(picture):
                picture = ""
            return sub, email, verified, {"name": name, "picture": picture}
        finally:
            if self._http is None:
                await client.aclose()

    # ------------------------------------------------------------ sessions --
    def user_for(self, request: Request) -> str | None:
        if self._dev_user:
            return self._dev_user
        token = request.cookies.get(self.session_cookie)
        if not token:
            return None
        key = _hash(token)
        now = int(self._clock())
        with self._lock:
            rec = self._sessions.get(key)
            if rec is None or rec["expires"] <= now:
                return None
            if now - rec.get("created", now) >= MAX_SESSION_AGE:
                return None  # absolute lifetime: sign in again
            if rec["user_id"] not in self._allowed_user_ids() \
                    and not self.coach_links.is_coach_user(rec["user_id"]):
                return None  # removed from the allowlist / members (or every athlete removed the coach)
            if now - rec["last_seen"] > LAST_SEEN_WRITE_INTERVAL:
                rec["last_seen"] = now
                rec["expires"] = min(now + self.s.app_session_ttl_seconds,  # sliding, but capped
                                     rec.get("created", now) + MAX_SESSION_AGE)
                self._sessions_doc.save(self._sessions)
            return str(rec["user_id"])

    def logout(self, request: Request, resp: Response) -> None:
        token = request.cookies.get(self.session_cookie)
        if token:
            with self._lock:
                if self._sessions.pop(_hash(token), None) is not None:
                    self._sessions_doc.save(self._sessions)
        resp.delete_cookie(self.session_cookie, path="/", secure=self._secure, httponly=True,
                           samesite="lax")

    def profile(self, user_id: str) -> dict[str, str]:
        data = self._store.user_doc(user_id, "account").load()
        return {"name": str(data.get("name", "")), "picture": str(data.get("picture", ""))}

    def revoke_user(self, user_id: str) -> None:
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items()
                              if v["user_id"] != user_id}
            self._sessions_doc.save(self._sessions)

    # --------------------------------------------------------------- guard --
    def check_origin(self, request: Request) -> bool:
        """Mutating requests must come from our own page."""
        origin = request.headers.get("origin", "")
        if origin != self.s.public_base_url:
            return False
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        return ctype == "application/json"
