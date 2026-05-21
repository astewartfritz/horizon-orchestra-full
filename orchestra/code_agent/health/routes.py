from __future__ import annotations

from orchestra.code_agent.health.checker import HealthChecker

__all__ = ["register_health_routes"]


def register_health_routes(app: object) -> None:
    try:
        from fastapi import APIRouter
        from fastapi.responses import JSONResponse
    except ImportError:
        return

    router = APIRouter(prefix="", tags=["health"])
    checker = HealthChecker()

    @router.get("/health")
    async def health_check():
        report = checker.run_all()
        status_code = 200 if report.overall == "ok" else 503
        return JSONResponse(content=report.to_dict(), status_code=status_code)

    @router.get("/health/ready")
    async def readiness():
        report = checker.run_all()
        status_code = 200 if report.overall == "ok" else 503
        return JSONResponse(content={"status": report.overall, "checks": [
            {"name": c.name, "status": c.status} for c in report.checks
        ]}, status_code=status_code)

    @router.get("/health/live")
    async def liveness():
        return JSONResponse(content={"status": "alive"})

    app.include_router(router)
