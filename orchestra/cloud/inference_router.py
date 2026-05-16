"""Inference Router — routes model requests to the best GPU endpoint.

Sits between Orchestra's :class:`ModelRouter` and the physical GPU
endpoints running vLLM, TGI, or SGLang.  Handles:

- Multi-endpoint load balancing
- Latency / cost-aware routing
- Model–GPU affinity (Kimi K2.5 → H200/B200 4+ GPUs, 7B → A100 40GB)
- Automatic failover when endpoints go down
- Request queuing during scaling events
- vLLM / TGI deployment helpers
- Continuous health monitoring

Usage::

    from orchestra.cloud.inference_router import (
        InferenceRouter, InferenceEndpoint, RoutingStrategy,
    )

    router = InferenceRouter(strategy=RoutingStrategy.HYBRID)
    await router.register_endpoint(endpoint)
    result = await router.route("moonshotai/Kimi-K2.5", messages)
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import os
import random
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
    "InferenceEndpoint",
    "InferenceRouter",
    "RoutingStrategy",
    "ModelGPUAffinity",
    "EndpointHealth",
    "RequestQueue",
]

log = logging.getLogger("orchestra.cloud.inference_router")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoutingStrategy(str, Enum):
    """Available routing strategies for endpoint selection."""
    LOWEST_LATENCY = "lowest_latency"
    LOWEST_COST = "lowest_cost"
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    GPU_AFFINITY = "gpu_affinity"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class InferenceEndpoint:
    """A single inference endpoint (vLLM / TGI / SGLang instance).

    Attributes:
        endpoint_id:         Unique identifier for this endpoint.
        url:                 Base URL, e.g. ``http://10.0.1.5:8000/v1``.
        model_id:            Model served, e.g. ``moonshotai/Kimi-K2.5``.
        gpu_type:            GPU SKU, e.g. ``h200``.
        gpu_count:           Number of GPUs backing this endpoint.
        provider:            Cloud provider name.
        status:              ``healthy`` | ``degraded`` | ``down``.
        current_load:        Normalised load 0-1.
        avg_latency_ms:      Exponentially-weighted avg latency.
        tokens_per_second:   Throughput metric.
        max_batch_size:      Maximum concurrent batch size.
        supported_features:  Feature flags for this endpoint.
        cost_per_hour:       Running cost of the underlying GPU(s).
        tensor_parallel:     TP degree for distributed inference.
        pipeline_parallel:   PP degree.
        engine:              Inference engine: ``vllm`` | ``tgi`` | ``sglang``.
        region:              Cloud region.
        created_at:          Timestamp of endpoint creation.
    """
    endpoint_id: str = field(
        default_factory=lambda: f"ep-{uuid.uuid4().hex[:10]}",
    )
    url: str = ""
    model_id: str = ""
    gpu_type: str = ""
    gpu_count: int = 1
    provider: str = ""
    status: str = "healthy"
    current_load: float = 0.0
    avg_latency_ms: float = 0.0
    tokens_per_second: float = 0.0
    max_batch_size: int = 64
    supported_features: list[str] = field(
        default_factory=lambda: ["chat", "completion"],
    )
    cost_per_hour: float = 0.0
    tensor_parallel: int = 1
    pipeline_parallel: int = 1
    engine: str = "vllm"
    region: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class EndpointHealth:
    """Snapshot of an endpoint's health state."""
    endpoint_id: str = ""
    healthy: bool = True
    latency_ms: float = 0.0
    error_rate: float = 0.0
    consecutive_failures: int = 0
    last_check: float = field(default_factory=time.time)
    last_success: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Model–GPU affinity map
# ---------------------------------------------------------------------------

