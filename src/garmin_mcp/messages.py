"""Direct messages between athletes (alongside Rabbit chat): 1:1 and small group conversations.

Who can message whom
--------------------
* Athletes only (never ``coach_`` accounts: coaches have their own coach<->athlete messaging).
* Blocked either way: never. A conversation with someone you blocked (or who blocked you)
  disappears for both and can't be written to.
* "Reachable" = mutual follow, or members of the same Rabbit club / race group / training block,
  or the same feed group. Anyone else gets a **message request**: the conversation shows up in
  their Requests until they accept (then it's a normal chat) or decline (the sender is never told;
  further messages are dropped silently).

Storage (encrypted, like every app doc)
---------------------------------------
* Global ``dm-index``: ``{"convs": {cid: {id, kind: direct|group, name, owner, created,
  members: [uid], state: {uid: {status: active|request|declined|left, read, muted}},
  last: {ts, by, preview}}}}``.
* Per conversation ``dm-<cid>``: ``{"msgs": [{id, by, ts, text, att?, reactions: {emoji: [uid]}}]}``
  capped at ``MAX_KEEP`` (oldest dropped).

Shared cards
------------
A workout or event is shared as a **snapshot** taken at send time from the sender's own data
(``card_for``): sport, title, date, distance, time and pace for workouts; name, date, time,
neighbourhood and type for events. Never heart rate, location, health or Oura data. Recipients
only ever see the snapshot; the full page link works for the owner only (``mine``).
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from .appstore import AppStore

MAX_TEXT = 2000
MAX_GROUP = 12            # people in a conversation, including you
CLUB_CHAT_MAX = 200       # a club's group chat (linked to the club, not started by hand)
MAX_KEEP = 2000           # messages kept per conversation
PAGE = 40                 # messages per page
MAX_CONVS = 300           # conversations a person can be in
SEND_PER_MIN = 30
SEND_PER_DAY = 600
NEW_PER_DAY = 30          # new conversations a person can start per day
NAME_LEN = 40
REACTIONS = ("👍", "❤️", "🔥", "😂", "👏", "💪")
_CID = re.compile(r"^[a-z0-9]{8,24}$")
_MID = re.compile(r"^[A-Za-z0-9_-]{6,24}$")
_UID = re.compile(r"^[A-Za-z0-9_.@+-]{1,80}$")


class DMError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def valid_cid(cid: Any) -> str:
    if not isinstance(cid, str) or not _CID.fullmatch(cid):
        raise DMError("Conversation not found.", 404)
    return cid


def clean_text(v: Any) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise DMError("Message must be text.")
    t = v.replace("\r\n", "\n").strip()
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", t)
    if len(t) > MAX_TEXT:
        raise DMError(f"Messages can be up to {MAX_TEXT} characters.")
    return t


def preview_of(text: str, att: dict[str, Any] | None) -> str:
    if text:
        one = " ".join(text.split())
        return one[:80] + ("…" if len(one) > 80 else "")
    if att:
        if att.get("type") == "workout":
            return f"Shared a workout: {att.get('title') or 'Workout'}"[:80]
        if att.get("type") == "event":
            return f"Shared an event: {att.get('name') or 'Event'}"[:80]
    return ""


class Messages:
    def __init__(self, store: AppStore, *, is_athlete: Callable[[str], bool],
                 follows: Callable[[str, str], bool], blocked: Callable[[str, str], bool],
                 shared_circle: Callable[[str, str], bool] | None = None,
                 card_for: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._index = store.global_doc("dm-index")
        self._is_athlete = is_athlete
        self._follows = follows
        self._blocked = blocked
        self._circle = shared_circle or (lambda a, b: False)
        self._card_for = card_for or (lambda uid, ref: None)
        self._clock = clock
        self._lock = threading.Lock()
        self._sends: dict[str, list[float]] = {}
        self._starts: dict[str, list[float]] = {}

    # ------------------------------------------------------------ helpers --
    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            raise DMError("Messages are for athletes on Rabbit.", 403)

    def reachable(self, a: str, b: str) -> bool:
        """No request needed: mutual follow, or a club / group in common."""
        if a == b or not self._is_athlete(b) or self._blocked(a, b):
            return False
        return (self._follows(a, b) and self._follows(b, a)) or bool(self._circle(a, b))

    def _msgs(self, cid: str):
        return self._store.global_doc(f"dm-{cid}")

    def _rate(self, bucket: dict[str, list[float]], uid: str, per_min: int | None, per_day: int) -> None:
        now = self._clock()
        ts = [t for t in bucket.get(uid, []) if now - t < 86400]
        if len(ts) >= per_day or (per_min is not None and sum(1 for t in ts if now - t < 60) >= per_min):
            raise DMError("You're sending a lot right now. Try again in a minute.", 429)
        ts.append(now)
        bucket[uid] = ts

    def _visible(self, c: dict[str, Any], uid: str) -> bool:
        st = (c.get("state") or {}).get(uid) or {}
        if uid not in c["members"] or st.get("status") in ("left", "declined"):
            return False
        # Any block between you and another member hides a 1:1 entirely.
        if c["kind"] == "direct":
            other = next((m for m in c["members"] if m != uid), None)
            if other is None or self._blocked(uid, other) or not self._is_athlete(other):
                return False
        return True

    def _conv(self, uid: str, cid: Any) -> dict[str, Any]:
        cid = valid_cid(cid)
        c = (self._index.load().get("convs") or {}).get(cid)
        if c is None or not self._visible(c, uid):
            raise DMError("Conversation not found.", 404)
        return c

    def _view(self, c: dict[str, Any], uid: str) -> dict[str, Any]:
        st = c.get("state") or {}
        me = st.get(uid) or {}
        others = [m for m in c["members"] if m != uid and (st.get(m) or {}).get("status") != "left"
                  and not self._blocked(uid, m) and self._is_athlete(m)]
        last = c.get("last") or {}
        unread = bool(last.get("ts") and last.get("by") != uid and last["ts"] > float(me.get("read") or 0))
        pending_for = [m for m in others if (st.get(m) or {}).get("status") == "request"]
        return {"id": c["id"], "kind": c["kind"], "name": c.get("name") or "", "members": others,
                "owner": c.get("owner") == uid, "status": me.get("status") or "active", "muted": bool(me.get("muted")),
                "last": {"ts": last.get("ts"), "mine": last.get("by") == uid, "preview": last.get("preview") or ""} if last else None,
                "unread": unread, "waiting_on": pending_for, "created": c.get("created")}

    # --------------------------------------------------------------- reads --
    def list(self, uid: str) -> dict[str, Any]:
        self.require(uid)
        convs = [c for c in (self._index.load().get("convs") or {}).values() if self._visible(c, uid)]
        convs.sort(key=lambda c: (c.get("last") or {}).get("ts") or c.get("created") or 0, reverse=True)
        views = [self._view(c, uid) for c in convs]
        chats = [v for v in views if v["status"] == "active"]
        requests = [v for v in views if v["status"] == "request"]
        return {"convs": chats, "requests": requests,
                "unread": sum(1 for v in chats if v["unread"] and not v["muted"]) + len(requests)}

    def unread(self, uid: str) -> int:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            return 0
        return int(self.list(uid)["unread"])

    def messages(self, uid: str, cid: Any, *, before: Any = None) -> dict[str, Any]:
        self.require(uid)
        c = self._conv(uid, cid)
        msgs = self._msgs(c["id"]).load().get("msgs") or []
        if before is not None:
            try:
                b = float(before)
            except (TypeError, ValueError):
                raise DMError("bad cursor") from None
            msgs = [m for m in msgs if m["ts"] < b]
        page = msgs[-PAGE:]
        out = [self._msg_view(m, uid) for m in page]
        self.mark_read(uid, c["id"])
        return {"conv": self._view(self._conv(uid, c["id"]), uid), "msgs": out, "more": len(msgs) > len(page)}

    @staticmethod
    def _msg_view(m: dict[str, Any], uid: str) -> dict[str, Any]:
        att = m.get("att")
        if att:
            att = dict(att)
            att["mine"] = m["by"] == uid  # only the owner's app links to the full page
            if not att["mine"]:
                att.pop("ref", None)
        return {"id": m["id"], "by": m["by"], "mine": m["by"] == uid, "ts": m["ts"], "text": m.get("text") or "",
                "att": att, "reactions": {e: {"n": len(us), "mine": uid in us}
                                          for e, us in (m.get("reactions") or {}).items() if us}}

    # -------------------------------------------------------------- writes --
    def _clean_people(self, uid: str, to: Any) -> list[str]:
        if isinstance(to, str):
            to = [to]
        if not isinstance(to, list) or not to:
            raise DMError("Pick who to message.")
        out: list[str] = []
        for p in to:
            if not isinstance(p, str) or not _UID.fullmatch(p) or p == uid:
                raise DMError("Pick people on Rabbit.")
            if p not in out:
                out.append(p)
        if len(out) + 1 > MAX_GROUP:
            raise DMError(f"A group chat can have up to {MAX_GROUP} people.")
        for p in out:
            if not self._is_athlete(p) or self._blocked(uid, p):
                raise DMError("You can't message that person.", 404)
        return out

    def start(self, uid: str, to: Any, *, name: Any = None) -> dict[str, Any]:
        """Open (or reuse) a conversation. 1:1 with the same person reuses the existing chat."""
        self.require(uid)
        people = self._clean_people(uid, to)
        nm = ""
        if name is not None:
            if not isinstance(name, str):
                raise DMError("Group name must be text.")
            nm = " ".join(name.split())[:NAME_LEN]
        now = self._clock()

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            convs = d.setdefault("convs", {})
            if len(people) == 1:
                for c in convs.values():
                    if c["kind"] == "direct" and set(c["members"]) == {uid, people[0]}:
                        st = c.setdefault("state", {})
                        mine = st.setdefault(uid, {})
                        if mine.get("status") in ("left", "declined", None):
                            mine["status"] = "active"
                        return c, False
            if sum(1 for c in convs.values() if uid in c["members"]) >= MAX_CONVS:
                raise DMError("You're in a lot of conversations. Leave some first.", 409)
            cid = secrets.token_hex(8)
            state = {uid: {"status": "active", "read": now}}
            for p in people:
                state[p] = {"status": "active" if self.reachable(uid, p) else "request", "read": 0}
            c = {"id": cid, "kind": "direct" if len(people) == 1 else "group", "name": nm if len(people) > 1 else "",
                 "owner": uid, "created": now, "members": [uid, *people], "state": state, "last": None}
            convs[cid] = c
            return c, True

        with self._lock:
            # Rate-limit new conversations only (reusing a chat is free).
            existing = len(people) == 1 and any(
                c["kind"] == "direct" and set(c["members"]) == {uid, people[0]}
                for c in (self._index.load().get("convs") or {}).values())
            if not existing:
                self._rate(self._starts, uid, None, NEW_PER_DAY)
            c, _new = self._index.update(apply)
        return self._view(c, uid)

    def club_chat(self, uid: str, club_id: str, name: str, members: list[str]) -> dict[str, Any]:
        """The club's group chat (one per club, created on first open): every current member,
        up to ``CLUB_CHAT_MAX``; members who joined later are added when they open it."""
        self.require(uid)
        if uid not in members:
            raise DMError("Join the club to see its chat.", 404)
        people = [m for m in dict.fromkeys(members) if isinstance(m, str) and _UID.fullmatch(m)
                  and self._is_athlete(m)][:CLUB_CHAT_MAX]
        nm = " ".join(str(name or "Club chat").split())[:NAME_LEN]
        now = self._clock()

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            convs = d.setdefault("convs", {})
            c = next((c for c in convs.values() if c.get("club_id") == club_id), None)
            if c is None:
                cid = secrets.token_hex(8)
                c = {"id": cid, "kind": "group", "club_id": club_id, "name": nm, "owner": uid, "created": now,
                     "members": [uid] + [m for m in people if m != uid], "state": {}, "last": None}
                convs[cid] = c
            st = c.setdefault("state", {})
            for m in people:
                if m not in c["members"] and len(c["members"]) < CLUB_CHAT_MAX:
                    c["members"].append(m)
            for m in c["members"]:
                cur = st.setdefault(m, {"status": "active", "read": 0 if m != uid else now})
                if m == uid and cur.get("status") in ("left", "declined", "request"):
                    cur["status"] = "active"
            c["name"] = nm
            return c
        with self._lock:
            c = self._index.update(apply)
        return self._view(c, uid)

    def _attachment(self, uid: str, att: Any) -> dict[str, Any] | None:
        if att is None:
            return None
        if not isinstance(att, dict) or att.get("type") not in ("workout", "event"):
            raise DMError("You can share a workout or an event.")
        ref = att.get("ref")
        if not isinstance(ref, dict):
            raise DMError("Pick what to share.")
        card = self._card_for(uid, {"type": att["type"], **ref})
        if not card:
            raise DMError("That isn't available to share.", 404)
        return {"type": att["type"], **card, "ref": {k: v for k, v in ref.items() if k in ("kind", "id", "date")}}

    def send(self, uid: str, cid: Any, text: Any, att: Any = None) -> tuple[dict[str, Any], list[str]]:
        """Returns (message view, people to notify)."""
        self.require(uid)
        c = self._conv(uid, cid)
        st = c.get("state") or {}
        if (st.get(uid) or {}).get("status") == "request":
            raise DMError("Accept the request to reply.", 409)
        body = clean_text(text)
        card = self._attachment(uid, att)
        if not body and not card:
            raise DMError("Write a message first.")
        self._rate(self._sends, uid, SEND_PER_MIN, SEND_PER_DAY)
        now = self._clock()
        msg = {"id": secrets.token_urlsafe(8), "by": uid, "ts": now, "text": body, "reactions": {}}
        if card:
            msg["att"] = card

        def add(d: dict[str, Any]) -> None:
            msgs = d.setdefault("msgs", [])
            msgs.append(msg)
            if len(msgs) > MAX_KEEP:
                del msgs[: len(msgs) - MAX_KEEP]

        def bump(d: dict[str, Any]) -> list[str]:
            cc = (d.get("convs") or {}).get(c["id"])
            if cc is None:
                raise DMError("Conversation not found.", 404)
            cc["last"] = {"ts": now, "by": uid, "preview": preview_of(body, card)}
            sts = cc.setdefault("state", {})
            sts.setdefault(uid, {})["read"] = now
            notify = []
            for m in cc["members"]:
                s = sts.get(m) or {}
                if m == uid or self._blocked(uid, m) or s.get("status") in ("left", "declined"):
                    continue
                if not s.get("muted"):
                    notify.append(m)
            return notify

        with self._lock:
            self._msgs(c["id"]).update(add)
            notify = self._index.update(bump)
        return self._msg_view(msg, uid), notify

    def react(self, uid: str, cid: Any, mid: Any, emoji: Any) -> dict[str, Any]:
        self.require(uid)
        c = self._conv(uid, cid)
        if not isinstance(mid, str) or not _MID.fullmatch(mid):
            raise DMError("Message not found.", 404)
        if emoji not in REACTIONS:
            raise DMError("Pick a reaction.")

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            m = next((x for x in d.get("msgs") or [] if x["id"] == mid), None)
            if m is None:
                raise DMError("Message not found.", 404)
            us = m.setdefault("reactions", {}).setdefault(emoji, [])
            if uid in us:
                us.remove(uid)
            else:
                us.append(uid)
            return m

        with self._lock:
            m = self._msgs(c["id"]).update(apply)
        return self._msg_view(m, uid)

    def _set_state(self, uid: str, cid: Any, **kv: Any) -> dict[str, Any]:
        self.require(uid)
        c = self._conv(uid, cid)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            cc = d["convs"][c["id"]]
            cc.setdefault("state", {}).setdefault(uid, {}).update(kv)
            return cc

        with self._lock:
            cc = self._index.update(apply)
        return cc

    def mark_read(self, uid: str, cid: Any) -> None:
        self._set_state(uid, cid, read=self._clock())

    def accept(self, uid: str, cid: Any) -> dict[str, Any]:
        c = self._conv(uid, cid)
        if ((c.get("state") or {}).get(uid) or {}).get("status") != "request":
            return self._view(c, uid)
        return self._view(self._set_state(uid, cid, status="active", read=self._clock()), uid)

    def decline(self, uid: str, cid: Any) -> None:
        c = self._conv(uid, cid)
        if ((c.get("state") or {}).get(uid) or {}).get("status") != "request":
            raise DMError("There's no request to decline.", 409)
        self._set_state(uid, cid, status="declined")

    def mute(self, uid: str, cid: Any, muted: Any) -> dict[str, Any]:
        if not isinstance(muted, bool):
            raise DMError("muted must be true or false")
        return self._view(self._set_state(uid, cid, muted=muted), uid)

    def leave(self, uid: str, cid: Any) -> None:
        self._set_state(uid, cid, status="left")

    def set_name(self, uid: str, cid: Any, name: Any) -> dict[str, Any]:
        self.require(uid)
        c = self._conv(uid, cid)
        if c["kind"] != "group":
            raise DMError("Only group chats have names.")
        if not isinstance(name, str):
            raise DMError("Group name must be text.")
        nm = " ".join(name.split())[:NAME_LEN]

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            d["convs"][c["id"]]["name"] = nm
            return d["convs"][c["id"]]

        with self._lock:
            return self._view(self._index.update(apply), uid)

    def report(self, uid: str, cid: Any, mid: Any, reason: Any) -> None:
        """Stored for the owner to review; nothing is sent to the reported person."""
        self.require(uid)
        c = self._conv(uid, cid)
        why = reason.strip()[:300] if isinstance(reason, str) else ""
        snap = None
        if isinstance(mid, str) and _MID.fullmatch(mid):
            m = next((x for x in self._msgs(c["id"]).load().get("msgs") or [] if x["id"] == mid), None)
            if m is not None:
                snap = {"id": m["id"], "by": m["by"], "ts": m["ts"], "text": (m.get("text") or "")[:500]}

        def apply(d: dict[str, Any]) -> None:
            rs = d.setdefault("reports", [])
            rs.append({"by": uid, "conv": c["id"], "msg": snap, "reason": why, "ts": self._clock()})
            del rs[:-500]

        with self._lock:
            self._store.global_doc("dm-reports").update(apply)

    def people(self, uid: str, candidates: list[str], q: Any = None) -> list[str]:
        """Who you can message without a request, from ``candidates`` (follows + club mates)."""
        self.require(uid)
        return [p for p in dict.fromkeys(candidates) if p != uid and self.reachable(uid, p)]
