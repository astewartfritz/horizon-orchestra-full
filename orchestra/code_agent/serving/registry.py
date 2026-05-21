from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ModelCapability(Enum):
    CHAT = "chat"
    STREAMING = "streaming"
    STRUCTURED = "structured"
    TOOLS = "tools"
    VISION = "vision"
    CODE = "code"
    REASONING = "reasoning"
    LONG_CONTEXT = "long_context"


@dataclass
class ModelEntry:
    model_id: str
    provider: str
    capabilities: set[ModelCapability] = field(default_factory=set)
    context_window: int = 8192
    max_output_tokens: int = 4096
    cost_per_million_input: float = 0.0
    cost_per_million_output: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    health_status: str = "unknown"
    aliases: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)

    @property
    def cost_per_token_input(self) -> float:
        return self.cost_per_million_input / 1_000_000

    @property
    def cost_per_token_output(self) -> float:
        return self.cost_per_million_output / 1_000_000


_DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "model_id": "gpt-4o",
        "provider": "openai",
        "capabilities": ["chat", "streaming", "structured", "tools", "vision", "code", "reasoning"],
        "context_window": 128000,
        "max_output_tokens": 16384,
        "cost_per_million_input": 2.50,
        "cost_per_million_output": 10.00,
        "aliases": ["gpt4o"],
        "tags": {"family": "gpt-4", "class": "premium"},
    },
    {
        "model_id": "gpt-4o-mini",
        "provider": "openai",
        "capabilities": ["chat", "streaming", "structured", "tools", "vision"],
        "context_window": 128000,
        "max_output_tokens": 16384,
        "cost_per_million_input": 0.15,
        "cost_per_million_output": 0.60,
        "aliases": ["gpt4o-mini"],
        "tags": {"family": "gpt-4", "class": "budget"},
    },
    {
        "model_id": "gpt-4-turbo",
        "provider": "openai",
        "capabilities": ["chat", "streaming", "structured", "tools", "vision", "code"],
        "context_window": 128000,
        "max_output_tokens": 4096,
        "cost_per_million_input": 10.00,
        "cost_per_million_output": 30.00,
        "aliases": ["gpt4-turbo"],
        "tags": {"family": "gpt-4", "class": "legacy"},
    },
    {
        "model_id": "claude-sonnet-4-20250514",
        "provider": "anthropic",
        "capabilities": ["chat", "streaming", "tools", "code", "reasoning", "long_context"],
        "context_window": 200000,
        "max_output_tokens": 8192,
        "cost_per_million_input": 3.00,
        "cost_per_million_output": 15.00,
        "aliases": ["claude-sonnet-4", "sonnet-4"],
        "tags": {"family": "claude-3.5", "class": "premium"},
    },
    {
        "model_id": "claude-3-opus",
        "provider": "anthropic",
        "capabilities": ["chat", "streaming", "tools", "code", "reasoning", "long_context"],
        "context_window": 200000,
        "max_output_tokens": 4096,
        "cost_per_million_input": 15.00,
        "cost_per_million_output": 75.00,
        "aliases": ["opus"],
        "tags": {"family": "claude-3", "class": "premium", "capability": "reasoning"},
    },
    {
        "model_id": "claude-3-haiku",
        "provider": "anthropic",
        "capabilities": ["chat", "streaming", "tools", "vision", "code"],
        "context_window": 200000,
        "max_output_tokens": 4096,
        "cost_per_million_input": 0.25,
        "cost_per_million_output": 1.25,
        "aliases": ["haiku"],
        "tags": {"family": "claude-3", "class": "budget"},
    },
    {
        "model_id": "llama3.1",
        "provider": "ollama",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 32768,
        "max_output_tokens": 2048,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["llama-3.1"],
        "tags": {"family": "llama", "class": "local"},
    },
    {
        "model_id": "mistral",
        "provider": "ollama",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 32768,
        "max_output_tokens": 2048,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["mistral-7b"],
        "tags": {"family": "mistral", "class": "local"},
    },
    {
        "model_id": "nemotron-mini",
        "provider": "ollama",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 8192,
        "max_output_tokens": 2048,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["nemotron-3", "nemotron"],
        "tags": {"family": "nemotron", "class": "local"},
    },
    {
        "model_id": "auto",
        "provider": "vllm",
        "capabilities": ["chat", "streaming", "structured", "tools", "code", "reasoning"],
        "context_window": 131072,
        "max_output_tokens": 32768,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["vllm-default"],
        "tags": {"family": "vllm", "class": "local"},
    },
    {
        "model_id": "Qwen/Qwen2.5-7B-Instruct",
        "provider": "vllm",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 32768,
        "max_output_tokens": 8192,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["qwen2.5-7b", "qwen2.5"],
        "tags": {"family": "qwen", "class": "local"},
    },
    {
        "model_id": "Qwen/Qwen2.5-32B-Instruct",
        "provider": "vllm",
        "capabilities": ["chat", "streaming", "structured", "tools", "code", "reasoning"],
        "context_window": 32768,
        "max_output_tokens": 8192,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["qwen2.5-32b"],
        "tags": {"family": "qwen", "class": "local"},
    },
    {
        "model_id": "meta-llama/Llama-3.1-8B-Instruct",
        "provider": "vllm",
        "capabilities": ["chat", "streaming", "structured", "tools", "code"],
        "context_window": 131072,
        "max_output_tokens": 8192,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["llama-3.1-8b", "llama3.1-8b"],
        "tags": {"family": "llama", "class": "local"},
    },
    {
        "model_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "provider": "vllm",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 32768,
        "max_output_tokens": 4096,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["mistral-7b-v0.3"],
        "tags": {"family": "mistral", "class": "local"},
    },
    {
        "model_id": "opencode",
        "provider": "opencode",
        "capabilities": ["chat", "streaming", "tools", "code", "reasoning"],
        "context_window": 128000,
        "max_output_tokens": 65536,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["oc"],
        "tags": {"family": "engine", "class": "local", "type": "coding_agent"},
    },
    {
        "model_id": "claude-code",
        "provider": "claude_code",
        "capabilities": ["chat", "streaming", "tools", "code", "reasoning", "long_context"],
        "context_window": 200000,
        "max_output_tokens": 65536,
        "cost_per_million_input": 3.00,
        "cost_per_million_output": 15.00,
        "aliases": ["claude-code-4"],
        "tags": {"family": "engine", "class": "api", "type": "coding_agent"},
    },
    {
        "model_id": "codex-mini-latest",
        "provider": "codex",
        "capabilities": ["chat", "streaming", "tools", "code"],
        "context_window": 128000,
        "max_output_tokens": 16384,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "aliases": ["codex-mini"],
        "tags": {"family": "engine", "class": "api", "type": "coding_agent"},
    },
]


