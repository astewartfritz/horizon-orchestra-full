from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ScalingAction(str, Enum):
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    HOLD = "hold"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class ScalingDecision:
    action: ScalingAction
    target_size: int
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScalingConfig:
    min_workers: int = 2
    max_workers: int = 100
    scale_up_threshold: int = 5_000
    scale_down_threshold: int = 500
    cooldown_seconds: float = 30.0
    cpu_high_threshold: float = 80.0
    cpu_low_threshold: float = 20.0
    latency_p99_high_ms: float = 5_000.0
    error_rate_high: float = 0.05
    target_workers_per_queue_depth: int = 50


class ScalingManager:
    """Metrics-driven auto-scaler for the worker pool.

    Reads queue depth, processing count, DLQ count, and latency,
    then decides whether to scale up/down the worker pool.
    """

    def __init__(
        self,
        config: ScalingConfig | None = None,
        get_queue_depth: callable | None = None,
        get_processing_count: callable | None = None,
        get_dlq_count: callable | None = None,
        get_current_workers: callable | None = None,
        scale_fn: callable | None = None,
    ):
        self.config = config or ScalingConfig()
        self._get_queue_depth = get_queue_depth or (lambda: {})
        self._get_processing_count = get_processing_count or (lambda: 0)
        self._get_dlq_count = get_dlq_count or (lambda: 0)
        self._get_current_workers = get_current_workers or (lambda: self.config.min_workers)
        self._scale_fn = scale_fn or (lambda n: None)
        self._last_scale_time: float = 0
        self._decisions: list[ScalingDecision] = []

    async def evaluate(self) -> ScalingDecision:
        queue_depth = await self._get_queue_depth() if asyncio.iscoroutinefunction(self._get_queue_depth) else self._get_queue_depth()
        processing = await self._get_processing_count() if asyncio.iscoroutinefunction(self._get_processing_count) else self._get_processing_count()
        dlq = await self._get_dlq_count() if asyncio.iscoroutinefunction(self._get_dlq_count) else self._get_dlq_count()

        total_depth = sum(queue_depth.values()) if isinstance(queue_depth, dict) else (queue_depth or 0)
        current_workers = self._get_current_workers()

        now = time.time()
        in_cooldown = (now - self._last_scale_time) < self.config.cooldown_seconds

        metrics = {
            "queue_depth": total_depth,
            "processing": processing,
            "dlq_count": dlq,
            "current_workers": current_workers,
            "in_cooldown": in_cooldown,
        }

        # Emergency: DLQ growing fast
        if dlq > 100 and total_depth > self.config.scale_up_threshold * 2:
            decision = ScalingDecision(
                action=ScalingAction.EMERGENCY_STOP,
                target_size=current_workers,
                reason=f"DLQ={dlq} + queue_depth={total_depth} — possible cascade failure",
                metrics=metrics,
            )
            self._decisions.append(decision)
            return decision

        if in_cooldown:
            return ScalingDecision(
                action=ScalingAction.HOLD, target_size=current_workers,
                reason=f"in cooldown ({now - self._last_scale_time:.1f}s < {self.config.cooldown_seconds}s)",
                metrics=metrics,
            )

        # Scale up
        if total_depth > self.config.scale_up_threshold:
            target = min(
                current_workers + (total_depth // self.config.target_workers_per_queue_depth),
                self.config.max_workers,
            )
            if target > current_workers:
                self._last_scale_time = now
                decision = ScalingDecision(
                    action=ScalingAction.SCALE_UP, target_size=target,
                    reason=f"queue_depth={total_depth} > threshold={self.config.scale_up_threshold}",
                    metrics=metrics,
                )
                self._decisions.append(decision)
                await self._apply(decision)
                return decision

        # Scale down
        if total_depth < self.config.scale_down_threshold and current_workers > self.config.min_workers:
            target = max(
                current_workers - 1,
                self.config.min_workers,
            )
            self._last_scale_time = now
            decision = ScalingDecision(
                action=ScalingAction.SCALE_DOWN, target_size=target,
                reason=f"queue_depth={total_depth} < threshold={self.config.scale_down_threshold}",
                metrics=metrics,
            )
            self._decisions.append(decision)
            await self._apply(decision)
            return decision

        return ScalingDecision(
            action=ScalingAction.HOLD, target_size=current_workers,
            reason=f"queue_depth={total_depth} within thresholds [{self.config.scale_down_threshold}, {self.config.scale_up_threshold}]",
            metrics=metrics,
        )

    async def _apply(self, decision: ScalingDecision):
        if decision.action == ScalingAction.SCALE_UP or decision.action == ScalingAction.SCALE_DOWN:
            try:
                if asyncio.iscoroutinefunction(self._scale_fn):
                    await self._scale_fn(decision.target_size)
                else:
                    self._scale_fn(decision.target_size)
            except Exception as e:
                logger.error(f"Scale failed: {e}")

    def get_history(self, limit: int = 20) -> list[ScalingDecision]:
        return self._decisions[-limit:]
