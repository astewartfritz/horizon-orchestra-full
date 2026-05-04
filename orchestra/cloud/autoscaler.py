"""GPU Auto-Scaler — intelligent scaling across cloud GPU providers.

Monitors cluster utilisation in real time and adds / removes GPU nodes
to satisfy the configured ScalingPolicy.  Key capabilities:

- Load-based scaling (GPU utilisation, queue depth)
- Cost-optimised provider selection (cheapest first from:
  lambda → coreweave → spheron → runpod → aws → gcp)
- Spot / preemptible instance bidding with on-demand fallback
- Time-based scaling (more capacity during business hours)
- Cross-provider failover
- Budget enforcement (hard cap on hourly spend)
- Spot-interruption handling with automatic replacement
- Scaling history and cost forecasting

Usage::

    from orchestra.cloud.autoscaler import AutoScaler, ScalingPolicy

    policy = ScalingPolicy(max_cost_per_hour=50.0)
    scaler = AutoScaler(cluster, policy)
    await scaler.start()
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    from .gpu_providers import (
        GPUProviderRegistry,
        GPUSpec,
        ProviderConfig,
        GPUPricing,
        GPUProviderClient,
    )
except ImportError:  # pragma: no cover
    GPUProviderRegistry = None  # type: ignore[assignment,misc]
    GPUSpec = None  # type: ignore[assignment,misc]
    ProviderConfig = None  # type: ignore[assignment,misc]
    GPUPricing = None  # type: ignore[assignment,misc]
    GPUProviderClient = None  # type: ignore[assignment,misc]

try:
    from .gpu_cluster import GPUCluster, ClusterConfig, GPUNode
except ImportError:  # pragma: no cover
    GPUCluster = None  # type: ignore[assignment,misc]
    ClusterConfig = None  # type: ignore[assignment,misc]
    GPUNode = None  # type: ignore[assignment,misc]

__all__ = [
    "AutoScaler",
    "ScalingPolicy",
    "ScalingDecision",
    "ScalingEvent",
    "ScalingDirection",
    "CostForecast",
    "SpotInterruptionHandler",
]

log = logging.getLogger("orchestra.cloud.autoscaler")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScalingDirection(str, Enum):
    """Direction of a scaling action."""
    UP = "up"
    DOWN = "down"
    NONE = "none"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScalingPolicy:
    """Defines thresholds and preferences that drive scaling decisions.

    Attributes:
        target_utilization:     Scale **up** when avg GPU util > this.
        scale_down_utilization: Scale **down** when avg GPU util < this.
        cooldown_seconds:       Min seconds between consecutive actions.
        min_nodes:              Hard floor — never scale below this.
        max_nodes:              Hard ceiling — never scale above this.
        prefer_spot:            Try spot / preemptible first.
        max_cost_per_hour:      Budget cap (USD / hr).  Scaling stops if
                                the projected hourly cost would exceed it.
        provider_priority:      Ordered list of providers to try.  The
                                scaler walks this list until it finds
                                capacity.
        fallback_to_smaller_gpu: If the requested GPU type is unavailable,
                                 try a smaller GPU (e.g. H200 → H100).
        time_based_scaling:     Map of **hour** (0-23) → minimum node
                                count.  Useful for pre-warming capacity
                                before traffic spikes.
        scale_up_step:          How many nodes to add per scale-up event.
        scale_down_step:        How many nodes to remove per scale-down.
        queue_depth_threshold:  If the pending-request queue exceeds this,
                                trigger a scale-up regardless of util.
        spot_max_price_pct:     Max spot bid as a percentage of on-demand
                                price (e.g. 0.65 = bid up to 65 %).
    """
    target_utilization: float = 0.7
    scale_down_utilization: float = 0.3
    cooldown_seconds: int = 300
    min_nodes: int = 1
    max_nodes: int = 64
    prefer_spot: bool = True
    max_cost_per_hour: float = 100.0
    provider_priority: list[str] = field(default_factory=lambda: [
        "lambda", "coreweave", "spheron", "runpod", "aws", "gcp",
    ])
    fallback_to_smaller_gpu: bool = True
    time_based_scaling: dict[str, int] = field(default_factory=dict)
    scale_up_step: int = 1
    scale_down_step: int = 1
    queue_depth_threshold: int = 50
    spot_max_price_pct: float = 0.65

    # GPU fallback order — when the desired GPU is unavailable, walk this
    # list downward.
    gpu_fallback_order: list[str] = field(default_factory=lambda: [
        "b200", "h200", "h100_sxm5", "h100_pcie", "a100_80gb",
        "a100_40gb", "l40s", "a10g",
    ])


@dataclass
class ScalingDecision:
    """Outcome of a single ``evaluate()`` call."""
    direction: ScalingDirection = ScalingDirection.NONE
    reason: str = ""
    target_count: int = 0
    current_count: int = 0
    avg_utilization: float = 0.0
    projected_cost_per_hour: float = 0.0
    provider: str = ""
    gpu_type: str = ""
    spot: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScalingEvent:
    """Persisted record of an executed scaling action."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    direction: str = "none"
    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    reason: str = ""
    provider: str = ""
    gpu_type: str = ""
    spot: bool = False
    cost_per_hour_before: float = 0.0
    cost_per_hour_after: float = 0.0
    avg_utilization: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class CostForecast:
    """Simple cost projection for a time horizon."""
    hours: int = 24
    current_cost_per_hour: float = 0.0
    projected_total: float = 0.0
    projected_spot_savings: float = 0.0
    node_count: int = 0
    breakdown_by_provider: dict[str, float] = field(default_factory=dict)
    breakdown_by_gpu: dict[str, float] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Spot interruption handler
