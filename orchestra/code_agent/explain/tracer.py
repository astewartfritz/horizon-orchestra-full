from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ThoughtStep:
    step: int = 0
    action: str = ""
    reasoning: str = ""
    tool: str = ""
    tool_input: str = ""
    tool_output: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExplanationTracer:
    """Record and explain the agent's decision-making process."""

    def __init__(self):
        self._thoughts: list[ThoughtStep] = []
        self._current_step = 0
        self._start_time = 0.0

    def begin(self) -> None:
        self._start_time = time.time()
        self._current_step = 0

    def record(self, action: str, reasoning: str, tool: str = "",
               tool_input: str = "", tool_output: str = "") -> ThoughtStep:
        self._current_step += 1
        step = ThoughtStep(
            step=self._current_step,
            action=action,
            reasoning=reasoning,
            tool=tool,
            tool_input=tool_input[:500],
            tool_output=tool_output[:500],
            duration_ms=(time.time() - self._start_time) * 1000,
        )
        self._thoughts.append(step)
        return step

    def get_trace(self) -> list[ThoughtStep]:
        return list(self._thoughts)

    def explain(self) -> str:
        lines = [f"## Agent Reasoning ({len(self._thoughts)} steps)\n"]
        for t in self._thoughts:
            lines.append(f"\n### Step {t.step}: {t.action}")
            lines.append(f"**Reasoning:** {t.reasoning[:300]}")
            if t.tool:
                lines.append(f"**Tool:** {t.tool}")
                if t.tool_input:
                    lines.append(f"**Input:** {t.tool_input[:200]}")
                if t.tool_output:
                    lines.append(f"**Output:** {t.tool_output[:200]}")
            lines.append(f"**Duration:** {t.duration_ms:.0f}ms")
        return "\n".join(lines)

    def to_dict(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._thoughts]

    def summary(self) -> dict[str, Any]:
        tool_counts: dict[str, int] = {}
        for t in self._thoughts:
            if t.tool:
                tool_counts[t.tool] = tool_counts.get(t.tool, 0) + 1
        total_ms = self._thoughts[-1].duration_ms if self._thoughts else 0
        return {
            "steps": len(self._thoughts),
            "total_duration_ms": round(total_ms, 1),
            "tool_calls": sum(tool_counts.values()),
            "tools_used": tool_counts,
        }
