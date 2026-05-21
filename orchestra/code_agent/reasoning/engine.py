from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestra.code_agent.config import ReasoningConfig
from orchestra.code_agent.llm.base import LLM, Message
from orchestra.code_agent.reasoning.strategies import (
    ChainOfThought,
    PlanAndExecute,
    ReflectOnError,
    TreeOfThought,
    ThinkingTrace,
    get_strategy_prompt,
)


@dataclass
class ReasoningSession:
    task: str
    strategy: str
    traces: list[dict[str, Any]] = field(default_factory=list)
    plan: str | None = None
    result: str | None = None
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ReasoningSession:
        return cls(**d)


class ReasoningEngine:
    """Orchestrates thinking strategies and persists reasoning traces."""

    def __init__(
        self,
        llm: LLM,
        config: ReasoningConfig | None = None,
    ):
        self.llm = llm
        self.config = config or ReasoningConfig()
        self.strategies = {
            "cot": ChainOfThought(llm),
            "plan": PlanAndExecute(llm),
            "reflect": ReflectOnError(llm),
            "tot": TreeOfThought(llm),
            "converse": ChainOfThought(llm),
        }
        self.current_session: ReasoningSession | None = None
        self._ensure_trace_dir()

    def _ensure_trace_dir(self) -> None:
        if self.config.save_traces:
            Path(self.config.trace_dir).mkdir(parents=True, exist_ok=True)

    def _trace_path(self, task_id: str) -> Path:
        return Path(self.config.trace_dir) / f"{task_id}.json"

    def _get_prompt(self) -> str:
        return get_strategy_prompt(self.config.strategy)

    def _is_conversation(self, text: str) -> bool:
        t = text.lower().strip()
        # Task keywords override conversation detection
        task_keywords = ["read ", "write ", "edit ", "find ", "search ", "list ",
                         "create ", "build ", "fix ", "update ", "delete ", "add ",
                         "run ", "execute ", "install ", "configure ", "implement "]
        for kw in task_keywords:
            if t.startswith(kw) or t.startswith("please " + kw):
                return False
        # Conversation patterns
        patterns = ["my name is", "i am", "i'm", "hello", "hi ", "hey", "nice to meet",
                     "how are you", "what's up", "good morning", "good evening",
                     "thanks", "thank you", "you're welcome", "cool", "got it",
                     "my name's"]
        if any(p in t for p in patterns):
            return True
        # Very short inputs without question marks are likely conversation
        if len(t.split()) <= 3 and "?" not in t:
            return True
        return False

    def select_strategy(self, task: str) -> str:
        strategy = self.config.strategy
        if strategy == "auto":
            if self._is_conversation(task):
                strategy = "converse"
            else:
                words = len(task.split())
                if words > 50:
                    strategy = "plan"
                elif "error" in task.lower() or "fix" in task.lower():
                    strategy = "reflect"
                else:
                    strategy = "cot"
        return strategy

    async def think(
        self, task: str, context: list[Message] | None = None
    ) -> str:
        start = time.time()
        strategy_name = self.select_strategy(task)
        self.current_session = ReasoningSession(
            task=task,
            strategy=strategy_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        trace = ThinkingTrace(strategy=strategy_name)

        # Phase 1: Analyze & Plan (skipped — `reason` below generates the plan)

        # Phase 2: Explore if needed (for complex tasks)
        if strategy_name == "tot":
            explorer = self.strategies["tot"]
            results = await explorer.explore(task, branches=self.config.max_plans)
            for name, content in results:
                self._log_thinking(f"[bold #e0af68]{name}:[/]\n{content[:300]}...")

        # Phase 3: Generate thinking trace
        thinking_prompt = self._build_thinking_prompt(task, strategy_name)
        msgs = list(context or [])
        msgs.append(Message(role="user", content=thinking_prompt))

        thinker = self.strategies.get(strategy_name, self.strategies["cot"])
        thought = await thinker.reason(task, context=msgs[-2:])

        trace.add_step("think", thought)
        self.current_session.traces.append(trace.to_dict())
        self.current_session.duration_ms = (time.time() - start) * 1000

        self._log_thinking(f"[bold #238636]Thought:[/]\n{thought[:500]}...")

        return thought

    def _build_thinking_prompt(
        self, task: str, strategy: str
    ) -> str:
        base = get_strategy_prompt(strategy)
        return f"""{base}

## Task
{task}

## Instructions
Think through this carefully before using any tools. Show your reasoning.
"""

    def _log_thinking(self, msg: str) -> None:
        if self.config.show_thinking:
            try:
                from rich.console import Console
                Console().print(msg)
            except ImportError:
                pass

    def record_error(self, error: str) -> None:
        if self.current_session:
            self.current_session.errors.append(error)

    async def reflect_on_error(
        self, error: str, context: str = ""
    ) -> str:
        reflector = self.strategies["reflect"]
        reflection = await reflector.reflect(error, context)
        if self.current_session:
            self.current_session.traces.append(reflector.trace.to_dict())
        self._log_thinking(f"[bold #f7768e]Reflection:[/]\n{reflection}")
        return reflection

    def finish(self, result: str) -> None:
        if self.current_session:
            self.current_session.result = result
            self._save_trace()

    def _save_trace(self) -> None:
        if not self.config.save_traces or not self.current_session:
            return
        try:
            task_id = self.current_session.task.replace(" ", "_")[:40]
            ts = datetime.now(timezone.utc).strftime("%H%M%S")
            path = self._trace_path(f"{task_id}_{ts}")
            path.write_text(
                json.dumps(self.current_session.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_trace(self, name: str) -> ReasoningSession | None:
        path = self._trace_path(name)
        if path.exists():
            return ReasoningSession.from_dict(
                json.loads(path.read_text("utf-8"))
            )
        # Search for partial match
        for p in sorted(Path(self.config.trace_dir).glob("*.json")):
            if name in p.stem:
                return ReasoningSession.from_dict(
                    json.loads(p.read_text("utf-8"))
                )
        return None

    def list_traces(self) -> list[dict[str, Any]]:
        results = []
        for p in sorted(
            Path(self.config.trace_dir).glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(p.read_text("utf-8"))
                results.append({
                    "name": p.stem,
                    "strategy": data.get("strategy", "?"),
                    "task": data.get("task", "")[:60],
                    "duration_ms": data.get("duration_ms", 0),
                    "errors": len(data.get("errors", [])),
                })
            except Exception:
                continue
        return results
