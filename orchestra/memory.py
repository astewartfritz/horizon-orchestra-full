"""Horizon Orchestra — Persistent Memory System.

Mirrors Perplexity Computer's cross-session memory:

* **Semantic search** — embed user facts and retrieve by cosine similarity.
* **Automatic fact extraction** — the LLM distils durable facts from
  conversations and stores them without being asked.
* **Session context** — rolling window of recent turns available to every
  agent in the loop.
* **Categorised storage** — facts are tagged (preference, project, person,
  tool, workflow, identity) for filtered retrieval.
* **Multiple backends** — SQLite+numpy for zero-dependency local use,
  or PostgreSQL+pgvector for production.

The memory system is exposed as tools that plug directly into
:class:`~orchestra.agent_loop.ToolRegistry` so every agent can
``memory_search`` and ``memory_store`` mid-loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from openai import AsyncOpenAI

__all__ = [
    "MemoryEntry",
    "MemoryStore",
    "MemoryManager",
    "register_memory_tools",
]

log = logging.getLogger("orchestra.memory")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

CATEGORIES = (
    "identity",     # name, role, company, demographics
    "preference",   # communication style, formatting, workflow preferences
    "project",      # active projects, repos, goals
    "person",       # colleagues, contacts, relationships
    "tool",         # tools, platforms, APIs the user works with
    "workflow",     # recurring processes, preferred patterns
    "fact",         # general durable facts
)


@dataclass
class MemoryEntry:
    """A single memory record."""
    id: str
    user_id: str
    content: str
    category: str = "fact"
    embedding: list[float] = field(default_factory=list, repr=False)
    created_at: float = 0.0
    updated_at: float = 0.0
    source: str = ""            # "auto" | "explicit" | "session"
    session_id: str = ""
    relevance_score: float = 0.0  # populated during search


@dataclass
class SessionContext:
    """Rolling window of recent conversation turns."""
    session_id: str
    user_id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    max_turns: int = 50
    created_at: float = field(default_factory=time.time)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content, "ts": time.time()})
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def to_context_string(self, last_n: int = 10) -> str:
        """Format recent turns as a context block for system prompts."""
        recent = self.turns[-last_n:]
        parts = []
        for t in recent:
            parts.append(f"[{t['role']}] {t['content']}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

class Embedder:
    """Generate text embeddings via OpenAI-compatible API.

    Tries Perplexity ``sonar-embedding`` first, then falls back to
    OpenAI ``text-embedding-3-small``, then to a local hash-based
    stub (no API key needed, but lower quality).
    """

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._model: str = ""
        self._dim: int = 0

    async def _init_client(self) -> None:
        pplx = os.environ.get("PERPLEXITY_API_KEY")
        if pplx:
            self._client = AsyncOpenAI(base_url="https://api.perplexity.ai", api_key=pplx)
            self._model = "sonar-embedding"
            self._dim = 1536
            return

        oai = os.environ.get("OPENAI_API_KEY")
        if oai:
            self._client = AsyncOpenAI(api_key=oai)
            self._model = "text-embedding-3-small"
            self._dim = 1536
            return

        # Stub: deterministic hash-based pseudo-embedding (for offline dev)
        self._client = None
        self._model = "local-hash"
        self._dim = 256
        log.warning("No embedding API key found; using hash-based stub embeddings")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._model:
            await self._init_client()

        if self._client is None:
            # Hash stub
            return [self._hash_embed(t) for t in texts]

        try:
            resp = await self._client.embeddings.create(model=self._model, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as exc:
            log.warning("Embedding API call failed (%s); falling back to hash stub", exc)
            return [self._hash_embed(t) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0]

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding from SHA-256 (offline fallback)."""
        h = hashlib.sha256(text.encode()).digest()
        # Expand to _dim floats in [-1, 1]
        import struct
        floats: list[float] = []
        while len(floats) < self._dim:
            h = hashlib.sha256(h).digest()
            for i in range(0, len(h), 4):
                if len(floats) >= self._dim:
                    break
                val = struct.unpack("f", h[i:i+4])[0]
                # Normalise to [-1, 1]
                clamped = max(-1.0, min(1.0, val / 1e38 if abs(val) > 1 else val))
                floats.append(clamped)
        return floats[:self._dim]

    @property
    def dim(self) -> int:
        return self._dim or 256


# ---------------------------------------------------------------------------
# SQLite-backed memory store  (zero external deps beyond stdlib + openai)
# ---------------------------------------------------------------------------

