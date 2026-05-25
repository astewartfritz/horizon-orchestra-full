"""Horizon Orchestra — Agent Kernel.

The core plan-act-observe-reflect loop with long-horizon planning,
FLARE lookahead, and self-correction.  This is the brain that makes
Orchestra smarter than OpenClaw's stateless tool loop or Perplexity
Computer's single-pass agent.

Kernel loop:
1. **PLAN** — decompose goal into subtasks with lookahead
2. **ACT** — execute the next step using tools
3. **OBSERVE** — analyze the result
4. **REFLECT** — evaluate progress, detect drift, self-correct
5. **COMMIT or REPLAN** — advance or revise the plan

This is Architecture A's agent_loop.py evolved into a cognitive
architecture.

Usage::

    from orchestra.kernel import AgentKernel, KernelConfig
    kernel = AgentKernel(router=router, tools=tools, config=config)
    result = await kernel.run("Build a full-stack app with auth")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from .router import ModelRouter
from .agent_loop import (
    AgentConfig,
    AgentEvent,
    AgentLoop,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
)
from .evaluation import Evaluator, EvalResult, QualityGate
from .telemetry import Tracer, Span, CostTracker
from .safety import SafetyLayer
from .queue.checkpoint import CheckpointStore, WorkflowCheckpoint

__all__ = ["AgentKernel", "KernelConfig", "KernelState", "PlanStep"]

log = logging.getLogger("orchestra.kernel")


# ---------------------------------------------------------------------------
# Plan representation
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    id: int
    description: str
    status: str = "pending"       # pending, active, done, failed, skipped
    result: str = ""
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    retries: int = 0


@dataclass
class KernelState:
    """Mutable state of the kernel during execution."""
    goal: str = ""
    plan: list[PlanStep] = field(default_factory=list)
    current_step: int = 0
    total_iterations: int = 0
    total_tool_calls: int = 0
    reflections: list[str] = field(default_factory=list)
    replans: int = 0
    eval_scores: list[float] = field(default_factory=list)
    status: str = "idle"          # idle, planning, acting, reflecting, done, failed


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class KernelConfig:
    model: str = "kimi-k2.5"
    planner_model: str = "kimi-k2.5"
    critic_model: str = "kimi-k2.5"
    max_iterations: int = 300
    max_plan_steps: int = 20
    max_retries_per_step: int = 2
    max_replans: int = 3
    reflection_interval: int = 5       # reflect every N tool calls
    quality_threshold: float = 0.7
    enable_evaluation: bool = True
    enable_safety: bool = True
    enable_tracing: bool = True
    lookahead_depth: int = 2           # FLARE: how many steps to look ahead
    temperature: float = 0.6
    max_tokens: int = 16384
    workflow_id: str = ""              # non-empty enables checkpoint save/resume
    checkpoint_dir: str = ""          # override CheckpointStore directory


# ---------------------------------------------------------------------------
# Planning prompts
# ---------------------------------------------------------------------------

PLAN_SYSTEM = """\
You are the Planner in Horizon Orchestra's kernel. Given a goal,
decompose it into concrete, ordered steps.

For each step, describe:
- What to do
- What tools are likely needed
- What the expected output is

Consider dependencies between steps. Output JSON:
{{"plan": [
  {{"id": 1, "description": "...", "tools": ["web_search", "execute_code"], "expected_output": "..."}},
  ...
]}}

Keep plans between 3-15 steps. Each step should be completable in
10-30 tool calls. If the task is simple, use fewer steps.
"""

REFLECT_SYSTEM = """\
You are the Critic in Horizon Orchestra's kernel. You review the agent's
progress and decide whether to continue, adjust, or replan.

Given:
- The original goal
- The current plan
- Work completed so far
- Current step results

Evaluate:
1. Is the agent on track to achieve the goal?
2. Are there any errors or drift from the plan?
3. Should the current step be retried, skipped, or the plan revised?

Respond with JSON:
{{
  "on_track": true/false,
  "assessment": "brief assessment",
  "action": "continue" | "retry_step" | "skip_step" | "replan",
  "suggestions": ["..."],
  "revised_plan": [...]  // only if action is "replan"
}}
"""

LOOKAHEAD_SYSTEM = """\
You are the Lookahead module. Given the current state and next planned
steps, predict potential issues and suggest preemptive adjustments.

