"""Repeating events: the rule, its occurrences, and its iCalendar RRULE.

A rule (stored on the event as ``recurring``)::

    {"freq": "weekly", "interval": 1 | 2, "weekdays": ["tue", "thu"],
     "until": "YYYY-MM-DD" | None, "count": int | None, "except": ["YYYY-MM-DD", ...],
     "weekday": "tue", "every": "week"}                     # weekday/every: older readers
    {"freq": "monthly", "interval": 1, "weekdays": ["tue"], "setpos": 2 | -1, ...}
                                                             # 2nd Tuesday / last Tuesday

``until`` and ``count`` are optional (at most one); without either the event repeats with no end,
and every expansion is bounded by the range it's asked for. ``count`` counts occurrences from the
first date before ``except`` removes any (as RFC 5545 COUNT does with EXDATE).
Older events stored ``{"weekday", "until"}`` (weekly): ``clean_rule`` and ``loose`` read both.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ICAL_DAY = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH", "fri": "FR", "sat": "SA", "sun": "SU"}
MAX_COUNT = 200
MAX_EXCEPT = 100
MAX_SCAN = 1500  # occurrences scanned per expansion, whatever the range


class RuleError(ValueError):
    """A repeat rule that can't be saved; the message is for people."""


def _day(v: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise RuleError(f"pick the {what}") from None


def setpos_of(d: date) -> int:
    """Which weekday of the month ``d`` is: 1..4, or -1 when it's the last one (5th week)."""
    n = (d.day - 1) // 7 + 1
    return -1 if n >= 5 else n


def clean_rule(v: Any, start: date | None) -> dict[str, Any] | None:
    """Validate a repeat rule from the form (or an older {weekday, until}); None = doesn't repeat."""
    if v in (None, "", False):
        return None
    if not isinstance(v, dict):
        raise RuleError("repeat must be an object")
    allowed = {"freq", "interval", "weekdays", "setpos", "until", "count", "except", "weekday", "every"}
    if set(v) - allowed:
        raise RuleError(f"unknown repeat field {sorted(set(v) - allowed)[0]!r}")
    freq = v.get("freq") or ("weekly" if v.get("every") in (None, "week") else None)
    if freq not in ("weekly", "monthly"):
        raise RuleError("events repeat weekly, every 2 weeks or monthly")
    interval = v.get("interval", 1)
    if interval in (None, ""):
        interval = 1
    if not isinstance(interval, int) or isinstance(interval, bool) or interval not in (1, 2):
        raise RuleError("repeat every 1 or 2 weeks")
    if freq == "monthly" and interval != 1:
        raise RuleError("monthly events repeat every month")
    days = v.get("weekdays")
    if days is None and v.get("weekday") is not None:
        days = [v.get("weekday")]
    if days is None and start is not None:
        days = [WEEKDAYS[start.weekday()]]
    if not isinstance(days, list) or not days or any(d not in WEEKDAYS for d in days):
        raise RuleError("pick the weekday it repeats on")
    days = sorted(set(days), key=WEEKDAYS.index)
    if freq == "monthly" and len(days) != 1:
        raise RuleError("a monthly event repeats on one weekday")
    setpos = None
    if freq == "monthly":
        setpos = v.get("setpos")
        if setpos is None and start is not None:
            setpos = setpos_of(start)
        if setpos not in (1, 2, 3, 4, -1):
            raise RuleError("pick which week of the month (1st to 4th, or last)")
    until = None if v.get("until") in (None, "") else _day(v.get("until"), "date it repeats until").isoformat()
    count = v.get("count")
    if count in (None, ""):
        count = None
    elif not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_COUNT:
        raise RuleError(f"repeat 1 to {MAX_COUNT} times")
    if until and count:
        raise RuleError("end it on a date or after a number of times, not both")
    if until and start is not None and until < start.isoformat():
        raise RuleError("A repeating event has to repeat until after its first date.")
    exc = v.get("except") or []
    if not isinstance(exc, list) or len(exc) > MAX_EXCEPT:
        raise RuleError("too many skipped dates")
    exc = sorted({_day(x, "skipped date").isoformat() for x in exc})
    out: dict[str, Any] = {"freq": freq, "interval": interval, "weekdays": days, "until": until, "count": count,
                           "except": exc, "weekday": days[0], "every": "week" if freq == "weekly" else "month"}
    if setpos is not None:
        out["setpos"] = setpos
    return out


def stored(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    """What an event keeps: the older {"weekday", "until"} when that says it all (so plans and
    signatures of existing weekly events don't change), else the full rule (no ``weekday`` /
    ``every`` echo)."""
    if not rule:
        return None
    if (rule["freq"] == "weekly" and rule["interval"] == 1 and len(rule["weekdays"]) == 1 and rule.get("until")
            and not rule.get("count") and not rule.get("except")):
        return {"weekday": rule["weekdays"][0], "until": rule["until"]}
    out = {k: v for k, v in rule.items() if k not in ("weekday", "every") and v not in (None, [])}
    return out


def loose(v: Any, start: date | None) -> dict[str, Any] | None:
    """Like clean_rule for stored data: never raises (a bad rule reads as "doesn't repeat")."""
    try:
        return clean_rule(v, start)
    except RuleError:
        return None


def _nth_weekday(y: int, m: int, wd: int, setpos: int) -> date | None:
    first = date(y, m, 1)
    if setpos > 0:
        d = first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (setpos - 1))
        return d if d.month == m else None
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - wd) % 7)


