"""Service registry — register, deregister, heartbeat, list services."""

from __future__ import annotations

import time
import logging
from threading import Lock
from typing import Any

from service_discovery.models import ServiceInstance, ServiceStatus


class ServiceRegistry:
    """Thread-safe in-memory service registry with heartbeat expiry."""

    def __init__(self):
        self._services: dict[str, dict[str, ServiceInstance]] = {}  # service_name → instance_id → instance
        self._lock = Lock()
        self.logger = logging.getLogger("orchestra.discovery.registry")

    # ── Registration ─────────────────────────────────────────

    def register(self, instance: ServiceInstance) -> str:
        """Register a service instance. Returns instance_id."""
        with self._lock:
            if instance.service_name not in self._services:
                self._services[instance.service_name] = {}
            self._services[instance.service_name][instance.instance_id] = instance
            self.logger.info("Registered %s at %s (id=%s)", instance.service_name, instance.address, instance.instance_id)
        return instance.instance_id

    def register_simple(self, service_name: str, host: str, port: int,
                        tags: list[str] | None = None, **kwargs) -> str:
        """Convenience: create + register a ServiceInstance in one call."""
        inst = ServiceInstance(
            service_name=service_name,
            host=host,
            port=port,
            tags=tags or [],
            **kwargs,
        )
        return self.register(inst)

    # ── Deregistration ───────────────────────────────────────

    def deregister(self, service_name: str, instance_id: str) -> bool:
        """Remove a service instance. Returns True if removed."""
        with self._lock:
            svc = self._services.get(service_name)
            if svc and instance_id in svc:
                del svc[instance_id]
                if not svc:
                    del self._services[service_name]
                self.logger.info("Deregistered %s id=%s", service_name, instance_id)
                return True
            return False

    def deregister_service(self, service_name: str) -> int:
        """Remove all instances of a service. Returns count removed."""
        with self._lock:
            svc = self._services.pop(service_name, {})
            count = len(svc)
            self.logger.info("Deregistered %s — removed %d instances", service_name, count)
        return count

    # ── Heartbeat ─────────────────────────────────────────────

    def heartbeat(self, service_name: str, instance_id: str) -> bool:
        """Update the last_heartbeat timestamp. Returns True if instance exists."""
        with self._lock:
            inst = self._services.get(service_name, {}).get(instance_id)
            if inst:
                inst.last_heartbeat = time.time()
                inst.status = ServiceStatus.UP
                return True
            return False

    # ── Query ─────────────────────────────────────────────────

    def get_instance(self, service_name: str, instance_id: str) -> ServiceInstance | None:
        with self._lock:
            return self._services.get(service_name, {}).get(instance_id)

    def get_instances(self, service_name: str, healthy_only: bool = True) -> list[ServiceInstance]:
        """Return all instances of a service, optionally filtering healthy ones."""
        with self._lock:
            svc = self._services.get(service_name, {})
            instances = list(svc.values())

        if healthy_only:
            instances = [
                i for i in instances
                if i.status == ServiceStatus.UP and not i.is_expired
            ]
        return instances

    def get_services(self) -> list[str]:
        """Return all registered service names."""
        with self._lock:
            return list(self._services.keys())

    def get_all_instances(self) -> dict[str, list[ServiceInstance]]:
        """Return all services and their instances."""
        with self._lock:
            return {name: list(instances.values()) for name, instances in self._services.items()}

    def get_instance_count(self) -> int:
        """Total number of registered instances."""
        with self._lock:
            return sum(len(v) for v in self._services.values())

    # ── Maintenance ───────────────────────────────────────────

    def evict_expired(self) -> int:
        """Remove all instances past their TTL. Returns count evicted."""
        evicted = 0
        with self._lock:
            expired_services = []
            for svc_name, instances in self._services.items():
                expired_ids = [
                    iid for iid, inst in instances.items()
                    if inst.is_expired
                ]
                for iid in expired_ids:
                    del instances[iid]
                    evicted += 1
                if not instances:
                    expired_services.append(svc_name)
            for svc in expired_services:
                del self._services[svc]
        if evicted:
            self.logger.info("Evicted %d expired instances", evicted)
        return evicted

    def mark_draining(self, service_name: str, instance_id: str) -> bool:
        """Mark an instance as draining (no new requests)."""
        with self._lock:
            inst = self._services.get(service_name, {}).get(instance_id)
            if inst:
                inst.status = ServiceStatus.DRAINING
                return True
            return False
