"""Horizon Orchestra — Embeddings Service.

Unified embedding pipeline with model management, in-memory, PostgreSQL,
Pinecone, and Supabase vector storage, configurable text chunking,
embedding caching, and end-to-end ingest/search.

Quick start::

    from orchestra.embeddings import EmbeddingPipeline, PipelineConfig

    pipeline = EmbeddingPipeline()
    ids = await pipeline.ingest("Long document text...", source="readme.md")
    results = await pipeline.semantic_search("What is the API?", top_k=5)

Components:

- **models** — Embedding model registry and async client
- **index** — In-memory vector index (brute-force + HNSW)
- **pgvector** — PostgreSQL pgvector integration
- **pinecone** — Pinecone serverless/pod index adapter
- **supabase** — Supabase PostgreSQL + pgvector adapter
- **cache** — Embedding result cache (LRU + SQLite persistence)
- **chunker** — Text chunking strategies
- **pipeline** — End-to-end ingest → chunk → embed → search
"""

from .cache import EmbeddingCache, CachedEntry
from .chunker import Chunk, ChunkStrategy, TextChunker
from .index import (
    DistanceMetric,
    SearchResult as IndexSearchResult,
    VectorIndex,
)
from .models import EMBEDDING_MODELS, EmbeddingClient, EmbeddingModel
from .pgvector import (
    PGDistanceMetric,
    PGIndexType,
    PGVectorStore,
    SearchResult as PGSearchResult,
)
from .pipeline import (
    EmbeddingPipeline,
    IngestResult,
    PipelineConfig,
    SearchResult,
)

try:
    from .pinecone import PineconeMetric, PineconeStore, PineconeCloud, PineconeRegion
    _HAS_PINECONE = True
except ImportError:
    PineconeStore = None  # type: ignore[assignment]
    PineconeMetric = None  # type: ignore[assignment]
    PineconeCloud = None  # type: ignore[assignment]
    PineconeRegion = None  # type: ignore[assignment]
    _HAS_PINECONE = False

try:
    from .supabase import SupabaseVectorStore, SupabaseDistanceMetric
    _HAS_SUPABASE = True
except ImportError:
    SupabaseVectorStore = None  # type: ignore[assignment]
    SupabaseDistanceMetric = None  # type: ignore[assignment]
    _HAS_SUPABASE = False

__all__ = [
    # models
    "EmbeddingModel",
    "EMBEDDING_MODELS",
    "EmbeddingClient",
    # index
    "VectorIndex",
    "IndexSearchResult",
    "DistanceMetric",
    # pgvector
    "PGVectorStore",
    "PGDistanceMetric",
    "PGIndexType",
    "PGSearchResult",
    # pinecone
    "PineconeStore",
    "PineconeMetric",
    "PineconeCloud",
    "PineconeRegion",
    # supabase
    "SupabaseVectorStore",
    "SupabaseDistanceMetric",
    # cache
    "EmbeddingCache",
    "CachedEntry",
    # chunker
    "Chunk",
    "ChunkStrategy",
    "TextChunker",
    # pipeline
    "EmbeddingPipeline",
    "PipelineConfig",
    "IngestResult",
    "SearchResult",
]
