from __future__ import annotations

from orchestra.code_agent.agent_headers.models import AgentType

__all__ = [
    "AgentType",
    "HumanVsAIPolicy",
    "parse_agent_type",
]

_TYPE_HEADER = "X-Agent-Type"


def parse_agent_type(headers: dict[str, str]) -> AgentType:
    raw = headers.get(_TYPE_HEADER) or headers.get(_TYPE_HEADER.lower(), "")
    try:
        return AgentType(raw.lower().strip())
    except ValueError:
        return AgentType.HUMAN


class HumanVsAIPolicy:
    """Enforces different API policies for AI agents vs human users.

    Uses the ``X-Agent-Type`` header to distinguish AI from human
    requests, enabling tailored rate limits, audit rules, and
    feature flags.
    """

    def __init__(self) -> None:
        self._policies: dict[AgentType, dict[str, object]] = {
            AgentType.AI: {
                "max_requests_per_min": 120,
                "require_audit": True,
                "allow_batch": True,
                "max_response_size_bytes": 10 * 1024 * 1024,
            },
            AgentType.HUMAN: {
                "max_requests_per_min": 30,
                "require_audit": False,
                "allow_batch": False,
                "max_response_size_bytes": 1 * 1024 * 1024,
            },
            AgentType.HYBRID: {
                "max_requests_per_min": 60,
                "require_audit": True,
                "allow_batch": True,
                "max_response_size_bytes": 5 * 1024 * 1024,
            },
        }

    def get_policy(self, agent_type: AgentType) -> dict[str, object]:
        return self._policies.get(agent_type, self._policies[AgentType.HUMAN])

    def set_policy(self, agent_type: AgentType, policy: dict[str, object]) -> None:
        self._policies[agent_type] = policy

    @staticmethod
    def header_name() -> str:
        return _TYPE_HEADER
