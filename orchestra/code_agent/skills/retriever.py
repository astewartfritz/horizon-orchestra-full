from __future__ import annotations

from typing import Any

from orchestra.code_agent.skills.models import Skill, Embedder
from orchestra.code_agent.skills.store import SkillStore


class SkillRetriever:
    def __init__(self, store: SkillStore, embedder: Embedder | None = None):
        self.store = store
        self.embedder = embedder or Embedder()

    def search(self, query: str, top_k: int = 5, env_filter: str | None = None, min_usage: int = 0) -> list[tuple[float, Skill]]:
        q_emb = self.embedder.embed(query)
        all_skills = self.store.list_all(limit=200)
        scored = []
        for s in all_skills:
            if min_usage > 0 and s.usage_count < min_usage:
                continue
            if env_filter and env_filter not in s.environments:
                continue
            if s.embedding:
                sim = self.embedder.cosine_similarity(q_emb, s.embedding)
                scored.append((sim, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def search_by_tag(self, tag: str, top_k: int = 10) -> list[Skill]:
        return [s for s in self.store.list_all(limit=200) if tag in s.tags][:top_k]

    def search_by_parent(self, parent_id: int) -> list[Skill]:
        return [s for s in self.store.list_all(limit=200) if s.parent_id == parent_id]

    def rerank(self, task_instruction: str, candidates: list[tuple[float, Skill]]) -> int | None:
        if not candidates:
            return None
        return candidates[0][1].id
