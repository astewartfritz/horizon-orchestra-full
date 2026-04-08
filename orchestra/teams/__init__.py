"""Horizon Orchestra — Multi-Orchestrator Team Engine.

This package provides a multi-agent team architecture where multiple
specialised Orchestra instances collaborate on complex tasks, hand off
work across organisations, and share context securely.

Core components
---------------
- :class:`OrchestraTeam` — Coordinator + specialist fleet.  The main
  entry-point: decompose a goal → assign subtasks → execute in parallel
  → synthesise results.
- :class:`TeamConfig` — Configuration dataclass for team behaviour.
- :class:`Specialist` — Descriptor for a single specialist agent.
- :class:`TeamTask` — Unit of work assigned to a specialist.
- :class:`HandoffPacket` — Structured data passed between agents.
- :class:`ContextBus` — Pub/sub + direct messaging bus for inter-agent
  communication with asyncio.Queue delivery.
- :class:`TeamMemory` — Shared persistent memory with team-aware
  namespacing, built on top of :mod:`orchestra.memory`.
- :class:`InterAgentTrust` — HMAC-signed trust negotiation and
  capability gating between agents.

Quick start::

    from orchestra.teams import OrchestraTeam, TeamConfig

    team = OrchestraTeam(TeamConfig(name="my-team"))
    await team.add_specialist("coder", capabilities=["python", "rust"])
    result = await team.run("Build a CLI tool that …")

Pre-built teams::

    from orchestra.teams.pre_built_teams import coding_team, research_team
    team = coding_team()
    result = await team.run("Implement a REST API for …")
"""

from __future__ import annotations

from .team import (
    OrchestraTeam,
    TeamConfig,
    Specialist,
    TeamTask,
    HandoffPacket,
)
from .context_bus import ContextBus, ContextMessage
from .team_memory import TeamMemory, MemoryEntry
from .inter_agent_trust import InterAgentTrust, TrustLevel

__all__ = [
    # team.py
    "OrchestraTeam",
    "TeamConfig",
    "Specialist",
    "TeamTask",
    "HandoffPacket",
    # context_bus.py
    "ContextBus",
    "ContextMessage",
    # team_memory.py
    "TeamMemory",
    "MemoryEntry",
    # inter_agent_trust.py
    "InterAgentTrust",
    "TrustLevel",
]
