"""Horizon Orchestra — End-to-End Embedding Pipeline.

Orchestrates the full ingest → chunk → embed → store workflow, with
support for in-memory (VectorIndex), PostgreSQL (PGVectorStore), Pinecone
(PineconeStore), and Supabase (SupabaseVectorStore) backends.  Provides
semantic search over ingested documents with optional embedding caching.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from .cache import EmbeddingCache
from .chunker import Chunk, ChunkStrategy, TextChunker
from .index import SearchResult as _IndexSearchResult, VectorIndex
from .models import EMBEDDING_MODELS, EmbeddingClient, EmbeddingModel
from .pgvector import PGVectorStore

try:
    from .pinecone import PineconeStore
    _HAS_PINECONE = True
except ImportError:
    PineconeStore = None  # type: ignore[assignment]
    _HAS_PINECONE = False

try:
    from .supabase import SupabaseVectorStore
    _HAS_SUPABASE = True
except ImportError:
    SupabaseVectorStore = None  # type: ignore[assignment]
    _HAS_SUPABASE = False

try:
    from .chroma import ChromaStore
    _HAS_CHROMA = True
except ImportError:
    ChromaStore = None  # type: ignore[assignment]
    _HAS_CHROMA = False

__all__ = [
    "EmbeddingPipeline",
    "PipelineConfig",
    "IngestResult",
    "SearchResult",
]

log = logging.getLogger("orchestra.embeddings.pipeline")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Configuration for the embedding pipeline."""

    # Embedding model
    model: str = "text-embedding-3-small"

    # Chunking
    chunk_strategy: ChunkStrategy | str = ChunkStrategy.RECURSIVE
    chunk_size: int = 512
    chunk_overlap: int = 64   # ~12.5% overlap; was 50
    min_chunk_size: int = 20  # micro-fragments below this are merged

    # Vector store backend
    store_backend: Literal["memory", "pgvector", "pinecone", "supabase", "chroma"] = "memory"

    # In-memory index options
    index_metric: str = "cosine"
    index_use_hnsw: bool = False

    # pgvector options
    pgvector_dsn: str = ""
    pgvector_collection: str = "default"
    pgvector_dimensions: int | None = None  # auto-detected from model

    # Pinecone options
    pinecone_api_key: str = ""
    pinecone_collection: str = "default"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-west-2"
    pinecone_metric: str = "cosine"

    # Supabase options
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_collection: str = "default"

    # Chroma options
    chroma_mode: str = "embedded"       # "embedded" | "http"
    chroma_path: str = ".chroma"        # local path for embedded mode
    chroma_host: str = "localhost"      # HTTP mode host
    chroma_port: int = 8000             # HTTP mode port
    chroma_collection: str = "default"
    chroma_metric: str = "cosine"       # cosine | l2 | ip

    # Embedding cache options
    embedding_cache_size: int = 10000
    embedding_cache_path: str = ".embedding-cache.db"

    def __post_init__(self) -> None:
        if isinstance(self.chunk_strategy, str):
            self.chunk_strategy = ChunkStrategy(self.chunk_strategy)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """Summary of an ingest operation."""

    source: str
    chunk_ids: list[str]
    chunk_count: int
    total_tokens: int
    elapsed_seconds: float

    def __repr__(self) -> str:
        return (
            f"IngestResult(source={self.source!r}, chunks={self.chunk_count}, "
            f"tokens={self.total_tokens}, elapsed={self.elapsed_seconds:.2f}s)"
        )


