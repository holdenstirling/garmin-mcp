"""Rabbit home "Up next": one card, one primary action, chosen deterministically (no model).

It wraps the Today card (``today.py``, so the same advice is never shown twice) and adds
what the Today card can't know: the session's main target and watch state, tomorrow's
session, and a group run for people without a plan or goal.

Priority, first match wins:

1. **Session** (``session``): a planned session today (built or uploaded plan). Title,
   duration, main target; primary "Start" (workout day), secondary "Send to watch" when the
   built-plan session isn't on the watch yet. Today's advice (race week, rough check-in,
   low recovery, adjustment) is the detail line, and a race-pack / review action rides
   along as ``extra``.
2. **Today** (``today``): the Today card's own call when it isn't about a session: race
   day / race week, a suggested adjustment, a rough check-in, done for today (with
   tomorrow), nothing planned on a plan day.
3. **Rest** (``rest``): the plan (or recovery) says rest; tomorrow's session as a preview.
4. **Build your plan** (``build_plan``): a goal but no plan.
5. **Group run** (``group_run``): no plan and no goal: a club meetup they RSVP'd (going or
   maybe) or a run/trail/tri group from the clubs directory, tonight or tomorrow.
6. **Set a goal** (``set_goal``).

Oura readiness only reaches this through the Today card's signals (display only).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import anyio

from .logs import log_event

if TYPE_CHECKING:
    from .agent import Agent
    from .oura import OuraClient

logger = logging.getLogger(__name__)

GROUP_KINDS = ("run_club", "trail", "tri")
EVENING = "17:00"
WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _mins(m: Any) -> str:
    return f" · {int(m)} min" if isinstance(m, int | float) and m else ""


def _day_label(day: date, hhmm: str, today: date) -> str:
    if day == today:
        return f"Tonight {hhmm}" if hhmm and hhmm >= EVENING else (f"Today {hhmm}" if hhmm else "Today")
    if day == today + timedelta(days=1):
        return f"Tomorrow {hhmm}".strip()
    return f"{WEEKDAY[day.weekday()]} {hhmm}".strip()


def pick_group(meetups: list[dict[str, Any]], listings: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The next group run tonight or tomorrow: an RSVP'd club meetup first, else the
    directory. ``meetups`` = ``Clubs.my_meetups`` rows, ``listings`` = ``Directory.view``
    rows; ``now`` is athlete-local."""
    local = now.replace(tzinfo=None)
    today = local.date()
    last = datetime.combine(today + timedelta(days=1), datetime.max.time())
    for m in sorted(meetups or [], key=lambda x: x.get("next") or ""):
        if m.get("my_rsvp") not in ("going", "maybe") or not m.get("next"):
            continue
        try:
            at = datetime.fromisoformat(m["next"]).replace(tzinfo=None)
        except ValueError:
            continue
        if local <= at <= last:
            club = m.get("club") or {}
            return {"source": "club", "name": str(m.get("title") or club.get("name") or "Club meetup"),
                    "club": str(club.get("name") or ""), "club_id": club.get("id"), "meetup_id": m.get("id"),
                    "when": _day_label(at.date(), at.strftime("%H:%M"), today), "where": str(m.get("where") or ""),
                    "rsvp": m.get("my_rsvp"), "url": None, "listing_id": None}
    best: tuple[int, str, dict[str, Any]] | None = None
    for x in listings or []:
        nxt = x.get("next") or {}
        if x.get("kind") not in GROUP_KINDS or nxt.get("in_days") not in (0, 1):
            continue
        cand = (int(nxt["in_days"]), str(nxt.get("time") or "99:99"), x)
        if best is None or cand[:2] < best[:2]:
            best = cand
    if best is None:
        return None
    d, hhmm, x = best
    return {"source": "directory", "name": str(x.get("name") or "Group run"), "club": "",
            "club_id": x.get("linked_club"), "meetup_id": None,
            "when": _day_label(today + timedelta(days=d), "" if hhmm == "99:99" else hhmm, today),
            "where": str(x.get("meet_spot") or ""), "rsvp": None, "url": x.get("join_url"), "listing_id": x.get("id")}


