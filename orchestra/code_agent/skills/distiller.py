from __future__ import annotations

import json
from typing import Any

from orchestra.code_agent.llm.base import LLM, Message
from orchestra.code_agent.skills.models import Skill, Trajectory, TaskSpec, Embedder
from orchestra.code_agent.skills.store import SkillStore
from orchestra.code_agent.skills.policy import SkillPolicy

DISTILL_PROMPT = """Distill the following trajectory into a reusable skill strategy.

Task: {task_instruction}
Steps:
{steps}
Final reward: {final_reward}
Success: {success}

Write a concise 3-5 step procedure capturing the essential method. Output ONLY the numbered steps."""


class SkillDistiller:
    def __init__(self, store: SkillStore, policy: SkillPolicy | None = None, llm: LLM | None = None):
        self.store = store
        self._policy = policy
        self._llm = llm

    @property
    def policy(self) -> SkillPolicy:
        if not self._policy:
            if not self._llm:
                self._llm = LLM(provider="ollama", model="nemotron-mini", timeout=120)
            self._policy = SkillPolicy(self._llm)
        return self._policy

    async def distill(self, trajectory: Trajectory | dict[str, Any], task_instruction: str | None = None) -> Skill | None:
        if isinstance(trajectory, dict):
            steps = trajectory
            task_text = task_instruction or "unknown"
            final_reward = 0.0
            success = False
        else:
            task_text = trajectory.task.instruction
            final_reward = trajectory.final_reward
            success = trajectory.success
            steps = [{"tool": e.action[:80], "reward": e.reward} for e in trajectory.events[:20]]

        steps_text = "\n".join(f"- {s.get('tool', s.get('action', '?'))}" for s in (steps if isinstance(steps, list) else []))
        prompt = DISTILL_PROMPT.format(task_instruction=task_text, steps=steps_text or "(no steps)", final_reward=final_reward, success=success)
        resp = await self.policy.llm.chat(messages=[Message(role="user", content=prompt)])
        body = (resp.content or "").strip()
        if not body or len(body) < 20:
            body = f"For {task_text[:60]}: {steps_text[:200]}"
        embedder = Embedder()
        skill = Skill(body=body, tags=[], creation_step=0)
        skill.embedding = embedder.embed(body)
        skill.id = self.store.add(skill)
        return skill
