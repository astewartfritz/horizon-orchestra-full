"""Horizon Orchestra — Pinecone vector store adapter.

Async wrapper around the Pinecone SDK providing the same interface as
PGVectorStore, so the EmbeddingPipeline can transparently swap backends.

Requires:
  - pinecone (``pip install pinecone``)
  - A Pinecone API key set in ``PINECONE_API_KEY`` env var.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from pinecone import Pinecone as PineconeClient, ServerlessSpec, PodSpec

    _HAS_PINECONE = True
except ImportError:  # pragma: no cover
    PineconeClient = None  # type: ignore[assignment]
    ServerlessSpec = None  # type: ignore[assignment]
    PodSpec = None  # type: ignore[assignment]
    _HAS_PINECONE = False

__all__ = [
    "PineconeStore",
    "PineconeMetric",
    "PineconeCloud",
    "PineconeRegion",
]

log = logging.getLogger("orchestra.embeddings.pinecone")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PineconeMetric(str, Enum):
    """Pinecone distance metrics (maps to PGVectorStore's PGDistanceMetric)."""

    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    DOTPRODUCT = "dotproduct"


class PineconeCloud(str, Enum):
    """Supported cloud providers for serverless indexes."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class PineconeRegion(str, Enum):
    """Common Pinecone regions."""

    US_WEST_2 = "us-west-2"
    US_EAST_1 = "us-east-1"
    EU_WEST_1 = "eu-west-1"
    EU_WEST_4 = "eu-west-4"
    AP_SOUTHEAST_1 = "ap-southeast-1"
    AP_NORTHEAST_1 = "ap-northeast-1"


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """Single search hit from Pinecone."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


# ---------------------------------------------------------------------------
# PineconeStore
# ---------------------------------------------------------------------------


class PineconeStore:
    """Async vector store backed by Pinecone.

    Usage::

        store = PineconeStore()
        await store.connect()  # reads PINECONE_API_KEY
        await store.create_collection("docs", dimensions=1536)
        await store.insert("docs", "id1", [0.1, ...], {"title": "hello"})
        results = await store.search("docs", query_vec, top_k=5)
        await store.close()
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_metric: PineconeMetric | str = PineconeMetric.COSINE,
        default_cloud: PineconeCloud | str = PineconeCloud.AWS,
        default_region: PineconeRegion | str = PineconeRegion.US_WEST_2,
    ) -> None:
        if not _HAS_PINECONE:
            log.warning(
                "pinecone SDK is not installed — PineconeStore will raise on connect(). "
                "Install with: pip install pinecone"
            )
        self._api_key = api_key or os.environ.get("PINECONE_API_KEY", "")
        if isinstance(default_metric, str):
            default_metric = PineconeMetric(default_metric)
        if isinstance(default_cloud, str):
            default_cloud = PineconeCloud(default_cloud)
        if isinstance(default_region, str):
            default_region = PineconeRegion(default_region)

        self._client: Any = None
        self._default_metric = default_metric
        self._default_cloud = default_cloud
        self._default_region = default_region
        self._indexes: dict[str, Any] = {}  # index_name -> Pinecone Index handle

    # -- connection ---------------------------------------------------------

    async def connect(self, dsn: str = "") -> None:
        """Connect to Pinecone.

        Parameters
        ----------
        dsn:
            Ignored for Pinecone (uses env var). Kept for interface
            compatibility with PGVectorStore.
        """
        if not _HAS_PINECONE:
            raise ImportError(
                "pinecone SDK is required. Install with: pip install pinecone"
            )
        api_key = self._api_key or os.environ.get("PINECONE_API_KEY", "")
        if not api_key:
            raise ValueError(
                "Pinecone API key not set. Set PINECONE_API_KEY env var "
                "or pass api_key to the constructor."
            )
        self._client = PineconeClient(api_key=api_key)
        log.info("Connected to Pinecone")

    async def close(self) -> None:
        """Close the Pinecone client."""
        self._indexes.clear()
        self._client = None
        log.info("Closed Pinecone client")

    def _ensure_connected(self) -> None:
        if self._client is None:
            raise RuntimeError("Not connected — call connect() first")

    # -- collection management ----------------------------------------------

    async def create_collection(
        self,
        name: str,
        dimensions: int,
        *,
        metric: PineconeMetric | str | None = None,
        cloud: PineconeCloud | str | None = None,
        region: PineconeRegion | str | None = None,
        spec_type: str = "serverless",
        pods: int = 1,
        pod_type: str = "p1.x1",
        if_not_exists: bool = True,
    ) -> None:
        """Create a Pinecone index (maps to 'collection' in our abstraction).

        Parameters
        ----------
        name:
            Index name (alphanumeric + hyphens, lowercase only).
        dimensions:
            Vector dimension count.
        metric:
            Distance metric (defaults to store's default_metric).
        cloud:
            Cloud provider for serverless indexes.
        region:
            Cloud region.
        spec_type:
            ``"serverless"`` (default) or ``"pod"``.
        pods:
            Number of pods (pod-based indexes only).
        pod_type:
            Pod type (pod-based indexes only).
        if_not_exists:
            Skip creation if the index already exists.
        """
        self._ensure_connected()

        if isinstance(metric, str):
            metric = PineconeMetric(metric)
        if metric is None:
            metric = self._default_metric
        if isinstance(cloud, str):
            cloud = PineconeCloud(cloud)
        if cloud is None:
            cloud = self._default_cloud
        if isinstance(region, str):
            region = PineconeRegion(region)
        if region is None:
            region = self._default_region

        # Check if index exists
        existing = self._client.list_indexes()
        existing_names = [idx.get("name") for idx in existing if isinstance(idx, dict)]
        if name in existing_names:
            if if_not_exists:
                log.info("Index %r already exists — skipping creation", name)
                self._indexes[name] = self._client.Index(name)
                return
            raise ValueError(f"Index {name!r} already exists")

        # Build index spec
        if spec_type == "serverless":
            spec = ServerlessSpec(cloud=cloud.value, region=region.value)
        else:
            spec = PodSpec(
                environment=f"{cloud.value}-{region.value}",
                pods=pods,
                pod_type=pod_type,
            )

        self._client.create_index(
            name=name,
            dimension=dimensions,
            metric=metric.value,
            spec=spec,
        )
        log.info(
            "Creating Pinecone index %r (%d dims, metric=%s, %s, %s/%s)",
            name, dimensions, metric.value, spec_type, cloud.value, region.value,
        )

        # Wait for index to be ready
        self._client.describe_index(name)
        self._indexes[name] = self._client.Index(name)
        log.info("Pinecone index %r is ready", name)

    async def drop_collection(self, name: str) -> None:
        """Delete a Pinecone index."""
        self._ensure_connected()
        self._client.delete_index(name)
        self._indexes.pop(name, None)
        log.info("Deleted Pinecone index %r", name)

    async def list_collections(self) -> list[str]:
        """List all Pinecone indexes."""
        self._ensure_connected()
        indexes = self._client.list_indexes()
        return [idx.get("name") for idx in indexes if isinstance(idx, dict)]

    # -- upsert -------------------------------------------------------------

    async def insert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Upsert a single vector into a Pinecone index."""
        self._ensure_connected()
        idx = self._indexes.get(collection)
        if idx is None:
            idx = self._client.Index(collection)
            self._indexes[collection] = idx

        idx.upsert(
            vectors=[(id, vector, metadata or {})],
        )

    async def batch_insert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert multiple vectors into a Pinecone index.

        Pinecone SDK handles batching internally — chunks of 1000.
        """
        self._ensure_connected()
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if len(ids) != len(vectors) or len(ids) != len(metadatas):
            raise ValueError("ids, vectors, and metadatas must have the same length")

        idx = self._indexes.get(collection)
        if idx is None:
            idx = self._client.Index(collection)
            self._indexes[collection] = idx

        records = [
            (id_, vec, meta)
            for id_, vec, meta in zip(ids, vectors, metadatas)
        ]
        idx.upsert(vectors=records)
        log.debug("Batch upserted %d vectors into %s", len(ids), collection)

    # -- search -------------------------------------------------------------

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        *,
        metric: PineconeMetric | str | None = None,
        include_values: bool = False,
    ) -> list[SearchResult]:
        """Search for nearest vectors in a Pinecone index.

        Parameters
        ----------
        collection:
            Index name.
        query_vector:
            The query embedding.
        top_k:
            Maximum number of results.
        filters:
            Optional metadata filters (Pinecone filter expression).
        metric:
            Ignored — Pinecone uses the index's configured metric.
        include_values:
            Include vector values in results.

        Returns
        -------
        list[SearchResult]
            Results ordered by descending score (highest similarity first).
        """
        self._ensure_connected()
        idx = self._indexes.get(collection)
        if idx is None:
            idx = self._client.Index(collection)
            self._indexes[collection] = idx

        response = idx.query(
            vector=query_vector,
            top_k=top_k,
            filter=filters or {},
            include_metadata=True,
            include_values=include_values,
        )

        results: list[SearchResult] = []
        for match in response.get("matches", []):
            meta = match.get("metadata", {})
            if isinstance(meta, str):
                meta = json.loads(meta)
            results.append(
                SearchResult(
                    id=match["id"],
                    score=match["score"],
                    metadata=meta,
                )
            )

        return results

    # -- delete -------------------------------------------------------------

    async def delete(self, collection: str, id: str) -> bool:
        """Delete a vector by id.  Returns True (Pinecone is fire-and-forget)."""
        self._ensure_connected()
        idx = self._get_index(collection)
        idx.delete(ids=[id])
        return True

    async def delete_by_metadata(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete all vectors matching metadata filters.

        .. note::
           Pinecone does not return the count of deleted vectors.
           Returns 1 if the delete succeeded (best-effort count).
        """
        self._ensure_connected()
        idx = self._get_index(collection)
        idx.delete(filter=filters)
        log.debug("Deleted vectors from %s matching %s", collection, filters)
        return 1  # Pinecone returns no count

    # -- stats --------------------------------------------------------------

    async def get_collection_stats(self, collection: str) -> dict[str, Any]:
        """Return statistics for a Pinecone index.

        Returns
        -------
        dict
            Keys: collection, count, dimensions, metric, total_vector_count,
            index_fullness, namespaces.
        """
        self._ensure_connected()
        idx = self._get_index(collection)
        desc = self._client.describe_index(collection)
        stats = idx.describe_index_stats()

        return {
            "collection": collection,
            "count": stats.get("total_vector_count", 0),
            "dimensions": desc.get("dimension", 0) if isinstance(desc, dict) else 0,
            "metric": desc.get("metric", self._default_metric.value) if isinstance(desc, dict) else self._default_metric.value,
            "total_vector_count": stats.get("total_vector_count", 0),
            "index_fullness": stats.get("index_fullness", 0),
            "namespaces": stats.get("namespaces", {}),
        }

    # -- health -------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Check Pinecone connection health.

        Returns
        -------
        dict
            Keys: status (``"healthy"`` or ``"unhealthy"``), latency_ms,
            index_count.
        """
        t0 = time.monotonic()
        try:
            self._ensure_connected()
            indexes = await self.list_collections()
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(elapsed, 1),
                "index_count": len(indexes),
                "backend": "pinecone",
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "status": "unhealthy",
                "latency_ms": round(elapsed, 1),
                "error": str(exc),
                "backend": "pinecone",
            }

    # -- helpers ------------------------------------------------------------

    def _get_index(self, collection: str) -> Any:
        """Get or cache a Pinecone Index handle."""
        idx = self._indexes.get(collection)
        if idx is None:
            idx = self._client.Index(collection)
            self._indexes[collection] = idx
        return idx

    def __repr__(self) -> str:
        connected = self._client is not None
        return (
            f"PineconeStore(connected={connected}, "
            f"indexes={list(self._indexes.keys())})"
        )
