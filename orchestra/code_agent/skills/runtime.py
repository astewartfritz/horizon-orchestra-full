from __future__ import annotations

import uuid

from orchestra.code_agent.skills.models import TaskSpec, Skill, Trajectory
from orchestra.code_agent.skills.store import SkillStore
from orchestra.code_agent.skills.retriever import SkillRetriever
from orchestra.code_agent.skills.policy import SkillPolicy
from orchestra.code_agent.skills.environment import WebShopEnv


class EpisodeRuntime:
    def __init__(self, store: SkillStore, retriever: SkillRetriever, policy: SkillPolicy, env: WebShopEnv):
        self.store = store
        self.retriever = retriever
        self.policy = policy
        self.env = env

    async def run(self, instruction: str, difficulty: float = 0.5, seed: int | None = None) -> dict[str, any]:
        task = TaskSpec(instruction=instruction, environment="webshop", difficulty=difficulty, seed=seed)
        episode_id = uuid.uuid4().hex[:12]
        result: dict[str, any] = {"episode_id": episode_id, "task": instruction}

        # 1. Query
        lib_stats = str(self.store.stats())
        query_out = await self.policy.query(instruction, lib_stats)
        result["query"] = query_out.content

        # 2. Retrieve + rank
        candidates = self.retriever.search(query_out.content, top_k=5)
        selected_id = None
        chosen_skill: Skill | None = None
        if candidates:
            rank_out = await self.policy.rank(instruction, candidates)
            try:
                selected_id = int(rank_out.content.strip())
            except (ValueError, TypeError):
                selected_id = candidates[0][1].id
            chosen_skill = next((s for _, s in candidates if s.id == selected_id), candidates[0][1])
            if not self.store.get(selected_id):
                selected_id = candidates[0][1].id
                chosen_skill = candidates[0][1]
        result["selected_skill_id"] = selected_id

        # 3. Rollout
        obs = self.env.reset(instruction)
        trajectory = Trajectory(task=task, skill_id=selected_id or 0, episode_id=episode_id)
        history: list[str] = []
        while not self.env.done:
            available = self.env.get_available_actions()
            skill_body = chosen_skill.body if chosen_skill else "Browse and search normally."
            act_out = await self.policy.act(instruction, skill_body, obs, available, history)
            action = self._resolve_action(act_out.content.strip(), available)
            nxt_obs, reward, done, info = self.env.step(action)
            trajectory.add_event(obs, action, reward, done, info)
            history.append(f"{action} -> reward={reward:+.2f}")
            obs = nxt_obs
        result["final_reward"] = trajectory.final_reward
        result["success"] = trajectory.success
        result["steps"] = trajectory.total_steps

        if selected_id:
            self.store.record_usage(selected_id, trajectory.final_reward, trajectory.success, "webshop")

        return result

    def _resolve_action(self, raw: str, available: list[str]) -> str:
        raw = raw.strip().lower()
        for a in available:
            if raw == a.lower():
                return a
            if a.startswith("search[") and raw.startswith("search"):
                return a
            if a.startswith("click[") and raw.startswith("click"):
                return a
        return available[0] if available else "back"
