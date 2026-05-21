from __future__ import annotations

import uuid
from typing import Any

from orchestra.code_agent.skills.v2.task import TaskSpec
from orchestra.code_agent.skills.v2.skill import SkillV2
from orchestra.code_agent.skills.v2.trajectory import Trajectory, Step
from orchestra.code_agent.skills.v2.library import SkillLibraryV2
from orchestra.code_agent.skills.v2.policy import MetaPolicy
from orchestra.code_agent.skills.v2.environment import WebShopEnv


class EpisodeLifecycle:
    def __init__(self, library: SkillLibraryV2, policy: MetaPolicy, env: WebShopEnv):
        self.library = library
        self.policy = policy
        self.env = env

    async def run(self, task: TaskSpec, step: int = 0) -> dict[str, Any]:
        episode_id = uuid.uuid4().hex[:12]
        result: dict[str, Any] = {"episode_id": episode_id, "task": task.instruction, "step": step}

        # Phase 1: Query generation
        lib_stats = str(self.library.stats())
        query_out = await self.policy.query(task.instruction, lib_stats)
        query = query_out.content
        result["query"] = query

        # Phase 2: Retrieve and re-rank
        candidates = self.library.search(query, top_k=5)
        selected_id = None
        if candidates:
            rerank_out = await self.policy.rerank(task.instruction, candidates)
            try:
                selected_id = int(rerank_out.content.strip())
            except (ValueError, TypeError):
                selected_id = candidates[0][1].id if candidates else None
        else:
            selected_id = None

        chosen_skill = self.library.get(selected_id) if selected_id else None
        result["selected_skill_id"] = selected_id
        result["skill_body"] = chosen_skill.body if chosen_skill else "(none)"

        # Phase 3: Skill-conditioned rollout
        obs = self.env.reset(task.instruction)
        trajectory = Trajectory(task=task, skill_id=selected_id or 0, episode_id=episode_id)
        history: list[str] = []

        while not self.env.done:
            available = self.env.get_available_actions()
            skill_body = chosen_skill.body if chosen_skill else "No specific strategy available. Browse and search the catalog normally."
            act_out = await self.policy.act(
                task_instruction=task.instruction,
                skill_body=skill_body,
                observation=obs,
                actions=available,
                history=history,
            )
            raw_action = act_out.content.strip()
            cleaned = self._parse_action(raw_action, available)
            nxt_obs, reward, done, info = self.env.step(cleaned)
            trajectory.add_step(obs, cleaned, reward, done, info)
            history.append(f"{cleaned} -> reward={reward:+.2f}")
            obs = nxt_obs

        result["final_reward"] = trajectory.final_reward
        result["success"] = trajectory.success
        result["steps"] = trajectory.total_steps
        result["actions"] = self.env.actions_taken

        # Update skill stats
        if selected_id:
            self.library.record_usage(selected_id, trajectory.final_reward, trajectory.success, task.environment)

        # Phase 4: Distillation
        summary = trajectory.summarize()
        distill_out = await self.policy.distill(task.instruction, summary, trajectory.final_reward, trajectory.success)
        new_body = distill_out.content.strip()
        if new_body and len(new_body) > 20:
            new_skill = SkillV2(
                body=new_body,
                tags=[task.environment],
                creation_step=step,
                parent_id=selected_id,
            )
            new_skill.id = self.library.add(new_skill)
            result["new_skill_id"] = new_skill.id
            result["new_skill_body"] = new_body[:200]
        else:
            result["new_skill_id"] = None

        return result

    def _parse_action(self, raw: str, available: list[str]) -> str:
        raw = raw.strip().lower()
        for a in available:
            if raw == a.lower():
                return a
            if a.startswith("search[") and raw.startswith("search"):
                return a
            if a.startswith("click[") and raw.startswith("click"):
                return a
        return available[0] if available else "back"
