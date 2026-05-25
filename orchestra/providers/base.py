from __future__ import annotations

"""LLM provider adapter protocol.

Every concrete provider (OpenAI, Anthropic, Perplexity, local vLLM …)
implements ProviderAdapter.  The kernel and agent loop talk only to this
interface, so swapping providers never touches orchestration logic.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass
class Message:
    role: str                            # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CompletionResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"


@runtime_checkable
class ProviderAdapter(Protocol):
    """Minimal interface every LLM provider must implement."""

    @property
    def model_id(self) -> str: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> CompletionResponse: ...

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]: ...
