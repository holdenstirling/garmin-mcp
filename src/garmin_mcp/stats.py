"""Rabbit's stats screen: streaks, totals, weekly volume, a training calendar, bests,
plan adherence and badges, computed from the athlete's Garmin activities.

Sport-agnostic: anything Garmin records counts as a workout, with or without a plan or
race. Pure functions over compact activities (``tools.compact_activity``); ``StatsService``
does the one cached Garmin read and caches the result for a few minutes.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .planbuilder import iter_sessions
from .weekplan import _seconds, merge, sport_of

if TYPE_CHECKING:
    from .tools import GarminService

KM_MI = 0.621371
M_FT = 3.28084
HISTORY_DAYS = 371  # a year plus a week, so year-over-year weeks line up
ACTIVE_WEEK = 3     # workouts that make a week "active" for the weekly streak
CACHE_S = 300

# Badge ladder: (id, title, description, metric, target)
BADGES: list[tuple[str, str, str, str, float]] = [
    ("first", "First step", "Log your first workout", "workouts_year", 1),
    ("streak3", "Three in a row", "Train 3 days in a row", "best_streak", 3),
    ("streak7", "Full week", "Train 7 days in a row", "best_streak", 7),
    ("streak30", "Unstoppable", "Train 30 days in a row", "best_streak", 30),
    ("weeks4", "Consistent", f"{ACTIVE_WEEK}+ workouts a week, 4 weeks running", "best_week_streak", 4),
    ("weeks12", "Habit formed", f"{ACTIVE_WEEK}+ workouts a week, 12 weeks running", "best_week_streak", 12),
    ("w50", "Fifty", "50 workouts in 12 months", "workouts_year", 50),
    ("w100", "Century club", "100 workouts in 12 months", "workouts_year", 100),
    ("w250", "Machine", "250 workouts in 12 months", "workouts_year", 250),
    ("h100", "100 hours", "100 hours of training in 12 months", "hours_year", 100),
    ("h300", "300 hours", "300 hours of training in 12 months", "hours_year", 300),
    ("climb10k", "Vertical mile x2", "10,000 m (32,800 ft) of climbing in 12 months", "climb_year_m", 10_000),
    ("climb30k", "Everest x3", "30,000 m of climbing in 12 months", "climb_year_m", 30_000),
    ("long3h", "Long haul", "One workout of 3 hours or more", "longest_min", 180),
    ("long6h", "All day", "One workout of 6 hours or more", "longest_min", 360),
    ("early", "Early bird", "10 workouts started before 7 am", "early_count", 10),
    ("multi", "All-rounder", "Train 3 or more different sports in a month", "max_sports_month", 3),
    ("plan_week", "By the book", "Complete every planned session in a plan week", "perfect_plan_weeks", 1),
]


def category(garmin_type: str | None) -> str:
    """Stats category: the plan sports plus the outdoor ones a plan doesn't schedule."""
    k = (garmin_type or "").lower()
    if any(w in k for w in ("ski", "snowboard", "snowshoe", "skate")):
        return "ski"
    if any(w in k for w in ("climb", "boulder", "mountaineer")):
        return "climb"
    if any(w in k for w in ("hik", "walk", "trek")):
        return "hike"
    if any(w in k for w in ("row", "paddl", "kayak", "sup", "canoe")):
        return "paddle"
    return sport_of(garmin_type)


