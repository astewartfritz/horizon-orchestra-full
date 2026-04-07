"""Horizon Orchestra — Sub-Agent Swarm.

Parallel execution engine inspired by Kimi K2.5's native Agent Swarm.
Decomposes goals into a DAG of subtasks, assigns models, and executes
with maximum parallelism via ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .router import ModelRouter
from .agent_loop import AgentLoop, AgentConfig, ToolRegistry, FinalAnswerEvent, ErrorEvent

__all__ = [
    "SubTask",
    "SwarmResult",
    "SwarmCoordinator",
]

log = logging.getLogger("orchestra.swarm")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    id: str
    description: str
    model: str
    tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    output_file: str = ""
    priority: str = "medium"


@dataclass
class SwarmResult:
    task_id: str
    output: str
    model_used: str
    duration_seconds: float
    success: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Planning prompt
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """\
You are a task planner for Horizon Orchestra.  Given a user goal, decompose
it into concrete subtasks that can be executed by specialist agents.

For each subtask assign the best model from the available list and declare
dependencies so independent work runs in parallel.

Available models (name → strengths → cost):
{model_table}

Available tools: {tool_names}

Respond with a JSON object containing a single key "tasks" whose value is
an array.  Each element:
{{
  "id":          "task_N",
  "description": "what to do",
  "model":       "model_name from the list above",
  "tools":       ["tool_names this agent needs"],
  "depends_on":  ["task_ids that must finish first"],
  "output_file": "/tmp/horizon_workspace/task_N.md",
  "priority":    "high | medium | low"
}}

