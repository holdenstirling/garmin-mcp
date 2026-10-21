"""Community: a small, calm feed of life events and accomplishments (not every workout).

Posts
-----
* **What people choose to share**: a category (race, personal best, milestone, life event,
  comeback, gratitude, other), text <= ``TEXT_LEN``, up to ``MAX_PHOTOS`` photos (resized in
  the browser to <= 1600 px JPEG/WebP <= 800 KB, checked here by magic bytes and size, stored
  encrypted; per-user quota ``PHOTO_QUOTA_COUNT`` photos / ``PHOTO_QUOTA_BYTES``), an optional
  link to one of their events, an optional feeling.
* **Milestones**, spotted deterministically: race finished (result, debrief or a race-day
  workout), personal best (the reaction card's 12-month bests), streak 7/14/30/50/100, level
  up, badge, challenge completed, firsts (first ultra, marathon, 70.3, century...). They are
  **drafts**, never posted on their own, unless the athlete turned on auto-share for that
  type: Rabbit posts a moment "🎉 ... Share it?" [Share] [Not now] and the drafts tray shows them.
* **Shared workouts**: from the reaction card, on request: sport, distance, time and a
  highlight line. Never maps, heart rate, power or any health/Oura data.
* **Auto-shared workouts** ("Share my workouts with friends", ``share_workouts``): each newly
  synced workout (today/yesterday, dated on or after the day sharing started) is posted once
  to ``share_audience`` (``friends`` by default, or chosen feed groups) as the same compact
  card, with the title replaced by the sport ("Run") since Garmin names often carry a place,
  plus pace, a split bar shape (lap times only, ``splits_from``) and the workout reward's
  headline. Unset + the one-time prompt shown = on (the default); never asked = nothing
  posted; declined = private. For ``PIN_S`` after it posts, it is pinned at the top of the
  author's own feed with "Add a photo or caption".

Unread (``unread``): new reactions/comments on my posts (per post), cleared when I open the
post or Community (``mark_seen``); feeds the app icon badge (``unread.py``).

Audience per post: ``friends`` (people with an active follow edge to the author),
``club:<id>`` (members of that club or race group), ``grp:<gid>[,<gid>...]`` (members of those
feed groups, ``feedgroups.py``, while the author is in one too), ``public`` (every allowlisted
athlete on Rabbit) or ``private`` (only me, a journal). Blocked people (either way) never see each other's
posts, comments or reactions. Reactions (one per person, switchable): 🎉 💪 ❤️ 🐇. Comments
<= ``COMMENT_LEN``, threaded one level (a reply to a reply joins its parent), at most
``MAX_COMMENTS`` per post; the post's author can delete any comment on it. Hide = gone for me;
report = hidden + logged for the operator. Rate limits per athlete and local day:
``POSTS_PER_DAY`` posts and ``COMMENTS_PER_DAY`` comments.

Pushes for reactions/comments go to the author (and a reply's parent author) at most once per
post per hour, never in quiet hours (21:00-07:00 local, same as moments).

Storage
-------
* Per author ``posts`` doc ``{"posts": {pid: post}}`` (bounded).
* Per user ``community`` doc: ``settings``, ``drafts``, dedupe ``keys``, photo usage,
  ``hidden`` posts, daily ``rate`` counters.
* Per author ``cphoto-<id>`` doc: one encrypted photo.
* Global ``community`` doc: ``index`` {pid: author}, ``public`` {pid: [author, created]} and
  capped ``reports``.
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from . import mentions as _mn
from . import routes as _rt
from .appstore import AppStore
from .explore import parse_distance_km
from .logs import log_event
from .progress import tier_name
from . import sportfamily as _sf
from .stats import _rows, _seconds, category

logger = logging.getLogger(__name__)

TEXT_LEN = 500
COMMENT_LEN = 280
MAX_COMMENTS = 200
MAX_PHOTOS = 10
PAGE = 20
MAX_POSTS = 1000          # per author; oldest dropped
MAX_PUBLIC = 2000         # public index; oldest dropped
MAX_DRAFTS = 20
DRAFT_TTL_DAYS = 14
MAX_KEYS = 600
MAX_HIDDEN = 1000
MAX_REPORTS = 500
FEED_FOLLOWEES = 500
PREVIEW_COMMENTS = 2
PUSH_EVERY_S = 3600
ASK_EVERY_S = 7 * 86400    # "Ask to see their workouts": once a week per friend
WAITING_MAX = 6            # the Feed's "haven't shared yet" row
MAX_MENTION_ITEMS = 50   # newest @mentions kept per person for the bell
MAX_LIKE_ITEMS = 50      # newest liked-comment bell items kept per person
LIKES_PER_DAY = 500
POSTS_PER_DAY = 20
COMMENTS_PER_DAY = 100
PHOTO_MAX = 800 * 1024
PHOTO_MAX_SIDE = 1600
PHOTO_QUOTA_COUNT = 300
PHOTO_QUOTA_BYTES = 300 * 1024 * 1024
ORPHAN_TTL_S = 86400
REMIND_EVERY_S = 600

CATEGORIES = ("race", "pb", "milestone", "life", "comeback", "gratitude", "other")
FEELINGS = ("😀", "🥳", "💪", "😅", "🥹", "🙏", "😤", "😴", "❤️", "🔥")
REACTIONS = ("party", "strong", "heart", "rabbit")  # 🎉 💪 ❤️ 🐇
AUDIENCES = ("friends", "public", "private")      # + "club:<id>"
MILESTONES = ("race", "pb", "streak", "level", "badge", "challenge", "first")
MILESTONE_CATEGORY = {"race": "race", "pb": "pb", "streak": "milestone", "level": "milestone",
                      "badge": "milestone", "challenge": "milestone", "first": "race"}
FIRSTS = {"ultra": "First ultra", "marathon": "First marathon", "half": "First half marathon",
          "70.3": "First 70.3", "140.6": "First full-distance triathlon", "century": "First century ride"}
RACE_SCAN_DAYS = 7
# Fields a workout card may carry. Anything else (HR, power, location, health) is dropped.
WORKOUT_FIELDS = ("activity_id", "sport", "title", "date", "km", "minutes", "climb_m", "highlight",
                  "pace_s_km", "speed_kmh", "pace_s_100m", "splits", "headline", "auto", "source",
                  "family", "kind", "pace_s_500m", "vertical_m", "sets", "reps", "legs", "route", "late")
LEG_FIELDS = ("family", "km", "minutes", "pace_s_km", "speed_kmh", "pace_s_100m", "pace_s_500m")
# Where a workout came from ("via Garmin" on its card). Garmin ids are ints; other sources use
# "<source>:<id>" (workout ingestion adds ``source`` to each activity).
SOURCES = ("garmin", "oura", "whoop", "apple", "coros", "strava", "polar", "suunto", "wahoo")
_SRC_ID = re.compile(r"^[a-z]{2,12}:[A-Za-z0-9_.-]{1,64}$")


def activity_key(aid: Any) -> str | None:
    """A stable key for an activity id from any source: Garmin's int or "<source>:<id>"."""
    if isinstance(aid, int) and not isinstance(aid, bool):
        return str(aid)
    if isinstance(aid, str) and _SRC_ID.fullmatch(aid):
        return aid
    return None


def source_of(act: dict[str, Any] | None) -> str:
    src = str((act or {}).get("source") or "garmin").lower()
    return src if src in SOURCES else "garmin"
MAX_SPLITS = 40
PIN_S = 3600              # the author's fresh auto-shared workout leads their feed this long
LATEST_N = 3
LATEST_DAYS = 7
VIEWS = ("feed", "clubs")
MAX_GROUP_AUDIENCE = 10
# Auto-shared workouts are titled by sport (Garmin's names often include the city).
SPORT_TITLE = {"run": "Run", "bike": "Ride", "swim": "Swim", "brick": "Brick", "strength": "Strength",
               "hike": "Hike", "ski": "Ski", "climb": "Climb", "paddle": "Paddle"}
AUTO_DAYS = 2             # auto-share workouts from today and the 2 days before (late syncs, uploads)
AUTO_PER_SYNC = 3
BACKFILL_DAYS = 2         # turning sharing on posts today and the 2 days before, once
BACKFILL_MAX = 5
CATCHUP_S = 15 * 60       # catch-up check per person at most this often (tick and Feed loads)
MAX_UNREAD_POSTS = 200
EVENT_FIELDS = ("id", "name", "date", "type", "distance")
_PID = re.compile(r"^p[0-9a-f]{16}$")
_ID = re.compile(r"^[a-z][0-9a-f]{12,16}$")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_LEAD_EMOJI = re.compile(r"^[^\w]+")


def _home_public(h: Any) -> dict[str, Any] | None:
    """The hidden area as the owner's app sees it: its size only. Where it is stays on the server."""
    return {"radius_m": int(h.get("radius_m") or 0)} if isinstance(h, dict) else None


class CommunityError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _mtext(v: Any, limit: int, *, what: str = "Text") -> str:
    """``_text`` for text that may hold @mention tokens: the limit applies to what people read."""
    s = _text(v, limit + _mn.TOKEN_ROOM, what=what)
    if len(_mn.display(s)) > limit:
        raise CommunityError(f"Keep it under {limit} characters.")
    return s


def _text(v: Any, limit: int, *, what: str = "Text") -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise CommunityError(f"{what} must be text")
    s = _CTRL.sub("", v.replace("\r\n", "\n")).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    if len(s) > limit:
        raise CommunityError(f"Keep it under {limit} characters.")
    return s


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def valid_pid(pid: Any) -> str:
    if not isinstance(pid, str) or not _PID.match(pid):
        raise CommunityError("post not found", 404)
    return pid


def norm_audience(v: Any) -> Any:
    """Older names: ``followers`` -> ``friends``, ``group:`` -> ``club:``."""
    if v == "followers":
        return "friends"
    if isinstance(v, str) and v.startswith("group:"):
        return "club:" + v[6:]
    return v


