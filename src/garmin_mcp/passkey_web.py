"""Routes for invite links, joining with a passkey, passkey sign-in and passkey management.

See ``access.py`` for the model and ``passkeys.py`` for WebAuthn verification.

Public (no session; Host check, Origin + JSON on POST, per-IP rate limit):
  GET  /app/api/join/{token}               is this invite usable?
  POST /app/auth/join/{token}/options      {name, email} -> creation options
  POST /app/auth/join/{token}/verify       {credential} -> new member + session cookie
  POST /app/auth/passkey/options           -> request options (discoverable credentials)
  POST /app/auth/passkey/verify            {credential} -> session cookie
Signed in (``_api``; coach-only accounts get 403 there):
  GET /app/api/access, GET/POST /app/api/passkeys, POST /app/api/passkeys/options,
  DELETE /app/api/passkeys/{cred_id}, POST /app/api/invites, DELETE /app/api/invites/{id},
  DELETE /app/api/members/{user_id}
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from .access import AccessError, Challenge, RateLimit, clean_label, clean_name, normalize_email
from .logs import log_event
from .passkeys import ALGS, WebAuthnError, b64u, client_challenge, verify_authentication, verify_registration
from .webauth import WebAuth

logger = logging.getLogger(__name__)

TIMEOUT_MS = 300_000
FAILED = "That passkey didn't work. Please try again."
BAD_INVITE = "This invite link isn't valid any more. Ask the person who sent it for a new one."


def _err(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status, headers={"Cache-Control": "no-store"})


def _ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def make_routes(*, auth: WebAuth, api: Callable[..., Callable[[Request], Awaitable[Response]]],
                host_ok: Callable[[Request], bool], read_json: Callable[[Request], Awaitable[Any]],
                join_limit: RateLimit | None = None, login_limit: RateLimit | None = None,
                on_join: Callable[[str, str, str], None] | None = None) -> list[BaseRoute]:
    """``on_join(new_user_id, inviter_id, first_name)`` runs after a successful join (best
    effort: the auto-follow + the inviter's moment; a failure never fails the join)."""
    acc = auth.access
    base = auth.s.public_base_url
    join_rl = join_limit or RateLimit(30, 600)
    login_rl = login_limit or RateLimit(30, 600)

    def first_name(uid: str) -> str:
        n = (auth.profile(uid).get("name") or "").strip()
        return n.split()[0][:40] if n else ""

    def ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def creation_options(challenge: str, handle: str, name: str, display: str, exclude: list[str]) -> dict[str, Any]:
        return {
            "challenge": challenge,
            "rp": {"id": auth.rp_id, "name": "rabbt"},
            "user": {"id": handle, "name": name, "displayName": display},
            "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in ALGS],
            "timeout": TIMEOUT_MS,
            "attestation": "none",
            "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True,
                                       "userVerification": "preferred"},
            "excludeCredentials": [{"type": "public-key", "id": c} for c in exclude],
        }

    def public(kind: str, handler: Callable[[Request], Awaitable[Response]], *, post: bool):
        rl = join_rl if kind == "join" else login_rl

        async def endpoint(request: Request) -> Response:
            if not host_ok(request):
                return _err(400, "bad host")
            if post and not auth.check_origin(request):
                return _err(403, "bad origin")
            if not rl.allow(ip(request)):
                return _err(429, "Too many tries. Wait a few minutes and try again.")
            try:
                return await handler(request)
            except AccessError as e:
                return _err(e.status, e.message, **e.extra)
            except WebAuthnError as e:
                log_event(logger, logging.WARNING, "passkey_failed", step=kind, reason=str(e)[:80])
                return _err(400, FAILED)
            except (ValueError, KeyError, TypeError):
                return _err(400, "bad request")
        return endpoint

    def user_route(handler: Callable[[Request, str], Awaitable[Response]]):
        async def wrapped(request: Request, user_id: str) -> Response:
            try:
                return await handler(request, user_id)
            except AccessError as e:
                return _err(e.status, e.message, **e.extra)
            except WebAuthnError as e:
                log_event(logger, logging.WARNING, "passkey_failed", step="add", reason=str(e)[:80])
                return _err(400, FAILED)
        return wrapped

    def credential_of(body: Any) -> dict[str, Any]:
        cred = body.get("credential") if isinstance(body, dict) else None
        if not isinstance(cred, dict):
            raise WebAuthnError("no credential")
        return cred

    def email_taken(email: str) -> bool:
        return email in auth.athlete_emails()

    # ------------------------------------------------------------- joining --
    async def join_info(request: Request) -> Response:
        found = acc.find_invite(request.path_params["token"])
        if found is None:
            return _err(404, BAD_INVITE)
        return _ok({"ok": True, "inviter": first_name(found[1]["created_by"]),
                    "signed_in": auth.user_for(request) is not None})

    async def join_options(request: Request) -> Response:
        body = await read_json(request)
        if not isinstance(body, dict):
            raise ValueError("bad body")
        found = acc.find_invite(request.path_params["token"])
        if found is None:
            return _err(404, BAD_INVITE)
        name, email = clean_name(body.get("name")), normalize_email(body.get("email"))
        if email_taken(email):
            raise AccessError("That email already has a rabbt account. Sign in with your passkey instead.",
                              409, signin=True)
        user_id = "u_" + secrets.token_hex(8)
        handle = b64u(secrets.token_bytes(16))
        ch = acc.new_challenge(Challenge("join", acc._clock(), user_id=user_id, handle=handle,
                                         invite_id=found[0], data={"name": name, "email": email}))
        return _ok({"publicKey": creation_options(ch, handle, email, name, [])})

    async def join_verify(request: Request) -> Response:
        body = await read_json(request)
        cred = credential_of(body)
        challenge = client_challenge(cred)
        ch = acc.take_challenge(challenge, "join")
        if ch is None:
            raise WebAuthnError("unknown or used challenge")
        found = acc.find_invite(request.path_params["token"])
        if found is None or found[0] != ch.invite_id:
            return _err(404, BAD_INVITE)
        reg = verify_registration(cred, challenge=challenge, rp_id=auth.rp_id, origin=base)
        if acc.credential(reg.cred_id) is not None:
            raise AccessError("That passkey is already registered.", 409)
        inviter = acc.add_member(invite_id=ch.invite_id, user_id=ch.user_id, name=ch.data["name"],
                                 email=ch.data["email"], taken=email_taken)
        acc.set_handle(ch.user_id, ch.handle)
        acc.add_passkey(ch.user_id, cred_id=reg.cred_id, public_key=reg.public_key, sign_count=reg.sign_count,
                        alg=reg.alg, name=clean_label(body.get("label")) or "Passkey", transports=reg.transports)
        auth._store.user_doc(ch.user_id, "account").save({"name": ch.data["name"], "picture": ""})
        log_event(logger, logging.INFO, "member_joined", user_id=ch.user_id, invite=ch.invite_id)
        if on_join is not None and inviter:
            try:
                on_join(ch.user_id, inviter, ch.data["name"])
            except Exception as e:  # the account exists either way
                log_event(logger, logging.WARNING, "member_join_hook_failed", user_id=ch.user_id,
                          error=type(e).__name__)
        resp = _ok({"ok": True})
        auth.set_session_cookie(resp, auth.mint_session(ch.user_id))
        return resp

    # ------------------------------------------------------------- sign in --
    async def login_options(request: Request) -> Response:
        ch = acc.new_challenge(Challenge("login", acc._clock()))
        return _ok({"publicKey": {"challenge": ch, "rpId": auth.rp_id, "timeout": TIMEOUT_MS,
                                  "userVerification": "preferred", "allowCredentials": []}})

    async def login_verify(request: Request) -> Response:
        cred = credential_of(await read_json(request))
        challenge = client_challenge(cred)
        if acc.take_challenge(challenge, "login") is None:
            raise WebAuthnError("unknown or used challenge")
        cred_id = cred.get("id")
        if not isinstance(cred_id, str) or (cred.get("rawId") not in (None, cred_id)):
            raise WebAuthnError("bad credential id")
        stored = acc.credential(cred_id)
        if stored is None:
            return _err(400, "rabbt doesn't know that passkey. It may have been removed.")
        handle = (cred.get("response") or {}).get("userHandle")
        if handle and acc.handle_owner(handle) != stored["user_id"]:
            raise WebAuthnError("user handle mismatch")
        count, _ = verify_authentication(cred, challenge=challenge, rp_id=auth.rp_id, origin=base,
                                         public_key=stored["public_key"], sign_count=int(stored["sign_count"]))
        uid = str(stored["user_id"])
        if not auth.is_athlete(uid):
            log_event(logger, logging.WARNING, "passkey_user_not_allowed", user_id=uid)
            return _err(403, "This account no longer has access to rabbt.")
        acc.touch_passkey(cred_id, count)
        log_event(logger, logging.INFO, "app_login_ok", user_id=uid, method="passkey")
        resp = _ok({"ok": True})
        auth.set_session_cookie(resp, auth.mint_session(uid))
        return resp

    # ------------------------------------------------- signed-in: passkeys --
    async def passkeys_get(request: Request, user_id: str) -> Response:
        return _ok({"passkeys": acc.passkeys(user_id), "google": auth_google(user_id)})

    def auth_google(user_id: str) -> bool:
        return user_id in set(auth.s.allowed_google_users.values())

    async def passkey_options(request: Request, user_id: str) -> Response:
        handle = acc.user_handle(user_id)
        name = auth.profile(user_id).get("name") or "rabbt athlete"
        ch = acc.new_challenge(Challenge("add", acc._clock(), user_id=user_id, handle=handle))
        label = next((e for e, u in auth.athlete_emails().items() if u == user_id), name)
        return _ok({"publicKey": creation_options(ch, handle, label, name, acc.passkey_ids(user_id))})

    async def passkey_add(request: Request, user_id: str) -> Response:
        body = await read_json(request)
        cred = credential_of(body)
        challenge = client_challenge(cred)
        ch = acc.take_challenge(challenge, "add")
        if ch is None or ch.user_id != user_id:
            raise WebAuthnError("unknown or used challenge")
        reg = verify_registration(cred, challenge=challenge, rp_id=auth.rp_id, origin=base)
        acc.add_passkey(user_id, cred_id=reg.cred_id, public_key=reg.public_key, sign_count=reg.sign_count,
                        alg=reg.alg, name=clean_label(body.get("label")) or "Passkey", transports=reg.transports)
        log_event(logger, logging.INFO, "passkey_added", user_id=user_id)
        return _ok({"passkeys": acc.passkeys(user_id)}, 201)

    async def passkey_remove(request: Request, user_id: str) -> Response:
        acc.remove_passkey(user_id, request.path_params["cred_id"], keep_one=not auth_google(user_id))
        return _ok({"passkeys": acc.passkeys(user_id)})

    # -------------------------------------------- signed-in: invites/members --
    async def access_get(request: Request, user_id: str) -> Response:
        owner = auth.is_owner(user_id)
        can = auth.can_invite(user_id)
        return _ok({
            "owner": owner, "can_invite": can,
            "invites": acc.invites(by=None if owner else user_id, names=first_name) if can else [],
            "members": acc.members(names=first_name) if owner else [],
            "passkeys": acc.passkeys(user_id), "google": auth_google(user_id),
        })

    async def invite_create(request: Request, user_id: str) -> Response:
        if not auth.can_invite(user_id):
            return _err(403, "Only the owner can create invite links.")
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        token, iid = acc.create_invite(user_id, max_uses=body.get("max_uses"), days=body.get("days"))
        log_event(logger, logging.INFO, "invite_created", user_id=user_id, invite=iid)
        inv = next(i for i in acc.invites(by=None, names=first_name) if i["id"] == iid)
        return _ok({"url": f"{base}/app/join/{token}", "invite": inv}, 201)

    async def invite_revoke(request: Request, user_id: str) -> Response:
        if not auth.can_invite(user_id):
            return _err(403, "Only the owner can manage invite links.")
        acc.revoke_invite(request.path_params["invite_id"], by=None if auth.is_owner(user_id) else user_id)
        return _ok({"ok": True})

    async def member_remove(request: Request, user_id: str) -> Response:
        if not auth.is_owner(user_id):
            return _err(403, "Only the owner can remove members.")
        target = request.path_params["user_id"]
        acc.remove_member(target)
        auth.revoke_user(target)
        log_event(logger, logging.INFO, "member_removed", user_id=user_id, member=target)
        return _ok({"ok": True})

    return [
        Route("/app/api/join/{token}", public("join", join_info, post=False), methods=["GET"]),
        Route("/app/auth/join/{token}/options", public("join", join_options, post=True), methods=["POST"]),
        Route("/app/auth/join/{token}/verify", public("join", join_verify, post=True), methods=["POST"]),
        Route("/app/auth/passkey/options", public("login", login_options, post=True), methods=["POST"]),
        Route("/app/auth/passkey/verify", public("login", login_verify, post=True), methods=["POST"]),
        Route("/app/api/access", api(user_route(access_get), mutating=False), methods=["GET"]),
        Route("/app/api/passkeys", api(user_route(passkeys_get), mutating=False), methods=["GET"]),
        Route("/app/api/passkeys/options", api(user_route(passkey_options), mutating=True), methods=["POST"]),
        Route("/app/api/passkeys", api(user_route(passkey_add), mutating=True), methods=["POST"]),
        Route("/app/api/passkeys/{cred_id}", api(user_route(passkey_remove), mutating=True), methods=["DELETE"]),
        Route("/app/api/invites", api(user_route(invite_create), mutating=True), methods=["POST"]),
        Route("/app/api/invites/{invite_id}", api(user_route(invite_revoke), mutating=True), methods=["DELETE"]),
        Route("/app/api/members/{user_id}", api(user_route(member_remove), mutating=True), methods=["DELETE"]),
    ]


__all__ = ["make_routes"]
