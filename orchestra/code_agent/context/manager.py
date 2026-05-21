from __future__ import annotations

import math
from typing import Any


class ContextManager:
    """Manage LLM context windows: track token usage, trim, prioritize content."""

    TIERS = {
        "critical": 1.0,
        "important": 0.6,
        "normal": 0.3,
        "low": 0.1,
    }

    TIER_COLORS = {
        "critical": (255, 80, 80),    # red
        "important": (255, 180, 50),  # orange
        "normal": (80, 160, 255),     # blue
        "low": (140, 140, 160),       # gray
    }

    TIER_ANSI = {
        "critical": "red",
        "important": "yellow",
        "normal": "blue",
        "low": "white",
    }

    def __init__(self, max_tokens: int = 128000, reserve_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self._entries: list[dict[str, Any]] = []

    def add(self, content: str, tier: str = "normal", source: str = "") -> None:
        tokens = self._estimate_tokens(content)
        self._entries.append({
            "content": content,
            "tier": tier,
            "source": source,
            "tokens": tokens,
            "priority": self.TIERS.get(tier, 0.3),
        })

    def _estimate_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return len(text) // 4

    def has_space_for(self, content: str) -> bool:
        needed = self._estimate_tokens(content)
        return (self.current_tokens() + needed) <= (self.max_tokens - self.reserve_tokens)

    def current_tokens(self) -> int:
        return sum(e["tokens"] for e in self._entries)

    def trim(self) -> list[dict[str, Any]]:
        total = self.current_tokens()
        budget = self.max_tokens - self.reserve_tokens

        if total <= budget:
            return self._entries

        sorted_entries = sorted(self._entries, key=lambda e: e["priority"])
        removed: list[dict[str, Any]] = []

        while total > budget and sorted_entries:
            entry = sorted_entries.pop(0)
            total -= entry["tokens"]
            removed.append(entry)

        self._entries = sorted_entries
        return removed

    def get_context(self) -> str:
        parts = []
        sorted_entries = sorted(self._entries, key=lambda e: e["priority"], reverse=True)
        for e in sorted_entries:
            tag = f"[{e['tier'].upper()}]" if e['source'] else ""
            header = f"{tag} " if tag else ""
            parts.append(f"{header}{e['content']}")
        return "\n\n".join(parts)

    def stats(self) -> dict[str, Any]:
        used = self.current_tokens()
        effective_max = self.max_tokens - self.reserve_tokens
        pct = (used / effective_max * 100) if effective_max > 0 else 0
        return {
            "max_tokens": self.max_tokens,
            "used_tokens": used,
            "reserve_tokens": self.reserve_tokens,
            "available_tokens": effective_max - used if used <= effective_max else 0,
            "effective_limit": effective_max,
            "saturation_pct": round(pct, 1),
            "entries": len(self._entries),
            "tiers": {t: sum(1 for e in self._entries if e["tier"] == t) for t in self.TIERS},
            "tier_tokens": {t: sum(e["tokens"] for e in self._entries if e["tier"] == t) for t in self.TIERS},
            "sources": self._sources_summary(),
        }

    def _sources_summary(self) -> dict[str, int]:
        sources: dict[str, int] = {}
        for e in self._entries:
            s = e["source"] or "unknown"
            sources[s] = sources.get(s, 0) + e["tokens"]
        return sources

    def visual_data(self) -> dict[str, Any]:
        """Rich structured data for UI rendering."""
        s = self.stats()
        used = s["used_tokens"]
        effective_max = s["effective_limit"]
        pct = s["saturation_pct"]

        bar_blocks = []
        remaining = effective_max
        for tier in ["critical", "important", "normal", "low"]:
            t_tokens = s["tier_tokens"].get(tier, 0)
            if t_tokens > 0:
                t_pct = (t_tokens / effective_max * 100) if effective_max > 0 else 0
                bar_blocks.append({
                    "tier": tier,
                    "tokens": t_tokens,
                    "pct": round(t_pct, 1),
                    "color": self.TIER_COLORS[tier],
                })
                remaining -= t_tokens

        reserve_pct = (self.reserve_tokens / effective_max * 100) if effective_max > 0 else 0
        free_pct = max(0, (remaining / effective_max * 100) if effective_max > 0 else 0)

        saturation_level = "low"
        if pct >= 90:
            saturation_level = "critical"
        elif pct >= 75:
            saturation_level = "high"
        elif pct >= 50:
            saturation_level = "moderate"

        return {
            "stats": s,
            "bar_blocks": bar_blocks,
            "reserve_pct": round(reserve_pct, 1),
            "free_pct": round(free_pct, 1),
            "free_tokens": max(0, remaining),
            "saturation_level": saturation_level,
            "bar_width": 40,
        }

    def clear(self, tier: str = "") -> None:
        if tier:
            self._entries = [e for e in self._entries if e["tier"] != tier]
        else:
            self._entries = []

    def summary(self) -> str:
        s = self.stats()
        bar = self._ascii_bar(s["saturation_pct"])
        return (
            f"Context: [{bar}] {s['used_tokens']:,}/{s['max_tokens']:,} tokens "
            f"({s['saturation_pct']}%) | {s['entries']} entries"
        )

    def _ascii_bar(self, pct: float, width: int = 20) -> str:
        filled = int(pct / 100 * width)
        bar = "#" * filled + "." * (width - filled)
        return bar
