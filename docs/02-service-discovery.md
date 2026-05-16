# Service Discovery — DNS/SD Integration

> **Module:** `src/code_agent/service_discovery/` — 50 tests

Orchestra's service discovery provides DNS-style resolution, load balancing, and health checking for microservice routing — all in-memory with zero infrastructure dependencies.

---

## Architecture

```
ServiceDiscoveryClient
  │
  ├── registry.register("ollama", "localhost", 11434)
  ├── resolver.resolve("ollama") → ServiceInstance
  ├── balancer.pick(instances) → best instance
  └── health.start() → periodic checks
```

## Components

### ServiceRegistry
Thread-safe in-memory registry with TTL-based expiry.

```
registry.register_simple("api", "10.0.0.1", 8000, tags=["v1"])
registry.heartbeat("api", instance_id)
registry.get_instances("api", healthy_only=True)
registry.evict_expired()  # removes stale instances
```

### DNSResolver
Resolves service names with k8s DNS suffix stripping and SRV/TXT records.

```
resolver.resolve("ollama.default.svc.cluster.local")
  → normalizes to "ollama"
  → returns (best_instance, all_instances)

resolver.resolve_srv("api")
  → [{priority, weight, host, port, status, tags}, ...]

resolver.set_local_override("ollama", "localhost")
```

### LoadBalancer
Five strategies for picking service instances.

| Strategy | Behavior |
|----------|----------|
| `ROUND_ROBIN` | Sequential rotation per service |
| `RANDOM` | Random selection |
| `WEIGHTED` | Weighted random (by `weight` field) |
| `PRIORITY` | Lowest priority wins |
| `LEAST_CONNECTIONS` | Instance with fewest active connections |

### HealthChecker
Async health checks with HTTP pings, TCP pings, and custom check functions.

```python
checker.register_http_check("ollama", "/api/tags", expected_status=200)
checker.register_ping_check("redis", timeout=3.0)
checker.start()  # runs in background
```

### ServiceDiscoveryClient
High-level client combining all components.

```python
sd = ServiceDiscoveryClient()
sd.register("ollama", "localhost", 11434, tags=["llm"])
sd.register_self("my-api", 8000)  # auto-detects host
inst = sd.resolve_one("ollama")
result = await sd.call("ollama", "/api/tags")
```

## FastAPI Middleware

```python
app = FastAPI()
sd_mw = ServiceDiscoveryMiddleware(app, "orchestra-api", 8000)
sd_mw.register()
ServiceDiscoveryRouter(sd.sd).mount_on(app)
```

Adds endpoints:
- `GET /sd/health` — service health + registration info
- `GET /sd/info` — service metadata + known services
- `GET /sd/services` — list all services
- `GET /sd/resolve/{name}` — resolve service to instance
- `GET /sd/srv/{name}` — SRV records
- `POST /sd/register` — programmatic registration

## Test Coverage (50 tests)

- ServiceInstance: auto-ID, address, expiry, serialization
- Registry: CRUD, heartbeat, eviction, draining, multi-service
- Resolver: k8s normalization, tag filter, local override, SRV/TXT
- Balancer: round-robin rotation, random, weighted, priority, least-connections, release
- Health checker: no-checks-up, custom pass/fail, HTTP check, run cycle
- Client: register, resolve, heartbeat, deregister, stats, call error