@dataclass
class SearchResult:
    """Single search result from the pipeline."""

    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        preview = self.text[:80].replace("\n", " ")
        return f"SearchResult(id={self.id!r}, score={self.score:.4f}, text={preview!r}…)"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class EmbeddingPipeline:
    """End-to-end embedding pipeline: ingest, chunk, embed, search.

    Usage::

        pipeline = EmbeddingPipeline()
        ids = await pipeline.ingest("Document text here...", source="readme.md")
        results = await pipeline.semantic_search("What is the API endpoint?", top_k=5)

    For pgvector backend::

        config = PipelineConfig(
            store_backend="pgvector",
            pgvector_dsn="postgresql://user:pass@localhost/db",
        )
        pipeline = EmbeddingPipeline(config=config)
        await pipeline.initialize()
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        embed_client: EmbeddingClient | None = None,
        chunker: TextChunker | None = None,
        vector_index: VectorIndex | None = None,
        pgvector_store: PGVectorStore | None = None,
        pinecone_store: Any = None,
        supabase_store: Any = None,
        chroma_store: Any = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self._embed_client = embed_client or EmbeddingClient()
        self._chunker = chunker or TextChunker(
            default_chunk_size=self.config.chunk_size,
            default_overlap=self.config.chunk_overlap,
            default_strategy=self.config.chunk_strategy,
            min_chunk_size=self.config.min_chunk_size,
        )

        # Resolve model dimensions
        model_spec = EMBEDDING_MODELS.get(self.config.model)
        self._dimensions = (
            model_spec.dimensions if model_spec else 1536
        )
        if self.config.pgvector_dimensions:
            self._dimensions = self.config.pgvector_dimensions

        # Store backend
        self._store_backend = self.config.store_backend
        self._vector_index: VectorIndex | None = vector_index
        self._pgvector_store: PGVectorStore | None = pgvector_store
        self._pinecone_store: Any = pinecone_store
        self._supabase_store: Any = supabase_store
        self._chroma_store: Any = chroma_store

        if self._store_backend == "memory" and self._vector_index is None:
            self._vector_index = VectorIndex(
                dimensions=self._dimensions,
                metric=self.config.index_metric,
                use_hnsw=self.config.index_use_hnsw,
            )

        # Embedding cache (optional — reduces API calls)
        self._cache = embedding_cache
        if self._cache is None and self.config.embedding_cache_size > 0:
            try:
                self._cache = EmbeddingCache(
                    max_size=self.config.embedding_cache_size,
                    db_path=self.config.embedding_cache_path or None,
                )
            except Exception as exc:
                log.warning("Failed to initialise embedding cache: %s", exc)

        # Bookkeeping
        self._total_documents: int = 0
        self._total_chunks: int = 0
        self._sources: dict[str, list[str]] = {}  # source -> list of chunk IDs
        self._chunk_texts: dict[str, str] = {}     # chunk_id -> chunk text

        self._initialized = self._store_backend == "memory"

    # -- initialization -----------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the pipeline (connect to backend store if needed)."""
        if self._store_backend == "pgvector":
            if self._pgvector_store is None:
                self._pgvector_store = PGVectorStore()
            dsn = self.config.pgvector_dsn
            if not dsn:
                raise ValueError(
                    "pgvector_dsn is required when store_backend='pgvector'"
                )
            await self._pgvector_store.connect(dsn)
            await self._pgvector_store.create_collection(
                self.config.pgvector_collection,
                dimensions=self._dimensions,
                if_not_exists=True,
            )
            log.info(
                "Initialized pgvector collection %r (%d dims)",
                self.config.pgvector_collection,
                self._dimensions,
            )

        elif self._store_backend == "pinecone":
            if not _HAS_PINECONE:
                raise ImportError(
                    "Pinecone SDK is required when store_backend='pinecone'. "
                    "Install with: pip install pinecone"
                )
            if self._pinecone_store is None:
                self._pinecone_store = PineconeStore(
                    api_key=self.config.pinecone_api_key or None,
                    default_metric=self.config.pinecone_metric,
                    default_region=self.config.pinecone_region,
                )
            await self._pinecone_store.connect()
            await self._pinecone_store.create_collection(
                self.config.pinecone_collection,
                dimensions=self._dimensions,
                metric=self.config.pinecone_metric,
                if_not_exists=True,
            )
            log.info(
                "Initialized Pinecone index %r (%d dims)",
                self.config.pinecone_collection,
                self._dimensions,
            )

        elif self._store_backend == "supabase":
            if not _HAS_SUPABASE:
                raise ImportError(
                    "Supabase SDK + asyncpg are required when "
                    "store_backend='supabase'. Install with: "
                    "pip install supabase asyncpg"
                )
            if self._supabase_store is None:
                self._supabase_store = SupabaseVectorStore(
                    supabase_url=self.config.supabase_url or None,
                    supabase_key=self.config.supabase_key or None,
                )
            await self._supabase_store.connect()
            await self._supabase_store.create_collection(
                self.config.supabase_collection,
                dimensions=self._dimensions,
                if_not_exists=True,
            )
            log.info(
                "Initialized Supabase collection %r (%d dims)",
                self.config.supabase_collection,
                self._dimensions,
            )

        elif self._store_backend == "chroma":
            if not _HAS_CHROMA:
                raise ImportError(
                    "chromadb is required when store_backend='chroma'. "
                    "Install with: pip install chromadb"
                )
            if self._chroma_store is None:
                self._chroma_store = ChromaStore(
                    mode=self.config.chroma_mode,
                    path=self.config.chroma_path,
                    host=self.config.chroma_host,
                    port=self.config.chroma_port,
                    default_metric=self.config.chroma_metric,
                )
            await self._chroma_store.connect()
            await self._chroma_store.create_collection(
                self.config.chroma_collection,
                dimensions=self._dimensions,
                if_not_exists=True,
            )
            log.info(
                "Initialized ChromaDB collection %r (%d dims, mode=%s)",
                self.config.chroma_collection,
                self._dimensions,
                self.config.chroma_mode,
            )

        self._initialized = True

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "Pipeline not initialized — call await pipeline.initialize() first"
            )

    # -- ingest -------------------------------------------------------------

    async def ingest(
        self,
        text: str,
        source: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Chunk, embed, and store text.  Returns chunk IDs.

        Parameters
        ----------
        text:
            The document text to ingest.
        source:
            Source identifier (filename, URL, etc.).
        metadata:
            Additional metadata to attach to each chunk.

        Returns
        -------
        list[str]
            IDs of the stored chunks.
        """
        self._ensure_initialized()
        t0 = time.monotonic()

        # 1. Chunk
        chunks = self._chunker.chunk(text)
        if not chunks:
            log.warning("No chunks produced from source=%s", source)
            return []

        # 2. Embed (with optional cache)
        chunk_texts = [c.text for c in chunks]
        cache = self._cache

        # Try cache hit for all chunks
        if cache is not None:
            hits, miss_indices = cache.get_batch(chunk_texts, model=self.config.model)
            if miss_indices:
                miss_texts = [chunk_texts[i] for i in miss_indices]
                miss_vectors = await self._embed_client.batch_embed(
                    miss_texts, model=self.config.model,
                )
                cache.put_batch(miss_texts, miss_vectors, model=self.config.model)
                # Rebuild full vectors list
                vectors = [None] * len(chunk_texts)
                for idx, vec in hits.items():
                    vectors[idx] = vec
                for idx, vec in zip(miss_indices, miss_vectors):
                    vectors[idx] = vec
            else:
                vectors = [hits[i] for i in range(len(chunk_texts))]
        else:
            vectors = await self._embed_client.batch_embed(chunk_texts, model=self.config.model)

        # 3. Generate IDs and prepare metadata
        chunk_ids: list[str] = []
        chunk_metas: list[dict[str, Any]] = []
        total_tokens = 0

        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = f"{source}::{uuid.uuid4().hex[:12]}"
            chunk_ids.append(chunk_id)

            meta = dict(metadata or {})
            meta.update({
                "source": source,
                "chunk_index": i,
                "chunk_start": chunk.start,
                "chunk_end": chunk.end,
                "token_count": chunk.token_count,
            })
            chunk_metas.append(meta)
            total_tokens += chunk.token_count

            # Store chunk text for retrieval
            self._chunk_texts[chunk_id] = chunk.text

        # 4. Store vectors
        if self._store_backend == "memory" and self._vector_index is not None:
            self._vector_index.batch_insert(chunk_ids, vectors, chunk_metas)
        elif self._store_backend == "pgvector" and self._pgvector_store is not None:
            await self._pgvector_store.batch_insert(
                self.config.pgvector_collection,
                chunk_ids,
                vectors,
                chunk_metas,
            )
        elif self._store_backend == "pinecone" and self._pinecone_store is not None:
            await self._pinecone_store.batch_insert(
                self.config.pinecone_collection,
                chunk_ids,
                vectors,
                chunk_metas,
            )
        elif self._store_backend == "supabase" and self._supabase_store is not None:
            await self._supabase_store.batch_insert(
                self.config.supabase_collection,
                chunk_ids,
                vectors,
                chunk_metas,
            )
        elif self._store_backend == "chroma" and self._chroma_store is not None:
            await self._chroma_store.batch_insert(
                self.config.chroma_collection,
                chunk_ids,
                vectors,
                chunk_metas,
            )
        else:
            raise RuntimeError(f"No vector store available for backend={self._store_backend}")

        # 5. Bookkeeping
        elapsed = time.monotonic() - t0
        self._total_documents += 1
        self._total_chunks += len(chunks)
        self._sources.setdefault(source, []).extend(chunk_ids)

        result = IngestResult(
            source=source,
            chunk_ids=chunk_ids,
            chunk_count=len(chunks),
            total_tokens=total_tokens,
            elapsed_seconds=elapsed,
        )
        log.info("Ingested %s", result)
        return chunk_ids

    async def ingest_file(self, path: str | Path, **kwargs: Any) -> list[str]:
        """Read a file and ingest its contents.

        Parameters
        ----------
        path:
            Path to the file to ingest.
        **kwargs:
            Additional arguments passed to :meth:`ingest`.

        Returns
        -------
        list[str]
            IDs of the stored chunks.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")
        source = kwargs.pop("source", path.name)
        return await self.ingest(text, source=source, **kwargs)

    async def ingest_url(self, url: str, **kwargs: Any) -> list[str]:
        """Fetch a URL and ingest its text content.

        Parameters
        ----------
        url:
            The URL to fetch.
        **kwargs:
            Additional arguments passed to :meth:`ingest`.

        Returns
        -------
        list[str]
            IDs of the stored chunks.

        Raises
        ------
        ImportError
            If httpx is not installed.
        """
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for ingest_url. Install with: pip install httpx"
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text

        # Try to extract text from HTML
        text = self._strip_html(text)
        source = kwargs.pop("source", url)
        return await self.ingest(text, source=source, **kwargs)

    @staticmethod
    def _strip_html(text: str) -> str:
        """Basic HTML tag stripping."""
        import re
        # Remove script/style blocks
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # -- search -------------------------------------------------------------

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search by raw vector.

        Parameters
        ----------
        query_vector:
            Pre-computed query embedding.
        top_k:
            Maximum results to return.
        filters:
            Optional metadata filters.

        Returns
        -------
        list[SearchResult]
        """
        self._ensure_initialized()

        if self._store_backend == "memory" and self._vector_index is not None:
            raw = self._vector_index.search(query_vector, top_k=top_k, filters=filters)
            return [
                SearchResult(
                    id=r.id,
                    score=r.score,
                    text=self._chunk_texts.get(r.id, ""),
                    metadata=r.metadata,
                )
                for r in raw
            ]
        elif self._store_backend == "pgvector" and self._pgvector_store is not None:
            raw_pg = await self._pgvector_store.search(
                self.config.pgvector_collection,
                query_vector,
                top_k=top_k,
                filters=filters,
            )
            return [
                SearchResult(
                    id=r.id,
                    score=r.score,
                    text=self._chunk_texts.get(r.id, ""),
                    metadata=r.metadata,
                )
                for r in raw_pg
            ]
        elif self._store_backend == "pinecone" and self._pinecone_store is not None:
            raw_pc = await self._pinecone_store.search(
                self.config.pinecone_collection,
                query_vector,
                top_k=top_k,
                filters=filters,
            )
            return [
                SearchResult(
                    id=r.id,
                    score=r.score,
                    text=self._chunk_texts.get(r.id, ""),
                    metadata=r.metadata,
                )
                for r in raw_pc
            ]
        elif self._store_backend == "supabase" and self._supabase_store is not None:
            raw_sb = await self._supabase_store.search(
                self.config.supabase_collection,
                query_vector,
                top_k=top_k,
                filters=filters,
            )
            return [
                SearchResult(
                    id=r.id,
                    score=r.score,
                    text=self._chunk_texts.get(r.id, ""),
                    metadata=r.metadata,
                )
                for r in raw_sb
            ]
        elif self._store_backend == "chroma" and self._chroma_store is not None:
            raw_ch = await self._chroma_store.search(
                self.config.chroma_collection,
                query_vector,
                top_k=top_k,
                filters=filters,
            )
            return [
                SearchResult(
                    id=r.id,
                    score=r.score,
                    text=self._chunk_texts.get(r.id, ""),
                    metadata=r.metadata,
                )
                for r in raw_ch
            ]
        else:
            raise RuntimeError("No vector store available")

    async def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Embed the query text and search for nearest chunks.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum results to return.
        filters:
            Optional metadata filters.

        Returns
        -------
        list[SearchResult]
        """
        query_vec = await self._embed_client.embed(query, model=self.config.model)
        return await self.search(query_vec, top_k=top_k, filters=filters)

    # -- deletion -----------------------------------------------------------

    async def delete_source(self, source: str) -> int:
        """Delete all chunks for a given source.

        Parameters
        ----------
        source:
            The source identifier used during ingest.

        Returns
        -------
        int
            Number of chunks deleted.
        """
        self._ensure_initialized()
        chunk_ids = self._sources.get(source, [])
        if not chunk_ids:
            return 0

        count = 0
        if self._store_backend == "memory" and self._vector_index is not None:
            for cid in chunk_ids:
                if self._vector_index.delete(cid):
                    count += 1
                self._chunk_texts.pop(cid, None)
        elif self._store_backend == "pgvector" and self._pgvector_store is not None:
            count = await self._pgvector_store.delete_by_metadata(
                self.config.pgvector_collection,
                {"source": source},
            )
            for cid in chunk_ids:
                self._chunk_texts.pop(cid, None)
        elif self._store_backend == "pinecone" and self._pinecone_store is not None:
            count = await self._pinecone_store.delete_by_metadata(
                self.config.pinecone_collection,
                {"source": source},
            )
            for cid in chunk_ids:
                self._chunk_texts.pop(cid, None)
        elif self._store_backend == "supabase" and self._supabase_store is not None:
            count = await self._supabase_store.delete_by_metadata(
                self.config.supabase_collection,
                {"source": source},
            )
            for cid in chunk_ids:
                self._chunk_texts.pop(cid, None)
        elif self._store_backend == "chroma" and self._chroma_store is not None:
            count = await self._chroma_store.delete_by_metadata(
                self.config.chroma_collection,
                {"source": source},
            )
            for cid in chunk_ids:
                self._chunk_texts.pop(cid, None)
        else:
            raise RuntimeError("No vector store available")

        self._total_chunks -= count
        self._total_documents = max(0, self._total_documents - 1)
        del self._sources[source]
        log.info("Deleted %d chunks for source=%s", count, source)
        return count

    # -- statistics ---------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return pipeline statistics.

        Returns
        -------
        dict
            Keys: total_documents, total_chunks, model, chunk_strategy,
            store_backend, dimensions, sources, index_stats.
        """
        index_stats: dict[str, Any] = {}
        if self._vector_index is not None:
            index_stats = self._vector_index.get_stats()

        return {
            "total_documents": self._total_documents,
            "total_chunks": self._total_chunks,
            "model": self.config.model,
            "chunk_strategy": (
                self.config.chunk_strategy.value
                if isinstance(self.config.chunk_strategy, ChunkStrategy)
                else self.config.chunk_strategy
            ),
            "chunk_size": self.config.chunk_size,
            "store_backend": self._store_backend,
            "dimensions": self._dimensions,
            "sources": list(self._sources.keys()),
            "source_count": len(self._sources),
            "index_stats": index_stats,
        }

    async def close(self) -> None:
        """Close underlying clients, connections, and cache."""
        await self._embed_client.close()
        if self._pgvector_store is not None:
            await self._pgvector_store.close()
        if self._pinecone_store is not None:
            await self._pinecone_store.close()
        if self._supabase_store is not None:
            await self._supabase_store.close()
        if self._chroma_store is not None:
            await self._chroma_store.close()
        if self._cache is not None:
            self._cache.close()

    async def health_check(self) -> dict[str, Any]:
        """Check health of the configured backend store.

        Returns
        -------
        dict with keys: status, backend, latency_ms, error (if unhealthy).
        """
        if self._store_backend == "memory":
            return {"status": "healthy", "backend": "memory", "latency_ms": 0.0}

        store: Any = None
        if self._store_backend == "pgvector":
            store = self._pgvector_store
        elif self._store_backend == "pinecone":
            store = self._pinecone_store
        elif self._store_backend == "supabase":
            store = self._supabase_store
        elif self._store_backend == "chroma":
            store = self._chroma_store

        if store is None or not hasattr(store, "health_check"):
            return {"status": "unknown", "backend": self._store_backend, "latency_ms": 0.0}

        return await store.health_check()

    def cache_stats(self) -> dict[str, Any]:
        """Return embedding cache statistics (or empty dict if disabled)."""
        if self._cache is None:
            return {"enabled": False}
        return {"enabled": True, **self._cache.stats()}

    def __repr__(self) -> str:
        return (
            f"EmbeddingPipeline(model={self.config.model!r}, "
            f"backend={self._store_backend!r}, "
            f"documents={self._total_documents}, chunks={self._total_chunks})"
        )
