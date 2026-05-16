"""High-level service discovery client with auto-registration."""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from service_discovery.registry import ServiceRegistry
from service_discovery.resolver import DNSResolver
from service_discovery.health import HealthChecker
from service_discovery.balancer import LoadBalancer, BalanceStrategy


class ServiceDiscoveryClient:
    """High-level client combining registry, resolver, health checker, and load balancer.

    Usage:
        sd = ServiceDiscoveryClient()
        sd.register("my-api", "10.0.1.5", 8080, tags=["v1"])
        sd.register("ollama", "localhost", 11434, tags=["llm"])

        instance = sd.resolve("ollama")
        if instance:
            result = await sd.call("ollama", "/api/tags")

        sd.register_health("ollama", "/api/tags")
        sd.start_health_checks()
    """

    def __init__(self, strategy: BalanceStrategy = BalanceStrategy.ROUND_ROBIN):
        self.registry = ServiceRegistry()
        self.balancer = LoadBalancer(strategy=strategy)
        self.resolver = DNSResolver(self.registry, self.balancer)
        self.health = HealthChecker(self.registry)
        self.logger = logging.getLogger("orchestra.discovery.client")

    # ── Registration ─────────────────────────────────────────

    def register(self, service_name: str, host: str, port: int,
                 tags: list[str] | None = None, **kwargs) -> str:
        """Register a service instance."""
        return self.registry.register_simple(service_name, host, port, tags, **kwargs)

    def register_self(self, service_name: str, port: int,
                      tags: list[str] | None = None, **kwargs) -> str:
        """Register the current machine as a service instance."""
        host = socket.gethostbyname(socket.gethostname())
        return self.register(service_name, host, port, tags, **kwargs)

    def deregister(self, service_name: str, instance_id: str) -> bool:
        return self.registry.deregister(service_name, instance_id)

    # ── Heartbeat ────────────────────────────────────────────

    def heartbeat(self, service_name: str, instance_id: str) -> bool:
        return self.registry.heartbeat(service_name, instance_id)

    # ── Resolution ───────────────────────────────────────────

    def resolve(self, name: str, tag_filter: str | None = None
                ) -> tuple[Any, list[Any]]:
        """Resolve a service name → (best_instance, all_instances)."""
        return self.resolver.resolve(name, tag_filter)

    def resolve_one(self, name: str, tag_filter: str | None = None) -> Any:
        """Resolve to a single instance (or None)."""
        inst, _ = self.resolver.resolve(name, tag_filter)
        return inst

    def resolve_srv(self, name: str) -> list[dict[str, Any]]:
        return self.resolver.resolve_srv(name)

    # ── Health checks ────────────────────────────────────────

    def register_http_health(self, service_name: str, path: str = "/health",
                             expected_status: int = 200) -> None:
        self.health.register_http_check(service_name, path, expected_status)

    def register_ping_health(self, service_name: str) -> None:
        self.health.register_ping_check(service_name)

    def start_health_checks(self, interval: float = 15.0) -> None:
        self.health.interval = interval
        self.health.start()

    async def stop(self) -> None:
        await self.health.stop()

    # ── Remote call ──────────────────────────────────────────

    async def call(self, service_name: str, path: str, method: str = "GET",
                   body: dict[str, Any] | None = None,
                   tag_filter: str | None = None) -> Any:
        """Make an HTTP request to a resolved service instance."""
        import httpx

        inst, _ = self.resolve(service_name, tag_filter)
        if not inst:
            raise ServiceUnavailableError(f"No healthy instance of {service_name}")

        url = f"http://{inst.host}:{inst.port}{path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            if method == "GET":
                resp = await client.get(url)
            elif method == "POST":
                resp = await client.post(url, json=body or {})
            elif method == "PUT":
                resp = await client.put(url, json=body or {})
            elif method == "DELETE":
                resp = await client.delete(url)
            else:
                raise ValueError(f"Unsupported method: {method}")

            try:
                return resp.json()
            except Exception:
                return resp.text

    async def call_all(self, service_name: str, path: str, method: str = "GET",
                       body: dict[str, Any] | None = None) -> list[Any]:
        """Call all healthy instances of a service and collect responses."""
        import httpx

        instances = self.registry.get_instances(service_name, healthy_only=True)
        results = []
        for inst in instances:
            url = f"http://{inst.host}:{inst.port}{path}"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                    if method == "GET":
                        resp = await client.get(url)
                    else:
                        resp = await client.post(url, json=body or {})
                    results.append(resp.json())
            except Exception as e:
                results.append({"error": str(e), "instance": inst.instance_id})
        return results

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        all_inst = self.registry.get_all_instances()
        return {
            "services": self.registry.get_services(),
            "instance_count": self.registry.get_instance_count(),
            "health_check_running": self.health._running,
            "strategy": self.balancer.strategy.value,
        }


class ServiceUnavailableError(Exception):
    """Raised when no healthy service instance is available."""
    pass
