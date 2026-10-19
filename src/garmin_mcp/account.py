"""Your data, your call: "Download my data" and "Delete my account" (Me -> Privacy & legal).

Export
------
A zip of every per-user doc (``AppStore.user_doc_names``), decrypted, as pretty JSON, plus a
README. Secrets never leave: any key that looks like a credential (tokens, cookies, refresh /
access tokens, push keys and endpoints, hashes) is replaced with ``"[removed]"`` at any depth,
and the push subscription doc is dropped entirely. Extra sections (social edges, DM threads you
are in, club memberships) come from ``extras`` callables registered by webapp.py. Rate limited
(``EXPORT_LIMIT`` per ``EXPORT_WINDOW`` seconds, per user).

Delete
------
``AccountDeleter`` runs every registered hook (each in its own try: one failure never stops
the rest; failures are reported by name), then removes the user's whole folder
(``AppStore.delete_user``) and finally their sign-in sessions. Hooks are registered by the
service blocks in webapp.py that own the global indexes: disconnect Garmin / Oura / Google
Calendar (revokes the Google token) / TrainingPeaks, social edges and invite code, leave DMs
(messages stay for the others, without your name or photo since your profile is gone), leave
clubs (ownership passes on), buddy profile, share links, calendar feed, public events, coach
links, usage and trend counters, invite membership and passkeys, push subscriptions.
"""

from __future__ import annotations

import inspect
import io
import json
import re
import time
import zipfile
from collections.abc import Callable
from typing import Any

from . import legal
from .appstore import AppStore

EXPORT_LIMIT = 3
EXPORT_WINDOW = 3600.0
REMOVED = "[removed]"
# Docs whose whole content is a credential (push subscriptions).
DROP_DOCS = frozenset({"push", "applehealth"})  # applehealth: import key hash
_SECRET = re.compile(r"(token|secret|cookie|password|passwd|refresh|access|p256dh|^auth$|endpoint|hash|"
                     r"credential|private_?key|verifier|nonce|api_?key)", re.I)

Hook = Callable[[str], Any]  # sync or async; returns anything


def redact(value: Any) -> Any:
    """Replace credential-looking keys at any depth."""
    if isinstance(value, dict):
        return {k: (REMOVED if isinstance(k, str) and _SECRET.search(k) and isinstance(v, (str, dict, list)) and v
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


README = """Your rabbt data
================

Exported {when} (UTC) for account {uid}.

docs/<name>.json   everything rabbt stores for your account, one file per kind of data
                   (profile, plan, events, goals, chats, workouts feedback, posts and more).
extra/<name>.json  your part of shared data: who you follow, clubs, conversations you're in.

Sign-in tokens, cookies and keys for connected apps are not included ({removed}).
Garmin, Oura, Google Calendar and TrainingPeaks keep their own copy of their data: export it
from those apps. Questions: {contact}.

Privacy policy version {version}: /app/privacy
"""


class RateLimited(Exception):
    pass


class AccountData:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock
        self._exports: dict[str, list[float]] = {}
        self.extras: dict[str, Callable[[str], Any]] = {}
        self.hooks: list[tuple[str, Hook]] = []

    # ------------------------------------------------------------------ export --
    def add_extra(self, name: str, fn: Callable[[str], Any]) -> None:
        self.extras[name] = fn

    def export_allowed(self, uid: str) -> bool:
        now = self._clock()
        recent = [t for t in self._exports.get(uid, []) if now - t < EXPORT_WINDOW]
        self._exports[uid] = recent
        return len(recent) < EXPORT_LIMIT

    def collect(self, uid: str) -> dict[str, Any]:
        docs: dict[str, Any] = {}
        for name in self._s.user_doc_names(uid):
            if name in DROP_DOCS:
                continue
            try:
                docs[name] = redact(self._s.user_doc(uid, name).load())
            except Exception:
                docs[name] = {"error": "could not be read"}
        extra: dict[str, Any] = {}
        for name, fn in self.extras.items():
            try:
                extra[name] = redact(fn(uid))
            except Exception:
                extra[name] = {"error": "could not be read"}
        return {"docs": docs, "extra": extra}

    def export_zip(self, uid: str, contact: str = "") -> bytes:
        if not self.export_allowed(uid):
            raise RateLimited()
        self._exports.setdefault(uid, []).append(self._clock())
        data = self.collect(uid)
        buf = io.BytesIO()
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(self._clock()))
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", README.format(when=when, uid=uid, removed=REMOVED,
                                                   contact=legal.contact_email(contact), version=legal.VERSION))
            for section in ("docs", "extra"):
                for name, val in sorted(data[section].items()):
                    z.writestr(f"{section}/{name}.json", json.dumps(val, indent=2, ensure_ascii=False, default=str))
        return buf.getvalue()

    # ------------------------------------------------------------------ delete --
    def on_delete(self, name: str, fn: Hook) -> None:
        self.hooks.append((name, fn))

    async def delete(self, uid: str, *, final: Callable[[str], Any] | None = None) -> dict[str, Any]:
        """Run every hook, remove the user's folder, then ``final`` (sessions). Returns
        ``{"files": n, "failed": [hook names]}``."""
        failed: list[str] = []
        for name, fn in list(self.hooks):
            try:
                r = fn(uid)
                if inspect.isawaitable(r):
                    await r
            except Exception:
                failed.append(name)
        files = self._s.delete_user(uid)
        if final is not None:
            try:
                r = final(uid)
                if inspect.isawaitable(r):
                    await r
            except Exception:
                failed.append("sessions")
        self._exports.pop(uid, None)
        return {"files": files, "failed": failed}


__all__ = ["AccountData", "RateLimited", "redact", "REMOVED", "EXPORT_LIMIT"]
