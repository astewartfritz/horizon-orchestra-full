"""Tests for the Orchestra Logistics platform."""

from __future__ import annotations

import pytest

from code_agent.logistics.brain import LogisticsBrain
from code_agent.logistics.fleet import FleetEngine
from code_agent.logistics.models import (
    Driver, FleetMetrics, InventoryItem, Route, RouteStop, Shipment,
    ShipmentStatus, Vehicle, VehicleStatus, Warehouse, haversine,
)
from code_agent.logistics.routing import DistanceMatrix, RoutingEngine
from code_agent.logistics.supply_chain import SupplyChainEngine


# ── Models ─────────────────────────────────

class TestVehicle:
    def test_auto_id(self):
        v = Vehicle(name="Truck 1", plate="ABC-123")
        assert len(v.id) == 12
        assert v.is_available is True

    def test_status_enum(self):
        assert VehicleStatus.AVAILABLE.value == "available"
        assert VehicleStatus.IN_TRANSIT.value == "in_transit"

    def test_distance_to(self):
        v = Vehicle(name="T1", plate="P", current_lat=40.7, current_lng=-74.0)
        dist = v.distance_to(40.8, -74.1)
        assert 10 < dist < 20


class TestDriver:
    def test_auto_id(self):
        d = Driver(name="Alice", license="L123")
        assert len(d.id) == 12
        assert d.is_available is True

    def test_hours_remaining(self):
        d = Driver(name="Bob", license="L456", hours_this_week=40)
        assert d.hours_remaining == 20.0

    def test_hours_exceeded(self):
        d = Driver(name="Bob", license="L456", hours_this_week=70)
        assert d.hours_remaining == 0


class TestRoute:
    def test_auto_id(self):
        r = Route(name="Morning Route", vehicle_id="v1")
        assert len(r.id) == 12

    def test_stop_count(self):
        r = Route(name="R1", vehicle_id="v1", stops=[RouteStop(), RouteStop()])
        assert r.stop_count == 2


class TestShipment:
    def test_auto_fields(self):
        s = Shipment(origin="NYC", destination="LAX")
        assert len(s.id) == 12
        assert s.tracking_code.startswith("ORCH-")
        assert s.is_delivered is False

    def test_profit(self):
        s = Shipment(origin="A", destination="B", cost=100, revenue=300)
        assert s.profit == 200


class TestWarehouse:
    def test_utilization(self):
        w = Warehouse(name="DC1", capacity_items=1000, current_items=300)
        assert w.utilization == 30.0
        assert w.available_capacity == 700

    def test_full_warehouse(self):
        w = Warehouse(name="DC1", capacity_items=1000, current_items=1000)
        assert w.utilization == 100.0
        assert w.available_capacity == 0


class TestInventoryItem:
    def test_needs_reorder(self):
        i = InventoryItem(sku="SKU-1", name="Widget", quantity=5, reorder_point=10)
        assert i.needs_reorder is True
        i2 = InventoryItem(sku="SKU-2", name="Gadget", quantity=20, reorder_point=10)
        assert i2.needs_reorder is False

    def test_total_value(self):
        i = InventoryItem(sku="S1", name="Item", quantity=10, unit_cost=25.0)
        assert i.total_value == 250.0


class TestFleetMetrics:
    def test_defaults(self):
        m = FleetMetrics()
        assert m.total_vehicles == 0
        assert m.fleet_utilization == 0.0


class TestHaversine:
    def test_known_distance(self):
        d = haversine(40.7, -74.0, 34.05, -118.25)
        assert 3900 < d < 4000  # NYC to LA ~3944 km

    def test_zero_distance(self):
        d = haversine(40.7, -74.0, 40.7, -74.0)
        assert d == 0.0


# ── FleetEngine ───────────────────────────

