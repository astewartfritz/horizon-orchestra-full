# Logistics v2 — Battle-Ready Multi-Language Engine

> **Module:** `src/code_agent/logistics2/` (42 tests) + `channels/ts/src/logistics/` + `go-services/telemetry/`

Production-grade, multi-language logistics platform with VRP/TSP optimization, demand forecasting, dynamic pricing, AI dispatch, real-time telemetry, and Temporal-style workflow orchestration.

---

## Language Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    TypeScript Planning UI                     │
│  Dispatch Dashboard │ Planning Grid │ Map View               │
│  React-style components, live KPI tiles, drag-drop trucks     │
├──────────────────────────────────────────────────────────────┤
│                     Python API + gRPC                         │
│  FastAPI routes + GRPCService (protobuf-compatible)          │
├──────────────────┬───────────────────┬───────────────────────┤
│   OPTIMIZATION   │    DATA LAYER     │     DISPATCH BRAIN    │
│   (Python)       │    (Python + DB)  │     (Python + TS)     │
│                  │                   │                       │
│  • VRPSolver     │  • HTAPEngine     │  • LoadMatcher        │
│  • TSPSolver     │  • WhatIfSim      │  • RateEngine         │
│  • DemandForecast│  • PlanningEng    │  • AgentOrchestrator  │
│  • DynamicPricing│                   │  • NLPAgent           │
├──────────────────┴───────────────────┴───────────────────────┤
│                                                              │
│   TELEMETRY (Go-style)     │   ORCHESTRATION (Temporal/Cad.) │
│                             │                                │
│  • EventIngester (async)    │  • WorkflowEngine              │
│  • EventStream (pub/sub)    │  • PlanningWorkflows           │
│                             │  • GRPCService                 │
│  go-services/telemetry/     │                                │
│  (Go module)                │                                │
└─────────────────────────────┴────────────────────────────────┘
```

---

## Optimization Engine

### VRP Solver — `optimization/vrp_solver.py`

Vehicle Routing Problem with OR-Tools integration + heuristic fallback.

| Feature | Description |
|---------|-------------|
| **Algorithm** | Nearest-neighbor clustering + 2-opt improvement |
| **OR-Tools** | Auto-detected: uses `pywrapcp` when available |
| **Constraints** | Stops per route (15), max distance (800km), max hours (11), capacity |
| **Depot** | Central starting/ending point per vehicle |

```python
solver = VRPSolver(VRPConstraints(max_stops_per_route=10))
stops = [VRPStop(lat=coord.lat, lng=coord.lng, weight_kg=500) for coord in coordinates]
result = solver.solve(stops, num_vehicles=5)
# result.routes: [[0, 3, 7, 0], [0, 1, 4, 0], ...]
# result.total_distance: 1245.6
# result.vehicle_utilization: [78.3, 65.1, ...]
```

### TSP Solver — `optimization/vrp_solver.py` (TSPSolver)

Traveling Salesman with nearest-neighbor + 2-opt swap improvement.

```python
solver = TSPSolver()
route = solver.solve(stops, depot_idx=0)
# Returns to depot: [0, 3, 1, 2, 0]
```

### Demand Forecasting — `optimization/demand_forecast.py`

| Method | Description | Best For |
|--------|-------------|----------|
| `exponential` | α=0.3 smoothing with Gaussian noise | Short-term trending |
| `linear` | OLS regression line | Steady trends |
| `seasonal` | Holt-Winters-style with season period | Weekly/monthly patterns |
| `ensemble` | Weighted avg (0.4 exp + 0.3 linear + 0.3 seasonal) | General purpose |

```python
forecaster = DemandForecaster()
result = forecaster.forecast([100, 110, 120, 130, 140], horizon=7, method="ensemble")
# {"forecast": [143, 146, ...], "trend": "up", "volatility": 0.12, "total_forecast": 1050}
```

### Dynamic Pricing — `optimization/dynamic_pricing.py`

| Component | Description |
|-----------|-------------|
| **Base rate** | Configurable per-km ($2.50 default) |
| **Fuel cost** | Calculated from distance × fuel efficiency |
| **Weight surcharge** | >5000kg adds 5% per additional 1000kg |
| **Demand multiplier** | Supply/demand ratio scales rate 0.8-1.5× |
| **Urgency** | economy 0.85×, standard 1.0×, express 1.25×, emergency 1.5× |
| **Reefer surcharge** | +$0.35/km for refrigerated |
| **Hazmat surcharge** | +$0.50/km for hazardous materials |

```python
pricing = DynamicPricingEngine()
result = pricing.calculate_rate(500, 8000, demand_supply_ratio=1.2, urgency="express")
# {"total_rate": 1875.50, "breakdown": {...}, "metrics": {"cost_per_km": 3.75}}

