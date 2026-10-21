"""Things on the Feed that need no health-data consent, so it's alive on rest days, plus the
Monday crew recap.

``extras(viewer)`` (first page of the main Feed):

* ``upcoming``: my clubs' meetups in the next 7 days (who's going, my RSVP) and races friends
  I follow chose to share (social setting ``races``, off by default), soonest first.
* ``joined``: people who joined one of my clubs in the last 7 days, per club.
* ``recap``: last week's crew recap (Monday to Wednesday), see below.

Shared milestones and PRs are already Feed posts (``community.milestone``), so nothing extra.

Crew recap: built from *posted* workout posts the viewer can see (theirs and people they
follow), so only people who agreed to share are in it. Last Monday-to-Sunday by the workout's
own day: total km, workouts, people, and up to 3 shout-outs (most workouts, longest effort,
farthest). Km goes to the app, which shows miles or km by the athlete's setting. Cached per
viewer per week (``feedlife`` user doc); ``warm(uid)`` builds it on Mondays from the moments
tick (outside quiet hours), and the Feed builds it on first read if the tick hasn't.

Blocks hide people everywhere here. Nothing is pushed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from .logs import log_event

logger = logging.getLogger(__name__)

UPCOMING_DAYS = 7
UPCOMING_MAX = 4
RACE_DAYS = 30
JOINED_DAYS = 7
JOINED_MAX = 3
RECAP_SHOW_DAYS = 3  # Monday, Tuesday, Wednesday
RECAP_FRESH_S = 3600  # a cached card older than this is rebuilt on the next Feed read
DOC = "feedlife"


def week_of(d: date) -> date:
    """The Monday of ``d``'s week."""
    return d - timedelta(days=d.weekday())


