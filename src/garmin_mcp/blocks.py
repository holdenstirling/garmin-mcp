"""Shared training blocks: friends (or a club) start the same N-week block together.

A block is a template (``TEMPLATES``: 8-week 5K build, 12-week half marathon, 12-week 70.3
base, 6-week consistency) or "our race" (one of the owner's races: everyone's plan targets the
same race date), a start Monday and its members. Every member trains on their OWN plan:

* ``plan: "new"``: the existing plan builder builds a plan for the template (or the race) from
  the member's own profile numbers, on the block's Monday-Sunday weeks (a template plan is a
  longer build cut to the block's weeks, so a "base" block is all base/build). It becomes a new
  active goal; the previous goal is archived (kept, restorable) and its Garmin workouts are
  handed over like any goal switch. When the member already has an active goal, this needs
  ``confirm_replace: true``; without it the call answers 409 ``{code: "confirm_plan"}`` and
  nothing changes. Never a silent overwrite.
* ``plan: "keep"``: join with the plan (or no plan) they already have; the block counts their
  own planned sessions (else workouts), like the home week ring. An "our race" block still
  copies the race onto their calendar (a same name + date event is reused).

Who: the owner invites mutual friends (an active follow edge both ways, re-checked on accept),
or opens the block to one of their clubs (club admins; members join without an invite). Blocks
(social) either way hide people from each other, stop invites and joins. Caps: ``MAX_MEMBERS``
per block, ``MAX_ACTIVE`` active blocks per athlete. Athletes only (coach accounts 403).

The block page shows week N of M, each member's sessions done/planned this week (nothing else:
no HR, health or Oura), a shared group ring, the block feed (Community posts to ``club:b-<id>``,
see ``clubs.Clubs.block_groups``) and the weekly check-in. A member's numbers are published by
their own reads/ticks (``publish``), so the block page never reads friends' Garmin.

Moments (``tick``, from ``Moments.on_tick``; quiet hours, the daily cap, dedupe and the push
toggle are ``Moments.post``'s): Sunday from ``CHECKIN_FROM`` one "How did week 3 go?" per
member and block (one-tap feel + optional note on the page, shown to the group); Monday from
``RECAP_FROM`` a recap "4 of 5 of you closed week 3". Nudge: one tap cheers a member who hasn't
closed their week, at most once a day per pair; the push to the cheered member is coalesced
(``COALESCE_S``) and never sent in their quiet hours.

Leave anytime (your plan stays yours; an owner who leaves hands the block to the longest
member); the owner can end it. Storage: global ``blocks`` doc ``{"blocks": {id: block}}``.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from .appstore import AppStore
from .planbuilder import PlanError, build_plan, iter_sessions

MAX_MEMBERS = 12
MAX_ACTIVE = 3
MAX_INVITES = 11          # per call
NAME_LEN = 40
NOTE_LEN = 140
START_AHEAD_WEEKS = 8     # a block starts at most this far out
KEEP_WEEKS = 6            # progress / check-ins kept per block
ENDED_KEEP_DAYS = 30
CHEERS_KEEP = 20
COALESCE_S = 3600         # one cheer push per person per hour; later cheers ride the next one
TICK_EVERY_S = 600
CHECKIN_FROM = dtime(15, 0)   # Sunday afternoon
RECAP_FROM = dtime(8, 0)      # Monday morning
FEELS = {"strong": "💪 Strong", "okay": "🙂 Okay", "tough": "😮‍💨 Tough"}
QUIET_START, QUIET_END = 21, 7
_ID = re.compile(r"^[0-9a-f]{12}$")
_UID = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# id -> name, weeks, builder distance, horizon weeks (a longer build cut to ``weeks``), race-day title
TEMPLATES: dict[str, dict[str, Any]] = {
    "5k_8": {"name": "8-week 5K build", "weeks": 8, "distance": "5k", "horizon": 8,
             "race_title": "5K time trial", "blurb": "Speed and a 5K time trial to finish"},
    "half_12": {"name": "12-week half marathon", "weeks": 12, "distance": "half marathon", "horizon": 12,
                "race_title": "Half marathon day", "blurb": "Long runs that build to 13.1"},
    "tri_base_12": {"name": "12-week 70.3 base", "weeks": 12, "distance": "70.3", "horizon": 28,
                    "race_title": "70.3", "blurb": "Swim, bike, run aerobic base"},
    "consistency_6": {"name": "6-week consistency", "weeks": 6, "distance": "other", "horizon": 20,
                      "race_title": "Consistency", "blurb": "Show up, week after week"},
}
RACE = "race"


class BlockError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400, code: str | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra or {}

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.message}
        if self.code:
            out["code"] = self.code
        return out | self.extra


def _clean(v: Any, limit: int, what: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BlockError(f"{what} must be text")
    s = " ".join(_CTRL.sub("", v).split())
    if len(s) > limit:
        raise BlockError(f"Keep the {what.lower()} under {limit} characters.")
    return s


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_info(block: dict[str, Any], today: date) -> dict[str, Any]:
    """``n`` (0 before the start, capped at ``of``), ``of``, this Monday, ``state``
    upcoming | active | done."""
    start = date.fromisoformat(block["start"])
    of = int(block["weeks"])
    if today < start:
        return {"n": 0, "of": of, "monday": start.isoformat(), "state": "upcoming",
                "days_to_start": (start - today).days}
    n = (today - start).days // 7 + 1
    state = "done" if n > of else "active"
    return {"n": min(n, of), "of": of, "monday": monday_of(today).isoformat(), "state": state}


def quiet(local: datetime) -> bool:
    return local.hour >= QUIET_START or local.hour < QUIET_END


def template_dates(tpl: dict[str, Any], start: date) -> tuple[date, date]:
    """(block end Sunday, the horizon "race" date the builder plans toward)."""
    end = start + timedelta(weeks=int(tpl["weeks"])) - timedelta(days=1)
    horizon = start + timedelta(weeks=int(tpl["horizon"])) - timedelta(days=1)
    return end, horizon


def template_plan(athlete: dict[str, Any], goal: dict[str, Any], tpl: dict[str, Any], start: date,
                  today: date, *, name: str, events: list[dict[str, Any]] | None = None,
                  block_id: str = "", clock: float | None = None) -> dict[str, Any]:
    """The member's own plan for a template block: ``build_plan`` toward the template's
    horizon from the block's (or this) Monday, cut to the block's weeks. Same weeks for
    everyone; volume, paces and days come from the member's profile."""
    end, horizon = template_dates(tpl, start)
    first = max(start, today)
    g = {**goal, "date": horizon.isoformat(), "title": tpl["race_title"], "distance": tpl["distance"]}
    plan = build_plan(athlete, g, today=today, start=first, events=events)
    plan["weeks"] = [w for w in plan["weeks"] if w["start"] <= end.isoformat()]
    if not plan["weeks"]:
        raise PlanError("This block has already finished.")
    for i, w in enumerate(plan["weeks"], start=1):
        w["index"] = i
        w["days"] = {d: ss for d, ss in w["days"].items() if d <= end.isoformat()}
    plan["race_date"] = end.isoformat()
    plan["events"] = [e for e in plan.get("events") or [] if str(e.get("date") or "") <= end.isoformat()]
    plan["block_id"] = block_id
    plan["origin"] = {"kind": "block", "by_name": name[:60], "at": int(clock if clock is not None else time.time()),
                      "source": "block", "name": name[:60]}
    return plan


