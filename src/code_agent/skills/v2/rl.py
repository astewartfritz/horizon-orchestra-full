from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CreditSignal:
    selection: float = 0.0
    utilization: float = 0.0
    distillation: float = 0.0


class RLTrainer:
    """REINFORCE-style trainer with frequency-based credit assignment ala Skill1.

    Base signal: utilization (raw reward per episode).
    Low-frequency (selection): smoothed moving average — credit for query/rerank quality.
    High-frequency (distillation): local fluctuations — credit for newly distilled skills.
    """

    def __init__(self, window_size: int = 20, selection_lr: float = 0.1, distill_lr: float = 0.05):
        self.window_size = window_size
        self.selection_lr = selection_lr
        self.distill_lr = distill_lr
        self._outcomes: list[float] = []
        self._selection_logprobs: list[float] = []
        self._utilization_logprobs: list[float] = []
        self._distillation_logprobs: list[float] = []
        self._params: dict[str, float] = {
            "selection_bias": 0.0,
            "utilization_bias": 0.0,
            "distillation_bias": 0.0,
        }

    def record_episode(self, outcome: float, selection_lp: float = 0.0, utilization_lp: float = 0.0, distillation_lp: float = 0.0) -> None:
        self._outcomes.append(outcome)
        self._selection_logprobs.append(selection_lp)
        self._utilization_logprobs.append(utilization_lp)
        self._distillation_logprobs.append(distillation_lp)
        if len(self._outcomes) > self.window_size * 3:
            self._outcomes = self._outcomes[-self.window_size * 2:]
            self._selection_logprobs = self._selection_logprobs[-self.window_size * 2:]
            self._utilization_logprobs = self._utilization_logprobs[-self.window_size * 2:]
            self._distillation_logprobs = self._distillation_logprobs[-self.window_size * 2:]

    def compute_credit(self) -> CreditSignal:
        n = len(self._outcomes)
        if n < 3:
            return CreditSignal(0.5, 0.5, 0.5)
        recent = self._outcomes[-min(self.window_size, n):]
        utilization = sum(recent) / len(recent)
        all_avg = sum(self._outcomes) / n
        variance = sum((o - all_avg) ** 2 for o in self._outcomes) / n if n > 1 else 0.0
        selection = all_avg
        distillation = min(1.0, variance * 0.5) if n > 5 else 0.0
        return CreditSignal(selection=selection, utilization=utilization, distillation=distillation)

    def update(self) -> dict[str, float]:
        credit = self.compute_credit()
        n = len(self._outcomes)
        if n < 2:
            return self._params
        advantage = self._outcomes[-1] - (sum(self._outcomes) / n)
        self._params["selection_bias"] += self.selection_lr * advantage * credit.selection
        self._params["utilization_bias"] += self.selection_lr * advantage * credit.utilization
        self._params["distillation_bias"] += self.distill_lr * advantage * credit.distillation
        for k in self._params:
            self._params[k] = max(-2.0, min(2.0, self._params[k]))
        return self._params

    def stats(self) -> dict[str, Any]:
        return {
            "episodes": len(self._outcomes),
            "params": self._params,
            "credit": {
                "selection": self.compute_credit().selection,
                "utilization": self.compute_credit().utilization,
                "distillation": self.compute_credit().distillation,
            },
            "avg_outcome": sum(self._outcomes) / len(self._outcomes) if self._outcomes else 0.0,
            "recent_avg": sum(self._outcomes[-min(self.window_size, len(self._outcomes)):]) / min(self.window_size, len(self._outcomes)) if self._outcomes else 0.0,
        }
