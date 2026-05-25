from __future__ import annotations

"""Perplexity provider adapter.

Perplexity Sonar models return grounded, web-cited completions.
This adapter surfaces citations alongside the text so the kernel can
log them as sources — matching the "Perplexity-style model as agent brain"
pattern from the agentic workflow architecture.
"""

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .base import CompletionResponse, Message

_PERPLEXITY_BASE = "https://api.perplexity.ai"


class PerplexityAdapter:
    """Wraps Perplexity Sonar behind ProviderAdapter.

    Perplexity uses OpenAI-compatible endpoints, so this is mostly
    a thin wrapper that extracts citations from the response metadata.
    """

    def __init__(self, api_key: str, model: str = "sonar-pro") -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=_PERPLEXITY_BASE)
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,   # Perplexity works best at low temp
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        raw = [{"role": m.role, "content": m.content} for m in messages]
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=raw,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        usage = resp.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()

        # Perplexity embeds citations in model_extra
        citations: list[str] = []
        if hasattr(resp, "model_extra") and resp.model_extra:
            citations = resp.model_extra.get("citations", [])

        content = choice.message.content or ""
        if citations:
            content += "\n\nSources:\n" + "\n".join(f"- {c}" for c in citations)

        return CompletionResponse(
            content=content,
            model=self._model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        raw = [{"role": m.role, "content": m.content} for m in messages]
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=raw,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else ""
            if delta:
                yield delta
