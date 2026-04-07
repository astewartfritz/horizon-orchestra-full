"""Horizon Orchestra — PostgreSQL pgvector Integration.

Provides a high-level async vector store backed by PostgreSQL with the
pgvector extension.  Supports L2 distance, cosine distance, and
inner-product operators, as well as GiST and IVFFlat indexing.

Requires:
  - asyncpg (``pip install asyncpg``)
  - PostgreSQL with ``CREATE EXTENSION vector;``
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

try:
    import asyncpg  # type: ignore[import-untyped]

    _HAS_ASYNCPG = True
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]
    _HAS_ASYNCPG = False

__all__ = [
    "PGVectorStore",
    "PGDistanceMetric",
    "PGIndexType",
]

log = logging.getLogger("orchestra.embeddings.pgvector")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PGDistanceMetric(str, Enum):
    """pgvector distance operators."""

    L2 = "l2"               # <->  Euclidean distance
    COSINE = "cosine"        # <=>  Cosine distance
    INNER_PRODUCT = "ip"     # <#>  Negative inner product


class PGIndexType(str, Enum):
    """pgvector index types."""

    NONE = "none"
    IVFFLAT = "ivfflat"
    HNSW = "hnsw"


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

_OPERATOR_MAP: dict[PGDistanceMetric, str] = {
    PGDistanceMetric.L2: "<->",
    PGDistanceMetric.COSINE: "<=>",
    PGDistanceMetric.INNER_PRODUCT: "<#>",
}

_IVFFLAT_OPS: dict[PGDistanceMetric, str] = {
    PGDistanceMetric.L2: "vector_l2_ops",
    PGDistanceMetric.COSINE: "vector_cosine_ops",
    PGDistanceMetric.INNER_PRODUCT: "vector_ip_ops",
}

_HNSW_OPS: dict[PGDistanceMetric, str] = {
    PGDistanceMetric.L2: "vector_l2_ops",
    PGDistanceMetric.COSINE: "vector_cosine_ops",
    PGDistanceMetric.INNER_PRODUCT: "vector_ip_ops",
}


# ---------------------------------------------------------------------------
# Search result re-export
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Single search hit from pgvector."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


# ---------------------------------------------------------------------------
# Collection metadata
# ---------------------------------------------------------------------------

@dataclass
class _CollectionInfo:
    """Internal bookkeeping for a pgvector collection."""

    name: str
    dimensions: int
    metric: PGDistanceMetric = PGDistanceMetric.COSINE
    index_type: PGIndexType = PGIndexType.NONE


# ---------------------------------------------------------------------------
# PGVectorStore
# ---------------------------------------------------------------------------

class PGVectorStore:
    """Async vector store backed by PostgreSQL + pgvector.

    Usage::

        store = PGVectorStore()
        await store.connect("postgresql://user:pass@localhost/mydb")
        await store.create_collection("docs", dimensions=1536)
        await store.insert("docs", "id1", [0.1, ...], {"title": "hello"})
        results = await store.search("docs", query_vec, top_k=5)
        await store.close()
    """

    def __init__(
        self,
        *,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
        default_metric: PGDistanceMetric | str = PGDistanceMetric.COSINE,
    ) -> None:
        if not _HAS_ASYNCPG:
            log.warning(
                "asyncpg is not installed — PGVectorStore will raise on connect(). "
                "Install with: pip install asyncpg"
            )
        if isinstance(default_metric, str):
            default_metric = PGDistanceMetric(default_metric)

        self._pool: Any = None  # asyncpg.Pool
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._default_metric = default_metric
        self._collections: dict[str, _CollectionInfo] = {}

    # -- connection ---------------------------------------------------------

    async def connect(self, dsn: str) -> None:
        """Connect to PostgreSQL and ensure the pgvector extension exists.

        Parameters
        ----------
        dsn:
            PostgreSQL connection string, e.g.
            ``postgresql://user:pass@localhost:5432/dbname``
        """
        if not _HAS_ASYNCPG:
            raise ImportError(
                "asyncpg is required for PGVectorStore. "
                "Install with: pip install asyncpg"
            )
        self._pool = await asyncpg.create_pool(
            dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
        )
        # Ensure pgvector extension
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            log.info("Connected to PostgreSQL and ensured pgvector extension")

        # Discover existing collections
        await self._discover_collections()

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("Closed PostgreSQL connection pool")

    def _ensure_connected(self) -> None:
        """Raise if not connected."""
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")

    # -- collection management ----------------------------------------------

    async def _discover_collections(self) -> None:
        """Load existing orchestra vector collections from the database."""
        self._ensure_connected()
        async with self._pool.acquire() as conn:
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
            cname = tname[4:]  # strip "vec_" prefix
            # Try to get dimension info
            try:
                async with self._pool.acquire() as conn:
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
            self._collections[cname] = _CollectionInfo(
                name=cname,
                dimensions=dims or 0,
            )

    async def create_collection(
        self,
        name: str,
        dimensions: int,
        *,
        metric: PGDistanceMetric | str | None = None,
        index_type: PGIndexType | str = PGIndexType.NONE,
        ivfflat_lists: int = 100,
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 64,
        if_not_exists: bool = True,
    ) -> None:
        """Create a new vector collection (table).

        Parameters
        ----------
        name:
            Collection name (alphanumeric + underscores).
        dimensions:
            Number of dimensions for the embedding vector.
        metric:
            Distance metric (defaults to store's default_metric).
        index_type:
            Type of vector index to create (none, ivfflat, or hnsw).
        ivfflat_lists:
            Number of lists for IVFFlat index (ignored for other types).
        hnsw_m:
            HNSW M parameter.
        hnsw_ef_construction:
            HNSW ef_construction parameter.
        if_not_exists:
            Skip creation if the table already exists.
        """
        self._ensure_connected()

        if isinstance(metric, str):
            metric = PGDistanceMetric(metric)
        if metric is None:
            metric = self._default_metric
        if isinstance(index_type, str):
            index_type = PGIndexType(index_type)

        table_name = f"vec_{name}"
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE {exists_clause} {table_name} (
                    id TEXT PRIMARY KEY,
                    embedding vector({dimensions}),
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Create vector index if requested
            if index_type == PGIndexType.IVFFLAT:
                ops = _IVFFLAT_OPS[metric]
                idx_name = f"idx_{name}_ivfflat"
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table_name}
                    USING ivfflat (embedding {ops})
                    WITH (lists = {ivfflat_lists});
                """)
                log.info("Created IVFFlat index on %s (lists=%d)", table_name, ivfflat_lists)

            elif index_type == PGIndexType.HNSW:
                ops = _HNSW_OPS[metric]
                idx_name = f"idx_{name}_hnsw"
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table_name}
                    USING hnsw (embedding {ops})
                    WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});
                """)
                log.info(
                    "Created HNSW index on %s (m=%d, ef_construction=%d)",
                    table_name,
                    hnsw_m,
                    hnsw_ef_construction,
                )

            # Metadata GiST index for filtered queries
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{name}_metadata
                ON {table_name}
                USING GIN (metadata);
            """)

        self._collections[name] = _CollectionInfo(
            name=name,
            dimensions=dimensions,
            metric=metric,
            index_type=index_type,
        )
        log.info(
            "Created collection %r (%d dims, metric=%s, index=%s)",
            name,
            dimensions,
            metric.value,
            index_type.value,
        )

    async def drop_collection(self, name: str) -> None:
        """Drop a vector collection and its associated table.

        Parameters
        ----------
        name:
            Collection name.
        """
        self._ensure_connected()
        table_name = f"vec_{name}"
        async with self._pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        self._collections.pop(name, None)
        log.info("Dropped collection %r", name)

    async def list_collections(self) -> list[str]:
        """Return a list of all known collection names."""
        self._ensure_connected()
        await self._discover_collections()
        return list(self._collections.keys())

    # -- insert -------------------------------------------------------------

    @staticmethod
    def _vec_literal(vector: list[float] | Sequence[float]) -> str:
        """Format a vector as a pgvector literal string ``'[0.1,0.2,...]'``."""
        return "[" + ",".join(f"{v}" for v in vector) + "]"

    async def insert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert a single vector into a collection.

        Parameters
        ----------
        collection:
            Collection name.
        id:
            Unique identifier.
        vector:
            The embedding vector.
        metadata:
            Optional JSON-serialisable metadata.
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"
        meta_json = json.dumps(metadata or {})
        vec_str = self._vec_literal(vector)

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {table_name} (id, embedding, metadata)
                VALUES ($1, $2::vector, $3::jsonb)
                ON CONFLICT (id) DO UPDATE
                    SET embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata;
                """,
                id,
                vec_str,
                meta_json,
            )

    async def batch_insert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert multiple vectors in a single transaction.

        Parameters
        ----------
        collection:
            Collection name.
        ids:
            List of unique identifiers.
        vectors:
            List of embedding vectors.
        metadatas:
            Optional per-vector metadata dicts.
        """
        self._ensure_connected()
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if len(ids) != len(vectors) or len(ids) != len(metadatas):
            raise ValueError("ids, vectors, and metadatas must have the same length")

        table_name = f"vec_{collection}"
        records = []
        for id_, vec, meta in zip(ids, vectors, metadatas):
            records.append((id_, self._vec_literal(vec), json.dumps(meta)))

        async with self._pool.acquire() as conn:
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
        metric: PGDistanceMetric | str | None = None,
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
            Distance metric override (defaults to collection's metric).

        Returns
        -------
        list[SearchResult]
            Results ordered by ascending distance (closest first).
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"

        # Resolve metric
        if metric is not None:
            if isinstance(metric, str):
                metric = PGDistanceMetric(metric)
        else:
            info = self._collections.get(collection)
            metric = info.metric if info else self._default_metric

        op = _OPERATOR_MAP[metric]
        vec_str = self._vec_literal(query_vector)

        # Build filter clause
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

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        results: list[SearchResult] = []
        for row in rows:
            meta = row["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            # Convert distance to a similarity score:
            # - For cosine/L2: score = -distance (lower distance = higher score)
            # - For inner product: pgvector returns negative IP, so negate back
            distance = float(row["distance"])
            if metric == PGDistanceMetric.COSINE:
                score = 1.0 - distance  # cosine similarity
            elif metric == PGDistanceMetric.L2:
                score = -distance
            else:  # inner product
                score = -distance  # pgvector uses negative IP
            results.append(
                SearchResult(
                    id=row["id"],
                    score=score,
                    metadata=meta,
                )
            )

        return results

    # -- delete -------------------------------------------------------------

    async def delete(self, collection: str, id: str) -> bool:
        """Delete a vector by id.  Returns True if a row was removed.

        Parameters
        ----------
        collection:
            Collection name.
        id:
            The vector's unique identifier.
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {table_name} WHERE id = $1;", id
            )
        deleted = result == "DELETE 1"
        if deleted:
            log.debug("Deleted %s from %s", id, collection)
        return deleted

    async def delete_by_metadata(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete all vectors matching metadata filters.

        Parameters
        ----------
        collection:
            Collection name.
        filters:
            Metadata key-value pairs (exact equality).

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
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {table_name} WHERE {where_clause};", *params
            )
        # Result is like "DELETE 5"
        count = int(result.split()[-1]) if result else 0
        log.debug("Deleted %d rows from %s matching %s", count, collection, filters)
        return count

    # -- stats --------------------------------------------------------------

    async def get_collection_stats(self, collection: str) -> dict[str, Any]:
        """Return statistics for a collection.

        Returns
        -------
        dict
            Keys: count, dimensions, metric, index_type, table_size_bytes.
        """
        self._ensure_connected()
        table_name = f"vec_{collection}"
        info = self._collections.get(collection)

        async with self._pool.acquire() as conn:
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
            "dimensions": info.dimensions if info else 0,
            "metric": info.metric.value if info else self._default_metric.value,
            "index_type": info.index_type.value if info else "none",
            "table_size_bytes": size_bytes,
            "table_size_mb": round(size_bytes / (1024 * 1024), 2) if size_bytes else 0,
        }

    def __repr__(self) -> str:
        connected = self._pool is not None
        return (
            f"PGVectorStore(connected={connected}, "
            f"collections={list(self._collections.keys())})"
        )
