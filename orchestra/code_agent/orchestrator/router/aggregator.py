from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from orchestra.code_agent.orchestrator.router.models import (
    AgentClass, RouterPlan, StepResult, TaskIntent, TaskState,
)
from orchestra.code_agent.orchestrator.router.agent_pool import AgentPool
from orchestra.code_agent.orchestrator.router.planner import RouterPlanner
from orchestra.code_agent.orchestrator.router.state import StateGraph


class ResultAggregator:
    def __init__(
        self,
        planner: RouterPlanner,
        agent_pool: AgentPool,
        state_graph: StateGraph,
        llm_call: callable | None = None,
    ):
        self.planner = planner
        self.agent_pool = agent_pool
        self.state_graph = state_graph
        self._llm_call = llm_call or self._default_llm_call

    async def execute(
        self,
        user_input: str,
        intent: TaskIntent | None = None,
        constraints: list[str] | None = None,
    ) -> TaskState:
        intent = intent or self.planner._detect_intent(user_input)
        state = self.state_graph.create_state(user_input, intent)
        plan = await self.planner.create_plan(user_input, intent, constraints)
        self.state_graph.update_plan(state.task_id, plan)
        self.state_graph.set_status(state.task_id, "running")
        state = await self._execute_plan(state.task_id, plan, user_input)
        return state

    async def _execute_plan(
        self,
        task_id: str,
        plan: RouterPlan,
        user_input: str,
    ) -> TaskState:
        results: dict[int, str] = {}
        errors: dict[int, str] = {}
        step_index = 0

        while step_index < len(plan.steps):
            step = plan.steps[step_index]
            context = self._build_context(user_input, plan, results, errors, step_index)
            prompt = self.agent_pool.build_prompt(
                step.agent, step.goal, context, 
                self.state_graph.get_state(task_id).history if self.state_graph.get_state(task_id) else [],
            )
            step.input_prompt = prompt
            output = await self._call_agent(step, prompt)
            result = StepResult(
                step=step.step,
                agent=step.agent,
                status=output.get("status", "success"),
                output=output.get("content"),
                error=output.get("error"),
            )
            self.state_graph.add_step_result(task_id, result)

            if result.status == "success":
                results[step.step] = result.output or ""
                step_index += 1
            elif result.status == "retry" and step.retries < step.max_retries:
                step.retries += 1
            else:
                errors[step.step] = result.error or "Unknown error"
                if self.planner.config.enable_replan:
                    new_plan = await self.planner.replan(
                        user_input, plan,
                        self.state_graph.get_state(task_id).history if self.state_graph.get_state(task_id) else [],
                        failed_step=step.step,
                    )
                    if new_plan.steps:
                        self.state_graph.update_plan(task_id, new_plan)
                        plan = new_plan
                        step_index = 0
                        continue
                step_index += 1

        final_output = await self._build_final_output(user_input, results, errors, plan.intent)
        self.state_graph.set_final_output(task_id, final_output)
        return self.state_graph.get_state(task_id)

    async def _call_agent(
        self,
        step: "TaskStep",
        prompt: str,
    ) -> dict[str, Any]:
        try:
            content = await self._llm_call(
                self.agent_pool.get(step.agent).model,
                prompt,
            )
            return {"status": "success", "content": content}
        except Exception as e:
            if self.planner.config.enable_fallback:
                fallback = self._find_fallback_model(step.agent)
                if fallback:
                    try:
                        content = await self._llm_call(fallback, prompt)
                        return {"status": "success", "content": content}
                    except Exception as e2:
                        return {"status": "fail", "error": str(e2)}
            return {"status": "fail", "error": str(e)}

    def _find_fallback_model(self, agent: AgentClass) -> str | None:
        fallbacks = {
            AgentClass.CODER: ["qwen2.5:7b", "deepseek-r1:8b"],
            AgentClass.REASONER: ["qwen2.5:7b", "qwen2.5:3b"],
            AgentClass.SUMMARIZER: ["qwen2.5:1.5b"],
            AgentClass.VALIDATOR: ["qwen2.5:3b"],
        }
        for fb in fallbacks.get(agent, []):
            current = self.agent_pool.select_model(agent)
            if fb != current:
                return fb
        return None

    async def _build_final_output(
        self,
        user_input: str,
        results: dict[int, str],
        errors: dict[int, str],
        intent: TaskIntent,
    ) -> str:
        if not results:
            return f"Task failed. Errors: {errors}"
        if intent == TaskIntent.SUMMARY:
            return list(results.values())[-1]
        if intent == TaskIntent.CODE:
            return self._merge_code_results(results)
        parts = [f"## Result for: {user_input}\n"]
        for step_num in sorted(results):
            parts.append(f"### Step {step_num}\n{results[step_num]}\n")
        return "\n".join(parts)

    def _merge_code_results(self, results: dict[int, str]) -> str:
        ordered = [results[k] for k in sorted(results.keys())]
        return "\n\n".join(ordered)

    def _build_context(
        self,
        user_input: str,
        plan: RouterPlan,
        results: dict[int, str],
        errors: dict[int, str],
        current_step: int,
    ) -> str:
        parts = [f"Original request: {user_input}"]
        for s in plan.steps:
            if s.step < current_step and s.step in results:
                parts.append(f"Step {s.step} ({s.agent.value}): {results[s.step][:500]}")
            elif s.step in errors:
                parts.append(f"Step {s.step} ({s.agent.value}): ERROR - {errors[s.step]}")
        return "\n\n".join(parts)

    @staticmethod
    async def _default_llm_call(model: str, prompt: str) -> str:
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
