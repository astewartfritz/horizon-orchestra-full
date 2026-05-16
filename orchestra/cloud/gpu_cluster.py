"""Multi-GPU Cluster Management — lifecycle, model deployment, distributed inference.

Orchestrates GPU nodes across one or more cloud providers, handles model
sharding (tensor-parallel + pipeline-parallel), NVLink topology reporting,
load-balanced inference, health monitoring, and cost tracking.

Usage::

    from orchestra.cloud.gpu_providers import GPUProviderRegistry
    from orchestra.cloud.gpu_cluster import GPUCluster, ClusterConfig

    registry = GPUProviderRegistry()
    config   = ClusterConfig(provider="lambda", gpu_type="h100", gpu_count=16)
    cluster  = GPUCluster(config, registry=registry)

    await cluster.create()
    endpoint = await cluster.deploy_model("meta-llama/Llama-3-70B",
                                           tensor_parallel=4,
                                           pipeline_parallel=2)
    result   = await cluster.infer("meta-llama/Llama-3-70B",
                                    messages=[{"role": "user", "content": "Hi"}])
    await cluster.destroy()
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from .gpu_providers import (
    GPUPricing,
    GPUProviderClient,
    GPUProviderRegistry,
    GPUSpec,
    ProviderConfig,
)

__all__ = [
    "ClusterConfig",
    "GPUNode",
    "GPUCluster",
    "ModelDeployment",
    "DeploymentStrategy",
    "InferenceResult",
]

log = logging.getLogger("orchestra.cloud.gpu_cluster")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClusterConfig:
    """Configuration for a multi-node GPU cluster."""

    name: str = "horizon-cluster"
    provider: str = "lambda"            # default provider
    gpu_type: str = "h100-sxm5"
    gpu_count: int = 8                  # total GPUs in cluster
    gpus_per_node: int = 8              # GPUs per physical node
    interconnect: str = "nvlink"        # "nvlink" | "infiniband" | "ethernet"
    spot: bool = False
    region: str = ""
    auto_scale: bool = True
    min_nodes: int = 1
    max_nodes: int = 16
    idle_timeout_minutes: int = 30

    # Advanced
    allow_heterogeneous: bool = False   # mix GPU types across nodes
    fallback_providers: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    max_cost_per_hour: float = 0.0      # 0 = no limit

    @property
    def total_nodes(self) -> int:
        return max(1, math.ceil(self.gpu_count / self.gpus_per_node))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "gpu_type": self.gpu_type,
            "gpu_count": self.gpu_count,
            "gpus_per_node": self.gpus_per_node,
            "interconnect": self.interconnect,
            "spot": self.spot,
            "region": self.region,
            "auto_scale": self.auto_scale,
            "min_nodes": self.min_nodes,
            "max_nodes": self.max_nodes,
            "idle_timeout_minutes": self.idle_timeout_minutes,
            "total_nodes": self.total_nodes,
        }


@dataclass
class GPUNode:
    """A single physical node in the cluster."""

    node_id: str
    provider: str
    instance_id: str
    gpu_type: str
    gpu_count: int
    status: str                         # "provisioning" | "ready" | "busy" | "draining" | "terminated"
    ip_address: str
    region: str
    gpu_utilization: list[float]        # per-GPU utilization 0-100
    memory_used_gb: list[float]         # per-GPU memory used
    inference_endpoint: str             # vLLM/TGI endpoint URL
    created_at: float
    cost_per_hour: float

    # Extended fields
    hostname: str = ""
    node_rank: int = 0                  # rank in cluster
    nvlink_domain: int = 0              # NVLink domain ID
    last_heartbeat: float = 0.0
    models_loaded: list[str] = field(default_factory=list)
    error_count: int = 0

    @property
    def uptime_hours(self) -> float:
        """Hours since node was created."""
        return (time.time() - self.created_at) / 3600

    @property
    def total_cost(self) -> float:
        """Accumulated cost since creation."""
        return self.uptime_hours * self.cost_per_hour

    @property
    def is_healthy(self) -> bool:
        """Quick health indicator based on status and heartbeat."""
        if self.status in ("terminated", "draining"):
            return False
        if self.last_heartbeat and (time.time() - self.last_heartbeat) > 120:
            return False
        return True

    @property
    def avg_utilization(self) -> float:
        """Average GPU utilization across all GPUs in this node."""
        if not self.gpu_utilization:
            return 0.0
        return sum(self.gpu_utilization) / len(self.gpu_utilization)

    @property
    def total_memory_used_gb(self) -> float:
        """Sum of memory used across all GPUs."""
        return sum(self.memory_used_gb) if self.memory_used_gb else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "provider": self.provider,
            "instance_id": self.instance_id,
            "gpu_type": self.gpu_type,
            "gpu_count": self.gpu_count,
            "status": self.status,
            "ip_address": self.ip_address,
            "region": self.region,
            "gpu_utilization": self.gpu_utilization,
            "memory_used_gb": self.memory_used_gb,
            "inference_endpoint": self.inference_endpoint,
            "created_at": self.created_at,
            "cost_per_hour": self.cost_per_hour,
            "uptime_hours": round(self.uptime_hours, 2),
            "total_cost": round(self.total_cost, 2),
            "is_healthy": self.is_healthy,
            "avg_utilization": round(self.avg_utilization, 1),
            "models_loaded": self.models_loaded,
            "node_rank": self.node_rank,
            "nvlink_domain": self.nvlink_domain,
        }


@dataclass
class ModelDeployment:
    """Tracks a model deployed across one or more nodes in the cluster."""

    model_id: str
    endpoint: str                       # primary inference endpoint
    tensor_parallel: int                # TP degree (GPUs within a node)
    pipeline_parallel: int              # PP degree (across nodes)
    total_gpus: int                     # TP × PP
    node_ids: list[str]                 # nodes hosting this model
    status: str                         # "deploying" | "ready" | "degraded" | "stopped"
    created_at: float
    requests_served: int = 0
    avg_latency_ms: float = 0.0
    tokens_generated: int = 0

    @property
    def uptime_hours(self) -> float:
        return (time.time() - self.created_at) / 3600

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "tensor_parallel": self.tensor_parallel,
            "pipeline_parallel": self.pipeline_parallel,
            "total_gpus": self.total_gpus,
            "node_ids": self.node_ids,
            "status": self.status,
            "requests_served": self.requests_served,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "tokens_generated": self.tokens_generated,
        }


@dataclass
class DeploymentStrategy:
    """Defines how a model should be sharded across GPUs.

    The strategy is computed from the model size, GPU VRAM, and cluster
    topology.  For example, a 70B FP16 model (~140 GB) on 8× H100 80 GB
    would use TP=2 (fits on 2 GPUs), PP=1.
    """

    tensor_parallel: int = 1
    pipeline_parallel: int = 1
    max_batch_size: int = 64
    quantization: str = ""              # "" | "fp8" | "int8" | "int4" | "fp4"
    engine: str = "vllm"               # "vllm" | "tgi" | "sglang"
    kv_cache_dtype: str = "auto"
    max_model_len: int = 8192

    @property
    def total_gpus(self) -> int:
        return self.tensor_parallel * self.pipeline_parallel


@dataclass
class InferenceResult:
    """Result from a cluster inference call."""

    model_id: str
    content: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    node_id: str = ""
    gpu_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "content": self.content,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "node_id": self.node_id,
            "gpu_type": self.gpu_type,
        }


# ---------------------------------------------------------------------------
# GPU Cluster
# ---------------------------------------------------------------------------

class GPUCluster:
    """Multi-node GPU cluster for distributed inference/training.

    Manages a cluster of GPU nodes across one or more providers,
    handles model sharding, load balancing, health monitoring,
    and cost tracking.

    Supports:
    - Single-node (1-8 GPUs with NVLink)
    - Multi-node (InfiniBand/EFA interconnect)
    - Heterogeneous (mix H100 + A100 for different models)
    - Auto-scaling based on load
    - Model parallelism (tensor parallel, pipeline parallel)
    """

    def __init__(
        self,
        config: ClusterConfig,
        registry: GPUProviderRegistry | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or GPUProviderRegistry()
        self.cluster_id = f"hzn-{uuid.uuid4().hex[:8]}"

        # State
        self._nodes: dict[str, GPUNode] = {}
        self._deployments: dict[str, ModelDeployment] = {}
        self._created_at: float = 0.0
        self._destroyed: bool = False
        self._scaling_lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None

        # Metrics
        self._total_requests: int = 0
        self._total_tokens: int = 0
        self._total_cost: float = 0.0

        log.info(
            "GPUCluster initialised: %s — %d × %s on %s",
            self.cluster_id, config.gpu_count, config.gpu_type, config.provider,
        )

    # ===================================================================
    # Lifecycle
    # ===================================================================

    async def create(self) -> None:
        """Provision all nodes and bring the cluster online.

        Creates ``ceil(gpu_count / gpus_per_node)`` nodes on the
        configured provider, waits for them to reach ``"ready"``
        status, and starts the background health-monitor.
        """
        if self._nodes:
            log.warning("Cluster %s already has nodes — skipping create", self.cluster_id)
            return

        self._created_at = time.time()
        num_nodes = self.config.total_nodes
        log.info("Creating cluster %s with %d nodes …", self.cluster_id, num_nodes)

        client = self.registry.get(self.config.provider)

        # Provision nodes in parallel
        tasks = [
            self._provision_node(client, rank=i)
            for i in range(num_nodes)
        ]
        nodes = await asyncio.gather(*tasks, return_exceptions=True)

        for result in nodes:
            if isinstance(result, GPUNode):
                self._nodes[result.node_id] = result
            else:
                log.error("Failed to provision node: %s", result)

        log.info(
            "Cluster %s online — %d/%d nodes ready",
            self.cluster_id, len(self._nodes), num_nodes,
        )

        # Start background health monitor
        self._health_task = asyncio.ensure_future(self._health_monitor_loop())

    async def destroy(self) -> None:
        """Tear down the entire cluster — deprovision all nodes.

        Stops all model deployments, terminates nodes, and cancels
        the health-monitor background task.
        """
        if self._destroyed:
            return

        log.info("Destroying cluster %s (%d nodes) …", self.cluster_id, len(self._nodes))

        # Stop health monitor
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Undeploy all models
        for model_id in list(self._deployments):
            await self.undeploy_model(model_id)

        # Deprovision nodes
        client = self.registry.get(self.config.provider)
        for node in list(self._nodes.values()):
            try:
                await client.deprovision(node.instance_id)
                node.status = "terminated"
            except Exception as exc:
                log.error("Error deprovisioning node %s: %s", node.node_id, exc)

        self._destroyed = True
        self._snapshot_cost()
        log.info("Cluster %s destroyed. Total cost: $%.2f", self.cluster_id, self._total_cost)

    async def scale_up(self, count: int = 1) -> list[GPUNode]:
        """Add *count* new nodes to the cluster.

        Respects ``max_nodes`` from ClusterConfig.  Returns the list of
        newly provisioned GPUNode objects.
        """
        async with self._scaling_lock:
            current = len(self._nodes)
            allowed = min(count, self.config.max_nodes - current)
            if allowed <= 0:
                log.warning(
                    "Cannot scale up: already at %d/%d max nodes",
                    current, self.config.max_nodes,
                )
                return []

            log.info("Scaling up cluster %s: +%d nodes", self.cluster_id, allowed)
            client = self.registry.get(self.config.provider)

            tasks = [
                self._provision_node(client, rank=current + i)
                for i in range(allowed)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_nodes: list[GPUNode] = []
            for result in results:
                if isinstance(result, GPUNode):
                    self._nodes[result.node_id] = result
                    new_nodes.append(result)
                else:
                    log.error("Scale-up provision failed: %s", result)

            log.info("Scaled up: %d new nodes (total %d)", len(new_nodes), len(self._nodes))
            return new_nodes

    async def scale_down(self, count: int = 1) -> list[str]:
        """Remove *count* nodes from the cluster (least-utilised first).

        Respects ``min_nodes``.  Returns a list of removed node IDs.
        """
        async with self._scaling_lock:
            current = len([n for n in self._nodes.values() if n.status != "terminated"])
            allowed = min(count, current - self.config.min_nodes)
            if allowed <= 0:
                log.warning(
                    "Cannot scale down: at minimum %d nodes",
                    self.config.min_nodes,
                )
                return []

            # Sort by utilization ascending (remove least-used first)
            candidates = sorted(
                [n for n in self._nodes.values() if n.status in ("ready", "busy")],
                key=lambda n: n.avg_utilization,
            )

            removed: list[str] = []
            client = self.registry.get(self.config.provider)

            for node in candidates[:allowed]:
                node.status = "draining"
                try:
                    await client.deprovision(node.instance_id)
                    node.status = "terminated"
                    removed.append(node.node_id)
                except Exception as exc:
                    log.error("Error removing node %s: %s", node.node_id, exc)

            log.info("Scaled down: removed %d nodes (%s)", len(removed), removed)
            return removed

    # ===================================================================
    # Node management
    # ===================================================================

    async def add_node(
        self,
        provider: str = "",
        gpu_type: str = "",
        spot: bool = False,
    ) -> GPUNode:
        """Add a single node, optionally from a different provider/GPU type.

        Useful for heterogeneous clusters.
        """
        prov = provider or self.config.provider
        gtype = gpu_type or self.config.gpu_type
        client = self.registry.get(prov)

        rank = len(self._nodes)
        node = await self._provision_node(
            client, rank=rank, gpu_type_override=gtype, spot_override=spot,
        )
        self._nodes[node.node_id] = node
        return node

    async def remove_node(self, node_id: str) -> None:
        """Remove a specific node by ID."""
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found in cluster {self.cluster_id}")

        node = self._nodes[node_id]
        client = self.registry.get(node.provider)
        node.status = "draining"

        # Undeploy models hosted on this node
        for deployment in self._deployments.values():
            if node_id in deployment.node_ids:
                deployment.node_ids.remove(node_id)
                if not deployment.node_ids:
                    deployment.status = "stopped"

        await client.deprovision(node.instance_id)
        node.status = "terminated"
        log.info("Removed node %s from cluster %s", node_id, self.cluster_id)

    async def get_node(self, node_id: str) -> GPUNode | None:
        """Retrieve node info by ID."""
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[GPUNode]:
        """Return all nodes (including terminated) in the cluster."""
        return list(self._nodes.values())

    def active_nodes(self) -> list[GPUNode]:
        """Return only non-terminated nodes."""
        return [n for n in self._nodes.values() if n.status != "terminated"]

    # ===================================================================
    # Model deployment
    # ===================================================================

    async def deploy_model(
        self,
        model_id: str,
        tensor_parallel: int = 1,
        pipeline_parallel: int = 1,
        engine: str = "vllm",
        quantization: str = "",
        max_model_len: int = 8192,
    ) -> str:
        """Deploy a model across the cluster and return the inference endpoint.

        *tensor_parallel* shards the model within a single node (requires
        NVLink).  *pipeline_parallel* distributes layers across nodes
        (requires InfiniBand / EFA).  The total GPU requirement is
        ``tensor_parallel × pipeline_parallel``.

        Returns the primary endpoint URL (e.g. ``http://10.0.1.5:8000/v1``).
        """
        total_gpus_needed = tensor_parallel * pipeline_parallel
        active = self.active_nodes()

        if not active:
            raise RuntimeError(f"No active nodes in cluster {self.cluster_id}")

        # Select nodes for this deployment
        assigned_nodes = self._select_nodes_for_deployment(
            active, total_gpus_needed, tensor_parallel,
        )

        if not assigned_nodes:
            raise RuntimeError(
                f"Cannot deploy {model_id}: need {total_gpus_needed} GPUs, "
                f"but insufficient capacity across {len(active)} nodes"
            )

        primary_node = assigned_nodes[0]
        endpoint = f"http://{primary_node.ip_address}:8000/v1"

        deployment = ModelDeployment(
            model_id=model_id,
            endpoint=endpoint,
            tensor_parallel=tensor_parallel,
            pipeline_parallel=pipeline_parallel,
            total_gpus=total_gpus_needed,
            node_ids=[n.node_id for n in assigned_nodes],
            status="ready",
            created_at=time.time(),
        )

        self._deployments[model_id] = deployment

        # Mark nodes as hosting this model
        for node in assigned_nodes:
            node.models_loaded.append(model_id)
            node.status = "busy"

        log.info(
            "Deployed %s on %d nodes (TP=%d, PP=%d) → %s",
            model_id, len(assigned_nodes), tensor_parallel,
            pipeline_parallel, endpoint,
        )
        return endpoint

    async def undeploy_model(self, model_id: str) -> None:
        """Remove a model deployment from the cluster."""
        deployment = self._deployments.pop(model_id, None)
        if deployment is None:
            log.warning("Model %s not found in cluster %s", model_id, self.cluster_id)
            return

        deployment.status = "stopped"

        # Update nodes
        for node_id in deployment.node_ids:
            node = self._nodes.get(node_id)
            if node and model_id in node.models_loaded:
                node.models_loaded.remove(model_id)
                if not node.models_loaded:
                    node.status = "ready"

        log.info("Undeployed %s from cluster %s", model_id, self.cluster_id)

    def get_deployment(self, model_id: str) -> ModelDeployment | None:
        """Return deployment info for a model."""
        return self._deployments.get(model_id)

    def list_deployments(self) -> list[ModelDeployment]:
        """Return all active model deployments."""
        return list(self._deployments.values())

    def compute_deployment_strategy(
        self,
        model_id: str,
        param_billions: float,
        precision_bytes: int = 2,
    ) -> DeploymentStrategy:
        """Compute optimal TP/PP for a model given cluster GPU specs.

        The heuristic:
        1. Calculate model weight size: param_billions × precision_bytes GB
        2. Determine how many GPUs needed for weights alone
        3. Choose TP = min(gpus_needed_per_node, gpus_per_node)
        4. Choose PP = ceil(total_gpus / TP)
        """
        try:
            spec = self.registry.get_gpu_spec(self.config.gpu_type)
            vram_per_gpu = spec.vram_gb
        except KeyError:
            vram_per_gpu = 80  # fallback

        model_size_gb = param_billions * precision_bytes
        # Leave 25 % for KV cache + activations
        usable_vram = vram_per_gpu * 0.75

        gpus_for_weights = max(1, math.ceil(model_size_gb / usable_vram))
        gpus_per_node = self.config.gpus_per_node

        # Tensor parallel within a single node
        tp = min(gpus_for_weights, gpus_per_node)
        # Pipeline parallel across nodes
        pp = max(1, math.ceil(gpus_for_weights / tp))

        total_available = len(self.active_nodes()) * gpus_per_node
        if tp * pp > total_available:
            log.warning(
                "Model %s needs %d GPUs but cluster has %d — will be constrained",
                model_id, tp * pp, total_available,
            )

        # Pick quantization if model is very large
        quantization = ""
        if model_size_gb > vram_per_gpu * gpus_per_node * 2:
            quantization = "fp8"

        return DeploymentStrategy(
            tensor_parallel=tp,
            pipeline_parallel=pp,
            max_batch_size=max(1, 256 // (tp * pp)),
            quantization=quantization,
            engine="vllm",
            max_model_len=8192 if param_billions < 100 else 4096,
        )

    # ===================================================================
    # Inference
    # ===================================================================

    async def infer(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a single inference request against a deployed model.

        Routes to the correct node(s) based on the deployment.  In
        production, this calls the vLLM/TGI OpenAI-compatible endpoint;
        the base implementation returns a simulated response.
        """
        deployment = self._deployments.get(model_id)
        if deployment is None or deployment.status != "ready":
            raise RuntimeError(
                f"Model {model_id} not deployed or not ready in cluster {self.cluster_id}"
            )

        start = time.time()

        # Select the least-loaded node for this deployment
        node = self._select_inference_node(deployment)

        # In production: POST to node.inference_endpoint
        # Simulated response for framework integration
        prompt_text = " ".join(
            m.get("content", "") for m in messages if m.get("role") == "user"
        )
        prompt_tokens = max(1, len(prompt_text.split()))
        completion_tokens = kwargs.get("max_tokens", 256)

        result = InferenceResult(
            model_id=model_id,
            content=f"[{model_id} on {node.gpu_type}] Inference placeholder",
            finish_reason="stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=(time.time() - start) * 1000,
            node_id=node.node_id,
            gpu_type=node.gpu_type,
        )

        # Update metrics
        deployment.requests_served += 1
        deployment.tokens_generated += completion_tokens
        deployment.avg_latency_ms = (
            (deployment.avg_latency_ms * (deployment.requests_served - 1)
             + result.latency_ms) / deployment.requests_served
        )

        self._total_requests += 1
        self._total_tokens += result.total_tokens

        return result.to_dict()

    async def stream_infer(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream inference tokens from a deployed model.

        Yields dicts with keys: ``token``, ``finish_reason``, ``model_id``.
        """
        deployment = self._deployments.get(model_id)
        if deployment is None or deployment.status != "ready":
            raise RuntimeError(f"Model {model_id} not deployed in cluster {self.cluster_id}")

        node = self._select_inference_node(deployment)
        max_tokens = kwargs.get("max_tokens", 128)

        for i in range(max_tokens):
            chunk = {
                "token": f"token_{i}",
                "index": i,
                "model_id": model_id,
                "node_id": node.node_id,
                "finish_reason": None,
            }
            if i == max_tokens - 1:
                chunk["finish_reason"] = "stop"

            yield chunk

        deployment.requests_served += 1
        deployment.tokens_generated += max_tokens
        self._total_requests += 1
        self._total_tokens += max_tokens

    # ===================================================================
    # Health & Metrics
    # ===================================================================

    async def health_check(self) -> dict[str, Any]:
        """Run a health check across all nodes.

        Returns a summary dict with per-node status, overall cluster
        health, and aggregate metrics.
        """
        node_health: dict[str, dict[str, Any]] = {}
        healthy_count = 0
        total_count = 0

        for node_id, node in self._nodes.items():
            if node.status == "terminated":
                continue
            total_count += 1

            status = {
                "node_id": node_id,
                "status": node.status,
                "is_healthy": node.is_healthy,
                "gpu_utilization": node.gpu_utilization,
                "memory_used_gb": node.memory_used_gb,
                "models_loaded": node.models_loaded,
                "uptime_hours": round(node.uptime_hours, 2),
                "error_count": node.error_count,
            }
            node_health[node_id] = status

            if node.is_healthy:
                healthy_count += 1

        cluster_healthy = healthy_count == total_count and total_count > 0

        return {
            "cluster_id": self.cluster_id,
            "cluster_name": self.config.name,
            "healthy": cluster_healthy,
            "nodes_healthy": healthy_count,
            "nodes_total": total_count,
            "deployments_active": len(self._deployments),
            "total_requests": self._total_requests,
            "total_tokens": self._total_tokens,
            "nodes": node_health,
        }

    def get_utilization(self) -> dict[str, Any]:
        """Aggregate utilization metrics across all active nodes."""
        active = self.active_nodes()
        if not active:
            return {
                "cluster_id": self.cluster_id,
                "avg_gpu_utilization": 0.0,
                "avg_memory_utilization": 0.0,
                "total_gpus": 0,
                "busy_gpus": 0,
                "idle_gpus": 0,
            }

        total_gpus = sum(n.gpu_count for n in active)
        all_utils = []
        for n in active:
            all_utils.extend(n.gpu_utilization)

        avg_util = sum(all_utils) / len(all_utils) if all_utils else 0.0
        busy = sum(1 for u in all_utils if u > 10.0)

        # Memory utilization
        try:
            spec = self.registry.get_gpu_spec(self.config.gpu_type)
            vram = spec.vram_gb
        except KeyError:
            vram = 80

        total_mem = sum(n.total_memory_used_gb for n in active)
        total_capacity = total_gpus * vram
        mem_util = (total_mem / total_capacity * 100) if total_capacity > 0 else 0.0

        return {
            "cluster_id": self.cluster_id,
            "avg_gpu_utilization": round(avg_util, 1),
            "avg_memory_utilization": round(mem_util, 1),
            "total_gpus": total_gpus,
            "busy_gpus": busy,
            "idle_gpus": total_gpus - busy,
            "nodes_active": len(active),
            "models_deployed": len(self._deployments),
        }

    def get_cost_report(self) -> dict[str, Any]:
        """Generate a cost report for the cluster.

        Includes per-node cost, total accumulated cost, projected
        hourly and daily spend, and cost-per-token.
        """
        self._snapshot_cost()

        active = self.active_nodes()
        hourly_rate = sum(n.cost_per_hour for n in active)
        per_node: list[dict[str, Any]] = []

        for node in self._nodes.values():
            per_node.append({
                "node_id": node.node_id,
                "provider": node.provider,
                "gpu_type": node.gpu_type,
                "gpu_count": node.gpu_count,
                "cost_per_hour": node.cost_per_hour,
                "total_cost": round(node.total_cost, 2),
                "uptime_hours": round(node.uptime_hours, 2),
                "status": node.status,
            })

        cost_per_token = (
            self._total_cost / self._total_tokens
            if self._total_tokens > 0 else 0.0
        )

        uptime_h = (time.time() - self._created_at) / 3600 if self._created_at else 0

        return {
            "cluster_id": self.cluster_id,
            "total_cost": round(self._total_cost, 2),
            "hourly_rate": round(hourly_rate, 2),
            "daily_projected": round(hourly_rate * 24, 2),
            "monthly_projected": round(hourly_rate * 24 * 30, 2),
            "cost_per_token": round(cost_per_token, 8),
            "cost_per_1k_tokens": round(cost_per_token * 1000, 4),
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
            "cluster_uptime_hours": round(uptime_h, 2),
            "nodes": per_node,
            "currency": "USD",
        }

    # ===================================================================
    # Topology
    # ===================================================================

    def get_topology(self) -> dict[str, Any]:
        """Return NVLink domain + InfiniBand fabric topology.

        Maps out which GPUs share NVLink domains (intra-node) and which
        nodes are connected via InfiniBand / EFA (inter-node).
        """
        active = self.active_nodes()

        # NVLink domains: each node is its own NVLink domain
        nvlink_domains: dict[int, list[str]] = defaultdict(list)
        for node in active:
            nvlink_domains[node.nvlink_domain].append(node.node_id)

        # Inter-node fabric
        fabric_links: list[dict[str, Any]] = []
        for i, n1 in enumerate(active):
            for n2 in active[i + 1:]:
                fabric_links.append({
                    "from": n1.node_id,
                    "to": n2.node_id,
                    "type": self.config.interconnect,
                    "bandwidth_gbps": self._interconnect_bandwidth(),
                })

        # Per-node GPU topology
        node_topologies: list[dict[str, Any]] = []
        for node in active:
            try:
                spec = self.registry.get_gpu_spec(node.gpu_type)
                nvlink_bw = spec.interconnect_bandwidth_gbps
            except KeyError:
                nvlink_bw = 0

            gpu_links: list[dict[str, Any]] = []
            for i in range(node.gpu_count):
                for j in range(i + 1, node.gpu_count):
                    gpu_links.append({
                        "gpu_a": i,
                        "gpu_b": j,
                        "type": "NVLink" if nvlink_bw > 0 else "PCIe",
                        "bandwidth_gbps": nvlink_bw,
                    })

            node_topologies.append({
                "node_id": node.node_id,
                "gpu_type": node.gpu_type,
                "gpu_count": node.gpu_count,
                "nvlink_domain": node.nvlink_domain,
                "intra_node_links": gpu_links,
                "nvlink_bandwidth_gbps": nvlink_bw,
            })

        return {
            "cluster_id": self.cluster_id,
            "interconnect": self.config.interconnect,
            "inter_node_bandwidth_gbps": self._interconnect_bandwidth(),
            "nvlink_domains": dict(nvlink_domains),
            "fabric_links": fabric_links,
            "node_topologies": node_topologies,
            "total_gpus": sum(n.gpu_count for n in active),
            "total_nodes": len(active),
        }

    # ===================================================================
    # Private helpers
    # ===================================================================

    async def _provision_node(
        self,
        client: GPUProviderClient,
        rank: int,
        gpu_type_override: str = "",
        spot_override: bool | None = None,
    ) -> GPUNode:
        """Provision a single node and return a GPUNode."""
        gpu_type = gpu_type_override or self.config.gpu_type
        spot = spot_override if spot_override is not None else self.config.spot

        instance = await client.provision(
            gpu_type=gpu_type,
            count=self.config.gpus_per_node,
            region=self.config.region,
            spot=spot,
        )

        # Look up cost from pricing
        cost_per_hour = 0.0
        pricing = await client.get_pricing(gpu_type)
        if pricing:
            per_gpu = pricing.spot_per_hour if (spot and pricing.spot_per_hour) else pricing.on_demand_per_hour
            cost_per_hour = per_gpu * self.config.gpus_per_node

        node_id = f"node-{self.cluster_id}-{rank:03d}"
        ip_addr = f"10.0.{rank // 256}.{rank % 256 + 1}"

        node = GPUNode(
            node_id=node_id,
            provider=client.provider.name,
            instance_id=instance["instance_id"],
            gpu_type=gpu_type,
            gpu_count=self.config.gpus_per_node,
            status="ready",
            ip_address=ip_addr,
            region=instance.get("region", self.config.region),
            gpu_utilization=[0.0] * self.config.gpus_per_node,
            memory_used_gb=[0.0] * self.config.gpus_per_node,
            inference_endpoint=f"http://{ip_addr}:8000/v1",
            created_at=time.time(),
            cost_per_hour=cost_per_hour,
            hostname=f"{self.config.name}-{rank:03d}",
            node_rank=rank,
            nvlink_domain=rank,
            last_heartbeat=time.time(),
        )

        log.debug("Provisioned node %s (rank %d) on %s", node_id, rank, client.provider.name)
        return node

    def _select_nodes_for_deployment(
        self,
        active_nodes: list[GPUNode],
        total_gpus: int,
        tensor_parallel: int,
    ) -> list[GPUNode]:
        """Choose which nodes host a model deployment.

        Prefers nodes with enough GPUs for a full TP shard.
        """
        selected: list[GPUNode] = []
        remaining_gpus = total_gpus

        # Sort by utilisation (prefer least-loaded)
        candidates = sorted(active_nodes, key=lambda n: n.avg_utilization)

        for node in candidates:
            if remaining_gpus <= 0:
                break
            if node.gpu_count >= tensor_parallel:
                selected.append(node)
                remaining_gpus -= tensor_parallel

        return selected

    def _select_inference_node(self, deployment: ModelDeployment) -> GPUNode:
        """Pick the best node for an inference request (least-loaded)."""
        candidate_nodes = [
            self._nodes[nid]
            for nid in deployment.node_ids
            if nid in self._nodes and self._nodes[nid].is_healthy
        ]

        if not candidate_nodes:
            # Fallback: pick any healthy node
            candidate_nodes = [n for n in self._nodes.values() if n.is_healthy]

        if not candidate_nodes:
            raise RuntimeError("No healthy nodes available for inference")

        return min(candidate_nodes, key=lambda n: n.avg_utilization)

    def _interconnect_bandwidth(self) -> int:
        """Parse inter-node bandwidth from config.interconnect."""
        mapping = {
            "nvlink": 900,
            "infiniband": 400,
            "infiniband-400g": 400,
            "infiniband-200g": 200,
            "efa": 3200,
            "efa-3200g": 3200,
            "rdma": 200,
            "ethernet": 100,
        }
        return mapping.get(self.config.interconnect, 100)

    def _snapshot_cost(self) -> None:
        """Update total cost based on current node uptimes."""
        self._total_cost = sum(n.total_cost for n in self._nodes.values())

    async def _health_monitor_loop(self) -> None:
        """Background loop that checks node health every 30 seconds."""
        try:
            while True:
                await asyncio.sleep(30)
                for node in self.active_nodes():
                    node.last_heartbeat = time.time()
                    # In production: ping node endpoint, check GPU utilisation
                    if node.error_count > 10:
                        log.warning(
                            "Node %s has %d errors — marking unhealthy",
                            node.node_id, node.error_count,
                        )
                        node.status = "draining"
        except asyncio.CancelledError:
            log.debug("Health monitor stopped for cluster %s", self.cluster_id)

    # ===================================================================
    # Serialisation / repr
    # ===================================================================

    def to_dict(self) -> dict[str, Any]:
        """Full cluster state as a dict."""
        return {
            "cluster_id": self.cluster_id,
            "config": self.config.to_dict(),
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "deployments": {mid: d.to_dict() for mid, d in self._deployments.items()},
            "metrics": {
                "total_requests": self._total_requests,
                "total_tokens": self._total_tokens,
                "total_cost": round(self._total_cost, 2),
            },
        }

    def summary(self) -> str:
        """One-line human-readable summary."""
        active = self.active_nodes()
        return (
            f"GPUCluster({self.cluster_id}): "
            f"{len(active)} active nodes, "
            f"{sum(n.gpu_count for n in active)} GPUs, "
            f"{len(self._deployments)} deployments"
        )

    def __repr__(self) -> str:
        return (
            f"<GPUCluster id={self.cluster_id} "
            f"nodes={len(self._nodes)} "
            f"gpu_type={self.config.gpu_type}>"
        )
