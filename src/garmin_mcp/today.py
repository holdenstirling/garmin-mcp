"""Rabbit's "Today" card: one deterministic recommendation for the day.

No model call, so Oura readiness may feed it (Oura's API terms forbid sending it to an
AI model; nothing here goes to one). Inputs: today's planned sessions (built plan, or
the cached week of an uploaded plan) merged with Garmin activities, form (TSB from
``load.compute``), Oura readiness vs. its 28-day baseline when connected, the day
streak, the plan-adjustment proposal, the main race date and this week's misses.

Priority, first match wins:

1. **Race** (tone ``race``): race day, or the main event within 14 days (race-week
   framing; today's session, if any, kept light). Action: race pack.
1b. **Rough check-in** (tone ``easy``): today's or yesterday's check-in has a pain flag or
   feel 2 or lower (``checkins.py``). Action: review the adjustment when there is one.
2. **Adjustment suggested** (tone ``plan``): ``adjust.propose`` has changes. Action: review.
3. **Done** (tone ``done``): trained today and nothing else is still planned.
4. **Recovery low**: readiness under 70 (and 5+ under baseline when there is one) or
   form under -25. Very low (readiness under 60 or form under -35) -> ``rest``,
   otherwise ``easy`` (quality swapped for ~70% easy).
5. **Planned session** (tone ``go``): hit it as planned, framed by form and readiness.
6. **Plan rest day** (tone ``rest``).
7. **Nothing planned**: streak at risk -> a short streak-keeper (``go``); fresh (form
   over +5) -> a good day for quality (``go``); else active recovery (``easy``). Without
   a plan the action is "Build a plan" (``plan``-less users still get a useful call).

Missing Garmin, Oura or plan data just drops that input.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import anyio

from .adjust import propose as propose_adjustment
from .logs import log_event
from .planbuilder import QUALITY, week_for
from .weekplan import merge

if TYPE_CHECKING:
    from .agent import Agent
    from .oura import OuraClient

logger = logging.getLogger(__name__)

RACE_WINDOW = 14
LOW_READINESS, VERY_LOW_READINESS = 70, 60
LOW_TSB, VERY_LOW_TSB = -25.0, -35.0
FRESH_TSB = 5.0


def _cut(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip(" ,.;:") + "…"


def _session(s: dict[str, Any] | None) -> dict[str, Any] | None:
    if not s:
        return None
    return {"id": s.get("id"), "title": str(s.get("title") or "Session"), "minutes": s.get("minutes"),
            "sport": s.get("sport") or "other"}


def _mins(m: Any) -> str:
    return f" ({int(m)}')" if isinstance(m, int | float) and m else ""


def _signals(form: float | None, readiness: float | None, streak: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if form is not None:
        out.append({"label": "Form", "value": f"{form:+.0f}", "good": form >= -10})
    if readiness is not None:
        out.append({"label": "Readiness", "value": f"{readiness:.0f}", "good": readiness >= LOW_READINESS})
    if streak and streak.get("current"):
        out.append({"label": "Streak", "value": str(streak["current"]), "good": not streak.get("at_risk")})
    return out[:3]


def recommend(*, today: date, days: list[dict[str, Any]] | None, has_plan: bool,
              form: float | None = None, readiness: float | None = None,
              readiness_baseline: float | None = None, streak: dict[str, Any] | None = None,
              adjust: dict[str, Any] | None = None, race: dict[str, Any] | None = None,
              checkins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Pure: the card for ``today``. ``days`` is ``weekplan.merge`` output for this week."""
    t = today.isoformat()
    day = next((d for d in days or [] if d.get("date") == t), None)
    sessions = [s for s in (day or {}).get("sessions", []) if s.get("status") != "rest"]
    planned = [s for s in sessions if s.get("status") == "planned"]
    done_s = [s for s in sessions if s.get("status") == "done"]
    done_acts = [s["activity"] for s in done_s if s.get("activity")] + list((day or {}).get("extra") or [])
    rest_day = bool(day) and bool(day.get("sessions")) and not sessions
    missed = [s for d in days or [] if d.get("date", "") < t for s in d.get("sessions", [])
              if s.get("status") == "missed"]
    session = planned[0] if planned else None
    trained_today = bool(done_acts) or bool((streak or {}).get("today_done"))
    signals = _signals(form, readiness, streak)

    def card(tone: str, headline: str, detail: str, action: tuple[str, str],
             s: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"date": t, "tone": tone, "headline": _cut(headline, 60), "detail": _cut(detail, 160),
                "session": _session(s), "action": {"kind": action[0], "label": action[1]},
                "signals": signals}

    # 1. Race day / race week.
    if race and 0 <= int(race.get("days", -1)) <= RACE_WINDOW:
        n, name = int(race["days"]), str(race.get("name") or "Your race")
        if n == 0:
            return card("race", f"Race day: {name}", "Trust the training. Start easier than you want to, "
                        "fuel early and often, and enjoy it.", ("open_racepack", "Race pack"))
        head = f"Race week: {name} in {n} day{'s' if n != 1 else ''}" if n <= 7 else f"{name} in {n} days"
        if session:
            detail = f"Today: {session['title']}{_mins(session.get('minutes'))}. Keep it smooth; the fitness is banked."
        elif done_acts:
            detail = f"Done today: {done_acts[0].get('name') or 'workout'}. Rest, sleep and check your race-week pack."
        else:
            detail = "Nothing planned today: rest, easy movement, and a look at pacing, fueling and the forecast."
        return card("race", head, detail, ("open_racepack", "Open race pack"), session)

    # 1b. The athlete told us it's rough (today's or yesterday's check-in).
    yday = (today - timedelta(days=1)).isoformat()
    rough = sorted((c for c in checkins or [] if isinstance(c, dict) and yday <= (c.get("date") or "") <= t
                    and (c.get("pain_flag") or (isinstance(c.get("feel"), int) and c["feel"] <= 2))),
                   key=lambda c: (c.get("date") or "", c.get("ts") or 0), reverse=True)
    if rough:
        c = rough[0]
        when = "today" if c.get("date") == t else "yesterday"
        said = _cut(str(c.get("summary") or "").rstrip("."), 70)
        if c.get("pain_flag"):
            detail = (f"You flagged pain {when}. Easy or rest, nothing that hurts. "
                      "If it's sharp or getting worse, check with a physio or doctor.")
        else:
            detail = f"Your check-in {when}: {said or 'felt rough'}. Keep it easy" + (
                f": {session['title']} truly easy, or shorter." if session else ", or rest.")
        if adjust and adjust.get("status") == "suggest":
            action = ("review_adjust", "Review changes")
        elif session and session.get("id"):
            action = ("open_session", "See session")
        else:
            action = ("log_rest", "Easy day")
        return card("easy", "Take it easy today", detail, action, session)

    # 2. Adjustment suggested.
    if adjust and adjust.get("status") == "suggest":
        reasons = adjust.get("reasons") or []
        n = len(adjust.get("changes") or [])
        detail = (reasons[0] if reasons else "Your week drifted from the plan.") + \
            f" {n} change{'s' if n != 1 else ''} ready to review."
        return card("plan", "Rabbit suggests adjusting your week", detail, ("review_adjust", "Review changes"), session)

    # 3. Already trained and nothing left today.
    if trained_today and not planned:
        a = done_acts[0] if done_acts else {}
        what = f"{a.get('name') or 'Workout'}{_mins(a.get('minutes'))}" if a else "Today's training"
        cur = (streak or {}).get("current") or 0
        tail = f" {cur}-day streak." if cur >= 2 else ""
        return card("done", "Done for today. Nice work", f"{what} logged.{tail} Refuel, hydrate and sleep well.",
                    ("ask", "How did it go?"), done_s[0] if done_s else None)

    # 4. Recovery low.
    low_ready = readiness is not None and readiness < LOW_READINESS and (
        readiness_baseline is None or readiness <= readiness_baseline - 5)
    low_form = form is not None and form < LOW_TSB
    if low_ready or low_form:
        very = (readiness is not None and readiness < VERY_LOW_READINESS) or (form is not None and form < VERY_LOW_TSB)
        why = " and ".join(x for x in (f"Readiness {readiness:.0f}" if low_ready and readiness is not None else "",
                                       f"form {form:+.0f}" if low_form and form is not None else "") if x)
        why = why[:1].upper() + why[1:]
        if very:
            detail = (f"{why}: swap {session['title']} for rest or 20' easy." if session
                      else f"{why}: your body is asking for a day off. Rest or a gentle walk.")
            return card("rest", "Rest day recommended", detail,
                        ("open_session", "Adjust session") if session and session.get("id") else ("log_rest", "Take a rest day"),
                        session)
        if session and session.get("kind") in QUALITY:
            m = session.get("minutes") or 45
            detail = f"{why}: swap {session['title']} for {max(20, int(round(m * 0.7 / 5) * 5))}' easy. Intensity can wait."
        elif session:
            detail = f"{why}: keep {session['title']} truly easy, or shorten it."
        else:
            detail = f"{why}: light movement only. 20-30' easy or a walk."
        return card("easy", "Take it easy today", detail,
                    ("open_session", "See session") if session and session.get("id") else ("log_rest", "Easy day"), session)

    # 5. Planned session.
    if session:
        bits = []
        if form is not None:
            bits.append(f"Form {form:+.0f}")
        if readiness is not None:
            bits.append(f"readiness {readiness:.0f}")
        lead = " and ".join(bits)
        if form is not None and form > FRESH_TSB:
            mood = "you're fresh."
        elif form is not None and form < -10:
            mood = "you're building; keep the easy parts easy."
        else:
            mood = "good to go."
        detail = (f"{lead}: {mood} " if lead else "") + f"Hit {session['title']} as planned."
        if missed:
            detail += " Skip making up missed work."
        return card("go", f"Today: {session['title']}{_mins(session.get('minutes'))}", detail,
                    ("open_session", "Open session") if session.get("id") else ("ask", "Ask Rabbit"), session)

    # 6. Plan rest day.
    if has_plan and rest_day:
        keep = " Your streak is safe." if (streak or {}).get("current") else ""
        return card("rest", "Rest day", f"Your plan has rest today. Sleep, eat well, maybe a walk.{keep}",
                    ("log_rest", "Enjoy the rest"))

    # 7. Nothing planned.
    cur = (streak or {}).get("current") or 0
    if streak and streak.get("at_risk"):
        return card("go", f"Keep your {cur}-day streak alive",
                    "You've used this week's free rest day. 20 easy minutes of anything counts.",
                    ("ask", "Ideas for today"))
    action = ("ask", "Ask Rabbit") if has_plan else ("build_plan", "Build a plan")
    if form is not None and form > FRESH_TSB:
        return card("go", "You're fresh: good day for quality",
                    f"Form {form:+.0f}. Try intervals or a tempo effort, or go a bit longer than usual.", action)
    return card("easy", "Active recovery day",
                "Nothing planned. An easy 30-45' or a walk keeps things moving"
                + (f" and adds to your {cur}-day streak." if cur else "."), action)


