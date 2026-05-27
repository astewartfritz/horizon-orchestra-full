"""Horizon Orchestra — ChromaDB Vector Store Integration.

Wraps the ChromaDB client (embedded or HTTP) in the same interface used by
PGVectorStore and PineconeStore so it plugs directly into EmbeddingPipeline.

Modes:
  - ``embedded`` (default): persistent local store at *path*
  - ``http``: remote Chroma server via host + port

Requires: ``pip install chromadb``
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

try:
    import chromadb  # type: ignore[import-untyped]
    from chromadb.api import ClientAPI  # type: ignore[import-untyped]
    _HAS_CHROMA = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    ClientAPI = object  # type: ignore[assignment, misc]
    _HAS_CHROMA = False

__all__ = ["ChromaStore"]

log = logging.getLogger("orchestra.embeddings.chroma")

_METRIC_MAP = {
    "cosine": "cosine",
    "l2": "l2",
    "ip": "ip",
}


@dataclass
class SearchResult:
    """Single search hit from ChromaDB."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


class ChromaStore:
    """Async-compatible vector store backed by ChromaDB.

    Usage (embedded)::

        store = ChromaStore()
        await store.connect()
        await store.create_collection("docs", dimensions=1536)
        await store.batch_insert("docs", ids, vectors, metadatas)
        results = await store.search("docs", query_vec, top_k=5)
        await store.close()

    Usage (HTTP)::

        store = ChromaStore(mode="http", host="localhost", port=8000)
        await store.connect()
        ...
    """

    def __init__(
        self,
        *,
        mode: str = "embedded",
        path: str = ".chroma",
        host: str = "localhost",
        port: int = 8000,
        default_metric: str = "cosine",
    ) -> None:
        if not _HAS_CHROMA:
            log.warning(
                "chromadb not installed — ChromaStore will raise on connect(). "
                "Install with: pip install chromadb"
            )
        if mode not in ("embedded", "http"):
            raise ValueError("mode must be 'embedded' or 'http'")
        if default_metric not in _METRIC_MAP:
            raise ValueError(f"metric must be one of: {list(_METRIC_MAP)}")

        self._mode = mode
        self._path = path
        self._host = host
        self._port = port
        self._default_metric = _METRIC_MAP[default_metric]
        self._client: Any = None  # chromadb ClientAPI
        self._collections: dict[str, Any] = {}  # name -> chroma Collection

    # -- connection ----------------------------------------------------------

    async def connect(self) -> None:
        """Initialise the Chroma client.  Runs synchronous Chroma I/O off the event loop."""
        if not _HAS_CHROMA:
            raise ImportError(
                "chromadb is required for ChromaStore. "
                "Install with: pip install chromadb"
            )

        def _init() -> Any:
            if self._mode == "http":
                return chromadb.HttpClient(host=self._host, port=self._port)
            return chromadb.PersistentClient(path=self._path)

        self._client = await asyncio.to_thread(_init)
        log.info(
            "Connected to ChromaDB (%s=%s)",
            "http" if self._mode == "http" else "path",
            f"{self._host}:{self._port}" if self._mode == "http" else self._path,
        )

    async def close(self) -> None:
        """Release the client reference (Chroma manages its own connections)."""
        self._client = None
        self._collections.clear()
        log.info("ChromaStore closed")

    def _ensure_connected(self) -> None:
        if self._client is None:
            raise RuntimeError("ChromaStore not connected — call connect() first")

    # -- collection management -----------------------------------------------

    async def create_collection(
        self,
        name: str,
        dimensions: int,
        *,
        metric: str | None = None,
        if_not_exists: bool = True,
    ) -> None:
        """Get or create a Chroma collection.

        Parameters
        ----------
        name:
            Collection name.
        dimensions:
            Embedding dimensionality (informational; Chroma infers from data).
        metric:
            Distance metric override (``cosine``, ``l2``, ``ip``).
        if_not_exists:
            If False, raises if the collection already exists.
        """
        self._ensure_connected()
        resolved_metric = _METRIC_MAP.get(metric or "", self._default_metric)
        client = self._client

        def _create() -> Any:
            if if_not_exists:
                return client.get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": resolved_metric},
                )
            return client.create_collection(
                name=name,
                metadata={"hnsw:space": resolved_metric},
            )

        collection = await asyncio.to_thread(_create)
        self._collections[name] = collection
        log.info(
            "ChromaDB collection %r ready (metric=%s, dims=%d)",
            name,
            resolved_metric,
            dimensions,
        )

    def _get_collection(self, name: str) -> Any:
        """Return cached collection or fetch it lazily (sync)."""
        if name in self._collections:
            return self._collections[name]
        # Lazy fetch — called inside to_thread
        col = self._client.get_collection(name)
        self._collections[name] = col
        return col

    # -- insert --------------------------------------------------------------

    async def batch_insert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert vectors into a collection.

        Parameters
        ----------
        collection:
            Collection name.
        ids:
            Unique identifiers for each vector.
        vectors:
            Embedding vectors.
        metadatas:
            Per-vector metadata dicts (must be flat str/int/float/bool values).
        """
        self._ensure_connected()
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if len(ids) != len(vectors) or len(ids) != len(metadatas):
            raise ValueError("ids, vectors, and metadatas must have the same length")

        # Chroma metadata values must be scalar; stringify nested structures
        flat_metas = [_flatten_metadata(m) for m in metadatas]
        client = self._client

        def _upsert() -> None:
            col = self._get_collection(collection)
            col.upsert(ids=ids, embeddings=vectors, metadatas=flat_metas)

        await asyncio.to_thread(_upsert)
        log.debug("Upserted %d vectors into ChromaDB collection %r", len(ids), collection)

    # -- search --------------------------------------------------------------

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Query the collection for nearest neighbours.

        Parameters
        ----------
        collection:
            Collection name.
        query_vector:
            The query embedding.
        top_k:
            Maximum results to return.
        filters:
            Metadata filters using Chroma's ``where`` clause format.
            Simple equality dict ``{"key": "value"}`` is automatically
            converted to Chroma's ``{"key": {"$eq": "value"}}`` form.

        Returns
        -------
        list[SearchResult]
            Results ordered by descending similarity.
        """
        self._ensure_connected()
        where = _build_where(filters) if filters else None
        client = self._client

        def _query() -> Any:
            col = self._get_collection(collection)
            kwargs: dict[str, Any] = {
                "query_embeddings": [query_vector],
                "n_results": top_k,
                "include": ["distances", "metadatas"],
            }
            if where:
                kwargs["where"] = where
            return col.query(**kwargs)

        raw = await asyncio.to_thread(_query)

        results: list[SearchResult] = []
        ids_list = raw.get("ids", [[]])[0]
        distances = raw.get("distances", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]

        for rid, dist, meta in zip(ids_list, distances, metas):
            # Chroma returns distances; convert to similarity score
            # For cosine: distance ∈ [0, 2], similarity = 1 - distance/2
            # For l2: use negative distance so higher = closer
            metric = self._default_metric
            if metric == "cosine":
                score = 1.0 - dist / 2.0
            elif metric == "ip":
                score = -dist
            else:
                score = -dist
            results.append(SearchResult(id=rid, score=score, metadata=meta or {}))

        return results

    # -- delete --------------------------------------------------------------

    async def delete_by_metadata(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete all vectors whose metadata matches *filters*.

        Parameters
        ----------
        collection:
            Collection name.
        filters:
            Metadata key-value pairs (exact equality).

        Returns
        -------
        int
            Number of vectors deleted.
        """
        self._ensure_connected()
        where = _build_where(filters)
        client = self._client

        def _delete() -> int:
            col = self._get_collection(collection)
            # First get matching IDs
            result = col.get(where=where, include=[])
            ids_to_delete = result.get("ids", [])
            if ids_to_delete:
                col.delete(ids=ids_to_delete)
            return len(ids_to_delete)

        count = await asyncio.to_thread(_delete)
        log.debug("Deleted %d vectors from ChromaDB collection %r", count, collection)
        return count

    # -- health --------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Return health status of the ChromaDB connection."""
        import time
        t0 = time.monotonic()
        try:
            self._ensure_connected()
            client = self._client

            def _ping() -> int:
                return client.heartbeat()

            await asyncio.to_thread(_ping)
            latency_ms = (time.monotonic() - t0) * 1000
            return {
                "status": "healthy",
                "backend": "chroma",
                "mode": self._mode,
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "backend": "chroma",
                "mode": self._mode,
                "error": str(exc),
            }

    def __repr__(self) -> str:
        connected = self._client is not None
        return (
            f"ChromaStore(connected={connected}, mode={self._mode!r}, "
            f"collections={list(self._collections.keys())})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma requires flat scalar metadata values; stringify everything else."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _build_where(filters: dict[str, Any]) -> dict[str, Any]:
    """Convert a simple equality dict to Chroma's ``where`` clause format."""
    if len(filters) == 1:
        k, v = next(iter(filters.items()))
        return {k: {"$eq": str(v)}}
    return {"$and": [{k: {"$eq": str(v)}} for k, v in filters.items()]}
