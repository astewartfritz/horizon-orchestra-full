"""Horizon Orchestra — Supabase vector store adapter.

Uses Supabase's PostgreSQL (with pgvector extension) for vector storage.
Connects via supabase-py for auth + asyncpg for efficient pgvector queries.

Requires:
  - supabase (``pip install supabase``)
  - asyncpg (``pip install asyncpg``)
  - ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY`` env vars.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from supabase import create_client as _supabase_create_client

    _HAS_SUPABASE = True
except ImportError:  # pragma: no cover
    _supabase_create_client = None  # type: ignore[assignment]
    _HAS_SUPABASE = False

try:
    import asyncpg  # type: ignore[import-untyped]

    _HAS_ASYNCPG = True
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]
    _HAS_ASYNCPG = False

__all__ = [
    "SupabaseVectorStore",
    "SupabaseDistanceMetric",
]

log = logging.getLogger("orchestra.embeddings.supabase")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SupabaseDistanceMetric(str, Enum):
    """Distance metric mapped to pgvector operators."""

    L2 = "l2"
    COSINE = "cosine"
    INNER_PRODUCT = "ip"


_OPERATOR_MAP: dict[SupabaseDistanceMetric, str] = {
    SupabaseDistanceMetric.L2: "<->",
    SupabaseDistanceMetric.COSINE: "<=>",
    SupabaseDistanceMetric.INNER_PRODUCT: "<#>",
}


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """Single search hit from Supabase."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


# ---------------------------------------------------------------------------
# SupabaseVectorStore
# ---------------------------------------------------------------------------


