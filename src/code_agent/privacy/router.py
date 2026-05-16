from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SensitivityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RouteDecision:
    query: str
    sensitivity: SensitivityLevel
    recommended_provider: str
    recommended_model: str
    reason: str
    local_fallback: Optional[str] = None


_SENSITIVE_PATTERNS = {
    SensitivityLevel.CRITICAL: [
        r"\b(password|passwd|secret|api[_-]?\s*key|token|auth|credential)\s*[:=]\s*\S+",
        r"\b(password|passwd|secret|api[_-]?\s*key|token)\s+is\s+\S+",
        r"\b(ssh[-_]?key|private[-_]?key|pem|pkcs|rsa|dsa)\b",
        r"\b(credit[-_\s]?card|ssn|social[-_\s]?security|tax[-_\s]?id|passport)\b",
        r"\b(bank[-_]?account|routing[-_]?number|iban|swift|bic)\b",
        r"\b(database[-_]?url|jdbc|mongodb(?:\+srv)?:\/\/\S+)\b",
        r"\b(AKIA[0-9A-Z]{16})\b",
        r"\b(ghp_|gho_|ghu_|ghs_|ghr_)[0-9a-zA-Z]{36}\b",
        r"\bsk-[0-9a-zA-Z]{16,}\b",
    ],
    SensitivityLevel.HIGH: [
        r"\b(employee|salary|review|performance|hr[-_]?)\b",
        r"\b(contract|nda|non[-_]?disclosure|proprietary)\b",
        r"\b(internal[-_]?only|confidential|restricted)\b",
        r"\b(health|medical|patient|diagnosis|treatment)\b",
        r"\b(legal|attorney|lawyer|litigation|settlement)\b",
        r"\b(financial|revenue|profit|earnings|quarterly[-_]?report)\b",
        r"\b(customer[-_]?(data|list|pii|record))\b",
    ],
    SensitivityLevel.MEDIUM: [
        r"\b(project[-_]?plan|roadmap|strategy|initiative)\b",
        r"\b(budget|forecast|allocation|spending)\b",
        r"\b(vendor|supplier|partner|contractor)\b",
        r"\b(architecture|design[-_]?doc|specification|requirement)\b",
        r"\b(deploy|release|rollout|migration)\b",
    ],
}


class PrivacyRouter:
    def __init__(
        self,
        local_provider: str = "ollama",
        local_model: str = "llama3",
        cloud_provider: str = "openai",
        cloud_model: str = "gpt-4o",
        sensitive_provider: str = "ollama",
        sensitive_model: str = "nemo-mistral",
    ):
        self.local_provider = local_provider
        self.local_model = local_model
        self.cloud_provider = cloud_provider
        self.cloud_model = cloud_model
        self.sensitive_provider = sensitive_provider
        self.sensitive_model = sensitive_model
        self._learned_patterns: list[tuple[re.Pattern, SensitivityLevel]] = []

    def classify(self, query: str) -> RouteDecision:
        ql = query.lower()

        for pattern, level in self._learned_patterns:
            if pattern.search(ql):
                return self._make_decision(query, level, f"Matched learned pattern: {pattern.pattern}")

        for level in [SensitivityLevel.CRITICAL, SensitivityLevel.HIGH, SensitivityLevel.MEDIUM]:
            for pattern in _SENSITIVE_PATTERNS.get(level, []):
                if re.search(pattern, ql):
                    return self._make_decision(query, level, f"Query contains sensitive data ({level.value})")

        if any(kw in ql for kw in ["public", "open source", "tutorial", "example", "hello world", "wikipedia", "docs", "documentation"]):
            return self._make_decision(query, SensitivityLevel.LOW, "Public/open content — safe for cloud")

        complexity_score = 0
        complexity_score += len(query.split())
        complexity_score += query.count("?")
        complexity_score += len(re.findall(r"\b(why|how|explain|compare|analyze|design|architect|plan)\b", ql)) * 5

        if complexity_score > 30:
            return self._make_decision(query, SensitivityLevel.LOW, f"High complexity ({complexity_score}) — needs cloud capability")

        return self._make_decision(query, SensitivityLevel.LOW, "Default — low sensitivity, routing to local")

    def _make_decision(self, query: str, level: SensitivityLevel, reason: str) -> RouteDecision:
        if level in (SensitivityLevel.CRITICAL, SensitivityLevel.HIGH):
            return RouteDecision(
                query=query,
                sensitivity=level,
                recommended_provider=self.sensitive_provider,
                recommended_model=self.sensitive_model,
                reason=reason,
                local_fallback=self.local_model,
            )
        elif level == SensitivityLevel.MEDIUM:
            return RouteDecision(
                query=query,
                sensitivity=level,
                recommended_provider=self.local_provider,
                recommended_model=self.local_model,
                reason=reason,
                local_fallback=None,
            )
        else:
            return RouteDecision(
                query=query,
                sensitivity=level,
                recommended_provider=self.cloud_provider,
                recommended_model=self.cloud_model,
                reason=reason,
                local_fallback=self.local_model,
            )

    def learn_pattern(self, pattern: str, level: SensitivityLevel) -> None:
        self._learned_patterns.append((re.compile(pattern, re.IGNORECASE), level))

    def route(self, query: str) -> dict:
        decision = self.classify(query)
        return {
            "provider": decision.recommended_provider,
            "model": decision.recommended_model,
            "sensitivity": decision.sensitivity.value,
            "reason": decision.reason,
        }

    def summary_text(self) -> str:
        return (
            f"Privacy Router Configuration\n"
            f"{'=' * 40}\n"
            f"Local:      {self.local_provider}/{self.local_model}\n"
            f"Cloud:      {self.cloud_provider}/{self.cloud_model}\n"
            f"Sensitive:  {self.sensitive_provider}/{self.sensitive_model}\n"
            f"Learned patterns: {len(self._learned_patterns)}"
        )
