from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from code_agent.active_agents.registry import build_default_registry
from code_agent.nemotron.classifier import NemotronClassifier
from code_agent.nemotron.dispatch import NemotronDispatch
from code_agent.nemotron.router import NemotronRouter


class _RouteRequest(BaseModel):
    task: str
    context: dict = {}
    skip_health_check: bool = False


class _ClassifyRequest(BaseModel):
    task: str


def _build_dispatch() -> NemotronDispatch:
    registry = build_default_registry()
    classifier = NemotronClassifier()

    # Wire in RL routing policy so Nemotron benefits from past experience
    try:
        from code_agent.rl.policy import RoutingPolicy
        from code_agent.rl.loop import FeedbackLoop
        from code_agent.rl.buffer import ExperienceBuffer
        from code_agent.rl.trainer import OrchestraTrainer
        policy = RoutingPolicy()
        router = NemotronRouter(registry, classifier, policy=policy)
        buf = ExperienceBuffer()
        trainer = OrchestraTrainer(buf, policy)
        feedback = FeedbackLoop(buffer=buf, policy=policy, trainer=trainer)
        dispatch = NemotronDispatch(router, feedback_loop=feedback)
    except Exception:
        router = NemotronRouter(registry, classifier)
        dispatch = NemotronDispatch(router)

    return dispatch


_dispatch: NemotronDispatch | None = None


def _get_dispatch() -> NemotronDispatch:
    global _dispatch
    if _dispatch is None:
        _dispatch = _build_dispatch()
    return _dispatch


def register_nemotron_routes(app: Any, prefix: str = "/api/nemotron") -> None:
    """Register Nemotron routing REST endpoints on the given FastAPI app."""
    from fastapi import HTTPException

    @app.post(f"{prefix}/route")
    async def route_and_execute(req: _RouteRequest):
        """Route task via Nemotron and execute with the selected agent."""
        dispatch = _get_dispatch()
        record = await dispatch.dispatch(
            req.task,
            context=req.context or None,
            skip_health_check=req.skip_health_check,
        )
        return {
            "success": record.result.success,
            "output": record.result.output,
            "error": record.result.error,
            "agent_used": record.result.agent_name,
            "routing": record.decision.to_dict(),
            "total_duration_ms": record.total_duration_ms,
        }

    @app.post(f"{prefix}/classify")
    async def classify_task(req: _ClassifyRequest):
        """Classify a task and return routing recommendation without executing."""
        dispatch = _get_dispatch()
        router = dispatch._router
        decision = await router.route(req.task, skip_health_check=True)
        return decision.to_dict()

    @app.get(f"{prefix}/agents")
    async def list_agents():
        """List all registered active agents with their capabilities."""
        dispatch = _get_dispatch()
        registry = dispatch._router._registry
        health = await registry.run_health_checks()
        agents = []
        for agent in registry.all_agents():
            h = health.get(agent.name)
            agents.append({
                **agent.to_dict(),
                "health": {
                    "status": h.status.value if h else "unknown",
                    "detail": h.detail if h else "",
                    "latency_ms": h.latency_ms if h else 0,
                },
            })
        return {"agents": agents, "count": len(agents)}

    @app.get(f"{prefix}/agents/{'{name}'}/health")
    async def agent_health(name: str):
        """Get health status for a specific agent."""
        dispatch = _get_dispatch()
        registry = dispatch._router._registry
        agent = registry.get(name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        status = await agent.health_check()
        return {
            "agent": name,
            "status": status.status.value,
            "version": status.version,
            "detail": status.detail,
            "latency_ms": status.latency_ms,
        }

    @app.get(f"{prefix}/history")
    async def dispatch_history(limit: int = 20):
        """Recent dispatch records."""
        dispatch = _get_dispatch()
        return {"history": dispatch.history(limit=limit)}

    @app.get(f"{prefix}/stats")
    async def dispatch_stats():
        """Aggregate dispatch statistics."""
        return _get_dispatch().stats()
