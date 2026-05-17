from __future__ import annotations

import json
import time
from typing import Any

from code_agent.orchestrator.router.agent_pool import AgentPool
from code_agent.orchestrator.router.agent_router import AgentRouter
from code_agent.orchestrator.router.models import (
    ModelLane, RouterConfig, RouterPlan, StepResult, StepStatus,
    TaskIntent, TaskState, TaskStatus, TaskStep,
)
from code_agent.orchestrator.router.planner import RouterPlanner
from code_agent.orchestrator.router.state import StateGraph

try:
    from code_agent.scaling.task_queue import DistributedTaskQueue, QueueTask
except ImportError:
    DistributedTaskQueue = None
    QueueTask = None

PLANNER_SYSTEM_PROMPT = """You are a routing planner for a multi-agent LLM system.
Your job is to decompose user requests into steps and assign each step to an agent role.

Available agent roles:
- coder: implements algorithms, writes code
- reasoner: decomposes problems, logical reasoning
- summarizer: condenses long outputs
- validator: checks correctness of outputs
- scratch: quick drafts and exploration
- searcher: finds relevant context/information
- extractor: pulls structured data from text

Return ONLY valid JSON with a "steps" array. Each step has: step (int), agent (string), goal (string).

Example:
{"steps": [{"step": 1, "agent": "reasoner", "goal": "Analyze the problem"}]}

Maximum {max_steps} steps."""


