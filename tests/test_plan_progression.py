"""Plans build slowly from where the athlete is (planbuilder safe-progression rules).

Grid: no data / beginner / intermediate / advanced with Garmin history x every race distance
x 6, 12, 20 and 30 week runways. Rounding to 5-minute sessions allows a little slack."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_mcp.planbuilder import (
    FITNESS_DAYS, MIN_START_H, QUALITY, RACES, build_plan, fitness_from, long_growth,
)

TODAY = date(2026, 10, 14)  # a Wednesday: week 1 is a partial week
DISTANCES = ["5k", "10k", "half marathon", "marathon", "sprint triathlon", "olympic triathlon",
             "70.3", "140.6", "century ride"]
WEEKS = [6, 12, 20, 30]


def _acts(run_week_min: float, longest: float, ride_week_min: float = 0.0, weeks: int = 6) -> list[dict]:
    out = []
    for w in range(weeks):
        mon = TODAY - timedelta(days=TODAY.weekday() + 7 * (w + 1))
        if run_week_min:
            out.append({"date": f"{mon + timedelta(days=5)} 08:00:00", "sport": "running", "duration": _hms(longest)})
            rest = max(0.0, run_week_min - longest)
            for i in range(2):
                out.append({"date": f"{mon + timedelta(days=1 + 2 * i)} 07:00:00", "sport": "running",
                            "duration": _hms(rest / 2)})
        if ride_week_min:
            out.append({"date": f"{mon + timedelta(days=6)} 09:00:00", "sport": "cycling", "duration": _hms(ride_week_min)})
    return out


def _hms(m: float) -> str:
    s = int(m * 60)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


PROFILES = {
    "no data": ({}, None),
    "beginner": ({"level": "new", "weekly_hours": 2}, None),
    "intermediate": ({"level": "intermediate", "weekly_hours": 5}, _acts(150, 60, 120)),
    "advanced": ({"level": "advanced", "weekly_hours": 9}, _acts(300, 100, 240)),
}


def _plan(profile: str, dist: str, n: int) -> tuple[dict, dict, dict | None]:
    ath, acts = PROFILES[profile]
    fit = fitness_from(acts, TODAY) if acts else None
    race = TODAY + timedelta(weeks=n - 1, days=4)
    return build_plan(dict(ath), {"distance": dist, "date": race.isoformat(), "title": "R"},
                      today=TODAY, fitness=fit), ath, fit


def _sessions(week: dict) -> list[dict]:
    return [s for _, ss in sorted(week["days"].items()) for s in ss if s["sport"] != "rest"]


def _mins(week: dict, sport: str | None = None, endurance: bool = False) -> float:
    return sum(s.get("minutes") or 0 for s in _sessions(week)
               if (sport is None or s["sport"] == sport) and (not endurance or s["sport"] in ("run", "bike", "swim", "brick")))


def _long(week: dict, sport: str) -> float:
    vals = [s.get("minutes") or 0 for s in _sessions(week)
            if s.get("kind") == "long" and s["sport"] == sport]
    for s in _sessions(week):
        if s.get("kind") == "brick" and sport == "bike":
            vals.append(s["legs"][0]["minutes"])
    return max(vals or [0])


GRID = [(p, d, n) for p in PROFILES for d in DISTANCES for n in WEEKS]


@pytest.mark.parametrize("profile,dist,n", GRID)
def test_safe_progression(profile: str, dist: str, n: int) -> None:
    plan, ath, fit = _plan(profile, dist, n)
    weeks = plan["weeks"]
    full = weeks[1:]  # week 1 is partial (the plan starts mid-week)
    ramp = [w for w in full if w["phase"] in ("base", "build", "peak")]

    # Weekly endurance volume: at most ~10% over the last full (non-recovery) week (+15'
    # rounding). Strength is a short fixed session and doesn't count toward the build.
    last = None
    for w in ramp:
        m = _mins(w, endurance=True)
        if w["recovery"]:
            assert last is None or m <= last * 0.9, (w["index"], m, last)
            continue
        if last is not None:
            assert m <= last * 1.10 + 15, f"week {w['index']}: {m}' after {last}'"
        last = m if last is None else max(last, m)

    # The first full week is not more than the athlete does now.
    first_full = _mins(full[0]) / 60.0
    declared = ath.get("weekly_hours")
    if declared:
        assert first_full <= max(declared, MIN_START_H[plan['race_kind']]) + 0.25, (first_full, declared)
    elif not fit:
        assert first_full <= 2.6, first_full  # nothing to go on: a conservative start

    # Long sessions start at (not above) the recent longest and grow slowly.
    for sport in ("run", "bike"):
        prev = None
        seen = ((fit or {}).get("sports") or {}).get(sport, {}).get("longest_min")
        cap = RACES.get(dist, RACES["other"])["long"].get(sport, 240)
        for w in weeks:
            if w["phase"] in ("taper", "race"):
                break
            lm = _long(w, sport)
            if not lm:
                continue
            assert lm <= cap + 5 + (25 if sport == "bike" else 0)
            if prev is None:
                if seen:
                    assert lm <= seen + 5, (sport, lm, seen)
                elif not declared:
                    assert lm <= 45, (sport, lm)
            elif not w["recovery"]:
                assert lm <= prev + long_growth(prev, sport) + 5, (w["index"], sport, lm, prev)
            if not w["recovery"]:
                prev = lm if prev is None else max(prev, lm)

    # Runners: the long run is at most ~35-40% of the week's running once there are 3+ runs.
    if plan["race_kind"] == "run":
        for w in ramp:
            runs = [s for s in _sessions(w) if s["sport"] == "run"]
            if len(runs) >= 3:
                assert _long(w, "run") <= 0.42 * _mins(w, "run") + 5, (w["index"], _long(w, "run"), _mins(w, "run"))

    # The first training day is short and easy.
    first = next((ss for _, ss in sorted(weeks[0]["days"].items()) if any(s["sport"] != "rest" for s in ss)), None)
    if first is None and len(weeks) > 1:
        first = next(ss for _, ss in sorted(weeks[1]["days"].items()) if any(s["sport"] != "rest" for s in ss))
    for s in first or []:
        if s["sport"] in ("run", "bike", "swim", "brick"):
            assert s.get("kind") not in QUALITY | {"long", "brick", "strides", "vo2"}, s
            assert (s.get("minutes") or 0) <= 30 or s["sport"] == "swim", s

    # Beginners (or no data): nothing hard in the first two weeks.
    if profile in ("no data", "beginner"):
        for w in weeks[:2]:
            assert not [s for s in _sessions(w) if s.get("kind") in QUALITY | {"strides"}], w["index"]

    # A recovery week at least every 4 build weeks.
    run_ = 0
    for w in weeks:
        if w["phase"] in ("base", "build"):
            run_ = 0 if w["recovery"] else run_ + 1
            assert run_ <= 4, w["index"]
    # Taper: lighter than the peak.
    peak = max((_mins(w, endurance=True) for w in weeks if w["phase"] in ("base", "build", "peak")), default=0)
    for w in weeks:
        if w["phase"] == "taper":
            assert _mins(w, endurance=True) < peak


def test_10k_in_april_regression() -> None:
    """Someone with no history asked for a 10K in April and got an 85' long run on day one."""
    plan = build_plan({}, {"distance": "10k", "date": "2027-04-18", "title": "10K"}, today=date(2026, 10, 16))
    w1, w2 = plan["weeks"][0], plan["weeks"][1]
    first = _sessions(w1)[0]
    assert first["kind"] == "easy" and first["minutes"] <= 30
    assert max(s["minutes"] for s in _sessions(w1) + _sessions(w2)) <= 35
    assert _mins(w2) <= 120  # about 1.5-2 hours in the first full week
    assert plan["start_from"] == "default"


