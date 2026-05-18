from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from code_agent.council.council import ModelCouncil
from code_agent.council.scorer import QualityGate, categorise_task


class _EvaluateRequest(BaseModel):
    task: str
    output: str
    agent_name: str = "unknown"


class _GateRequest(BaseModel):
    task: str
    output: str
    agent_name: str = "unknown"


_council: ModelCouncil | None = None
_gate: QualityGate | None = None


def _get_council() -> ModelCouncil:
    global _council
    if _council is None:
        _council = ModelCouncil()
    return _council


def _get_gate() -> QualityGate:
    global _gate
    if _gate is None:
        _gate = QualityGate()
    return _gate


def register_council_routes(app: Any, prefix: str = "/api/council") -> None:

    @app.post(f"{prefix}/evaluate")
    async def evaluate(req: _EvaluateRequest):
        """Run model council scoring on a task+output pair."""
        council = _get_council()
        verdict = await council.evaluate(req.task, req.output, req.agent_name)
        return verdict.to_dict()

    @app.post(f"{prefix}/gate")
    async def quality_gate(req: _GateRequest):
        """Run council + quality gate; returns reward signal."""
        council = _get_council()
        gate = _get_gate()
        verdict = await council.evaluate(req.task, req.output, req.agent_name)
        result = gate.evaluate(verdict, req.task)
        return result.to_dict()

    @app.get(f"{prefix}/judges")
    async def list_judges():
        """List active judges in the council."""
        council = _get_council()
        return {
            "judges": [
                {"judge_id": j.judge_id, "backend": j._backend, "model": j._model}
                for j in council._judges
            ],
            "count": len(council._judges),
        }

    @app.get(f"{prefix}/categorise")
    async def categorise(task: str):
        """Classify a task string into a task category."""
        return {"task_category": categorise_task(task)}
