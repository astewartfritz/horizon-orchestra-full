from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from orchestra.code_agent.scaling import (
    CircuitBreaker, CircuitBreakerRegistry, CircuitState,
    DistributedTaskQueue, EdgeAdapter, EdgeMode,
    QueuePriority, QueueTask,
    ScalingManager, ScalingConfig,
    WorkerPool,
)
from orchestra.code_agent.scaling.redis_state import RedisStateGraph


def register_scaling_routes(
    app: Any,
    prefix: str = "/api/scaling",
    redis_url: str = "redis://localhost:6379/0",
    task_queue: DistributedTaskQueue | None = None,
    worker_pool: WorkerPool | None = None,
    scaling_manager: ScalingManager | None = None,
    breaker_registry: CircuitBreakerRegistry | None = None,
    edge_adapter: EdgeAdapter | None = None,
    redis_state: RedisStateGraph | None = None,
) -> None:
    tq = task_queue or DistributedTaskQueue(redis_url=redis_url)
    br = breaker_registry or CircuitBreakerRegistry()
    sm = scaling_manager or ScalingManager()
    ea = edge_adapter or EdgeAdapter()
    rs = redis_state or RedisStateGraph(redis_url=redis_url)

    router = APIRouter(prefix=prefix)

    # ── Queue endpoints ──

    @router.post("/queue/enqueue")
    async def enqueue(body: dict[str, Any]):
        user_input = body.get("input", "")
        if not user_input:
            raise HTTPException(400, "input is required")
        task = QueueTask(
            user_input=user_input,
            intent=body.get("intent", "general"),
            priority=QueuePriority(body.get("priority", 2)),
            rate_limit_key=body.get("rate_limit_key", ""),
            metadata=body.get("metadata", {}),
        )
        ok = await tq.enqueue(task)
        if not ok:
            raise HTTPException(503, "queue full or rate limited")
        return {"task_id": task.task_id, "status": "enqueued"}

    @router.get("/queue/depth")
    async def queue_depth():
        return {"depth": await tq.depth(), "total": sum((await tq.depth()).values())}

    @router.get("/queue/backpressure")
    async def backpressure():
        return {"backpressured": await tq.is_backpressured()}

    @router.get("/queue/processing")
    async def processing():
        return {"count": await tq.processing_count()}

    @router.get("/queue/dlq")
    async def dlq():
        return {"count": await tq.dlq_count()}

    @router.post("/queue/ack/{task_id}")
    async def ack(task_id: str, body: dict[str, Any]):
        success = body.get("success", True)
        result = body.get("result")
        error = body.get("error")
        ok = await tq.ack(task_id, success=success, result=result, error=error)
        if not ok:
            raise HTTPException(404, "task not found")
        return {"status": "acknowledged"}

    @router.post("/queue/nack/{task_id}")
    async def nack(task_id: str):
        ok = await tq.nack(task_id)
        if not ok:
            raise HTTPException(404, "task not found")
        return {"status": "nacked"}

    # ── Circuit breaker endpoints ──

    @router.get("/circuits")
    async def list_circuits():
        return {"circuits": br.all_summaries()}

    @router.post("/circuits/{name}/record-success")
    async def record_success(name: str):
        br.record_success(name)
        return {"status": "recorded"}

    @router.post("/circuits/{name}/record-failure")
    async def record_failure(name: str):
        br.record_failure(name)
        return {"status": "recorded"}

    @router.post("/circuits/{name}/reset")
    async def reset_circuit(name: str):
        cb = br._breakers.get(name)
        if cb:
            cb.reset()
        return {"status": "reset"}

    @router.post("/circuits/reset-all")
    async def reset_all():
        br.reset_all()
        return {"status": "all reset"}

    # ── Scaling manager endpoints ──

    @router.post("/scaling/evaluate")
    async def evaluate():
        decision = await sm.evaluate()
        return {
            "action": decision.action.value,
            "target_size": decision.target_size,
            "reason": decision.reason,
            "metrics": decision.metrics,
        }

    @router.get("/scaling/history")
    async def scaling_history():
        return {"decisions": [{
            "action": d.action.value,
            "target_size": d.target_size,
            "reason": d.reason,
            "timestamp": d.timestamp,
        } for d in sm.get_history()]}

    # ── Edge adapter endpoints ──

    @router.post("/edge/infer")
    async def edge_infer(body: dict[str, Any]):
        prompt = body.get("prompt", "")
        lane = body.get("lane", "general")
        if not prompt:
            raise HTTPException(400, "prompt is required")
        result, error = await ea.infer(prompt, lane)
        if error:
            raise HTTPException(500, error)
        return {"result": result}

    @router.get("/edge/status")
    async def edge_status():
        return {
            "mode": ea.mode.value,
            "cache_size": ea.cache_size,
            "privacy_mode": ea.privacy_mode,
            "model": ea.ollama_model if ea.mode == EdgeMode.OLLAMA else ea.model_path,
        }

    # ── Redis state endpoints ──

    @router.get("/state/{task_id}")
    async def get_state(task_id: str):
        state = rs.get_state(task_id)
        if not state:
            raise HTTPException(404, "task not found")
        return {
            "task_id": state.task_id,
            "status": state.status.value if state.status else None,
            "intent": state.intent.value if state.intent else None,
            "steps": len(state.history),
            "final_output": state.final_output,
        }

    @router.delete("/state/{task_id}")
    async def delete_state(task_id: str):
        ok = rs.delete_state(task_id)
        if not ok:
            raise HTTPException(404, "task not found")
        return {"status": "deleted"}

    # ── Health ──

    @router.get("/health")
    async def health():
        return {
            "service": "scaling",
            "redis_url": redis_url,
            "queue_depth": sum((await tq.depth()).values()),
            "processing": await tq.processing_count(),
            "dlq": await tq.dlq_count(),
            "circuits": len(br.all_summaries()),
        }

    app.include_router(router)
