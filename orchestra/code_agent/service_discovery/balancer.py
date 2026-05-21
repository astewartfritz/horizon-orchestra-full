"""Load balancer — round-robin, random, least-connections strategies."""

from __future__ import annotations

import random
from enum import Enum
from threading import Lock
from typing import Any

from orchestra.code_agent.service_discovery.models import ServiceInstance


class BalanceStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    PRIORITY = "priority"


class LoadBalancer:
    """Picks a service instance from a list according to strategy."""

    def __init__(self, strategy: BalanceStrategy = BalanceStrategy.ROUND_ROBIN):
        self.strategy = strategy
        self._rr_index: dict[str, int] = {}  # service_name → current index
        self._connections: dict[str, dict[str, int]] = {}  # service_name → instance_id → count
        self._lock = Lock()

    def pick(self, instances: list[ServiceInstance]) -> ServiceInstance | None:
        """Pick an instance from the list according to the strategy."""
        if not instances:
            return None

        strategy_map = {
            BalanceStrategy.ROUND_ROBIN: self._rr,
            BalanceStrategy.RANDOM: self._random,
            BalanceStrategy.LEAST_CONNECTIONS: self._least_connections,
            BalanceStrategy.WEIGHTED: self._weighted,
            BalanceStrategy.PRIORITY: self._priority,
        }

        fn = strategy_map.get(self.strategy, self._rr)
        return fn(instances)

    def release(self, service_name: str, instance_id: str) -> None:
        """Decrement connection count for an instance."""
        with self._lock:
            svc_conns = self._connections.get(service_name, {})
            if instance_id in svc_conns:
                svc_conns[instance_id] = max(0, svc_conns[instance_id] - 1)

    def _rr(self, instances: list[ServiceInstance]) -> ServiceInstance:
        svc_name = instances[0].service_name if instances else ""
        with self._lock:
            idx = self._rr_index.get(svc_name, 0) % len(instances)
            self._rr_index[svc_name] = idx + 1
        return instances[idx]

    def _random(self, instances: list[ServiceInstance]) -> ServiceInstance:
        return random.choice(instances)

    def _weighted(self, instances: list[ServiceInstance]) -> ServiceInstance:
        total_weight = sum(i.weight for i in instances)
        r = random.uniform(0, total_weight)
        upto = 0
        for inst in instances:
            upto += inst.weight
            if r <= upto:
                return inst
        return instances[-1]

    def _priority(self, instances: list[ServiceInstance]) -> ServiceInstance:
        min_priority = min(i.priority for i in instances)
        candidates = [i for i in instances if i.priority == min_priority]
        return self._random(candidates)

    def _least_connections(self, instances: list[ServiceInstance]) -> ServiceInstance:
        svc_name = instances[0].service_name
        with self._lock:
            svc_conns = self._connections.setdefault(svc_name, {})
            for inst in instances:
                svc_conns.setdefault(inst.instance_id, 0)
            best = min(instances, key=lambda i: svc_conns.get(i.instance_id, 0))
            svc_conns[best.instance_id] = svc_conns.get(best.instance_id, 0) + 1
        return best
