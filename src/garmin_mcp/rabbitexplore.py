""""Let Rabbit explore": one tap, one ranked list.

RunSignup around the resolved location (the athlete's race types, next 6 months) plus the
existing Explore web research (``explore.WebFinder``: notable races that aren't on RunSignup,
filters only in the prompt, daily allowance on a cache miss) -> merged, de-duplicated (same
race id, or the same name within 3 days), calendar/taper/avoided-month races dropped, ranked
with ``foryou.score`` (a small nudge for notable web finds), each with a one-line "why", and a
deterministic intro sentence. No athlete data reaches the model.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import foryou as fy

MONTHS = 6
LIMIT = 20
WEB_NUDGE = 1


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def dedupe(lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """First wins (pass RunSignup first: it has registration and fees); a later copy of the same
    race only fills in a missing summary."""
    out: list[dict[str, Any]] = []
    for lst in lists:
        for r in lst:
            rd = _d(r.get("date"))
            dup = next((o for o in out if o["id"] == r["id"] or (
                fy.same_name(o["name"], r["name"]) and rd and (od := _d(o["date"])) and abs((od - rd).days) <= 3)), None)
            if dup is None:
                out.append(dict(r))
            elif not dup.get("summary") and r.get("summary"):
                dup["summary"] = r["summary"]
    return out


def rank(races: list[dict[str, Any]], *, interests: dict[str, Any], events: list[dict[str, Any]],
         today: date) -> tuple[list[dict[str, Any]], int]:
    """(all ranked races with score/why/fit, how many are tune-ups for the main race); the
    caller shows the first ``LIMIT``."""
    main = fy.main_race(events, today)
    a_dates = fy.a_race_dates(events, today)
    calendar = {(str(e.get("name", "")).strip().lower(), e.get("date")) for e in events}
    out = []
    tunes = 0
    for r in races:
        rd = _d(r.get("date"))
        if rd is None or rd < today:
            continue
        if fy.blocked(r, interests=interests, a_dates=a_dates, calendar=calendar):
            continue
        s = fy.score(r, interests=interests, main=main, a_dates=a_dates)
        tu = fy.tune_up(r, main)
        tunes += bool(tu)
        pts = s["score"] + (WEB_NUDGE if r.get("source") == "web" else 0)
        why = s["why"]
        if why == "Fits your calendar":
            why = ("A notable race Rabbit found on the web" if r.get("source") == "web"
                   else f"Coming up {'this week' if (rd - today).days < 7 else 'in ' + fy._MONTHS[rd.month - 1]}")
        out.append({**r, **s, "score": pts, "why": why, "tune_up": bool(tu)})
    out.sort(key=lambda r: (-r["score"], r["date"], r["name"].lower()))
    return out, tunes


def intro(n: int, *, zip_: str, state: str, radius: int, tunes: int, main: dict[str, Any] | None,
          months: int = MONTHS) -> str:
    where = f"within {radius} mi" if zip_ else (f"in {state}" if state else "around the country")
    if n == 0:
        return f"No races turned up {where} in the next {months} months. Try a bigger trip radius in your interests."
    s = f"Found {n} race{'s' if n != 1 else ''} {where} in the next {months} months"
    if tunes and main:
        s += f"; {tunes} {'is a great tune-up' if tunes == 1 else 'are great tune-ups'} for {fy._short_name(main['name'])}"
    return s + "."


__all__ = ["dedupe", "intro", "rank"]
