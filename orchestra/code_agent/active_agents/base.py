from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class AgentCapability:
    name: str
    description: str
    intent_keywords: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    agent_name: str
    output: str
    success: bool
    error: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


@dataclass
class AgentHealthStatus:
    agent_name: str
    status: AgentStatus
    version: str = ""
    latency_ms: float = 0.0
    detail: str = ""


class ActiveAgent(ABC):
    """Base class for all active agent drivers in Orchestra."""

    name: str = ""
    display_name: str = ""
    capabilities: list[AgentCapability] = []
    priority: int = 50  # lower = higher priority

    def can_handle(self, intent: str) -> bool:
        intent_lower = intent.lower()
        for cap in self.capabilities:
            if any(kw in intent_lower for kw in cap.intent_keywords):
                return True
        return False

    def capability_names(self) -> list[str]:
        return [c.name for c in self.capabilities]

    @abstractmethod
    async def execute(
        self, task: str, context: dict[str, Any] | None = None
    ) -> AgentResult:
        """Execute a task and return a result."""

    @abstractmethod
    async def health_check(self) -> AgentHealthStatus:
        """Return the current health/availability of this agent."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "capabilities": [
                {"name": c.name, "description": c.description}
                for c in self.capabilities
            ],
            "priority": self.priority,
        }
