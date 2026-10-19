"""TrainingPeaks two-way sync for the Rabbit app (any athlete, their own TrainingPeaks login).

Auth: TrainingPeaks has no public API and its sign-in form is behind a captcha, so we can't
take a username + password. The athlete pastes their ``Production_tpAuth`` session cookie
(the same thing ``garmin-mcp-trainingpeaks-login`` stores for the MCP server) into the connect
sheet; it is checked once against TrainingPeaks and stored only in the encrypted per-user
``trainingpeaks`` doc. It is never logged and never sent back to the browser. The client
exchanges it for an in-memory bearer (``trainingpeaks.TrainingPeaksClient``). When
TrainingPeaks rejects it the row turns "Needs attention" and the app asks to reconnect;
nothing re-authenticates on its own.

What it does (state in the encrypted ``tp_sync`` doc):
- **Pull**: planned workouts from 14 days back to 42 days ahead (``TrainingPeaksService.calendar``)
  -> compact items (title, sport, minutes, distance, description, coach notes, structure lines).
  Pure completed entries (no planned values) are skipped: completed workouts come from Garmin
  only. A planned workout is *linked* to a matching Garmin activity (same day + sport), never
  copied.
- **Source of truth** (``source``): ``trainingpeaks`` (default: the coach's plan; nothing is
  written to TrainingPeaks unasked) or ``rabbit``. ``view`` matches TrainingPeaks workouts to
  Rabbit sessions (same day + sport + similar duration, or a workout we pushed) and shows one of
  each pair: the source's.
- **Push** (``source == "rabbit"``): Rabbit's sessions for the next 14 days become planned
  TrainingPeaks workouts (structured for bike = %FTP and run = %threshold HR). ``pushed`` maps
  session id -> workout id + content hash, so edits update, moves change the date and deleted
  sessions delete; only workout ids in that map are ever changed or deleted.
- **Move** (``source == "trainingpeaks"``, or a coach workout with no Rabbit twin): moving a
  TrainingPeaks workout in Rabbit PUTs its new date to TrainingPeaks.

Rate limits: a per-user token bucket on every TrainingPeaks call, exponential backoff after
429/5xx/network trouble, a per-user lock so a tick and "Sync now" never overlap, and the tick
pulls at most every ``PULL_EVERY_S``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import httpx2

from .appstore import AppStore
from .logs import log_event
from .providers import NotFound, RateLimited
from .resilience import RateLimiter
from .tokens import TokenStore
from .tp_login_cli import clean_cookie
from .trainingpeaks import (
    SPORT_NAMES,
    TPReauthRequired,
    TrainingPeaksClient,
    TrainingPeaksError,
    TrainingPeaksService,
    is_completed,
    workout_payload,
)
from .weekplan import _seconds, sport_of

logger = logging.getLogger(__name__)

COOKIE_DOC = "trainingpeaks"
STATE_DOC = "tp_sync"
SOURCES = ("trainingpeaks", "rabbit")
PULL_BACK_DAYS = 14
PULL_AHEAD_DAYS = 42
PUSH_DAYS = 14
PULL_EVERY_S = 30 * 60
PUSH_DEBOUNCE_S = 3.0
BACKOFF_S = (120, 300, 900, 3600)
MAX_ITEMS = 200
RABBIT_NOTE = "Planned in rabbt."
# The app's HTTP transport for TrainingPeaks (None = the network). Tests set a MockTransport.
TRANSPORT: httpx2.BaseTransport | None = None

REAUTH_MSG = "Your TrainingPeaks sign-in expired. Reconnect to keep your plan in sync."
BUSY_MSG = "TrainingPeaks is busy right now. rabbt will try again in a few minutes."
FORBIDDEN_MSG = ("TrainingPeaks said no to that (some calendar features need TrainingPeaks "
                 "Premium, or your coach may have locked this workout).")

# TrainingPeaks sport -> Rabbit's plan sports (weekplan.sport_of keys).
TP_TO_RABBIT = {"swim": "swim", "bike": "bike", "mtb": "bike", "run": "run", "brick": "brick",
                "strength": "strength", "race": "race", "dayoff": "rest"}
RABBIT_TO_TP = {"swim": "swim", "bike": "bike", "run": "run", "brick": "brick",
                "strength": "strength", "other": "other"}
# Rabbit zones -> % of threshold for TrainingPeaks structure.
BIKE_FTP = {1: (45, 55), 2: (56, 75), 3: (76, 90), 4: (91, 105), 5: (106, 120)}
RUN_HR = {1: (65, 80), 2: (81, 89), 3: (90, 94), 4: (95, 100), 5: (101, 106)}
STEP_KIND = {"warmup": "warmup", "cooldown": "cooldown", "recover": "rest", "rest": "rest"}


class TPUserError(ValueError):
    """A message safe to show the athlete (400/409 from the routes)."""

    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ------------------------------------------------------------------ store ---
class CookieDocStore(TokenStore):
    """The per-user ``trainingpeaks`` AppStore doc as the client's cookie store (encrypted)."""

    def __init__(self, store: AppStore) -> None:
        self._s = store

    def load(self, user_id: str) -> str | None:
        return self._s.user_doc(user_id, COOKIE_DOC).load().get("cookie") or None

    def save(self, user_id: str, blob: str) -> None:
        self._s.user_doc(user_id, COOKIE_DOC).update(lambda d: d.update(cookie=blob))

    def delete(self, user_id: str) -> None:
        self._s.user_doc(user_id, COOKIE_DOC).delete()


