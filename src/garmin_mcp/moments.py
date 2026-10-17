"""Rabbit moments: short, deterministic updates posted into the athlete's Rabbit log.

No model call. Each moment is one line (<= 140 chars, Rabbit voice, at most one emoji,
with a real number) plus optional action chips the app routes to existing screens. They
land in the active goal's pinned coach thread as a turn with ``kind: "moment"`` (UI-only:
never sent to the model, see ``Agent._context_messages``), so the feed shows them in order
with briefs and workout notes. A coach sees them only through the existing Rabbit-chat
share (``can_see_rabbit_chats``), as plain text.

Triggers
* **Workout synced** (live sync + the background poller): "Logged: Morning Run · 6.2 mi in
  52:10 · +42 XP." with [How did it feel?] [See breakdown]. Posts at once, even in quiet
  hours (never pushed). When the AI workout note is on, the moment stays factual and leaves
  the coaching to the note. Deduped per activity id; only activities from today/yesterday.
* **Streak milestones** 7/14/30/50/100 (with a workout synced).
* **Progress**: level up, badge earned, challenge completed (from ``/app/api/progress``
  deltas). The first look only records what's already there (no back-fill spam).
* **Time-based** (``tick`` from ``Proactive.tick``): streak at risk at 18:30 local (streak
  >= 3, ``at_risk``, nothing today, not a plan rest day; once a day), main-race countdown
  (8 weeks, 4 weeks, 2 weeks, race week, race eve; from 08:00), readiness grade change
  (checked daily from 09:00, posted at most weekly).
* **Coach plan**: "Your coach Bill updated your plan." [Open plan] (the coach chat and push
  already told them; this is the Rabbit-log entry, no push).
* **Friend joined** (``friend_joined``): someone joined from the athlete's invite link (they now
  follow each other); webapp's ``on_join`` hook sends the push itself.

Rules: quiet hours 21:00-07:00 local queue a moment until 07:00 (workout synced is exempt);
at most ``DAILY_CAP`` moments a day besides workouts; only streak-at-risk, race countdown and
the Friday week nudge (``weekring.py``) push, at most ``PUSH_CAP`` a day, never in quiet hours, and only when ``moments_push`` isn't
off. Dedupe keys and the queue live in the per-user ``moments`` doc (bounded). Oura data is
never read here.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Callable
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from .appstore import AppStore
from .logs import log_event
from .progress import level_of, tier_name, workout_xp
from .stats import category

logger = logging.getLogger(__name__)

MAX_CHARS = 140
DAILY_CAP = 4
PUSH_CAP = 2
QUIET_START, QUIET_END = 21, 7
MAX_KEYS = 400
MAX_QUEUE = 10
STREAK_MILESTONES = (7, 14, 30, 50, 100)
SICK_AT = dtime(8, 0)        # daily sick-mode upkeep and the one check-in
RISK_AT = dtime(18, 30)
RACE_FROM = dtime(8, 0)
GRADE_FROM = dtime(9, 0)
GRADE_EVERY_DAYS = 7
# Race countdown: (days out at most, window in days, id). A milestone fires once while the
# race is inside its window (a phone that was off on the day still gets it the next day).
RACE_STEPS = ((56, 3, "8w"), (28, 3, "4w"), (14, 2, "2w"), (7, 2, "week"), (1, 0, "eve"))
GRADE_ORDER = ("F", "D", "C", "C+", "B-", "B", "B+", "A-", "A")
WORKOUT_TYPES = frozenset({"workout"})  # exempt from the daily cap and quiet hours
PUSH_TYPES = frozenset({"streak_risk", "race", "week_nudge", "block_checkin", "pace"})  # + blocks.py Sunday check-in, paces.py
SICK_QUIET = frozenset({"streak_risk", "week_nudge"})  # held back while sick mode is on
MILESTONE_TYPES = frozenset({"streak", "level", "badge", "challenge"})  # may become Community drafts

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⭐⏳]")


def emoji_count(text: str) -> int:
    return len(_EMOJI.findall(text))


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(v: Any, limit: int = 40) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    return (s[: limit - 1].rstrip() + "…") if len(s) > limit else s


def fmt_duration(seconds: float) -> str:
    s = int(round(max(0.0, seconds)))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_distance(meters: float, sport: str, imperial: bool) -> str | None:
    if not meters or meters <= 0:
        return None
    if sport == "swim":
        return f"{round(meters * 1.09361):,} yd" if imperial else f"{round(meters):,} m"
    km = meters / 1000
    return f"{km * 0.621371:.1f} mi" if imperial else f"{km:.1f} km"


def action(id_: str, label: str, **extra: Any) -> dict[str, Any]:
    return {"id": id_, "label": label, **{k: v for k, v in extra.items() if v is not None}}


# ------------------------------------------------------------- builders ----
def workout_moment(a: dict[str, Any], *, imperial: bool, streak: int | None = None,
                   ai_note: bool = False, milestone: bool = False) -> dict[str, Any] | None:
    """``a``: a raw Garmin activity summary (``activityId``, ``activityName``, ...)."""
    aid = a.get("activityId")
    if not isinstance(aid, int) or isinstance(aid, bool):
        return None
    atype = a.get("activityType")
    sport = category(atype.get("typeKey") if isinstance(atype, dict) else None)
    dur = a.get("duration") if isinstance(a.get("duration"), int | float) else 0
    dist = a.get("distance") if isinstance(a.get("distance"), int | float) else 0
    name = _name(a.get("activityName")) or "Workout"
    d = fmt_distance(dist, sport, imperial)
    what = f"{d} in {fmt_duration(dur)}" if d else (f"{round(dur / 60)} min" if dur else "")
    xp = workout_xp(dur / 60)
    text = f"🐇 Logged: {name}" + (f" · {what}" if what else "") + f" · +{xp} XP."
    if streak and streak >= 3 and not milestone:
        text += f" {streak}-day streak!"
    elif not ai_note:
        text += " Nice hop."  # the AI note brings the coaching; alone, a small cheer
    return {"type": "workout", "key": f"act:{aid}", "text": _clip(text),
            "actions": [action("checkin", "How did it feel?", activity_id=aid, title=name),
                        action("reaction", "See breakdown", activity_id=aid)]}


STREAK_LINES = {
    7: "🔥 7-day streak! A full week of showing up.",
    14: "🔥 14 days in a row. Two solid weeks, keep the legs fresh.",
    30: "🔥 30-day streak! A whole month of hops.",
    50: "🔥 50 days straight. That's a habit now.",
    100: "🔥 100-day streak! Legend status.",
}


def streak_milestone(n: int) -> dict[str, Any] | None:
    if n not in STREAK_LINES:
        return None
    return {"type": "streak", "key": f"streak:{n}", "ttl_days": n, "text": STREAK_LINES[n],
            "actions": [action("progress", "See progress")]}


def streak_risk(n: int, day: date) -> dict[str, Any]:
    return {"type": "streak_risk", "key": f"risk:{day.isoformat()}",
            "text": _clip(f"⏳ Your {n}-day streak is on the line. Even 20 easy minutes keeps it alive."),
            "push_title": "Streak on the line",
            "actions": [action("ask", "Plan a quick one",
                               prompt="Plan me a quick 20-minute session to keep my streak alive.")]}


def race_step(days: int) -> str | None:
    for most, window, sid in RACE_STEPS:
        if most - window <= days <= most:
            return sid
    return None


def race_moment(event: dict[str, Any], days: int) -> dict[str, Any] | None:
    sid = race_step(days)
    eid = event.get("id")
    if sid is None or not eid:
        return None
    name = _name(event.get("name") or event.get("title"), 40) or "your race"
    weeks = round(days / 7)
    lines = {
        "8w": f"🏁 {weeks} weeks to {name}. Build time: your key sessions matter most now.",
        "4w": f"🏁 {weeks} weeks to {name}. Peak block: nail the long ones and sleep like it's training.",
        "2w": f"🏁 {days} days to {name}. Taper's close: less volume, same sharpness.",
        "week": f"🏁 Race week: {name} in {days} days. Easy miles, early nights, pack checked.",
        "eve": f"🏁 {name} is tomorrow! Lay out your kit, fuel early, trust the work.",
    }
    if event.get("kind") not in (None, "", "race"):  # a challenge or other main event
        lines["week"] = f"🏁 Big week: {name} in {days} days. Easy miles, early nights, kit checked."
        return {"type": "race", "key": f"race:{eid}:{sid}", "text": _clip(lines[sid]),
                "push_title": "Event countdown", "actions": []}
    acts = [action("readiness", "Race readiness", event_id=eid)]
    if sid in ("week", "eve"):
        acts.append(action("racepack", "Race-week pack", event_id=eid))
    return {"type": "race", "key": f"race:{eid}:{sid}", "text": _clip(lines[sid]),
            "push_title": "Race countdown", "actions": acts}


def level_moment(level: int) -> dict[str, Any]:
    return {"type": "level", "key": f"level:{level}",
            "text": _clip(f"⭐ Level {level}: {tier_name(level)}! Your training just leveled you up."),
            "actions": [action("progress", "See progress")]}


def badge_moment(badge_id: str, title: str) -> dict[str, Any]:
    return {"type": "badge", "key": f"badge:{badge_id}",
            "text": _clip(f"🏅 Badge earned: {_name(title, 60)}. +100 XP."),
            "actions": [action("progress", "See progress")]}


def challenge_moment(key: str, name: str, xp: int) -> dict[str, Any]:
    return {"type": "challenge", "key": f"challenge:{key}",
            "text": _clip(f"🏆 Challenge complete: {_name(name, 60)} · +{xp} XP."),
            "actions": [action("progress", "See progress")]}


def grade_moment(event: dict[str, Any], old: str, new: str, day: date) -> dict[str, Any]:
    name = _name(event.get("name"), 40) or "Race"
    up = GRADE_ORDER.index(new) > GRADE_ORDER.index(old) if old in GRADE_ORDER and new in GRADE_ORDER else True
    tail = "The work is showing." if up else "Here's what would lift it."
    return {"type": "grade", "key": f"grade:{event.get('id')}:{day.isoformat()}",
            "text": _clip(f"{'📈' if up else '📉'} {name} readiness: {old} → {new}. {tail}"),
            "actions": [action("readiness", "Race readiness", event_id=event.get("id"))]}


def coach_plan_moment(coach_first: str, stamp: str) -> dict[str, Any]:
    first = _name(coach_first, 30) or "Your coach"
    who = f"Your coach {first}" if first != "Your coach" else first
    return {"type": "coach_plan", "key": f"coachplan:{stamp}",
            "text": _clip(f"📋 {who} updated your plan. See this week's sessions."),
            "actions": [action("plan", "Open plan")]}


def friend_joined_moment(name: str, joiner: str) -> dict[str, Any]:
    """For the inviter, once per joiner: someone joined from their invite link (mutual follow)."""
    first = _name(name, 30) or "A friend"
    return {"type": "friend_joined", "key": f"joined:{joiner}",
            "text": _clip(f"🎉 {first} joined Rabbit from your invite. You now follow each other."),
            "push_title": "New friend on Rabbit",
            "actions": [action("community", "See friends", view="people")]}


def completed_challenges(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Completed challenges from the ``challenges`` doc, keyed like their XP bonus."""
    from .challenges import XP
    out = []
    for c in (doc.get("joined") or []) + (doc.get("history") or []):
        if isinstance(c, dict) and c.get("completed_at") and c.get("id"):
            out.append({"key": c.get("xp_key") or c["id"], "name": c.get("name") or "Challenge",
                        "xp": XP.get(c.get("period"), 0)})
    return out


