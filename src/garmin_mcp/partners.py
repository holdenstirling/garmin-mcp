"""Partners: clubs, shops and groups the app owner promotes to people in their area.

Different from ``featured.py`` (which spotlights a Rabbit club or a directory listing): a partner
is a curated card the owner writes (name, kind, tagline, description, schedule text, https links)
for one or more metros. Partners are always labelled "Partner" wherever they show, never mixed in
as organic results:

* Community -> Clubs near you: a "Partners near you" spot at the top for people whose home metro
  ("City, ST", same as ``clubdir.metro``) is one of the partner's metros;
* the club search there and Search everywhere: pinned first, labelled, when the query is about
  that kind of group ("run club", "running") or names the partner.

Owner only (``is_owner``; coach accounts never): add / edit / remove, plus anonymous counts per
partner (card views, link taps, "I'm interested"): daily totals, each person counted at most
once per partner, kind and day (deduped in memory, nobody's id is stored).

Sponsored placement: a partner marked ``sponsored`` (the default for the seeded one) also shows
as one "Sponsored partner" card in the find-clubs flows (Local, Discover, Explore, the directory's
empty state, search) for people whose area is one of its metros, or who search or set a zip that
maps to one (``zip_metro``: a static Front Range prefix table). Always disclosed ("Sponsored" plus
"Why am I seeing this?"), at most one card per screen, and "Hide" keeps it off that screen for that
person for 30 days. The owner sees impressions, taps and hides per placement.

Storage: global ``partners`` doc ``{"items": {pid: {...}}, "seeded": bool, "stats": {pid: {...}}}``.
The first load seeds 5280 Runners for Denver and nearby Front Range cities (facts from the club's
RunSignup page only); the owner can edit or remove it and it never comes back once removed.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

from .clubdir import key_words, metro as to_metro, name_match, words_of
from .localacts import clean_url

MAX_PARTNERS = 30
MAX_METROS = 25
NAME_LEN, TAGLINE_LEN, DESC_LEN, SCHEDULE_LEN = 60, 80, 280, 160
STATS_DAYS = 30
SHOW_MAX = 3
COUNT_KINDS = ("view", "website", "instagram", "signup", "interested")
# Sponsored placements (one card per screen) and what's counted there.
PLACEMENTS = ("local", "home", "discover", "explore", "directory_empty", "search")
PLACE_KINDS = ("impression", "tap", "hide")
HIDE_DAYS = 30
_ZIP = re.compile(r"^\d{5}$")
# Zip -> metro for the partners' Front Range cities (USPS prefixes 800-802 are the Denver metro;
# a few named suburbs get their own city so a partner can serve them separately). Static and
# deterministic: no geocoding call per keystroke.
_ZIP_CITY = {
    "80010": "Aurora", "80011": "Aurora", "80012": "Aurora", "80013": "Aurora", "80014": "Aurora",
    "80015": "Aurora", "80016": "Aurora", "80017": "Aurora", "80018": "Aurora", "80019": "Aurora",
    "80045": "Aurora", "80247": "Aurora",
    "80226": "Lakewood", "80227": "Lakewood", "80228": "Lakewood", "80232": "Lakewood", "80235": "Lakewood",
    "80110": "Englewood", "80111": "Englewood", "80112": "Englewood", "80113": "Englewood",
    "80120": "Littleton", "80121": "Littleton", "80122": "Littleton", "80123": "Littleton", "80127": "Littleton",
    "80128": "Littleton", "80129": "Highlands Ranch", "80130": "Highlands Ranch", "80126": "Highlands Ranch",
    "80002": "Arvada", "80003": "Arvada", "80004": "Arvada", "80005": "Arvada", "80007": "Arvada",
    "80030": "Westminster", "80031": "Westminster", "80234": "Westminster", "80021": "Westminster",
    "80033": "Wheat Ridge", "80401": "Golden", "80403": "Golden",
    "80020": "Broomfield", "80023": "Broomfield",
    "80022": "Commerce City", "80640": "Commerce City",
    "80241": "Thornton", "80229": "Thornton", "80233": "Thornton", "80260": "Thornton",
    "80214": "Edgewater", "80246": "Glendale", "80237": "Greenwood Village",
}
_ZIP_PREFIX = {"800": "Denver", "801": "Denver", "802": "Denver"}


def zip_metro(zip_: Any) -> tuple[str, str] | None:
    """(city, "CO") for a Front Range zip a partner can serve, else None."""
    z = str(zip_ or "").strip()
    if not _ZIP.match(z):
        return None
    city = _ZIP_CITY.get(z) or _ZIP_PREFIX.get(z[:3])
    return (city, "CO") if city else None
KINDS = ("run_club", "tri_club", "ride", "swim", "trail", "store", "coach", "other")
KIND_LABEL = {"run_club": "Run club", "tri_club": "Tri club", "ride": "Cycling club", "swim": "Swim group",
              "trail": "Trail group", "store": "Shop", "coach": "Coaching", "other": "Group"}
# Words that make a query "about" a kind of partner (so the partner is pinned, labelled).
KIND_WORDS: dict[str, frozenset[str]] = {
    "run_club": frozenset({"run", "runs", "running", "runner", "runners", "jog", "jogging", "5k", "10k", "marathon",
                           "track", "club", "clubs", "group", "groups", "crew", "social"}),
    "trail": frozenset({"trail", "trails", "run", "running", "hike", "club", "group", "crew"}),
    "tri_club": frozenset({"tri", "triathlon", "triathlete", "club", "clubs", "group", "multisport"}),
    "ride": frozenset({"ride", "rides", "bike", "biking", "cycling", "cyclist", "club", "group", "gravel"}),
    "swim": frozenset({"swim", "swimming", "masters", "pool", "open", "water", "club", "group"}),
    "store": frozenset({"store", "shop", "shoes", "gear", "run", "running"}),
    "coach": frozenset({"coach", "coaching", "training", "plan"}),
    "other": frozenset({"club", "group", "groups"}),
}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_HANDLE = re.compile(r"^@?([A-Za-z0-9._]{1,30})$")
_PID = re.compile(r"^p[0-9a-f]{10}$")

FRONT_RANGE = ("Denver", "Aurora", "Lakewood", "Englewood", "Littleton", "Arvada", "Westminster", "Wheat Ridge",
               "Golden", "Centennial", "Thornton", "Commerce City", "Glendale", "Edgewater", "Greenwood Village",
               "Cherry Hills Village", "Highlands Ranch", "Broomfield")
SEED: dict[str, Any] = {
    "id": "p5280runner",
    "name": "5280 Runners",
    "kind": "run_club",
    "tagline": "Run with Altitude",
    "description": "A Denver running club for runners of all abilities, from a first 5K to a marathon. "
                   "Memberships include group runs.",
    "schedule": "",
    "website": "https://5280runners.com/",
    "instagram": "",
    "signup": "https://runsignup.com/Club/CO/DENVER/5280Runners",
    "metros": [{"city": c, "state": "CO"} for c in FRONT_RANGE],
    "starts": None, "ends": None, "active": True, "sponsored": True,
}


class PartnerError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------- matching --
def about_kind(query: Any, kind: str) -> bool:
    """True when every query word is a generic word for this kind ("run club", "running groups")."""
    w = words_of(query)
    return bool(w) and all(x in KIND_WORDS.get(kind, KIND_WORDS["other"]) for x in w)


def monogram(name: str) -> str:
    w = [x for x in re.split(r"\s+", name.strip()) if x]
    if not w:
        return "?"
    if w[0][:1].isdigit():
        return w[0][:4]
    return "".join(x[0] for x in w[:2]).upper()


# ------------------------------------------------------------- cleaning --
def _text(v: Any, n: int, *, required: str | None = None) -> str:
    t = " ".join(_CTRL.sub(" ", v).split()) if isinstance(v, str) else ""
    if required and not t:
        raise PartnerError(required)
    if len(t) > n:
        raise PartnerError(f"Keep it under {n} characters.")
    return t


def _https(v: Any, label: str) -> str:
    if v in (None, ""):
        return ""
    t = v.strip() if isinstance(v, str) else ""
    if t and "://" not in t:
        t = "https://" + t  # "5280runners.com" -> https://5280runners.com
    u = clean_url(t)
    if not u:
        raise PartnerError(f"{label} must be an https:// link.")
    return u


def _instagram(v: Any) -> str:
    if v in (None, ""):
        return ""
    if isinstance(v, str) and (m := _HANDLE.match(v.strip())):
        return f"https://www.instagram.com/{m.group(1)}/"
    u = _https(v, "Instagram")
    host = (urlsplit(u).hostname or "").lower()
    if host not in ("instagram.com", "www.instagram.com"):
        raise PartnerError("Instagram must be an instagram.com link or @handle.")
    return u


def _day(v: Any, label: str) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not _DATE.match(v):
        raise PartnerError(f"{label} must be YYYY-MM-DD.")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise PartnerError(f"{label} must be a real date.") from None
    return v


def _metros(v: Any) -> list[dict[str, str]]:
    if not isinstance(v, list) or not v:
        raise PartnerError("Add at least one city (City, ST).")
    out: list[dict[str, str]] = []
    for x in v[: MAX_METROS + 1]:
        if isinstance(x, str) and "," in x:
            c, s = x.rsplit(",", 1)
            x = {"city": c, "state": s}
        m = to_metro((x or {}).get("city") if isinstance(x, dict) else None,
                     (x or {}).get("state") if isinstance(x, dict) else None)
        if m is None:
            raise PartnerError("Each city needs a US city and state, like Denver, CO.")
        row = {"city": m.city, "state": m.state}
        if row not in out:
            out.append(row)
    if len(out) > MAX_METROS:
        raise PartnerError(f"At most {MAX_METROS} cities.")
    return out


def clean(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise PartnerError("bad request")
    kind = body.get("kind") or "run_club"
    if kind not in KINDS:
        raise PartnerError("Pick a kind.")
    out = {
        "name": _text(body.get("name"), NAME_LEN, required="Add the partner's name."),
        "kind": kind,
        "tagline": _text(body.get("tagline"), TAGLINE_LEN),
        "description": _text(body.get("description"), DESC_LEN),
        "schedule": _text(body.get("schedule"), SCHEDULE_LEN),
        "website": _https(body.get("website"), "Website"),
        "instagram": _instagram(body.get("instagram")),
        "signup": _https(body.get("signup"), "Sign-up link"),
        "metros": _metros(body.get("metros")),
        "starts": _day(body.get("starts"), "Start date"),
        "ends": _day(body.get("ends"), "End date"),
        "active": body.get("active", True) is not False,
        "sponsored": body.get("sponsored", True) is not False,
    }
    if not (out["website"] or out["instagram"] or out["signup"]):
        raise PartnerError("Add a website, Instagram or sign-up link.")
    if out["starts"] and out["ends"] and out["ends"] < out["starts"]:
        raise PartnerError("The end date is before the start date.")
    return out


def live(item: dict[str, Any], today: date) -> bool:
    d = today.isoformat()
    return bool(item.get("active", True)) and (not item.get("starts") or item["starts"] <= d) \
        and (not item.get("ends") or d <= item["ends"])


def in_metro(item: dict[str, Any], city: str, state: str) -> bool:
    c, s = (city or "").strip().lower(), (state or "").strip().lower()
    return bool(c and s) and any(m.get("city", "").lower() == c and m.get("state", "").lower() == s
                                 for m in item.get("metros") or [])


def public(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "label": "Partner", "name": item["name"], "kind": item["kind"],
            "kind_label": KIND_LABEL.get(item["kind"], "Group"), "tagline": item.get("tagline") or "",
            "description": item.get("description") or "", "schedule": item.get("schedule") or "",
            "website": item.get("website") or "", "instagram": item.get("instagram") or "",
            "signup": item.get("signup") or "", "monogram": monogram(item["name"]),
            "sponsored": bool(item.get("sponsored", True))}


def sponsored_card(item: dict[str, Any], metro_label: str) -> dict[str, Any]:
    """A promotional card: always disclosed as sponsored, with the reason it shows."""
    near = metro_label or "your area"
    return {**public(item), "label": "Sponsored partner", "sponsored": True,
            "why": f"{item['name']} is a rabbt partner shown to people near {near}."}


# -------------------------------------------------------------- service --
class Partners:
    def __init__(self, store: Any, *, is_owner: Callable[[str], bool],
                 clock: Callable[[], float] = time.time) -> None:
        self._doc = store.global_doc("partners")
        self._is_owner = is_owner
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        self._seen_day = ""

    def _today(self) -> date:
        return date.fromtimestamp(self._clock())

    def _load(self) -> dict[str, Any]:
        d = self._doc.load()
        if isinstance(d, dict) and d.get("seeded"):
            return d

        def seed(doc: dict[str, Any]) -> dict[str, Any]:
            if not doc.get("seeded"):
                items = doc.setdefault("items", {})
                items.setdefault(SEED["id"], {**SEED, "created": int(self._clock()), "by": "seed"})
                doc["seeded"] = True
            return doc
        return dict(self._doc.update(seed))

    def require_owner(self, uid: str) -> None:
        if uid.startswith("coach_") or not self._is_owner(uid):
            raise PartnerError("Only the app owner can manage partners.", 403)

    # ------------------------------------------------------------ owner --
    def admin_list(self, uid: str) -> dict[str, Any]:
        self.require_owner(uid)
        d = self._load()
        today = self._today()
        since = (today - timedelta(days=STATS_DAYS - 1)).isoformat()
        rows = []
        for it in sorted((d.get("items") or {}).values(), key=lambda x: (-int(x.get("created") or 0), x.get("name", ""))):
            st = (d.get("stats") or {}).get(it["id"]) or {}
            days = {k: v for k, v in (st.get("days") or {}).items() if k >= since}
            totals = {k: sum(int((v or {}).get(k) or 0) for v in days.values()) for k in COUNT_KINDS}
            places = {pl: {k: sum(int((v or {}).get(f"{k}:{pl}") or 0) for v in days.values()) for k in PLACE_KINDS}
                      for pl in PLACEMENTS}
            places = {pl: c for pl, c in places.items() if any(c.values())}
            rows.append({**public(it), "metros": it.get("metros") or [], "starts": it.get("starts"),
                         "placements": places,
                         "ends": it.get("ends"), "active": bool(it.get("active", True)), "live": live(it, today),
                         "stats": totals})
        return {"partners": rows, "kinds": [{"id": k, "label": KIND_LABEL[k]} for k in KINDS],
                "stats_days": STATS_DAYS, "placements": list(PLACEMENTS)}

    def save(self, uid: str, body: Any, pid: str | None = None) -> dict[str, Any]:
        self.require_owner(uid)
        row = clean(body)
        self._load()
        now = int(self._clock())

        def put(d: dict[str, Any]) -> str:
            items = d.setdefault("items", {})
            if pid is None:
                if len(items) >= MAX_PARTNERS:
                    raise PartnerError(f"At most {MAX_PARTNERS} partners. Remove one first.", 409)
                new = "p" + hashlib.sha256(f"{row['name']}|{now}|{len(items)}".encode()).hexdigest()[:10]
                items[new] = {**row, "id": new, "created": now, "by": uid}
                return new
            if not isinstance(pid, str) or pid not in items:
                raise PartnerError("not found", 404)
            items[pid] = {**items[pid], **row, "id": pid, "updated": now}
            return pid
        out = self._doc.update(put)
        return {"id": out, **self.admin_list(uid)}

    def remove(self, uid: str, pid: Any) -> dict[str, Any]:
        self.require_owner(uid)
        self._load()

        def put(d: dict[str, Any]) -> None:
            items = d.setdefault("items", {})
            if not isinstance(pid, str) or pid not in items:
                raise PartnerError("not found", 404)
            del items[pid]
            (d.get("stats") or {}).pop(pid, None)
        self._doc.update(put)
        return self.admin_list(uid)

    # ---------------------------------------------------------- viewers --
    def near(self, city: str, state: str, *, query: str | None = None, limit: int = SHOW_MAX) -> list[dict[str, Any]]:
        """Live partners for this home metro; with ``query`` only the relevant ones (named, or
        the query is about that kind of group). Labelled "Partner" (``public``)."""
        d = self._load()
        today = self._today()
        rows = [it for it in (d.get("items") or {}).values()
                if isinstance(it, dict) and live(it, today) and in_metro(it, city, state)]
        if query is not None:
            rows = [it for it in rows if name_match(query, it.get("name")) or about_kind(query, it.get("kind", "other"))]
        # Fair order: rotate by local day so each partner leads in turn.
        rows.sort(key=lambda x: (int(x.get("created") or 0), x["id"]))
        if rows:
            k = today.toordinal() % len(rows)
            rows = rows[k:] + rows[:k]
        return [public(it) for it in rows[:limit]]

    def get(self, pid: Any, city: str, state: str, zips: list[Any] | None = None) -> dict[str, Any]:
        if not isinstance(pid, str) or not (_PID.match(pid) or pid == SEED["id"]):
            raise PartnerError("not found", 404)
        it = (self._load().get("items") or {}).get(pid)
        if not isinstance(it, dict) or not live(it, self._today()) \
                or not any(in_metro(it, c, st) for c, st in self.metros_for(city, state, zips)):
            raise PartnerError("not found", 404)
        return public(it)

    # -------------------------------------------------------- sponsored --
    @staticmethod
    def _who(uid: str) -> str:
        return hashlib.sha256(f"hide|{uid}".encode()).hexdigest()[:20]

    def metros_for(self, city: str, state: str, zips: list[Any] | None = None) -> list[tuple[str, str]]:
        """The metros this person is "near": their area's city plus any zip they set or searched."""
        out: list[tuple[str, str]] = []
        if city and state:
            out.append((city, state))
        for z in zips or []:
            m = zip_metro(z)
            if m and m not in out:
                out.append(m)
        return out

    def sponsored(self, uid: str, placement: Any, city: str, state: str,
                  zips: list[Any] | None = None) -> dict[str, Any] | None:
        """One sponsored card for this screen, or None (not in a partner metro, hidden, none live)."""
        if placement not in PLACEMENTS:
            raise PartnerError("bad placement")
        if uid.startswith("coach_"):
            return None
        d = self._load()
        today = self._today()
        hidden = ((d.get("hides") or {}).get(self._who(uid)) or {}).get(placement)
        if isinstance(hidden, str) and hidden >= (today - timedelta(days=HIDE_DAYS - 1)).isoformat():
            return None
        metros = self.metros_for(city, state, zips)
        rows = [(it, m) for it in (d.get("items") or {}).values() for m in metros
                if isinstance(it, dict) and it.get("sponsored", True) and live(it, today) and in_metro(it, *m)]
        if not rows:
            return None
        rows.sort(key=lambda x: (int(x[0].get("created") or 0), x[0]["id"]))
        k = today.toordinal() % len(rows)  # fair rotation, one card at a time
        it, (c, st) = rows[k]
        return sponsored_card(it, f"{c}, {st}")

    def hide(self, uid: str, pid: Any, placement: Any) -> None:
        if placement not in PLACEMENTS:
            raise PartnerError("bad placement")
        if not isinstance(pid, str) or not (_PID.match(pid) or pid == SEED["id"]):
            raise PartnerError("not found", 404)
        today = self._today().isoformat()
        who = self._who(uid)
        cutoff = (self._today() - timedelta(days=HIDE_DAYS)).isoformat()

        def put(d: dict[str, Any]) -> None:
            hides = d.setdefault("hides", {})
            mine = hides.setdefault(who, {})
            mine[placement] = today
            for w in [w for w, v in hides.items() if not any(x >= cutoff for x in (v or {}).values())]:
                del hides[w]
        self._doc.update(put)
        self._bump(uid, pid, f"hide:{placement}")

    def placement_count(self, uid: str, pid: Any, what: Any, placement: Any) -> bool:
        """An anonymous impression or tap for one placement (deduped per person, partner, day)."""
        if what not in ("impression", "tap") or placement not in PLACEMENTS:
            raise PartnerError("bad request")
        if not isinstance(pid, str) or pid not in (self._load().get("items") or {}):
            raise PartnerError("not found", 404)
        return self._bump(uid, pid, f"{what}:{placement}")

    def _bump(self, uid: str, pid: str, key: str) -> bool:
        today = self._today().isoformat()
        tag = hashlib.sha256(f"{today}|{uid}|{pid}|{key}".encode()).hexdigest()[:16]
        with self._lock:
            if self._seen_day != today:
                self._seen, self._seen_day = set(), today
            if tag in self._seen:
                return False
            self._seen.add(tag)
        since = (self._today() - timedelta(days=STATS_DAYS + 7)).isoformat()

        def put(d: dict[str, Any]) -> None:
            days = d.setdefault("stats", {}).setdefault(pid, {}).setdefault("days", {})
            day = days.setdefault(today, {})
            day[key] = int(day.get(key) or 0) + 1
            for k in [k for k in days if k < since]:
                del days[k]
        self._doc.update(put)
        return True

    def count(self, uid: str, pid: Any, what: Any, city: str, state: str,
              zips: list[Any] | None = None) -> bool:
        """One anonymous count (view / website / instagram / signup / interested). Each person at
        most once per partner, kind and day; only ids of partners this person can see."""
        if what not in COUNT_KINDS:
            raise PartnerError("bad request")
        self.get(pid, city, state, zips)
        today = self._today().isoformat()
        tag = hashlib.sha256(f"{today}|{uid}|{pid}|{what}".encode()).hexdigest()[:16]
        with self._lock:
            if self._seen_day != today:
                self._seen, self._seen_day = set(), today
            if tag in self._seen:
                return False
            self._seen.add(tag)
        since = (self._today() - timedelta(days=STATS_DAYS + 7)).isoformat()

        def put(d: dict[str, Any]) -> None:
            st = d.setdefault("stats", {}).setdefault(str(pid), {})
            days = st.setdefault("days", {})
            day = days.setdefault(today, {})
            day[what] = int(day.get(what) or 0) + 1
            for k in [k for k in days if k < since]:
                del days[k]
        self._doc.update(put)
        return True


__all__ = ["KINDS", "KIND_LABEL", "PLACEMENTS", "PartnerError", "Partners", "SEED", "about_kind", "clean",
           "key_words", "monogram", "name_match", "sponsored_card", "zip_metro"]