class _OneShot(TokenStore):
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

    def load(self, user_id: str) -> str | None:
        return self.cookie

    def save(self, user_id: str, blob: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete(self, user_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


# ------------------------------------------------------------ pure helpers ---
def _minutes(hours: Any) -> int | None:
    return int(round(hours * 60)) if isinstance(hours, int | float) and hours > 0 else None


def _pct(t: dict[str, Any]) -> str:
    lo, hi = t.get("minValue"), t.get("maxValue")
    if not isinstance(lo, int | float):
        return ""
    return f"{lo:g}%" if not isinstance(hi, int | float) or hi == lo else f"{lo:g}-{hi:g}%"


def structure_lines(raw: Any) -> list[str]:
    """TrainingPeaks structure JSON -> short readable lines ("3x: 5' 95-105%, 3' 55%")."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, dict) or not isinstance(raw.get("structure"), list):
        return []
    metric = {"percentOfFtp": "FTP", "percentOfThresholdHr": "threshold HR",
              "percentOfThresholdPace": "threshold pace"}.get(str(raw.get("primaryIntensityMetric")), "")

    def step(s: dict[str, Any]) -> str:
        ln = s.get("length") or {}
        v, unit = ln.get("value"), ln.get("unit")
        size = (f"{v / 60:g}'" if unit == "second" and isinstance(v, int | float)
                else f"{v:g} {unit}" if isinstance(v, int | float) else "")
        tg = (s.get("targets") or [{}])[0] if isinstance(s.get("targets"), list) else {}
        name = str(s.get("name") or "").strip()
        return " ".join(x for x in (name, size, _pct(tg) if isinstance(tg, dict) else "") if x)

    out: list[str] = []
    for b in raw["structure"][:40]:
        if not isinstance(b, dict):
            continue
        steps = [step(s) for s in b.get("steps") or [] if isinstance(s, dict)]
        reps = (b.get("length") or {}).get("value")
        if b.get("type") == "repetition" and isinstance(reps, int) and reps > 1:
            out.append(f"{reps}x: " + ", ".join(steps))
        else:
            out.extend(steps)
    if out and metric:
        out.append(f"(% of {metric})")
    return [x[:160] for x in out]


def compact(w: dict[str, Any]) -> dict[str, Any] | None:
    """One TrainingPeaks workout for the app, or None for pure completed entries / days off."""
    planned = any(isinstance(w.get(k), int | float) and w.get(k) > 0
                  for k in ("totalTimePlanned", "distancePlanned", "tssPlanned")) or bool(w.get("structure"))
    if is_completed(w) and not planned:
        return None
    tp_sport = SPORT_NAMES.get(w.get("workoutTypeValueId"), "other")
    sport = TP_TO_RABBIT.get(str(tp_sport), "other")
    if sport == "rest" or not isinstance(w.get("workoutId"), int):
        return None
    dist = w.get("distancePlanned")
    return {
        "id": w["workoutId"],
        "date": str(w.get("workoutDay") or "")[:10],
        "sport": sport,
        "tp_sport": tp_sport,
        "title": str(w.get("title") or "Workout")[:200],
        "minutes": _minutes(w.get("totalTimePlanned")),
        "distance_km": round(dist / 1000, 2) if isinstance(dist, int | float) and dist > 0 else None,
        "tss": w.get("tssPlanned") if isinstance(w.get("tssPlanned"), int | float) else None,
        "description": str(w.get("description") or "")[:2000] or None,
        "coach_notes": str(w.get("coachComments") or "")[:2000] or None,
        "structure": structure_lines(w.get("structure")),
        "completed": is_completed(w),
    }


def session_hash(day: str, s: dict[str, Any]) -> str:
    keep = {k: s.get(k) for k in ("sport", "kind", "title", "minutes", "detail", "meters", "steps", "legs")}
    return hashlib.sha256(json.dumps([day, keep], sort_keys=True, default=str).encode()).hexdigest()[:16]


def _zone_step(st: dict[str, Any], table: dict[int, tuple[int, int]]) -> dict[str, Any]:
    if isinstance(st.get("pct"), int | float):
        lo = hi = float(st["pct"])
        lo, hi = max(0.0, lo - 2.5), min(300.0, hi + 2.5)
    else:
        lo, hi = table.get(int(st.get("zone") or 2), table[2])
    return {"minutes": max(1 / 60, float(st.get("minutes") or 0)), "low": lo, "high": hi,
            "kind": STEP_KIND.get(str(st.get("type")), "active")}


def session_structure(s: dict[str, Any]) -> dict[str, Any] | None:
    """Rabbit steps -> trainingpeaks.build_structure input (bike %FTP, run %threshold HR)."""
    table, metric = {"bike": (BIKE_FTP, "ftp"), "run": (RUN_HR, "hr")}.get(s.get("sport") or "", (None, ""))
    steps = s.get("steps") or []
    if table is None or not steps:
        return None
    out: list[dict[str, Any]] = []
    for st in steps:
        if not isinstance(st, dict):
            return None
        if st.get("type") == "repeat":
            inner = [x for x in st.get("steps") or [] if isinstance(x, dict) and x.get("minutes")]
            if not inner:
                return None
            out.append({"repeat": int(st.get("reps") or 1), "steps": [_zone_step(x, table) for x in inner]})
        elif st.get("minutes"):
            out.append(_zone_step(st, table))
        else:  # meters (swim) or something we can't express: plain workout instead
            return None
    return {"metric": metric, "steps": out}


def session_payload(day: str, s: dict[str, Any]) -> dict[str, Any]:
    """Wire fields for one Rabbit session (structure when we can express it)."""
    sport = "race" if s.get("kind") == "race" else RABBIT_TO_TP.get(s.get("sport") or "", "other")
    desc = "\n\n".join(x for x in (str(s.get("detail") or "").strip(), RABBIT_NOTE) if x)
    minutes = s.get("minutes") if isinstance(s.get("minutes"), int | float) and s.get("minutes") > 0 else None
    km = round(s["meters"] / 1000, 2) if isinstance(s.get("meters"), int | float) and s.get("meters") > 0 else None
    common = dict(date_=day, sport=sport, title=str(s.get("title") or "Workout")[:200],
                  description=desc, duration_minutes=minutes, distance_km=km)
    struct = session_structure(s)
    if struct is not None:
        try:
            return workout_payload(**common, structure=struct)
        except TrainingPeaksError:
            pass
    return workout_payload(**common)


def _similar(a: int | None, b: int | None) -> bool:
    if not a or not b:
        return True
    return abs(a - b) <= max(10, 0.25 * max(a, b))


def match(items: list[dict[str, Any]], sessions: dict[str, list[dict[str, Any]]],
          pushed: dict[str, dict[str, Any]]) -> dict[int, str]:
    """TrainingPeaks workout id -> Rabbit session id: our own pushes first, then the same day
    + sport + similar duration (closest minutes wins; each session pairs once)."""
    out: dict[int, str] = {}
    used: set[str] = set()
    by_wid = {int(p["wid"]): sid for sid, p in pushed.items() if p.get("wid")}
    known = {s["id"] for ss in sessions.values() for s in ss}
    for it in items:
        sid = by_wid.get(it["id"])
        if sid and sid in known:
            out[it["id"]] = sid
    # A coach's similar workout duplicates a session even when we pushed that session too.
    for it in items:
        if it["id"] in out:
            continue
        cands = [s for s in sessions.get(it["date"], []) if s["id"] not in used
                 and (s.get("sport") == it["sport"] or (it["sport"] == "race" and s.get("kind") == "race"))
                 and _similar(it.get("minutes"), s.get("minutes"))]
        if not cands:
            continue
        best = min(cands, key=lambda s: abs((s.get("minutes") or 0) - (it.get("minutes") or 0)))
        out[it["id"]] = best["id"]
        used.add(best["id"])
    return out


def link_garmin(items: list[dict[str, Any]], acts: list[dict[str, Any]], today: str) -> dict[int, int]:
    """TrainingPeaks workout id -> Garmin activity id for past/today planned workouts done the
    same day in the same sport (closest duration). Links only; nothing is copied."""
    out: dict[int, int] = {}
    used: set[int] = set()
    by_day: dict[str, list[dict[str, Any]]] = {}
    for a in acts:
        d = str(a.get("date") or "")[:10]
        if d and isinstance(a.get("activity_id"), int):
            by_day.setdefault(d, []).append(a)
    for it in items:
        if it["date"] > today:
            continue
        cands = [a for a in by_day.get(it["date"], []) if a["activity_id"] not in used
                 and sport_of(a.get("sport")) == it["sport"]]
        if not cands:
            continue
        want = (it.get("minutes") or 0) * 60
        best = min(cands, key=lambda a: abs(_seconds(a.get("duration")) - want))
        out[it["id"]] = best["activity_id"]
        used.add(best["activity_id"])
    return out


def _sessions_by_day(plan: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for w in (plan or {}).get("weeks") or []:
        for d, ss in (w.get("days") or {}).items():
            real = [s for s in ss if s.get("sport") != "rest"]
            if real:
                out[d] = real
    return out


# ---------------------------------------------------------------- service ---
class TPSync:
    def __init__(self, store: AppStore, *, plan: Callable[[str], dict[str, Any] | None],
                 today: Callable[[str], date],
                 activities: Callable[[str], list[dict[str, Any]]] | None = None,
                 transport: httpx2.BaseTransport | None = None,
                 clock: Callable[[], float] = time.time, per_minute: int = 30,
                 spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
        self._s = store
        self._plan = plan
        self._today = today
        self._acts = activities
        self._transport = transport
        self._clock = clock
        self.client = TrainingPeaksClient(CookieDocStore(store), transport=transport, clock=clock)
        self.svc = TrainingPeaksService(self.client, allow_writes=True, limiter=RateLimiter(per_minute),
                                        today=date.today)
        self._spawn = spawn or self._timer
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._backoff: dict[str, tuple[float, int]] = {}  # uid -> (until, failures)
        self._pending: set[str] = set()

    # ---------------------------------------------------------- plumbing --
    @staticmethod
    def _timer(fn: Callable[[], None]) -> None:
        t = threading.Timer(PUSH_DEBOUNCE_S, fn)
        t.daemon = True
        t.start()

    def _lock(self, uid: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(uid, threading.Lock())

    def _state(self, uid: str):
        return self._s.user_doc(uid, STATE_DOC)

    def connected(self, uid: str) -> bool:
        return bool(self._s.user_doc(uid, COOKIE_DOC).load().get("cookie"))

    def source(self, uid: str) -> str:
        src = self._state(uid).load().get("source")
        return src if src in SOURCES else "trainingpeaks"

    def _set(self, uid: str, **fields: Any) -> None:
        self._state(uid).update(lambda d: d.update(fields))

    def _fail(self, uid: str, e: Exception) -> None:
        """Turn a TrainingPeaks failure into the row's status (and backoff when transient)."""
        if isinstance(e, TPReauthRequired):
            self.client.invalidate(uid)
            self._set(uid, error=REAUTH_MSG, code="reauth")
            return
        if isinstance(e, RateLimited) or (isinstance(e, TrainingPeaksError) and "HTTP 5" in str(e)) \
                or "Could not reach" in str(e):
            _, n = self._backoff.get(uid, (0.0, 0))
            self._backoff[uid] = (self._clock() + BACKOFF_S[min(n, len(BACKOFF_S) - 1)], n + 1)
            self._set(uid, error=BUSY_MSG, code="busy")
            return
        msg = FORBIDDEN_MSG if "HTTP 403" in str(e) else (
            str(e) if isinstance(e, TrainingPeaksError) else "TrainingPeaks didn't answer just now. Try again later.")
        self._set(uid, error=msg[:300], code="error")

    def _ok(self, uid: str, **fields: Any) -> None:
        self._backoff.pop(uid, None)
        self._set(uid, error=None, code=None, **fields)

    def in_backoff(self, uid: str) -> bool:
        until, _ = self._backoff.get(uid, (0.0, 0))
        return self._clock() < until

    # ------------------------------------------------------------ connect --
    def connect(self, uid: str, raw: str) -> dict[str, Any]:
        cookie = clean_cookie(str(raw or ""))
        if len(cookie) < 20 or len(cookie) > 8000 or any(c.isspace() for c in cookie):
            raise TPUserError("That doesn't look like the Production_tpAuth value. Copy the whole Value "
                              "(usually a few hundred characters) and paste it again.")
        probe = TrainingPeaksClient(_OneShot(cookie), transport=self._transport, clock=self._clock)
        try:
            user = probe.user(uid)
            athlete = probe.athlete_id(uid)
        except TPReauthRequired:
            raise TPUserError("TrainingPeaks didn't accept that sign-in. Sign in at app.trainingpeaks.com "
                              "again, copy a fresh Production_tpAuth value and paste it here.") from None
        except RateLimited:
            raise TPUserError(BUSY_MSG, 503) from None
        except TrainingPeaksError as e:
            raise TPUserError(FORBIDDEN_MSG if "HTTP 403" in str(e) else str(e)[:300], 502) from None
        name = " ".join(x for x in (user.get("firstName"), user.get("lastName")) if x) or None
        self._s.user_doc(uid, COOKIE_DOC).save({"cookie": cookie, "athlete_id": athlete,
                                                "name": name, "connected_at": int(self._clock())})
        self.client.invalidate(uid)
        self._backoff.pop(uid, None)
        self._state(uid).update(lambda d: d.update(error=None, code=None))
        log_event(logger, logging.INFO, "tp_connected", user_id=uid)
        return {"name": name}

    def disconnect(self, uid: str) -> None:
        """Forget the sign-in and the synced copy. Workouts already in TrainingPeaks stay."""
        self._s.user_doc(uid, COOKIE_DOC).delete()
        self._state(uid).update(lambda d: [d.pop(k, None) for k in
                                          ("items", "pulled_at", "error", "code", "pushed_at")])
        self.client.invalidate(uid)
        self._backoff.pop(uid, None)
        log_event(logger, logging.INFO, "tp_disconnected", user_id=uid)

    def set_source(self, uid: str, source: str) -> dict[str, Any]:
        if source not in SOURCES:
            raise TPUserError("Pick TrainingPeaks or rabbt.")
        self._set(uid, source=source)
        if source == "rabbit" and self.connected(uid):
            self.sync(uid)
        return self.view(uid)

    # --------------------------------------------------------------- sync --
    def pull(self, uid: str) -> None:
        today = self._today(uid)
        raw = self.svc.calendar(uid, today - timedelta(days=PULL_BACK_DAYS),
                                today + timedelta(days=PULL_AHEAD_DAYS))
        items = [c for c in (compact(w) for w in raw) if c is not None]
        items.sort(key=lambda i: (i["date"], i["id"]))
        self._ok(uid, items=items[:MAX_ITEMS], pulled_at=int(self._clock()))

    def push(self, uid: str) -> dict[str, int]:
        """Rabbit -> TrainingPeaks for the next PUSH_DAYS (only when Rabbit is the source)."""
        counts = {"created": 0, "updated": 0, "deleted": 0}
        if self.source(uid) != "rabbit":
            return counts
        today = self._today(uid)
        horizon = (today + timedelta(days=PUSH_DAYS - 1)).isoformat()
        t0 = today.isoformat()
        by_day = _sessions_by_day(self._plan(uid))
        where = {s["id"]: (d, s) for d, ss in by_day.items() for s in ss}
        pushed: dict[str, dict[str, Any]] = dict(self._state(uid).load().get("pushed") or {})

        def save() -> None:
            snap = dict(pushed)
            self._state(uid).update(lambda d: d.update(pushed=snap))

        try:
            # Sessions we pushed before: update, move or delete (ours only).
            for sid, rec in list(pushed.items()):
                if sid not in where:
                    if rec.get("date", "") >= t0 and not rec.get("done"):
                        try:
                            self.svc.delete_workout(uid, int(rec["wid"]))
                            counts["deleted"] += 1
                        except NotFound:
                            pass
                        except TrainingPeaksError as e:
                            if "completed data" not in str(e):
                                raise
                    if rec.get("date", "") >= t0 or rec.get("date", "") < (today - timedelta(days=60)).isoformat():
                        pushed.pop(sid, None)
                        save()
                    continue
                day, s = where[sid]
                h = session_hash(day, s)
                if h == rec.get("hash") or rec.get("done") or day < t0:
                    continue
                try:
                    self.svc.update_workout(uid, int(rec["wid"]), session_payload(day, s))
                    pushed[sid] = {"wid": rec["wid"], "hash": h, "date": day}
                    counts["updated"] += 1
                except NotFound:  # deleted in TrainingPeaks: the changed session goes back up
                    pushed.pop(sid, None)
                except TrainingPeaksError as e:
                    if "completed data" not in str(e):
                        raise
                    pushed[sid] = rec | {"done": True}
                save()
            # New sessions in the window.
            for day in sorted(by_day):
                if not t0 <= day <= horizon:
                    continue
                for s in by_day[day]:
                    if s["id"] in pushed:
                        continue
                    wid = self.svc.create_planned(uid, session_payload(day, s)).get("workoutId")
                    if isinstance(wid, int):
                        pushed[s["id"]] = {"wid": wid, "hash": session_hash(day, s), "date": day}
                        counts["created"] += 1
                        save()
        finally:
            save()
        self._ok(uid, pushed_at=int(self._clock()))
        if any(counts.values()):
            log_event(logger, logging.INFO, "tp_pushed", user_id=uid, **counts)
        return counts

    def sync(self, uid: str, *, wait: bool = True) -> dict[str, Any]:
        """Push (Rabbit source) then pull. Returns {ok, error?, counts?}."""
        if not self.connected(uid):
            return {"ok": False, "error": "TrainingPeaks isn't connected."}
        lock = self._lock(uid)
        if not lock.acquire(timeout=30 if wait else 0):
            return {"ok": False, "error": "Already syncing."}
        try:
            counts = self.push(uid)
            self.pull(uid)
            return {"ok": True, "counts": counts}
        except Exception as e:
            if not isinstance(e, TrainingPeaksError | RateLimited):
                log_event(logger, logging.WARNING, "tp_sync_failed", user_id=uid, error=type(e).__name__)
            self._fail(uid, e)
            self._set(uid, tried_at=int(self._clock()))  # the tick waits PULL_EVERY_S after a failure too
            return {"ok": False, "error": self._state(uid).load().get("error")}
        finally:
            lock.release()

    def tick(self, uid: str) -> None:
        """From Moments.on_tick (once a minute per user): pull every PULL_EVERY_S."""
        if uid.startswith("coach_") or not self.connected(uid) or self.in_backoff(uid):
            return
        st = self._state(uid).load()
        if st.get("code") == "reauth":
            return
        last = max(float(st.get("pulled_at") or 0), float(st.get("tried_at") or 0))
        if self._clock() - last < PULL_EVERY_S or uid in self._pending:
            return
        self._pending.add(uid)

        def run() -> None:  # off the tick thread: a slow TrainingPeaks never delays other users
            self._pending.discard(uid)
            self.sync(uid, wait=False)
        self._spawn(run)

    def on_plan_write(self, uid: str, doc: str) -> None:
        """AppStore.on_user_write: a Rabbit plan changed -> push soon (debounced)."""
        if not doc.startswith("plan-") or uid in self._pending:
            return
        try:
            if not self.connected(uid) or self.source(uid) != "rabbit":
                return
        except Exception:
            return
        self._pending.add(uid)

        def run() -> None:
            self._pending.discard(uid)
            self.sync(uid)
        self._spawn(run)

    # --------------------------------------------------------------- move --
    def move(self, uid: str, wid: int, day: str) -> dict[str, Any]:
        try:
            new = date.fromisoformat(str(day)).isoformat()
        except ValueError:
            raise TPUserError("date must be YYYY-MM-DD") from None
        if new < self._today(uid).isoformat():
            raise TPUserError("Workouts can't be moved into the past.")
        st = self._state(uid).load()
        item = next((i for i in st.get("items") or [] if i["id"] == wid), None)
        if item is None:
            raise TPUserError("That workout isn't on your TrainingPeaks calendar anymore. Sync and try again.", 404)
        if item.get("completed"):
            raise TPUserError("That workout is already done, so it stays where it is.", 409)
        ours = {int(p["wid"]) for p in (st.get("pushed") or {}).values() if p.get("wid")}
        if wid in ours and self.source(uid) == "rabbit":
            raise TPUserError("This one follows your rabbt plan: move the session in rabbt and "
                              "TrainingPeaks follows.", 409)
        with self._lock(uid):
            try:
                self.svc.update_workout(uid, wid, {"workoutDay": f"{new}T00:00:00"})
            except (TrainingPeaksError, RateLimited) as e:
                self._fail(uid, e)
                if isinstance(e, NotFound):
                    raise TPUserError("TrainingPeaks says that workout no longer exists.", 404) from None
                raise TPUserError(self._state(uid).load().get("error") or str(e), 502) from None

            def apply(d: dict[str, Any]) -> None:
                for i in d.get("items") or []:
                    if i["id"] == wid:
                        i["date"] = new
                d["items"] = sorted(d.get("items") or [], key=lambda i: (i["date"], i["id"]))
            self._state(uid).update(apply)
        return self.view(uid)

    # --------------------------------------------------------------- view --
    def status(self, uid: str) -> dict[str, Any]:
        on = self.connected(uid)
        st = self._state(uid).load() if on else {}
        return {"connected": on, "attention": on and st.get("code") == "reauth",
                "last_sync": st.get("pulled_at"), "error": st.get("error") if on else None,
                "source": self.source(uid)}

    def view(self, uid: str) -> dict[str, Any]:
        """For the plan calendar: TrainingPeaks items to show, Rabbit sessions to hide."""
        on = self.connected(uid)
        st = self._state(uid).load()
        src = st.get("source") if st.get("source") in SOURCES else "trainingpeaks"
        base = {"connected": on, "source": src, "last_sync": st.get("pulled_at"),
                "state": ("attention" if st.get("code") == "reauth" else "connected") if on else "not_connected",
                "error": st.get("error") if on else None, "items": [], "hide_sessions": [],
                "linked_sessions": {}}
        if not on:
            return base
        items = [dict(i) for i in st.get("items") or []]
        pushed = st.get("pushed") or {}
        ours = {int(p["wid"]) for p in pushed.values() if p.get("wid")}
        try:
            plan = self._plan(uid)
        except Exception:
            plan = None
        pairs = match(items, _sessions_by_day(plan), pushed)
        acts: list[dict[str, Any]] = []
        if self._acts is not None:
            try:
                acts = self._acts(uid)
            except Exception:
                acts = []
        links = link_garmin(items, acts, self._today(uid).isoformat())
        hide: list[str] = []
        for it in items:
            sid = pairs.get(it["id"])
            it["ours"] = it["id"] in ours
            it["session_id"] = sid
            it["garmin_activity_id"] = links.get(it["id"])
            it["show"] = src == "trainingpeaks" or sid is None
            it["can_move"] = not it["completed"] and not (it["ours"] and src == "rabbit")
            if sid and src == "trainingpeaks":
                hide.append(sid)
        base["items"] = items
        base["hide_sessions"] = hide
        base["linked_sessions"] = {sid: wid for wid, sid in sorted(pairs.items(), key=lambda p: p[0] in ours)}
        return base


__all__ = ["TPSync", "TPUserError", "compact", "match", "link_garmin", "session_payload",
           "structure_lines", "SOURCES"]
