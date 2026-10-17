"""Fueling for long sessions and races, with a gut-training ramp toward race-day carbs.

General sports-nutrition ranges (carbohydrate per hour by duration; 400-800 ml fluid and
300-600 mg sodium per hour, more in heat). Long sessions practice race fueling, stepping
up from about 16 weeks out so race-day intake is familiar by the final month.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Race-day carbohydrate target (g/h) by distance.
RACE_CARBS = {"sprint triathlon": 30, "olympic triathlon": 60, "70.3": 80, "140.6": 90, "5k": 0,
              "10k": 0, "half marathon": 40, "marathon": 70, "ultra": 80, "century ride": 70, "other": 60}
RAMP_WEEKS = 16


def race_target(distance: str | None) -> int:
    return RACE_CARBS.get((distance or "other").lower(), 60)


def fuel(session: dict[str, Any], day: str, *, race_date: str | None, distance: str | None) -> dict[str, Any] | None:
    """Fueling guide for one session, or None when water is enough (< 75 min)."""
    minutes = session.get("minutes") or sum(lg.get("minutes", 0) for lg in session.get("legs") or [])
    is_race = session.get("kind") == "race"
    if session.get("sport") in ("rest", "strength") or (not is_race and minutes < 75):
        return None
    target = race_target(distance)
    if is_race:
        if target == 0:
            return {"carbs_g_per_h": 0, "note": "Short race: a carb-rich breakfast 2-3 hours before is enough. Water as needed."}
        return {"carbs_g_per_h": target, "fluid_ml_per_h": "500-800", "sodium_mg_per_h": "400-800",
                "note": f"Start fueling in the first 20-30 minutes and keep a steady {target} g/h. Use only what you've trained with."}
    weeks_out = None
    if race_date:
        try:
            weeks_out = (date.fromisoformat(race_date) - date.fromisoformat(day)).days // 7
        except ValueError:
            weeks_out = None
    base = 30 if minutes < 120 else 45
    gh = base
    note = "Practice fueling: start after 30-45 minutes, then little and often."
    if weeks_out is not None and target >= 60 and weeks_out <= RAMP_WEEKS:
        progress = min(1.0, (RAMP_WEEKS - weeks_out) / (RAMP_WEEKS - 4))
        gh = int(round((base + (target - base) * progress) / 5) * 5)
        note = (f"Gut training: {gh} g/h today, building to your race target of {target} g/h. "
                "Use your race-day products.")
    hours = minutes / 60
    return {"carbs_g_per_h": gh, "total_carbs_g": int(round(gh * max(0.0, hours - 0.5))),
            "fluid_ml_per_h": "400-800", "sodium_mg_per_h": "300-600", "note": note}


__all__ = ["fuel", "fuel_plan", "fuel_context", "race_target", "RACE_CARBS", "FUEL_STYLES", "DIETS"]


# ------------------------------------------------------------- fuel plan --
# Before / during / after for one session: plain, mainstream sports-nutrition ranges (carbs
# before and during, carbs + 20-30 g protein after hard or long work, fluids and sodium per hour).
# No calorie targets and no weight-loss framing. Examples are filtered by the athlete's diet tags
# (``diet``) and leaned toward their ``fuel_style`` (gels / real_food / mix, default mix).
FUEL_STYLES = ("gels", "real_food", "mix")
DIETS = ("vegetarian", "vegan", "gluten_free", "dairy_free")
HARD_KINDS = {"tempo", "threshold", "vo2", "racepace", "css", "brick", "long", "race"}
GEL_G = 25          # carbs in a typical gel
DRINK_G = 40        # carbs in a typical 500 ml bottle of drink mix
LEARN_MORE = ("Gels, chews and drink mixes (Maurten, SiS, GU and others) all work. "
              "Use what you've practised with, never something new on race day.")

# name, tags that rule it out (meat, fish, dairy, egg, honey, gluten)
_PRE_MEAL = [("oats with banana and honey", {"gluten", "honey"}), 
             ("bagel with peanut butter and jam", {"gluten"}), ("rice with eggs", {"egg"}),
             ("toast with eggs", {"gluten", "egg"}), ("rice or potatoes with a little lean protein", set()),
             ("yogurt with granola and fruit", {"dairy", "gluten"}),
             ("oats with banana and maple syrup", {"gluten", "_alt"})]
_PRE_SNACK = [("a banana", set()), ("toast with honey or jam", {"gluten", "honey"}), ("toast with jam", {"gluten", "_alt"}), ("a few dates", set()),
              ("an applesauce pouch", set()), ("a rice cake with jam", set()), ("a granola bar", {"gluten"})]
_DURING_FOOD = [("a banana (~25 g)", set()), ("2 dates (~30 g)", set()), ("a rice cake (~25 g)", set()),
                ("half a PB&J (~25 g)", {"gluten"}), ("a fig bar (~20 g)", {"gluten"})]
_AFTER = [("chocolate milk", {"dairy"}), ("Greek yogurt with granola and fruit", {"dairy", "gluten"}),
          ("a recovery shake and a banana", {"dairy"}), ("a plant-protein shake and a banana", set()),
          ("eggs on toast", {"egg", "gluten"}), ("a rice bowl with chicken or tofu", {"meat"}),
          ("a rice bowl with tofu or beans", set()), ("a bagel with peanut butter and a glass of milk", {"gluten", "dairy"}),
          ("hummus wrap with veggies", {"gluten"})]
_BLOCKED = {"vegan": {"meat", "fish", "dairy", "egg", "honey"}, "vegetarian": {"meat", "fish"},
            "dairy_free": {"dairy"}, "gluten_free": {"gluten"}}


def _pick(items: list[tuple[str, set[str]]], diet: list[str], n: int) -> list[str]:
    bad: set[str] = set() if "vegan" in diet else {"_alt"}  # _alt: a swap shown only to vegans
    for d in diet:
        bad |= _BLOCKED.get(d, set())
    return [name for name, tags in items if not (tags & bad)][:n]


def _ml(lo: int, hi: int, imperial: bool) -> str:
    if imperial:
        return f"{round(lo / 29.57 / 2) * 2}-{round(hi / 29.57 / 2) * 2} oz"
    return f"{lo}-{hi} ml"


def _hour(session: dict[str, Any]) -> int | None:
    t = session.get("time")
    if isinstance(t, str) and len(t) >= 2 and t[:2].isdigit():
        return int(t[:2])
    return None


def _round5(x: float) -> int:
    return max(5, int(round(x / 5) * 5))


def fuel_plan(session: dict[str, Any], day: str, athlete: dict[str, Any] | None = None,
              plan: dict[str, Any] | None = None, *, start_time: str | None = None,
              later_today: bool = False, hot: bool = False) -> dict[str, Any] | None:
    """Before / during / after fueling for one planned session (None for rest days).

    ``start_time`` (HH:MM) overrides ``session["time"``]; unknown times are treated as a morning
    session. ``later_today``: another session follows the same day (refuel faster). ``hot``: the
    forecast is hot (more fluid and sodium)."""
    a = athlete or {}
    sport, kind = session.get("sport") or "other", session.get("kind")
    if sport == "rest":
        return None
    minutes = int(session.get("minutes") or sum(int(lg.get("minutes") or 0) for lg in session.get("legs") or []) or 0)
    is_race = kind == "race"
    hard = kind in HARD_KINDS or is_race or sport == "brick"
    long_ = minutes >= 90 or kind == "long"
    style = a.get("fuel_style") if a.get("fuel_style") in FUEL_STYLES else "mix"
    diet = [d for d in (a.get("diet") or []) if d in DIETS]
    imperial = a.get("units") != "metric"
    kg = a.get("weight_kg") if isinstance(a.get("weight_kg"), int | float) and not isinstance(a.get("weight_kg"), bool) else None
    salty = a.get("sweat") in ("heavy", "salty")
    hour = _hour({"time": start_time} if start_time else session)
    early = hour is None or hour < 9
    strength = sport == "strength"

    # ----- before
    if strength or (minutes and minutes < 60 and not hard):
        before = {"when": "Optional", "headline": "a small snack 30-60 min before, or nothing",
                  "items": _pick(_PRE_SNACK, diet, 3), "optional": True,
                  "tip": "Easy and under an hour: training on an empty stomach is fine if that suits you."}
    elif early:
        head = "a small, easy carb snack" + (" (about 30-60 g carbs)" if long_ or hard else "")
        before = {"when": "30-60 min before", "headline": head,
                  "items": ((["a gel with water"] if style == "gels" else []) + _pick(_PRE_SNACK, diet, 3))[:3],
                  "optional": False,
                  "tip": ("If you're up 2 hours early, a proper breakfast is even better: "
                          + ", ".join(_pick(_PRE_MEAL, diet, 2)) + ".") if long_ or is_race else None}
    else:
        grams = f" (about {round(kg)}-{round(kg * 2)} g carbs)" if kg else ""
        before = {"when": "2-3 h before", "headline": "a carb-rich meal" + grams,
                  "items": _pick(_PRE_MEAL, diet, 3), "optional": False,
                  "tip": "Hungry closer to the start? Top up with " + (_pick(_PRE_SNACK, diet, 1) or ["a banana"])[0]
                  + " 30-60 min before."}
    before["hydration"] = f"Drink {_ml(400, 600, imperial)} in the 2 hours before."
    night_before = None
    if (long_ or is_race or (hard and minutes >= 75)) and early and not strength:
        dinner = "pasta, rice or potatoes" if "gluten_free" not in diet else "rice or potatoes"
        night_before = f"Carb-rich dinner the night before ({dinner})."

    # ----- during
    legacy = fuel(session, day, race_date=(plan or {}).get("race_date"), distance=(plan or {}).get("distance"))
    gh = int((legacy or {}).get("carbs_g_per_h") or 0)
    lo_fl, hi_fl = (500, 1000) if hot else (400, 800)
    sodium = "500-1000 mg" if (hot or salty) else "300-600 mg"
    during: dict[str, Any]
    if sport == "swim":
        long_ow = minutes > 90
        during = {"headline": "Nothing during" if not long_ow else "A gel before you start",
                  "plan": ("Pool: keep a bottle on the deck and sip between sets."
                           if not long_ow else "Long open-water swim: take a gel just before, and one every 45 min if you can stop."),
                  "items": [], "carbs_g_per_h": 0}
    elif strength or minutes < 60:
        during = {"headline": "Water is enough", "plan": "Sip water as you need it.", "items": [], "carbs_g_per_h": 0}
    elif gh == 0:
        during = {"headline": "Water is enough" if not hard else "Water, or a sports drink",
                  "plan": "A sports drink helps if it's hot or you're going hard." if minutes >= 60 else "Sip water.",
                  "items": [], "carbs_g_per_h": 0}
    else:
        gel_every = _round5(60 * GEL_G / gh)
        if sport == "bike" and style != "gels":
            rest = max(0, gh - DRINK_G)
            if rest == 0:
                how = "1 bottle of drink mix an hour"
            else:
                n = max(1, round(rest / 25))
                how = ("1 bottle of drink mix an hour + a snack (~25 g)" if n == 1
                       else f"1 bottle of drink mix an hour + {n} snacks (~25 g each)")
            items = _pick(_DURING_FOOD, diet, 3) + ["a gel (~25 g)"]
        elif sport == "bike":
            how = f"1 gel every {gel_every} min, with water"
            items = ["a gel (~25 g)", "chews (~25 g a half pack)", "drink mix (~40 g a bottle)"]
        else:  # run, brick, other on foot
            if style == "real_food":
                how = f"About 25 g every {gel_every} min: chews or dates carry best"
                items = ["chews (~25 g a half pack)", "2 dates (~30 g)", "a gel (~25 g)"]
            else:
                how = f"1 gel every {gel_every} min, with a few sips of water"
                items = ["a gel (~25 g)", "chews (~25 g a half pack)", "drink mix in a soft flask"]
        during = {"headline": f"{gh} g carbs an hour", "plan": how, "items": items, "carbs_g_per_h": gh,
                  "start": "Start after 20-30 min, then little and often."}
        if legacy and legacy.get("total_carbs_g"):
            during["total_carbs_g"] = legacy["total_carbs_g"]
        if legacy and legacy.get("note", "").startswith("Gut training"):
            during["note"] = legacy["note"]
    if minutes >= 60 and sport != "swim" and not strength:
        during["fluids"] = f"{_ml(lo_fl, hi_fl, imperial)} an hour"
        if minutes >= 90 or hot or salty:
            during["sodium"] = f"{sodium} sodium an hour"
        during["heat"] = (None if hot else
                          "Hot day: drink toward the top of the range and add electrolytes.")
        if hot:
            during["heat"] = "It's hot: drink toward the top of the range and add electrolytes."
    caffeine = None
    if (long_ or hard) and not strength:
        if a.get("caffeine") is True:
            caffeine = "Caffeine: a coffee before or a caffeinated gel in the last third can help."
        elif a.get("caffeine") is None:
            caffeine = "Optional: caffeine (coffee before, or a caffeinated gel late on) helps if you're used to it."

    # ----- after
    if strength:
        after = {"when": "Within 1-2 h", "headline": "20-30 g protein with some carbs",
                 "items": _pick(_AFTER, diet, 3), "optional": False}
    elif hard or minutes >= 75:
        head = "carbs + 20-30 g protein"
        if kg:
            head = f"about {round(kg)} g carbs + {round(kg * 0.3)} g protein"
        after = {"when": "Within 30-60 min", "headline": head, "items": _pick(_AFTER, diet, 3), "optional": False,
                 "tip": "Rehydrate with water, plus something salty if you sweated a lot."}
    else:
        after = {"when": "After", "headline": "your next normal meal is fine", "items": [], "optional": True,
                 "tip": "Drink some water."}
    if later_today:
        after["when"] = "Right away"
        after["tip"] = "Another session later today: refuel straight after, then a real meal 2-3 h before the next one."

    # ----- one-line hint for plan days (only where it matters)
    hint = None
    if not strength and sport != "swim":
        bits = []
        if gh:
            bits.append(during["plan"].split(",")[0].lower() if during["plan"].startswith("1 gel") else f"{gh} g carbs/h")
        elif hard and not before.get("optional"):
            bits.append("small snack before")
        if after.get("optional") is False:
            bits.append("recovery snack after")
        if bits:
            hint = "Fuel: " + " · ".join(bits)
    return {"before": before, "during": during, "after": after, "night_before": night_before,
            "caffeine": caffeine, "hint": hint, "style": style, "learn_more": LEARN_MORE,
            "minutes": minutes or None,
            # what the athlete chose (the workout page's "Fueling preferences" sheet starts from these)
            "prefs": {"fuel_style": a.get("fuel_style") if a.get("fuel_style") in FUEL_STYLES else None,
                      "caffeine": a.get("caffeine") if isinstance(a.get("caffeine"), bool) else None, "diet": diet}}


def fuel_context(session: dict[str, Any], plan_view: dict[str, Any]) -> str:
    """One line for Rabbit's context: the same plan the app shows."""
    b, d, af = plan_view["before"], plan_view["during"], plan_view["after"]
    parts = [f"before: {b['when']}, {b['headline']}",
             f"during: {d['headline']} ({d.get('plan', '')})",
             f"after: {af['when'].lower()}, {af['headline']}"]
    if plan_view.get("night_before"):
        parts.insert(0, plan_view["night_before"].rstrip("."))
    return f"Fueling the app shows for {session.get('title') or 'the session'}: " + "; ".join(parts) + "."
