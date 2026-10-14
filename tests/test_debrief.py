"""After-race debrief: saved on the event and carried into Rabbit's context."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from garmin_mcp.coaching import CoachError
from tests.test_agent import env  # noqa: F401  (fixture)


def test_debrief_saves_and_carries_forward(env) -> None:
    agent, _ = env.agent([])
    today = agent._now("u").date()
    past = agent.events.create("u", {"name": "Spring Half", "type": "running", "distance": "half marathon",
                                     "date": (today - timedelta(days=3)).isoformat()})
    future = agent.events.create("u", {"name": "Later", "date": (today + timedelta(days=30)).isoformat()})
    seen = {}

    async def fake_structured(system, prompt, tool):
        seen["prompt"] = prompt
        return {"summary": "Strong first half, faded after 15 km.", "went_well": ["Pacing early"],
                "work_on": ["Late-race fueling"], "learnings": ["Practise 60 g/h on long runs"]}
    agent._backend.structured = fake_structured  # type: ignore[attr-defined]
    out = asyncio.run(agent.debrief("u", past["id"], result="1:44:10", feel=4, notes="hot day"))
    assert out["learnings"] == ["Practise 60 g/h on long runs"] and out["feel"] == 4
    assert '"result": "1:44:10"' in seen["prompt"] and "hot day" in seen["prompt"]
    ev = agent.events.get("u", past["id"])
    assert ev["debrief"]["summary"].startswith("Strong") and ev["result"] == "1:44:10"
    ctx = agent.coach.context_block("u", agent._now("u"), None)
    assert "Practise 60 g/h on long runs" in ctx
    with pytest.raises(CoachError, match="once the race is done"):
        asyncio.run(agent.debrief("u", future["id"]))
