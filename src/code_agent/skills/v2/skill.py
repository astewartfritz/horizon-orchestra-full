from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any


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
    def __init__(self, provider: str = "hash", dim: int = 128):
        self.provider = provider
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        if self.provider == "hash":
            return self._hash_embed(text)
        raise ValueError(f"Unknown embedder: {self.provider}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        import hashlib
        vec = [0.0] * self.dim
        for word in text.lower().split():
            h = hashlib.md5(word.encode()).hexdigest()
            for i in range(self.dim):
                vec[i] += (int(h[i % 32], 16) / 15.0) * (1.0 if (int(h[(i + 1) % 32], 16) % 2 == 0) else -1.0)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)
