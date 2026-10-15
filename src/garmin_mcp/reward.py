"""Post-workout reward and the monthly recap card. Deterministic, no model call.

Workout reward
--------------
When a new Garmin activity syncs (``Moments.workouts`` from live sync or the poller hands the
fresh activities to ``Rewards.on_workouts``), the newest one gets a reward payload, built
once per activity and kept in the per-user ``rewards`` doc:

* ONE headline insight, chosen by fixed rules from real data (``pick_headline``):
  1. records against the athlete's own last year (compact Garmin activities): fastest
     5K/10K (Garmin's ``fastestSplit_*``), longest run/ride/swim/hike, most climbing, longest
     workout, biggest training effect. A record needs a prior activity to beat; ties are not
     records. "in N weeks" = since the last activity at least as good (N >= ``MIN_WEEKS``);
     nothing as good in the window -> "in 12 months" (a year of history) or "on record".
     Ranked by how long it's been (year/record first), then the order above.
  2. a streak milestone (7/14/30/50/100 days),
  3. the week's goal closed by this workout (plan sessions, else active-week workouts),
  4. the planned session nailed (``workoutday.verdict``),
  5. else "Logged: <name>".
* 2-3 stat chips (distance, time, pace/speed or climbing) in the athlete's units,
* XP for the workout (+ the planned-session bonus), level before/after for the XP bar,
  the current streak, the verdict and session id (for the check-in).

``GET /app/api/reward`` returns the newest unseen reward (activity from the last
``SHOW_DAYS`` days) so the app shows it once on the next open; ``?activity_id=`` returns that
one (push tap). ``POST /app/api/reward/{id}/seen`` dismisses it and anything older, for
good. The background workout note (``proactive.AgentDelivery``, kind ``workout``) claims
the headline once per activity as its push title and opens the reward
(``/app/?open=reward&activity=<id>``): no second push, the note's own rules apply (workout
pushes aren't held for quiet hours, as in moments.py). Nothing here reads Oura.

Monthly recap
-------------
``month_recap`` (``GET /app/api/recap/month?month=YYYY-MM``, default last month, last 12
months): hours, sessions, longest session (sport + time, never its name: names can carry
places), best day streak inside the month, top sport, top club (the club the athlete posted
to most that month, else their first club) and hours per Monday-start week. The app draws
the share image itself (canvas, 1080x1350). ``check_month`` (from ``Moments.on_tick``, so
never in quiet hours) posts one "Your September is ready" moment on days 1-3 of a month when
last month had a session; ``Moments.post`` applies the daily cap and dedupe.
"""

from __future__ import annotations

import calendar
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .moments import STREAK_MILESTONES, action, fmt_distance, fmt_duration
from .progress import level_of, level_view, week_goal, workout_xp
from .stats import _rows, _streaks, category

if TYPE_CHECKING:
    from .appstore import AppStore

MIN_WEEKS = 4          # "longest run in 2 weeks" isn't news
YEAR_SPAN_DAYS = 300   # history this long makes "in 12 months" honest
SHOW_DAYS = 3          # unseen rewards older than this don't pop up on open
KEEP_ITEMS = 12
KEEP_SEEN = 200
HEADLINE_MAX = 80
MONTHS_BACK = 12
MONTH_MOMENT_DAYS = 3  # the 1st, or the next two days if the app/server missed it
M_FT = 3.28084

# (kind, field, sport filter, higher is better); order = tie-break priority.
RECORDS: tuple[tuple[str, str, str | None, bool], ...] = (
    ("split_5k", "split5", "run", False),
    ("split_10k", "split10", "run", False),
    ("distance", "km", "*", True),   # per sport: run, bike, swim, hike
    ("climb", "climb", None, True),
    ("duration", "min", None, True),
    ("effect", "te", None, True),
)
DIST_SPORTS = {"run": "run", "bike": "ride", "swim": "swim", "hike": "hike"}
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim", "brick": "brick", "strength": "strength session",
              "hike": "hike", "ski": "ski", "climb": "climb", "paddle": "paddle"}


