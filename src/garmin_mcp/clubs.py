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

import hashlib
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
GROUP_LABEL_LEN = 30
GROUP_PACE_LEN = 20
MAX_GROUPS = 4
WAIVER_LEN = 1500
PAID_LEN = 80
MAX_CAPACITY = 500
MAX_GUESTS = 300
GUEST_NAME_LEN = 40
GUEST_EMAIL_LEN = 120
MESSAGE_LEN = 280
HISTORY_KEEP = 16
# Who sees a club run: public (the club's public link page, Local, anyone signed in can RSVP),
# club (members) or private (members who already RSVP'd, admins, and anyone with the run's link).
RUN_SEE = ("public", "club", "private")
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


def clean_block(text: Any, limit: int, what: str) -> str:
    """Like ``clean`` but keeps line breaks (a waiver's paragraphs)."""
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ClubError(f"{what} must be text")
    lines = [" ".join(_CTRL.sub("", ln).split()) for ln in text.replace("\r\n", "\n").split("\n")]
    s = "\n".join(lines).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    if len(s) > limit:
        raise ClubError(f"{what} can be up to {limit} characters.")
    return s


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


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
    skips = set(m.get("skips") or [])
    if m.get("repeat") != "weekly":
        return start if start >= since and start.date().isoformat() not in skips else None
    t = start
    if t < since:
        t = start + timedelta(weeks=(since - start).days // 7)
        while t < since:
            t += timedelta(weeks=1)
    for _ in range(60):  # skipped weeks (at most a year of them)
        if t.date().isoformat() not in skips:
            return t
        t += timedelta(weeks=1)
    return None


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
            raise ClubError("Community is for athletes on rabbt.", 403)

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
    # A meetup is a club run: one-off or weekly, with pace groups, a walk option, beginner and
    # women-only flags, an optional cap (then a waitlist), an optional waiver, a "paid at the
    # door" note and an optional map pin. RSVPs are per occurrence (its date): signed-in people
    # in ``rsvps[date][uid]`` (going | maybe | waitlist), people from the public link page in
    # ``guests[date][gid]``. ``waitq[date]`` orders the waitlist; ``checkins[date]`` lists who
    # showed up (uids and ``g:<gid>``); ``history[date]`` keeps counts once a date is past.

    @staticmethod
    def _flag(body: dict[str, Any], key: str) -> bool:
        v = body.get(key)
        if v is None:
            return False
        if not isinstance(v, bool):
            raise ClubError(f"{key} must be true or false")
        return v

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
        if not partial or "groups" in body:
            gs = body.get("groups") or []
            if not isinstance(gs, list) or len(gs) > MAX_GROUPS:
                raise ClubError(f"Up to {MAX_GROUPS} pace groups.")
            groups = []
            for g in gs:
                if not isinstance(g, dict):
                    raise ClubError("bad pace group")
                label = clean(g.get("label"), GROUP_LABEL_LEN, "Group name")
                pace = clean(g.get("pace"), GROUP_PACE_LEN, "Group pace")
                if label or pace:
                    groups.append({"label": label or "Group", "pace": pace})
            out["groups"] = groups
        for k in ("walk", "beginner", "women"):
            if not partial or k in body:
                out[k] = self._flag(body, k)
        if not partial or "capacity" in body:
            cap = body.get("capacity")
            if cap in (None, "", 0):
                out["capacity"] = None
            elif isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_CAPACITY:
                raise ClubError(f"Spots can be 1 to {MAX_CAPACITY}, or leave it empty for no limit.")
            else:
                out["capacity"] = cap
        if not partial or "see" in body:
            s = body.get("see") or "club"
            if s not in RUN_SEE:
                raise ClubError("Who can see it: public, club or private.")
            out["see"] = s
        if not partial or "waiver" in body:
            out["waiver"] = clean_block(body.get("waiver"), WAIVER_LEN, "Waiver")
        if not partial or "paid" in body:
            out["paid"] = clean(body.get("paid"), PAID_LEN, "Cost")
        if not partial or "lat" in body or "lng" in body:
            lat, lng = body.get("lat"), body.get("lng")
            if lat is None and lng is None:
                out["lat"] = out["lng"] = None
            else:
                ok = (isinstance(lat, int | float) and not isinstance(lat, bool) and -90 <= lat <= 90
                      and isinstance(lng, int | float) and not isinstance(lng, bool) and -180 <= lng <= 180)
                if not ok:
                    raise ClubError("Drop the pin on the map again.")
                out["lat"], out["lng"] = round(float(lat), 5), round(float(lng), 5)
        return out

    def _run_visible(self, c: dict[str, Any], m: dict[str, Any], uid: str, role: str | None,
                     token: str | None = None) -> bool:
        """Can ``uid`` (role in the club or None) see this run?"""
        if self._blocked(uid, c["owner"]) or (m.get("by") and self._blocked(uid, m["by"])):
            return False
        see = m.get("see") or "club"
        if self._admin(role) or m.get("by") == uid:
            return True
        if token is not None and secrets.compare_digest(str(m.get("token") or ""), str(token)):
            return True
        if see == "public":
            return not self._private(c) or role is not None
        if see == "club":
            return role is not None
        return role is not None and any(uid in day for day in (m.get("rsvps") or {}).values())

    def _find_run(self, d: dict[str, Any], cid: Any, mid: Any, uid: str,
                  token: str | None = None) -> tuple[dict[str, Any], dict[str, Any], str | None]:
        c = self._get(d, cid)
        role = c["members"].get(uid)
        m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
        if m is None or not self._run_visible(c, m, uid, role, token):
            raise ClubError("meetup not found", 404)
        return c, m, role

    def add_meetup(self, uid: str, cid: Any, body: Any, now: datetime) -> dict[str, Any]:
        self.require(uid)
        f = self._meetup_fields(body, partial=False)
        if datetime.fromisoformat(f["start"]) < now.replace(tzinfo=None) - timedelta(hours=1):
            raise ClubError("Pick a time that hasn't passed.")

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can plan meetups.", 403)
            if f["see"] == "public" and self._private(c):
                f["see"] = "club"  # a private club's runs never go public
            ms = c.setdefault("meetups", {})
            live = {k: m for k, m in ms.items() if next_occurrence(m, now.replace(tzinfo=None)) is not None}
            if len(live) >= MAX_MEETUPS:
                raise ClubError(f"A club can have {MAX_MEETUPS} meetups planned at once.")
            c["meetups"] = live
            mid = "m" + secrets.token_hex(5)
            live[mid] = {"id": mid, **f, "by": uid, "created": int(self._clock()), "rsvps": {},
                         "token": secrets.token_urlsafe(12)}
            if f["see"] == "public":
                self._ensure_slug(d, c)
            return live[mid]
        return self._meetup_view(self._update(apply), uid, now, admin=True)

    def update_meetup(self, uid: str, cid: Any, mid: Any, body: Any, now: datetime) -> dict[str, Any]:
        """Returns the meetup view plus ``tell``: who's going when the time or spot changed."""
        self.require(uid)
        f = self._meetup_fields(body, partial=True)
        local = now.replace(tzinfo=None)

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
            c, role = self._role(d, cid, uid)
            m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
            if m is None:
                raise ClubError("meetup not found", 404)
            if not self._admin(role) and m["by"] != uid:
                raise ClubError("Only the club's owner or admins can change meetups.", 403)
            if f.get("see") == "public" and self._private(c):
                f["see"] = "club"
            moved = any(k in f and f[k] != m.get(k) for k in ("where", "start", "lat", "lng"))
            m.update(f)
            if m.get("see") == "public":
                self._ensure_slug(d, c)
            tell: list[str] = []
            if moved:
                occ = next_occurrence(m, local)
                day = (m.get("rsvps") or {}).get(occ.date().isoformat(), {}) if occ else {}
                tell = [u for u, s in day.items() if s in ("going", "maybe", "waitlist") and u != uid]
            return m, tell
        m, tell = self._update(apply)
        return self._meetup_view(m, uid, now, admin=True) | {"tell": tell}

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

    @staticmethod
    def _going_count(m: dict[str, Any], key: str) -> int:
        users = sum(1 for s in ((m.get("rsvps") or {}).get(key) or {}).values() if s == "going")
        guests = sum(1 for g in ((m.get("guests") or {}).get(key) or {}).values() if g.get("status") == "going")
        return users + guests

    @staticmethod
    def _prune(m: dict[str, Any], local: datetime) -> None:
        """Move dates before yesterday into ``history`` (counts only) and drop their details."""
        cut = (local.date() - timedelta(days=1)).isoformat()
        rs, gs, wq, ck = (m.setdefault(k, {}) for k in ("rsvps", "guests", "waitq", "checkins"))
        hist = m.setdefault("history", {})
        for key in sorted({*rs, *gs, *wq, *ck}):
            if key >= cut:
                continue
            going = sum(1 for s in (rs.get(key) or {}).values() if s == "going") + sum(
                1 for g in (gs.get(key) or {}).values() if g.get("status") == "going")
            hist[key] = {"going": going, "checkins": len(ck.get(key) or [])}
            for doc in (rs, gs, wq, ck):
                doc.pop(key, None)
        for k in sorted(hist)[:-HISTORY_KEEP]:
            del hist[k]

    def _promote(self, m: dict[str, Any], key: str) -> str | None:
        """Fill a freed spot from the waitlist: returns the promoted uid or ``g:<gid>``."""
        cap = m.get("capacity")
        q = (m.get("waitq") or {}).get(key) or []
        while q and (not cap or self._going_count(m, key) < cap):
            who = q.pop(0)
            if who.startswith("g:"):
                g = ((m.get("guests") or {}).get(key) or {}).get(who[2:])
                if g and g.get("status") == "waitlist":
                    g["status"] = "going"
                    return who
            else:
                day = (m.get("rsvps") or {}).get(key) or {}
                if day.get(who) == "waitlist":
                    day[who] = "going"
                    return who
        return None

    def rsvp(self, uid: str, cid: Any, mid: Any, status: Any, now: datetime, *,
             accept_waiver: bool = False, token: str | None = None) -> dict[str, Any]:
        """going | maybe | none (clear), for the meetup's next occurrence. A full run puts
        "going" on the waitlist; a waiver must be accepted to go. Anyone signed in can RSVP to a
        public run (members or not). Returns the view plus ``promoted`` (who moved up)."""
        self.require(uid)
        if status not in ("going", "maybe", "none", None):
            raise ClubError("RSVP going, maybe or none.")
        local = now.replace(tzinfo=None)

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            c, m, role = self._find_run(d, cid, mid, uid, token)
            if role is None and (m.get("see") or "club") != "public" and token is None:
                raise ClubError("meetup not found", 404)
            occ = next_occurrence(m, local)
            if occ is None:
                raise ClubError("meetup not found", 404)
            key = occ.date().isoformat()
            self._prune(m, local)
            day = m.setdefault("rsvps", {}).setdefault(key, {})
            q = m.setdefault("waitq", {}).setdefault(key, [])
            was = day.get(uid)
            promoted = None
            if status == "going" and m.get("waiver"):
                signed = (m.get("waivers") or {}).get(uid)
                if not (signed and signed.get("v") == _digest(m["waiver"])):
                    if not accept_waiver:
                        raise ClubError("Read and accept the waiver to go.", 409)
                    m.setdefault("waivers", {})[uid] = {"v": _digest(m["waiver"]), "at": int(self._clock())}
            if status in ("none", None):
                day.pop(uid, None)
                if uid in q:
                    q.remove(uid)
            elif status == "going":
                if was != "going":
                    cap = m.get("capacity")
                    if cap and self._going_count(m, key) >= cap:
                        day[uid] = "waitlist"
                        if uid not in q:
                            q.append(uid)
                    else:
                        day[uid] = "going"
            else:
                day[uid] = status
                if uid in q:
                    q.remove(uid)
            if was == "going" and day.get(uid) != "going":
                promoted = self._promote(m, key)
            return m, promoted
        m, promoted = self._update(apply)
        return self._meetup_view(m, uid, now) | {"promoted": promoted}

    def _meetup_view(self, m: dict[str, Any], uid: str, now: datetime, *, admin: bool = False) -> dict[str, Any]:
        occ = next_occurrence(m, now.replace(tzinfo=None))
        key = occ.date().isoformat() if occ else ""
        day = (m.get("rsvps") or {}).get(key, {}) if occ else {}
        seen = [u for u, s in day.items() if self._is_athlete(u) and (u == uid or not self._blocked(uid, u))]
        going = [u for u in seen if day[u] == "going"]
        maybe = [u for u in seen if day[u] == "maybe"]
        guests = (m.get("guests") or {}).get(key, {}) if occ else {}
        guests_going = sum(1 for g in guests.values() if g.get("status") == "going")
        cap = m.get("capacity")
        count = len([s for s in day.values() if s == "going"]) + guests_going
        q = (m.get("waitq") or {}).get(key, []) if occ else []
        out = {k: m.get(k) for k in ("id", "title", "start", "repeat", "where", "pace", "level", "notes", "by")} | {
            "next": occ.isoformat(timespec="minutes") if occ else None, "going": going, "maybe": len(maybe),
            "my_rsvp": day.get(uid), "mine": m.get("by") == uid,
            "groups": list(m.get("groups") or []), "walk": bool(m.get("walk")), "beginner": bool(m.get("beginner")),
            "women": bool(m.get("women")), "capacity": cap, "count": count, "guests": guests_going,
            "spots_left": max(0, cap - count) if cap else None, "waitlist": len(q),
            "wait_pos": (q.index(uid) + 1) if uid in q else None,
            "see": m.get("see") or "club", "waiver": m.get("waiver") or "", "paid": m.get("paid") or "",
            "lat": m.get("lat"), "lng": m.get("lng"), "skips": sorted(m.get("skips") or []),
            "waiver_signed": bool((m.get("waivers") or {}).get(uid)
                                  and (m.get("waivers") or {}).get(uid, {}).get("v") == _digest(m.get("waiver") or "")),
            "checked_in": uid in ((m.get("checkins") or {}).get(key) or []),
        }
        if admin:
            out["token"] = m.get("token")
        return out

    def meetups(self, uid: str, cid: str, now: datetime) -> list[dict[str, Any]]:
        """A club's upcoming meetups the viewer can see, soonest first."""
        if cid.startswith("r-"):
            return []
        c = (self._doc.load().get("clubs") or {}).get(cid)
        if not c:
            return []
        role = c["members"].get(uid)
        if role is None and self._private(c):
            return []
        out = [self._meetup_view(m, uid, now, admin=self._admin(role) or m.get("by") == uid)
               for m in (c.get("meetups") or {}).values() if self._run_visible(c, m, uid, role)]
        out = [m for m in out if m["next"]]
        out.sort(key=lambda m: m["next"])
        return out

    def my_meetups(self, uid: str, now: datetime, *, days: int = 14) -> list[dict[str, Any]]:
        """Upcoming meetups across my clubs, plus public runs I RSVP'd to, within ``days``
        (``club`` attached), soonest first."""
        last = now.replace(tzinfo=None) + timedelta(days=days)
        out = []
        for c in (self._doc.load().get("clubs") or {}).values():
            role = c["members"].get(uid)
            for m in (c.get("meetups") or {}).values():
                if role is None and not any(uid in day for day in (m.get("rsvps") or {}).values()):
                    continue
                if not self._run_visible(c, m, uid, role):
                    continue
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

    # ---------------------------------------------------- organizer tools --
    def _admin_run(self, d: dict[str, Any], cid: Any, mid: Any, uid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        c, role = self._role(d, cid, uid)
        m = (c.get("meetups") or {}).get(mid) if isinstance(mid, str) else None
        if m is None:
            raise ClubError("meetup not found", 404)
        if not self._admin(role) and m.get("by") != uid:
            raise ClubError("Only the club's owner or admins can do that.", 403)
        return c, m

    def roster(self, uid: str, cid: Any, mid: Any, now: datetime) -> dict[str, Any]:
        """Organizer view of the next occurrence: who's going, maybe, on the waitlist (users and
        guests with their contact email), who checked in, waivers signed."""
        self.require(uid)
        local = now.replace(tzinfo=None)
        d = self._doc.load()
        c, m = self._admin_run(d, cid, mid, uid)
        occ = next_occurrence(m, local)
        key = occ.date().isoformat() if occ else ""
        day = (m.get("rsvps") or {}).get(key, {})
        ck = set((m.get("checkins") or {}).get(key) or [])
        waivers = m.get("waivers") or {}
        v = _digest(m.get("waiver") or "")
        rows = [{"id": u, "kind": "user", "status": s, "checked_in": u in ck,
                 "waiver": bool(waivers.get(u) and waivers[u].get("v") == v), "waiver_at": (waivers.get(u) or {}).get("at")}
                for u, s in day.items() if self._is_athlete(u)]
        for gid, g in ((m.get("guests") or {}).get(key) or {}).items():
            rows.append({"id": f"g:{gid}", "kind": "guest", "name": g.get("name"), "email": g.get("email"),
                         "status": g.get("status"), "checked_in": f"g:{gid}" in ck,
                         "waiver": bool(g.get("waiver_at")), "waiver_at": g.get("waiver_at")})
        order = {"going": 0, "waitlist": 1, "maybe": 2}
        rows.sort(key=lambda r: (order.get(str(r["status"]), 3), str(r.get("name") or r["id"])))
        return {"date": key or None, "next": occ.isoformat(timespec="minutes") if occ else None,
                "rows": rows, "going": sum(1 for r in rows if r["status"] == "going"),
                "checked_in": len(ck), "waitlist": len((m.get("waitq") or {}).get(key) or [])}

    def checkin(self, uid: str, cid: Any, mid: Any, who: Any, on: bool, now: datetime) -> dict[str, Any]:
        self.require(uid)
        local = now.replace(tzinfo=None)
        if not isinstance(who, str) or len(who) > 80:
            raise ClubError("Pick someone to check in.")

        def apply(d: dict[str, Any]) -> None:
            _, m = self._admin_run(d, cid, mid, uid)
            occ = next_occurrence(m, local)
            if occ is None:
                raise ClubError("meetup not found", 404)
            key = occ.date().isoformat()
            known = set((m.get("rsvps") or {}).get(key, {})) | {
                f"g:{g}" for g in ((m.get("guests") or {}).get(key) or {})}
            if who not in known:
                raise ClubError("They aren't on the list for this run.")
            ck = m.setdefault("checkins", {}).setdefault(key, [])
            if on and who not in ck:
                ck.append(who)
            elif not on and who in ck:
                ck.remove(who)
        self._update(apply)
        return self.roster(uid, cid, mid, now)

    def skip_week(self, uid: str, cid: Any, mid: Any, day: Any, skip: bool, now: datetime) -> tuple[dict[str, Any], list[str]]:
        """Skip (or un-skip) one date of a weekly run. Returns the view and who had RSVP'd."""
        self.require(uid)
        try:
            dd = date.fromisoformat(str(day))
        except ValueError:
            raise ClubError("Pick a week to skip.") from None

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
            _, m = self._admin_run(d, cid, mid, uid)
            if m.get("repeat") != "weekly":
                raise ClubError("Only weekly runs can skip a week. Cancel a one-off run instead.")
            if dd.weekday() != datetime.fromisoformat(m["start"]).weekday():
                raise ClubError("That date isn't one of this run's days.")
            skips = set(m.get("skips") or [])
            key = dd.isoformat()
            tell: list[str] = []
            if skip:
                skips.add(key)
                tell = [u for u, s in ((m.get("rsvps") or {}).get(key) or {}).items() if u != uid and s in ("going", "maybe", "waitlist")]
            else:
                skips.discard(key)
            m["skips"] = sorted(s for s in skips if s >= (now.date() - timedelta(days=7)).isoformat())[-52:]
            return m, tell
        m, tell = self._update(apply)
        return self._meetup_view(m, uid, now, admin=True), tell

    def duplicate(self, uid: str, cid: Any, mid: Any, now: datetime) -> dict[str, Any]:
        """A copy of a run a week after its next occurrence (or its start), with no RSVPs."""
        self.require(uid)
        d = self._doc.load()
        _, m = self._admin_run(d, cid, mid, uid)
        occ = next_occurrence(m, now.replace(tzinfo=None)) or datetime.fromisoformat(m["start"])
        start = occ + timedelta(weeks=1)
        while start < now.replace(tzinfo=None):
            start += timedelta(weeks=1)
        body = {k: m.get(k) for k in ("title", "repeat", "where", "pace", "level", "notes", "groups", "walk",
                                      "beginner", "women", "capacity", "see", "waiver", "paid", "lat", "lng")}
        body["start"] = start.isoformat(timespec="minutes")
        return self.add_meetup(uid, cid, body, now)

    def message_targets(self, uid: str, cid: Any, mid: Any, text: Any, now: datetime) -> tuple[str, list[str]]:
        """Admins message everyone going / on the waitlist for the next run (in-app + push).
        Returns the cleaned text and the user ids to tell (guests have no in-app inbox)."""
        self.require(uid)
        msg = clean(text, MESSAGE_LEN, "Message", required=True)
        d = self._doc.load()
        _, m = self._admin_run(d, cid, mid, uid)
        occ = next_occurrence(m, now.replace(tzinfo=None))
        day = (m.get("rsvps") or {}).get(occ.date().isoformat(), {}) if occ else {}
        return msg, [u for u, s in day.items() if u != uid and s in ("going", "maybe", "waitlist") and self._is_athlete(u)]

    def waiver_rows(self, uid: str, cid: Any, mid: Any) -> list[dict[str, Any]]:
        """Everyone who accepted this run's current waiver: ``{id, kind, name?, email?, at}``."""
        self.require(uid)
        d = self._doc.load()
        _, m = self._admin_run(d, cid, mid, uid)
        v = _digest(m.get("waiver") or "")
        rows = [{"id": u, "kind": "user", "at": w.get("at")} for u, w in (m.get("waivers") or {}).items()
                if w.get("v") == v]
        for key, gs in (m.get("guests") or {}).items():
            for gid, g in gs.items():
                if g.get("waiver_at"):
                    rows.append({"id": f"g:{gid}", "kind": "guest", "name": g.get("name"), "email": g.get("email"),
                                 "at": g.get("waiver_at"), "date": key})
        rows.sort(key=lambda r: r.get("at") or 0)
        return rows

    def dashboard(self, uid: str, cid: Any, now: datetime) -> dict[str, Any]:
        """Organizer dashboard: members, requests, upcoming runs with counts, and weekly
        attendance (going and checked in) over the last ``HISTORY_KEEP`` run dates."""
        self.require(uid)
        d = self._doc.load()
        c, role = self._role(d, cid, uid)
        if not self._admin(role):
            raise ClubError("Only the club's owner or admins can see the dashboard.", 403)
        local = now.replace(tzinfo=None)
        runs = []
        trend: dict[str, dict[str, int]] = {}
        for m in (c.get("meetups") or {}).values():
            v = self._meetup_view(m, uid, now, admin=True)
            if v["next"]:
                runs.append({k: v[k] for k in ("id", "title", "next", "count", "capacity", "waitlist", "see")})
            for k, h in (m.get("history") or {}).items():
                t = trend.setdefault(k, {"going": 0, "checkins": 0})
                t["going"] += int(h.get("going") or 0)
                t["checkins"] += int(h.get("checkins") or 0)
            for k, ck in (m.get("checkins") or {}).items():
                if k < local.date().isoformat():
                    t = trend.setdefault(k, {"going": 0, "checkins": 0})
                    t["checkins"] = max(t["checkins"], len(ck))
        runs.sort(key=lambda r: r["next"])
        dates = sorted(trend)[-HISTORY_KEEP:]
        return {"members": len(self._live(c)), "requests": len(c.get("requests") or {}),
                "runs": runs, "attendance": [{"date": k, **trend[k]} for k in dates],
                "link": self.public_link(c, d) if not self._private(c) else None}

    def report_run(self, uid: str, cid: Any, mid: Any, reason: Any) -> None:
        """Log a report on a run for the operator (shown nowhere else)."""
        self.require(uid)
        why = clean(reason, 200, "Reason") if isinstance(reason, str) else ""

        def apply(d: dict[str, Any]) -> None:
            c, m, _ = self._find_run(d, cid, mid, uid)
            r = d.setdefault("reports", [])
            r.append({"club": c["id"], "meetup": m["id"], "by": uid, "reason": why, "ts": int(self._clock())})
            del r[: max(0, len(r) - 500)]
        self._update(apply)

    # ------------------------------------------------- public link page --
    @staticmethod
    def _slugify(name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32].strip("-")
        return s or "club"

    def _ensure_slug(self, d: dict[str, Any], c: dict[str, Any]) -> str:
        slugs = d.setdefault("slugs", {})
        if c.get("slug") and slugs.get(c["slug"]) == c["id"]:
            return str(c["slug"])
        base = self._slugify(c["name"])
        s, n = base, 2
        while s in slugs and slugs[s] != c["id"]:
            s, n = f"{base}-{n}", n + 1
        slugs[s] = c["id"]
        c["slug"] = s
        return s

    def public_link(self, c: dict[str, Any], d: dict[str, Any] | None = None) -> str | None:
        return f"/c/{c['slug']}" if c.get("slug") else None

    def share_link(self, uid: str, cid: Any) -> str:
        """The club's public link page path (``/c/<slug>``); admins of public clubs only."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> str:
            c, role = self._role(d, cid, uid)
            if not self._admin(role):
                raise ClubError("Only the club's owner or admins can share the club page.", 403)
            if self._private(c):
                raise ClubError("Private clubs don't have a public page.")
            return f"/c/{self._ensure_slug(d, c)}"
        return self._update(apply)

    def by_slug(self, slug: Any) -> dict[str, Any] | None:
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", slug):
            return None
        d = self._doc.load()
        cid = (d.get("slugs") or {}).get(slug)
        c = (d.get("clubs") or {}).get(cid) if cid else None
        if c is None or self._private(c):
            return None
        return c

    def public_page(self, slug: Any, now: datetime, *, token: str | None = None, mid: str | None = None) -> dict[str, Any] | None:
        """What the public link page shows: the club and its public runs (or one run by its
        private link), with counts only, never names."""
        c = self.by_slug(slug)
        if c is None:
            return None
        local = now.replace(tzinfo=None)
        runs = []
        for m in (c.get("meetups") or {}).values():
            if mid is not None and m["id"] != mid:
                continue
            public = (m.get("see") or "club") == "public"
            linked = token is not None and secrets.compare_digest(str(m.get("token") or ""), str(token))
            if not (public or linked):
                continue
            occ = next_occurrence(m, local)
            if occ is None:
                continue
            v = self._meetup_view(m, "", now)
            runs.append({k: v[k] for k in ("id", "title", "next", "repeat", "where", "pace", "level", "notes",
                                           "groups", "walk", "beginner", "women", "capacity", "count",
                                           "spots_left", "waitlist", "waiver", "paid", "lat", "lng")})
        runs.sort(key=lambda r: r["next"])
        return {"id": c["id"], "slug": c.get("slug"), "name": c["name"], "emoji": c.get("emoji") or "🐇",
                "sport": c.get("sport") or "running", "city": c.get("city") or "", "state": c.get("state") or "",
                "description": c.get("description") or "", "members": len(self._live(c)), "runs": runs}

    def guest_rsvp(self, slug: Any, mid: Any, name: Any, email: Any, accept_waiver: bool, now: datetime,
                   *, token: str | None = None) -> dict[str, Any]:
        """RSVP from the public page without an account: name + email (contact for the
        organizers only). Returns ``{status, cancel}`` (the secret that cancels it)."""
        nm = clean(name, GUEST_NAME_LEN, "Name", required=True)
        em = clean(email, GUEST_EMAIL_LEN, "Email", required=True).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em):
            raise ClubError("Enter a real email so the organizers can reach you.")
        local = now.replace(tzinfo=None)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            cid = (d.get("slugs") or {}).get(slug) if isinstance(slug, str) else None
            c = (d.get("clubs") or {}).get(cid) if cid else None
            m = (c.get("meetups") or {}).get(mid) if c and isinstance(mid, str) else None
            if c is None or self._private(c) or m is None:
                raise ClubError("That run isn't open for sign-ups.", 404)
            linked = token is not None and secrets.compare_digest(str(m.get("token") or ""), str(token))
            if (m.get("see") or "club") != "public" and not linked:
                raise ClubError("That run isn't open for sign-ups.", 404)
            occ = next_occurrence(m, local)
            if occ is None:
                raise ClubError("That run already happened.", 404)
            key = occ.date().isoformat()
            self._prune(m, local)
            gs = m.setdefault("guests", {}).setdefault(key, {})
            if sum(len(x) for x in (m.get("guests") or {}).values()) >= MAX_GUESTS:
                raise ClubError("This run has too many sign-ups from the web. Join rabbt to RSVP.")
            for gid, g in gs.items():
                if g.get("email") == em and g.get("status") in ("going", "waitlist"):
                    return {"status": g["status"], "cancel": None, "date": key}
            if m.get("waiver") and not accept_waiver:
                raise ClubError("Read and accept the waiver to go.", 409)
            gid = secrets.token_hex(4)
            cancel = secrets.token_urlsafe(16)
            cap = m.get("capacity")
            status = "waitlist" if cap and self._going_count(m, key) >= cap else "going"
            gs[gid] = {"name": nm, "email": em, "status": status, "ts": int(self._clock()),
                       "cancel": _digest(cancel), "waiver_at": int(self._clock()) if m.get("waiver") else None}
            if status == "waitlist":
                m.setdefault("waitq", {}).setdefault(key, []).append(f"g:{gid}")
            return {"status": status, "cancel": f"{gid}.{cancel}", "date": key}
        return self._update(apply)

    def guest_cancel(self, slug: Any, mid: Any, secret: Any) -> str | None:
        """Cancel a guest RSVP by its secret; returns who moved up from the waitlist."""
        if not isinstance(secret, str) or "." not in secret or len(secret) > 80:
            raise ClubError("That cancel link isn't valid.", 404)
        gid, raw = secret.split(".", 1)

        def apply(d: dict[str, Any]) -> str | None:
            cid = (d.get("slugs") or {}).get(slug) if isinstance(slug, str) else None
            c = (d.get("clubs") or {}).get(cid) if cid else None
            m = (c.get("meetups") or {}).get(mid) if c and isinstance(mid, str) else None
            if m is None:
                raise ClubError("That cancel link isn't valid.", 404)
            for key, gs in (m.get("guests") or {}).items():
                g = gs.get(gid)
                if g and secrets.compare_digest(str(g.get("cancel")), _digest(raw)):
                    was = g.get("status")
                    del gs[gid]
                    q = (m.get("waitq") or {}).get(key) or []
                    if f"g:{gid}" in q:
                        q.remove(f"g:{gid}")
                    return self._promote(m, key) if was == "going" else None
            raise ClubError("That cancel link isn't valid.", 404)
        return self._update(apply)

    def nearby_runs(self, uid: str, now: datetime, *, city: str, state: str, hours: int = 36) -> list[dict[str, Any]]:
        """Runs starting in the next ``hours`` the viewer can join: their clubs' runs plus public
        runs of public clubs in their city (then state). ``club`` attached; soonest first."""
        local = now.replace(tzinfo=None)
        last = local + timedelta(hours=hours)
        city_l, state_l = city.strip().lower(), state.strip().lower()
        out = []
        for c in (self._doc.load().get("clubs") or {}).values():
            role = c["members"].get(uid)
            if role is None:
                if self._private(c) or self._blocked(uid, c["owner"]):
                    continue
                ccity, cstate = (c.get("city") or "").lower(), (c.get("state") or "").lower()
                near = (city_l and ccity == city_l) or (not city_l and state_l and cstate == state_l)
                if not near:
                    continue
            for m in (c.get("meetups") or {}).values():
                if role is None and (m.get("see") or "club") != "public":
                    continue
                if not self._run_visible(c, m, uid, role):
                    continue
                v = self._meetup_view(m, uid, now)
                if v["next"] and local - timedelta(hours=1) <= datetime.fromisoformat(v["next"]) <= last:
                    out.append({**v, "club": {"id": c["id"], "name": c["name"], "emoji": c.get("emoji") or "🐇",
                                              "member": role is not None}})
        out.sort(key=lambda m: m["next"])
        return out

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
