from __future__ import annotations

"""OpenAI-compatible provider adapter.

Wraps any AsyncOpenAI client (Moonshot, Together, OpenRouter, local vLLM)
behind the ProviderAdapter protocol so the kernel never imports openai directly.
"""

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .base import CompletionResponse, Message, ProviderAdapter


class OpenAIAdapter:
    """Adapts an AsyncOpenAI client to ProviderAdapter."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        raw = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=raw,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                })
        return CompletionResponse(
            content=choice.message.content or "",
            model=self._model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        raw = [{"role": m.role, "content": m.content} for m in messages]
        async with self._client.chat.completions.stream(
            model=self._model,
            messages=raw,
            temperature=temperature,
            max_tokens=max_tokens,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else ""
                if delta:
                    yield delta
