"""Supply chain engine — inventory, warehouses, order fulfillment, suppliers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from code_agent.logistics.models import (
    InventoryItem, Shipment, ShipmentStatus, SupplyChainEvent, Warehouse,
)


class SupplyChainEngine:
    """Manages warehouses, inventory, shipments, and order fulfillment."""

    def __init__(self):
        self.warehouses: dict[str, Warehouse] = {}
        self.inventory: dict[str, InventoryItem] = {}
        self.shipments: dict[str, Shipment] = {}
        self._next_sku = 1000

    # ── Warehouses ─────────────────────────

    def create_warehouse(self, name: str, lat: float, lng: float,
                         capacity: int = 10000, region: str = "us-east") -> Warehouse:
        w = Warehouse(name=name, lat=lat, lng=lng,
                      capacity_items=capacity, region=region)
        self.warehouses[w.id] = w
        return w

    def get_warehouse(self, wid: str) -> Warehouse | None:
        return self.warehouses.get(wid)

    def get_warehouses_by_region(self, region: str) -> list[Warehouse]:
        return [w for w in self.warehouses.values() if w.region == region]

    # ── Inventory ─────────────────────────

    def add_inventory(self, name: str, warehouse_id: str,
                      quantity: int = 0, unit_cost: float = 0.0,
                      reorder_point: int = 10, category: str = "general",
                      supplier: str = "") -> InventoryItem:
        sku = f"SKU-{self._next_sku}"
        self._next_sku += 1
        item = InventoryItem(
            sku=sku, name=name, warehouse_id=warehouse_id,
            quantity=quantity, unit_cost=unit_cost,
            reorder_point=reorder_point, category=category, supplier=supplier,
        )
        self.inventory[sku] = item
        wh = self.warehouses.get(warehouse_id)
        if wh:
            wh.current_items += quantity
        return item

    def adjust_inventory(self, sku: str, delta: int) -> bool:
        item = self.inventory.get(sku)
        if not item:
            return False
        old_qty = item.quantity
        item.quantity = max(0, item.quantity + delta)
        wh = self.warehouses.get(item.warehouse_id)
        if wh:
            wh.current_items += item.quantity - old_qty
        return True

    def get_items_needing_reorder(self) -> list[InventoryItem]:
        return [i for i in self.inventory.values() if i.needs_reorder]

    def get_inventory_by_warehouse(self, wid: str) -> list[InventoryItem]:
        return [i for i in self.inventory.values() if i.warehouse_id == wid]

    def get_inventory_value(self) -> float:
        return sum(i.total_value for i in self.inventory.values())

    # ── Shipments ─────────────────────────

    def create_shipment(self, origin: str, destination: str,
                        weight_kg: float = 0, volume_m3: float = 0,
                        customer: str = "", priority: str = "standard",
                        cost: float = 0, revenue: float = 0) -> Shipment:
        s = Shipment(
            origin=origin, destination=destination,
            weight_kg=weight_kg, volume_m3=volume_m3,
            customer=customer, priority=priority,
            cost=cost, revenue=revenue,
        )
        self.shipments[s.id] = s
        return s

    def get_shipment(self, sid: str) -> Shipment | None:
        return self.shipments.get(sid)

    def update_shipment_status(self, sid: str, status: ShipmentStatus,
                               location: str = "", description: str = "") -> bool:
        s = self.shipments.get(sid)
        if not s:
            return False
        s.status = status
        if status == ShipmentStatus.DELIVERED:
            s.actual_delivery = datetime.now(timezone.utc).isoformat()
        s.events.append(SupplyChainEvent(
            type=status.value, location=location,
            description=description or f"Status changed to {status.value}",
            actor="system",
        ))
        return True

    def track_shipment(self, tracking_code: str) -> Shipment | None:
        for s in self.shipments.values():
            if s.tracking_code == tracking_code:
                return s
        return None

    def get_shipments_by_status(self, status: ShipmentStatus) -> list[Shipment]:
        return [s for s in self.shipments.values() if s.status == status]

    def get_delivery_success_rate(self) -> float:
        total = len(self.shipments)
        if not total:
            return 0.0
        delivered = sum(1 for s in self.shipments.values() if s.is_delivered)
        return round(delivered / total * 100, 1)

    def get_on_time_rate(self) -> float:
        delivered = [s for s in self.shipments.values() if s.is_delivered]
        if not delivered:
            return 0.0
        on_time = 0
        for s in delivered:
            if s.estimated_delivery and s.actual_delivery:
                try:
                    est = datetime.fromisoformat(s.estimated_delivery)
                    act = datetime.fromisoformat(s.actual_delivery)
                    if act <= est:
                        on_time += 1
                except ValueError:
                    pass
        return round(on_time / len(delivered) * 100, 1) if delivered else 0.0

    def assign_to_route(self, shipment_id: str, vehicle_id: str, route_id: str) -> bool:
        s = self.shipments.get(shipment_id)
        if not s:
            return False
        s.vehicle_id = vehicle_id
        s.route_id = route_id
        s.status = ShipmentStatus.IN_TRANSIT
        s.events.append(SupplyChainEvent(
            type="assigned", description=f"Assigned to route {route_id}",
        ))
        return True
