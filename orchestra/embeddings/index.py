"""Horizon Orchestra — In-Memory Vector Index.

Provides brute-force exact search and an optional HNSW-like approximate
nearest-neighbour index.  Supports cosine similarity, L2 (Euclidean)
distance, and inner-product metrics.

Persistence is handled via pickle + optional numpy serialization.
"""

from __future__ import annotations

import heapq
import logging
import math
import os
import pickle
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Sequence

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

__all__ = [
    "SearchResult",
    "DistanceMetric",
    "VectorIndex",
]

log = logging.getLogger("orchestra.embeddings.index")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Single search hit from the vector index."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


class DistanceMetric(str, Enum):
    """Supported distance / similarity metrics."""

    COSINE = "cosine"
    L2 = "l2"
    INNER_PRODUCT = "inner_product"


# ---------------------------------------------------------------------------
# Pure-Python vector math helpers
# ---------------------------------------------------------------------------

def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Inner product of two equal-length vectors."""
    return sum(x * y for x, y in zip(a, b))


def _norm(a: Sequence[float]) -> float:
    """L2 norm."""
    return math.sqrt(sum(x * x for x in a))


def _l2_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [−1, 1]."""
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _inner_product(a: Sequence[float], b: Sequence[float]) -> float:
    """Raw inner product (higher is more similar)."""
    return _dot(a, b)


# ---------------------------------------------------------------------------
# NumPy-accelerated helpers (when available)
# ---------------------------------------------------------------------------

def _np_cosine_scores(
    query: Any,  # np.ndarray (D,)
    matrix: Any,  # np.ndarray (N, D)
) -> Any:
    """Batch cosine similarity using numpy — returns (N,) array of scores."""
    norms = np.linalg.norm(matrix, axis=1)
    q_norm = np.linalg.norm(query)
    safe = norms * q_norm
    safe = np.where(safe == 0, 1.0, safe)
    return matrix @ query / safe


def _np_l2_scores(query: Any, matrix: Any) -> Any:
    """Batch L2 distances (negated so higher = closer)."""
    diff = matrix - query[np.newaxis, :]
    dists = np.linalg.norm(diff, axis=1)
    return -dists  # negate so that heapq (max by score) works


def _np_ip_scores(query: Any, matrix: Any) -> Any:
    """Batch inner-product scores."""
    return matrix @ query


# ---------------------------------------------------------------------------
# HNSW-like layer (simplified)
# ---------------------------------------------------------------------------

@dataclass
class _HNSWNode:
    """Node in the HNSW graph."""

    idx: int
    connections: list[list[int]] = field(default_factory=list)  # per level


