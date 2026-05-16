from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.skills.v2.task import TaskSpec


@dataclass
class Step:
    observation: str
    action: str
    reward: float
    done: bool
    info: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation[:500],
            "action": self.action[:200],
            "reward": self.reward,
            "done": self.done,
            "info": self.info,
        }


@dataclass
class Trajectory:
    task: TaskSpec
    skill_id: int
    steps: list[Step] = field(default_factory=list)
    final_reward: float = 0.0
    success: bool = False
    episode_id: str = ""

    def add_step(self, obs: str, action: str, reward: float, done: bool, info: dict | None = None) -> None:
        self.steps.append(Step(observation=obs, action=action, reward=reward, done=done, info=info or {}))
        self.final_reward = reward
        self.success = done and reward > 0

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def cumulative_reward(self) -> float:
        return sum(s.reward for s in self.steps)

    def summarize(self, max_steps: int = 10) -> str:
        lines = [f"Task: {self.task.instruction}", f"Skill: #{self.skill_id}", f"Steps: {self.total_steps}", f"Final reward: {self.final_reward:.2f}", f"Success: {self.success}"]
        for i, s in enumerate(self.steps[:max_steps]):
            lines.append(f"  Step {i}: {s.action[:80]} → reward={s.reward:+.2f}")
        if self.total_steps > max_steps:
            lines.append(f"  ... ({self.total_steps - max_steps} more steps)")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "skill_id": self.skill_id,
            "steps": [s.to_dict() for s in self.steps],
            "final_reward": self.final_reward,
            "success": self.success,
            "episode_id": self.episode_id,
        }


class TrajectoryBuffer:
    def __init__(self, max_size: int = 1000):
        self.trajectories: list[Trajectory] = []
        self.max_size = max_size

    def add(self, traj: Trajectory) -> None:
        self.trajectories.append(traj)
        if len(self.trajectories) > self.max_size:
            self.trajectories.pop(0)

    def recent(self, n: int = 10) -> list[Trajectory]:
        return self.trajectories[-n:]

    def clear(self) -> None:
        self.trajectories.clear()

    def stats(self) -> dict[str, Any]:
        if not self.trajectories:
            return {"count": 0, "avg_reward": 0.0, "success_rate": 0.0}
        rewards = [t.final_reward for t in self.trajectories]
        successes = sum(1 for t in self.trajectories if t.success)
        return {
            "count": len(self.trajectories),
            "avg_reward": sum(rewards) / len(rewards),
            "success_rate": successes / len(self.trajectories),
            "max_reward": max(rewards),
            "min_reward": min(rewards),
        }