class PlanHooks:
    """Builds and installs a member's own plan through the existing plan builder services
    (``coaching.CoachStore``, ``plans.PlanService``, ``events.EventStore``)."""

    def __init__(self, *, coach: Any, plans: Any, events: Any, now: Callable[[str], datetime],
                 clock: Callable[[], float] = time.time) -> None:
        self.coach, self.plans, self.events, self._now, self._clock = coach, plans, events, now, clock

    def current(self, uid: str) -> dict[str, Any]:
        g = self.coach.active_goal(uid)
        plan = self.plans.get(uid) if g else None
        has = bool(plan and any(True for _ in iter_sessions(plan))) or bool(g and g.get("plan"))
        return {"goal": (g or {}).get("title"), "has_plan": has, "has_goal": g is not None}

    def copy_event(self, uid: str, ev: dict[str, Any], *, priority: str) -> str:
        """The shared race on the member's calendar (a same name + date event is reused)."""
        for e in self.events.list(uid):
            if e.get("date") == ev.get("date") and (e.get("name") or "").strip().lower() == (ev.get("name") or "").strip().lower():
                return str(e["id"])
        fields = {k: ev[k] for k in ("name", "type", "distance", "date", "location", "url") if ev.get(k)}
        return str(self.events.create(uid, fields | {"priority": priority})["id"])

    def install(self, uid: str, block: dict[str, Any], mode: str) -> str:
        today = self._now(uid).date()
        start = date.fromisoformat(block["start"])
        ev = block.get("event")
        if mode == "keep":
            if ev:
                self.copy_event(uid, ev, priority="B")
            return "kept"
        if ev:  # our race: a goal for the shared race, built by the builder from this Monday on
            eid = self.copy_event(uid, ev, priority="A")
            self.plans.switch_goal(uid, lambda: self.coach.create_goal(uid, {"title": ev["name"][:80], "priority": "A"}))
            self.events.set_main(uid, eid)
            self.plans.build(uid, start=max(start, today).isoformat())
            return "built"
        tpl = TEMPLATES[block["template"]]
        goal = self.plans.switch_goal(uid, lambda: self.coach.create_goal(
            uid, {"title": block["name"][:80], "distance": tpl["distance"], "target": "Shared block"}))
        plan = template_plan(self.coach.athlete(uid), goal, tpl, start, today, name=block["name"],
                             events=self.events.plan_events(uid), block_id=block["id"], clock=self._clock())
        self.plans.install(uid, goal, plan)
        return "built"


