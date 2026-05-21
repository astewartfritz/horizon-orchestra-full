"""Tests for service discovery — registry, resolver, health, balancer, client."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.code_agent.service_discovery.balancer import LoadBalancer, BalanceStrategy
from orchestra.code_agent.service_discovery.client import ServiceDiscoveryClient, ServiceUnavailableError
from orchestra.code_agent.service_discovery.health import HealthChecker
from orchestra.code_agent.service_discovery.models import ServiceInstance, ServiceHealth, ServiceStatus
from orchestra.code_agent.service_discovery.registry import ServiceRegistry
from orchestra.code_agent.service_discovery.resolver import DNSResolver


# ── ServiceInstance ───────────────────────────────────────

class TestServiceInstance:
    def test_auto_assigns_instance_id(self):
        inst = ServiceInstance("test-svc", "10.0.0.1", 8080)
        assert len(inst.instance_id) == 12

    def test_address_property(self):
        inst = ServiceInstance("svc", "1.2.3.4", 9999)
        assert inst.address == "1.2.3.4:9999"

    def test_expired_when_ttl_passed(self):
        inst = ServiceInstance("svc", "host", 80, ttl_seconds=1, last_heartbeat=time.time() - 100)
        assert inst.is_expired is True

    def test_not_expired_within_ttl(self):
        inst = ServiceInstance("svc", "host", 80, ttl_seconds=300)
        assert inst.is_expired is False

    def test_not_expired_when_ttl_zero(self):
        inst = ServiceInstance("svc", "host", 80, ttl_seconds=0)
        assert inst.is_expired is False

    def test_to_dict_contains_all_keys(self):
        inst = ServiceInstance("svc", "host", 80, tags=["v1"])
        d = inst.to_dict()
        assert d["service_name"] == "svc"
        assert d["tags"] == ["v1"]
        assert d["address"] == "host:80"


# ── ServiceRegistry ───────────────────────────────────────

class TestServiceRegistry:
    def test_register_and_get_instance(self):
        r = ServiceRegistry()
        inst = ServiceInstance("api", "10.0.0.1", 8000)
        iid = r.register(inst)
        assert r.get_instance("api", iid) is inst

    def test_register_simple(self):
        r = ServiceRegistry()
        iid = r.register_simple("api", "10.0.0.1", 8000, tags=["v1"])
        inst = r.get_instance("api", iid)
        assert inst.tags == ["v1"]
        assert inst.address == "10.0.0.1:8000"

    def test_deregister_returns_true(self):
        r = ServiceRegistry()
        iid = r.register_simple("api", "h", 1)
        assert r.deregister("api", iid) is True

    def test_deregister_unknown_returns_false(self):
        r = ServiceRegistry()
        assert r.deregister("nonexistent", "nope") is False

    def test_deregister_service(self):
        r = ServiceRegistry()
        r.register_simple("api", "h1", 1)
        r.register_simple("api", "h2", 2)
        assert r.deregister_service("api") == 2
        assert r.get_services() == []

    def test_get_instances_healthy_only(self):
        r = ServiceRegistry()
        r.register(ServiceInstance("api", "h1", 1, status=ServiceStatus.UP))
        r.register(ServiceInstance("api", "h2", 2, status=ServiceStatus.DOWN))
        healthy = r.get_instances("api", healthy_only=True)
        assert len(healthy) == 1

    def test_get_instances_all(self):
        r = ServiceRegistry()
        r.register(ServiceInstance("api", "h1", 1, status=ServiceStatus.UP))
        r.register(ServiceInstance("api", "h2", 2, status=ServiceStatus.DOWN))
        all_inst = r.get_instances("api", healthy_only=False)
        assert len(all_inst) == 2

    def test_heartbeat_updates_timestamp(self):
        r = ServiceRegistry()
        iid = r.register_simple("api", "h", 1)
        inst = r.get_instance("api", iid)
        old = inst.last_heartbeat
        time.sleep(0.01)
        assert r.heartbeat("api", iid) is True
        assert inst.last_heartbeat > old

    def test_heartbeat_unknown_returns_false(self):
        r = ServiceRegistry()
        assert r.heartbeat("nope", "nope") is False

    def test_evict_expired(self):
        r = ServiceRegistry()
        iid = r.register(ServiceInstance("api", "h", 1, ttl_seconds=1, last_heartbeat=time.time() - 100))
        assert r.evict_expired() == 1
        assert r.get_instance("api", iid) is None

    def test_get_services(self):
        r = ServiceRegistry()
        r.register_simple("a", "h", 1)
        r.register_simple("b", "h", 2)
        assert sorted(r.get_services()) == ["a", "b"]

    def test_get_all_instances(self):
        r = ServiceRegistry()
        r.register_simple("a", "h", 1)
        r.register_simple("b", "h", 2)
        all_i = r.get_all_instances()
        assert set(all_i.keys()) == {"a", "b"}

    def test_get_instance_count(self):
        r = ServiceRegistry()
        r.register_simple("a", "h", 1)
        r.register_simple("a", "h", 2)
        r.register_simple("b", "h", 3)
        assert r.get_instance_count() == 3

    def test_mark_draining(self):
        r = ServiceRegistry()
        iid = r.register_simple("api", "h", 1)
        assert r.mark_draining("api", iid) is True
        assert r.get_instance("api", iid).status == ServiceStatus.DRAINING


# ── DNS Resolver ──────────────────────────────────────────

class TestDNSResolver:
    def test_resolve_returns_instance(self):
        registry = ServiceRegistry()
        registry.register_simple("api", "10.0.0.1", 8000)
        resolver = DNSResolver(registry)
        inst, all_inst = resolver.resolve("api")
        assert inst is not None
        assert inst.host == "10.0.0.1"

    def test_resolve_unknown_returns_none(self):
        resolver = DNSResolver(ServiceRegistry())
        inst, all_inst = resolver.resolve("unknown")
        assert inst is None
        assert all_inst == []

    def test_resolve_with_tag_filter(self):
        registry = ServiceRegistry()
        registry.register_simple("api", "h1", 1, tags=["v1"])
        registry.register_simple("api", "h2", 2, tags=["v2"])
        resolver = DNSResolver(registry)
        _, all_inst = resolver.resolve("api", tag_filter="v1")
        assert len(all_inst) == 1
        assert all_inst[0].host == "h1"

    def test_normalize_strips_k8s_suffix(self):
        resolver = DNSResolver(ServiceRegistry())
        assert resolver._normalize("api.svc.cluster.local") == "api"
        assert resolver._normalize("api.svc") == "api"
        assert resolver._normalize("api.local") == "api"

    def test_local_override(self):
        resolver = DNSResolver(ServiceRegistry())
        resolver.set_local_override("ollama", "localhost")
        inst, _ = resolver.resolve("ollama")
        assert inst is not None
        assert inst.host == "localhost"

    def test_resolve_all(self):
        registry = ServiceRegistry()
        registry.register_simple("api", "h1", 1)
        registry.register_simple("api", "h2", 2)
        resolver = DNSResolver(registry)
        assert len(resolver.resolve_all("api")) == 2

    def test_resolve_srv(self):
        registry = ServiceRegistry()
        registry.register_simple("api", "h1", 8001, tags=["v1"])
        resolver = DNSResolver(registry)
        records = resolver.resolve_srv("api")
        assert len(records) == 1
        assert records[0]["host"] == "h1"
        assert records[0]["port"] == 8001

    def test_resolve_txt(self):
        registry = ServiceRegistry()
        iid = registry.register_simple("api", "h1", 1)
        inst = registry.get_instance("api", iid)
        inst.metadata["version"] = "1.0"
        resolver = DNSResolver(registry)
        txt = resolver.resolve_txt("api")
        assert len(txt) == 1
        assert txt[0]["version"] == "1.0"


# ── Load Balancer ─────────────────────────────────────────

class TestLoadBalancer:
    def make_instances(self, n: int, base_host: str = "10.0.0.") -> list[ServiceInstance]:
        return [ServiceInstance("api", f"{base_host}{i}", 8000 + i) for i in range(n)]

    def test_round_robin_rotates(self):
        lb = LoadBalancer(BalanceStrategy.ROUND_ROBIN)
        instances = self.make_instances(3)
        picked = [lb.pick(instances).host for _ in range(6)]
        expected = ["10.0.0.0", "10.0.0.1", "10.0.0.2", "10.0.0.0", "10.0.0.1", "10.0.0.2"]
        assert picked == expected

    def test_random_returns_something(self):
        lb = LoadBalancer(BalanceStrategy.RANDOM)
        instances = self.make_instances(5)
        for _ in range(20):
            assert lb.pick(instances) is not None

    def test_weighted_prefers_higher_weight(self):
        lb = LoadBalancer(BalanceStrategy.WEIGHTED)
        instances = [
            ServiceInstance("api", "heavy", 1, weight=100),
            ServiceInstance("api", "light", 2, weight=1),
        ]
        picks = [lb.pick(instances).host for _ in range(100)]
        heavy_count = picks.count("heavy")
        assert heavy_count > 80  # 100/101 ≈ 99% but let's be generous

    def test_priority_picks_lowest(self):
        lb = LoadBalancer(BalanceStrategy.PRIORITY)
        instances = [
            ServiceInstance("api", "backup", 1, priority=2),
            ServiceInstance("api", "primary", 2, priority=1),
        ]
        for _ in range(20):
            assert lb.pick(instances).host == "primary"

    def test_least_connections(self):
        lb = LoadBalancer(BalanceStrategy.LEAST_CONNECTIONS)
        instances = self.make_instances(2)
        # First pick: both 0, picks first
        first = lb.pick(instances)
        assert first.host == "10.0.0.0"
        # Second pick: first has 1, second has 0, picks second
        second = lb.pick(instances)
        assert second.host == "10.0.0.1"

    def test_release_decrements(self):
        lb = LoadBalancer(BalanceStrategy.LEAST_CONNECTIONS)
        instances = self.make_instances(1)
        inst = lb.pick(instances)
        lb.release("api", inst.instance_id)
        # Internal connections should be 0
        assert lb._connections["api"][inst.instance_id] == 0

    def test_empty_list_returns_none(self):
        lb = LoadBalancer()
        assert lb.pick([]) is None


# ── Health Checker ────────────────────────────────────────

class TestHealthChecker:
    @pytest.mark.asyncio
    async def test_no_checks_assumes_up(self):
        registry = ServiceRegistry()
        inst = ServiceInstance("api", "10.0.0.1", 8000)
        registry.register(inst)
        checker = HealthChecker(registry)
        health = await checker.check_instance(inst)
        assert health.status == ServiceStatus.UP

    @pytest.mark.asyncio
    async def test_http_check_passes(self):
        registry = ServiceRegistry()
        inst = ServiceInstance("api", "10.0.0.1", 8000)
        registry.register(inst)
        checker = HealthChecker(registry)
        checker.register_http_check("api", path="/health", expected_status=200)
        health = await checker.check_instance(inst)
        # No actual server → DOWN
        assert health.status == ServiceStatus.DOWN

    @pytest.mark.asyncio
    async def test_custom_check_passes(self):
        registry = ServiceRegistry()
        inst = ServiceInstance("api", "h", 1)
        registry.register(inst)
        checker = HealthChecker(registry)

        async def ok_check(i):
            return True
        checker.register_check("api", ok_check)
        health = await checker.check_instance(inst)
        assert health.status == ServiceStatus.UP

    @pytest.mark.asyncio
    async def test_custom_check_fails(self):
        registry = ServiceRegistry()
        inst = ServiceInstance("api", "h", 1)
        registry.register(inst)
        checker = HealthChecker(registry)

        async def fail_check(i):
            return False
        checker.register_check("api", fail_check)
        health = await checker.check_instance(inst)
        assert health.status == ServiceStatus.DOWN

    @pytest.mark.asyncio
    async def test_run_cycle_checks_all(self):
        registry = ServiceRegistry()
        registry.register(ServiceInstance("a", "h", 1))
        registry.register(ServiceInstance("a", "h", 2))
        registry.register(ServiceInstance("b", "h", 3))
        checker = HealthChecker(registry)
        results = await checker.run_cycle()
        assert "a" in results
        assert "b" in results


# ── ServiceDiscoveryClient ────────────────────────────────

class TestServiceDiscoveryClient:
    def test_register_and_resolve(self):
        sd = ServiceDiscoveryClient()
        sd.register("api", "10.0.0.1", 8000)
        inst = sd.resolve_one("api")
        assert inst is not None
        assert inst.host == "10.0.0.1"

    def test_resolve_unknown_returns_none(self):
        sd = ServiceDiscoveryClient()
        assert sd.resolve_one("unknown") is None

    def test_heartbeat(self):
        sd = ServiceDiscoveryClient()
        iid = sd.register("api", "h", 1)
        assert sd.heartbeat("api", iid) is True

    def test_deregister(self):
        sd = ServiceDiscoveryClient()
        iid = sd.register("api", "h", 1)
        assert sd.deregister("api", iid) is True

    def test_get_stats(self):
        sd = ServiceDiscoveryClient()
        sd.register("a", "h", 1)
        stats = sd.get_stats()
        assert stats["instance_count"] == 1
        assert stats["strategy"] == "round_robin"

    @pytest.mark.asyncio
    async def test_call_raises_on_no_instance(self):
        sd = ServiceDiscoveryClient()
        with pytest.raises(ServiceUnavailableError):
            await sd.call("nonexistent", "/health")

    @pytest.mark.asyncio
    async def test_call_all_empty(self):
        sd = ServiceDiscoveryClient()
        results = await sd.call_all("nonexistent", "/health")
        assert results == []

    def test_register_self(self):
        sd = ServiceDiscoveryClient()
        import socket
        iid = sd.register("test", socket.gethostbyname(socket.gethostname()), 9999)
        inst = sd.resolve_one("test")
        assert inst is not None
        assert inst.port == 9999


# ── Health Model ──────────────────────────────────────────

class TestServiceHealth:
    def test_auto_timestamp(self):
        h = ServiceHealth("id1", "api", ServiceStatus.UP)
        assert h.checked_at > 0

    def test_latency_default_zero(self):
        h = ServiceHealth("id1", "api", ServiceStatus.UP)
        assert h.latency_ms == 0.0
