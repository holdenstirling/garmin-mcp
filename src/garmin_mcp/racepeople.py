"""Race people: who's racing, crewing, pacing or cheering at one of your races.

Per event (owner + event id) the athlete keeps a list of people, each with a role:

* ``racing``: a Rabbit friend racing it too. Accepting copies the race into their own
  Races (name, type, distance, date, location, url; priority B; notes "Racing with Ann")
  and links both events in a shared race group: "Racing together" (first names, photos,
  countdown, and grade / estimated finish only when that teammate opted in), a small group
  chat (participants only, <= ``MAX_MSGS``) and cheers.
* ``crew`` / ``pacer`` / ``spectator``: a Rabbit friend who follows the race (Races ->
  "Races you're following": countdown, the athlete's crew notes, a race-day banner with
  the official tracking link). Nothing goes into their training plan.
* ``coach``: only a coach already linked to the athlete (``coach_links``); listed, no invite.

Rabbit users can only be invited when there's an active follow edge in either direction
(checked again on accept and on every read, so unfollowing/blocking ends access). Invites
by email are enumeration-safe: the same answer whether or not the address is on Rabbit;
an address that isn't an eligible friend is kept as a "ghost" (shown to the inviter only
by the typed email, expires after ``GHOST_TTL``). Invites by code reveal no more than a
follow by code does.

People without Rabbit get a per-race share link (``/app/r/<token>``, one per race,
regenerable/revocable): a server-rendered, escaped, noindex page with the race, the
athlete's first name, countdown, crew notes, and (only when the athlete turns them on) the
estimated finish with a pace chart, the readiness grade letter and this week's training.
Never health data, never Oura, never chats.

Storage: global ``racepeople`` doc ``{"races": {"<owner>:<eid>": {owner, event_id, group,
people: {pid: person}, settings, token}}, "tokens": {token: key}, "groups": {gid: {members:
{uid: event_id}, created}}}`` and global ``racechat`` doc ``{gid: [message]}``. Deleting an
event (any path that writes the ``events`` doc, see ``sync``) drops its people, link and
group membership.
"""

from __future__ import annotations

import html
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from . import legal as _legal
from .appstore import AppStore

ROLES = ("racing", "crew", "pacer", "spectator", "coach")
FOLLOW_ROLES = ("crew", "pacer", "spectator")
ROLE_LABEL = {"racing": "racing", "crew": "crew", "pacer": "pace", "spectator": "cheer", "coach": "coach"}
GENERIC_SENT = "If they're a rabbt friend, they'll get your invite."
MAX_PEOPLE = 40
MAX_INVITES_PER_DAY = 30
GHOST_TTL = 30 * 86400
CREW_NOTES_LEN = 1000
MSG_LEN = 500
MAX_MSGS = 500
TOKEN_BYTES = 24
DEFAULT_SETTINGS: dict[str, Any] = {
    "show_finish": False, "show_grade": False, "show_week": False,  # share link
    "team_grade": False, "team_finish": False,  # teammates racing with you
    "crew_notes": "", "tracking_url": "",
}
COPY_FIELDS = ("name", "type", "distance", "date", "location", "url", "kind", "end_date", "time", "at")
CREW_KIT = ["Bib number, start time and wave", "Spare fuel and bottles they trained with",
            "Warm layer and dry clothes for the finish", "Phone charged + a battery pack",
            "Chairs, sunscreen, snacks and water for you", "Where and when to meet (see the plan above)"]
CREW_KIT_TRAIL = ["Drop bags labelled by aid station", "Headlamp + spare batteries for night legs",
                  "Spare shoes and socks, blister kit"]
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RaceError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _key(uid: str, eid: str) -> str:
    return f"{uid}:{eid}"


def _clean(text: Any, limit: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        raise RaceError("text expected")
    s = text.replace("\r\n", "\n").strip()
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s)
    if len(s) > limit:
        raise RaceError(f"Keep it under {limit} characters.")
    return s