class FeedLife:
    def __init__(self, *, community: Any, clubs: Any, social: Any, now: Callable[[str], datetime],
                 events: Callable[[str], list[dict[str, Any]]], store: Any,
                 clock: Callable[[], float]) -> None:
        self.cm = community
        self.clubs = clubs
        self.social = social
        self._now = now
        self._events = events
        self._s = store
        self._clock = clock

    def _first(self, uid: str) -> str:
        try:
            return str(self.cm._name(uid) or "Friend").split(" ")[0]
        except Exception:
            return "Friend"

    def _person(self, uid: str) -> dict[str, Any]:
        return {"id": uid, "name": self._first(uid)}

    # ---------------------------------------------------------- upcoming --
    def upcoming(self, viewer: str) -> list[dict[str, Any]]:
        now = self._now(viewer)
        out: list[dict[str, Any]] = []
        try:
            for m in self.clubs.my_meetups(viewer, now, days=UPCOMING_DAYS):
                going = [u for u in (m.get("going") or []) if u != viewer]
                out.append({"kind": "meetup", "when": m["next"], "title": m.get("title") or "Club run",
                            "where": m.get("where") or "", "club": m["club"], "meetup_id": m.get("id"),
                            "count": int(m.get("count") or 0), "my_rsvp": m.get("my_rsvp"),
                            "people": [self._person(u) for u in going[:3]]})
        except Exception as e:  # clubs unavailable: the rest still shows
            log_event(logger, logging.INFO, "feedlife_meetups_failed", error=type(e).__name__)
        out += self._shared_races(viewer, now.date())
        out.sort(key=lambda x: str(x["when"]))
        return out[:UPCOMING_MAX]

    def _shared_races(self, viewer: str, today: date) -> list[dict[str, Any]]:
        """Races friends I follow chose to share (social setting ``races``), next ``RACE_DAYS``
        days. Blocks and the setting come from one read of the social doc, not one per
        followee (this runs on every Feed load); events are read only for those who share."""
        last = (today + timedelta(days=RACE_DAYS)).isoformat()
        races: dict[tuple[str, str], dict[str, Any]] = {}
        following = self.social.following_ids(viewer)
        blocked = self.social.blocked_ids(viewer)
        sets = self.social.settings_many([f for f in following if f not in blocked])
        for f, st in sets.items():
            if not st.get("races"):
                continue
            try:
                evs = self._events(f)
            except Exception:
                continue
            for e in evs:
                dd = str(e.get("date") or "")
                if e.get("kind") not in (None, "", "race") or not (today.isoformat() <= dd <= last):
                    continue
                name = str(e.get("name") or "Race")[:60]
                k = (name.lower(), dd)
                r = races.setdefault(k, {"kind": "race", "when": dd, "title": name,
                                         "distance": e.get("distance"), "people": []})
                r["people"].append(self._person(f))
        return list(races.values())

    # ------------------------------------------------------------ joined --
    def joined(self, viewer: str) -> list[dict[str, Any]]:
        since = self._clock() - JOINED_DAYS * 86400
        try:
            rows = self.clubs.recent_joins(viewer, since)
        except Exception:
            return []
        return [{"kind": "joined", "club": r["club"], "ts": r["ts"], "count": len(r["user_ids"]),
                 "people": [self._person(u) for u in r["user_ids"][:3]]} for r in rows[:JOINED_MAX]]

    # ------------------------------------------------------------- recap --
    def build_recap(self, viewer: str, monday: date) -> dict[str, Any] | None:
        """Last week's numbers from the workout posts ``viewer`` can see (``monday`` = the
        Monday of that week). None when nobody shared a workout that week."""
        start, end = monday.isoformat(), (monday + timedelta(days=6)).isoformat()
        owners = [viewer, *self.social.following_ids(viewer)]
        by: dict[str, dict[str, Any]] = {}
        longest: tuple[float, str, str] | None = None
        farthest: tuple[float, str, str] | None = None
        blocked = self.social.blocked_ids(viewer)
        for o in dict.fromkeys(owners):
            if o != viewer and o in blocked:
                continue
            for p in (self.cm._posts(o).load().get("posts") or {}).values():
                w = p.get("workout") or {}
                if p.get("author") != o or not w or not (start <= str(w.get("date") or "") <= end):
                    continue
                if not self.cm.can_see(viewer, p):
                    continue
                me = by.setdefault(o, {"n": 0, "km": 0.0})
                me["n"] += 1
                km = w.get("km") if isinstance(w.get("km"), int | float) else 0
                mins = w.get("minutes") if isinstance(w.get("minutes"), int | float) else 0
                me["km"] += float(km or 0)
                title = str(w.get("title") or "workout")
                if mins and (longest is None or mins > longest[0]):
                    longest = (float(mins), o, title)
                if km and (farthest is None or km > farthest[0]):
                    farthest = (float(km), o, title)
        if not by:
            return None
        shout: list[dict[str, Any]] = []
        top = max(by.items(), key=lambda kv: (kv[1]["n"], kv[1]["km"]))
        if top[1]["n"] >= 2:
            shout.append({"kind": "most", "person": self._person(top[0]), "workouts": top[1]["n"]})
        if longest is not None:
            shout.append({"kind": "longest", "person": self._person(longest[1]), "minutes": round(longest[0]),
                          "title": longest[2]})
        if farthest is not None and not (longest is not None and farthest[1] == longest[1] and farthest[2] == longest[2]):
            shout.append({"kind": "farthest", "person": self._person(farthest[1]), "km": round(farthest[0], 1),
                          "title": farthest[2]})
        return {"kind": "recap", "week": start, "km": round(sum(v["km"] for v in by.values()), 1),
                "workouts": sum(v["n"] for v in by.values()), "people": len(by), "shoutouts": shout[:3]}

    def _doc(self, uid: str) -> Any:
        return self._s.user_doc(uid, DOC)

    def recap(self, viewer: str, *, build: bool = True, fresh: bool = True) -> dict[str, Any] | None:
        """This week's card (about last week), shown Monday to Wednesday; cached per week and
        rebuilt when older than ``RECAP_FRESH_S`` (``fresh``), so a post deleted, sharing turned
        off or an unfollow since Monday drops out of it. Shout-outs never show a blocked person."""
        today = self._now(viewer).date()
        if today.weekday() >= RECAP_SHOW_DAYS:
            return None
        last_monday = week_of(today) - timedelta(days=7)
        key = last_monday.isoformat()
        hit = self._doc(viewer).load().get("recap")
        if isinstance(hit, dict) and hit.get("week") == key and (
                not fresh or self._clock() - float(hit.get("at") or 0) < RECAP_FRESH_S):
            card = hit.get("card")
            # Someone blocked since it was built: never show them, rebuild without them.
            if not (isinstance(card, dict) and any(
                    self.social.blocked_between(viewer, str((sh.get("person") or {}).get("id")))
                    for sh in card.get("shoutouts") or [])):
                return card
        if not build:
            return None
        try:
            card = self.build_recap(viewer, last_monday)
        except Exception as e:
            log_event(logger, logging.INFO, "feedlife_recap_failed", user_id=viewer, error=type(e).__name__)
            return None

        def save(d: dict[str, Any]) -> None:
            d["recap"] = {"week": key, "card": card, "at": int(self._clock())}
        self._doc(viewer).update(save)
        return card

    def warm(self, uid: str) -> None:
        """Moments tick (outside quiet hours): build Monday's recap before they open the Feed."""
        if uid.startswith("coach_") or not self.social.is_athlete(uid):
            return
        if self._now(uid).date().weekday() == 0:
            self.recap(uid, fresh=False)  # once per week from here; Feed reads keep it fresh

    # -------------------------------------------------------------- all --
    def extras(self, viewer: str) -> dict[str, Any]:
        return {"recap": self.recap(viewer), "upcoming": self.upcoming(viewer), "joined": self.joined(viewer)}


__all__ = ["FeedLife", "week_of"]
