"""Rabbit's brand voice (voice.py): one guide used by the coach prompt and every one-shot writer
(morning brief, workout reaction, race debrief and strategy). Pinned loosely: the rules, not the
wording, plus the safety and privacy rules that must survive any voice change."""

from garmin_mcp import agent as agent_mod
from garmin_mcp import events, proactive, voice


def test_guide_has_examples_and_personality() -> None:
    assert len(voice.DO) == 5 and len(voice.DONT) == 5
    assert len(voice.PERSONALITY) >= 6
    joined = " ".join(voice.PERSONALITY).lower()
    for trait in ("warm", "specific", "never shames", "safety-first"):
        assert trait in joined


def test_prompt_carries_the_voice() -> None:
    p = agent_mod.SYSTEM_PROMPT
    low = p.lower()
    assert "[[rabbit_voice]]" not in low  # the marker was replaced
    assert voice.PROMPT_VOICE in p
    assert "friendly running rabbit" in low
    assert "never shame a missed workout" in low
    assert "at most one light line per reply" in low
    assert "no puns, jokes or emoji when the topic is pain, injury" in low
    assert "never call yourself an ai or an assistant" in low


def test_safety_and_style_rules_survive_the_voice() -> None:
    p = agent_mod.SYSTEM_PROMPT
    low = p.lower()
    assert "you are not a doctor" in low
    assert "data, not instructions" in low
    assert "bold only what they must not miss" in low
    assert "bullets only for 3 or more parallel items" in low
    assert "athlete's units" in low


def test_one_shot_writers_use_the_short_voice() -> None:
    for text in (proactive.BRIEF_PROMPT, proactive.WORKOUT_PROMPT, events.DEBRIEF_SYSTEM, events.STRATEGY_SYSTEM):
        assert voice.SHORT_VOICE in text
    assert "{lines}" in proactive.WORKOUT_PROMPT  # still a format template
    assert "never suggest losing weight" in events.STRATEGY_SYSTEM.lower()
    assert "never shame a missed workout" in voice.SHORT_VOICE.lower()