class TestFleetEngine:
    def test_register_vehicle(self):
        eng = FleetEngine()
        v = eng.register_vehicle("Truck 1", "ABC-123", capacity_kg=15000)
        assert v.id in eng.vehicles
        assert v.capacity_kg == 15000

    def test_get_vehicle(self):
        eng = FleetEngine()
        v = eng.register_vehicle("T1", "P1")
        assert eng.get_vehicle(v.id) is v
        assert eng.get_vehicle("nonexistent") is None

    def test_update_status(self):
        eng = FleetEngine()
        v = eng.register_vehicle("T1", "P1")
        assert eng.update_vehicle_status(v.id, VehicleStatus.IN_TRANSIT) is True
        assert eng.vehicles[v.id].status == VehicleStatus.IN_TRANSIT
        assert eng.update_vehicle_status("bad", VehicleStatus.IN_TRANSIT) is False

    def test_register_driver(self):
        eng = FleetEngine()
        d = eng.register_driver("Alice", "L123")
        assert d.id in eng.drivers

    def test_assign_driver(self):
        eng = FleetEngine()
        v = eng.register_vehicle("T1", "P1")
        d = eng.register_driver("Bob", "L456")
        assert eng.assign_driver(v.id, d.id) is True
        assert eng.vehicles[v.id].driver_id == d.id
        assert eng.drivers[d.id].vehicle_id == v.id

    def test_release_vehicle(self):
        eng = FleetEngine()
        v = eng.register_vehicle("T1", "P1")
        d = eng.register_driver("Bob", "L456")
        eng.assign_driver(v.id, d.id)
        assert eng.release_vehicle(v.id) is True
        assert eng.vehicles[v.id].driver_id == ""

    def test_find_nearest_available(self):
        eng = FleetEngine()
        eng.register_vehicle("T1", "P1", region="us-east")
        v = eng.find_nearest_available(40.7, -74.0, region="us-east")
        assert v is not None

    def test_find_nearest_no_match(self):
        eng = FleetEngine()
        r = eng.find_nearest_available(40.7, -74.0, type="container_ship")
        assert r is None

    def test_metrics(self):
        eng = FleetEngine()
        eng.register_vehicle("T1", "P1")
        eng.register_driver("A", "L1")
        m = eng.get_metrics()
        assert m.total_vehicles == 1
        assert m.total_drivers == 1


# ── RoutingEngine ─────────────────────────

class TestRoutingEngine:
    def test_create_route(self):
        eng = RoutingEngine()
        route = eng.create_route("Test Route", "v1", "d1")
        assert route.id in eng.routes
        assert route.vehicle_id == "v1"

    def test_add_stop(self):
        eng = RoutingEngine()
        route = eng.create_route("R1", "v1")
        stop = RouteStop(location_name="Stop A", lat=40.7, lng=-74.0)
        assert eng.add_stop(route.id, stop) is True
        assert len(route.stops) == 1
        assert eng.add_stop("bad", stop) is False

    def test_optimize_short_route(self):
        eng = RoutingEngine()
        route = eng.create_route("R1", "v1", stops=[
            RouteStop(lat=40.7, lng=-74.0),
            RouteStop(lat=40.8, lng=-74.1),
        ])
        assert eng.optimize_stops(route.id) is False  # < 3 stops

    def test_optimize_long_route(self):
        eng = RoutingEngine()
        route = eng.create_route("R1", "v1", stops=[
            RouteStop(lat=40.7, lng=-74.0),
            RouteStop(lat=40.8, lng=-74.1),
            RouteStop(lat=40.75, lng=-73.95),
            RouteStop(lat=40.72, lng=-74.05),
        ])
        assert eng.optimize_stops(route.id) is True
        assert route.total_distance_km > 0

    def test_get_active_routes(self):
        eng = RoutingEngine()
        r1 = eng.create_route("R1", "v1")
        r2 = eng.create_route("R2", "v2")
        eng.update_status(r1.id, "active")
        assert len(eng.get_active_routes()) == 1

    def test_eta(self):
        eng = RoutingEngine()
        route = eng.create_route("R1", "v1", stops=[
            RouteStop(lat=40.7, lng=-74.0),
            RouteStop(lat=40.8, lng=-74.1),
            RouteStop(lat=40.75, lng=-73.95),
        ])
        eta = eng.estimate_eta(route.id)
        assert "remaining_stops" in eta
        assert eta["remaining_stops"] == 3


