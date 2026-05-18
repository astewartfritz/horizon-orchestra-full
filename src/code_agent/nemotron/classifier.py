from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """\
You are a task routing classifier for a multi-agent AI system called Orchestra.

Available agents and their strengths:
{agent_descriptions}

User task:
{task}

Respond with a JSON object only, no markdown:
{{
  "agent": "<agent_name>",
  "confidence": <0.0-1.0>,
  "reason": "<one sentence>",
  "fallback_agents": ["<agent_name>", ...]
}}

Rules:
- "agent" must be one of the agent names listed above
- "confidence" must be between 0.0 and 1.0
- "fallback_agents" should list 1-2 alternatives in order of preference
- If no agent is clearly best, pick the highest-priority one (lowest priority number)
"""


@dataclass
class ClassificationResult:
    agent_name: str
    confidence: float
    reason: str
    fallback_agents: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    via: str = "nemotron"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "fallback_agents": self.fallback_agents,
            "duration_ms": self.duration_ms,
            "via": self.via,
        }


class NemotronClassifier:
    """Uses Nemotron (via Ollama) to classify tasks and select the best active agent.

    Falls back to keyword-based heuristics if Ollama is unavailable.
    """

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        model: str = "nemotron-mini",
        timeout: int = 30,
    ):
        self._ollama_host = ollama_host
        self._model = model
        self._timeout = timeout

    async def classify(
        self,
        task: str,
        available_agents: list[dict[str, Any]],
    ) -> ClassificationResult:
        """Classify task and return the best agent name with confidence."""
        start = time.time()

        if not available_agents:
            return ClassificationResult(
                agent_name="",
                confidence=0.0,
                reason="No agents available",
                duration_ms=(time.time() - start) * 1000,
                via="empty",
            )

        agent_descriptions = self._format_agents(available_agents)
        prompt = _CLASSIFY_PROMPT.format(
            agent_descriptions=agent_descriptions,
            task=task,
        )

        result = await self._call_ollama(prompt)
        if result is not None:
            result.duration_ms = (time.time() - start) * 1000
            return result

        # Keyword fallback
        return self._keyword_classify(task, available_agents, start)

    def _format_agents(self, agents: list[dict[str, Any]]) -> str:
        lines = []
        for a in agents:
            caps = ", ".join(c["name"] for c in a.get("capabilities", []))
            lines.append(
                f"- {a['name']} (priority={a.get('priority', 50)}): {caps}"
            )
        return "\n".join(lines)

    async def _call_ollama(self, prompt: str) -> ClassificationResult | None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._ollama_host}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
            if resp.status_code != 200:
                return None

            raw = resp.json().get("response", "")
            data = json.loads(raw)
            return ClassificationResult(
                agent_name=data.get("agent", ""),
                confidence=float(data.get("confidence", 0.5)),
                reason=data.get("reason", ""),
                fallback_agents=data.get("fallback_agents", []),
                via="nemotron",
            )
        except Exception as e:
            logger.debug("Ollama classify failed: %s", e)
            return None

    def _keyword_classify(
        self,
        task: str,
        agents: list[dict[str, Any]],
        start: float,
    ) -> ClassificationResult:
        task_lower = task.lower()
        scored: list[tuple[int, dict[str, Any]]] = []

        for agent in agents:
            score = 0
            for cap in agent.get("capabilities", []):
                for kw in cap.get("intent_keywords", []):
                    if kw in task_lower:
                        score += 1
            scored.append((score, agent))

        scored.sort(key=lambda x: (-x[0], x[1].get("priority", 50)))

        if not scored:
            return ClassificationResult(
                agent_name="",
                confidence=0.0,
                reason="No agents matched",
                duration_ms=(time.time() - start) * 1000,
                via="keyword",
            )

        best_score, best_agent = scored[0]
        fallbacks = [a["name"] for _, a in scored[1:3]]
        confidence = min(0.9, 0.3 + best_score * 0.15) if best_score > 0 else 0.3

        return ClassificationResult(
            agent_name=best_agent["name"],
            confidence=confidence,
            reason=f"Keyword match (score={best_score})",
            fallback_agents=fallbacks,
            duration_ms=(time.time() - start) * 1000,
            via="keyword",
        )
