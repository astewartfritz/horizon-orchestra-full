from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrainingSignal:
    """A single experience tuple used for RL policy updates.

    Stores everything needed to update the routing policy:
    - what task was issued
    - which agent handled it
    - what the council scored
    - the resulting reward
    - task category for policy lookup
    """

    task: str
    agent_name: str
    task_category: str
    reward: float                       # 0.0–1.0
    council_mean: float                 # raw council mean score (0–10)
    dimension_scores: dict[str, float]  # per-dimension council scores
    passed_gate: bool
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def task_preview(self) -> str:
        return self.task[:100]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_preview": self.task_preview,
            "agent_name": self.agent_name,
            "task_category": self.task_category,
            "reward": self.reward,
            "council_mean": round(self.council_mean, 3),
            "dimension_scores": {k: round(v, 3) for k, v in self.dimension_scores.items()},
            "passed_gate": self.passed_gate,
            "timestamp": self.timestamp,
        }