class ModelRegistry:
    def __init__(self, path: str | Path | None = None):
        self._models: dict[str, ModelEntry] = {}
        self._path = Path(path) if path else None
        self._load_defaults()
        if self._path and self._path.exists():
            self._load_file()

    def _load_defaults(self) -> None:
        for entry in _DEFAULT_MODELS:
            caps = set()
            for c in entry.get("capabilities", []):
                try:
                    caps.add(ModelCapability(c))
                except ValueError:
                    pass
            aliases = entry.get("aliases", [])
            model_id = entry["model_id"]
            self._models[model_id] = ModelEntry(
                model_id=model_id,
                provider=entry["provider"],
                capabilities=caps,
                context_window=entry.get("context_window", 8192),
                max_output_tokens=entry.get("max_output_tokens", 4096),
                cost_per_million_input=entry.get("cost_per_million_input", 0.0),
                cost_per_million_output=entry.get("cost_per_million_output", 0.0),
                aliases=aliases,
                tags=entry.get("tags", {}),
            )

    def _load_file(self) -> None:
        try:
            data = json.loads(self._path.read_text("utf-8"))
            for entry in data:
                self.register(**entry)
        except Exception:
            pass

    def _save_file(self) -> None:
        if self._path:
            data = []
            for m in self._models.values():
                d = {
                    "model_id": m.model_id,
                    "provider": m.provider,
                    "capabilities": [c.value for c in m.capabilities],
                    "context_window": m.context_window,
                    "max_output_tokens": m.max_output_tokens,
                    "cost_per_million_input": m.cost_per_million_input,
                    "cost_per_million_output": m.cost_per_million_output,
                    "aliases": m.aliases,
                    "tags": m.tags,
                }
                data.append(d)
            self._path.write_text(json.dumps(data, indent=2), "utf-8")

    def register(
        self,
        model_id: str,
        provider: str,
        capabilities: list[str] | None = None,
        context_window: int = 8192,
        max_output_tokens: int = 4096,
        cost_per_million_input: float = 0.0,
        cost_per_million_output: float = 0.0,
        aliases: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> ModelEntry:
        caps = set()
        for c in (capabilities or []):
            try:
                caps.add(ModelCapability(c))
            except ValueError:
                pass
        entry = ModelEntry(
            model_id=model_id,
            provider=provider,
            capabilities=caps,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            cost_per_million_input=cost_per_million_input,
            cost_per_million_output=cost_per_million_output,
            aliases=aliases or [],
            tags=tags or {},
        )
        self._models[model_id] = entry
        self._save_file()
        return entry

    def unregister(self, model_id: str) -> bool:
        if model_id in self._models:
            del self._models[model_id]
            self._save_file()
            return True
        return False

    def get(self, model_id: str) -> ModelEntry | None:
        direct = self._models.get(model_id)
        if direct:
            return direct
        for entry in self._models.values():
            if model_id in entry.aliases:
                return entry
        return None

    def list_models(
        self,
        provider: str | None = None,
        capability: ModelCapability | None = None,
        tag_key: str | None = None,
        tag_value: str | None = None,
    ) -> list[ModelEntry]:
        results = list(self._models.values())
        if provider:
            results = [m for m in results if m.provider == provider]
        if capability:
            results = [m for m in results if capability in m.capabilities]
        if tag_key:
            results = [m for m in results if tag_key in m.tags and (tag_value is None or m.tags[tag_key] == tag_value)]
        return sorted(results, key=lambda m: m.model_id)

    def find_by_capability(self, capability: ModelCapability, min_context: int = 0) -> list[ModelEntry]:
        results = []
        for entry in self._models.values():
            if capability in entry.capabilities and entry.context_window >= min_context:
                results.append(entry)
        return sorted(results, key=lambda m: m.cost_per_million_input)

    def get_cheapest(self, capability: ModelCapability | None = None) -> ModelEntry | None:
        candidates = self._models.values()
        if capability:
            candidates = [m for m in candidates if capability in m.capabilities]
        if not candidates:
            return None
        return min(candidates, key=lambda m: m.cost_per_million_input)

    def update_health(self, model_id: str, status: str) -> None:
        entry = self.get(model_id)
        if entry:
            entry.health_status = status

    def summary(self) -> dict[str, Any]:
        models = self.list_models()
        return {
            "total": len(models),
            "by_provider": {p: len([m for m in models if m.provider == p]) for p in set(m.provider for m in models)},
            "healthy": len([m for m in models if m.health_status == "healthy"]),
            "unhealthy": len([m for m in models if m.health_status == "unhealthy"]),
        }

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {"models": [
            {
                "model_id": m.model_id,
                "provider": m.provider,
                "capabilities": [c.value for c in m.capabilities],
                "context_window": m.context_window,
                "cost_per_million_input": m.cost_per_million_input,
                "cost_per_million_output": m.cost_per_million_output,
                "health_status": m.health_status,
                "aliases": m.aliases,
                "tags": m.tags,
            }
            for m in self._models.values()
        ]}
