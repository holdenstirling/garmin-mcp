"""Following friends: athletes follow each other's training, cheer workouts, give kudos.

Rules
-----
* Only real athletes (allowlisted users, never ``coach_`` accounts) can follow or be
  followed. Following is one-way; it doesn't have to be mutual.
* A request is made by another athlete's email or by their personal invite code (8 chars,
  regenerable). It waits for the target to accept unless the target turned on
  ``auto_accept`` and already follows the requester.
* No enumeration: a request by email gets the same answer whether or not the email has a
  Rabbit account. Unknown emails are kept as a "ghost" request (shown to the requester as
  pending, by the email they typed) and turn into a real request if that person is later
  allowlisted. A request to someone who blocked you is stored hidden and never surfaces.
* Followers see only what the followee shares (``settings``): workouts, distance, times,
  streak & level, races (off by default). Never heart rate, health/Oura data or locations.

Storage
-------
* Global ``social`` doc: ``{"edges": {id: {id, follower, followee|None, email|None,
  status: "pending"|"active", ts, hidden?}}, "users": {uid: {settings, code, blocked,
  ever_followed}}, "codes": {code: uid}}``.
* Per owner ``kudos`` doc: ``{"acts": {activity_id: {"by": {uid: ts}, "cheers": [...],
  "ts": last}}}`` (capped), per user ``social_seen`` for the home badge.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .appstore import AppStore
from .progress import workout_xp
from .stats import _rows

GENERIC_SENT = "If they're on rabbt, they'll get your request."
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
MAX_OUTGOING = 200
MAX_NEW_PER_DAY = 30
GHOST_TTL = 30 * 86400
FEED_DAYS = 14
FEED_FOLLOWEES = 30
FEED_CACHE_S = 600
FEED_MAX_ITEMS = 60
MAX_KUDOS_ACTS = 300
MAX_KUDOS_PER_ACT = 200
MAX_CHEERS = 50
CHEER_LEN = 140
KUDOS_XP = 5
KUDOS_XP_PER_DAY = 10  # kudos that earn XP per day (50 XP)
KUDOS_XP_DAYS = 14
DEFAULT_SETTINGS: dict[str, bool] = {
    "workouts": True, "distance": True, "times": True, "streak": True, "races": False,
    "auto_accept": False,
}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_AID = re.compile(r"^[0-9]{1,20}$")


class SocialError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def valid_activity_id(aid: Any) -> str:
    if not isinstance(aid, str) or not _AID.match(aid):
        raise SocialError("workout not found", 404)
    return aid


class Social:
    def __init__(self, store: AppStore, *, athletes: Callable[[], dict[str, str]],
                 clock: Callable[[], float] = time.time) -> None:
        """``athletes``: the allowlist, lower-case email -> athlete user id."""
        self._s = store
        self._doc = store.global_doc("social")
        self._allow = athletes
        self._clock = clock
        self._lock = threading.Lock()

    # ------------------------------------------------------------ identity --
    def _athlete_ids(self) -> set[str]:
        return {v for v in self._allow().values() if not v.startswith("coach_")}

    def is_athlete(self, uid: str) -> bool:
        return not uid.startswith("coach_") and uid in self._athlete_ids()

    def require(self, uid: str) -> None:
        if not self.is_athlete(uid):
            raise SocialError("Friends are for athletes on rabbt.", 403)

    def _new_code(self, d: dict[str, Any]) -> str:
        codes = d.setdefault("codes", {})
        while True:
            c = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            if c not in codes:
                return c

    def _user(self, d: dict[str, Any], uid: str) -> dict[str, Any]:
        u = d.setdefault("users", {}).setdefault(uid, {})
        if not u.get("code"):
            u["code"] = self._new_code(d)
            d["codes"][u["code"]] = uid
        u.setdefault("blocked", [])
        return u

    def _update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            return self._doc.update(fn)

    # ---------------------------------------------------- account export / delete --
    def export_user(self, uid: str) -> dict[str, Any]:
        d = self._doc.load()
        edges = [{k: e.get(k) for k in ("follower", "followee", "email", "status", "ts")}
                 for e in (d.get("edges") or {}).values()
                 if uid in (e.get("follower"), e.get("followee"))]
        u = (d.get("users") or {}).get(uid) or {}
        return {"settings": u.get("settings") or {}, "blocked": u.get("blocked") or [], "follows": edges}

    def forget_user(self, uid: str) -> None:
        """Account deletion: drop follow edges either way, settings, blocks and invite code."""
        def apply(d: dict[str, Any]) -> None:
            edges = d.get("edges") or {}
            for k in [k for k, e in edges.items() if uid in (e.get("follower"), e.get("followee"))]:
                del edges[k]
            (d.get("users") or {}).pop(uid, None)
            codes = d.get("codes") or {}
            for c in [c for c, v in codes.items() if v == uid]:
                del codes[c]
            for u in (d.get("users") or {}).values():
                if uid in (u.get("blocked") or []):
                    u["blocked"] = [b for b in u["blocked"] if b != uid]
        self._update(apply)

    # ------------------------------------------------------------ settings --
    @staticmethod
    def _settings_of(d: dict[str, Any], uid: str) -> dict[str, bool]:
        stored = ((d.get("users") or {}).get(uid) or {}).get("settings") or {}
        return {k: bool(stored.get(k, v)) for k, v in DEFAULT_SETTINGS.items()}

    def settings(self, uid: str) -> dict[str, bool]:
        return self._settings_of(self._doc.load(), uid)

    def settings_many(self, uids: list[str]) -> dict[str, dict[str, bool]]:
        """``settings`` for several people from one read (Feed paths that loop over followees)."""
        d = self._doc.load()
        return {u: self._settings_of(d, u) for u in dict.fromkeys(uids)}

    def explicit_workouts(self, uid: str) -> bool | None:
        """The "workouts" share as the person saved it in these settings (None = never saved,
        only the default). A saved yes counts as their earlier consent to share workouts."""
        stored = ((self._doc.load().get("users") or {}).get(uid) or {}).get("settings") or {}
        v = stored.get("workouts")
        return v if isinstance(v, bool) else None

    def put_settings(self, uid: str, patch: Any) -> dict[str, bool]:
        if not isinstance(patch, dict):
            raise SocialError("settings must be an object")
        clean: dict[str, bool] = {}
        for k, v in patch.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if not isinstance(v, bool):
                raise SocialError(f"{k} must be true or false")
            clean[k] = v

        def apply(d: dict[str, Any]) -> dict[str, bool]:
            u = self._user(d, uid)
            u["settings"] = {**self._settings_of(d, uid), **clean}
            return dict(u["settings"])
        return self._update(apply)

    def invite_code(self, uid: str) -> str:
        u = ((self._doc.load().get("users") or {}).get(uid) or {})
        if u.get("code"):
            return str(u["code"])
        return self._update(lambda d: self._user(d, uid)["code"])

    def code_owner(self, code: str) -> str | None:
        """An invite code -> its athlete's user id (race invites by code)."""
        return (self._doc.load().get("codes") or {}).get(code)

    def regenerate_code(self, uid: str) -> str:
        def apply(d: dict[str, Any]) -> str:
            u = self._user(d, uid)
            d["codes"].pop(u["code"], None)
            u["code"] = self._new_code(d)
            d["codes"][u["code"]] = uid
            return str(u["code"])
        return self._update(apply)

    # --------------------------------------------------------------- edges --
    def _materialize(self, d: dict[str, Any]) -> None:
        """Ghost requests whose email is now an athlete become real; old ghosts expire."""
        allow = {k.lower(): v for k, v in self._allow().items()}
        now = self._clock()
        edges = d.setdefault("edges", {})
        for eid, e in list(edges.items()):
            if e.get("followee") is not None:
                continue
            target = allow.get(e.get("email") or "")
            if target and not target.startswith("coach_") and target != e["follower"]:
                e["followee"] = target
                blocked = ((d.get("users") or {}).get(target) or {}).get("blocked") or []
                if e["follower"] in blocked:
                    e["hidden"] = True
                if any(x is not e and x.get("follower") == e["follower"] and x.get("followee") == target
                       for x in edges.values()):
                    del edges[eid]
            elif now - e.get("ts", now) > GHOST_TTL:
                del edges[eid]

    def follow(self, uid: str, *, email: Any = None, code: Any = None) -> dict[str, Any]:
        """Request to follow. Returns ``{"status", "target", "notify", "by_email"}``; for an
        email request the caller must answer with ``GENERIC_SENT`` whatever happened."""
        self.require(uid)
        allow = {k.lower(): v for k, v in self._allow().items()}
        target: str | None
        if isinstance(code, str) and code.strip():
            c = code.strip().upper().replace("-", "").replace(" ", "")
            target = (self._doc.load().get("codes") or {}).get(c)
            if not target or not self.is_athlete(target):
                raise SocialError("That code doesn't match anyone on rabbt.", 404)
            e_addr = None
        elif isinstance(email, str) and email.strip():
            e_addr = email.strip().lower()
            if not _EMAIL.match(e_addr):
                raise SocialError("Enter an email address or an invite code.")
            target = allow.get(e_addr)
            if target is not None and target.startswith("coach_"):
                target = None
        else:
            raise SocialError("Enter an email address or an invite code.")
        if target == uid:
            raise SocialError("That's you!")
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            self._materialize(d)
            edges = d.setdefault("edges", {})
            mine = [e for e in edges.values() if e["follower"] == uid]
            for e in mine:
                if (target and e.get("followee") == target) or \
                        (target is None and e.get("followee") is None and e.get("email") == e_addr):
                    return {"status": e["status"] if not e.get("hidden") else "pending",
                            "target": target, "notify": None, "by_email": e_addr is not None}
            if len(mine) >= MAX_OUTGOING:
                raise SocialError(f"You can follow up to {MAX_OUTGOING} people.")
            if sum(1 for e in mine if now - e.get("ts", 0) < 86400) >= MAX_NEW_PER_DAY:
                raise SocialError("That's a lot of requests today. Try again tomorrow.", 429)
            edge: dict[str, Any] = {"id": "f" + secrets.token_hex(6), "follower": uid, "followee": target,
                                    "email": e_addr, "status": "pending", "ts": now}
            notify = None
            if target is not None:
                tu = self._user(d, target)
                if uid in tu["blocked"]:
                    edge["hidden"] = True
                else:
                    reverse = any(e["follower"] == target and e.get("followee") == uid
                                  and e["status"] == "active" for e in edges.values())
                    if self._settings_of(d, target)["auto_accept"] and reverse:
                        edge["status"] = "active"
                        self._user(d, uid)["ever_followed"] = True
                    notify = target
            edges[edge["id"]] = edge
            return {"status": edge["status"], "target": target, "notify": notify,
                    "by_email": e_addr is not None}
        return self._update(apply)

    def connect_invited(self, inviter: str, joiner: str) -> bool:
        """Invite-link join (``access.py``): a mutual, active follow between the person who
        made the invite and the new member, marked ``via: "invite"``. Nothing happens (False)
        for coach accounts, non-athletes, the same id, or a block either way."""
        if not inviter or inviter == joiner or not (self.is_athlete(inviter) and self.is_athlete(joiner)):
            return False
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> bool:
            self._materialize(d)
            users = d.get("users") or {}
            if joiner in ((users.get(inviter) or {}).get("blocked") or []) \
                    or inviter in ((users.get(joiner) or {}).get("blocked") or []):
                return False
            edges = d.setdefault("edges", {})
            for a, b in ((inviter, joiner), (joiner, inviter)):
                e = next((x for x in edges.values() if x["follower"] == a and x.get("followee") == b), None)
                if e is None:
                    e = {"id": "f" + secrets.token_hex(6), "follower": a, "followee": b, "email": None,
                         "status": "pending", "ts": now}
                    edges[e["id"]] = e
                if e["status"] != "active":
                    e["status"], e["accepted"] = "active", now
                e.pop("hidden", None)
                e["via"] = "invite"
                self._user(d, a)["ever_followed"] = True
            return True
        return bool(self._update(apply))

    def _edge_action(self, uid: str, edge_id: Any, role: str,
                     fn: Callable[[dict[str, Any], dict[str, Any]], Any]) -> Any:
        """Run ``fn(doc, edge)`` on an edge where ``uid`` plays ``role`` (follower/followee)."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> Any:
            e = (d.get("edges") or {}).get(edge_id) if isinstance(edge_id, str) else None
            if e is None or e.get(role) != uid or (role == "followee" and e.get("hidden")):
                raise SocialError("request not found", 404)
            return fn(d, e)
        return self._update(apply)

    def accept(self, uid: str, edge_id: Any) -> str:
        def fn(d: dict[str, Any], e: dict[str, Any]) -> str:
            if e["status"] != "pending":
                raise SocialError("request not found", 404)
            e["status"], e["accepted"] = "active", int(self._clock())
            self._user(d, e["follower"])["ever_followed"] = True
            return str(e["follower"])
        return self._edge_action(uid, edge_id, "followee", fn)

    def decline(self, uid: str, edge_id: Any) -> None:
        def fn(d: dict[str, Any], e: dict[str, Any]) -> None:
            if e["status"] != "pending":
                raise SocialError("request not found", 404)
            del d["edges"][e["id"]]
        self._edge_action(uid, edge_id, "followee", fn)

    def unfollow(self, uid: str, edge_id: Any) -> None:
        """Stop following, or cancel a request (including one by email)."""
        self._edge_action(uid, edge_id, "follower", lambda d, e: d["edges"].pop(e["id"]))

    def remove_follower(self, uid: str, edge_id: Any) -> None:
        self._edge_action(uid, edge_id, "followee", lambda d, e: d["edges"].pop(e["id"]))

    def block(self, uid: str, other: Any) -> None:
        """Remove every edge between the two and keep ``other`` from following again."""
        self.require(uid)
        if not isinstance(other, str) or other == uid or not self.is_athlete(other):
            raise SocialError("person not found", 404)

        def apply(d: dict[str, Any]) -> None:
            u = self._user(d, uid)
            if other not in u["blocked"]:
                u["blocked"] = (u["blocked"] + [other])[-500:]
            edges = d.setdefault("edges", {})
            for eid, e in list(edges.items()):
                if {e["follower"], e.get("followee")} == {uid, other}:
                    del edges[eid]
        self._update(apply)

    def unblock(self, uid: str, other: Any) -> None:
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            u = self._user(d, uid)
            u["blocked"] = [b for b in u["blocked"] if b != other]
            for e in (d.get("edges") or {}).values():
                if e["follower"] == other and e.get("followee") == uid:
                    e.pop("hidden", None)
        self._update(apply)

    # --------------------------------------------------------------- reads --
    def follows(self, viewer: str, owner: str) -> bool:
        """Active edge, and both are still athletes (removed users drop out of feeds)."""
        if not (self.is_athlete(viewer) and self.is_athlete(owner)):
            return False
        return any(e["follower"] == viewer and e.get("followee") == owner and e["status"] == "active"
                   for e in (self._doc.load().get("edges") or {}).values())

    def following_ids(self, uid: str, limit: int = FEED_FOLLOWEES) -> list[str]:
        es = [e for e in (self._doc.load().get("edges") or {}).values()
              if e["follower"] == uid and e["status"] == "active" and e.get("followee")]
        live = self._athlete_ids()
        es = [e for e in es if e["followee"] in live]
        es.sort(key=lambda e: e.get("accepted") or e.get("ts", 0), reverse=True)
        return [str(e["followee"]) for e in es[:limit]]

    def follower_ids(self, uid: str) -> list[str]:
        """People with an active edge to ``uid`` (still athletes)."""
        live = self._athlete_ids()
        return [str(e["follower"]) for e in (self._doc.load().get("edges") or {}).values()
                if e.get("followee") == uid and e["status"] == "active" and e["follower"] in live]

    def pending_ids(self, uid: str) -> set[str]:
        """People ``uid`` asked to follow (still pending)."""
        return {str(e["followee"]) for e in (self._doc.load().get("edges") or {}).values()
                if e["follower"] == uid and e["status"] == "pending" and e.get("followee")}

    def blocked_between(self, a: str, b: str) -> bool:
        """Either one blocked the other."""
        users = self._doc.load().get("users") or {}
        return b in ((users.get(a) or {}).get("blocked") or []) or a in ((users.get(b) or {}).get("blocked") or [])

    def blocked_ids(self, uid: str) -> set[str]:
        """Everyone ``uid`` blocked or who blocked ``uid`` (``blocked_between`` for many, one read)."""
        users = self._doc.load().get("users") or {}
        out = set((users.get(uid) or {}).get("blocked") or [])
        out.update(o for o, u in users.items() if uid in ((u or {}).get("blocked") or []))
        return out

    def ever_followed(self, uid: str) -> bool:
        return bool(((self._doc.load().get("users") or {}).get(uid) or {}).get("ever_followed"))

    def people(self, uid: str) -> dict[str, Any]:
        """Raw lists; the caller adds names and photos for ``user_id``s."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            self._materialize(d)
            u = self._user(d, uid)
            out: dict[str, Any] = {"following": [], "followers": [], "pending_in": [], "pending_out": []}
            for e in d["edges"].values():
                if e["follower"] == uid:
                    if e["status"] == "active":
                        out["following"].append({"edge_id": e["id"], "user_id": e["followee"],
                                                 "since": e.get("accepted") or e["ts"]})
                    else:  # by email: show what they typed, never whether it's an account
                        out["pending_out"].append({"edge_id": e["id"], "ts": e["ts"],
                                                   "email": e.get("email"),
                                                   "user_id": None if e.get("email") else e.get("followee")})
                elif e.get("followee") == uid and not e.get("hidden"):
                    item = {"edge_id": e["id"], "user_id": e["follower"], "ts": e["ts"],
                            "since": e.get("accepted") or e["ts"]}
                    out["followers" if e["status"] == "active" else "pending_in"].append(item)
            for k in out:
                out[k].sort(key=lambda x: x.get("ts") or x.get("since") or 0, reverse=True)
            out["blocked"] = list(u["blocked"])
            out["invite_code"] = u["code"]
            out["settings"] = self._settings_of(d, uid)
            return out
        return self._update(apply)

    # --------------------------------------------------------------- kudos --
    def _kudos(self, owner: str):
        return self._s.user_doc(owner, "kudos")

    def _can_cheer(self, giver: str, owner: str) -> None:
        self.require(giver)
        if giver == owner or not self.follows(giver, owner):
            raise SocialError("workout not found", 404)

    def give_kudos(self, giver: str, owner: str, aid: Any) -> dict[str, Any]:
        """Returns ``{"count", "you_kudoed", "new"}``; giving twice is a no-op."""
        aid = valid_activity_id(aid)
        self._can_cheer(giver, owner)
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            acts = d.setdefault("acts", {})
            a = acts.setdefault(aid, {"by": {}, "cheers": [], "ts": now})
            new = giver not in a["by"]
            if new:
                if len(a["by"]) >= MAX_KUDOS_PER_ACT:
                    raise SocialError("That workout has all the kudos it can hold.")
                a["by"][giver] = now
                a["ts"] = now
            self._trim(acts)
            return {"count": len(a["by"]), "you_kudoed": True, "new": new}
        return self._kudos(owner).update(apply)

    def remove_kudos(self, giver: str, owner: str, aid: Any) -> dict[str, Any]:
        aid = valid_activity_id(aid)
        self._can_cheer(giver, owner)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            a = d.get("acts", {}).get(aid)
            if a is None:
                return {"count": 0, "you_kudoed": False}
            a["by"].pop(giver, None)
            return {"count": len(a["by"]), "you_kudoed": False}
        return self._kudos(owner).update(apply)

    def cheer(self, giver: str, owner: str, aid: Any, text: Any) -> dict[str, Any]:
        aid = valid_activity_id(aid)
        self._can_cheer(giver, owner)
        if not isinstance(text, str) or not text.strip():
            raise SocialError("Write a short cheer first.")
        body = " ".join(text.split())[:CHEER_LEN]
        now = int(self._clock())
        cheer = {"id": "c" + secrets.token_hex(6), "by": giver, "text": body, "ts": now}

        def apply(d: dict[str, Any]) -> None:
            acts = d.setdefault("acts", {})
            a = acts.setdefault(aid, {"by": {}, "cheers": [], "ts": now})
            if len(a["cheers"]) >= MAX_CHEERS:
                raise SocialError(f"Up to {MAX_CHEERS} cheers per workout.")
            a["cheers"].append(cheer)
            a["ts"] = now
            self._trim(acts)
        self._kudos(owner).update(apply)
        return cheer

    def delete_cheer(self, uid: str, owner: str, aid: Any, cheer_id: Any) -> None:
        """The cheer's author or the workout's owner may delete it."""
        aid = valid_activity_id(aid)
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            a = d.get("acts", {}).get(aid) or {}
            cs = a.get("cheers") or []
            keep = [c for c in cs if not (c["id"] == cheer_id and (uid == owner or c["by"] == uid))]
            if len(keep) == len(cs):
                raise SocialError("cheer not found", 404)
            a["cheers"] = keep
        self._kudos(owner).update(apply)

    @staticmethod
    def _trim(acts: dict[str, Any]) -> None:
        if len(acts) > MAX_KUDOS_ACTS:
            for k in sorted(acts, key=lambda k: acts[k].get("ts", 0))[:len(acts) - MAX_KUDOS_ACTS]:
                del acts[k]

    def kudos_of(self, owner: str) -> dict[str, Any]:
        return self._kudos(owner).load().get("acts", {})

    def kudos_bonus(self, uid: str, today: date) -> dict[str, int]:
        """Progress bonus keys: +5 XP per kudos received, at most 10 a day (by UTC day)."""
        per_day: dict[str, int] = {}
        first = (today - timedelta(days=KUDOS_XP_DAYS)).isoformat()
        for a in self.kudos_of(uid).values():
            for giver, ts in (a.get("by") or {}).items():
                if giver == uid:
                    continue
                day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                if day >= first:
                    per_day[day] = per_day.get(day, 0) + 1
        return {f"kudos:{day}:{i}": KUDOS_XP for day, n in per_day.items()
                for i in range(1, min(n, KUDOS_XP_PER_DAY) + 1)}

    def badge(self, uid: str) -> dict[str, int]:
        seen = int(self._s.user_doc(uid, "social_seen").load().get("ts") or 0)
        pending = sum(1 for e in (self._doc.load().get("edges") or {}).values()
                      if e.get("followee") == uid and e["status"] == "pending" and not e.get("hidden"))
        new = 0
        for a in self.kudos_of(uid).values():
            new += sum(1 for g, ts in (a.get("by") or {}).items() if ts > seen and g != uid)
            new += sum(1 for c in a.get("cheers") or [] if c["ts"] > seen and c["by"] != uid)
        return {"pending": pending, "new_kudos": new}

    def mark_seen(self, uid: str) -> None:
        self._s.user_doc(uid, "social_seen").save({"ts": int(self._clock())})

    def requests_since(self, uid: str, since: float) -> int:
        """Pending follow requests to ``uid`` newer than ``since`` (app icon badge)."""
        return sum(1 for e in (self._doc.load().get("edges") or {}).values()
                   if e.get("followee") == uid and e["status"] == "pending" and not e.get("hidden")
                   and e.get("ts", 0) > since and not self.blocked_between(uid, e.get("follower") or ""))


