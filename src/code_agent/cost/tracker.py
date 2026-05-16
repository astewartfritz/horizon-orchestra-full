from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost(self, model: str) -> float:
        pricing = MODEL_PRICING.get(model, {"input": 1.0, "output": 2.0})
        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost


@dataclass
class CostEntry:
    timestamp: float
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    task: str = ""
    session_id: str = ""


class CostTracker:
    def __init__(self, path: str | Path = ".code-agent-cost.json"):
        self.path = Path(path)
        self.entries: list[CostEntry] = []
        self._current: TokenUsage = TokenUsage()
        self._current_model: str = ""
        if self.path.exists():
            self._load()

    def start_task(self, task: str, model: str, session_id: str = "") -> None:
        self._current = TokenUsage()
        self._current_model = model

    def record_usage(self, input_tokens: int, output_tokens: int, cached: int = 0) -> None:
        self._current.input_tokens += input_tokens
        self._current.output_tokens += output_tokens
        self._current.cached_input_tokens += cached

    def end_task(self, task: str = "", session_id: str = "") -> CostEntry:
        entry = CostEntry(
            timestamp=time.time(),
            model=self._current_model,
            usage=self._current,
            task=task,
            session_id=session_id,
        )
        self.entries.append(entry)
        self._save()
        return entry

    def summary(self) -> str:
        if not self.entries:
            return "No usage recorded."
        total_in = sum(e.usage.input_tokens for e in self.entries)
        total_out = sum(e.usage.output_tokens for e in self.entries)
        total_cost = sum(e.usage.cost(e.model) for e in self.entries)
        unique_models = set(e.model for e in self.entries)
        return (
            f"Total input tokens: {total_in:,}\n"
            f"Total output tokens: {total_out:,}\n"
            f"Estimated cost: ${total_cost:.4f}\n"
            f"Models used: {', '.join(sorted(unique_models))}\n"
            f"Requests: {len(self.entries)}"
        )

    def reset(self) -> None:
        self.entries = []
        self._current = TokenUsage()
        if self.path.exists():
            self.path.unlink()

    def _save(self) -> None:
        data = [asdict(e) for e in self.entries]
        self.path.write_text(json.dumps(data, indent=2), "utf-8")

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            self.entries = [CostEntry(**d) for d in data]
        except Exception:
            self.entries = []
