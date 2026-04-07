"""
orchestra/adaptive_context.py
-------------------------------
Adaptive context window management — auto-compress at 80% capacity
with priority-based message retention.

Optimised for Kimi K2.5's 262K token context window but works with
any model by adjusting ``AdaptiveContextConfig.max_tokens``.
"""
from __future__ import annotations

__all__ = [
    "AdaptiveContextConfig",
    "TokenCounter",
    "PriorityMessage",
    "AdaptiveContext",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("orchestra.adaptive_context")

_OVERHEAD_PER_MESSAGE = 4  # approximate token overhead per message dict


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AdaptiveContextConfig:
    """Configuration for the adaptive context window."""

    max_tokens: int = 262144                        # Kimi K2.5 context window
    compress_threshold_pct: float = 80.0           # compress when 80% full
    min_recent_turns: int = 5                       # always keep last N user turns
    priority_categories: list[str] = field(
        default_factory=lambda: [
            "system",
            "user_latest",
            "tool_result_latest",
        ]
    )
    compression_model: str = "kimi-k2.5"
    token_counter: str = "cl100k_base"             # tiktoken encoding or "chars/4"


@dataclass
class PriorityMessage:
    """A message with associated priority metadata."""

    role: str
    content: str
    priority: int = 3          # 1 = highest, 5 = lowest
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
    compressible: bool = True  # False for system prompts and latest user msg


# ---------------------------------------------------------------------------
# TokenCounter
# ---------------------------------------------------------------------------

class TokenCounter:
    """Count tokens using tiktoken if available, else chars/4 heuristic."""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        self._encoding_name = encoding
        self._enc: Any = None
        self._tiktoken_available = False
        self._try_load_tiktoken()

    def _try_load_tiktoken(self) -> None:
        try:
            import tiktoken  # type: ignore

            self._enc = tiktoken.get_encoding(self._encoding_name)
            self._tiktoken_available = True
            logger.debug("TokenCounter: using tiktoken encoding=%s", self._encoding_name)
        except Exception:
            logger.debug(
                "TokenCounter: tiktoken not available, using chars/4 fallback"
            )

    def count(self, text: str) -> int:
        """Count tokens in a string."""
        if not text:
            return 0
        if self._tiktoken_available and self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:
                pass
        # Fallback: approximate 4 chars per token
        return max(1, len(text) // 4)

    def count_messages(self, messages: list[dict]) -> int:
        """Sum tokens across all messages including per-message overhead."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multi-part content (e.g. tool results)
                text = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            else:
                text = str(content) if content else ""

            role = str(msg.get("role", ""))
            total += self.count(text) + self.count(role) + _OVERHEAD_PER_MESSAGE
        return total


# ---------------------------------------------------------------------------
# AdaptiveContext
# ---------------------------------------------------------------------------

class AdaptiveContext:
    """
    Manages a dynamic context window with priority-based retention and
    automatic LLM summarisation when nearing capacity.

    Priority scale:
      1 — system prompt, latest user message (never dropped)
      2 — memory injections, latest tool results
      3 — recent conversation turns (default)
      4 — older turns
      5 — background context, injected lore (first to compress)
    """

    def __init__(self, config: AdaptiveContextConfig, router: Any) -> None:
        self._config = config
        self._router = router
        self._counter = TokenCounter(config.token_counter)
        self._messages: list[PriorityMessage] = []
        self._compressed_count: int = 0
        self._compression_lock = asyncio.Lock()
        logger.info(
            "AdaptiveContext initialised (max_tokens=%d, threshold=%.0f%%)",
            config.max_tokens,
            config.compress_threshold_pct,
        )

    # ------------------------------------------------------------------
    # Adding messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        priority: int = 3,
    ) -> None:
        """Add a message and compute its token count."""
        tokens = self._counter.count(content) + self._counter.count(role) + _OVERHEAD_PER_MESSAGE

        # Downgrade previously-latest user messages
        if role == "user":
            for pm in self._messages:
                if pm.role == "user" and pm.priority == 1:
                    pm.priority = 3  # demote old "latest" user messages
            # New user message is highest priority
            priority = 1
            compressible = False
        elif role == "system":
            priority = 1
            compressible = False
        else:
            compressible = True

        pm = PriorityMessage(
            role=role,
            content=content,
            priority=priority,
            token_count=tokens,
            compressible=compressible,
        )
        self._messages.append(pm)
        logger.debug(
            "add_message: role=%s priority=%d tokens=%d total=%d",
            role,
            priority,
            tokens,
            self._estimate_tokens(),
        )

    # ------------------------------------------------------------------
    # Building the context
    # ------------------------------------------------------------------

    def get_messages(self, max_tokens: int = 0) -> list[dict]:
        """Return an optimised message list within the token budget.

        Selection order:
        1. All non-compressible messages (system, latest user).
        2. Latest tool results (priority ≤ 2).
        3. Fill remaining budget with older messages by ascending priority.
        """
        budget = max_tokens or self._config.max_tokens

        # Separate non-compressible (always include) from compressible
        must_include: list[PriorityMessage] = [
            m for m in self._messages if not m.compressible
        ]
        optional: list[PriorityMessage] = [
            m for m in self._messages if m.compressible
        ]

        must_tokens = sum(m.token_count for m in must_include)
        remaining = budget - must_tokens

        if remaining <= 0:
            logger.warning(
                "get_messages: must-include messages alone exceed token budget"
            )
            return [{"role": m.role, "content": m.content} for m in must_include]

        # Sort optional by priority (ascending = highest first) then timestamp
        optional_sorted = sorted(optional, key=lambda m: (m.priority, m.timestamp))

        selected: list[PriorityMessage] = []
        used = 0
        for msg in optional_sorted:
            if used + msg.token_count <= remaining:
                selected.append(msg)
                used += msg.token_count
            else:
                # Cannot fit this message; skip (it may be compressed later)
                pass

        # Combine: must-include first, then optional in chronological order
        all_selected = must_include + sorted(selected, key=lambda m: m.timestamp)

        logger.debug(
            "get_messages: selected %d messages, ~%d tokens",
            len(all_selected),
            must_tokens + used,
        )
        return [{"role": m.role, "content": m.content} for m in all_selected]

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    async def compress(self, target_tokens: int = 0) -> int:
        """Force compression of compressible messages.

        Returns the number of tokens freed.
        """
        async with self._compression_lock:
            target = target_tokens or int(
                self._config.max_tokens * self._config.compress_threshold_pct / 100
            )
            before = self._estimate_tokens()

            # Find compressible blocks (lowest priority first)
            candidates = [
                m for m in self._messages
                if m.compressible and m.priority >= 3
            ]
            if not candidates:
                logger.debug("compress: no compressible messages found")
                return 0

            # Sort by priority (highest number = lowest priority = compress first)
            # and take oldest first within same priority
            candidates.sort(key=lambda m: (-m.priority, m.timestamp))

            # Group into a block for summarisation
            to_compress: list[PriorityMessage] = []
            freed = 0
            for msg in candidates:
                if self._estimate_tokens() - freed <= target:
                    break
                to_compress.append(msg)
                freed += msg.token_count

            if not to_compress:
                logger.debug("compress: already under target")
                return 0

            summary = await self._summarize_messages(
                [{"role": m.role, "content": m.content} for m in to_compress]
            )

            # Replace compressed messages with a single summary injection
            ids_to_remove = {id(m) for m in to_compress}
            self._messages = [m for m in self._messages if id(m) not in ids_to_remove]

            summary_tokens = self._counter.count(summary)
            summary_msg = PriorityMessage(
                role="assistant",
                content=f"[COMPRESSED SUMMARY]\n{summary}",
                priority=2,
                token_count=summary_tokens + _OVERHEAD_PER_MESSAGE,
                compressible=False,  # Don't compress summaries again
                timestamp=to_compress[0].timestamp,  # Keep original timestamp position
            )
            # Insert summary at the position of the first compressed message
            # Find insertion index
            min_ts = to_compress[0].timestamp
            insert_idx = 0
            for i, m in enumerate(self._messages):
                if m.timestamp <= min_ts:
                    insert_idx = i + 1
            self._messages.insert(insert_idx, summary_msg)

            self._compressed_count += len(to_compress)
            after = self._estimate_tokens()
            freed_actual = before - after
            logger.info(
                "compress: freed ~%d tokens (before=%d after=%d, compressed %d messages)",
                freed_actual,
                before,
                after,
                len(to_compress),
            )
            return freed_actual

    async def _summarize_messages(self, messages: list[dict]) -> str:
        """LLM call to summarise a block of messages into a compact summary."""
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You are a concise summariser. Summarise the following conversation "
                    "segment into 3-5 sentences, preserving all key facts, decisions, "
                    "tool results, and conclusions. Be dense and specific."
                ),
            },
            {
                "role": "user",
                "content": "Summarise this conversation segment:\n\n"
                + "\n".join(
                    f"[{m['role'].upper()}]: {m['content'][:1000]}"
                    for m in messages
                ),
            },
        ]

        try:
            if hasattr(self._router, "complete"):
                summary = await self._router.complete(
                    prompt_messages[-1]["content"],
                    system=prompt_messages[0]["content"],
                    model=self._config.compression_model,
                )
                return str(summary)

            # Fallback: naive truncation summary
            texts = [
                f"[{m['role'].upper()}]: {m['content'][:200]}" for m in messages[:5]
            ]
            return "Summary: " + " | ".join(texts)
        except Exception as exc:
            logger.exception("_summarize_messages: LLM error")
            # Fall back to truncated content
            return "Compressed segment: " + " ".join(
                m["content"][:100] for m in messages[:3]
            )

    # ------------------------------------------------------------------
    # Stats / utilities
    # ------------------------------------------------------------------

    def _estimate_tokens(self) -> int:
        """Sum of all message token counts."""
        return sum(m.token_count for m in self._messages)

    def _is_over_threshold(self) -> bool:
        """True if estimated token usage exceeds compress_threshold_pct."""
        threshold = int(
            self._config.max_tokens * self._config.compress_threshold_pct / 100
        )
        return self._estimate_tokens() > threshold

    def get_stats(self) -> dict:
        """Return context usage statistics."""
        total = self._estimate_tokens()
        pct = total / self._config.max_tokens * 100 if self._config.max_tokens > 0 else 0
        return {
            "total_tokens": total,
            "max_tokens": self._config.max_tokens,
            "pct_used": round(pct, 1),
            "message_count": len(self._messages),
            "compressed_count": self._compressed_count,
            "over_threshold": self._is_over_threshold(),
        }

    def reset(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._compressed_count = 0
        logger.debug("reset: context cleared")

    def inject_memory(self, memory_block: str) -> None:
        """Inject a memory context block at priority 2."""
        self.add_message(
            role="system",
            content=f"[MEMORY CONTEXT]\n{memory_block}",
            priority=2,
        )
        # Mark it as compressible (priority 2 memory can be compressed)
        if self._messages:
            self._messages[-1].compressible = True

    def inject_context(self, context: str, priority: int = 3) -> None:
        """Add arbitrary background context."""
        self.add_message(
            role="system",
            content=f"[CONTEXT]\n{context}",
            priority=priority,
        )
        if self._messages:
            self._messages[-1].compressible = True
