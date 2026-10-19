"""Feed groups: small private circles for the Community feed ("Saturday long run crew").

* An athlete creates a group (name <= ``NAME_LEN``, an emoji) and adds people from their
  **mutual friends** (both follow edges active, no block). Any member can add more of their own
  mutual friends ("invite more"); people are in right away and can leave any time.
* Caps: ``MAX_MEMBERS`` per group (owner included), ``MAX_GROUPS`` groups per athlete
  (memberships, owned or not).
* The owner renames it (name/emoji), removes members or deletes it. An owner who leaves hands
  it to the longest-standing member; the last one out deletes it.
* Posts to a group (``community.py`` audience ``grp:<gid>[,<gid>...]``) are seen only by people
  in one of those groups, and only while the author is still in it. Blocks (either way) hide
  people from each other's member lists and posts.

Athletes only (allowlisted, never ``coach_``: 403). Storage: global ``feedgroups`` doc
``{"groups": {gid: {id, name, emoji, owner, members: [uid, ...], created}}}`` (members in
join order).
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore

NAME_LEN = 40
EMOJI_LEN = 8
MAX_MEMBERS = 50
MAX_GROUPS = 10
_GID = re.compile(r"^f[0-9a-f]{12}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class GroupError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def valid_gid(gid: Any) -> str:
    if not isinstance(gid, str) or not _GID.match(gid):
        raise GroupError("group not found", 404)
    return gid


def _name(v: Any) -> str:
    if not isinstance(v, str):
        raise GroupError("Give the group a name.")
    s = " ".join(_CTRL.sub(" ", v).split())
    if not s:
        raise GroupError("Give the group a name.")
    if len(s) > NAME_LEN:
        raise GroupError(f"Keep the name under {NAME_LEN} characters.")
    return s


def _emoji(v: Any) -> str:
    if v in (None, ""):
        return "👟"
    if not isinstance(v, str):
        raise GroupError("Pick an emoji.")
    s = v.strip()
    if not s or len(s) > EMOJI_LEN or any(ch.isalnum() or ch.isspace() for ch in s):
        raise GroupError("Pick an emoji.")
    return s


class FeedGroups:
    def __init__(self, store: AppStore, *, is_athlete: Callable[[str], bool], follows: Callable[[str, str], bool],
                 blocked: Callable[[str, str], bool], clock: Callable[[], float] = time.time) -> None:
        self._doc = store.global_doc("feedgroups")
        self._is_athlete = is_athlete
        self._follows = follows
        self._blocked = blocked
        self._clock = clock
        self._lock = threading.Lock()

    def _update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            return self._doc.update(fn)

    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            raise GroupError("Groups are for athletes on rabbt.", 403)

    def mutual(self, a: str, b: str) -> bool:
        return (a != b and self._is_athlete(a) and self._is_athlete(b) and not self._blocked(a, b)
                and self._follows(a, b) and self._follows(b, a))

    # ------------------------------------------------------------ reads --
    def _all(self) -> dict[str, dict[str, Any]]:
        return self._doc.load().get("groups") or {}

    @staticmethod
    def _count(groups: dict[str, dict[str, Any]], uid: str) -> int:
        return sum(1 for g in groups.values() if uid in g["members"])

    def is_member(self, gid: str, uid: str) -> bool:
        g = self._all().get(gid) if isinstance(gid, str) else None
        return g is not None and uid in g["members"] and self._is_athlete(uid)

    def ids_of(self, uid: str) -> list[str]:
        return [gid for gid, g in self._all().items() if uid in g["members"]]

    def member_ids(self, gid: str, viewer: str) -> list[str]:
        """Members of a group ``viewer`` is in (else [])."""
        g = self._all().get(gid)
        if not g or viewer not in g["members"]:
            return []
        return [m for m in g["members"] if self._is_athlete(m)]

    def brief(self, gid: str, viewer: str) -> dict[str, Any] | None:
        g = self._all().get(gid)
        if not g or viewer not in g["members"]:
            return None
        return {"id": g["id"], "name": g["name"], "emoji": g.get("emoji") or "👟"}

    def _view(self, g: dict[str, Any], viewer: str) -> dict[str, Any]:
        people = [m for m in g["members"] if self._is_athlete(m) and (m == viewer or not self._blocked(viewer, m))]
        return {"id": g["id"], "name": g["name"], "emoji": g.get("emoji") or "👟", "owner": g["owner"] == viewer,
                "owner_id": g["owner"], "members": people, "count": len(people), "max": MAX_MEMBERS}

    def mine(self, uid: str) -> list[dict[str, Any]]:
        self.require(uid)
        out = [self._view(g, uid) for g in self._all().values() if uid in g["members"]]
        out.sort(key=lambda g: g["name"].lower())
        return out

    def get(self, uid: str, gid: Any) -> dict[str, Any]:
        self.require(uid)
        g = self._all().get(valid_gid(gid))
        if g is None or uid not in g["members"]:
            raise GroupError("group not found", 404)
        return self._view(g, uid)

    # ----------------------------------------------------------- writes --
    def _check_new(self, groups: dict[str, dict[str, Any]], adder: str, people: Any,
                   g: dict[str, Any] | None) -> list[str]:
        if people is None:
            people = []
        if not isinstance(people, list) or not all(isinstance(p, str) for p in people):
            raise GroupError("Pick friends to add.")
        current = set(g["members"]) if g else {adder}
        new = [p for p in dict.fromkeys(people) if p not in current]
        for p in new:
            if not self.mutual(adder, p):
                raise GroupError("You can add friends who follow you back.", 404)
            if self._count(groups, p) >= MAX_GROUPS:
                raise GroupError(f"One of them is in {MAX_GROUPS} groups already.", 409)
        if len(current) + len(new) > MAX_MEMBERS:
            raise GroupError(f"A group can have up to {MAX_MEMBERS} people.", 409)
        return new

    def create(self, uid: str, body: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(body, dict):
            raise GroupError("bad request")
        name, emoji = _name(body.get("name")), _emoji(body.get("emoji"))

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            groups = d.setdefault("groups", {})
            if self._count(groups, uid) >= MAX_GROUPS:
                raise GroupError(f"You can be in up to {MAX_GROUPS} groups. Leave one to start another.", 409)
            new = self._check_new(groups, uid, body.get("members"), None)
            gid = "f" + secrets.token_hex(6)
            g = {"id": gid, "name": name, "emoji": emoji, "owner": uid, "members": [uid, *new],
                 "created": int(self._clock())}
            groups[gid] = g
            return self._view(g, uid)
        return self._update(apply)

    def add(self, uid: str, gid: Any, people: Any) -> tuple[dict[str, Any], list[str]]:
        """Any member adds their own mutual friends. Returns (group, newly added)."""
        self.require(uid)
        gid = valid_gid(gid)

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
            groups = d.setdefault("groups", {})
            g = groups.get(gid)
            if g is None or uid not in g["members"]:
                raise GroupError("group not found", 404)
            new = self._check_new(groups, uid, people, g)
            g["members"].extend(new)
            return self._view(g, uid), new
        return self._update(apply)

    def update(self, uid: str, gid: Any, body: Any) -> dict[str, Any]:
        """Owner: rename / new emoji."""
        self.require(uid)
        gid = valid_gid(gid)
        if not isinstance(body, dict):
            raise GroupError("bad request")
        patch: dict[str, Any] = {}
        if "name" in body:
            patch["name"] = _name(body["name"])
        if "emoji" in body:
            patch["emoji"] = _emoji(body["emoji"])

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            g = (d.get("groups") or {}).get(gid)
            if g is None or uid not in g["members"]:
                raise GroupError("group not found", 404)
            if g["owner"] != uid:
                raise GroupError("Only the group's owner can change it.", 403)
            g.update(patch)
            return self._view(g, uid)
        return self._update(apply)

    def remove(self, uid: str, gid: Any, member: Any) -> dict[str, Any]:
        """Owner removes someone."""
        self.require(uid)
        gid = valid_gid(gid)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            g = (d.get("groups") or {}).get(gid)
            if g is None or uid not in g["members"]:
                raise GroupError("group not found", 404)
            if g["owner"] != uid:
                raise GroupError("Only the group's owner can remove people.", 403)
            if not isinstance(member, str) or member == uid or member not in g["members"]:
                raise GroupError("member not found", 404)
            g["members"].remove(member)
            return self._view(g, uid)
        return self._update(apply)

    def leave(self, uid: str, gid: Any) -> None:
        self.require(uid)
        gid = valid_gid(gid)

        def apply(d: dict[str, Any]) -> None:
            groups = d.get("groups") or {}
            g = groups.get(gid)
            if g is None or uid not in g["members"]:
                raise GroupError("group not found", 404)
            g["members"].remove(uid)
            live = [m for m in g["members"] if self._is_athlete(m)]
            if not live:
                del groups[gid]
                return
            if g["owner"] == uid:
                g["owner"] = live[0]
        self._update(apply)

    def delete(self, uid: str, gid: Any) -> None:
        self.require(uid)
        gid = valid_gid(gid)

        def apply(d: dict[str, Any]) -> None:
            groups = d.get("groups") or {}
            g = groups.get(gid)
            if g is None or uid not in g["members"]:
                raise GroupError("group not found", 404)
            if g["owner"] != uid:
                raise GroupError("Only the group's owner can delete it.", 403)
            del groups[gid]
        self._update(apply)


__all__ = ["MAX_GROUPS", "MAX_MEMBERS", "FeedGroups", "GroupError", "valid_gid"]
