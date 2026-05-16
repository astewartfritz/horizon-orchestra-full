from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    key: str
    content: str
    source: str = "conversation"
    tags: list[str] = field(default_factory=list)
    timestamp: float = 0.0
    embedding: list[float] | None = None


@dataclass
class SearchHit:
    entry: MemoryEntry
    score: float


def _embed(text: str, dim: int = 64) -> list[float]:
    vec = [0.0] * dim
    tokens = re.findall(r'\w+', text.lower())
    for i, token in enumerate(tokens):
        h = hash(token + str(i)) % dim
        vec[abs(h)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class KnowledgeBase:
    def __init__(self, db_path: str | Path = ".code-agent-knowledge.db"):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                key TEXT PRIMARY KEY,
                content TEXT,
                source TEXT,
                tags TEXT,
                timestamp REAL,
                embedding BLOB
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_tags
            ON knowledge(tags)
        """)
        self.conn.commit()

    def store(self, key: str, content: str, source: str = "conversation", tags: list[str] | None = None) -> None:
        emb = _embed(content)
        self.conn.execute(
            "INSERT OR REPLACE INTO knowledge (key, content, source, tags, timestamp, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, content, source, json.dumps(tags or []), time.time(), json.dumps(emb)),
        )
        self.conn.commit()

    def store_conversation(self, role: str, content: str, tags: list[str] | None = None) -> str:
        key = f"{role}_{int(time.time() * 1000)}"
        self.store(key, content, source=role, tags=tags)
        return key

    def search(self, query: str, top_k: int = 5, tag_filter: str | None = None) -> list[SearchHit]:
        q_emb = _embed(query)
        sql = "SELECT key, content, source, tags, timestamp, embedding FROM knowledge"
        params: list[Any] = []
        if tag_filter:
            sql += " WHERE tags LIKE ?"
            params.append(f"%{tag_filter}%")

        rows = self.conn.execute(sql, params).fetchall()
        scored: list[tuple[float, MemoryEntry]] = []

        for row in rows:
            key, content, source, tags_str, ts, emb_blob = row
            if not emb_blob:
                continue
            stored = json.loads(emb_blob)
            score = sum(a * b for a, b in zip(q_emb, stored))
            na = math.sqrt(sum(x * x for x in q_emb))
            nb = math.sqrt(sum(x * x for x in stored))
            if na * nb > 0:
                score /= na * nb
            else:
                score = 0.0

            entry = MemoryEntry(
                key=key, content=content, source=source,
                tags=json.loads(tags_str) if tags_str else [],
                timestamp=ts,
            )
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [SearchHit(entry=s[1], score=s[0]) for s in scored[:top_k]]

    def recall(self, key: str) -> MemoryEntry | None:
        row = self.conn.execute(
            "SELECT key, content, source, tags, timestamp FROM knowledge WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return MemoryEntry(
            key=row[0], content=row[1], source=row[2],
            tags=json.loads(row[3]) if row[3] else [],
            timestamp=row[4],
        )

    def forget(self, key: str) -> None:
        self.conn.execute("DELETE FROM knowledge WHERE key = ?", (key,))
        self.conn.commit()

    def list_sources(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT source FROM knowledge ORDER BY source").fetchall()
        return [r[0] for r in rows]

    def stats(self) -> dict[str, Any]:
        count = self.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        sources = self.list_sources()
        return {"entries": count, "sources": sources}

    def close(self) -> None:
        self.conn.close()
