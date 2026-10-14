"""Race fit: deterministic athlete-vs-event factors."""

from __future__ import annotations

from garmin_mcp.racefit import analyze, course_profile, race_elevation


def _by_id(out):
    return {f["id"]: f for f in out["factors"]}


LEADVILLE = {"name": "Leadville Trail 100 Run", "type": "trail", "distance": "ultra", "date": "2027-08-21",
             "location": "Leadville, CO",
             "info": {"distances": "100 miles", "elevation_gain": "18,000 ft", "terrain": "Rocky trails over Hope Pass"}}


def test_leadville_sea_level_athlete_is_an_altitude_risk() -> None:
    out = analyze(LEADVILLE, {"home_elevation_m": 20, "units": "imperial"})
    f = _by_id(out)
    assert f["altitude"]["impact"] == "risk"
    assert "10,150 ft" in f["altitude"]["detail"] and "12,600 ft" in f["altitude"]["detail"]
    assert "14 or more days early" in f["altitude"]["tip"] and "24 hours" in f["altitude"]["tip"]
    assert out["factors"][0]["impact"] == "risk"
    assert "altitude" in out["summary"].lower()
    assert f["night"]["impact"] == "neutral"


def test_leadville_local_athlete_altitude_helps() -> None:
    out = analyze(LEADVILLE, {"home_elevation_m": 3000, "strengths": ["climbing"], "terrain_access": ["mountains", "trails"]})
    f = _by_id(out)
    assert f["altitude"]["impact"] == "helps"
    assert f["climbing"]["impact"] == "helps"
    assert f["terrain"]["impact"] != "watch"


def test_acclimatized_flag_softens_altitude() -> None:
    f = _by_id(analyze(LEADVILLE, {"altitude_acclimatized": True, "home_elevation_m": 1600}))
    assert f["altitude"]["impact"] == "watch"


def test_flat_race_with_flats_strength_helps() -> None:
    ev = {"name": "Chicago Marathon", "type": "running", "distance": "marathon", "date": "2027-10-10",
          "info": {"distances": "42.2 km", "elevation_gain": "75 m"}}
    assert course_profile(ev)[0] == "flat"
    f = _by_id(analyze(ev, {"strengths": ["flats"]}))
    assert f["course"]["impact"] == "helps"
    assert "altitude" not in f
    # Limiter flips it.
    assert _by_id(analyze(ev, {"limiters": ["flats"]}))["course"]["impact"] == "watch"


def test_explicit_course_profile_and_elevation_win() -> None:
    ev = {"name": "Local 10K", "type": "running", "distance": "10k", "date": "2027-05-01",
          "elevation_m": 2600, "course_profile": "hilly"}
    assert race_elevation(ev)["m"] == 2600
    f = _by_id(analyze(ev, {"limiters": ["climbing"]}))
    assert f["climbing"]["impact"] == "watch" and f["altitude"]["impact"] == "risk"


def test_heat_factor_with_sweat_and_tolerance() -> None:
    ev = {"name": "Kona", "type": "triathlon", "distance": "140.6", "date": "2027-10-09",
          "info": {"typical_weather": "Hot and humid, 30-32 °C"}}
    f = _by_id(analyze(ev, {"heat_tolerance": "low", "sweat": "salty", "terrain_access": ["pool"]}))
    assert f["heat"]["impact"] == "risk"
    assert "10-14 days" in f["heat"]["tip"] and "sodium" in f["heat"]["tip"]
    assert f["open_water"]["impact"] == "watch"
    assert _by_id(analyze(ev, {"heat_tolerance": "high"}))["heat"]["impact"] == "helps"
    assert _by_id(analyze(ev, {"years_training": 1}))["duration"]["impact"] == "risk"


def test_climbing_gain_is_not_mistaken_for_altitude() -> None:
    ev = {"name": "Hill Century", "type": "cycling", "distance": "century ride", "date": "2027-06-01",
          "info": {"elevation_gain": "3,000 m", "terrain": "climbing 3,000 m of elevation gain"}}
    assert race_elevation(ev) is None
    f = _by_id(analyze(ev, {"ftp_w": 250, "weight_kg": 80}))
    assert "3.1 W/kg" in f["climbing"]["detail"]
    text = " ".join(x["detail"] + x["tip"] for x in analyze(ev, {"ftp_w": 250, "weight_kg": 80})["factors"]).lower()
    assert "lose weight" not in text and "weight loss" not in text


def test_nothing_known_gives_a_plain_summary() -> None:
    out = analyze({"name": "Mystery", "type": "other", "date": "2027-01-01"}, {})
    assert out["factors"] == [] and "Nothing stands out" in out["summary"]
