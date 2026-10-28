"""HYROX: the race format, station sessions for built plans, a pacing guide and race-day notes.

The race is 8 x 1 km run, each followed by a station, in this order:
SkiErg 1000 m, sled push 50 m, sled pull 50 m, burpee broad jumps 80 m, rowing 1000 m,
farmers carry 200 m, sandbag lunges 100 m, wall balls 100 reps. Divisions: open, pro,
doubles, relay. Station weights differ by division and sex, so rabbt never states them:
the athlete checks their division on hyrox.com.

Station work is race-specific training: a HYROX plan always has it, whether or not the
athlete opted into (optional, gym) strength workouts (``coaching.strength_on``).
"""

from __future__ import annotations

from typing import Any

STATIONS: list[tuple[str, str]] = [
    ("SkiErg", "1000 m"), ("Sled push", "50 m"), ("Sled pull", "50 m"),
    ("Burpee broad jumps", "80 m"), ("Rowing", "1000 m"), ("Farmers carry", "200 m"),
    ("Sandbag lunges", "100 m"), ("Wall balls", "100 reps"),
]
DIVISIONS = ("open", "pro", "doubles", "relay")
WEIGHTS_NOTE = "Check your division's weights on hyrox.com."
# Variants of a station session (planbuilder sport "strength", kind "hyrox").
VARIANTS = ("stations", "compromised", "half_sim", "full_sim", "primer")
HARD = ("compromised", "half_sim", "full_sim")
TITLES = {"stations": "HYROX stations", "compromised": "Compromised running",
          "half_sim": "HYROX half simulation", "full_sim": "HYROX full simulation",
          "primer": "HYROX station primer"}

# (name, sets, reps, rest_s, cue). Cues carry the no-gym substitute.
_SUB = {
    "SkiErg": "No SkiErg: band pull-downs or a rower.",
    "Sled push": "No sled: push a loaded car or prowler, or do hill sprints.",
    "Sled pull": "No sled: heavy backward drag with a rope, or band rows walking back.",
    "Burpee broad jumps": "Step the jump if your knees complain.",
    "Rowing": "No rower: SkiErg or a fast bike.",
    "Farmers carry": "Dumbbells, kettlebells or two full bags.",
    "Sandbag lunges": "No sandbag: a backpack with books, or a held dumbbell.",
    "Wall balls": "No wall ball: thrusters with a dumbbell, or air squats with a press.",
}
_STATION_SETS: dict[str, dict[str, list[tuple[str, int, str, int, str]]]] = {
    "base": {
        "a": [("SkiErg", 4, "250 m", 60, "Long pulls, hinge at the hips."),
              ("Sled push", 4, "15 m", 90, "Low hips, short fast steps."),
              ("Wall balls", 4, "15", 60, "Full squat, catch high."),
              ("Farmers carry", 3, "50 m", 60, "Tall posture, quick feet.")],
        "b": [("Rowing", 4, "250 m", 60, "Legs, then body, then arms."),
              ("Sled pull", 4, "15 m", 90, "Lean back, hand over hand."),
              ("Sandbag lunges", 3, "20 m", 75, "Knee kisses the floor, chest up."),
              ("Burpee broad jumps", 3, "10 m", 75, "Land soft, keep a rhythm.")],
    },
    "build": {
        "a": [("SkiErg", 3, "500 m", 75, "Hold your race pace, not faster."),
              ("Sled push", 4, "25 m", 90, "Drive through the balls of your feet."),
              ("Wall balls", 4, "25", 60, "Break into sets of 10 to 15 before you have to."),
              ("Sandbag lunges", 3, "25 m", 75, "Steady, no stopping mid set.")],
        "b": [("Rowing", 3, "500 m", 75, "Steady stroke rate, about 26 to 30."),
              ("Sled pull", 4, "25 m", 90, "Walk back fast between pulls."),
              ("Burpee broad jumps", 3, "20 m", 75, "Same rhythm every rep."),
              ("Farmers carry", 3, "100 m", 60, "Grip it and go, no set downs.")],
    },
}


def _ex(name: str, sets: int, reps: str, rest_s: int, cue: str) -> dict[str, Any]:
    sub = _SUB.get(name, "")
    full = " ".join(x for x in (cue, sub) if x)
    return {"name": name, "sets": sets, "reps": reps, "rest_s": rest_s, "cue": full,
            "dose": f"{sets}×{reps}"}