def test_declared_hours_are_a_ceiling_and_garmin_checks_them() -> None:
    fit = fitness_from(_acts(90, 40), TODAY)
    plan = build_plan({"weekly_hours": 6, "level": "intermediate"},
                      {"distance": "half marathon", "date": (TODAY + timedelta(weeks=16)).isoformat()},
                      today=TODAY, fitness=fit)
    assert plan["start_from"] == "profile+garmin"
    assert plan["start_hours"] <= 90 / 60 * 1.3 + 0.05  # told us 6h, Garmin shows 1.5h
    assert _long(plan["weeks"][1], "run") <= 45


def test_short_runway_says_so() -> None:
    plan = build_plan({"level": "new", "weekly_hours": 2},
                      {"distance": "marathon", "date": (TODAY + timedelta(weeks=8)).isoformat()}, today=TODAY)
    assert plan["note"] and "short runway" in plan["note"]


def test_fitness_from_activities() -> None:
    fit = fitness_from(_acts(150, 60, 120), TODAY)
    assert fit is not None and fit["sports"]["run"]["longest_min"] == 60
    assert 130 <= fit["sports"]["run"]["weekly_min"] <= 150 and fit["weeks"] == 6
    assert fitness_from([], TODAY) is None
    old = [{"date": f"{TODAY - timedelta(days=FITNESS_DAYS + 3)} 07:00:00", "sport": "running", "duration": "1:00:00"}]
    assert fitness_from(old, TODAY) is None
    # A watch worn for 1 week: averaged over at least 3 weeks, so it doesn't look like a big load.
    one = [{"date": f"{TODAY - timedelta(days=2)} 07:00:00", "sport": "running", "duration": "1:30:00"}]
    assert fitness_from(one, TODAY)["sports"]["run"]["weekly_min"] == 30.0
