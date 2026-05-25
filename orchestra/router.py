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
    "GEMMA4_MODELS",
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
    supports_audio: bool = False    # Audio input (speech, ASR) — Gemma 4 E2B/E4B
    supports_thinking: bool = False  # Native reasoning/thinking mode
    architecture: str = ""          # Model architecture: "dense" | "moe" | "efficient" | ""
    parameters_b: float = 0.0       # Parameter count in billions (e.g., 31.0 for Gemma 4 31B)
    on_device: bool = False          # Whether this model can run on-device


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
        api_key_env="",
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

    # ── Google Gemma 4 family ─────────────────────────────────────────────
    # Dense models (Gemini API / vLLM / Ollama)
    "gemma-4-31b": ModelConfig(
        model_id="gemma-4-31b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        strengths=("reasoning", "coding", "vision", "tool_use", "thinking"),
        cost_input=0.10, cost_output=0.30,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-26b-moe": ModelConfig(
        model_id="gemma-4-26b-moe-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        strengths=("reasoning", "coding", "vision", "tool_use", "thinking", "speed"),
        cost_input=0.08, cost_output=0.25,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
        architecture="moe", parameters_b=25.2,
    ),
    "gemma-4-12b": ModelConfig(
        model_id="gemma-4-12b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        strengths=("reasoning", "coding", "vision", "tool_use"),
        cost_input=0.05, cost_output=0.15,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=False,
        architecture="dense", parameters_b=12.0,
    ),
    # Efficient models with audio input
    "gemma-4-e4b": ModelConfig(
        model_id="gemma-4-e4b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        strengths=("speed", "vision", "audio", "lightweight", "on_device"),
        cost_input=0.02, cost_output=0.06,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True, supports_thinking=True,
        architecture="efficient", parameters_b=4.0, on_device=True,
    ),
    "gemma-4-e2b": ModelConfig(
        model_id="gemma-4-e2b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_API_KEY",
        strengths=("speed", "vision", "audio", "lightweight", "on_device"),
        cost_input=0.01, cost_output=0.03,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True, supports_thinking=False,  # E2B: audio but no thinking
        architecture="efficient", parameters_b=2.0, on_device=True,
    ),
    # Local vLLM / Ollama deployments — zero cost, no API key required.
    # Registered here so the router can select them when a local server is
    # running. Use ModelRouter(isolated=True) in unit tests to exclude them.
    "gemma-4-31b-vllm": ModelConfig(
        model_id="gemma-4-31b-it",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=True,
    ),
    "gemma-4-e4b-vllm": ModelConfig(
        model_id="gemma-4-e4b-it",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",
        strengths=("speed", "audio", "vision", "lightweight"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True, supports_thinking=True,
    ),
    "gemma-4-ollama": ModelConfig(
        model_id="gemma4:12b",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        strengths=("speed", "lightweight", "vision"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=False,
    ),
    "gemma-4-hf": ModelConfig(
        model_id="google/gemma-4-12b-it",
        provider="huggingface",
        base_url="http://localhost:8080/v1",
        api_key_env="HF_TOKEN",
        strengths=("reasoning", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=False, supports_thinking=False,
    ),

    # ── Local / Ollama ────────────────────────────────────────────────────
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

    # ── OpenCode (local software engineering agent) ───────────────────────
    "opencode": ModelConfig(
        model_id="opencode",
        provider="opencode",
        base_url="",
        api_key_env="",
        strengths=("coding", "tool_use", "agentic", "reasoning"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=False,
        supports_audio=False, supports_thinking=False,
        architecture="", parameters_b=0.0,
        on_device=True,
    ),
}

# Convenience set of all Gemma 4 model keys
GEMMA4_MODELS: frozenset[str] = frozenset(
    k for k in DEFAULT_MODELS if k.startswith("gemma-4")
)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ModelRouter:
    """Registry + intelligent routing across all model providers."""

    def __init__(
        self,
        custom_models: dict[str, ModelConfig] | None = None,
        isolated: bool = False,
    ) -> None:
        # isolated=True starts with an empty registry — useful in unit tests
        # that want to control exactly which models participate in routing.
        self.models: dict[str, ModelConfig] = {} if isolated else dict(DEFAULT_MODELS)
        if custom_models:
            self.models.update(custom_models)
        self._clients: dict[str, AsyncOpenAI] = {}

    # -- client management --------------------------------------------------

    def get_client(self, model_name: str) -> tuple[AsyncOpenAI, str]:
        """Return ``(AsyncOpenAI_client, model_id)`` for *model_name*.

        Clients are cached so repeated calls reuse the same connection pool.
        """
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")

        if model_name not in self._clients:
            api_key = (
                os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else "not-needed"
            )
            self._clients[model_name] = AsyncOpenAI(
                base_url=cfg.base_url,
                api_key=api_key or "not-needed",
            )
        return self._clients[model_name], cfg.model_id

    def adapter(self, model_name: str) -> "ProviderAdapter":  # type: ignore[name-defined]
        """Return a swap-safe ProviderAdapter for *model_name*.

        Prefers PerplexityAdapter for Perplexity models and OpenAIAdapter
        for everything else.  Import is deferred to avoid circular imports.
        """
        from .providers import LocalAdapter, OpenAIAdapter, PerplexityAdapter
        cfg = self.models.get(model_name)
        if cfg and cfg.provider == "perplexity":
            api_key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
            return PerplexityAdapter(api_key=api_key, model=cfg.model_id)
        if cfg and cfg.provider == "local":
            return LocalAdapter(model=cfg.model_id, base_url=cfg.base_url)
        client, model_id = self.get_client(model_name)
        return OpenAIAdapter(client=client, model=model_id)

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

    # -- model helpers ------------------------------------------------------

    def get_config(self, model_name: str) -> ModelConfig:
        """Return the :class:`ModelConfig` for *model_name*.

        Raises ``KeyError`` if the model is not registered.
        """
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")
        return cfg

    def is_gemma4(self, model_name: str) -> bool:
        """Return True if *model_name* is a Gemma 4 variant."""
        return model_name in GEMMA4_MODELS or model_name.startswith("gemma-4")

    def list_gemma4_models(self) -> list[str]:
        """Return all registered Gemma 4 model keys."""
        return [k for k in self.models if self.is_gemma4(k)]

    def register(self, name: str, config: ModelConfig) -> None:
        """Register a new model (or override an existing one)."""
        self.models[name] = config
        log.debug("Registered model: %s (%s)", name, config.provider)

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
                "on_device": cfg.on_device,
                "available": has_key,
            })
        return out
