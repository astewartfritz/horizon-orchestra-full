"""Service discovery — DNS/SD integration for microservice routing."""

from __future__ import annotations

from orchestra.code_agent.service_discovery.models import ServiceInstance, ServiceHealth, ServiceStatus
from orchestra.code_agent.service_discovery.registry import ServiceRegistry
from orchestra.code_agent.service_discovery.resolver import DNSResolver
from orchestra.code_agent.service_discovery.health import HealthChecker
from orchestra.code_agent.service_discovery.balancer import LoadBalancer, BalanceStrategy
from orchestra.code_agent.service_discovery.client import ServiceDiscoveryClient

__all__ = [
    "ServiceInstance", "ServiceHealth", "ServiceStatus",
    "ServiceRegistry",
    "DNSResolver",
    "HealthChecker",
    "LoadBalancer", "BalanceStrategy",
    "ServiceDiscoveryClient",
]