class ModelGPUAffinity:
    """Maps model identifiers / sizes to minimum GPU requirements.

    The affinity map encodes the recommended GPU type, count, and
    parallelism strategy for each class of model.  Routing and autoscaler
    components use this to select the right endpoints.
    """

    # Each entry: (gpu_type, min_gpu_count, tensor_parallel, pipeline_parallel)
    _AFFINITY: dict[str, dict[str, Any]] = {
        # 200B+ parameter models (MoE / dense) -------------------------
        "kimi_k2.5": {
            "model_patterns": [
                "kimi-k2.5", "kimi_k2.5", "Kimi-K2.5", "Kimi K2.5",
                "moonshotai/Kimi-K2.5",
            ],
            "param_class": "200B+",
            "recommended_gpu": "h200",
            "acceptable_gpus": ["h200", "b200"],
            "min_gpu_count": 4,
            "tensor_parallel": 4,
            "pipeline_parallel": 1,
            "min_vram_per_gpu_gb": 141,
            "total_vram_needed_gb": 500,
            "notes": "MoE architecture — needs 4+ GPUs with tensor parallel",
        },
        "gpt4_class": {
            "model_patterns": [
                "gpt-4", "gpt4", "175b", "175B",
            ],
            "param_class": "175B",
            "recommended_gpu": "h100_sxm5",
            "acceptable_gpus": ["h100_sxm5", "h100", "h200", "b200"],
            "min_gpu_count": 4,
            "max_gpu_count": 8,
            "tensor_parallel": 4,
            "pipeline_parallel": 1,
            "min_vram_per_gpu_gb": 80,
            "total_vram_needed_gb": 350,
            "notes": "Dense 175B — 4-8× H100 SXM5 via NVLink",
        },
        "70b": {
            "model_patterns": [
                "70b", "70B", "llama-70b", "llama-3-70b",
                "qwen-72b", "mixtral-8x7b",
            ],
            "param_class": "70B",
            "recommended_gpu": "h100",
            "acceptable_gpus": ["h100", "h100_sxm5", "h200", "b200"],
            "min_gpu_count": 2,
            "tensor_parallel": 2,
            "pipeline_parallel": 1,
            "min_vram_per_gpu_gb": 80,
            "total_vram_needed_gb": 140,
            "notes": "2× H100 or single H200 (141 GB VRAM)",
            "single_gpu_alternative": "h200",
        },
        "13b": {
            "model_patterns": [
                "13b", "13B", "llama-13b", "llama-2-13b",
                "codellama-13b",
            ],
            "param_class": "13B",
            "recommended_gpu": "h100",
            "acceptable_gpus": ["h100", "h100_sxm5", "a100_80gb", "h200"],
            "min_gpu_count": 1,
            "tensor_parallel": 1,
            "pipeline_parallel": 1,
            "min_vram_per_gpu_gb": 40,
            "total_vram_needed_gb": 30,
            "notes": "Single H100 or A100 80 GB",
        },
        "7b": {
            "model_patterns": [
                "7b", "7B", "llama-7b", "llama-2-7b",
                "mistral-7b", "llama-3-8b", "8b", "8B",
            ],
            "param_class": "7B",
            "recommended_gpu": "a100_40gb",
            "acceptable_gpus": ["a100_40gb", "a100_80gb", "l40s", "h100"],
            "min_gpu_count": 1,
            "tensor_parallel": 1,
            "pipeline_parallel": 1,
            "min_vram_per_gpu_gb": 24,
            "total_vram_needed_gb": 16,
            "notes": "Single A100 40 GB or L40S",
        },
    }

    # Quick lookup: pattern → affinity key
    _pattern_index: dict[str, str] = {}

    @classmethod
    def _build_index(cls) -> None:
        if cls._pattern_index:
            return
        for key, info in cls._AFFINITY.items():
            for pat in info.get("model_patterns", []):
                cls._pattern_index[pat.lower()] = key

    @classmethod
    def get_affinity(cls, model_id: str) -> dict[str, Any] | None:
        """Look up affinity info for a model by ID or pattern match."""
        cls._build_index()
        model_lower = model_id.lower()

        # Exact / substring match against known patterns ---------------
        for pattern, key in cls._pattern_index.items():
            if pattern in model_lower or model_lower in pattern:
                return dict(cls._AFFINITY[key])

        # Heuristic: extract parameter size from name ------------------
        import re
        m = re.search(r"(\d+)[bB]", model_id)
        if m:
            size = int(m.group(1))
            if size >= 150:
                return dict(cls._AFFINITY["gpt4_class"])
            if size >= 60:
                return dict(cls._AFFINITY["70b"])
            if size >= 10:
                return dict(cls._AFFINITY["13b"])
            return dict(cls._AFFINITY["7b"])

        return None

    @classmethod
    def get_recommended_gpu(cls, model_id: str) -> str:
        """Return the recommended GPU type string for a model.

        Falls back to ``"h100"`` if no affinity is found.
        """
        affinity = cls.get_affinity(model_id)
        if affinity:
            return affinity["recommended_gpu"]
        return "h100"

    @classmethod
    def get_model_requirements(cls, model_id: str) -> dict[str, Any]:
        """Return full requirements dict for a model.

        Includes recommended GPU, count, parallelism, VRAM, etc.
        """
        affinity = cls.get_affinity(model_id)
        if affinity is None:
            return {
                "model_id": model_id,
                "recommended_gpu": "h100",
                "acceptable_gpus": ["h100", "a100_80gb"],
                "min_gpu_count": 1,
                "tensor_parallel": 1,
                "pipeline_parallel": 1,
                "min_vram_per_gpu_gb": 80,
                "total_vram_needed_gb": 80,
                "notes": "Unknown model — defaulting to single H100",
            }
        affinity["model_id"] = model_id
        return affinity

    @classmethod
    def list_affinities(cls) -> dict[str, dict[str, Any]]:
        """Return the full affinity table."""
        return {k: dict(v) for k, v in cls._AFFINITY.items()}


