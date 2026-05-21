from orchestra.code_agent.skills.models import Embedder
from orchestra.code_agent.skills.store import SkillStore
from orchestra.code_agent.skills.credit import CreditSignal
from orchestra.code_agent.skills.retriever import SkillRetriever


class SkillManager:
    def __init__(self, library=None, embedder=None):
        self.library = library or SkillStore()
        self._embedder = embedder or Embedder()
        self._retriever = SkillRetriever(self.library, self._embedder)

    async def retrieve(self, query, top_k=3):
        return [s for _, s in self._retriever.search(query, top_k=top_k)]

    def record_outcome(self, outcome):
        pass

    def compute_credit(self):
        return CreditSignal(0.5, 0.5, 0.5)

    async def distill(self, task, trajectory, outcome, llm_synthesize=None):
        from orchestra.code_agent.skills.distiller import SkillDistiller
        d = SkillDistiller(self.library)
        return await d.distill({"task": type("o", (), {"instruction": task})(), "events": [{"action": s.get("tool", "?"), "reward": 0.0} for s in trajectory], "final_reward": outcome, "success": outcome > 0}, task)


__all__ = ["SkillManager", "Embedder", "CreditSignal"]
