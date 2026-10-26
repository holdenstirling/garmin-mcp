"""Strength, mobility and injury care for built plans.

Strength sessions get a routine for the training phase and the sport (runners get
single-leg and calf/tendon work, cyclists hinge and core, swimmers shoulders), and any
injuries the athlete listed add a short prehab block. This is general guidance, labelled
as such; it never diagnoses.
"""

from __future__ import annotations

import re
from typing import Any

Ex = tuple[str, str]  # (exercise, dose)

ROUTINES: dict[str, list[Ex]] = {
    "base": [("Goblet squat", "3×10"), ("Romanian deadlift", "3×8"), ("Step-ups", "3×8 each leg"),
             ("Calf raises", "3×15"), ("Plank", "3×40s"), ("Side plank", "2×30s each side")],
    "build": [("Rear-foot split squat", "3×8 each leg"), ("Single-leg RDL", "3×8 each leg"),
              ("Push-ups", "3×10"), ("Pallof press", "3×10 each side"), ("Dead bug", "3×10")],
    "peak": [("Goblet squat", "2×8"), ("Single-leg RDL", "2×6 each leg"), ("Plank", "2×45s")],
    "taper": [("Glute bridge", "2×12"), ("Monster walks", "2×10 steps each way"), ("Calf raises", "2×12"),
              ("Dead bug", "2×8")],
}
SPORT_EXTRA: dict[str, list[Ex]] = {
    "run": [("Pogo hops", "3×20"), ("Eccentric heel drops", "2×12")],
    "tri": [("Band pull-aparts", "3×15"), ("Pogo hops", "2×20")],
    "bike": [("Trap-bar or kettlebell deadlift", "3×6"), ("Side-lying hip abduction", "2×15")],
    "general": [("Band pull-aparts", "2×15")],
}
MOBILITY: list[Ex] = [("World's greatest stretch", "5 each side"), ("Hip flexor stretch", "45s each side"),
                      ("Thoracic rotations", "8 each side"), ("Pigeon or figure-4", "45s each side"),
                      ("Calf and Achilles stretch", "45s each side"), ("Cat-cow", "10 slow reps")]

# keyword pattern -> (area, exercises)
CARE: list[tuple[re.Pattern[str], str, list[Ex]]] = [
    (re.compile(r"achilles|calf|calves", re.I), "Achilles/calf",
     [("Eccentric heel drops, straight and bent knee", "3×15"), ("Slow calf raises", "3×12")]),
    (re.compile(r"knee|patell|\bitb?\b|it band|iliotibial", re.I), "Knee/IT band",
     [("Spanish squat or wall sit", "4×40s"), ("Side-lying hip abduction", "3×15"), ("Step-downs", "3×10 each leg")]),
    (re.compile(r"plantar|arch|heel pain|foot", re.I), "Foot/plantar",
     [("Towel scrunches", "3×20"), ("Slow single-leg calf raise", "3×10"), ("Roll the arch", "2 min")]),
    (re.compile(r"shin", re.I), "Shins",
     [("Tibialis raises", "3×20"), ("Calf raises", "3×15")]),
    (re.compile(r"hamstring", re.I), "Hamstrings",
     [("Assisted Nordic curls", "3×5"), ("Single-leg bridge", "3×10 each leg")]),
    (re.compile(r"back|lumbar|spine", re.I), "Lower back",
     [("Bird-dog", "3×8 each side"), ("Dead bug", "3×10"), ("McGill curl-up", "3×6")]),
    (re.compile(r"hip|glute|piriformis", re.I), "Hips/glutes",
     [("Clamshells", "3×15"), ("Monster walks", "3×10 steps"), ("Glute bridge", "3×12")]),
    (re.compile(r"shoulder|rotator", re.I), "Shoulder",
     [("Band external rotation", "3×15"), ("Face pulls", "3×12"), ("Y-T-W raises", "2×8")]),
]
CARE_NOTE = "General prehab, not a diagnosis. If pain is sharp, getting worse or changes how you move, see a physio."


def care_plan(injuries: str | None) -> list[dict[str, Any]]:
    """Areas found in the athlete's injury notes, with prehab exercises."""
    if not injuries:
        return []
    out = []
    for pat, area, exs in CARE:
        if pat.search(injuries):
            out.append({"area": area, "exercises": [{"name": n, "dose": d} for n, d in exs]})
    return out


