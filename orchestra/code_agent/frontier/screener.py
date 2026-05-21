from __future__ import annotations

from dataclasses import dataclass, field

from enum import Enum
from typing import Any


class SafetyLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    UNSAFE = "unsafe"


@dataclass
class ScreeningResult:
    level: SafetyLevel
    reason: str = ""
    matched_patterns: list[str] = field(default_factory=list)


class ContentScreener:
    """Layered defense: content is screened before it can influence the assistant.

    Unsafe states trigger a controlled stop instead of silent failure.
    Defenses are continuously improved using bug bounty findings and red-team exercises.
    """

    def __init__(self):
        self._blocked_patterns: list[str] = []
        self._suspicious_patterns: list[str] = []

    def block_pattern(self, pattern: str) -> None:
        self._blocked_patterns.append(pattern.lower())

    def suspicious_pattern(self, pattern: str) -> None:
        self._suspicious_patterns.append(pattern.lower())

    def screen(self, text: str) -> ScreeningResult:
        t = text.lower()

        # Check blocked patterns first (hard block)
        for pat in self._blocked_patterns:
            if pat in t:
                return ScreeningResult(
                    level=SafetyLevel.UNSAFE,
                    reason=f"Blocked pattern: {pat}",
                    matched_patterns=[pat],
                )

        # Check suspicious patterns (soft block — flag but allow with warning)
        matched = [p for p in self._suspicious_patterns if p in t]
        if matched:
            return ScreeningResult(
                level=SafetyLevel.SUSPICIOUS,
                reason=f"Suspicious patterns: {', '.join(matched)}",
                matched_patterns=matched,
            )

        return ScreeningResult(level=SafetyLevel.SAFE)
