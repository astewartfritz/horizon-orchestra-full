"""Service discovery — DNS/SD integration for microservice routing."""

from __future__ import annotations

from service_discovery.models import ServiceInstance, ServiceHealth, ServiceStatus
from service_discovery.registry import ServiceRegistry
from service_discovery.resolver import DNSResolver
from service_discovery.health import HealthChecker
from service_discovery.balancer import LoadBalancer, BalanceStrategy
from service_discovery.client import ServiceDiscoveryClient

__all__ = [
    "ServiceInstance", "ServiceHealth", "ServiceStatus",
    "ServiceRegistry",
    "DNSResolver",
    "HealthChecker",
    "LoadBalancer", "BalanceStrategy",
    "ServiceDiscoveryClient",
]
