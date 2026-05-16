from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from code_agent.agent import Agent
from code_agent.config import AgentConfig


@dataclass
class SpecialistRole:
    name: str
    expertise: str
    instructions: str = ""


SPECIALIST_ROLES = {
    "architect": SpecialistRole(
        "Architect",
        "system design, architecture, trade-offs",
        "Focus on high-level architecture, design patterns, and system trade-offs."
    ),
    "engineer": SpecialistRole(
        "Engineer",
        "implementation, coding, testing",
        "Focus on concrete implementation, code quality, and testability."
    ),
    "reviewer": SpecialistRole(
        "Reviewer",
        "code review, security, best practices",
        "Focus on security, performance, edge cases, and adherence to best practices."
    ),
    "debugger": SpecialistRole(
        "Debugger",
        "debugging, root cause analysis",
        "Focus on identifying root causes, reproducing issues, and systematic debugging."
    ),
    "docs": SpecialistRole(
        "Docs",
        "documentation, explanation, communication",
        "Focus on clear documentation, API references, and user-facing explanations."
    ),
}


@dataclass
class SpecialistTeamResult:
    task: str
    contributions: dict[str, str] = field(default_factory=dict)
    synthesis: str = ""


class SpecialistTeam:
    """Team of specialist agents collaborating on a task."""

    def __init__(self, roles: list[str] | None = None):
        self.roles = [SPECIALIST_ROLES[r] for r in (roles or list(SPECIALIST_ROLES.keys())) if r in SPECIALIST_ROLES]

    async def collaborate(self, task: str) -> SpecialistTeamResult:
        result = SpecialistTeamResult(task=task)

        contributions: dict[str, str] = {}
        for role in self.roles:
            agent_cfg = AgentConfig(name=role.name)
            agent = Agent(agent_cfg)
            ctx = "\n".join(
                f"- {r.name}: {r.expertise}\n  {contributions.get(r.name, '(pending)')[:200]}"
                for r in self.roles
            )
            contribution = await agent.run(
                f"Task: {task}\n\n"
                f"Your role: {role.name} ({role.expertise})\n"
                f"{role.instructions}\n\n"
                f"Context from other specialists:\n{ctx}\n\n"
                f"Provide your specialist contribution to this task."
            )
            contributions[role.name] = contribution

        result.contributions = contributions

        synth_agent = Agent(AgentConfig(name="Synthesizer"))
        contribs = "\n\n".join(
            f"=== {name} ===\n{text}" for name, text in contributions.items()
        )
        result.synthesis = await synth_agent.run(
            f"Task: {task}\n\n"
            f"Specialist contributions:\n{contribs}\n\n"
            f"Synthesize these into a coherent final output that addresses the original task. "
            f"Resolve any conflicts between specialist views."
        )

        return result


async def specialist_team_tool(**kwargs: Any) -> str:
    """Collaborative specialist team tool: multiple expert agents work on a task."""
    task = kwargs.get("task", "")
    if not task:
        return "Error: task required"
    roles_str = kwargs.get("roles", "")
    roles = [r.strip() for r in roles_str.split(",") if r.strip()] if roles_str else None

    team = SpecialistTeam(roles)
    result = await team.collaborate(task)

    lines = [f"# Specialist Team: {result.task}\n"]
    for name, contrib in result.contributions.items():
        lines.append(f"## {name}\n{contrib[:500]}")
    lines.append(f"\n## Synthesis\n{result.synthesis[:1000]}")
    return "\n".join(lines)
