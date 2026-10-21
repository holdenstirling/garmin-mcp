"""Traction counts for the owner Usage screen: activation, core-job retention, where people
heard about rabbt, referrals, organizer health, Denver share and the day-7 recommend score.

Same privacy model as ``usage.py``: counters only, no free text, nothing per event. The app
reports what it already counts (``usage.py`` events) plus ``milestone`` events; this module
turns a person's *first* of each milestone into a counter on their signup-day cohort. Everything
arrives through ``POST /app/api/usage``, so Do Not Track / Global Privacy Control and "Don't
count my usage" (``profile.usage_off``) drop it before it gets here.

Per person, their own encrypted doc ``traction`` keeps only dates: ``joined`` (their usage.py
first day when known), ``firsts`` {milestone: date}, ``core`` (first core job), ``w4`` (counted
as active in week 4), ``week`` (last ISO week counted), ``src`` (their answer to "How did you hear
about rabbt?") and ``pulse`` (asked / answered). No events, no places, no counts.

Global doc ``traction``:

* ``cohorts`` {signup date: {"signup", "f.<milestone>", "job", "core", "core7", "w4"}}
* ``weeks`` {ISO week: {"active", "denver"}}: first activity of each person each week; Denver =
  their saved area is within ``DENVER_KM`` of downtown (checked here, never stored).
* ``sources`` {date: {source: n}}, ``refs`` {"invite": n, "club:<slug>": n}
* ``nps`` {date: {"0".."10": n}}; the optional note goes to ``pulse_notes`` (the person's own
  feedback to the owners, like an email to us; capped, newest first), never into counters.

Core jobs (the two reasons people come): RSVP to a run, post a run, or build a plan. Activated =
did one within 7 days of joining. Week-4 retention = of activated people, active on a day 21-27
days after joining.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .appstore import AppStore

FIRSTS = ("area_set", "rsvp", "run_posted", "plan_built", "post", "follow", "watch_connected")
CORE = frozenset({"rsvp", "run_posted", "plan_built"})
JOB = frozenset({"rsvp", "run_posted"})  # "do one thing near you"
SOURCES = ("friend", "club", "instagram", "strava", "event", "search", "other")
KEEP_DAYS = 120
WINDOW = 30
NOTE_LEN = 500
MAX_NOTES = 200
PULSE_AFTER_DAYS = 7

# Denver metro: within ~30 miles of downtown. Market doc: ~94,000 people run with groups in the
# metro, 26 known clubs.
DENVER = (39.7392, -104.9903)
DENVER_KM = 48.0
DENVER_RUNNERS = 94_000
DENVER_CLUBS = 26

# Go / iterate / stop thresholds after 4 weeks (market doc's discovery plan).
TARGETS = {"core7_pct": 40, "w4_pct": 25, "clubs_weekly": 5, "rsvps_per_run": 8, "nps": 30}


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def in_denver(lat: Any, lon: Any) -> bool:
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lon)):
        return False
    return km_between((float(lat), float(lon)), DENVER) <= DENVER_KM


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _pct(n: int, of: int) -> int | None:
    return round(100 * n / of) if of else None


class Traction:
    def __init__(self, store: AppStore, *, clock: Callable[[], float] = time.time,
                 joined_of: Callable[[str], str | None] | None = None,
                 area_of: Callable[[str], tuple[Any, Any] | None] | None = None) -> None:
        self._store = store
        self._clock = clock
        # usage.py's first-seen day for a person (their real start), when known
        self._joined_of = joined_of or (lambda uid: (store.user_doc(uid, "usage").load() or {}).get("first"))
        # their saved area's rounded coordinates (geo.py), only to test "in the Denver metro"
        self._area_of = area_of or (lambda uid: None)
        self._lock = threading.Lock()
        self._seen: set[tuple[str, str]] = set()  # (uid, day): active() once per person per day

    def today(self) -> date:
        return datetime.fromtimestamp(self._clock(), UTC).date()

    # --------------------------------------------------------------- write --
    def _mine(self, uid: str) -> Any:
        return self._store.user_doc(uid, "traction")

    def _joined(self, mine: dict[str, Any], uid: str, today: date, cohorts: dict[str, Any]) -> date:
        """The person's signup day; the first time we see them it also counts their signup."""
        if mine.get("joined"):
            return _d(mine["joined"])
        raw = self._joined_of(uid)
        try:
            j = min(_d(raw), today) if raw else today
        except ValueError:
            j = today
        mine["joined"] = j.isoformat()
        c = cohorts.setdefault(j.isoformat(), {})
        c["signup"] = c.get("signup", 0) + 1
        return j

    def _update(self, uid: str, fn: Callable[[dict[str, Any], dict[str, Any], date], None]) -> None:
        today = self.today()
        doc = self._mine(uid)
        with self._lock:
            mine = doc.load()
            before = dict(mine)

            def apply(g: dict[str, Any]) -> None:
                cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
                for part in ("cohorts", "sources", "nps"):
                    g[part] = {k: v for k, v in (g.get(part) or {}).items() if k >= cutoff}
                fn(mine, g, today)
            self._store.global_doc("traction").update(apply)
            if mine != before:
                doc.save(mine)

    def active(self, uid: str, ref: str | None = None) -> None:
        """A counted visit (from ``POST /app/api/usage``): signup cohort, week-4 retention of
        activated people, weekly actives and Denver actives. ``ref`` = "club:<slug>" or "invite"
        when a new person arrived from a club page or an invite (counted once, at signup)."""
        key = (uid, self.today().isoformat())
        if key in self._seen:
            return
        if len(self._seen) > 50_000:
            self._seen.clear()
        self._seen.add(key)

        def fn(mine: dict[str, Any], g: dict[str, Any], today: date) -> None:
            cohorts = g.setdefault("cohorts", {})
            new = not mine.get("joined")
            j = self._joined(mine, uid, today, cohorts)
            if new and ref and (today - j).days <= 1 and not mine.get("ref"):
                mine["ref"] = True
                refs = g.setdefault("refs", {})
                refs[ref] = refs.get(ref, 0) + 1
            if mine.get("core") and not mine.get("w4") and 21 <= (today - j).days <= 27:
                mine["w4"] = True
                c = cohorts.setdefault(j.isoformat(), {})
                c["w4"] = c.get("w4", 0) + 1
            wk = iso_week(today)
            if mine.get("week") != wk:
                mine["week"] = wk
                w = g.setdefault("weeks", {}).setdefault(wk, {})
                w["active"] = w.get("active", 0) + 1
                area = self._area_of(uid)
                if area and in_denver(*area):
                    w["denver"] = w.get("denver", 0) + 1
                weeks = g["weeks"]
                for k in sorted(weeks)[:-20]:
                    del weeks[k]
        self._update(uid, fn)

    def first(self, uid: str, what: str) -> bool:
        """Count ``what`` the first time this person does it; True when it was their first."""
        if what not in FIRSTS:
            return False
        if what in (self._mine(uid).load().get("firsts") or {}):
            return False  # the common case: no global write
        hit = {"new": False}

        def fn(mine: dict[str, Any], g: dict[str, Any], today: date) -> None:
            firsts = mine.setdefault("firsts", {})
            if what in firsts:
                return
            cohorts = g.setdefault("cohorts", {})
            j = self._joined(mine, uid, today, cohorts)
            firsts[what] = today.isoformat()
            c = cohorts.setdefault(j.isoformat(), {})
            c[f"f.{what}"] = c.get(f"f.{what}", 0) + 1
            if what in JOB and not mine.get("job"):
                mine["job"] = today.isoformat()
                c["job"] = c.get("job", 0) + 1
            if what in CORE and not mine.get("core"):
                mine["core"] = today.isoformat()
                c["core"] = c.get("core", 0) + 1
                if (today - j).days < 7:
                    c["core7"] = c.get("core7", 0) + 1
            hit["new"] = True
        self._update(uid, fn)
        return hit["new"]

    def from_events(self, uid: str, events: Iterable[tuple[str, dict[str, str]]]) -> None:
        """Map counted usage events to firsts (``milestone`` events name theirs)."""
        for name, props in events:
            what = props.get("what") if name == "milestone" else \
                "rsvp" if name == "rsvp" else \
                "post" if name == "share" and props.get("what") == "post" else \
                "plan_built" if name == "setup_complete" else None
            if what:
                self.first(uid, what)

    def set_source(self, uid: str, src: Any) -> str:
        """"How did you hear about rabbt?" (once; a later answer just replaces your own)."""
        if src not in SOURCES:
            raise ValueError("source")

        def fn(mine: dict[str, Any], g: dict[str, Any], today: date) -> None:
            if not mine.get("src"):
                day = g.setdefault("sources", {}).setdefault(today.isoformat(), {})
                day[src] = day.get(src, 0) + 1
            mine["src"] = src
        self._update(uid, fn)
        return str(src)

    def source_of(self, uid: str) -> str | None:
        return self._mine(uid).load().get("src")

    # ------------------------------------------------------------- pulse --
    def pulse_due(self, uid: str) -> bool:
        """The one "How likely are you to recommend rabbt?" card: from day 7, until answered or
        dismissed."""
        mine = self._mine(uid).load()
        if mine.get("pulse"):
            return False
        raw = mine.get("joined") or self._joined_of(uid)
        try:
            return bool(raw) and (self.today() - _d(raw)).days >= PULSE_AFTER_DAYS
        except ValueError:
            return False

    def pulse(self, uid: str, score: Any = None, note: Any = None, *, name: str = "",
              counted: bool = True) -> None:
        """Answer (0-10 plus an optional note) or dismiss (``score`` None). Asked once either way.
        ``counted`` False (usage off / DNT): no histogram, but the note still reaches us."""
        if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10):
            raise ValueError("score")
        text = " ".join(str(note).split())[:NOTE_LEN] if isinstance(note, str) else ""

        def fn(mine: dict[str, Any], g: dict[str, Any], today: date) -> None:
            if mine.get("pulse"):
                return
            mine["pulse"] = today.isoformat()
            if score is not None and counted:
                day = g.setdefault("nps", {}).setdefault(today.isoformat(), {})
                day[str(score)] = day.get(str(score), 0) + 1
        self._update(uid, fn)
        if text:
            first = (name.split() or [""])[0][:30]

            def add(d: dict[str, Any]) -> None:
                notes = d.setdefault("notes", [])
                notes.insert(0, {"uid": uid, "name": first, "score": score, "note": text,
                                 "date": self.today().isoformat()})
                del notes[MAX_NOTES:]
            self._store.global_doc("pulse_notes").update(add)

    def forget(self, uid: str) -> None:
        self._mine(uid).delete()

        def drop(d: dict[str, Any]) -> None:
            d["notes"] = [n for n in d.get("notes") or [] if n.get("uid") != uid]
        self._store.global_doc("pulse_notes").update(drop)

    # -------------------------------------------------------------- read --
    def summary(self, clubs_doc: dict[str, Any] | None = None) -> dict[str, Any]:
        g = self._store.global_doc("traction").load()
        notes = self._store.global_doc("pulse_notes").load().get("notes") or []
        return summarize(g, self.today(), clubs_doc or {}, notes)


