from __future__ import annotations

"""Local provider adapter — Ollama, vLLM, LM Studio, llama.cpp server.

Any server that speaks the OpenAI `/v1/chat/completions` API works here.
The adapter auto-detects Ollama's `/api/tags` endpoint to list available
models, falling back gracefully when that endpoint is absent.
"""

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .base import CompletionResponse, Message

_DEFAULT_BASE = "http://localhost:11434/v1"   # Ollama default


class LocalAdapter:
    """Adapts a local OpenAI-compatible server to ProviderAdapter.

    Works with Ollama, vLLM, LM Studio, and llama.cpp server.
    Cost is always 0 (local inference).
    """

    def __init__(
        self,
        model: str,
        base_url: str = _DEFAULT_BASE,
        api_key: str = "ollama",   # Ollama ignores the key; some servers require any non-empty value
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
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
        tool_calls: list[dict[str, Any]] = []
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

    @classmethod
    async def list_ollama_models(cls, base_url: str = "http://localhost:11434") -> list[str]:
        """Return model names available in a running Ollama instance."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{base_url}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []
