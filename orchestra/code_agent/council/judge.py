from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DIMENSIONS = ["correctness", "completeness", "clarity", "efficiency", "safety"]

_EVAL_PROMPT = """\
You are an expert evaluator for AI coding and task assistant outputs.

Task given to the AI assistant:
{task}

Agent that produced this output: {agent_name}

Output produced:
{output}

Evaluate the output on these five dimensions (integer 0–10 each):
- correctness: solves the task correctly and accurately
- completeness: addresses every part of the task
- clarity: clear, well-structured, easy to follow
- efficiency: uses good practices, avoids unnecessary complexity
- safety: free of harmful patterns, security issues, or regressions

Respond with a JSON object ONLY (no markdown, no explanation):
{{
  "correctness": <int 0-10>,
  "completeness": <int 0-10>,
  "clarity": <int 0-10>,
  "efficiency": <int 0-10>,
  "safety": <int 0-10>,
  "reasoning": "<one sentence explaining the score>"
}}
"""


@dataclass
class JudgeScore:
    judge_id: str
    agent_name: str
    correctness: float
    completeness: float
    clarity: float
    efficiency: float
    safety: float
    reasoning: str = ""
    duration_ms: float = 0.0
    error: str = ""

    @property
    def mean(self) -> float:
        return (
            self.correctness + self.completeness + self.clarity
            + self.efficiency + self.safety
        ) / 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "agent_name": self.agent_name,
            "scores": {d: getattr(self, d) for d in DIMENSIONS},
            "mean": round(self.mean, 3),
            "reasoning": self.reasoning,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class LLMJudge:
    """Single LLM judge that scores an agent output on 5 dimensions.

    Supports three backends (tried in order based on availability):
      - Anthropic Claude (Haiku for speed)
      - OpenAI GPT
      - Ollama (any local model)
    """

    def __init__(
        self,
        judge_id: str,
        backend: str = "auto",
        model: str | None = None,
        ollama_host: str = "http://localhost:11434",
        timeout: int = 30,
    ):
        self.judge_id = judge_id
        self._backend = backend
        self._model = model
        self._ollama_host = ollama_host
        self._timeout = timeout

    async def evaluate(
        self,
        task: str,
        output: str,
        agent_name: str,
    ) -> JudgeScore:
        start = time.time()
        prompt = _EVAL_PROMPT.format(
            task=task[:2000],
            agent_name=agent_name,
            output=output[:4000],
        )

        raw: str | None = None
        backend_used = self._backend

        if backend_used in ("auto", "anthropic"):
            raw, backend_used = await self._try_anthropic(prompt), "anthropic"
        if raw is None and backend_used in ("auto", "openai"):
            raw, backend_used = await self._try_openai(prompt), "openai"
        if raw is None and backend_used in ("auto", "ollama"):
            raw, backend_used = await self._try_ollama(prompt), "ollama"

        duration = (time.time() - start) * 1000

        if not raw:
            return JudgeScore(
                judge_id=self.judge_id,
                agent_name=agent_name,
                correctness=5.0, completeness=5.0, clarity=5.0,
                efficiency=5.0, safety=5.0,
                reasoning="judge unavailable — using neutral scores",
                duration_ms=duration,
                error="no backend available",
            )

        return self._parse(raw, agent_name, duration)

    async def _try_anthropic(self, prompt: str) -> str | None:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic()
            model = self._model or "claude-haiku-4-5-20251001"
            msg = await client.messages.create(
                model=model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text if msg.content else None
        except Exception as e:
            logger.debug("Anthropic judge failed: %s", e)
            return None

    async def _try_openai(self, prompt: str) -> str | None:
        try:
            import os
            import httpx
            key = os.environ.get("OPENAI_API_KEY", "")
            if not key:
                return None
            model = self._model or "gpt-3.5-turbo"
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": 512,
                    },
                )
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.debug("OpenAI judge failed: %s", e)
            return None

    async def _try_ollama(self, prompt: str) -> str | None:
        try:
            import httpx
            model = self._model or "nemotron-mini"
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._ollama_host}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                )
            if resp.status_code == 200:
                return resp.json().get("response", "")
        except Exception as e:
            logger.debug("Ollama judge failed: %s", e)
        return None

    def _parse(self, raw: str, agent_name: str, duration: float) -> JudgeScore:
        try:
            # Extract JSON from possible surrounding text
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return JudgeScore(
                judge_id=self.judge_id,
                agent_name=agent_name,
                correctness=float(data.get("correctness", 5)),
                completeness=float(data.get("completeness", 5)),
                clarity=float(data.get("clarity", 5)),
                efficiency=float(data.get("efficiency", 5)),
                safety=float(data.get("safety", 10)),
                reasoning=str(data.get("reasoning", "")),
                duration_ms=duration,
            )
        except Exception as e:
            logger.warning("Judge parse failed: %s | raw=%r", e, raw[:200])
            return JudgeScore(
                judge_id=self.judge_id,
                agent_name=agent_name,
                correctness=5.0, completeness=5.0, clarity=5.0,
                efficiency=5.0, safety=5.0,
                reasoning="parse error",
                duration_ms=duration,
                error=str(e),
            )
