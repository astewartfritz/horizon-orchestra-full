from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable

from orchestra.code_agent.llm.base import Message, LLMError


@dataclass
class ProviderConfig:
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout: float = 600.0
    extra_headers: dict[str, str] | None = None


@dataclass
class ProviderMetadata:
    name: str
    supported_models: list[str]
    supports_streaming: bool = True
    supports_structured: bool = False
    supports_tools: bool = True
    supports_system_prompt: bool = True


class BaseProvider(ABC):
    def __init__(self, model: str, config: ProviderConfig | None = None):
        self.model = model
        self.config = config or ProviderConfig()
        self._on_token: Callable[[str], None] | None = None
        self._cost_tracker: Any = None

    def on_token(self, callback: Callable[[str], None] | None) -> None:
        self._on_token = callback

    def set_cost_tracker(self, tracker: Any) -> None:
        self._cost_tracker = tracker

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        ...

    async def chat_structured(
        self,
        messages: list[Message],
        response_model: type[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        raise LLMError(f"Structured output not supported by {self.__class__.__name__}")

    @abstractmethod
    def get_metadata(self) -> ProviderMetadata:
        ...

    @abstractmethod
    async def check_health(self) -> bool:
        ...

    @staticmethod
    def _message_to_dict(msg: Message) -> dict[str, Any]:
        d: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if msg.name:
            d["name"] = msg.name
        if msg.tool_calls:
            d["tool_calls"] = msg.tool_calls
        return d