result = pricing.spot_market_rate(500, 8000, market_volatility=0.15)
# {"spot_rate": 1950.00, "vs_market": 4.2, ...}

result = pricing.lane_profitability(revenue=1500, cost=1200, distance_km=500)
# {"margin_pct": 20.0, "revenue_per_km": 3.00, ...}
```

---

## Data Layer

### HTAP Engine — `data/htap_engine.py`

DuckDB-powered hybrid OLTP/OLAP for logistics analytics.

```python
htap = HTAPEngine()
htap.insert_lanes([{...}, {...}])
htap.insert_shipments([{...}, {...}])

htap.top_lanes_by_volume(limit=10)
htap.avg_rate_by_lane()
htap.on_time_performance()
htap.capacity_utilization()
htap.lane_summary_stats()  # total_lanes, avg_rate, avg_distance, total_volume
```

### What-If Simulator — `data/what_if.py`

```python
sim = WhatIfSimulator()
base = FleetScenario(num_trucks=50, avg_distance_km=500)
result = sim.simulate_fleet_expansion(base, new_trucks=20)
# "Add 20 trucks across 3 lanes"
# ROI: 14.2 months

result = sim.simulate_rate_change(current_volume=100, current_rate=2500,
                                   new_rate=2800, elasticity=-0.5)
# Revenue change: +4.8%
```

---

## Dispatch Brain

### Load Matcher — `dispatch/load_matcher.py`

Multi-factor load-to-truck matching engine.

| Factor | Weight | Description |
|--------|--------|-------------|
| Distance score | 25% | Proximity of truck to pickup (≤500km) |
| Compatibility | 30% | Equipment type match + capacity fit |
| Profitability | 25% | Revenue per km vs cost per km |
| Deadhead score | 20% | Empty return miles ratio |

```python
matcher = LoadMatcher()
load = Load(id="L1", origin_lat=40.7, origin_lng=-74.0, weight_kg=5000, rate=1500)
vehicles = [{"id": "V1", "current_lat": 40.7, "current_lng": -74.0, "capacity_kg": 10000}]
matches = matcher.match([load], vehicles)
best = matcher.best_match(load, vehicles)
```

### Rate Engine — `dispatch/rate_engine.py`

```python
engine = RateEngine()
engine.register_carrier_rate("Carrier A", 2.30)
engine.register_carrier_rate("Carrier B", 2.80)

result = engine.recommend_rate(500, 8000, demand_supply=1.2)
# {"market_rate": 1450, "recommended_rate": 1522.50,
#   "cheapest_carrier": "Carrier A", "savings_vs_market": 75.00}

result = engine.benchmark_lane("NYC", "Chicago", 800, volume=200)
# {"annual_lane_value": 480000, "rate_per_shipment": 2000}
```

### Agent Orchestrator — `dispatch/agent_orchestrator.py`

Four dispatch agents running as async services:

| Agent | Role | Input | Output |
|-------|------|-------|--------|
| `dispatcher` | Load matching + routing | loads, vehicles | Match scores |
| `compliance` | Regulatory checks | drivers | Violations list |
| `cost_visibility` | Profitability analytics | loads | Rate insights |
| `exception_handler` | Anomaly resolution | anomalies | Resolved status |

```python
orch = AgentOrchestrator()
result = await orch.run_all({"loads": [...], "vehicles": [...], "drivers": [...]})
# {"dispatcher": {...}, "compliance": {...}, "cost_visibility": {...}, "exception_handler": {...}}
await orch.run_agent("compliance", {"drivers": [...]})  # single agent
```

### NLP Agent — `dispatch/nlp_agent.py`

Voice/text command parsing for logistics operations.

| Intent | Example | Entities |
|--------|---------|----------|
| `find_vehicle` | "Find available trucks near Chicago" | locations |
| `rate_query` | "Rate for a 500-mile load?" | distance |
| `anomaly_check` | "Show me overdue shipments" | — |
| `route_optimize` | "Optimize route for truck TRK-1001" | vehicle_id |
| `fleet_health` | "What's our fleet health?" | — |
| `demand_forecast` | "Forecast demand for next week" | — |
| `track_shipment` | "Where is shipment ORCH-ABC123?" | — |

```python
agent = NLPAgent()
parsed = agent.parse_intent("Find available trucks near Chicago")
# {"intent": "find_vehicle", "entities": {"locations": ["Chicago"]}, "confidence": 0.85}
response = await agent.handle("Find trucks near NYC", context={})
# {"response": "Searching for available vehicles near NYC...", "intent": "find_vehicle"}
```

---

## Telemetry — Go-Style Event Pipeline

### Event Ingester — `telemetry/event_ingester.py`

High-throughput concurrent ingestion pipeline.

```python
ingester = EventIngester()

