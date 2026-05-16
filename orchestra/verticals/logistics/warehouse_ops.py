"""Warehouse Operations Agent — Warehouse and inventory management.

AI-powered warehouse operations covering slotting optimization, pick
path optimization, labor planning, receiving, put-away, cycle count,
and WMS (Warehouse Management System) integration.

Key metrics
-----------
- Units per hour (UPH), lines per hour (LPH)
- Order accuracy rate (target: 99.9%+)
- Inventory accuracy (target: 99.5%+)
- Perfect order rate
- Dock-to-stock time
- Warehouse cost per unit

Target customers
----------------
- DHL Supply Chain: Multi-client 3PL warehouse operations
- Ryder: Dedicated contract logistics / warehouse management
- XPO Logistics: Contract logistics and fulfillment
- FedEx Supply Chain: E-commerce fulfillment centers
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "WarehouseOpsAgent",
    "SlotAssignment",
    "PickPath",
    "LaborForecast",
    "CycleCountPlan",
    "ReceivingTask",
    "PutAwayTask",
    "WarehouseKPIs",
    "DockSchedule",
    "Waveplan",
    "PickMethodology",
    "StorageType",
]

log = logging.getLogger("orchestra.verticals.logistics.warehouse_ops")

# ---------------------------------------------------------------------------
# Graceful imports
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except Exception:
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class PickMethodology(str, Enum):
    """Warehouse pick methodologies."""
    DISCRETE = "discrete"           # Single order picking
    BATCH = "batch"                 # Multiple orders, single pass
    ZONE = "zone"                   # Zone-based picking
    WAVE = "wave"                   # Wave-based release
    CLUSTER = "cluster"             # Cart-based cluster picking
    GOODS_TO_PERSON = "goods_to_person"  # Automated G2P (Kiva/AutoStore)


class StorageType(str, Enum):
    """Warehouse storage types."""
    FLOOR_STACK = "floor_stack"
    SELECTIVE_RACK = "selective_rack"
    DRIVE_IN = "drive_in"
    PUSH_BACK = "push_back"
    PALLET_FLOW = "pallet_flow"     # Gravity flow FIFO
    CARTON_FLOW = "carton_flow"     # Case pick flow rack
    MEZZANINE = "mezzanine"
    AS_RS = "as_rs"                 # Automated Storage & Retrieval
    SHUTTLE = "shuttle"             # Shuttle system
    VLM = "vlm"                     # Vertical Lift Module


class InventoryMethod(str, Enum):
    """Inventory management methods."""
    FIFO = "fifo"                   # First In, First Out
    FEFO = "fefo"                   # First Expired, First Out
    LIFO = "lifo"                   # Last In, First Out
    SPECIFIC_ID = "specific_id"     # Lot/serial specific


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SlotAssignment:
    """Product slotting assignment."""
    sku: str
    product_name: str
    current_location: str
    recommended_location: str
    storage_type: StorageType
    velocity_class: str             # A (fast), B (medium), C (slow)
    units_per_day: float
    weight_kg: float = 0.0
    cube_m3: float = 0.0
    ergonomic_score: float = 0.0    # 0-100 (100 = best)
    move_priority: int = 1          # 1 = highest


@dataclass
class PickPath:
    """Optimized pick path for a batch of orders."""
    path_id: str
    methodology: PickMethodology
    order_ids: List[str] = field(default_factory=list)
    locations_sequence: List[str] = field(default_factory=list)
    total_picks: int = 0
    estimated_time_minutes: float = 0.0
    total_distance_meters: float = 0.0
    picker_id: Optional[str] = None
    zone: Optional[str] = None


@dataclass
class LaborForecast:
    """Labor planning forecast by shift."""
    forecast_date: str
    shift: str                      # "morning", "afternoon", "night"
    headcount_needed: int = 0
    receiving_staff: int = 0
    picking_staff: int = 0
    packing_staff: int = 0
    shipping_staff: int = 0
    projected_volume: int = 0       # units
    projected_orders: int = 0
    cost_estimate: float = 0.0


@dataclass
class CycleCountPlan:
    """Inventory cycle count schedule."""
    plan_id: str
    count_date: str
    locations: List[str] = field(default_factory=list)
    skus: List[str] = field(default_factory=list)
    abc_class: str = "A"            # A = count most frequently
    estimated_time_hours: float = 0.0
    counter_count: int = 1
    methodology: str = "blind_count"  # blind_count, guided_count


@dataclass
class ReceivingTask:
    """Inbound receipt processing task."""
    receipt_id: str
    po_number: str
    vendor: str
    expected_quantity: int
    received_quantity: int = 0
    variance: int = 0
    dock_door: str = ""
    arrival_time: Optional[str] = None
    processing_status: str = "pending"  # pending, in_progress, complete
    quality_check: bool = False
    items: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PutAwayTask:
    """Put-away location suggestion."""
    task_id: str
    sku: str
    quantity: int
    from_location: str              # Staging location
    to_location: str                # Suggested storage location
    storage_type: StorageType
    priority: int = 1
    fifo_compliant: bool = True
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None


@dataclass
class WarehouseKPIs:
    """Warehouse performance KPIs."""
    period: str
    units_per_hour: float = 0.0
    lines_per_hour: float = 0.0
    order_accuracy_pct: float = 99.9
    inventory_accuracy_pct: float = 99.5
    on_time_ship_pct: float = 98.0
    dock_to_stock_hours: float = 4.0
    perfect_order_pct: float = 95.0
    cost_per_unit: float = 0.0
    fill_rate_pct: float = 97.0
    space_utilization_pct: float = 0.0
    labor_cost_per_unit: float = 0.0
    damage_rate_pct: float = 0.1


@dataclass
class DockSchedule:
    """Inbound/outbound dock scheduling."""
    schedule_id: str
    dock_door: str
    scheduled_time: str
    direction: str                  # inbound, outbound
    carrier: str
    trailer_number: str = ""
    status: str = "scheduled"       # scheduled, arrived, loading, complete
    estimated_duration_minutes: int = 60
    priority: int = 1


@dataclass
class Waveplan:
    """Order wave planning."""
    wave_id: str
    wave_time: str
    order_count: int = 0
    line_count: int = 0
    unit_count: int = 0
    pick_methodology: PickMethodology = PickMethodology.WAVE
    zones_involved: List[str] = field(default_factory=list)
    estimated_completion_minutes: float = 0.0
    carrier_cutoff_time: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Warehouse labor standards
# ═══════════════════════════════════════════════════════════════════════════

_LABOR_STANDARDS: Dict[str, Dict[str, float]] = {
    "receiving": {"units_per_hour": 120.0, "cost_per_hour": 22.0},
    "putaway": {"units_per_hour": 80.0, "cost_per_hour": 22.0},
    "picking_discrete": {"lines_per_hour": 60.0, "cost_per_hour": 24.0},
    "picking_batch": {"lines_per_hour": 100.0, "cost_per_hour": 24.0},
    "picking_g2p": {"lines_per_hour": 200.0, "cost_per_hour": 20.0},
    "packing": {"units_per_hour": 50.0, "cost_per_hour": 22.0},
    "shipping": {"units_per_hour": 100.0, "cost_per_hour": 22.0},
}


# ═══════════════════════════════════════════════════════════════════════════
# WarehouseOpsAgent
# ═══════════════════════════════════════════════════════════════════════════

class WarehouseOpsAgent:
    """Warehouse operations and inventory management agent.

    Slotting optimization, pick path optimization, labor planning,
    receiving, put-away, cycle count, WMS integration.

    Examples
    --------
    >>> agent = WarehouseOpsAgent()
    >>> slotting = await agent.optimize_slotting(sku_data)
    >>> forecast = await agent.calculate_labor_forecast("2024-12-15", 50000)
    """

    TOOLS = [
        "optimize_slotting",              # Product location assignment
        "plan_pick_path",                 # Pick sequence optimization
        "process_receiving",              # Inbound receipt processing
        "generate_put_away_task",         # Put-away location suggestion
        "run_cycle_count",                # Inventory count scheduling
        "calculate_labor_forecast",       # Labor planning by shift
        "analyze_warehouse_kpis",         # Units/hour, accuracy, fill rate
        "manage_replenishment",           # Forward pick replenishment
        "track_inventory_aging",          # FIFO/FEFO compliance
        "generate_packing_list",          # Order packing instructions
        "plan_dock_scheduling",           # Inbound/outbound dock scheduling
        "calculate_storage_cost",         # Storage cost by SKU/location
        "detect_shrinkage",              # Inventory variance analysis
        "optimize_wave_planning",         # Order wave planning
        "generate_wms_report",            # WMS performance dashboard
    ]

    def __init__(
        self,
        *,
        warehouse_id: str = "WH-001",
        pick_methodology: str = "batch",
        inventory_method: str = "fifo",
        model: str = "kimi-k2.5",
    ) -> None:
        self._warehouse_id = warehouse_id
        self._pick_method = PickMethodology(pick_methodology)
        self._inventory_method = InventoryMethod(inventory_method)
        self._model = model
        self._inventory: Dict[str, Dict[str, Any]] = {}
        log.info(
            "WarehouseOpsAgent initialized (wh=%s, pick=%s, inv=%s)",
            warehouse_id, pick_methodology, inventory_method,
        )

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for warehouse operations."""
        return (
            "You are an expert warehouse operations and inventory management agent "
            "supporting 3PL and distribution center operations (DHL Supply Chain, "
            "Ryder, XPO, FedEx Supply Chain).\n\n"
            "WAREHOUSE OPERATIONS:\n"
            "- Receiving: ASN matching, quality inspection, dock scheduling\n"
            "- Put-away: Directed put-away, zone balancing, FIFO/FEFO compliance\n"
            "- Slotting: ABC velocity analysis, ergonomic golden zone, cube utilization\n"
            "- Picking: Discrete, batch, zone, wave, cluster, goods-to-person\n"
            "- Packing: Cartonization, void fill, dunnage, label placement\n"
            "- Shipping: Carrier manifesting, dock loading, trailer seal\n\n"
            "INVENTORY MANAGEMENT:\n"
            "- FIFO (First In, First Out) — standard for most products\n"
            "- FEFO (First Expired, First Out) — food, pharma, chemicals\n"
            "- Cycle counting: ABC classification, perpetual vs. periodic\n"
            "- Shrinkage analysis: theft, damage, miscounts, process errors\n"
            "- Safety stock calculation: Z × σ_d × √LT\n\n"
            "STORAGE TYPES:\n"
            "- Selective rack (most common — single-deep pallet positions)\n"
            "- Drive-in/through (high density, low selectivity)\n"
            "- Pallet flow (FIFO gravity, ideal for high-velocity items)\n"
            "- Carton flow (case pick from flow rack face)\n"
            "- AS/RS (automated storage — high throughput, reduced labor)\n"
            "- VLM / shuttle systems (small parts, high density)\n\n"
            "KEY METRICS:\n"
            "- UPH (units per hour): target varies by methodology\n"
            "  * Discrete pick: 60 LPH | Batch: 100 LPH | G2P: 200+ LPH\n"
            "- Order accuracy: 99.9% (Six Sigma level)\n"
            "- Inventory accuracy: 99.5% (cycle count tolerance)\n"
            "- Perfect order rate: 95%+ (on-time, complete, damage-free, accurate)\n"
            "- Space utilization: 85-90% target\n\n"
            "LABOR MANAGEMENT:\n"
            "- Engineered labor standards (ELS)\n"
            "- Labor Management System (LMS) integration\n"
            "- Incentive pay programs based on UPH/LPH\n"
            "- Shift planning, stagger starts, flex labor pools\n"
        )

    # -------------------------------------------------------------------
    # Core warehouse operations
    # -------------------------------------------------------------------

    async def optimize_slotting(
        self,
        sku_data: List[Dict[str, Any]],
        *,
        available_locations: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SlotAssignment]:
        """Optimize product location assignments (slotting).

        Parameters
        ----------
        sku_data:
            List of SKU dicts with: sku, name, velocity (units/day),
            weight_kg, cube_m3, current_location.
        available_locations:
            Optional list of location dicts with: location_id, zone,
            storage_type, height, weight_capacity.
        """
        log.info("Optimizing slotting for %d SKUs", len(sku_data))

        # Classify SKUs by velocity (ABC analysis)
        sorted_skus = sorted(
            sku_data, key=lambda s: s.get("velocity", 0), reverse=True,
        )

        assignments: List[SlotAssignment] = []
        total_skus = len(sorted_skus)

        for i, sku in enumerate(sorted_skus):
            # ABC classification: A=top 20%, B=next 30%, C=bottom 50%
            pct = (i + 1) / total_skus
            if pct <= 0.20:
                velocity_class = "A"
                storage = StorageType.CARTON_FLOW
                ergonomic = 90.0  # Golden zone
            elif pct <= 0.50:
                velocity_class = "B"
                storage = StorageType.SELECTIVE_RACK
                ergonomic = 70.0
            else:
                velocity_class = "C"
                storage = StorageType.SELECTIVE_RACK
                ergonomic = 50.0

            assignments.append(SlotAssignment(
                sku=sku.get("sku", ""),
                product_name=sku.get("name", ""),
                current_location=sku.get("current_location", ""),
                recommended_location=f"ZONE-{velocity_class}-{i + 1:04d}",
                storage_type=storage,
                velocity_class=velocity_class,
                units_per_day=sku.get("velocity", 0),
                weight_kg=sku.get("weight_kg", 0),
                cube_m3=sku.get("cube_m3", 0),
                ergonomic_score=ergonomic,
                move_priority=1 if velocity_class == "A" else 2 if velocity_class == "B" else 3,
            ))

        log.info(
            "Slotting complete: %d A-items, %d B-items, %d C-items",
            sum(1 for a in assignments if a.velocity_class == "A"),
            sum(1 for a in assignments if a.velocity_class == "B"),
            sum(1 for a in assignments if a.velocity_class == "C"),
        )
        return assignments

    async def plan_pick_path(
        self,
        order_lines: List[Dict[str, Any]],
        *,
        methodology: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> PickPath:
        """Optimize pick sequence for a batch of order lines.

        Parameters
        ----------
        order_lines:
            List of pick dicts with: order_id, sku, location, quantity.
        methodology:
            Override pick methodology.
        zone:
            Zone filter.
        """
        method = PickMethodology(methodology) if methodology else self._pick_method
        path_id = uuid.uuid4().hex[:12]

        log.info("Planning pick path %s (%d lines, method=%s)", path_id, len(order_lines), method.value)

        # Sort locations for optimal path (S-pattern through aisles)
        locations = [line.get("location", "") for line in order_lines]
        locations_sorted = sorted(locations)  # Simple sort by location code

        # Time estimate based on labor standards
        rate = _LABOR_STANDARDS.get(f"picking_{method.value}", _LABOR_STANDARDS["picking_discrete"])
        estimated_time = len(order_lines) / rate["lines_per_hour"] * 60  # minutes

        order_ids = list(set(line.get("order_id", "") for line in order_lines))

        return PickPath(
            path_id=path_id,
            methodology=method,
            order_ids=order_ids,
            locations_sequence=locations_sorted,
            total_picks=len(order_lines),
            estimated_time_minutes=round(estimated_time, 1),
            total_distance_meters=len(order_lines) * 8.0,  # ~8m per pick avg
            zone=zone,
        )

    async def process_receiving(
        self,
        po_number: str,
        items: List[Dict[str, Any]],
        *,
        vendor: str = "",
        dock_door: str = "",
    ) -> ReceivingTask:
        """Process inbound receipt against purchase order.

        Parameters
        ----------
        po_number:
            Purchase order number.
        items:
            List of received items with: sku, expected_qty, received_qty.
        vendor:
            Vendor name.
        dock_door:
            Dock door assignment.
        """
        receipt_id = uuid.uuid4().hex[:12]
        expected = sum(i.get("expected_qty", 0) for i in items)
        received = sum(i.get("received_qty", 0) for i in items)

        return ReceivingTask(
            receipt_id=receipt_id,
            po_number=po_number,
            vendor=vendor,
            expected_quantity=expected,
            received_quantity=received,
            variance=received - expected,
            dock_door=dock_door,
            arrival_time=datetime.now(timezone.utc).isoformat(),
            processing_status="complete",
            quality_check=True,
            items=items,
        )

    async def calculate_labor_forecast(
        self,
        forecast_date: str,
        projected_units: int,
        *,
        projected_orders: int = 0,
        shift: str = "morning",
    ) -> LaborForecast:
        """Calculate labor requirements by shift.

        Parameters
        ----------
        forecast_date:
            Date for forecast.
        projected_units:
            Expected unit volume.
        projected_orders:
            Expected order count.
        shift:
            Shift name.
        """
        if not projected_orders:
            projected_orders = projected_units // 10

        receiving = max(1, int(projected_units * 0.15 / _LABOR_STANDARDS["receiving"]["units_per_hour"] / 8))
        picking = max(1, int(projected_orders / _LABOR_STANDARDS["picking_batch"]["lines_per_hour"] / 8 * 3))
        packing = max(1, int(projected_units / _LABOR_STANDARDS["packing"]["units_per_hour"] / 8))
        shipping = max(1, int(projected_units / _LABOR_STANDARDS["shipping"]["units_per_hour"] / 8))

        total = receiving + picking + packing + shipping
        cost = (
            receiving * _LABOR_STANDARDS["receiving"]["cost_per_hour"] * 8
            + picking * _LABOR_STANDARDS["picking_batch"]["cost_per_hour"] * 8
            + packing * _LABOR_STANDARDS["packing"]["cost_per_hour"] * 8
            + shipping * _LABOR_STANDARDS["shipping"]["cost_per_hour"] * 8
        )

        return LaborForecast(
            forecast_date=forecast_date,
            shift=shift,
            headcount_needed=total,
            receiving_staff=receiving,
            picking_staff=picking,
            packing_staff=packing,
            shipping_staff=shipping,
            projected_volume=projected_units,
            projected_orders=projected_orders,
            cost_estimate=round(cost, 2),
        )

    async def analyze_warehouse_kpis(
        self,
        period: str,
        metrics_data: Optional[Dict[str, Any]] = None,
    ) -> WarehouseKPIs:
        """Generate warehouse KPI dashboard.

        Parameters
        ----------
        period:
            Reporting period (e.g., "2024-Q4").
        metrics_data:
            Optional raw metrics to compute KPIs from.
        """
        data = metrics_data or {}

        return WarehouseKPIs(
            period=period,
            units_per_hour=data.get("uph", 0.0),
            lines_per_hour=data.get("lph", 0.0),
            order_accuracy_pct=data.get("order_accuracy", 99.9),
            inventory_accuracy_pct=data.get("inv_accuracy", 99.5),
            on_time_ship_pct=data.get("ots", 98.0),
            dock_to_stock_hours=data.get("d2s", 4.0),
            perfect_order_pct=data.get("perfect_order", 95.0),
            cost_per_unit=data.get("cpu", 0.0),
            fill_rate_pct=data.get("fill_rate", 97.0),
            space_utilization_pct=data.get("space_util", 0.0),
        )

    async def optimize_wave_planning(
        self,
        orders: List[Dict[str, Any]],
        *,
        carrier_cutoff: Optional[str] = None,
        max_wave_size: int = 500,
    ) -> List[Waveplan]:
        """Plan order release waves.

        Parameters
        ----------
        orders:
            List of order dicts with: order_id, lines, units, zone, priority.
        carrier_cutoff:
            Carrier pickup cutoff time.
        max_wave_size:
            Maximum orders per wave.
        """
        log.info("Planning waves for %d orders (max_wave=%d)", len(orders), max_wave_size)

        waves: List[Waveplan] = []
        for i in range(0, len(orders), max_wave_size):
            batch = orders[i: i + max_wave_size]
            total_lines = sum(o.get("lines", 1) for o in batch)
            total_units = sum(o.get("units", 1) for o in batch)
            zones = list(set(o.get("zone", "A") for o in batch))

            rate = _LABOR_STANDARDS["picking_batch"]["lines_per_hour"]
            est_time = total_lines / rate * 60

            wave = Waveplan(
                wave_id=f"WAVE-{uuid.uuid4().hex[:8].upper()}",
                wave_time=datetime.now(timezone.utc).isoformat(),
                order_count=len(batch),
                line_count=total_lines,
                unit_count=total_units,
                pick_methodology=self._pick_method,
                zones_involved=zones,
                estimated_completion_minutes=round(est_time, 1),
                carrier_cutoff_time=carrier_cutoff,
            )
            waves.append(wave)

        return waves

    async def plan_dock_scheduling(
        self,
        appointments: List[Dict[str, Any]],
        *,
        available_doors: int = 10,
    ) -> List[DockSchedule]:
        """Schedule inbound/outbound dock appointments.

        Parameters
        ----------
        appointments:
            List of appointment dicts with: carrier, time, direction, duration.
        available_doors:
            Number of dock doors available.
        """
        schedules: List[DockSchedule] = []
        door_idx = 0

        for appt in appointments:
            door = f"DOOR-{(door_idx % available_doors) + 1:02d}"
            door_idx += 1

            schedules.append(DockSchedule(
                schedule_id=uuid.uuid4().hex[:10],
                dock_door=door,
                scheduled_time=appt.get("time", ""),
                direction=appt.get("direction", "inbound"),
                carrier=appt.get("carrier", ""),
                trailer_number=appt.get("trailer", ""),
                estimated_duration_minutes=appt.get("duration", 60),
            ))

        return schedules

    async def detect_shrinkage(
        self,
        inventory_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze inventory variances to detect shrinkage.

        Parameters
        ----------
        inventory_records:
            List of records with: sku, system_qty, physical_qty, value.
        """
        total_variance = 0
        total_value_loss = 0.0
        variances: List[Dict[str, Any]] = []

        for record in inventory_records:
            system = record.get("system_qty", 0)
            physical = record.get("physical_qty", 0)
            unit_value = record.get("unit_value", 0.0)
            variance = physical - system

            if variance != 0:
                total_variance += abs(variance)
                total_value_loss += abs(variance) * unit_value
                variances.append({
                    "sku": record.get("sku", ""),
                    "variance": variance,
                    "value_impact": abs(variance) * unit_value,
                    "direction": "overage" if variance > 0 else "shortage",
                })

        total_system = sum(r.get("system_qty", 0) for r in inventory_records)
        accuracy = ((total_system - total_variance) / max(1, total_system)) * 100

        return {
            "total_records": len(inventory_records),
            "records_with_variance": len(variances),
            "total_unit_variance": total_variance,
            "total_value_loss": round(total_value_loss, 2),
            "inventory_accuracy_pct": round(accuracy, 2),
            "top_variances": sorted(variances, key=lambda v: abs(v["value_impact"]), reverse=True)[:20],
        }
