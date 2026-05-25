"""Horizon Orchestra — Pluggable Context Engine.

Inspired by OpenClaw's ContextEngine architecture.  Provides a
plugin-based system for assembling, compacting, and evolving the
context passed to LLM agents.

Two built-in plugins are provided:

* :class:`DefaultContextPlugin` — sliding-window + LLM summarisation.
* :class:`RAGContextPlugin` — embedding-based retrieval over ingested docs.

Usage::

    from orchestra.context_engine import ContextEngine, DefaultContextPlugin

    engine = ContextEngine()
    engine.register_plugin(DefaultContextPlugin(), name="default")
    engine.set_active("default")

    await engine.ingest("The user's name is Alice.", source="profile")
    messages = await engine.build_context("What is the user's name?", max_tokens=4096)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ContextPlugin",
    "DefaultContextPlugin",
    "RAGContextPlugin",
    "ContextEngine",
]

log = logging.getLogger("orchestra.context_engine")


# ---------------------------------------------------------------------------
# Token counting — use TextChunker's tiktoken-backed counter throughout
# ---------------------------------------------------------------------------

try:
    from orchestra.embeddings.chunker import count_tokens as _estimate_tokens
except Exception:  # chunker not yet importable (circular or missing dep)
    def _estimate_tokens(text: str) -> int:  # type: ignore[misc]
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Abstract base plugin
# ---------------------------------------------------------------------------

class ContextPlugin(ABC):
    """Abstract base class for context plugins.

    All lifecycle hooks receive simple Python objects and must be
    implemented as async coroutines.
    """

    @abstractmethod
    async def bootstrap(self, config: dict[str, Any]) -> None:
        """Initialise the plugin with runtime configuration.

        Called once when the plugin is registered or activated.

        Args:
            config: Arbitrary configuration dict (model names, paths, etc.).
        """

    @abstractmethod
    async def ingest(self, content: str, source: str) -> None:
        """Add a document or piece of content to the context store.

        Args:
            content: Raw text content to ingest.
            source: Label or path identifying the content origin.
        """

    @abstractmethod
    async def assemble(self, query: str, max_tokens: int) -> str:
        """Assemble the most relevant context for *query*.

        Args:
            query: Current user query or task description.
            max_tokens: Budget for the assembled context.

        Returns:
            Context string, token count ≤ max_tokens (approximately).
        """

    @abstractmethod
    async def compact(self, context: str, target_tokens: int) -> str:
        """Summarise *context* to fit within *target_tokens*.

        Args:
            context: Full context string to compact.
            target_tokens: Target token budget.

        Returns:
            Compacted context string.
        """

    @abstractmethod
    async def after_turn(self, turn: dict[str, Any]) -> None:
        """Hook called after each agent turn completes.

        Args:
            turn: Dict with keys ``role``, ``content``, ``timestamp``, etc.
        """

    @abstractmethod
    async def prepare_subagent_spawn(self, task: str) -> str:
        """Prepare a context string for spawning a sub-agent.

        Args:
            task: The task the sub-agent will perform.

        Returns:
            Context string suitable for injection into the sub-agent's system
            prompt.
        """


# ---------------------------------------------------------------------------
# DefaultContextPlugin
# ---------------------------------------------------------------------------

class DefaultContextPlugin(ContextPlugin):
    """Sliding-window context with LLM-based summarisation.

    Maintains:
    - An ordered list of ingested documents.
    - A rolling conversation window.
    - Periodic summarisation when the window exceeds the token budget.

    Args:
        router: ModelRouter for LLM summarisation calls. If None,
            summarisation truncates rather than compressing.
        model: Model name to use for summarisation.
        max_window_tokens: Token budget for the sliding conversation window.
    """

    def __init__(
        self,
        router: Any | None = None,
        model: str = "kimi-k2.5",
        max_window_tokens: int = 8_000,
    ) -> None:
        self.router = router
        self.model = model
        self.max_window_tokens = max_window_tokens
        self._docs: list[tuple[str, str]] = []  # (content, source)
        self._turns: list[dict[str, Any]] = []
        self._summary: str = ""

    async def bootstrap(self, config: dict[str, Any]) -> None:
        """Initialise with config values.

        Recognises keys: ``router``, ``model``, ``max_window_tokens``.
        """
        if "router" in config:
            self.router = config["router"]
        if "model" in config:
            self.model = config["model"]
        if "max_window_tokens" in config:
            self.max_window_tokens = int(config["max_window_tokens"])
        log.debug("DefaultContextPlugin bootstrapped (model=%s)", self.model)

    async def ingest(self, content: str, source: str) -> None:
        """Add a document to the internal store."""
        self._docs.append((content, source))
        log.debug("Ingested %d chars from %r", len(content), source)

    async def assemble(self, query: str, max_tokens: int) -> str:
        """Assemble context relevant to *query*.

        Strategy:
        1. Include the running summary (if any).
        2. Add documents in reverse-insertion order until token budget fills.
        3. Add the most recent turns.

        Args:
            query: Current query.
            max_tokens: Token budget.

        Returns:
            Assembled context string.
        """
        parts: list[str] = []
        used_tokens = 0

        # Always include the running summary first
        if self._summary:
            summary_block = f"<context_summary>\n{self._summary}\n</context_summary>"
            t = _estimate_tokens(summary_block)
            if t <= max_tokens:
                parts.append(summary_block)
                used_tokens += t

        # Add documents (most recently ingested first)
        for content, source in reversed(self._docs):
            block = f"<document source={source!r}>\n{content}\n</document>"
            t = _estimate_tokens(block)
            if used_tokens + t > max_tokens:
                break
            parts.append(block)
            used_tokens += t

        # Add recent conversation turns
        for turn in reversed(self._turns[-20:]):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            block = f"[{role}] {content}"
            t = _estimate_tokens(block)
            if used_tokens + t > max_tokens:
                break
            parts.insert(0, block)  # Turns go at the beginning
            used_tokens += t

        return "\n\n".join(filter(None, parts))

    async def compact(self, context: str, target_tokens: int) -> str:
        """Summarise *context* to fit within *target_tokens*.

        Uses the LLM if available; otherwise truncates from the start.

        Args:
            context: Context to compress.
            target_tokens: Target token count.

        Returns:
            Compressed context string.
        """
        current_tokens = _estimate_tokens(context)
        if current_tokens <= target_tokens:
            return context

        if self.router is None:
            # Fallback: truncate
            chars_target = target_tokens * 4
            return context[-chars_target:]

        prompt = (
            f"Summarise the following context in approximately {target_tokens} tokens. "
            f"Preserve the most important facts, decisions, and code snippets.\n\n"
            f"{context}"
        )

        try:
            client, model_id = self.router.get_client(self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are a context compression assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=target_tokens,
            )
            summary = response.choices[0].message.content or context[-target_tokens * 4:]
            log.debug("Compacted context from %d to %d tokens", current_tokens, _estimate_tokens(summary))
            return summary
        except Exception as exc:
            log.warning("Context compaction failed: %s", exc)
            return context[-target_tokens * 4:]

    async def after_turn(self, turn: dict[str, Any]) -> None:
        """Record a conversation turn and compact if over budget."""
        self._turns.append(turn)

        # Compact the conversation window if needed
        window_text = "\n".join(
            f"[{t.get('role')}] {t.get('content', '')}"
            for t in self._turns
        )
        if _estimate_tokens(window_text) > self.max_window_tokens:
            # Summarise older turns into the running summary
            turns_to_summarise = self._turns[:-10]  # Keep last 10 turns fresh
            if turns_to_summarise:
                old_text = "\n".join(
                    f"[{t.get('role')}] {t.get('content', '')}"
                    for t in turns_to_summarise
                )
                new_summary = await self.compact(
                    (self._summary + "\n\n" + old_text).strip(),
                    target_tokens=self.max_window_tokens // 2,
                )
                self._summary = new_summary
                self._turns = self._turns[-10:]
                log.debug("Compacted conversation window; keeping last 10 turns")

    async def prepare_subagent_spawn(self, task: str) -> str:
        """Build a concise context snippet for a sub-agent."""
        # Include summary + last 5 turns
        parts: list[str] = []
        if self._summary:
            parts.append(f"Session summary:\n{self._summary}")

        recent = self._turns[-5:]
        if recent:
            turns_text = "\n".join(
                f"[{t.get('role')}] {t.get('content', '')[:500]}" for t in recent
            )
            parts.append(f"Recent conversation:\n{turns_text}")

        parts.append(f"Sub-agent task: {task}")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# RAGContextPlugin
# ---------------------------------------------------------------------------

@dataclass
class _Chunk:
    """An embedded text chunk for RAG retrieval."""
    source: str
    text: str
    embedding: list[float] = field(default_factory=list, repr=False)
    created_at: float = field(default_factory=time.time)


class RAGContextPlugin(ContextPlugin):
    """Embedding-based retrieval-augmented context plugin.

    Ingested documents are split into chunks using Orchestra's TextChunker
    (token-aware, recursive by default), embedded, and stored in memory.
    At assembly time the most semantically similar chunks are retrieved.

    Args:
        router: ModelRouter for embedding and summarisation calls.
        model: Chat model for summarisation/compaction.
        embedding_model: Model name for embeddings.
        chunk_size: Max tokens per chunk (was previously characters — now tokens).
        chunk_overlap: Token overlap between adjacent chunks.
        chunk_strategy: TextChunker strategy (recursive, sentence, paragraph…).
        top_k: Number of chunks to retrieve per query.
    """

    def __init__(
        self,
        router: Any | None = None,
        model: str = "kimi-k2.5",
        embedding_model: str = "text-embedding-3-small",
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        chunk_strategy: str = "recursive",
        top_k: int = 5,
    ) -> None:
        self.router = router
        self.model = model
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunk_strategy = chunk_strategy
        self.top_k = top_k
        self._chunks: list[_Chunk] = []
        self._turns: list[dict[str, Any]] = []
        self._summary: str = ""

        try:
            from orchestra.embeddings.chunker import TextChunker
            self._chunker: Any = TextChunker(
                default_chunk_size=chunk_size,
                default_overlap=chunk_overlap,
                default_strategy=chunk_strategy,
                min_chunk_size=20,
            )
        except Exception:
            self._chunker = None

    async def bootstrap(self, config: dict[str, Any]) -> None:
        """Initialise from config dict."""
        changed = False
        for key in ("router", "model", "embedding_model", "chunk_size",
                    "chunk_overlap", "chunk_strategy", "top_k"):
            if key in config:
                setattr(self, key, config[key])
                changed = True
        if changed and self._chunker is not None:
            try:
                from orchestra.embeddings.chunker import TextChunker
                self._chunker = TextChunker(
                    default_chunk_size=self.chunk_size,
                    default_overlap=self.chunk_overlap,
                    default_strategy=self.chunk_strategy,
                    min_chunk_size=20,
                )
            except Exception:
                pass
        log.debug("RAGContextPlugin bootstrapped")

    async def ingest(self, content: str, source: str) -> None:
        """Split *content* into chunks via TextChunker and embed each."""
        if self._chunker is not None:
            raw_chunks = [c.text for c in self._chunker.chunk(content)]
        else:
            # Fallback: paragraph split, token-aware size
            raw_chunks = self._split_fallback(content, self.chunk_size)

        log.debug("Ingesting %d chunks from %r", len(raw_chunks), source)
        for chunk_text in raw_chunks:
            embedding = await self._embed(chunk_text)
            self._chunks.append(_Chunk(source=source, text=chunk_text, embedding=embedding))

    async def assemble(self, query: str, max_tokens: int) -> str:
        """Retrieve the most relevant chunks for *query*.

        Args:
            query: User query or task description.
            max_tokens: Token budget.

        Returns:
            Assembled context string with source attribution.
        """
        if not self._chunks:
            return ""

        query_emb = await self._embed(query)
        scored: list[tuple[float, _Chunk]] = []

        for chunk in self._chunks:
            if not chunk.embedding:
                continue
            score = self._cosine(query_emb, chunk.embedding)
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored[: self.top_k]

        parts: list[str] = []
        used_tokens = 0

        for score, chunk in top_chunks:
            block = f"[Source: {chunk.source} | Relevance: {score:.2f}]\n{chunk.text}"
            t = _estimate_tokens(block)
            if used_tokens + t > max_tokens:
                break
            parts.append(block)
            used_tokens += t

        # Append recent turns
        for turn in self._turns[-5:]:
            block = f"[{turn.get('role')}] {turn.get('content', '')}"
            t = _estimate_tokens(block)
            if used_tokens + t > max_tokens:
                break
            parts.append(block)
            used_tokens += t

        return "\n\n".join(parts)

    async def compact(self, context: str, target_tokens: int) -> str:
        """Summarise *context* using the LLM.

        Args:
            context: Context to compact.
            target_tokens: Target token count.

        Returns:
            Compacted context.
        """
        if _estimate_tokens(context) <= target_tokens:
            return context

        if self.router is None:
            return context[-target_tokens * 4:]

        try:
            client, model_id = self.router.get_client(self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "Summarise concisely."},
                    {
                        "role": "user",
                        "content": (
                            f"Summarise in {target_tokens} tokens:\n\n{context}"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=target_tokens,
            )
            return response.choices[0].message.content or context[-target_tokens * 4:]
        except Exception as exc:
            log.warning("RAG compact failed: %s", exc)
            return context[-target_tokens * 4:]

    async def after_turn(self, turn: dict[str, Any]) -> None:
        """Record a turn and ingest its content for future retrieval."""
        self._turns.append(turn)
        content = turn.get("content", "")
        if content and len(content) > 100:
            await self.ingest(content, source=f"turn:{turn.get('role', 'unknown')}")

    async def prepare_subagent_spawn(self, task: str) -> str:
        """Retrieve task-relevant context for a sub-agent."""
        assembled = await self.assemble(task, max_tokens=2000)
        return f"Relevant context:\n{assembled}\n\nTask: {task}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _embed(self, text: str) -> list[float]:
        """Embed *text* using the configured model.

        Falls back to a deterministic hash-based pseudo-embedding if the
        router is unavailable.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        if self.router is None:
            return self._hash_embed(text)

        try:
            client, _ = self.router.get_client(self.model)
            # Use the raw httpx client to call an embeddings endpoint
            # since AsyncOpenAI supports embeddings directly
            from openai import AsyncOpenAI
            # Try to get an embedding-capable client
            oai_key = os.environ.get("OPENAI_API_KEY")
            pplx_key = os.environ.get("PERPLEXITY_API_KEY")
            if oai_key:
                emb_client = AsyncOpenAI(api_key=oai_key)
                resp = await emb_client.embeddings.create(
                    model=self.embedding_model, input=[text]
                )
                return resp.data[0].embedding
            elif pplx_key:
                emb_client = AsyncOpenAI(
                    base_url="https://api.perplexity.ai", api_key=pplx_key
                )
                resp = await emb_client.embeddings.create(
                    model="sonar-embedding", input=[text]
                )
                return resp.data[0].embedding
            else:
                return self._hash_embed(text)
        except Exception as exc:
            log.debug("Embedding failed (%s); using hash fallback", exc)
            return self._hash_embed(text)

    @staticmethod
    def _hash_embed(text: str, dim: int = 256) -> list[float]:
        """Deterministic hash-based pseudo-embedding for offline use.

        Args:
            text: Input text.
            dim: Embedding dimensionality.

        Returns:
            Float list of length *dim*.
        """
        h = hashlib.sha256(text.encode()).digest()
        floats: list[float] = []
        while len(floats) < dim:
            h = hashlib.sha256(h).digest()
            for i in range(0, len(h), 4):
                if len(floats) >= dim:
                    break
                val = struct.unpack("f", h[i : i + 4])[0]
                clamped = max(-1.0, min(1.0, val / 1e38 if abs(val) > 1 else val))
                floats.append(clamped)
        return floats[:dim]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two equal-length vectors.

        Args:
            a: First vector.
            b: Second vector.

        Returns:
            Similarity score in [-1, 1].
        """
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _split_fallback(text: str, chunk_size: int) -> list[str]:
        """Paragraph-aware split used only when TextChunker is unavailable.

        Uses *token* counts (via _estimate_tokens) rather than character
        counts, and carries a 12% overlap between consecutive chunks.
        """
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""
        overlap_tokens = max(1, int(chunk_size * 0.12))

        for para in paragraphs:
            candidate = (current + "\n\n" + para).strip() if current else para
            if _estimate_tokens(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                if _estimate_tokens(para) > chunk_size:
                    # Token-aware stride split
                    words = para.split()
                    buf: list[str] = []
                    buf_tok = 0
                    for w in words:
                        wt = _estimate_tokens(w)
                        if buf_tok + wt > chunk_size and buf:
                            chunks.append(" ".join(buf))
                            # carry overlap words
                            keep: list[str] = []
                            keep_tok = 0
                            for bw in reversed(buf):
                                bt = _estimate_tokens(bw)
                                if keep_tok + bt > overlap_tokens:
                                    break
                                keep.insert(0, bw)
                                keep_tok += bt
                            buf = keep
                            buf_tok = keep_tok
                        buf.append(w)
                        buf_tok += wt
                    if buf:
                        current = " ".join(buf)
                    else:
                        current = ""
                else:
                    current = para

        if current:
            chunks.append(current)
        return chunks


# ---------------------------------------------------------------------------
# ContextEngine
# ---------------------------------------------------------------------------

class ContextEngine:
    """Multi-plugin context management engine.

    Maintains a registry of named :class:`ContextPlugin` instances. One
    plugin is "active" at a time; all engine methods delegate to it.

    Args:
        default_plugin: Plugin instance to register as ``"default"``
            and activate immediately. If None, you must call
            :meth:`register_plugin` and :meth:`set_active` before use.
    """

    def __init__(self, default_plugin: ContextPlugin | None = None) -> None:
        self._plugins: dict[str, ContextPlugin] = {}
        self._active: str = ""

        if default_plugin is not None:
            self._plugins["default"] = default_plugin
            self._active = "default"

    # ------------------------------------------------------------------
    # Plugin management
    # ------------------------------------------------------------------

    def register_plugin(
        self,
        plugin: ContextPlugin,
        name: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        """Register a plugin under *name*.

        If this is the first plugin, it is automatically set as active.

        Args:
            plugin: Plugin instance to register.
            name: Registry name. Defaults to the plugin class name in
                lowercase.
            config: Optional bootstrap config passed to
                :meth:`ContextPlugin.bootstrap`.
        """
        if not name:
            name = type(plugin).__name__.lower()
        self._plugins[name] = plugin
        if not self._active:
            self._active = name
        log.debug("Registered context plugin %r", name)

    def set_active(self, name: str) -> None:
        """Set the active plugin by name.

        Args:
            name: Plugin registry name.

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._plugins:
            raise KeyError(f"Context plugin {name!r} is not registered")
        self._active = name
        log.debug("Active context plugin → %r", name)

    @property
    def active_plugin(self) -> ContextPlugin:
        """Return the currently active plugin instance."""
        if not self._active:
            raise RuntimeError("No context plugin is active")
        return self._plugins[self._active]

    # ------------------------------------------------------------------
    # Delegation to active plugin
    # ------------------------------------------------------------------

    async def build_context(
        self,
        query: str,
        max_tokens: int = 8000,
    ) -> list[dict[str, Any]]:
        """Assemble context and return it as OpenAI message list.

        The context is returned as a list with a single ``system``-role
        message containing the assembled context block.

        Args:
            query: Current user query or task.
            max_tokens: Token budget for the context block.

        Returns:
            List of OpenAI-format message dicts.
        """
        context_text = await self.active_plugin.assemble(query, max_tokens)
        if not context_text:
            return []

        return [
            {
                "role": "system",
                "content": f"<context>\n{context_text}\n</context>",
            }
        ]

    async def ingest(self, content: str, source: str) -> None:
        """Ingest content into the active plugin's store.

        Args:
            content: Text to ingest.
            source: Origin label.
        """
        await self.active_plugin.ingest(content, source)

    async def compact(self) -> None:
        """Compact the active plugin's context to its default budget.

        Uses each plugin's :meth:`~ContextPlugin.compact` method with a
        sensible default budget (4000 tokens).
        """
        plugin = self.active_plugin
        # Ask the plugin to compact whatever context it has assembled
        sample_context = await plugin.assemble("", max_tokens=100_000)
        if sample_context:
            compacted = await plugin.compact(sample_context, target_tokens=4000)
            # Re-ingest the compacted version as a summary
            await plugin.ingest(compacted, source="compact_summary")
            log.debug("Context compacted to %d tokens", _estimate_tokens(compacted))

    async def after_turn(self, turn: dict[str, Any]) -> None:
        """Propagate a completed turn to the active plugin.

        Args:
            turn: Dict with ``role``, ``content``, etc.
        """
        await self.active_plugin.after_turn(turn)

    async def bootstrap(self, config: dict[str, Any] | None = None) -> None:
        """Bootstrap the active plugin with *config*.

        Args:
            config: Arbitrary configuration dict.
        """
        await self.active_plugin.bootstrap(config or {})

    async def prepare_subagent_spawn(self, task: str) -> str:
        """Delegate sub-agent context preparation to the active plugin.

        Args:
            task: Sub-agent's task.

        Returns:
            Context string for injection into the sub-agent's system prompt.
        """
        return await self.active_plugin.prepare_subagent_spawn(task)
