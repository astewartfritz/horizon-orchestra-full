# Logistics v1 — Fleet, Routing & Supply Chain

> **Module:** `src/code_agent/logistics/` — 49 tests

Enterprise logistics platform with fleet management, route optimization, supply chain tracking, and an AI brain for anomaly detection and demand forecasting.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Web Dashboard (/logistics/app)  │
│  Fleet │ Resources │ Supply Chain │ AI       │
└───────────────────┬─────────────────────────┘
                    │ REST API
┌───────────────────▼─────────────────────────┐
│           Python Logistics Engine            │
│  ┌──────────┬──────────┬──────────────────┐  │
│  │ FleetEng │ RouteEng │ SupplyChainEng   │  │
│  └─────┬────┴─────┬────┴──────┬──────────┘  │
│        │          │           │              │
│  ┌─────▼──────────▼───────────▼──────────┐  │
│  │           LogisticsBrain               │  │
│  │  Forecast / Anomalies / Health / LLM   │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

---

## Models — `models.py`

| Model | Key Fields | Computed Properties |
|-------|-----------|-------------------|
| `Vehicle` | name, plate, type, status, capacity_kg, lat/lng, fuel_efficiency | `is_available`, `distance_to()` |
| `Driver` | name, license, hours_this_week, max_hours, rating | `is_available`, `hours_remaining` |
| `Route` | vehicle_id, driver_id, stops, distance, duration | `stop_count` |
| `RouteStop` | sequence, lat/lng, type (pickup/delivery/depot) | — |
| `Shipment` | tracking_code, origin, destination, status, cost, revenue | `is_delivered`, `days_in_transit`, `profit` |
| `Warehouse` | capacity, current_items, lat/lng, region | `utilization`, `available_capacity` |
| `InventoryItem` | sku, quantity, reorder_point, unit_cost | `needs_reorder`, `total_value` |
| `FleetMetrics` | totals, utilization, on_time_rate | — |
| `SupplyChainEvent` | type, timestamp, location, description | — |

`haversine(lat1, lng1, lat2, lng2)` → great-circle distance in km

---

## Fleet Engine — `fleet.py`

```python
fleet = FleetEngine()
fleet.register_vehicle("Truck-101", "TRK-1001", capacity_kg=12000)
fleet.register_driver("Alice", "LIC-2001")

fleet.assign_driver(vehicle_id, driver_id)
fleet.release_vehicle(vehicle_id)

# Find nearest available vehicle
v = fleet.find_nearest_available(40.7, -74.0, type="truck", region="us-east")

# Metrics
fleet.get_metrics()  # FleetMetrics with utilization, counts
fleet.get_vehicles_by_region("us-east")
```

---

## Routing Engine — `routing.py`

```python
routing = RoutingEngine()
route = routing.create_route("Morning Route", vehicle_id, driver_id)
routing.add_stop(route.id, RouteStop(location_name="Stop A", lat=40.7, lng=-74.0))

# Nearest-neighbor optimization (requires 3+ stops)
routing.optimize_stops(route.id)

# ETA prediction
eta = routing.estimate_eta(route.id, current_stop_index=0)
# {"remaining_stops": 5, "remaining_km": 340, "remaining_hours": 5.7}

# Carbon tracking: 0.27 kg CO₂ per km
```

---

## Supply Chain Engine — `supply_chain.py`

```python
supply = SupplyChainEngine()
wh = supply.create_warehouse("Main DC", 40.7, -74.0, capacity=50000)

# Inventory
item = supply.add_inventory("Widget", wh.id, quantity=500, unit_cost=25.0,
                             reorder_point=50, category="electronics")
supply.adjust_inventory(item.sku, -30)
supply.get_items_needing_reorder()  # items below reorder point

# Shipments
s = supply.create_shipment("NYC", "LAX", weight_kg=500, revenue=1000, cost=200)
supply.update_shipment_status(s.id, ShipmentStatus.DELIVERED,
                               location="LAX", description="Signed for")
supply.track_shipment("ORCH-ABC123")
supply.get_delivery_success_rate()  # 92.0%
supply.get_on_time_rate()          # 87.5%
```