def _cohort_rows(cohorts: dict[str, Any], today: date, lo: int, hi: int) -> list[dict[str, Any]]:
    """Cohorts that signed up between ``hi`` and ``lo`` days ago (inclusive)."""
    return [cohorts.get((today - timedelta(days=i)).isoformat()) or {} for i in range(lo, hi + 1)]


def _s(rows: Iterable[dict[str, Any]], key: str) -> int:
    return sum(int(r.get(key, 0)) for r in rows)


def nps_of(hist: dict[str, int]) -> dict[str, Any]:
    n = sum(hist.values())
    pro = sum(v for k, v in hist.items() if int(k) >= 9)
    det = sum(v for k, v in hist.items() if int(k) <= 6)
    return {"answers": n, "promoters": pro, "passives": n - pro - det, "detractors": det,
            "score": round(100 * (pro - det) / n) if n else None,
            "hist": [int(hist.get(str(i), 0)) for i in range(11)]}


def organizers(clubs_doc: dict[str, Any], today: date, weeks: int = 4) -> dict[str, Any]:
    """Weekly organizer health from the clubs doc (counts only): club pages created, runs held,
    RSVPs per run, check-in rate, repeat attendees, and clubs running weekly with >= 8 RSVPs."""
    start = today - timedelta(days=today.weekday())  # this Monday
    out = []
    span = [(start - timedelta(weeks=i), start - timedelta(weeks=i) + timedelta(days=6)) for i in range(weeks, 0, -1)]
    clubs = [c for c in (clubs_doc.get("clubs") or {}).values() if isinstance(c, dict)]
    healthy = 0
    last_lo, last_hi = span[-1]
    for c in clubs:
        runs = going = 0
        for m in (c.get("meetups") or {}).values():
            for k, h in (m.get("history") or {}).items():
                if last_lo.isoformat() <= k <= last_hi.isoformat():
                    runs += 1
                    going += int(h.get("going") or 0)
        if runs and going / runs >= TARGETS["rsvps_per_run"]:
            healthy += 1
    for lo, hi in span:
        a, b = lo.isoformat(), hi.isoformat()
        created = posted = runs = going = checkins = 0
        for c in clubs:
            if lo <= datetime.fromtimestamp(int(c.get("created") or 0), UTC).date() <= hi:
                created += 1
            for m in (c.get("meetups") or {}).values():
                if lo <= datetime.fromtimestamp(int(m.get("created") or 0), UTC).date() <= hi:
                    posted += 1
                for k, h in (m.get("history") or {}).items():
                    if a <= k <= b:
                        runs += 1
                        going += int(h.get("going") or 0)
                        checkins += int(h.get("checkins") or 0)
        out.append({"week": iso_week(lo), "from": a, "clubs_created": created, "runs_posted": posted,
                    "runs_held": runs, "rsvps_per_run": round(going / runs, 1) if runs else None,
                    "checkin_pct": _pct(checkins, going)})
    repeat = 0
    for c in clubs:
        regs: dict[str, int] = {}
        for m in (c.get("meetups") or {}).values():
            for who, n in (m.get("regulars") or {}).items():
                regs[who] = regs.get(who, 0) + int(n or 0)
        repeat += sum(1 for n in regs.values() if n >= 2)
    return {"weeks": out, "clubs": len(clubs), "healthy_clubs": healthy, "repeat_attendees": repeat}


