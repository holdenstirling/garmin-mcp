"""Weekly and monthly challenges: small, personal, sport-agnostic goals from Garmin workouts.

Catalog
-------
``TEMPLATES`` maps a template id to a metric over a period (``week`` = Monday-Sunday,
``month`` = calendar month, both in the athlete's local time; Garmin's ``startTimeLocal``
is already local). Metrics: workouts, active_days, minutes, distance_km (optional sport),
climb_m, long_session (one session of at least X min), early_sessions (start before 7 am),
sports_variety (distinct sports), streak_days (longest run of training days inside the
period), strength_sessions and plan_adherence (% of the period's planned sessions done;
only with a built plan). Targets are stored in canonical units (minutes, km, m) and the app
formats them in the athlete's units.

Personalization
---------------
* Baseline: the 6 complete Monday-start weeks before this week. Weekly value = median of
  those weeks; monthly = weekly median x days/7 for additive metrics (long session and
  streak use the 6-week best, variety the distinct sports of the last 4 weeks).
* Target = baseline x factor (easy 1.1, fun 1.15, stretch 1.25), rounded to friendly
  numbers with per-metric floors (a starter target when there's no history) and caps.
* Interests (``athlete.interests``, ``favorite_sports``) order the stretch/fun picks and
  pick the distance sport. A current ``injuries`` note keeps stretch volume at x1.1.
* Calm mode: a check-in pain flag in the last 7 days, a taper/race plan week or a race
  within 7 days -> no volume challenges (only plan adherence; strength while tapering).
  Sleep/rest aren't trackable from Garmin workouts and an "easy-only week" isn't reliably
  computable from compact activities, so neither is offered.

Each period offers up to 3 suggestions (easy, stretch, fun), rotated by period so they
change week to week. An athlete joins at most ``MAX_JOINED`` per period kind. Progress is
always computed live from ``StatsService.activities`` (cached); completion is recorded the
first time it's seen and earns XP once through the progress ledger's bonus keys
(``challenge:<id>``: +75 weekly, +150 monthly). The "challenge streak" counts consecutive
periods with a completed challenge.

Friends: a joined challenge can be shared with athletes the owner follows (active edge).
The global ``challenge_groups`` doc keys a group by the owner's challenge id; invitees see
it in their challenges card and can join the same template/target. Only participants see
the leaderboard (progress % and first names, nothing else).

Storage: per user ``challenges`` doc ``{"joined": [...], "history": [...]}`` (history: last
``KEEP_HISTORY``), global ``challenge_groups`` doc ``{"groups": {id: {...}}}``.
"""

from __future__ import annotations

import calendar
import math
import re
import secrets
import statistics
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .appstore import AppStore
from .planbuilder import week_for
from .stats import _rows
from .weekplan import merge

if TYPE_CHECKING:
    from .agent import Agent

MAX_JOINED = 2           # per period kind (2 weekly + 2 monthly)
KEEP_HISTORY = 52
XP = {"week": 75, "month": 150}
BASELINE_WEEKS = 6
EARLY_HOUR = 7
MAX_INVITES = 10         # per call
MAX_PARTICIPANTS = 10
BONUS_DAYS = 120         # completions this recent are passed to the XP ledger
FACTORS = {"easy": 1.1, "fun": 1.15, "stretch": 1.25}
EVEREST_M = 8848
_ID = re.compile(r"^[0-9a-f]{12}$")
_UID = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")

VOLUME = {"workouts", "active_days", "minutes", "distance_km", "climb_m", "long_session", "streak_days",
          "early_sessions"}
ADDITIVE = {"workouts", "active_days", "minutes", "distance_km", "climb_m", "early_sessions",
            "strength_sessions"}