class _HNSWGraph:
    """Simplified Hierarchical Navigable Small World graph.

    This is a pedagogical implementation good for up to ~100 k vectors.
    For production workloads prefer a C++ library (hnswlib, faiss).
    """

    def __init__(
        self,
        dim: int,
        m: int = 16,
        ef_construction: int = 200,
        ef_search: int = 50,
        ml: float = 1.0 / math.log(2.0),
        metric: DistanceMetric = DistanceMetric.COSINE,
    ) -> None:
        self.dim = dim
        self.m = m
        self.m_max0 = m * 2
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.ml = ml
        self.metric = metric
        self.nodes: list[_HNSWNode] = []
        self.vectors: list[list[float]] = []
        self.entry_point: int | None = None
        self.max_level: int = -1

    def _random_level(self) -> int:
        return int(-math.log(random.random()) * self.ml)

    def _distance(self, a: Sequence[float], b: Sequence[float]) -> float:
        """Return distance (lower = closer)."""
        if self.metric == DistanceMetric.COSINE:
            return 1.0 - _cosine_similarity(a, b)
        elif self.metric == DistanceMetric.L2:
            return _l2_distance(a, b)
        else:  # inner_product — negate so lower = more similar
            return -_inner_product(a, b)

    def _search_layer(
        self,
        query: Sequence[float],
        entry: int,
        ef: int,
        level: int,
    ) -> list[tuple[float, int]]:
        """Greedy BFS on a single HNSW layer, returning up to *ef* neighbours."""
        visited: set[int] = {entry}
        d_entry = self._distance(query, self.vectors[entry])
        candidates: list[tuple[float, int]] = [(d_entry, entry)]
        results: list[tuple[float, int]] = [(-d_entry, entry)]  # max-heap (neg dist)

        while candidates:
            dist_c, c = heapq.heappop(candidates)
            worst_result = -results[0][0]
            if dist_c > worst_result:
                break
            node = self.nodes[c]
            if level < len(node.connections):
                for neighbour in node.connections[level]:
                    if neighbour in visited:
                        continue
                    visited.add(neighbour)
                    d_n = self._distance(query, self.vectors[neighbour])
                    worst_result = -results[0][0]
                    if d_n < worst_result or len(results) < ef:
                        heapq.heappush(candidates, (d_n, neighbour))
                        heapq.heappush(results, (-d_n, neighbour))
                        if len(results) > ef:
                            heapq.heappop(results)

        return [(abs(neg_d), idx) for neg_d, idx in results]

    def insert(self, vector: list[float]) -> int:
        """Insert a vector and return its index."""
        idx = len(self.nodes)
        level = self._random_level()
        node = _HNSWNode(idx=idx)
        for _ in range(level + 1):
            node.connections.append([])
        self.nodes.append(node)
        self.vectors.append(vector)

        if self.entry_point is None:
            self.entry_point = idx
            self.max_level = level
            return idx

        # Traverse from top level down to level+1
        ep = self.entry_point
        for lev in range(self.max_level, level, -1):
            results = self._search_layer(vector, ep, 1, lev)
            ep = min(results, key=lambda x: x[0])[1]

        # Insert into layers [min(level, max_level) .. 0]
        for lev in range(min(level, self.max_level), -1, -1):
            results = self._search_layer(vector, ep, self.ef_construction, lev)
            m_max = self.m_max0 if lev == 0 else self.m
            # Select m closest
            results.sort(key=lambda x: x[0])
            neighbours = [r[1] for r in results[:m_max]]
            node.connections[lev] = neighbours
            # Add back-links
            for n_idx in neighbours:
                n_node = self.nodes[n_idx]
                if lev < len(n_node.connections):
                    n_node.connections[lev].append(idx)
                    if len(n_node.connections[lev]) > m_max:
                        # Prune: keep only m_max closest
                        dists = [
                            (self._distance(self.vectors[n_idx], self.vectors[c]), c)
                            for c in n_node.connections[lev]
                        ]
                        dists.sort(key=lambda x: x[0])
                        n_node.connections[lev] = [c for _, c in dists[:m_max]]
            if results:
                ep = results[0][1]

        if level > self.max_level:
            self.max_level = level
            self.entry_point = idx

        return idx

    def search(
        self,
        query: Sequence[float],
        top_k: int = 10,
    ) -> list[tuple[float, int]]:
        """Return up to *top_k* nearest neighbours as ``(distance, index)``."""
        if self.entry_point is None:
            return []

        ep = self.entry_point
        for lev in range(self.max_level, 0, -1):
            results = self._search_layer(query, ep, 1, lev)
            ep = min(results, key=lambda x: x[0])[1]

        results = self._search_layer(query, ep, max(self.ef_search, top_k), 0)
        results.sort(key=lambda x: x[0])
        return results[:top_k]


# ---------------------------------------------------------------------------
# Vector index (main public class)
# ---------------------------------------------------------------------------

