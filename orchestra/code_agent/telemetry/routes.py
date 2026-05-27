from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException

from orchestra.code_agent.telemetry.tracer import AgentTracer


def register_telemetry_routes(app, prefix: str = "/api/telemetry"):
    router = APIRouter(prefix=prefix)
    tracer = AgentTracer.get()

    @router.post("/traces")
    async def start_trace():
        trace_id = tracer.start_trace()
        return {"trace_id": trace_id}

    @router.post("/traces/{trace_id}/spans")
    async def start_span(trace_id: str, body: dict):
        ctx = tracer.get_trace(trace_id)
        if not ctx:
            raise HTTPException(404, "Trace not found")
        name = body.get("name", "")
        if not name:
            raise HTTPException(400, "name is required")
        parent_id = body.get("parent_id", "")
        attributes = body.get("attributes", {})
        span_id = tracer.start_span(trace_id, name, parent_id=parent_id, attributes=attributes)
        return {"trace_id": trace_id, "span_id": span_id}

    @router.put("/traces/{trace_id}/spans/{span_id}")
    async def end_span(trace_id: str, span_id: str, body: dict | None = None):
        body = body or {}
        ctx = tracer.get_trace(trace_id)
        if not ctx:
            raise HTTPException(404, "Trace not found")
        status = body.get("status", "ok")
        tracer.end_span(trace_id, span_id, status=status)
        return {"trace_id": trace_id, "span_id": span_id, "status": status}

    @router.get("/traces/{trace_id}")
    async def get_trace(trace_id: str):
        ctx = tracer.get_trace(trace_id)
        if not ctx:
            raise HTTPException(404, "Trace not found")
        summary = tracer.summary(trace_id)
        span_list = [
            {
                "span_id": s.span_id,
                "parent_id": s.parent_id,
                "name": s.name,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "duration_ms": round(s.duration_ms(), 2),
                "status": s.status,
                "attributes": s.attributes,
            }
            for s in ctx.spans
        ]
        return {
            "trace_id": trace_id,
            "spans": span_list,
            "span_count": summary.get("spans", len(span_list)),
            "total_duration_ms": summary.get("total_duration_ms", 0),
            "errors": summary.get("errors", 0),
        }

    @router.get("/traces/{trace_id}/summary")
    async def get_trace_summary(trace_id: str):
        ctx = tracer.get_trace(trace_id)
        if not ctx:
            raise HTTPException(404, "Trace not found")
        return tracer.summary(trace_id)

    @router.get("/traces")
    async def list_traces():
        active = list(tracer._contexts.keys())
        return {
            "traces": [
                tracer.summary(tid)
                for tid in active
            ],
            "count": len(active),
        }

    @router.delete("/traces/{trace_id}")
    async def delete_trace(trace_id: str):
        if trace_id not in tracer._contexts:
            raise HTTPException(404, "Trace not found")
        del tracer._contexts[trace_id]
        return {"trace_id": trace_id, "status": "deleted"}

    @router.get("/health")
    async def telemetry_health():
        return {
            "active_traces": len(tracer._contexts),
            "output_path": str(tracer.path),
            "output_exists": tracer.path.exists(),
        }

    app.include_router(router)
