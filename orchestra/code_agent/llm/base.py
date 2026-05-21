from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal

try:
    from pydantic import BaseModel as PydanticModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class LLMError(Exception):
    pass


class LLM:
    """Backward-compatible LLM class that delegates to serving providers internally."""

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        timeout: float = 600.0,
    ):
        self.provider_name = provider
        self.model = model
        self.api_key = api_key
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif provider == "ollama":
            self.base_url = "http://localhost:11434/v1"
        else:
            self.base_url = "https://api.openai.com/v1"
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._on_token: Any = None
        self._cost_tracker: Any = None
        self._provider_instance: Any = None

    # Preserve backward-compatible property access
    @property
    def provider(self) -> str:
        return self.provider_name

    @provider.setter
    def provider(self, value: str) -> None:
        self.provider_name = value
        self._provider_instance = None

    def _get_provider(self) -> Any:
        if self._provider_instance is None:
            from orchestra.code_agent.serving.factory import ProviderFactory
            from orchestra.code_agent.serving.base import ProviderConfig
            cfg = ProviderConfig(
                api_key=self.api_key,
                base_url=self.base_url,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
            )
            self._provider_instance = ProviderFactory.create(
                self.provider_name, self.model, cfg,
            )
            if self._on_token:
                self._provider_instance.on_token(self._on_token)
            if self._cost_tracker:
                self._provider_instance.set_cost_tracker(self._cost_tracker)
        return self._provider_instance

    def on_token(self, callback: Any) -> None:
        self._on_token = callback
        if self._provider_instance:
            self._provider_instance.on_token(callback)

    def set_cost_tracker(self, tracker: Any) -> None:
        self._cost_tracker = tracker
        if self._provider_instance:
            self._provider_instance.set_cost_tracker(tracker)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        return await self._get_provider().chat(messages, tools, tool_choice, stream=stream)

    async def chat_structured(
        self,
        messages: list[Message],
        response_model: type[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        return await self._get_provider().chat_structured(messages, response_model, tools)

    # Backward-compatible method wrappers
    async def _chat_openai(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> Message:
        from orchestra.code_agent.serving.providers import OpenAIProvider
        from orchestra.code_agent.serving.base import ProviderConfig
        cfg = ProviderConfig(api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, timeout=self.timeout)
        p = OpenAIProvider(self.model, cfg)
        return await p.chat(messages, tools, tool_choice)

    async def _chat_openai_stream(
        self,
        messages: list[Message],
    ) -> Message:
        from orchestra.code_agent.serving.providers import OpenAIProvider
        from orchestra.code_agent.serving.base import ProviderConfig
        cfg = ProviderConfig(api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, timeout=self.timeout)
        p = OpenAIProvider(self.model, cfg)
        return await p.chat(messages, stream=True)

    async def _chat_openai_structured(
        self,
        messages: list[Message],
        response_model: type[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        from orchestra.code_agent.serving.providers import OpenAIProvider
        from orchestra.code_agent.serving.base import ProviderConfig
        cfg = ProviderConfig(api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, timeout=self.timeout)
        p = OpenAIProvider(self.model, cfg)
        return await p.chat_structured(messages, response_model, tools)

    async def _chat_anthropic(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        from orchestra.code_agent.serving.providers import AnthropicProvider
        from orchestra.code_agent.serving.base import ProviderConfig
        cfg = ProviderConfig(api_key=self.api_key, base_url=self.base_url, max_tokens=self.max_tokens, temperature=self.temperature, timeout=self.timeout)
        p = AnthropicProvider(self.model, cfg)
        return await p.chat(messages, tools)

    def _to_dict(self, msg: Message) -> dict[str, Any]:
        d: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if msg.name:
            d["name"] = msg.name
        if msg.tool_calls:
            d["tool_calls"] = msg.tool_calls
        return d