def _rows(acts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = {a.get("activity_id") for a in acts if (a.get("multisport") or {}).get("is_parent")}
    rows = []
    for a in acts:
        if (a.get("multisport") or {}).get("parent_id") in parents:
            continue
        stamp = str(a.get("date") or "")
        try:
            d = date.fromisoformat(stamp[:10])
        except ValueError:
            continue
        hour = None
        try:
            hour = datetime.fromisoformat(stamp.replace(" ", "T")[:19]).hour if len(stamp) > 10 else None
        except ValueError:
            pass
        rows.append({"date": d, "sport": category(a.get("sport")), "raw": a.get("sport") or "other",
                     "name": a.get("name") or "Workout", "min": _seconds(a.get("duration")) / 60,
                     "km": float(a.get("distance_km") or 0), "climb": float(a.get("elevation_gain_m") or 0),
                     "hour": hour, "id": a.get("activity_id")})
    return rows


def _streaks(days: set[date], today: date, rest: set[date] | frozenset[date] = frozenset()) -> dict[str, Any]:
    """Day streak that rewards consistency without punishing recovery.

    A day keeps the streak if you trained, if your plan scheduled rest, or (once per
    Monday-start week) as a free rest day. Only trained days add to the count. Today not
    done yet never breaks it.
    """
    best = run = 0
    graced: set[date] = set()
    cur_week_grace = False
    if days:
        d = min(days)
        while d <= today:
            week = d - timedelta(days=d.weekday())
            if d in days:
                run += 1
            elif d in rest or d == today:
                pass
            elif week not in graced:
                graced.add(week)
            else:
                run = 0
            best = max(best, run)
            d += timedelta(days=1)
        cur_week_grace = (today - timedelta(days=today.weekday())) in graced
    done = today in days
    return {"current": run, "best": best, "today_done": done,
            "grace_left": not cur_week_grace,
            "at_risk": run > 0 and not done and today not in rest and cur_week_grace}


def _week_streaks(rows: list[dict[str, Any]], today: date) -> tuple[int, int]:
    """Consecutive Monday-start weeks with ACTIVE_WEEK+ workouts (this week counts once it
    gets there, and doesn't break the streak before then)."""
    per_week: dict[date, int] = defaultdict(int)
    for r in rows:
        per_week[r["date"] - timedelta(days=r["date"].weekday())] += 1
    this_week = today - timedelta(days=today.weekday())
    cur = 0
    w = this_week if per_week.get(this_week, 0) >= ACTIVE_WEEK else this_week - timedelta(days=7)
    while per_week.get(w, 0) >= ACTIVE_WEEK:
        cur += 1
        w -= timedelta(days=7)
    best = run = 0
    if per_week:
        w = min(per_week)
        while w <= this_week:
            run = run + 1 if per_week.get(w, 0) >= ACTIVE_WEEK else 0
            best = max(best, run)
            w += timedelta(days=7)
    return cur, best


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"workouts": len(rows), "hours": round(sum(r["min"] for r in rows) / 60, 1),
            "km": round(sum(r["km"] for r in rows), 1), "climb_m": round(sum(r["climb"] for r in rows)),
            "days": len({r["date"] for r in rows})}