# ------------------------------------------------------------------ photos --
def sniff_photo(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise CommunityError("Use a JPEG or WebP photo.")


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a JPEG or WebP header, else None."""
    try:
        if data.startswith(b"\xff\xd8"):
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    return None
                marker = data[i + 1]
                if marker == 0xFF:
                    i += 1
                    continue
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return w, h
                if seg < 2:
                    return None
                i += 2 + seg
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            kind = data[12:16]
            if kind == b"VP8 ":
                return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                        int.from_bytes(data[28:30], "little") & 0x3FFF)
            if kind == b"VP8L":
                b = data[21:25]
                return 1 + (b[0] | (b[1] & 0x3F) << 8), 1 + ((b[1] >> 6) | b[2] << 2 | (b[3] & 0x0F) << 10)
            if kind == b"VP8X":
                return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    except (IndexError, ValueError):
        return None
    return None


def check_photo(data: bytes) -> str:
    if not data:
        raise CommunityError("That photo is empty.")
    if len(data) > PHOTO_MAX:
        raise CommunityError("That photo is too large (max 800 KB).", 413)
    mime = sniff_photo(data)
    size = image_size(data)
    if size is None or not all(size):
        raise CommunityError("We couldn't read that photo. Try another one.")
    if max(size) > PHOTO_MAX_SIDE:
        raise CommunityError(f"That photo is too big (max {PHOTO_MAX_SIDE} px).")
    return mime


# ------------------------------------------------------------- milestones --
def event_class(ev: dict[str, Any]) -> str | None:
    """The "first ..." an event counts for: ultra, marathon, half, 70.3, 140.6, century."""
    dist = str(ev.get("distance") or "").strip().lower()
    typ = str(ev.get("type") or "").lower()
    name = str(ev.get("name") or "").lower()
    if dist in ("70.3",) or "70.3" in name or "half iron" in name:
        return "70.3"
    if dist == "140.6" or "140.6" in name or ("ironman" in name and typ == "triathlon"):
        return "140.6"
    if dist == "ultra":
        return "ultra"
    if dist == "century ride" or "century" in name:
        return "century"
    if dist == "half marathon":
        return "half"
    if dist == "marathon":
        return "marathon"
    km = parse_distance_km(dist) if dist else None
    if km is None:
        return None
    if typ in ("running", "trail", "mountaineering", ""):
        if km > 42.6:
            return "ultra"
        if km >= 42.0:
            return "marathon"
        if 21.0 <= km <= 21.2:
            return "half"
    if typ == "cycling" and km >= 160:
        return "century"
    return None


def event_snapshot(ev: dict[str, Any]) -> dict[str, Any]:
    return {k: ev.get(k) for k in EVENT_FIELDS}


def _fmt_km(km: float, imperial: bool) -> str:
    return f"{km * 0.621371:.1f} mi" if imperial else f"{km:.1f} km"


def _fmt_min(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d} h" if m >= 60 else f"{m} min"


def pb_text(best: dict[str, Any], imperial: bool) -> str:
    key, v = best["key"], float(best["value"])
    what = {"longest_run_km": "longest run", "longest_ride_km": "longest ride", "longest_swim_km": "longest swim",
            "longest_workout_min": "longest workout", "biggest_climb_m": "biggest climb"}.get(key, "best")
    if key.endswith("_km"):
        val = _fmt_km(v, imperial) if key != "longest_swim_km" else (
            f"{round(v * 1093.61):,} yd" if imperial else f"{round(v * 1000):,} m")
    elif key.endswith("_min"):
        val = _fmt_min(v)
    else:
        val = f"{round(v * 3.28084):,} ft" if imperial else f"{round(v):,} m"
    return f"New personal best: {what} this year, {val}."


def feed_ts(p: dict[str, Any]) -> int:
    """Where a post sorts in the Feed: when it was made, except that a workout auto-posted on
    a later day than it was done (a catch-up or a late sync, marked ``late``) sorts by its own
    day, never above workouts done after it."""
    created = int(p.get("created") or 0)
    w = p.get("workout") or {}
    day = w.get("date")
    if w.get("late") and isinstance(day, str):
        try:
            # end of that day plus 12 h, so a same-day post anywhere from UTC-12 keeps its time
            end = int(datetime.fromisoformat(day + "T23:59:59+00:00").timestamp()) + 12 * 3600
        except ValueError:
            return created
        return min(created, end)
    return created


def workout_card(acts: list[dict[str, Any]], aid: int | str, today: date) -> dict[str, Any] | None:
    """A compact, shareable workout: sport, its family (``sportfamily``: which numbers make
    sense), title, date, distance, time, climb and a highlight line, plus the one rate that
    suits the family, a multisport's legs, a ski day's vertical and a gym session's sets and
    reps. Never HR, power, location or health data."""
    from .workoutday import new_bests
    r = next((r for r in _rows(acts) if r["id"] == aid), None)
    if r is None:
        return None
    bests = new_bests(acts, aid, today)
    hl = bests[0]["label"] if bests else ""
    act = next((a for a in acts if a.get("activity_id") == aid), None) or {}
    fam = _sf.family(r["sport"], r.get("raw"))
    km = r["km"] if fam not in _sf.NO_DISTANCE else 0
    card: dict[str, Any] = {
        "activity_id": aid, "source": source_of(act), "sport": r["sport"], "family": fam,
        "kind": _clip(str(r.get("raw") or ""), 40), "title": _clip(str(r["name"] or "Workout"), 80),
        "date": r["date"].isoformat(), "km": round(km, 2) if km else None,
        "minutes": round(r["min"]) if r["min"] else None,
        "climb_m": int(r["climb"]) if r["climb"] and fam not in ("swim", "indoor_ride", "row", "mind", "strength", "hiit") else None,
        "highlight": hl, **_sf.pace_fields(fam, km, r["min"])}
    if fam == "ski":
        loss = act.get("elevation_loss_m")
        if isinstance(loss, int | float) and loss > 0:
            card["vertical_m"] = int(loss)
    if fam in ("strength", "hiit"):
        for k in ("total_sets", "total_reps"):
            v = act.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                card[k.removeprefix("total_")] = v
    if fam == "brick":
        legs = []
        for a in acts:
            if (a.get("multisport") or {}).get("parent_id") != aid:
                continue
            lf = _sf.family(category(a.get("sport")), a.get("sport"))
            if "transition" in str(a.get("sport") or "").lower():
                continue
            lkm = float(a.get("distance_km") or 0)
            lmin = _seconds(a.get("duration")) / 60
            legs.append({"family": lf, "km": round(lkm, 2) if lkm else None,
                         "minutes": round(lmin) if lmin else None, **_sf.pace_fields(lf, lkm, lmin)})
        if legs:
            card["legs"] = legs[:5]
    return card


def pace_fields(sport: str, km: float | None, minutes: float | None, raw: str | None = None) -> dict[str, Any]:
    """The rate that suits the workout's family (``sportfamily.pace_fields``)."""
    return _sf.pace_fields(_sf.family(sport, raw), km, minutes)


def splits_from(raw: Any) -> list[dict[str, Any]]:
    """Lap shape for the workout card: ``[{km, s}]`` from Garmin's ``get_activity_splits``
    (``lapDTOs``: distance m + duration s only; never HR, power or position). Laps under
    100 m are dropped; at most ``MAX_SPLITS``."""
    laps = raw.get("lapDTOs") if isinstance(raw, dict) else None
    out: list[dict[str, Any]] = []
    for lap in laps if isinstance(laps, list) else []:
        if not isinstance(lap, dict):
            continue
        d, t = lap.get("distance"), lap.get("duration")
        if not isinstance(d, int | float) or not isinstance(t, int | float) or isinstance(d, bool) or d < 100 or t <= 0:
            continue
        out.append({"km": round(float(d) / 1000, 2), "s": int(round(float(t)))})
    return out[:MAX_SPLITS] if len(out) >= 2 else []


def workout_label(w: dict[str, Any] | None) -> str:
    """"10K", "half marathon", "ride": how a cheer push names a workout."""
    if not w:
        return "post"
    sport, km = w.get("sport"), w.get("km") or 0
    if sport == "run" and km:
        for target, name in ((42.2, "marathon"), (21.1, "half marathon"), (10, "10K"), (5, "5K")):
            if abs(km - target) <= max(0.25, target * 0.03):
                return name
        if km >= 1:
            return f"{round(km):d} km run"
    return {"run": "run", "bike": "ride", "swim": "swim", "hike": "hike"}.get(str(sport), "workout")


def from_moment_text(m: dict[str, Any]) -> tuple[str, str] | None:
    """(milestone type, post text) for a moment that may become a draft."""
    t, key, text = m.get("type"), str(m.get("key") or ""), str(m.get("text") or "")
    if t == "streak":
        days = key.split(":")[-1]
        return "streak", f"{days}-day streak! Showing up, day after day. 🔥"
    if t == "level":
        try:
            n = int(key.split(":")[-1])
        except ValueError:
            return None
        return "level", f"Reached level {n} on rabbt: {tier_name(n)}. ⭐"
    if t == "badge":
        mm = re.search(r"Badge earned: (.+?)\.(?: \+\d+ XP\.)?$", text)
        return "badge", f"Earned the {mm.group(1) if mm else 'new'} badge. 🏅"
    if t == "challenge":
        mm = re.search(r"Challenge complete: (.+?) · ", text)
        return "challenge", f"Challenge complete: {mm.group(1) if mm else 'done'}. 🏆"
    return None


def meetup_line(m: dict[str, Any], today: date) -> str:
    """"📍 Tomorrow 7:00: Long run with Trail Crew · City Park.\""""
    t = datetime.fromisoformat(m["next"])
    day = "Today" if t.date() == today else "Tomorrow" if t.date() == today + timedelta(days=1) else t.strftime("%a")
    return _clip(f"📍 {day} {t.hour}:{t.minute:02d}: {m['title']} with {m['club']['name']} · {m['where']}.", 140)


# ------------------------------------------------------------------ service --
Push = Callable[[str, str, str], None]  # (to, title, body)


class Community:
    def __init__(self, store: AppStore, *, social: Any, clubs: Any, now: Callable[[str], datetime],
                 clock: Callable[[], float] = time.time,
                 moment: Callable[[str, dict[str, Any]], Any] | None = None,
                 push: Push | None = None, quiet: Callable[[str], bool] | None = None,
                 name: Callable[[str], str] = lambda u: "Someone") -> None:
        """``social``: ``social.Social``; ``clubs``: ``clubs.Clubs``; ``moment(uid, m)``:
        ``Moments.post``; ``quiet(uid)``: the recipient's quiet hours."""
        self._s = store
        self.social = social
        self.clubs = clubs
        self._now = now
        self._clock = clock
        self.moment = moment
        self.push = push
        self._quiet = quiet
        self._name = name
        self._g = store.global_doc("community")
        self._lock = threading.Lock()
        # Set by webapp: feed groups (feedgroups.FeedGroups), the lap shape of a workout
        # (``splits(uid, aid) -> [{km, s}]``) and its reward headline (``headline(uid, aid)``).
        self.groups: Any = None
        self.splits: Callable[[str, int], list[dict[str, Any]]] | None = None
        self.headline: Callable[[str, int], str | None] | None = None
        # Set by webapp: ``workouts_of(uid) -> (garmin_acts, external_workouts)`` for the
        # one-time backfill when "Share my workouts with friends" turns on.
        self.workouts_of: Callable[[str], tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None
        # Set by webapp: ``route_of(uid, aid, trim_m) -> routes.from_details(...)`` (a Garmin
        # GPS line, trimmed and simplified), fetched once when a workout post is made.
        self.route_of: Callable[[str, int, int], dict[str, Any] | None] | None = None
        # Set by webapp: a push that opens a given app link (``(to, title, body, url)``), for
        # @mentions that open the exact post. Falls back to ``push``.
        self.push_link: Callable[[str, str, str, str], None] | None = None
        self._pushed: dict[tuple[str, str], float] = {}
        self._reminded: dict[str, float] = {}
        # catch_up(): when each person was last checked (in memory; a restart re-checks once).
        self._caught: dict[str, float] = {}
        self._caught_lock = threading.Lock()
        # Runs a background job (a thread by default; tests make it run inline).
        self.spawn: Callable[[Callable[[], Any]], Any] = lambda fn: threading.Thread(target=fn, daemon=True).start()

    # ------------------------------------------------------------ docs --
    def _posts(self, uid: str):
        return self._s.user_doc(uid, "posts")

    def _mine(self, uid: str):
        return self._s.user_doc(uid, "community")

    def require(self, uid: str) -> None:
        if uid.startswith("coach_") or not self.social.is_athlete(uid):
            raise CommunityError("Community is for athletes on rabbt.", 403)

    # -------------------------------------------------------- settings --
    @staticmethod
    def _settings_of(d: dict[str, Any]) -> dict[str, Any]:
        s = d.get("settings") or {}
        aud = norm_audience(s.get("audience") or s.get("visibility"))
        sw = s.get("share_workouts")
        sa = s.get("share_audience")
        view = s.get("default_view")
        return {"milestones": {t: bool((s.get("milestones") or {}).get(t, True)) for t in MILESTONES},
                "share_audience": sa if isinstance(sa, str) and (sa == "friends" or sa.startswith("grp:")) else "friends",
                "default_view": view if view in VIEWS else "feed",
                "auto_share": {t: bool((s.get("auto_share") or {}).get(t, False)) for t in MILESTONES},
                "audience": aud if aud in AUDIENCES else "friends",
                # None = never answered (off: sharing needs a yes).
                "share_workouts": sw if isinstance(sw, bool) else None,
                "share_prompted": bool(s.get("share_prompted")),
                "share_since": s.get("share_since") if isinstance(s.get("share_since"), str) else None,
                # Route maps: shown to me unless I turn them off; shared with friends only after I
                # say yes (None = not asked yet = off); start and finish trimmed; an optional
                # area where routes that start there are never shown to anyone else.
                "routes_own": s.get("routes_own") is not False,
                "routes_share": s.get("routes_share") if isinstance(s.get("routes_share"), bool) else None,
                "routes_trim_m": s.get("routes_trim_m") if s.get("routes_trim_m") in _rt.TRIM_CHOICES else _rt.DEFAULT_TRIM_M,
                "routes_home": s.get("routes_home") if isinstance(s.get("routes_home"), dict) else None}

    @staticmethod
    def sharing_workouts(s: dict[str, Any]) -> bool:
        """Effective "Share my workouts with friends": only when the person said yes (an opt-in
        consent to share health data, as Washington's My Health My Data Act asks: the prompt,
        the connect sheet, the consent screen or the setting). Unanswered means off."""
        return s["share_workouts"] is True

    def sharing_consent(self, uid: str, s: dict[str, Any] | None = None) -> bool:
        """Has ``uid`` agreed to share workouts with friends? A yes here (prompt, connect sheet,
        consent screen, setting) or, if never answered here, a "workouts" share they saved
        themselves in the older friends settings (that was their earlier consent). A no here
        always wins. Drives both the Feed's auto-shared posts and friends' workout lists."""
        s = s if s is not None else self._settings_of(self._mine(uid).load())
        if s["share_workouts"] is not None:
            return s["share_workouts"] is True
        try:
            return self.social.explicit_workouts(uid) is True
        except Exception:
            return False

    def sharing_source(self, uid: str, s: dict[str, Any]) -> str:
        """``yes`` | ``earlier`` (saved in friends settings) | ``off`` (said no) | ``unanswered``."""
        if s["share_workouts"] is True:
            return "yes"
        if s["share_workouts"] is False:
            return "off"
        return "earlier" if self.sharing_consent(uid, s) else "unanswered"

    def settings(self, uid: str) -> dict[str, Any]:
        self.require(uid)
        s = self._settings_of(self._mine(uid).load())
        return {**s, "routes_home": _home_public(s["routes_home"]), "last_shared_at": self.last_shared_at(uid),
                "sharing_effective": self.sharing_consent(uid, s), "sharing_source": self.sharing_source(uid, s),
                "followers": self._follower_names(uid)}

    def _follower_names(self, uid: str) -> dict[str, Any]:
        """Who'd see my shared workouts: a count and up to 2 first names, for the share ask."""
        try:
            ids = [f for f in self.social.follower_ids(uid) if f != uid and not self.social.blocked_between(uid, f)]
        except Exception:
            return {"count": 0, "names": []}
        names: list[str] = []
        for f in ids[:2]:
            try:
                names.append(str(self._name(f)).split(" ")[0])
            except Exception:
                pass
        return {"count": len(ids), "names": names}

    def ask_status(self, viewer: str, friend: str) -> dict[str, Any]:
        """Can ``viewer`` ask ``friend`` to share workouts? ``reason`` when not: not_following,
        shares (already), said_no, self. ``next_at``: when a recent ask allows another."""
        if viewer == friend:
            return {"can_ask": False, "reason": "self"}
        if (not self.social.is_athlete(friend) or self.social.blocked_between(viewer, friend)
                or not self.social.follows(viewer, friend)):
            return {"can_ask": False, "reason": "not_following"}
        s = self._settings_of(self._mine(friend).load())
        if s["share_workouts"] is False:
            return {"can_ask": False, "reason": "said_no"}
        if self.sharing_consent(friend, s):
            return {"can_ask": False, "reason": "shares"}
        last = ((self._mine(friend).load().get("asked_by") or {}).get(viewer))
        if isinstance(last, int | float) and self._clock() - last < ASK_EVERY_S:
            return {"can_ask": False, "reason": "asked_recently", "asked_recently": True,
                    "next_at": int(last + ASK_EVERY_S)}
        return {"can_ask": True}

    def ask_friend(self, viewer: str, friend: str) -> dict[str, Any]:
        """``viewer`` asks ``friend`` (someone they follow who never answered) to share their
        workouts: one push from them by name, at most once a week per pair. Asking shares
        nothing; the friend still decides on the Share card."""
        self.require(viewer)
        st = self.ask_status(viewer, friend)
        if not st["can_ask"]:
            if st.get("reason") in ("not_following", "self"):
                raise CommunityError("person not found", 404)
            return {"asked": False, **{k: v for k, v in st.items() if k != "can_ask"}}
        now = self._clock()

        def claim(d: dict[str, Any]) -> bool:
            by = d.setdefault("asked_by", {})
            last = by.get(viewer)
            if isinstance(last, int | float) and now - last < ASK_EVERY_S:
                return False
            by[viewer] = now
            if len(by) > 200:
                for k in sorted(by, key=lambda k: by[k])[: len(by) - 200]:
                    del by[k]
            return True
        if not self._mine(friend).update(claim):
            return {"asked": False, "reason": "asked_recently", "asked_recently": True}
        first = str(self._name(viewer)).split(" ")[0] or "A friend"
        self._notify(friend, f"ask-share:{viewer}", f"{first} wants to see your workouts",
                     "Share them on the rabbt Feed? Sport, time and distance only. Tap to choose.")
        log_event(logger, logging.INFO, "share_asked_by_friend", user_id=friend)
        return {"asked": True, "next_at": int(now + ASK_EVERY_S)}

    def waiting(self, viewer: str) -> list[dict[str, Any]]:
        """People I follow who never answered "share my workouts" (the Feed's waiting row)."""
        out: list[dict[str, Any]] = []
        for f in self.social.following_ids(viewer, limit=FEED_FOLLOWEES):
            if f == viewer or not self.social.is_athlete(f) or self.social.blocked_between(viewer, f):
                continue
            try:
                d = self._mine(f).load()
                s = self._settings_of(d)
                if s["share_workouts"] is not None or self.sharing_consent(f, s):
                    continue
                last = (d.get("asked_by") or {}).get(viewer)
                recent = isinstance(last, int | float) and self._clock() - last < ASK_EVERY_S
                out.append({"id": f, "name": str(self._name(f)), "asked_recently": bool(recent)})
            except Exception:
                continue
            if len(out) >= WAITING_MAX:
                break
        return out

    def ask_to_share(self, uid: str) -> bool:
        """Once per person: if they never answered "share my workouts" and friends follow
        them, one push asking (it opens the Feed's Share card). Asking isn't sharing: nothing
        leaves until they tap Share. Returns True when the push went out."""
        if self.push is None or uid.startswith("coach_") or not self.social.is_athlete(uid):
            return False
        s = self._settings_of(self._mine(uid).load())
        if s["share_workouts"] is not None or self.sharing_consent(uid, s):
            return False
        fol = self._follower_names(uid)
        if not fol["count"]:
            return False

        def claim(d: dict[str, Any]) -> bool:
            if d.get("share_asked"):
                return False
            d["share_asked"] = self._now(uid).date().isoformat()
            return True
        if not self._mine(uid).update(claim):
            return False
        who = (fol["names"][0] if fol["count"] == 1 and fol["names"]
               else f"{fol['names'][0]} and {fol['count'] - 1} other{'s' if fol['count'] > 2 else ''}"
               if fol["names"] else f"{fol['count']} friends")
        self._notify(uid, "share-ask", f"{who} want{'s' if fol['count'] == 1 else ''} to see your workouts",
                     "Share them on the rabbt Feed? Sport, time and distance only. Tap to choose.")
        log_event(logger, logging.INFO, "share_asked", user_id=uid, followers=fol["count"])
        return True

    def last_shared_at(self, uid: str) -> int | None:
        """When my newest workout post went out (auto or by hand), for "Sharing: On · last shared"."""
        ts = [int(p["created"]) for p in (self._posts(uid).load().get("posts") or {}).values()
              if p.get("author") == uid and p.get("workout")]
        return max(ts) if ts else None

    def workout_post(self, uid: str, aid: Any) -> str | None:
        """My post for this workout (auto-shared or shared by hand), if any."""
        key = activity_key(aid)
        if key is None:
            return None
        for p in (self._posts(uid).load().get("posts") or {}).values():
            w = p.get("workout") or {}
            if p.get("author") == uid and activity_key(w.get("activity_id")) == key:
                return str(p["id"])
        return None

    def claim_workout(self, uid: str, aid: Any) -> None:
        """Shared by hand: auto-share must not post it again."""
        key = activity_key(aid)
        if key is None:
            return
        today = self._now(uid).date().isoformat()

        def apply(d: dict[str, Any]) -> None:
            d.setdefault("keys", {})[f"auto:{key}"] = today
        self._mine(uid).update(apply)

    def put_settings(self, uid: str, patch: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(patch, dict):
            raise CommunityError("settings must be an object")
        clean: dict[str, Any] = {}
        for k in ("milestones", "auto_share"):
            if k in patch:
                v = patch[k]
                if not isinstance(v, dict) or any(t not in MILESTONES or not isinstance(b, bool) for t, b in v.items()):
                    raise CommunityError(f"{k} must map milestone types to true/false")
                clean[k] = v
        if "audience" in patch:
            a = norm_audience(patch["audience"])
            if a not in AUDIENCES:
                raise CommunityError("audience must be friends, public or private")
            clean["audience"] = a
        if "share_workouts" in patch:
            if not isinstance(patch["share_workouts"], bool):
                raise CommunityError("share_workouts must be true or false")
            clean["share_workouts"] = patch["share_workouts"]
        if patch.get("share_prompted") is True:
            clean["share_prompted"] = True
        if "share_audience" in patch:
            a = patch["share_audience"]
            if a != "friends":
                a = self._group_audience(uid, a)
            clean["share_audience"] = a
        for k in ("routes_own", "routes_share"):
            if k in patch:
                if not isinstance(patch[k], bool):
                    raise CommunityError(f"{k} must be true or false")
                clean[k] = patch[k]
        if "routes_trim_m" in patch:
            if patch["routes_trim_m"] not in _rt.TRIM_CHOICES:
                raise CommunityError("routes_trim_m must be 200, 400 or 800")
            clean["routes_trim_m"] = patch["routes_trim_m"]
        if "routes_home" in patch:
            clean["routes_home"] = self._home_from(uid, patch["routes_home"])
        if "default_view" in patch:
            if patch["default_view"] not in VIEWS:
                raise CommunityError("default_view must be feed or clubs")
            clean["default_view"] = patch["default_view"]
        today = self._now(uid).date().isoformat()

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            cur = self._settings_of(d)
            was = self.sharing_workouts(cur)
            for k in ("milestones", "auto_share"):
                cur[k] = {**cur[k], **clean.get(k, {})}
            for k in ("audience", "share_workouts", "share_prompted", "share_audience", "default_view",
                      "routes_own", "routes_share", "routes_trim_m", "routes_home"):
                if k in clean:
                    cur[k] = clean[k]
            if self.sharing_workouts(cur) and not was:
                # Sharing starts with the last few days (posted once, below), never older.
                cur["share_since"] = (self._now(uid).date() - timedelta(days=BACKFILL_DAYS)).isoformat()
                d["backfill_due"] = True
            d["settings"] = cur
            return cur
        out = self._mine(uid).update(apply)
        self.backfill(uid)
        o = self._settings_of({"settings": out})
        return {**out, "routes_home": _home_public(o["routes_home"]), "last_shared_at": self.last_shared_at(uid),
                "sharing_effective": self.sharing_consent(uid, o), "sharing_source": self.sharing_source(uid, o)}

    def _home_from(self, uid: str, v: Any) -> dict[str, Any] | None:
        """``null`` clears the hidden area; ``{"post_id", "radius_m"}`` sets it around where one of
        my own route posts starts (the server's rounded start, never sent to the app)."""
        if v is None:
            return None
        if not isinstance(v, dict) or v.get("radius_m") not in _rt.HOME_RADIUS_CHOICES:
            raise CommunityError("Pick 200, 400, 800 or 1,600 m.")
        try:
            _, post = self._load(uid, v.get("post_id"))
        except CommunityError:
            raise CommunityError("That workout isn't yours.", 404) from None
        cell = ((post.get("workout") or {}).get("route") or {}).get("start_cell")
        if post.get("author") != uid or not (isinstance(cell, list) and len(cell) == 2):
            raise CommunityError("That workout has no map to set this from.", 400)
        return {"lat": float(cell[0]), "lon": float(cell[1]), "radius_m": int(v["radius_m"])}

    def route_card(self, uid: str, aid: Any, card: dict[str, Any]) -> None:
        """Add the GPS line to a workout card I'm about to post (outdoor Garmin workouts only;
        best effort: no route is fine)."""
        if self.route_of is None or not isinstance(aid, int) or not _rt.has_route(card.get("family"), card.get("kind")):
            return
        try:
            s = self._settings_of(self._mine(uid).load())
            r = self.route_of(uid, aid, s["routes_trim_m"])
            if r:
                card["route"] = r
        except Exception as e:
            log_event(logger, logging.INFO, "community_route_failed", user_id=uid, error=type(e).__name__)

    def route_shown(self, viewer: str, author: str, route: Any) -> list[list[float]] | None:
        """The line ``viewer`` may see on ``author``'s workout: the owner if their own maps are
        on; anyone else unless the owner turned map sharing off ("Keep maps private"), and never
        when it starts in their hidden area. Only workouts they chose to share are posts at all,
        and every line has its start and finish trimmed (``routes_trim_m``, 400 m by default)."""
        if not isinstance(route, dict):
            return None
        s = self._settings_of(self._mine(author).load())
        if viewer == author:
            return _rt.public(route) if s["routes_own"] else None
        if s["routes_share"] is False or _rt.near_home(route, s["routes_home"]):
            return None
        return _rt.public(route)

    def backfill(self, uid: str) -> list[str]:
        """Once, right after sharing turns on: post the last ``BACKFILL_DAYS`` days of workouts
        (Garmin and other sources, oldest first, at most ``BACKFILL_MAX``) so friends see
        something straight away. Same cards and once-per-workout keys as auto-sharing, so the
        regular sync never posts them again. Best effort: a failure leaves it due for the next try."""
        if self.workouts_of is None or not self._mine(uid).load().get("backfill_due"):
            return []
        try:
            acts, ext = self.workouts_of(uid)
        except Exception:
            return []
        today = self._now(uid).date()
        out = self.auto_share_workouts(uid, acts, today, days=BACKFILL_DAYS, cap=BACKFILL_MAX)
        out += self.auto_share_external(uid, ext, today, days=BACKFILL_DAYS, cap=max(0, BACKFILL_MAX - len(out)))

        def done(d: dict[str, Any]) -> None:
            d.pop("backfill_due", None)
        self._mine(uid).update(done)
        return out

    def _catch_due(self, uid: str, force: bool) -> bool:
        now = time.monotonic()
        with self._caught_lock:
            last = self._caught.get(uid)
            if not force and last is not None and now - last < CATCHUP_S:
                return False
            self._caught[uid] = now
            if len(self._caught) > 5000:
                for k in sorted(self._caught, key=self._caught.__getitem__)[:1000]:
                    self._caught.pop(k, None)
            return True

    @staticmethod
    def _post_share_key(post: dict[str, Any]) -> str | None:
        """The ``auto:<key>`` a workout post was shared under (Garmin id, ``share_key`` for
        other sources), or None."""
        w = post.get("workout") or {}
        if isinstance(w.get("share_key"), str):
            return f"auto:{w['share_key']}"
        k = activity_key(w.get("activity_id"))
        return f"auto:{k}" if k is not None else None

    def _share_keys(self, uid: str) -> tuple[set[str], set[str]]:
        """(keys that have a post now, keys of other-source posts as ``source|day|minutes``)."""
        have: set[str] = set()
        loose: set[str] = set()
        for p in (self._posts(uid).load().get("posts") or {}).values():
            if p.get("author") != uid or not p.get("workout"):
                continue
            if (k := self._post_share_key(p)) is not None:
                have.add(k)
            w = p["workout"]
            loose.add(f"{w.get('source') or ''}|{w.get('date') or ''}|{w.get('minutes')}")
        return have, loose

    def _candidates(self, uid: str, acts: list[dict[str, Any]], ext: list[dict[str, Any]],
                    today: date) -> list[dict[str, Any]]:
        """Workouts from the last ``BACKFILL_DAYS`` days, each with its share key."""
        out: list[dict[str, Any]] = []
        for r in _rows(acts):
            if (k := activity_key(r["id"])) is not None and 0 <= (today - r["date"]).days <= BACKFILL_DAYS:
                out.append({"key": f"auto:{k}", "id": r["id"], "date": r["date"].isoformat(), "source": "garmin",
                            "loose": None})
        for w in ext:
            day = str(w.get("start") or "")[:10]
            try:
                d0 = date.fromisoformat(day)
            except ValueError:
                continue
            if isinstance(w.get("key"), str) and 0 <= (today - d0).days <= BACKFILL_DAYS:
                mins = w.get("minutes") if isinstance(w.get("minutes"), int | float) else None
                out.append({"key": f"auto:{w['key']}", "id": w["key"], "date": day,
                            "source": str(w.get("source") or ""),
                            "loose": f"{w.get('source') or ''}|{day}|{round(mins) if mins else None}"})
        return out

    def _release_orphans(self, uid: str, cands: list[dict[str, Any]]) -> int:
        """A workout whose share was claimed but whose post never got made (an error between
        the two, or an older bug) would otherwise be stuck off the Feed forever. Drop those
        claims so the normal share runs again. Never for a post the person deleted."""
        have, loose = self._share_keys(uid)
        stuck = [c["key"] for c in cands if c["key"] not in have and (c["loose"] is None or c["loose"] not in loose)]
        if not stuck:
            return 0

        def apply(d: dict[str, Any]) -> int:
            keys, gone = d.get("keys") or {}, d.get("removed") or {}
            n = 0
            for k in stuck:
                if k in keys and k not in gone:
                    del keys[k]
                    n += 1
            return n
        return int(self._mine(uid).update(apply) or 0)

    def diagnose(self, uid: str) -> dict[str, Any]:
        """Why each of ``uid``'s recent workouts is or isn't on the Feed (owner tool)."""
        s = self._settings_of(self._mine(uid).load())
        info: dict[str, Any] = {"athlete": self.social.is_athlete(uid), "sharing": self.sharing_source(uid, s),
                                "share_since": s.get("share_since"), "audience": s.get("share_audience") or "friends",
                                "workouts": []}
        if self.workouts_of is None:
            info["error"] = "workouts_of not wired"
            return info
        try:
            acts, ext = self.workouts_of(uid)
        except Exception as e:
            info["error"] = f"reading workouts failed: {type(e).__name__}"
            return info
        today = self._now(uid).date()
        d = self._mine(uid).load()
        keys, gone = d.get("keys") or {}, d.get("removed") or {}
        have, loose = self._share_keys(uid)
        since = s["share_since"] or (today.isoformat() if s["share_workouts"] is True
                                     else (today - timedelta(days=BACKFILL_DAYS)).isoformat())
        for c in self._candidates(uid, acts, ext, today):
            if c["key"] in have or (c["loose"] is not None and c["loose"] in loose):
                why = "on the Feed"
            elif c["key"] in gone:
                why = "they deleted the post"
            elif not info["sharing"] in ("yes", "earlier"):
                why = "sharing is off or unanswered"
            elif c["date"] < since:
                why = f"before sharing started ({since})"
            elif c["key"] in keys:
                why = "claimed but never posted (catch-up will retry)"
            else:
                why = "waiting for the next catch-up"
            info["workouts"].append({"date": c["date"], "source": c["source"], "id": str(c["id"]), "status": why})
        info["today"] = today.isoformat()
        info["garmin_count"] = len(acts)
        info["other_count"] = len(ext)
        return info

    def catch_up(self, uid: str, *, force: bool = False) -> list[str]:
        """Post any workout from the last ``BACKFILL_DAYS`` days that should be on the Feed and
        isn't: the regular auto-share only runs when a sync finds something *new*, so a workout
        synced before sharing took effect (a yes given later, or the earlier friends-settings
        consent) would otherwise never post. Same rules, cards and once-per-workout keys as
        auto-sharing, so it is safe to call often; checked at most every ``CATCHUP_S`` per person."""
        if (self.workouts_of is None or uid.startswith("coach_") or not self.social.is_athlete(uid)
                or not self._catch_due(uid, force)):
            return []
        try:
            if not self.sharing_consent(uid):
                log_event(logger, logging.INFO, "feed_catch_up", user_id=uid, posted=0, sharing=False)
                return []
            acts, ext = self.workouts_of(uid)
            today = self._now(uid).date()
            freed = self._release_orphans(uid, self._candidates(uid, acts, ext, today))
            if freed:
                log_event(logger, logging.INFO, "feed_catch_up_released", user_id=uid, released=freed)
            out = self.auto_share_workouts(uid, acts, today, days=BACKFILL_DAYS, cap=BACKFILL_MAX)
            out += self.auto_share_external(uid, ext, today, days=BACKFILL_DAYS,
                                            cap=max(0, BACKFILL_MAX - len(out)))
        except Exception as e:  # best effort: the next tick tries again
            log_event(logger, logging.INFO, "feed_catch_up_failed", user_id=uid, error=type(e).__name__)
            with self._caught_lock:
                self._caught.pop(uid, None)
            return []
        log_event(logger, logging.INFO, "feed_catch_up", user_id=uid, posted=len(out),
                  workouts=len(acts) + len(ext))
        return out

    def catch_up_soon(self, uids: list[str]) -> None:
        """In the background, ``catch_up`` the people whose check is due (a Feed load asks this
        for the people in it, so a friend's missed workout shows on the next refresh)."""
        with self._caught_lock:
            now = time.monotonic()
            due = [u for u in dict.fromkeys(uids)
                   if not (self._caught.get(u) is not None and now - self._caught[u] < CATCHUP_S)]
        if not due or self.workouts_of is None:
            return

        def run() -> None:
            for u in due:
                self.catch_up(u)
        try:
            self.spawn(run)
        except Exception:
            pass

    # ----------------------------------------------------------- access --
    @staticmethod
    def group_ids(audience: Any) -> list[str]:
        """``grp:a,b`` -> ``[a, b]``; anything else -> []."""
        if not isinstance(audience, str) or not audience.startswith("grp:"):
            return []
        return [g for g in audience[4:].split(",") if g]

    def _group_audience(self, uid: str, v: Any) -> str:
        """``grp:<gid>[,...]`` or a list of group ids, each a group ``uid`` is in."""
        ids = v if isinstance(v, list) else self.group_ids(v)
        ids = [g for g in dict.fromkeys(ids) if isinstance(g, str)]
        if (not ids or len(ids) > MAX_GROUP_AUDIENCE or self.groups is None
                or not all(self.groups.is_member(g, uid) for g in ids)):
            raise CommunityError("Pick groups you're in.", 400)
        return "grp:" + ",".join(sorted(ids))

    def _audience(self, uid: str, v: Any, groups: Any = None) -> str:
        if v == "groups" or isinstance(v, list) or (isinstance(v, str) and v.startswith("grp:")):
            return self._group_audience(uid, groups if v == "groups" else v)
        v = norm_audience(v)
        if v is None:
            return self._settings_of(self._mine(uid).load())["audience"]
        if v in AUDIENCES:
            return str(v)
        if isinstance(v, str) and v.startswith("club:") and self.clubs.is_member(v[5:], uid):
            return v
        raise CommunityError("Pick who can see this: friends, a club you're in, everyone on rabbt, or only you.")

    def can_see(self, viewer: str, post: dict[str, Any]) -> bool:
        author = post["author"]
        if viewer == author:
            return True
        if not (self.social.is_athlete(viewer) and self.social.is_athlete(author)):
            return False
        if self.social.blocked_between(viewer, author):
            return False
        v = norm_audience(post.get("audience") or post.get("visibility") or "friends")
        if v == "public":
            return True
        if v == "friends":
            return bool(self.social.follows(viewer, author))
        if v.startswith("club:"):
            cid = v[5:]
            return self.clubs.is_member(cid, viewer) and self.clubs.is_member(cid, author)
        if v.startswith("grp:") and self.groups is not None:
            return any(self.groups.is_member(g, viewer) and self.groups.is_member(g, author)
                       for g in self.group_ids(v))
        return False

    def _owner(self, pid: Any) -> str:
        pid = valid_pid(pid)
        owner = (self._g.load().get("index") or {}).get(pid)
        if not owner:
            raise CommunityError("post not found", 404)
        return str(owner)

    def _load(self, viewer: str, pid: Any) -> tuple[str, dict[str, Any]]:
        owner = self._owner(pid)
        post = (self._posts(owner).load().get("posts") or {}).get(pid)
        if post is None or not self.can_see(viewer, post):
            raise CommunityError("post not found", 404)
        return owner, post

    # ------------------------------------------------------- rate limits --
    def _take(self, uid: str, what: str, limit: int) -> None:
        today = self._now(uid).date().isoformat()

        def apply(d: dict[str, Any]) -> None:
            r = d.get("rate") or {}
            if r.get("day") != today:
                r = {"day": today}
            if int(r.get(what) or 0) >= limit:
                noun = {"posts": "posts", "likes": "likes"}.get(what, "comments")
                raise CommunityError(f"That's {limit} {noun} today, the daily limit. Try again tomorrow.", 429)
            r[what] = int(r.get(what) or 0) + 1
            d["rate"] = r
        self._mine(uid).update(apply)

    # ------------------------------------------------------------ views --
    def view(self, viewer: str, post: dict[str, Any], *, all_comments: bool = False) -> dict[str, Any]:
        reactions = {u: r for u, r in (post.get("reactions") or {}).items()
                     if u == viewer or not self.social.blocked_between(viewer, u)}
        counts = {k: 0 for k in REACTIONS}
        for r in reactions.values():
            if r in counts:
                counts[r] += 1
        mine = post["author"] == viewer
        comments = [c for c in post.get("comments") or [] if c["by"] == viewer or not self.social.blocked_between(viewer, c["by"])]
        top = {c["id"] for c in comments if not c.get("parent")}
        comments = [c for c in comments if not c.get("parent") or c["parent"] in top]
        # The feed shows the newest conversations (top-level comments, each with how many replies
        # it has); the post's own page shows everything.
        shown = comments if all_comments else [c for c in comments if not c.get("parent")][-PREVIEW_COMMENTS:]
        replies: dict[str, int] = {}
        for c in comments:
            if c.get("parent"):
                replies[c["parent"]] = replies.get(c["parent"], 0) + 1
        v = norm_audience(post.get("audience") or post.get("visibility") or "friends")
        out = {k: post.get(k) for k in ("id", "author", "kind", "category", "text", "feeling", "event", "workout",
                                         "milestone", "created", "edited")}
        if isinstance(out.get("workout"), dict):  # the stored route never leaves as is (start cell)
            w = {k: v for k, v in out["workout"].items() if k != "route"}
            line = self.route_shown(viewer, post["author"], out["workout"].get("route"))
            if line:
                w["route"] = line
            elif mine and isinstance(out["workout"].get("route"), dict):
                w["route_hidden"] = True  # mine, maps off: the card can say so
            elif isinstance(out["workout"].get("route"), dict):
                w["map_private"] = True  # a friend's map they keep to themselves: the Feed map says so
            out["workout"] = w
        out["text"], out["mentions"] = self._shown_mentions(viewer, post)
        photos = post.get("photos") or ([post["photo"]] if post.get("photo") else [])
        out.update({
            "audience": v, "club": None, "mine": mine,
            "photos": [p["v"] for p in photos],
            # The author's own photo ids, so an edit can keep some and add more (only the
            # author can attach them; they mean nothing to anyone else).
            **({"photo_ids": [p["id"] for p in photos if p.get("id")]} if mine else {}),
            "reactions": counts, "reaction_total": sum(counts.values()), "my_reaction": reactions.get(viewer),
            "comment_count": len(comments),
            "comments": [{**self._comment_view(viewer, c, mine), "reply_count": replies.get(c["id"], 0)} for c in shown],
        })
        if v.startswith("club:"):
            out["club"] = {"id": v[5:], "name": self.clubs.name_of(v[5:], viewer) or "Club"}
        if v.startswith("grp:"):
            gs = [self.groups.brief(g, viewer) for g in self.group_ids(v)] if self.groups is not None else []
            out["groups"] = [g for g in gs if g]
        return out

    def _comment_view(self, viewer: str, c: dict[str, Any], post_mine: bool) -> dict[str, Any]:
        likes = [u for u in c.get("likes") or [] if u == viewer or not self.social.blocked_between(viewer, u)]
        text, shown = self._shown_mentions(viewer, c)
        return {"id": c["id"], "by": c["by"], "ts": c["ts"], "parent": c.get("parent"), "text": text,
                "mentions": shown, "mine": c["by"] == viewer, "can_delete": c["by"] == viewer or post_mine,
                "can_edit": c["by"] == viewer, "edited": c.get("edited"),
                "like_count": len(likes), "liked": viewer in likes}

    # ------------------------------------------------------------ posts --
    def _event_link(self, uid: str, eid: Any) -> dict[str, Any] | None:
        if eid in (None, ""):
            return None
        ev = (self._s.user_doc(uid, "events").load().get("events") or {}).get(eid) if isinstance(eid, str) else None
        if ev is None:
            raise CommunityError("event not found", 404)
        return event_snapshot(ev)

    def _fields(self, uid: str, body: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not partial or "text" in body:
            out["text"] = _mtext(body.get("text"), TEXT_LEN)
        if not partial or "category" in body:
            c = body.get("category") or "other"
            if c not in CATEGORIES:
                raise CommunityError("Pick a category.")
            out["category"] = c
        if not partial or "feeling" in body:
            f = body.get("feeling")
            if f not in (None, "") and f not in FEELINGS:
                raise CommunityError("Pick a feeling from the list.")
            out["feeling"] = f or None
        if not partial or "event_id" in body:
            out["event"] = self._event_link(uid, body.get("event_id"))
        if not partial or "audience" in body or "visibility" in body:
            out["audience"] = self._audience(uid, body.get("audience", body.get("visibility")), body.get("groups"))
        return out

    @staticmethod
    def _photo_ids(body: dict[str, Any]) -> list[str] | None:
        """``photo_ids`` (or a single ``photo_id``); None when not given."""
        if "photo_ids" in body:
            ids = body["photo_ids"]
        elif "photo_id" in body:
            ids = [body["photo_id"]] if body["photo_id"] else []
        else:
            return None
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise CommunityError("photo not found", 404)
        ids = list(dict.fromkeys(ids))
        if len(ids) > MAX_PHOTOS:
            raise CommunityError(f"Up to {MAX_PHOTOS} photos per post.")
        return ids

    def _store_post(self, uid: str, post: dict[str, Any]) -> None:
        def apply(d: dict[str, Any]) -> list[dict[str, Any]]:
            posts = d.setdefault("posts", {})
            posts[post["id"]] = post
            old = sorted(posts, key=lambda k: posts[k]["created"])[: max(0, len(posts) - MAX_POSTS)]
            return [posts.pop(k) for k in old]
        dropped = self._posts(uid).update(apply)
        for x in dropped:
            self._drop_photos(uid, x)

        def index(g: dict[str, Any]) -> None:
            ix = g.setdefault("index", {})
            ix[post["id"]] = uid
            for x in dropped:
                ix.pop(x["id"], None)
                (g.get("public") or {}).pop(x["id"], None)
            self._index_public(g, post)
        self._g.update(index)

    @staticmethod
    def _index_public(g: dict[str, Any], post: dict[str, Any]) -> None:
        pub = g.setdefault("public", {})
        if post.get("audience") == "public":
            pub[post["id"]] = [post["author"], post["created"]]
            if len(pub) > MAX_PUBLIC:
                for k in sorted(pub, key=lambda k: pub[k][1])[: len(pub) - MAX_PUBLIC]:
                    del pub[k]
        else:
            pub.pop(post["id"], None)

    def create(self, uid: str, body: Any, *, workout: dict[str, Any] | None = None,
               milestone: dict[str, Any] | None = None, limited: bool = True) -> dict[str, Any]:
        """A new post. ``workout``: a ``workout_card`` (server-built); ``milestone``:
        ``{type, key}`` from a draft. ``limited``: counts toward the daily post limit."""
        self.require(uid)
        if not isinstance(body, dict):
            raise CommunityError("bad request")
        f = self._fields(uid, body, partial=False)
        f["text"], mids = self._mentions(uid, f["text"], {"author": uid, "audience": f["audience"], "comments": []})
        photo_ids = self._photo_ids(body) or []
        if not f["text"] and not photo_ids and workout is None and milestone is None:
            raise CommunityError("Write something or add a photo.")
        if limited:
            self._take(uid, "posts", POSTS_PER_DAY)
        pid = "p" + secrets.token_hex(8)
        post: dict[str, Any] = {"id": pid, "author": uid, "kind": "workout" if workout else "milestone" if milestone else "moment",
                                **f, "photos": [], "created": int(self._clock()), "edited": None,
                                "reactions": {}, "comments": [], "mentions": mids}
        if workout is not None:
            post["workout"] = {k: workout.get(k) for k in WORKOUT_FIELDS
                               if k in WORKOUT_FIELDS[:8] or workout.get(k) not in (None, "", [], False)}
            if isinstance(post["workout"].get("legs"), list):
                post["workout"]["legs"] = [{k: lg.get(k) for k in LEG_FIELDS if lg.get(k) is not None}
                                           for lg in post["workout"]["legs"][:5] if isinstance(lg, dict)]
        if milestone is not None:
            post["milestone"] = {"type": milestone.get("type"), "key": milestone.get("key")}
        post["photos"] = self._attach_photos(uid, photo_ids, pid)
        self._store_post(uid, post)
        log_event(logger, logging.INFO, "community_post", user_id=uid, kind=post["kind"], audience=post["audience"].split(":")[0])
        self._tell_mentioned(uid, post, None, mids, skip=set())
        return self.view(uid, post)

    def update(self, uid: str, pid: Any, body: Any) -> dict[str, Any]:
        self.require(uid)
        if not isinstance(body, dict):
            raise CommunityError("bad request")
        pid = valid_pid(pid)
        if self._owner(pid) != uid:
            raise CommunityError("post not found", 404)
        f = self._fields(uid, body, partial=True)
        ids = self._photo_ids(body)
        cur = (self._posts(uid).load().get("posts") or {}).get(pid)
        if cur is None:
            raise CommunityError("post not found", 404)
        before = set(cur.get("mentions") or [])
        if "text" in f:
            f["text"], f["mentions"] = self._mentions(uid, f["text"], {**cur, **f})
        old = {p["id"]: p for p in cur.get("photos") or []}
        new_photos: list[dict[str, Any]] | None = None
        if ids is not None:
            fresh = {p["id"]: p for p in self._attach_photos(uid, [i for i in ids if i not in old], pid)}
            new_photos = [old.get(i) or fresh[i] for i in ids]

        def apply(d: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            p = (d.get("posts") or {}).get(pid)
            if p is None:
                raise CommunityError("post not found", 404)
            p.update(f)
            gone: list[dict[str, Any]] = []
            if new_photos is not None:
                keep = {x["id"] for x in new_photos}
                gone = [x for x in p.get("photos") or [] if x["id"] not in keep]
                p["photos"] = new_photos
            if not p.get("text") and not p.get("photos") and not p.get("workout") and not p.get("milestone"):
                raise CommunityError("Write something or add a photo.")
            p["edited"] = int(self._clock())
            return p, gone
        post, gone = self._posts(uid).update(apply)
        self._drop_photos(uid, {"photos": gone})
        self._g.update(lambda g: self._index_public(g, post))
        if "mentions" in f:  # only people newly mentioned by this edit hear about it
            self._tell_mentioned(uid, post, None, [m for m in f["mentions"] if m not in before], skip=set())
        return self.view(uid, post)

    def delete(self, uid: str, pid: Any) -> None:
        self.require(uid)
        pid = valid_pid(pid)
        if self._owner(pid) != uid:
            raise CommunityError("post not found", 404)

        def apply(d: dict[str, Any]) -> dict[str, Any] | None:
            return (d.get("posts") or {}).pop(pid, None)
        gone = self._posts(uid).update(apply)
        if gone:
            self._drop_photos(uid, gone)
            if (wk := self._post_share_key(gone)) is not None:  # deleted on purpose: never re-post it
                day = self._now(uid).date().isoformat()

                def removed(d: dict[str, Any]) -> None:
                    r = d.setdefault("removed", {})
                    r[wk] = day
                    if len(r) > MAX_KEYS:
                        for k in sorted(r, key=lambda k: r[k])[: len(r) - MAX_KEYS]:
                            del r[k]
                self._mine(uid).update(removed)

        def unindex(g: dict[str, Any]) -> None:
            (g.get("index") or {}).pop(pid, None)
            (g.get("public") or {}).pop(pid, None)
        self._g.update(unindex)

    def get(self, viewer: str, pid: Any) -> dict[str, Any]:
        self.require(viewer)
        _, post = self._load(viewer, pid)
        if pid in self._hidden(viewer):
            raise CommunityError("post not found", 404)
        self.mark_seen(viewer, pid)
        return self.view(viewer, post, all_comments=True)

    # ------------------------------------------------------------- feed --
    def _hidden(self, uid: str) -> set[str]:
        return set(self._mine(uid).load().get("hidden") or [])

    def feed(self, viewer: str, cursor: Any = None, *, club: str | None = None, scope: str = "all",
             limit: int = PAGE, group: str | None = None) -> dict[str, Any]:
        """Newest first, ``limit`` per page. ``cursor``: the ``next`` of the previous page.
        ``scope``: ``all`` (friends, my clubs and groups, everyone's public posts), ``friends``
        (only people I follow, and me) or ``clubs`` (posts to my clubs). ``group``: one feed
        group's posts. On the first page of the main feed, my own auto-shared workout from the
        last ``PIN_S`` comes back separately as ``pinned`` (with a caption prompt)."""
        self.require(viewer)
        after: tuple[int, str] | None = None
        if cursor:
            try:
                ts, _, cid = str(cursor).partition(".")
                after = (int(ts), cid)
            except ValueError:
                raise CommunityError("bad cursor") from None
        if scope not in ("all", "friends", "clubs"):
            raise CommunityError("scope must be all, friends or clubs")
        if club is not None:
            if not self.clubs.is_member(club, viewer):
                raise CommunityError("club not found", 404)
            owners = self.clubs.member_ids(club, viewer)
        elif group is not None:
            if self.groups is None or not self.groups.is_member(group, viewer):
                raise CommunityError("group not found", 404)
            owners = self.groups.member_ids(group, viewer)
        elif scope == "clubs":
            owners = [viewer]
            for cid in self.clubs.ids_of(viewer):
                owners += self.clubs.member_ids(cid, viewer)
        else:
            owners = [viewer, *self.social.following_ids(viewer, limit=FEED_FOLLOWEES)]
            if scope == "all":
                for cid in self.clubs.ids_of(viewer):
                    owners += self.clubs.member_ids(cid, viewer)
                for gid in (self.groups.ids_of(viewer) if self.groups is not None else []):
                    owners += self.groups.member_ids(gid, viewer)
                owners += [a for a, _ in (self._g.load().get("public") or {}).values()]
        main = club is None and group is None and scope in ("all", "friends")
        if after is None:  # make sure friends' recent workouts have their posts (next refresh)
            self.catch_up_soon([viewer, *self.social.following_ids(viewer, limit=FEED_FOLLOWEES)])
        pinned: dict[str, Any] | None = None
        hidden = self._hidden(viewer)
        posts: list[dict[str, Any]] = []
        for owner in dict.fromkeys(owners):
            if owner != viewer and self.social.blocked_between(viewer, owner):
                continue
            for p in (self._posts(owner).load().get("posts") or {}).values():
                if p["id"] in hidden:
                    continue
                aud = norm_audience(p.get("audience") or p.get("visibility") or "friends")
                if club is not None and aud != f"club:{club}":
                    continue
                if group is not None and group not in self.group_ids(aud):
                    continue
                if scope == "clubs" and club is None and group is None and not aud.startswith("club:"):
                    continue
                if after is not None and (feed_ts(p), p["id"]) >= after:
                    continue
                if self.can_see(viewer, p):
                    posts.append(p)
        posts.sort(key=lambda p: (feed_ts(p), p["id"]), reverse=True)
        if main and after is None:
            now = self._clock()
            pin = next((p for p in posts if p["author"] == viewer and (p.get("workout") or {}).get("auto")
                        and not (p.get("workout") or {}).get("late")
                        and 0 <= now - p["created"] <= PIN_S), None)
            if pin is not None:
                posts = [p for p in posts if p["id"] != pin["id"]]
                pinned = {**self.view(viewer, pin), "pinned_until": int(pin["created"]) + PIN_S,
                          "prompt": "Add a photo or caption" if not pin.get("text") and not pin.get("photos") else None}
        page = posts[:limit]
        nxt = f"{feed_ts(page[-1])}.{page[-1]['id']}" if len(posts) > limit else None
        out: dict[str, Any] = {"items": [self.view(viewer, p) for p in page], "next": nxt, "pinned": pinned}
        if main and after is None:
            try:
                out["waiting"] = self.waiting(viewer)
            except Exception:
                out["waiting"] = []
        return out

    def latest(self, viewer: str, limit: int = LATEST_N) -> list[dict[str, Any]]:
        """Friends' latest: the newest posts (workouts first-class) from people I follow in the
        last ``LATEST_DAYS`` days that I can see, not mine, not hidden. For the Rabbit home."""
        self.require(viewer)
        hidden = self._hidden(viewer)
        since = self._clock() - LATEST_DAYS * 86400
        posts: list[dict[str, Any]] = []
        for owner in self.social.following_ids(viewer, limit=FEED_FOLLOWEES):
            if owner == viewer or self.social.blocked_between(viewer, owner):
                continue
            for p in (self._posts(owner).load().get("posts") or {}).values():
                if p["id"] in hidden or p["created"] < since:
                    continue
                if self.can_see(viewer, p):
                    posts.append(p)
        posts.sort(key=lambda p: (p["created"], p["id"]), reverse=True)
        return [self.view(viewer, p) for p in posts[:limit]]

    # -------------------------------------------------------- reactions --
    def _touch(self, owner: str, pid: str, fn: Callable[[dict[str, Any]], Any]) -> Any:
        def apply(d: dict[str, Any]) -> Any:
            p = (d.get("posts") or {}).get(pid)
            if p is None:
                raise CommunityError("post not found", 404)
            return fn(p)
        return self._posts(owner).update(apply)

    def react(self, viewer: str, pid: Any, kind: Any) -> dict[str, Any]:
        self.require(viewer)
        if kind not in REACTIONS:
            raise CommunityError("Pick a reaction.")
        owner, _ = self._load(viewer, pid)

        def fn(p: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            r = p.setdefault("reactions", {})
            new = viewer not in r
            r[viewer] = kind
            return p, new
        post, new = self._touch(owner, pid, fn)
        if new and owner != viewer:
            self._bump_unread(owner, pid)
            what = workout_label(post.get("workout")) if post.get("workout") else "post"
            self._notify(owner, pid, f"{self._name(viewer)} cheered your {what}",
                         _mn.display(post.get("text") or "") or ("Tap to see who's cheering." if post.get("workout") else "Your post"))
        return self.view(viewer, post)

    def unreact(self, viewer: str, pid: Any) -> dict[str, Any]:
        self.require(viewer)
        owner, _ = self._load(viewer, pid)

        def fn(p: dict[str, Any]) -> dict[str, Any]:
            (p.get("reactions") or {}).pop(viewer, None)
            return p
        return self.view(viewer, self._touch(owner, pid, fn))

    # --------------------------------------------------------- comments --
    def comment(self, viewer: str, pid: Any, text: Any, reply_to: Any = None) -> dict[str, Any]:
        """A comment, or a reply (one level: a reply to a reply joins the same thread)."""
        self.require(viewer)
        body = _mtext(text, COMMENT_LEN, what="Comment")
        if not body:
            raise CommunityError("Write a comment first.")
        owner, post = self._load(viewer, pid)
        body, mids = self._mentions(viewer, body, post)
        if reply_to is not None and not isinstance(reply_to, str):
            raise CommunityError("comment not found", 404)
        self._take(viewer, "comments", COMMENTS_PER_DAY)
        c = {"id": "c" + secrets.token_hex(6), "by": viewer, "text": body, "ts": int(self._clock()), "parent": None,
             "mentions": mids}

        def fn(p: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            cs = p.setdefault("comments", [])
            if len(cs) >= MAX_COMMENTS:
                raise CommunityError(f"That post has {MAX_COMMENTS} comments, the most it can hold.")
            to = None
            if reply_to:
                target = next((x for x in cs if x["id"] == reply_to), None)
                if target is None or (target["by"] != viewer and self.social.blocked_between(viewer, target["by"])):
                    raise CommunityError("comment not found", 404)
                c["parent"] = target.get("parent") or target["id"]
                to = target["by"]
            cs.append(c)
            return p, to
        post, to = self._touch(owner, pid, fn)
        said = _mn.display(body)
        if owner != viewer:
            self._bump_unread(owner, pid)
            self._notify(owner, pid, f"{self._name(viewer)} commented", said)
        if to and to not in (viewer, owner):
            self._bump_unread(to, pid)
            self._notify(to, pid, f"{self._name(viewer)} replied", said)
        # The owner and the person replied to already got a push for this comment.
        self._tell_mentioned(viewer, post, c["id"], mids, skip={owner, to or ""})
        return self._comment_view(viewer, c, owner == viewer)

    def edit_comment(self, viewer: str, pid: Any, cid: Any, text: Any) -> dict[str, Any]:
        """The comment's author rewrites it. Only people newly @mentioned hear about it."""
        self.require(viewer)
        body = _mtext(text, COMMENT_LEN, what="Comment")
        if not body:
            raise CommunityError("Write a comment first.")
        owner, post = self._load(viewer, pid)
        body, mids = self._mentions(viewer, body, post)
        before: list[str] = []

        def fn(p: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            c = next((x for x in p.get("comments") or [] if x["id"] == cid and x["by"] == viewer), None)
            if c is None:
                raise CommunityError("comment not found", 404)
            before.extend(c.get("mentions") or [])
            if c["text"] != body:
                c["text"], c["mentions"], c["edited"] = body, mids, int(self._clock())
            return p, c
        post, c = self._touch(owner, pid, fn)
        self._tell_mentioned(viewer, post, c["id"], [m for m in mids if m not in before], skip=set())
        return self._comment_view(viewer, c, owner == viewer)

    # ------------------------------------------------------------ likes --
    def like_comment(self, viewer: str, pid: Any, cid: Any, on: bool = True) -> dict[str, Any]:
        """Like (or unlike) a comment. Idempotent. The comment's author gets one bell item per
        comment ("Jesse and 2 others liked your comment") and at most one push an hour."""
        self.require(viewer)
        owner, _ = self._load(viewer, pid)
        if on:
            self._take(viewer, "likes", LIKES_PER_DAY)

        def fn(p: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
            c = next((x for x in p.get("comments") or [] if x["id"] == cid), None)
            if c is None or (c["by"] != viewer and self.social.blocked_between(viewer, c["by"])):
                raise CommunityError("comment not found", 404)
            likes = list(c.get("likes") or [])
            changed = (viewer not in likes) if on else (viewer in likes)
            if changed:
                likes = [*likes, viewer] if on else [u for u in likes if u != viewer]
                c["likes"] = likes
            return p, c, changed
        post, c, changed = self._touch(owner, pid, fn)
        author = c["by"]
        if changed and author != viewer:
            self._like_item(author, pid, c["id"], viewer, on)
            if on:
                said = _mn.display(str(c.get("text") or ""))
                self._notify(author, f"l:{pid}:{c['id']}", f"{self._name(viewer)} liked your comment", said,
                             url=f"/app/?open=post&id={pid}&c={c['id']}")
        return self._comment_view(viewer, c, owner == viewer)

    def comment_likers(self, viewer: str, pid: Any, cid: Any) -> list[str]:
        """Who liked a comment, newest first, without anyone blocked either way."""
        self.require(viewer)
        _, post = self._load(viewer, pid)
        c = next((x for x in post.get("comments") or [] if x["id"] == cid), None)
        if c is None or (c["by"] != viewer and self.social.blocked_between(viewer, c["by"])):
            raise CommunityError("comment not found", 404)
        return [u for u in reversed(c.get("likes") or []) if u == viewer or not self.social.blocked_between(viewer, u)]

    def _like_item(self, to: str, pid: str, cid: str, by: str, on: bool) -> None:
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> None:
            items = [x for x in d.get("likes") or [] if isinstance(x, dict)]
            cur = next((x for x in items if x.get("pid") == pid and x.get("cid") == cid), None)
            if cur is None:
                if not on:
                    return
                cur = {"pid": pid, "cid": cid, "by": []}
            items = [x for x in items if x is not cur]
            who = [u for u in cur.get("by") or [] if u != by]
            if on:
                who.append(by)
                cur["ts"] = now
            cur["by"] = who[-20:]
            if who:
                items.append(cur)
            d["likes"] = items[-MAX_LIKE_ITEMS:]
        try:
            self._mine(to).update(apply)
        except Exception as e:  # the like is saved; the bell item is best effort
            log_event(logger, logging.WARNING, "community_like_item_failed", error=type(e).__name__)

    def likes_for(self, uid: str) -> list[dict[str, Any]]:
        """The bell's "liked your comment" items: one per comment, newest liker first, only
        while the comment is still there and visible."""
        out: list[dict[str, Any]] = []
        for m in reversed(self._mine(uid).load().get("likes") or []):
            pid, cid = m.get("pid"), m.get("cid")
            if not isinstance(pid, str) or not isinstance(cid, str):
                continue
            try:
                _, post = self._load(uid, pid)
            except CommunityError:
                continue
            c = next((x for x in post.get("comments") or [] if x["id"] == cid and x["by"] == uid), None)
            if c is None:
                continue
            still = set(c.get("likes") or [])
            who = [u for u in reversed(m.get("by") or []) if u in still and not self.social.blocked_between(uid, u)]
            if not who:
                continue
            out.append({"pid": pid, "cid": cid, "by": who[0], "others": len(who) - 1, "ts": int(m.get("ts") or 0),
                        "text": _clip(_mn.display(str(c.get("text") or "")), 140)})
        return out

    def delete_comment(self, viewer: str, pid: Any, cid: Any) -> None:
        """The comment's author, or the post's author. Replies go with their comment."""
        self.require(viewer)
        owner, _ = self._load(viewer, pid)

        def fn(p: dict[str, Any]) -> None:
            cs = p.get("comments") or []
            target = next((c for c in cs if c["id"] == cid and (c["by"] == viewer or owner == viewer)), None)
            if target is None:
                raise CommunityError("comment not found", 404)
            p["comments"] = [c for c in cs if c["id"] != cid and c.get("parent") != cid]
        self._touch(owner, pid, fn)

    # ------------------------------------------------------ hide/report --
    def hide(self, viewer: str, pid: Any) -> None:
        """Gone from my feed (nobody is told)."""
        self.require(viewer)
        owner, _ = self._load(viewer, pid)
        if owner == viewer:
            raise CommunityError("That's your own post. You can delete it instead.")

        def apply(d: dict[str, Any]) -> None:
            h = d.setdefault("hidden", [])
            if pid not in h:
                h.append(pid)
                del h[: max(0, len(h) - MAX_HIDDEN)]
        self._mine(viewer).update(apply)

    def report(self, viewer: str, pid: Any, reason: Any = None) -> None:
        """Hide for the reporter and log for the operator."""
        self.hide(viewer, pid)
        owner = self._owner(pid)
        why = _clip(reason, 200) if isinstance(reason, str) else ""

        def log(g: dict[str, Any]) -> None:
            r = g.setdefault("reports", [])
            r.append({"post": pid, "author": owner, "by": viewer, "reason": why, "ts": int(self._clock())})
            del r[: max(0, len(r) - MAX_REPORTS)]
        self._g.update(log)
        log_event(logger, logging.WARNING, "community_report", user_id=viewer, post=pid, author=owner)

    # ----------------------------------------------------------- unread --
    def _bump_unread(self, uid: str, pid: str) -> None:
        """One more new reaction/comment on ``pid`` for ``uid`` (before the push, so the push
        carries the new badge count)."""
        def apply(d: dict[str, Any]) -> None:
            u = d.setdefault("unread", {})
            u[pid] = int(u.get(pid) or 0) + 1
            if len(u) > MAX_UNREAD_POSTS:
                for k in list(u)[: len(u) - MAX_UNREAD_POSTS]:
                    del u[k]
        try:
            self._mine(uid).update(apply)
        except Exception as e:  # the badge is best effort
            log_event(logger, logging.WARNING, "community_unread_failed", error=type(e).__name__)

    def unread_count(self, uid: str) -> int:
        """New reactions/comments on posts I'm in, on posts I can still see."""
        u = self._mine(uid).load().get("unread") or {}
        return sum(int(n) for n in u.values() if isinstance(n, int))

    def mark_seen(self, uid: str, pid: str | None = None) -> None:
        """Clear one post's unread, or all of them (Community opened)."""
        if not (self._mine(uid).load().get("unread") or {}):
            return

        def apply(d: dict[str, Any]) -> None:
            u = d.get("unread") or {}
            if pid is None:
                u.clear()
            else:
                u.pop(pid, None)
            d["unread"] = u
        self._mine(uid).update(apply)

    # ----------------------------------------------------- auto-sharing --
    def auto_share_workouts(self, uid: str, acts: list[dict[str, Any]], today: date, *,
                            days: int = AUTO_DAYS, cap: int = AUTO_PER_SYNC) -> list[str]:
        """Post each newly synced workout (today/yesterday, on or after ``share_since``) to
        friends, once per activity, when "Share my workouts with friends" is on. Returns the
        new post ids. Same compact card as "Share this workout"; title = the sport."""
        if uid.startswith("coach_") or not self.social.is_athlete(uid):
            return []
        s = self._settings_of(self._mine(uid).load())
        if not self.sharing_consent(uid, s):
            return []
        # Earlier consent (friends settings) has no start date: the regular window applies.
        since = s["share_since"] or (today.isoformat() if s["share_workouts"] is True
                                     else (today - timedelta(days=days)).isoformat())
        rows = [r for r in _rows(acts) if activity_key(r["id"]) is not None
                and 0 <= (today - r["date"]).days <= days and r["date"].isoformat() >= since]
        rows.sort(key=lambda r: (r["date"], str(r["id"])))
        out: list[str] = []
        for r in (rows[-cap:] if cap > 0 else []):
            key = f"auto:{activity_key(r['id'])}"

            def claim(d: dict[str, Any], key: str = key) -> bool:
                if self._seen(d, key, today, None):
                    return False
                keys = d.setdefault("keys", {})
                keys[key] = today.isoformat()
                if len(keys) > MAX_KEYS:
                    for k in sorted(keys, key=lambda k: keys[k])[: len(keys) - MAX_KEYS]:
                        del keys[k]
                return True
            if not self._mine(uid).update(claim):
                continue
            card = workout_card(acts, r["id"], today)
            if card is None:
                continue
            card["title"] = _sf.title(card["family"], card.get("kind"))
            card["auto"] = True
            if r["date"] < today:
                card["late"] = True
            if isinstance(r["id"], int):  # Garmin: lap splits (where they mean something) and the reward headline
                card.update(self._extras(uid, r["id"], splits=_sf.splits_ok(card["family"])))
                self.route_card(uid, r["id"], card)
            post = self.create(uid, {"text": "", "category": "other", "audience": self._share_audience(uid, s)},
                               workout=card, limited=False)
            out.append(post["id"])
        return out

    def auto_share_external(self, uid: str, workouts: list[dict[str, Any]], today: date, *,
                            days: int = AUTO_DAYS, cap: int = AUTO_PER_SYNC) -> list[str]:
        """Same as ``auto_share_workouts`` for workouts another source recorded and Garmin didn't
        (``workouts.py`` model, e.g. Oura): sport, distance and time only, labelled with the
        source. Never heart rate or calories. Once per workout."""
        if uid.startswith("coach_") or not self.social.is_athlete(uid):
            return []
        s = self._settings_of(self._mine(uid).load())
        if not self.sharing_consent(uid, s):
            return []
        # Earlier consent (friends settings) has no start date: the regular window applies.
        since = s["share_since"] or (today.isoformat() if s["share_workouts"] is True
                                     else (today - timedelta(days=days)).isoformat())
        out: list[str] = []
        ws = sorted(workouts, key=lambda x: str(x.get("start")))
        for w in (ws[-cap:] if cap > 0 else []):
            day = str(w.get("start") or "")[:10]
            try:
                d0 = date.fromisoformat(day)
            except ValueError:
                continue
            if not (0 <= (today - d0).days <= days) or day < since or not isinstance(w.get("key"), str):
                continue
            key = f"auto:{w['key']}"

            def claim(d: dict[str, Any], key: str = key) -> bool:
                if self._seen(d, key, today, None):
                    return False
                d.setdefault("keys", {})[key] = today.isoformat()
                return True
            if not self._mine(uid).update(claim):
                continue
            sport = str(w.get("sport") or "other")
            km = w.get("km") if isinstance(w.get("km"), int | float) else None
            mins = w.get("minutes") if isinstance(w.get("minutes"), int | float) else None
            raw = str(w.get("kind") or w.get("type") or w.get("name") or "")
            fam = _sf.family(sport, raw)
            if fam in _sf.NO_DISTANCE:
                km = None
            card = {"activity_id": None, "source": str(w.get("source") or ""), "sport": sport, "family": fam,
                    "title": _sf.title(fam, raw), "date": day,
                    "km": round(km, 2) if km else None, "minutes": round(mins) if mins else None,
                    "climb_m": None, "highlight": "", "auto": True, "share_key": w["key"],
                    **_sf.pace_fields(fam, km, mins)}
            if d0 < today:
                card["late"] = True
            post = self.create(uid, {"text": "", "category": "other", "audience": self._share_audience(uid, s)},
                               workout=card, limited=False)
            out.append(post["id"])
        return out

    def _share_audience(self, uid: str, s: dict[str, Any]) -> str:
        """The chosen auto-share audience; groups I've since left drop out, and when none are
        left the workout stays private rather than going wider than chosen."""
        a = s.get("share_audience") or "friends"
        if a == "friends":
            return a
        live = [g for g in self.group_ids(a) if self.groups is not None and self.groups.is_member(g, uid)]
        return "grp:" + ",".join(live) if live else "private"

    def _extras(self, uid: str, aid: int, *, splits: bool = True) -> dict[str, Any]:
        """Split shape (``splits``: only for families where laps mean something) and reward
        headline for a workout card (both best effort)."""
        out: dict[str, Any] = {}
        try:
            if splits and self.splits is not None:
                sp = self.splits(uid, aid)
                if sp:
                    out["splits"] = sp[:MAX_SPLITS]
        except Exception as e:
            log_event(logger, logging.INFO, "community_splits_failed", user_id=uid, error=type(e).__name__)
        try:
            if self.headline is not None:
                h = self.headline(uid, aid)
                if h:
                    out["headline"] = _clip(str(h), 120)
        except Exception as e:
            log_event(logger, logging.INFO, "community_headline_failed", user_id=uid, error=type(e).__name__)
        return out

    # ------------------------------------------------------------- push --
    def _notify(self, to: str, pid: str, title: str, body: str, url: str | None = None) -> None:
        """At most one push per post per hour per person; none in their quiet hours.
        ``url``: the app link it opens (``push_link``), else the feed."""
        if self.push is None:
            return
        try:
            if self._quiet is not None and self._quiet(to):
                return
        except Exception:
            return
        now = self._clock()
        with self._lock:
            last = self._pushed.get((to, pid))
            if last is not None and now - last < PUSH_EVERY_S:
                return
            self._pushed[(to, pid)] = now
            if len(self._pushed) > 5000:
                self._pushed.pop(next(iter(self._pushed)))
        try:
            if url and self.push_link is not None:
                self.push_link(to, title[:60], _clip(body, 140), url)
            else:
                self.push(to, title[:60], _clip(body, 140))
        except Exception as e:
            log_event(logger, logging.WARNING, "community_push_failed", error=type(e).__name__)

    # --------------------------------------------------------- mentions --
    def _may_mention(self, author: str, uid: str, post: dict[str, Any]) -> bool:
        """People ``author`` may @mention here: athletes they follow or who follow them, the
        post's author and commenters, and members of the club or group the post is in.
        Never a coach account, never across a block."""
        if uid == author or uid.startswith("coach_") or not self.social.is_athlete(uid):
            return False
        if self.social.blocked_between(author, uid):
            return False
        if self.social.follows(author, uid) or self.social.follows(uid, author):
            return True
        if uid == post.get("author") or any(c.get("by") == uid for c in post.get("comments") or []):
            return True
        aud = norm_audience(post.get("audience") or "friends")
        if aud.startswith("club:"):
            return bool(self.clubs.is_member(aud[5:], uid))
        if aud.startswith("grp:") and self.groups is not None:
            return any(self.groups.is_member(g, uid) for g in self.group_ids(aud))
        return False

    def _mentions(self, author: str, text: str, post: dict[str, Any]) -> tuple[str, list[str]]:
        """Check the @mentions in ``text`` for ``post``: tokens for people the author may
        mention stay (as links); any other token becomes plain ``@Name``. Someone who can't
        see the post can't be mentioned in it (a clear error rather than a silent link)."""
        names: dict[str, str] = {}
        for m in _mn.TOKEN.finditer(text or ""):
            names.setdefault(m.group(2), m.group(1).strip())
        ok: list[str] = []
        for uid in names:
            if not self._may_mention(author, uid, post):
                continue
            if not self.can_see(uid, post):
                raise CommunityError(f"{self._name(uid)} can't see this post. Change who can see it or remove the mention.")
            ok.append(uid)
        if len(ok) > _mn.MAX_MENTIONS:
            raise CommunityError(f"Mention up to {_mn.MAX_MENTIONS} people at a time.")
        return _mn.keep(text, ok), ok

    def _shown_mentions(self, viewer: str, item: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
        """``(text, [{id, name}])`` for a post or comment as ``viewer`` sees it: links only for
        its own validated mentions, never to someone blocked with the viewer; current names."""
        vis = [u for u in item.get("mentions") or []
               if u == viewer or not self.social.blocked_between(viewer, u)]
        return _mn.keep(str(item.get("text") or ""), vis), [{"id": u, "name": self._name(u)} for u in vis]

    def _tell_mentioned(self, author: str, post: dict[str, Any], cid: str | None, uids: list[str],
                        *, skip: set[str]) -> None:
        """A bell item for each newly mentioned person, and a push (unless they're in ``skip``,
        already told about this comment by another push)."""
        if not uids:
            return
        now = int(self._clock())
        pid = post["id"]
        where = "a comment" if cid else "a post"
        said = _mn.display(next((c["text"] for c in post.get("comments") or [] if c["id"] == cid), "")
                           if cid else str(post.get("text") or ""))
        url = f"/app/?open=post&id={pid}" + (f"&c={cid}" if cid else "")
        for to in uids:
            if to == author:
                continue
            item = {"pid": pid, "cid": cid, "by": author, "ts": now}

            def apply(d: dict[str, Any], item: dict[str, Any] = item) -> None:
                ms = [x for x in d.get("mentions") or [] if not (x.get("pid") == item["pid"] and x.get("cid") == item["cid"])]
                ms.append(item)
                d["mentions"] = ms[-MAX_MENTION_ITEMS:]
            try:
                self._mine(to).update(apply)
            except Exception as e:  # the comment is saved; the bell item is best effort
                log_event(logger, logging.WARNING, "community_mention_failed", error=type(e).__name__)
                continue
            if to not in skip:
                self._notify(to, f"m:{pid}", f"{self._name(author)} mentioned you in {where}", said, url=url)

    def mentions_for(self, uid: str) -> list[dict[str, Any]]:
        """The bell's "mentioned you" items still worth showing: the post is there, ``uid``
        can still see it, the comment wasn't deleted and nobody is blocked."""
        out: list[dict[str, Any]] = []
        for m in reversed(self._mine(uid).load().get("mentions") or []):
            pid, cid, by = m.get("pid"), m.get("cid"), m.get("by")
            if not isinstance(pid, str) or not isinstance(by, str) or self.social.blocked_between(uid, by):
                continue
            try:
                _, post = self._load(uid, pid)
            except CommunityError:
                continue
            if cid:
                c = next((x for x in post.get("comments") or [] if x["id"] == cid), None)
                if c is None or uid not in (c.get("mentions") or []):
                    continue
                text = c["text"]
            else:
                if uid not in (post.get("mentions") or []):
                    continue
                text = str(post.get("text") or "")
            out.append({"pid": pid, "cid": cid, "by": by, "ts": int(m.get("ts") or 0),
                        "where": "comment" if cid else "post", "text": _clip(_mn.display(text), 140)})
        return out

    def mentionable(self, viewer: str, pid: Any = None, audience: Any = None) -> list[dict[str, Any]]:
        """Who ``viewer`` can @mention: ``[{id, can_see}]``. On a post (``pid``) the post's
        author, commenters and its club/group members come first; ``can_see`` is False for
        someone the post (or the chosen ``audience`` of a new post) doesn't reach."""
        self.require(viewer)
        if pid:
            _, post = self._load(viewer, pid)
        else:
            aud = audience if isinstance(audience, str) and audience else "friends"
            post = {"author": viewer, "audience": aud, "comments": []}
        ids: list[str] = []
        if pid:
            ids.append(str(post["author"]))
            ids += [str(c["by"]) for c in post.get("comments") or []]
        aud = norm_audience(post.get("audience") or "friends")
        if aud.startswith("club:"):
            ids += list(self.clubs.member_ids(aud[5:], viewer))
        if aud.startswith("grp:") and self.groups is not None:
            for g in self.group_ids(aud):
                ids += list(self.groups.member_ids(g, viewer))
        ids += self.social.following_ids(viewer) + self.social.follower_ids(viewer)
        out: list[dict[str, Any]] = []
        for u in dict.fromkeys(i for i in ids if i):
            if self._may_mention(viewer, u, post):
                out.append({"id": u, "can_see": bool(self.can_see(u, post))})
            if len(out) >= 300:
                break
        return out

    # ----------------------------------------------------------- photos --
    def save_photo(self, uid: str, data: bytes) -> dict[str, Any]:
        self.require(uid)
        mime = check_photo(data)
        now = int(self._clock())
        phid = "f" + secrets.token_hex(8)
        orphans: list[str] = []

        def reserve(d: dict[str, Any]) -> None:
            u = d.setdefault("photos", {"items": {}})
            items = u.setdefault("items", {})
            for k, it in list(items.items()):  # uploaded but never posted
                if it.get("post") is None and now - it.get("ts", now) > ORPHAN_TTL_S:
                    orphans.append(k)
                    del items[k]
            if len(items) >= PHOTO_QUOTA_COUNT or sum(it["size"] for it in items.values()) + len(data) > PHOTO_QUOTA_BYTES:
                raise CommunityError(f"You've reached the photo limit ({PHOTO_QUOTA_COUNT} photos or "
                                     f"{PHOTO_QUOTA_BYTES // 1024 // 1024} MB). Delete old posts to free space.", 413)
            items[phid] = {"size": len(data), "ts": now, "post": None}
        self._mine(uid).update(reserve)
        for k in orphans:
            self._s.user_doc(uid, f"cphoto-{k}").delete()
        self._s.user_doc(uid, f"cphoto-{phid}").save({"mime": mime, "data": base64.b64encode(data).decode("ascii")})
        return {"photo_id": phid}

    def _attach_photos(self, uid: str, ids: list[str], pid: str) -> list[dict[str, Any]]:
        if not ids:
            return []
        for phid in ids:
            if not _ID.match(phid):
                raise CommunityError("photo not found", 404)

        def apply(d: dict[str, Any]) -> None:
            items = (d.get("photos") or {}).get("items") or {}
            for phid in ids:
                it = items.get(phid)
                if it is None or it.get("post") not in (None, pid):
                    raise CommunityError("photo not found", 404)
            for phid in ids:
                items[phid]["post"] = pid
        self._mine(uid).update(apply)
        v = int(self._clock())
        return [{"id": phid, "v": v + i} for i, phid in enumerate(ids)]

    def _drop_photos(self, uid: str, post: dict[str, Any]) -> None:
        ids = [p["id"] for p in post.get("photos") or [] if p.get("id")]
        if not ids:
            return
        for phid in ids:
            self._s.user_doc(uid, f"cphoto-{phid}").delete()

        def apply(d: dict[str, Any]) -> None:
            items = (d.get("photos") or {}).get("items") or {}
            for phid in ids:
                items.pop(phid, None)
        self._mine(uid).update(apply)

    def photo(self, viewer: str, pid: Any, n: int = 0) -> tuple[str, bytes] | None:
        """Photo ``n`` of a post, only for its audience."""
        self.require(viewer)
        owner, post = self._load(viewer, pid)
        photos = post.get("photos") or []
        if not 0 <= n < len(photos):
            return None
        d = self._s.user_doc(owner, f"cphoto-{photos[n]['id']}").load()
        if not d.get("data"):
            return None
        data = base64.b64decode(d["data"])
        try:
            return sniff_photo(data), data
        except CommunityError:
            return None

    def usage(self, uid: str) -> dict[str, int]:
        items = ((self._mine(uid).load().get("photos") or {}).get("items") or {})
        return {"photos": len(items), "bytes": sum(it["size"] for it in items.values()),
                "max_photos": PHOTO_QUOTA_COUNT, "max_bytes": PHOTO_QUOTA_BYTES}

    # ------------------------------------------------------- milestones --
    def drafts(self, uid: str) -> list[dict[str, Any]]:
        self.require(uid)
        today = self._now(uid).date()
        ds = list((self._mine(uid).load().get("drafts") or {}).values())
        ds = [x for x in ds if (today - date.fromisoformat(x["day"])).days <= DRAFT_TTL_DAYS]
        ds.sort(key=lambda x: x["created"], reverse=True)
        return ds

    def _seen(self, d: dict[str, Any], key: str, today: date, ttl_days: int | None) -> bool:
        when = (d.get("keys") or {}).get(key)
        if when is None:
            return False
        if ttl_days is None:
            return True
        try:
            return (today - date.fromisoformat(when)).days < ttl_days
        except ValueError:
            return True

    def milestone(self, uid: str, mtype: str, key: str, text: str, *, event: dict[str, Any] | None = None,
                  ttl_days: int | None = None, announce: bool = True) -> dict[str, Any] | None:
        """Make a milestone: a draft (``{"draft": ...}``), or a post when auto-share is on
        for that type (``{"post": ...}``); None when turned off or already made. With
        ``announce`` Rabbit posts a moment with [Share] [Not now] (or "Shared")."""
        if uid.startswith("coach_") or not self.social.is_athlete(uid) or mtype not in MILESTONES:
            return None
        today = self._now(uid).date()
        now = int(self._clock())

        def apply(d: dict[str, Any]) -> dict[str, Any] | None:
            s = self._settings_of(d)
            if not s["milestones"][mtype] or self._seen(d, key, today, ttl_days):
                return None
            keys = d.setdefault("keys", {})
            keys[key] = today.isoformat()
            if len(keys) > MAX_KEYS:
                for k in sorted(keys, key=lambda k: keys[k])[: len(keys) - MAX_KEYS]:
                    del keys[k]
            draft = {"id": "d" + secrets.token_hex(6), "type": mtype, "key": key, "text": _clip(text, TEXT_LEN),
                     "category": MILESTONE_CATEGORY[mtype], "event": event, "created": now, "day": today.isoformat()}
            if s["auto_share"][mtype]:
                return {"auto": draft, "audience": s["audience"]}
            drafts = d.setdefault("drafts", {})
            drafts[draft["id"]] = draft
            if len(drafts) > MAX_DRAFTS:
                for k in sorted(drafts, key=lambda k: drafts[k]["created"])[: len(drafts) - MAX_DRAFTS]:
                    del drafts[k]
            return {"draft": draft}
        res = self._mine(uid).update(apply)
        if res is None:
            return None
        if "auto" in res:
            dr = res["auto"]
            post = self.create(uid, {"text": dr["text"], "category": dr["category"], "audience": res["audience"],
                                     "event_id": (dr.get("event") or {}).get("id")},
                               milestone={"type": mtype, "key": key}, limited=False)
            out: dict[str, Any] = {"post": post}
        else:
            out = {"draft": res["draft"]}
        if announce and self.moment is not None:
            self._announce(uid, out, key)
        return out

    @staticmethod
    def share_actions(out: dict[str, Any]) -> list[dict[str, Any]]:
        if "post" in out:
            return [{"id": "community", "label": "See it in your Feed", "post_id": out["post"]["id"]}]
        did = out["draft"]["id"]
        return [{"id": "community_share", "label": "Share", "draft_id": did},
                {"id": "community_later", "label": "Not now", "draft_id": did}]

    def _announce(self, uid: str, out: dict[str, Any], key: str) -> None:
        text = (out.get("post") or out.get("draft") or {}).get("text") or ""
        text = _LEAD_EMOJI.sub("", text).strip()
        tail = " Shared to your Feed." if "post" in out else " Share it with your people?"
        line = _clip(f"🎉 {_clip(text, 140 - len(tail) - 3)}{tail}", 140)
        try:
            assert self.moment is not None
            self.moment(uid, {"type": "milestone", "key": f"cm:{key}", "text": line, "ttl_days": 30,
                              "actions": self.share_actions(out)})
        except Exception as e:  # the draft stands without the Rabbit-log line
            log_event(logger, logging.WARNING, "community_moment_failed", user_id=uid, error=type(e).__name__)

    def from_moment(self, uid: str, m: dict[str, Any]) -> list[dict[str, Any]] | None:
        """``Moments.on_milestone``: a streak/level/badge/challenge moment becomes a draft
        (or an auto-shared post); returns the chips for that moment."""
        got = from_moment_text(m)
        if got is None:
            return None
        mtype, text = got
        out = self.milestone(uid, mtype, str(m["key"]), text, ttl_days=m.get("ttl_days"), announce=False)
        return self.share_actions(out) if out else None

    def dismiss(self, uid: str, did: Any) -> None:
        self.require(uid)

        def apply(d: dict[str, Any]) -> None:
            (d.get("drafts") or {}).pop(did, None) if isinstance(did, str) else None
        self._mine(uid).update(apply)

    def share(self, uid: str, did: Any, body: Any = None) -> dict[str, Any]:
        """Post a draft (text/audience/photos/feeling may be edited first). Sharing a draft
        that was already shared or dismissed is a 404."""
        self.require(uid)
        body = body if isinstance(body, dict) else {}

        def take(d: dict[str, Any]) -> dict[str, Any] | None:
            return (d.get("drafts") or {}).pop(did, None) if isinstance(did, str) else None
        dr = self._mine(uid).update(take)
        if dr is None:
            raise CommunityError("That one's already shared or dismissed.", 404)
        fields = {"text": dr["text"], "category": dr["category"], "event_id": (dr.get("event") or {}).get("id"),
                  **{k: body[k] for k in ("text", "category", "feeling", "audience", "photo_ids", "event_id") if k in body}}
        try:
            return self.create(uid, fields, milestone={"type": dr["type"], "key": dr["key"]})
        except CommunityError:
            self._mine(uid).update(lambda d: d.setdefault("drafts", {}).__setitem__(dr["id"], dr))
            raise

    # ------------------------------------------------------------ people --
    def suggestions(self, uid: str, limit: int = 20) -> list[dict[str, Any]]:
        """People you might follow: followers you don't follow back, people in your clubs
        (race groups too). Allowlisted athletes only; never blocked either way."""
        self.require(uid)
        skip = {uid, *self.social.following_ids(uid, limit=FEED_FOLLOWEES), *self.social.pending_ids(uid)}
        out: dict[str, str] = {}
        for f in self.social.follower_ids(uid):
            if f not in skip:
                out.setdefault(f, "Follows you")
        for cid in self.clubs.ids_of(uid):
            name = self.clubs.name_of(cid, uid) or "your club"
            for m in self.clubs.member_ids(cid, uid):
                if m not in skip:
                    out.setdefault(m, f"In {name}")
        return [{"user_id": u, "reason": why} for u, why in out.items()
                if self.social.is_athlete(u) and not self.social.blocked_between(uid, u)][:limit]

    def related(self, viewer: str, other: str) -> bool:
        """May ``viewer`` see ``other``'s profile photo: self, a follow edge either way, a
        shared club, or ``other`` posted publicly."""
        if viewer == other:
            return True
        if self.social.blocked_between(viewer, other):
            return False
        if self.social.follows(viewer, other) or self.social.follows(other, viewer):
            return True
        if any(self.clubs.is_member(c, other) for c in self.clubs.ids_of(viewer)):
            return True
        return any(a == other for a, _ in (self._g.load().get("public") or {}).values())

    # ----------------------------------------------------------- meetups --
    def meetup_reminders(self, uid: str) -> int:
        """``Moments.tick``: a Rabbit moment for each "going" meetup in the next 18 h (once
        each; checked at most every 10 minutes)."""
        if uid.startswith("coach_") or self.moment is None:
            return 0
        now = self._clock()
        with self._lock:
            if now - self._reminded.get(uid, 0) < REMIND_EVERY_S:
                return 0
            self._reminded[uid] = now
        local = self._now(uid)
        n = 0
        for m in self.clubs.reminders(uid, local):
            self.moment(uid, {"type": "meetup", "key": f"meetup:{m['id']}:{m['next']}", "ttl_days": 3,
                              "text": meetup_line(m, local.date()),
                              "actions": [{"id": "community", "label": "Open club", "club_id": m["club"]["id"]}]})
            n += 1
        return n

    # ---------------------------------------------------------- scanning --
    def scan_events(self, uid: str, events: list[dict[str, Any]], today: date,
                    acts: list[dict[str, Any]] | None = None) -> int:
        """Races finished in the last week: a result or debrief, or a workout on race day.
        Also "firsts" (first ultra, 70.3, ...) from the event's distance. Only race events
        (not trips, group activities or life events)."""
        if uid.startswith("coach_"):
            return 0
        act_days: dict[str, set[str]] = {}
        for r in _rows(acts or []):
            act_days.setdefault(r["date"].isoformat(), set()).add(r["sport"])
        n = 0
        races = [e for e in events if e.get("kind") in (None, "", "race")]
        done = sorted((e for e in races if e.get("id") and e.get("date")
                       and 0 <= (today - _day(e["date"], today)).days <= RACE_SCAN_DAYS),
                      key=lambda e: e["date"])
        for ev in done:
            day = ev["date"]
            finished = bool(ev.get("result") or ev.get("debrief")) or bool(act_days.get(day))
            if not finished:
                continue
            name = _clip(str(ev.get("name") or "my race"), 60)
            result = _clip(str(ev.get("result") or ""), 40)
            text = f"Finished {name}!" + (f" {result}." if result and len(result) <= 40 else "")
            if self.milestone(uid, "race", f"race:{ev['id']}", text, event=event_snapshot(ev)):
                n += 1
            cls = event_class(ev)
            if cls is None:
                continue
            earlier = [e for e in races if e.get("id") != ev["id"] and str(e.get("date") or "") < day
                       and (e.get("result") or e.get("debrief")) and event_class(e) == cls]
            if earlier:
                continue
            got = self.milestone(uid, "first", f"first:{cls}", f"{FIRSTS[cls]}! {name}, done.", event=event_snapshot(ev))
            n += bool(got)
        return n

    def scan_bests(self, uid: str, acts: list[dict[str, Any]], today: date, *, imperial: bool) -> int:
        """Personal bests (12-month bests, as on the reaction card) set today or yesterday."""
        if uid.startswith("coach_"):
            return 0
        from .workoutday import new_bests
        n = 0
        recent = [r for r in _rows(acts) if isinstance(r["id"], int) and 0 <= (today - r["date"]).days <= 1]
        for r in recent[-3:]:
            for b in new_bests(acts, r["id"], today)[:1]:
                if self.milestone(uid, "pb", f"pb:{b['key']}:{r['id']}", pb_text(b, imperial)):
                    n += 1
        return n


def _day(s: str, fallback: date) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return fallback + timedelta(days=9999)


__all__ = [
    "AUDIENCES",
    "CATEGORIES",
    "COMMENTS_PER_DAY",
    "COMMENT_LEN",
    "FEELINGS",
    "MAX_COMMENTS",
    "MAX_PHOTOS",
    "MILESTONES",
    "PAGE",
    "PHOTO_MAX",
    "PHOTO_QUOTA_BYTES",
    "PHOTO_QUOTA_COUNT",
    "POSTS_PER_DAY",
    "REACTIONS",
    "TEXT_LEN",
    "SOURCES",
    "Community",
    "CommunityError",
    "activity_key",
    "source_of",
    "check_photo",
    "event_class",
    "from_moment_text",
    "image_size",
    "meetup_line",
    "pb_text",
    "valid_pid",
    "workout_card",
    "workout_label",
]