def denver_clubs(clubs_doc: dict[str, Any]) -> int:
    n = 0
    for c in (clubs_doc.get("clubs") or {}).values():
        if not isinstance(c, dict) or not (c.get("meetups") or c.get("slug")):
            continue
        lat = next((m.get("lat") for m in (c.get("meetups") or {}).values() if m.get("lat") is not None), None)
        lng = next((m.get("lng") for m in (c.get("meetups") or {}).values() if m.get("lng") is not None), None)
        if (lat is not None and in_denver(lat, lng)) or (
                lat is None and str(c.get("city") or "").strip().lower() == "denver"
                and str(c.get("state") or "").strip().upper() in ("CO", "COLORADO")):
            n += 1
    return n


def summarize(g: dict[str, Any], today: date, clubs_doc: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    cohorts = g.get("cohorts") or {}
    win = _cohort_rows(cohorts, today, 0, WINDOW - 1)
    signups = _s(win, "signup")
    funnel = [{"id": "signup", "users": signups}] + [
        {"id": k, "users": _s(win, f"f.{k}") if k != "job" else _s(win, "job")} for k in ("area_set", "job", "plan_built")]
    for f in funnel:
        f["pct"] = _pct(f["users"], signups)
    # activated within 7 days: cohorts whose 7 days are over (joined 7..36 days ago)
    done7 = _cohort_rows(cohorts, today, 7, WINDOW + 6)
    c7, a7 = _s(done7, "signup"), _s(done7, "core7")
    # week-4 retention: activated cohorts whose week 4 is over (joined 28..57 days ago)
    done28 = _cohort_rows(cohorts, today, 28, WINDOW + 27)
    act28, w4 = _s(done28, "core"), _s(done28, "w4")
    weeks = g.get("weeks") or {}
    wk_keys = sorted(weeks)[-8:]
    last_full = iso_week(today - timedelta(days=7))
    lw = weeks.get(last_full) or {}
    src_days = [v for k, v in (g.get("sources") or {}).items() if k >= (today - timedelta(days=WINDOW - 1)).isoformat()]
    sources = [{"id": s, "users": sum(int(d.get(s, 0)) for d in src_days)} for s in SOURCES]
    refs = g.get("refs") or {}
    clubs_refs = sorted(({"slug": k[5:], "users": v} for k, v in refs.items() if k.startswith("club:")),
                        key=lambda r: -r["users"])[:20]
    hist: dict[str, int] = {}
    for k, v in (g.get("nps") or {}).items():
        if k >= (today - timedelta(days=90)).isoformat():
            for s, n in v.items():
                hist[s] = hist.get(s, 0) + int(n)
    org = organizers(clubs_doc, today)
    dclubs = denver_clubs(clubs_doc)
    return {
        "targets": TARGETS,
        "growth": {"signups": signups, "sources": sources, "answered": sum(s["users"] for s in sources),
                   "invite_joins": int(refs.get("invite", 0)), "club_joins": sum(r["users"] for r in clubs_refs),
                   "club_refs": clubs_refs},
        "activation": {"funnel": funnel, "core7": {"cohort": c7, "users": a7, "pct": _pct(a7, c7)},
                       "firsts": {k: _s(win, f"f.{k}") for k in FIRSTS}},
        "retention": {"w4": {"cohort": act28, "users": w4, "pct": _pct(w4, act28)}},
        "weeks": [{"week": k, "active": int(weeks[k].get("active", 0)), "denver": int(weeks[k].get("denver", 0))}
                  for k in wk_keys],
        "denver": {"week": last_full, "active": int(lw.get("denver", 0)), "runners": DENVER_RUNNERS,
                   "pct": round(100 * int(lw.get("denver", 0)) / DENVER_RUNNERS, 2),
                   "clubs": dclubs, "known_clubs": DENVER_CLUBS, "clubs_pct": _pct(dclubs, DENVER_CLUBS)},
        "organizers": org,
        "nps": nps_of(hist),
        "notes": [{k: n.get(k) for k in ("name", "score", "note", "date")} for n in notes[:50]],
    }


__all__ = ["CORE", "FIRSTS", "SOURCES", "TARGETS", "Traction", "in_denver", "nps_of", "organizers", "summarize"]