def choose(*, card: dict[str, Any] | None, has_plan: bool, goal: dict[str, Any] | None,
           session: dict[str, Any] | None = None, tomorrow: dict[str, Any] | None = None,
           group: dict[str, Any] | None = None, garmin: bool = True) -> dict[str, Any]:
    """Pure: the Up next card. ``card`` = ``TodayService.get`` output (or None); ``session`` =
    ``{target, on_watch, syncable}`` for today's built-plan session; ``tomorrow`` =
    ``workoutday._tomorrow``; ``group`` = ``pick_group``."""
    def out(kind: str, tone: str, headline: str, detail: str, primary: tuple[str, str], **extra: Any) -> dict[str, Any]:
        return {"kind": kind, "tone": tone, "headline": headline, "detail": detail,
                "primary": {"kind": primary[0], "label": primary[1]}, "secondary": extra.get("secondary"),
                "extra": extra.get("extra"), "session": extra.get("session"), "tomorrow": extra.get("tomorrow"),
                "group": extra.get("group"), "signals": (card or {}).get("signals") or [],
                "today": card, "garmin": garmin}

    tone = (card or {}).get("tone") or ""
    action = (card or {}).get("action") or {}
    s = (card or {}).get("session")
    # 1. Today's planned session.
    if card and s and tone != "done":
        info = session or {}
        sess = {"id": s.get("id"), "title": s.get("title") or "Session", "minutes": s.get("minutes"),
                "sport": s.get("sport") or "other", "target": info.get("target"),
                "on_watch": bool(info.get("on_watch")), "syncable": bool(info.get("syncable"))}
        secondary = ({"kind": "send_to_watch", "label": "Send to watch"}
                     if sess["id"] and sess["syncable"] and not sess["on_watch"] and garmin else None)
        extra = ({"kind": "today", "label": action.get("label") or "Open"}
                 if action.get("kind") in ("review_adjust", "open_racepack") else None)
        primary = ("start", "Start") if sess["id"] else ("today", action.get("label") or "Ask Rabbit")
        return out("session", tone or "go", f"{sess['title']}{_mins(sess['minutes'])}", str(card.get("detail") or ""),
                   primary, session=sess, secondary=secondary, extra=extra)
    # 2. Race, adjustment, rough check-in: the Today card's own call.
    if card and (tone in ("race", "plan") or (tone == "easy" and card.get("headline") == "Take it easy today")):
        return out("today", tone, str(card["headline"]), str(card.get("detail") or ""),
                   (str(action.get("kind") or "ask"), str(action.get("label") or "Ask Rabbit")))
    if has_plan:
        # 3. Rest day (plan or recovery), with tomorrow.
        if card and tone == "rest":
            return out("rest", "rest", str(card.get("headline") or "Rest day"), str(card.get("detail") or ""),
                       ("today", str(action.get("label") or "Enjoy the rest")), tomorrow=tomorrow)
        if card:
            return out("today", tone or "go", str(card["headline"]), str(card.get("detail") or ""),
                       (str(action.get("kind") or "ask"), str(action.get("label") or "Ask Rabbit")),
                       tomorrow=tomorrow if tone == "done" else None)
        return out("today", "plan", "Your plan", "Open your plan to see this week's sessions.", ("open_plan", "Open plan"))
    # 4. A goal, no plan.
    if goal:
        title = str(goal.get("title") or "your goal")
        return out("build_plan", "plan", "Build your plan",
                   f"Turn {title} into sessions from today to the day, ready to send to your watch.",
                   ("build_plan", "Build your plan"))
    # 5. No plan, no goal: a group run tonight or tomorrow.
    if group:
        bits = [group["when"]] + ([group["where"]] if group.get("where") else [])
        return out("group_run", "go", group["name"], " · ".join(bits), ("group", "Find a group run tonight"),
                   group=group)
    if card and tone == "done":
        return out("today", "done", str(card["headline"]), str(card.get("detail") or ""), ("set_goal", "Set a goal"))
    # 6. Nothing yet.
    return out("set_goal", "plan", "Set a goal", "A race, a distance or just showing up 3x a week. "
               "Rabbit builds the plan around it.", ("set_goal", "Set a goal"))


# ------------------------------------------------------------ first visit --
# Invited friends arrive without Garmin. Garmin-only reads (stats, load) answer 409 with
# this body; the app shows a friendly empty state with "Connect Garmin" instead of an error.
NO_GARMIN: dict[str, Any] = {
    "error": "Connect Garmin to see your training here.", "code": "garmin_not_connected",
    "action": {"kind": "connect_garmin", "label": "Connect Garmin"},
}