class RacePeople:
    def __init__(self, store: AppStore, *, create_event: Callable[[str, dict[str, Any]], dict[str, Any]],
                 related: Callable[[str, str], bool], is_athlete: Callable[[str], bool],
                 athletes: Callable[[], dict[str, str]], code_owner: Callable[[str], str | None],
                 coach_emails: Callable[[str], set[str]], first_name: Callable[[str], str],
                 clock: Callable[[], float] = time.time) -> None:
        """``related(a, b)``: an active follow edge either way. ``athletes``: allowlist
        email -> user id. ``code_owner(code)``: social invite code -> user id."""
        self._s = store
        self._doc = store.global_doc("racepeople")
        self._chat = store.global_doc("racechat")
        self._create_event = create_event
        self._related = related
        self._is_athlete = is_athlete
        self._allow = athletes
        self._code_owner = code_owner
        self._coach_emails = coach_emails
        self._first = first_name
        self._clock = clock
        self._lock = threading.RLock()

    # ------------------------------------------------------------- helpers --
    def _events(self, uid: str) -> dict[str, Any]:
        return self._s.user_doc(uid, "events").load().get("events", {})

    def _event(self, uid: str, eid: Any) -> dict[str, Any]:
        ev = self._events(uid).get(eid) if isinstance(eid, str) else None
        if ev is None:
            raise RaceError("event not found", 404)
        return ev

    def _ok(self, a: str, b: str) -> bool:
        return a != b and self._is_athlete(a) and self._is_athlete(b) and self._related(a, b)

    @staticmethod
    def _race(d: dict[str, Any], owner: str, eid: str) -> dict[str, Any]:
        r = d.setdefault("races", {}).setdefault(_key(owner, eid), {})
        r.setdefault("owner", owner)
        r.setdefault("event_id", eid)
        r.setdefault("people", {})
        r.setdefault("group", None)
        r.setdefault("token", None)
        return r

    @staticmethod
    def _settings_of(r: dict[str, Any] | None) -> dict[str, Any]:
        stored = (r or {}).get("settings") or {}
        return {k: stored.get(k, v) for k, v in DEFAULT_SETTINGS.items()}

    def _find_person(self, d: dict[str, Any], pid: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
        if not isinstance(pid, str) or not _ID.match(pid):
            return None
        for r in (d.get("races") or {}).values():
            p = (r.get("people") or {}).get(pid)
            if p is not None:
                return r, p
        return None

    def _leave_group(self, d: dict[str, Any], gid: str | None, uid: str) -> None:
        if not gid:
            return
        g = (d.get("groups") or {}).get(gid)
        if not g:
            return
        eid = g["members"].pop(uid, None)
        if eid:
            mine = (d.get("races") or {}).get(_key(uid, eid))
            if mine and mine.get("group") == gid:
                mine["group"] = None
        if len(g["members"]) < 2:
            for other, oeid in g["members"].items():
                r = (d.get("races") or {}).get(_key(other, oeid))
                if r and r.get("group") == gid:
                    r["group"] = None
            del d["groups"][gid]
            self._chat.update(lambda c: c.pop(gid, None))

    def _drop_race(self, d: dict[str, Any], key: str) -> None:
        r = (d.get("races") or {}).pop(key, None)
        if r is None:
            return
        if r.get("token"):
            (d.get("tokens") or {}).pop(r["token"], None)
        self._leave_group(d, r.get("group"), r["owner"])  # teammates keep their own copy

    # ----------------------------------------------------------- the owner --
    def view(self, uid: str, eid: Any) -> dict[str, Any]:
        """People and settings for one of ``uid``'s races (raw; the caller adds names)."""
        ev = self._event(uid, eid)
        d = self._doc.load()
        r = (d.get("races") or {}).get(_key(uid, ev["id"])) or {}
        coaches = self._coach_emails(uid)
        now = self._clock()
        people = []
        for p in (r.get("people") or {}).values():
            if p["role"] == "coach":
                if p.get("coach_email") not in coaches:
                    continue
            elif p.get("user_id") and p["status"] == "accepted" and not self._ok(uid, p["user_id"]):
                continue
            elif p.get("user_id") is None and now - p.get("ts", now) > GHOST_TTL:
                continue
            show_id = p.get("user_id") if (p["status"] == "accepted" or p.get("via") != "email") else None
            people.append({"id": p["id"], "role": p["role"], "status": p["status"], "user_id": show_id,
                           "email": p.get("email") if p.get("via") == "email" else None,
                           "coach_email": p.get("coach_email"), "ts": p.get("ts")})
        people.sort(key=lambda x: (x["status"] != "accepted", ROLES.index(x["role"]), x.get("ts") or 0))
        return {"event_id": ev["id"], "people": people, "settings": self._settings_of(r),
                "token": r.get("token"), "group": r.get("group"),
                "coaches": sorted(coaches - {p["coach_email"] for p in people if p.get("coach_email")})}

    def summary(self, uid: str) -> dict[str, dict[str, Any]]:
        """Per event of ``uid``: accepted people (user ids first) for the "People" row."""
        out: dict[str, dict[str, Any]] = {}
        d = self._doc.load()
        for r in (d.get("races") or {}).values():
            if r.get("owner") != uid:
                continue
            accepted = [p for p in (r.get("people") or {}).values() if p["status"] == "accepted"
                        and (p["role"] == "coach" or (p.get("user_id") and self._ok(uid, p["user_id"])))]
            pending = sum(1 for p in (r.get("people") or {}).values() if p["status"] == "invited")
            team = [m for m in ((d.get("groups") or {}).get(r.get("group") or "", {}).get("members") or {}) if m != uid]
            ids = list(dict.fromkeys(team + [p["user_id"] for p in accepted if p.get("user_id")]))
            if ids or pending or accepted or r.get("token"):
                out[r["event_id"]] = {"user_ids": ids[:5], "count": len(set(ids)) + sum(1 for p in accepted if p["role"] == "coach"),
                                      "pending": pending, "racing": len(team), "link": bool(r.get("token"))}
        return out

    def invite(self, uid: str, eid: Any, *, role: Any, user_id: Any = None, email: Any = None,
               code: Any = None, coach_email: Any = None) -> dict[str, Any]:
        """Returns ``{"person", "notify", "by_email"}``. For an email invite the caller must
        answer with ``GENERIC_SENT`` whatever happened."""
        if role not in ROLES:
            raise RaceError("Pick a role: racing, crew, pacer, spectator or coach.")
        ev = self._event(uid, eid)
        # Server-local date (a day of slack for time zones) is enough to stop invites to old races.
        if ev.get("date") and date.fromisoformat(ev["date"]) < date.fromtimestamp(self._clock()) - timedelta(days=1):
            raise RaceError("That race is over.")
        target: str | None = None
        e_addr: str | None = None
        via: str
        c_email: str | None = None
        if role == "coach":
            c = str(coach_email or "").strip().lower()
            if not c or c not in self._coach_emails(uid):
                raise RaceError("Only coaches you've linked can be added as your coach.", 404)
            via, c_email = "coach", c
        elif isinstance(user_id, str) and user_id:
            if not self._ok(uid, user_id):
                raise RaceError("person not found", 404)
            via, target = "friend", user_id
        elif isinstance(code, str) and code.strip():
            target = self._code_owner(code.strip().upper().replace("-", "").replace(" ", ""))
            if not target or not self._is_athlete(target):
                raise RaceError("That code doesn't match anyone on rabbt.", 404)
            if target == uid:
                raise RaceError("That's you!")
            if not self._ok(uid, target):
                raise RaceError("You can invite friends you follow or who follow you.", 403)
            via = "code"
        elif isinstance(email, str) and email.strip():
            e_addr = email.strip().lower()
            if not _EMAIL.match(e_addr):
                raise RaceError("Enter an email address or an invite code.")
            t = {k.lower(): v for k, v in self._allow().items()}.get(e_addr)
            target = t if t and t != uid and self._ok(uid, t) else None
            via = "email"
        else:
            raise RaceError("Pick a friend, or enter an email or invite code.")
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            r = self._race(d, uid, ev["id"])
            people = r["people"]
            for p in people.values():
                same = (c_email and p.get("coach_email") == c_email) or \
                       (target and p.get("user_id") == target) or \
                       (not target and e_addr and p.get("user_id") is None and p.get("email") == e_addr)
                if same:
                    if p["status"] == "invited" and p["role"] != role and role != "coach":
                        p["role"] = role
                    return {"person": dict(p), "notify": None, "by_email": via == "email"}
            if len(people) >= MAX_PEOPLE:
                raise RaceError(f"Up to {MAX_PEOPLE} people per race.")
            today_n = sum(1 for x in (d.get("races") or {}).values() if x.get("owner") == uid
                          for p in (x.get("people") or {}).values() if now - p.get("ts", 0) < 86400)
            if today_n >= MAX_INVITES_PER_DAY:
                raise RaceError("That's a lot of invites today. Try again tomorrow.", 429)
            if target and role == "racing" and target in (((d.get("groups") or {}).get(r.get("group") or "") or {}).get("members") or {}):
                raise RaceError("They're already racing this with you.")
            p = {"id": "p" + secrets.token_hex(6), "user_id": target, "email": e_addr, "coach_email": c_email,
                 "role": role, "status": "accepted" if role == "coach" else "invited", "ts": now, "via": via,
                 "by": uid}
            people[p["id"]] = p
            return {"person": dict(p), "notify": target, "by_email": via == "email"}
        with self._lock:
            return self._doc.update(apply)

    def remove(self, uid: str, eid: Any, pid: Any) -> None:
        """The owner removes someone: their access ends now (a teammate keeps their own copy
        of the race, unlinked)."""
        ev = self._event(uid, eid)

        def apply(d: dict[str, Any]) -> None:
            r = (d.get("races") or {}).get(_key(uid, ev["id"]))
            p = (r or {}).get("people", {}).get(pid) if isinstance(pid, str) else None
            if p is None:
                raise RaceError("person not found", 404)
            del r["people"][pid]
            if p["role"] == "racing" and p["status"] == "accepted" and p.get("user_id"):
                self._leave_group(d, r.get("group"), p["user_id"])
        with self._lock:
            self._doc.update(apply)

    def put_settings(self, uid: str, eid: Any, patch: Any) -> dict[str, Any]:
        ev = self._event(uid, eid)
        if not isinstance(patch, dict):
            raise RaceError("settings must be an object")
        clean: dict[str, Any] = {}
        for k, v in patch.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k == "crew_notes":
                clean[k] = _clean(v, CREW_NOTES_LEN)
            elif k == "tracking_url":
                u = _clean(v, 300)
                if u and not re.match(r"^https://[^\s<>\"']+$", u):
                    raise RaceError("The tracking link must start with https://")
                clean[k] = u
            elif not isinstance(v, bool):
                raise RaceError(f"{k} must be true or false")
            else:
                clean[k] = v

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            r = self._race(d, uid, ev["id"])
            r["settings"] = {**self._settings_of(r), **clean}
            return dict(r["settings"])
        with self._lock:
            return self._doc.update(apply)

    # --------------------------------------------------------- share link --
    def share_create(self, uid: str, eid: Any) -> str:
        ev = self._event(uid, eid)
        token = secrets.token_urlsafe(TOKEN_BYTES)

        def apply(d: dict[str, Any]) -> str:
            r = self._race(d, uid, ev["id"])
            toks = d.setdefault("tokens", {})
            if r.get("token"):
                toks.pop(r["token"], None)
            r["token"] = token
            toks[token] = _key(uid, ev["id"])
            return token
        with self._lock:
            return self._doc.update(apply)

    def share_revoke(self, uid: str, eid: Any) -> None:
        ev = self._event(uid, eid)

        def apply(d: dict[str, Any]) -> None:
            r = (d.get("races") or {}).get(_key(uid, ev["id"]))
            if r and r.get("token"):
                (d.get("tokens") or {}).pop(r["token"], None)
                r["token"] = None
        with self._lock:
            self._doc.update(apply)

    def resolve(self, token: Any) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
        """A share token -> (owner, event, settings), or None (bad, revoked, event gone)."""
        if not isinstance(token, str) or not (20 <= len(token) <= 64):
            return None
        d = self._doc.load()
        key = None
        for t, k in (d.get("tokens") or {}).items():
            if secrets.compare_digest(t, token):
                key = k
        r = (d.get("races") or {}).get(key or "")
        if not r or r.get("token") is None or not secrets.compare_digest(r["token"], token):
            return None
        ev = self._events(r["owner"]).get(r["event_id"])
        if ev is None:
            return None
        return r["owner"], ev, self._settings_of(r)

    # ---------------------------------------------------------- the guest --
    def inbox(self, uid: str) -> list[dict[str, Any]]:
        """Pending invites to ``uid`` (still friends, race still on the calendar)."""
        out = []
        for r in (self._doc.load().get("races") or {}).values():
            for p in (r.get("people") or {}).values():
                if p.get("user_id") != uid or p["status"] != "invited" or not self._ok(uid, r["owner"]):
                    continue
                ev = self._events(r["owner"]).get(r["event_id"])
                if ev is None:
                    continue
                out.append({"id": p["id"], "role": p["role"], "from": r["owner"], "ts": p["ts"],
                            "event": {k: ev.get(k) for k in COPY_FIELDS}})
        out.sort(key=lambda x: x["ts"], reverse=True)
        return out

    def _match_own(self, uid: str, ev: dict[str, Any]) -> str | None:
        for e in self._events(uid).values():
            if e.get("date") == ev.get("date") and (e.get("name") or "").strip().lower() == (ev.get("name") or "").strip().lower():
                return str(e["id"])
        return None

    def respond(self, uid: str, pid: Any, accept: bool) -> dict[str, Any]:
        """Accept or decline an invite. Accepting "racing" copies the race into ``uid``'s
        Races and links both in a race group. Returns ``{"role", "owner", "event_id"?}``."""
        with self._lock:
            d = self._doc.load()
            got = self._find_person(d, pid)
            if got is None or got[1].get("user_id") != uid or got[1]["status"] != "invited":
                raise RaceError("invite not found", 404)
            r, p = got
            owner, oeid = r["owner"], r["event_id"]
            if not accept:
                def drop(d2: dict[str, Any]) -> None:
                    rr = (d2.get("races") or {}).get(_key(owner, oeid)) or {}
                    rr.get("people", {}).pop(pid, None)
                self._doc.update(drop)
                return {"role": p["role"], "owner": owner}
            if not self._ok(uid, owner):
                raise RaceError("invite not found", 404)
            oev = self._events(owner).get(oeid)
            if oev is None:
                raise RaceError("That race isn't on their calendar anymore.", 404)
            my_eid: str | None = None
            if p["role"] == "racing":
                my_eid = self._match_own(uid, oev)
                if my_eid is None:
                    fields = {k: oev.get(k) for k in COPY_FIELDS if oev.get(k) not in (None, "")}
                    fields |= {"priority": "B", "notes": f"Racing with {self._first(owner)}"}
                    try:
                        my_eid = str(self._create_event(uid, fields)["id"])
                    except ValueError as e:  # CoachError: too many events, bad field
                        raise RaceError(str(e)) from None
            now = int(self._clock())

            def apply(d2: dict[str, Any]) -> None:
                rr = (d2.get("races") or {}).get(_key(owner, oeid)) or {}
                pp = rr.get("people", {}).get(pid)
                if pp is None:
                    raise RaceError("invite not found", 404)
                pp["status"], pp["accepted"] = "accepted", now
                if my_eid is None:
                    return
                pp["linked_event"] = my_eid
                groups = d2.setdefault("groups", {})
                gid = rr.get("group")
                if not gid or gid not in groups:
                    gid = "g" + secrets.token_hex(8)
                    groups[gid] = {"members": {owner: oeid}, "created": now}
                    rr["group"] = gid
                mine = self._race(d2, uid, my_eid)
                if mine.get("group") and mine["group"] != gid:
                    self._leave_group(d2, mine["group"], uid)
                groups[gid]["members"][uid] = my_eid
                mine["group"] = gid
            self._doc.update(apply)
            return {"role": p["role"], "owner": owner, "event_id": my_eid}

    def following(self, uid: str) -> list[dict[str, Any]]:
        """Races ``uid`` crews, paces or cheers at (accepted, still friends)."""
        out = []
        for r in (self._doc.load().get("races") or {}).values():
            for p in (r.get("people") or {}).values():
                if p.get("user_id") != uid or p["status"] != "accepted" or p["role"] not in FOLLOW_ROLES:
                    continue
                if not self._ok(uid, r["owner"]):
                    continue
                ev = self._events(r["owner"]).get(r["event_id"])
                if ev is None:
                    continue
                s = self._settings_of(r)
                info = ev.get("info") or {}
                out.append({"id": p["id"], "role": p["role"], "owner": r["owner"],
                            "event": {k: ev.get(k) for k in COPY_FIELDS} | {"start_time": info.get("start_time") or ""},
                            "crew_notes": s["crew_notes"], "tracking_url": s["tracking_url"]})
        out.sort(key=lambda x: x["event"].get("date") or "")
        return out

    def leave(self, uid: str, pid: Any) -> None:
        """The guest stops following / racing (their own race copy stays theirs)."""
        def apply(d: dict[str, Any]) -> None:
            got = self._find_person(d, pid)
            if got is None or got[1].get("user_id") != uid:
                raise RaceError("not found", 404)
            r, p = got
            del r["people"][pid]
            if p["role"] == "racing" and p["status"] == "accepted":
                self._leave_group(d, r.get("group"), uid)
        with self._lock:
            self._doc.update(apply)

    def related_people(self, viewer: str, other: str) -> bool:
        """For photos: same race group, or one invited the other to a race."""
        if viewer == other:
            return True
        d = self._doc.load()
        for g in (d.get("groups") or {}).values():
            if viewer in g["members"] and other in g["members"]:
                return True
        for r in (d.get("races") or {}).values():
            if r.get("owner") in (viewer, other):
                guest = other if r["owner"] == viewer else viewer
                if any(p.get("user_id") == guest and (p["status"] == "accepted" or p.get("via") != "email")
                       for p in (r.get("people") or {}).values()):
                    return True
        return False

    # ------------------------------------------------------ racing together --
    def team(self, uid: str, eid: Any) -> dict[str, Any] | None:
        """``{"group", "members": [{user_id, event_id, settings}]}`` (others only), or None."""
        ev = self._event(uid, eid)
        d = self._doc.load()
        r = (d.get("races") or {}).get(_key(uid, ev["id"])) or {}
        g = (d.get("groups") or {}).get(r.get("group") or "")
        if not g or g["members"].get(uid) != ev["id"]:
            return None
        members = []
        for m, meid in g["members"].items():
            if m == uid or not self._is_athlete(m):
                continue
            mev = self._events(m).get(meid)
            if mev is None:
                continue
            mr = (d.get("races") or {}).get(_key(m, meid))
            members.append({"user_id": m, "event_id": meid, "date": mev.get("date"), "settings": self._settings_of(mr)})
        return {"group": r["group"], "members": members}

    def groups_of(self, uid: str) -> list[dict[str, Any]]:
        """Race groups ``uid`` is in (Community mirrors them): ``{id, members, name, date}``
        from ``uid``'s own copy of the race; members still athletes."""
        out = []
        evs = self._events(uid)
        for gid, g in ((self._doc.load().get("groups") or {}).items()):
            mine = (g.get("members") or {}).get(uid)
            ev = evs.get(mine) if mine else None
            if ev is None:
                continue
            members = [m for m in g["members"] if m == uid or self._is_athlete(m)]
            out.append({"id": gid, "members": members, "name": str(ev.get("name") or "Race")[:60],
                        "date": ev.get("date"), "event_id": ev.get("id")})
        return out

    def _group_for(self, uid: str, eid: Any) -> tuple[str, list[str]]:
        t = self.team(uid, eid)
        if t is None:
            raise RaceError("You're not racing this with anyone yet.", 404)
        return t["group"], [m["user_id"] for m in t["members"]]

    def messages(self, uid: str, eid: Any, after: int = 0) -> list[dict[str, Any]]:
        gid, _ = self._group_for(uid, eid)
        return [m for m in self._chat.load().get(gid, []) if m["ts"] > after or after <= 0]

    def post(self, uid: str, eid: Any, text: Any, *, kind: str = "msg") -> tuple[dict[str, Any], list[str]]:
        """Add a message (or a cheer) to the race group chat. Returns it and the others."""
        gid, others = self._group_for(uid, eid)
        if kind == "cheer":
            body = _clean(text, 140) if text else ""
        else:
            body = _clean(text, MSG_LEN)
            if not body:
                raise RaceError("Write something first.")
        msg = {"id": "m" + secrets.token_hex(6), "by": uid, "text": body, "kind": kind, "ts": int(self._clock())}

        def apply(c: dict[str, Any]) -> None:
            msgs = c.setdefault(gid, [])
            msgs.append(msg)
            if len(msgs) > MAX_MSGS:
                del msgs[: len(msgs) - MAX_MSGS]
        self._chat.update(apply)
        return msg, others

    # --------------------------------------------------------- clean-up --
    def sync(self, uid: str) -> None:
        """After ``uid``'s events doc changed: drop people, links and group membership of
        events that no longer exist."""
        d = self._doc.load()
        mine = [k for k, r in (d.get("races") or {}).items() if r.get("owner") == uid]
        in_groups = [gid for gid, g in (d.get("groups") or {}).items() if uid in g["members"]]
        if not mine and not in_groups:
            return
        have = set(self._events(uid))
        gone = [k for k in mine if d["races"][k]["event_id"] not in have]
        stale = [gid for gid in in_groups if d["groups"][gid]["members"][uid] not in have]
        if not gone and not stale:
            return

        def apply(d2: dict[str, Any]) -> None:
            for k in gone:
                self._drop_race(d2, k)
            for gid in stale:
                g = (d2.get("groups") or {}).get(gid)
                if g and g["members"].get(uid) not in have:
                    self._leave_group(d2, gid, uid)
        with self._lock:
            self._doc.update(apply)


# ------------------------------------------------------------- share page --
def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _hm(seconds: float) -> str:
    s = round(seconds)
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}" if h else f"{rem // 60} min"


def pace_rows(finish: dict[str, Any], distance_km: float | None, imperial: bool) -> list[tuple[str, str]]:
    """Crew pace chart from an estimate: triathlon legs (cumulative), else even-pace
    checkpoints at each quarter. ``(where, about when after the start)``."""
    est = finish.get("estimate") or {}
    mid = est.get("mid_s")
    if not mid:
        return []
    rows: list[tuple[str, str]] = []
    splits = finish.get("splits")
    if isinstance(splits, list) and splits:
        t = 0.0
        names = {"swim": "Out of the swim", "t1": "", "bike": "Off the bike", "t2": "", "run": "Finish"}
        for s in splits:
            t += float(s.get("mid_s") or 0)
            if names.get(s.get("leg"), ""):
                rows.append((names[s["leg"]], _hm(t)))
        return rows
    if distance_km and distance_km > 0:
        unit, k = ("mi", 1.609344) if imperial else ("km", 1.0)
        total = distance_km / k
        for q in (0.25, 0.5, 0.75):
            rows.append((f"{total * q:.1f} {unit}", _hm(mid * q)))
        rows.append((f"Finish ({total:.1f} {unit})", _hm(mid)))
    return rows


def render(first: str, event: dict[str, Any], settings: dict[str, Any], today: date, *,
           grade: str | None = None, finish: dict[str, Any] | None = None, distance_km: float | None = None,
           week: list[tuple[str, str]] | None = None, imperial: bool = False) -> str:
    """The crew page. Everything is escaped; only what the athlete turned on is passed in."""
    first = (first or "An athlete").split(" ")[0]
    name = event.get("name") or "Race"
    when = ""
    days = None
    if event.get("date"):
        dd = date.fromisoformat(event["date"])
        when = dd.strftime("%a %b %-d, %Y")
        days = (dd - today).days
    info = event.get("info") or {}
    sub = " · ".join(x for x in (when, event.get("location") or "", info.get("start_time") or "") if x)
    if days is None:
        count = ""
    elif days > 1:
        count = f"{days} days to go"
    elif days == 1:
        count = "Tomorrow!"
    elif days == 0:
        count = "Race day!"
    else:
        count = "Race done"
    parts = [f"<h1>{_e(first)} is racing {_e(name)}</h1>", f"<p class=sub>{_e(sub)}</p>",
             f"<p class=count>{_e(count)}</p>" if count else ""]
    track = settings.get("tracking_url") or ""
    link = track or (event.get("url") or "")
    if days == 0 and link.startswith("https://"):
        label = "Official live tracking" if track else "Race website"
        parts.append(f"<p class=banner>It's race day. rabbt has no live tracking; follow along on the "
                     f"<a href=\"{_e(link)}\" rel=\"noopener noreferrer nofollow\">{_e(label)}</a>.</p>")
    if settings.get("crew_notes"):
        parts.append(f"<h2>Crew notes from {_e(first)}</h2><p class=notes>{_e(settings['crew_notes'])}</p>")
    if finish and settings.get("show_finish"):
        est = finish.get("estimate") or {}
        txt = est.get("text") or finish.get("text") or ""
        rows = pace_rows(finish, distance_km, imperial)
        table = "".join(f"<tr><th>{_e(a)}</th><td>~{_e(b)}</td></tr>" for a, b in rows)
        parts.append(f"<h2>Estimated finish</h2><p><b>{_e(txt)}</b> <span class=sub>(a guide, not a promise)</span></p>"
                     + (f"<table>{table}</table><p class=sub>Time after the start, even pacing.</p>" if table else ""))
    if grade and settings.get("show_grade"):
        parts.append(f"<h2>Race readiness</h2><p>Grade <b>{_e(grade)}</b></p>")
    if week and settings.get("show_week"):
        rows_w = "".join(f"<tr><th>{_e(a)}</th><td>{_e(b)}</td></tr>" for a, b in week)
        parts.append(f"<h2>Training this week</h2><table>{rows_w}</table>")
    if link.startswith("https://") and days != 0:
        parts.append(f"<p><a href=\"{_e(link)}\" rel=\"noopener noreferrer nofollow\">"
                     f"{'Live tracking' if track else 'Race website'}</a></p>")
    if days is not None and 0 <= days <= 21:
        kit = CREW_KIT + (CREW_KIT_TRAIL if event.get("type") in ("trail", "mountaineering") else [])
        parts.append("<h2>Crew essentials</h2><ul>" + "".join(f"<li>{_e(k)}</li>" for k in kit) + "</ul>")
    body = "\n".join(p for p in parts if p)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name=robots content="noindex,nofollow">
<title>{_e(first)} · {_e(name)}</title>
<style>:root{{color-scheme:light dark;--a:#2f7d5b}}body{{margin:0;font:15px/1.45 system-ui,-apple-system,sans-serif;background:Canvas;color:CanvasText}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}}h1{{font-size:22px;margin:0 0 4px}}.sub{{color:GrayText;margin:0}}
.count{{font-size:18px;font-weight:600;color:var(--a);margin:12px 0 0}}.banner{{border:1px solid var(--a);border-radius:10px;padding:10px 12px}}
h2{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:GrayText;margin:24px 0 8px}}.notes{{white-space:pre-wrap}}
table{{width:100%;border-collapse:collapse}}th{{text-align:left;font-weight:600;white-space:nowrap;padding:8px 12px 8px 0;vertical-align:top;width:1%}}
td{{padding:8px 0}}tr{{border-bottom:1px solid color-mix(in srgb,CanvasText 12%,transparent)}}ul{{padding-left:18px}}a{{color:var(--a)}}
footer{{margin-top:32px;color:GrayText;font-size:12px}}</style></head>
<body><main>{body}
<footer>Shared from rabbt for {_e(first)}'s crew and family. {_e(first)} can turn this link off at any time.{_legal.FOOTER}</footer></main></body></html>"""


__all__ = [
    "CREW_KIT",
    "DEFAULT_SETTINGS",
    "FOLLOW_ROLES",
    "GENERIC_SENT",
    "ROLES",
    "RaceError",
    "RacePeople",
    "pace_rows",
    "render",
]