class Engine:
    """Implements the exact state-diagram flow:

    [*] → UserRequest → IngestTask → PlanTask → EnqueueSteps
          → ExecuteStep (DispatchStep → RunAgent → CollectResult → CheckStatus)
          → UserResponse → [*]
    """

    def __init__(
        self,
        config: RouterConfig | None = None,
        llm_call: callable | None = None,
        state_graph: StateGraph | None = None,
        task_queue: DistributedTaskQueue | None = None,
    ):
        self.config = config or RouterConfig()
        self.state_graph = state_graph or StateGraph()
        self.task_queue = task_queue
        self.agent_pool = AgentPool(config)
        self.agent_router = AgentRouter(config)
        self.planner = RouterPlanner(config, llm_call or self._llm_call)
        self._llm = llm_call or self._llm_call

    # ── IngestTask ──────────────────────────────────────────────

    def ingest(self, user_input: str, intent: TaskIntent | None = None) -> TaskState:
        intent = intent or self.planner._detect_intent(user_input)
        state = TaskState(
            user_input=user_input,
            intent=intent,
            status=TaskStatus.INGESTED,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.state_graph._states[state.task_id] = state
        self.state_graph._traces[state.task_id] = []
        self.state_graph._append_trace(state.task_id, "ingested", {
            "user_input": user_input,
            "intent": intent.value,
        })
        return state

    # ── PlanTask ────────────────────────────────────────────────

    async def plan(self, task_id: str) -> RouterPlan:
        state = self.state_graph.get_state(task_id)
        if not state:
            raise ValueError(f"task {task_id} not found")
        state.status = TaskStatus.PLANNED
        plan = await self.planner.create_plan(state.user_input, state.intent)
        state.plan = plan
        state.updated_at = time.time()
        self.state_graph._append_trace(task_id, "planned", {
            "steps": [{"step": s.step, "agent": s.agent_role or s.lane.value, "goal": s.goal}
                      for s in plan.steps],
        })
        return plan

    # ── EnqueueSteps ────────────────────────────────────────────

    def enqueue(self, task_id: str) -> TaskState:
        state = self.state_graph.get_state(task_id)
        if not state or not state.plan:
            raise ValueError(f"task {task_id} has no plan")
        state.status = TaskStatus.ENQUEUED
        state.updated_at = time.time()
        resolved = []
        for s in state.plan.steps:
            lane, model = self.agent_router.route(s.agent_role or s.lane.value, {
                "input_length": len(state.user_input),
            })
            s.lane = lane
            s.input_prompt = self.agent_pool.build_prompt_from_lane(
                lane, s.goal, state.user_input,
            )
            resolved.append({"step": s.step, "lane": lane.value, "model": model})
        self.state_graph._append_trace(task_id, "enqueued", {
            "resolved_lanes": resolved,
        })
        return state

    # ── ExecuteStep ─────────────────────────────────────────────

    async def execute(self, task_id: str) -> TaskState:
        state = self.state_graph.get_state(task_id)
        if not state or not state.plan:
            raise ValueError(f"task {task_id} has no plan")

        state.status = TaskStatus.RUNNING
        state.updated_at = time.time()
        steps = state.plan.steps
        index = 0

        while index < len(steps):
            step = steps[index]
            result = await self._dispatch_step(task_id, state, step, index)
            self.state_graph.add_step_result(task_id, result)

            if result.status == StepStatus.SUCCESS:
                index += 1
            elif result.status == StepStatus.RETRY and step.retries < step.max_retries:
                step.retries += 1
                self.state_graph._append_trace(task_id, "retry", {
                    "step": step.step, "retries": step.retries,
                })
            elif result.status == StepStatus.NEEDS_REPLAN and self.config.enable_replan:
                state = await self._replan(task_id, state, step.step)
                steps = state.plan.steps
                index = 0
            else:
                index += 1

        return await self._respond(task_id)

    async def _dispatch_step(
        self, task_id: str, state: TaskState, step: TaskStep, index: int,
    ) -> StepResult:
        step.status = StepStatus.DISPATCHED
        self.state_graph._append_trace(task_id, "dispatched", {
            "step": step.step, "lane": step.lane.value,
        })

        step.status = StepStatus.RUNNING
        prompt = step.input_prompt or self.agent_pool.build_prompt_from_lane(
            step.lane, step.goal, state.user_input,
        )
        model = self.config.model_lanes.get(step.lane, step.lane.value)
        self.state_graph._append_trace(task_id, "running", {
            "step": step.step, "model": model,
        })

        content, err = await self._run_agent(model, prompt, step.lane)
        step.result = content

        self.state_graph._append_trace(task_id, "collected", {
            "step": step.step, "has_result": content is not None, "error": err,
        })

        if err:
            if self.config.enable_fallback:
                fallback_lane, fallback_model = self._fallback(step.lane)
                if fallback_model:
                    content2, err2 = await self._run_agent(fallback_model, prompt, fallback_lane)
                    if content2 and not err2:
                        content = content2
                        err = None
                        step.lane = fallback_lane

        status = StepStatus.SUCCESS if content and not err else (StepStatus.FAILED if err else StepStatus.RETRY)
        return StepResult(
            step=step.step, lane=step.lane,
            agent_role=step.agent if hasattr(step, 'agent') else step.lane.value,
            status=status,
            output=content, error=err,
        )

    async def _run_agent(
        self, model: str, prompt: str, lane: ModelLane,
    ) -> tuple[str | None, str | None]:
        try:
            content = await self._llm(model, prompt)
            return content, None
        except Exception as e:
            return None, str(e)

    def _fallback(self, lane: ModelLane) -> tuple[ModelLane, str | None]:
        table = {
            ModelLane.CODER_7B: (ModelLane.REASONER_7B, self.config.model_lanes[ModelLane.REASONER_7B]),
            ModelLane.REASONER_7B: (ModelLane.MASTER_PLANNER_7B, self.config.model_lanes[ModelLane.MASTER_PLANNER_7B]),
            ModelLane.SUMMARIZER_3B: (ModelLane.SCRATCH_3B, self.config.model_lanes[ModelLane.SCRATCH_3B]),
            ModelLane.VALIDATOR_7B: (ModelLane.REASONER_7B, self.config.model_lanes[ModelLane.REASONER_7B]),
        }
        return table.get(lane, (ModelLane.FALLBACK_3B, self.config.model_lanes[ModelLane.FALLBACK_3B]))

    async def _replan(self, task_id: str, state: TaskState, failed_step: int) -> TaskState:
        self.state_graph._append_trace(task_id, "replanning", {
            "failed_step": failed_step,
        })
        new_plan = await self.planner.replan(
            state.user_input, state.plan,
            state.history, failed_step=failed_step,
        )
        state.plan = new_plan
        state.updated_at = time.time()
        self.state_graph._append_trace(task_id, "replanned", {
            "steps": [{"step": s.step, "agent": s.agent_role or s.lane.value, "goal": s.goal}
                      for s in new_plan.steps],
        })
        return state

    # ── UserResponse ────────────────────────────────────────────

    async def _respond(self, task_id: str) -> TaskState:
        state = self.state_graph.get_state(task_id)
        if not state:
            raise ValueError(f"task {task_id} not found")

        results = {r.step: r.output for r in state.history if r.status == StepStatus.SUCCESS and r.output}
        if state.intent == TaskIntent.SUMMARY and results:
            final = list(results.values())[-1]
        elif state.intent == TaskIntent.CODE and results:
            ordered = [results[k] for k in sorted(results.keys())]
            final = "\n\n".join(ordered)
        else:
            parts = [f"## Result\n"]
            for r in state.history:
                if r.output:
                    label = f"Step {r.step} ({r.agent_role})"
                    parts.append(f"### {label}\n{r.output}\n")
            final = "\n".join(parts)

        state.final_output = final
        state.status = TaskStatus.COMPLETED
        state.updated_at = time.time()
        self.state_graph._append_trace(task_id, "responded", {
            "output_preview": final[:300],
        })
        return state

    # ── Full lifecycle ──────────────────────────────────────────

    async def run(self, user_input: str, intent: TaskIntent | None = None) -> TaskState:
        state = self.ingest(user_input, intent)
        await self.plan(state.task_id)
        self.enqueue(state.task_id)
        return await self.execute(state.task_id)

    # ── Distributed queue integration ──────────────────────────

    async def enqueue_to_queue(self, task_id: str) -> bool:
        if not self.task_queue or not QueueTask:
            return False
        state = self.state_graph.get_state(task_id)
        if not state:
            return False
        qt = QueueTask(
            task_id=task_id,
            user_input=state.user_input,
            intent=state.intent.value if state.intent else "general",
        )
        return await self.task_queue.enqueue(qt)

    # ── LLM call ────────────────────────────────────────────────

    @staticmethod
    async def _llm_call(model: str, prompt: str) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            data = resp.json()
            return data.get("message", {}).get("content", "")
