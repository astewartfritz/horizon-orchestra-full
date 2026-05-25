"""Horizon Orchestra — Embedding result cache.

LRU cache with optional SQLite persistence to avoid re-embedding the
same text.  Keyed by (text_hash, model_name) to handle identical texts
across different models.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

__all__ = [
    "EmbeddingCache",
    "CachedEntry",
]

log = logging.getLogger("orchestra.embeddings.cache")


def _text_key(text: str, model: str) -> str:
    """Produce a stable cache key from text + model name."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model}::{h}"


class CachedEntry:
    """A single cached embedding result."""

    __slots__ = ("vector", "model", "text_length", "cached_at", "hit_count")

    def __init__(
        self,
        vector: list[float],
        model: str,
        text_length: int = 0,
    ) -> None:
        self.vector = vector
        self.model = model
        self.text_length = text_length
        self.cached_at = time.time()
        self.hit_count = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector": self.vector,
            "model": self.model,
            "text_length": self.text_length,
            "cached_at": self.cached_at,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedEntry:
        entry = cls(
            vector=data["vector"],
            model=data["model"],
            text_length=data.get("text_length", 0),
        )
        entry.cached_at = data.get("cached_at", 0)
        entry.hit_count = data.get("hit_count", 1)
        return entry


class EmbeddingCache:
    """LRU cache for embedding results with optional SQLite persistence.

    Usage::

        cache = EmbeddingCache(max_size=10000, db_path=".embedding-cache.db")
        vec = cache.get("some text", model="text-embedding-3-small")
        if vec is None:
            vec = await client.embed("some text")
            cache.put("some text", vec, model="text-embedding-3-small")
        cache.close()
    """

    def __init__(
        self,
        max_size: int = 10000,
        db_path: str | None = None,
    ) -> None:
        self._max_size = max_size
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, CachedEntry] = OrderedDict()

        self._db_path: str | None = db_path
        self._db_conn: sqlite3.Connection | None = None
        if db_path:
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self._db_conn = sqlite3.connect(db_path, check_same_thread=False)
                self._db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        cache_key TEXT PRIMARY KEY,
                        vector TEXT NOT NULL,
                        model TEXT NOT NULL,
                        text_length INTEGER DEFAULT 0,
                        cached_at REAL DEFAULT 0,
                        hit_count INTEGER DEFAULT 1
                    )
                """)
                self._db_conn.commit()
                # Load existing entries into memory
                self._load_from_db()
                log.info(
                    "EmbeddingCache loaded %d entries from %s",
                    len(self._cache), db_path,
                )
            except Exception as exc:
                log.warning("Failed to open embedding cache DB: %s", exc)
                self._db_conn = None

    def _load_from_db(self) -> None:
        if self._db_conn is None:
            return
        try:
            cursor = self._db_conn.execute(
                "SELECT cache_key, vector, model, text_length, cached_at, hit_count "
                "FROM embedding_cache ORDER BY cached_at DESC LIMIT ?",
                (self._max_size,),
            )
            for row in cursor:
                key, vec_json, model, text_len, cached_at, hits = row
                entry = CachedEntry(
                    vector=json.loads(vec_json),
                    model=model,
                    text_length=text_len,
                )
                entry.cached_at = cached_at
                entry.hit_count = hits
                self._cache[key] = entry
        except Exception as exc:
            log.warning("Error loading cache from DB: %s", exc)

    def get(self, text: str, model: str = "text-embedding-3-small") -> list[float] | None:
        """Look up a cached embedding.  Returns None on miss.

        On hit, promotes the entry to MRU position and increments hit_count.
        """
        key = _text_key(text, model)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            return entry.vector

    def put(
        self,
        text: str,
        vector: list[float],
        model: str = "text-embedding-3-small",
    ) -> None:
        """Store an embedding result.  Evicts LRU entry if at capacity."""
        key = _text_key(text, model)
        entry = CachedEntry(vector=vector, model=model, text_length=len(text))

        with self._lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)

            # Evict if over max size
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

        # Persist to DB
        self._persist(key, entry)

    def _persist(self, key: str, entry: CachedEntry) -> None:
        if self._db_conn is None:
            return
        try:
            self._db_conn.execute(
                """
                INSERT OR REPLACE INTO embedding_cache
                (cache_key, vector, model, text_length, cached_at, hit_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    json.dumps(entry.vector),
                    entry.model,
                    entry.text_length,
                    entry.cached_at,
                    entry.hit_count,
                ),
            )
            self._db_conn.commit()
        except Exception as exc:
            log.debug("Failed to persist cache entry: %s", exc)

    def get_batch(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> tuple[dict[int, list[float]], list[int]]:
        """Batch lookup.

        Returns
        -------
        (hits, miss_indices)
            hits: dict mapping original index -> vector
            miss_indices: list of original indices that were not found
        """
        hits: dict[int, list[float]] = {}
        misses: list[int] = []
        for i, text in enumerate(texts):
            vec = self.get(text, model=model)
            if vec is not None:
                hits[i] = vec
            else:
                misses.append(i)
        return hits, misses

    def put_batch(
        self,
        texts: list[str],
        vectors: list[list[float]],
        model: str = "text-embedding-3-small",
    ) -> None:
        """Store multiple embeddings at once."""
        for text, vec in zip(texts, vectors):
            self.put(text, vec, model=model)

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "db_path": self._db_path,
                "keys_sample": list(self._cache.keys())[:5],
            }

    def clear(self) -> None:
        """Clear the in-memory cache."""
        with self._lock:
            self._cache.clear()

    def clear_persistent(self) -> None:
        """Clear the in-memory cache and the backing DB."""
        self.clear()
        if self._db_conn is not None:
            try:
                self._db_conn.execute("DELETE FROM embedding_cache;")
                self._db_conn.commit()
            except Exception as exc:
                log.warning("Failed to clear persistent cache: %s", exc)

    def close(self) -> None:
        """Close the database connection."""
        if self._db_conn is not None:
            self._db_conn.close()
            self._db_conn = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __repr__(self) -> str:
        return f"EmbeddingCache(size={len(self._cache)}, max={self._max_size})"
