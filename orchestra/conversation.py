"""Horizon Orchestra — Conversation Manager.

Multi-turn context management, session persistence, turn compression,
and context window optimization.  Ensures agents have the right amount
of history without exceeding token limits.

Usage::

    from orchestra.conversation import ConversationManager
    conv = ConversationManager(user_id="ashton", max_turns=50)
    conv.add_user("Build me an API")
    conv.add_assistant("Here's the API...")
    context = conv.get_context(max_tokens=8000)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .memory import MemoryStore, SessionContext

__all__ = [
    "ConversationManager",
    "Turn",
    "ConversationConfig",
]

log = logging.getLogger("orchestra.conversation")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    """A single conversation turn."""
    role: str                    # user, assistant, system, tool
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0      # rough token count

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = len(self.content) // 4  # rough: 4 chars per token


@dataclass
class ConversationConfig:
    max_turns: int = 50
    max_context_tokens: int = 32_000
    compression_threshold: int = 40       # compress when turns exceed this
    summary_model: str = "kimi-k2.5"
    persist: bool = True                   # auto-save sessions to memory store


# ---------------------------------------------------------------------------
# Conversation manager
# ---------------------------------------------------------------------------

class ConversationManager:
    """Manages multi-turn conversation state with compression.

    Key features:
    - Rolling window of recent turns
    - Automatic compression of old turns into summaries
    - Token-aware context building for model input
    - Session persistence to MemoryStore
    - Fork/branch for sub-agent conversations
    """

    def __init__(
        self,
        user_id: str = "default",
        session_id: str = "",
        config: ConversationConfig | None = None,
        memory_store: MemoryStore | None = None,
        router: Any = None,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id or hashlib.sha256(
            f"{user_id}:{time.time()}".encode()
        ).hexdigest()[:12]
        self.config = config or ConversationConfig()
        self.memory_store = memory_store
        self.router = router

        self._turns: list[Turn] = []
        self._summaries: list[str] = []  # compressed old context
        self._system_prompt: str = ""
        self._total_turns: int = 0

    # -- turn management ----------------------------------------------------

    def set_system(self, prompt: str) -> None:
        self._system_prompt = prompt

    def add_user(self, content: str, metadata: dict | None = None) -> None:
        self._add_turn("user", content, metadata)

    def add_assistant(self, content: str, metadata: dict | None = None) -> None:
        self._add_turn("assistant", content, metadata)

    def add_tool_result(self, content: str, tool_name: str = "") -> None:
        self._add_turn("tool", content, {"tool_name": tool_name})

    def _add_turn(self, role: str, content: str, metadata: dict | None = None) -> None:
        turn = Turn(role=role, content=content, metadata=metadata or {})
        self._turns.append(turn)
        self._total_turns += 1

        # Auto-compress if needed
        if len(self._turns) > self.config.compression_threshold:
            self._compress_old_turns()

    # -- context building ---------------------------------------------------

    def get_context(self, max_tokens: int | None = None) -> list[dict[str, str]]:
        """Build the message list for model input, respecting token limits.

        Returns OpenAI-format messages: [{role, content}, ...]
        """
        max_tokens = max_tokens or self.config.max_context_tokens
        messages: list[dict[str, str]] = []

        # System prompt
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        # Summaries of old context
        if self._summaries:
            summary_block = "\n\n".join(self._summaries)
            messages.append({
                "role": "system",
                "content": f"Summary of earlier conversation:\n{summary_block}",
            })

        # Recent turns (add from most recent, respecting token budget)
        token_budget = max_tokens - sum(
            len(m["content"]) // 4 for m in messages
        )

        turns_to_include: list[Turn] = []
        tokens_used = 0
        for turn in reversed(self._turns):
            if tokens_used + turn.token_estimate > token_budget:
                break
            turns_to_include.insert(0, turn)
            tokens_used += turn.token_estimate

        for turn in turns_to_include:
            messages.append({"role": turn.role, "content": turn.content})

        return messages

    def get_last_n(self, n: int = 5) -> list[dict[str, str]]:
        """Get the last N turns as messages (no system prompt or summaries)."""
        return [
            {"role": t.role, "content": t.content}
            for t in self._turns[-n:]
        ]

    # -- compression --------------------------------------------------------

    def _compress_old_turns(self) -> None:
        """Compress the oldest turns into a summary."""
        if len(self._turns) <= 10:
            return

        # Take the oldest half of turns and summarize them
        split = len(self._turns) // 2
        old_turns = self._turns[:split]
        self._turns = self._turns[split:]

        # Build summary text
        parts = []
        for t in old_turns:
            prefix = "User" if t.role == "user" else "Assistant"
            parts.append(f"[{prefix}] {t.content[:200]}")
        summary = "Earlier conversation:\n" + "\n".join(parts)

        self._summaries.append(summary)
        log.debug("Compressed %d turns into summary (%d chars)", len(old_turns), len(summary))

    async def compress_with_llm(self) -> str | None:
        """Use the LLM to create a high-quality summary of old turns.

        Requires a router to be set. Falls back to simple truncation.
        """
        if not self.router or len(self._turns) < 20:
            return None

        old_text = "\n".join(
            f"[{t.role}] {t.content[:300]}" for t in self._turns[:len(self._turns) // 2]
        )

        client, model_id = self.router.get_client(self.config.summary_model)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "Summarize this conversation in 3-5 bullet points. Preserve key facts, decisions, and action items."},
                    {"role": "user", "content": old_text[:6000]},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content or ""
            self._summaries.append(summary)

            # Drop the compressed turns
            self._turns = self._turns[len(self._turns) // 2:]

            log.info("LLM-compressed conversation: %d chars summary", len(summary))
            return summary
        except Exception as exc:
            log.warning("LLM compression failed: %s", exc)
            self._compress_old_turns()
            return None

    # -- persistence --------------------------------------------------------

    async def save(self) -> None:
        """Persist the conversation to the memory store."""
        if not self.memory_store or not self.config.persist:
            return

        session = SessionContext(
            session_id=self.session_id,
            user_id=self.user_id,
            turns=[
                {"role": t.role, "content": t.content[:2000], "ts": t.timestamp}
                for t in self._turns
            ],
        )
        await self.memory_store.save_session(session)

    async def load(self, session_id: str) -> bool:
        """Load a previous conversation from the memory store."""
        if not self.memory_store:
            return False

        session = await self.memory_store.load_session(session_id)
        if not session:
            return False

        self.session_id = session.session_id
        self._turns = [
            Turn(
                role=t.get("role", "user"),
                content=t.get("content", ""),
                timestamp=t.get("ts", 0),
            )
            for t in session.turns
        ]
        self._total_turns = len(self._turns)
        log.info("Loaded session %s: %d turns", session_id, len(self._turns))
        return True

    # -- forking (for sub-agents) -------------------------------------------

    def fork(self, system_prompt: str = "") -> "ConversationManager":
        """Create a child conversation with inherited context.

        Used when spawning sub-agents: the child gets a summary of
        the parent's conversation as context.
        """
        child = ConversationManager(
            user_id=self.user_id,
            config=self.config,
            memory_store=self.memory_store,
            router=self.router,
        )
        # Inject parent context as summary
        if self._turns:
            parent_summary = "\n".join(
                f"[{t.role}] {t.content[:200]}" for t in self._turns[-10:]
            )
            child._summaries.append(f"Parent conversation context:\n{parent_summary}")
        if system_prompt:
            child.set_system(system_prompt)
        return child

    # -- properties ---------------------------------------------------------

    @property
    def total_turns(self) -> int:
        return self._total_turns

    @property
    def current_turns(self) -> int:
        return len(self._turns)

    @property
    def estimated_tokens(self) -> int:
        return sum(t.token_estimate for t in self._turns) + sum(
            len(s) // 4 for s in self._summaries
        )

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_turns": self._total_turns,
            "current_turns": len(self._turns),
            "summaries": len(self._summaries),
            "estimated_tokens": self.estimated_tokens,
        }
