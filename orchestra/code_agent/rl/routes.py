from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from orchestra.code_agent.rl.buffer import ExperienceBuffer
from orchestra.code_agent.rl.loop import FeedbackLoop
from orchestra.code_agent.rl.policy import RoutingPolicy
from orchestra.code_agent.rl.trainer import OrchestraTrainer


class _TrainRequest(BaseModel):
    run_lora: bool = False


class _ResetRequest(BaseModel):
    agent_name: str | None = None

_loop: FeedbackLoop | None = None


def _get_loop() -> FeedbackLoop:
    global _loop
    if _loop is None:
        buf = ExperienceBuffer()
        pol = RoutingPolicy()
        trainer = OrchestraTrainer(buf, pol)
        _loop = FeedbackLoop(buffer=buf, policy=pol, trainer=trainer)
    return _loop


def register_rl_routes(app: Any, prefix: str = "/api/rl") -> None:
    from fastapi import HTTPException

    @app.get(f"{prefix}/stats")
    async def rl_stats():
        """Full RL pipeline stats: buffer, policy, trainer."""
        return _get_loop().stats()

    @app.get(f"{prefix}/buffer/recent")
    async def buffer_recent(limit: int = 20):
        """Most recent training signals in the experience buffer."""
        return {"signals": _get_loop()._buffer.recent(limit=limit)}

    @app.get(f"{prefix}/buffer/stats")
    async def buffer_stats():
        """Aggregate buffer stats by agent and task category."""
        return _get_loop()._buffer.stats()

    @app.get(f"{prefix}/buffer/pairs")
    async def preference_pairs(limit: int = 100):
        """Preference pairs (winner/loser) for DPO-style training."""
        return {"pairs": _get_loop()._buffer.preference_pairs(limit=limit)}

    @app.delete(f"{prefix}/buffer")
    async def clear_buffer():
        """Clear all training signals (reset learning data)."""
        deleted = _get_loop()._buffer.clear()
        return {"deleted": deleted, "message": "Experience buffer cleared"}

    @app.get(f"{prefix}/policy")
    async def policy_table():
        """Full routing policy table — all (agent, category, ema_reward) entries."""
        return {"entries": _get_loop()._policy.all_entries()}

    @app.get(f"{prefix}/policy/rankings")
    async def agent_rankings(task_category: str):
        """Agent rankings by learned EMA reward for a given task category."""
        return {
            "task_category": task_category,
            "rankings": _get_loop()._policy.agent_rankings(task_category),
        }

    @app.get(f"{prefix}/policy/summary")
    async def policy_summary():
        """Policy summary — top performers and total entries."""
        return _get_loop()._policy.summary()

    @app.post(f"{prefix}/policy/reset")
    async def reset_policy(req: _ResetRequest):
        """Reset policy for a specific agent or all agents."""
        loop = _get_loop()
        if req.agent_name:
            count = loop._policy.reset_agent(req.agent_name)
            return {"reset": count, "agent": req.agent_name}
        else:
            count = loop._policy.reset_all()
            return {"reset": count, "message": "Full policy reset"}

    @app.post(f"{prefix}/train")
    async def trigger_training(req: _TrainRequest):
        """Manually trigger a training cycle (policy update + optional LoRA)."""
        loop = _get_loop()
        report = loop._trainer.train(run_lora=req.run_lora)
        return report.to_dict()

    @app.get(f"{prefix}/train/history")
    async def training_history(limit: int = 10):
        """Recent training cycle reports."""
        return {"reports": _get_loop()._trainer.last_reports(limit)}