def adherence(plan: dict[str, Any] | None, acts: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """Planned sessions done vs planned: this week, and plan-to-date (past days only)."""
    if not plan:
        return None
    by_week: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for w, day, s in iter_sessions(plan):
        by_week.setdefault(w["start"], {}).setdefault(day, []).append({"sport": s["sport"], "title": s["title"],
                                                               "minutes": s.get("minutes")})
    this_monday = (today - timedelta(days=today.weekday())).isoformat()
    total_done = total_planned = perfect = 0
    week: dict[str, Any] | None = None
    weeks: list[dict[str, Any]] = []
    for start, planned in sorted(by_week.items()):
        if start > this_monday:
            break
        days = merge(date.fromisoformat(start), today, planned, acts)
        ss = [s for d in days for s in d["sessions"] if s["status"] != "rest"]
        due = [s for s in ss if s["status"] in ("done", "missed")]
        done = sum(s["status"] == "done" for s in ss)
        mins_planned = sum(s.get("minutes") or 0 for s in ss)
        if start == this_monday:
            week = {"done": done, "planned": len(ss), "due": len(due),
                    "minutes_done": sum((s.get("activity") or {}).get("minutes", 0) for s in ss if s["status"] == "done")
                    + sum(a["minutes"] for d in days for a in d["extra"]),
                    "minutes_planned": mins_planned}
        total_done += sum(s["status"] == "done" for s in due)
        total_planned += len(due)
        if start < this_monday and ss:
            perfect += int(done == len(ss))
            weeks.append({"start": start, "done": done, "planned": len(ss)})
    return {"week": week, "to_date": {"done": total_done, "planned": total_planned,
                                      "pct": round(100 * total_done / total_planned) if total_planned else None},
            "perfect_weeks": perfect, "recent_weeks": weeks[-8:]}


def compute(acts: list[dict[str, Any]], today: date, *, imperial: bool = False,
            plan: dict[str, Any] | None = None, favorites: list[str] | None = None) -> dict[str, Any]:
    rows = [r for r in _rows(acts) if r["date"] <= today]
    year_ago = today - timedelta(days=364)
    rows_year = [r for r in rows if r["date"] >= year_ago]
    monday = today - timedelta(days=today.weekday())
    month1 = today.replace(day=1)
    days = {r["date"] for r in rows}
    st = _streaks(days, today, plan_rest_days(plan, today))
    cur, best, today_done = st["current"], st["best"], st["today_done"]
    wcur, wbest = _week_streaks(rows, today)

    # Weekly volume, last 12 weeks, by sport (oldest first).
    weekly = []
    for i in range(11, -1, -1):
        ws = monday - timedelta(weeks=i)
        rs = [r for r in rows if ws <= r["date"] <= ws + timedelta(days=6)]
        by: dict[str, float] = defaultdict(float)
        for r in rs:
            by[r["sport"]] += r["min"] / 60
        weekly.append({"start": ws.isoformat(), "hours": round(sum(by.values()), 1),
                       "workouts": len(rs), "by_sport": {k: round(v, 2) for k, v in by.items() if v > 0}})

    # Calendar: last 26 weeks, minutes per day.
    cal_start = monday - timedelta(weeks=25)
    per_day: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["date"] >= cal_start:
            per_day[r["date"].isoformat()] += r["min"]
    calendar = {"start": cal_start.isoformat(), "days": {k: round(v) for k, v in per_day.items()}}

    # Sports (12 months), favorites first.
    sports: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows_year:
        sports[r["sport"]].append(r)
    fav_engine = {"run": "run", "trail": "run", "hike": "hike", "walk": "hike", "bike": "bike",
                  "gravel": "bike", "mtb": "bike", "swim": "swim", "open_water": "swim",
                  "strength": "strength", "yoga": "strength", "climb": "climb", "ski": "ski",
                  "row": "paddle"}
    fav = {fav_engine.get(f, "other") for f in (favorites or [])}
    by_sport = sorted(({"sport": s, **_totals(rs), "favorite": s in fav,
                        "longest_min": round(max(r["min"] for r in rs))} for s, rs in sports.items()),
                      key=lambda x: (not x["favorite"], -x["hours"]))

    # Bests (12 months).
    def best_of(key: str, sport: str | None = None) -> dict[str, Any] | None:
        rs = [r for r in rows_year if sport is None or r["sport"] == sport]
        if not rs:
            return None
        r = max(rs, key=lambda x: x[key])
        if not r[key]:
            return None
        return {"value": round(r[key], 1), "date": r["date"].isoformat(), "name": r["name"], "sport": r["sport"]}
    bests = {k: v for k, v in {
        "longest_workout_min": best_of("min"), "longest_run_km": best_of("km", "run"),
        "longest_ride_km": best_of("km", "bike"), "longest_swim_km": best_of("km", "swim"),
        "biggest_climb_m": best_of("climb"),
    }.items() if v}

    # Badges.
    months: dict[tuple[int, int], set[str]] = defaultdict(set)
    for r in rows_year:
        months[(r["date"].year, r["date"].month)].add(r["sport"])
    adh = adherence(plan, acts, today)
    metrics = {
        "workouts_year": len(rows_year), "hours_year": sum(r["min"] for r in rows_year) / 60,
        "climb_year_m": sum(r["climb"] for r in rows_year), "best_streak": best,
        "best_week_streak": wbest, "longest_min": max((r["min"] for r in rows_year), default=0),
        "early_count": sum(1 for r in rows_year if r["hour"] is not None and r["hour"] < 7),
        "max_sports_month": max((len(v - {"other"}) for v in months.values()), default=0),
        "perfect_plan_weeks": (adh or {}).get("perfect_weeks", 0),
    }
    badges = [{"id": bid, "title": t, "description": desc, "earned": metrics[m] >= target,
               "progress": round(min(1.0, metrics[m] / target), 2)} for bid, t, desc, m, target in BADGES]

    week_rows = [r for r in rows if r["date"] >= monday]
    totals = {"week": _totals(week_rows), "month": _totals([r for r in rows if r["date"] >= month1]),
              "year": _totals(rows_year)}
    last_week = [r for r in rows if monday - timedelta(days=7) <= r["date"] <= today - timedelta(days=7)]
    totals["week"]["vs_last_week_hours"] = round(totals["week"]["hours"] - sum(r["min"] for r in last_week) / 60, 1)
    return {
        "today": today.isoformat(), "units": "imperial" if imperial else "metric",
        "streak": {"current": cur, "best": best, "today_done": today_done,
                   "grace_left": st["grace_left"], "at_risk": st["at_risk"],
                   "weeks_current": wcur, "weeks_best": wbest, "active_week": ACTIVE_WEEK},
        "totals": totals, "weekly": weekly, "calendar": calendar, "by_sport": by_sport,
        "bests": bests, "badges": badges, "plan": adh,
        "recent": [{"date": r["date"].isoformat(), "name": r["name"], "sport": r["sport"],
                    "minutes": round(r["min"]), "km": round(r["km"], 1), "id": r["id"]}
                   for r in sorted(rows, key=lambda x: x["date"], reverse=True)[:8]],
        "headline": headline(cur, today_done, best, totals["week"], adh, wcur, at_risk=st["at_risk"]),
    }


def headline(cur: int, today_done: bool, best: int, week: dict[str, Any],
             adh: dict[str, Any] | None, wcur: int, *, at_risk: bool = False) -> str:
    """One encouraging, honest line for the top of the screen."""
    pw = (adh or {}).get("week")
    if cur >= 2 and today_done:
        return f"{cur} days in a row. That's how fitness gets built." if cur < best or best < 7 \
            else f"{cur} days in a row: your best streak yet."
    if cur >= 1 and at_risk:
        return f"{cur}-day streak on the line. You've used this week's free rest day, so a short session today keeps it going."
    if cur >= 1 and not today_done:
        return f"{cur}-day streak. Train today to add to it; a rest day won't break it."
    if pw and pw["planned"]:
        left = pw["planned"] - pw["done"]
        return (f"{pw['done']} of {pw['planned']} planned sessions done this week."
                + (" Plan complete!" if left == 0 else ""))
    if week["workouts"]:
        return f"{week['workouts']} workout{'s' if week['workouts'] != 1 else ''} this week. Keep stacking them."
    if wcur:
        return f"{wcur} active week{'s' if wcur != 1 else ''} in a row. Let's make this one count."
    return "Every streak starts with one workout. Today's a good day for it."


def plan_rest_days(plan: dict[str, Any] | None, today: date) -> set[date]:
    """Days the plan scheduled no training (they keep the streak alive)."""
    out: set[date] = set()
    for w in (plan or {}).get("weeks") or []:
        try:
            start = date.fromisoformat(w["start"])
        except (KeyError, TypeError, ValueError):
            continue
        for i in range(7):
            d = start + timedelta(days=i)
            if d > today:
                break
            ss = (w.get("days") or {}).get(d.isoformat()) or []
            if not any(s.get("sport") != "rest" for s in ss):
                out.add(d)
    return out


class StatsService:
    def __init__(self, service: "GarminService", *, now: Callable[[str], datetime],
                 athlete: Callable[[str], dict[str, Any]],
                 plan: Callable[[str], dict[str, Any] | None], clock: Callable[[], float] = time.time) -> None:
        self._svc = service
        self._now = now
        self._athlete = athlete
        self._plan = plan
        self._clock = clock
        self._cache: dict[str, tuple[float, date, dict[str, Any]]] = {}
        self._acts: dict[str, tuple[float, date, list[dict[str, Any]]]] = {}

    def activities(self, user_id: str, *, fresh: bool = False) -> tuple[date, list[dict[str, Any]]]:
        """A year of compact activities (one Garmin read, cached a few minutes)."""
        today = self._now(user_id).date()
        hit = self._acts.get(user_id)
        if hit and not fresh and self._clock() - hit[0] < CACHE_S and hit[1] == today:
            return today, hit[2]
        acts = self._svc.activities_between(user_id, today - timedelta(days=HISTORY_DAYS), today)
        self._acts[user_id] = (self._clock(), today, acts)
        return today, acts

    def get(self, user_id: str, *, fresh: bool = False) -> dict[str, Any]:
        hit = self._cache.get(user_id)
        if hit and not fresh and self._clock() - hit[0] < CACHE_S and hit[1] == self._now(user_id).date():
            return hit[2]
        today, acts = self.activities(user_id, fresh=fresh)
        a = self._athlete(user_id)
        out = compute(acts, today, imperial=a.get("units") == "imperial", plan=self._plan(user_id),
                      favorites=a.get("favorite_sports"))
        self._cache[user_id] = (self._clock(), today, out)
        return out

    def invalidate(self, user_id: str) -> None:
        """Drop cached stats (after a plan edit) so adherence is current."""
        self._cache.pop(user_id, None)

    def load(self, user_id: str) -> dict[str, Any]:
        from .load import compute as load_compute
        today, acts = self.activities(user_id)
        a = self._athlete(user_id)
        return load_compute(acts, today, threshold_hr=a.get("threshold_hr"), plan=self._plan(user_id))


__all__ = ["StatsService", "compute", "adherence", "headline", "plan_rest_days", "BADGES"]
