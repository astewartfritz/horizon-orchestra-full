from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent.memory.base import MemoryEntry
from orchestra.embeddings.models import (
    CANONICAL_EMBEDDING_CLIENT,
    EmbeddingClient,
    _md5_hash_embed,
    cosine_similarity,
)


@dataclass
class StoredMemory:
    id: int
    content: str
    memory_type: str = "working"
    tier: str = "normal"
    role: str = "user"
    source: str = "conversation"
    session_id: str = ""
    importance: float = 0.5
    token_count: int = 0
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content[:200],
            "memory_type": self.memory_type,
            "tier": self.tier,
            "role": self.role,
            "source": self.source,
            "session_id": self.session_id,
            "importance": self.importance,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
        }


@dataclass
class MemoryEntity:
    id: int
    name: str
    entity_type: str = "concept"
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class EntityEdge:
    id: int
    source_id: int
    target_id: int
    relation: str = "related_to"
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class EmbeddingEngine:
    """Generates text embeddings — delegates to canonical EmbeddingClient.

    Falls back to a deterministic hash when no API key is available.
    """

    def __init__(self, provider: str = "hash", api_key: str | None = None, model: str = "text-embedding-3-small"):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self._dim = 128
        self._client: EmbeddingClient | None = None

    def _get_client(self) -> EmbeddingClient | None:
        if self._client is None:
            try:
                if self.provider == "openai" or self.provider == "hash":
                    self._client = CANONICAL_EMBEDDING_CLIENT()
                    # Check if any API key is set
                    available = self._client.list_models()
                    has_key = any(m["available"] for m in available)
                    if not has_key and self.provider == "hash":
                        self._client = None
                else:
                    self._client = CANONICAL_EMBEDDING_CLIENT()
            except Exception:
                self._client = None
        return self._client

    def embed(self, text: str) -> list[float]:
        client = self._get_client()
        if client is not None:
            try:
                return asyncio.run(client.embed(text, model=self.model))
            except Exception:
                pass
        return _md5_hash_embed(text, self._dim)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        if client is not None:
            try:
                return asyncio.run(client.batch_embed(texts, model=self.model))
            except Exception:
                pass
        return [_md5_hash_embed(t, self._dim) for t in texts]

    @staticmethod
    def cosine_sim(a: list[float], b: list[float]) -> float:
        return cosine_similarity(a, b)


