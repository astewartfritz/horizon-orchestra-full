from __future__ import annotations

"""Anthropic provider adapter.

Adapts the Anthropic Python SDK to ProviderAdapter so Claude models
(claude-opus-4-7, claude-sonnet-4-6, …) can be used anywhere an
OpenAI-compatible model is used — no changes to kernel or agent logic.
"""

from typing import Any, AsyncIterator

from .base import CompletionResponse, Message

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


class AnthropicAdapter:
    """Adapts anthropic.AsyncAnthropic to ProviderAdapter."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6") -> None:
        if not _HAS_ANTHROPIC:
            raise ImportError("pip install anthropic")
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
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
        system = next((m.content for m in messages if m.role == "system"), "")
        user_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages if m.role != "system"
        ]
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=user_msgs,
        )
        if system:
            kwargs["system"] = system
        if tools:
            # Translate OpenAI-style tool defs to Anthropic format
            kwargs["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools if t.get("type") == "function"
            ]

        resp = await self._client.messages.create(**kwargs)
        text = ""
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                import json
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {"name": block.name, "arguments": json.dumps(block.input)},
                })
        return CompletionResponse(
            content=text,
            model=self._model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            tool_calls=tool_calls,
            finish_reason=resp.stop_reason or "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        system = next((m.content for m in messages if m.role == "system"), "")
        user_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages if m.role != "system"
        ]
        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=user_msgs,
        )
        if system:
            kwargs["system"] = system

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