FIRST_VISIT_ITEMS: tuple[dict[str, str], ...] = (
    {"id": "clubs", "title": "Find clubs near you", "detail": "Run clubs, group rides and leagues"},
    {"id": "events", "title": "Find an event", "detail": "Races and group events to aim for"},
    {"id": "feed", "title": "See your community", "detail": "What friends and clubs are sharing"},
    {"id": "friends", "title": "Follow friends", "detail": "Cheer each other on"},
)


def first_visit(*, garmin: bool, inviter: str | None) -> dict[str, Any]:
    """The Rabbit-home welcome for anyone without Garmin connected: what works right now,
    with "Connect Garmin" as the one primary action. ``inviter``: first name, when the
    member joined from someone's invite and they follow each other."""
    return {"show": not garmin, "garmin": garmin, "inviter": inviter,
            "title": f"Welcome! You and {inviter} are connected" if inviter else "Welcome to Rabbit",
            "items": [dict(i) for i in FIRST_VISIT_ITEMS] if not garmin else [],
            "primary": {"kind": "connect_garmin", "label": "Connect Garmin",
                        "detail": "Your workouts, streak and plan sync on their own"}}


Group = Callable[[str, datetime], "dict[str, Any] | None"]


class UpNextService:
    """Gathers the inputs (the Today card, the plan, tomorrow, a group run) and calls ``choose``."""

    def __init__(self, agent: "Agent", oura: "OuraClient | None", *, group: Group | None = None,
                 garmin: Callable[[str], bool] | None = None) -> None:
        self._a = agent
        self._oura = oura
        self._group = group
        self._garmin = garmin

    async def get(self, user_id: str) -> dict[str, Any]:
        from .today import TodayService
        from .workoutday import _find, _tomorrow, clean_fuel_plan, session_view
        a = self._a
        now = a._now(user_id)
        today = now.date()
        try:
            card: dict[str, Any] | None = await TodayService(a, self._oura).get(user_id)
        except Exception as e:  # still useful without it
            log_event(logger, logging.WARNING, "upnext_today_failed", user_id=user_id, error=type(e).__name__)
            card = None
        plan = await anyio.to_thread.run_sync(a.plans.get, user_id)
        goal = a.coach.active_goal(user_id)
        has_plan = bool(plan) or bool(goal and goal.get("plan"))
        session = None
        fuel_line: str | None = None
        sid = ((card or {}).get("session") or {}).get("id")
        if plan and sid:
            found = _find(plan, sid)
            if found is not None:
                s, d, w = found
                v = session_view(s, d, a.coach.athlete(user_id), phase=w.get("phase"),
                                 recovery=bool(w.get("recovery")), plan=plan)
                t = (v.get("main_targets") or [None])[0]
                session = {"target": (str(t.get("label") or "") or None) if isinstance(t, dict) else None,
                           "on_watch": v["garmin"]["on_watch"], "syncable": v["garmin"]["syncable"]}
                fp = v.get("fuel_plan") or {}
                b = fp.get("before") or {}
                if b and not b.get("optional") and ((card or {}).get("session") or {}).get("status") != "done":
                    fuel_line = f"{b['when']}: {b['headline']}"
        group = None
        if not has_plan and not goal and self._group is not None:
            try:
                group = await anyio.to_thread.run_sync(lambda: self._group(user_id, now))  # type: ignore[misc]
            except Exception as e:
                log_event(logger, logging.INFO, "upnext_group_failed", user_id=user_id, error=type(e).__name__)
        garmin = self._garmin(user_id) if self._garmin is not None else bool((card or {}).get("garmin"))
        tomorrow = _tomorrow(plan, today) if plan else None
        if fuel_line is None and plan and tomorrow and tomorrow.get("id") and now.hour >= 12:
            found = _find(plan, tomorrow["id"])
            if found is not None:
                fp2 = clean_fuel_plan(found[0], found[1], a.coach.athlete(user_id), plan) or {}
                if fp2.get("night_before"):
                    fuel_line = f"Tonight: a carb-rich dinner for tomorrow's {str(found[0].get('title') or 'session').lower()}"
        out = choose(card=card, has_plan=has_plan, goal=goal, session=session,
                     tomorrow=tomorrow, group=group, garmin=garmin)
        if fuel_line and out.get("kind") in ("session", "rest", "today"):
            out["fuel"] = fuel_line
        return out


__all__ = ["NO_GARMIN", "UpNextService", "choose", "first_visit", "pick_group"]
