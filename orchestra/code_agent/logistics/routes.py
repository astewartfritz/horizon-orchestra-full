"""API routes for the Orchestra Logistics platform."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

import random

from orchestra.code_agent.logistics.brain import LogisticsBrain
from orchestra.code_agent.logistics.fleet import FleetEngine
from orchestra.code_agent.logistics.models import VehicleStatus
from orchestra.code_agent.logistics.routing import DistanceMatrix, RoutingEngine
from orchestra.code_agent.logistics.supply_chain import SupplyChainEngine


def register_logistics_routes(app: Any, prefix: str = "/api/logistics") -> None:
    fleet = FleetEngine()
    routing = RoutingEngine()
    supply = SupplyChainEngine()
    brain = LogisticsBrain(fleet, routing, supply)
    router = APIRouter(prefix=prefix)

    # Seed some demo data
    _seed_demo_data(fleet, supply)

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestra-logistics"}

    # ── Fleet ──────────────────────────────
    @router.get("/fleet")
    async def get_fleet():
        return {
            "vehicles": {vid: {"name": v.name, "plate": v.plate, "type": v.type,
                               "status": v.status.value, "region": v.region}
                         for vid, v in fleet.vehicles.items()},
            "drivers": {did: {"name": d.name, "status": d.status, "region": d.region,
                              "hours": d.hours_this_week, "remaining": d.hours_remaining}
                        for did, d in fleet.drivers.items()},
        }

    @router.get("/fleet/metrics")
    async def fleet_metrics():
        m = fleet.get_metrics()
        return {
            "total_vehicles": m.total_vehicles, "available": m.available,
            "in_transit": m.in_transit, "maintenance": m.maintenance,
            "total_drivers": m.total_drivers, "active_drivers": m.active_drivers,
            "utilization": round(m.fleet_utilization, 1),
        }

    @router.post("/fleet/vehicles")
    async def register_vehicle(body: dict[str, Any]):
        v = fleet.register_vehicle(
            name=body["name"], plate=body.get("plate", ""),
            type=body.get("type", "truck"),
            capacity_kg=body.get("capacity_kg", 10000),
            region=body.get("region", "us-east"),
        )
        return {"id": v.id, "name": v.name, "plate": v.plate, "status": v.status.value}

    @router.post("/fleet/drivers")
    async def register_driver(body: dict[str, Any]):
        d = fleet.register_driver(
            name=body["name"], license=body.get("license", ""),
            phone=body.get("phone", ""), region=body.get("region", "us-east"),
        )
        return {"id": d.id, "name": d.name, "status": d.status}

    @router.get("/fleet/nearest")
    async def nearest_vehicle(lat: float = 40.7, lng: float = -74.0, type: str = ""):
        v = fleet.find_nearest_available(lat, lng, type=type)
        if not v:
            raise HTTPException(404, "No available vehicles nearby")
        return {"id": v.id, "name": v.name, "distance_km": round(v.distance_to(lat, lng), 1)}

    # ── Routes ─────────────────────────────
    @router.get("/routes")
    async def get_routes():
        return {
            rid: {"name": r.name, "stops": len(r.stops), "distance_km": r.total_distance_km,
                  "duration_h": r.estimated_duration_hours, "status": r.status,
                  "carbon_kg": r.carbon_footprint_kg}
            for rid, r in routing.routes.items()
        }

    @router.post("/routes")
    async def create_route(body: dict[str, Any]):
        route = routing.create_route(
            name=body["name"],
            vehicle_id=body.get("vehicle_id", ""),
            driver_id=body.get("driver_id", ""),
        )
        return {"id": route.id, "name": route.name, "distance_km": route.total_distance_km}

    @router.post("/routes/{route_id}/optimize")
    async def optimize_route(route_id: str):
        ok = routing.optimize_stops(route_id)
        if not ok:
            raise HTTPException(400, "Route optimization failed")
        route = routing.get_route(route_id)
        return {"id": route_id, "distance_km": route.total_distance_km,
                "duration_h": route.estimated_duration_hours}

    @router.get("/routes/{route_id}/eta")
    async def route_eta(route_id: str):
        eta = routing.estimate_eta(route_id)
        if not eta:
            raise HTTPException(404, "Route not found")
        return eta

    # ── Supply Chain ───────────────────────
    @router.get("/supply/warehouses")
    async def get_warehouses():
        return {w.id: {"name": w.name, "utilization": round(w.utilization, 1),
                       "capacity": w.capacity_items, "current": w.current_items}
                for w in supply.warehouses.values()}

    @router.get("/supply/inventory")
    async def get_inventory(warehouse_id: str = ""):
        items = supply.get_inventory_by_warehouse(warehouse_id) if warehouse_id else list(supply.inventory.values())
        return {
            "items": [{"sku": i.sku, "name": i.name, "quantity": i.quantity,
                       "reorder": i.needs_reorder, "value": round(i.total_value, 2)}
                      for i in items],
            "total_value": round(supply.get_inventory_value(), 2),
            "needs_reorder": len(supply.get_items_needing_reorder()),
        }

    @router.get("/supply/shipments")
    async def get_shipments(status: str = ""):
        if status:
            from orchestra.code_agent.logistics.models import ShipmentStatus
            try:
                s = ShipmentStatus(status)
                results = supply.get_shipments_by_status(s)
            except ValueError:
                results = list(supply.shipments.values())
        else:
            results = list(supply.shipments.values())
        return {
            "count": len(results),
            "total_profit": round(sum(s.profit for s in results), 2),
            "on_time_rate": supply.get_on_time_rate(),
            "delivery_success_rate": supply.get_delivery_success_rate(),
            "shipments": [{"id": s.id, "tracking": s.tracking_code, "status": s.status.value,
                           "origin": s.origin, "destination": s.destination, "profit": round(s.profit, 2)}
                          for s in results],
        }

    # ── AI Brain ───────────────────────────
    @router.get("/brain/summary")
    async def brain_summary():
        return brain.get_summary()

    @router.post("/brain/optimize")
    async def ai_optimize():
        return brain.optimize_daily_routes()

    @router.post("/brain/forecast")
    async def ai_forecast(body: dict[str, Any]):
        return brain.forecast_demand(
            historical_data=body.get("historical"),
            horizon=body.get("horizon", 7),
        )

    @router.get("/brain/anomalies")
    async def ai_anomalies():
        return {"anomalies": brain.detect_anomalies(), "count": 0}

    @router.get("/brain/health")
    async def fleet_health():
        return brain.fleet_health_score()

    @router.post("/brain/query")
    async def ai_query(body: dict[str, Any]):
        metrics = fleet.get_metrics()
        ctx = {
            "fleet": f"{metrics.total_vehicles} vehicles, {metrics.available} available",
            "routes": f"{len(routing.routes)} total, {len(routing.get_active_routes())} active",
            "shipments": f"{len(supply.shipments)} total",
        }
        result = await brain.llm_analyze(body.get("prompt", ""), ctx)
        return {"response": result}

    app.include_router(router)


def _seed_demo_data(fleet: FleetEngine, supply: SupplyChainEngine) -> None:
    if fleet.vehicles:
        return
    for i in range(5):
        fleet.register_vehicle(f"Truck-{100+i}", f"TRK-{1000+i}", "truck",
                                capacity_kg=10000 + i * 2000, region="us-east")
    for i in range(3):
        fleet.register_driver(f"Driver {chr(65+i)}", f"LIC-{2000+i}", region="us-east")
    wh = supply.create_warehouse("Main DC", 40.7, -74.0, capacity=50000, region="us-east")
    wh2 = supply.create_warehouse("West Coast Hub", 34.05, -118.25, capacity=30000, region="us-west")
    for cat, items in [("electronics", ["Widgets", "Gadgets", "Chips"]),
                       ("clothing", ["Shirts", "Pants", "Shoes"]),
                       ("food", ["Produce", "Dairy", "Meat"])]:
        for item in items:
            supply.add_inventory(item, wh.id, quantity=random.randint(50, 500),
                                  unit_cost=round(random.uniform(5, 50), 2),
                                  reorder_point=50, category=cat)
    for i in range(8):
        supply.create_shipment(
            origin="Main DC", destination=f"Customer-{chr(65+i)}",
            weight_kg=random.randint(100, 2000),
            customer=f"Acme Corp {chr(65+i)}",
            cost=random.randint(100, 500), revenue=random.randint(300, 1500),
        )
