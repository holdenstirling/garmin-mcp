"""Find friends: @handles, people search, contact matching, "People you may know".

* **Handles** (``handle_of``/``set_handle``): every athlete gets a unique @handle, made from
  their name the first time it's needed ("jesse", then "jesse2"...), editable in Me.
  3-20 chars, lower-case letters, digits, ``_`` and ``.``. Used by search and @mentions.
* **Who can find me** (``prefs``): by name/@handle, by email (the address they sign in
  with), by phone (only once they add one; it's optional and not verified). All on by
  default; a person who turned one off never shows up through that route, and blocked
  people never show up at all.
* **Search** (``search``): an email or phone matches exactly; anything else matches
  @handle and name prefixes. Athletes only (never coach accounts), never yourself.
* **Contact matching** (``match``): the app sends the emails and phone numbers the person
  picked from their contacts. They are normalized, compared against an HMAC index (a random
  per-server key; phone numbers are only kept as HMACs in the index) and thrown away: nothing
  uploaded is stored or logged. 500 values per request, 10 requests an hour per person.
* **People you may know** (``suggestions``): follows you, friends of friends (with the
  mutual count), your clubs, the same upcoming race, training-buddy matches, and the same
  city. Dismissable. Never people you follow or asked to follow, blocked either way, or coaches.

Storage: global ``directory`` doc ``{"users": {uid: {handle, phone, find, dismissed}},
"handles": {handle: uid}, "phones": {hmac: uid}, "key": hex}``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

HANDLE_RE = re.compile(r"^[a-z0-9_.]{3,20}$")
RESERVED = {"rabbit", "admin", "support", "help", "coach", "team", "everyone", "here", "all", "me",
            "you", "null", "undefined", "settings", "privacy", "app", "api", "root", "staff"}
DEFAULT_FIND = {"name": True, "email": True, "phone": True}
MATCH_MAX = 500
MATCH_PER_HOUR = 10
SEARCH_MAX = 20
SUGGEST_MAX = 30
DISMISS_MAX = 300
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


class FindError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def norm_email(v: Any) -> str | None:
    s = str(v or "").strip().lower()
    if s.startswith("mailto:"):
        s = s[7:]
    return s if _EMAIL.match(s) else None


def norm_phone(v: Any, default_cc: str = "1") -> str | None:
    """E.164 (``+13035551234``). US/Canada numbers without a country code get +1; anything
    shorter than 8 digits or longer than 15 isn't a phone number."""
    raw = str(v or "").strip()
    if not raw:
        return None
    plus = raw.startswith("+") or raw.startswith("00")
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]
    if not plus:
        if len(digits) == 10:
            digits = default_cc + digits
        elif len(digits) == 11 and digits.startswith(default_cc):
            pass
        else:
            return None
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def handle_base(name: str) -> str:
    """"Jesse O'Neil" -> "jesse"; accents dropped; at least 3 chars ("al" -> "al_")."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    first = (s.split() or ["runner"])[0]
    base = re.sub(r"[^a-z0-9]", "", first)[:16] or "runner"
    return base if len(base) >= 3 else (base + "_runner")[:16] if base else "runner"


class FriendFinder:
    def __init__(self, store: Any, *, soc: Any, emails: Callable[[], dict[str, str]],
                 name: Callable[[str], str],
                 base_suggestions: Callable[[str], list[dict[str, Any]]] | None = None,
                 races: Callable[[str], Iterable[str]] | None = None,
                 metro: Callable[[str], str] | None = None,
                 buddies: Callable[[str], Iterable[str]] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        """``emails``: lower-case email -> athlete id. ``name``: full display name.
        ``base_suggestions``: rows ``{"user_id", "reason"}`` (follows you, your clubs).
        ``races``: keys of a person's upcoming races (normalized name + date).
        ``metro``: "city, ST" or "". ``buddies``: training-buddy matches."""
        self._doc = store.global_doc("directory")
        self.soc = soc
        self._emails = emails
        self._name = name
        self._base = base_suggestions or (lambda u: [])
        self._races = races or (lambda u: [])
        self._metro = metro or (lambda u: "")
        self._buddies = buddies or (lambda u: [])
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    # ------------------------------------------------------------ storage --
    def _update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            return self._doc.update(fn)

    @staticmethod
    def _key(d: dict[str, Any]) -> bytes:
        if not d.get("key"):
            d["key"] = secrets.token_hex(32)
        return bytes.fromhex(d["key"])

    def _mac(self, key: bytes, value: str) -> str:
        return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()

    def _athletes(self) -> list[str]:
        return sorted({u for u in self._emails().values() if self.soc.is_athlete(u)})

    @staticmethod
    def _u(d: dict[str, Any], uid: str) -> dict[str, Any]:
        return d.setdefault("users", {}).setdefault(uid, {})

    def _assign(self, d: dict[str, Any], uid: str) -> str:
        u = self._u(d, uid)
        h = u.get("handle")
        handles = d.setdefault("handles", {})
        if h and handles.get(h) == uid:
            return str(h)
        base = handle_base(self._name(uid))
        cand, n = base, 1
        while cand in handles or cand in RESERVED:
            n += 1
            cand = f"{base}{n}"
        handles[cand] = uid
        u["handle"] = cand
        return cand

    # ------------------------------------------------------------ handles --
    def handle_of(self, uid: str) -> str:
        d = self._doc.load()
        h = ((d.get("users") or {}).get(uid) or {}).get("handle")
        if h and (d.get("handles") or {}).get(h) == uid:
            return str(h)
        return str(self._update(lambda d: self._assign(d, uid)))

    def handles(self, uids: Iterable[str]) -> dict[str, str]:
        """Many at once (assigns any missing in one write)."""
        want = [u for u in dict.fromkeys(uids) if u]
        d = self._doc.load()
        users = d.get("users") or {}
        missing = [u for u in want if not (users.get(u) or {}).get("handle")]
        if missing:
            def apply(d: dict[str, Any]) -> None:
                for u in missing:
                    self._assign(d, u)
            self._update(apply)
            users = self._doc.load().get("users") or {}
        return {u: str((users.get(u) or {}).get("handle") or "") for u in want}

    def uid_for_handle(self, handle: str) -> str | None:
        h = str(handle or "").strip().lstrip("@").lower()
        return (self._doc.load().get("handles") or {}).get(h)

    def set_handle(self, uid: str, raw: Any) -> str:
        h = str(raw or "").strip().lstrip("@").lower()
        if not HANDLE_RE.match(h):
            raise FindError("Use 3-20 letters, numbers, _ or . for your @handle.")
        if h in RESERVED:
            raise FindError("That @handle is reserved. Try another.")

        def apply(d: dict[str, Any]) -> str:
            handles = d.setdefault("handles", {})
            owner = handles.get(h)
            if owner and owner != uid:
                raise FindError("That @handle is taken. Try another.", 409)
            u = self._u(d, uid)
            old = u.get("handle")
            if old and handles.get(old) == uid:
                del handles[old]
            handles[h] = uid
            u["handle"] = h
            return h
        return str(self._update(apply))

    # -------------------------------------------------------------- prefs --
    def prefs(self, uid: str) -> dict[str, Any]:
        d = self._doc.load()
        u = (d.get("users") or {}).get(uid) or {}
        find = {k: bool((u.get("find") or {}).get(k, v)) for k, v in DEFAULT_FIND.items()}
        return {"handle": self.handle_of(uid), "phone": u.get("phone") or None, "find": find}

    def put_prefs(self, uid: str, patch: Any) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise FindError("Send an object.")
        if "handle" in patch and patch["handle"] is not None:
            self.set_handle(uid, patch["handle"])
        find_patch: dict[str, bool] = {}
        for k, v in (patch.get("find") or {}).items() if isinstance(patch.get("find"), dict) else []:
            if k in DEFAULT_FIND:
                if not isinstance(v, bool):
                    raise FindError(f"find.{k} must be true or false")
                find_patch[k] = v
        phone_set = "phone" in patch
        phone = None
        if phone_set and patch["phone"] not in (None, ""):
            phone = norm_phone(patch["phone"])
            if phone is None:
                raise FindError("That doesn't look like a phone number. Include the area code.")

        def apply(d: dict[str, Any]) -> None:
            key = self._key(d)
            u = self._u(d, uid)
            if find_patch:
                u["find"] = {**DEFAULT_FIND, **(u.get("find") or {}), **find_patch}
            if phone_set:
                phones = d.setdefault("phones", {})
                old = u.get("phone")
                if old:
                    m = self._mac(key, old)
                    if phones.get(m) == uid:
                        del phones[m]
                if phone:
                    m = self._mac(key, phone)
                    owner = phones.get(m)
                    if owner and owner != uid:
                        raise FindError("That number is already on another Rabbit account.", 409)
                    phones[m] = uid
                    u["phone"] = phone
                else:
                    u.pop("phone", None)
        self._update(apply)
        return self.prefs(uid)

    def _find(self, d: dict[str, Any], uid: str, how: str) -> bool:
        u = (d.get("users") or {}).get(uid) or {}
        return bool((u.get("find") or {}).get(how, DEFAULT_FIND[how]))

    # ----------------------------------------------------- visibility rule --
    def _ok(self, viewer: str, uid: str) -> bool:
        return uid != viewer and self.soc.is_athlete(uid) and not self.soc.blocked_between(viewer, uid)

    def can_follow(self, viewer: str, uid: str) -> bool:
        """Someone Find friends could have shown: findable some way, already connected
        either way, or in People you may know. (A request still needs their OK.)"""
        if not self._ok(viewer, uid):
            return False
        d = self._doc.load()
        if any(self._find(d, uid, how) for how in DEFAULT_FIND):
            return True
        if self.soc.follows(uid, viewer) or self.soc.follows(viewer, uid):
            return True
        return any(r["user_id"] == uid for r in self.suggestions(viewer, limit=500))

    def status(self, viewer: str, uid: str) -> str:
        if self.soc.follows(viewer, uid):
            return "following"
        if uid in self.soc.pending_ids(viewer):
            return "requested"
        return "none"

    def _row(self, viewer: str, uid: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"user_id": uid, "reason": reason, "status": self.status(viewer, uid),
                "follows_you": self.soc.follows(uid, viewer), **extra}

    # ------------------------------------------------------------- search --
    def search(self, viewer: str, q: Any) -> list[dict[str, Any]]:
        self.soc.require(viewer)
        text = " ".join(str(q or "").split())[:80]
        if len(text) < 2:
            return []
        d = self._doc.load()
        email = norm_email(text)
        if email:
            uid = {k.lower(): v for k, v in self._emails().items()}.get(email)
            if uid and self._ok(viewer, uid) and self._find(d, uid, "email"):
                return [self._row(viewer, uid, "Email match")]
            return []
        if re.fullmatch(r"[+()\d\s.-]{7,}", text):
            phone = norm_phone(text)
            if phone and d.get("key"):
                uid = (d.get("phones") or {}).get(self._mac(bytes.fromhex(d["key"]), phone))
                if uid and self._ok(viewer, uid) and self._find(d, uid, "phone"):
                    return [self._row(viewer, uid, "Phone match")]
            return []
        words = [w for w in unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode().split() if w]
        at = text.startswith("@")
        handles = self.handles(self._athletes())
        scored: list[tuple[int, str, str]] = []
        for uid in self._athletes():
            if not self._ok(viewer, uid):
                continue
            related = self.soc.follows(viewer, uid) or self.soc.follows(uid, viewer)
            if not related and not self._find(d, uid, "name"):
                continue
            h = handles.get(uid, "")
            name = unicodedata.normalize("NFKD", self._name(uid).lower()).encode("ascii", "ignore").decode()
            parts = name.split()
            hq = words[0].lstrip("@") if words else ""
            score = 0
            if hq and h == hq:
                score = 100
            elif hq and h.startswith(hq):
                score = 70
            elif not at and words and all(any(p.startswith(w) for p in parts) for w in words):
                score = 60 if parts and parts[0].startswith(words[0]) else 50
            if not score:
                continue
            score += 20 if related else 0
            scored.append((-score, name, uid))
        scored.sort()
        return [self._row(viewer, uid, "") for _, _, uid in scored[:SEARCH_MAX]]

    # ---------------------------------------------------- contact matching --
    def _rate(self, viewer: str) -> None:
        now = self._clock()
        with self._lock:
            hits = [t for t in self._hits.get(viewer, []) if now - t < 3600]
            if len(hits) >= MATCH_PER_HOUR:
                raise FindError("That's a lot of contact checks. Try again in an hour.", 429)
            hits.append(now)
            self._hits[viewer] = hits

    def match(self, viewer: str, contacts: Any) -> dict[str, Any]:
        """``contacts``: ``[{"emails": [...], "phones": [...]}, ...]`` in the order the app
        shows them. Returns which entries are on Rabbit (``index``, ``user_id``); nothing
        sent is stored."""
        self.soc.require(viewer)
        if not isinstance(contacts, list):
            raise FindError("Send a list of contacts.")
        total = sum(len(c.get("emails") or []) + len(c.get("phones") or [])
                    for c in contacts if isinstance(c, dict))
        if total > MATCH_MAX or len(contacts) > MATCH_MAX:
            raise FindError(f"Up to {MATCH_MAX} emails and numbers at a time.", 413)
        self._rate(viewer)
        d = self._doc.load()
        key = bytes.fromhex(d["key"]) if d.get("key") else None
        phones = d.get("phones") or {}
        emails = {k.lower(): v for k, v in self._emails().items()}
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, c in enumerate(contacts):
            if not isinstance(c, dict):
                continue
            uid = None
            for e in (c.get("emails") or [])[:10]:
                n = norm_email(e)
                cand = emails.get(n) if n else None
                if cand and self._find(d, cand, "email"):
                    uid = cand
                    break
            if uid is None and key is not None:
                for p in (c.get("phones") or [])[:10]:
                    n = norm_phone(p)
                    cand = phones.get(self._mac(key, n)) if n else None
                    if cand and self._find(d, cand, "phone"):
                        uid = cand
                        break
            if uid and uid not in seen and self._ok(viewer, uid):
                seen.add(uid)
                found.append({"index": i, **self._row(viewer, uid, "In your contacts")})
        return {"on_rabbit": found, "checked": len(contacts)}

    # -------------------------------------------------------- suggestions --
    def dismiss(self, viewer: str, uid: Any) -> None:
        if not isinstance(uid, str) or not uid:
            raise FindError("person not found", 404)

        def apply(d: dict[str, Any]) -> None:
            u = self._u(d, viewer)
            u["dismissed"] = ([x for x in u.get("dismissed") or [] if x != uid] + [uid])[-DISMISS_MAX:]
        self._update(apply)

    def suggestions(self, viewer: str, limit: int = SUGGEST_MAX) -> list[dict[str, Any]]:
        self.soc.require(viewer)
        d = self._doc.load()
        dismissed = set(((d.get("users") or {}).get(viewer) or {}).get("dismissed") or [])
        following = set(self.soc.following_ids(viewer, limit=500))
        skip = {viewer, *following, *self.soc.pending_ids(viewer), *dismissed}
        score: dict[str, float] = {}
        why: dict[str, tuple[float, str]] = {}

        def add(uid: str, pts: float, reason: str) -> None:
            if uid in skip or not uid:
                return
            score[uid] = score.get(uid, 0) + pts
            if pts > why.get(uid, (0, ""))[0]:
                why[uid] = (pts, reason)
        for r in self._base(viewer):
            r_why = str(r.get("reason") or "")
            add(str(r.get("user_id") or ""), 100 if r_why == "Follows you" else 30, r_why)
        mutual: dict[str, int] = {}
        for f in following:
            for ff in self.soc.following_ids(f, limit=200):
                mutual[ff] = mutual.get(ff, 0) + 1
        for uid, n in mutual.items():
            add(uid, 10 * n + 5, f"{n} mutual friend{'s' if n != 1 else ''}")
        mine = set(self._races(viewer))
        metro = (self._metro(viewer) or "").strip().lower()
        if mine or metro:
            for uid in self._athletes():
                if uid in skip:
                    continue
                if mine and mine & set(self._races(uid)):
                    add(uid, 25, "Same race as you")
                if metro and (self._metro(uid) or "").strip().lower() == metro:
                    add(uid, 5, f"Also in {self._metro(viewer).split(',')[0]}")
        for uid in self._buddies(viewer):
            add(uid, 20, "Trains like you")
        rows = [(-s, uid) for uid, s in score.items() if self._ok(viewer, uid)]
        rows.sort()
        out = []
        for _, uid in rows[:limit]:
            extra = {"mutual": mutual.get(uid, 0)}
            out.append(self._row(viewer, uid, why[uid][1], **extra))
        return out

    # ---------------------------------------------------- account lifecycle --
    def forget_user(self, uid: str) -> None:
        def apply(d: dict[str, Any]) -> None:
            u = (d.get("users") or {}).pop(uid, None) or {}
            h = u.get("handle")
            if h and (d.get("handles") or {}).get(h) == uid:
                del d["handles"][h]
            d["phones"] = {k: v for k, v in (d.get("phones") or {}).items() if v != uid}
            for other in (d.get("users") or {}).values():
                if uid in (other.get("dismissed") or []):
                    other["dismissed"] = [x for x in other["dismissed"] if x != uid]
        self._update(apply)

    def export_user(self, uid: str) -> dict[str, Any]:
        u = ((self._doc.load().get("users") or {}).get(uid) or {})
        return {"handle": u.get("handle"), "phone": u.get("phone"),
                "find": {**DEFAULT_FIND, **(u.get("find") or {})}}


__all__ = ["FriendFinder", "FindError", "norm_email", "norm_phone", "handle_base", "MATCH_MAX"]