# -------------------------------------------------------------- service ----
Push = Callable[[str, str, str, str], None]  # (user_id, title, body, url)


class Moments:
    """Posts moments into the athlete's Rabbit log. Thread-safe through ``AppStore`` docs."""

    def __init__(self, store: AppStore, coach: Any, *, now: Callable[[str], datetime],
                 clock: Callable[[], float] = time.time,
                 stats: Callable[[str], dict[str, Any]] | None = None,
                 events: Callable[[str], list[dict[str, Any]]] | None = None,
                 grade: Callable[[str, str], str | None] | None = None,
                 push: Push | None = None) -> None:
        self._s = store
        self._coach = coach
        self._now = now
        self._clock = clock
        self.stats = stats
        self.events = events
        self.grade = grade
        self.push = push
        # Community (community.py): a milestone moment (streak/level/badge/challenge) may
        # become a share draft; the hook returns extra action chips ([Share] [Not now]).
        self.on_milestone: Callable[[str, dict[str, Any]], list[dict[str, Any]] | None] | None = None
        # Called after new workouts were handled (personal bests, race finished).
        self.after_workouts: Callable[[str], None] | None = None
        # Set by webapp: share new workouts with friends (community auto-share) without a
        # moment, for the background check when workout feedback is off; ``wants_share(uid)``
        # says whether that person shares at all (skips the Garmin read when not).
        self.share_scan: Callable[[str], None] | None = None
        self.wants_share: Callable[[str], bool] | None = None
        # Called with the fresh activities after their moments (reward.py: post-workout reward).
        self.on_workouts: Callable[[str, list[dict[str, Any]]], Any] | None = None
        # Called from tick outside quiet hours (club meetup reminders).
        self.on_tick: Callable[[str], Any] | None = None
        # Sick mode (sick.py, set by webapp): while it's on, no streak or close-your-week nudges;
        # ``sick_daily(uid)`` runs once a day (keeps the plan covered, starts the easy return) and
        # may return one gentle check-in moment.
        self.sick_active: Callable[[str], bool] | None = None
        self.sick_daily: Callable[[str], dict[str, Any] | None] | None = None
        # Countdown steps another feature replaces for an event (raceweek.py: "week", "eve").
        self.skip_steps: Callable[[dict[str, Any]], set[str]] | None = None

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "moments")

    def _profile(self, uid: str) -> dict[str, Any]:
        return self._s.user_doc(uid, "profile").load()

    @staticmethod
    def quiet(local: datetime) -> bool:
        return local.hour >= QUIET_START or local.hour < QUIET_END

    @staticmethod
    def _seen(d: dict[str, Any], key: str, today: date, ttl_days: int | None) -> bool:
        when = (d.get("keys") or {}).get(key)
        if when is None:
            return False
        if ttl_days is None:
            return True
        try:
            return (today - date.fromisoformat(when)).days < ttl_days
        except ValueError:
            return True

    @staticmethod
    def _mark(d: dict[str, Any], key: str, today: date) -> None:
        keys = d.setdefault("keys", {})
        keys[key] = today.isoformat()
        if len(keys) > MAX_KEYS:
            for k in sorted(keys, key=lambda k: keys[k])[: len(keys) - MAX_KEYS]:
                del keys[k]

    @staticmethod
    def _take_slot(d: dict[str, Any], today: date) -> bool:
        if d.get("day") != today.isoformat():
            d["day"], d["count"] = today.isoformat(), 0
        if int(d.get("count") or 0) >= DAILY_CAP:
            return False
        d["count"] = int(d.get("count") or 0) + 1
        return True

    # ------------------------------------------------------------ post --
    def post(self, uid: str, m: dict[str, Any] | None) -> str:
        """Dedupe, quiet hours and the daily cap, then append. Returns ``posted``,
        ``queued``, ``duplicate``, ``capped`` or ``skipped``."""
        if m is None or uid.startswith("coach_"):
            return "skipped"
        local = self._now(uid)
        today = local.date()
        if m["type"] in SICK_QUIET and self.sick_active is not None:
            try:
                if self.sick_active(uid):
                    return "skipped"
            except Exception:  # a broken check never blocks a moment
                pass
        exempt = m["type"] in WORKOUT_TYPES
        quiet = self.quiet(local)
        if self.on_milestone is not None and m["type"] in MILESTONE_TYPES \
                and not self._seen(self._doc(uid).load(), m["key"], today, m.get("ttl_days")):
            try:
                extra = self.on_milestone(uid, m)
            except Exception as e:  # the moment still goes out
                log_event(logger, logging.WARNING, "moment_milestone_failed", user_id=uid, error=type(e).__name__)
                extra = None
            if extra:
                m = {**m, "actions": [*(m.get("actions") or []), *extra][:3]}

        def apply(d: dict[str, Any]) -> str:
            if self._seen(d, m["key"], today, m.get("ttl_days")):
                return "duplicate"
            self._mark(d, m["key"], today)
            if exempt:
                return "posted"
            if quiet:
                q = d.setdefault("queue", [])
                if len(q) >= MAX_QUEUE:
                    return "capped"
                q.append({k: v for k, v in m.items() if k != "ttl_days"})
                return "queued"
            return "posted" if self._take_slot(d, today) else "capped"
        outcome = self._doc(uid).update(apply)
        if outcome == "posted":
            self._append(uid, m, push=not quiet)
        log_event(logger, logging.INFO, "moment", user_id=uid, type=m["type"], outcome=outcome)
        return outcome

    def _append(self, uid: str, m: dict[str, Any], *, push: bool) -> None:
        thread = self._coach.coach_thread(uid)
        now = int(self._clock())
        self._coach.append_turn(uid, thread["id"], {
            "id": "m" + secrets.token_hex(8), "ts": now, "kind": "moment", "user": None,
            "assistant": m["text"],
            "parts": [{"type": "moment", "moment": m["type"], "text": m["text"],
                       "actions": m.get("actions") or []}],
        })
        if push and m["type"] in PUSH_TYPES:
            self._maybe_push(uid, m)

    def _maybe_push(self, uid: str, m: dict[str, Any]) -> None:
        if self.push is None or self._profile(uid).get("moments_push") is False:
            return
        today = self._now(uid).date().isoformat()

        def take(d: dict[str, Any]) -> bool:
            p = d.setdefault("pushes", {})
            if p.get("day") != today:
                p["day"], p["n"] = today, 0
            if p["n"] >= PUSH_CAP:
                return False
            p["n"] += 1
            return True
        if not self._doc(uid).update(take):
            return
        try:
            body = re.sub(r"^[^\w]+", "", m["text"]).strip()  # no leading emoji in the notification
            self.push(uid, m.get("push_title") or "Rabbit", body, "/app/?open=coach")
        except Exception as e:  # the moment is already in the log
            log_event(logger, logging.WARNING, "moment_push_failed", user_id=uid, error=type(e).__name__)

    def flush(self, uid: str) -> int:
        """Post moments queued during quiet hours (from 07:00 local)."""
        local = self._now(uid)
        if self.quiet(local):
            return 0
        today = local.date()

        def take(d: dict[str, Any]) -> list[dict[str, Any]]:
            q = d.get("queue") or []
            if not q:
                return []
            out = [m for m in q if self._take_slot(d, today)]
            d["queue"] = []
            return out
        due = self._doc(uid).update(take) if (self._doc(uid).load().get("queue")) else []
        for m in due:
            self._append(uid, m, push=True)
        return len(due)

    # -------------------------------------------------------- triggers --
    def workouts(self, uid: str, acts: list[dict[str, Any]], *, ai_note: bool | None = None) -> int:
        """New activities from live sync or the poller (raw Garmin summaries)."""
        if uid.startswith("coach_"):
            return 0
        today = self._now(uid).date()
        fresh = []
        for a in acts:
            if not isinstance(a, dict) or a.get("parentId"):
                continue
            try:
                day = date.fromisoformat(str(a.get("startTimeLocal") or "")[:10])
            except ValueError:
                continue
            if 0 <= (today - day).days <= 1:
                fresh.append(a)
        fresh = sorted(fresh, key=lambda a: a.get("activityId") or 0)[-3:]
        if not fresh:
            # A late sync or a manual upload from a few days ago: no moment, but friends still
            # see it (auto-share covers the last few days).
            if acts and self.after_workouts is not None:
                try:
                    self.after_workouts(uid)
                except Exception as e:
                    log_event(logger, logging.WARNING, "after_workouts_failed", user_id=uid, error=type(e).__name__)
            return 0
        athlete = self._coach.athlete(uid)
        imperial = athlete.get("units") != "metric"
        if ai_note is None:
            ai_note = self._profile(uid).get("workout_feedback", True) is not False
        streak = None
        if self.stats is not None:
            try:
                streak = int((self.stats(uid).get("streak") or {}).get("current") or 0)
            except Exception:  # Garmin busy: the moment goes out without the streak
                streak = None
        ms = streak_milestone(streak) if streak else None
        n = 0
        for i, a in enumerate(fresh):
            last = i == len(fresh) - 1
            m = workout_moment(a, imperial=imperial, streak=streak if last else None,
                               ai_note=ai_note, milestone=bool(ms) and last)
            n += self.post(uid, m) == "posted"
        if ms is not None:
            self.post(uid, ms)
        if self.on_workouts is not None:
            try:
                self.on_workouts(uid, fresh)
            except Exception as e:  # the reward never breaks the workout moment
                log_event(logger, logging.WARNING, "on_workouts_failed", user_id=uid, error=type(e).__name__)
        if self.after_workouts is not None:
            try:
                self.after_workouts(uid)
            except Exception as e:  # milestones never break the workout moment
                log_event(logger, logging.WARNING, "after_workouts_failed", user_id=uid, error=type(e).__name__)
        return n

    def on_progress(self, uid: str, out: dict[str, Any],
                    challenges: list[dict[str, Any]] | None = None) -> int:
        """``out``: ``Progress.update`` result; ``challenges``: completed ones
        (``{"key", "name", "xp"}``). The first call only records what's there."""
        if uid.startswith("coach_"):
            return 0
        cands: list[dict[str, Any]] = []
        level = int(out.get("level") or level_of(int(out.get("xp") or 0)))
        cands.append(level_moment(level))
        for b in out.get("new_badges") or []:
            cands.append(badge_moment(str(b.get("id")), str(b.get("title") or "")))
        for c in challenges or []:
            cands.append(challenge_moment(str(c["key"]), str(c.get("name") or "Challenge"), int(c.get("xp") or 0)))
        today = self._now(uid).date()

        def baseline(d: dict[str, Any]) -> bool:
            if d.get("progress_init"):
                return False
            d["progress_init"] = True
            for m in cands:
                self._mark(d, m["key"], today)
            return True
        if self._doc(uid).update(baseline):
            return 0
        n = 0
        for m in cands:
            if m["type"] == "level" and not out.get("level_up"):
                continue  # only a real level-up (the ledger's own celebration flag)
            n += self.post(uid, m) == "posted"
        return n

    def coach_plan(self, uid: str, coach_first: str) -> str:
        return self.post(uid, coach_plan_moment(coach_first, str(int(self._clock()))))

    def friend_joined(self, uid: str, name: str, joiner: str) -> str:
        """Invite joins (``passkey_web`` ``on_join``); the caller sends the push."""
        return self.post(uid, friend_joined_moment(name, joiner))

    # ------------------------------------------------------ time-based --
    def _claim(self, uid: str, what: str, day: date) -> bool:
        def apply(d: dict[str, Any]) -> bool:
            c = d.setdefault("claims", {})
            if c.get(what) == day.isoformat():
                return False
            c[what] = day.isoformat()
            return True
        return bool(self._doc(uid).update(apply))

    def tick(self, uid: str) -> None:
        """Once a minute from ``Proactive.tick``. Cheap unless something is due."""
        if uid.startswith("coach_"):
            return
        self.flush(uid)
        local = self._now(uid)
        if self.quiet(local):
            return
        t, today = local.time(), local.date()
        if t >= SICK_AT and self.sick_daily is not None and self._claim(uid, "sick", today):
            try:
                self.post(uid, self.sick_daily(uid))
            except Exception as e:  # sick mode never breaks the tick
                log_event(logger, logging.WARNING, "sick_daily_failed", user_id=uid, error=type(e).__name__)
        if t >= RISK_AT and self._claim(uid, "risk", today):
            self.check_streak_risk(uid, today)
        if t >= RACE_FROM and self.events is not None and self._claim(uid, "race", today):
            self.check_race(uid, today)
        if t >= GRADE_FROM and self.grade is not None and self._claim(uid, "grade", today):
            self.check_grade(uid, today)
        if self.on_tick is not None:
            try:
                self.on_tick(uid)
            except Exception as e:  # reminders never break the tick
                log_event(logger, logging.WARNING, "moment_tick_hook_failed", user_id=uid, error=type(e).__name__)

    def check_streak_risk(self, uid: str, today: date) -> str:
        if self.stats is None:
            return "skipped"
        try:
            st = self.stats(uid).get("streak") or {}
        except Exception:
            return "skipped"
        n = int(st.get("current") or 0)
        if n < 3 or not st.get("at_risk") or st.get("today_done"):
            return "skipped"  # at_risk already excludes plan rest days
        return self.post(uid, streak_risk(n, today))

    def _main_race(self, uid: str, today: date) -> dict[str, Any] | None:
        evs = [e for e in (self.events(uid) if self.events else []) if (e.get("date") or "") >= today.isoformat()]
        return next((e for e in evs if e.get("main")), None)

    def check_race(self, uid: str, today: date) -> str:
        ev = self._main_race(uid, today)
        if ev is None:
            return "skipped"
        try:
            days = (date.fromisoformat(ev["date"]) - today).days
        except (KeyError, ValueError):
            return "skipped"
        if self.skip_steps is not None and race_step(days) in self.skip_steps(ev):
            return "skipped"
        return self.post(uid, race_moment(ev, days))

    def check_grade(self, uid: str, today: date) -> str:
        ev = self._main_race(uid, today)
        if ev is None or self.grade is None:
            return "skipped"
        try:
            new = self.grade(uid, ev["id"])
        except Exception:
            return "skipped"
        if not new:
            return "skipped"

        def apply(d: dict[str, Any]) -> tuple[str, str | None]:
            g = d.get("grade") or {}
            if g.get("event_id") != ev["id"] or not g.get("grade"):
                d["grade"] = {"event_id": ev["id"], "grade": new, "posted": None}
                return "baseline", None
            if g["grade"] == new:
                return "same", None
            posted = g.get("posted")
            if posted and (today - date.fromisoformat(posted)).days < GRADE_EVERY_DAYS:
                return "wait", None  # keep the last announced grade; compare again tomorrow
            old = g["grade"]
            d["grade"] = {"event_id": ev["id"], "grade": new, "posted": today.isoformat()}
            return "changed", old
        state, old = self._doc(uid).update(apply)
        if state != "changed" or old is None:
            return state
        return self.post(uid, grade_moment(ev, old, new, today))


__all__ = ["Moments", "workout_moment", "streak_milestone", "streak_risk", "race_moment", "race_step",
           "level_moment", "badge_moment", "challenge_moment", "grade_moment", "coach_plan_moment",
           "completed_challenges", "emoji_count", "fmt_duration", "fmt_distance", "DAILY_CAP", "MAX_CHARS"]
