"""Data models for the Orchestra Logistics platform."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class VehicleStatus(Enum):
    AVAILABLE = "available"
    IN_TRANSIT = "in_transit"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    RESERVED = "reserved"


class ShipmentStatus(Enum):
    PENDING = "pending"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    RETURNED = "returned"


@dataclass
class Vehicle:
    id: str = ""
    name: str = ""
    plate: str = ""
    type: str = "truck"  # truck, van, container_ship, forklift, drone
    status: VehicleStatus = VehicleStatus.AVAILABLE
    capacity_kg: float = 10000.0
    capacity_m3: float = 50.0
    current_lat: float = 0.0
    current_lng: float = 0.0
    fuel_efficiency: float = 6.5  # km/l
    driver_id: str = ""
    region: str = "us-east"
    tags: list[str] = field(default_factory=list)
    last_maintenance: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_available(self) -> bool:
        return self.status == VehicleStatus.AVAILABLE

    def distance_to(self, lat: float, lng: float) -> float:
        return haversine(self.current_lat, self.current_lng, lat, lng)


@dataclass
class Driver:
    id: str = ""
    name: str = ""
    license: str = ""
    phone: str = ""
    status: str = "available"  # available, driving, off_duty, sick
    hours_this_week: float = 0.0
    max_hours_per_week: float = 60.0
    region: str = "us-east"
    rating: float = 5.0
    vehicle_id: str = ""
    certifications: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_available(self) -> bool:
        return self.status == "available"

    @property
    def hours_remaining(self) -> float:
        return max(0, self.max_hours_per_week - self.hours_this_week)


@dataclass
class RouteStop:
    sequence: int = 0
    location_name: str = ""
    lat: float = 0.0
    lng: float = 0.0
    arrival_time: str = ""
    departure_time: str = ""
    type: str = "pickup"  # pickup, delivery, depot
    notes: str = ""


@dataclass
class Route:
    id: str = ""
    name: str = ""
    vehicle_id: str = ""
    driver_id: str = ""
    stops: list[RouteStop] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_duration_hours: float = 0.0
    status: str = "planned"  # planned, active, completed, cancelled
    carbon_footprint_kg: float = 0.0
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def stop_count(self) -> int:
        return len(self.stops)


@dataclass
class Shipment:
    id: str = ""
    tracking_code: str = ""
    origin: str = ""
    destination: str = ""
    weight_kg: float = 0.0
    volume_m3: float = 0.0
    status: ShipmentStatus = ShipmentStatus.PENDING
    vehicle_id: str = ""
    route_id: str = ""
    customer: str = ""
    priority: str = "standard"  # express, standard, economy
    estimated_delivery: str = ""
    actual_delivery: str = ""
    cost: float = 0.0
    revenue: float = 0.0
    notes: str = ""
    events: list[SupplyChainEvent] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.tracking_code:
            self.tracking_code = f"ORCH-{uuid.uuid4().hex[:8].upper()}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_delivered(self) -> bool:
        return self.status == ShipmentStatus.DELIVERED

    @property
    def days_in_transit(self) -> int:
        if not self.estimated_delivery:
            return 0
        try:
            est = datetime.fromisoformat(self.estimated_delivery)
            now = datetime.now(timezone.utc)
            return max(0, (now - est).days)
        except ValueError:
            return 0

    @property
    def profit(self) -> float:
        return self.revenue - self.cost


@dataclass
class SupplyChainEvent:
    type: str = ""
    timestamp: str = ""
    location: str = ""
    description: str = ""
    actor: str = ""


@dataclass
class Warehouse:
    id: str = ""
    name: str = ""
    lat: float = 0.0
    lng: float = 0.0
    capacity_items: int = 10000
    current_items: int = 0
    region: str = "us-east"
    operating_hours: str = "06:00-22:00"
    staff_count: int = 0
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def utilization(self) -> float:
        return (self.current_items / self.capacity_items * 100) if self.capacity_items else 0

    @property
    def available_capacity(self) -> int:
        return max(0, self.capacity_items - self.current_items)


@dataclass
class InventoryItem:
    sku: str = ""
    name: str = ""
    quantity: int = 0
    warehouse_id: str = ""
    reorder_point: int = 0
    unit_cost: float = 0.0
    category: str = "general"
    supplier: str = ""

    @property
    def needs_reorder(self) -> bool:
        return self.quantity <= self.reorder_point

    @property
    def total_value(self) -> float:
        return self.quantity * self.unit_cost


@dataclass
class FleetMetrics:
    total_vehicles: int = 0
    available: int = 0
    in_transit: int = 0
    maintenance: int = 0
    total_drivers: int = 0
    active_drivers: int = 0
    total_routes: int = 0
    active_routes: int = 0
    total_shipments: int = 0
    delivered_today: int = 0
    on_time_rate: float = 0.0
    avg_delivery_time_hours: float = 0.0
    carbon_saved_kg: float = 0.0
    fleet_utilization: float = 0.0


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
