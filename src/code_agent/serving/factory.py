from __future__ import annotations

from typing import Any

from code_agent.llm.base import LLMError
from code_agent.serving.base import BaseProvider, ProviderConfig
from code_agent.serving.providers import OpenAIProvider, AnthropicProvider, OllamaProvider


class ProviderFactory:
    @classmethod
    def create(
        cls,
        provider: str,
        model: str | None = None,
        config: ProviderConfig | None = None,
    ) -> BaseProvider:
        provider = provider.lower()
        models: dict[str, list[str]] = {
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            "anthropic": ["claude-sonnet-4-20250514", "claude-sonnet-4", "claude-3-opus", "claude-3-haiku"],
            "ollama": ["llama3.1", "llama3", "mistral", "codellama", "nemotron-mini", "nemotron"],
            "vllm": ["auto"],
            "custom": ["gpt-4o", "gpt-4o-mini"],
        }

        resolved_model = model
        if not resolved_model:
            resolved_model = models.get(provider, ["gpt-4o"])[0]

        if provider == "openai":
            return OpenAIProvider(resolved_model, config)
        elif provider == "anthropic":
            return AnthropicProvider(resolved_model, config)
        elif provider in ("ollama", "custom"):
            cfg = config or ProviderConfig()
            if provider == "ollama" and not cfg.base_url:
                cfg.base_url = "http://localhost:11434/v1"
            return OllamaProvider(resolved_model, cfg)
        elif provider == "vllm":
            from code_agent.serving.vllm_provider import VLLMProvider
            return VLLMProvider(resolved_model, config)
        raise LLMError(f"Unsupported provider: {provider}")

    @classmethod
    def get_providers(cls) -> dict[str, type[BaseProvider]]:
        providers: dict[str, type[BaseProvider]] = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "ollama": OllamaProvider,
            "custom": OllamaProvider,
        }
        try:
            from code_agent.serving.vllm_provider import VLLMProvider
            providers["vllm"] = VLLMProvider
        except ImportError:
            pass
        return providers

    @classmethod
    def create_from_llm_config(cls, llm_cfg: Any) -> BaseProvider:
        from code_agent.config import LLMConfig
        if isinstance(llm_cfg, LLMConfig):
            cfg = ProviderConfig(
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                max_tokens=llm_cfg.max_tokens,
                temperature=llm_cfg.temperature,
                timeout=llm_cfg.timeout,
            )
            return cls.create(llm_cfg.provider, llm_cfg.model, cfg)
        raise LLMError("Expected LLMConfig instance")