---

## Logistics Brain — `brain.py`

```python
brain = LogisticsBrain(fleet, routing, supply)

# Route optimization
brain.optimize_daily_routes()  # auto-assigns pending to available fleet

# Demand forecast
brain.forecast_demand([30, 40, 35, 50, 45], horizon=7)
# {"forecast": [...], "trend": "up", "volatility": 0.15}

# Anomaly detection
anomalies = brain.detect_anomalies()
# alerts for: overdue shipments, vehicle maintenance, driver hours, low inventory

# Fleet health score (A-F grade)
brain.fleet_health_score()
# {"score": 85.0, "grade": "B", "reasons": [...], "metrics": {...}}

# LLM copilot
await brain.llm_analyze("What's our fleet health?")
# Offline fallback: returns operational summary with anomaly count
```

### Health Score Rubric

| Factor | Penalty | Threshold |
|--------|---------|-----------|
| Fleet utilization | −15 | < 50% |
| Maintenance ratio | −10 | > 20% of fleet |
| Driver availability | −10 | < 50% active |
| On-time delivery | −15 | < 80% |

Grade: A ≥ 90, B ≥ 75, C ≥ 50, D < 50

---

## API Routes — `routes.py`

15 endpoints under `/api/logistics/`:

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Service health |
| `GET /fleet` | All vehicles + drivers |
| `GET /fleet/metrics` | Fleet KPIs |
| `POST /fleet/vehicles` | Register vehicle |
| `POST /fleet/drivers` | Register driver |
| `GET /fleet/nearest?lat=&lng=` | Nearest available vehicle |
| `GET /routes` | All routes |
| `POST /routes` | Create route |
| `POST /routes/{id}/optimize` | Optimize stops |
| `GET /routes/{id}/eta` | ETA prediction |
| `GET /supply/warehouses` | All warehouses |
| `GET /supply/inventory` | Inventory list |
| `GET /supply/shipments` | Shipment list with KPIs |
| `GET /brain/summary` | AI brain status |
| `POST /brain/optimize` | Auto-assign routes |
| `POST /brain/forecast` | Demand forecast |
| `GET /brain/anomalies` | Anomaly detection |
| `GET /brain/health` | Fleet health score |
| `POST /brain/query` | LLM copilot |

Auto-seeds demo data: 5 trucks, 3 drivers, 2 warehouses, 9 inventory items, 8 shipments.

---

## Frontend — `/logistics/app`

4-tab dashboard:

| Tab | Content |
|-----|---------|
| **Fleet** | 5 KPI cards (size/available/in-transit/maintenance/utilization), vehicles table, drivers table with hour remaining |
| **Resources** | Warehouse utilization bars, inventory table with reorder alerts, total value |
| **Supply Chain** | Shipment KPIs (count/profit/on-time/success), shipments table |
| **AI** | Logistics copilot chat, anomaly list (critical/warning), demand forecast chart (Canvas), fleet health score (A-F), health reasons |

---

## Test Coverage (49 tests)

- Models: Vehicle (auto-ID, status, distance), Driver (hours, remaining, exceeded), Route (auto-ID, stops), Shipment (tracking, profit), Warehouse (utilization, full), InventoryItem (reorder, value), FleetMetrics, Haversine
- FleetEngine: register/get/update-status/assign/release/nearest/metrics
- RoutingEngine: create/add/optimize (short + long)/active/ETA
- DistanceMatrix: add/get/estimate-distance/estimate-duration
- SupplyChainEngine: warehouse/inventory/adjust/reorder/shipment/status/track/success/assign
- LogisticsBrain: optimize/anomalies/health/forecast/summary