class TodayService:
    """Gathers the inputs (cheap, cached reads; never the model) and calls ``recommend``."""

    def __init__(self, agent: "Agent", oura: "OuraClient | None") -> None:
        self._a = agent
        self._oura = oura

    async def get(self, user_id: str) -> dict[str, Any]:
        a = self._a
        today = a._now(user_id).date()
        plan = await anyio.to_thread.run_sync(a.plans.get, user_id)
        goal = a.coach.active_goal(user_id)
        acts: list[dict[str, Any]] | None
        try:
            _, acts = await anyio.to_thread.run_sync(a.stats.activities, user_id)
        except Exception as e:  # Garmin not connected or down: plan-only card
            log_event(logger, logging.INFO, "today_no_garmin", user_id=user_id, error=type(e).__name__)
            acts = None
        streak = form = None
        if acts is not None:
            try:
                streak = (await anyio.to_thread.run_sync(a.stats.get, user_id)).get("streak")
                now = (await anyio.to_thread.run_sync(a.stats.load, user_id)).get("now") or {}
                form = now.get("tsb") if isinstance(now.get("tsb"), int | float) else None
            except Exception:
                pass
        recovery = readiness = base = None
        if self._oura is not None and self._oura.connected(user_id):
            try:
                recovery = await self._oura.recovery(user_id, today, 28)
                latest = recovery.get("latest") or {}
                if latest.get("date", "") >= (today - timedelta(days=1)).isoformat() \
                        and isinstance(latest.get("readiness"), int | float):
                    readiness = float(latest["readiness"])
                b = (recovery.get("baseline") or {}).get("readiness")
                base = float(b) if isinstance(b, int | float) else None
            except Exception:  # Oura down: decide from the rest
                recovery = None
        try:
            checkins = a.checkins.list(user_id, 7)
        except Exception:
            checkins = []
        adjust = None
        if plan and acts is not None:
            adjust = propose_adjustment(plan, acts, today, recovery=recovery, tsb=form,
                                        dismissed=plan.get("adjust_dismissed"), checkins=checkins)
        # This week's planned sessions merged with what was done.
        monday = today - timedelta(days=today.weekday())
        planned: dict[str, list[dict[str, Any]]] | None = None
        start = monday
        if plan:
            w = week_for(plan, today)
            if w is not None:
                start = date.fromisoformat(w["start"])
                planned = {d: [{"sport": s["sport"], "title": s["title"], "minutes": s.get("minutes"),
                                "kind": s.get("kind"), "id": s.get("id")} for s in ss] for d, ss in w["days"].items()}
        elif goal and goal.get("plan"):
            try:
                pw, cached = a.planner.cached_days(user_id, goal, today)
                if cached:
                    start, planned = date.fromisoformat(pw["start"]), cached.get("days")
            except Exception:
                planned = None
        days = merge(start, today, planned, acts or [])
        race = None
        try:
            for e in a.events.list(user_id):
                if e.get("main") and e.get("date"):
                    n = (date.fromisoformat(e["date"]) - today).days
                    if 0 <= n <= RACE_WINDOW:
                        race = {"name": e.get("name") or e.get("title") or "Your race", "date": e["date"], "days": n}
                    break
        except Exception:
            race = None
        out = recommend(today=today, days=days, has_plan=bool(plan) or planned is not None, form=form,
                        readiness=readiness, readiness_baseline=base, streak=streak, adjust=adjust, race=race,
                        checkins=checkins)
        out["garmin"] = acts is not None
        return out


__all__ = ["recommend", "TodayService"]
