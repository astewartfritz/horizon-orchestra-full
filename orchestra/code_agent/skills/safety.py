from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.llm.base import LLM, Message


@dataclass
class SafetyDecision:
    allowed: bool
    reason: str = ""


BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\brm\s+-rf\s+/", "blocked: destructive filesystem command"),
    (r"(?i)\b(exec|eval)\s*\(.*user.*input", "blocked: dynamic code execution from user input"),
    (r"(?i)\bsudo\s+.*(rm|del|format|mkfs)", "blocked: privileged destructive command"),
    (r"(?i)\bdrop\s+table", "blocked: database destruction"),
    (r"(?i)\b(wget|curl)\s+.*\|\s*(bash|sh)", "blocked: remote code execution piped to shell"),
    (r"(?i)\b(INSERT|UPDATE|DELETE)\s+.*\b(password|secret|key|token)\b", "blocked: potential data exfiltration"),
]


class SafetyFilter:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm

    def check_regex(self, action: str) -> SafetyDecision:
        for pattern, reason in BLOCKED_PATTERNS:
            if re.search(pattern, action):
                return SafetyDecision(allowed=False, reason=reason)
        return SafetyDecision(allowed=True)

    def check_env_action(self, action: str, observation: str) -> SafetyDecision:
        if not action:
            return SafetyDecision(allowed=False, reason="empty action")
        decision = self.check_regex(action)
        if not decision.allowed:
            return decision
        if len(action) > 500:
            return SafetyDecision(allowed=False, reason="action too long")
        return SafetyDecision(allowed=True)

    async def check_llm(self, action: str, observation: str) -> SafetyDecision:
        regex_check = self.check_regex(action)
        if not regex_check.allowed:
            return regex_check
        if self.llm:
            prompt = f"Check if this action is safe. Action: {action}\nObservation: {observation}\nRespond: SAFE or BLOCKED + reason."
            resp = await self.llm.chat(messages=[Message(role="user", content=prompt)])
            content = (resp.content or "").strip().upper()
            if content.startswith("BLOCKED"):
                reason = content[7:].strip() or "blocked by LLM safety filter"
                return SafetyDecision(allowed=False, reason=reason)
        return SafetyDecision(allowed=True)