class TestDistanceMatrix:
    def test_add_and_get(self):
        dm = DistanceMatrix()
        dm.add_entry("A", "B", 100.0, 1.5)
        assert dm.get_distance("A", "B") == 100.0
        assert dm.get_duration("A", "B") == 1.5
        assert dm.get_distance("B", "A") == 0.0

    def test_estimate_distance(self):
        dm = DistanceMatrix()
        d = dm.estimate_distance(40.7, -74.0, 40.8, -74.1)
        assert 10 < d < 20

    def test_estimate_duration(self):
        dm = DistanceMatrix()
        assert dm.estimate_duration(120, 60) == 2.0
        assert dm.estimate_duration(120, 0) == 0


# ── SupplyChainEngine ─────────────────────

class TestSupplyChainEngine:
    def test_create_warehouse(self):
        eng = SupplyChainEngine()
        w = eng.create_warehouse("Main DC", 40.7, -74.0)
        assert w.id in eng.warehouses

    def test_add_inventory(self):
        eng = SupplyChainEngine()
        w = eng.create_warehouse("DC", 0, 0)
        item = eng.add_inventory("Widget", w.id, quantity=100, unit_cost=10)
        assert item.sku.startswith("SKU-")
        assert w.current_items == 100

    def test_adjust_inventory(self):
        eng = SupplyChainEngine()
        w = eng.create_warehouse("DC", 0, 0)
        item = eng.add_inventory("Widget", w.id, quantity=100)
        assert eng.adjust_inventory(item.sku, -30) is True
        assert item.quantity == 70
        assert eng.adjust_inventory("bad", 10) is False

    def test_needs_reorder(self):
        eng = SupplyChainEngine()
        w = eng.create_warehouse("DC", 0, 0)
        eng.add_inventory("Widget", w.id, quantity=5, reorder_point=10)
        assert len(eng.get_items_needing_reorder()) == 1

    def test_create_shipment(self):
        eng = SupplyChainEngine()
        s = eng.create_shipment("NYC", "LAX", weight_kg=500, revenue=1000, cost=200)
        assert s.id in eng.shipments
        assert s.profit == 800

    def test_update_shipment_status(self):
        eng = SupplyChainEngine()
        s = eng.create_shipment("A", "B")
        assert eng.update_shipment_status(s.id, ShipmentStatus.DELIVERED) is True
        assert s.is_delivered is True
        assert len(s.events) == 1
        assert eng.update_shipment_status("bad", ShipmentStatus.DELIVERED) is False

    def test_track_shipment(self):
        eng = SupplyChainEngine()
        s = eng.create_shipment("A", "B")
        found = eng.track_shipment(s.tracking_code)
        assert found is not None
        assert found.id == s.id

    def test_delivery_success_rate(self):
        eng = SupplyChainEngine()
        s1 = eng.create_shipment("A", "B")
        s2 = eng.create_shipment("C", "D")
        eng.update_shipment_status(s1.id, ShipmentStatus.DELIVERED)
        assert eng.get_delivery_success_rate() == 50.0

    def test_assign_to_route(self):
        eng = SupplyChainEngine()
        s = eng.create_shipment("A", "B")
        assert eng.assign_to_route(s.id, "v1", "r1") is True
        assert s.vehicle_id == "v1"


# ── LogisticsBrain ────────────────────────

class TestLogisticsBrain:
    def test_optimize_no_data(self):
        brain = LogisticsBrain()
        result = brain.optimize_daily_routes()
        assert "routes_created" in result

    def test_detect_anomalies(self):
        brain = LogisticsBrain()
        anomalies = brain.detect_anomalies()
        assert isinstance(anomalies, list)

    def test_fleet_health(self):
        brain = LogisticsBrain()
        health = brain.fleet_health_score()
        assert "score" in health
        assert "grade" in health

    def test_forecast_demand(self):
        brain = LogisticsBrain()
        result = brain.forecast_demand([30, 40, 35, 50, 45], horizon=3)
        assert len(result["forecast"]) == 3
        assert "trend" in result

    def test_summary(self):
        brain = LogisticsBrain()
        summary = brain.get_summary()
        assert "fleet" in summary
        assert "health_score" in summary