def _raw(rule: dict[str, Any], start: date):
    """Every date the rule produces from ``start`` on, before except/until/count."""
    if rule["freq"] == "weekly":
        monday = start - timedelta(days=start.weekday())
        wds = [WEEKDAYS.index(d) for d in rule["weekdays"]]
        k = 0
        while True:
            if k % rule["interval"] == 0:
                for wd in wds:
                    d = monday + timedelta(weeks=k, days=wd)
                    if d >= start:
                        yield d
            k += 1
    else:
        wd = WEEKDAYS.index(rule["weekdays"][0])
        y, m = start.year, start.month
        while True:
            d = _nth_weekday(y, m, wd, rule.get("setpos") or 1)
            if d is not None and d >= start:
                yield d
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def dates(rule: dict[str, Any], start: date, frm: date, to: date, *, limit: int = 400,
          keep_except: bool = False) -> list[date]:
    """Occurrences in [frm, to] (inclusive), oldest first, at most ``limit``."""
    until = date.fromisoformat(rule["until"]) if rule.get("until") else None
    exc = set(rule.get("except") or [])
    out: list[date] = []
    for n, d in enumerate(_raw(rule, start), 1):
        if n > MAX_SCAN or d > to or (until and d > until) or (rule.get("count") and n > rule["count"]):
            break
        if d >= frm and (keep_except or d.isoformat() not in exc):
            out.append(d)
            if len(out) >= limit:
                break
    return out


def first_date(rule: dict[str, Any], start: date) -> date | None:
    got = dates(rule, start, start, start + timedelta(days=400), limit=1, keep_except=True)
    return got[0] if got else None


def rrule(rule: dict[str, Any], *, timed: bool) -> str:
    """The rule as an iCalendar RRULE value (no "RRULE:" prefix)."""
    parts = ["FREQ=WEEKLY" if rule["freq"] == "weekly" else "FREQ=MONTHLY"]
    if rule["freq"] == "weekly":
        if rule["interval"] != 1:
            parts.append(f"INTERVAL={rule['interval']}")
        parts.append("BYDAY=" + ",".join(ICAL_DAY[d] for d in rule["weekdays"]))
    else:
        parts.append(f"BYDAY={rule.get('setpos') or 1}{ICAL_DAY[rule['weekdays'][0]]}")
    if rule.get("until"):
        u = rule["until"].replace("-", "")
        parts.append(f"UNTIL={u}T235959" if timed else f"UNTIL={u}")
    elif rule.get("count"):
        parts.append(f"COUNT={rule['count']}")
    return ";".join(parts)


ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", -1: "last"}
DAY_NAME = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
            "sat": "Saturday", "sun": "Sunday"}


def describe(rule: dict[str, Any]) -> str:
    """"Every Tuesday and Thursday", "Every 2 weeks on Saturday", "Monthly on the 2nd Tuesday"."""
    names = [DAY_NAME[d] for d in rule["weekdays"]]
    days = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    if rule["freq"] == "monthly":
        s = f"Monthly on the {ORD.get(rule.get('setpos') or 1, '1st')} {names[0]}"
    elif rule["interval"] == 2:
        s = f"Every 2 weeks on {days}"
    else:
        s = f"Every {days}"
    if rule.get("until"):
        s += f" until {rule['until']}"
    elif rule.get("count"):
        s += f", {rule['count']} times"
    return s


__all__ = ["RuleError", "clean_rule", "stored", "loose", "dates", "first_date", "rrule", "describe", "setpos_of"]
