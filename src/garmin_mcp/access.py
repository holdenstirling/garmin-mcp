"""Invite links, invited members and passkeys for the Rabbit web app.

People join without Google and without being added to ``ALLOWED_GOOGLE_USERS``:

* The owner (``OWNER_USER_IDS``, else every allowlisted Google user; members too when
  ``MEMBERS_CAN_INVITE``) creates an invite link ``/app/join/<token>``. The token is 32
  random bytes; only its SHA-256 is stored. Invites have ``max_uses`` (default 10), an
  expiry (default 14 days), can be revoked, and record who joined.
* Joining asks for a first name and an email (contact only: normalized, never verified,
  never shown to other athletes) and creates a passkey. The new user id is ``u_<hex>``
  and goes into the ``members`` registry, which ``WebAuth.user_for`` accepts like the
  allowlist. Removing a member drops their passkeys and kills their sessions.
* Any athlete (Google or member) can register passkeys and sign in with them.

Storage (global docs, Fernet-encrypted like everything in ``AppStore``):
``invites`` ``{id: {hash, created_by, created, expires, max_uses, uses: [{user_id, at, inviter}],
revoked}}``, ``members`` ``{user_id: {name, email, invited_by, invite_id, joined}}``,
``passkeys`` ``{"creds": {cred_id: {user_id, public_key, sign_count, alg, name, created,
last_used, transports}}, "handles": {user_id: user_handle}}``.

WebAuthn challenges are in memory only: single use, 5 minute TTL.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .appstore import AppStore
from .passkeys import b64u

INVITE_DEFAULT_USES = 10
INVITE_MAX_USES = 100
INVITE_DEFAULT_DAYS = 14
INVITE_MAX_DAYS = 90
MAX_LIVE_INVITES = 50
MAX_PASSKEYS = 10
CHALLENGE_TTL = 300
MAX_CHALLENGES = 500

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f<>]")


class AccessError(Exception):
    def __init__(self, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(raw: Any) -> str:
    e = str(raw or "").strip().lower()
    if len(e) > 254 or not _EMAIL_RE.match(e):
        raise AccessError("Enter a valid email address.")
    return e


def clean_name(raw: Any) -> str:
    n = " ".join(str(raw or "").split())
    if not n or len(n) > 40 or _CTRL_RE.search(n):
        raise AccessError("Enter your first name (up to 40 characters).")
    return n


def clean_label(raw: Any) -> str:
    n = " ".join(str(raw or "").split())[:40]
    return "" if _CTRL_RE.search(n) else n


@dataclass
class Challenge:
    kind: str                       # "join" | "login" | "add"
    created: float
    user_id: str = ""               # join: the new id; add: the signed-in user
    handle: str = ""                # WebAuthn user.id (base64url) for join/add
    invite_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class RateLimit:
    """Simple in-memory sliding window per key (client IP)."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            if len(self._hits) > 5000:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            ok = len(recent) < self.limit
            if ok:
                recent.append(now)
            self._hits[key] = recent
            return ok


