"""Featured clubs: the app owner promotes up to ``MAX_FEATURED`` clubs at once.

The owner (``auth.is_owner``) flips "Feature this club" on a Rabbit club page or on a
directory listing (clubdir.py), with an optional end date (inclusive, ``YYYY-MM-DD``) and a
short tagline (<= ``TAGLINE_LEN``). Featured clubs show, clearly labelled "Featured", at the
top of Community (Feed and Clubs) and in Explore -> For you, as one card: name, sport, city,
next meetup, member count and Join / RSVP.

Who sees a feature (``matches``): people in that club's city (same city + state), people whose
sports match the club's (favorite sports, race interests, main race), and everyone when the
club is online/virtual. Nobody else. A club owner who blocked the viewer (either way) never
shows. Expired features drop out (and are pruned on the next write).

Fair rotation (``rotate``): the eligible features, oldest first, rotated by one per local day,
so each one leads in turn; at most ``SHOW_MAX`` are shown.

Storage: global ``featured`` doc ``{"items": {fid: {...}}}``. ``fid`` = ``club:<cid>`` or
``dir:<city>|<st>|<lid>``. Deterministic; no clock reads here except the injected one.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date
from typing import Any

from .appstore import AppStore

MAX_FEATURED = 3
SHOW_MAX = 3
TAGLINE_LEN = 80
MAX_DAYS = 366
KINDS = ("club", "listing")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_ONLINE = re.compile(r"\b(online|virtual|remote|zwift|anywhere)\b", re.I)

# Canonical sport families shared by clubs, directory listings and the athlete's profile.
CLUB_SPORT = {"running": "run", "trail": "trail", "cycling": "bike", "triathlon": "tri", "swimming": "swim",
              "walking": "walk", "multisport": "tri", "other": "other"}
LISTING_SPORT = {"run_club": "run", "trail": "trail", "tri": "tri", "ride": "bike", "swim": "swim",
                 "league": "other", "other": "other"}
FAVORITE_SPORT = {"run": "run", "trail": "trail", "bike": "bike", "gravel": "bike", "mtb": "bike", "swim": "swim",
                  "open_water": "swim", "walk": "walk", "hike": "walk"}
RACE_TYPE_SPORT = {"road": "run", "trail": "trail", "ultra": "trail", "triathlon": "tri", "duathlon": "tri",
                   "gravel": "bike", "road_cycling": "bike", "mtb": "bike", "swim": "swim"}
EVENT_TYPE_SPORT = {"running": "run", "trail": "trail", "triathlon": "tri", "cycling": "bike", "swimming": "swim",
                    "duathlon": "tri", "mountaineering": "trail"}


class FeatureError(ValueError):
    """Message is safe to show the user."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def athlete_sports(athlete: dict[str, Any], main_event_type: str | None = None) -> set[str]:
    """The viewer's sport families from their profile (never Garmin or health data)."""
    out: set[str] = set()
    for f in athlete.get("favorite_sports") or []:
        if f in FAVORITE_SPORT:
            out.add(FAVORITE_SPORT[f])
    for t in (athlete.get("interests") or {}).get("race_types") or []:
        if t in RACE_TYPE_SPORT:
            out.add(RACE_TYPE_SPORT[t])
    if main_event_type in EVENT_TYPE_SPORT:
        out.add(EVENT_TYPE_SPORT[main_event_type])
    if "tri" in out:
        out |= {"run", "bike", "swim"}
    if "trail" in out:
        out.add("run")
    return out


def sport_match(club_sport: str, viewer: set[str]) -> bool:
    """A run club matches runners (trail runners too); a tri club matches triathletes."""
    if club_sport == "other" or not viewer:
        return False
    return club_sport in viewer


def matches(item: dict[str, Any], *, city: str, state: str, sports: set[str]) -> bool:
    """Local (same city + state), the same sport, or an online/virtual club."""
    if item.get("online"):
        return True
    ic, ist = str(item.get("city") or "").strip().lower(), str(item.get("state") or "").strip().lower()
    if ic and city and ic == city.strip().lower() and (not ist or not state or ist == state.strip().lower()):
        return True
    return sport_match(str(item.get("family") or "other"), sports)


def active(item: dict[str, Any], today: date) -> bool:
    until = item.get("until")
    return not until or str(until) >= today.isoformat()


def rotate(items: list[dict[str, Any]], today: date, n: int = SHOW_MAX) -> list[dict[str, Any]]:
    """Oldest first, rotated by one per day, at most ``n``."""
    xs = sorted(items, key=lambda x: (x.get("created") or 0, x["id"]))
    if not xs:
        return []
    k = today.toordinal() % len(xs)
    return (xs[k:] + xs[:k])[:n]


def online_hint(*texts: Any) -> bool:
    return any(isinstance(t, str) and _ONLINE.search(t) for t in texts)


def clean_tagline(v: Any) -> str:
    if v in (None, ""):
        return ""
    if not isinstance(v, str):
        raise FeatureError("Tagline must be text.")
    s = " ".join(_CTRL.sub(" ", v).split())
    if len(s) > TAGLINE_LEN:
        raise FeatureError(f"Keep the tagline under {TAGLINE_LEN} characters.")
    return s


def clean_until(v: Any, today: date) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not _DATE.match(v):
        raise FeatureError("Pick an end date.")
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise FeatureError("Pick an end date.") from None
    if d < today:
        raise FeatureError("Pick an end date that hasn't passed.")
    if (d - today).days > MAX_DAYS:
        raise FeatureError("Feature a club for up to a year at a time.")
    return d.isoformat()


Resolve = Callable[[dict[str, Any], str], dict[str, Any] | None]