def _num(v: Any) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0.0


def _row(a: dict[str, Any]) -> dict[str, Any] | None:
    rs = _rows([a])
    if not rs:
        return None
    r = rs[0]
    r["split5"] = _num(a.get("fastest_5k_s"))
    r["split10"] = _num(a.get("fastest_10k_s"))
    r["te"] = _num(a.get("aerobic_te"))
    return r


def _mmss(sec: float) -> str:
    return fmt_duration(sec)


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d}" if m >= 60 else f"{m} min"


def _value_text(kind: str, r: dict[str, Any], imperial: bool) -> str:
    if kind == "split_5k":
        return _mmss(r["split5"])
    if kind == "split_10k":
        return _mmss(r["split10"])
    if kind == "distance":
        return fmt_distance(r["km"] * 1000, r["sport"], imperial) or ""
    if kind == "climb":
        return f"{round(r['climb'] * M_FT):,} ft" if imperial else f"{round(r['climb']):,} m"
    if kind == "duration":
        return _hm(r["min"])
    return f"{r['te']:.1f}"


def _subject(kind: str, r: dict[str, Any]) -> str:
    return {"split_5k": "Fastest 5K", "split_10k": "Fastest 10K",
            "distance": f"Longest {DIST_SPORTS.get(r['sport'], 'workout')}", "climb": "Most climbing",
            "duration": "Longest workout", "effect": "Biggest training effect"}[kind]


def records(me: dict[str, Any], others: list[dict[str, Any]], *, imperial: bool) -> list[dict[str, Any]]:
    """Every record ``me`` sets against earlier (or same-day) ``others``, best first."""
    out = []
    for prio, (kind, field, sport, higher) in enumerate(RECORDS):
        if sport == "*":
            if me["sport"] not in DIST_SPORTS:
                continue
            pool_sport: str | None = me["sport"]
        else:
            if sport is not None and me["sport"] != sport:
                continue
            pool_sport = sport
        v = me[field]
        if not v:
            continue
        prior = [o for o in others if o["date"] <= me["date"] and o[field]
                 and (pool_sport is None or o["sport"] == pool_sport)]
        if not prior:
            continue  # a first is not a record
        as_good = [o for o in prior if (o[field] >= v if higher else o[field] <= v)]
        weeks: int | None
        if as_good:
            weeks = (me["date"] - max(o["date"] for o in as_good)).days // 7
            if weeks < MIN_WEEKS:
                continue
            when = f"in {weeks} weeks"
            rank = weeks
        else:
            span = (me["date"] - min(o["date"] for o in prior)).days
            if span >= YEAR_SPAN_DAYS:
                when, rank = "in 12 months", 1000
            elif len(prior) >= 2:
                when, rank = "on record", 999
            else:
                continue
            weeks = None
        value = _value_text(kind, me, imperial)
        out.append({"kind": kind, "weeks": weeks, "rank": rank, "prio": prio, "value": value,
                    "text": f"{_subject(kind, me)} {when}: {value}"})
    out.sort(key=lambda x: (-x["rank"], x["prio"]))
    return out