# id -> (period, metric, name). Names are short; the app adds the formatted target.
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "w_workouts": ("week", "workouts", "Consistency week"),
    "w_active_days": ("week", "active_days", "Show up"),
    "w_minutes": ("week", "minutes", "Time in the bank"),
    "w_distance": ("week", "distance_km", "Distance week"),
    "w_climb": ("week", "climb_m", "Climb the Flatirons"),
    "w_long": ("week", "long_session", "Long one"),
    "w_streak": ("week", "streak_days", "Days in a row"),
    "w_early": ("week", "early_sessions", "Dawn patrol"),
    "w_strength": ("week", "strength_sessions", "Strength matters"),
    "w_variety": ("week", "sports_variety", "Mix it up"),
    "w_plan": ("week", "plan_adherence", "By the book"),
    "m_workouts": ("month", "workouts", "Consistency month"),
    "m_active_days": ("month", "active_days", "Show-up month"),
    "m_minutes": ("month", "minutes", "Hours month"),
    "m_distance": ("month", "distance_km", "Distance month"),
    "m_climb": ("month", "climb_m", "Vertical month"),
    "m_long": ("month", "long_session", "Long one"),
    "m_streak": ("month", "streak_days", "Streak month"),
    "m_early": ("month", "early_sessions", "Dawn patrol"),
    "m_strength": ("month", "strength_sessions", "Strength matters"),
    "m_variety": ("month", "sports_variety", "Mix it up"),
    "m_plan": ("month", "plan_adherence", "By the book"),
}
POOLS = {  # suggestion slots, in default preference order (metric names)
    "easy": ["workouts", "active_days", "plan_adherence"],
    "stretch": ["minutes", "distance_km", "climb_m"],
    "fun": ["sports_variety", "long_session", "early_sessions", "strength_sessions", "streak_days"],
}
SPORT_NAMES = {"run": "Run", "bike": "Ride", "swim": "Swim", "hike": "Hike", "ski": "Ski", "paddle": "Paddle"}
FAV_SPORT = {"run": "run", "trail": "run", "bike": "bike", "gravel": "bike", "mtb": "bike", "swim": "swim",
             "open_water": "swim", "hike": "hike", "walk": "hike", "ski": "ski", "row": "paddle"}
# interest keyword -> metric it makes more appealing
INTEREST_METRICS: list[tuple[str, str]] = [
    (r"climb|mountain|vert|hill|trail|ski|hike|alpin|fourteener|14er", "climb_m"),
    (r"strength|gym|lift|weights|core|yoga|pilates", "strength_sessions"),
    (r"variety|cross|multi|tri|explor|new sport|adventure", "sports_variety"),
    (r"early|morning|dawn|sunrise", "early_sessions"),
    (r"long|ultra|endurance|epic|all.?day", "long_session"),
    (r"streak|habit|consisten|daily", "streak_days"),
]


class ChallengeError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------ periods --
def period_bounds(period: str, today: date) -> tuple[date, date]:
    """Monday-Sunday week or calendar month containing ``today`` (local date)."""
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        last = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last)
    raise ChallengeError("period must be week or month")


def local_today(now: datetime) -> date:
    """The athlete's local date (``now`` is already in their zone, as ``Agent._now`` returns)."""
    return now.date()


# ------------------------------------------------------------------ metrics --
def _longest_run(days: set[date]) -> int:
    best = run = 0
    prev: date | None = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def _planned_pct(plan: dict[str, Any] | None, acts: list[dict[str, Any]], start: date, end: date,
                 today: date) -> float:
    """% of the period's planned sessions done (planned for the whole period; done to date)."""
    if not plan:
        return 0.0
    done = planned = 0
    monday = start - timedelta(days=start.weekday())
    while monday <= end:
        w = week_for(plan, monday)
        if w is not None:
            days = {d: [{"sport": s["sport"], "title": s.get("title"), "minutes": s.get("minutes")} for s in ss]
                    for d, ss in (w.get("days") or {}).items()}
            for day in merge(monday, today, days, acts):
                if not (start.isoformat() <= day["date"] <= end.isoformat()):
                    continue
                for s in day["sessions"]:
                    if s["status"] == "rest":
                        continue
                    planned += 1
                    done += s["status"] == "done"
        monday += timedelta(days=7)
    return round(100 * done / planned, 1) if planned else 0.0


def value(metric: str, rows: list[dict[str, Any]], start: date, end: date, *, sport: str | None = None,
          plan: dict[str, Any] | None = None, acts: list[dict[str, Any]] | None = None,
          today: date | None = None) -> float:
    """The metric over ``rows`` (``stats._rows``) dated ``start..end`` inclusive."""
    rs = [r for r in rows if start <= r["date"] <= end]
    if sport:
        rs_s = [r for r in rs if r["sport"] == sport]
    else:
        rs_s = rs
    if metric == "workouts":
        return float(len(rs))
    if metric == "active_days":
        return float(len({r["date"] for r in rs}))
    if metric == "minutes":
        return round(sum(r["min"] for r in rs), 1)
    if metric == "distance_km":
        return round(sum(r["km"] for r in rs_s), 2)
    if metric == "climb_m":
        return float(round(sum(r["climb"] for r in rs)))
    if metric == "long_session":
        return round(max((r["min"] for r in rs), default=0.0), 1)
    if metric == "early_sessions":
        return float(sum(1 for r in rs if r.get("hour") is not None and r["hour"] < EARLY_HOUR))
    if metric == "sports_variety":
        return float(len({r["sport"] for r in rs} - {"other"}))
    if metric == "streak_days":
        return float(_longest_run({r["date"] for r in rs}))
    if metric == "strength_sessions":
        return float(sum(1 for r in rs if r["sport"] == "strength"))
    if metric == "plan_adherence":
        return _planned_pct(plan, acts or [], start, end, today or end)
    raise ChallengeError("unknown metric")


