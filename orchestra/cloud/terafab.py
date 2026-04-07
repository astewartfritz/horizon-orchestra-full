"""Terafab Runtime — Horizon's custom compute infrastructure.

Interface-compatible with LambdaRuntime so Orchestra can migrate
seamlessly once Terafab is operational. Terafab is designed for:
- Persistent GPU-backed containers (not ephemeral like Lambda)
- Direct vLLM/SGLang integration (models loaded in-process)
- Sub-10ms function dispatch (no cold start)
- Multi-tenant with per-user GPU time-slicing
- Native support for long-running agent loops (hours, not 15min)

Until Terafab hardware is live, this module falls back to local
subprocess execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .compute import (
    ComputeBackend,
    ComputeRequest,
    ComputeResponse,
    FunctionSpec,
    RuntimeInfo,
)

__all__ = ["TerafabRuntime", "TerafabConfig"]

log = logging.getLogger("orchestra.cloud.terafab")


@dataclass
class TerafabConfig:
    """Configuration for the Terafab compute backend."""
    # Terafab cluster endpoint (when live)
    endpoint: str = ""                     # e.g. "https://compute.terafab.horizon.dev"
    api_key: str = ""
    cluster_id: str = ""

    # GPU configuration
    gpu_type: str = "h200"                 # h200, h100, a100, l40s
    gpu_count: int = 1
    gpu_memory_gb: int = 80

    # Container configuration
    base_image: str = "horizon/orchestra:latest"
    persistent_storage_gb: int = 100
    vllm_preloaded: bool = True           # model loaded at container boot
    model_id: str = "moonshotai/Kimi-K2.5"

    # Execution
    max_runtime_hours: int = 24           # no 15-min Lambda limit
    max_concurrent: int = 50
    enable_gpu_timeslice: bool = True

    # Fallback when Terafab isn't live
    fallback_to_local: bool = True
    local_workspace: str = "/tmp/terafab_workspace"


class TerafabRuntime(ComputeBackend):
    """Terafab compute backend — Horizon's custom infrastructure.

    Falls back to local subprocess execution until Terafab cluster
    is deployed. The interface is identical to LambdaRuntime.
    """

    name = "terafab"

    def __init__(self, config: TerafabConfig | None = None) -> None:
        self.config = config or TerafabConfig()
        self._live = bool(self.config.endpoint)
        self._functions: dict[str, FunctionSpec] = {}
        self._results: dict[str, ComputeResponse] = {}

    @property
    def is_live(self) -> bool:
        """Whether Terafab cluster is reachable."""
        return self._live

    async def invoke(self, request: ComputeRequest) -> ComputeResponse:
        """Invoke on Terafab or fall back to local."""
        if self._live:
            return await self._invoke_terafab(request)
        if self.config.fallback_to_local:
            return await self._invoke_local(request)
        return ComputeResponse(
            request_id=request.id, status="error",
            error="Terafab cluster not available and fallback disabled",
            backend="terafab",
        )

    async def invoke_async(self, request: ComputeRequest) -> str:
        """Async invocation — runs in background task."""
        task = asyncio.create_task(self._invoke_and_store(request))
        return request.id

    async def _invoke_and_store(self, request: ComputeRequest) -> None:
        resp = await self.invoke(request)
        self._results[request.id] = resp

    async def get_result(self, request_id: str) -> ComputeResponse | None:
        return self._results.get(request_id)

    async def deploy(self, spec: FunctionSpec) -> dict[str, Any]:
        self._functions[spec.name] = spec
        if self._live:
            return await self._deploy_terafab(spec)
        return {"deployed": True, "function": spec.name, "backend": "terafab_local", "note": "Registered locally — will deploy to cluster when live"}

    async def list_functions(self) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "handler": s.handler, "memory": s.memory_mb, "timeout": s.timeout}
            for s in self._functions.values()
        ]

    async def health(self) -> RuntimeInfo:
        return RuntimeInfo(
            backend="terafab" if self._live else "terafab_local",
            instance_id=self.config.cluster_id or "local",
            memory_mb=self.config.gpu_memory_gb * 1024 if self._live else 8192,
            cpu_count=self.config.gpu_count * 16 if self._live else os.cpu_count() or 4,
            version="0.1.0",
        )

    async def scale(self, function: str, min_instances: int = 0, max_instances: int = 100) -> dict[str, Any]:
        if not self._live:
            return {"note": "Terafab not live — scaling has no effect locally"}
        return await self._scale_terafab(function, min_instances, max_instances)

    # -- Terafab cluster calls (when live) ----------------------------------

    async def _invoke_terafab(self, request: ComputeRequest) -> ComputeResponse:
        """Call the Terafab cluster API."""
        import httpx
        t0 = time.monotonic()
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        body = {
            "request_id": request.id,
            "function": request.function,
            "payload": request.payload,
            "user_id": request.user_id,
            "timeout": request.timeout,
            "gpu_type": self.config.gpu_type,
            "gpu_count": self.config.gpu_count,
        }

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(f"{self.config.endpoint}/v1/invoke", headers=headers, json=body)
                data = resp.json()

            return ComputeResponse(
                request_id=request.id,
                status="success" if resp.status_code == 200 else "error",
                result=data.get("result", {}),
                error=data.get("error", ""),
                duration_ms=round((time.monotonic() - t0) * 1000, 2),
                backend="terafab",
                cold_start=data.get("cold_start", False),
                metadata={
                    "gpu_type": self.config.gpu_type,
                    "cluster_id": self.config.cluster_id,
                    "node_id": data.get("node_id", ""),
                },
            )
        except Exception as exc:
            return ComputeResponse(
                request_id=request.id, status="error", error=str(exc),
                duration_ms=(time.monotonic() - t0) * 1000, backend="terafab",
            )

    async def _deploy_terafab(self, spec: FunctionSpec) -> dict[str, Any]:
        """Deploy to the Terafab cluster."""
        import httpx
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        body = {
            "name": spec.name,
            "handler": spec.handler,
            "runtime": spec.runtime,
            "memory_mb": spec.memory_mb,
            "timeout": spec.timeout,
            "environment": spec.environment,
            "gpu_type": self.config.gpu_type,
            "gpu_count": self.config.gpu_count,
            "base_image": self.config.base_image,
            "vllm_preloaded": self.config.vllm_preloaded,
            "model_id": self.config.model_id,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{self.config.endpoint}/v1/deploy", headers=headers, json=body)
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}

    async def _scale_terafab(self, function: str, min_inst: int, max_inst: int) -> dict[str, Any]:
        import httpx
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.config.endpoint}/v1/scale",
                    headers=headers,
                    json={"function": function, "min": min_inst, "max": max_inst, "gpu_timeslice": self.config.enable_gpu_timeslice},
                )
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}

    # -- Local fallback (until Terafab is live) -----------------------------

    async def _invoke_local(self, request: ComputeRequest) -> ComputeResponse:
        """Execute locally as subprocess fallback."""
        t0 = time.monotonic()

        # Route to Orchestra components locally
        payload = request.payload
        action = payload.get("action", "run")

        try:
            if action == "run":
                from ..arch_a import MonolithicAgent, MonolithicConfig
                config = MonolithicConfig(user_id=request.user_id)
                agent = MonolithicAgent(config=config)
                result = await agent.run(payload.get("task", ""))
                return ComputeResponse(
                    request_id=request.id, status="success",
                    result={"output": result, "stats": agent.stats},
                    duration_ms=round((time.monotonic() - t0) * 1000, 2),
                    backend="terafab_local",
                )
            elif action == "query":
                from ..router import ModelRouter
                router = ModelRouter()
                client, model_id = router.get_client(payload.get("model", "kimi-k2.5"))
                resp = await client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": payload.get("prompt", "")}],
                    max_tokens=payload.get("max_tokens", 4096),
                )
                return ComputeResponse(
                    request_id=request.id, status="success",
                    result={"content": resp.choices[0].message.content},
                    duration_ms=round((time.monotonic() - t0) * 1000, 2),
                    backend="terafab_local",
                )
            else:
                return ComputeResponse(
                    request_id=request.id, status="error",
                    error=f"Unknown action: {action}", backend="terafab_local",
                )
        except Exception as exc:
            return ComputeResponse(
                request_id=request.id, status="error", error=str(exc),
                duration_ms=(time.monotonic() - t0) * 1000, backend="terafab_local",
            )