class VectorIndex:
    """In-memory vector index with brute-force and optional HNSW search.

    Usage::

        idx = VectorIndex(dimensions=1536, metric="cosine")
        idx.insert("doc-1", [0.1, 0.2, ...], {"title": "Hello"})
        results = idx.search(query_vector, top_k=5)
    """

    def __init__(
        self,
        dimensions: int = 1536,
        metric: DistanceMetric | str = DistanceMetric.COSINE,
        *,
        use_hnsw: bool = False,
        hnsw_m: int = 16,
        hnsw_ef_construction: int = 200,
        hnsw_ef_search: int = 50,
    ) -> None:
        if isinstance(metric, str):
            metric = DistanceMetric(metric)
        self.dimensions = dimensions
        self.metric = metric
        self.use_hnsw = use_hnsw

        # Core storage
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []
        self._metadata: list[dict[str, Any]] = []
        self._id_to_idx: dict[str, int] = {}

        # NumPy matrix cache (invalidated on mutation)
        self._np_matrix: Any = None  # Optional[np.ndarray]
        self._np_dirty: bool = True

        # HNSW graph (optional)
        self._hnsw: _HNSWGraph | None = None
        if use_hnsw:
            self._hnsw = _HNSWGraph(
                dim=dimensions,
                m=hnsw_m,
                ef_construction=hnsw_ef_construction,
                ef_search=hnsw_ef_search,
                metric=metric,
            )

    # -- mutation -----------------------------------------------------------

    def insert(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert a single vector into the index.

        Parameters
        ----------
        id:
            Unique identifier for the vector.
        vector:
            The embedding vector.  Must match *self.dimensions*.
        metadata:
            Optional key-value metadata attached to this vector.
        """
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Vector dimension mismatch: expected {self.dimensions}, got {len(vector)}"
            )
        if id in self._id_to_idx:
            raise ValueError(f"Duplicate id: {id!r} — use update() to replace")

        idx = len(self._ids)
        self._ids.append(id)
        self._vectors.append(vector)
        self._metadata.append(metadata or {})
        self._id_to_idx[id] = idx
        self._np_dirty = True

        if self._hnsw is not None:
            self._hnsw.insert(vector)

    def batch_insert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert multiple vectors in one call.

        Parameters
        ----------
        ids:
            List of unique identifiers.
        vectors:
            List of embedding vectors.
        metadatas:
            Optional per-vector metadata dicts.
        """
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if len(ids) != len(vectors) or len(ids) != len(metadatas):
            raise ValueError("ids, vectors, and metadatas must have the same length")
        for id_, vec, meta in zip(ids, vectors, metadatas):
            self.insert(id_, vec, meta)

    def delete(self, id: str) -> bool:
        """Remove a vector by id.  Returns True if found and removed.

        HNSW graph is invalidated lazily — rebuilt on the next search
        that requests HNSW.  Brute-force deletion is immediate O(1).
        """
        idx = self._id_to_idx.get(id)
        if idx is None:
            return False

        last_idx = len(self._ids) - 1
        if idx != last_idx:
            last_id = self._ids[last_idx]
            self._ids[idx] = last_id
            self._vectors[idx] = self._vectors[last_idx]
            self._metadata[idx] = self._metadata[last_idx]
            self._id_to_idx[last_id] = idx

        self._ids.pop()
        self._vectors.pop()
        self._metadata.pop()
        del self._id_to_idx[id]
        self._np_dirty = True
        self._invalidate_hnsw()

        return True

    def batch_delete(self, ids: list[str]) -> int:
        """Delete multiple vectors by id.  Returns count of deletions.

        Invalidates HNSW only once (after all deletions), avoiding
        repeated rebuilds.
        """
        count = 0
        for id_ in ids:
            idx = self._id_to_idx.get(id_)
            if idx is None:
                continue
            last_idx = len(self._ids) - 1
            if idx != last_idx:
                last_id = self._ids[last_idx]
                self._ids[idx] = last_id
                self._vectors[idx] = self._vectors[last_idx]
                self._metadata[idx] = self._metadata[last_idx]
                self._id_to_idx[last_id] = idx
            self._ids.pop()
            self._vectors.pop()
            self._metadata.pop()
            del self._id_to_idx[id_]
            count += 1

        if count > 0:
            self._np_dirty = True
            self._invalidate_hnsw()
        return count

    def _invalidate_hnsw(self) -> None:
        """Mark HNSW as needing rebuild.  Calls set ``_hnsw = None``."""
        if self._hnsw is not None:
            log.debug("HNSW graph invalidated — will rebuild on next search")
            self._hnsw = None

    def update(
        self,
        id: str,
        vector: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update a vector and/or its metadata in-place.

        Parameters
        ----------
        id:
            The vector's unique identifier (must exist).
        vector:
            New embedding vector (optional).
        metadata:
            New metadata dict (optional; replaces entire dict).
        """
        idx = self._id_to_idx.get(id)
        if idx is None:
            raise KeyError(f"Unknown id: {id!r}")

        if vector is not None:
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Vector dimension mismatch: expected {self.dimensions}, got {len(vector)}"
                )
            self._vectors[idx] = vector
            self._np_dirty = True
            if self._hnsw is not None:
                self._hnsw = None  # invalidate

        if metadata is not None:
            self._metadata[idx] = metadata

    # -- search -------------------------------------------------------------

    def _build_np_matrix(self) -> None:
        """Rebuild the numpy matrix cache."""
        if not _HAS_NUMPY or not self._vectors:
            return
        self._np_matrix = np.array(self._vectors, dtype=np.float32)
        self._np_dirty = False

    def _apply_filters(
        self,
        indices: Sequence[int],
        filters: dict[str, Any] | None,
    ) -> list[int]:
        """Filter indices by metadata key-value equality."""
        if not filters:
            return list(indices)
        out: list[int] = []
        for idx in indices:
            meta = self._metadata[idx]
            match = all(meta.get(k) == v for k, v in filters.items())
            if match:
                out.append(idx)
        return out

    def _brute_force_search(
        self,
        query_vector: list[float] | Sequence[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Exact brute-force search over all vectors."""
        if not self._vectors:
            return []

        candidate_indices = self._apply_filters(range(len(self._ids)), filters)
        if not candidate_indices:
            return []

        # Fast path: numpy batch computation
        if _HAS_NUMPY and len(candidate_indices) > 50:
            if self._np_dirty:
                self._build_np_matrix()
            if self._np_matrix is not None:
                q = np.array(query_vector, dtype=np.float32)
                subset = np.array(candidate_indices)
                matrix = self._np_matrix[subset]

                if self.metric == DistanceMetric.COSINE:
                    scores = _np_cosine_scores(q, matrix)
                elif self.metric == DistanceMetric.L2:
                    scores = _np_l2_scores(q, matrix)
                else:
                    scores = _np_ip_scores(q, matrix)

                # Get top_k indices
                if len(scores) <= top_k:
                    best = np.argsort(-scores)
                else:
                    best = np.argpartition(-scores, top_k)[:top_k]
                    best = best[np.argsort(-scores[best])]

                results: list[SearchResult] = []
                for b in best:
                    orig_idx = candidate_indices[int(b)]
                    results.append(
                        SearchResult(
                            id=self._ids[orig_idx],
                            score=float(scores[b]),
                            metadata=self._metadata[orig_idx],
                        )
                    )
                return results

        # Slow path: pure Python
        scored: list[tuple[float, int]] = []
        for idx in candidate_indices:
            vec = self._vectors[idx]
            if self.metric == DistanceMetric.COSINE:
                s = _cosine_similarity(query_vector, vec)
            elif self.metric == DistanceMetric.L2:
                s = -_l2_distance(query_vector, vec)
            else:
                s = _inner_product(query_vector, vec)
            scored.append((s, idx))

        # Use heapq for efficiency when top_k << len
        if top_k < len(scored):
            top = heapq.nlargest(top_k, scored, key=lambda x: x[0])
        else:
            top = sorted(scored, key=lambda x: x[0], reverse=True)

        return [
            SearchResult(
                id=self._ids[idx],
                score=score,
                metadata=self._metadata[idx],
            )
            for score, idx in top
        ]

    def _rebuild_hnsw(self) -> None:
        """Rebuild the HNSW graph from current vectors."""
        self._hnsw = _HNSWGraph(
            dim=self.dimensions,
            metric=self.metric,
        )
        for vec in self._vectors:
            self._hnsw.insert(vec)

    def search(
        self,
        query_vector: list[float] | Sequence[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for the closest vectors to *query_vector*.

        Parameters
        ----------
        query_vector:
            The query embedding.
        top_k:
            Maximum number of results to return.
        filters:
            Optional metadata filters (exact equality on each key).

        Returns
        -------
        list[SearchResult]
            Results ordered by descending score (higher = more similar).
        """
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query dimension mismatch: expected {self.dimensions}, got {len(query_vector)}"
            )

        # HNSW path (approximate, no filter support at graph level)
        if self.use_hnsw and filters is None:
            if self._hnsw is None:
                log.info("Rebuilding HNSW graph for %d vectors", len(self._vectors))
                self._rebuild_hnsw()
            raw = self._hnsw.search(query_vector, top_k)  # type: ignore[union-attr]
            results: list[SearchResult] = []
            for dist, idx in raw:
                # Convert distance back to a similarity score
                if self.metric == DistanceMetric.COSINE:
                    score = 1.0 - dist
                elif self.metric == DistanceMetric.L2:
                    score = -dist
                else:
                    score = -dist  # was negated in _HNSWGraph._distance
                results.append(
                    SearchResult(
                        id=self._ids[idx],
                        score=score,
                        metadata=self._metadata[idx],
                    )
                )
            return results

        # Brute-force path (exact)
        return self._brute_force_search(query_vector, top_k, filters)

    # -- persistence --------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the index to disk.

        Uses pickle for the core data and numpy's .npy format for the
        vector matrix when available.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "dimensions": self.dimensions,
            "metric": self.metric.value,
            "use_hnsw": self.use_hnsw,
            "ids": self._ids,
            "metadata": self._metadata,
        }
        if _HAS_NUMPY and self._vectors:
            mat = np.array(self._vectors, dtype=np.float32)
            np_path = path + ".npy"
            np.save(np_path, mat)
            data["vectors_file"] = os.path.basename(np_path)
        else:
            data["vectors"] = self._vectors

        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

        log.info("Saved index (%d vectors) to %s", len(self._ids), path)

    @classmethod
    def load(cls, path: str) -> "VectorIndex":
        """Load an index from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)  # noqa: S301

        idx = cls(
            dimensions=data["dimensions"],
            metric=data["metric"],
            use_hnsw=data.get("use_hnsw", False),
        )
        idx._ids = data["ids"]
        idx._metadata = data["metadata"]
        idx._id_to_idx = {id_: i for i, id_ in enumerate(idx._ids)}

        if "vectors_file" in data:
            np_path = os.path.join(os.path.dirname(path), data["vectors_file"])
            mat = np.load(np_path)
            idx._vectors = mat.tolist()
            idx._np_matrix = mat
            idx._np_dirty = False
        else:
            idx._vectors = data.get("vectors", [])

        log.info("Loaded index (%d vectors) from %s", len(idx._ids), path)
        return idx

    # -- stats --------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the index."""
        count = len(self._ids)
        # Memory estimate
        vec_bytes = count * self.dimensions * 4  # float32
        meta_bytes = sum(sys.getsizeof(m) for m in self._metadata) if count else 0
        memory_mb = (vec_bytes + meta_bytes) / (1024 * 1024)

        return {
            "count": count,
            "dimensions": self.dimensions,
            "metric": self.metric.value,
            "memory_mb": round(memory_mb, 2),
            "use_hnsw": self.use_hnsw,
            "has_numpy": _HAS_NUMPY,
        }

    def __len__(self) -> int:
        return len(self._ids)

    def __contains__(self, id: str) -> bool:
        return id in self._id_to_idx

    def __repr__(self) -> str:
        return (
            f"VectorIndex(dimensions={self.dimensions}, "
            f"count={len(self._ids)}, metric={self.metric.value!r})"
        )
