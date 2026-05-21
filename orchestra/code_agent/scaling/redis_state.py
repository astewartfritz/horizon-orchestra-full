from __future__ import annotations

import json
import time
import uuid
from typing import Any

from orchestra.code_agent.orchestrator.router.models import (
    RouterPlan, StepResult, TaskState, TaskStatus, StepStatus,
)
from orchestra.code_agent.orchestrator.router.state import StateGraph


class RedisStateGraph(StateGraph):
    """Drop-in replacement for StateGraph backed by Redis.

    Uses the same interface so existing code works unmodified.
    Falls back to in-memory dicts if Redis is unreachable.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "orchestra:state:",
        ttl_seconds: int = 86400,
    ):
        super().__init__()
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.ttl = ttl_seconds
        self._redis = None
        self._connected = False

    async def _connect(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self.redis_url, decode_responses=True,
                    socket_connect_timeout=2, socket_timeout=5,
                )
                await self._redis.ping()
                self._connected = True
            except Exception:
                self._connected = False
                self._redis = None

    def _state_key(self, task_id: str) -> str:
        return f"{self.key_prefix}{task_id}"

    def _trace_key(self, task_id: str) -> str:
        return f"{self.key_prefix}trace:{task_id}"

    def _serialize_state(self, state: TaskState) -> dict:
        return {
            "task_id": state.task_id,
            "user_input": state.user_input,
            "intent": state.intent.value if state.intent else None,
            "status": state.status.value if state.status else None,
            "plan": {
                "steps": [
                    {
                        "step": s.step, "lane": s.lane.value,
                        "goal": s.goal, "agent_role": s.agent_role,
                        "input_prompt": s.input_prompt,
                        "status": s.status.value,
                        "result": s.result, "error": s.error,
                        "retries": s.retries, "max_retries": s.max_retries,
                    }
                    for s in (state.plan.steps if state.plan else [])
                ],
                "intent": state.plan.intent.value if state.plan and state.plan.intent else None,
                "constraints": list(state.plan.constraints) if state.plan else [],
                "raw_llm_output": state.plan.raw_llm_output if state.plan else "",
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
            "current_step_index": state.current_step_index,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }

    def _deserialize_state(self, data: dict) -> TaskState:
        state = TaskState(
            task_id=data.get("task_id", uuid.uuid4().hex[:12]),
            user_input=data.get("user_input", ""),
            intent=TaskIntent(data["intent"]) if data.get("intent") and data["intent"] in [e.value for e in TaskIntent] else TaskIntent.GENERAL,
            status=TaskStatus(data["status"]) if data.get("status") and data["status"] in [e.value for e in TaskStatus] else TaskStatus.PENDING,
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )
        plan_data = data.get("plan")
        if plan_data:
            from orchestra.code_agent.orchestrator.router.models import TaskIntent as TI, ModelLane, TaskStep, RouterPlan
            steps = []
            for s in plan_data.get("steps", []):
                lane_val = s.get("lane", "fallback_3b")
                lane = lane_val if isinstance(lane_val, ModelLane) else (ModelLane(lane_val) if lane_val in [e.value for e in ModelLane] else ModelLane.FALLBACK_3B)
                step_status_val = s.get("status", "pending")
                step_status = step_status_val if isinstance(step_status_val, StepStatus) else (StepStatus(step_status_val) if step_status_val in [e.value for e in StepStatus] else StepStatus.PENDING)
                steps.append(TaskStep(
                    step=s.get("step", 0), lane=lane,
                    goal=s.get("goal", ""),
                    agent_role=s.get("agent_role", ""),
                    input_prompt=s.get("input_prompt", ""),
                    status=step_status,
                    result=s.get("result"), error=s.get("error"),
                    retries=s.get("retries", 0),
                    max_retries=s.get("max_retries", 2),
                ))
            intent_val = plan_data.get("intent")
            plan_intent = intent_val if isinstance(intent_val, TI) else (TI(intent_val) if intent_val and intent_val in [e.value for e in TI] else None)
            state.plan = RouterPlan(
                steps=steps,
                intent=plan_intent or TI.GENERAL,
                constraints=plan_data.get("constraints", []),
                raw_llm_output=plan_data.get("raw_llm_output", ""),
            )
        for h in data.get("history", []):
            lane_val = h.get("lane", "fallback_3b")
            lane = lane_val if isinstance(lane_val, ModelLane) else (ModelLane(lane_val) if lane_val in [e.value for e in ModelLane] else ModelLane.FALLBACK_3B)
            step_status_val = h.get("status", "success")
            step_status = step_status_val if isinstance(step_status_val, StepStatus) else (StepStatus(step_status_val) if step_status_val in [e.value for e in StepStatus] else StepStatus.SUCCESS)
            state.history.append(StepResult(
                step=h.get("step", 0), lane=lane,
                agent_role=h.get("agent_role", ""),
                status=step_status,
                output=h.get("output"), error=h.get("error"),
            ))
        state.final_output = data.get("final_output")
        state.current_step_index = data.get("current_step_index", 0)
        return state

    async def _redis_set(self, key: str, value: dict):
        if not self._connected:
            return
        try:
            await self._redis.setex(key, self.ttl, json.dumps(value, default=str))
        except Exception:
            pass

    async def _redis_get(self, key: str) -> dict | None:
        if not self._connected:
            return None
        try:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _redis_delete(self, key: str):
        if not self._connected:
            return
        try:
            await self._redis.delete(key)
        except Exception:
            pass

    async def _redis_lpush(self, key: str, value: dict):
        if not self._connected:
            return
        try:
            await self._redis.lpush(key, json.dumps(value, default=str))
            await self._redis.expire(key, self.ttl)
        except Exception:
            pass

    async def _redis_lrange(self, key: str) -> list[dict]:
        if not self._connected:
            return []
        try:
            raw = await self._redis.lrange(key, 0, -1)
            return [json.loads(r) for r in raw] if raw else []
        except Exception:
            return []

    # ── Override StateGraph methods ──

    def create_state(self, user_input: str, intent: str = "general") -> TaskState:
        import anyio
        state = super().create_state(user_input, intent)
        try:
            anyio.from_thread.run(self._push_to_redis, state)
        except Exception:
            pass
        return state

    async def _push_to_redis(self, state: TaskState):
        await self._connect()
        await self._redis_set(self._state_key(state.task_id), self._serialize_state(state))

    def get_state(self, task_id: str) -> TaskState | None:
        import anyio
        local = self._states.get(task_id)
        if local:
            return local
        try:
            data = anyio.from_thread.run(self._pull_from_redis, task_id)
            if data:
                state = self._deserialize_state(data)
                self._states[task_id] = state
                return state
        except Exception:
            pass
        return None

    async def _pull_from_redis(self, task_id: str) -> dict | None:
        await self._connect()
        return await self._redis_get(self._state_key(task_id))

    def update_plan(self, task_id: str, plan: RouterPlan) -> None:
        super().update_plan(task_id, plan)
        import anyio
        state = self._states.get(task_id)
        if state:
            try:
                anyio.from_thread.run(self._push_to_redis, state)
            except Exception:
                pass

    def add_step_result(self, task_id: str, result: StepResult) -> None:
        super().add_step_result(task_id, result)
        import anyio
        state = self._states.get(task_id)
        if state:
            try:
                anyio.from_thread.run(self._push_to_redis, state)
            except Exception:
                pass

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        super().set_status(task_id, status)
        import anyio
        state = self._states.get(task_id)
        if state:
            try:
                anyio.from_thread.run(self._push_to_redis, state)
            except Exception:
                pass

    def delete_state(self, task_id: str) -> bool:
        ok = super().delete_state(task_id)
        import anyio
        try:
            anyio.from_thread.run(self._redis_delete, self._state_key(task_id))
            anyio.from_thread.run(self._redis_delete, self._trace_key(task_id))
        except Exception:
            pass
        return ok

    def _append_trace(self, task_id: str, event: str, data: dict) -> None:
        super()._append_trace(task_id, event, data)
        import anyio
        try:
            entry = {"event": event, "data": data, "timestamp": time.time()}
            anyio.from_thread.run(self._redis_lpush, self._trace_key(task_id), entry)
        except Exception:
            pass

    def get_trace(self, task_id: str) -> list[dict]:
        local = self._traces.get(task_id)
        if local:
            return local
        import anyio
        try:
            data = anyio.from_thread.run(self._redis_lrange, self._trace_key(task_id))
            if data:
                self._traces[task_id] = data
                return data
        except Exception:
            pass
        return []


from orchestra.code_agent.orchestrator.router.models import TaskIntent, ModelLane
