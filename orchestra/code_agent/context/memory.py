from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    role: str
    content: str
    tokens: int = 0

    def __post_init__(self):
        if not self.tokens:
            self.tokens = len(self.content) // 4


class WorkingMemory:
    """Short-term conversation history with selective summarization.

    Preserves the last N turns in full. Older turns are summarized
    to maintain continuity without unbounded growth.
    """

    def __init__(self, max_turns: int = 10, max_tokens: int = 4096):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._turns: list[Turn] = []
        self._summary: str = ""

    def add_turn(self, role: str, content: str) -> None:
        self._turns.append(Turn(role=role, content=content))
        self._maybe_summarize()

    def _maybe_summarize(self) -> None:
        """If over budget, summarize older half of turns."""
        total = sum(t.tokens for t in self._turns)
        if total <= self.max_tokens and len(self._turns) <= self.max_turns:
            return

        # Keep the last N/2 turns in full, summarize the rest
        keep = max(self.max_turns // 2, 3)
        if len(self._turns) <= keep + 2:
            return

        to_summarize = self._turns[:-keep]
        summary_parts = []
        for t in to_summarize:
            label = "User" if t.role == "user" else "Assistant"
            summary_parts.append(f"{label}: {t.content[:100]}")
        self._summary = "\n".join(summary_parts)
        self._turns = self._turns[-keep:]

    def get_context(self) -> str:
        """Build the working memory context string."""
        parts = []
        if self._summary:
            parts.append(f"[Earlier]\n{self._summary}")
        for t in self._turns:
            label = "You" if t.role == "user" else "Assistant"
            parts.append(f"{label}: {t.content}")
        return "\n\n".join(parts)

    def stats(self) -> dict[str, Any]:
        return {
            "turns": len(self._turns),
            "total_tokens": sum(t.tokens for t in self._turns),
            "max_turns": self.max_turns,
            "has_summary": bool(self._summary),
            "summarized_tokens": len(self._summary) // 4 if self._summary else 0,
        }
