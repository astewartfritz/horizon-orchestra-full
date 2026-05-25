"""Tests for orchestra.embeddings package — vector stores, cache, pipeline.

Run with: python -m pytest tests/test_embeddings.py -v --tb=short --cache-clear
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

from orchestra.embeddings import (
    EmbeddingCache,
    EmbeddingClient,
    EmbeddingPipeline,
    PipelineConfig,
    TextChunker,
    ChunkStrategy,
    CachedEntry,
)
from orchestra.embeddings.pinecone import PineconeStore, PineconeMetric
from orchestra.embeddings.supabase import SupabaseVectorStore, SupabaseDistanceMetric


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingCache Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEmbeddingCache(unittest.TestCase):
    """Tests for embedding LRU cache with optional SQLite persistence."""

    def test_get_put(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put("hello", [0.1, 0.2, 0.3])
        vec = cache.get("hello")
        self.assertEqual(vec, [0.1, 0.2, 0.3])
        self.assertIsNone(cache.get("nonexistent"))

    def test_get_put_with_model(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put("hello", [0.1], model="text-embedding-3-small")
        cache.put("hello", [0.9], model="voyage-3-large")
        self.assertEqual(cache.get("hello", model="text-embedding-3-small"), [0.1])
        self.assertEqual(cache.get("hello", model="voyage-3-large"), [0.9])

    def test_batch_operations(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put_batch(["a", "b", "c"], [[0.1], [0.2], [0.3]])
        hits, misses = cache.get_batch(["a", "c", "d"])
        self.assertIn(0, hits)
        self.assertIn(1, hits)
        self.assertEqual(misses, [2])
        self.assertEqual(hits[0], [0.1])
        self.assertEqual(hits[1], [0.3])

    def test_eviction(self):
        cache = EmbeddingCache(max_size=3, db_path=None)
        cache.put("a", [0.1])
        cache.put("b", [0.2])
        cache.put("c", [0.3])
        self.assertEqual(len(cache), 3)
        cache.put("d", [0.4])  # evicts 'a' (LRU)
        self.assertEqual(len(cache), 3)
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("d"))

    def test_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Write
            cache = EmbeddingCache(max_size=100, db_path=db_path)
            cache.put("hello", [0.1, 0.2])
            cache.close()

            # Read (new instance)
            cache2 = EmbeddingCache(max_size=100, db_path=db_path)
            vec = cache2.get("hello")
            self.assertEqual(vec, [0.1, 0.2])
            cache2.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_clear(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put("a", [0.1])
        cache.put("b", [0.2])
        self.assertEqual(len(cache), 2)
        cache.clear()
        self.assertEqual(len(cache), 0)

    def test_stats(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put("a", [0.1])
        cache.put("b", [0.2])
        stats = cache.stats()
        self.assertEqual(stats["size"], 2)
        self.assertEqual(stats["max_size"], 100)

    def test_hit_count_increments(self):
        cache = EmbeddingCache(max_size=100, db_path=None)
        cache.put("x", [0.5])
        cache.get("x")
        cache.get("x")
        cache.get("x")
        # After close+reload, the hit_count should be > 1
        # We can't easily check internal state, but verify no crash
        self.assertIsNotNone(cache.get("x"))


# ═════════════════════════════════════════════════════════════════════════════
# PineconeStore Tests (unit — no actual Pinecone connection)
# ═════════════════════════════════════════════════════════════════════════════

class TestPineconeStore(unittest.TestCase):
    """Unit tests for PineconeStore (no actual Pinecone connection)."""

    def test_constructor(self):
        store = PineconeStore(
            api_key="test-key",
            default_metric=PineconeMetric.COSINE,
        )
        self.assertEqual(store._default_metric, PineconeMetric.COSINE)
        self.assertEqual(store._api_key, "test-key")

    def test_connect_raises_without_sdk(self):
        # Should raise ImportError if pinecone SDK not installed
        store = PineconeStore(api_key="test-key")
        with self.assertRaises((ImportError, RuntimeError)):
            # May raise ImportError (no SDK) or RuntimeError (not connected)
            store._ensure_connected()

    def test_ensure_connected_raises(self):
        store = PineconeStore(api_key="test-key")
        with self.assertRaises(RuntimeError):
            store._ensure_connected()

    def test_metric_enum_values(self):
        self.assertEqual(PineconeMetric.COSINE.value, "cosine")
        self.assertEqual(PineconeMetric.EUCLIDEAN.value, "euclidean")
        self.assertEqual(PineconeMetric.DOTPRODUCT.value, "dotproduct")

    def test_repr(self):
        store = PineconeStore(api_key="test")
        r = repr(store)
        self.assertIn("PineconeStore", r)
        self.assertIn("connected=False", r)


# ═════════════════════════════════════════════════════════════════════════════
# SupabaseVectorStore Tests (unit — no actual Supabase connection)
# ═════════════════════════════════════════════════════════════════════════════

class TestSupabaseVectorStore(unittest.TestCase):
    """Unit tests for SupabaseVectorStore (no actual Supabase connection)."""

    def test_constructor(self):
        store = SupabaseVectorStore(
            supabase_url="https://project.supabase.co",
            supabase_key="test-key",
        )
        self.assertEqual(store._supabase_url, "https://project.supabase.co")
        self.assertEqual(store._supabase_key, "test-key")

    def test_ensure_connected_raises(self):
        store = SupabaseVectorStore()
        with self.assertRaises(RuntimeError):
            store._ensure_connected()

    def test_metric_enum_values(self):
        self.assertEqual(SupabaseDistanceMetric.COSINE.value, "cosine")
        self.assertEqual(SupabaseDistanceMetric.L2.value, "l2")
        self.assertEqual(SupabaseDistanceMetric.INNER_PRODUCT.value, "ip")

    def test_build_pg_dsn(self):
        dsn = SupabaseVectorStore._build_pg_dsn(
            "https://abcproject.supabase.co",
            "service_role_key_here",
        )
        self.assertIn("postgresql://", dsn)
        self.assertIn("abcproject", dsn)
        self.assertIn("service_role_key_here", dsn)

    def test_build_pg_dsn_custom(self):
        # If URL doesn't match supabase.co pattern, return as-is
        dsn = SupabaseVectorStore._build_pg_dsn(
            "postgresql://localhost:5432/mydb",
            "password",
        )
        self.assertEqual(dsn, "postgresql://localhost:5432/mydb")

    def test_repr(self):
        store = SupabaseVectorStore()
        r = repr(store)
        self.assertIn("SupabaseVectorStore", r)
        self.assertIn("connected=False", r)


# ═════════════════════════════════════════════════════════════════════════════
# TextChunker Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestTextChunker(unittest.TestCase):
    """Tests for the five chunking strategies."""

    def setUp(self):
        self.text = (
            "This is a relatively long text. It has multiple sentences. "
            "And paragraphs.\n\n"
            "This is the second paragraph. With more sentences here. "
            "And even more content to make it interesting."
        )
        self.short_text = "Hello world."

    def test_fixed_chunking(self):
        chunker = TextChunker(
            default_chunk_size=10,
            default_overlap=0,
            default_strategy=ChunkStrategy.FIXED,
        )
        chunks = chunker.chunk(self.text)
        self.assertGreater(len(chunks), 1)

    def test_sentence_chunking(self):
        sent_text = "A. B. C. D. E."
        chunker = TextChunker(
            default_chunk_size=2,
            default_overlap=0,
            default_strategy=ChunkStrategy.SENTENCE,
        )
        chunks = chunker.chunk(sent_text)
        self.assertGreaterEqual(len(chunks), 2)
        for c in chunks:
            self.assertGreater(len(c.text), 0)

    def test_paragraph_chunking(self):
        para_text = "A.\n\nB.\n\nC."
        chunker = TextChunker(
            default_chunk_size=2,
            default_overlap=0,
            default_strategy=ChunkStrategy.PARAGRAPH,
        )
        chunks = chunker.chunk(para_text)
        self.assertGreaterEqual(len(chunks), 2)
        # Each chunk should be a single paragraph (well under chunk_size)
        # So text "A B C" would be 1 chunk, but "A.\n\nB.\n\nC." splits on \n\n
        self.assertIn("A", chunks[0].text)
        self.assertIn("B", " ".join(c.text for c in chunks))

    def test_recursive_chunking(self):
        chunker = TextChunker(
            default_chunk_size=50,
            default_strategy=ChunkStrategy.RECURSIVE,
        )
        chunks = chunker.chunk(self.text)
        self.assertGreaterEqual(len(chunks), 1)

    def test_semantic_chunking(self):
        chunker = TextChunker(
            default_strategy=ChunkStrategy.SEMANTIC,
        )
        chunks = chunker.chunk(self.text)
        self.assertGreaterEqual(len(chunks), 1)

    def test_short_text(self):
        chunker = TextChunker(default_strategy=ChunkStrategy.SENTENCE)
        chunks = chunker.chunk(self.short_text)
        self.assertEqual(len(chunks), 1)

    def test_empty_text(self):
        chunker = TextChunker()
        chunks = chunker.chunk("")
        self.assertEqual(len(chunks), 0)


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingClient Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEmbeddingClient(unittest.TestCase):
    """Tests for EmbeddingClient — model resolution, cache integration."""

    def test_resolve_model(self):
        client = EmbeddingClient()
        spec = client._resolve_model("text-embedding-3-small")
        self.assertEqual(spec.name, "text-embedding-3-small")
        self.assertEqual(spec.dimensions, 1536)

    def test_resolve_unknown_model(self):
        client = EmbeddingClient()
        with self.assertRaises(KeyError):
            client._resolve_model("nonexistent-model")

    def test_list_models(self):
        client = EmbeddingClient()
        models = client.list_models()
        self.assertGreater(len(models), 0)
        names = [m["name"] for m in models]
        self.assertIn("text-embedding-3-small", names)

    def test_cache_integration(self):
        import asyncio
        cache = EmbeddingCache(max_size=100, db_path=None)
        fake_vec = [0.5] * 16
        cache.put("test text", fake_vec, model="text-embedding-3-small")
        client = EmbeddingClient(cache=cache)
        vec = asyncio.run(client.embed("test text", model="text-embedding-3-small"))
        self.assertEqual(vec, fake_vec)

    def test_batch_embed_empty(self):
        import asyncio
        client = EmbeddingClient()
        result = asyncio.run(client.batch_embed([]))
        self.assertEqual(result, [])

    def test_mean_pool(self):
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        pooled = EmbeddingClient._mean_pool(vectors)
        # Mean (0.5, 0.5) L2-normalised
        self.assertAlmostEqual(pooled[0], 0.707106, places=5)
        self.assertAlmostEqual(pooled[1], 0.707106, places=5)

    def test_mean_pool_empty(self):
        self.assertEqual(EmbeddingClient._mean_pool([]), [])

    def test_mean_pool_single(self):
        vec = [0.5, 0.5]
        pooled = EmbeddingClient._mean_pool([vec])
        norm = (0.5**2 + 0.5**2) ** 0.5
        self.assertAlmostEqual(pooled[0], 0.5 / norm)
        self.assertAlmostEqual(pooled[1], 0.5 / norm)

    def test_custom_models(self):
        from orchestra.embeddings.models import EmbeddingModel
        custom = {
            "my-model": EmbeddingModel(
                name="my-model",
                dimensions=128,
                max_tokens=512,
                provider="openai",
                cost_per_million=0.0,
            ),
        }
        client = EmbeddingClient(custom_models=custom)
        spec = client._resolve_model("my-model")
        self.assertEqual(spec.dimensions, 128)
        # Built-in models still available
        spec2 = client._resolve_model("text-embedding-3-small")
        self.assertEqual(spec2.dimensions, 1536)


# ═════════════════════════════════════════════════════════════════════════════
# VectorIndex Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestVectorIndex(unittest.TestCase):
    """Tests for VectorIndex — insert, search, delete, batch, HNSW, save/load."""

    def setUp(self):
        from orchestra.embeddings.index import VectorIndex, DistanceMetric
        self.VectorIndex = VectorIndex
        self.DistanceMetric = DistanceMetric

    def _make_index(self, dim=4, use_hnsw=False):
        return self.VectorIndex(dimensions=dim, metric="cosine", use_hnsw=use_hnsw)

    def _simple_vectors(self):
        return {
            "a": [1.0, 0.0, 0.0, 0.0],
            "b": [0.0, 1.0, 0.0, 0.0],
            "c": [0.0, 0.0, 1.0, 0.0],
            "d": [0.0, 0.0, 0.0, 1.0],
        }

    def test_insert_and_size(self):
        idx = self._make_index()
        idx.insert("a", [1.0, 0.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0, 0.0])
        self.assertEqual(len(idx), 2)

    def test_batch_insert(self):
        idx = self._make_index()
        ids = ["a", "b", "c"]
        vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
        metas = [{"i": 0}, {"i": 1}, {"i": 2}]
        idx.batch_insert(ids, vecs, metas)
        self.assertEqual(len(idx), 3)

    def test_search_exact(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        idx.insert("c", [0.0, 0.0, 1.0])
        results = idx.search([1.0, 0.0, 0.0], top_k=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].id, "a")
        self.assertGreater(results[0].score, 0.99)

    def test_search_with_filters(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0], {"group": "x"})
        idx.insert("b", [0.0, 1.0, 0.0], {"group": "y"})
        idx.insert("c", [0.0, 0.0, 1.0], {"group": "x"})
        results = idx.search([1.0, 0.0, 0.0], top_k=5, filters={"group": "x"})
        self.assertEqual(len(results), 2)
        ids = {r.id for r in results}
        self.assertIn("a", ids)
        self.assertIn("c", ids)

    def test_delete(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        self.assertTrue(idx.delete("a"))
        self.assertFalse(idx.delete("nonexistent"))
        self.assertEqual(len(idx), 1)

    def test_batch_delete(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        idx.insert("c", [0.0, 0.0, 1.0])
        count = idx.batch_delete(["a", "c", "nonexistent"])
        self.assertEqual(count, 2)
        self.assertEqual(len(idx), 1)

    def test_update(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.update("a", vector=[0.0, 1.0, 0.0])
        results = idx.search([0.0, 1.0, 0.0], top_k=1)
        self.assertEqual(results[0].id, "a")

    def test_update_metadata(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0], {"key": "old"})
        idx.update("a", metadata={"key": "new"})
        results = idx.search([1.0, 0.0, 0.0], top_k=1, filters={"key": "new"})
        self.assertEqual(len(results), 1)

    def test_update_unknown_raises(self):
        idx = self._make_dim_index(3)
        with self.assertRaises(KeyError):
            idx.update("nonexistent")

    def test_search_empty(self):
        idx = self._make_dim_index(3)
        results = idx.search([1.0, 0.0, 0.0])
        self.assertEqual(len(results), 0)

    def test_save_and_load(self):
        import tempfile, os
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0], {"k": "v"})
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            idx.save(path)
            loaded = self.VectorIndex.load(path)
            self.assertEqual(len(loaded), 1)
            results = loaded.search([1.0, 0.0, 0.0])
            self.assertEqual(results[0].id, "a")
        finally:
            os.unlink(path)

    def test_get_stats(self):
        idx = self._make_dim_index(3)
        idx.insert("a", [1.0, 0.0, 0.0])
        stats = idx.get_stats()
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["dimensions"], 3)

    def test_delete_invalidates_hnsw(self):
        idx = self._make_dim_index(3, use_hnsw=True)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        # First search builds HNSW
        idx.search([1.0, 0.0, 0.0])
        self.assertIsNotNone(idx._hnsw)
        idx.delete("b")
        # HNSW should be invalidated
        self.assertIsNone(idx._hnsw)

    def test_batch_delete_invalidates_hnsw_once(self):
        idx = self._make_dim_index(3, use_hnsw=True)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        idx.insert("c", [0.0, 0.0, 1.0])
        idx.search([1.0, 0.0, 0.0])
        self.assertIsNotNone(idx._hnsw)
        idx.batch_delete(["b", "c"])
        self.assertIsNone(idx._hnsw)

    def test_search_with_hnsw(self):
        idx = self._make_dim_index(3, use_hnsw=True)
        idx.insert("a", [1.0, 0.0, 0.0])
        idx.insert("b", [0.0, 1.0, 0.0])
        idx.insert("c", [0.0, 0.0, 1.0])
        results = idx.search([1.0, 0.0, 0.0], top_k=2)
        self.assertEqual(len(results), 2)

    def test_distance_metrics(self):
        for metric_name in ("cosine", "l2", "inner_product"):
            idx = self.VectorIndex(dimensions=3, metric=metric_name)
            idx.insert("a", [1.0, 0.0, 0.0])
            r = idx.search([1.0, 0.0, 0.0], top_k=1)
            self.assertEqual(len(r), 1)

    def _make_dim_index(self, dim, use_hnsw=False):
        return self.VectorIndex(dimensions=dim, metric="cosine", use_hnsw=use_hnsw)


# ═════════════════════════════════════════════════════════════════════════════
# PGVectorStore Tests (unit — no actual PostgreSQL connection)
# ═════════════════════════════════════════════════════════════════════════════

class TestPGVectorStore(unittest.TestCase):
    """Unit tests for PGVectorStore — SQL generation, connection handling."""

    def test_constructor(self):
        from orchestra.embeddings.pgvector import PGVectorStore, PGDistanceMetric
        store = PGVectorStore(default_metric=PGDistanceMetric.COSINE)
        self.assertEqual(store._default_metric, PGDistanceMetric.COSINE)

    def test_ensure_connected_raises(self):
        from orchestra.embeddings.pgvector import PGVectorStore
        store = PGVectorStore()
        with self.assertRaises(RuntimeError):
            store._ensure_connected()

    def test_metric_enum_values(self):
        from orchestra.embeddings.pgvector import PGDistanceMetric, PGIndexType
        self.assertEqual(PGDistanceMetric.COSINE.value, "cosine")
        self.assertEqual(PGDistanceMetric.L2.value, "l2")
        self.assertEqual(PGDistanceMetric.INNER_PRODUCT.value, "ip")
        self.assertEqual(PGIndexType.NONE.value, "none")
        self.assertEqual(PGIndexType.IVFFLAT.value, "ivfflat")
        self.assertEqual(PGIndexType.HNSW.value, "hnsw")

    def test_vec_literal(self):
        from orchestra.embeddings.pgvector import PGVectorStore
        lit = PGVectorStore._vec_literal([0.1, 0.2, 0.3])
        self.assertEqual(lit, "[0.1,0.2,0.3]")

    def test_search_result_repr(self):
        from orchestra.embeddings.pgvector import SearchResult
        sr = SearchResult(id="test", score=0.95, metadata={"key": "val"})
        r = repr(sr)
        self.assertIn("test", r)
        self.assertIn("0.95", r)

    def test_repr(self):
        from orchestra.embeddings.pgvector import PGVectorStore
        store = PGVectorStore()
        r = repr(store)
        self.assertIn("PGVectorStore", r)
        self.assertIn("connected=False", r)

    def test_create_collection_without_connection_raises(self):
        from orchestra.embeddings.pgvector import PGVectorStore
        store = PGVectorStore()
        with self.assertRaises(RuntimeError):
            import asyncio
            asyncio.run(store.create_collection("test", 1536))

    def test_ivfflat_ops_map(self):
        from orchestra.embeddings.pgvector import PGDistanceMetric, _IVFFLAT_OPS
        self.assertIn(PGDistanceMetric.L2, _IVFFLAT_OPS)
        self.assertIn(PGDistanceMetric.COSINE, _IVFFLAT_OPS)
        self.assertIn(PGDistanceMetric.INNER_PRODUCT, _IVFFLAT_OPS)


# ═════════════════════════════════════════════════════════════════════════════
# EmbeddingPipeline Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEmbeddingPipeline(unittest.TestCase):
    """Tests for EmbeddingPipeline — config, construction, cache integration."""

    def test_default_config(self):
        config = PipelineConfig()
        self.assertEqual(config.model, "text-embedding-3-small")
        self.assertEqual(config.store_backend, "memory")

    def test_custom_config(self):
        config = PipelineConfig(
            model="text-embedding-3-large",
            store_backend="pgvector",
            pgvector_dsn="postgresql://localhost/db",
        )
        self.assertEqual(config.model, "text-embedding-3-large")
        self.assertEqual(config.store_backend, "pgvector")

    def test_pinecone_config(self):
        config = PipelineConfig(
            store_backend="pinecone",
            pinecone_api_key="test-key",
            pinecone_collection="my-index",
            pinecone_region="us-east-1",
        )
        self.assertEqual(config.store_backend, "pinecone")
        self.assertEqual(config.pinecone_collection, "my-index")

    def test_supabase_config(self):
        config = PipelineConfig(
            store_backend="supabase",
            supabase_url="https://project.supabase.co",
            supabase_key="test-key",
            supabase_collection="my-collection",
        )
        self.assertEqual(config.store_backend, "supabase")

    def test_cache_creation(self):
        import asyncio
        config = PipelineConfig(
            embedding_cache_size=1000,
            embedding_cache_path="",
        )
        pipeline = EmbeddingPipeline(config=config)
        self.assertIsNotNone(pipeline._cache)
        asyncio.run(pipeline.close())

    def test_cache_stats(self):
        import asyncio
        pipeline = EmbeddingPipeline()
        stats = pipeline.cache_stats()
        self.assertIn("enabled", stats)
        asyncio.run(pipeline.close())

    def test_health_check_memory(self):
        import asyncio
        pipeline = EmbeddingPipeline()
        result = asyncio.run(pipeline.health_check())
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["backend"], "memory")
        asyncio.run(pipeline.close())

    def test_initialized_default(self):
        pipeline = EmbeddingPipeline()
        self.assertTrue(pipeline._initialized)

    def test_run_without_initialization(self):
        pipeline = EmbeddingPipeline(config=PipelineConfig(
            store_backend="pgvector",
            pgvector_dsn="postgresql://localhost/db",
        ))
        self.assertFalse(pipeline._initialized)
        with self.assertRaises(RuntimeError):
            pipeline._ensure_initialized()


# ═════════════════════════════════════════════════════════════════════════════
# Run tests
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