def routine(phase: str, race_kind: str, injuries: str | None = None, *, mobility: bool = False) -> dict[str, Any]:
    """Exercises and a one-paragraph detail for a strength (or mobility) session."""
    if mobility:
        exs = list(MOBILITY)
        head = "20 minutes, easy breathing, no pain."
    else:
        exs = list(ROUTINES.get(phase if phase in ROUTINES else "base", ROUTINES["base"]))
        if phase in ("base", "build"):
            exs += SPORT_EXTRA.get(race_kind, [])[:2]
        head = {"base": "Build strength: 2-3 rounds, controlled reps, 1-2 reps in reserve.",
                "build": "Strength endurance: 3 rounds, steady tempo.",
                "peak": "Maintenance: short and sharp, nothing sore tomorrow.",
                "taper": "Activation only: 15 minutes."}.get(phase, "2-3 rounds, controlled reps.")
    care = care_plan(injuries)
    care_exs = [(e["name"], e["dose"]) for c in care for e in c["exercises"]][:4]
    lines = [head, "; ".join(f"{n} {d}" for n, d in exs)]
    if care_exs:
        lines.append("Prehab (" + ", ".join(c["area"] for c in care) + "): " + "; ".join(f"{n} {d}" for n, d in care_exs))
    return {"exercises": [structured(n, d, 30 if mobility else 60) for n, d in exs],
            "prehab": [structured(n, d, 30) for n, d in care_exs],
            "detail": " ".join(lines)[:900]}


# How to do each move well (one short cue each), shown with sets and reps.
CUES: dict[str, str] = {
    "Goblet squat": "Chest up, sit between your heels, knees track over toes.",
    "Back squat": "Brace first, hips and chest rise together.",
    "Romanian deadlift": "Soft knees, push hips back, bar close to your legs.",
    "Trap-bar or kettlebell deadlift": "Push the floor away, finish tall with glutes, not your back.",
    "Trap-bar deadlift": "Push the floor away, finish tall with glutes, not your back.",
    "Step-ups": "Drive through the front heel, control the way down.",
    "Rear-foot split squat": "Most weight on the front leg, drop the back knee straight down.",
    "Single-leg RDL": "Hips square, reach long from head to back heel.",
    "Calf raises": "Full range, pause at the top, 3 seconds down.",
    "Hip thrust": "Chin tucked, ribs down, squeeze glutes at the top.",
    "Box jumps": "Land soft and quiet, step down, quality over quantity.",
    "Pogo hops": "Stiff ankles, quick contacts, stay tall.",
    "Eccentric heel drops": "Up on two feet, lower slowly on one.",
    "Push-ups": "Body in one line, elbows about 45 degrees.",
    "Dumbbell bench press": "Shoulder blades pinned, press up and slightly back.",
    "Overhead press": "Squeeze glutes, press straight up, head through at the top.",
    "One-arm dumbbell row": "Pull your elbow to your hip, no twisting.",
    "Pull-ups or lat pulldown": "Shoulders down first, chest to the bar.",
    "Band pull-aparts": "Arms straight, squeeze between the shoulder blades.",
    "Face pulls": "Pull to your forehead, thumbs back.",
    "Plank": "Squeeze glutes, ribs down, breathe.",
    "Side plank": "Hips high, body in one line.",
    "Dead bug": "Low back pressed down, move slowly.",
    "Pallof press": "Resist the twist, press straight out.",
    "Glute bridge": "Ribs down, squeeze glutes at the top.",
    "Monster walks": "Band above the knees, stay low, toes forward.",
    "Side-lying hip abduction": "Toes slightly down, lift from the hip.",
    "Farmer carry": "Tall posture, shoulders down, walk smoothly.",
}
REST_S = {"heavy": 90, "power": 75, "light": 45, "upper": 60, "core": 30}