def _baseline_weeks(today: date) -> list[tuple[date, date]]:
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(weeks=i), monday - timedelta(weeks=i) + timedelta(days=6))
            for i in range(BASELINE_WEEKS, 0, -1)]


def baseline(metric: str, period: str, rows: list[dict[str, Any]], today: date,
             sport: str | None = None) -> float:
    """What the athlete typically does in such a period, from the last 6 complete weeks."""
    weeks = _baseline_weeks(today)
    vals = [value(metric, rows, s, e, sport=sport) for s, e in weeks]
    if period == "week":
        return float(statistics.median(vals))
    start, end = period_bounds("month", today)
    days = (end - start).days + 1
    if metric in ADDITIVE:
        return float(statistics.median(vals)) * days / 7
    if metric in ("long_session", "streak_days"):
        return float(max(vals, default=0))
    if metric == "sports_variety":
        return value(metric, rows, weeks[-4][0], weeks[-1][1])
    return float(statistics.median(vals))


# (week floor, month floor, week cap, month cap, rounding step)
_SHAPE: dict[str, tuple[float, float, float, float, float]] = {
    "workouts": (2, 6, 14, 60, 1),
    "active_days": (2, 6, 7, 31, 1),
    "minutes": (60, 240, 1200, 4800, 15),
    "distance_km": (5, 15, 400, 1600, 5),
    "climb_m": (300, 1000, 8000, 30000, 100),
    "long_session": (45, 60, 600, 720, 15),
    "early_sessions": (1, 2, 7, 25, 1),
    "sports_variety": (2, 2, 4, 5, 1),
    "streak_days": (2, 3, 7, 21, 1),
    "strength_sessions": (1, 3, 5, 20, 1),
}


def scale_target(metric: str, period: str, base: float, factor: float, *, days: int = 7) -> float:
    """Baseline x factor, rounded up to a friendly step, within floors and caps."""
    if metric == "plan_adherence":
        return 100.0 if factor >= FACTORS["stretch"] else 80.0 if factor <= 1.0 else 90.0
    wf, mf, wc, mc, step = _SHAPE[metric]
    floor, cap = (wf, wc) if period == "week" else (mf, mc)
    if metric == "active_days" and period == "month":
        cap = days
    if metric == "long_session":
        factor = min(factor, 1.15)  # +25% on the longest session is a lot
    if metric == "sports_variety":
        raw = base + 1 if factor > 1.0 else base
    else:
        raw = base * factor
    if metric == "distance_km" and raw < 20:
        step = 1
    t = math.ceil(raw / step - 1e-9) * step
    if factor > 1.0 and base > 0 and step == 1 and t <= base:
        t = math.floor(base) + 1
    return float(min(max(t, floor), cap))


# --------------------------------------------------------------- suggestions --
def _interest_metrics(athlete: dict[str, Any]) -> list[str]:
    words = [str(x).lower() for x in (athlete.get("interests") or []) if isinstance(x, str)]
    words += [str(x).lower() for x in (athlete.get("favorite_sports") or []) if isinstance(x, str)]
    text = " ".join(words)
    return [m for rx, m in INTEREST_METRICS if re.search(rx, text)]


def _distance_sport(rows: list[dict[str, Any]], athlete: dict[str, Any], today: date) -> str | None:
    s, _ = _baseline_weeks(today)[0]
    recent = [r for r in rows if s <= r["date"] < today - timedelta(days=today.weekday())]
    km: dict[str, float] = {}
    for r in recent:
        if r["sport"] in SPORT_NAMES and r["km"] > 0:
            km[r["sport"]] = km.get(r["sport"], 0.0) + r["km"]
    favs = [FAV_SPORT[f] for f in (athlete.get("favorite_sports") or []) if f in FAV_SPORT]
    for f in favs:
        if km.get(f):
            return f
    return max(km, key=lambda k: km[k]) if km else None


def _calm_reason(*, pain: bool, phase: str | None, race_soon: bool) -> str | None:
    if pain:
        return "Something hurt in a recent check-in, so no volume challenges this week."
    if phase in ("taper", "race") or race_soon:
        return "Race week or taper: the challenge is to rest well, so no volume challenges."
    return None


