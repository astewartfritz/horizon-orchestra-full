from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    instruction: str
    environment: str = "webshop"
    difficulty: float = 0.5
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"instruction": self.instruction, "environment": self.environment, "difficulty": self.difficulty, "seed": self.seed, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskSpec:
        return cls(**d)


@dataclass
class Skill:
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
        return {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Skill:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass
class RolloutEvent:
    observation: str
    action: str
    reward: float
    done: bool
    info: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"observation": self.observation[:500], "action": self.action[:200], "reward": self.reward, "done": self.done, "info": self.info}


@dataclass
class Trajectory:
    task: TaskSpec
    skill_id: int
    events: list[RolloutEvent] = field(default_factory=list)
    final_reward: float = 0.0
    success: bool = False
    episode_id: str = ""

    def add_event(self, obs: str, action: str, reward: float, done: bool, info: dict | None = None) -> None:
        self.events.append(RolloutEvent(observation=obs, action=action, reward=reward, done=done, info=info or {}))
        self.final_reward = reward
        self.success = done and reward > 0

    @property
    def total_steps(self) -> int:
        return len(self.events)

    @property
    def cumulative_reward(self) -> float:
        return sum(e.reward for e in self.events)

    def summarize(self, max_events: int = 10) -> str:
        lines = [f"Task: {self.task.instruction}", f"Skill: #{self.skill_id}", f"Steps: {self.total_steps}", f"Final reward: {self.final_reward:.2f}", f"Success: {self.success}"]
        for i, e in enumerate(self.events[:max_events]):
            lines.append(f"  Step {i}: {e.action[:80]} -> reward={e.reward:+.2f}")
        if self.total_steps > max_events:
            lines.append(f"  ... ({self.total_steps - max_events} more)")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"task": self.task.to_dict(), "skill_id": self.skill_id, "events": [e.to_dict() for e in self.events], "final_reward": self.final_reward, "success": self.success, "episode_id": self.episode_id}


class Embedder:
    def __init__(self, provider: str = "", dim: int = 128):
        self.provider = provider or os.environ.get("EMBEDDING_PROVIDER", "hash")
        self.dim = dim
        self._model = None
        self._tokenizer = None

    def _use_gpu(self) -> bool:
        if self.provider not in ("", "auto", "hash"):
            return self.provider in ("sentence-transformers", "transformers")
        if self.provider == "hash":
            return False
        try:
            import torch
            return torch.cuda.is_available() and torch.cuda.device_count() > 0
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        if self._use_gpu() and self.provider != "hash":
            return self._model_embed(text)
        return self._hash_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._use_gpu() and self.provider != "hash":
            return self._model_embed_batch(texts)
        return [self._hash_embed(t) for t in texts]

    def _lazy_init_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            self._model = SentenceTransformer(model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
        except ImportError:
            try:
                from transformers import AutoModel, AutoTokenizer
                model_name = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._model = AutoModel.from_pretrained(model_name)
                self.dim = self._model.config.hidden_size
            except ImportError:
                self.provider = "hash"

    def _model_embed(self, text: str) -> list[float]:
        self._lazy_init_model()
        if self._model is None:
            return self._hash_embed(text)
        try:
            emb = self._model.encode(text) if hasattr(self._model, "encode") else self._hf_embed(text)
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)
        except Exception:
            return self._hash_embed(text)

    def _model_embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._lazy_init_model()
        if self._model is None:
            return [self._hash_embed(t) for t in texts]
        try:
            embs = self._model.encode(texts) if hasattr(self._model, "encode") else [self._hf_embed(t) for t in texts]
            return [e.tolist() if hasattr(e, "tolist") else list(e) for e in embs]
        except Exception:
            return [self._hash_embed(t) for t in texts]

    def _hf_embed(self, text: str) -> list[float]:
        import torch
        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self._model(**inputs)
        return outputs.last_hidden_state.mean(dim=1).squeeze().tolist()

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
