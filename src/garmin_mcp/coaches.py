"""Human coaches: an athlete invites a coach by email; the coach signs in with Google and
sees the athletes who invited them.

Security model
--------------
* The athlete is in control. Only the athlete adds or removes a coach and sets what the
  coach may do: ``can_edit_plan`` (edit sessions in the built plan) and
  ``can_see_rabbit_chats`` (read-only view of the athlete's Rabbit chats; off by default).
* A coach's identity is their verified Google email. A coach who isn't an allowlisted
  athlete gets a stable user id derived from the email (``coach_<hash>``) and can sign in
  only while at least one athlete has an invite out to that email. Removing the last
  link revokes access on the next request (``WebAuth.user_for`` re-checks).
* Every coach API call resolves the athlete id from the URL and checks it against the
  coach's links (``require``); nothing is taken on trust from the request body.

Storage
-------
* Global ``coach_links`` doc: ``{"by_email": {email: {athlete_id: link}}}``; link =
  ``{"email", "status": "invited"|"active", "can_edit_plan", "can_see_rabbit_chats",
  "invited_at", "accepted_at", "coach_user_id"}``.
* Per athlete ``coach_chat``: message threads between athlete and coach, general or tied
  to one planned session; and ``coach_notes``: notes a coach keeps on the athlete
  (``shared`` ones are visible to the athlete and to Rabbit; ``event_id`` makes one a race
  note, shown in that race's Race fit view).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore
from .coaching import CoachError

MAX_COACHES = 5
MAX_THREADS = 200
MAX_MESSAGES = 500
MAX_NOTES = 300
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


def coach_user_id(email: str) -> str:
    return "coach_" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def _clean(v: Any, limit: int, field: str) -> str:
    if not isinstance(v, str):
        raise CoachError(f"{field} must be text")
    v = v.strip()
    if not v:
        raise CoachError(f"{field} can't be empty")
    return v[:limit]


class CoachLinks:
    def __init__(self, store: AppStore, *, athlete_emails: Callable[[], dict[str, str]],
                 clock: Callable[[], float] = time.time) -> None:
        """``athlete_emails``: the allowlist, email -> athlete user id."""
        self._s = store
        self._doc = store.global_doc("coach_links")
        self._allow = athlete_emails
        self._clock = clock
        self._lock = threading.Lock()

    # ------------------------------------------------------------ identity --
    def _athletes(self) -> set[str]:
        """User ids of allowlisted athletes: only their links count."""
        return set(self._allow().values())

    def _live(self, links: dict[str, Any]) -> dict[str, Any]:
        ok = self._athletes()
        return {aid: link for aid, link in links.items() if aid in ok}

    def user_id_for_email(self, email: str) -> str | None:
        """Sign-in: the user id for a coach email with at least one live invite, else None."""
        e = email.strip().lower()
        if not self._live(self._doc.load().get("by_email", {}).get(e, {})):
            return None
        return self._allow().get(e) or coach_user_id(e)

    def is_coach_user(self, user_id: str) -> bool:
        """True while some allowlisted athlete still links this coach-only user id."""
        if not user_id.startswith("coach_"):
            return False
        return any(coach_user_id(e) == user_id and self._live(links)
                   for e, links in self._doc.load().get("by_email", {}).items())

    def _emails_for(self, user_id: str) -> list[str]:
        allow = self._allow()
        out = []
        for e in self._doc.load().get("by_email", {}):
            if allow.get(e) == user_id or coach_user_id(e) == user_id:
                out.append(e)
        return out

    # ------------------------------------------------------- athlete side --
    def coach_emails(self, athlete_id: str) -> set[str]:
        return {e for e, links in self._doc.load().get("by_email", {}).items() if athlete_id in links}

    def coaches_of(self, athlete_id: str) -> list[dict[str, Any]]:
        out = []
        for e, links in self._doc.load().get("by_email", {}).items():
            link = links.get(athlete_id)
            if link:
                out.append(dict(link, email=e))
        return sorted(out, key=lambda x: x.get("invited_at", 0))

    def invite(self, athlete_id: str, email: str, *, can_edit_plan: bool = True,
               can_see_rabbit_chats: bool = False) -> dict[str, Any]:
        e = email.strip().lower() if isinstance(email, str) else ""
        if athlete_id not in self._athletes():
            raise CoachError("Only athletes can invite coaches.")
        if not _EMAIL.match(e):
            raise CoachError("Enter your coach's email address.")
        if self._allow().get(e) == athlete_id:
            raise CoachError("That's your own email.")
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            by = d.setdefault("by_email", {})
            mine = sum(1 for links in by.values() if athlete_id in links)
            links = by.setdefault(e, {})
            if athlete_id not in links and mine >= MAX_COACHES:
                raise CoachError(f"You can have up to {MAX_COACHES} coaches.")
            link = links.get(athlete_id) or {"status": "invited", "invited_at": now, "accepted_at": None}
            link.update(email=e, can_edit_plan=bool(can_edit_plan),
                        can_see_rabbit_chats=bool(can_see_rabbit_chats))
            links[athlete_id] = link
            return dict(link)
        with self._lock:
            return self._doc.update(apply)

    def update(self, athlete_id: str, email: str, patch: dict[str, Any]) -> dict[str, Any]:
        e = str(email).strip().lower()

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            link = d.get("by_email", {}).get(e, {}).get(athlete_id)
            if link is None:
                raise CoachError("coach not found")
            for k in ("can_edit_plan", "can_see_rabbit_chats"):
                if k in patch:
                    if not isinstance(patch[k], bool):
                        raise CoachError(f"{k} must be true or false")
                    link[k] = patch[k]
            return dict(link)
        with self._lock:
            return self._doc.update(apply)

    def remove(self, athlete_id: str, email: str) -> None:
        e = str(email).strip().lower()

        def apply(d: dict[str, Any]) -> None:
            by = d.get("by_email", {})
            if by.get(e, {}).pop(athlete_id, None) is None:
                raise CoachError("coach not found")
            if not by[e]:
                by.pop(e)
        with self._lock:
            self._doc.update(apply)

    # --------------------------------------------------------- coach side --
    def athletes_of(self, coach_id: str) -> list[dict[str, Any]]:
        """Athletes linked to this coach (marks invites active on first look)."""
        emails = self._emails_for(coach_id)
        if not emails:
            return []
        now = int(self._clock())

        live = self._athletes()

        def apply(d: dict[str, Any]) -> list[dict[str, Any]]:
            out = []
            for e in emails:
                for aid, link in d.get("by_email", {}).get(e, {}).items():
                    if aid not in live:
                        continue
                    if link.get("status") != "active":
                        link["status"], link["accepted_at"] = "active", now
                    link["coach_user_id"] = coach_id
                    out.append(dict(link, athlete_id=aid, email=e))
            return out
        with self._lock:
            return self._doc.update(apply)

    def require(self, coach_id: str, athlete_id: str, *, perm: str | None = None) -> dict[str, Any]:
        """The coach's link to this athlete, or CoachError. ``perm``: a permission flag
        that must be on."""
        if not isinstance(athlete_id, str) or not athlete_id or athlete_id == coach_id \
                or athlete_id not in self._athletes():
            raise CoachError("athlete not found")
        by = self._doc.load().get("by_email", {})
        for e in self._emails_for(coach_id):
            link = by.get(e, {}).get(athlete_id)
            if link:
                if perm and not link.get(perm):
                    raise CoachError("Your athlete hasn't given you access to that.")
                return dict(link, email=e)
        raise CoachError("athlete not found")


# ------------------------------------------------------------------- chat ---
class CoachChat:
    """Athlete <-> coach messages, per athlete. ``coach`` is the coach's email."""

    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, athlete_id: str):
        return self._s.user_doc(athlete_id, "coach_chat")

    def threads(self, athlete_id: str, coach: str | None = None) -> list[dict[str, Any]]:
        ts = self._doc(athlete_id).load().get("threads", {}).values()
        out = []
        for t in ts:
            if coach and t["coach"] != coach:
                continue
            last = t["messages"][-1] if t["messages"] else None
            out.append({k: t.get(k) for k in ("id", "coach", "title", "session_id", "session_date",
                                              "event_id", "created", "updated", "read")}
                       | {"last": last, "count": len(t["messages"])})
        return sorted(out, key=lambda x: x["updated"], reverse=True)

    def thread(self, athlete_id: str, thread_id: str, coach: str | None = None) -> dict[str, Any]:
        t = self._doc(athlete_id).load().get("threads", {}).get(thread_id)
        if t is None or (coach and t["coach"] != coach):
            raise CoachError("conversation not found")
        return t

    def open_thread(self, athlete_id: str, coach: str, *, session: dict[str, Any] | None = None,
                    event: dict[str, Any] | None = None, title: str | None = None) -> dict[str, Any]:
        """The general thread with this coach, the thread for one planned session
        (``session``: {"id", "date", "title"}) or for one race (``event``: {"id", "title"},
        e.g. "<race> strategy"; the caller checks the event is the athlete's); created on
        first use."""
        now = int(self._clock())
        if session and event:
            raise CoachError("A conversation is about a session or a race, not both.")
        sid, eid = (session or {}).get("id"), (event or {}).get("id")

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            ts = d.setdefault("threads", {})
            for t in ts.values():
                if t["coach"] == coach and t.get("session_id") == sid and t.get("event_id") == eid:
                    return t
            if len(ts) >= MAX_THREADS:
                # Only an empty thread may make room; conversations are never dropped.
                empty = [t for t in ts.values() if not t["messages"]]
                if not empty:
                    raise CoachError("Too many conversations. Delete an old one first.")
                ts.pop(min(empty, key=lambda t: t["updated"])["id"])
            tid = "c" + secrets.token_hex(6)
            t = {"id": tid, "coach": coach, "created": now, "updated": now, "messages": [],
                 "read": {"athlete": None, "coach": None},  # last message id each side has seen
                 "title": (title or (f"{session['title']} · {session['date']}" if session
                                     else event["title"] if event else "General"))[:80],
                 "session_id": sid, "session_date": (session or {}).get("date"), "event_id": eid}
            ts[tid] = t
            return t
        return self._doc(athlete_id).update(apply)

    def post(self, athlete_id: str, thread_id: str, *, sender: str, text: Any,
             coach: str | None = None) -> dict[str, Any]:
        """``sender``: "athlete" or "coach". ``coach`` (coach side): must own the thread."""
        body = _clean(text, 4000, "message")
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            t = d.get("threads", {}).get(thread_id)
            if t is None or (coach and t["coach"] != coach):
                raise CoachError("conversation not found")
            msg = {"id": "m" + secrets.token_hex(6), "from": sender, "text": body, "ts": now}
            t["messages"] = (t["messages"] + [msg])[-MAX_MESSAGES:]
            t["updated"] = now
            t.setdefault("read", {})[sender] = msg["id"]
            return msg
        return self._doc(athlete_id).update(apply)

    def mark_read(self, athlete_id: str, thread_id: str, who: str, coach: str | None = None) -> None:
        def apply(d: dict[str, Any]) -> None:
            t = d.get("threads", {}).get(thread_id)
            if t is not None and (not coach or t["coach"] == coach) and t["messages"]:
                t.setdefault("read", {})[who] = t["messages"][-1]["id"]
        self._doc(athlete_id).update(apply)

    def unread(self, athlete_id: str, who: str, coach: str | None = None) -> int:
        n = 0
        other = "coach" if who == "athlete" else "athlete"
        for t in self._doc(athlete_id).load().get("threads", {}).values():
            if coach and t["coach"] != coach:
                continue
            seen = (t.get("read") or {}).get(who)
            ids = [m["id"] for m in t["messages"]]
            start = ids.index(seen) + 1 if seen in ids else 0
            n += sum(1 for m in t["messages"][start:] if m["from"] == other)
        return n


