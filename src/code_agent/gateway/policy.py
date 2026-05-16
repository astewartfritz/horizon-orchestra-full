from __future__ import annotations

from enum import Enum
from typing import Any


class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"


class PolicyEngine:
    """Governs tool availability and side-effecting actions per session or agent.

    Enforces allow/deny policies, sandbox rules, and least-privilege per skill/agent.
    """

    def __init__(self):
        self._denied_actions: list[str] = []
        self._allowed_actions: list[str] = []
        self._denied_senders: list[str] = []
        self._sandbox_required: list[str] = []
        self._rate_limits: dict[str, int] = {}  # action → max per minute

    def deny_action(self, action: str) -> None:
        self._denied_actions.append(action)

    def allow_action(self, action: str) -> None:
        self._allowed_actions.append(action)

    def require_sandbox(self, action: str) -> None:
        self._sandbox_required.append(action)

    def deny_sender(self, sender: str) -> None:
        self._denied_senders.append(sender)

    def set_rate_limit(self, action: str, max_per_minute: int) -> None:
        self._rate_limits[action] = max_per_minute

    def check(self, content: str, sender: str = "user", session_id: str = "") -> PolicyDecision:
        if sender in self._denied_senders:
            return PolicyDecision.DENY
        return PolicyDecision.ALLOW

    def check_tool(self, tool_name: str, session_id: str = "") -> PolicyDecision:
        if tool_name in self._denied_actions:
            return PolicyDecision.DENY
        if tool_name in self._sandbox_required:
            return PolicyDecision.REVIEW
        return PolicyDecision.ALLOW