class MemoryStore:
    """SQLite-backed persistent memory with cosine-similarity search.

    For production, swap to PostgreSQL + pgvector by subclassing and
    overriding ``search`` / ``store`` / ``_cosine``.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or Path.home() / ".horizon" / "memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = Embedder()
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                content     TEXT NOT NULL,
                category    TEXT DEFAULT 'fact',
                embedding   TEXT,          -- JSON-serialised float array
                created_at  REAL,
                updated_at  REAL,
                source      TEXT DEFAULT 'explicit',
                session_id  TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id);
            CREATE INDEX IF NOT EXISTS idx_mem_cat  ON memories(user_id, category);

            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                turns       TEXT,          -- JSON array
                created_at  REAL,
                updated_at  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(user_id);
        """)
        conn.commit()

    # -- store --------------------------------------------------------------

    async def store(
        self,
        user_id: str,
        content: str,
        category: str = "fact",
        source: str = "explicit",
        session_id: str = "",
        dedup: bool = True,
    ) -> MemoryEntry:
        """Store a new memory, embedding it for later search."""
        # Dedup: if very similar content exists, update instead
        if dedup:
            existing = await self.search(user_id, content, limit=1)
            if existing and existing[0].relevance_score > 0.92:
                return await self.update(existing[0].id, content)

        now = time.time()
        entry_id = hashlib.sha256(f"{user_id}:{content}:{now}".encode()).hexdigest()[:16]
        embedding = await self.embedder.embed_one(content)

        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, user_id, content, category, embedding, created_at, updated_at, source, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, user_id, content, category, json.dumps(embedding),
             now, now, source, session_id),
        )
        conn.commit()

        log.debug("Stored memory %s [%s]: %s", entry_id, category, content[:60])
        return MemoryEntry(
            id=entry_id, user_id=user_id, content=content,
            category=category, embedding=embedding,
            created_at=now, updated_at=now, source=source,
            session_id=session_id,
        )

    async def update(self, entry_id: str, new_content: str) -> MemoryEntry:
        """Update an existing memory's content and re-embed."""
        now = time.time()
        embedding = await self.embedder.embed_one(new_content)
        conn = self._get_conn()
        conn.execute(
            "UPDATE memories SET content=?, embedding=?, updated_at=? WHERE id=?",
            (new_content, json.dumps(embedding), now, entry_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM memories WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise ValueError(f"Memory {entry_id} not found")
        return self._row_to_entry(row)

    # -- search -------------------------------------------------------------

    async def search(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        category: str | None = None,
        min_score: float = 0.0,
    ) -> list[MemoryEntry]:
        """Semantic search across stored memories."""
        query_embedding = await self.embedder.embed_one(query)

        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND category=?",
                (user_id, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=?",
                (user_id,),
            ).fetchall()

        scored: list[tuple[float, MemoryEntry]] = []
        for row in rows:
            stored_emb = json.loads(row["embedding"]) if row["embedding"] else []
            if not stored_emb:
                continue
            score = self._cosine(query_embedding, stored_emb)
            if score >= min_score:
                entry = self._row_to_entry(row, relevance=score)
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    # -- delete / list ------------------------------------------------------

    async def delete(self, entry_id: str) -> bool:
        conn = self._get_conn()
        conn.execute("DELETE FROM memories WHERE id=?", (entry_id,))
        conn.commit()
        return True

    async def list_all(
        self,
        user_id: str,
        category: str | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND category=? ORDER BY updated_at DESC LIMIT ?",
                (user_id, category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # -- session management -------------------------------------------------

    async def save_session(self, session: SessionContext) -> None:
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, user_id, turns, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session.session_id, session.user_id,
             json.dumps(session.turns), session.created_at, now),
        )
        conn.commit()

    async def load_session(self, session_id: str) -> SessionContext | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,),
        ).fetchone()
        if not row:
            return None
        return SessionContext(
            session_id=row["session_id"],
            user_id=row["user_id"],
            turns=json.loads(row["turns"]) if row["turns"] else [],
            created_at=row["created_at"],
        )

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT session_id, created_at, updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _row_to_entry(self, row: sqlite3.Row, relevance: float = 0.0) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            user_id=row["user_id"],
            content=row["content"],
            category=row["category"],
            embedding=[],  # don't load full embedding into returned objects
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source=row["source"],
            session_id=row["session_id"],
            relevance_score=relevance,
        )


# ---------------------------------------------------------------------------
# Automatic fact extraction
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are a memory extraction agent.  Analyse the conversation below and
extract **durable facts** about the user that should be remembered across
sessions.

Categories: identity, preference, project, person, tool, workflow, fact.