def station_session(variant: str, phase: str, minutes: int, *, week: int = 0,
                    division: str | None = None) -> dict[str, Any]:
    """Title, exercises and detail for one HYROX session. ``week`` alternates the station
    sets (a/b) so the week has variety."""
    var = variant if variant in VARIANTS else "stations"
    ph = "base" if phase == "base" else "build"
    if var == "stations":
        moves = _STATION_SETS[ph]["a" if week % 2 == 0 else "b"]
        exs = [_ex(*m) for m in moves]
        head = "Station skills and strength endurance. Smooth reps, steady breathing."
    elif var == "compromised":
        rounds = 3 if minutes < 50 else 4
        picks = STATIONS[(week * 2) % 8:(week * 2) % 8 + rounds] or STATIONS[:rounds]
        if len(picks) < rounds:
            picks = picks + STATIONS[:rounds - len(picks)]
        exs = []
        for name, full in picks:
            part = {"1000 m": "500 m", "50 m": "25 m", "80 m": "40 m", "200 m": "100 m",
                    "100 m": "50 m", "100 reps": "50 reps"}.get(full, full)
            exs.append(_ex(f"1 km run, then {name}", 1, part, 60, "Run the 1 km at goal race pace, go straight into the station."))
        head = (f"{rounds} rounds: 1 km run at goal race pace straight into a station, 1 minute easy between rounds. "
                "Learning to run on tired legs is the race.")
    elif var in ("half_sim", "full_sim"):
        picks = STATIONS if var == "full_sim" else STATIONS[:4]
        exs = [_ex(f"1 km run, then {n}", 1, d, 0, "Race order, race pace, no rest beyond moving between.")
               for n, d in picks]
        head = ("Full race simulation: all 8 runs and stations in race order. Practise pacing, fueling and transitions."
                if var == "full_sim" else
                "Half simulation: the first 4 runs and stations in race order at goal pace.")
    else:  # primer
        exs = [_ex("Wall balls", 2, "10", 60, "Easy and crisp."),
               _ex("SkiErg", 2, "200 m", 60, "Easy, just the feel."),
               _ex("Sled push", 2, "10 m", 90, "Light, quick steps.")]
        head = "Race week primer: a few easy reps to keep the movements sharp. Stop well before tired."
    detail = " ".join([head, "; ".join(f"{e['name']} {e['sets']}x{e['reps']}" for e in exs), WEIGHTS_NOTE])
    if division == "doubles":
        detail += " Doubles: you split station reps with your partner and run every 1 km together."
    elif division == "relay":
        detail += " Relay: each of you runs 2 x 1 km and does 2 stations; train your legs hard."
    return {"title": TITLES[var], "exercises": exs, "detail": detail[:1000], "variant": var}


# ------------------------------------------------------------- pacing ---
# Rough share of an Open finish (estimate): runs ~52%, stations ~40%, roxzone (moving
# between run and station areas) ~8%. Stations by relative time.
RUN_SHARE, ROX_SHARE = 0.52, 0.08
STATION_WEIGHT = {"SkiErg": 4.5, "Sled push": 3.5, "Sled pull": 4.5, "Burpee broad jumps": 4.5,
                  "Rowing": 4.75, "Farmers carry": 2.0, "Sandbag lunges": 4.5, "Wall balls": 6.0}


def parse_time(v: Any) -> int | None:
    """"1:15:00" / "75:00" -> seconds."""
    if not isinstance(v, str):
        return None
    try:
        p = [int(x) for x in v.strip().split(":")]
    except ValueError:
        return None
    if len(p) == 3:
        return p[0] * 3600 + p[1] * 60 + p[2]
    if len(p) == 2:
        return p[0] * 60 + p[1]
    return None


def fmt(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pacing(target_time: Any, division: str | None = None) -> dict[str, Any] | None:
    """An estimate splitting the target into 8 runs, 8 stations and roxzone. The parts add up
    to the target exactly. None without a usable target."""
    total = parse_time(target_time)
    if not total or total < 30 * 60 or total > 4 * 3600:
        return None
    run_total = round(total * RUN_SHARE)
    rox = round(total * ROX_SHARE)
    st_total = total - run_total - rox
    per_run = run_total // 8
    runs = [per_run] * 8
    runs[-1] += run_total - per_run * 8
    wsum = sum(STATION_WEIGHT.values())
    st = [round(st_total * STATION_WEIGHT[n] / wsum) for n, _ in STATIONS]
    st[-1] += st_total - sum(st)
    legs = [{"run": f"Run {i + 1}: 1 km", "run_s": runs[i], "run_time": fmt(runs[i]),
             "station": f"{STATIONS[i][0]} {STATIONS[i][1]}", "station_s": st[i], "station_time": fmt(st[i])}
            for i in range(8)]
    note = ("An estimate from typical race splits: about half your time is running, around 40% "
            "stations and the rest is the roxzone, moving between them. Your strengths will shift it.")
    if division == "doubles":
        note += " In doubles you share station work, so stations usually go faster."
    elif division == "relay":
        note += " In a relay each person covers 2 runs and 2 stations."
    return {"total_s": total, "total": fmt(total), "run_pace_per_km": fmt(per_run), "roxzone_s": rox,
            "roxzone": fmt(rox), "legs": legs, "note": note, "estimate": True}


RACE_DAY = ("HYROX race day. Eat a carb-rich meal 2 to 3 hours before, sip water, and warm up "
            "with an easy jog and a few wall balls. Start the first 1 km slower than you want. "
            "For a finish over about 90 minutes, a gel around halfway helps. " + WEIGHTS_NOTE)
FUEL_NOTE = ("A HYROX race is about 60 to 100 minutes of hard work: carbs before, water at the "
             "roxzone, and a gel around halfway if you'll be out there more than 90 minutes.")

__all__ = ["DIVISIONS", "FUEL_NOTE", "HARD", "RACE_DAY", "STATIONS", "TITLES", "VARIANTS", "WEIGHTS_NOTE",
           "fmt", "pacing", "parse_time", "station_session"]