class Featured:
    """``club_card(cid, viewer)`` / ``listing_card(city, state, lid, viewer)``: the live card
    (``{name, sport, city, state, online?, ...}``) or None when gone/hidden/blocked for the
    viewer. ``is_owner(uid)``: the app owner."""

    def __init__(self, store: AppStore, *, is_owner: Callable[[str], bool],
                 club_card: Callable[[str, str], dict[str, Any] | None],
                 listing_card: Callable[[str, str, str, str], dict[str, Any] | None],
                 clock: Callable[[], float] = time.time) -> None:
        self._doc = store.global_doc("featured")
        self._is_owner = is_owner
        self._club = club_card
        self._listing = listing_card
        self._clock = clock

    @staticmethod
    def fid(kind: str, ref: dict[str, str]) -> str:
        if kind == "club":
            return f"club:{ref['club_id']}"
        return f"dir:{ref['city'].lower()}|{ref['state'].lower()}|{ref['listing_id']}"

    def _card(self, item: dict[str, Any], viewer: str) -> dict[str, Any] | None:
        try:
            if item["kind"] == "club":
                card = self._club(item["club_id"], viewer)
                fam = club_sport((card or {}).get("sport"))
            else:
                card = self._listing(item["city"], item["state"], item["listing_id"], viewer)
                fam = listing_sport((card or {}).get("listing_kind"))
        except Exception:  # a club or listing that vanished never breaks the strip
            return None
        return None if card is None else {**card, "family": fam}

    def _require_owner(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_owner(uid):
            raise FeatureError("Only the app owner can feature clubs.", 403)

    # ------------------------------------------------------------ owner --
    def state(self, uid: str, kind: str, ref: dict[str, str], today: date) -> dict[str, Any]:
        """``{owner, featured, until, tagline, online, slots_left}`` for the owner's switch."""
        if uid.startswith("coach_") or not self._is_owner(uid):
            return {"owner": False}
        items = {k: v for k, v in (self._doc.load().get("items") or {}).items() if active(v, today)}
        it = items.get(self.fid(kind, ref))
        return {"owner": True, "featured": it is not None, "until": (it or {}).get("until"),
                "tagline": (it or {}).get("tagline") or "", "online": bool((it or {}).get("online")),
                "slots_left": MAX_FEATURED - len(items) + (1 if it else 0)}

    def set(self, uid: str, kind: Any, ref: dict[str, Any], body: Any, today: date) -> dict[str, Any]:
        """Turn a feature on (or update it) / off. Owner only; at most ``MAX_FEATURED`` live."""
        self._require_owner(uid)
        if kind not in KINDS or not isinstance(body, dict):
            raise FeatureError("bad request")
        on = body.get("on")
        if not isinstance(on, bool):
            raise FeatureError("on must be true or false")
        key = self.fid(kind, ref)
        if not on:
            def off(d: dict[str, Any]) -> None:
                items = d.setdefault("items", {})
                items.pop(key, None)
                for k in [k for k, v in items.items() if not active(v, today)]:
                    del items[k]
            self._doc.update(off)
            return self.state(uid, kind, ref, today)
        tagline = clean_tagline(body.get("tagline"))
        until = clean_until(body.get("until"), today)
        probe = {"kind": kind, **ref}
        card = self._card(probe, uid)
        if card is None:
            raise FeatureError("club not found", 404)
        online = body.get("online")
        if online is None:
            online = bool(card.get("online")) or online_hint(card.get("name"), card.get("city"), card.get("description"))
        elif not isinstance(online, bool):
            raise FeatureError("online must be true or false")

        def put(d: dict[str, Any]) -> None:
            items = d.setdefault("items", {})
            for k in [k for k, v in items.items() if not active(v, today)]:
                del items[k]
            cur = items.get(key)
            if cur is None and len(items) >= MAX_FEATURED:
                raise FeatureError(f"{MAX_FEATURED} clubs are featured already. Turn one off first.", 409)
            items[key] = {**(cur or {}), "id": key, **probe, "tagline": tagline, "until": until, "online": online,
                          "family": card["family"], "city": str(card.get("city") or ""),
                          "state": str(card.get("state") or ""), "by": uid,
                          "created": (cur or {}).get("created") or int(self._clock())}
        self._doc.update(put)
        return self.state(uid, kind, ref, today)

    # ------------------------------------------------------------ viewers --
    def for_viewer(self, viewer: str, *, city: str, state: str, sports: set[str], today: date,
                   limit: int = SHOW_MAX) -> list[dict[str, Any]]:
        """The featured cards this viewer may see, rotated fairly."""
        items = [v for v in (self._doc.load().get("items") or {}).values() if isinstance(v, dict) and active(v, today)]
        out: list[dict[str, Any]] = []
        for it in rotate(items, today, n=MAX_FEATURED):
            card = self._card(it, viewer)
            if card is None:
                continue
            look = {**card, "online": bool(it.get("online"))}
            if not matches(look, city=city, state=state, sports=sports):
                continue
            out.append({"id": it["id"], "kind": it["kind"], "label": "Featured", "tagline": it.get("tagline") or "",
                        "until": it.get("until"), "online": bool(it.get("online")),
                        "local": bool(city) and str(card.get("city") or "").lower() == city.strip().lower(),
                        **card})
            if len(out) >= limit:
                break
        return out


def club_sport(sport: Any) -> str:
    return CLUB_SPORT.get(str(sport or ""), "other")


def listing_sport(kind: Any) -> str:
    return LISTING_SPORT.get(str(kind or ""), "other")


__all__ = [
    "MAX_FEATURED",
    "SHOW_MAX",
    "TAGLINE_LEN",
    "FeatureError",
    "Featured",
    "active",
    "athlete_sports",
    "club_sport",
    "listing_sport",
    "matches",
    "online_hint",
    "rotate",
]
