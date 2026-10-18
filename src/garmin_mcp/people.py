"""Connected screens (people_web.py routes): person profiles, the notifications inbox, the
"Friends today" strip and "Who else is doing this?".

Everything reads existing sources through injected callables (no new Garmin calls):

* **Profile** (``profile``): visible when the viewer may already see the person somewhere
  (``related``: self, a follow edge either way, a shared club, a public post) or can message
  them without a request (mutual follow / shared circle). A block either way is a 404.
  Workouts only for the person themselves or someone who follows them, through
  ``SocialFeed.visible_items`` (their sharing settings: no heart rate, power, health data or
  location ever). City only with a follow edge or a shared club; public events only (the
  public-events index), never private ones.
* **Notifications** (``inbox``): DMs and message requests, follow requests, cheers and
  kudos on my workouts, new reactions/comments on my posts, club invites and race reminders
  (A/B races in the next 14 days, opening the race checklist). Read state is a per-user
  ``notif_seen`` doc of item keys (capped), so "mark all read" works without timestamps.
* **Friends today** (``friends_today``): people I follow who trained today (their visible
  workouts) and who race soon (their public events in the next 14 days).
* **Who else** (``also``): people I follow who did the same sport this week, and people I
  follow going to an event with the same name and date (public events).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

SEEN_MAX = 600
INBOX_MAX = 60
RACE_SOON_DAYS = 14


class PeopleError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())


class People:
    def __init__(self, store: Any, *, soc: Any, feed: Any, clubs: Any = None, dms: Any = None,
                 related: Callable[[str, str], bool], person: Callable[[str], dict[str, Any] | None],
                 name: Callable[[str], str], home: Callable[[str], dict[str, str]],
                 today: Callable[[str], date], public_events: Callable[[], dict[str, dict[str, Any]]] | None = None,
                 events: Callable[[str], list[dict[str, Any]]] | None = None,
                 post_unread: Callable[[str], dict[str, int]] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self.soc = soc
        self.feed = feed
        self.clubs = clubs
        self.dms = dms
        self._related = related
        self._person = person
        self._name = name
        self._home = home
        self._today = today
        self._pub = public_events or (lambda: {})
        self._events = events or (lambda uid: [])
        self._post_unread = post_unread or (lambda uid: {})
        self._clock = clock

    # ------------------------------------------------------------ access --
    def can_see(self, viewer: str, uid: str) -> bool:
        if viewer == uid:
            return True
        if self.soc.blocked_between(viewer, uid) or not self.soc.is_athlete(uid):
            return False
        if self._related(viewer, uid):
            return True
        try:
            return bool(self.dms is not None and self.dms.reachable(viewer, uid))
        except Exception:
            return False

    def _require(self, viewer: str, uid: str) -> None:
        if not self.can_see(viewer, uid):
            raise PeopleError("Person not found.", 404)

    def _shared_clubs(self, viewer: str, uid: str) -> list[dict[str, Any]]:
        if self.clubs is None:
            return []
        out = []
        mine = set(self.clubs.ids_of(viewer))
        for cid in self.clubs.ids_of(uid):
            if cid.startswith(("r-", "b-")):
                continue
            try:
                c = self.clubs.get(viewer, cid)
            except Exception:  # private and I'm not in it: not shown
                continue
            if c.get("visibility") == "private" and cid not in mine:
                continue
            out.append({"id": cid, "name": c.get("name") or "", "emoji": c.get("emoji") or "",
                        "sport": c.get("sport") or "", "members": c.get("members"), "shared": cid in mine})
        out.sort(key=lambda c: (not c["shared"], c["name"].lower()))
        return out[:8]

    def _public_races(self, uid: str, today: date) -> list[dict[str, Any]]:
        out = []
        for key, it in self._pub().items():
            if it.get("owner") != uid:
                continue
            d = str(it.get("date") or "")
            if d < today.isoformat():
                continue
            out.append({"key": key, "name": it.get("name") or "", "date": d, "type": it.get("type") or "",
                        "activity": it.get("activity") or "", "neighborhood": it.get("neighborhood") or ""})
        out.sort(key=lambda e: e["date"])
        return out[:6]

    # ----------------------------------------------------------- profile --
    def profile(self, viewer: str, uid: str) -> dict[str, Any]:
        self._require(viewer, uid)
        me = viewer == uid
        following = me or self.soc.follows(viewer, uid)
        follows_you = not me and self.soc.follows(uid, viewer)
        pending = False
        if not me and not following:
            try:
                pending = any(p.get("user_id") == uid for p in self.soc.people(viewer)["pending_out"])
            except Exception:
                pending = False
        clubs = self._shared_clubs(viewer, uid)
        today = self._today(viewer)
        workouts: list[dict[str, Any]] = []
        if following and self.feed is not None:
            try:
                workouts = list(self.feed.visible_items(viewer, uid))
            except Exception:
                workouts = []
        recent = [w for w in workouts if w.get("date", "") >= (today - timedelta(days=28)).isoformat()]
        km = sum(float(w.get("km") or 0) for w in recent)
        stats = {"workouts_4w": len(recent), "km_4w": round(km, 1) if any(w.get("km") for w in recent) else None,
                 "minutes_4w": sum(int(w.get("minutes") or 0) for w in recent) or None} if following else None
        close = me or following or follows_you or any(c["shared"] for c in clubs)
        city = ""
        if close:
            try:
                h = self._home(uid)
                city = ", ".join(x for x in (h.get("city"), h.get("state")) if x)
            except Exception:
                city = ""
        can_message = None if me else ("direct" if self.dms is not None and self.dms.reachable(viewer, uid) else "request")
        p = self._person(uid) or {"id": uid, "name": self._name(uid)}
        return {"person": p, "me": me, "city": city, "following": bool(following and not me),
                "follows_you": follows_you, "pending": pending, "can_message": can_message,
                "workouts": workouts[:10], "workouts_hidden": not following,
                "stats": stats, "clubs": clubs, "races": self._public_races(uid, today),
                "in_common": {"clubs": [c["name"] for c in clubs if c["shared"]]}}

    def follow(self, viewer: str, uid: str) -> dict[str, Any]:
        self._require(viewer, uid)
        if viewer == uid:
            raise PeopleError("That's you.")
        return self.soc.follow(viewer, code=self.soc.invite_code(uid))

    def unfollow(self, viewer: str, uid: str) -> None:
        self._require(viewer, uid)
        for e in self.soc.people(viewer)["following"]:
            if e.get("user_id") == uid:
                self.soc.unfollow(viewer, e["edge_id"])
                return
        for e in self.soc.people(viewer)["pending_out"]:
            if e.get("user_id") == uid:
                self.soc.unfollow(viewer, e["edge_id"])
                return

    def block(self, viewer: str, uid: str) -> None:
        if viewer == uid:
            raise PeopleError("That's you.")
        self.soc.block(viewer, uid)

    def report(self, viewer: str, uid: str, reason: Any) -> None:
        self._require(viewer, uid)
        text = " ".join(str(reason or "").split())[:300]
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            rows = d.setdefault("reports", [])
            rows.append({"by": viewer, "about": uid, "reason": text, "ts": now})
            del rows[:-500]
        self._s.global_doc("people-reports").update(apply)

    # ----------------------------------------------------- notifications --
    def _seen_doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, "notif_seen")

    def inbox(self, uid: str) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        today = self._today(uid)
        if self.dms is not None:
            try:
                dm = self.dms.list(uid)
                for c in dm["requests"]:
                    who = [self._name(m) for m in c["members"]][:3]
                    items.append({"key": f"dmreq:{c['id']}:{(c.get('last') or {}).get('ts')}", "kind": "dm_request",
                                  "title": f"{', '.join(who) or 'Someone'} wants to message you",
                                  "body": (c.get("last") or {}).get("preview") or "", "ts": (c.get("last") or {}).get("ts") or c.get("created") or 0,
                                  "person": self._person(c["members"][0]) if c["members"] else None,
                                  "open": {"k": "dm", "id": c["id"]}})
                for c in dm["convs"]:
                    if not c["unread"] or c["muted"]:
                        continue
                    who = c.get("name") or ", ".join(self._name(m) for m in c["members"][:3])
                    items.append({"key": f"dm:{c['id']}:{c['last']['ts']}", "kind": "dm", "title": f"New message from {who}",
                                  "body": c["last"]["preview"], "ts": c["last"]["ts"] or 0,
                                  "person": self._person(c["members"][0]) if len(c["members"]) == 1 else None,
                                  "open": {"k": "dm", "id": c["id"]}})
            except Exception:
                pass
        try:
            ppl = self.soc.people(uid)
            for e in ppl["pending_in"]:
                items.append({"key": f"follow:{e['edge_id']}", "kind": "follow_request",
                              "title": f"{self._name(e['user_id'])} wants to follow your training",
                              "body": "", "ts": e.get("ts") or 0, "edge_id": e["edge_id"],
                              "person": self._person(e["user_id"]), "open": {"k": "people"}})
            mine = {x["user_id"] for x in ppl["following"]} | {x.get("user_id") for x in ppl["pending_out"]}
            for e in ppl["followers"][:20]:
                items.append({"key": f"follower:{e['edge_id']}", "kind": "follower",
                              "title": f"{self._name(e['user_id'])} started following you", "body": "",
                              "ts": e.get("since") or 0, "person": self._person(e["user_id"]),
                              "follow_back": e["user_id"] not in mine,
                              "open": {"k": "person", "id": e["user_id"]}})
        except Exception:
            pass
        try:
            for aid, a in (self.soc.kudos_of(uid) or {}).items():
                for giver, ts in (a.get("by") or {}).items():
                    if giver != uid:
                        items.append({"key": f"kudos:{aid}:{giver}", "kind": "kudos",
                                      "title": f"{self._name(giver)} cheered your workout", "body": "",
                                      "ts": ts or 0, "person": self._person(giver), "open": {"k": "activity", "id": str(aid)}})
                for c in a.get("cheers") or []:
                    if c.get("by") != uid:
                        items.append({"key": f"cheer:{aid}:{c.get('id')}", "kind": "comment",
                                      "title": f"{self._name(c['by'])} commented on your workout",
                                      "body": str(c.get("text") or "")[:140], "ts": c.get("ts") or 0,
                                      "person": self._person(c["by"]), "open": {"k": "activity", "id": str(aid)}})
        except Exception:
            pass
        try:
            for pid, n in (self._post_unread(uid) or {}).items():
                if isinstance(n, int) and n > 0:
                    items.append({"key": f"post:{pid}:{n}", "kind": "post",
                                  "title": f"{n} new reaction{'s' if n != 1 else ''} or comment{'s' if n != 1 else ''} on your post",
                                  "body": "", "ts": self._clock(), "person": None, "open": {"k": "feed"}})
        except Exception:
            pass
        if self.clubs is not None:
            try:
                for c in self.clubs.overview(uid)["invites"]:
                    items.append({"key": f"clubinv:{c['id']}", "kind": "club_invite",
                                  "title": f"{self._name(c.get('invited_by') or '')} invited you to {c['name']}",
                                  "body": c.get("description") or "", "ts": self._clock(),
                                  "person": self._person(c["invited_by"]) if c.get("invited_by") else None,
                                  "open": {"k": "club", "id": c["id"]}})
            except Exception:
                pass
        try:
            for e in self._events(uid):
                d = str(e.get("date") or "")
                if not d:
                    continue
                try:
                    days = (date.fromisoformat(d) - today).days
                except ValueError:
                    continue
                if 0 <= days <= RACE_SOON_DAYS and (e.get("priority") in ("A", "B") or e.get("type") == "race"):
                    window = "week" if days <= 7 else "2wk"
                    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
                    items.append({"key": f"race:{e['id']}:{window}", "kind": "race",
                                  "title": f"{e.get('name') or 'Your race'} is {when}",
                                  "body": "Check your race checklist.", "ts": self._clock() - days,
                                  "person": None, "open": {"k": "checklist", "id": e["id"]}})
        except Exception:
            pass
        seen = set(self._seen_doc(uid).load().get("keys") or [])
        for it in items:
            it["unread"] = it["key"] not in seen
        items.sort(key=lambda x: (x["unread"], float(x.get("ts") or 0)), reverse=True)
        items = items[:INBOX_MAX]
        return {"items": items, "unread": sum(1 for it in items if it["unread"])}

    def mark_read(self, uid: str, keys: list[str] | None = None) -> int:
        if keys is None:
            keys = [it["key"] for it in self.inbox(uid)["items"]]
        keys = [k for k in keys if isinstance(k, str) and len(k) <= 200]

        def apply(d: dict[str, Any]) -> int:
            cur = [k for k in (d.get("keys") or []) if k not in keys] + keys
            d["keys"] = cur[-SEEN_MAX:]
            return len(keys)
        return self._seen_doc(uid).update(apply)

    # ----------------------------------------------------- friends today --
    def friends_today(self, uid: str) -> dict[str, Any]:
        today = self._today(uid)
        trained: list[dict[str, Any]] = []
        following = list(self.soc.following_ids(uid))
        if self.feed is not None:
            for f in following[:60]:
                try:
                    items = [w for w in self.feed.visible_items(uid, f) if w.get("date") == today.isoformat()]
                except Exception:
                    continue
                if items:
                    kudos = (self.soc.kudos_of(f) or {}).get(items[0]["id"]) or {}
                    trained.append({"person": self._person(f), "workout": items[0], "count": len(items),
                                    "kudos": len(kudos.get("by") or {}),
                                    "you_cheered": uid in (kudos.get("by") or {})})
        trained.sort(key=lambda r: r["workout"].get("time") or "", reverse=True)
        soon: list[dict[str, Any]] = []
        fset = set(following)
        last = (today + timedelta(days=RACE_SOON_DAYS)).isoformat()
        for key, it in self._pub().items():
            if it.get("owner") in fset and today.isoformat() <= str(it.get("date") or "") <= last:
                soon.append({"person": self._person(it["owner"]), "key": key, "name": it.get("name") or "",
                             "date": it.get("date"), "activity": it.get("activity") or ""})
        soon.sort(key=lambda r: r["date"])
        return {"today": today.isoformat(), "trained": trained[:12], "racing": soon[:6]}

    # ---------------------------------------------------------- who else --
    def also(self, uid: str, *, sport: str | None = None, day: str | None = None,
             event_name: str | None = None, event_date: str | None = None) -> dict[str, Any]:
        today = self._today(uid)
        try:
            ref = date.fromisoformat(day) if day else today
        except ValueError:
            raise PeopleError("bad date") from None
        monday = ref - timedelta(days=ref.weekday())
        sunday = monday + timedelta(days=6)
        same: list[dict[str, Any]] = []
        following = list(self.soc.following_ids(uid))
        if sport and self.feed is not None:
            for f in following[:60]:
                try:
                    hits = [w for w in self.feed.visible_items(uid, f)
                            if _fam(w.get("sport")) == _fam(sport) and monday.isoformat() <= w.get("date", "") <= sunday.isoformat()]
                except Exception:
                    continue
                if hits:
                    same.append({"person": self._person(f), "workout": hits[0], "count": len(hits)})
        going: list[dict[str, Any]] = []
        if event_name and event_date:
            fset = set(following) | set(self.soc.follower_ids(uid))
            for key, it in self._pub().items():
                if it.get("owner") in fset and it.get("owner") != uid and str(it.get("date")) == event_date \
                        and _norm(it.get("name")) == _norm(event_name):
                    going.append({"person": self._person(it["owner"]), "key": key})
        return {"same_sport": same[:8], "same_event": going[:12]}


def _fam(sport: Any) -> str:
    """A sport's family, so a plan's "run" matches Garmin's "trail_running" or "treadmill_running"."""
    s = str(sport or "").lower()
    for fam, keys in (("run", ("run",)), ("bike", ("cycl", "bik", "ride", "spin")), ("swim", ("swim",)),
                      ("walk", ("walk", "hik")), ("strength", ("strength", "weight"))):
        if any(k in s for k in keys):
            return fam
    return s


__all__ = ["People", "PeopleError"]
