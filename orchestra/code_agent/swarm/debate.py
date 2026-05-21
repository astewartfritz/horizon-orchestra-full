from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig, LLMConfig


@dataclass
class DebateTurn:
    speaker: str
    argument: str
    critique: str = ""


@dataclass
class DebateResult:
    topic: str
    turns: list[DebateTurn] = field(default_factory=list)
    consensus: str = ""
    winner: str = ""


class DebateTeam:
    """Two or more agents debate a topic and reach consensus."""

    def __init__(self, agents: list[Agent], rounds: int = 2):
        self.agents = agents
        self.rounds = rounds

    async def debate(self, topic: str) -> DebateResult:
        result = DebateResult(topic=topic)
        positions: list[str] = []

        for i, agent in enumerate(self.agents):
            pos = await agent.run(
                f"You are debating: {topic}\n\nState your initial position on this topic clearly and concisely."
            )
            positions.append(pos)
            result.turns.append(DebateTurn(
                speaker=agent.config.name or f"Agent {i}",
                argument=pos,
            ))

        for rnd in range(self.rounds):
            for i, agent in enumerate(self.agents):
                others = [p for j, p in enumerate(positions) if j != i]
                critique = await agent.run(
                    f"The topic is: {topic}\n\n"
                    f"Your position: {positions[i]}\n\n"
                    f"Other positions:\n" + "\n".join(f"- {o}" for o in others) + "\n\n"
                    f"Provide constructive critique of the other positions and defend your own. "
                    f"Be concise but thorough."
                )
                result.turns[-1].critique = critique

                revised = await agent.run(
                    f"The topic is: {topic}\n\n"
                    f"Your original position: {positions[i]}\n\n"
                    f"After hearing the critiques, provide your revised position. "
                    f"Concede points where appropriate and strengthen where you still disagree."
                )
                positions[i] = revised

        consensus_prompt = (
            f"The topic was: {topic}\n\n"
            f"Final positions:\n" +
            "\n".join(f"Agent {i}: {p}" for i, p in enumerate(positions)) +
            "\n\nSynthesize these positions into a single consensus view. "
            f"Highlight areas of agreement and remaining disagreement."
        )
        result.consensus = await self.agents[0].run(consensus_prompt)
        return result


async def debate_tool(**kwargs: Any) -> str:
    """Multi-agent debate tool: two agents debate and reach consensus."""
    topic = kwargs.get("topic", "")
    if not topic:
        return "Error: topic required"
    rounds = int(kwargs.get("rounds", 2))

    cfg1 = AgentConfig(name="Debater1")
    cfg2 = AgentConfig(name="Debater2")
    agent1 = Agent(cfg1)
    agent2 = Agent(cfg2)
    team = DebateTeam([agent1, agent2], rounds=rounds)
    result = await team.debate(topic)

    lines = [f"# Debate: {result.topic}\n"]
    for t in result.turns:
        lines.append(f"## {t.speaker}")
        lines.append(t.argument[:500])
        if t.critique:
            lines.append(f"Critique: {t.critique[:300]}")
    lines.append(f"\n## Consensus\n{result.consensus[:1000]}")
    return "\n".join(lines)
