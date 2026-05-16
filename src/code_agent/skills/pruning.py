from __future__ import annotations

from code_agent.skills.models import Embedder
from code_agent.skills.store import SkillStore


class SkillPruner:
    def __init__(self, store: SkillStore, embedder: Embedder | None = None):
        self.store = store
        self.embedder = embedder or Embedder()

    def prune(self, min_usage: int = 2, min_success_rate: float = 0.1, max_skills: int = 200) -> int:
        all_skills = self.store.list_all(limit=1000)
        removed = 0
        if len(all_skills) <= max_skills:
            for s in all_skills:
                if s.usage_count >= min_usage and s.success_rate < min_success_rate:
                    self.store.remove(s.id)
                    removed += 1
        else:
            to_remove = sorted(all_skills, key=lambda s: (s.usage_count, s.avg_reward))[:len(all_skills) - max_skills]
            for s in to_remove:
                self.store.remove(s.id)
                removed += 1
        return removed

    def deduplicate(self, threshold: float = 0.95) -> int:
        all_skills = self.store.list_all(limit=500)
        removed = 0
        for i, a in enumerate(all_skills):
            for b in all_skills[i + 1:]:
                if a.embedding and b.embedding:
                    sim = self.embedder.cosine_similarity(a.embedding, b.embedding)
                    if sim >= threshold:
                        self.store.remove(b.id)
                        removed += 1
        return removed

    def merge(self, skill_ids: list[int]) -> int | None:
        skills = [self.store.get(sid) for sid in skill_ids]
        skills = [s for s in skills if s]
        if len(skills) < 2:
            return None
        total_usage = sum(s.usage_count for s in skills)
        merged = skills[0]
        merged.tags = list(set(t for s in skills for t in s.tags))
        merged.environments = list(set(e for s in skills for e in s.environments))
        merged.usage_count = total_usage
        merged.total_reward = sum(s.total_reward for s in skills)
        merged.success_count = sum(s.success_count for s in skills)
        self.store.update(merged)
        for s in skills[1:]:
            self.store.remove(s.id)
        return merged.id
