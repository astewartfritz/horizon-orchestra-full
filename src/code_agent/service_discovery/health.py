"""Health checker — periodic pings to registered services."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from service_discovery.models import ServiceInstance, ServiceHealth, ServiceStatus
from service_discovery.registry import ServiceRegistry


class HealthChecker:
    """Periodically checks registered service health via user-provided check functions.

    Usage:
        checker = HealthChecker(registry)
        checker.register_check("ollama", lambda inst: ping_ollama(inst.host, inst.port))
        await checker.run_cycle()       # single cycle
        await checker.run_forever()     # runs in background every interval
    """

    def __init__(self, registry: ServiceRegistry, interval: float = 15.0):
        self.registry = registry
        self.interval = interval
        self._checks: dict[str, list[Callable[[ServiceInstance], Any]]] = {}
        self._results: dict[str, list[ServiceHealth]] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self.logger = logging.getLogger("orchestra.discovery.health")

    def register_check(self, service_name: str, check_fn: Callable[[ServiceInstance], Any]) -> None:
        """Register a health check function for a service type."""
        self._checks.setdefault(service_name, []).append(check_fn)

    def register_http_check(self, service_name: str, path: str = "/health",
                            expected_status: int = 200, timeout: float = 5.0) -> None:
        """Register a simple HTTP health check."""
        import httpx

        async def http_check(inst: ServiceInstance) -> bool:
            url = f"http://{inst.host}:{inst.port}{path}"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                    resp = await client.get(url)
                    return resp.status_code == expected_status
            except (httpx.RequestError, httpx.HTTPStatusError):
                return False

        self.register_check(service_name, http_check)

    def register_ping_check(self, service_name: str, timeout: float = 3.0) -> None:
        """Register a TCP ping check."""
        import asyncio

        async def ping_check(inst: ServiceInstance) -> bool:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(inst.host, inst.port),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (OSError, asyncio.TimeoutError):
                return False

        self.register_check(service_name, ping_check)

    async def check_instance(self, inst: ServiceInstance) -> ServiceHealth:
        """Run all registered checks for a service instance."""
        start = time.time()
        checks = self._checks.get(inst.service_name, [])

        if not checks:
            # No checks registered — assume UP
            return ServiceHealth(
                instance_id=inst.instance_id,
                service_name=inst.service_name,
                status=ServiceStatus.UP,
                latency_ms=0,
            )

        all_ok = True
        last_error = ""
        for check_fn in checks:
            try:
                if asyncio.iscoroutinefunction(check_fn):
                    result = await check_fn(inst)
                else:
                    result = check_fn(inst)
                if not result:
                    all_ok = False
            except Exception as e:
                all_ok = False
                last_error = str(e)

        latency_ms = (time.time() - start) * 1000
        status = ServiceStatus.UP if all_ok else ServiceStatus.DOWN

        health = ServiceHealth(
            instance_id=inst.instance_id,
            service_name=inst.service_name,
            status=status,
            latency_ms=round(latency_ms, 2),
            error=last_error,
        )

        # Update instance status in registry
        if status == ServiceStatus.DOWN:
            inst.status = ServiceStatus.DOWN

        return health

    async def run_cycle(self) -> dict[str, list[ServiceHealth]]:
        """Run one health check cycle across all registered services."""
        all_instances = self.registry.get_all_instances()
        results: dict[str, list[ServiceHealth]] = {}

        tasks = []
        for svc_name, instances in all_instances.items():
            for inst in instances:
                tasks.append(self.check_instance(inst))

        if not tasks:
            return {}

        health_results = await asyncio.gather(*tasks, return_exceptions=True)

        for hr in health_results:
            if isinstance(hr, ServiceHealth):
                results.setdefault(hr.service_name, []).append(hr)

        self._results = results
        return results

    async def run_forever(self) -> None:
        """Run health checks in a loop until stopped."""
        self._running = True
        while self._running:
            try:
                results = await self.run_cycle()
                down = [
                    h for hh in results.values() for h in hh
                    if h.status == ServiceStatus.DOWN
                ]
                if down:
                    for d in down:
                        self.logger.warning("Health check FAILED: %s (%s)", d.service_name, d.error)
                else:
                    self.logger.debug("Health check cycle complete — all up")
            except Exception:
                self.logger.exception("Health check cycle failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        """Start the health check loop as an asyncio task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())
            self.logger.info("Health checker started (interval=%ss)", self.interval)

    async def stop(self) -> None:
        """Stop the health check loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