Return a JSON object with a "memories" array.  Each element:
{{"content": "Remember that I ...", "category": "..."}}

Rules:
- Use first-person ("I", "my") from the user's perspective.
- Only extract persistent information, NOT ephemeral instructions.
- Deduplicate: if a fact is obvious from prior memories, skip it.
- If nothing new is worth remembering, return {{"memories": []}}.

Prior memories (already stored):
{prior_memories}

Recent conversation:
{conversation}
"""


class MemoryManager:
    """High-level memory operations: auto-extraction + tool integration."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        user_id: str = "default",
    ) -> None:
        self.store = store or MemoryStore()
        self.user_id = user_id

    async def auto_extract(
        self,
        conversation: str,
        model: str = "kimi-k2.5",
        router: Any = None,
    ) -> list[MemoryEntry]:
        """Analyse a conversation and auto-store durable facts.

        Called at the end of each session (or periodically).
        """
        # Get existing memories for dedup context
        existing = await self.store.list_all(self.user_id, limit=50)
        prior_block = "\n".join(f"- [{m.category}] {m.content}" for m in existing) or "(none yet)"

        prompt = EXTRACTION_PROMPT.format(
            prior_memories=prior_block,
            conversation=conversation[-8000:],  # last ~8k chars
        )

        # Use provided router or create a minimal client
        if router:
            client, model_id = router.get_client(model)
        else:
            from openai import AsyncOpenAI
            api_key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
            client = AsyncOpenAI(
                base_url="https://api.moonshot.ai/v1" if os.environ.get("MOONSHOT_API_KEY") else "https://api.openai.com/v1",
                api_key=api_key or "not-needed",
            )
            model_id = model

        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "Extract memories as JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2048,
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
        except Exception as exc:
            log.warning("Memory extraction failed: %s", exc)
            return []

        entries: list[MemoryEntry] = []
        for item in data.get("memories", []):
            content = item.get("content", "")
            category = item.get("category", "fact")
            if content and category in CATEGORIES:
                entry = await self.store.store(
                    user_id=self.user_id,
                    content=content,
                    category=category,
                    source="auto",
                )
                entries.append(entry)
                log.info("Auto-extracted: [%s] %s", category, content[:60])

        return entries

    async def get_context_block(self, query: str = "", limit: int = 15) -> str:
        """Build a memory context block for injection into system prompts.

        If *query* is provided, returns the most relevant memories.
        Otherwise returns the most recent memories.
        """
        if query:
            entries = await self.store.search(self.user_id, query, limit=limit, min_score=0.3)
        else:
            entries = await self.store.list_all(self.user_id, limit=limit)

        if not entries:
            return ""

        lines = ["<user_memory>"]
        for e in entries:
            score_str = f" (relevance: {e.relevance_score:.2f})" if e.relevance_score else ""
            lines.append(f"- [{e.category}]{score_str} {e.content}")
        lines.append("</user_memory>")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registration — plug memory into the agent loop
# ---------------------------------------------------------------------------

def register_memory_tools(
    tool_registry: Any,  # ToolRegistry from agent_loop
    manager: MemoryManager,
) -> None:
    """Register ``memory_search`` and ``memory_store`` as agent tools.

    After calling this, any agent in the loop can search and store
    memories mid-execution.
    """

    async def _memory_search(query: str, category: str = "", limit: int = 10) -> str:
        results = await manager.store.search(
            user_id=manager.user_id,
            query=query,
            limit=limit,
            category=category or None,
        )
        return json.dumps([
            {
                "content": r.content,
                "category": r.category,
                "relevance": round(r.relevance_score, 3),
                "updated_at": r.updated_at,
            }
            for r in results
        ])

    async def _memory_store(content: str, category: str = "fact") -> str:
        entry = await manager.store.store(
            user_id=manager.user_id,
            content=content,
            category=category,
            source="explicit",
        )
        return json.dumps({"id": entry.id, "stored": True, "content": content})

    tool_registry.register(
        name="memory_search",
        description=(
            "Search the user's persistent memory for facts, preferences, "
            "projects, and past context. Returns the most relevant matches."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                    "description": "Optional: filter by category",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)",
                },
            },
            "required": ["query"],
        },
        handler=_memory_search,
    )

    tool_registry.register(
        name="memory_store",
        description=(
            "Store a durable fact about the user. Use first-person from "
            "the user's perspective (e.g. 'I prefer dark mode'). Only store "
            "persistent information, not ephemeral instructions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact to remember, in first person",
                },
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                    "description": "Category for the memory",
                },
            },
            "required": ["content"],
        },
        handler=_memory_store,
    )
