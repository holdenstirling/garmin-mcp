"""How the athlete wants to use Rabbit ("What brings you to Rabbit?").

``athlete.intents`` is a short list of ids in priority order (the order they were tapped):

* ``train``       Train for a goal or race
* ``consistent``  Stay active and consistent
* ``community``   Find my people (friends, clubs, support)
* ``events``      Find events, races and meetups
* ``coach``       Work with a (human) coach
* ``explore``     Just exploring

It steers what the app shows first (Rabbit home, setup quests, composer prompts) and adds one
line to Rabbit's context so replies lean the right way. ``athlete.welcomed_at`` is set when the
welcome flow is finished or skipped, so it is shown once; it is server-written only
(``validate_athlete`` rejects it). New accounts get the full flow (``welcome_mode`` "full");
accounts that were already set up before this existed get the lighter "lite" sheet once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .appstore import AppStore
from .coaching import CoachError

# id -> (title, what we help with, phrase for Rabbit's context)
INTENTS: dict[str, tuple[str, str, str]] = {
    "train": ("Train for a goal or race", "A plan that adapts to real life, synced to your watch",
              "training for a goal or race"),
    "consistent": ("Stay active and consistent", "Streaks, challenges and nudges that stick",
                   "staying active and consistent"),
    "community": ("Find my people", "Friends, local clubs and a feed for the moments that matter",
                  "finding friends, clubs and support"),
    "events": ("Find events", "Races, group runs and meetups near you",
               "finding events, races and meetups"),
    "coach": ("Work with a coach", "Find one or bring yours", "working with a human coach"),
    "explore": ("Just exploring", "Look around first, set things up later", "just exploring"),
}
INTENT_IDS = tuple(INTENTS)

# Setup quests by intent: which ones come first, and which become core (they count toward the
# setup total and can be the "Next:" banner). Without "train", plan building and watch sync are
# optional.
QUEST_FOCUS: dict[str, tuple[str, ...]] = {
    "train": ("garmin", "goal", "plan", "sync"),
    "consistent": ("garmin", "sports", "notify"),
    "community": ("garmin", "friend"),
    "events": ("garmin", "interests", "goal"),
    "coach": ("garmin", "coach_status", "coach"),
    "explore": ("garmin",),
}
CORE_FOR: dict[str, str] = {"community": "friend", "events": "interests", "coach": "coach_status"}
TRAIN_ONLY = ("plan", "sync")


def validate_intents(v: Any) -> list[str]:
    """A list of known ids, deduped, keeping the athlete's order (= priority)."""
    if v is None:
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) or x not in INTENTS for x in v):
        raise CoachError(f"intents must be a list from {', '.join(INTENT_IDS)}")
    out: list[str] = []
    for x in v:
        if x not in out:
            out.append(x)
    return out


def clean(v: Any) -> list[str]:
    """Stored intents, tolerant of junk (never raises)."""
    try:
        return validate_intents(v if isinstance(v, list) else None)
    except CoachError:
        return [x for x in dict.fromkeys(v) if x in INTENTS] if isinstance(v, list) else []


def primary(intents: Any) -> str | None:
    c = clean(intents)
    return c[0] if c else None


def context_line(intents: Any) -> str:
    """One line for Rabbit's context; empty when the athlete hasn't said."""
    c = clean(intents)
    if not c:
        return ""
    line = "Uses Rabbit mainly for (athlete-entered, most important first): " + "; ".join(
        INTENTS[i][2] for i in c) + "."
    if "train" not in c and c != ["explore"]:
        line += " Lean replies that way; don't push a race plan unless they ask."
    return line


def wants_plan(intents: Any) -> bool:
    """Plan building is core unless they told us training isn't why they're here."""
    c = clean(intents)
    return not c or "train" in c


def quest_layout(quests: list[dict[str, Any]], intents: Any) -> list[dict[str, Any]]:
    """Reorder (and re-flag core/optional) setup quests for these intents. No intents: as is."""
    c = clean(intents)
    if not c:
        return quests
    core_extra = {CORE_FOR[i] for i in c if i in CORE_FOR}
    out = []
    for q in quests:
        q = dict(q)
        if q["id"] in TRAIN_ONLY and "train" not in c:
            q["optional"] = True
        elif q["id"] in core_extra:
            q["optional"] = False
        out.append(q)

    def rank(q: dict[str, Any]) -> tuple[int, int]:
        for n, i in enumerate(c):
            focus = QUEST_FOCUS.get(i, ())
            if q["id"] in focus:
                return n, focus.index(q["id"])
        return len(c), 0
    # garmin first always (everything else reads it); stable within the same rank
    return sorted(out, key=lambda q: (q["id"] != "garmin", rank(q)))


def welcome_mode(athlete: dict[str, Any], *, existing: bool) -> str | None:
    """"full" for a new account, "lite" once for an account set up before this, None after."""
    if athlete.get("welcomed_at"):
        return None
    return "lite" if existing else "full"


def is_existing(athlete: dict[str, Any], *, garmin_connected: bool, has_goal: bool) -> bool:
    """Already set up (connected Garmin, a goal, or filled in their profile)."""
    rest = {k for k, v in athlete.items() if v not in (None, "", [], {}) and k not in ("intents", "welcomed_at")}
    return garmin_connected or has_goal or bool(rest)


def options() -> list[dict[str, str]]:
    return [{"id": k, "title": t, "help": h} for k, (t, h, _) in INTENTS.items()]


def save(store: AppStore, user_id: str, intents: Any, *, skip: bool = False,
         now: datetime | None = None) -> dict[str, Any]:
    """Store the answer (or a skip) and mark the welcome as seen. Returns the athlete."""
    upd: dict[str, Any] = {"welcomed_at": (now or datetime.now(UTC)).isoformat(timespec="seconds")}
    if not skip:
        upd["intents"] = validate_intents(intents)

    def apply(p: dict[str, Any]) -> dict[str, Any]:
        a = p.setdefault("athlete", {})
        a.update(upd)
        return dict(a)
    return store.user_doc(user_id, "profile").update(apply)


__all__ = ["INTENTS", "INTENT_IDS", "clean", "context_line", "is_existing", "options", "primary",
           "quest_layout", "save", "validate_intents", "wants_plan", "welcome_mode"]
