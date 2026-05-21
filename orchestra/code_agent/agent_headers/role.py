from __future__ import annotations

from orchestra.code_agent.agent_headers.models import AgentRole

__all__ = [
    "AgentRole",
    "RolePolicy",
    "parse_agent_role",
]

_ROLE_HEADER = "X-Agent-Role"


def parse_agent_role(headers: dict[str, str]) -> AgentRole:
    raw = headers.get(_ROLE_HEADER) or headers.get(_ROLE_HEADER.lower(), "")
    try:
        return AgentRole(raw.lower().strip())
    except ValueError:
        return AgentRole.SYSTEM


class RolePolicy:
    """Applies role-specific response tailoring based on ``X-Agent-Role``.

    Different agent roles (customer service, analytics, etc.) may need
    different response formats, verbosity, or data scopes.
    """

    def __init__(self) -> None:
        self._response_config: dict[AgentRole, dict[str, object]] = {
            AgentRole.CUSTOMER_SERVICE: {
                "verbosity": "low",
                "include_internal_ids": False,
                "include_timestamps": True,
            },
            AgentRole.ANALYTICS: {
                "verbosity": "high",
                "include_internal_ids": True,
                "include_timestamps": True,
            },
            AgentRole.DEVELOPER: {
                "verbosity": "high",
                "include_internal_ids": True,
                "include_timestamps": True,
            },
            AgentRole.ADMIN: {
                "verbosity": "full",
                "include_internal_ids": True,
                "include_timestamps": True,
            },
            AgentRole.SYSTEM: {
                "verbosity": "normal",
                "include_internal_ids": False,
                "include_timestamps": True,
            },
        }

    def get_config(self, role: AgentRole) -> dict[str, object]:
        return self._response_config.get(role, self._response_config[AgentRole.SYSTEM])

    def set_config(self, role: AgentRole, config: dict[str, object]) -> None:
        self._response_config[role] = config

    @staticmethod
    def header_name() -> str:
        return _ROLE_HEADER
