from __future__ import annotations

import json
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
        return {
            "instruction": self.instruction,
            "environment": self.environment,
            "difficulty": self.difficulty,
            "seed": self.seed,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskSpec:
        return cls(**d)