def suggest(period: str, today: date, rows: list[dict[str, Any]], *, athlete: dict[str, Any] | None = None,
            plan: dict[str, Any] | None = None, pain: bool = False, race_soon: bool = False,
            exclude: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """Up to 3 suggestions for the period containing ``today`` (easy, stretch, fun)."""
    athlete = athlete or {}
    start, end = period_bounds(period, today)
    days = (end - start).days + 1
    pw = week_for(plan, today) if plan else None
    phase = (pw or {}).get("phase")
    calm = _calm_reason(pain=pain, phase=phase, race_soon=race_soon)
    b0 = _baseline_weeks(today)[0][0]
    b1 = today - timedelta(days=today.weekday() + 1)  # last Sunday: the baseline's end
    has_history = any(b0 <= r["date"] <= b1 for r in rows)
    likes = _interest_metrics(athlete)
    injured = bool(str(athlete.get("injuries") or "").strip())
    dsport = _distance_sport(rows, athlete, today)
    ordinal = (start.toordinal() // 7) if period == "week" else (start.year * 12 + start.month)
    prefix = "w_" if period == "week" else "m_"

    def item(metric: str, kind: str, factor: float) -> dict[str, Any] | None:
        tid = prefix + {"workouts": "workouts", "active_days": "active_days", "minutes": "minutes",
                        "distance_km": "distance", "climb_m": "climb", "long_session": "long",
                        "streak_days": "streak", "early_sessions": "early", "strength_sessions": "strength",
                        "sports_variety": "variety", "plan_adherence": "plan"}[metric]
        if tid in exclude:
            return None
        sport = dsport if metric == "distance_km" else None
        if metric == "distance_km" and not sport:
            return None
        if metric == "plan_adherence" and not plan:
            return None
        base = 0.0 if metric == "plan_adherence" else baseline(metric, period, rows, today, sport)
        target = scale_target(metric, period, base, factor, days=days)
        name = TEMPLATES[tid][2]
        if metric == "distance_km" and sport:
            name = f"{SPORT_NAMES[sport]} {'week' if period == 'week' else 'month'}"
        if metric == "climb_m" and period == "month" and 7000 <= target <= 11000:
            target, name = float(EVEREST_M), "Everest month"
        if calm and metric == "plan_adherence":
            name = "Stick to the taper" if "taper" in calm.lower() or "race" in calm.lower() else "Easy does it"
        if metric == "plan_adherence":
            why = "Planned sessions in your built plan"
        elif has_history and base > 0:
            why = f"Based on your last {BASELINE_WEEKS} weeks"
        else:
            why = "A starter target"
        return {"template": tid, "period": period, "metric": metric, "sport": sport, "name": name,
                "target": target, "baseline": round(base, 1), "kind": kind, "why": why, "xp": XP[period],
                "period_start": start.isoformat(), "period_end": end.isoformat()}

    out: list[dict[str, Any]] = []
    if calm:
        for metric in ["plan_adherence"] + ([] if pain else ["strength_sessions"]):
            x = item(metric, "easy", 1.0)
            if x:
                out.append(x)
        return {"items": out, "notice": calm}

    def eligible(metric: str) -> bool:
        if metric == "climb_m":
            return baseline("climb_m", "week", rows, today) >= 150 or "climb_m" in likes
        if metric == "early_sessions":
            return value("early_sessions", rows, b0, b1) > 0 \
                or "early_sessions" in likes
        if metric == "strength_sessions":
            return baseline("strength_sessions", "week", rows, today) > 0 or "strength_sessions" in likes
        if metric == "sports_variety":
            return value("sports_variety", rows, b0, b1) >= 2 \
                or "sports_variety" in likes
        if metric == "distance_km":
            return dsport is not None
        if metric == "plan_adherence":
            return plan is not None
        return True

    for kind in ("easy", "stretch", "fun"):
        pool = [m for m in POOLS[kind] if eligible(m)]
        liked = [m for m in pool if m in likes]
        pick_from = liked or pool
        factor = FACTORS[kind]
        if injured and kind == "stretch":
            factor = FACTORS["easy"]
        for i in range(len(pick_from)):
            m = pick_from[(ordinal + i) % len(pick_from)]
            if any(x["metric"] == m for x in out):
                continue
            x = item(m, kind, factor)
            if x:
                out.append(x)
                break
    return {"items": out, "notice": None}


# --------------------------------------------------------------- the store --
def _new_id() -> str:
    return secrets.token_hex(6)


class Challenges:
    def __init__(self, store: AppStore, *, now: Callable[[str], datetime],
                 activities: Callable[[str], tuple[date, list[dict[str, Any]]]],
                 athlete: Callable[[str], dict[str, Any]] = lambda uid: {},
                 plan: Callable[[str], dict[str, Any] | None] = lambda uid: None,
                 checkins: Callable[[str], list[dict[str, Any]]] = lambda uid: [],
                 events: Callable[[str], list[dict[str, Any]]] = lambda uid: [],
                 follows: Callable[[str, str], bool] | None = None,
                 names: Callable[[str], str] = lambda uid: "Friend",
                 clock: Callable[[], float] = time.time) -> None:
        self._s = store
        self._now = now
        self._acts = activities
        self._athlete = athlete
        self._plan = plan
        self._checkins = checkins
        self._events = events
        self._follows = follows
        self._names = names
        self._clock = clock
        self._glock = threading.Lock()

    # ---------------------------------------------------------------- docs --
    def _doc(self, uid: str):
        return self._s.user_doc(uid, "challenges")

    def _groups(self):
        return self._s.global_doc("challenge_groups")

    @staticmethod
    def _require(uid: str) -> None:
        if uid.startswith("coach_"):
            raise ChallengeError("Challenges are for athletes.", 403)

    def _stamp(self, uid: str) -> str:
        """Now in the athlete's zone (so ``[:10]`` is their local date)."""
        return self._now(uid).isoformat(timespec="seconds")

    # ------------------------------------------------------------- context --
    def _safe(self, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception:
            return default

    def _ctx(self, uid: str, acts: list[dict[str, Any]] | None = None,
             today: date | None = None) -> dict[str, Any]:
        if acts is None:
            today2, acts = self._acts(uid)
            today = today or today2
        today = today or local_today(self._now(uid))
        rows = [r for r in _rows(acts) if r["date"] <= today]
        plan = self._safe(lambda: self._plan(uid), None)
        return {"today": today, "acts": acts, "rows": rows, "plan": plan}

    def _mode(self, uid: str, today: date) -> dict[str, bool]:
        recent = (today - timedelta(days=7)).isoformat()
        pain = any(c.get("pain_flag") and str(c.get("date") or "") >= recent
                   for c in self._safe(lambda: self._checkins(uid), []) or [])
        soon = (today + timedelta(days=7)).isoformat()
        race_soon = any(today.isoformat() <= str(e.get("date") or "")[:10] <= soon
                        for e in self._safe(lambda: self._events(uid), []) or [])
        return {"pain": pain, "race_soon": race_soon}

    def _progress(self, c: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        start, end = date.fromisoformat(c["period_start"]), date.fromisoformat(c["period_end"])
        v = value(c["metric"], ctx["rows"], start, min(end, ctx["today"]), sport=c.get("sport"),
                  plan=ctx["plan"], acts=ctx["acts"], today=ctx["today"]) if start <= ctx["today"] else 0.0
        tgt = float(c["target"]) or 1.0
        return {"value": v, "pct": round(min(100.0, 100 * v / tgt)), "done": v >= tgt}

    # ------------------------------------------------------------- refresh --
    def _sync(self, uid: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Record completions, move past periods to history. Returns the doc snapshot."""
        today = ctx["today"]
        progress = {c["id"]: self._progress(c, ctx) for c in self._doc(uid).load().get("joined") or []}

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            joined = d.setdefault("joined", [])
            hist = d.setdefault("history", [])
            keep = []
            for c in joined:
                p = progress.get(c["id"])
                if p is not None and p["done"] and not c.get("completed_at"):
                    c["completed_at"] = self._stamp(uid)
                if c["period_end"] < today.isoformat():
                    if p is not None:
                        c["final"] = p["value"]
                    hist.append(c)
                else:
                    keep.append(c)
            d["joined"] = keep
            hist.sort(key=lambda c: (c["period_end"], c.get("joined_at") or ""))
            del hist[:-KEEP_HISTORY]
            return {"joined": [dict(c) for c in keep], "history": [dict(c) for c in hist]}
        return self._doc(uid).update(apply)

    def refresh(self, uid: str, *, acts: list[dict[str, Any]] | None = None,
                today: date | None = None) -> dict[str, int]:
        """Mark completions and return the progress-ledger bonus keys (``challenge:<id>``)."""
        if uid.startswith("coach_"):
            return {}
        snap = self._sync(uid, self._ctx(uid, acts, today))
        t = today or local_today(self._now(uid))
        since = (t - timedelta(days=BONUS_DAYS)).isoformat()
        return {f"challenge:{c['id']}": XP.get(c["period"], 0)
                for c in snap["joined"] + snap["history"]
                if c.get("completed_at") and c["period_end"] >= since}

    # --------------------------------------------------------------- views --
    @staticmethod
    def streaks(items: list[dict[str, Any]], today: date) -> dict[str, int]:
        """Consecutive periods (weeks / months) with a completed challenge, ending this period
        if it's done already, else the last one."""
        out = {}
        for period in ("week", "month"):
            done = {c["period_start"] for c in items if c["period"] == period and c.get("completed_at")}
            start, _ = period_bounds(period, today)
            n = 0
            cur = start
            if cur.isoformat() not in done:
                cur = _prev(period, cur)
            while cur.isoformat() in done:
                n += 1
                cur = _prev(period, cur)
            out[period] = n
        return out

    def _view(self, c: dict[str, Any], ctx: dict[str, Any], uid: str) -> dict[str, Any]:
        p = self._progress(c, ctx)
        end = date.fromisoformat(c["period_end"])
        out = {k: c.get(k) for k in ("id", "template", "period", "period_start", "period_end", "target", "metric",
                                      "sport", "name", "joined_at", "completed_at", "group")}
        out.update(value=p["value"], pct=p["pct"], done=bool(c.get("completed_at")) or p["done"],
                   days_left=max(0, (end - ctx["today"]).days), xp=XP[c["period"]])
        if c.get("group"):
            out["leaderboard"] = self._leaderboard(uid, c["group"], ctx)
        return out

    def _leaderboard(self, uid: str, gid: str, ctx: dict[str, Any]) -> list[dict[str, Any]] | None:
        g = (self._groups().load().get("groups") or {}).get(gid)
        if not g or uid not in g.get("participants", []):
            return None
        rows = []
        for p in g["participants"][:MAX_PARTICIPANTS]:
            if p == uid:
                pctx = ctx
            else:
                try:
                    today, acts = self._acts(p)
                    pctx = self._ctx(p, acts, ctx["today"])
                except Exception:
                    rows.append({"user_id": p, "name": self._names(p), "pct": None, "me": False})
                    continue
            prog = self._progress({**g, "sport": g.get("sport")}, pctx)
            rows.append({"user_id": p, "name": self._names(p), "pct": prog["pct"], "me": p == uid})
        rows.sort(key=lambda r: (-(r["pct"] if r["pct"] is not None else -1), not r["me"]))
        return rows

    def _invites(self, uid: str, today: date) -> list[dict[str, Any]]:
        out = []
        for g in (self._groups().load().get("groups") or {}).values():
            if uid in (g.get("invited") or {}) and uid not in g.get("participants", []) \
                    and g["period_end"] >= today.isoformat():
                out.append({"id": g["id"], "from": {"id": g["owner"], "name": self._names(g["owner"])},
                            "name": g["name"], "template": g["template"], "period": g["period"],
                            "metric": g["metric"], "sport": g.get("sport"), "target": g["target"],
                            "period_end": g["period_end"], "participants": len(g.get("participants", [])),
                            "xp": XP[g["period"]]})
        return out

    def get(self, uid: str) -> dict[str, Any]:
        self._require(uid)
        ctx = self._ctx(uid)
        today = ctx["today"]
        snap = self._sync(uid, ctx)
        mode = self._mode(uid, today)
        athlete = self._safe(lambda: self._athlete(uid), {}) or {}
        periods = {}
        for period in ("week", "month"):
            start, end = period_bounds(period, today)
            mine = [c for c in snap["joined"] if c["period"] == period]
            s = suggest(period, today, ctx["rows"], athlete=athlete, plan=ctx["plan"],
                        exclude={c["template"] for c in mine}, **mode)
            periods[period] = {"start": start.isoformat(), "end": end.isoformat(),
                               "days_left": (end - today).days, "joined": len(mine), "limit": MAX_JOINED,
                               "suggestions": s["items"], "notice": s["notice"]}
        recent = [{"id": c["id"], "name": c["name"], "period": c["period"], "metric": c["metric"],
                   "sport": c.get("sport"), "target": c["target"], "period_start": c["period_start"],
                   "completed_at": c["completed_at"]}
                  for c in reversed(snap["history"]) if c.get("completed_at")][:5]
        return {"today": today.isoformat(), "periods": periods,
                "joined": [self._view(c, ctx, uid) for c in snap["joined"]],
                "recent": recent, "streak": self.streaks(snap["joined"] + snap["history"], today),
                "invites": self._invites(uid, today), "can_invite": self._follows is not None, "xp": XP}

    # ------------------------------------------------------------- actions --
    def _add(self, uid: str, c: dict[str, Any]) -> dict[str, Any]:
        def apply(d: dict[str, Any]) -> dict[str, Any]:
            joined = d.setdefault("joined", [])
            mine = [x for x in joined if x["period"] == c["period"] and x["period_start"] == c["period_start"]]
            if any(x["template"] == c["template"] for x in mine):
                raise ChallengeError("You're already doing this challenge.", 409)
            if len(mine) >= MAX_JOINED:
                raise ChallengeError(f"You can join {MAX_JOINED} {c['period']}ly challenges at a time.", 409)
            joined.append(c)
            return c
        return self._doc(uid).update(apply)

    def join(self, uid: str, template: Any, period: Any) -> dict[str, Any]:
        self._require(uid)
        if period not in ("week", "month"):
            raise ChallengeError("period must be week or month")
        if not isinstance(template, str) or template not in TEMPLATES or TEMPLATES[template][0] != period:
            raise ChallengeError("Unknown challenge.")
        ctx = self._ctx(uid)
        athlete = self._safe(lambda: self._athlete(uid), {}) or {}
        s = suggest(period, ctx["today"], ctx["rows"], athlete=athlete, plan=ctx["plan"],
                    **self._mode(uid, ctx["today"]))
        pick = next((x for x in s["items"] if x["template"] == template), None)
        if pick is None:
            raise ChallengeError("That challenge isn't on offer right now.", 409)
        c = {"id": _new_id(), "template": template, "period": period, "period_start": pick["period_start"],
             "period_end": pick["period_end"], "target": pick["target"], "metric": pick["metric"],
             "sport": pick.get("sport"), "name": pick["name"], "joined_at": self._stamp(uid)}
        self._add(uid, c)
        return c

    def leave(self, uid: str, cid: Any) -> None:
        self._require(uid)
        if not isinstance(cid, str) or not _ID.match(cid):
            raise ChallengeError("Challenge not found.", 404)

        def apply(d: dict[str, Any]) -> dict[str, Any] | None:
            joined = d.setdefault("joined", [])
            c = next((x for x in joined if x["id"] == cid), None)
            if c is None:
                return None
            joined.remove(c)
            return c
        c = self._doc(uid).update(apply)
        if c is None:
            raise ChallengeError("Challenge not found.", 404)
        gid = c.get("group")
        if gid:
            def drop(d: dict[str, Any]) -> None:
                g = (d.get("groups") or {}).get(gid)
                if g and uid in g.get("participants", []):
                    g["participants"].remove(uid)
                    if not g["participants"]:
                        del d["groups"][gid]
            with self._glock:
                self._groups().update(drop)

    def invite(self, uid: str, cid: Any, user_ids: Any) -> dict[str, Any]:
        self._require(uid)
        if self._follows is None:
            raise ChallengeError("Friends aren't configured on this server.", 503)
        if not isinstance(cid, str) or not _ID.match(cid):
            raise ChallengeError("Challenge not found.", 404)
        if not isinstance(user_ids, list) or not user_ids or len(user_ids) > MAX_INVITES \
                or not all(isinstance(x, str) and _UID.match(x) for x in user_ids):
            raise ChallengeError(f"Pick 1 to {MAX_INVITES} friends.")
        today = local_today(self._now(uid))
        c = next((x for x in self._doc(uid).load().get("joined") or [] if x["id"] == cid), None)
        if c is None or c["period_end"] < today.isoformat():
            raise ChallengeError("Challenge not found.", 404)
        ids = list(dict.fromkeys(x for x in user_ids if x != uid))
        if not ids or any(x.startswith("coach_") or not self._follows(uid, x) for x in ids):
            raise ChallengeError("You can only invite friends you follow.", 403)
        gid = c.get("group") or cid
        stamp = self._stamp(uid)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            groups = d.setdefault("groups", {})
            for k in [k for k, g in groups.items() if g["period_end"] < (today - timedelta(days=7)).isoformat()]:
                del groups[k]
            g = groups.get(gid)
            if g is None:
                g = groups[gid] = {k: c.get(k) for k in ("template", "period", "period_start", "period_end",
                                                         "target", "metric", "sport", "name")}
                g.update(id=gid, owner=uid, participants=[uid], invited={})
            elif uid not in g["participants"]:
                raise ChallengeError("Challenge not found.", 404)
            if len(set(g["invited"]) | set(ids)) > 2 * MAX_PARTICIPANTS:
                raise ChallengeError("That's a lot of invites already.", 409)
            for x in ids:
                if x not in g["participants"]:
                    g["invited"].setdefault(x, stamp)
            return {"group": gid, "invited": sorted(g["invited"])}
        with self._glock:
            res = self._groups().update(apply)
        if not c.get("group"):
            def link(d: dict[str, Any]) -> None:
                for x in d.get("joined") or []:
                    if x["id"] == cid:
                        x["group"] = gid
            self._doc(uid).update(link)
        return res

    def accept(self, uid: str, gid: Any) -> dict[str, Any]:
        self._require(uid)
        if not isinstance(gid, str) or not _ID.match(gid):
            raise ChallengeError("Invite not found.", 404)
        today = local_today(self._now(uid))
        g = (self._groups().load().get("groups") or {}).get(gid)
        if not g or uid not in (g.get("invited") or {}) or g["period_end"] < today.isoformat() \
                or g["period_start"] > today.isoformat():
            raise ChallengeError("Invite not found.", 404)
        if self._follows is None or not self._follows(g["owner"], uid):
            raise ChallengeError("Invite not found.", 404)
        if len(g.get("participants", [])) >= MAX_PARTICIPANTS:
            raise ChallengeError("This challenge is full.", 409)
        c = {"id": _new_id(), "template": g["template"], "period": g["period"], "period_start": g["period_start"],
             "period_end": g["period_end"], "target": g["target"], "metric": g["metric"], "sport": g.get("sport"),
             "name": g["name"], "joined_at": self._stamp(uid), "group": gid}
        self._add(uid, c)

        def apply(d: dict[str, Any]) -> None:
            gg = (d.get("groups") or {}).get(gid)
            if gg is None:
                return
            gg["invited"].pop(uid, None)
            if uid not in gg["participants"]:
                gg["participants"].append(uid)
        with self._glock:
            self._groups().update(apply)
        return c

    def decline(self, uid: str, gid: Any) -> None:
        self._require(uid)
        if not isinstance(gid, str) or not _ID.match(gid):
            raise ChallengeError("Invite not found.", 404)

        def apply(d: dict[str, Any]) -> None:
            g = (d.get("groups") or {}).get(gid)
            if g:
                (g.get("invited") or {}).pop(uid, None)
        with self._glock:
            self._groups().update(apply)

    # -------------------------------------------------------------- recap --
    def week_summary(self, uid: str, start: date, *, acts: list[dict[str, Any]] | None = None,
                     today: date | None = None) -> dict[str, Any] | None:
        """Weekly challenges for the week at ``start`` (done / joined) plus any monthly ones
        completed that week. None when nothing was joined."""
        if uid.startswith("coach_"):
            return None
        try:
            ctx = self._ctx(uid, acts, today)
            snap = self._sync(uid, ctx)
        except Exception:
            return None
        items = snap["joined"] + snap["history"]
        end = start + timedelta(days=6)
        week = [c for c in items if c["period"] == "week" and c["period_start"] == start.isoformat()]
        month_done = [c for c in items if c["period"] == "month" and c.get("completed_at")
                      and start.isoformat() <= c["completed_at"][:10] <= end.isoformat()]
        if not week and not month_done:
            return None
        return {"done": sum(1 for c in week if c.get("completed_at")), "joined": len(week),
                "items": [{"name": c["name"], "period": c["period"], "done": bool(c.get("completed_at"))}
                          for c in week + month_done],
                "xp": sum(XP[c["period"]] for c in week + month_done if c.get("completed_at"))}


def _prev(period: str, start: date) -> date:
    if period == "week":
        return start - timedelta(days=7)
    return (start - timedelta(days=1)).replace(day=1)


def for_agent(agent: "Agent", *, follows: Callable[[str, str], bool] | None = None,
              names: Callable[[str], str] | None = None) -> Challenges:
    """A ``Challenges`` wired to the agent's store, clock, cached activities, plan, check-ins
    and events."""
    return Challenges(agent._store, now=agent._now, activities=lambda uid: agent.stats.activities(uid),
                      athlete=agent.coach.athlete, plan=agent.plans.get,
                      checkins=lambda uid: agent.checkins.list(uid, 10), events=agent.events.list,
                      follows=follows, names=names or (lambda uid: "Friend"), clock=agent._clock)


__all__ = ["Challenges", "ChallengeError", "TEMPLATES", "XP", "MAX_JOINED", "period_bounds", "local_today",
           "value", "baseline", "scale_target", "suggest", "for_agent"]
