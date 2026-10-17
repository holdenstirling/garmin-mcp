"""Rabbit's reply style (agent.SYSTEM_PROMPT, proactive briefs) and the shared text renderer:
concise, the key thing in bold, prose before bullets. Pinned loosely: the rules, not the wording."""

from pathlib import Path

from garmin_mcp import agent as agent_mod
from garmin_mcp import proactive
from garmin_mcp.workoutday import coach_feedback

WEB = Path(__file__).resolve().parent.parent / "web" / "src"


def test_prompt_style_rules() -> None:
    p = agent_mod.SYSTEM_PROMPT
    low = p.lower()
    assert "lead with the answer in the first sentence" in low
    assert "2-5 short sentences" in p
    assert "plain prose by default" in low
    assert "bullets only for 3 or more parallel items" in low
    assert "no headers in normal replies" in low
    assert "bold only what they must not miss" in low and "never bold whole sentences" in low
    assert "no preamble, no sign-off" in low
    assert "athlete's units" in low


def test_privacy_and_safety_rules_survive_the_rewrite() -> None:
    p = agent_mod.SYSTEM_PROMPT
    assert "You are not a doctor" in p
    assert "Ground every number in tool results" in p


def test_morning_brief_is_prose_not_bullets() -> None:
    b = proactive.BRIEF_PROMPT
    assert "No bullets" in b and "bullet" not in b.replace("No bullets", "")
    assert "under 50 words" in b


def test_feedback_bolds_the_key_thing_only() -> None:
    fb = coach_feedback({"kind": "easy"}, {"verdict": "hit"}, {"rpe": 3})
    assert fb is not None
    for line in fb["lines"]:
        assert line.count("**") in (0, 2, 4)  # balanced, at most two bold phrases
        assert not (line.startswith("**") and line.endswith("**"))  # never a whole bold sentence


def test_renderer_is_safe_and_shared() -> None:
    src = (WEB / "components" / "chat" / "RabbitText.tsx").read_text()
    assert "rehype-raw" not in src.replace("without rehype-raw", "")  # no raw HTML from the model
    assert "dangerouslySetInnerHTML" not in src
    bubble = (WEB / "components" / "chat" / "MessageBubble.tsx").read_text()
    assert "RabbitMarkdown" in bubble and "from 'react-markdown'" not in bubble