def pick_headline(act: dict[str, Any], acts: list[dict[str, Any]], *, imperial: bool,
                  streak: dict[str, Any] | None = None, ring: dict[str, Any] | None = None,
                  verdict: str | None = None, planned_title: str | None = None) -> dict[str, Any]:
    """ONE headline for ``act`` (a compact activity) given the year of ``acts``.

    ``streak``: stats streak (current, today_done); ``ring``: ``progress.week_goal`` when this
    workout closed the week's goal; ``verdict``/``planned_title``: from ``workoutday.verdict``."""
    me = _row(act)
    name = str(act.get("name") or "Workout")[:40]
    if me is None:
        return {"kind": "logged", "text": f"Logged: {name}"[:HEADLINE_MAX], "value": None}
    others = [r for r in (_row(a) for a in acts) if r is not None and r["id"] != me["id"]]
    recs = records(me, others, imperial=imperial)
    if recs:
        r = recs[0]
        return {"kind": r["kind"], "text": r["text"][:HEADLINE_MAX], "value": r["value"], "weeks": r["weeks"]}
    n = int((streak or {}).get("current") or 0)
    if n in STREAK_MILESTONES and (streak or {}).get("today_done", True):
        return {"kind": "streak", "text": f"{n}-day streak! A new milestone", "value": str(n)}
    if ring and ring.get("target"):
        what = "planned sessions" if ring.get("kind") == "plan" else "workouts"
        return {"kind": "ring", "text": f"Week closed: {ring['done']} of {ring['target']} {what}",
                "value": f"{ring['done']}/{ring['target']}"}
    if verdict == "nailed":
        title = str(planned_title or "Your session")[:40]
        return {"kind": "nailed", "text": f"Nailed it: {title}, right on target"[:HEADLINE_MAX], "value": None}
    word = SPORT_WORD.get(me["sport"], "workout")
    return {"kind": "logged", "text": f"Logged: {name}"[:HEADLINE_MAX] if name != "Workout" else f"Another {word} in the bank",
            "value": None}


def chips(act: dict[str, Any], *, imperial: bool) -> list[dict[str, str]]:
    """2-3 stat chips: distance, time, then pace (run/hike/swim), speed (ride) or climbing."""
    sport = category(act.get("sport"))
    me = _row(act) or {"min": 0.0, "km": 0.0, "climb": 0.0}
    out: list[dict[str, str]] = []
    if me["km"] > 0:
        out.append({"label": "Distance", "value": fmt_distance(me["km"] * 1000, sport, imperial) or ""})
    if me["min"] > 0:
        out.append({"label": "Time", "value": fmt_duration(me["min"] * 60)})
    sec = me["min"] * 60
    if me["km"] > 0.2 and sec > 0 and sport in ("run", "hike"):
        per = sec / (me["km"] * (0.621371 if imperial else 1))
        out.append({"label": "Pace", "value": f"{_mmss(per)} /{'mi' if imperial else 'km'}"})
    elif me["km"] > 0.05 and sec > 0 and sport == "swim":
        per = sec / (me["km"] * 10 * (1.09361 if imperial else 1))
        out.append({"label": "Pace", "value": f"{_mmss(per)} /100{'yd' if imperial else 'm'}"})
    elif me["km"] > 0.2 and sec > 0 and sport == "bike":
        kmh = me["km"] / (sec / 3600)
        out.append({"label": "Speed", "value": f"{kmh * 0.621371:.1f} mph" if imperial else f"{kmh:.1f} km/h"})
    elif me["climb"] >= 50:
        out.append({"label": "Climb", "value": _value_text("climb", me, imperial)})
    return out[:3]


def build_reward(act: dict[str, Any], acts: list[dict[str, Any]], *, today: date, imperial: bool,
                 streak: dict[str, Any] | None, ring: dict[str, Any] | None, verdict: str | None,
                 planned_title: str | None, session_id: str | None, plan_xp: int,
                 ledger_xp: int, counted: bool, created: int) -> dict[str, Any]:
    """Pure: the stored reward payload. ``ledger_xp``: the progress ledger's total;
    ``counted``: whether the ledger already holds this workout's XP."""
    me = _row(act)
    minutes = me["min"] if me else 0.0
    wxp = workout_xp(minutes)
    gained = wxp + plan_xp
    after = ledger_xp + (0 if counted else gained)
    before = max(0, after - gained)
    head = pick_headline(act, acts, imperial=imperial, streak=streak, ring=ring, verdict=verdict,
                         planned_title=planned_title)
    return {
        "activity_id": act.get("activity_id"), "name": str(act.get("name") or "Workout")[:80],
        "sport": category(act.get("sport")), "date": str(act.get("date") or "")[:10],
        "headline": head, "chips": chips(act, imperial=imperial),
        "xp": {"gained": gained, "workout": wxp, "plan": plan_xp},
        "level": {"before": level_view(before), "after": level_view(after),
                  "level_up": level_of(after) > level_of(before)},
        "streak": int((streak or {}).get("current") or 0),
        "verdict": verdict, "session_id": session_id, "units": "imperial" if imperial else "metric",
        "created": created,
    }


