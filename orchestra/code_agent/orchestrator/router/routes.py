from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from orchestra.code_agent.orchestrator.router import (
    AgentRouter, Engine, RouterConfig,
)
from orchestra.code_agent.orchestrator.router.models import TaskIntent, TaskStatus


def register_router_orchestrator_routes(app: Any, prefix: str = "/api/router") -> None:
    config = RouterConfig()
    engine = Engine(config)
    agent_router = AgentRouter(config)

    router = APIRouter(prefix=prefix)

    # ── Full lifecycle: IngestTask → PlanTask → EnqueueSteps → ExecuteStep → UserResponse ──

    @router.post("/run")
    async def run(body: dict[str, Any]):
        user_input = body.get("input", "")
        if not user_input:
            raise HTTPException(400, "input is required")
        intent_str = body.get("intent")
        intent = TaskIntent(intent_str) if intent_str and intent_str in [e.value for e in TaskIntent] else None
        state = await engine.run(user_input, intent)
        return {
            "task_id": state.task_id,
            "status": state.status.value,
            "intent": state.intent.value if state.intent else None,
            "steps": [
                {"step": h.step, "lane": h.lane.value, "status": h.status.value, "output": h.output}
                for h in state.history
            ],
            "final_output": state.final_output,
        }

    # ── Individual stages ──

    @router.post("/ingest")
    async def ingest(body: dict[str, Any]):
        user_input = body.get("input", "")
        if not user_input:
            raise HTTPException(400, "input is required")
        intent_str = body.get("intent")
        intent = TaskIntent(intent_str) if intent_str and intent_str in [e.value for e in TaskIntent] else None
        state = engine.ingest(user_input, intent)
        return {"task_id": state.task_id, "status": state.status.value}

    @router.post("/plan/{task_id}")
    async def plan(task_id: str):
        plan = await engine.plan(task_id)
        return {
            "task_id": task_id,
            "steps": [{"step": s.step, "lane": s.lane.value, "goal": s.goal} for s in plan.steps],
        }

    @router.post("/enqueue/{task_id}")
    async def enqueue(task_id: str):
        state = engine.enqueue(task_id)
        return {
            "task_id": task_id,
            "status": state.status.value,
            "steps": [
                {"step": s.step, "lane": s.lane.value, "goal": s.goal}
                for s in (state.plan.steps if state.plan else [])
            ],
        }

    @router.post("/execute/{task_id}")
    async def execute(task_id: str):
        state = await engine.execute(task_id)
        return {
            "task_id": task_id,
            "status": state.status.value,
            "steps": [
                {"step": h.step, "lane": h.lane.value, "status": h.status.value, "output": h.output}
                for h in state.history
            ],
            "final_output": state.final_output,
        }

    # ── State management ──

    @router.get("/state/{task_id}")
    async def get_state(task_id: str):
        state = engine.state_graph.get_state(task_id)
        if not state:
            raise HTTPException(404, "task not found")
        return {
            "task_id": state.task_id,
            "user_input": state.user_input,
            "intent": state.intent.value if state.intent else None,
            "status": state.status.value,
            "plan": {
                "steps": [
                    {"step": s.step, "lane": s.lane.value, "goal": s.goal, "status": s.status.value}
                    for s in (state.plan.steps if state.plan else [])
                ]
            } if state.plan else None,
            "history": [
                {"step": h.step, "lane": h.lane.value, "status": h.status.value, "output": h.output}
                for h in state.history
            ],
            "final_output": state.final_output,
        }

    @router.get("/trace/{task_id}")
    async def get_trace(task_id: str):
        trace = engine.state_graph.export_trace(task_id)
        if not trace:
            raise HTTPException(404, "task not found")
        return trace

    @router.get("/states")
    async def list_states(status: str | None = None, limit: int = 50):
        states = engine.state_graph.list_states(status, limit)
        return {
            "states": [
                {
                    "task_id": s.task_id,
                    "user_input": s.user_input[:100],
                    "intent": s.intent.value if s.intent else None,
                    "status": s.status.value,
                    "steps": len(s.history),
                }
                for s in states
            ],
            "count": len(states),
        }

    @router.delete("/state/{task_id}")
    async def delete_state(task_id: str):
        ok = engine.state_graph.delete_state(task_id)
        if not ok:
            raise HTTPException(404, "task not found")
        return {"status": "deleted"}

    # ── AgentRouter info ──

    @router.get("/lanes")
    async def list_lanes():
        return {"lanes": agent_router.list_lanes()}

    @router.post("/route")
    async def route(body: dict[str, Any]):
        task_type = body.get("task_type", "")
        context = body.get("context", {})
        if not task_type:
            raise HTTPException(400, "task_type is required")
        lane, model = agent_router.route(task_type, context)
        return {"lane": lane.value, "model": model}

    # ── Health ──

    @router.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "router-orchestrator",
            "state_count": len(engine.state_graph.list_states()),
            "lanes": len(agent_router.list_lanes()),
        }

    app.include_router(router)
