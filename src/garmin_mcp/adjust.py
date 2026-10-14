"""Plan adjusts to real life: spot missed sessions and poor recovery, and propose a
revised rest of the week the athlete approves with one tap.

Deterministic rules (no model call), so recovery data from any source, including Oura,
can be used without sending it to an AI model. ``recovery`` comes from the athlete's chosen
source (``sources.recovery_for``: Oura or Garmin, tagged ``source``; reasons name it):

* **Recovery low** (any of: readiness under 70 on 2 of the last 3 days; HRV 15%+
  under baseline on 2 of the last 3 days; resting HR 5+ bpm over baseline on 2 of 3;
  form (TSB) under -30): the next 3 days' quality sessions become easy at 70% duration,
  long sessions are capped at 75%, and if tomorrow has a session it becomes rest when
  recovery is very low.
* **Missed a long session** this week and there's a free home day before Sunday with no
  long session next to it: the long session comes back, shortened to 70%.
* **Missed half or more** of the last 7 days' sessions: next week's volume is cut 15%
  ("ease back in"), never stacking missed work.
* **Check-ins** (``checkins.py``, athlete-entered): a pain flag in the last 3 days eases the
  next 3 days (no intensity, about 60-70% duration) with a tip to see a professional if it
  persists; soreness level 3 in the last 2 days, or the last two check-ins both at feel 2
  or lower, turn the next hard session into an easy day.

A proposal has an id (hash of the plan's sessions it touches and the changes); applying
checks the sessions are unchanged, so a stale proposal can't overwrite newer edits.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from .planbuilder import KINDS_BY_SPORT, QUALITY, iter_sessions, week_for
from .weekplan import merge

EASE_IF = 0.7
LONG_CAP = 0.75
MISSED_SHARE = 0.5


def _recovery_flags(recovery: dict[str, Any] | None, tsb: float | None) -> tuple[list[str], bool]:
    """(reasons, very_low)."""
    reasons: list[str] = []
    very = False
    days = (recovery or {}).get("days") or []
    last3 = days[-3:]
    base = (recovery or {}).get("baseline") or {}
    if last3:
        low_ready = sum(1 for d in last3 if isinstance(d.get("readiness"), int | float) and d["readiness"] < 70)
        if low_ready >= 2:
            src = {"oura": "Oura readiness", "garmin": "Garmin readiness"}.get(str((recovery or {}).get("source")), "Readiness")
            reasons.append(f"{src} has been low (under 70) on 2 of the last 3 days.")
            very = very or any((d.get("readiness") or 100) < 60 for d in last3[-2:])
        if base.get("hrv"):
            low_hrv = sum(1 for d in last3 if isinstance(d.get("hrv"), int | float) and d["hrv"] < base["hrv"] * 0.85)
            if low_hrv >= 2:
                reasons.append(f"HRV is running 15%+ below your usual {base['hrv']:.0f} ms.")
        if base.get("resting_hr"):
            high_rhr = sum(1 for d in last3 if isinstance(d.get("resting_hr"), int | float) and d["resting_hr"] >= base["resting_hr"] + 5)
            if high_rhr >= 2:
                reasons.append(f"Resting heart rate is 5+ bpm above your usual {base['resting_hr']:.0f}.")
    if tsb is not None and tsb < -30:
        reasons.append(f"Fatigue is high (form {tsb:.0f}).")
        very = very or tsb < -40
    return reasons, very


PAIN_TIP = "If it persists or gets worse, check with a physio or doctor."


def _checkin_flags(checkins: list[dict[str, Any]] | None, today: date) -> tuple[str | None, str | None]:
    """(pain reason, rough-days reason) from recent check-ins (newest first or any order)."""
    from .checkins import area_label  # local: keeps adjust importable without the store
    rows = sorted((c for c in checkins or [] if isinstance(c, dict) and (c.get("date") or "") <= today.isoformat()),
                  key=lambda c: (c.get("date") or "", c.get("ts") or 0), reverse=True)
    pain = None
    since3 = (today - timedelta(days=2)).isoformat()
    for c in rows:
        if c.get("date", "") >= since3 and c.get("pain_flag"):
            worst = max(c.get("soreness") or [], key=lambda s: s.get("level") or 0, default=None)
            area = area_label(worst) if worst and worst.get("area") != "other" else None
            pain = f"You mentioned {area} pain." if area else "You mentioned pain."
            break
    rough = None
    since2 = (today - timedelta(days=1)).isoformat()
    heavy = next((s for c in rows if c.get("date", "") >= since2 for s in c.get("soreness") or []
                  if (s.get("level") or 0) >= 3), None)
    if heavy:
        rough = f"You reported a really sore {area_label(heavy)}."
    elif len(rows) >= 2 and all(isinstance(c.get("feel"), int) and c["feel"] <= 2 for c in rows[:2]) \
            and rows[1].get("date", "") >= (today - timedelta(days=6)).isoformat():
        rough = "Your last two check-ins felt rough."
    return pain, rough


def _easy_change(s: dict[str, Any], d: str, share: float, why: str) -> dict[str, Any] | None:
    minutes = s.get("minutes") or 0
    quality = s.get("kind") in QUALITY or s.get("kind") in ("long", "brick")
    kind = ("easy" if "easy" in KINDS_BY_SPORT.get(s["sport"], ()) else KINDS_BY_SPORT.get(s["sport"], ("easy",))[0]) \
        if s.get("kind") in QUALITY else s.get("kind")
    if not minutes or (not quality and minutes <= 30):
        return None
    return {"session_id": s["id"], "date": d, "action": "ease" if s.get("kind") in QUALITY else "shorten",
            "from": _session_view(s), "to": {"sport": s["sport"], "kind": kind, "minutes": _r5(minutes * share)},
            "why": why}


def _session_view(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ("title", "sport", "kind", "minutes")}


def propose(plan: dict[str, Any] | None, acts: list[dict[str, Any]], today: date, *,
            recovery: dict[str, Any] | None = None, tsb: float | None = None,
            dismissed: list[str] | None = None, checkins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not plan:
        return {"status": "none"}
    changes: list[dict[str, Any]] = []
    reasons: list[str] = []
    t = today.isoformat()

    # Missed sessions in the last 7 days (per plan week, matched to activities).
    weeks_seen: set[str] = set()
    past: list[dict[str, Any]] = []
    for i in range(1, 8):
        w = week_for(plan, today - timedelta(days=i))
        if w is None or w["start"] in weeks_seen:
            continue
        weeks_seen.add(w["start"])
        planned = {d: [{"sport": s["sport"], "title": s["title"], "minutes": s.get("minutes"), "kind": s.get("kind"),
                        "id": s["id"]} for s in ss] for d, ss in w["days"].items()}
        for day in merge(date.fromisoformat(w["start"]), today, planned, acts):
            if (today - timedelta(days=7)).isoformat() <= day["date"] < t:
                past += [s for s in day["sessions"] if s["status"] in ("done", "missed") and s.get("kind") != "race"]
    missed = [s for s in past if s["status"] == "missed"]

    rec_reasons, very_low = _recovery_flags(recovery, tsb)
    # Sessions already adjusted once are left alone, so suggestions never compound.
    upcoming = [(w, d, s) for w, d, s in iter_sessions(plan)
                if t <= d and s["sport"] != "rest" and s.get("kind") != "race" and not s.get("adjusted")]
    made_up = set(plan.get("made_up", []))
    taken: set[str] = set()
    tip: str | None = None

    # Athlete check-ins first: what they told us beats any signal we infer.
    pain, rough = _checkin_flags(checkins, today)
    if pain:
        reasons.append(pain)
        tip = PAIN_TIP
        horizon = (today + timedelta(days=2)).isoformat()
        for w, d, s in upcoming:
            if d > horizon:
                break
            c = _easy_change(s, d, EASE_IF if s.get("kind") in QUALITY else 0.6,
                             "No intensity and shorter while it settles. " + PAIN_TIP)
            if c:
                changes.append(c)
                taken.add(s["id"])
    elif rough:
        tomorrow = (today + timedelta(days=1)).isoformat()
        for w, d, s in upcoming:
            if d > tomorrow:
                break
            if s.get("kind") in QUALITY or s.get("kind") in ("long", "brick"):
                c = _easy_change(s, d, EASE_IF, "Make it an easy day; the hard work keeps.")
                if c:
                    reasons.append(rough)
                    changes.append(c)
                    taken.add(s["id"])
                    break

    if rec_reasons:
        reasons += rec_reasons
        horizon = (today + timedelta(days=2)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        for w, d, s in upcoming:
            if d > horizon:
                break
            if s["id"] in taken:
                continue
            minutes = s.get("minutes") or 0
            if very_low and d == tomorrow:
                changes.append({"session_id": s["id"], "date": d, "action": "rest", "from": _session_view(s),
                                "to": {"title": "Rest", "sport": "rest", "kind": "rest", "minutes": None},
                                "why": "Recovery is very low: take a full day off."})
            elif s.get("kind") in QUALITY:
                kind = "easy" if "easy" in KINDS_BY_SPORT.get(s["sport"], ()) else KINDS_BY_SPORT.get(s["sport"], ("easy",))[0]
                changes.append({"session_id": s["id"], "date": d, "action": "ease", "from": _session_view(s),
                                "to": {"sport": s["sport"], "kind": kind, "minutes": _r5(minutes * EASE_IF)},
                                "why": "Swap intensity for easy aerobic work until recovery bounces back."})
            elif s.get("kind") in ("long", "brick") and minutes > 60:
                changes.append({"session_id": s["id"], "date": d, "action": "shorten", "from": _session_view(s),
                                "to": {"sport": s["sport"], "kind": s.get("kind"), "minutes": _r5(minutes * LONG_CAP)},
                                "why": "Keep the long session, but shorter."})
            else:
                continue
            taken.add(s["id"])

    # A missed long session this week comes back (shortened) on a free home day.
    this_week = week_for(plan, today)
    missed_long = [s for s in missed if s.get("kind") in ("long", "brick") and s.get("id") not in made_up
                   and this_week and s.get("id") and any(x["id"] == s["id"] for ss in this_week["days"].values() for x in ss)]
    if missed_long and this_week and not rec_reasons and not pain and not rough:
        s = missed_long[0]
        free = _free_day(this_week, today)
        if free:
            changes.append({"session_id": s["id"], "date": free, "action": "move", "from": _session_view(s),
                            "to": {"sport": s["sport"], "kind": s.get("kind"), "minutes": _r5((s.get("minutes") or 60) * 0.7)},
                            "why": "You missed this week's long session. A shorter one fits here without stacking hard days."})
            reasons.append(f"You missed {s['title']}.")

    # Lots missed: ease back in next week.
    if past and len(missed) / len(past) >= MISSED_SHARE and len(missed) >= 2:
        nxt = week_for(plan, today + timedelta(days=7 - today.weekday()))
        if nxt and nxt["phase"] not in ("taper", "race"):
            reasons.append(f"You missed {len(missed)} of {len(past)} sessions in the last week; ease back in rather than catch up.")
            for d, ss in sorted(nxt["days"].items()):
                for s in ss:
                    if s["sport"] == "rest" or s.get("kind") == "race" or s["id"] in taken or not s.get("minutes") \
                            or s.get("adjusted"):
                        continue
                    changes.append({"session_id": s["id"], "date": d, "action": "shorten", "from": _session_view(s),
                                    "to": {"sport": s["sport"], "kind": s.get("kind"), "minutes": _r5(s["minutes"] * 0.85)},
                                    "why": "Next week 15% lighter to rebuild momentum."})

    # Drop no-ops (a change that wouldn't change anything).
    changes = [c for c in changes if c["action"] in ("rest", "move")
               or c["to"].get("minutes") != c["from"].get("minutes") or c["to"].get("kind") != c["from"].get("kind")]
    if not changes:
        # Low recovery but nothing hard coming up: just say so.
        out: dict[str, Any] = {"status": "watch" if rec_reasons or pain else "ok", "reasons": reasons}
        if tip:
            out["tip"] = tip
        return out
    pid = proposal_id(plan, changes)
    if pid in (dismissed or []):
        return {"status": "dismissed", "id": pid}
    out = {"status": "suggest", "id": pid, "reasons": reasons, "changes": changes}
    if tip:
        out["tip"] = tip
    return out


def _free_day(week: dict[str, Any], today: date) -> str | None:
    days = sorted(week["days"])
    longs = {d for d in days if any(x.get("kind") in ("long", "brick", "race") for x in week["days"][d])}
    for d in days:
        if d <= today.isoformat():
            continue
        dd = date.fromisoformat(d)
        near = {(dd + timedelta(days=o)).isoformat() for o in (-1, 0, 1)}
        if near & longs:
            continue
        if any(x.get("kind") in QUALITY for x in week["days"][d]):
            continue
        return d
    return None


def _r5(m: float) -> int:
    return max(15, int(round(m / 5.0) * 5))


def proposal_id(plan: dict[str, Any], changes: list[dict[str, Any]]) -> str:
    ids = {c["session_id"] for c in changes}
    now = sorted((s["id"], d, s.get("minutes"), s.get("kind"), s["sport"]) for _, d, s in iter_sessions(plan) if s["id"] in ids)
    return hashlib.sha256(json.dumps([now, changes], sort_keys=True, default=str).encode()).hexdigest()[:16]


__all__ = ["propose", "proposal_id"]