def ring_closed(stats: dict[str, Any], act_day: date, today: date, matched: bool) -> dict[str, Any] | None:
    """The week's goal (``progress.week_goal``) when this workout is what closed it."""
    try:
        wg = week_goal(stats)
    except (KeyError, TypeError):
        return None
    monday = today - timedelta(days=today.weekday())
    if act_day < monday or not wg.get("target") or wg.get("done") != wg.get("target"):
        return None
    if wg.get("kind") == "plan" and not matched:
        return None
    return wg


# --------------------------------------------------------------- service ----
def agent_context(agent: Any, uid: str, aid: int) -> dict[str, Any] | None:
    """Everything ``build_reward`` needs, from the agent's cached reads (no model call)."""
    from .workoutday import _by_id, _planned_week, build_reaction
    from .weekplan import merge
    today, acts = agent.stats.activities(uid)
    act = _by_id(acts or [], aid)
    if act is None:
        return None
    stats = agent.stats.get(uid)
    athlete = agent.coach.athlete(uid)
    plan = agent.plans.get(uid) if getattr(agent, "plans", None) is not None else None
    goal = agent.coach.active_goal(uid)
    try:
        day = date.fromisoformat(str(act.get("date") or "")[:10])
    except ValueError:
        day = today
    start, planned, _w = _planned_week(agent, uid, plan, goal, day)
    days = merge(start, max(today, day), planned, acts)
    dview = next((d for d in days if d["date"] == day.isoformat()), None)
    r = build_reaction(act, acts, dview, plan=plan, athlete=athlete, today=today,
                       streak=stats.get("streak") or {}, gear=[], tomorrow=None)
    matched = r.get("planned") is not None
    return {"act": act, "acts": acts, "today": today, "imperial": athlete.get("units") == "imperial",
            "streak": stats.get("streak") or {}, "ring": ring_closed(stats, day, today, matched),
            "verdict": r.get("verdict"), "planned_title": (r.get("planned") or {}).get("title"),
            "session_id": r.get("session_id"), "plan_xp": int((r.get("xp") or {}).get("plan") or 0)}


