"""Fleet management engine — vehicles, drivers, availability, utilization."""

from __future__ import annotations

from code_agent.logistics.models import (
    Driver, FleetMetrics, Vehicle, VehicleStatus,
)


class FleetEngine:
    """Manages fleet vehicles, drivers, and operational metrics."""

    def __init__(self):
        self.vehicles: dict[str, Vehicle] = {}
        self.drivers: dict[str, Driver] = {}

    # ── Vehicle Management ─────────────────────

    def register_vehicle(self, name: str, plate: str, type: str = "truck",
                         capacity_kg: float = 10000, capacity_m3: float = 50,
                         region: str = "us-east", **kwargs) -> Vehicle:
        v = Vehicle(name=name, plate=plate, type=type,
                    capacity_kg=capacity_kg, capacity_m3=capacity_m3,
                    region=region, **kwargs)
        self.vehicles[v.id] = v
        return v

    def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        return self.vehicles.get(vehicle_id)

    def update_vehicle_status(self, vehicle_id: str, status: VehicleStatus) -> bool:
        v = self.vehicles.get(vehicle_id)
        if not v:
            return False
        v.status = status
        return True

    def assign_driver(self, vehicle_id: str, driver_id: str) -> bool:
        v = self.vehicles.get(vehicle_id)
        d = self.drivers.get(driver_id)
        if not v or not d:
            return False
        v.driver_id = driver_id
        d.vehicle_id = vehicle_id
        v.status = VehicleStatus.RESERVED
        return True

    def release_vehicle(self, vehicle_id: str) -> bool:
        v = self.vehicles.get(vehicle_id)
        if not v:
            return False
        driver = self.drivers.get(v.driver_id)
        if driver:
            driver.vehicle_id = ""
            driver.status = "available"
        v.driver_id = ""
        v.status = VehicleStatus.AVAILABLE
        return True

    def find_nearest_available(self, lat: float, lng: float,
                                type: str = "", region: str = "") -> Vehicle | None:
        candidates = [v for v in self.vehicles.values() if v.is_available]
        if type:
            candidates = [v for v in candidates if v.type == type]
        if region:
            candidates = [v for v in candidates if v.region == region]
        if not candidates:
            return None
        return min(candidates, key=lambda v: v.distance_to(lat, lng))

    # ── Driver Management ──────────────────────

    def register_driver(self, name: str, license: str, phone: str = "",
                        region: str = "us-east", **kwargs) -> Driver:
        d = Driver(name=name, license=license, phone=phone,
                   region=region, **kwargs)
        self.drivers[d.id] = d
        return d

    def get_driver(self, driver_id: str) -> Driver | None:
        return self.drivers.get(driver_id)

    def update_driver_hours(self, driver_id: str, hours: float) -> bool:
        d = self.drivers.get(driver_id)
        if not d:
            return False
        d.hours_this_week = hours
        return True

    def find_available_driver(self, region: str = "") -> Driver | None:
        candidates = [d for d in self.drivers.values() if d.is_available]
        if region:
            candidates = [d for d in candidates if d.region == region]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.hours_remaining)

    # ── Metrics ────────────────────────────────

    def get_metrics(self) -> FleetMetrics:
        vehicles = list(self.vehicles.values())
        drivers = list(self.drivers.values())
        m = FleetMetrics(
            total_vehicles=len(vehicles),
            available=sum(1 for v in vehicles if v.status == VehicleStatus.AVAILABLE),
            in_transit=sum(1 for v in vehicles if v.status == VehicleStatus.IN_TRANSIT),
            maintenance=sum(1 for v in vehicles if v.status == VehicleStatus.MAINTENANCE),
            total_drivers=len(drivers),
            active_drivers=sum(1 for d in drivers if d.status == "driving"),
            fleet_utilization=(len(vehicles) - sum(1 for v in vehicles if v.status == VehicleStatus.AVAILABLE)) / len(vehicles) * 100 if vehicles else 0,
        )
        return m

    def get_vehicles_by_region(self, region: str) -> list[Vehicle]:
        return [v for v in self.vehicles.values() if v.region == region]
