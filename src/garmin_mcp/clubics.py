""""Add to calendar" for a club directory listing: an iCalendar file (RFC 5545) with one weekly
VEVENT per session that has a time (``RRULE:FREQ=WEEKLY;BYDAY=..``), local to the athlete's
timezone (``DTSTART;TZID=America/Denver``) with a VTIMEZONE derived from ``zoneinfo``, the
public meet spot as LOCATION and the join link as URL. Text is escaped (backslash, ``;``, ``,``,
newlines) and lines are folded at 75 octets with CRLF endings. Pure: no clock, no IO.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

BYDAY = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH", "fri": "FR", "sat": "SA", "sun": "SU"}
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DURATION = "PT1H"  # club pages rarely say how long; an hour is a sane placeholder


def escape(text: Any) -> str:
    """RFC 5545 3.3.11 TEXT escaping."""
    s = str(text or "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return re.sub(r"\r\n|\r|\n", "\\\\n", s)


def fold(line: str) -> str:
    """Fold to <= 75 octets per line (continuations start with a space), never splitting a
    UTF-8 character."""
    out: list[str] = []
    cur, size, limit = "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " ", 1, 75
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _offset(td: timedelta | None) -> str:
    mins = int((td or timedelta()).total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{sign}{mins // 60:02d}{mins % 60:02d}"


def _transitions(tz: tzinfo, year: int) -> list[tuple[datetime, timedelta, timedelta, str]]:
    """Offset changes in ``year``: (local wall time in the old offset, old, new, tzname)."""
    out = []
    prev = datetime(year, 1, 1, 12, tzinfo=tz).utcoffset() or timedelta()
    d = date(year, 1, 2)
    while d.year == year:
        off = datetime(d.year, d.month, d.day, 12, tzinfo=tz).utcoffset() or timedelta()
        if off != prev:
            base = (datetime(d.year, d.month, d.day, 12, tzinfo=tz) - timedelta(days=1)).astimezone(UTC)
            for h in range(1, 26):
                u = base + timedelta(hours=h)
                if u.astimezone(tz).utcoffset() == off:
                    wall = (u + prev).replace(tzinfo=None)
                    out.append((wall, prev, off, u.astimezone(tz).tzname() or ""))
                    break
            prev = off
        d += timedelta(days=1)
    return out


def vtimezone(tz: ZoneInfo, year: int) -> list[str]:
    """A VTIMEZONE for ``tz`` with yearly rules taken from last year's transitions (so it
    starts before any event), or a single STANDARD block when there's no DST."""
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tz.key}"]
    trs = _transitions(tz, year - 1)
    if len(trs) != 2:
        off = datetime(year, 1, 15, 12, tzinfo=tz).utcoffset()
        name = datetime(year, 1, 15, 12, tzinfo=tz).tzname() or ""
        lines += ["BEGIN:STANDARD", "DTSTART:19700101T000000", f"TZOFFSETFROM:{_offset(off)}",
                  f"TZOFFSETTO:{_offset(off)}", f"TZNAME:{escape(name)}", "END:STANDARD"]
    else:
        for wall, old, new, name in trs:
            kind = "DAYLIGHT" if new > old else "STANDARD"
            last = wall.day + 7 > calendar.monthrange(wall.year, wall.month)[1]
            nth = -1 if last else (wall.day - 1) // 7 + 1
            day = BYDAY[_DAYS[wall.weekday()]]
            lines += [f"BEGIN:{kind}", f"DTSTART:{wall:%Y%m%dT%H%M%S}",
                      f"RRULE:FREQ=YEARLY;BYMONTH={wall.month};BYDAY={nth}{day}",
                      f"TZOFFSETFROM:{_offset(old)}", f"TZOFFSETTO:{_offset(new)}",
                      f"TZNAME:{escape(name)}", f"END:{kind}"]
    return [*lines, "END:VTIMEZONE"]


def _first(weekday: str, hhmm: str, now: datetime) -> datetime:
    """The first start on ``weekday`` at ``hhmm`` at or after ``now`` (naive local)."""
    h, m = map(int, hhmm.split(":"))
    d = (_DAYS.index(weekday) - now.weekday()) % 7
    t = datetime(now.year, now.month, now.day, h, m) + timedelta(days=d)
    return t if t >= now.replace(tzinfo=None, second=0, microsecond=0) else t + timedelta(days=7)


def filename(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40]
    return f"{slug or 'group'}.ics"


def listing_ics(listing: dict[str, Any], now_local: datetime, *, host: str = "rabbit") -> str:
    """The .ics text for a public listing (``Directory.public`` shape). ``now_local`` is an aware
    datetime in the athlete's zone (its ZoneInfo key is the TZID). Raises ValueError when the
    listing has no session with a time."""
    tz = now_local.tzinfo
    if not isinstance(tz, ZoneInfo):
        raise ValueError("timezone")
    sessions = [s for s in listing.get("sessions") or []
                if s.get("weekday") in BYDAY and re.fullmatch(r"\d{2}:\d{2}", str(s.get("time") or ""))]
    if not sessions:
        raise ValueError("no weekly time")
    stamp = now_local.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    desc = " · ".join(x for x in (listing.get("kind_label"), listing.get("pace"),
                                  {"free": "Free", "paid": "Paid"}.get(listing.get("cost") or "", "")) if x)
    note = f"From {listing.get('source') or 'the club page'} via rabbt. Times change; check {listing.get('join_url')}"
    body = f"{desc}\n{listing.get('description') or ''}".strip() + "\n" + note
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//rabbt//Club directory//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", *vtimezone(tz, now_local.year)]
    for s in sessions:
        start = _first(s["weekday"], s["time"], now_local)
        lines += ["BEGIN:VEVENT",
                  f"UID:{listing['id']}-{s['weekday']}{s['time'].replace(':', '')}@{host}",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID={tz.key}:{start:%Y%m%dT%H%M%S}",
                  f"DURATION:{DURATION}",
                  f"RRULE:FREQ=WEEKLY;BYDAY={BYDAY[s['weekday']]}",
                  f"SUMMARY:{escape(listing.get('name'))}"]
        if listing.get("meet_spot"):
            lines.append(f"LOCATION:{escape(listing['meet_spot'])}")
        if isinstance(listing.get("join_url"), str) and listing["join_url"].startswith("https://"):
            lines.append(f"URL:{listing['join_url']}")
        lines += [f"DESCRIPTION:{escape(body)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(x) + "\r\n" for x in lines)


__all__ = ["escape", "filename", "fold", "listing_ics", "vtimezone"]
