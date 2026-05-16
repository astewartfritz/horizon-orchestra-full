"""OpenJarvis — Hybrid Model Router.

Merges the OpenJarvis model catalog with Orchestra's extended model registry
(brain2/brain3/brain4 Nemotron, Kimi K2.5 variants, Sonar variants, Gemma 4,
Claude, Grok) and provides domain-aware, cost/latency-aware routing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from openjarvis.intelligence.model_catalog import BUILTIN_MODELS

__all__ = [
    "CloudModelConfig",
    "HybridRouter",
    "ORCHESTRA_MODELS",
]

log = logging.getLogger("openjarvis.intelligence.hybrid_router")


@dataclass(frozen=True)
class CloudModelConfig:
    """Descriptor for a cloud/API-hosted model with routing metadata."""

    model_id: str
    provider: str
    base_url: str
    api_key_env: str
    strengths: tuple[str, ...] = ()
    cost_input: float = 0.0
    cost_output: float = 0.0
    max_context: int = 128_000
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_thinking: bool = False
    architecture: str = ""
    parameters_b: float = 0.0


ORCHESTRA_MODELS: dict[str, CloudModelConfig] = {
    "kimi-k2.5": CloudModelConfig(
        model_id="kimi-k2.5",
        provider="moonshot",
        base_url="https://api.moonshot.ai/v1",
        api_key_env="MOONSHOT_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.60, cost_output=2.50,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-openrouter": CloudModelConfig(
        model_id="moonshotai/kimi-k2.5",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.55, cost_output=2.19,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-together": CloudModelConfig(
        model_id="moonshotai/Kimi-K2.5",
        provider="together",
        base_url="https://api.together.xyz/v1",
        api_key_env="TOGETHER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.60, cost_output=2.50,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "kimi-k2.5-local": CloudModelConfig(
        model_id="moonshotai/Kimi-K2.5",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=262_144,
        supports_tools=True, supports_vision=True,
    ),
    "sonar": CloudModelConfig(
        model_id="sonar",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations"),
        cost_input=1.00, cost_output=1.00,
        max_context=128_000,
        supports_tools=False, supports_vision=False,
    ),
    "sonar-pro": CloudModelConfig(
        model_id="sonar-pro",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations", "deep_research"),
        cost_input=3.00, cost_output=15.00,
        max_context=200_000,
        supports_tools=False, supports_vision=False,
    ),
    "sonar-reasoning-pro": CloudModelConfig(
        model_id="sonar-reasoning-pro",
        provider="perplexity",
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("web_search", "citations", "deep_research", "reasoning"),
        cost_input=3.00, cost_output=15.00,
        max_context=200_000,
        supports_tools=False, supports_vision=False,
    ),
    "gpt-5.4": CloudModelConfig(
        model_id="openai/gpt-5.4",
        provider="perplexity-agent",
        base_url="https://api.perplexity.ai/v1",
        api_key_env="PERPLEXITY_API_KEY",
        strengths=("reasoning", "coding", "long_context"),
        cost_input=2.00, cost_output=10.00,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
    ),
    "claude-opus-4.6-openrouter": CloudModelConfig(
        model_id="anthropic/claude-opus-4-6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "long_context"),
        cost_input=5.00, cost_output=25.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
    ),
    "claude-sonnet-4.6-openrouter": CloudModelConfig(
        model_id="anthropic/claude-sonnet-4-6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=3.00, cost_output=15.00,
        max_context=1_000_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
    ),
    "claude-haiku-4.5-openrouter": CloudModelConfig(
        model_id="anthropic/claude-haiku-4-5-20251015",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("speed", "lightweight", "vision", "tool_use"),
        cost_input=1.00, cost_output=5.00,
        max_context=200_000,
        supports_tools=True, supports_vision=True,
    ),
    "grok-3": CloudModelConfig(
        model_id="xai/grok-3",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("speed", "summarization", "lightweight"),
        cost_input=0.30, cost_output=1.50,
        max_context=131_072,
        supports_tools=True, supports_vision=False,
    ),
    "gemma-4-31b": CloudModelConfig(
        model_id="gemma-4-31b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.15, cost_output=0.60,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-26b-moe": CloudModelConfig(
        model_id="gemma-4-26b-a4b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "speed"),
        cost_input=0.10, cost_output=0.40,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
        architecture="moe", parameters_b=25.2,
    ),
    "gemma-4-e4b": CloudModelConfig(
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
    "gemma-4-e2b": CloudModelConfig(
        model_id="gemma-4-e2b-it",
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GEMINI_API_KEY",
        strengths=("speed", "lightweight", "audio", "on_device"),
        cost_input=0.0, cost_output=0.0,
        max_context=128_000,
        supports_tools=True, supports_vision=True,
        supports_audio=True,
        architecture="efficient", parameters_b=2.3,
    ),
    "gemma-4-31b-openrouter": CloudModelConfig(
        model_id="google/gemma-4-31b-it",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.15, cost_output=0.60,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-31b-local": CloudModelConfig(
        model_id="google/gemma-4-31B-it",
        provider="local",
        base_url="http://localhost:8000/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use", "long_context"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    "gemma-4-ollama": CloudModelConfig(
        model_id="gemma4:31b",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
        cost_input=0.0, cost_output=0.0,
        max_context=256_000,
        supports_tools=True, supports_vision=True,
        supports_thinking=True,
        architecture="dense", parameters_b=30.7,
    ),
    # NVIDIA Nemotron — brain2 / brain3 / brain4
    "brain2": CloudModelConfig(
        model_id="nvidia/llama-3.1-nemotron-70b-instruct",
        provider="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        strengths=("reasoning", "coding", "instruction_following", "agentic"),
        cost_input=0.35, cost_output=0.40,
        max_context=131_072,
        supports_tools=True, supports_vision=False,
        architecture="dense", parameters_b=70.0,
    ),
    "brain3": CloudModelConfig(
        model_id="nvidia/llama-3.3-nemotron-super-49b-v1",
        provider="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        strengths=("reasoning", "math", "coding", "efficiency", "tool_use"),
        cost_input=0.23, cost_output=0.40,
        max_context=131_072,
        supports_tools=True, supports_vision=False,
        supports_thinking=True,
        architecture="dense", parameters_b=49.0,
    ),
    "brain4": CloudModelConfig(
        model_id="nvidia/nemotron-4-340b-instruct",
        provider="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        strengths=("reasoning", "coding", "long_context", "agentic", "tool_use"),
        cost_input=4.20, cost_output=4.20,
        max_context=4_096,
        supports_tools=True, supports_vision=False,
        architecture="dense", parameters_b=340.0,
    ),
    "ollama-local": CloudModelConfig(
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

_DOMAIN_TASK_MAP: dict[str, list[str]] = {
    "coding": ["reasoning", "coding", "agentic", "tool_use"],
    "research": ["web_search", "citations", "deep_research", "long_context"],
    "math": ["reasoning", "math", "coding"],
    "vision": ["vision", "reasoning"],
    "audio": ["audio", "speed"],
    "speed": ["speed", "lightweight"],
    "agentic": ["agentic", "tool_use", "reasoning"],
    "summarization": ["summarization", "speed"],
    "web_search": ["web_search", "citations"],
    "long_context": ["long_context", "reasoning"],
    "instruction_following": ["instruction_following", "agentic"],
}


class HybridRouter:
    """Combines the OpenJarvis model catalog with Orchestra's cloud model registry.

    Provides domain-aware routing (task type → strength tags) layered on top of
    cost/latency-aware scoring derived from both catalogs.
    """

    def __init__(
        self,
        extra_models: dict[str, CloudModelConfig] | None = None,
    ) -> None:
        self.models: dict[str, CloudModelConfig] = dict(ORCHESTRA_MODELS)
        if extra_models:
            self.models.update(extra_models)

        # Index OpenJarvis catalog model_ids for overlap detection
        self._jarvis_model_ids: set[str] = {
            spec.model_id for spec in BUILTIN_MODELS
        }

        self._clients: dict[str, AsyncOpenAI] = {}

    def get_client(self, model_name: str) -> tuple[AsyncOpenAI, str]:
        """Return ``(AsyncOpenAI_client, model_id)`` for *model_name*."""
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")

        if model_name not in self._clients:
            api_key = (
                os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else "not-needed"
            )
            if cfg.provider == "gemini":
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            elif cfg.provider == "anthropic":
                raise ValueError(
                    "Direct Anthropic API requires the native SDK. "
                    "Use the OpenRouter variant (e.g., 'claude-opus-4.6-openrouter') "
                    "for OpenAI-compatible access."
                )
            else:
                base_url = cfg.base_url
            self._clients[model_name] = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed",
            )
        return self._clients[model_name], cfg.model_id

    def get_config(self, model_name: str) -> CloudModelConfig:
        cfg = self.models.get(model_name)
        if cfg is None:
            raise KeyError(f"Unknown model: {model_name!r}")
        return cfg

    def route(
        self,
        task_type: str,
        constraints: dict[str, Any] | None = None,
    ) -> str:
        """Pick the best model for *task_type*.

        *task_type* may be a high-level domain key (``"coding"``, ``"research"``,
        ``"math"``, ``"vision"``, ``"audio"``, ``"speed"``, ``"agentic"``,
        ``"summarization"``, ``"web_search"``, ``"long_context"``,
        ``"instruction_following"``) or a raw strength tag.

        *constraints* may contain:

        - ``max_cost_input``  – max $/M input tokens
        - ``max_cost_output`` – max $/M output tokens
        - ``require_tools``   – model must support tool calling
        - ``require_vision``  – model must support vision
        - ``require_thinking`` – model must support extended thinking
        - ``providers``       – list of acceptable provider strings
        - ``max_latency``     – prefer cheaper/faster models (heuristic)
        """
        constraints = constraints or {}

        strength_tags = _DOMAIN_TASK_MAP.get(task_type, [task_type])
        epsilon = 0.001

        candidates: list[tuple[str, float]] = []
        for name, cfg in self.models.items():
            if constraints.get("require_tools") and not cfg.supports_tools:
                continue
            if constraints.get("require_vision") and not cfg.supports_vision:
                continue
            if constraints.get("require_thinking") and not cfg.supports_thinking:
                continue
            if cfg.cost_input > constraints.get("max_cost_input", float("inf")):
                continue
            if cfg.cost_output > constraints.get("max_cost_output", float("inf")):
                continue
            if "providers" in constraints and cfg.provider not in constraints["providers"]:
                continue
            if cfg.api_key_env and not os.environ.get(cfg.api_key_env):
                continue

            matched_strength = any(tag in cfg.strengths for tag in strength_tags)
            if matched_strength:
                avg_cost = (cfg.cost_input + cfg.cost_output) / 2
                cost_score = 1000.0 / (avg_cost + epsilon)
                latency_bias = 1.2 if constraints.get("max_latency") and avg_cost < 1.0 else 1.0
                score = cost_score * latency_bias
            else:
                score = 0.1

            candidates.append((name, score))

        if not candidates:
            log.warning(
                "No model matched task_type=%r with constraints; using fallback", task_type
            )
            return self._cheapest_available()

        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0][0]
        log.debug(
            "HybridRouter: task_type=%r -> %s (score=%.3f)",
            task_type, best, candidates[0][1],
        )
        return best

    def _cheapest_available(self) -> str:
        avail = [
            (n, c)
            for n, c in self.models.items()
            if not c.api_key_env or os.environ.get(c.api_key_env)
        ]
        if not avail:
            return "kimi-k2.5"
        avail.sort(key=lambda x: x[1].cost_input + x[1].cost_output)
        return avail[0][0]

    def list_models(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, cfg in self.models.items():
            has_key = not cfg.api_key_env or bool(os.environ.get(cfg.api_key_env))
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
                "in_jarvis_catalog": cfg.model_id in self._jarvis_model_ids,
            })
        return out

    @property
    def available_models(self) -> list[str]:
        return [
            name
            for name, cfg in self.models.items()
            if not cfg.api_key_env or os.environ.get(cfg.api_key_env)
        ]