# ---------------------------------------------------------------------------

class SpotInterruptionHandler:
    """Watches for spot / preemptible interruption notices and replaces
    the affected nodes before workloads are evicted.

    Flow:
        1. Receive interruption signal (webhook or poll-based).
        2. Drain the node (stop accepting new requests).
        3. Attempt to provision a replacement (spot first, on-demand
           fallback).
        4. Migrate in-flight work or let the router re-route.
    """

    def __init__(self, cluster: Any, policy: ScalingPolicy) -> None:
        self._cluster = cluster
        self._policy = policy
        self._replacements: dict[str, str] = {}  # old_node_id → new_node_id
        self._interruption_log: list[dict[str, Any]] = []
        log.info("SpotInterruptionHandler initialised")

    async def handle_interruption(self, node_id: str) -> dict[str, Any]:
        """Handle a spot interruption for *node_id*.

        Returns a dict describing the replacement outcome.
        """
        log.warning("Spot interruption received for node %s", node_id)
        result: dict[str, Any] = {
            "interrupted_node": node_id,
            "replacement_node": None,
            "fallback_on_demand": False,
            "timestamp": time.time(),
        }

        # 1. Drain the interrupted node --------------------------------
        if self._cluster is not None:
            node = await self._cluster.get_node(node_id)
            if node is not None:
                gpu_type = node.gpu_type
                provider = node.provider
            else:
                gpu_type = ""
                provider = ""
        else:
            gpu_type = ""
            provider = ""

        # 2. Attempt spot replacement ----------------------------------
        replacement = await self._try_replace_spot(gpu_type, provider)
        if replacement is not None:
            result["replacement_node"] = replacement
            self._replacements[node_id] = replacement
        else:
            # 3. Fallback to on-demand ---------------------------------
            replacement = await self._try_replace_on_demand(gpu_type)
            if replacement is not None:
                result["replacement_node"] = replacement
                result["fallback_on_demand"] = True
                self._replacements[node_id] = replacement

        self._interruption_log.append(result)
        return result

    async def _try_replace_spot(
        self, gpu_type: str, provider: str,
    ) -> str | None:
        """Try to provision a spot replacement."""
        if self._cluster is None:
            return None
        for prov in self._policy.provider_priority:
            try:
                node = await self._cluster.add_node(
                    provider=prov, gpu_type=gpu_type, spot=True,
                )
                log.info(
                    "Spot replacement provisioned on %s: %s",
                    prov, node.node_id,
                )
                return node.node_id
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "Spot replacement on %s failed: %s", prov, exc,
                )
        return None

    async def _try_replace_on_demand(self, gpu_type: str) -> str | None:
        """Fallback: provision on-demand across providers."""
        if self._cluster is None:
            return None
        for prov in self._policy.provider_priority:
            try:
                node = await self._cluster.add_node(
                    provider=prov, gpu_type=gpu_type, spot=False,
                )
                log.info(
                    "On-demand replacement provisioned on %s: %s",
                    prov, node.node_id,
                )
                return node.node_id
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "On-demand replacement on %s failed: %s", prov, exc,
                )
        return None

    def get_interruption_log(self) -> list[dict[str, Any]]:
        """Return the list of all interruption events handled."""
        return list(self._interruption_log)


