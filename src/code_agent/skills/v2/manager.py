from __future__ import annotations

import random
from typing import Any

from code_agent.llm.base import LLM
from code_agent.skills.v2.task import TaskSpec
from code_agent.skills.v2.skill import SkillV2, Embedder
from code_agent.skills.v2.trajectory import TrajectoryBuffer
from code_agent.skills.v2.library import SkillLibraryV2
from code_agent.skills.v2.policy import MetaPolicy, PromptTemplates
from code_agent.skills.v2.environment import WebShopEnv
from code_agent.skills.v2.lifecycle import EpisodeLifecycle
from code_agent.skills.v2.rl import RLTrainer


class SkillManagerV2:
    def __init__(
        self,
        library: SkillLibraryV2 | None = None,
        policy: MetaPolicy | None = None,
        env: WebShopEnv | None = None,
        llm: LLM | None = None,
    ):
        self.library = library or SkillLibraryV2()
        self.embedder = Embedder()
        self.llm = llm
        self.policy = policy
        self.env = env or WebShopEnv()
        self.buffer = TrajectoryBuffer()
        self.trainer = RLTrainer()
        self.lifecycle: EpisodeLifecycle | None = None
        self._step = 0

    def ensure_policy(self) -> MetaPolicy:
        if self.policy:
            return self.policy
        if not self.llm:
            from code_agent.llm.base import LLM as _LLM
            self.llm = _LLM(provider="ollama", model="nemotron-mini", timeout=120)
        self.policy = MetaPolicy(self.llm)
        return self.policy

    async def run_episode(self, instruction: str, difficulty: float = 0.5, seed: int | None = None) -> dict[str, Any]:
        policy = self.ensure_policy()
        if seed is not None:
            import random as _r
            _r.seed(seed)
        if not self.lifecycle:
            self.lifecycle = EpisodeLifecycle(self.library, policy, self.env)
        task = TaskSpec(instruction=instruction, difficulty=difficulty, seed=seed)
        result = await self.lifecycle.run(task, step=self._step)
        self._step += 1
        self.trainer.record_episode(
            outcome=result.get("final_reward", 0.0),
            utilization_lp=1.0 if result.get("steps", 0) > 0 else 0.0,
            selection_lp=1.0 if result.get("selected_skill_id") else 0.0,
            distillation_lp=1.0 if result.get("new_skill_id") else 0.0,
        )
        self.trainer.update()
        result["credit"] = {
            "selection": self.trainer.compute_credit().selection,
            "utilization": self.trainer.compute_credit().utilization,
            "distillation": self.trainer.compute_credit().distillation,
        }
        result["rl_params"] = dict(self.trainer._params)
        return result

    async def train(self, num_episodes: int = 10, task_pool: list[str] | None = None) -> list[dict[str, Any]]:
        if task_pool is None:
            task_pool = [
                "Buy a 27-inch 4K monitor under $300",
                "Find a red dress size M under $50",
                "Buy a premium electronics product with high rating",
                "Find a sports item under $100",
                "Buy a book with best rating",
                "Find a basic home product in blue",
                "Buy a laptop under $800",
                "Find a white clothing item size L",
            ]
        results = []
        for i in range(num_episodes):
            instruction = task_pool[i % len(task_pool)]
            diff = 0.3 + (i / num_episodes) * 0.7
            r = await self.run_episode(instruction, difficulty=diff, seed=i)
            results.append(r)
            if (i + 1) % 5 == 0:
                self.library.prune()
        return results

    def stats(self) -> dict[str, Any]:
        return {
            "library": self.library.stats(),
            "buffer": self.buffer.stats(),
            "trainer": self.trainer.stats(),
            "step": self._step,
        }