class Rewards:
    """Builds, stores and hands out post-workout rewards (``rewards`` doc per user)."""

    def __init__(self, store: "AppStore", *, now: Callable[[str], datetime],
                 context: Callable[[str, int], dict[str, Any] | None],
                 clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._now = now
        self._context = context
        self._clock = clock

    def _doc(self, uid: str):
        return self._s.user_doc(uid, "rewards")

    def on_workouts(self, uid: str, raw: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Fresh raw Garmin summaries (``Moments.workouts``): reward the newest, once."""
        if uid.startswith("coach_"):
            return None
        ids = [a.get("activityId") for a in raw if isinstance(a, dict) and not a.get("parentId")]
        ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
        if not ids:
            return None
        aid = max(ids)
        d = self._doc(uid).load()
        if str(aid) in (d.get("items") or {}) or str(aid) in (d.get("seen") or {}):
            return None
        ctx = self._context(uid, aid)
        if ctx is None:
            return None
        led = self._s.user_doc(uid, "progress").load()
        payload = build_reward(ctx["act"], ctx["acts"], today=ctx["today"], imperial=ctx["imperial"],
                               streak=ctx["streak"], ring=ctx["ring"], verdict=ctx["verdict"],
                               planned_title=ctx["planned_title"], session_id=ctx["session_id"],
                               plan_xp=ctx["plan_xp"], ledger_xp=int(led.get("xp") or 0),
                               counted=str(aid) in (led.get("acts") or {}), created=int(self._clock()))

        def put(doc: dict[str, Any]) -> bool:
            items = doc.setdefault("items", {})
            if str(aid) in items or str(aid) in (doc.get("seen") or {}):
                return False
            items[str(aid)] = payload
            for k in sorted(items, key=int)[:-KEEP_ITEMS]:
                del items[k]
            return True
        return payload if self._doc(uid).update(put) else None

    def _fresh(self, uid: str, item: dict[str, Any]) -> bool:
        try:
            day = date.fromisoformat(str(item.get("date") or ""))
        except ValueError:
            return False
        return (self._now(uid).date() - day).days < SHOW_DAYS

    def pending(self, uid: str) -> dict[str, Any] | None:
        """The newest unseen reward from the last few days (shown once on open)."""
        d = self._doc(uid).load()
        seen = d.get("seen") or {}
        live = [v for k, v in (d.get("items") or {}).items() if k not in seen and self._fresh(uid, v)]
        return max(live, key=lambda v: int(v.get("activity_id") or 0), default=None)

    def get(self, uid: str, aid: int) -> dict[str, Any] | None:
        d = self._doc(uid).load()
        item = (d.get("items") or {}).get(str(aid))
        return None if item is None else {**item, "seen": str(aid) in (d.get("seen") or {})}

    def seen(self, uid: str, aid: int) -> None:
        """Dismissed: this one and every older reward never pop up again."""
        stamp = self._now(uid).date().isoformat()

        def apply(d: dict[str, Any]) -> None:
            s = d.setdefault("seen", {})
            s[str(aid)] = stamp
            for k in d.get("items") or {}:
                if int(k) <= aid:
                    s.setdefault(k, stamp)
            for k in sorted(s, key=int)[:-KEEP_SEEN]:
                del s[k]
        self._doc(uid).update(apply)

    def claim_push(self, uid: str) -> tuple[str, str] | None:
        """(title, url) for the newest unseen, unpushed reward; once per activity."""
        r = self.pending(uid)
        if r is None:
            return None
        aid = str(r.get("activity_id"))

        def take(d: dict[str, Any]) -> bool:
            p = d.setdefault("pushed", [])
            if aid in p:
                return False
            p.append(aid)
            del p[:-KEEP_ITEMS]
            return True
        if not self._doc(uid).update(take):
            return None
        return str(r["headline"]["text"]), f"/app/?open=reward&activity={aid}"

    # ---------------------------------------------------------- monthly --
    def check_month(self, uid: str, *, acts: Callable[[str], tuple[date, list[dict[str, Any]]]],
                    post: Callable[[str, dict[str, Any]], str]) -> str:
        """From ``Moments.on_tick`` (outside quiet hours): the month moment on days 1-3."""
        if uid.startswith("coach_"):
            return "skipped"
        today = self._now(uid).date()
        if today.day > MONTH_MOMENT_DAYS:
            return "skipped"
        last = prev_month(today)

        def claim(d: dict[str, Any]) -> bool:
            m = d.setdefault("month", {})
            if m.get("done") == last.isoformat()[:7] or m.get("tried") == today.isoformat():
                return False
            m["tried"] = today.isoformat()
            return True
        if not self._doc(uid).update(claim):
            return "skipped"
        _today, rows = acts(uid)
        rec = month_recap(rows, last, today, imperial=False)
        self._doc(uid).update(lambda d: d.setdefault("month", {}).update(done=last.isoformat()[:7]))
        if not rec["sessions"]:
            return "empty"
        return post(uid, month_moment(rec))


# ---------------------------------------------------------------- month ----
def prev_month(today: date) -> date:
    first = today.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def month_end(start: date) -> date:
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


def parse_month(raw: str | None, today: date) -> date:
    """``YYYY-MM`` within the last ``MONTHS_BACK`` months (this month too); default last month."""
    if not raw:
        return prev_month(today)
    try:
        y, m = (int(x) for x in str(raw).split("-"))
        start = date(y, m, 1)
    except (ValueError, TypeError):
        raise ValueError("month must be YYYY-MM") from None
    this = today.replace(day=1)
    oldest = this
    for _ in range(MONTHS_BACK):
        oldest = prev_month(oldest)
    if start > this or start < oldest:
        raise ValueError(f"Monthly recaps cover the last {MONTHS_BACK} months.")
    return start


def month_recap(acts: list[dict[str, Any]], start: date, today: date, *, imperial: bool,
                top_club: str | None = None) -> dict[str, Any]:
    """Totals for the month starting ``start`` (up to today for the current month). No
    names, places or health data: hours, sessions, longest (sport + minutes), best streak,
    top sport, top club, hours per Monday-start week."""
    end = month_end(start)
    last = min(end, today)
    rows = [r for r in _rows(acts) if start <= r["date"] <= last]
    hours = sum(r["min"] for r in rows) / 60
    by_sport: dict[str, float] = {}
    for r in rows:
        by_sport[r["sport"]] = by_sport.get(r["sport"], 0.0) + r["min"]
    top = sorted(by_sport.items(), key=lambda kv: (-kv[1], kv[0]))
    longest = max(rows, key=lambda r: (r["min"], -r["date"].toordinal()), default=None)
    streak = _streaks({r["date"] for r in rows}, last)["best"] if rows else 0
    weeks = []
    ws = start - timedelta(days=start.weekday())
    while ws <= end:
        we = ws + timedelta(days=6)
        mins = sum(r["min"] for r in rows if max(ws, start) <= r["date"] <= min(we, end))
        weeks.append({"start": ws.isoformat(), "hours": round(mins / 60, 1)})
        ws += timedelta(days=7)
    return {
        "month": start.isoformat()[:7], "label": start.strftime("%B"), "year": start.year,
        "partial": last < end, "units": "imperial" if imperial else "metric",
        "hours": round(hours, 1), "sessions": len(rows), "active_days": len({r["date"] for r in rows}),
        "longest": {"sport": longest["sport"], "minutes": round(longest["min"])} if longest and longest["min"] else None,
        "best_streak": streak,
        "top_sport": {"sport": top[0][0], "hours": round(top[0][1] / 60, 1)} if top else None,
        "top_club": top_club, "weeks": weeks,
    }


def month_moment(rec: dict[str, Any]) -> dict[str, Any]:
    h = rec["hours"]
    hours = f"{h:g} hour{'s' if h != 1 else ''}"
    text = f"📅 Your {rec['label']}: {rec['sessions']} sessions, {hours}. Your recap card is ready to share."
    return {"type": "month", "key": f"month:{rec['month']}", "text": text[:140],
            "actions": [action("month_recap", f"See your {rec['label']}", month=rec["month"])]}


def top_club_of(store: "AppStore", clubs: Any, uid: str, start: date, end: date) -> str | None:
    """The club ``uid`` posted to most between ``start`` and ``end`` (local dates, compared
    as UTC days: close enough for a monthly card), else their first club by name."""
    try:
        ids = [c for c in clubs.ids_of(uid) if not c.startswith("r-")]
    except Exception:
        return None
    if not ids:
        return None
    lo = datetime(start.year, start.month, start.day).timestamp()
    hi = datetime(end.year, end.month, end.day).timestamp() + 86400
    counts: dict[str, int] = {}
    for p in (store.user_doc(uid, "posts").load().get("posts") or {}).values():
        aud = str(p.get("audience") or "")
        if aud.startswith("club:") and lo <= _num(p.get("created")) < hi and aud[5:] in ids:
            counts[aud[5:]] = counts.get(aud[5:], 0) + 1
    names = {c: clubs.name_of(c, uid) for c in ids}
    pick = sorted(ids, key=lambda c: (-counts.get(c, 0), str(names.get(c) or "")))[0]
    return names.get(pick)


__all__ = ["Rewards", "agent_context", "build_reward", "chips", "month_moment", "month_recap", "parse_month",
           "month_end", "pick_headline", "prev_month", "records", "ring_closed", "top_club_of", "MIN_WEEKS"]