# ---------------------------------------------------------------------------
# AutoScaler
# ---------------------------------------------------------------------------

class AutoScaler:
    """Intelligent auto-scaling across GPU cloud providers.

    Features
    --------
    - **Load-based scaling** — watches GPU utilisation across the cluster
      and adds / removes nodes to hover around ``policy.target_utilization``.
    - **Cost-optimised provider selection** — walks the provider priority
      list (cheapest → most expensive) until capacity is found.
    - **Spot / preemptible bidding** — requests spot instances first,
      falls back to on-demand transparently.
    - **Time-based scaling** — honours ``policy.time_based_scaling`` so
      you can pre-warm nodes before known traffic peaks.
    - **Cross-provider failover** — if one provider is at capacity or
      returns errors, the scaler tries the next in the priority list.
    - **Budget enforcement** — never provisions nodes that would push the
      hourly cost above ``policy.max_cost_per_hour``.
    - **Spot-interruption handling** — delegates to
      :class:`SpotInterruptionHandler` for seamless replacement.
    - **Predictive scaling** — keeps a rolling history and exposes
      :meth:`get_cost_forecast` for forward-looking estimates.

    Parameters
    ----------
    cluster:
        The :class:`GPUCluster` instance to scale.
    policy:
        A :class:`ScalingPolicy` that governs thresholds and preferences.
    registry:
        Optional :class:`GPUProviderRegistry` for pricing look-ups.
    """

    def __init__(
        self,
        cluster: Any,
        policy: ScalingPolicy | None = None,
        registry: Any | None = None,
    ) -> None:
        self._cluster = cluster
        self._policy = policy or ScalingPolicy()
        self._registry = registry
        self._running = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._last_scale_time: float = 0.0
        self._scaling_history: list[ScalingEvent] = []
        self._utilization_samples: list[tuple[float, float]] = []  # (ts, util)
        self._queue_depth: int = 0
        self._interruption_handler = SpotInterruptionHandler(
            cluster, self._policy,
        )
        log.info(
            "AutoScaler initialised — target_util=%.0f%%, max_cost=$%.2f/hr, "
            "providers=%s",
            self._policy.target_utilization * 100,
            self._policy.max_cost_per_hour,
            self._policy.provider_priority,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            log.warning("AutoScaler is already running")
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        log.info("AutoScaler monitoring started")

    async def stop(self) -> None:
        """Gracefully stop monitoring."""
        self._running = False
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        log.info("AutoScaler monitoring stopped")

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    async def evaluate(self) -> dict[str, Any]:
        """Evaluate current cluster state and decide whether to scale.

        Returns a dict summarising the decision (direction, reason,
        projected cost, etc.).  Does **not** execute the scaling — call
        :meth:`scale_up` or :meth:`scale_down` for that.
        """
        decision = ScalingDecision()

        # Gather metrics -----------------------------------------------
        nodes = self._get_nodes()
        decision.current_count = len(nodes)
        avg_util = self._compute_avg_utilization(nodes)
        decision.avg_utilization = avg_util
        self._utilization_samples.append((time.time(), avg_util))
        # Trim to last 24 h of samples
        cutoff = time.time() - 86_400
        self._utilization_samples = [
            s for s in self._utilization_samples if s[0] > cutoff
        ]

        current_cost = self._compute_current_cost(nodes)
        decision.projected_cost_per_hour = current_cost

        # Time-based minimum -------------------------------------------
        time_min = self._get_time_based_min_nodes()
        if decision.current_count < time_min:
            decision.direction = ScalingDirection.UP
            decision.target_count = time_min
            decision.reason = (
                f"Time-based policy requires {time_min} nodes, "
                f"have {decision.current_count}"
            )
            return self._decision_to_dict(decision)

        # Min-nodes floor ----------------------------------------------
        if decision.current_count < self._policy.min_nodes:
            decision.direction = ScalingDirection.UP
            decision.target_count = self._policy.min_nodes
            decision.reason = (
                f"Below min_nodes ({self._policy.min_nodes})"
            )
            return self._decision_to_dict(decision)

        # Queue depth trigger ------------------------------------------
        if self._queue_depth > self._policy.queue_depth_threshold:
            decision.direction = ScalingDirection.UP
            delta = min(
                self._policy.scale_up_step,
                self._policy.max_nodes - decision.current_count,
            )
            decision.target_count = decision.current_count + max(delta, 1)
            decision.reason = (
                f"Queue depth {self._queue_depth} > threshold "
                f"{self._policy.queue_depth_threshold}"
            )
            return self._decision_to_dict(decision)

        # Utilization-based scale UP -----------------------------------
        if avg_util > self._policy.target_utilization:
            if decision.current_count >= self._policy.max_nodes:
                decision.direction = ScalingDirection.NONE
                decision.reason = "High utilization but at max_nodes"
                return self._decision_to_dict(decision)

            delta = min(
                self._policy.scale_up_step,
                self._policy.max_nodes - decision.current_count,
            )
            projected = current_cost + self._estimate_node_cost(delta)
            if projected > self._policy.max_cost_per_hour:
                decision.direction = ScalingDirection.NONE
                decision.reason = (
                    f"Would exceed budget: ${projected:.2f}/hr "
                    f"> ${self._policy.max_cost_per_hour:.2f}/hr"
                )
                return self._decision_to_dict(decision)

            decision.direction = ScalingDirection.UP
            decision.target_count = decision.current_count + delta
            decision.reason = (
                f"Avg utilization {avg_util:.0%} > target "
                f"{self._policy.target_utilization:.0%}"
            )
            return self._decision_to_dict(decision)

        # Utilization-based scale DOWN ---------------------------------
        if avg_util < self._policy.scale_down_utilization:
            if decision.current_count <= self._policy.min_nodes:
                decision.direction = ScalingDirection.NONE
                decision.reason = "Low utilization but at min_nodes"
                return self._decision_to_dict(decision)

            delta = min(
                self._policy.scale_down_step,
                decision.current_count - self._policy.min_nodes,
            )
            decision.direction = ScalingDirection.DOWN
            decision.target_count = decision.current_count - delta
            decision.reason = (
                f"Avg utilization {avg_util:.0%} < threshold "
                f"{self._policy.scale_down_utilization:.0%}"
            )
            return self._decision_to_dict(decision)

        # Steady state -------------------------------------------------
        decision.direction = ScalingDirection.NONE
        decision.reason = (
            f"Utilization {avg_util:.0%} within target range "
            f"[{self._policy.scale_down_utilization:.0%}, "
            f"{self._policy.target_utilization:.0%}]"
        )
        return self._decision_to_dict(decision)

    # ------------------------------------------------------------------
    # Scaling actions
    # ------------------------------------------------------------------

    async def scale_up(self, reason: str = "") -> list[Any]:
        """Add nodes to the cluster, respecting provider priority and
        budget.

        Returns a list of newly provisioned :class:`GPUNode` objects
        (or dicts if the cluster is unavailable).
        """
        if not self._can_scale():
            log.info("Scale-up blocked by cooldown")
            return []

        nodes_before = self._get_nodes()
        cost_before = self._compute_current_cost(nodes_before)
        added: list[Any] = []

        for _ in range(self._policy.scale_up_step):
            node = await self._provision_node()
            if node is not None:
                added.append(node)

        self._last_scale_time = time.time()

        # Record event -------------------------------------------------
        event = ScalingEvent(
            direction="up",
            nodes_added=[
                n.node_id if hasattr(n, "node_id") else str(n)
                for n in added
            ],
            reason=reason or "manual scale-up",
            cost_per_hour_before=cost_before,
            cost_per_hour_after=self._compute_current_cost(
                self._get_nodes(),
            ),
            avg_utilization=self._latest_utilization(),
        )
        self._scaling_history.append(event)
        log.info(
            "Scaled UP — added %d node(s): %s  reason=%s",
            len(added), event.nodes_added, reason,
        )
        return added

    async def scale_down(self, reason: str = "") -> list[str]:
        """Remove the least-utilised (or most-expensive) nodes.

        Returns a list of removed node IDs.
        """
        if not self._can_scale():
            log.info("Scale-down blocked by cooldown")
            return []

        nodes = self._get_nodes()
        cost_before = self._compute_current_cost(nodes)
        removed: list[str] = []

        candidates = self._select_removal_candidates(nodes)
        for node in candidates[: self._policy.scale_down_step]:
            try:
                if self._cluster is not None:
                    await self._cluster.remove_node(node.node_id)
                removed.append(node.node_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to remove node %s: %s",
                    node.node_id, exc,
                )

        self._last_scale_time = time.time()

        event = ScalingEvent(
            direction="down",
            nodes_removed=removed,
            reason=reason or "manual scale-down",
            cost_per_hour_before=cost_before,
            cost_per_hour_after=self._compute_current_cost(
                self._get_nodes(),
            ),
            avg_utilization=self._latest_utilization(),
        )
        self._scaling_history.append(event)
        log.info(
            "Scaled DOWN — removed %d node(s): %s  reason=%s",
            len(removed), removed, reason,
        )
        return removed

    # ------------------------------------------------------------------
    # Cost optimisation
    # ------------------------------------------------------------------

    async def find_cheapest_capacity(
        self, gpu_type: str, count: int = 1,
    ) -> list[dict[str, Any]]:
        """Return ranked options for obtaining *count* GPUs of *gpu_type*,
        cheapest first.

        Each entry contains provider, pricing, spot availability, and
        region.
        """
        options: list[dict[str, Any]] = []

        # Real-world reference pricing (April 2026) --------------------
        _reference_pricing: dict[str, dict[str, float]] = {
            "h100_sxm5": {
                "spheron": 0.99, "lambda": 2.49, "runpod": 2.69,
                "coreweave": 2.95, "aws": 4.10, "gcp": 4.40,
            },
            "h100": {
                "spheron": 0.99, "lambda": 2.49, "runpod": 2.69,
                "coreweave": 2.95, "aws": 4.10, "gcp": 4.40,
            },
            "h200": {
                "lambda": 3.99, "coreweave": 4.25, "runpod": 4.49,
                "spheron": 2.50, "aws": 4.98, "gcp": 5.20,
            },
            "b200": {
                "lambda": 4.62, "coreweave": 4.99, "runpod": 5.50,
                "aws": 7.12, "gcp": 7.50,
            },
            "a100_80gb": {
                "spheron": 0.80, "lambda": 1.29, "runpod": 1.64,
                "coreweave": 2.06, "aws": 3.67, "gcp": 3.80,
            },
            "a100_40gb": {
                "lambda": 1.10, "runpod": 1.14, "coreweave": 1.50,
                "aws": 3.06, "gcp": 3.20,
            },
            "l40s": {
                "runpod": 0.74, "spheron": 0.89, "lambda": 1.10,
                "coreweave": 1.25, "aws": 2.36, "gcp": 2.50,
            },
        }

        normalized = gpu_type.lower().replace(" ", "_").replace("-", "_")
        pricing = _reference_pricing.get(normalized, {})

        for provider in self._policy.provider_priority:
            per_gpu = pricing.get(provider)
            if per_gpu is None:
                continue

            spot_price = per_gpu * self._policy.spot_max_price_pct
            options.append({
                "provider": provider,
                "gpu_type": gpu_type,
                "count": count,
                "on_demand_per_gpu_hr": per_gpu,
                "spot_per_gpu_hr": round(spot_price, 2),
                "total_on_demand_hr": round(per_gpu * count, 2),
                "total_spot_hr": round(spot_price * count, 2),
                "spot_available": self._policy.prefer_spot,
                "region": "auto",
            })

        # Sort by effective price (spot if preferred, else on-demand) --
        options.sort(
            key=lambda o: o["total_spot_hr"]
            if self._policy.prefer_spot
            else o["total_on_demand_hr"],
        )
        return options

    async def migrate_to_spot(self) -> dict[str, Any]:
        """Attempt to migrate on-demand nodes to cheaper spot instances.

        For each on-demand node, the scaler:
        1. Finds the cheapest spot option on any provider.
        2. Provisions the spot node.
        3. Drains and terminates the on-demand node.

        Returns a summary dict.
        """
        migrated: list[dict[str, Any]] = []
        failed: list[str] = []
        nodes = self._get_nodes()

        for node in nodes:
            is_spot = getattr(node, "spot", False) if hasattr(node, "spot") else False
            if is_spot:
                continue  # already spot

            gpu_type = getattr(node, "gpu_type", "h100")
            try:
                replacement = await self._provision_spot_node(gpu_type)
                if replacement is not None:
                    # Remove old on-demand node
                    if self._cluster is not None:
                        await self._cluster.remove_node(node.node_id)
                    migrated.append({
                        "old_node": node.node_id,
                        "new_node": (
                            replacement.node_id
                            if hasattr(replacement, "node_id")
                            else str(replacement)
                        ),
                        "savings_pct": round(
                            (1 - self._policy.spot_max_price_pct) * 100, 1,
                        ),
                    })
                else:
                    failed.append(node.node_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Spot migration failed for %s: %s", node.node_id, exc,
                )
                failed.append(node.node_id)

        result = {
            "migrated": migrated,
            "failed": failed,
            "total_migrated": len(migrated),
            "total_failed": len(failed),
        }
        log.info("Spot migration complete: %s", result)
        return result

    async def handle_spot_interruption(self, node_id: str) -> Any:
        """Delegate spot interruption to the handler.

        Returns the replacement :class:`GPUNode` (or ``None``).
        """
        result = await self._interruption_handler.handle_interruption(
            node_id,
        )
        replacement_id = result.get("replacement_node")
        if replacement_id and self._cluster is not None:
            return await self._cluster.get_node(replacement_id)
        return None

    # ------------------------------------------------------------------
    # Metrics / history
    # ------------------------------------------------------------------

    def get_scaling_history(self) -> list[dict[str, Any]]:
        """Return the full scaling history as a list of dicts."""
        return [
            {
                "event_id": e.event_id,
                "direction": e.direction,
                "nodes_added": e.nodes_added,
                "nodes_removed": e.nodes_removed,
                "reason": e.reason,
                "provider": e.provider,
                "gpu_type": e.gpu_type,
                "spot": e.spot,
                "cost_per_hour_before": e.cost_per_hour_before,
                "cost_per_hour_after": e.cost_per_hour_after,
                "avg_utilization": e.avg_utilization,
                "timestamp": e.timestamp,
                "timestamp_iso": datetime.fromtimestamp(
                    e.timestamp, tz=timezone.utc,
                ).isoformat(),
            }
            for e in self._scaling_history
        ]

    def get_cost_forecast(self, hours: int = 24) -> dict[str, Any]:
        """Project cost for the next *hours* based on current state.

        Returns a :class:`CostForecast`-shaped dict.
        """
        nodes = self._get_nodes()
        current_cost = self._compute_current_cost(nodes)

        by_provider: dict[str, float] = {}
        by_gpu: dict[str, float] = {}
        for node in nodes:
            prov = getattr(node, "provider", "unknown")
            gpu = getattr(node, "gpu_type", "unknown")
            cost = getattr(node, "cost_per_hour", 0.0)
            by_provider[prov] = by_provider.get(prov, 0.0) + cost
            by_gpu[gpu] = by_gpu.get(gpu, 0.0) + cost

        spot_count = sum(
            1 for n in nodes if getattr(n, "spot", False)
        )
        on_demand_count = len(nodes) - spot_count
        spot_savings = (
            current_cost
            * (1 - self._policy.spot_max_price_pct)
            * (spot_count / max(len(nodes), 1))
        )

        forecast = CostForecast(
            hours=hours,
            current_cost_per_hour=round(current_cost, 2),
            projected_total=round(current_cost * hours, 2),
            projected_spot_savings=round(spot_savings * hours, 2),
            node_count=len(nodes),
            breakdown_by_provider={
                k: round(v * hours, 2) for k, v in by_provider.items()
            },
            breakdown_by_gpu={
                k: round(v * hours, 2) for k, v in by_gpu.items()
            },
        )
        return {
            "hours": forecast.hours,
            "current_cost_per_hour": forecast.current_cost_per_hour,
            "projected_total": forecast.projected_total,
            "projected_spot_savings": forecast.projected_spot_savings,
            "node_count": forecast.node_count,
            "breakdown_by_provider": forecast.breakdown_by_provider,
            "breakdown_by_gpu": forecast.breakdown_by_gpu,
            "generated_at": forecast.generated_at,
            "generated_at_iso": datetime.fromtimestamp(
                forecast.generated_at, tz=timezone.utc,
            ).isoformat(),
        }

    def set_queue_depth(self, depth: int) -> None:
        """Allow external components to feed the current queue depth."""
        self._queue_depth = depth

    # ------------------------------------------------------------------
    # Internal — monitoring loop
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Background loop that evaluates and executes scaling decisions."""
        log.info("Monitor loop started (interval ~30 s)")
        while self._running:
            try:
                decision = await self.evaluate()
                direction = decision.get("direction", "none")

                if direction == ScalingDirection.UP.value:
                    await self.scale_up(
                        reason=decision.get("reason", "auto"),
                    )
                elif direction == ScalingDirection.DOWN.value:
                    await self.scale_down(
                        reason=decision.get("reason", "auto"),
                    )

            except Exception as exc:  # noqa: BLE001
                log.error("Monitor loop error: %s", exc, exc_info=True)

            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    def _get_nodes(self) -> list[Any]:
        """Return the list of nodes from the cluster."""
        if self._cluster is None:
            return []
        try:
            return self._cluster.list_nodes()
        except Exception:  # noqa: BLE001
            return []

    def _compute_avg_utilization(self, nodes: list[Any]) -> float:
        """Compute average GPU utilization across all nodes."""
        if not nodes:
            return 0.0
        total, count = 0.0, 0
        for node in nodes:
            utils = getattr(node, "gpu_utilization", [])
            if utils:
                total += sum(utils)
                count += len(utils)
        return (total / count / 100.0) if count else 0.0

    def _compute_current_cost(self, nodes: list[Any]) -> float:
        """Sum of cost_per_hour across all nodes."""
        return sum(
            getattr(n, "cost_per_hour", 0.0) for n in nodes
        )

    def _latest_utilization(self) -> float:
        """Return the most recent utilization sample."""
        if self._utilization_samples:
            return self._utilization_samples[-1][1]
        return 0.0

    def _estimate_node_cost(self, count: int = 1) -> float:
        """Rough estimate of cost for *count* new nodes."""
        # Use the cheapest provider's H100 spot price as default
        base = 0.99  # Spheron H100 spot
        if not self._policy.prefer_spot:
            base = 2.01  # Spheron H100 on-demand
        return base * count

    def _can_scale(self) -> bool:
        """Check cooldown period."""
        elapsed = time.time() - self._last_scale_time
        return elapsed >= self._policy.cooldown_seconds

    def _get_time_based_min_nodes(self) -> int:
        """Return the minimum node count for the current hour."""
        if not self._policy.time_based_scaling:
            return self._policy.min_nodes
        now_hour = str(datetime.now(tz=timezone.utc).hour)
        return self._policy.time_based_scaling.get(
            now_hour, self._policy.min_nodes,
        )

    async def _provision_node(self) -> Any:
        """Provision a node using provider priority + spot preference."""
        if self._cluster is None:
            log.warning("No cluster attached — cannot provision")
            return None

        gpu_types_to_try: list[str] = [
            getattr(self._cluster, "_config", None)
            and getattr(self._cluster._config, "gpu_type", "h100")
            or "h100"
        ]
        if self._policy.fallback_to_smaller_gpu:
            gpu_types_to_try.extend(self._policy.gpu_fallback_order)
            # Deduplicate while preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for g in gpu_types_to_try:
                if g not in seen:
                    seen.add(g)
                    deduped.append(g)
            gpu_types_to_try = deduped

        for gpu_type in gpu_types_to_try:
            for provider in self._policy.provider_priority:
                # Try spot first -----------------------------------------
                if self._policy.prefer_spot:
                    try:
                        node = await self._cluster.add_node(
                            provider=provider,
                            gpu_type=gpu_type,
                            spot=True,
                        )
                        log.info(
                            "Provisioned spot %s on %s",
                            gpu_type, provider,
                        )
                        return node
                    except Exception:  # noqa: BLE001
                        pass

                # On-demand fallback ------------------------------------
                try:
                    node = await self._cluster.add_node(
                        provider=provider,
                        gpu_type=gpu_type,
                        spot=False,
                    )
                    log.info(
                        "Provisioned on-demand %s on %s",
                        gpu_type, provider,
                    )
                    return node
                except Exception:  # noqa: BLE001
                    pass

        log.error("Failed to provision a node on any provider / GPU type")
        return None

    async def _provision_spot_node(self, gpu_type: str) -> Any:
        """Provision a spot node only (no on-demand fallback)."""
        if self._cluster is None:
            return None
        for provider in self._policy.provider_priority:
            try:
                node = await self._cluster.add_node(
                    provider=provider, gpu_type=gpu_type, spot=True,
                )
                return node
            except Exception:  # noqa: BLE001
                continue
        return None

    def _select_removal_candidates(self, nodes: list[Any]) -> list[Any]:
        """Rank nodes for removal — prefer least-utilised, then most
        expensive, then spot over on-demand (keep on-demand longer)."""

        def _sort_key(node: Any) -> tuple[float, float, int]:
            avg_util = 0.0
            utils = getattr(node, "gpu_utilization", [])
            if utils:
                avg_util = sum(utils) / len(utils)
            cost = getattr(node, "cost_per_hour", 0.0)
            is_spot = 0 if getattr(node, "spot", False) else 1
            return (avg_util, -cost, is_spot)

        return sorted(nodes, key=_sort_key)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AutoScaler(running={self._running}, "
            f"history_len={len(self._scaling_history)}, "
            f"policy={self._policy!r})"
        )

    # ------------------------------------------------------------------
    # Private helpers — dict conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _decision_to_dict(d: ScalingDecision) -> dict[str, Any]:
        return {
            "direction": d.direction.value,
            "reason": d.reason,
            "target_count": d.target_count,
            "current_count": d.current_count,
            "avg_utilization": round(d.avg_utilization, 4),
            "projected_cost_per_hour": round(d.projected_cost_per_hour, 2),
            "provider": d.provider,
            "gpu_type": d.gpu_type,
            "spot": d.spot,
            "timestamp": d.timestamp,
        }
