from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LayerConfig:
    name: str
    max_tokens: int
    reserve_tokens: int = 0
    priority: float = 1.0


DEFAULT_LAYERS = {
    "prompt": LayerConfig(name="prompt", max_tokens=4096, reserve_tokens=512, priority=3.0),
    "evidence": LayerConfig(name="evidence", max_tokens=16384, reserve_tokens=2048, priority=2.0),
    "reasoning": LayerConfig(name="reasoning", max_tokens=8192, reserve_tokens=1024, priority=1.0),
    "working_memory": LayerConfig(name="working_memory", max_tokens=4096, reserve_tokens=512, priority=1.5),
}


@dataclass
class ContextEntry:
    content: str
    layer: str = "reasoning"
    tier: str = "normal"
    source: str = ""
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.tokens:
            self.tokens = len(self.content) // 4


class LayeredContext:
    """Manages the context window as budget-partitioned layers.

    ┌────────────────────────────────────────────┐
    │  Prompt Layer   (system prompt, task)       │  4K tokens
    ├────────────────────────────────────────────┤
    │  Evidence Layer (retrieved docs, search)    │ 16K tokens
    ├────────────────────────────────────────────┤
    │  Reasoning Layer (plan, thoughts, steps)    │  8K tokens
    ├────────────────────────────────────────────┤
    │  Working Memory  (recent conversation)      │  4K tokens
    └────────────────────────────────────────────┘
    """

    def __init__(self, total_budget: int = 32000, layers: dict[str, LayerConfig] | None = None):
        self.total_budget = total_budget
        self.layers = layers or DEFAULT_LAYERS
        self._entries: dict[str, list[ContextEntry]] = {k: [] for k in self.layers}
        self._verify_budget()

    def _verify_budget(self) -> None:
        allocated = sum(lc.max_tokens for lc in self.layers.values())
        if allocated > self.total_budget:
            import logging
            logging.getLogger("orchestra.context").warning(
                "Layer budgets (%d) exceed total budget (%d). Some layers will be trimmed.",
                allocated, self.total_budget,
            )

    def add(self, content: str, layer: str = "reasoning", tier: str = "normal",
            source: str = "", metadata: dict[str, Any] | None = None) -> None:
        layer = layer if layer in self.layers else "reasoning"
        entry = ContextEntry(
            content=content, layer=layer, tier=tier,
            source=source, metadata=metadata or {},
        )
        self._entries[layer].append(entry)

    def _layer_used(self, layer: str) -> int:
        return sum(e.tokens for e in self._entries.get(layer, []))

    def _layer_budget(self, layer: str) -> int:
        cfg = self.layers.get(layer)
        if not cfg:
            return 0
        return cfg.max_tokens - cfg.reserve_tokens

    def trim_layer(self, layer: str) -> list[ContextEntry]:
        cfg = self.layers.get(layer)
        if not cfg:
            return []
        entries = self._entries.get(layer, [])
        budget = cfg.max_tokens - cfg.reserve_tokens
        used = sum(e.tokens for e in entries)
        if used <= budget:
            return []
        # Trim lowest priority entries
        sorted_e = sorted(entries, key=lambda e: (
            {"critical": 0, "important": 1, "normal": 2, "low": 3}.get(e.tier, 4), -e.tokens
        ))
        removed = []
        while used > budget and sorted_e:
            e = sorted_e.pop(0)
            used -= e.tokens
            removed.append(e)
        self._entries[layer] = sorted_e
        return removed

    def trim_all(self) -> dict[str, list[ContextEntry]]:
        return {l: self.trim_layer(l) for l in self.layers}

    def get_context(self, layer: str | None = None) -> str:
        parts = []
        target_layers = [layer] if layer else list(self.layers.keys())
        for l in target_layers:
            for e in self._entries.get(l, []):
                parts.append(e.content)
        return "\n\n".join(parts)

    def build_prompt(self, task: str, system_prompt: str = "") -> list[dict[str, str]]:
        """Build the final LLM messages from all layers respecting budgets."""
        self.trim_all()
        messages = []

        # 1. Prompt layer: system prompt + task
        sys_content = system_prompt or "You are an autonomous code agent."
        prompt_entries = self._entries.get("prompt", [])
        prompt_text = "\n".join(e.content for e in prompt_entries)
        full_system = f"{sys_content}\n\n{prompt_text}".strip()
        messages.append({"role": "system", "content": full_system[:self._layer_budget("prompt")]})

        # 2. Working memory: recent conversation
        wm_entries = self._entries.get("working_memory", [])
        if wm_entries:
            wm_text = "\n".join(e.content for e in wm_entries)
            messages.append({"role": "user", "content": f"[Conversation]\n{wm_text[:self._layer_budget('working_memory')]}"})

        # 3. Evidence layer: retrieved documents
        ev_entries = self._entries.get("evidence", [])
        if ev_entries:
            ev_text = "\n".join(e.content for e in ev_entries)
            messages.append({"role": "user", "content": f"[Evidence]\n{ev_text[:self._layer_budget('evidence')]}"})

        # 4. Reasoning layer: intermediate thoughts
        re_entries = self._entries.get("reasoning", [])
        if re_entries:
            re_text = "\n".join(e.content for e in re_entries)
            messages.append({"role": "assistant", "content": f"[Reasoning]\n{re_text[:self._layer_budget('reasoning')]}"})

        # 5. The task itself
        messages.append({"role": "user", "content": task})

        return messages

    def stats(self) -> dict[str, Any]:
        result = {}
        for layer, cfg in self.layers.items():
            used = self._layer_used(layer)
            budget = cfg.max_tokens
            result[layer] = {
                "budget": budget,
                "used": used,
                "reserve": cfg.reserve_tokens,
                "available": budget - cfg.reserve_tokens - used,
                "entries": len(self._entries.get(layer, [])),
                "saturation_pct": round(used / max(budget, 1) * 100, 1),
            }
        total_used = sum(v["used"] for v in result.values())
        result["total"] = {
            "budget": self.total_budget,
            "used": total_used,
            "available": self.total_budget - total_used,
            "saturation_pct": round(total_used / max(self.total_budget, 1) * 100, 1),
        }
        return result

    def summarize_layer(self, layer: str) -> str | None:
        """Summarize a layer's content to free tokens. Returns summary if any."""
        entries = self._entries.get(layer, [])
        if not entries:
            return None
        full = "\n".join(e.content for e in entries)
        # Simple extractive summary: take first and last entries
        summary_parts = []
        if len(entries) > 3:
            summary_parts.append(entries[0].content[:200])
            summary_parts.append(f"... ({len(entries) - 2} entries omitted) ...")
            summary_parts.append(entries[-1].content[:200])
            summary = "\n".join(summary_parts)
            self._entries[layer] = [ContextEntry(
                content=summary, layer=layer, tier="summarized",
                source="summarizer", tokens=len(summary) // 4,
            )]
            return summary
        return None