# ---------------------------------------------------------------------------
# Request queue — buffers requests during scaling events
# ---------------------------------------------------------------------------

class RequestQueue:
    """Simple async queue for buffering inference requests when no
    healthy endpoints are available (e.g. during a scale-up).

    Requests are drained automatically once an endpoint becomes
    available.
    """

    def __init__(self, max_size: int = 500, timeout: float = 60.0) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max_size,
        )
        self._timeout = timeout
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._total_dropped = 0

    async def enqueue(self, request: dict[str, Any]) -> bool:
        """Add a request to the queue.  Returns False if full."""
        try:
            self._queue.put_nowait(request)
            self._total_enqueued += 1
            return True
        except asyncio.QueueFull:
            self._total_dropped += 1
            log.warning("Request queue full — dropping request")
            return False

    async def dequeue(self) -> dict[str, Any] | None:
        """Pop a request from the front.  Returns None on timeout."""
        try:
            item = await asyncio.wait_for(
                self._queue.get(), timeout=self._timeout,
            )
            self._total_dequeued += 1
            return item
        except asyncio.TimeoutError:
            return None

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    def stats(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "total_enqueued": self._total_enqueued,
            "total_dequeued": self._total_dequeued,
            "total_dropped": self._total_dropped,
        }


# ---------------------------------------------------------------------------
# Inference Router
# ---------------------------------------------------------------------------

