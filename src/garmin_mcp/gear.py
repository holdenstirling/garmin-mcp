"""Gear garage: shoes, bikes, wetsuits and the rest, with mileage and retirement alerts.

Items live in the per-user encrypted ``gear`` doc. Mileage is computed, never stored:
``start_km`` plus the activities since the item was added that are tagged to it
(``activity_ids``), or untagged ones whose stats category is in its ``default_for``. Items
imported from Garmin (``garmin_uuid``) prefer Garmin's own total from ``get_gear_stats``.
Activities come from ``StatsService.activities`` (the cached year), so the garage adds
no Garmin activity reads.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import date
from typing import Any

from .appstore import AppStore
from .coaching import CoachError
from .stats import category

KINDS = ("shoes", "bike", "wetsuit", "watch", "power_meter", "helmet", "other")
BIKE_TYPES = ("road", "tri", "gravel", "mtb", "indoor")
SHOE_TYPES = ("road", "trail", "track", "racing")
# Stats categories (stats.category) an item can be used for or be the default for.
SPORTS = ("run", "bike", "swim", "hike", "climb", "ski", "paddle", "strength", "other")
DEFAULT_ALERT_KM: dict[str, float | None] = {"shoes": 640.0}  # ~400 mi
DEFAULT_SPORT = {"shoes": "run", "bike": "bike", "wetsuit": "swim"}
MAX_ITEMS = 60
MAX_TAGGED = 500
MAX_KM = 100_000.0
SOON_PCT = 80
NEW_SHOE_KM = 30.0
UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")

SHOE_BRANDS = sorted({
    "Hoka", "Nike", "Brooks", "ASICS", "Saucony", "New Balance", "On", "Altra", "Adidas", "Salomon",
    "La Sportiva", "Mizuno", "Puma", "Topo Athletic", "Inov-8", "Merrell", "Scott", "Norda", "Craft",
    "Under Armour", "Diadora", "Karhu", "Saysh", "Newton", "Skechers", "Reebok", "Arc'teryx",
    "The North Face", "VJ", "Dynafit", "Mount to Coast", "Speedland", "Xero", "Vivobarefoot",
    "Joe Nimble", "Kailas", "Li-Ning", "Anta", "361°", "Kiprun (Decathlon)", "Tracksmith", "Veja",
    "Allbirds", "Columbia", "Icebug", "Hylo", "Xtep", "Peak", "Mammut",
}, key=str.lower)
BIKE_BRANDS = sorted({
    "Specialized", "Trek", "Cannondale", "Canyon", "Cervélo", "Giant", "Liv", "Pinarello", "BMC", "Scott",
    "Felt", "Quintana Roo", "Santa Cruz", "Yeti", "Orbea", "Factor", "Ventum", "Bianchi", "Colnago",
    "Lauf", "Allied", "Enve", "Argon 18", "Ribble", "Wilier", "Look", "Time", "Ridley", "Merida", "Cube",
    "Focus", "Lapierre", "Niner", "Salsa", "Surly", "Kona", "Rocky Mountain", "Pivot", "Ibis",
    "Transition", "Juliana", "Marin", "Diamondback", "GT", "Fuji", "Polygon", "3T", "Open", "Chapter2",
    "Cervelo", "De Rosa", "Storck", "Rose", "Van Rysel (Decathlon)", "Wahoo KICKR Bike", "Tacx",
}, key=str.lower)
BIKE_BRANDS = [b for b in BIKE_BRANDS if b != "Cervelo"]  # keep the accented spelling only
WETSUIT_BRANDS = ["Orca", "Roka", "Zone3", "Huub", "Blueseventy", "Xterra", "2XU", "Synergy", "Sailfish",
                  "Aqua Sphere", "Dare2Tri", "Deboer"]
WATCH_BRANDS = ["Garmin", "COROS", "Polar", "Suunto", "Apple", "Wahoo", "Samsung", "Amazfit"]
POWER_BRANDS = ["Garmin", "Favero", "SRM", "Quarq", "Stages", "4iiii", "Power2Max", "Rotor", "Wahoo",
                "Shimano", "Stryd"]
HELMET_BRANDS = ["Giro", "Specialized", "POC", "Kask", "Bell", "MET", "Lazer", "Smith", "Abus", "Rudy Project",
                 "Oakley", "Scott", "Trek (Bontrager)"]
BRANDS: dict[str, list[str]] = {"shoes": SHOE_BRANDS, "bike": BIKE_BRANDS, "wetsuit": WETSUIT_BRANDS,
                                "watch": WATCH_BRANDS, "power_meter": POWER_BRANDS, "helmet": HELMET_BRANDS}


def _half(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:.1f}"


SHOE_SIZES = [f"US {_half(4 + i / 2)}" for i in range(25)] + [f"EU {n}" for n in range(35, 51)]
APPAREL_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
BIKE_SIZES = APPAREL_SIZES + [f"{n} cm" for n in range(44, 65)]
SIZES: dict[str, list[str]] = {"shoes": SHOE_SIZES, "bike": BIKE_SIZES,
                               "wetsuit": ["XS", "S", "SM", "MS", "M", "MT", "ML", "L", "LT", "XL", "XXL"],
                               "helmet": ["S", "M", "L", "XL"]}

# Garmin gearTypeName -> kind
GARMIN_KINDS = {"shoes": "shoes", "bike": "bike", "bicycle": "bike", "watch": "watch", "wetsuit": "wetsuit",
                "power meter": "power_meter", "helmet": "helmet"}
TEXT_LIMITS = {"brand": 60, "model": 60, "nickname": 60, "size": 20, "notes": 300}


class GearError(CoachError):
    """Validation error whose message is safe to show the user."""


def catalog() -> dict[str, Any]:
    return {"kinds": list(KINDS), "brands": BRANDS, "sizes": SIZES, "bike_types": list(BIKE_TYPES),
            "shoe_types": list(SHOE_TYPES), "sports": list(SPORTS), "default_alert_km": DEFAULT_ALERT_KM,
            "max_items": MAX_ITEMS}


# ------------------------------------------------------------- validation --
def _text(v: Any, field: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise GearError(f"{field.capitalize()} must be text.")
    v = " ".join(v.split()) if field != "notes" else v.strip()
    if len(v) > TEXT_LIMITS[field]:
        raise GearError(f"{field.capitalize()} can be at most {TEXT_LIMITS[field]} characters.")
    return v


def _km(v: Any, field: str, *, allow_none: bool) -> float | None:
    if v is None or v == "":
        if allow_none:
            return None
        return 0.0
    if isinstance(v, bool) or not isinstance(v, int | float) or v != v:
        raise GearError(f"{field} must be a number.")
    lo = 0 if field == "Starting distance" else 1
    if not lo <= v <= MAX_KM:
        raise GearError(f"{field} must be between {lo} and {int(MAX_KM):,} km.")
    return round(float(v), 1)


def _sports(v: Any, field: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > len(SPORTS):
        raise GearError(f"{field} must be a list of sports.")
    out: list[str] = []
    for s in v:
        if s not in SPORTS:
            raise GearError(f"Unknown sport in {field.lower()}: {str(s)[:20]!r}.")
        if s not in out:
            out.append(s)
    return out


def _day(v: Any, field: str, today: date) -> str:
    if not isinstance(v, str):
        raise GearError(f"{field} must be a date (YYYY-MM-DD).")
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        raise GearError(f"{field} must be a date (YYYY-MM-DD).") from None
    if d > today:
        raise GearError(f"{field} can't be in the future.")
    if d.year < 1990:
        raise GearError(f"{field} looks too far back.")
    return d.isoformat()


def clean(body: dict[str, Any], today: date, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a create (``current`` None) or a patch; returns the full new item."""
    if not isinstance(body, dict):
        raise GearError("Send gear as an object.")
    item: dict[str, Any] = dict(current or {})
    if current is None:
        kind = body.get("kind")
        if kind not in KINDS:
            raise GearError(f"Kind must be one of: {', '.join(KINDS)}.")
        item = {"id": "g" + secrets.token_hex(5), "kind": kind, "brand": "", "model": "", "nickname": "",
                "size": "", "bike_type": None, "shoe_type": None,
                "sports": [DEFAULT_SPORT[kind]] if kind in DEFAULT_SPORT else [],
                "default_for": [], "start_km": 0.0, "alert_km": DEFAULT_ALERT_KM.get(kind),
                "added": today.isoformat(), "retired": False, "retired_on": None, "notes": "",
                "garmin_uuid": None, "activity_ids": []}
    elif "kind" in body and body["kind"] != item["kind"]:
        if body["kind"] not in KINDS:
            raise GearError(f"Kind must be one of: {', '.join(KINDS)}.")
        item["kind"] = body["kind"]
    for f in TEXT_LIMITS:
        if f in body:
            item[f] = _text(body[f], f)
    if "bike_type" in body:
        if body["bike_type"] not in (None, *BIKE_TYPES):
            raise GearError(f"Bike type must be one of: {', '.join(BIKE_TYPES)}.")
        item["bike_type"] = body["bike_type"]
    if "shoe_type" in body:
        if body["shoe_type"] not in (None, *SHOE_TYPES):
            raise GearError(f"Shoe type must be one of: {', '.join(SHOE_TYPES)}.")
        item["shoe_type"] = body["shoe_type"]
    if item["kind"] != "bike":
        item["bike_type"] = None
    if item["kind"] != "shoes":
        item["shoe_type"] = None
    if "sports" in body:
        item["sports"] = _sports(body["sports"], "Sports")
    if "default_for" in body:
        item["default_for"] = _sports(body["default_for"], "Default for")
    if "start_km" in body:
        item["start_km"] = _km(body["start_km"], "Starting distance", allow_none=False)
    if "alert_km" in body:
        item["alert_km"] = _km(body["alert_km"], "Retirement distance", allow_none=True)
    if "added" in body:
        item["added"] = _day(body["added"], "Date added", today)
    if "activity_ids" in body:
        ids = body["activity_ids"]
        if not isinstance(ids, list) or len(ids) > MAX_TAGGED or \
                any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in ids):
            raise GearError("Tagged activities must be a list of activity ids.")
        item["activity_ids"] = list(dict.fromkeys(ids))
    if "retired" in body:
        if not isinstance(body["retired"], bool):
            raise GearError("Retired must be true or false.")
        if body["retired"] and not item.get("retired"):
            item["retired_on"] = today.isoformat()
        elif not body["retired"]:
            item["retired_on"] = None
        item["retired"] = body["retired"]
    for k in item["default_for"]:
        if k not in item["sports"]:
            item["sports"].append(k)
    if not (item["brand"] or item["model"] or item["nickname"]):
        raise GearError("Give it a brand, model or nickname.")
    return item