class Access:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        self._lock = threading.Lock()
        self._invites = store.global_doc("invites")
        self._members_doc = store.global_doc("members")
        self._passkeys = store.global_doc("passkeys")
        # user_for() runs on every request: keep the member ids in memory (one process).
        self._member_ids: set[str] = set(self._members_doc.load())
        self._challenges: dict[str, Challenge] = {}

    # ---------------------------------------------------------- challenges --
    def new_challenge(self, ch: Challenge) -> str:
        key = b64u(secrets.token_bytes(32))
        with self._lock:
            now = self._clock()
            for k in [k for k, v in self._challenges.items() if now - v.created >= CHALLENGE_TTL]:
                del self._challenges[k]
            while len(self._challenges) >= MAX_CHALLENGES:
                del self._challenges[min(self._challenges, key=lambda k: self._challenges[k].created)]
            self._challenges[key] = ch
        return key

    def take_challenge(self, key: str, kind: str) -> Challenge | None:
        """Single use: the entry is gone after this, whatever the outcome."""
        with self._lock:
            ch = self._challenges.pop(key, None)
        if ch is None or ch.kind != kind or self._clock() - ch.created >= CHALLENGE_TTL:
            return None
        return ch

    # ------------------------------------------------------------- invites --
    def _invite_view(self, iid: str, inv: dict[str, Any], *, names: Callable[[str], str]) -> dict[str, Any]:
        now = self._clock()
        uses = inv.get("uses", [])
        status = ("revoked" if inv.get("revoked") else "expired" if inv["expires"] <= now
                  else "full" if len(uses) >= inv["max_uses"] else "active")
        return {"id": iid, "created": inv["created"], "expires": inv["expires"], "max_uses": inv["max_uses"],
                "uses": len(uses), "status": status, "created_by": inv["created_by"],
                "joined": [{"user_id": u["user_id"], "name": names(u["user_id"]), "at": u["at"]} for u in uses]}

    def create_invite(self, created_by: str, *, max_uses: Any = None, days: Any = None) -> tuple[str, str]:
        """Returns (token, invite id). The token is shown once; only its hash is kept."""
        uses = INVITE_DEFAULT_USES if max_uses in (None, "") else int(max_uses)
        d = INVITE_DEFAULT_DAYS if days in (None, "") else int(days)
        if not 1 <= uses <= INVITE_MAX_USES or not 1 <= d <= INVITE_MAX_DAYS:
            raise AccessError(f"Uses must be 1-{INVITE_MAX_USES} and days 1-{INVITE_MAX_DAYS}.")
        token = secrets.token_urlsafe(32)
        iid = secrets.token_hex(6)
        now = int(self._clock())

        def add(data: dict[str, Any]) -> None:
            live = [i for i in data.values() if not i.get("revoked") and i["expires"] > now]
            if len(live) >= MAX_LIVE_INVITES:
                raise AccessError("Too many open invite links. Revoke some first.")
            # drop long-dead invites so the doc stays small
            for k in [k for k, v in data.items() if v["expires"] < now - 180 * 86400]:
                del data[k]
            data[iid] = {"hash": token_hash(token), "created_by": created_by, "created": now,
                         "expires": now + d * 86400, "max_uses": uses, "uses": [], "revoked": False}
        self._invites.update(add)
        return token, iid

    def invites(self, *, by: str | None, names: Callable[[str], str]) -> list[dict[str, Any]]:
        data = self._invites.load()
        out = [self._invite_view(k, v, names=names) for k, v in data.items() if by is None or v["created_by"] == by]
        return sorted(out, key=lambda i: -i["created"])

    def revoke_invite(self, iid: str, *, by: str | None) -> None:
        def rev(data: dict[str, Any]) -> None:
            inv = data.get(iid)
            if inv is None or (by is not None and inv["created_by"] != by):
                raise AccessError("Invite not found.", 404)
            inv["revoked"] = True
        self._invites.update(rev)

    def find_invite(self, token: str) -> tuple[str, dict[str, Any]] | None:
        """A usable invite for this token, else None (unknown, revoked, expired or full)."""
        if not isinstance(token, str) or not 20 <= len(token) <= 100:
            return None
        h = token_hash(token)
        now = self._clock()
        for iid, inv in self._invites.load().items():
            if secrets.compare_digest(inv["hash"], h):
                if inv.get("revoked") or inv["expires"] <= now or len(inv.get("uses", [])) >= inv["max_uses"]:
                    return None
                return iid, inv
        return None

    def _use_invite(self, iid: str, user_id: str) -> str:
        """Record the use (with who made the invite, for the auto-follow). Returns the inviter."""
        now = self._clock()

        def use(data: dict[str, Any]) -> str:
            inv = data.get(iid)
            if (inv is None or inv.get("revoked") or inv["expires"] <= now
                    or len(inv.get("uses", [])) >= inv["max_uses"]):
                raise AccessError("This invite link has expired or is used up. Ask for a new one.", 410)
            inviter = str(inv.get("created_by") or "")
            inv.setdefault("uses", []).append({"user_id": user_id, "at": int(now), "inviter": inviter})
            return inviter
        return str(self._invites.update(use))

    # ------------------------------------------------------------- members --
    def is_member(self, user_id: str) -> bool:
        return user_id in self._member_ids

    def member_ids(self) -> set[str]:
        return set(self._member_ids)

    def member_emails(self) -> dict[str, str]:
        """email -> user id (friend search by email; emails are never shown to others)."""
        return {v["email"]: k for k, v in self._members_doc.load().items() if v.get("email")}

    def members(self, *, names: Callable[[str], str]) -> list[dict[str, Any]]:
        data = self._members_doc.load()
        creds = self._passkeys.load().get("creds", {})
        out = [{"user_id": k, "name": names(k) or v.get("name", ""), "email": v.get("email", ""),
                "joined": v.get("joined"), "invited_by": v.get("invited_by"),
                "passkeys": sum(1 for c in creds.values() if c["user_id"] == k)} for k, v in data.items()]
        return sorted(out, key=lambda m: -(m["joined"] or 0))

    def add_member(self, *, invite_id: str, user_id: str, name: str, email: str,
                   taken: Callable[[str], bool]) -> str:
        """Consume one use of the invite and register the member (atomically re-checked).
        Returns the inviter's user id (``""`` if unknown)."""
        with self._lock:
            if taken(email):
                raise AccessError("That email already has a Rabbit account. Sign in with your passkey instead.",
                                  409, signin=True)
            inviter = self._use_invite(invite_id, user_id)
            now = int(self._clock())

            def add(data: dict[str, Any]) -> None:
                data[user_id] = {"name": name, "email": email, "invited_by": inviter,
                                 "invite_id": invite_id, "joined": now}
            self._members_doc.update(add)
            self._member_ids.add(user_id)
            return inviter

    def inviter_of(self, user_id: str) -> str | None:
        """Who made the invite link this member joined with (None for Google athletes)."""
        m = self._members_doc.load().get(user_id) or {}
        return str(m["invited_by"]) if m.get("invited_by") else None

    def remove_member(self, user_id: str) -> None:
        def rm(data: dict[str, Any]) -> None:
            if user_id not in data:
                raise AccessError("Member not found.", 404)
            del data[user_id]
        self._members_doc.update(rm)
        with self._lock:
            self._member_ids.discard(user_id)
        self._passkeys.update(lambda d: d.__setitem__(
            "creds", {k: v for k, v in d.get("creds", {}).items() if v["user_id"] != user_id}))

    def forget_user(self, user_id: str) -> None:
        """Account deletion: drop the membership (if they joined by invite) and passkeys."""
        def rm(data: dict[str, Any]) -> None:
            data.pop(user_id, None)
        self._members_doc.update(rm)
        with self._lock:
            self._member_ids.discard(user_id)

        def pk(d: dict[str, Any]) -> None:
            d["creds"] = {k: v for k, v in d.get("creds", {}).items() if v.get("user_id") != user_id}
            (d.get("handles") or {}).pop(user_id, None)
        self._passkeys.update(pk)

    # ------------------------------------------------------------ passkeys --
    def user_handle(self, user_id: str) -> str:
        """Stable random WebAuthn user.id for this user (never the user id itself)."""
        def get(d: dict[str, Any]) -> str:
            handles = d.setdefault("handles", {})
            if user_id not in handles:
                handles[user_id] = b64u(secrets.token_bytes(16))
            return str(handles[user_id])
        return str(self._passkeys.update(get))

    def set_handle(self, user_id: str, handle: str) -> None:
        self._passkeys.update(lambda d: d.setdefault("handles", {}).__setitem__(user_id, handle))

    def credential(self, cred_id: str) -> dict[str, Any] | None:
        c = self._passkeys.load().get("creds", {}).get(cred_id)
        return dict(c) if c else None

    def handle_owner(self, handle: str) -> str | None:
        for uid, h in self._passkeys.load().get("handles", {}).items():
            if h == handle:
                return str(uid)
        return None

    def passkeys(self, user_id: str) -> list[dict[str, Any]]:
        creds = self._passkeys.load().get("creds", {})
        out = [{"id": k, "name": v.get("name") or "Passkey", "created": v.get("created"),
                "last_used": v.get("last_used")} for k, v in creds.items() if v["user_id"] == user_id]
        return sorted(out, key=lambda p: p["created"] or 0)

    def passkey_ids(self, user_id: str) -> list[str]:
        return [p["id"] for p in self.passkeys(user_id)]

    def add_passkey(self, user_id: str, *, cred_id: str, public_key: str, sign_count: int, alg: int,
                    name: str, transports: list[str]) -> None:
        now = int(self._clock())

        def add(d: dict[str, Any]) -> None:
            creds = d.setdefault("creds", {})
            if cred_id in creds:
                raise AccessError("That passkey is already registered.", 409)
            if sum(1 for c in creds.values() if c["user_id"] == user_id) >= MAX_PASSKEYS:
                raise AccessError(f"You can have up to {MAX_PASSKEYS} passkeys. Remove one first.")
            creds[cred_id] = {"user_id": user_id, "public_key": public_key, "sign_count": sign_count,
                              "alg": alg, "name": name or "Passkey", "created": now, "last_used": None,
                              "transports": transports}
        self._passkeys.update(add)

    def touch_passkey(self, cred_id: str, sign_count: int) -> None:
        now = int(self._clock())

        def touch(d: dict[str, Any]) -> None:
            c = d.get("creds", {}).get(cred_id)
            if c is not None:
                c["sign_count"], c["last_used"] = sign_count, now
        self._passkeys.update(touch)

    def remove_passkey(self, user_id: str, cred_id: str, *, keep_one: bool) -> None:
        def rm(d: dict[str, Any]) -> None:
            creds = d.get("creds", {})
            c = creds.get(cred_id)
            if c is None or c["user_id"] != user_id:
                raise AccessError("Passkey not found.", 404)
            if keep_one and sum(1 for v in creds.values() if v["user_id"] == user_id) <= 1:
                raise AccessError("This is your only way to sign in. Add another passkey before removing it.", 409)
            del creds[cred_id]
        self._passkeys.update(rm)


__all__ = ["Access", "AccessError", "Challenge", "RateLimit", "clean_label", "clean_name", "normalize_email",
           "token_hash"]
