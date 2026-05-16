from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.agent import Agent
from code_agent.config import AgentConfig, LLMConfig


@dataclass
class ABTestConfig:
    name: str = "ab-test"
    task: str = ""
    model_a: str = "gpt-4o-mini"
    model_b: str = "gpt-4o"
    provider: str = "openai"
    max_iterations: int = 10
    runs: int = 3


@dataclass
class ABTestRun:
    model: str = ""
    run_number: int = 0
    output: str = ""
    duration_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ABTestResult:
    config: ABTestConfig = field(default_factory=ABTestConfig)
    runs_a: list[ABTestRun] = field(default_factory=list)
    runs_b: list[ABTestRun] = field(default_factory=list)
    avg_duration_a: float = 0.0
    avg_duration_b: float = 0.0
    success_rate_a: float = 0.0
    success_rate_b: float = 0.0
    winner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "runs_a": [r.to_dict() for r in self.runs_a],
            "runs_b": [r.to_dict() for r in self.runs_b],
            "avg_duration_a_ms": round(self.avg_duration_a, 1),
            "avg_duration_b_ms": round(self.avg_duration_b, 1),
            "success_rate_a": self.success_rate_a,
            "success_rate_b": self.success_rate_b,
            "winner": self.winner,
        }


class ABTestRunner:
    """Compare two model configurations side by side."""

    def __init__(self):
        self._results: list[ABTestResult] = []

    async def run(self, config: ABTestConfig) -> ABTestResult:
        result = ABTestResult(config=config)

        for run_num in range(1, config.runs + 1):
            for model_name, runs_list in [(config.model_a, result.runs_a), (config.model_b, result.runs_b)]:
                llm = LLMConfig(provider=config.provider, model=model_name)
                cfg = AgentConfig(llm=llm, max_iterations=config.max_iterations)
                agent = Agent(cfg)

                start = time.time()
                try:
                    output = await agent.run(config.task)
                    duration = (time.time() - start) * 1000
                    runs_list.append(ABTestRun(
                        model=model_name, run_number=run_num,
                        output=output[:500], duration_ms=round(duration, 1),
                        success=True,
                    ))
                except Exception as e:
                    duration = (time.time() - start) * 1000
                    runs_list.append(ABTestRun(
                        model=model_name, run_number=run_num,
                        output="", duration_ms=round(duration, 1),
                        success=False,
                    ))

        # Calculate stats
        if result.runs_a:
            result.avg_duration_a = sum(r.duration_ms for r in result.runs_a) / len(result.runs_a)
            result.success_rate_a = sum(1 for r in result.runs_a if r.success) / len(result.runs_a)
        if result.runs_b:
            result.avg_duration_b = sum(r.duration_ms for r in result.runs_b) / len(result.runs_b)
            result.success_rate_b = sum(1 for r in result.runs_b if r.success) / len(result.runs_b)

        if result.avg_duration_a < result.avg_duration_b:
            result.winner = config.model_a
        elif result.avg_duration_b < result.avg_duration_a:
            result.winner = config.model_b
        else:
            result.winner = "tie"

        self._results.append(result)
        return result

    def summary(self) -> str:
        lines = ["A/B Test Results\n"]
        for r in self._results:
            lines.append(f"  {r.config.name}:")
            lines.append(f"    A ({r.config.model_a}): avg {r.avg_duration_a:.0f}ms, success {r.success_rate_a:.0%}")
            lines.append(f"    B ({r.config.model_b}): avg {r.avg_duration_b:.0f}ms, success {r.success_rate_b:.0%}")
            lines.append(f"    Winner: {r.winner}")
        return "\n".join(lines)
