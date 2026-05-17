from __future__ import annotations

import time
from typing import Any

from code_agent.orchestrator.router.models import (
    RouterPlan, StepResult, TaskState, TaskStatus, StepStatus,
)


class StateGraph:
    def __init__(self):
        self._states: dict[str, TaskState] = {}
        self._traces: dict[str, list[dict[str, Any]]] = {}

    def create_state(
        self, user_input: str, intent: str = "general",
    ) -> TaskState:
        state = TaskState(
            user_input=user_input,
            status=TaskStatus.PENDING,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._states[state.task_id] = state
        self._traces[state.task_id] = []
        self._append_trace(state.task_id, "created", {"user_input": user_input})
        return state

    def get_state(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    def update_plan(self, task_id: str, plan: RouterPlan) -> None:
        state = self._states.get(task_id)
        if state:
            state.plan = plan
            state.updated_at = time.time()

    def add_step_result(self, task_id: str, result: StepResult) -> None:
        state = self._states.get(task_id)
        if state:
            state.history.append(result)
            state.updated_at = time.time()

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        state = self._states.get(task_id)
        if state:
            state.status = status
            state.updated_at = time.time()

    def list_states(self, status: str | None = None, limit: int = 50) -> list[TaskState]:
        states = list(self._states.values())
        if status:
            states = [s for s in states if s.status.value == status]
        states.sort(key=lambda s: s.updated_at, reverse=True)
        return states[:limit]

    def delete_state(self, task_id: str) -> bool:
        if task_id in self._states:
            del self._states[task_id]
            self._traces.pop(task_id, None)
            return True
        return False

    def get_trace(self, task_id: str) -> list[dict[str, Any]]:
        return self._traces.get(task_id, [])

    def export_trace(self, task_id: str) -> dict[str, Any] | None:
        state = self._states.get(task_id)
        if not state:
            return None
        return {
            "task_id": state.task_id,
            "user_input": state.user_input,
            "intent": state.intent.value if state.intent else None,
            "status": state.status.value if state.status else None,
            "plan": {
                "steps": [
                    {"step": s.step, "lane": s.lane.value, "goal": s.goal}
                    for s in (state.plan.steps if state.plan else [])
                ]
            } if state.plan else None,
            "history": [
                {
                    "step": h.step, "lane": h.lane.value,
                    "agent_role": h.agent_role,
                    "status": h.status.value,
                    "output": h.output, "error": h.error,
                }
                for h in state.history
            ],
            "final_output": state.final_output,
            "trace": self._traces.get(task_id, []),
        }

    def _append_trace(self, task_id: str, event: str, data: dict[str, Any]) -> None:
        if task_id in self._traces:
            self._traces[task_id].append({
                "event": event, "data": data, "timestamp": time.time(),
            })