# ------------------------------------------------------------------- feed ---
def normalize(acts: list[dict[str, Any]], today: date, days: int = FEED_DAYS) -> list[dict[str, Any]]:
    """Recent workouts as feed items (newest first). No HR, power, health data or location."""
    by_id = {str(a.get("activity_id")): a for a in acts if a.get("activity_id") is not None}
    first = today - timedelta(days=days)
    out = []
    for r in _rows(acts):
        if r.get("id") is None or not (first <= r["date"] <= today):
            continue
        raw = by_id.get(str(r["id"])) or {}
        stamp = str(raw.get("date") or "")
        out.append({"id": str(r["id"]), "date": r["date"].isoformat(),
                    "time": stamp[11:16] if len(stamp) >= 16 else None,
                    "sport": r["sport"], "title": str(r["name"] or "Workout")[:80],
                    "minutes": round(r["min"]), "km": round(r["km"], 1) if r["km"] else None,
                    "climb_m": int(r["climb"]) if r["climb"] else None,
                    "xp": workout_xp(r["min"]), "race": raw.get("event") == "race"})
    out.sort(key=lambda x: (x["date"], x["time"] or ""), reverse=True)
    return out


def visible(item: dict[str, Any], s: dict[str, bool]) -> dict[str, Any] | None:
    """What a follower may see of one workout under the owner's settings."""
    if not s["workouts"] or (item.get("race") and not s["races"]):
        return None
    out = dict(item)
    if not s["distance"]:
        out["km"] = out["climb_m"] = None
    if not s["times"]:
        out["minutes"] = out["xp"] = out["time"] = None
    if not s["races"]:
        out["race"] = False
    return out


