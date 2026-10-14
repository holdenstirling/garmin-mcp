"""Find a coach: a small curated directory of human coaches.

The list lives in the global ``coach_directory`` doc, seeded from ``SEED_COACHES`` on first
read so the operator can edit it later without a deploy. Seed entries hold only facts
verified from the coach's own website; don't add claims that aren't there.

Rabbit doesn't take a cut and doesn't contact coaches: the athlete reaches out themselves
(email, phone, website). ``rabbit_user_email`` (optional, never sent to the browser) is the
coach's Google login when they use Rabbit; it enables "Invite as my coach", which goes
through the normal ``CoachLinks.invite``.

Matching is deterministic: the athlete's main race type/distance, favorite sports and home
location against each coach's sports, specialties and location, with a one-line "why".
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .appstore import AppStore
from .coaching import CoachError

SEED_VERSION = 1
SEED_COACHES: list[dict[str, Any]] = [
    {
        "id": "bill-ludington",
        "name": "Bill Ludington",
        "business": "Bigdog Coaching",
        "location": "Golden, Colorado",
        "photo_url": None,
        "sports": ["triathlon", "running", "cycling", "swimming", "strength"],
        "specialties": ["Triathlon", "70.3 & Ironman", "Strength & functional fitness"],
        "credentials": ["Ironman-U certified coach", "ACE certified trainer",
                        "Ironman World Championship qualifier"],
        "bio": ("Golden, Colorado triathlon coach (Ironman-U and ACE certified) building custom "
                "training plans and lifestyle guidance, from first 70.3s to Ironman age-group podiums."),
        "highlights": [
            "Ironman Texas 2021: 1st AG 25-29, 8th overall, Kona qualifier",
            "Texas 70.3 2022: 2nd M50-54",
            "Victoria 70.3 2022: 4th M55-59",
            "Napa 70.3 2021: two age-group wins",
        ],
        "testimonial": {"quote": "Bill has taken me from nothing to multiple age group wins.",
                        "by": "Ian, Denver, CO"},
        "services": ["Custom training plans and lifestyle advice"],
        "pricing_note": "Contact for pricing",
        "contact": {"email": "bill.ludington@gmail.com", "phone": "(720) 480-5749",
                    "website": "https://bigdogcoaching.com"},
        "accepting": True,
        "verified_by_operator": True,
        "rabbit_user_email": None,
    },
]

SPORTS = ("triathlon", "running", "cycling", "swimming", "strength")
SPORT_LABEL = {"triathlon": "triathlon", "running": "running", "cycling": "cycling",
               "swimming": "swimming", "strength": "strength"}
# Athlete favorite sports (coaching._FAVORITES) -> directory sport tags.
_FAV_SPORT = {"run": "running", "trail": "running", "bike": "cycling", "gravel": "cycling",
              "mtb": "cycling", "swim": "swimming", "open_water": "swimming", "strength": "strength"}
# Event types (events.py) -> directory sport tags.
_EVENT_SPORT = {"triathlon": ["triathlon"], "running": ["running"], "trail": ["running"],
                "cycling": ["cycling"], "swimming": ["swimming"], "duathlon": ["running", "cycling"]}
_LONG_TRI = re.compile(r"70\.3|140\.6|ironman|half[- ]iron|long[- ]course", re.I)
_TRI = re.compile(r"triathlon|\btri\b|70\.3|140\.6|ironman", re.I)
# Fields the browser gets (rabbit_user_email stays server-side).
PUBLIC = ("id", "name", "business", "location", "photo_url", "sports", "specialties", "credentials",
          "bio", "highlights", "testimonial", "services", "pricing_note", "contact", "accepting",
          "verified_by_operator")
# "Near you" distances (miles) and the coach formats the app filters on.
DISTANCES_MI = (10, 25, 50)
FORMATS = ("any", "in_person", "remote")
SCOPES = ("local", "remote")
KM_PER_MI = 1.609344


def remote_of(c: dict[str, Any]) -> bool | None:
    """True/False only when the operator recorded it; unknown stays None (never claimed)."""
    v = c.get("remote")
    return v if isinstance(v, bool) else None


def public_view(c: dict[str, Any]) -> dict[str, Any]:
    out = {k: copy.deepcopy(c.get(k)) for k in PUBLIC}
    out["can_invite"] = bool(c.get("rabbit_user_email"))
    out["remote"] = remote_of(c)
    return out


def coach_place(c: dict[str, Any]) -> dict[str, str]:
    """{"city", "state"} from the entry (``city``/``state`` fields, else "Golden, Colorado")."""
    from .geo import parse_home, state_code
    if c.get("city") and c.get("state"):
        return {"city": str(c["city"])[:60], "state": state_code(c["state"]) or str(c["state"])[:40]}
    p = parse_home(str(c.get("location") or ""))
    return {"city": p["city"], "state": p["state"]}


def coach_coords(c: dict[str, Any]) -> tuple[float, float] | None:
    """Coordinates the operator stored on the entry (``lat``/``lon``), if any."""
    lat, lon = c.get("lat"), c.get("lon")
    if isinstance(lat, int | float) and isinstance(lon, int | float) and not isinstance(lat, bool) \
            and -90 <= lat <= 90 and -180 <= lon <= 180:
        return float(lat), float(lon)
    return None


def distance_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    from .local import distance_km
    return distance_km(a[0], a[1], b[0], b[1]) / KM_PER_MI


def distance_label(mi: float) -> str:
    """"~15 mi from you": coarse on purpose (city centroids, and it mustn't pinpoint anyone)."""
    if mi < 5:
        return "Under 5 mi from you"
    step = 5 if mi < 100 else 25
    return f"~{int(round(mi / step) * step)} mi from you"


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def match(coach: dict[str, Any], athlete: dict[str, Any], race: dict[str, Any] | None) -> dict[str, Any]:
    """Score (higher is better) and a one-line "why" for this athlete.

    ``race``: the athlete's main race ({"name", "type", "distance"}) or None."""
    sports = set(coach.get("sports") or [])
    specs = " ".join(coach.get("specialties") or [])
    score, why = 0, None
    if race:
        kind = str(race.get("type") or "").lower()
        text = f"{race.get('name') or ''} {race.get('distance') or ''} {kind}"
        name = str(race.get("name") or "your race")[:60]
        race_sports = _EVENT_SPORT.get(kind, []) or (["triathlon"] if _TRI.search(text) else [])
        if _LONG_TRI.search(text) and _LONG_TRI.search(specs) and "triathlon" in sports:
            score += 6
            why = f"Coaches 70.3 & Ironman: fits your {name}"
        elif race_sports and all(s in sports for s in race_sports):
            score += 4
            why = f"Coaches {_join([SPORT_LABEL[s] for s in race_sports])}: fits your {name}"
    favs = {_FAV_SPORT[f] for f in (athlete.get("favorite_sports") or []) if f in _FAV_SPORT}
    shared = [s for s in SPORTS if s in favs and s in sports]
    score += len(shared)
    if why is None and shared:
        why = f"Coaches {_join([SPORT_LABEL[s] for s in shared])}, like you"
    home = str(athlete.get("home_location") or "").lower()
    loc = [p.strip().lower() for p in str(coach.get("location") or "").split(",") if p.strip()]
    if home and loc and any(re.search(rf"\b{re.escape(p)}\b", home) for p in loc):
        score += 1
        if why is None:
            why = f"Based in {coach.get('location')}, near you"
    if why is None:
        why = "Coaches " + _join(coach.get("specialties") or ["endurance sports"]).lower()
    if not coach.get("accepting", True):
        score -= 10
    return {"score": score, "why": why}


class CoachDirectory:
    def __init__(self, store: AppStore) -> None:
        self._doc = store.global_doc("coach_directory")

    def all(self) -> list[dict[str, Any]]:
        """Every entry; seeds the doc on first use (the operator can edit it afterwards)."""
        d = self._doc.load()
        if "coaches" in d:
            return list(d["coaches"])

        def apply(doc: dict[str, Any]) -> list[dict[str, Any]]:
            if "coaches" not in doc:
                doc["coaches"] = copy.deepcopy(SEED_COACHES)
                doc["seed_version"] = SEED_VERSION
            return list(doc["coaches"])
        return self._doc.update(apply)

    def get(self, coach_id: str) -> dict[str, Any]:
        for c in self.all():
            if c.get("id") == coach_id:
                return c
        raise CoachError("coach not found")

    def search(self, athlete: dict[str, Any], race: dict[str, Any] | None, *,
               sport: str | None = None, q: str | None = None, scope: str | None = None,
               fmt: str | None = None, within_mi: int | None = None,
               origin: tuple[float, float] | None = None,
               coords: dict[str, tuple[float, float] | None] | None = None,
               home_state: str = "") -> list[dict[str, Any]]:
        """``scope`` "local": coaches within ``within_mi`` of ``origin`` (the athlete's saved
        location; coach coordinates from ``coords`` by id, city centroids) or, without an
        origin, in ``home_state``. "remote": everyone except coaches recorded as in-person
        only. ``fmt`` "remote" keeps only coaches recorded as coaching remotely. Each result
        gets ``distance_label`` ("~15 mi from you") when both ends are known; the athlete's
        own location never leaves the server."""
        sport = (sport or "").strip().lower() or None
        if sport and sport not in SPORTS:
            raise CoachError(f"sport must be one of {', '.join(SPORTS)}")
        if scope not in (None, "", *SCOPES):
            raise CoachError("scope must be local or remote")
        if fmt not in (None, "", *FORMATS):
            raise CoachError("format must be any, in_person or remote")
        if within_mi is not None and within_mi not in DISTANCES_MI:
            raise CoachError(f"distance must be one of {', '.join(map(str, DISTANCES_MI))} mi")
        coords = coords or {}
        words = [w for w in (q or "").lower().split() if w][:6]
        out = []
        for c in self.all():
            if sport and sport not in (c.get("sports") or []):
                continue
            if words:
                hay = " ".join([c.get("name", ""), c.get("business", ""), c.get("location", ""),
                                c.get("bio", ""), *(c.get("specialties") or []), *(c.get("sports") or [])]).lower()
                if not all(w in hay for w in words):
                    continue
            remote = remote_of(c)
            if fmt == "remote" and remote is not True:
                continue
            if scope == "remote" and remote is False:
                continue
            here = coords.get(c.get("id") or "") or coach_coords(c)
            mi = distance_mi(origin, here) if origin and here else None
            if scope == "local":
                if origin is not None:
                    if mi is None or mi > (within_mi or 50):
                        continue
                elif not home_state or coach_place(c)["state"] != home_state:
                    continue
            view = public_view(c) | {"match": match(c, athlete, race)}
            view["distance_label"] = distance_label(mi) if mi is not None else None
            view["_mi"] = mi
            out.append(view)
        out.sort(key=lambda c: ((c["_mi"] if scope == "local" and c["_mi"] is not None else 0),
                                -c["match"]["score"], c["name"]))
        for c in out:
            c.pop("_mi", None)
        return out


__all__ = ["CoachDirectory", "DISTANCES_MI", "FORMATS", "SCOPES", "SEED_COACHES", "SPORTS", "coach_coords",
           "coach_place", "distance_label", "distance_mi", "match", "public_view", "remote_of"]