class MemoryStore:
    def __init__(self, path: str | Path = ".agent-memory.db", embedding_provider: str = "hash", embedding_api_key: str | None = None):
        self.path = Path(path)
        self.embedder = EmbeddingEngine(provider=embedding_provider, api_key=embedding_api_key)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'working',
                tier TEXT DEFAULT 'normal',
                role TEXT DEFAULT 'user',
                source TEXT DEFAULT 'conversation',
                session_id TEXT DEFAULT '',
                importance REAL DEFAULT 0.5,
                token_count INTEGER DEFAULT 0,
                content_hash TEXT,
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                accessed_at REAL,
                access_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier);
            CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source);
            CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
            CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash);
            CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
            CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);

            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                entity_type TEXT DEFAULT 'concept',
                aliases TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

            CREATE TABLE IF NOT EXISTS entity_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT DEFAULT 'related_to',
                weight REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                FOREIGN KEY(source_id) REFERENCES entities(id),
                FOREIGN KEY(target_id) REFERENCES entities(id),
                UNIQUE(source_id, target_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON entity_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON entity_edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_relation ON entity_edges(relation);

            CREATE TABLE IF NOT EXISTS memory_entities (
                memory_id INTEGER NOT NULL,
                entity_id INTEGER NOT NULL,
                PRIMARY KEY(memory_id, entity_id),
                FOREIGN KEY(memory_id) REFERENCES memories(id),
                FOREIGN KEY(entity_id) REFERENCES entities(id)
            );

            CREATE TABLE IF NOT EXISTS consolidation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                source_ids TEXT,
                target_id INTEGER,
                summary TEXT,
                created_at REAL
            );
        """)
        self.conn.commit()

    def store(
        self,
        content: str,
        memory_type: str = "working",
        tier: str = "normal",
        role: str = "user",
        source: str = "conversation",
        session_id: str = "",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        skip_embedding: bool = False,
    ) -> int:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = self.conn.execute(
            "SELECT id FROM memories WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                (time.time(), existing["id"]),
            )
            self.conn.commit()
            return existing["id"]

        token_count = max(1, len(content) // 4)
        embedding = None if skip_embedding else self.embedder.embed(content)
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO memories (content, memory_type, tier, role, source, session_id, "
            "importance, token_count, content_hash, embedding, metadata, created_at, accessed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                content, memory_type, tier, role, source, session_id,
                importance, token_count, content_hash,
                json.dumps(embedding) if embedding else None,
                json.dumps(metadata or {}), now, now,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get(self, memory_id: int) -> StoredMemory | None:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return None
        self.conn.execute(
            "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            (time.time(), memory_id),
        )
        self.conn.commit()
        return self._row_to_memory(row)

    def delete(self, memory_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def search(
        self,
        query: str,
        top_k: int = 10,
        memory_type: str | None = None,
        tier: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        min_importance: float = 0.0,
    ) -> list[tuple[StoredMemory, float]]:
        query_emb = self.embedder.embed(query)
        rows = self.conn.execute("SELECT * FROM memories").fetchall()
        scored: list[tuple[StoredMemory, float]] = []
        for row in rows:
            m = self._row_to_memory(row)
            if memory_type and m.memory_type != memory_type:
                continue
            if tier and m.tier != tier:
                continue
            if source and m.source != source:
                continue
            if session_id and m.session_id != session_id:
                continue
            if m.importance < min_importance:
                continue
            emb = self._load_embedding(row)
            sim = self.embedder.cosine_sim(query_emb, emb) if emb else 0.0
            recency = 1.0 / (1.0 + (time.time() - m.created_at) / 86400)
            importance = m.importance
            freq = min(1.0, m.access_count / 10.0)
            score = sim * 0.5 + recency * 0.15 + importance * 0.25 + freq * 0.1
            if score > 0.01:
                scored.append((m, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[tuple[StoredMemory, float]]:
        terms = query.lower().split()
        rows = self.conn.execute("SELECT * FROM memories").fetchall()
        scored: list[tuple[StoredMemory, float]] = []
        for row in rows:
            m = self._row_to_memory(row)
            content_lower = m.content.lower()
            score = 0.0
            for term in terms:
                if term in content_lower:
                    score += content_lower.count(term) * 2.0
            if m.source in content_lower:
                score += 3.0
            if score > 0:
                scored.append((m, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def list_memories(
        self,
        memory_type: str | None = None,
        tier: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredMemory]:
        conditions = []
        params: list[Any] = []
        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)
        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def update_importance(self, memory_id: int, importance: float) -> None:
        self.conn.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id),
        )
        self.conn.commit()

    def update_tier(self, memory_id: int, tier: str) -> None:
        self.conn.execute(
            "UPDATE memories SET tier = ? WHERE id = ?",
            (tier, memory_id),
        )
        self.conn.commit()

    def count(self, memory_type: str | None = None) -> int:
        if memory_type:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_type = ?", (memory_type,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    def total_tokens(self) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(token_count), 0) FROM memories").fetchone()
        return row[0] if row else 0

    ## Entity operations

    def extract_and_store_entities(self, text: str, memory_id: int | None = None) -> list[int]:
        entity_ids = []
        patterns = [
            (r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b", "person"),
            (r"\b([A-Z]{2,})\b", "acronym"),
            (r"\b([A-Z][a-z]{2,})\b", "proper_noun"),
        ]
        stop_words = {
            "the", "and", "for", "this", "that", "with", "from", "was", "were", "been",
            "have", "has", "had", "not", "but", "are", "all", "can", "each", "which",
            "their", "them", "into", "about", "than", "then", "also", "its", "just",
            "more", "some", "such", "very", "when", "where", "while", "will", "would",
            "could", "should", "may", "might", "shall", "every", "after", "before",
            "between", "over", "under", "again", "further", "once", "here", "there",
            "both", "few", "most", "other", "own", "same", "too", "above", "below",
            "up", "down", "out", "off", "on", "off", "over", "been",
        }
        found = set()
        for pattern, etype in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                if name.lower() in stop_words:
                    continue
                if name not in found:
                    found.add(name)
                    eid = self._ensure_entity(name, etype)
                    entity_ids.append(eid)
                    if memory_id:
                        self._link_memory_to_entity(memory_id, eid)
        return entity_ids

    def _ensure_entity(self, name: str, entity_type: str = "concept") -> int:
        existing = self.conn.execute(
            "SELECT id FROM entities WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing["id"]
        cur = self.conn.execute(
            "INSERT INTO entities (name, entity_type, created_at) VALUES (?, ?, ?)",
            (name, entity_type, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def _link_memory_to_entity(self, memory_id: int, entity_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id) VALUES (?, ?)",
            (memory_id, entity_id),
        )
        self.conn.commit()

    def get_entities(self, entity_type: str | None = None) -> list[MemoryEntity]:
        if entity_type:
            rows = self.conn.execute(
                "SELECT * FROM entities WHERE entity_type = ? ORDER BY name", (entity_type,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM entities ORDER BY name").fetchall()
        return [self._row_to_entity(r) for r in rows]

    def get_memories_by_entity(self, entity_name: str) -> list[StoredMemory]:
        row = self.conn.execute(
            "SELECT id FROM entities WHERE name = ?", (entity_name,)
        ).fetchone()
        if not row:
            return []
        rows = self.conn.execute(
            "SELECT m.* FROM memories m JOIN memory_entities me ON m.id = me.memory_id "
            "WHERE me.entity_id = ? ORDER BY m.importance DESC",
            (row["id"],),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    ## Edge operations

    def create_edge(self, source_id: int, target_id: int, relation: str = "related_to", weight: float = 1.0) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO entity_edges (source_id, target_id, relation, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, relation, weight, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_related_entities(self, entity_id: int, max_depth: int = 2) -> list[tuple[MemoryEntity, str, float]]:
        related = []
        visited = {entity_id}
        queue = [(entity_id, 0)]
        while queue:
            eid, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            rows = self.conn.execute(
                "SELECT e.*, edge.relation, edge.weight FROM entity_edges edge "
                "JOIN entities e ON e.id = edge.target_id "
                "WHERE edge.source_id = ? AND e.id NOT IN (?)",
                (eid, ",".join(str(v) for v in visited)) if visited else (eid, "0"),
            ).fetchall()
            for r in rows:
                entity = self._row_to_entity(r)
                if entity.id not in visited:
                    visited.add(entity.id)
                    related.append((entity, r["relation"], r["weight"]))
                    queue.append((entity.id, depth + 1))
        return related

    ## Consolidation log

    def log_consolidation(self, operation: str, source_ids: list[int], target_id: int | None = None, summary: str = "") -> None:
        self.conn.execute(
            "INSERT INTO consolidation_log (operation, source_ids, target_id, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (operation, json.dumps(source_ids), target_id, summary, time.time()),
        )
        self.conn.commit()

    def get_consolidation_history(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    ## Stats

    def stats(self) -> dict[str, Any]:
        total = self.count()
        by_type = {}
        for t in ("working", "episodic", "semantic", "long_term"):
            c = self.count(t)
            if c > 0:
                by_type[t] = c
        by_tier = {}
        for t in ("critical", "important", "normal", "low", "archived"):
            c = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE tier = ?", (t,)
            ).fetchone()[0]
            if c > 0:
                by_tier[t] = c
        entity_count = self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        total_tok = self.total_tokens()
        return {
            "total_memories": total,
            "total_tokens": total_tok,
            "by_type": by_type,
            "by_tier": by_tier,
            "entities": entity_count,
            "consolidations": self.conn.execute("SELECT COUNT(*) FROM consolidation_log").fetchone()[0],
        }

    ## Helpers

    def _row_to_memory(self, row: sqlite3.Row) -> StoredMemory:
        emb = self._load_embedding(row)
        return StoredMemory(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            tier=row["tier"],
            role=row["role"],
            source=row["source"],
            session_id=row["session_id"],
            importance=row["importance"],
            token_count=row["token_count"],
            embedding=emb,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"],
        )

    def _load_embedding(self, row: sqlite3.Row) -> list[float] | None:
        raw = row["embedding"]
        if raw:
            try:
                emb = json.loads(raw)
                if isinstance(emb, list) and len(emb) > 0:
                    return emb
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def _row_to_entity(self, row: sqlite3.Row) -> MemoryEntity:
        return MemoryEntity(
            id=row["id"],
            name=row["name"],
            entity_type=row["entity_type"],
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
        )

    def close(self) -> None:
        self.conn.close()

    def clear(self) -> None:
        self.conn.executescript("""
            DELETE FROM memories;
            DELETE FROM entities;
            DELETE FROM entity_edges;
            DELETE FROM memory_entities;
            DELETE FROM consolidation_log;
        """)
        self.conn.commit()
