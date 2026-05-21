"""DNS resolver — service name → IP:port resolution with SRV-like records."""

from __future__ import annotations

import re
from typing import Any

from orchestra.code_agent.service_discovery.models import ServiceInstance
from orchestra.code_agent.service_discovery.registry import ServiceRegistry
from orchestra.code_agent.service_discovery.balancer import LoadBalancer, BalanceStrategy


class DNSResolver:
    """Resolves service names to addresses via the registry + load balancer.

    Supports dot-notation names:
      - "orchestra-api" → resolves to the 'orchestra-api' service
      - "llm-ollama.default.svc.cluster.local" → strips known suffixes
      - "api:chat" → tag-based filtering (service:tag)
    """

    def __init__(self, registry: ServiceRegistry, balancer: LoadBalancer | None = None):
        self.registry = registry
        self.balancer = balancer or LoadBalancer(strategy=BalanceStrategy.ROUND_ROBIN)
        self._localhost_overrides: dict[str, str] = {}

    def set_local_override(self, service_name: str, host: str) -> None:
        """Override resolution for local development (e.g. 'ollama' → 'localhost')."""
        self._localhost_overrides[service_name] = host

    def resolve(self, name: str, tag_filter: str | None = None) -> tuple[ServiceInstance | None, list[ServiceInstance]]:
        """Resolve a service name to its best instance + all available instances.

        Returns (selected_instance, all_healthy_instances).
        """
        service_name = self._normalize(name)

        if service_name in self._localhost_overrides:
            host = self._localhost_overrides[service_name]
            return self._make_local_override(service_name, host), []

        instances = self.registry.get_instances(service_name, healthy_only=True)
        if tag_filter:
            instances = [i for i in instances if tag_filter in i.tags]

        if not instances:
            return None, []

        selected = self.balancer.pick(instances)
        return selected, instances

    def resolve_all(self, name: str) -> list[ServiceInstance]:
        """Return all healthy instances for a service."""
        service_name = self._normalize(name)
        if service_name in self._localhost_overrides:
            return [self._make_local_override(service_name, self._localhost_overrides[service_name])]
        return self.registry.get_instances(service_name, healthy_only=True)

    def resolve_srv(self, name: str) -> list[dict[str, Any]]:
        """SRV-style records: (priority, weight, host, port)."""
        instances = self.resolve_all(name)
        return [
            {
                "priority": inst.priority,
                "weight": inst.weight,
                "host": inst.host,
                "port": inst.port,
                "instance_id": inst.instance_id,
                "status": inst.status.value,
                "tags": inst.tags,
            }
            for inst in instances
        ]

    def resolve_txt(self, name: str) -> list[dict[str, str]]:
        """TXT-style metadata records."""
        instances = self.resolve_all(name)
        return [
            {
                "instance_id": inst.instance_id,
                **inst.metadata,
            }
            for inst in instances
        ]

    def _normalize(self, name: str) -> str:
        """Strip k8s DNS suffixes, port suffixes, etc."""
        name = name.strip(".")
        for suffix in [".svc.cluster.local", ".svc", ".local", ".service"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        # Remove port suffix like :8000
        name = re.sub(r":\d+$", "", name)
        return name

    def _make_local_override(self, service_name: str, host: str) -> ServiceInstance:
        return ServiceInstance(
            service_name=service_name,
            host=host,
            port=0,
            instance_id="local-override",
        )
