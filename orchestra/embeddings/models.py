"""Horizon Orchestra — Embedding Model Management.

Unified embedding client supporting OpenAI, Voyage AI, Nomic, and BAAI models.
Uses OpenAI-compatible clients for OpenAI models and httpx for third-party
providers, with automatic chunking and retry logic.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from openai import AsyncOpenAI

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

__all__ = [
    "EmbeddingModel",
    "EMBEDDING_MODELS",
    "EmbeddingClient",
]

log = logging.getLogger("orchestra.embeddings.models")


# ---------------------------------------------------------------------------
# Embedding model descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmbeddingModel:
    """Immutable descriptor for an embedding model."""

    name: str
    dimensions: int
    max_tokens: int
    provider: str
    cost_per_million: float
    base_url: str = ""
    api_key_env: str = ""
    is_open_source: bool = False
    description: str = ""

    @property
    def available(self) -> bool:
        """Check whether the required API key is present in the environment."""
        if not self.api_key_env:
            return True
        return bool(os.environ.get(self.api_key_env))


# ---------------------------------------------------------------------------
# Built-in embedding model catalogue
# ---------------------------------------------------------------------------

EMBEDDING_MODELS: dict[str, EmbeddingModel] = {
    # ── OpenAI models ─────────────────────────────────────────────────────
    "text-embedding-3-large": EmbeddingModel(
        name="text-embedding-3-large",
        dimensions=3072,
        max_tokens=8191,
        provider="openai",
        cost_per_million=0.13,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        description="OpenAI's most capable embedding model, 3072 dimensions.",
    ),
    "text-embedding-3-small": EmbeddingModel(
        name="text-embedding-3-small",
        dimensions=1536,
        max_tokens=8191,
        provider="openai",
        cost_per_million=0.02,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        description="OpenAI's efficient embedding model, 1536 dimensions.",
    ),
    "text-embedding-ada-002": EmbeddingModel(
        name="text-embedding-ada-002",
        dimensions=1536,
        max_tokens=8191,
        provider="openai",
        cost_per_million=0.10,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        description="OpenAI legacy embedding model (ada-002). Use v3 models instead.",
    ),

    # ── Voyage AI ─────────────────────────────────────────────────────────
    "voyage-3-large": EmbeddingModel(
        name="voyage-3-large",
        dimensions=1024,
        max_tokens=32000,
        provider="voyage",
        cost_per_million=0.18,
        base_url="https://api.voyageai.com/v1",
        api_key_env="VOYAGE_API_KEY",
        description="Voyage AI's large embedding model, 1024 dimensions.",
    ),

    # ── Nomic (open source) ───────────────────────────────────────────────
    "nomic-embed-text-v2.5": EmbeddingModel(
        name="nomic-embed-text-v2.5",
        dimensions=768,
        max_tokens=8192,
        provider="nomic",
        cost_per_million=0.0,
        base_url="https://api-atlas.nomic.ai/v1",
        api_key_env="NOMIC_API_KEY",
        is_open_source=True,
        description="Nomic open-source text embedding, 768 dimensions.",
    ),

    # ── BAAI (open source) ────────────────────────────────────────────────
    "bge-large-en-v1.5": EmbeddingModel(
        name="bge-large-en-v1.5",
        dimensions=1024,
        max_tokens=512,
        provider="baai",
        cost_per_million=0.0,
        base_url="",
        api_key_env="",
        is_open_source=True,
        description="BAAI general embedding, 1024 dimensions. Self-hosted only.",
    ),
}


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def _retry_with_backoff(
    coro_factory,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> Any:
    """Execute an async callable with exponential backoff on failure.

    *coro_factory* is a zero-argument callable that returns a new coroutine
    on each invocation — e.g. ``lambda: client.embeddings.create(...)``.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == max_retries:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            log.warning(
                "Embedding request failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"All {max_retries + 1} attempts failed") from last_exc


# ---------------------------------------------------------------------------
# Text chunking for token limits
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Cheap token estimate — 1 token ≈ 4 characters."""
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("text-embedding-3-small")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _chunk_text(text: str, max_tokens: int) -> list[str]:
    """Split *text* into segments that fit within *max_tokens*."""
    estimated = _estimate_tokens(text)
    if estimated <= max_tokens:
        return [text]

    # Approximate character budget per chunk
    chars_per_token = len(text) / estimated
    chunk_chars = int(max_tokens * chars_per_token * 0.95)  # 5 % safety margin
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        # Try to break on whitespace
        if end < len(text):
            ws_pos = text.rfind(" ", start, end)
            if ws_pos > start:
                end = ws_pos + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------

class EmbeddingClient:
    """Unified async embedding client for all supported providers.

    Uses the OpenAI Python SDK for OpenAI-compatible endpoints and falls
    back to httpx for providers that use a different wire format.

    Usage::

        client = EmbeddingClient()
        vec = await client.embed("Hello world", model="text-embedding-3-small")
        vecs = await client.batch_embed(["one", "two"], model="text-embedding-3-large")
    """

    def __init__(
        self,
        custom_models: dict[str, EmbeddingModel] | None = None,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_batch_size: int = 2048,
    ) -> None:
        self.models: dict[str, EmbeddingModel] = dict(EMBEDDING_MODELS)
        if custom_models:
            self.models.update(custom_models)
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_batch_size = max_batch_size

        # Cached OpenAI clients keyed by (base_url, api_key_env)
        self._openai_clients: dict[tuple[str, str], AsyncOpenAI] = {}
        self._httpx_client: Any = None  # lazy httpx.AsyncClient

    # -- helpers ------------------------------------------------------------

    def _resolve_model(self, model: str) -> EmbeddingModel:
        """Look up a model by name, raising KeyError if unknown."""
        m = self.models.get(model)
        if m is None:
            raise KeyError(
                f"Unknown embedding model: {model!r}. "
                f"Available: {list(self.models.keys())}"
            )
        return m

    def _get_openai_client(self, spec: EmbeddingModel) -> AsyncOpenAI:
        """Return a cached AsyncOpenAI client for the given model spec."""
        key = (spec.base_url, spec.api_key_env)
        if key not in self._openai_clients:
            api_key = (
                os.environ.get(spec.api_key_env, "")
                if spec.api_key_env
                else "not-needed"
            )
            self._openai_clients[key] = AsyncOpenAI(
                base_url=spec.base_url,
                api_key=api_key or "not-needed",
            )
        return self._openai_clients[key]

    def _get_httpx_client(self) -> Any:
        """Return a cached httpx.AsyncClient."""
        if httpx is None:
            raise ImportError("httpx is required for non-OpenAI embedding providers")
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=120.0)
        return self._httpx_client

    # -- OpenAI-compatible embedding ----------------------------------------

    async def _embed_openai(
        self,
        texts: list[str],
        spec: EmbeddingModel,
    ) -> list[list[float]]:
        """Embed via the OpenAI embeddings API."""
        client = self._get_openai_client(spec)

        async def _call() -> list[list[float]]:
            response = await client.embeddings.create(
                model=spec.name,
                input=texts,
            )
            # Sort by index to preserve order
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]

        return await _retry_with_backoff(
            _call,
            max_retries=self._max_retries,
            base_delay=self._base_delay,
        )

    # -- httpx-based embedding for Voyage / Nomic / BAAI --------------------

    async def _embed_httpx(
        self,
        texts: list[str],
        spec: EmbeddingModel,
    ) -> list[list[float]]:
        """Embed via a generic REST endpoint using httpx."""
        hclient = self._get_httpx_client()
        api_key = os.environ.get(spec.api_key_env, "") if spec.api_key_env else ""

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": spec.name,
            "input": texts,
        }

        url = f"{spec.base_url}/embeddings" if spec.base_url else ""
        if not url:
            raise ValueError(
                f"Model {spec.name!r} has no base_url configured — "
                "cannot call remote API"
            )

        async def _call() -> list[list[float]]:
            resp = await hclient.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            sorted_data = sorted(data, key=lambda d: d.get("index", 0))
            return [d["embedding"] for d in sorted_data]

        return await _retry_with_backoff(
            _call,
            max_retries=self._max_retries,
            base_delay=self._base_delay,
        )

    # -- dispatch -----------------------------------------------------------

    async def _dispatch_embed(
        self,
        texts: list[str],
        spec: EmbeddingModel,
    ) -> list[list[float]]:
        """Route to the correct transport based on provider."""
        if spec.provider == "openai":
            return await self._embed_openai(texts, spec)
        elif spec.provider in ("voyage", "nomic"):
            return await self._embed_httpx(texts, spec)
        elif spec.provider == "baai":
            # BAAI models are self-hosted — try OpenAI-compatible endpoint
            if spec.base_url:
                return await self._embed_openai(texts, spec)
            raise ValueError(
                f"BAAI model {spec.name!r} requires a self-hosted endpoint. "
                "Set base_url in the model config."
            )
        else:
            # Default: try OpenAI-compatible API
            log.info("Unknown provider %r — trying OpenAI-compatible API", spec.provider)
            return await self._embed_openai(texts, spec)

    # -- public API ---------------------------------------------------------

    async def embed(
        self,
        text: str,
        model: str = "text-embedding-3-small",
    ) -> list[float]:
        """Embed a single text string, returning a float vector.

        If *text* exceeds the model's token limit it is automatically
        chunked and the resulting vectors are averaged (mean pooling).

        Parameters
        ----------
        text:
            The text to embed.
        model:
            Name of the embedding model (must be in the model registry).

        Returns
        -------
        list[float]
            The embedding vector.
        """
        spec = self._resolve_model(model)
        chunks = _chunk_text(text, spec.max_tokens)

        if len(chunks) == 1:
            results = await self._dispatch_embed(chunks, spec)
            return results[0]

        # Mean-pool across chunks
        log.debug(
            "Text too long for %s (est. tokens > %d); splitting into %d chunks",
            spec.name,
            spec.max_tokens,
            len(chunks),
        )
        all_vecs = await self._dispatch_embed(chunks, spec)
        return self._mean_pool(all_vecs)

    async def batch_embed(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> list[list[float]]:
        """Embed multiple texts, returning one vector per input text.

        Long texts are automatically chunked and mean-pooled.  The batch
        is split into sub-batches that respect the provider's limits.

        Parameters
        ----------
        texts:
            A list of text strings.
        model:
            Name of the embedding model.

        Returns
        -------
        list[list[float]]
            One embedding vector per input text.
        """
        if not texts:
            return []

        spec = self._resolve_model(model)
        results: list[list[float]] = [[] for _ in texts]

        # Identify which texts need chunking
        single_texts: list[tuple[int, str]] = []  # (original_idx, text)
        chunked_texts: list[tuple[int, list[str]]] = []

        for i, t in enumerate(texts):
            chunks = _chunk_text(t, spec.max_tokens)
            if len(chunks) == 1:
                single_texts.append((i, chunks[0]))
            else:
                chunked_texts.append((i, chunks))

        # Batch-embed all single-chunk texts in sub-batches
        for batch_start in range(0, len(single_texts), self._max_batch_size):
            batch = single_texts[batch_start : batch_start + self._max_batch_size]
            batch_texts = [t for _, t in batch]
            vecs = await self._dispatch_embed(batch_texts, spec)
            for (orig_idx, _), vec in zip(batch, vecs):
                results[orig_idx] = vec

        # Handle chunked texts individually (mean-pool each)
        for orig_idx, chunks in chunked_texts:
            vecs = await self._dispatch_embed(chunks, spec)
            results[orig_idx] = self._mean_pool(vecs)

        return results

    # -- utilities ----------------------------------------------------------

    @staticmethod
    def _mean_pool(vectors: list[list[float]]) -> list[float]:
        """Average multiple vectors element-wise and L2-normalise."""
        if not vectors:
            return []
        dim = len(vectors[0])
        pooled = [0.0] * dim
        for vec in vectors:
            for j in range(dim):
                pooled[j] += vec[j]
        n = len(vectors)
        for j in range(dim):
            pooled[j] /= n
        # L2 normalise
        norm = math.sqrt(sum(x * x for x in pooled))
        if norm > 0:
            pooled = [x / norm for x in pooled]
        return pooled

    def list_models(self) -> list[dict[str, Any]]:
        """Return all registered embedding models as serialisable dicts."""
        out: list[dict[str, Any]] = []
        for name, spec in self.models.items():
            out.append({
                "name": name,
                "dimensions": spec.dimensions,
                "max_tokens": spec.max_tokens,
                "provider": spec.provider,
                "cost_per_million": spec.cost_per_million,
                "is_open_source": spec.is_open_source,
                "available": spec.available,
                "description": spec.description,
            })
        return out

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
        for client in self._openai_clients.values():
            await client.close()
        self._openai_clients.clear()
