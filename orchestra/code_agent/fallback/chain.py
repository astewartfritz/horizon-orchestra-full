from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.config import LLMConfig


@dataclass
class FallbackResult:
    success: bool = False
    output: str = ""
    provider: str = ""
    model: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    total_cost: float = 0.0


class FallbackChain:
    """Try multiple LLM providers/models in sequence until one succeeds."""

    def __init__(self, configs: list[LLMConfig] | None = None):
        self.configs = configs or [
            LLMConfig(provider="openai", model="gpt-4o"),
            LLMConfig(provider="openai", model="gpt-4o-mini"),
            LLMConfig(provider="anthropic", model="claude-3-5-sonnet-20241022"),
            LLMConfig(provider="ollama", model="llama3.1"),
        ]

    async def run(self, prompt: str, max_attempts: int = None) -> FallbackResult:
        result = FallbackResult()
        attempts = min(max_attempts or len(self.configs), len(self.configs))

        for i, cfg in enumerate(self.configs[:attempts]):
            attempt: dict[str, Any] = {"provider": cfg.provider, "model": cfg.model, "status": "pending"}
            try:
                from orchestra.code_agent.llm.base import LLM, Message
                llm = LLM(
                    provider=cfg.provider,
                    model=cfg.model,
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    max_tokens=cfg.max_tokens or 4096,
                    temperature=cfg.temperature or 0.0,
                )
                messages = [Message(role="user", content=prompt)]
                response = await llm.chat(messages)
                content = ""
                async for chunk in response:
                    content += chunk
                attempt["status"] = "success"
                attempt["output_preview"] = content[:200]
                result.attempts.append(attempt)
                result.success = True
                result.output = content
                result.provider = cfg.provider
                result.model = cfg.model
                break
            except Exception as e:
                attempt["status"] = "error"
                attempt["error"] = str(e)
                result.attempts.append(attempt)

        return result
