"""Community clubs: local run clubs, crews and race groups, with meetups and challenges.

* User clubs: name (<= 40), sport, city/state (for "near you"), description (<= 300), an
  emoji, privacy ``open`` (anyone on Rabbit joins) or ``approval`` (admins approve join
  requests). Roles: owner, admin, member. Invites (a follow edge either way) and the club
  code skip approval. At most ``MAX_CLUBS`` clubs per athlete, ``MAX_MEMBERS`` per club.
* Race groups: every race group from ``racepeople`` (people racing the same event together)
  shows up as a club "Leadville 100 · 2027" (id ``r-<gid>``). Membership is the race's.
* Meetups (user clubs): title, start (club-local ``YYYY-MM-DDTHH:MM``), one-off or weekly,
  where (a public place, free text), pace and level. Owner/admins create them; members RSVP
  going / maybe per occurrence. ``reminders`` lists "going" occurrences in the next
  ``REMIND_H`` hours for a Rabbit moment (community.py).
* Challenges: a club challenge is a ``challenges.py`` friend group tagged with the club;
  members join without an invite. The club keeps the challenge group ids.
* Discover: clubs in the athlete's city (then state) from the profile's home location.

Athletes only (allowlisted, never ``coach_``). Blocked people (either way) never see each
other in member lists, and a club owner who blocked you never shows up in Discover.

Storage: global ``clubs`` doc ``{"clubs": {cid: {...}}, "codes": {code: cid}}``.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from .appstore import AppStore

MAX_CLUBS = 50
MAX_MEMBERS = 500
NAME_LEN = 40
DESC_LEN = 300
CITY_LEN = 40
STATE_LEN = 20
EMOJI_LEN = 8
MAX_INVITES = 200
MAX_REQUESTS = 200
MAX_MEETUPS = 30
MAX_CHALLENGES = 6
TITLE_LEN = 60
WHERE_LEN = 120
PACE_LEN = 40
NOTE_LEN = 200
REMIND_H = 18
DISCOVER_MAX = 20
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
PRIVACY = ("open", "approval")
# Who can find the club: public (Local, search, featured cards; the default and every club saved
# before this) or private (invite or club code only; hidden from everyone who isn't a member or
# invited, and nobody can request to join).
VISIBILITY = ("public", "private")
SPORTS = ("running", "trail", "cycling", "triathlon", "swimming", "walking", "multisport", "other")
LEVELS = ("all", "easy", "moderate", "fast")
ROLES = ("owner", "admin", "member")
UPCOMING_DAYS = 120
UPCOMING_MAX = 8
_CID = re.compile(r"^(g[0-9a-f]{12}|r-[A-Za-z0-9_-]{1,64}|b-[0-9a-f]{12})$")
_MID = re.compile(r"^m[0-9a-f]{10}$")
_WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ClubError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def clean(text: Any, limit: int, what: str, *, required: bool = False) -> str:
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise ClubError(f"{what} must be text")
    s = " ".join(_CTRL.sub("", text).split())
    if required and not s:
        raise ClubError(f"Give it a {what.lower()}.")
    if len(s) > limit:
        raise ClubError(f"{what} can be up to {limit} characters.")
    return s


def race_cid(gid: str) -> str:
    return f"r-{gid}"


def valid_cid(cid: Any) -> str:
    if not isinstance(cid, str) or not _CID.match(cid):
        raise ClubError("club not found", 404)
    return cid


def _when(v: Any) -> datetime:
    if not isinstance(v, str) or not _WHEN.match(v):
        raise ClubError("Pick a date and time.")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        raise ClubError("Pick a date and time.") from None


def next_occurrence(m: dict[str, Any], now: datetime) -> datetime | None:
    """The next start of a meetup at or after ``now`` minus 2 h (still "on" while it runs);
    None once a one-off is over. ``now`` is naive local time."""
    start = datetime.fromisoformat(m["start"])
    since = now - timedelta(hours=2)
    if start >= since:
        return start
    if m.get("repeat") != "weekly":
        return None
    weeks = (since - start).days // 7
    t = start + timedelta(weeks=weeks)
    while t < since:
        t += timedelta(weeks=1)
    return t


class Clubs:
    def __init__(self, store: AppStore, *, is_athlete: Callable[[str], bool],
                 related: Callable[[str, str], bool], blocked: Callable[[str, str], bool],
                 race_groups: Callable[[str], list[dict[str, Any]]] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        """``related(a, b)``: active follow edge either way; ``race_groups(uid)``:
        ``RacePeople.groups_of``."""
        self._doc = store.global_doc("clubs")
        self._is_athlete = is_athlete
        self._related = related
        self._blocked = blocked
        self._race_groups = race_groups
        # Shared training blocks (blocks.py): ``b-<id>`` groups for the block feed, set by webapp.
        self.block_groups: Callable[[str], list[dict[str, Any]]] | None = None
        self._clock = clock
        self._lock = threading.Lock()

    def _update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            return self._doc.update(fn)

    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            raise ClubError("Community is for athletes on Rabbit.", 403)

    # ------------------------------------------------------------ helpers --
    @staticmethod
    def _new_code(d: dict[str, Any]) -> str:
        codes = d.setdefault("codes", {})
        while True:
            c = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            if c not in codes:
                return c

    def _races(self, uid: str) -> list[dict[str, Any]]:
        if self._race_groups is None:
            return []
        try:
            return self._race_groups(uid)
        except Exception:  # race people unavailable: clubs still work
            return []

    def _block(self, uid: str, cid: str) -> dict[str, Any] | None:
        """``uid``'s training block ``b-<id>`` (blocks.py), else None."""
        if self.block_groups is None:
            return None
        try:
            return next((b for b in self.block_groups(uid) if b["id"] == cid), None)
        except Exception:  # blocks unavailable: clubs still work
            return None

    @staticmethod
    def _count(d: dict[str, Any], uid: str) -> int:
        return sum(1 for c in (d.get("clubs") or {}).values() if uid in c["members"])

    @staticmethod
    def _get(d: dict[str, Any], cid: Any) -> dict[str, Any]:
        c = (d.get("clubs") or {}).get(cid) if isinstance(cid, str) else None
        if c is None:
            raise ClubError("club not found", 404)
        return c

    def _role(self, d: dict[str, Any], cid: Any, uid: str) -> tuple[dict[str, Any], str]:
        c = self._get(d, cid)
        role = c["members"].get(uid)
        if role is None:
            raise ClubError("club not found", 404)
        return c, role

    @staticmethod
    def _private(c: dict[str, Any]) -> bool:
        return c.get("visibility") == "private"

    @staticmethod
    def _admin(role: str | None) -> bool:
        return role in ("owner", "admin")

    @staticmethod
    def _race_name(r: dict[str, Any]) -> str:
        year = str(r.get("date") or "")[:4]
        return f"{r['name']} · {year}" if year else str(r["name"])

    def _live(self, c: dict[str, Any]) -> list[str]:
        return [m for m in c["members"] if self._is_athlete(m)]

    # -------------------------------------------------------------- reads --
    def is_member(self, cid: str, uid: str) -> bool:
        if not isinstance(cid, str):
            return False
        if cid.startswith("r-"):
            return any(race_cid(r["id"]) == cid for r in self._races(uid))
        if cid.startswith("b-"):
            return self._block(uid, cid) is not None
        c = (self._doc.load().get("clubs") or {}).get(cid)
        return c is not None and uid in c["members"]

    def member_ids(self, cid: str, viewer: str) -> list[str]:
        """Members of a club ``viewer`` is in (else [])."""
        if cid.startswith("r-"):
            r = next((r for r in self._races(viewer) if race_cid(r["id"]) == cid), None)
            return list(r["members"]) if r else []
        if cid.startswith("b-"):
            return list((self._block(viewer, cid) or {}).get("members") or [])
        c = (self._doc.load().get("clubs") or {}).get(cid)
        if not c or viewer not in c["members"]:
            return []
        return self._live(c)

    def ids_of(self, uid: str) -> list[str]:
        """Every club ``uid`` is in (user clubs and race groups)."""
        mine = [cid for cid, c in (self._doc.load().get("clubs") or {}).items() if uid in c["members"]]
        try:
            blocks = [b["id"] for b in (self.block_groups(uid) if self.block_groups is not None else [])]
        except Exception:  # blocks unavailable: clubs still work
            blocks = []
        return mine + [race_cid(r["id"]) for r in self._races(uid)] + blocks

    def name_of(self, cid: str, viewer: str) -> str | None:
        if cid.startswith("r-"):
            r = next((r for r in self._races(viewer) if race_cid(r["id"]) == cid), None)
            return self._race_name(r) if r else None
        if cid.startswith("b-"):
            return (self._block(viewer, cid) or {}).get("name")
        c = (self._doc.load().get("clubs") or {}).get(cid)
        return c["name"] if c and viewer in c["members"] else None

    def admins_of(self, cid: str) -> list[str]:
        c = (self._doc.load().get("clubs") or {}).get(cid)
        return [m for m, r in (c or {}).get("members", {}).items() if self._admin(r)]

    def _view(self, c: dict[str, Any], uid: str) -> dict[str, Any]:
        role = c["members"].get(uid)
        out = {"id": c["id"], "kind": "club", "name": c["name"], "sport": c.get("sport") or "running",
               "city": c.get("city") or "", "state": c.get("state") or "",
               "description": c.get("description") or "", "emoji": c.get("emoji") or "🐇",
               "privacy": c.get("privacy") or "open", "visibility": c.get("visibility") or "public",
               "role": role, "members": len(self._live(c)),
               "requested": uid in (c.get("requests") or {})}
        if self._admin(role) or (role and out["privacy"] == "open"):
            out["code"] = c.get("code")
        if self._admin(role):
            out["requests"] = len(c.get("requests") or {})
        return out

    def _race_view(self, r: dict[str, Any]) -> dict[str, Any]:
        return {"id": race_cid(r["id"]), "kind": "race", "name": self._race_name(r), "sport": "other",
                "city": "", "state": "", "description": "Racing together", "emoji": "🏁", "privacy": "approval",
                "role": "member", "members": len(r["members"]), "requested": False,
                "event_id": r.get("event_id"), "date": r.get("date")}

    def overview(self, uid: str, *, city: str = "", state: str = "", q: str = "") -> dict[str, Any]:
        """``{"clubs": mine (user + race), "invites": to me, "discover": near me / matching q}``."""
        self.require(uid)
        d = self._doc.load()
        clubs = [self._view(c, uid) for c in (d.get("clubs") or {}).values() if uid in c["members"]]
        clubs.sort(key=lambda c: c["name"].lower())
        races = sorted((self._race_view(r) for r in self._races(uid)), key=lambda c: c.get("date") or "")
        invites = []
        for c in (d.get("clubs") or {}).values():
            inv = (c.get("invites") or {}).get(uid)
            if uid not in c["members"] and inv and not self._blocked(uid, inv["by"]):
                invites.append({**self._view(c, uid), "invited_by": inv["by"]})
        return {"clubs": races + clubs, "invites": invites,
                "discover": self.discover(uid, city=city, state=state, q=q, d=d), "max": MAX_CLUBS}

    def invites_since(self, uid: str, since: float) -> int:
        """Open club invites to ``uid`` newer than ``since`` (app icon badge)."""
        n = 0
        for c in (self._doc.load().get("clubs") or {}).values():
            inv = (c.get("invites") or {}).get(uid)
            if uid not in c["members"] and inv and inv.get("ts", 0) > since and not self._blocked(uid, inv["by"]):
                n += 1
        return n

    def discover(self, uid: str, *, city: str = "", state: str = "", q: str = "",
                 d: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Clubs to join: matching ``q`` (name/city), else in my city, then my state."""
        d = d if d is not None else self._doc.load()
        city_l, state_l, ql = city.strip().lower(), state.strip().lower(), " ".join(q.lower().split())[:40]
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for c in (d.get("clubs") or {}).values():
            if uid in c["members"] or self._blocked(uid, c["owner"]) or len(c["members"]) >= MAX_MEMBERS:
                continue
            if self._private(c):
                continue  # private clubs are invite / code only
            ccity, cstate = (c.get("city") or "").lower(), (c.get("state") or "").lower()
            if ql:
                if ql not in c["name"].lower() and ql not in ccity:
                    continue
                score = 0
            elif city_l and ccity == city_l and (not state_l or not cstate or cstate == state_l):
                score = 0
            elif state_l and cstate == state_l:
                score = 1
            else:
                continue
            scored.append((score, c["name"].lower(), c))
        scored.sort(key=lambda x: (x[0], -len(x[2]["members"]), x[1]))
        return [{**self._view(c, uid), "near": "city" if s == 0 and not ql else "state" if s == 1 else None}
                for s, _, c in scored[:DISCOVER_MAX]]

    def get(self, uid: str, cid: Any) -> dict[str, Any]:
        """One club with its members (``{user_id, role}``), requests (admins) and meetups.
        Non-members see an open club's card (to join), never its members or meetups."""
        self.require(uid)
        if isinstance(cid, str) and cid.startswith("r-"):
            r = next((r for r in self._races(uid) if race_cid(r["id"]) == cid), None)
            if r is None:
                raise ClubError("club not found", 404)
            return {**self._race_view(r), "people": [{"user_id": m, "role": "member"} for m in r["members"]
                                                     if m == uid or not self._blocked(uid, m)],
                    "meetups": [], "challenges": [], "pending": []}
        d = self._doc.load()
        c = self._get(d, cid)
        role = c["members"].get(uid)
        if role is None:
            if self._blocked(uid, c["owner"]) or (self._private(c) and uid not in (c.get("invites") or {})):
                raise ClubError("club not found", 404)
            return {**self._view(c, uid), "people": [], "meetups": [], "challenges": [], "pending": []}
        people = [{"user_id": m, "role": r} for m, r in c["members"].items()
                  if self._is_athlete(m) and (m == uid or not self._blocked(uid, m))]
        people.sort(key=lambda p: (ROLES.index(p["role"]), p["user_id"]))
        return {**self._view(c, uid), "people": people,
                "pending": [m for m in (c.get("requests") or {}) if self._admin(role) and self._is_athlete(m)],
                "invited": [m for m in (c.get("invites") or {}) if self._admin(role)],
                "challenges": list(c.get("challenges") or [])}

    def featured_card(self, cid: str, viewer: str, now: datetime) -> dict[str, Any] | None:
        """A featured club's public card (featured.py): name, sport, city, members, my role and
        the next meetup (its place only for open clubs or members). None when gone, a race
        group/block, or the owner and viewer blocked each other."""
        c = (self._doc.load().get("clubs") or {}).get(cid) if isinstance(cid, str) else None
        if c is None or self._blocked(viewer, c["owner"]):
            return None
        if self._private(c) and viewer not in c["members"]:
            return None
        v = self._view(c, viewer)
        member = v["role"] is not None
        nxt = None
        for m in (c.get("meetups") or {}).values():
            mv = self._meetup_view(m, viewer, now)
            if mv["next"] and (nxt is None or mv["next"] < nxt["next"]):
                nxt = mv
        meet = None
        if nxt is not None:
            meet = {"id": nxt["id"], "title": nxt["title"], "next": nxt["next"], "going": len(nxt["going"]),
                    "my_rsvp": nxt["my_rsvp"], "where": nxt["where"] if member or v["privacy"] == "open" else ""}
        return {"club_id": c["id"], "name": v["name"], "emoji": v["emoji"], "sport": v["sport"],
                "city": v["city"], "state": v["state"], "description": v["description"], "members": v["members"],
                "privacy": v["privacy"], "role": v["role"], "requested": v["requested"], "next_meetup": meet,
                "full": len(c["members"]) >= MAX_MEMBERS}

    # ------------------------------------------------------------- writes --
    def _validate(self, fields: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not partial or "name" in fields:
            out["name"] = clean(fields.get("name"), NAME_LEN, "Name", required=True)
        if not partial or "description" in fields:
            out["description"] = clean(fields.get("description"), DESC_LEN, "Description")
        if not partial or "city" in fields:
            out["city"] = clean(fields.get("city"), CITY_LEN, "City")
        if not partial or "state" in fields:
            out["state"] = clean(fields.get("state"), STATE_LEN, "State")
        if not partial or "sport" in fields:
            s = fields.get("sport") or "running"
            if s not in SPORTS:
                raise ClubError("Pick a sport.")
            out["sport"] = s
        if not partial or "emoji" in fields:
            e = clean(fields.get("emoji"), EMOJI_LEN, "Icon")
            if e and (any(ch.isalnum() for ch in e) or " " in e):
                raise ClubError("Pick an emoji for the icon.")
            out["emoji"] = e or "🐇"
        if not partial or "privacy" in fields:
            v = fields.get("privacy") or "open"
            if v not in PRIVACY:
                raise ClubError("privacy must be open or approval")
            out["privacy"] = v
        if not partial or "visibility" in fields:
            v = fields.get("visibility") or "public"
            if v not in VISIBILITY:
                raise ClubError("visibility must be public or private")
            out["visibility"] = v
        return out

    def create(self, uid: str, fields: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(fields, dict):
            raise ClubError("bad request")
        clean_f = self._validate(fields, partial=False)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            if self._count(d, uid) >= MAX_CLUBS:
                raise ClubError(f"You can be in up to {MAX_CLUBS} clubs.")
            cid = "g" + secrets.token_hex(6)
            code = self._new_code(d)
            c = {"id": cid, **clean_f, "owner": uid, "members": {uid: "owner"}, "invites": {}, "requests": {},
                 "meetups": {}, "challenges": [], "code": code, "created": int(self._clock())}
            d.setdefault("clubs", {})[cid] = c
            d["codes"][code] = cid
            return self._view(c, uid)
        return self._update(apply)

    def update(self, uid: str, cid: Any, fields: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(fields, dict):
            raise ClubError("bad request")
        clean_f = self._validate(fields, partial=True)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can change it.", 403)
            c.update(clean_f)
            return self._view(c, uid)
        return self._update(apply)

    def delete(self, uid: str, cid: Any) -> list[str]:
        """Owner only. Returns the former members."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> list[str]:
            c, role = self._role(d, cid, uid)
            if role != "owner":
                raise ClubError("Only the owner can delete the club.", 403)
            (d.get("codes") or {}).pop(c.get("code"), None)
            del d["clubs"][c["id"]]
            return list(c["members"])
        return self._update(apply)

    def invite(self, uid: str, cid: Any, other: Any) -> dict[str, Any]:
        """Invite a friend (follow edge either way): admins, or any member of an open club.
        Returns ``{"notify": uid | None}``."""
        self.require(uid)
        if not isinstance(other, str) or other == uid or not self._is_athlete(other) \
                or not self._related(uid, other) or self._blocked(uid, other):
            raise ClubError("You can invite people you follow or who follow you.", 404)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, role = self._role(d, cid, uid)
            if not self._admin(role) and c.get("privacy") != "open":
                raise ClubError("Only the club's owner or admins can invite.", 403)
            if other in c["members"]:
                return {"notify": None}
            inv = c.setdefault("invites", {})
            if other in inv:
                return {"notify": None}
            if len(inv) >= MAX_INVITES:
                raise ClubError("That club has a lot of open invites already.")
            inv[other] = {"by": uid, "ts": int(self._clock())}
            return {"notify": other}
        return self._update(apply)

    def _join(self, d: dict[str, Any], c: dict[str, Any], uid: str) -> dict[str, Any]:
        if uid in c["members"]:
            return self._view(c, uid)
        if len(c["members"]) >= MAX_MEMBERS:
            raise ClubError(f"That club is full ({MAX_MEMBERS} members).")
        if self._count(d, uid) >= MAX_CLUBS:
            raise ClubError(f"You can be in up to {MAX_CLUBS} clubs.")
        c["members"][uid] = "member"
        (c.get("invites") or {}).pop(uid, None)
        (c.get("requests") or {}).pop(uid, None)
        return self._view(c, uid)

    def respond(self, uid: str, cid: Any, accept: bool) -> dict[str, Any] | None:
        """Answer an invite."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> dict[str, Any] | None:
            c = self._get(d, cid)
            inv = (c.get("invites") or {}).pop(uid, None)
            if inv is None:
                raise ClubError("invite not found", 404)
            return self._join(d, c, uid) if accept else None
        return self._update(apply)

    def join(self, uid: str, cid: Any = None, code: Any = None) -> dict[str, Any]:
        """By code (skips approval), an invite, an open club, or a request to an approval
        club (``{"requested": true}``; admins get notified by the caller)."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            if isinstance(code, str) and code.strip():
                k = code.strip().upper().replace("-", "").replace(" ", "")
                c = (d.get("clubs") or {}).get((d.get("codes") or {}).get(k, ""))
                if c is None or self._blocked(uid, c["owner"]):
                    raise ClubError("That code doesn't match a club.", 404)
                return self._join(d, c, uid)
            c = self._get(d, cid)
            if self._blocked(uid, c["owner"]):
                raise ClubError("club not found", 404)
            if self._private(c) and uid not in c["members"] and uid not in (c.get("invites") or {}):
                raise ClubError("club not found", 404)  # private: invite or club code only
            if uid in c["members"] or uid in (c.get("invites") or {}) or c.get("privacy") == "open":
                return self._join(d, c, uid)
            reqs = c.setdefault("requests", {})
            if uid not in reqs:
                if len(reqs) >= MAX_REQUESTS:
                    raise ClubError("That club has a lot of requests waiting. Try again later.")
                reqs[uid] = {"ts": int(self._clock())}
            return self._view(c, uid)
        return self._update(apply)

    def cancel_request(self, uid: str, cid: Any) -> None:
        self.require(uid)
        self._update(lambda d: (self._get(d, cid).get("requests") or {}).pop(uid, None))

    def decide(self, uid: str, cid: Any, member: Any, approve: bool) -> None:
        """Admins approve or decline a join request."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can do that.", 403)
            if not isinstance(member, str) or member not in (c.get("requests") or {}):
                raise ClubError("request not found", 404)
            if approve:
                if not self._is_athlete(member):
                    c["requests"].pop(member, None)
                    raise ClubError("request not found", 404)
                self._join(d, c, member)
            else:
                c["requests"].pop(member, None)
        self._update(apply)

    def leave(self, uid: str, cid: Any) -> None:
        """Leave a club. An owner hands it to the first admin (else member); the last one out
        deletes it."""
        self.require(uid)
        if isinstance(cid, str) and cid.startswith("r-"):
            raise ClubError("Race groups follow the race: leave it from the race's people.", 400)

        def apply(d: dict[str, Any]) -> None:
            c, role = self._role(d, cid, uid)
            del c["members"][uid]
            for m in (c.get("meetups") or {}).values():
                for occ in (m.get("rsvps") or {}).values():
                    occ.pop(uid, None)
            if not c["members"]:
                (d.get("codes") or {}).pop(c.get("code"), None)
                del d["clubs"][c["id"]]
                return
            if role == "owner":
                heir = next((m for m, r in c["members"].items() if r == "admin"), None) or next(iter(c["members"]))
                c["members"][heir] = "owner"
                c["owner"] = heir
        self._update(apply)

    def remove(self, uid: str, cid: Any, member: Any) -> None:
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            c, role = self._role(d, cid, uid)
            if isinstance(member, str) and member in (c.get("invites") or {}) and self._admin(role):
                del c["invites"][member]
                return
            target = c["members"].get(member) if isinstance(member, str) else None
            if target is None or member == uid:
                raise ClubError("member not found", 404)
            if role == "member" or target == "owner" or (role == "admin" and target == "admin"):
                raise ClubError("You can't remove them.", 403)
            del c["members"][member]
        self._update(apply)

    def set_role(self, uid: str, cid: Any, member: Any, new_role: Any) -> None:
        self.require(uid)
        if new_role not in ("admin", "member"):
            raise ClubError("role must be admin or member")

        def apply(d: dict[str, Any]) -> None:
            c, role = self._role(d, cid, uid)
            if role != "owner":
                raise ClubError("Only the owner can change roles.", 403)
            if not isinstance(member, str) or c["members"].get(member) in (None, "owner"):
                raise ClubError("member not found", 404)
            c["members"][member] = new_role
        self._update(apply)

    def new_code(self, uid: str, cid: Any) -> str:
        self.require(uid)

        def apply(d: dict[str, Any]) -> str:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can do that.", 403)
            d.setdefault("codes", {}).pop(c.get("code"), None)
            c["code"] = self._new_code(d)
            d["codes"][c["code"]] = c["id"]
            return str(c["code"])
        return self._update(apply)

    # ------------------------------------------------------------ meetups --
    def _meetup_fields(self, body: Any, *, partial: bool) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ClubError("bad request")
        out: dict[str, Any] = {}
        if not partial or "title" in body:
            out["title"] = clean(body.get("title"), TITLE_LEN, "Title", required=True)
        if not partial or "start" in body:
            out["start"] = _when(body.get("start")).isoformat(timespec="minutes")
        if not partial or "repeat" in body:
            r = body.get("repeat") or "none"
            if r not in ("none", "weekly"):
                raise ClubError("repeat must be none or weekly")
            out["repeat"] = r
        if not partial or "where" in body:
            out["where"] = clean(body.get("where"), WHERE_LEN, "Where", required=True)
        if not partial or "pace" in body:
            out["pace"] = clean(body.get("pace"), PACE_LEN, "Pace")
        if not partial or "level" in body:
            lv = body.get("level") or "all"
            if lv not in LEVELS:
                raise ClubError("Pick a level.")
            out["level"] = lv
        if not partial or "notes" in body:
            out["notes"] = clean(body.get("notes"), NOTE_LEN, "Notes")
        return out

    def add_meetup(self, uid: str, cid: Any, body: Any, now: datetime) -> dict[str, Any]:
        self.require(uid)
        f = self._meetup_fields(body, partial=False)
        if datetime.fromisoformat(f["start"]) < now.replace(tzinfo=None) - timedelta(hours=1):
            raise ClubError("Pick a time that hasn't passed.")

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can plan meetups.", 403)
            ms = c.setdefault("meetups", {})
            live = {k: m for k, m in ms.items() if next_occurrence(m, now.replace(tzinfo=None)) is not None}
            if len(live) >= MAX_MEETUPS:
                raise ClubError(f"A club can have {MAX_MEETUPS} meetups planned at once.")
            c["meetups"] = live
            mid = "m" + secrets.token_hex(5)
            live[mid] = {"id": mid, **f, "by": uid, "created": int(self._clock()), "rsvps": {}}
            return live[mid]
        return self._meetup_view(self._update(apply), uid, now)

    def update_meetup(self, uid: str, cid: Any, mid: Any, body: Any, now: datetime) -> dict[str, Any]:
        self.require(uid)
        f = self._meetup_fields(body, partial=True)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, role = self._role(d, cid, uid)
            m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
            if m is None:
                raise ClubError("meetup not found", 404)
            if not self._admin(role) and m["by"] != uid:
                raise ClubError("Only the club's owner or admins can change meetups.", 403)
            m.update(f)
            return m
        return self._meetup_view(self._update(apply), uid, now)

    def delete_meetup(self, uid: str, cid: Any, mid: Any) -> list[str]:
        """Returns who had said going/maybe (to tell them)."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> list[str]:
            c, role = self._role(d, cid, uid)
            m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
            if m is None:
                raise ClubError("meetup not found", 404)
            if not self._admin(role) and m["by"] != uid:
                raise ClubError("Only the club's owner or admins can cancel meetups.", 403)
            del c["meetups"][mid]
            return sorted({u for occ in (m.get("rsvps") or {}).values() for u in occ if u != uid})
        return self._update(apply)

    def rsvp(self, uid: str, cid: Any, mid: Any, status: Any, now: datetime) -> dict[str, Any]:
        """going | maybe | none (clear), for the meetup's next occurrence."""
        self.require(uid)
        if status not in ("going", "maybe", "none", None):
            raise ClubError("RSVP going, maybe or none.")
        local = now.replace(tzinfo=None)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, _ = self._role(d, cid, uid)
            m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
            occ = next_occurrence(m, local) if m else None
            if m is None or occ is None:
                raise ClubError("meetup not found", 404)
            key = occ.date().isoformat()
            rs = m.setdefault("rsvps", {})
            for k in [k for k in rs if k < (local.date() - timedelta(days=1)).isoformat()]:
                del rs[k]
            day = rs.setdefault(key, {})
            if status in ("none", None):
                day.pop(uid, None)
            else:
                day[uid] = status
            return m
        return self._meetup_view(self._update(apply), uid, now)

    def _meetup_view(self, m: dict[str, Any], uid: str, now: datetime) -> dict[str, Any]:
        occ = next_occurrence(m, now.replace(tzinfo=None))
        day = (m.get("rsvps") or {}).get(occ.date().isoformat(), {}) if occ else {}
        going = [u for u, s in day.items() if s == "going" and self._is_athlete(u) and (u == uid or not self._blocked(uid, u))]
        maybe = [u for u, s in day.items() if s == "maybe" and self._is_athlete(u) and (u == uid or not self._blocked(uid, u))]
        return {k: m.get(k) for k in ("id", "title", "start", "repeat", "where", "pace", "level", "notes", "by")} | {
            "next": occ.isoformat(timespec="minutes") if occ else None, "going": going, "maybe": len(maybe),
            "my_rsvp": day.get(uid), "mine": m.get("by") == uid}

    def meetups(self, uid: str, cid: str, now: datetime) -> list[dict[str, Any]]:
        """A club's upcoming meetups, soonest first (members only)."""
        if cid.startswith("r-"):
            return []
        c = (self._doc.load().get("clubs") or {}).get(cid)
        if not c or uid not in c["members"]:
            return []
        out = [self._meetup_view(m, uid, now) for m in (c.get("meetups") or {}).values()]
        out = [m for m in out if m["next"]]
        out.sort(key=lambda m: m["next"])
        return out

    def my_meetups(self, uid: str, now: datetime, *, days: int = 14) -> list[dict[str, Any]]:
        """Upcoming meetups across my clubs within ``days`` (``club`` attached), soonest first."""
        last = now.replace(tzinfo=None) + timedelta(days=days)
        out = []
        for c in (self._doc.load().get("clubs") or {}).values():
            if uid not in c["members"]:
                continue
            for m in (c.get("meetups") or {}).values():
                v = self._meetup_view(m, uid, now)
                if v["next"] and datetime.fromisoformat(v["next"]) <= last:
                    out.append({**v, "club": {"id": c["id"], "name": c["name"], "emoji": c.get("emoji") or "🐇"}})
        out.sort(key=lambda m: m["next"])
        return out

    def reminders(self, uid: str, now: datetime) -> list[dict[str, Any]]:
        """"Going" occurrences starting within ``REMIND_H`` hours."""
        local = now.replace(tzinfo=None)
        return [m for m in self.my_meetups(uid, now, days=2) if m["my_rsvp"] == "going"
                and local <= datetime.fromisoformat(m["next"]) <= local + timedelta(hours=REMIND_H)]

    # --------------------------------------------------------- challenges --
    def add_challenge(self, uid: str, cid: Any, gid: str) -> None:
        """Record a club challenge group (the caller started it). Admins only."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can start a club challenge.", 403)
            ch = [g for g in c.get("challenges") or [] if g != gid]
            c["challenges"] = (ch + [gid])[-MAX_CHALLENGES:]
        self._update(apply)

    def can_start_challenge(self, uid: str, cid: Any) -> None:
        d = self._doc.load()
        _, role = self._role(d, cid, uid)
        if not self._admin(role):
            raise ClubError("Only the club's owner or admins can start a club challenge.", 403)

    # ---------------------------------------------------------- upcoming --
    def upcoming(self, viewer: str, cid: str, *, events: Callable[[str], list[dict[str, Any]]],
                 shares_races: Callable[[str], bool], today: date) -> list[dict[str, Any]]:
        """Members' upcoming races (only members who share races; the race itself for a
        race group): ``{user_ids, name, date, type, distance}``, soonest first."""
        members = self.member_ids(cid, viewer)
        if not members:
            raise ClubError("club not found", 404)
        last = (today + timedelta(days=UPCOMING_DAYS)).isoformat()
        out: list[dict[str, Any]] = []
        for m in members:
            if m != viewer and (self._blocked(viewer, m) or (not shares_races(m) and not cid.startswith("r-"))):
                continue
            try:
                evs = events(m)
            except Exception:  # one member's events never break the strip
                evs = []
            for e in evs:
                dd = str(e.get("date") or "")
                if today.isoformat() <= dd <= last:
                    out.append({"user_id": m, "event_id": e.get("id") if m == viewer else None,
                                "name": str(e.get("name") or "Race")[:60], "date": dd,
                                "type": e.get("type"), "distance": e.get("distance")})
        out.sort(key=lambda x: x["date"])
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for x in out:
            k = (x["name"].lower(), x["date"])
            if k in merged:
                merged[k]["user_ids"].append(x["user_id"])
                merged[k]["event_id"] = merged[k]["event_id"] or x["event_id"]
            else:
                merged[k] = {**{k2: v for k2, v in x.items() if k2 != "user_id"}, "user_ids": [x["user_id"]]}
        return list(merged.values())[:UPCOMING_MAX]


def valid_mid(mid: Any) -> str:
    if not isinstance(mid, str) or not _MID.match(mid):
        raise ClubError("meetup not found", 404)
    return mid


__all__ = [
    "LEVELS",
    "MAX_CLUBS",
    "MAX_MEMBERS",
    "SPORTS",
    "ClubError",
    "Clubs",
    "next_occurrence",
    "race_cid",
    "valid_cid",
    "valid_mid",
]