Think {depth} steps ahead. What could go wrong? What information will
the agent need that it doesn't have yet?

Respond with JSON:
{{
  "risks": ["..."],
  "preemptive_actions": ["..."],
  "confidence": 0.0-1.0
}}
"""


# ---------------------------------------------------------------------------
# Agent kernel
# ---------------------------------------------------------------------------

class AgentKernel:
    """The cognitive architecture for Horizon Orchestra.

    This is the orchestration brain that elevates Orchestra beyond
    simple tool-calling loops (OpenClaw) and single-pass agents
    into a self-correcting, planning system.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        tools: ToolRegistry | None = None,
        config: KernelConfig | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.tools = tools or ToolRegistry()
        self.config = config or KernelConfig()

        self.state = KernelState()
        self.tracer = Tracer() if self.config.enable_tracing else None
        self.cost_tracker = CostTracker()
        self.evaluator = Evaluator(self.router, self.config.critic_model) if self.config.enable_evaluation else None
        self.safety = SafetyLayer() if self.config.enable_safety else None
        self.gate = QualityGate(min_score=self.config.quality_threshold)

        # Durable checkpointing (opt-in via workflow_id)
        if self.config.workflow_id:
            kw = {"directory": self.config.checkpoint_dir} if self.config.checkpoint_dir else {}
            self._checkpoints: CheckpointStore | None = CheckpointStore(**kw)
        else:
            self._checkpoints = None

    async def run(self, goal: str, context: str = "") -> str:
        """Execute the full kernel loop: plan → act → observe → reflect."""
        self.state = KernelState(goal=goal, status="planning")

        # Safety check on input
        if self.safety:
            check = self.safety.check_input(goal)
            if check.blocked:
                return f"[BLOCKED] {check.block_reason}"

        # ── Resume from checkpoint if one exists ──────────────────────
        _results: list[str] = []
        if self._checkpoints:
            saved = self._checkpoints.load(self.config.workflow_id)
            if saved and saved.status == "running":
                log.info("[KERNEL] Resuming workflow %s at step %d",
                         self.config.workflow_id, saved.current_step)
                self.state.plan = [PlanStep(**s) for s in saved.plan]
                self.state.current_step = saved.current_step
                self.state.total_tool_calls = saved.total_tool_calls
                self.state.replans = saved.replans
                _results = saved.results

        root_span = self.tracer.span("kernel.run") if self.tracer else None

        try:
            # ── PHASE 1: PLAN (skip if resumed) ───────────────────────
            plan_span = self.tracer.span("kernel.plan", root_span) if self.tracer else None
            if not self.state.plan:
                await self._plan(goal, context)
            if plan_span:
                plan_span.set("steps", len(self.state.plan))
                plan_span.end()

            log.info("[KERNEL] Plan created: %d steps", len(self.state.plan))

            # ── PHASE 2: EXECUTE STEPS ────────────────────────────────
            self.state.status = "acting"
            results: list[str] = _results  # may be pre-populated on resume

            for step in self.state.plan:
                if step.status in ("skipped", "done"):
                    continue

                step.status = "active"
                self.state.current_step = step.id
                step_span = self.tracer.span(f"kernel.step.{step.id}", root_span) if self.tracer else None

                # FLARE lookahead
                if self.config.lookahead_depth > 0 and step.id < len(self.state.plan):
                    await self._lookahead(step)

                # Execute the step
                step_result = await self._execute_step(step, goal, "\n".join(results[-3:]))

                if step_result:
                    step.result = step_result
                    step.status = "done"
                    results.append(f"[Step {step.id}] {step_result[:2000]}")
                else:
                    step.status = "failed"
                    step.retries += 1
                    if step.retries <= self.config.max_retries_per_step:
                        step.status = "active"
                        step_result = await self._execute_step(step, goal, "\n".join(results[-3:]))
                        if step_result:
                            step.result = step_result
                            step.status = "done"
                            results.append(f"[Step {step.id}] {step_result[:2000]}")

                if step_span:
                    step_span.set("status", step.status)
                    step_span.set("iterations", step.iterations)
                    step_span.end()

                # Checkpoint after every step so we can resume on restart
                self._save_checkpoint(goal, results)

                # ── PHASE 3: REFLECT ──────────────────────────────────
                if (self.state.total_tool_calls % self.config.reflection_interval == 0
                        and self.state.total_tool_calls > 0):
                    self.state.status = "reflecting"
                    action = await self._reflect(goal, results)
                    self.state.status = "acting"

                    if action == "replan" and self.state.replans < self.config.max_replans:
                        await self._replan(goal, results)
                        break  # restart from new plan
                    elif action == "skip_step":
                        step.status = "skipped"
                        continue

            # ── PHASE 4: SYNTHESIZE ───────────────────────────────────
            self.state.status = "done"
            final = await self._synthesize(goal, results)

            # Quality gate
            if self.evaluator and final:
                eval_result = await self.evaluator.evaluate(goal, final)
                self.state.eval_scores.append(eval_result.overall_score)
                self.gate.check(eval_result)
                if not eval_result.passed_gate:
                    log.warning("[KERNEL] Output below quality threshold: %.2f", eval_result.overall_score)

            # Safety check on output
            if self.safety and final:
                out_check = self.safety.check_output(final)
                final = out_check.cleaned_text

            return final

        finally:
            if root_span:
                root_span.set("total_iterations", self.state.total_iterations)
                root_span.set("total_tool_calls", self.state.total_tool_calls)
                root_span.set("replans", self.state.replans)
                root_span.end()
            # Remove checkpoint when the workflow finishes cleanly
            if self._checkpoints and self.config.workflow_id:
                self._checkpoints.delete(self.config.workflow_id)

    # -- checkpoint helper --------------------------------------------------

    def _save_checkpoint(self, goal: str, results: list[str]) -> None:
        if not self._checkpoints or not self.config.workflow_id:
            return
        cp = WorkflowCheckpoint(
            workflow_id=self.config.workflow_id,
            goal=goal,
            plan=[
                {"id": s.id, "description": s.description, "status": s.status,
                 "result": s.result, "tools_used": s.tools_used,
                 "iterations": s.iterations, "retries": s.retries}
                for s in self.state.plan
            ],
            current_step=self.state.current_step,
            total_tool_calls=self.state.total_tool_calls,
            replans=self.state.replans,
            results=results[-20:],  # keep last 20 to bound file size
            status="running",
        )
        self._checkpoints.save(cp)

    # -- planning -----------------------------------------------------------

    async def _plan(self, goal: str, context: str) -> None:
        """Generate an execution plan."""
        client, model_id = self.router.get_client(self.config.planner_model)
        messages = [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": f"Goal: {goal}\n\nContext: {context[:3000]}" if context else f"Goal: {goal}"},
        ]

        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3, max_tokens=2048,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            steps = data.get("plan", [])
            self.state.plan = [
                PlanStep(
                    id=s.get("id", i + 1),
                    description=s.get("description", ""),
                )
                for i, s in enumerate(steps[:self.config.max_plan_steps])
            ]
        except Exception as exc:
            log.warning("Planning failed: %s — using single-step fallback", exc)
            self.state.plan = [PlanStep(id=1, description=goal)]

    # -- step execution -----------------------------------------------------

    async def _execute_step(self, step: PlanStep, goal: str, prior_results: str) -> str:
        """Execute a single plan step via the agent loop."""
        config = AgentConfig(
            model=self.config.model,
            max_iterations=50,  # per-step limit
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=(
                f"You are executing step {step.id} of a plan.\n"
                f"Overall goal: {goal}\n"
                f"This step: {step.description}\n"
                f"Prior results:\n{prior_results[:3000]}\n\n"
                f"Complete this step using the tools available."
            ),
        )

        agent = AgentLoop(router=self.router, tools=self.tools, config=config)
        output = ""

        async for event in agent.run(step.description):
            if isinstance(event, ToolCallEvent):
                step.tools_used.append(event.tool_name)
                step.iterations += 1
                self.state.total_tool_calls += 1
            elif isinstance(event, FinalAnswerEvent):
                output = event.content
                self.state.total_iterations += event.total_iterations

        return output

    # -- reflection ---------------------------------------------------------

    async def _reflect(self, goal: str, results: list[str]) -> str:
        """Reflect on progress and decide next action."""
        client, model_id = self.router.get_client(self.config.critic_model)

        plan_summary = "\n".join(
            f"  Step {s.id} [{s.status}]: {s.description[:80]}"
            for s in self.state.plan
        )
        results_summary = "\n".join(results[-5:])

        messages = [
            {"role": "system", "content": REFLECT_SYSTEM},
            {"role": "user", "content": (
                f"Goal: {goal}\n\n"
                f"Plan:\n{plan_summary}\n\n"
                f"Current step: {self.state.current_step}\n"
                f"Tool calls so far: {self.state.total_tool_calls}\n\n"
                f"Recent results:\n{results_summary[:4000]}"
            )},
        ]

        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2, max_tokens=1024,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            action = data.get("action", "continue")
            assessment = data.get("assessment", "")
            self.state.reflections.append(f"[Step {self.state.current_step}] {assessment}")
            log.info("[KERNEL] Reflection: %s → %s", assessment[:80], action)
            return action
        except Exception:
            return "continue"

    # -- FLARE lookahead ----------------------------------------------------

    async def _lookahead(self, current_step: PlanStep) -> None:
        """Look ahead to predict issues with upcoming steps."""
        client, model_id = self.router.get_client(self.config.planner_model)

        upcoming = [
            s for s in self.state.plan
            if s.id > current_step.id and s.status == "pending"
        ][:self.config.lookahead_depth]

        if not upcoming:
            return

        upcoming_desc = "\n".join(f"  Step {s.id}: {s.description}" for s in upcoming)

        messages = [
            {"role": "system", "content": LOOKAHEAD_SYSTEM.format(depth=self.config.lookahead_depth)},
            {"role": "user", "content": (
                f"Current step: {current_step.description}\n"
                f"Upcoming steps:\n{upcoming_desc}\n"
                f"Goal: {self.state.goal}"
            )},
        ]

        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3, max_tokens=512,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            risks = data.get("risks", [])
            if risks:
                log.info("[KERNEL] Lookahead risks: %s", risks[:2])
        except Exception as exc:
            log.warning("[KERNEL] Lookahead failed: %s — proceeding without preemptive actions", exc)

    # -- replanning ---------------------------------------------------------

    async def _replan(self, goal: str, results: list[str]) -> None:
        """Generate a revised plan based on progress so far."""
        self.state.replans += 1
        log.info("[KERNEL] Replanning (attempt %d/%d)", self.state.replans, self.config.max_replans)

        client, model_id = self.router.get_client(self.config.planner_model)

        completed = [s for s in self.state.plan if s.status == "done"]
        completed_desc = "\n".join(f"  Done: {s.description[:80]}" for s in completed)

        messages = [
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": (
                f"REPLANNING. The original plan hit issues.\n"
                f"Goal: {goal}\n\n"
                f"Completed steps:\n{completed_desc}\n\n"
                f"Results so far:\n{chr(10).join(results[-3:])[:3000]}\n\n"
                f"Create a revised plan for the REMAINING work only."
            )},
        ]

        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3, max_tokens=2048,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            new_steps = data.get("plan", [])
            offset = len(completed) + 1
            self.state.plan = [s for s in self.state.plan if s.status == "done"]
            for i, s in enumerate(new_steps[:self.config.max_plan_steps]):
                self.state.plan.append(PlanStep(
                    id=offset + i,
                    description=s.get("description", ""),
                ))
            log.info("[KERNEL] Revised plan: %d new steps", len(new_steps))
        except Exception as exc:
            log.warning("Replan failed: %s", exc)

    # -- synthesis ----------------------------------------------------------

    async def _synthesize(self, goal: str, results: list[str]) -> str:
        """Synthesize all step results into a final answer."""
        client, model_id = self.router.get_client(self.config.model)

        messages = [
            {"role": "system", "content": (
                "You are Horizon Orchestra. Synthesize the results from all plan steps "
                "into a complete, well-structured final answer. Cite sources where available."
            )},
            {"role": "user", "content": f"Goal: {goal}\n\nResults:\n{chr(10).join(results)[:12000]}"},
        ]

        try:
            resp = await client.chat.completions.create(
                model=model_id, messages=messages,
                max_tokens=self.config.max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            return "\n\n".join(results)  # fallback: raw results

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "status": self.state.status,
            "plan_steps": len(self.state.plan),
            "completed_steps": sum(1 for s in self.state.plan if s.status == "done"),
            "total_iterations": self.state.total_iterations,
            "total_tool_calls": self.state.total_tool_calls,
            "replans": self.state.replans,
            "reflections": len(self.state.reflections),
            "eval_scores": self.state.eval_scores,
            "cost": self.cost_tracker.summary() if self.cost_tracker else {},
            "trace": self.tracer.summary() if self.tracer else {},
        }
