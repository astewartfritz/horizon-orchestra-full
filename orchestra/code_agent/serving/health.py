from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.serving.base import BaseProvider, ProviderConfig
from orchestra.code_agent.serving.factory import ProviderFactory


@dataclass
class ProbeResult:
    provider: str
    model: str
    healthy: bool
    latency_ms: float = 0.0
    error: str = ""
    checked_at: float = field(default_factory=time.time)


@dataclass
class HealthProbe:
    provider: str
    model: str
    interval_seconds: int = 60
    timeout: float = 10.0
    consecutive_failures: int = 0
    max_failures_before_down: int = 3


class ModelHealthChecker:
    def __init__(self):
        self._probes: dict[str, HealthProbe] = {}
        self._results: dict[str, ProbeResult] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def register(self, provider: str, model: str, interval: int = 60, timeout: float = 10.0) -> HealthProbe:
        key = f"{provider}/{model}"
        probe = HealthProbe(provider=provider, model=model, interval_seconds=interval, timeout=timeout)
        self._probes[key] = probe
        return probe

    def unregister(self, provider: str, model: str) -> bool:
        key = f"{provider}/{model}"
        if key in self._probes:
            del self._probes[key]
            self._results.pop(key, None)
            return True
        return False

    async def probe(self, provider: str, model: str, timeout: float = 10.0) -> ProbeResult:
        key = f"{provider}/{model}"
        start = time.time()
        try:
            cfg = ProviderConfig(timeout=timeout)
            instance = ProviderFactory.create(provider, model, cfg)
            healthy = await instance.check_health()
            latency = (time.time() - start) * 1000
            result = ProbeResult(
                provider=provider,
                model=model,
                healthy=healthy,
                latency_ms=round(latency, 2),
                error="" if healthy else "Health check returned unhealthy",
            )
        except Exception as e:
            result = ProbeResult(
                provider=provider,
                model=model,
                healthy=False,
                latency_ms=round((time.time() - start) * 1000, 2),
                error=str(e),
            )
        self._results[key] = result
        return result

    async def probe_all(self) -> dict[str, ProbeResult]:
        results = {}
        for key, probe in self._probes.items():
            results[key] = await self.probe(probe.provider, probe.model, probe.timeout)
        return results

    async def _loop(self) -> None:
        while self._running:
            for key, probe in list(self._probes.items()):
                result = await self.probe(probe.provider, probe.model, probe.timeout)
                if result.healthy:
                    probe.consecutive_failures = 0
                else:
                    probe.consecutive_failures += 1
            await asyncio.sleep(
                min((p.interval_seconds for p in self._probes.values()), default=60)
            )

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def get_result(self, provider: str, model: str) -> ProbeResult | None:
        return self._results.get(f"{provider}/{model}")

    def get_all_results(self) -> dict[str, ProbeResult]:
        return dict(self._results)

    def is_healthy(self, provider: str, model: str) -> bool:
        result = self.get_result(provider, model)
        return result is not None and result.healthy

    def is_provider_healthy(self, provider: str) -> bool:
        """Check if any registered probe for the given provider is healthy.

        Returns True if no probes are registered or no results yet (assume healthy).
        """
        has_probes = any(p.provider == provider for p in self._probes.values())
        if not has_probes:
            return True
        has_results = any(r.provider == provider for r in self._results.values())
        if not has_results:
            return True
        return any(r.provider == provider and r.healthy for r in self._results.values())

    def summary(self) -> dict[str, Any]:
        results = self.get_all_results()
        return {
            "total_models": len(results),
            "healthy": sum(1 for r in results.values() if r.healthy),
            "unhealthy": sum(1 for r in results.values() if not r.healthy),
            "probes": {
                k: {"healthy": r.healthy, "latency_ms": r.latency_ms, "error": r.error}
                for k, r in results.items()
            },
        }