Moment = Callable[[str, dict[str, Any]], Any]


class Blocks:
    def __init__(self, store: AppStore, *, now: Callable[[str], datetime],
                 is_athlete: Callable[[str], bool], follows: Callable[[str, str], bool],
                 blocked: Callable[[str, str], bool], names: Callable[[str], str],
                 week: Callable[[str, date], tuple[int, int] | None],
                 plan: PlanHooks | Any,
                 events: Callable[[str], list[dict[str, Any]]] = lambda uid: [],
                 club_member: Callable[[str, str], bool] = lambda cid, uid: False,
                 club_admin: Callable[[str, str], bool] = lambda cid, uid: False,
                 club_name: Callable[[str, str], str | None] = lambda cid, uid: None,
                 moment: Moment | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        """``week(uid, day)``: (done, planned) for the Monday-Sunday week containing ``day``
        from the member's own plan + Garmin (``weekring.ring``), None when unreadable."""
        self._doc = store.global_doc("blocks")
        self._now = now
        self._is_athlete = is_athlete
        self._follows = follows
        self._blocked = blocked
        self._names = names
        self._week = week
        self.plan = plan
        self._events = events
        self._club_member = club_member
        self._club_admin = club_admin
        self._club_name = club_name
        self.moment = moment
        self._clock = clock
        self._lock = threading.RLock()
        self._ticked: dict[str, float] = {}
        self._pushed: dict[str, float] = {}

    # ------------------------------------------------------------ helpers --
    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_athlete(uid):
            raise BlockError("Training blocks are for athletes on rabbt.", 403)

    def _today(self, uid: str) -> date:
        return self._now(uid).date()

    def _update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            return self._doc.update(fn)

    def _all(self) -> dict[str, dict[str, Any]]:
        return self._doc.load().get("blocks") or {}

    def mutual(self, a: str, b: str) -> bool:
        return (a != b and self._is_athlete(a) and self._is_athlete(b) and not self._blocked(a, b)
                and self._follows(a, b) and self._follows(b, a))

    @staticmethod
    def _live(b: dict[str, Any], today: date) -> bool:
        return b.get("status") == "active" and b["end"] >= today.isoformat()

    def _active_count(self, uid: str, today: date, blocks: dict[str, dict[str, Any]]) -> int:
        return sum(1 for b in blocks.values() if uid in b["members"] and self._live(b, today))

    def _get(self, d: dict[str, Any], bid: Any) -> dict[str, Any]:
        b = (d.get("blocks") or {}).get(bid) if isinstance(bid, str) and _ID.match(bid) else None
        if b is None:
            raise BlockError("Block not found.", 404)
        return b

    def _can_join(self, uid: str, b: dict[str, Any]) -> bool:
        """Invited by someone who's still a mutual friend, or a member of the block's club."""
        if self._blocked(uid, b["owner"]):
            return False
        inv = (b.get("invited") or {}).get(uid)
        if inv and self.mutual(uid, inv["by"]) and inv["by"] in b["members"]:
            return True
        return bool(b.get("club")) and self._club_member(b["club"], uid)

    def _prune(self, d: dict[str, Any], today: date) -> None:
        cut = (today - timedelta(days=ENDED_KEEP_DAYS)).isoformat()
        blocks = d.setdefault("blocks", {})
        for k in [k for k, b in blocks.items() if b["end"] < cut or (b.get("ended_on") or "9") < cut]:
            del blocks[k]

    # ------------------------------------------------------------- templates --
    def templates(self, uid: str) -> dict[str, Any]:
        """Templates + the athlete's upcoming races ("our race") + suggested start Mondays."""
        today = self._today(uid)
        nxt = monday_of(today) + timedelta(days=7)
        races = []
        for e in self._events(uid):
            if (e.get("kind") or "race") != "race" or not e.get("date"):
                continue
            try:
                d = date.fromisoformat(e["date"])
            except ValueError:
                continue
            weeks = (monday_of(d) - nxt).days // 7 + 1
            if 2 <= weeks <= 52:
                races.append({"id": e["id"], "name": e.get("name") or "Race", "date": e["date"],
                              "distance": e.get("distance") or "", "weeks": weeks})
        races.sort(key=lambda r: r["date"])
        return {"templates": [{"id": k, "name": t["name"], "weeks": t["weeks"], "blurb": t["blurb"]}
                              for k, t in TEMPLATES.items()],
                "races": races[:10],
                "starts": [(nxt + timedelta(weeks=i)).isoformat() for i in range(4)],
                "max_members": MAX_MEMBERS, "max_active": MAX_ACTIVE}

    def _start(self, raw: Any, today: date) -> date:
        try:
            start = date.fromisoformat(str(raw))
        except ValueError:
            raise BlockError("Pick a start Monday.") from None
        if start.weekday() != 0:
            raise BlockError("Blocks start on a Monday.")
        if start < monday_of(today):
            raise BlockError("Pick this Monday or a later one.")
        if start > monday_of(today) + timedelta(weeks=START_AHEAD_WEEKS):
            raise BlockError(f"Start within the next {START_AHEAD_WEEKS} weeks.")
        return start

    # ------------------------------------------------------------- writes --
    def _plan_choice(self, uid: str, body: dict[str, Any]) -> str:
        mode = body.get("plan")
        cur = self.plan.current(uid)
        if mode is None:
            if cur["has_goal"]:
                raise BlockError("You already have a goal. Keep your plan, or replace it with a block plan?",
                                 409, "confirm_plan", {"current": cur})
            mode = "new"
        if mode not in ("new", "keep"):
            raise BlockError("plan must be new or keep")
        if mode == "new" and cur["has_goal"] and body.get("confirm_replace") is not True:
            raise BlockError("This replaces your current goal and plan. Confirm to go ahead.",
                             409, "confirm_plan", {"current": cur})
        return mode

    def _install(self, uid: str, b: dict[str, Any], mode: str) -> str:
        try:
            return str(self.plan.install(uid, b, mode))
        except PlanError as e:
            raise BlockError(str(e)) from None
        except ValueError as e:  # CoachError: too many events, bad field
            raise BlockError(str(e)) from None

    def create(self, uid: str, body: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(body, dict):
            raise BlockError("bad request")
        today = self._today(uid)
        start = self._start(body.get("start"), today)
        tid = body.get("template")
        event = None
        if tid == RACE:
            ev = next((e for e in self._events(uid) if e.get("id") == body.get("event_id")), None)
            if ev is None or (ev.get("kind") or "race") != "race" or not ev.get("date"):
                raise BlockError("Pick one of your races.", 404)
            race = date.fromisoformat(ev["date"])
            weeks = (monday_of(race) - start).days // 7 + 1
            if weeks < 2:
                raise BlockError("That race is too close for a block. Pick an earlier start or a later race.")
            if weeks > 52:
                raise BlockError("That race is more than a year after the start.")
            end = monday_of(race) + timedelta(days=6)
            event = {k: ev.get(k) for k in ("name", "date", "type", "distance", "location", "url") if ev.get(k)}
            name = _clean(body.get("name"), NAME_LEN, "Name") or f"Road to {ev.get('name') or 'race day'}"[:NAME_LEN]
        elif tid in TEMPLATES:
            tpl = TEMPLATES[tid]
            weeks = int(tpl["weeks"])
            end = template_dates(tpl, start)[0]
            name = _clean(body.get("name"), NAME_LEN, "Name") or tpl["name"]
        else:
            raise BlockError("Pick a block.")
        club = body.get("club") or None
        if club is not None and (not isinstance(club, str) or not self._club_admin(club, uid)):
            raise BlockError("Only club admins can start a block for the club.", 403)
        invite = body.get("invite") or []
        if not isinstance(invite, list) or len(invite) > MAX_INVITES or not all(isinstance(x, str) and _UID.match(x) for x in invite):
            raise BlockError(f"Invite up to {MAX_INVITES} friends.")
        invite = list(dict.fromkeys(x for x in invite if x != uid))
        if any(not self.mutual(uid, x) for x in invite):
            raise BlockError("You can invite friends who follow you back.", 403)
        if self._active_count(uid, today, self._all()) >= MAX_ACTIVE:
            raise BlockError(f"You're in {MAX_ACTIVE} blocks already. Finish or leave one first.", 409)
        mode = self._plan_choice(uid, body)
        now = int(self._clock())
        bid = secrets.token_hex(6)
        b = {"id": bid, "owner": uid, "name": name, "template": tid, "start": start.isoformat(), "weeks": weeks,
             "end": end.isoformat(), "event": event, "club": club, "created": now, "status": "active",
             "members": {uid: {"joined": now, "plan": mode, "checkins": True}},
             "invited": {x: {"by": uid, "ts": now} for x in invite},
             "progress": {}, "checkins": {}, "nudges": {}, "cheers": {}}
        # Build the owner's plan first: a builder error leaves nothing behind.
        b["members"][uid]["result"] = self._install(uid, b, mode)

        def apply(d: dict[str, Any]) -> None:
            self._prune(d, today)
            if self._active_count(uid, today, d.get("blocks") or {}) >= MAX_ACTIVE:
                raise BlockError(f"You're in {MAX_ACTIVE} blocks already. Finish or leave one first.", 409)
            d.setdefault("blocks", {})[bid] = b
        self._update(apply)
        for x in invite:
            self._invite_moment(x, uid, b)
        return {"block": self.view(uid, bid), "invited": invite, "plan": b["members"][uid]["result"]}

    def _invite_moment(self, to: str, by: str, b: dict[str, Any]) -> None:
        if self.moment is None:
            return
        start = date.fromisoformat(b["start"])
        text = f"🤝 {self._names(by)} invited you to {b['name']}, starting {start:%a %b} {start.day}."
        self.moment(to, {"type": "block_invite", "key": f"blockinvite:{b['id']}", "text": text[:140],
                         "actions": [{"id": "block", "label": "View invite", "block_id": b["id"]}]})

    def invite(self, uid: str, bid: Any, user_ids: Any) -> list[str]:
        self.require(uid)
        if not isinstance(user_ids, list) or not user_ids or len(user_ids) > MAX_INVITES \
                or not all(isinstance(x, str) and _UID.match(x) for x in user_ids):
            raise BlockError(f"Pick 1 to {MAX_INVITES} friends.")
        ids = list(dict.fromkeys(x for x in user_ids if x != uid))
        if not ids or any(not self.mutual(uid, x) for x in ids):
            raise BlockError("You can invite friends who follow you back.", 403)
        today = self._today(uid)
        stamp = int(self._clock())

        def apply(d: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
            b = self._get(d, bid)
            if uid not in b["members"]:
                raise BlockError("Block not found.", 404)
            if not self._live(b, today):
                raise BlockError("This block has finished.", 409)
            new = [x for x in ids if x not in b["members"] and x not in b["invited"]]
            if len(b["members"]) + len(b["invited"]) + len(new) > 2 * MAX_MEMBERS:
                raise BlockError("That's a lot of invites already.", 409)
            for x in new:
                b["invited"][x] = {"by": uid, "ts": stamp}
            return new, dict(b)
        new, b = self._update(apply)
        for x in new:
            self._invite_moment(x, uid, b)
        return new

    def join(self, uid: str, bid: Any, body: Any = None) -> dict[str, Any]:
        self.require(uid)
        body = body if isinstance(body, dict) else {}
        today = self._today(uid)
        b = self._get(self._doc.load(), bid)
        if uid in b["members"]:
            raise BlockError("You're already in this block.", 409)
        if not self._can_join(uid, b):
            raise BlockError("Block not found.", 404)
        if not self._live(b, today):
            raise BlockError("This block has finished.", 409)
        if len(b["members"]) >= MAX_MEMBERS:
            raise BlockError(f"This block is full ({MAX_MEMBERS} people).", 409)
        if self._active_count(uid, today, self._all()) >= MAX_ACTIVE:
            raise BlockError(f"You're in {MAX_ACTIVE} blocks already. Finish or leave one first.", 409)
        mode = self._plan_choice(uid, body)
        result = self._install(uid, b, mode)
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            bb = self._get(d, bid)
            if len(bb["members"]) >= MAX_MEMBERS:
                raise BlockError(f"This block is full ({MAX_MEMBERS} people).", 409)
            bb["invited"].pop(uid, None)
            bb["members"][uid] = {"joined": now, "plan": mode, "checkins": True, "result": result}
        self._update(apply)
        return {"block": self.view(uid, bid), "plan": result}

    def decline(self, uid: str, bid: Any) -> None:
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            b = self._get(d, bid)
            b["invited"].pop(uid, None)
        self._update(apply)

    def leave(self, uid: str, bid: Any) -> None:
        """Your plan stays yours: leaving only drops you from the block."""
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            b = self._get(d, bid)
            if uid not in b["members"]:
                raise BlockError("Block not found.", 404)
            del b["members"][uid]
            for wk in (b.get("progress") or {}).values():
                wk.pop(uid, None)
            if not b["members"]:
                del d["blocks"][bid]
                return
            if b["owner"] == uid:
                b["owner"] = min(b["members"], key=lambda m: b["members"][m]["joined"])
        self._update(apply)

    def end(self, uid: str, bid: Any) -> None:
        self.require(uid)
        today = self._today(uid)

        def apply(d: dict[str, Any]) -> None:
            b = self._get(d, bid)
            if uid not in b["members"]:
                raise BlockError("Block not found.", 404)
            if b["owner"] != uid:
                raise BlockError("Only the block's owner can end it.", 403)
            b["status"], b["ended_on"] = "ended", today.isoformat()
            b["invited"] = {}
        self._update(apply)

    def set_checkins(self, uid: str, bid: Any, on: Any) -> None:
        self.require(uid)
        if not isinstance(on, bool):
            raise BlockError("on must be true or false")

        def apply(d: dict[str, Any]) -> None:
            b = self._get(d, bid)
            if uid not in b["members"]:
                raise BlockError("Block not found.", 404)
            b["members"][uid]["checkins"] = on
        self._update(apply)

    # ----------------------------------------------------------- progress --
    def publish(self, uid: str, day: date | None = None) -> int:
        """Store the member's own done/planned for the week containing ``day`` (default
        today) on each of their live blocks. Returns how many blocks were updated."""
        today = self._today(uid)
        day = day or today
        mine = [b for b in self._all().values() if uid in b["members"]
                and b["start"] <= day.isoformat() <= b["end"] and b.get("status") == "active"]
        if not mine:
            return 0
        try:
            got = self._week(uid, day)
        except Exception:
            got = None
        if got is None:
            return 0
        done, target = int(got[0]), int(got[1])
        key = monday_of(day).isoformat()

        def apply(d: dict[str, Any]) -> int:
            n = 0
            for b in mine:
                bb = (d.get("blocks") or {}).get(b["id"])
                if bb is None or uid not in bb["members"]:
                    continue
                prog = bb.setdefault("progress", {})
                prog.setdefault(key, {})[uid] = [done, target]
                for k in sorted(prog)[:-KEEP_WEEKS]:
                    del prog[k]
                n += 1
            return n
        return int(self._update(apply))

    @staticmethod
    def _closed(row: list[int] | None) -> bool:
        return bool(row) and row[1] > 0 and row[0] >= row[1]

    @staticmethod
    def behind(row: list[int] | None, weekday: int) -> bool:
        """Not closed and short of a fair share of the week so far."""
        if not row or row[1] <= 0 or row[0] >= row[1]:
            return False
        return row[0] < (row[1] * (weekday + 1)) // 7

    def recap_counts(self, b: dict[str, Any], monday: str) -> tuple[int, int]:
        """(closed, members) for the week at ``monday``; no numbers = not closed."""
        rows = (b.get("progress") or {}).get(monday) or {}
        members = [m for m in b["members"] if b["members"][m]["joined"] <= self._ts_end(monday)]
        return sum(1 for m in members if self._closed(rows.get(m))), len(members)

    @staticmethod
    def _ts_end(monday: str) -> float:
        d = date.fromisoformat(monday) + timedelta(days=7)
        return datetime(d.year, d.month, d.day).timestamp() + 86400  # generous: tz-free

    # -------------------------------------------------------------- reads --
    def _summary(self, uid: str, b: dict[str, Any], today: date) -> dict[str, Any]:
        wk = week_info(b, today)
        rows = (b.get("progress") or {}).get(wk["monday"]) or {}
        mine = rows.get(uid)
        visible = [m for m in b["members"] if m == uid or not self._blocked(uid, m)]
        return {"id": b["id"], "name": b["name"], "template": b["template"], "start": b["start"], "end": b["end"],
                "weeks": b["weeks"], "week": wk, "status": b.get("status", "active"),
                "members": len(visible), "owner": b["owner"] == uid,
                "event": {k: (b.get("event") or {}).get(k) for k in ("name", "date", "distance")} if b.get("event") else None,
                "club": {"id": b["club"], "name": self._club_name(b["club"], uid) or "Club"} if b.get("club") else None,
                "me": {"done": mine[0], "target": mine[1]} if mine else None,
                "closed": sum(1 for m in visible if self._closed(rows.get(m)))}

    def overview(self, uid: str) -> dict[str, Any]:
        """My blocks (live first), invites to me, blocks open to my clubs."""
        self.require(uid)
        today = self._today(uid)
        try:
            self.publish(uid)
        except Exception:
            pass
        mine, invites, clubs = [], [], []
        for b in self._all().values():
            if uid in b["members"]:
                mine.append(self._summary(uid, b, today))
            elif self._live(b, today) and not self._blocked(uid, b["owner"]) and len(b["members"]) < MAX_MEMBERS:
                inv = (b.get("invited") or {}).get(uid)
                if inv and self.mutual(uid, inv["by"]) and inv["by"] in b["members"]:
                    invites.append({**self._summary(uid, b, today), "invited_by": inv["by"]})
                elif b.get("club") and self._club_member(b["club"], uid):
                    clubs.append(self._summary(uid, b, today))
        mine.sort(key=lambda s: (s["status"] != "active" or s["week"]["state"] == "done", s["start"]))
        return {"blocks": mine, "invites": invites, "clubs": clubs,
                "active": self._active_count(uid, today, self._all()), "max_active": MAX_ACTIVE}

    def view(self, uid: str, bid: Any) -> dict[str, Any]:
        """The block page: members' done/planned this week, the group ring, check-ins."""
        self.require(uid)
        today = self._today(uid)
        b = self._get(self._doc.load(), bid)
        member = uid in b["members"]
        if not member and not self._can_join(uid, b):
            raise BlockError("Block not found.", 404)
        if member:
            try:
                self.publish(uid)
            except Exception:
                pass
            b = self._get(self._doc.load(), bid)
        out = self._summary(uid, b, today)
        out["member"] = member
        if not member:  # an invite / club preview: the card, never people or numbers
            inv = (b.get("invited") or {}).get(uid)
            out["invited_by"] = inv["by"] if inv else None
            return out
        wk = out["week"]
        rows = (b.get("progress") or {}).get(wk["monday"]) or {}
        sent = b.get("nudges") or {}
        people = []
        for m, info in sorted(b["members"].items(), key=lambda x: x[1]["joined"]):
            if m != uid and self._blocked(uid, m):
                continue
            row = rows.get(m)
            people.append({"user_id": m, "name": self._names(m), "me": m == uid, "owner": m == b["owner"],
                           "done": row[0] if row else None, "target": row[1] if row else None,
                           "closed": self._closed(row), "behind": self.behind(row, today.weekday()),
                           "cheered": sent.get(f"{uid}>{m}") == today.isoformat()})
        shown = [rows.get(p["user_id"]) for p in people]
        tot = sum(r[1] for r in shown if r)
        done = sum(min(r[0], r[1]) for r in shown if r)
        prev = (date.fromisoformat(wk["monday"]) - timedelta(days=7)).isoformat()

        def checks(monday: str) -> list[dict[str, Any]]:
            got = (b.get("checkins") or {}).get(monday) or {}
            return [{"user_id": m, "name": self._names(m), "me": m == uid, **{k: c.get(k) for k in ("feel", "note", "ts")}}
                    for m, c in sorted(got.items(), key=lambda x: x[1].get("ts", 0))
                    if m in b["members"] and (m == uid or not self._blocked(uid, m))]
        me = b["members"][uid]
        cheers = [c for c in (b.get("cheers") or {}).get(uid) or [] if c.get("day", "") >= (today - timedelta(days=6)).isoformat()
                  and not self._blocked(uid, c["by"])]
        out.update({
            "people": people,
            "group": {"done": done, "target": tot, "pct": round(100 * done / tot) if tot else 0,
                      "closed": sum(1 for p in people if p["closed"]), "count": len(people)},
            "checkins": checks(wk["monday"]), "last_checkins": checks(prev),
            "my_checkin": ((b.get("checkins") or {}).get(wk["monday"]) or {}).get(uid),
            "checkins_on": me.get("checkins", True), "plan": me.get("plan"),
            "cheers": [{"name": self._names(c["by"]), "day": c["day"]} for c in cheers][-5:],
            "feels": [{"id": k, "label": v} for k, v in FEELS.items()],
            "invited": [x for x in (b.get("invited") or {}) if b["owner"] == uid and not self._blocked(uid, x)],
            "feed": f"b-{b['id']}",
        })
        return out

    def groups_of(self, uid: str) -> list[dict[str, Any]]:
        """For ``clubs.Clubs.block_groups``: the block feed's audience (``club:b-<id>``)."""
        return [{"id": f"b-{b['id']}", "name": b["name"], "members": list(b["members"])}
                for b in self._all().values() if uid in b["members"]]

    # ------------------------------------------------------------ check-in --
    def checkin(self, uid: str, bid: Any, feel: Any, note: Any = None) -> dict[str, Any]:
        self.require(uid)
        if feel not in FEELS:
            raise BlockError("Pick how the week felt.")
        text = _clean(note, NOTE_LEN, "Note")
        today = self._today(uid)
        stamp = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            b = self._get(d, bid)
            if uid not in b["members"]:
                raise BlockError("Block not found.", 404)
            wk = week_info(b, today)
            if wk["state"] == "upcoming":
                raise BlockError("Check-ins open once the block starts.", 409)
            # Monday morning still answers last week's Sunday question.
            monday = wk["monday"]
            if today.weekday() == 0 and b["start"] < monday:
                prev = ((b.get("checkins") or {}).get(monday) or {}).get(uid)
                last = (date.fromisoformat(monday) - timedelta(days=7)).isoformat()
                if prev is None and uid not in ((b.get("checkins") or {}).get(last) or {}):
                    monday = last
            cs = b.setdefault("checkins", {})
            cs.setdefault(monday, {})[uid] = {"feel": feel, "note": text, "ts": stamp}
            for k in sorted(cs)[:-KEEP_WEEKS]:
                del cs[k]
            return {"week": monday, "feel": feel, "note": text}
        return self._update(apply)

    # --------------------------------------------------------------- nudge --
    def nudge(self, uid: str, bid: Any, other: Any) -> dict[str, Any]:
        """Cheer a member who hasn't closed their week. Once a day per pair. Returns
        ``{"push": text | None}``: the coalesced push for ``other`` (the caller sends it)."""
        self.require(uid)
        if not isinstance(other, str) or other == uid:
            raise BlockError("Pick a teammate.")
        today = self._today(uid)
        stamp = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            b = self._get(d, bid)
            if uid not in b["members"] or other not in b["members"] or self._blocked(uid, other):
                raise BlockError("Block not found.", 404)
            if not self._live(b, today):
                raise BlockError("This block has finished.", 409)
            row = ((b.get("progress") or {}).get(monday_of(today).isoformat()) or {}).get(other)
            if self._closed(row):
                raise BlockError("They've already closed their week.", 409)
            key = f"{uid}>{other}"
            if (b.get("nudges") or {}).get(key) == today.isoformat():
                raise BlockError("You've cheered them today. Try again tomorrow.", 429)
            n = b.setdefault("nudges", {})
            n[key] = today.isoformat()
            for k in [k for k, v in n.items() if v < (today - timedelta(days=7)).isoformat()]:
                del n[k]
            cs = b.setdefault("cheers", {}).setdefault(other, [])
            cs.append({"by": uid, "ts": stamp, "day": today.isoformat(), "pushed": False})
            del cs[:-CHEERS_KEEP]
            return dict(b)
        b = self._update(apply)
        if self.moment is not None:
            self.moment(other, {"type": "block_cheer", "key": f"blockcheer:{b['id']}:{self._today(other).isoformat()}",
                                "ttl_days": 2,
                                "text": f"📣 {self._names(uid)} cheered you on in {b['name']}. You've got this!"[:140],
                                "actions": [{"id": "block", "label": "Open block", "block_id": b["id"]}]})
        return {"ok": True, "push": self.cheer_push(other, b["id"])}

    def cheer_push(self, to: str, bid: str) -> str | None:
        """Coalesced: at most one push per ``COALESCE_S`` per person, never in their quiet
        hours; it names everyone who cheered since the last one."""
        if quiet(self._now(to)):
            return None
        now = self._clock()
        with self._lock:
            if now - self._pushed.get(to, -1e12) < COALESCE_S:
                return None

            def apply(d: dict[str, Any]) -> list[str]:
                b = (d.get("blocks") or {}).get(bid) or {}
                names: list[str] = []
                for c in reversed((b.get("cheers") or {}).get(to) or []):  # newest first
                    if not c.get("pushed") and now - c["ts"] < 12 * 3600 and not self._blocked(to, c["by"]):
                        c["pushed"] = True
                        if c["by"] not in names:
                            names.append(c["by"])
                return names
            who = self._doc.update(apply)
            if not who:
                return None
            self._pushed[to] = now
        first = self._names(who[0])
        return f"{first} cheered you on" + (f" (+{len(who) - 1} more)" if len(who) > 1 else "") + ". You've got this!"

    # ---------------------------------------------------------- moments --
    def tick(self, uid: str) -> int:
        """``Moments.on_tick`` (outside quiet hours): publish my numbers, then the Sunday
        check-in and Monday recap moments for each of my blocks (``Moments.post`` dedupes per
        block and week and applies the daily cap). Evaluated at most every 10 minutes."""
        if uid.startswith("coach_") or self.moment is None:
            return 0
        now = self._clock()
        with self._lock:
            if now - self._ticked.get(uid, -1e12) < TICK_EVERY_S:
                return 0
            self._ticked[uid] = now
        local = self._now(uid)
        if quiet(local):
            return 0
        today = local.date()
        mine = [b for b in self._all().values() if uid in b["members"] and b.get("status") == "active"]
        if not mine:
            return 0
        if today.weekday() == 0:
            self.publish(uid, today - timedelta(days=1))  # last week's final numbers first
        self.publish(uid)
        return self.check_in(uid, local) + self.recap(uid, local)

    def check_in(self, uid: str, local: datetime) -> int:
        today = local.date()
        if today.weekday() != 6 or local.time() < CHECKIN_FROM or self.moment is None:
            return 0
        n = 0
        for b in self._all().values():
            m = b["members"].get(uid)
            if not m or not m.get("checkins", True) or not self._live(b, today) or b["start"] > today.isoformat():
                continue
            wk = week_info(b, today)
            if uid in ((b.get("checkins") or {}).get(wk["monday"]) or {}):
                continue
            text = f"🐇 How did week {wk['n']} of {b['name']} go? One tap tells your crew."
            out = self.moment(uid, {"type": "block_checkin", "key": f"blockcheckin:{b['id']}:{wk['monday']}",
                                    "text": text[:140], "push_title": b["name"],
                                    "actions": [{"id": "block_checkin", "label": label, "block_id": b["id"], "feel": k}
                                                for k, label in FEELS.items()]})
            n += out == "posted"
        return n

    def recap(self, uid: str, local: datetime) -> int:
        today = local.date()
        if today.weekday() != 0 or local.time() < RECAP_FROM or self.moment is None:
            return 0
        last = (today - timedelta(days=7)).isoformat()
        n = 0
        for b in self._all().values():
            if uid not in b["members"] or b.get("status") != "active" or not (b["start"] <= last <= b["end"]):
                continue
            closed, count = self.recap_counts(b, last)
            if count < 2:
                continue
            wk = week_info(b, date.fromisoformat(last))
            if closed == count:
                text = f"🏁 All {count} of you closed week {wk['n']} of {b['name']}. What a crew!"
            else:
                text = f"🏁 {closed} of {count} of you closed week {wk['n']} of {b['name']}."
            if wk["n"] >= int(b["weeks"]):
                text = text.rstrip(".!") + ". That's the block done!"
            out = self.moment(uid, {"type": "block_recap", "key": f"blockrecap:{b['id']}:{last}",
                                    "text": text[:140],
                                    "actions": [{"id": "block", "label": "Open block", "block_id": b["id"]}]})
            n += out == "posted"
        return n


__all__ = ["Blocks", "BlockError", "PlanHooks", "TEMPLATES", "FEELS", "MAX_MEMBERS", "MAX_ACTIVE",
           "template_plan", "template_dates", "week_info", "monday_of"]
