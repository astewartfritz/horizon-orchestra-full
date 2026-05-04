"""Logistics / Supply Chain vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for enterprise logistics and supply
chain management.  Targets global 3PL and carrier companies including
DHL, Ryder, FedEx, UPS, Maersk, and XPO Logistics.

Agents
------
:class:`ShipmentTrackingAgent`
    Multi-carrier tracking, exception management, ETA prediction,
    carbon footprint calculation, and proof-of-delivery validation.

:class:`RouteOptimizationAgent`
    Vehicle Routing Problem (VRP) solving, dynamic rerouting,
    FMCSA HOS compliance, fleet capacity planning.

:class:`WarehouseOpsAgent`
    Slotting optimization, pick path optimization, labor planning,
    cycle counts, WMS integration, and dock scheduling.

:class:`CustomsComplianceAgent`
    HTS classification, OFAC screening, EAR/ITAR export controls,
    FTA qualification, duty drawback, and customs entry filing.

:class:`CarrierManagementAgent`
    Carrier performance scoring, rate procurement, RFP analysis,
    capacity monitoring, and contract management.

Pre-Built Teams
---------------
:func:`enterprise_logistics_team`
    Full logistics operations (DHL/Ryder-level).

:func:`trade_compliance_team`
    Customs + OFAC + export control pipeline.

:func:`fleet_management_team`
    Routing + drivers + warehouse operations.

:func:`last_mile_team`
    Last-mile delivery optimization.
"""

from __future__ import annotations

from .shipment_tracking import ShipmentTrackingAgent
from .route_optimization import RouteOptimizationAgent
from .warehouse_ops import WarehouseOpsAgent
from .customs_compliance import CustomsComplianceAgent
from .carrier_management import CarrierManagementAgent
from .pre_built_teams import (
    enterprise_logistics_team,
    trade_compliance_team,
    fleet_management_team,
    last_mile_team,
)

__all__ = [
    "ShipmentTrackingAgent",
    "RouteOptimizationAgent",
    "WarehouseOpsAgent",
    "CustomsComplianceAgent",
    "CarrierManagementAgent",
    "enterprise_logistics_team",
    "trade_compliance_team",
    "fleet_management_team",
    "last_mile_team",
]