# ------------------------------------------------------------------ notes ---
class CoachNotes:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._clock = clock

    def _doc(self, athlete_id: str):
        return self._s.user_doc(athlete_id, "coach_notes")

    def list(self, athlete_id: str, *, coach: str | None = None, shared_only: bool = False) -> list[dict[str, Any]]:
        notes = self._doc(athlete_id).load().get("notes", [])
        out = [n for n in notes if (not shared_only or n.get("shared")) and
               (coach is None or n["coach"] == coach or n.get("shared"))]
        return sorted(out, key=lambda n: (not n.get("pinned"), -n["ts"]))

    def add(self, athlete_id: str, coach: str, text: Any, *, shared: bool = True,
            pinned: bool = False, event_id: str | None = None) -> dict[str, Any]:
        """``event_id``: a race note, tied to one of the athlete's events (the caller checks
        that the event is the athlete's)."""
        note = {"id": "n" + secrets.token_hex(6), "coach": coach, "text": _clean(text, 2000, "note"),
                "shared": bool(shared), "pinned": bool(pinned), "ts": int(self._clock())}
        if event_id:
            note["event_id"] = event_id

        def apply(d: dict[str, Any]) -> None:
            notes = d.setdefault("notes", [])
            if len(notes) >= MAX_NOTES:
                raise CoachError(f"Up to {MAX_NOTES} notes per athlete. Delete old ones first.")
            notes.append(note)
        self._doc(athlete_id).update(apply)
        return note

    def for_event(self, athlete_id: str, event_id: str, coaches: set[str]) -> list[dict[str, Any]]:
        """Shared race notes for one event from the athlete's current coaches."""
        return [n for n in self.list(athlete_id, shared_only=True)
                if n.get("event_id") == event_id and n["coach"] in coaches]

    def update(self, athlete_id: str, coach: str, note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        def apply(d: dict[str, Any]) -> dict[str, Any]:
            for n in d.get("notes", []):
                if n["id"] == note_id and n["coach"] == coach:
                    if "text" in patch:
                        n["text"] = _clean(patch["text"], 2000, "note")
                    for k in ("shared", "pinned"):
                        if k in patch:
                            n[k] = bool(patch[k])
                    return dict(n)
            raise CoachError("note not found")
        return self._doc(athlete_id).update(apply)

    def delete(self, athlete_id: str, coach: str, note_id: str) -> None:
        def apply(d: dict[str, Any]) -> None:
            notes = d.get("notes", [])
            keep = [n for n in notes if not (n["id"] == note_id and n["coach"] == coach)]
            if len(keep) == len(notes):
                raise CoachError("note not found")
            d["notes"] = keep
        self._doc(athlete_id).update(apply)


__all__ = ["CoachLinks", "CoachChat", "CoachNotes", "coach_user_id", "MAX_COACHES"]
