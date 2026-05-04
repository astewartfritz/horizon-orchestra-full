"""Compute Abstraction Layer — the interface that Lambda and Terafab both implement.

Every cloud backend implements ComputeBackend. Orchestra's kernel,
agent loop, and swarm call this interface — they never know whether
they're running on Lambda, Terafab, or bare metal.

Usage::

    backend: ComputeBackend = LambdaRuntime()   # now
    backend: ComputeBackend = TerafabRuntime()   # later — same interface
    response = await backend.invoke(request)
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ComputeBackend",
    "ComputeRequest",
    "ComputeResponse",
    "FunctionSpec",
    "RuntimeInfo",
]


@dataclass
class ComputeRequest:
    """A unit of work to execute on the cloud backend."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    function: str = ""             # which function to invoke
    payload: dict[str, Any] = field(default_factory=dict)
    user_id: str = "default"
    timeout: int = 300             # seconds
    memory_mb: int = 1024
    environment: dict[str, str] = field(default_factory=dict)
    async_mode: bool = False       # fire-and-forget
    priority: str = "normal"       # low, normal, high, critical
    created_at: float = field(default_factory=time.time)


@dataclass
class ComputeResponse:
    """Result from a compute invocation."""
    request_id: str = ""
    status: str = "success"        # success, error, timeout, throttled
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    cold_start: bool = False
    backend: str = ""              # "lambda", "terafab", "local"
    cost_estimate: float = 0.0     # $ estimate
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionSpec:
    """Specification for a deployable function."""
    name: str
    handler: str                   # module.function
    runtime: str = "python3.12"
    memory_mb: int = 1024
    timeout: int = 300
    layers: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    description: str = ""
    triggers: list[dict[str, Any]] = field(default_factory=list)  # API Gateway, SQS, schedule


@dataclass
class RuntimeInfo:
    """Information about the current runtime environment."""
    backend: str = ""
    region: str = ""
    instance_id: str = ""
    memory_mb: int = 0
    cpu_count: int = 0
    cold_start: bool = False
    version: str = ""


class ComputeBackend(ABC):
    """Abstract compute backend — implemented by Lambda and Terafab."""

    name: str = ""

    @abstractmethod
    async def invoke(self, request: ComputeRequest) -> ComputeResponse:
        """Invoke a function synchronously."""
        ...

    @abstractmethod
    async def invoke_async(self, request: ComputeRequest) -> str:
        """Invoke a function asynchronously. Returns request ID for polling."""
        ...

    @abstractmethod
    async def get_result(self, request_id: str) -> ComputeResponse | None:
        """Poll for an async invocation result."""
        ...

    @abstractmethod
    async def deploy(self, spec: FunctionSpec) -> dict[str, Any]:
        """Deploy a function to the backend."""
        ...

    @abstractmethod
    async def list_functions(self) -> list[dict[str, Any]]:
        """List deployed functions."""
        ...

    @abstractmethod
    async def health(self) -> RuntimeInfo:
        """Health check / runtime info."""
        ...

    @abstractmethod
    async def scale(self, function: str, min_instances: int = 0, max_instances: int = 100) -> dict[str, Any]:
        """Configure auto-scaling."""
        ...