class SocialFeed:
    """Followees' recent workouts, cached per followee for ``FEED_CACHE_S``."""

    def __init__(self, social: Social, *, activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                 meta: Callable[[str], dict[str, Any]], clock: Callable[[], float] = time.monotonic,
                 consent: Callable[[str], bool] | None = None) -> None:
        """``activities(uid)`` -> (their today, compact activities); ``meta(uid)`` -> name,
        photo, picture, level, streak (called at most once per cache period). ``consent(uid)``:
        has this person agreed to share workouts with friends (community.sharing_consent)? Without
        it, followers see none of their workouts. Unset (tests, no community) = settings only."""
        self.social = social
        self.consent = consent
        self._acts = activities
        self._meta = meta
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def entry(self, uid: str) -> dict[str, Any]:
        with self._lock:
            hit = self._cache.get(uid)
        if hit and self._clock() - hit[0] < FEED_CACHE_S:
            return hit[1]
        try:
            today, acts = self._acts(uid)
            items = normalize(acts, today)
        except Exception:  # Garmin not connected or unreachable: nothing to show
            today, items = None, []
        try:
            meta = self._meta(uid)
        except Exception:
            meta = {"name": "Friend", "photo": None, "picture": "", "level": None, "streak": None}
        e = {"today": today.isoformat() if today else None, "items": items, "meta": meta}
        with self._lock:
            self._cache[uid] = (self._clock(), e)
            if len(self._cache) > 500:
                self._cache.pop(next(iter(self._cache)))
        return e

    def invalidate(self, uid: str) -> None:
        with self._lock:
            self._cache.pop(uid, None)

    def _user(self, uid: str, e: dict[str, Any], s: dict[str, bool]) -> dict[str, Any]:
        m = e["meta"]
        return {"id": uid, "name": m.get("name") or "Friend", "photo": m.get("photo"),
                "picture": m.get("picture") or "",
                "level": m.get("level") if s["streak"] else None,
                "streak": m.get("streak") if s["streak"] else None}

    def _decorate(self, viewer: str, owner: str, items: list[dict[str, Any]], user: dict[str, Any],
                  names: Callable[[str], str]) -> list[dict[str, Any]]:
        kudos = self.social.kudos_of(owner)
        out = []
        for it in items:
            k = kudos.get(it["id"]) or {}
            by = k.get("by") or {}
            cheers = [{"id": c["id"], "by": {"id": c["by"], "name": names(c["by"])}, "text": c["text"],
                       "ts": c["ts"], "mine": c["by"] == viewer, "can_delete": c["by"] == viewer or viewer == owner}
                      for c in k.get("cheers") or []]
            out.append({**it, "user": user, "mine": viewer == owner, "kudos": len(by),
                        "you_kudoed": viewer in by, "cheers": cheers})
        return out

    def visible_items(self, viewer: str, owner: str) -> list[dict[str, Any]]:
        e = self.entry(owner)
        if viewer == owner:
            return list(e["items"])
        if not self.shares(owner):
            return []
        s = self.social.settings(owner)
        return [v for it in e["items"] if (v := visible(it, s)) is not None]

    def shares(self, owner: str) -> bool:
        """Has ``owner`` consented to friends seeing their workouts?"""
        if self.consent is None:
            return True
        try:
            return bool(self.consent(owner))
        except Exception:
            return False

    def has_item(self, viewer: str, owner: str, aid: str) -> bool:
        return any(it["id"] == aid for it in self.visible_items(viewer, owner))

    def feed(self, viewer: str, names: Callable[[str], str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for owner in [viewer] + self.social.following_ids(viewer):
            e = self.entry(owner)
            s = DEFAULT_SETTINGS | {"streak": True} if owner == viewer else self.social.settings(owner)
            out += self._decorate(viewer, owner, self.visible_items(viewer, owner), self._user(owner, e, s), names)
        out.sort(key=lambda x: (x["date"], x["time"] or ""), reverse=True)
        return out[:FEED_MAX_ITEMS]

    def card(self, viewer: str, owner: str, names: Callable[[str], str]) -> dict[str, Any]:
        if viewer != owner and not self.social.follows(viewer, owner):
            raise SocialError("person not found", 404)
        e = self.entry(owner)
        s = self.social.settings(owner)
        items = self.visible_items(viewer, owner)
        week: dict[str, Any] | None = None
        if e["today"] and s["workouts"] and (viewer == owner or self.shares(owner)):
            today = date.fromisoformat(e["today"])
            monday = (today - timedelta(days=today.weekday())).isoformat()
            wk = [it for it in items if it["date"] >= monday]
            week = {"workouts": len(wk),
                    "hours": round(sum(it["minutes"] or 0 for it in wk) / 60, 1) if s["times"] else None}
        return {"user": self._user(owner, e, s), "week": week,
                "recent": self._decorate(viewer, owner, items[:5], self._user(owner, e, s), names),
                "shares": {k: s[k] for k in ("workouts", "distance", "times", "streak", "races")}}


__all__ = ["Social", "SocialFeed", "SocialError", "GENERIC_SENT", "DEFAULT_SETTINGS", "normalize", "visible",
           "valid_activity_id"]
