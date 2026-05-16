"""Horizon Orchestra — Intent Router.

NLU classifier that routes user messages to the optimal architecture,
skill set, and model configuration.  Classifies intent using keyword
matching (fast path) or LLM classification (complex queries).

This is the front door — every user message hits the intent router first.

Usage::

    from orchestra.intent import IntentRouter
    router = IntentRouter()
    intent = await router.classify("Build me a React dashboard with auth")
    # intent.architecture = "C", intent.skills = ["visualization", "ml_pipeline"], ...
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["IntentRouter", "Intent", "IntentConfig"]

log = logging.getLogger("orchestra.intent")


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    """Classified intent for a user message."""
    category: str = "general"         # research, coding, data, creative, ops, general
    architecture: str = "A"           # A, C, E
    skills: list[str] = field(default_factory=list)
    model_preference: str = ""        # override model if needed
    confidence: float = 0.0
    reasoning: str = ""
    requires_tools: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"  # low, medium, high, extreme


# Keyword patterns for fast classification
INTENT_PATTERNS: dict[str, dict[str, Any]] = {
    "research": {
        "patterns": [
            r"\b(?:research|find|search|look up|what is|who is|compare|analyze|investigate)\b",
            r"\b(?:latest|news|trend|market|industry|competitor)\b",
        ],
        "architecture": "A",
        "skills": [],
        "tools": ["web_search", "fetch_url"],
    },
    "coding": {
        "patterns": [
            r"\b(?:build|create|implement|code|develop|fix|debug|refactor|deploy)\b",
            r"\b(?:api|app|website|server|database|function|class|script|repo)\b",
        ],
        "architecture": "A",
        "skills": [],
        "tools": ["execute_code", "file_write", "file_read"],
    },
    "data_analysis": {
        "patterns": [
            r"\b(?:analyze|visualize|chart|graph|plot|dashboard|statistics|regression)\b",
            r"\b(?:csv|dataset|dataframe|correlation|outlier|cluster|predict|forecast)\b",
            r"\b(?:sql|query|database|warehouse|snowflake|table|schema)\b",
        ],
        "architecture": "A",
        "skills": ["data_exploration", "statistical_analysis", "visualization", "ml_pipeline", "sql_analytics"],
        "tools": ["execute_code", "file_read", "file_write"],
    },
    "multi_step": {
        "patterns": [
            r"\b(?:research.+(?:and|then).+build)\b",
            r"\b(?:compare.+(?:and|then).+create)\b",
            r"\b(?:find.+(?:and|then).+implement)\b",
            r"\b(?:multiple|several|parallel|simultaneously)\b",
        ],
        "architecture": "C",
        "skills": [],
        "tools": ["web_search", "execute_code", "file_write"],
    },
    "ops": {
        "patterns": [
            r"\b(?:email|send|schedule|remind|slack|notify|calendar|meeting)\b",
            r"\b(?:github|issue|pr|pull request|jira|linear|ticket)\b",
        ],
        "architecture": "A",
        "skills": [],
        "tools": [],
    },
    "creative": {
        "patterns": [
            r"\b(?:write|draft|compose|blog|article|essay|story|poem|copy)\b",
            r"\b(?:design|mockup|wireframe|presentation|slide)\b",
        ],
        "architecture": "A",
        "skills": [],
        "tools": ["file_write"],
    },
}

# Complexity indicators
COMPLEXITY_HIGH = [
    r"\b(?:full.?stack|end.?to.?end|production|enterprise|scalable)\b",
    r"\b(?:multiple|several|comprehensive|complete|thorough)\b",
    r"\b(?:deploy|ship|launch|release|publish)\b",
]
COMPLEXITY_EXTREME = [
    r"\b(?:operating system|framework|platform|infrastructure)\b",
    r"\b(?:distributed|microservice|kubernetes|cluster)\b",
]


@dataclass
class IntentConfig:
    use_llm_classification: bool = True
    llm_model: str = "kimi-k2.5"
    confidence_threshold: float = 0.6


class IntentRouter:
    """Classifies user intent and routes to the optimal architecture."""

    def __init__(self, config: IntentConfig | None = None, router: Any = None) -> None:
        self.config = config or IntentConfig()
        self._router = router

    async def classify(self, message: str) -> Intent:
        """Classify a user message into an Intent."""
        # Fast path: keyword matching
        intent = self._keyword_classify(message)

        # If low confidence and LLM available, use LLM classification
        if (intent.confidence < self.config.confidence_threshold
                and self.config.use_llm_classification
                and self._router):
            llm_intent = await self._llm_classify(message)
            if llm_intent.confidence > intent.confidence:
                intent = llm_intent

        # Complexity estimation
        intent.estimated_complexity = self._estimate_complexity(message)

        # Upgrade to Architecture C for high/extreme complexity
        if intent.estimated_complexity in ("high", "extreme") and intent.architecture == "A":
            intent.architecture = "C"

        log.info(
            "[INTENT] %s → arch=%s, skills=%s, complexity=%s (conf=%.2f)",
            intent.category, intent.architecture,
            intent.skills[:3], intent.estimated_complexity, intent.confidence,
        )
        return intent

    def _keyword_classify(self, message: str) -> Intent:
        """Fast keyword-based classification."""
        msg_lower = message.lower()
        scores: list[tuple[str, float, dict]] = []

        for category, config in INTENT_PATTERNS.items():
            score = 0.0
            for pattern in config["patterns"]:
                matches = len(re.findall(pattern, msg_lower, re.IGNORECASE))
                score += matches * 0.2
            if score > 0:
                scores.append((category, min(score, 1.0), config))

        if not scores:
            return Intent(category="general", architecture="A", confidence=0.3)

        scores.sort(key=lambda x: x[1], reverse=True)
        best_cat, best_score, best_config = scores[0]

        return Intent(
            category=best_cat,
            architecture=best_config["architecture"],
            skills=best_config.get("skills", []),
            requires_tools=best_config.get("tools", []),
            confidence=round(best_score, 2),
        )

    async def _llm_classify(self, message: str) -> Intent:
        """LLM-based classification for ambiguous messages."""
        if not self._router:
            return Intent(confidence=0.0)

        client, model_id = self._router.get_client(self.config.llm_model)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": (
                        "Classify this user message. Respond JSON:\n"
                        '{"category": "research|coding|data_analysis|multi_step|ops|creative|general", '
                        '"architecture": "A|C", '
                        '"skills": ["skill_names"], '
                        '"confidence": 0.0-1.0, '
                        '"reasoning": "brief"}'
                    )},
                    {"role": "user", "content": message[:500]},
                ],
                response_format={"type": "json_object"},
                temperature=0.1, max_tokens=256,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            return Intent(
                category=data.get("category", "general"),
                architecture=data.get("architecture", "A"),
                skills=data.get("skills", []),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", ""),
            )
        except Exception:
            return Intent(confidence=0.0)

    def _estimate_complexity(self, message: str) -> str:
        msg_lower = message.lower()
        extreme = sum(1 for p in COMPLEXITY_EXTREME if re.search(p, msg_lower))
        high = sum(1 for p in COMPLEXITY_HIGH if re.search(p, msg_lower))

        if extreme >= 2 or (extreme >= 1 and high >= 2):
            return "extreme"
        if high >= 2 or extreme >= 1:
            return "high"
        if len(message.split()) > 40 or high >= 1:
            return "medium"
        return "low"