Rules:
- Maximise parallelism: only add depends_on when truly needed.
- Use the cheapest model that can handle each subtask.
- Use sonar-pro ONLY for tasks requiring live web data with citations.
- Use kimi-k2.5 for coding, reasoning, and agentic tasks (10× cheaper than Claude).
- Use grok-3 for fast, lightweight tasks like summarisation.
"""


# ---------------------------------------------------------------------------
# Swarm coordinator
# ---------------------------------------------------------------------------

class SwarmCoordinator:
    """Plan → execute DAG → synthesise."""

    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        workspace_dir: str = "/tmp/horizon_workspace",
    ) -> None:
        self.router = router
        self.tool_registry = tool_registry
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # -- planning -----------------------------------------------------------

    async def plan(
        self,
        goal: str,
        planner_model: str = "kimi-k2.5",
    ) -> list[SubTask]:
        """Decompose *goal* into a DAG of :class:`SubTask` objects."""
        model_rows = []
        for m in self.router.list_models():
            if m["available"]:
                model_rows.append(
                    f"- {m['name']}: {', '.join(m['strengths'])} "
                    f"(${m['cost_input']}/{m['cost_output']})"
                )
        model_table = "\n".join(model_rows) or "- kimi-k2.5: reasoning, coding, agentic ($0.60/$2.50)"

        system = PLANNER_SYSTEM.format(
            model_table=model_table,
            tool_names=", ".join(self.tool_registry.names) or "web_search, execute_code, file_read, file_write",
        )

        client, model_id = self.router.get_client(planner_model)

        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": goal},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4096,
            )
        except Exception as exc:
            log.error("Planning call failed: %s", exc)
            # Fallback: single-task plan
            return [SubTask(
                id="task_1",
                description=goal,
                model=planner_model,
                tools=self.tool_registry.names,
                output_file=str(self.workspace / "task_1.md"),
            )]

        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Planner returned invalid JSON; using single-task fallback")
            return [SubTask(
                id="task_1",
                description=goal,
                model=planner_model,
                tools=self.tool_registry.names,
                output_file=str(self.workspace / "task_1.md"),
            )]

        tasks_raw = data.get("tasks", data if isinstance(data, list) else [data])
        tasks: list[SubTask] = []
        for t in tasks_raw:
            tasks.append(SubTask(
                id=t.get("id", f"task_{len(tasks)+1}"),
                description=t.get("description", ""),
                model=t.get("model", planner_model),
                tools=t.get("tools", []),
                depends_on=t.get("depends_on", []),
                output_file=t.get("output_file", str(self.workspace / f"{t.get('id', 'task')}.md")),
                priority=t.get("priority", "medium"),
            ))

        log.info("Planned %d subtasks for goal: %s", len(tasks), goal[:80])
        return tasks

    # -- DAG execution ------------------------------------------------------

    async def execute(self, tasks: list[SubTask]) -> dict[str, SwarmResult]:
        """Execute tasks respecting the dependency DAG."""
        completed: dict[str, SwarmResult] = {}
        pending: dict[str, SubTask] = {t.id: t for t in tasks}

        while pending:
            ready = [
                t for t in pending.values()
                if all(dep in completed for dep in t.depends_on)
            ]
            if not ready:
                # Detect circular deps or missing references
                missing = set()
                for t in pending.values():
                    for dep in t.depends_on:
                        if dep not in completed and dep not in pending:
                            missing.add(dep)
                if missing:
                    log.error("Missing dependency task IDs: %s — skipping blocked tasks", missing)
                    # Unblock by dropping the missing deps
                    for t in pending.values():
                        t.depends_on = [d for d in t.depends_on if d not in missing]
                    continue
                # True circular dependency
                log.error("Circular dependency detected among: %s", list(pending))
                for tid, task in list(pending.items()):
                    completed[tid] = SwarmResult(
                        task_id=tid, output="", model_used=task.model,
                        duration_seconds=0, success=False,
                        error="Circular dependency",
                    )
                break

            # Launch all ready tasks in parallel
            coros = [self._run_subtask(t) for t in ready]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for task, result in zip(ready, results):
                if isinstance(result, Exception):
                    completed[task.id] = SwarmResult(
                        task_id=task.id, output="", model_used=task.model,
                        duration_seconds=0, success=False, error=str(result),
                    )
                else:
                    completed[task.id] = result
                del pending[task.id]
                status = "✓" if completed[task.id].success else "✗"
                log.info("  %s %s (%s, %.1fs)", status, task.id, task.model,
                         completed[task.id].duration_seconds)

        return completed

    async def _run_subtask(self, task: SubTask) -> SwarmResult:
        """Run a single subtask via its own AgentLoop."""
        t0 = time.monotonic()

        # Build a scoped tool registry for this subtask
        tools = self.tool_registry.subset(task.tools) if task.tools else self.tool_registry

        config = AgentConfig(
            model=task.model,
            max_iterations=100,  # per-subtask limit
            system_prompt=(
                f"You are a specialist sub-agent (task {task.id}) in Horizon Orchestra. "
                f"Complete this task: {task.description}\n"
                f"Save your output to: {task.output_file}"
            ),
        )

        agent = AgentLoop(router=self.router, tools=tools, config=config)

        output_parts: list[str] = []
        try:
            async for event in agent.run(task.description):
                if isinstance(event, FinalAnswerEvent):
                    output_parts.append(event.content)
                elif isinstance(event, ErrorEvent) and not event.recoverable:
                    return SwarmResult(
                        task_id=task.id, output="", model_used=task.model,
                        duration_seconds=time.monotonic() - t0,
                        success=False, error=event.message,
                    )
        except Exception as exc:
            return SwarmResult(
                task_id=task.id, output="", model_used=task.model,
                duration_seconds=time.monotonic() - t0,
                success=False, error=str(exc),
            )

        output = "\n".join(output_parts)

        # Persist to workspace file
        if task.output_file:
            try:
                p = Path(task.output_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(output, encoding="utf-8")
            except OSError as exc:
                log.warning("Could not write output for %s: %s", task.id, exc)

        return SwarmResult(
            task_id=task.id,
            output=output,
            model_used=task.model,
            duration_seconds=time.monotonic() - t0,
            success=True,
        )

    # -- synthesis ----------------------------------------------------------

    async def synthesize(
        self,
        goal: str,
        results: dict[str, SwarmResult],
        model: str = "kimi-k2.5",
    ) -> str:
        """Merge all subtask outputs into a coherent final answer."""
        parts: list[str] = []
        for tid, r in results.items():
            status = "SUCCESS" if r.success else f"FAILED: {r.error}"
            parts.append(f"## {tid} [{status}] (model: {r.model_used}, {r.duration_seconds:.1f}s)\n{r.output}")

        artifacts = "\n\n---\n\n".join(parts)

        client, model_id = self.router.get_client(model)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the synthesis agent in Horizon Orchestra. "
                            "Read the sub-agent outputs below and produce a unified, "
                            "well-structured final response. Cite sources where available."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Original goal: {goal}\n\nSub-agent outputs:\n\n{artifacts}",
                    },
                ],
                max_tokens=16384,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("Synthesis failed: %s", exc)
            return artifacts  # fallback: return raw outputs

    # -- full pipeline ------------------------------------------------------

    async def run(self, goal: str, planner_model: str = "kimi-k2.5") -> str:
        """Plan → execute DAG → synthesise."""
        log.info("[PLAN] Decomposing: %s", goal[:120])
        tasks = await self.plan(goal, planner_model=planner_model)
        log.info("[PLAN] Created %d subtasks", len(tasks))

        log.info("[EXEC] Running sub-agents...")
        results = await self.execute(tasks)

        log.info("[SYNTH] Assembling final output...")
        return await self.synthesize(goal, results)