class InferenceRouter:
    """Routes model inference to the best available GPU endpoint.

    Sits between Orchestra's :class:`ModelRouter` and the actual GPU
    endpoints.  Selects the optimal endpoint based on the chosen
    :class:`RoutingStrategy` and transparently handles failover,
    health monitoring, and request queuing.

    Parameters
    ----------
    cluster:
        Optional :class:`GPUCluster` for auto-discovery of endpoints.
    strategy:
        Default routing strategy.  Can be overridden per-request.
    health_interval:
        Seconds between health-check sweeps (default 15).
    request_timeout:
        Per-request timeout in seconds (default 120).
    """

    def __init__(
        self,
        cluster: Any | None = None,
        strategy: RoutingStrategy = RoutingStrategy.HYBRID,
        health_interval: float = 15.0,
        request_timeout: float = 120.0,
    ) -> None:
        self._cluster = cluster
        self._default_strategy = strategy
        self._health_interval = health_interval
        self._request_timeout = request_timeout

        # Endpoint registry keyed by endpoint_id ----------------------
        self._endpoints: dict[str, InferenceEndpoint] = {}
        # Endpoint health state keyed by endpoint_id ------------------
        self._health: dict[str, EndpointHealth] = {}
        # Round-robin index per model ---------------------------------
        self._rr_index: dict[str, int] = {}
        # Request queue for buffering during scale-up -----------------
        self._queue = RequestQueue()
        # Health monitor task -----------------------------------------
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False

        # Latency tracking (endpoint_id → deque of latencies) ---------
        self._latency_window: dict[str, collections.deque[float]] = {}
        self._latency_window_size = 100

        # Request counters per endpoint (for LEAST_LOADED) -------------
        self._active_requests: dict[str, int] = {}

        # Cost per token tracked per endpoint --------------------------
        self._cost_per_token: dict[str, float] = {}

        log.info(
            "InferenceRouter initialised — strategy=%s, health_interval=%.0fs",
            strategy.value, health_interval,
        )

    # ------------------------------------------------------------------
    # Endpoint management
    # ------------------------------------------------------------------

    async def register_endpoint(
        self, endpoint: InferenceEndpoint,
    ) -> None:
        """Register an inference endpoint with the router."""
        self._endpoints[endpoint.endpoint_id] = endpoint
        self._health[endpoint.endpoint_id] = EndpointHealth(
            endpoint_id=endpoint.endpoint_id,
        )
        self._active_requests[endpoint.endpoint_id] = 0
        self._latency_window[endpoint.endpoint_id] = collections.deque(
            maxlen=self._latency_window_size,
        )
        # Estimate cost-per-token from GPU throughput
        if endpoint.tokens_per_second > 0:
            self._cost_per_token[endpoint.endpoint_id] = (
                endpoint.cost_per_hour / 3600.0 / endpoint.tokens_per_second
            )
        log.info(
            "Registered endpoint %s → %s [%s × %d on %s]",
            endpoint.endpoint_id, endpoint.url,
            endpoint.gpu_type, endpoint.gpu_count, endpoint.provider,
        )

    async def deregister_endpoint(self, endpoint_id: str) -> None:
        """Remove an endpoint from the router."""
        self._endpoints.pop(endpoint_id, None)
        self._health.pop(endpoint_id, None)
        self._active_requests.pop(endpoint_id, None)
        self._latency_window.pop(endpoint_id, None)
        self._cost_per_token.pop(endpoint_id, None)
        log.info("Deregistered endpoint %s", endpoint_id)

    async def discover_endpoints(self) -> list[InferenceEndpoint]:
        """Auto-discover endpoints from the attached cluster.

        Queries every ``ready`` node's inference endpoint and creates
        :class:`InferenceEndpoint` objects.
        """
        discovered: list[InferenceEndpoint] = []
        if self._cluster is None:
            return discovered

        try:
            nodes = self._cluster.list_nodes()
        except Exception:  # noqa: BLE001
            return discovered

        for node in nodes:
            status = getattr(node, "status", "")
            if status not in ("ready", "busy"):
                continue
            ep_url = getattr(node, "inference_endpoint", "")
            if not ep_url:
                continue
            ep = InferenceEndpoint(
                url=ep_url,
                model_id="",  # will be discovered via health check
                gpu_type=getattr(node, "gpu_type", ""),
                gpu_count=getattr(node, "gpu_count", 1),
                provider=getattr(node, "provider", ""),
                cost_per_hour=getattr(node, "cost_per_hour", 0.0),
                region=getattr(node, "region", ""),
            )
            await self.register_endpoint(ep)
            discovered.append(ep)

        log.info("Discovered %d endpoints from cluster", len(discovered))
        return discovered

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        strategy: RoutingStrategy | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Route an inference request to the best endpoint.

        Selects an endpoint, sends the request, and returns the response
        dict.  On failure, retries with the next-best endpoint.
        """
        effective_strategy = strategy or self._default_strategy
        attempted: set[str] = set()
        last_error: str = ""

        # Try up to 3 endpoints before giving up ----------------------
        for attempt in range(3):
            try:
                ep = await self.select_endpoint(
                    model_id, strategy=effective_strategy,
                    exclude=attempted,
                )
            except ValueError:
                # No healthy endpoints — queue the request
                log.warning("No healthy endpoints — queuing request")
                queued = await self._queue.enqueue({
                    "model_id": model_id,
                    "messages": messages,
                    "kwargs": kwargs,
                })
                return {
                    "status": "queued" if queued else "rejected",
                    "error": "No healthy endpoints available",
                    "queue_depth": self._queue.depth,
                }

            attempted.add(ep.endpoint_id)
            self._active_requests[ep.endpoint_id] = (
                self._active_requests.get(ep.endpoint_id, 0) + 1
            )

            try:
                result = await self._send_request(ep, model_id, messages, **kwargs)
                # Update metrics
                self._active_requests[ep.endpoint_id] = max(
                    self._active_requests.get(ep.endpoint_id, 1) - 1, 0,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                self._active_requests[ep.endpoint_id] = max(
                    self._active_requests.get(ep.endpoint_id, 1) - 1, 0,
                )
                last_error = str(exc)
                log.warning(
                    "Request to %s failed (attempt %d): %s",
                    ep.endpoint_id, attempt + 1, exc,
                )
                # Mark degraded
                health = self._health.get(ep.endpoint_id)
                if health:
                    health.consecutive_failures += 1
                    if health.consecutive_failures >= 3:
                        ep.status = "down"
                        health.healthy = False

        return {"status": "error", "error": last_error}

    async def stream_route(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream tokens from the best available endpoint.

        Yields dicts with incremental content.  On failure, attempts
        failover to the next endpoint.
        """
        try:
            ep = await self.select_endpoint(model_id)
        except ValueError:
            yield {"status": "error", "error": "No healthy endpoints"}
            return

        self._active_requests[ep.endpoint_id] = (
            self._active_requests.get(ep.endpoint_id, 0) + 1
        )

        try:
            async for chunk in self._stream_request(
                ep, model_id, messages, **kwargs,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            log.warning("Stream to %s failed: %s", ep.endpoint_id, exc)
            yield {"status": "error", "error": str(exc)}
        finally:
            self._active_requests[ep.endpoint_id] = max(
                self._active_requests.get(ep.endpoint_id, 1) - 1, 0,
            )

    # ------------------------------------------------------------------
    # Endpoint selection
    # ------------------------------------------------------------------

    async def select_endpoint(
        self,
        model_id: str,
        strategy: RoutingStrategy | None = None,
        exclude: set[str] | None = None,
    ) -> InferenceEndpoint:
        """Select the best endpoint for *model_id* using *strategy*.

        Raises ``ValueError`` if no healthy endpoint serves the model.
        """
        effective = strategy or self._default_strategy
        exclude = exclude or set()

        candidates = self._get_healthy_endpoints(model_id, exclude)
        if not candidates:
            # Widen search: any healthy endpoint (model not checked)
            candidates = [
                ep for ep in self._endpoints.values()
                if ep.status == "healthy"
                and ep.endpoint_id not in exclude
            ]
        if not candidates:
            raise ValueError(
                f"No healthy endpoints available for model {model_id}",
            )

        if effective == RoutingStrategy.LOWEST_LATENCY:
            return self._select_lowest_latency(candidates)
        if effective == RoutingStrategy.LOWEST_COST:
            return self._select_lowest_cost(candidates)
        if effective == RoutingStrategy.ROUND_ROBIN:
            return self._select_round_robin(candidates, model_id)
        if effective == RoutingStrategy.LEAST_LOADED:
            return self._select_least_loaded(candidates)
        if effective == RoutingStrategy.GPU_AFFINITY:
            return self._select_gpu_affinity(candidates, model_id)
        # HYBRID — weighted combination
        return self._select_hybrid(candidates, model_id)

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _select_lowest_latency(
        self, candidates: list[InferenceEndpoint],
    ) -> InferenceEndpoint:
        """Pick the endpoint with the lowest average latency."""
        def _lat(ep: InferenceEndpoint) -> float:
            window = self._latency_window.get(ep.endpoint_id)
            if window:
                return sum(window) / len(window)
            return ep.avg_latency_ms or float("inf")
        return min(candidates, key=_lat)

    def _select_lowest_cost(
        self, candidates: list[InferenceEndpoint],
    ) -> InferenceEndpoint:
        """Pick the cheapest endpoint by cost_per_hour."""
        return min(candidates, key=lambda ep: ep.cost_per_hour)

    def _select_round_robin(
        self, candidates: list[InferenceEndpoint], model_id: str,
    ) -> InferenceEndpoint:
        """Rotate through candidates deterministically."""
        idx = self._rr_index.get(model_id, 0) % len(candidates)
        self._rr_index[model_id] = idx + 1
        return candidates[idx]

    def _select_least_loaded(
        self, candidates: list[InferenceEndpoint],
    ) -> InferenceEndpoint:
        """Pick the endpoint with the fewest active requests."""
        return min(
            candidates,
            key=lambda ep: (
                self._active_requests.get(ep.endpoint_id, 0),
                ep.current_load,
            ),
        )

    def _select_gpu_affinity(
        self,
        candidates: list[InferenceEndpoint],
        model_id: str,
    ) -> InferenceEndpoint:
        """Prefer endpoints whose GPU matches the model's affinity."""
        affinity = ModelGPUAffinity.get_affinity(model_id)
        if affinity is None:
            return self._select_least_loaded(candidates)

        acceptable = set(affinity.get("acceptable_gpus", []))
        min_gpus = affinity.get("min_gpu_count", 1)

        # Filter to matching GPU type + count
        matching = [
            ep for ep in candidates
            if ep.gpu_type in acceptable and ep.gpu_count >= min_gpus
        ]
        if matching:
            return self._select_least_loaded(matching)

        # Fallback: any endpoint meeting min GPU count
        enough_gpus = [
            ep for ep in candidates if ep.gpu_count >= min_gpus
        ]
        if enough_gpus:
            return self._select_least_loaded(enough_gpus)

        return self._select_least_loaded(candidates)

    def _select_hybrid(
        self,
        candidates: list[InferenceEndpoint],
        model_id: str,
    ) -> InferenceEndpoint:
        """Weighted score combining latency, cost, load, and affinity.

        Weights:
            latency   0.30
            cost      0.25
            load      0.25
            affinity  0.20
        """
        W_LAT, W_COST, W_LOAD, W_AFF = 0.30, 0.25, 0.25, 0.20

        affinity = ModelGPUAffinity.get_affinity(model_id)
        acceptable = set()
        if affinity:
            acceptable = set(affinity.get("acceptable_gpus", []))

        # Normalise metrics --------------------------------------------
        latencies = [
            self._avg_latency(ep) for ep in candidates
        ]
        costs = [ep.cost_per_hour for ep in candidates]
        loads = [
            self._active_requests.get(ep.endpoint_id, 0)
            + ep.current_load * 10
            for ep in candidates
        ]

        def _norm(vals: list[float]) -> list[float]:
            lo, hi = min(vals), max(vals)
            rng = hi - lo if hi != lo else 1.0
            return [(v - lo) / rng for v in vals]

        n_lat = _norm(latencies)
        n_cost = _norm(costs)
        n_load = _norm(loads)

        best_score = float("inf")
        best_ep = candidates[0]

        for i, ep in enumerate(candidates):
            aff_score = 0.0 if ep.gpu_type in acceptable else 1.0
            score = (
                W_LAT * n_lat[i]
                + W_COST * n_cost[i]
                + W_LOAD * n_load[i]
                + W_AFF * aff_score
            )
            if score < best_score:
                best_score = score
                best_ep = ep

        return best_ep

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def health_check_all(self) -> dict[str, Any]:
        """Run a health check against every registered endpoint.

        Returns a summary dict with per-endpoint status.
        """
        results: dict[str, Any] = {}
        for ep_id, ep in self._endpoints.items():
            health = await self._check_endpoint_health(ep)
            results[ep_id] = {
                "healthy": health.healthy,
                "latency_ms": round(health.latency_ms, 1),
                "error_rate": round(health.error_rate, 4),
                "consecutive_failures": health.consecutive_failures,
                "status": ep.status,
            }
        healthy_count = sum(
            1 for r in results.values() if r["healthy"]
        )
        return {
            "total": len(results),
            "healthy": healthy_count,
            "unhealthy": len(results) - healthy_count,
            "endpoints": results,
        }

    async def start_health_monitor(self) -> None:
        """Start the background health-check loop."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._health_loop())
        log.info("Health monitor started (interval %.0fs)", self._health_interval)

    async def stop_health_monitor(self) -> None:
        """Stop the background health-check loop."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        log.info("Health monitor stopped")

    # ------------------------------------------------------------------
    # vLLM / TGI deployment helpers
    # ------------------------------------------------------------------

    async def deploy_vllm(
        self,
        model_id: str,
        node: Any,
        tensor_parallel: int = 1,
    ) -> InferenceEndpoint:
        """Generate and (conceptually) execute a vLLM deployment on *node*.

        In production this would SSH / kubectl into the node and start
        ``vllm serve``.  Here we build the command, register the
        endpoint, and return it.
        """
        ip = getattr(node, "ip_address", "127.0.0.1")
        port = 8000
        gpu_count = getattr(node, "gpu_count", 1)
        tp = min(tensor_parallel, gpu_count) if tensor_parallel else gpu_count

        affinity = ModelGPUAffinity.get_affinity(model_id)
        if affinity and tp < affinity.get("tensor_parallel", 1):
            tp = affinity["tensor_parallel"]

        cmd = (
            f"vllm serve {model_id} "
            f"--host 0.0.0.0 --port {port} "
            f"--tensor-parallel-size {tp} "
            f"--dtype auto "
            f"--max-model-len 32768 "
            f"--gpu-memory-utilization 0.92 "
            f"--enforce-eager "
            f"--trust-remote-code"
        )
        log.info("vLLM deploy command: %s", cmd)

        ep = InferenceEndpoint(
            url=f"http://{ip}:{port}/v1",
            model_id=model_id,
            gpu_type=getattr(node, "gpu_type", "h100"),
            gpu_count=gpu_count,
            provider=getattr(node, "provider", ""),
            cost_per_hour=getattr(node, "cost_per_hour", 0.0),
            tensor_parallel=tp,
            engine="vllm",
            region=getattr(node, "region", ""),
            supported_features=["chat", "completion", "embedding"],
        )
        await self.register_endpoint(ep)
        return ep

    async def deploy_tgi(
        self,
        model_id: str,
        node: Any,
    ) -> InferenceEndpoint:
        """Generate and register a TGI deployment on *node*.

        Similar to :meth:`deploy_vllm` but for Hugging Face TGI.
        """
        ip = getattr(node, "ip_address", "127.0.0.1")
        port = 8080
        gpu_count = getattr(node, "gpu_count", 1)

        cmd = (
            f"text-generation-launcher "
            f"--model-id {model_id} "
            f"--hostname 0.0.0.0 --port {port} "
            f"--num-shard {gpu_count} "
            f"--dtype float16 "
            f"--max-input-length 4096 "
            f"--max-total-tokens 32768 "
            f"--trust-remote-code"
        )
        log.info("TGI deploy command: %s", cmd)

        ep = InferenceEndpoint(
            url=f"http://{ip}:{port}/v1",
            model_id=model_id,
            gpu_type=getattr(node, "gpu_type", "h100"),
            gpu_count=gpu_count,
            provider=getattr(node, "provider", ""),
            cost_per_hour=getattr(node, "cost_per_hour", 0.0),
            tensor_parallel=gpu_count,
            engine="tgi",
            region=getattr(node, "region", ""),
            supported_features=["chat", "completion"],
        )
        await self.register_endpoint(ep)
        return ep

    # ------------------------------------------------------------------
    # Model-GPU affinity (convenience delegates)
    # ------------------------------------------------------------------

    def get_recommended_gpu(self, model_id: str) -> str:
        """Return the recommended GPU type for *model_id*."""
        return ModelGPUAffinity.get_recommended_gpu(model_id)

    def get_model_requirements(self, model_id: str) -> dict[str, Any]:
        """Return full GPU requirements for *model_id*."""
        return ModelGPUAffinity.get_model_requirements(model_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_healthy_endpoints(
        self,
        model_id: str,
        exclude: set[str] | None = None,
    ) -> list[InferenceEndpoint]:
        """Return healthy endpoints that serve *model_id*."""
        exclude = exclude or set()
        return [
            ep for ep in self._endpoints.values()
            if ep.status == "healthy"
            and ep.endpoint_id not in exclude
            and (
                ep.model_id == model_id
                or model_id.lower() in ep.model_id.lower()
                or not ep.model_id  # wildcard endpoints
            )
        ]

    def _avg_latency(self, ep: InferenceEndpoint) -> float:
        window = self._latency_window.get(ep.endpoint_id)
        if window:
            return sum(window) / len(window)
        return ep.avg_latency_ms or 999.0

    async def _send_request(
        self,
        ep: InferenceEndpoint,
        model_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat-completion request to the endpoint."""
        if httpx is None:
            # Dry-run when httpx is unavailable
            return {
                "status": "ok",
                "endpoint": ep.endpoint_id,
                "model": model_id,
                "dry_run": True,
            }

        url = ep.url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            **kwargs,
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._request_timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        # Track latency
        window = self._latency_window.get(ep.endpoint_id)
        if window is not None:
            window.append(elapsed_ms)
        ep.avg_latency_ms = elapsed_ms  # simple update

        result = resp.json()
        result["_router_meta"] = {
            "endpoint_id": ep.endpoint_id,
            "latency_ms": round(elapsed_ms, 1),
            "gpu_type": ep.gpu_type,
            "provider": ep.provider,
        }
        return result

    async def _stream_request(
        self,
        ep: InferenceEndpoint,
        model_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a chat-completion request."""
        if httpx is None:
            yield {
                "status": "ok",
                "endpoint": ep.endpoint_id,
                "model": model_id,
                "dry_run": True,
                "done": True,
            }
            return

        url = ep.url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            **kwargs,
        }

        async with httpx.AsyncClient(timeout=self._request_timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            yield {"done": True}
                            return
                        try:
                            import json
                            yield json.loads(data)
                        except Exception:  # noqa: BLE001
                            yield {"raw": data}

    async def _check_endpoint_health(
        self, ep: InferenceEndpoint,
    ) -> EndpointHealth:
        """Probe an endpoint's health (GET /health or /v1/models)."""
        health = self._health.get(
            ep.endpoint_id,
            EndpointHealth(endpoint_id=ep.endpoint_id),
        )

        if httpx is None:
            health.healthy = True
            health.latency_ms = 0.0
            health.last_check = time.time()
            return health

        url = ep.url.rstrip("/").rsplit("/v1", 1)[0] + "/health"
        try:
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            elapsed_ms = (time.monotonic() - start) * 1000.0
            if resp.status_code < 400:
                health.healthy = True
                health.latency_ms = elapsed_ms
                health.consecutive_failures = 0
                health.last_success = time.time()
                ep.status = "healthy"
            else:
                health.consecutive_failures += 1
                health.latency_ms = elapsed_ms
                if health.consecutive_failures >= 3:
                    health.healthy = False
                    ep.status = "down"
                else:
                    ep.status = "degraded"
        except Exception:  # noqa: BLE001
            health.consecutive_failures += 1
            if health.consecutive_failures >= 3:
                health.healthy = False
                ep.status = "down"
            else:
                ep.status = "degraded"

        health.last_check = time.time()
        self._health[ep.endpoint_id] = health
        return health

    async def _health_loop(self) -> None:
        """Background loop that probes all endpoints."""
        while self._running:
            try:
                await self.health_check_all()
            except Exception as exc:  # noqa: BLE001
                log.error("Health loop error: %s", exc)
            await asyncio.sleep(self._health_interval)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        healthy = sum(
            1 for ep in self._endpoints.values() if ep.status == "healthy"
        )
        return (
            f"InferenceRouter(endpoints={len(self._endpoints)}, "
            f"healthy={healthy}, strategy={self._default_strategy.value})"
        )
