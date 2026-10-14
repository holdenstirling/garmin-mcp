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
    return {"exercises": [{"name": n, "dose": d} for n, d in exs],
            "prehab": [{"name": n, "dose": d} for n, d in care_exs],
            "detail": " ".join(lines)[:900]}


__all__ = ["routine", "care_plan", "CARE_NOTE"]