class SupabaseVectorStore:
    """Async vector store backed by Supabase PostgreSQL + pgvector.

    Usage::

        store = SupabaseVectorStore()
        await store.connect()  # reads SUPABASE_URL + SUPABASE_SERVICE_KEY
        await store.create_collection("docs", dimensions=1536)
        await store.insert("docs", "id1", [0.1, ...], {"title": "hello"})
        results = await store.search("docs", query_vec, top_k=5)
        await store.close()
    """

    def __init__(
        self,
        *,
        supabase_url: str | None = None,
        supabase_key: str | None = None,
        default_metric: SupabaseDistanceMetric | str = SupabaseDistanceMetric.COSINE,
        pool_min_size: int = 1,
        pool_max_size: int = 5,
    ) -> None:
        if not _HAS_SUPABASE:
            log.warning(
                "supabase SDK is not installed — SupabaseVectorStore will raise "
                "on connect(). Install with: pip install supabase"
            )
        if not _HAS_ASYNCPG:
            log.warning(
                "asyncpg is not installed — SupabaseVectorStore will raise "
                "on connect(). Install with: pip install asyncpg"
            )

        self._supabase_url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self._supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        if isinstance(default_metric, str):
            default_metric = SupabaseDistanceMetric(default_metric)

        self._supabase_client: Any = None
        self._pg_pool: Any = None  # asyncpg connection pool (for raw SQL)
        self._default_metric = default_metric
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._collections: dict[str, int] = {}  # name -> dimensions

    # -- connection ---------------------------------------------------------

    async def connect(self, dsn: str = "") -> None:
        """Connect to Supabase.

        Parameters
        ----------
        dsn:
            Optional full PostgreSQL DSN. If not provided, constructs one
            from ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY`` env vars.
        """
        if not _HAS_SUPABASE:
            raise ImportError(
                "supabase SDK is required. Install with: pip install supabase"
            )
        if not _HAS_ASYNCPG:
            raise ImportError(
                "asyncpg is required. Install with: pip install asyncpg"
            )

        supabase_url = self._supabase_url
        supabase_key = self._supabase_key

        if not supabase_url:
            supabase_url = os.environ.get("SUPABASE_URL", "")
        if not supabase_key:
            supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in the "
                "environment or passed to the constructor."
            )

        # Create supabase-py client (for auth, table operations, etc.)
        self._supabase_client = _supabase_create_client(supabase_url, supabase_key)

        # Build PostgreSQL DSN from Supabase URL
        if not dsn:
            dsn = self._build_pg_dsn(supabase_url, supabase_key)

        # Create asyncpg pool for direct pgvector queries
        self._pg_pool = await asyncpg.create_pool(
            dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
        )

        # Ensure pgvector extension exists
        async with self._pg_pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        log.info("Connected to Supabase and ensured pgvector extension")

    @staticmethod
    def _build_pg_dsn(supabase_url: str, service_key: str) -> str:
        """Construct a PostgreSQL DSN from a Supabase project URL.

        Transforms ``https://project.supabase.co`` into
        ``postgresql://postgres:<password>@db.project.supabase.co:5432/postgres``.

        The service_role key acts as the password for the ``postgres`` user
        when connecting to Supabase's PostgreSQL.
        """
        import re

        # Extract project ref from URL
        match = re.match(r"https?://(.+)\.supabase\.co", supabase_url)
        if not match:
            # Try direct DSN
            return supabase_url

        project_ref = match.group(1)
        # Supabase connection string format
        return (
            f"postgresql://postgres:{service_key}@"
            f"db.{project_ref}.supabase.co:5432/postgres"
        )

    async def close(self) -> None:
        """Close the connection pool and supabase client."""
        if self._pg_pool is not None:
            await self._pg_pool.close()
            self._pg_pool = None
        self._supabase_client = None
        log.info("Closed Supabase connections")

    def _ensure_connected(self) -> None:
        if self._pg_pool is None:
            raise RuntimeError("Not connected — call connect() first")

    # -- collection management ----------------------------------------------

    async def _discover_collections(self) -> None:
        """Discover existing vector tables in Supabase Postgres."""
        self._ensure_connected()
        async with self._pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name LIKE 'vec_%'
                """
            )
        for row in rows:
            tname = row["table_name"]
            cname = tname[4:]
            try:
                async with self._pg_pool.acquire() as conn:
                    col_info = await conn.fetchrow(
                        """
                        SELECT character_maximum_length
                        FROM information_schema.columns
                        WHERE table_name = $1 AND column_name = 'embedding'
                        """,
                        tname,
                    )
                dims = col_info["character_maximum_length"] if col_info else 0
            except Exception:
                dims = 0
            self._collections[cname] = dims or 0

    async def create_collection(
        self,
        name: str,
        dimensions: int,
        *,
        metric: SupabaseDistanceMetric | str | None = None,
        if_not_exists: bool = True,
    ) -> None:
        """Create a new vector collection (table) in Supabase.

        Parameters
        ----------
        name:
            Collection name (alphanumeric + underscores).
        dimensions:
            Number of dimensions for the embedding vector.
        metric:
            Distance metric (defaults to store's default_metric).
        if_not_exists:
            Skip creation if the table already exists.
        """
        self._ensure_connected()

        if isinstance(metric, str):
            metric = SupabaseDistanceMetric(metric)
        if metric is None:
            metric = self._default_metric

        table_name = f"vec_{name}"
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        async with self._pg_pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE {exists_clause} {table_name} (
                    id TEXT PRIMARY KEY,
                    embedding vector({dimensions}),
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # GIN index for metadata queries
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{name}_metadata
                ON {table_name}
                USING GIN (metadata);
            """)

        self._collections[name] = dimensions
        log.info(
            "Created Supabase collection %r (%d dims, metric=%s)",
            name, dimensions, metric.value,
        )

    async def drop_collection(self, name: str) -> None:
        """Drop a vector collection and its associated table."""
        self._ensure_connected()
        table_name = f"vec_{name}"
        async with self._pg_pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        self._collections.pop(name, None)
        log.info("Dropped Supabase collection %r", name)

    async def list_collections(self) -> list[str]:
        """Return a list of all known collection names."""
        self._ensure_connected()
        await self._discover_collections()
        return list(self._collections.keys())

    # -- insert -------------------------------------------------------------

    @staticmethod
    def _vec_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{v}" for v in vector) + "]"

    async def insert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert a single vector into a collection."""
        self._ensure_connected()
        table_name = f"vec_{collection}"
        meta_json = json.dumps(metadata or {})
        vec_str = self._vec_literal(vector)

        async with self._pg_pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {table_name} (id, embedding, metadata)
                VALUES ($1, $2::vector, $3::jsonb)
                ON CONFLICT (id) DO UPDATE
                    SET embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata;
                """,
                id, vec_str, meta_json,
            )

    async def batch_insert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert multiple vectors in a single transaction."""
        self._ensure_connected()
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if len(ids) != len(vectors) or len(ids) != len(metadatas):
            raise ValueError("ids, vectors, and metadatas must have the same length")

        table_name = f"vec_{collection}"
        records = [
            (id_, self._vec_literal(vec), json.dumps(meta))
            for id_, vec, meta in zip(ids, vectors, metadatas)
        ]

        async with self._pg_pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    f"""
                    INSERT INTO {table_name} (id, embedding, metadata)
                    VALUES ($1, $2::vector, $3::jsonb)
                    ON CONFLICT (id) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata;
                    """,
                    records,
                )
        log.debug("Batch inserted %d vectors into %s", len(ids), collection)

    # -- search -------------------------------------------------------------

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        *,
        metric: SupabaseDistanceMetric | str | None = None,
    ) -> list[SearchResult]:
        """Search for nearest vectors in a collection.

        Parameters
        ----------
        collection:
            Collection name.
        query_vector:
            The query embedding.
        top_k:
            Maximum number of results.
        filters:
            Optional metadata filters (exact equality on each key).
        metric:
            Distance metric override.

        Returns
        -------
        list[SearchResult]
            Results ordered by ascending distance (closest first).
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"

        if isinstance(metric, str):
            metric = SupabaseDistanceMetric(metric)
        if metric is None:
            metric = self._default_metric

        op = _OPERATOR_MAP[metric]
        vec_str = self._vec_literal(query_vector)

        where_parts: list[str] = []
        params: list[Any] = []
        param_idx = 1

        if filters:
            for key, value in filters.items():
                where_parts.append(f"metadata->>'{key}' = ${param_idx}")
                params.append(str(value))
                param_idx += 1

        where_clause = ""
        if where_parts:
            where_clause = "WHERE " + " AND ".join(where_parts)

        query = f"""
            SELECT id, embedding {op} '{vec_str}'::vector AS distance, metadata
            FROM {table_name}
            {where_clause}
            ORDER BY embedding {op} '{vec_str}'::vector
            LIMIT {top_k};
        """

        async with self._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        results: list[SearchResult] = []
        for row in rows:
            meta = row["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            distance = float(row["distance"])
            if metric == SupabaseDistanceMetric.COSINE:
                score = 1.0 - distance
            elif metric == SupabaseDistanceMetric.L2:
                score = -distance
            else:
                score = -distance
            results.append(
                SearchResult(id=row["id"], score=score, metadata=meta)
            )

        return results

    # -- delete -------------------------------------------------------------

    async def delete(self, collection: str, id: str) -> bool:
        """Delete a vector by id.  Returns True if a row was removed."""
        self._ensure_connected()
        table_name = f"vec_{collection}"
        async with self._pg_pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {table_name} WHERE id = $1;", id
            )
        return result == "DELETE 1"

    async def delete_by_metadata(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete all vectors matching metadata filters.

        Returns
        -------
        int
            Number of rows deleted.
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"

        where_parts: list[str] = []
        params: list[Any] = []
        for i, (key, value) in enumerate(filters.items(), start=1):
            where_parts.append(f"metadata->>'{key}' = ${i}")
            params.append(str(value))

        where_clause = " AND ".join(where_parts)
        async with self._pg_pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {table_name} WHERE {where_clause};", *params
            )
        count = int(result.split()[-1]) if result else 0
        log.debug("Deleted %d rows from %s matching %s", count, collection, filters)
        return count

    # -- stats --------------------------------------------------------------

    async def get_collection_stats(self, collection: str) -> dict[str, Any]:
        """Return statistics for a collection.

        Returns
        -------
        dict
            Keys: count, dimensions, metric, table_size_bytes, table_size_mb.
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"
        dims = self._collections.get(collection, 0)

        async with self._pg_pool.acquire() as conn:
            count_row = await conn.fetchrow(
                f"SELECT COUNT(*) as cnt FROM {table_name};"
            )
            size_row = await conn.fetchrow(
                "SELECT pg_total_relation_size($1) as size;", table_name
            )

        count = count_row["cnt"] if count_row else 0
        size_bytes = size_row["size"] if size_row else 0

        return {
            "collection": collection,
            "count": count,
            "dimensions": dims,
            "metric": self._default_metric.value,
            "table_size_bytes": size_bytes,
            "table_size_mb": round(size_bytes / (1024 * 1024), 2) if size_bytes else 0,
        }

    # -- health -------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Check Supabase connection health.

        Returns
        -------
        dict
            Keys: status, latency_ms, collection_count.
        """
        t0 = time.monotonic()
        try:
            self._ensure_connected()
            async with self._pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1;")
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(elapsed, 1),
                "collection_count": len(self._collections),
                "backend": "supabase",
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "status": "unhealthy",
                "latency_ms": round(elapsed, 1),
                "error": str(exc),
                "backend": "supabase",
            }

    def __repr__(self) -> str:
        connected = self._pg_pool is not None
        return (
            f"SupabaseVectorStore(connected={connected}, "
            f"collections={list(self._collections.keys())})"
        )