async def on_gps(event):
    print(f"Vehicle {event.vehicle_id} at {event.lat},{event.lng}")

ingester.on("location_update", on_gps)

# Ingest single event
event = TelemetryEvent(source="gps", vehicle_id="V1", lat=40.7, lng=-74.0)
await ingester.ingest(event)

# Simulate GPS feed (for testing)
await ingester.simulate_gps_feed("V1", num_events=100, interval=0.1)

# Start background flush
await ingester.start(interval=1.0)
```

### Event Stream — `telemetry/streaming.py`

Kafka/Pulsar-style pub/sub with partition-aware routing.

```python
stream = EventStream()
stream.subscribe("gps", handler)
stream.subscribe_all(wildcard_handler)
await stream.publish("gps", {"lat": 40.7, "lng": -74.0})

stream.replay("gps", since=timestamp, limit=100)
stream.stats()  # {"total_events": 500, "topics": {"gps": 300}, "subscribers": {...}}
```

---

## Orchestration — Temporal/Cadence-Style Workflows

### Workflow Engine — `orchestration/workflow_engine.py`

```python
engine = WorkflowEngine()

# Define workflow
wf = engine.define("daily_dispatch", [
    WorkflowStep("load_pending", _load_pending, max_retries=3),
    WorkflowStep("match_loads", _match_loads),
    WorkflowStep("optimize_routes", _optimize_routes),
    WorkflowStep("assign_drivers", _assign_drivers),
    WorkflowStep("notify", _notify_dispatchers),
])

# Execute
result = await engine.run(wf.id)
# {"status": "completed", "workflow_id": "...", "duration": 1.23}

# Monitor
engine.get_status(wf.id)
engine.cancel(wf.id)
engine.list_workflows(status="running")
```

### Planning Workflows — `orchestration/planning_workflows.py`

| Workflow | Steps | Schedule |
|----------|-------|----------|
| `week_end_closing` | Validate → Calculate → Audit → Generate Report | Weekly |
| `daily_dispatch` | Load → Match → Optimize → Assign → Notify | Daily |
| `contract_compliance` | Load → Validate → Check Service Levels → Report | Monthly |

### gRPC Service — `orchestration/grpc_service.py`

```python
svc = GRPCService()

# VRP
result = svc.solve_vrp({"stops": [...], "num_vehicles": 5})

# TSP
result = svc.optimize_tsp({"stops": [{"lat": 40.7, "lng": -74.0}, ...]})

# Forecast
result = svc.forecast_demand({"historical": [...], "horizon": 7})

# Load matching
result = svc.match_loads({"loads": [...], "vehicles": [...]})

svc.health()  # {"service": "logistics-grpc", "status": "serving"}
```

---

## TypeScript Scaffold — `channels/ts/src/logistics/`

| File | Purpose |
|------|---------|
| `dispatch-dashboard.tsx` | React-style live KPI dashboard for dispatchers |
| `planning-grid.ts` | Excel-like grid for drag-drop truck-on-lane planning |
| `map-view.ts` | Map-based dispatch view with vehicle positions |

## Go Scaffold — `go-services/telemetry/`

| File | Purpose |
|------|---------|
| `go.mod` | Go module |
| `main.go` | gRPC + HTTP telemetry server |
| `ingester.go` | Concurrent GPS/ELD event ingestion |
| `kafka.go` | Kafka producer for event streaming |

---

## Test Coverage (42 tests)

- VRPSolver: multi-route, single-stop, constraints defaults
- TSPSolver: 5-stop, 2-stop
- DemandForecaster: exponential, linear, ensemble, insufficient data, volatility
- DynamicPricing: calculate, spot market, lane profitability, unprofitable lane, reefer
- HTAPEngine: query, insert lanes (2 skipped w/o duckdb)
- WhatIfSimulator: fleet expansion, rate change
- LoadMatcher: match scores, best match, equipment mismatch
- RateEngine: recommend, benchmark
- AgentOrchestrator: all agents, specific agent, unknown agent
- NLPAgent: find truck, rate query, unknown, handle
- EventIngester: ingest single, ingest batch
- EventStream: publish/subscribe, wildcard, replay, stats
- WorkflowEngine: define/run, failure/retry, get status, list
- GRPCService: health, service list
- TelemetryEvent: auto-ID, timestamp
