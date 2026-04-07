"""Horizon Orchestra — Embeddings Service.

Unified embedding pipeline with model management, in-memory and PostgreSQL
vector indexing, configurable text chunking, and end-to-end ingest/search.

Quick start::

    from orchestra.embeddings import EmbeddingPipeline, PipelineConfig

    pipeline = EmbeddingPipeline()
    ids = await pipeline.ingest("Long document text...", source="readme.md")
    results = await pipeline.semantic_search("What is the API?", top_k=5)

Components:

- **models** — Embedding model registry and async client
- **index** — In-memory vector index (brute-force + HNSW)
- **pgvector** — PostgreSQL pgvector integration
- **chunker** — Text chunking strategies
- **pipeline** — End-to-end ingest → chunk → embed → search
"""

from .models import EmbeddingModel, EMBEDDING_MODELS, EmbeddingClient
from .index import VectorIndex, SearchResult as IndexSearchResult, DistanceMetric
from .pgvector import PGVectorStore, PGDistanceMetric, PGIndexType
from .pgvector import SearchResult as PGSearchResult
from .chunker import Chunk, ChunkStrategy, TextChunker
from .pipeline import (
    EmbeddingPipeline,
    PipelineConfig,
    IngestResult,
    SearchResult,
)

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