# ---------------------------------------------------------------- mileage --
def _legs(acts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Activities that carry distance: multisport legs count, their parent doesn't."""
    out = []
    for a in acts:
        if (a.get("multisport") or {}).get("is_parent"):
            continue
        try:
            d = date.fromisoformat(str(a.get("date") or "")[:10])
        except ValueError:
            continue
        out.append({"id": a.get("activity_id"), "date": d.isoformat(), "sport": category(a.get("sport")),
                    "km": float(a.get("distance_km") or 0)})
    return out


def usage(items: list[dict[str, Any]], acts: list[dict[str, Any]],
          garmin_stats: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Each item plus total_km, activities, last_used, pct_of_alert and status."""
    legs = _legs(acts)
    garmin_stats = garmin_stats or {}
    tagged_to: dict[Any, str] = {}
    for it in items:
        for aid in it.get("activity_ids") or []:
            tagged_to.setdefault(aid, it["id"])
    out = []
    for it in items:
        start, end = it.get("added") or "0000", (it.get("retired_on") if it.get("retired") else None) or "9999"
        km, n, last = 0.0, 0, None
        defaults = set(it.get("default_for") or [])
        for r in legs:
            if not start <= r["date"] <= end:
                continue
            owner = tagged_to.get(r["id"])
            if owner == it["id"] or (owner is None and r["sport"] in defaults):
                km += r["km"]
                n += 1
                last = max(last or r["date"], r["date"])
        source = "rabbit"
        g = garmin_stats.get(it.get("garmin_uuid") or "")
        if g and isinstance(g.get("totalDistance"), int | float):
            km = float(g["totalDistance"]) / 1000
            if isinstance(g.get("totalActivities"), int):
                n = g["totalActivities"]
            source = "garmin"
        total = round(float(it.get("start_km") or 0) + km, 1)
        alert = it.get("alert_km")
        pct = round(100 * total / alert) if alert else None
        status = "ok" if pct is None or pct < SOON_PCT else "soon" if pct < 100 else "retire"
        out.append({**it, "total_km": total, "activities": n, "last_used": last, "pct_of_alert": pct,
                    "status": status, "source": source})
    order = {k: i for i, k in enumerate(KINDS)}
    out.sort(key=lambda x: (x["retired"], order.get(x["kind"], 99), -(x["total_km"] or 0)))
    return out


# ------------------------------------------------------------ Garmin import --
def from_garmin(g: dict[str, Any], defaults: dict[str, list[str]]) -> dict[str, Any] | None:
    """One Garmin gear record -> a patch for a Rabbit item (None when unusable)."""
    uuid = g.get("uuid")
    if not isinstance(uuid, str) or not UUID_RE.match(uuid):
        return None
    tname = str(g.get("gearTypeName") or "").strip().lower()
    kind = GARMIN_KINDS.get(tname, "other")
    s = lambda k, n: (g.get(k) if isinstance(g.get(k), str) else "").strip()[:n]  # noqa: E731
    brand = s("gearMakeName", 60)
    if brand.lower() in ("other", "unknown"):
        brand = ""
    model = s("gearModelName", 60)
    if model.lower() in ("other", "unknown"):
        model = ""
    custom = s("customMakeModel", 60)
    if not model and custom:
        model = custom
    nickname = s("displayName", 60)
    if not (brand or model or nickname):
        nickname = {"shoes": "Shoes", "bike": "Bike"}.get(kind, "Gear")
    patch: dict[str, Any] = {"kind": kind, "brand": brand, "model": model, "nickname": nickname,
                             "garmin_uuid": uuid,
                             "retired": str(g.get("gearStatusName") or "").lower() == "retired"}
    mx = g.get("maximumMeters")
    if isinstance(mx, int | float) and 1000 <= mx <= MAX_KM * 1000:
        patch["alert_km"] = round(mx / 1000, 1)
    begin = g.get("dateBegin")
    if isinstance(begin, str) and len(begin) >= 10:
        patch["added"] = begin[:10]
    if defaults.get(uuid):
        patch["default_for"] = [x for x in defaults[uuid] if x in SPORTS]
    return patch


def garmin_defaults(raw: Any) -> dict[str, list[str]]:
    """``get_gear_defaults`` -> {gear uuid: [sports]}, tolerant of its loose shape."""
    out: dict[str, list[str]] = {}
    rows = raw if isinstance(raw, list) else (raw or {}).get("activityTypes") if isinstance(raw, dict) else None
    for r in rows or []:
        if not isinstance(r, dict) or r.get("defaultGear") is False:
            continue
        uuid = r.get("uuid") or r.get("gearUUID") or r.get("gearPk")
        tkey = r.get("typeKey") or r.get("activityTypeKey") or r.get("activityTypeName")
        if isinstance(uuid, str) and isinstance(tkey, str):
            sp = category(tkey)
            if sp not in out.setdefault(uuid, []):
                out[uuid].append(sp)
    return out


class GearStore:
    def __init__(self, store: AppStore, *, today: Callable[[str], date]) -> None:
        self._s = store
        self._today = today

    def _doc(self, user_id: str):
        return self._s.user_doc(user_id, "gear")

    def list(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._doc(user_id).load().get("items") or [])

    @staticmethod
    def _one_default(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
        """A sport has one default per kind among active items: the newest claim wins."""
        if item.get("retired"):
            item["default_for"] = []
            return
        for o in items:
            if o["id"] != item["id"] and o["kind"] == item["kind"] and not o.get("retired"):
                o["default_for"] = [s for s in o.get("default_for") or [] if s not in item["default_for"]]

    def create(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        today = self._today(user_id)
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if k not in ("id", "garmin_uuid", "retired_on")}
        item = clean(body, today)

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            items = d.setdefault("items", [])
            if len(items) >= MAX_ITEMS:
                raise GearError(f"Your garage is full ({MAX_ITEMS} items). Delete something you no longer use.")
            if "default_for" not in body and item["kind"] in DEFAULT_SPORT and not any(
                    o["kind"] == item["kind"] and not o.get("retired") for o in items):
                item["default_for"] = [DEFAULT_SPORT[item["kind"]]]
            self._one_default(items, item)
            items.append(item)
            return item
        return self._doc(user_id).update(apply)

    def update(self, user_id: str, gear_id: str, body: dict[str, Any]) -> dict[str, Any]:
        today = self._today(user_id)
        if not isinstance(body, dict):
            raise GearError("Send gear as an object.")
        body = {k: v for k, v in body.items() if k not in ("id", "garmin_uuid", "retired_on")}

        def apply(d: dict[str, Any]) -> dict[str, Any]:
            items = d.setdefault("items", [])
            for i, cur in enumerate(items):
                if cur["id"] == gear_id:
                    new = clean(body, today, cur)
                    self._one_default(items, new)
                    items[i] = new
                    return new
            raise GearError("That gear isn't in your garage.")
        return self._doc(user_id).update(apply)

    def retire(self, user_id: str, gear_id: str, retired: bool = True) -> dict[str, Any]:
        return self.update(user_id, gear_id, {"retired": retired})

    def delete(self, user_id: str, gear_id: str) -> None:
        def apply(d: dict[str, Any]) -> None:
            items = d.setdefault("items", [])
            keep = [x for x in items if x["id"] != gear_id]
            if len(keep) == len(items):
                raise GearError("That gear isn't in your garage.")
            d["items"] = keep
        self._doc(user_id).update(apply)

    def import_garmin(self, user_id: str, raw_gear: Any, raw_defaults: Any = None) -> dict[str, int]:
        """Create or update items from Garmin's gear list (matched by ``garmin_uuid``)."""
        today = self._today(user_id)
        rows = raw_gear if isinstance(raw_gear, list) else []
        defaults = garmin_defaults(raw_defaults)
        patches = [p for p in (from_garmin(g, defaults) for g in rows if isinstance(g, dict)) if p]

        def apply(d: dict[str, Any]) -> dict[str, int]:
            items = d.setdefault("items", [])
            by_uuid = {x.get("garmin_uuid"): i for i, x in enumerate(items) if x.get("garmin_uuid")}
            created = updated = skipped = 0
            for p in patches:
                uuid = p.pop("garmin_uuid")
                if p.get("added"):
                    try:
                        p["added"] = _day(p["added"], "Date added", today)
                    except GearError:
                        p.pop("added")
                if uuid in by_uuid:
                    i = by_uuid[uuid]
                    cur = items[i]
                    # Garmin owns identity and status; the athlete's own edits to size,
                    # notes and types stay.
                    keep_user = {k: v for k, v in p.items() if k != "added" and v != "" and
                                 not (k == "nickname" and cur.get("nickname"))}
                    try:
                        new = clean(keep_user, today, cur)
                    except GearError:
                        skipped += 1
                        continue
                    self._one_default(items, new)
                    items[i] = new
                    updated += 1
                    continue
                if len(items) >= MAX_ITEMS:
                    skipped += 1
                    continue
                try:
                    new = clean(p, today)
                except GearError:
                    skipped += 1
                    continue
                new["garmin_uuid"] = uuid
                if new["retired"]:
                    new["retired_on"] = today.isoformat()
                self._one_default(items, new)
                items.append(new)
                by_uuid[uuid] = len(items) - 1
                created += 1
            return {"created": created, "updated": updated, "skipped": skipped}
        return self._doc(user_id).update(apply)


# ------------------------------------------------------------- race pack --
RACE_KINDS = {"triathlon": ("shoes", "bike", "wetsuit"), "duathlon": ("shoes", "bike"),
              "running": ("shoes",), "trail": ("shoes",), "mountaineering": ("shoes",),
              "cycling": ("bike",), "swimming": ("wetsuit",), "other": ("shoes",)}


def for_race(views: list[dict[str, Any]], event_type: str, *, imperial: bool = False) -> list[dict[str, Any]]:
    """Active gear relevant to a race, with warnings (worn-out or brand-new shoes)."""
    kinds = RACE_KINDS.get(event_type, RACE_KINDS["other"])
    unit, f = ("mi", 0.621371) if imperial else ("km", 1.0)
    out = []
    for it in views:
        if it.get("retired") or it.get("kind") not in kinds:
            continue
        warn = None
        if it["kind"] == "shoes":
            if (it.get("pct_of_alert") or 0) >= SOON_PCT:
                warn = (f"{round(it['total_km'] * f):,} {unit} on these ({it['pct_of_alert']}% of their life). "
                        "Race in a fresher pair you've already broken in.")
            elif it["total_km"] < NEW_SHOE_KM:
                warn = "New shoes on race day: break them in with a few runs first."
        name = " ".join(x for x in (it.get("brand"), it.get("model")) if x) or it.get("nickname") or it["kind"]
        out.append({"id": it["id"], "kind": it["kind"], "name": name, "nickname": it.get("nickname") or "",
                    "total_km": it["total_km"], "pct_of_alert": it.get("pct_of_alert"), "status": it["status"],
                    "is_default": bool(it.get("default_for")), "warning": warn})
    out.sort(key=lambda x: (kinds.index(x["kind"]), not x["is_default"]))
    return out[:8]


__all__ = ["GearStore", "GearError", "catalog", "clean", "usage", "from_garmin", "garmin_defaults", "for_race",
           "KINDS", "SHOE_BRANDS", "BIKE_BRANDS", "WETSUIT_BRANDS", "WATCH_BRANDS", "SHOE_SIZES", "BIKE_SIZES"]
