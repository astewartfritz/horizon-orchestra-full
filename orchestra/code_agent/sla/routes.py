from __future__ import annotations

from orchestra.code_agent.sla.calculator import SlaTracker

__all__ = ["register_sla_routes"]

_SLA = SlaTracker()
for _g in SlaTracker.default_guarantees():
    _SLA.register(_g)


def register_sla_routes(app: object) -> None:
    try:
        from fastapi import APIRouter
        from fastapi.responses import JSONResponse
    except ImportError:
        return

    router = APIRouter(prefix="/api/sla", tags=["sla"])

    @router.get("/guarantees")
    async def list_guarantees():
        return JSONResponse(content=[
            {"name": g.name, "target_ms": g.target_ms,
             "tolerance_pct": g.tolerance_pct, "description": g.description}
            for g in _SLA.list_guarantees()
        ])

    @router.get("/report/{guarantee_name}")
    async def sla_report(guarantee_name: str, window: float = 3600.0):
        report = _SLA.report(guarantee_name, window)
        if report is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Guarantee '{guarantee_name}' not found")
        return JSONResponse(content={
            "guarantee_name": report.guarantee_name,
            "total_requests": report.total_requests,
            "met": report.met,
            "violated": report.violated,
            "compliance_pct": report.compliance_pct,
            "p50_ms": report.p50_ms,
            "p95_ms": report.p95_ms,
            "p99_ms": report.p99_ms,
            "window_seconds": report.window_seconds,
        })

    app.include_router(router)
