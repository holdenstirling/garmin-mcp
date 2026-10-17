"""Typed race distances map to the right plan shape (an ultra is a running plan, not run + bike)."""
from garmin_mcp.planbuilder import race_key, race_profile


def test_free_text_distances() -> None:
    cases = {
        "100 mile": "ultra", "Leadville Trail 100 Run": "ultra", "50k": "ultra", "100k": "ultra",
        "ultra": "ultra", "marathon": "marathon", "Denver Half": "half marathon", "21.1k": "half marathon",
        "10K": "10k", "5k": "5k", "Boulder 70.3": "70.3", "Ironman": "140.6", "Olympic triathlon": "olympic triathlon",
        "100 mile ride": "century ride", "gravel 100": "century ride", "": "other", "something else": "other",
    }
    for typed, key in cases.items():
        assert race_key(typed) == key, typed


def test_ultra_plan_is_running_only() -> None:
    assert race_profile("Leadville Trail 100 Run")["kind"] == "run"
    assert race_profile("100 mile")["kind"] == "run"
