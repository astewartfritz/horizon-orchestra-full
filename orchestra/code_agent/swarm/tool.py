from __future__ import annotations

import json
from typing import Any

from orchestra.code_agent.swarm.debate import DebateTeam
from orchestra.code_agent.swarm.reflection import ReflectiveAgent
from orchestra.code_agent.swarm.specialist import SpecialistTeam
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class SwarmTool(Tool):
    spec = ToolSpec(
        name="swarm",
        description="Multi-agent collaboration patterns: debate, reflect, specialists. Run teams of agents on a task.",
        parameters={
            "task": {"type": "string", "description": "Task or topic for the team"},
            "mode": {"type": "string", "description": "debate, reflect, specialists", "default": "specialists"},
            "rounds": {"type": "integer", "description": "Debate rounds (debate mode)", "default": 2},
            "roles": {"type": "string", "description": "Comma-separated roles for specialists mode", "default": ""},
        },
    )

    async def __call__(
        self, task: str = "", mode: str = "specialists",
        rounds: int = 2, roles: str = "",
    ) -> ToolResult:
        try:
            if mode == "debate":
                from orchestra.code_agent.config import AgentConfig
                agent1_cfg = AgentConfig(name="Debater1")
                agent2_cfg = AgentConfig(name="Debater2")
                from orchestra.code_agent.agent import Agent
                team = DebateTeam([Agent(agent1_cfg), Agent(agent2_cfg)], rounds=rounds)
                result = await team.debate(task)
                lines = [f"# Debate: {result.topic}\n"]
                for t in result.turns:
                    lines.append(f"\n## {t.speaker}")
                    lines.append(t.argument[:500])
                lines.append(f"\n## Consensus\n{result.consensus[:1000]}")
                return ToolResult(output="\n".join(lines))

            elif mode == "reflect":
                reflector = ReflectiveAgent()
                from orchestra.code_agent.config import AgentConfig
                reflector.agent = __import__("code_agent.agent", fromlist=[""]).Agent(AgentConfig(name="Reflector"))
                result = await reflector.solve(task)
                return ToolResult(
                    output=f"## Initial\n{result.initial_answer[:500]}\n\n"
                    f"## Critique\n{result.self_critique[:500]}\n\n"
                    f"## Improved\n{result.improved_answer[:500]}\n\n"
                    f"## Final\n{result.final_answer[:500]}"
                )

            else:
                parsed_roles = [r.strip() for r in roles.split(",") if r.strip()] if roles else None
                team = SpecialistTeam(parsed_roles)
                result = await team.collaborate(task)
                lines = [f"# Specialists\n"]
                for name, contrib in result.contributions.items():
                    lines.append(f"\n## {name}\n{contrib[:500]}")
                lines.append(f"\n## Synthesis\n{result.synthesis[:1000]}")
                return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=str(e))
