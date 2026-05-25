from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.embeddings.models import (
    EmbeddingClient,
    cosine_similarity as _cosine_similarity,
    hash_embed as _hash_embed_shared,
)


@dataclass
class SkillV2:
    id: int = 0
    body: str = ""
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    creation_step: int = 0
    usage_count: int = 0
    success_count: int = 0
    total_reward: float = 0.0
    environments: list[str] = field(default_factory=list)
    parent_id: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def avg_reward(self) -> float:
        return self.total_reward / max(self.usage_count, 1)

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.usage_count, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "body": self.body,
            "tags": self.tags,
            "embedding": self.embedding,
            "creation_step": self.creation_step,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "total_reward": self.total_reward,
            "environments": self.environments,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SkillV2:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Embedder:
    """Embedding provider — delegates to canonical EmbeddingClient.

    Supports ``"hash"`` (deterministic fallback) and ``"api"`` (remote
    embedding via EmbeddingClient).  Falls through to hash on API failure.
    """

    def __init__(self, provider: str = "hash", dim: int = 128):
        self.provider = provider
        self.dim = dim
        self._api_client: EmbeddingClient | None = None

    def _get_api_client(self) -> EmbeddingClient | None:
        if self._api_client is None and self.provider == "api":
            try:
                from orchestra.embeddings.models import CANONICAL_EMBEDDING_CLIENT
                self._api_client = CANONICAL_EMBEDDING_CLIENT()
            except Exception:
                pass
        return self._api_client

    def embed(self, text: str) -> list[float]:
        if self.provider == "api":
            client = self._get_api_client()
            if client is not None:
                try:
                    return asyncio.run(client.embed(text))
                except Exception:
                    pass
        return _hash_embed_shared(text, dim=self.dim)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "api":
            client = self._get_api_client()
            if client is not None:
                try:
                    return asyncio.run(client.batch_embed(texts))
                except Exception:
                    pass
        return [_hash_embed_shared(t, dim=self.dim) for t in texts]

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        return _cosine_similarity(a, b)