# Opted-in strength workouts (weekly rhythm): (name, sets, reps, kind of rest) by phase and day type.
# heavy = legs and hinge first (not the day before a long or key session); light = upper body and core.
WORKOUTS: dict[str, dict[str, list[tuple[str, int, str, str]]]] = {
    "base": {
        "heavy": [("Goblet squat", 3, "8-10", "heavy"), ("Romanian deadlift", 3, "8", "heavy"),
                  ("Rear-foot split squat", 3, "8 each leg", "heavy"), ("Calf raises", 3, "15", "light"),
                  ("One-arm dumbbell row", 3, "10 each arm", "upper"), ("Dead bug", 3, "10", "core"),
                  ("Side plank", 2, "30s each side", "core")],
        "light": [("Push-ups", 3, "10-12", "upper"), ("One-arm dumbbell row", 3, "10 each arm", "upper"),
                  ("Overhead press", 3, "8-10", "upper"), ("Band pull-aparts", 3, "15", "core"),
                  ("Glute bridge", 3, "12", "light"), ("Dead bug", 3, "10", "core"),
                  ("Pallof press", 3, "10 each side", "core")],
    },
    "build": {
        "heavy": [("Trap-bar deadlift", 4, "5", "heavy"), ("Rear-foot split squat", 3, "6 each leg", "heavy"),
                  ("Step-ups", 3, "8 each leg", "heavy"), ("Box jumps", 3, "5", "power"),
                  ("Calf raises", 3, "12", "light"), ("Pull-ups or lat pulldown", 3, "6-8", "upper"),
                  ("Pallof press", 3, "10 each side", "core")],
        "light": [("Dumbbell bench press", 3, "8", "upper"), ("Pull-ups or lat pulldown", 3, "6-8", "upper"),
                  ("Face pulls", 3, "12", "upper"), ("Hip thrust", 3, "10", "light"),
                  ("Side plank", 3, "30s each side", "core"), ("Farmer carry", 3, "40 m", "core")],
    },
    "peak": {
        "heavy": [("Trap-bar deadlift", 3, "3", "heavy"), ("Rear-foot split squat", 2, "5 each leg", "heavy"),
                  ("Box jumps", 3, "4", "power"), ("Pull-ups or lat pulldown", 3, "6", "upper"),
                  ("Plank", 2, "45s", "core")],
        "light": [("Push-ups", 2, "10", "upper"), ("One-arm dumbbell row", 2, "10 each arm", "upper"),
                  ("Glute bridge", 2, "12", "light"), ("Dead bug", 2, "10", "core")],
    },
    "taper": {
        "heavy": [("Goblet squat", 2, "6", "light"), ("Glute bridge", 2, "10", "light"),
                  ("Band pull-aparts", 2, "15", "core"), ("Dead bug", 2, "8", "core")],
        "light": [("Glute bridge", 2, "10", "light"), ("Band pull-aparts", 2, "15", "core"),
                  ("Dead bug", 2, "8", "core")],
    },
}
WORKOUT_HEAD = {
    "base": "Build general strength. Controlled reps, stop with 2 reps left in the tank.",
    "build": "Strength and power. Heavier and fewer reps, full rest between sets.",
    "peak": "Maintenance. Short and sharp, nothing sore tomorrow.",
    "taper": "Light activation only. Feel better leaving than arriving.",
}
WARMUP = "Warm up 5 to 8 minutes: easy cardio, leg swings, hip circles, a few bodyweight squats."


def _parse_dose(dose: str) -> tuple[int | None, str]:
    m = re.match(r"\s*(\d+)\s*[×x]\s*(.+)", dose)
    return (int(m.group(1)), m.group(2).strip()) if m else (None, dose)


def structured(name: str, dose: str, rest_s: int = 60) -> dict[str, Any]:
    """One exercise with sets, reps, rest and a cue (``dose`` kept for older screens)."""
    sets, reps = _parse_dose(dose)
    return {"name": name, "dose": dose, "sets": sets, "reps": reps, "rest_s": rest_s, "cue": CUES.get(name, "")}


def workout(phase: str, race_kind: str, variant: str, minutes: int, injuries: str | None = None) -> dict[str, Any]:
    """An opted-in strength workout: ``variant`` heavy (legs and hinge) or light (upper body
    and core). Fewer moves when the session is short."""
    ph = phase if phase in WORKOUTS else "base"
    var = variant if variant in ("heavy", "light") else "light"
    moves = list(WORKOUTS[ph][var])
    if race_kind == "run" and var == "heavy" and ph in ("base", "build"):
        moves.insert(len(moves) - 1, ("Eccentric heel drops", 2, "12 each leg", "light"))
    keep = 4 if minutes < 40 else 5 if minutes < 50 else 7
    moves = moves[:keep]
    exs = [{"name": n, "dose": f"{s}×{r}", "sets": s, "reps": r, "rest_s": REST_S[k], "cue": CUES.get(n, "")}
           for n, s, r, k in moves]
    care = care_plan(injuries)
    pre = [structured(e["name"], e["dose"], 30) for c in care for e in c["exercises"]][:3]
    detail = " ".join([WARMUP, WORKOUT_HEAD[ph],
                       "; ".join(f"{e['name']} {e['sets']}x{e['reps']}, rest {e['rest_s']}s" for e in exs)]
                      + (["Prehab: " + "; ".join(f"{e['name']} {e['dose']}" for e in pre)] if pre else []))
    return {"exercises": exs, "prehab": pre, "detail": detail[:1000],
            "title": {"heavy": "Strength: legs and core", "light": "Strength: upper body and core"}[var]}


__all__ = ["routine", "workout", "structured", "care_plan", "CARE_NOTE", "CUES"]
