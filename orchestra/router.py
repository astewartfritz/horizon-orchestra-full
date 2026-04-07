"""Horizon Orchestra — Multi-Model Router.

Intelligent model registry and routing engine. Every model is accessed
through an OpenAI-compatible client, so Moonshot, OpenRouter, Together,
Perplexity, vLLM, and Ollama all use the same AsyncOpenAI interface.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

__all__ = [
    "ModelConfig",
    "ModelRouter",
    "DEFAULT_MODELS",
]

log = logging.getLogger("orchestra.router")


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Immutable descriptor for a single model endpoint."""

    model_id: str
    provider: str
    base_url: str
    api_key_env: str
    strengths: tuple[str, ...] = ()
    cost_input: float = 0.0     # $ per 1 M input tokens
    cost_output: float = 0.0    # $ per 1 M output tokens
    max_context: int = 128_000
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_thinking: bool = False
    architecture: str = ""            # "dense", "moe", "efficient", ""
    parameters_b: float = 0.0         # total param count in billions


# ---------------------------------------------------------------------------
# Default model catalogue
# ---------------------------------------------------------------------------

DEFAULT_MODELS: dict[str, ModelConfig] = {
    # ── Kimi K2.5 (primary backbone) ──────────────────────────────────────
    "kimi-k2.5": ModelConfig(
        model_id="kimi-k2.5",
        provider="moonshot",
        base_url="https://api.moonshot.ai/v1",
        api_key_env="MOONSHOT_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.60, cost_output=2.50,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-openrouter": ModelConfig(
        model_id="moonshotai/kimi-k2.5",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.55, cost_output=2.19,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-together": ModelConfig(
        model_id="moonshotai/Kimi-K2.5",
        provider="together",
        base_url="https://api.together.xyz/v1",
        api_key_env="TOGETHER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.60, cost_output=2.50,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-local": ModelConfig(
        model_id="moonshotai/Kimi-K2.5",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",                       # vLLM needs no key
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),

    # ── Perplexity Sonar (web search) ─────────────────────────────────────
    "sonar": ModelConfig(
        model_id="sonar",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations"),
        cost_input=1.00, cost_output=1.00,
        max_context=128_000,
        supports_tools=False, supports_vision=False,
    ),
    "sonar-pro": ModelConfig(
        model_id="sonar-pro",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations", "deep_research"),
        cost_input=3.00, cost_output=15.00,
        max_context=200_000,
        supports_tools=False, supports_vision=False,
    ),
    "sonar-reasoning-pro": ModelConfig(
        model_id="sonar-reasoning-pro",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations", "deep_research", "reasoning"),
        cost_input=3.00, cost_output=15.00,
        max_context=200_000,
        supports_tools=False, supports_vision=False,
    ),

    # ── Third-party frontier models via Perplexity Agent API / OpenRouter ─
    "gpt-5.4": ModelConfig(
        model_id="openai/gpt-5.4",
        provider="perplexity-agent",
        base_url="https://api.perplexity.ai/v1",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("reasoning", "coding", "long_context"),
        cost_input=2.00, cost_output=10.00,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
    ),
    "claude-opus-4.6": ModelConfig(
        model_id="anthropic/claude-opus-4-6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "long_context"),
        cost_input=5.00, cost_output=25.00,
        max_context=200_000,
        supports_tools=True, supports_vision=True,
    ),
    # NOTE: The fully-featured Claude entries (with native Anthropic provider,
    # thinking support, and 1M context) are registered below after the Gemma 4
    # block, following the canonical Claude / Anthropic section.
    "grok-3": ModelConfig(
        model_id="xai/grok-3",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("speed", "summarization", "lightweight"),
        cost_input=0.30, cost_output=1.50,
        max_context=131_072,
        supports_tools=True, supports_vision=False,
    ),

    # ── Gemma 4 (Google — Apache 2.0) ──────────────────────────────────
    "gemma-4-31b": ModelConfig(
        model_id="gemma-4-31b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.15, cost_output=0.60,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-26b-moe": ModelConfig(
        model_id="gemma-4-26b-a4b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=0.10, cost_output=0.40,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="moe", parameters_b=25.2,
    ),
    "gemma-4-e4b": ModelConfig(
        model_id="gemma-4-e4b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("speed", "lightweight", "vision", "audio", "on_device"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True, supports_thinking=True,
        architecture="efficient", parameters_b=4.5,
    ),
    "gemma-4-e2b": ModelConfig(
        model_id="gemma-4-e2b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("speed", "lightweight", "audio", "on_device"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True, supports_thinking=False,
        architecture="efficient", parameters_b=2.3,
    ),
    "gemma-4-31b-openrouter": ModelConfig(
        model_id="google/gemma-4-31b-it",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.15, cost_output=0.60,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-26b-openrouter": ModelConfig(
        model_id="google/gemma-4-26b-a4b-it",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=0.10, cost_output=0.40,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="moe", parameters_b=25.2,
    ),
    "gemma-4-31b-local": ModelConfig(
        model_id="google/gemma-4-31B-it",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-ollama": ModelConfig(
        model_id="gemma4:31b",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-26b-ollama": ModelConfig(
        model_id="gemma4:26b-a4b",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="moe", parameters_b=25.2,
    ),

    # ── Claude / Anthropic ─────────────────────────────────────────────────
    "claude-opus-4.6-native": ModelConfig(
        model_id="claude-opus-4-6",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=5.00, cost_output=25.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=0.0,  # undisclosed
    ),
    "claude-opus-4.6-openrouter": ModelConfig(
        model_id="anthropic/claude-opus-4-6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=5.00, cost_output=25.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=0.0,
    ),
    "claude-sonnet-4.6": ModelConfig(
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=3.00, cost_output=15.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=0.0,
    ),
    "claude-sonnet-4.6-openrouter": ModelConfig(
        model_id="anthropic/claude-sonnet-4-6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=3.00, cost_output=15.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=0.0,
    ),
    "claude-haiku-4.5": ModelConfig(
        model_id="claude-haiku-4-5-20251015",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        strengths=("speed", "lightweight", "vision", "tool_use"),
        cost_input=1.00, cost_output=5.00,
        max_context=200_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=False,
        architecture="dense", parameters_b=0.0,
    ),
    "claude-haiku-4.5-openrouter": ModelConfig(
        model_id="anthropic/claude-haiku-4-5-20251015",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("speed", "lightweight", "vision", "tool_use"),
        cost_input=1.00, cost_output=5.00,
        max_context=200_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=False,
        architecture="dense", parameters_b=0.0,
    ),

    # ── Local / Ollama (other) ─────────────────────────────────────────────
    "ollama-local": ModelConfig(
        model_id="llama3",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        strengths=("speed", "lightweight"),
        cost_input=0.0, cost_output=0.0,
        max_context=32_768,
        supports_tools=False, supports_vision=False,
    ),
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ModelRouter:
    """Registry + intelligent routing across all model providers."""

    def __init__(
        self,
        custom_models: dict[str, ModelConfig] | None = None,
    ) -> None:
        self.models: dict[str, ModelConfig] = dict(DEFAULT_MODELS)
        if custom_models:
            self.models.update(custom_models)
        self._clients: dict[str, AsyncOpenAI] = {}

    # -- client management --------------------------------------------------

    def get_client(self, model_name: str) -> tuple[AsyncOpenAI, str]:
        """Return ``(AsyncOpenAI_client, model_id)`` for *model_name*.

        Clients are cached so repeated calls reuse the same connection pool.

        For Gemini-hosted models the Gemini API uses an OpenAI-compatible
        endpoint at ``/v1beta/openai/``, so we can still return an
        AsyncOpenAI client.  Native Gemini SDK usage is handled by
        ``gemma4_provider.py`` for multimodal and thinking features.
        """
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")

        if model_name not in self._clients:
            api_key = (
                os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else "not-needed"
            )
            # Gemini API exposes an OpenAI-compatible layer
            if cfg.provider == "gemini":
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            elif cfg.provider == "anthropic":
                # The native Anthropic API does NOT implement the OpenAI
                # Messages spec.  Native SDK calls are handled by
                # opus4_provider.Opus4Provider.  For OpenAI-compatible access,
                # use the OpenRouter variant (e.g. 'claude-opus-4.6-openrouter').
                raise ValueError(
                    "Direct Anthropic API requires the native SDK. "
                    "Use opus4_provider.Opus4Provider for native features, or use "
                    "the OpenRouter variant (e.g., 'claude-opus-4.6-openrouter') "
                    "for OpenAI-compatible access."
                )
            else:
                base_url = cfg.base_url
            self._clients[model_name] = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed",
            )
        return self._clients[model_name], cfg.model_id

    def get_config(self, model_name: str) -> ModelConfig:
        """Return the :class:`ModelConfig` for *model_name*."""
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")
        return cfg

    def is_gemma4(self, model_name: str) -> bool:
        """Return True if *model_name* is a Gemma 4 variant."""
        return model_name.startswith("gemma-4")

    def is_claude(self, model_name: str) -> bool:
        """Return True if *model_name* is a Claude model."""
        return model_name.startswith("claude-")

    # -- intelligent routing ------------------------------------------------

    def route(
        self,
        task_type: str,
        constraints: dict[str, Any] | None = None,
    ) -> str:
        """Pick the best model for *task_type*.

        *task_type* is a strength tag such as ``"reasoning"``,
        ``"coding"``, ``"web_search"``, ``"speed"``, ``"vision"``,
        or ``"agentic"``.

        *constraints* may contain:
        - ``max_cost_input``  – max $/M input tokens
        - ``max_cost_output`` – max $/M output tokens
        - ``require_tools``   – model must support tool calling
        - ``require_vision``  – model must support vision
        - ``providers``       – list of acceptable provider strings
        """
        constraints = constraints or {}
        epsilon = 0.001

        candidates: list[tuple[str, float]] = []
        for name, cfg in self.models.items():
            # --- constraint filtering ---
            if constraints.get("require_tools") and not cfg.supports_tools:
                continue
            if constraints.get("require_vision") and not cfg.supports_vision:
                continue
            if cfg.cost_input > constraints.get("max_cost_input", float("inf")):
                continue
            if cfg.cost_output > constraints.get("max_cost_output", float("inf")):
                continue
            if "providers" in constraints and cfg.provider not in constraints["providers"]:
                continue
            # Skip models whose API key is required but missing
            if cfg.api_key_env and not os.environ.get(cfg.api_key_env):
                continue

            # --- scoring ---
            has_strength = task_type in cfg.strengths
            # Models without the requested capability get a flat low score
            # so that even free models don't outrank capable paid ones.
            if has_strength:
                avg_cost = (cfg.cost_input + cfg.cost_output) / 2
                score = 1000.0 / (avg_cost + epsilon)  # cheaper = higher among capable
            else:
                score = 0.1  # fallback tier
            candidates.append((name, score))

        if not candidates:
            # Fallback: return cheapest available model regardless of fit
            log.warning("No model matched task_type=%r with constraints; using fallback", task_type)
            return self._cheapest_available()

        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0][0]
        log.debug("Routed task_type=%r -> %s (score=%.3f)", task_type, best, candidates[0][1])
        return best

    def _cheapest_available(self) -> str:
        """Return the cheapest model that has a resolvable API key."""
        avail = [
            (n, c)
            for n, c in self.models.items()
            if not c.api_key_env or os.environ.get(c.api_key_env)
        ]
        if not avail:
            return "kimi-k2.5"  # absolute fallback
        avail.sort(key=lambda x: x[1].cost_input + x[1].cost_output)
        return avail[0][0]

    # -- enumeration --------------------------------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        """Return every registered model as a serialisable dict."""
        out: list[dict[str, Any]] = []
        for name, cfg in self.models.items():
            has_key = (
                not cfg.api_key_env or bool(os.environ.get(cfg.api_key_env))
            )
            out.append({
                "name": name,
                "model_id": cfg.model_id,
                "provider": cfg.provider,
                "strengths": list(cfg.strengths),
                "cost_input": cfg.cost_input,
                "cost_output": cfg.cost_output,
                "max_context": cfg.max_context,
                "supports_tools": cfg.supports_tools,
                "supports_vision": cfg.supports_vision,
                "supports_audio": cfg.supports_audio,
                "supports_thinking": cfg.supports_thinking,
                "architecture": cfg.architecture,
                "parameters_b": cfg.parameters_b,
                "available": has_key,
            })
        return out
