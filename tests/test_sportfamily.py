"""sportfamily: which numbers a workout card shows, by sport family."""

from __future__ import annotations

from datetime import date

from garmin_mcp import activitypage as ap
from garmin_mcp import sportfamily as sf
from garmin_mcp.community import LEG_FIELDS, workout_card

DAY = date(2026, 10, 18)


def test_family_reads_garmin_types_before_the_coarse_sport() -> None:
    assert sf.family("bike", "indoor_cycling") == "indoor_ride"
    assert sf.family("bike", "virtual_ride") == "indoor_ride"
    assert sf.family("bike", "mountain_biking") == "ride"
    assert sf.family("run", "trail_running") == "run"
    assert sf.family("run", "treadmill_running") == "run"
    assert sf.family("hike", "walking") == "walk"
    assert sf.family("hike", "hiking") == "hike"
    assert sf.family("swim", "open_water_swimming") == "swim"
    assert sf.family("strength", "strength_training") == "strength"
    assert sf.family("other", "yoga") == "mind"
    assert sf.family("other", "pilates") == "mind"
    assert sf.family("other", "hiit") == "hiit"
    assert sf.family("paddle", "indoor_rowing") == "row"
    assert sf.family("paddle", "stand_up_paddleboarding") == "paddle"
    assert sf.family("ski", "resort_skiing_snowboarding_ws") == "ski"
    assert sf.family("climb", "indoor_climbing") == "climb"
    assert sf.family("other", "multi_sport") == "brick"
    assert sf.family("bike", "track_cycling") == "ride"
    assert sf.family("other", "golf") == "other"
    assert sf.family(None, None) == "other"
    assert sf.family("run") == "run" and sf.family("bike") == "ride"


def test_each_family_gets_only_its_own_rate() -> None:
    assert sf.pace_fields("run", 10, 50) == {"pace_s_km": 300}
    assert sf.pace_fields("walk", 5, 60) == {"pace_s_km": 720}
    assert sf.pace_fields("ride", 40, 80) == {"speed_kmh": 30.0}
    assert sf.pace_fields("indoor_ride", 30, 60) == {"speed_kmh": 30.0}
    assert sf.pace_fields("swim", 2, 40) == {"pace_s_100m": 120}
    assert sf.pace_fields("row", 5, 20) == {"pace_s_500m": 120}
    for fam in ("ski", "strength", "mind", "hiit", "climb", "brick", "other"):
        assert sf.pace_fields(fam, 10, 60) == {}, fam
    assert sf.pace_fields("indoor_ride", 0, 60) == {}  # a trainer ride with no distance: time only
    assert [f for f in sf.FAMILIES if sf.splits_ok(f)] == ["run", "walk", "hike", "swim"]


def _act(aid: int, sport: str, *, km: float | None = None, minutes: int = 60, **kw: object) -> dict:
    return {"activity_id": aid, "date": f"{DAY.isoformat()} 07:00:00", "name": "Morning", "sport": sport,
            "duration": f"{minutes // 60}:{minutes % 60:02d}:00", "distance_km": km, **kw}


def test_cards_carry_the_numbers_that_fit() -> None:
    acts = [
        _act(1, "running", km=10, minutes=50, elevation_gain_m=40),
        _act(2, "indoor_cycling", km=None, minutes=45, elevation_gain_m=0),
        _act(3, "yoga", km=0.4, minutes=60),
        _act(4, "strength_training", minutes=40, total_sets=18, total_reps=150, elevation_gain_m=12),
        _act(5, "indoor_rowing", km=6, minutes=24),
        _act(6, "resort_skiing_snowboarding_ws", km=30, minutes=180, elevation_loss_m=2400),
        _act(7, "lap_swimming", km=2, minutes=40),
    ]
    run = workout_card(acts, 1, DAY)
    assert run["family"] == "run" and run["pace_s_km"] == 300 and "speed_kmh" not in run
    trainer = workout_card(acts, 2, DAY)
    assert trainer["family"] == "indoor_ride" and trainer["km"] is None and trainer["climb_m"] is None
    assert not {"speed_kmh", "pace_s_km"} & set(trainer)
    yoga = workout_card(acts, 3, DAY)
    assert yoga["family"] == "mind" and yoga["km"] is None and not {"pace_s_km", "speed_kmh"} & set(yoga)
    gym = workout_card(acts, 4, DAY)
    assert gym["family"] == "strength" and gym["sets"] == 18 and gym["reps"] == 150
    assert gym["km"] is None and gym["climb_m"] is None
    row = workout_card(acts, 5, DAY)
    assert row["family"] == "row" and row["pace_s_500m"] == 120
    ski = workout_card(acts, 6, DAY)
    assert ski["family"] == "ski" and ski["vertical_m"] == 2400 and not {"pace_s_km", "speed_kmh"} & set(ski)
    swim = workout_card(acts, 7, DAY)
    assert swim["family"] == "swim" and swim["pace_s_100m"] == 120


def test_a_multisport_card_lists_each_leg_with_its_own_rate() -> None:
    acts = [
        _act(10, "multi_sport", km=40.5, minutes=120, multisport={"is_parent": True}),
        _act(11, "open_water_swimming", km=1.5, minutes=30, multisport={"parent_id": 10}),
        _act(12, "transition", minutes=3, multisport={"parent_id": 10}),
        _act(13, "cycling", km=30, minutes=60, multisport={"parent_id": 10}),
        _act(14, "running", km=9, minutes=45, multisport={"parent_id": 10}),
    ]
    card = workout_card(acts, 10, DAY)
    assert card["family"] == "brick" and "pace_s_km" not in card
    assert [lg["family"] for lg in card["legs"]] == ["swim", "ride", "run"]
    assert card["legs"][0]["pace_s_100m"] == 120 and card["legs"][1]["speed_kmh"] == 30.0
    assert card["legs"][2]["pace_s_km"] == 300
    assert all(set(lg) <= set(LEG_FIELDS) for lg in card["legs"])


def test_activity_page_keeps_only_fitting_numbers() -> None:
    yoga = ap.build_view(_act(20, "yoga", km=0.3, minutes=60, avg_speed_kmh=0.3))
    assert yoga["family"] == "mind" and not {"km", "speed_kmh", "pace_s_per_km"} & set(yoga["numbers"])
    run = ap.build_view(_act(21, "running", km=10, minutes=50, avg_speed_kmh=12.0, avg_pace_per_km="5:00"))
    assert "speed_kmh" not in run["numbers"] and run["numbers"]["pace_s_per_km"] == 300
    row = ap.build_view(_act(22, "indoor_rowing", km=6, minutes=24, moving_duration="0:24:00", avg_speed_kmh=15.0))
    assert row["numbers"]["pace_s_per_500m"] == 120 and "speed_kmh" not in row["numbers"]
    ride = ap.build_view(_act(23, "road_biking", km=40, minutes=80, avg_speed_kmh=30.0))
    assert ride["family"] == "ride" and ride["numbers"]["speed_kmh"] == 30.0


def test_titles_name_the_activity() -> None:
    assert sf.title("indoor_ride") == "Indoor ride"
    assert sf.title("mind", "pilates") == "Pilates"
    assert sf.title("mind", "yoga") == "Yoga"
    assert sf.title("ski", "snowboarding") == "Snowboard"
    assert sf.title("other") == "Workout"
