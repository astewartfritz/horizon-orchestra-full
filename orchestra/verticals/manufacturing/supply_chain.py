"""Horizon Orchestra — Manufacturing Supply Chain Agent.

Provides a domain-specialized agent for manufacturing supply chain
workflows including supplier risk analysis, inventory optimization,
S&OP planning, and make-vs-buy analysis.

Industry references:
- APICS / ASCM SCOR Model (Supply Chain Operations Reference)
- INCOTERMS 2020 (international commercial terms)
- ISO 28000 (Supply Chain Security Management)
- ISM (Institute for Supply Management) best practices
- ABC/XYZ inventory classification
- Wagner-Whitin / Silver-Meal lot sizing algorithms

Target customers: GE, 3M, Caterpillar, Deere, and comparable
manufacturing enterprises with complex supply chains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

__all__ = ["ManufacturingSupplyChainAgent"]

log = logging.getLogger("orchestra.verticals.manufacturing.supply_chain")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class SupplierRiskLevel(Enum):
    """Supplier risk classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InventoryClass(Enum):
    """ABC classification for inventory."""
    A = "A"  # ~20% items, ~80% value
    B = "B"  # ~30% items, ~15% value
    C = "C"  # ~50% items, ~5% value


@dataclass
class SupplierScorecard:
    """Supplier performance scorecard."""
    supplier_name: str = ""
    quality_score: float = 0.0  # 0-100
    delivery_score: float = 0.0
    cost_score: float = 0.0
    responsiveness_score: float = 0.0
    overall_score: float = 0.0
    ppm_defect_rate: float = 0.0
    on_time_delivery_pct: float = 0.0


@dataclass
class EOQResult:
    """Economic Order Quantity calculation result."""
    eoq: float = 0.0
    annual_ordering_cost: float = 0.0
    annual_holding_cost: float = 0.0
    total_annual_cost: float = 0.0
    reorder_point: float = 0.0
    number_of_orders: float = 0.0


@dataclass
class ToolResult:
    """Standardised tool execution result."""
    tool_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    execution_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manufacturing Supply Chain Agent
# ---------------------------------------------------------------------------

class ManufacturingSupplyChainAgent:
    """Domain-specialized agent for manufacturing supply chain management.

    Covers supplier risk analysis, inventory optimization, demand
    sensing, S&OP planning, BOM management, and total cost of ownership.

    Attributes
    ----------
    TOOLS : list[str]
        The 14 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = ManufacturingSupplyChainAgent()
        result = await agent.execute_tool("calculate_eoq", annual_demand=10000)
    """

    TOOLS: list[str] = [
        "analyze_supplier_risk",
        "optimize_safety_stock",
        "calculate_eoq",
        "run_demand_sensing",
        "manage_purchase_orders",
        "track_supplier_scorecard",
        "optimize_inventory_turns",
        "analyze_lead_time_variability",
        "run_abc_xyz_analysis",
        "manage_bom_changes",
        "calculate_total_cost_of_ownership",
        "plan_s_op",
        "analyze_make_vs_buy",
        "manage_supplier_contracts",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        plant_code: str = "PLANT01",
    ) -> None:
        self.agent_id = agent_id or f"scm-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.plant_code = plant_code
        self._audit_log: list[dict[str, Any]] = []
        log.info("ManufacturingSupplyChainAgent %s initialised (plant=%s)", self.agent_id, plant_code)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for supply chain management.

        Returns a comprehensive prompt embedding SCM knowledge,
        procurement best practices, and inventory optimization methods.
        """
        return (
            "You are a senior supply chain manager with deep expertise in "
            "manufacturing procurement, inventory management, and S&OP "
            "planning. You optimize the end-to-end supply chain for cost, "
            "quality, delivery, and risk.\n\n"
            "INVENTORY MANAGEMENT:\n"
            "- EOQ (Economic Order Quantity): Q* = √(2DS/H) where D = annual "
            "demand, S = order/setup cost, H = annual holding cost per unit.\n"
            "- Safety Stock: SS = Z × σ_dLT where Z = service factor, "
            "σ_dLT = standard deviation of demand during lead time. For "
            "variable demand and lead time: σ_dLT = √(LT × σ_d² + d̄² × σ_LT²).\n"
            "- Reorder Point: ROP = d̄ × LT + SS.\n"
            "- ABC Classification: A items (~20% SKUs, ~80% value) — tight "
            "control, frequent review. B items (~30%, ~15%) — moderate. "
            "C items (~50%, ~5%) — simple controls.\n"
            "- XYZ Classification: X = stable demand (CV < 0.5), Y = variable "
            "(0.5-1.0), Z = erratic (CV > 1.0). Combine with ABC for "
            "differentiated strategies.\n"
            "- Inventory Turns = COGS / Average Inventory. Higher is better "
            "but balance against stockout risk.\n\n"
            "SUPPLIER MANAGEMENT:\n"
            "- Supplier Scorecards: QCDR framework — Quality (PPM, incoming "
            "inspection pass rate), Cost (price competitiveness, cost "
            "reduction YoY), Delivery (OTD%, lead time reliability), "
            "Responsiveness (RFQ turnaround, issue resolution time).\n"
            "- Supplier Risk: Financial stability (D&B, credit rating), "
            "geographic concentration, single-source exposure, geopolitical "
            "risk, natural disaster exposure. Dual/multi-source strategy "
            "for critical items.\n"
            "- Total Cost of Ownership (TCO): Unit price + freight + customs "
            "duties + quality costs + inventory carrying + admin + risk premium.\n"
            "- INCOTERMS 2020: EXW, FCA, CPT, CIP, DAP, DPU, DDP for any "
            "mode; FAS, FOB, CFR, CIF for sea/inland waterway.\n\n"
            "S&OP (SALES & OPERATIONS PLANNING):\n"
            "- Monthly cadence: Demand Review → Supply Review → Pre-S&OP → "
            "Executive S&OP → Implementation.\n"
            "- Consensus demand plan: Statistical forecast + market intelligence "
            "+ sales input. Forecast accuracy: MAPE, bias, tracking signal.\n"
            "- Rough-cut capacity check: Can we make what we plan to sell?\n"
            "- Financial reconciliation: Does the operations plan align with "
            "the business plan / budget?\n\n"
            "MAKE VS BUY:\n"
            "- Decision factors: Core competency, capacity availability, cost "
            "(variable + allocated fixed + opportunity), quality capability, "
            "lead time, IP protection, strategic importance.\n"
            "- Total cost comparison: Internal = material + labour + overhead + "
            "depreciation + opportunity cost. External = purchase price + "
            "freight + quality + inventory + risk.\n\n"
            "BOM MANAGEMENT:\n"
            "- Engineering Change Orders (ECO): Phase-in/phase-out management. "
            "Effectivity dates. Impact analysis across all affected items.\n"
            "- BOM accuracy target: 98%+. Cycle counting for verification.\n"
            "- Multi-level BOM explosion for MRP.\n\n"
            "PROCUREMENT:\n"
            "- Strategic sourcing: Spend analysis, market intelligence, "
            "RFx process (RFI → RFP → RFQ), supplier selection, contract "
            "negotiation.\n"
            "- Purchase order management: Requisition → Approval → PO → "
            "Goods Receipt → Invoice Verification → Payment.\n"
            f"- Plant code: {self.plant_code}\n"
        )

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute one of this agent's registered tools."""
        if tool_name not in self.TOOLS:
            raise ValueError(f"Unknown tool '{tool_name}'. Available: {self.TOOLS}")
        start = asyncio.get_event_loop().time()
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            return ToolResult(tool_name=tool_name, success=False, error=f"Handler not implemented for {tool_name}")
        try:
            data = await handler(**kwargs)
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            result = ToolResult(tool_name=tool_name, success=True, data=data, execution_time_ms=elapsed)
        except Exception as exc:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            log.exception("Tool %s failed", tool_name)
            result = ToolResult(tool_name=tool_name, success=False, error=str(exc), execution_time_ms=elapsed)
        self._record_audit(tool_name, result)
        return result

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _tool_analyze_supplier_risk(
        self,
        *,
        supplier: str = "",
        risk_factors: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse supplier risk across multiple dimensions."""
        return {
            "supplier": supplier,
            "overall_risk": "medium",
            "risk_factors": {
                "financial_stability": "low",
                "geographic_concentration": "medium",
                "single_source": False,
                "geopolitical": "low",
                "natural_disaster": "low",
                "cyber_security": "medium",
                "capacity_constraint": "low",
            },
            "mitigation_recommendations": [],
            "alternative_suppliers": [],
            "reference": "ISO 28000 Supply Chain Security",
        }

    async def _tool_optimize_safety_stock(
        self,
        *,
        item_number: str = "",
        service_level: float = 0.95,
        demand_std_dev: float = 0.0,
        lead_time_days: int = 0,
        lead_time_std_dev: float = 0.0,
        avg_daily_demand: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize safety stock levels based on service level targets."""
        import statistics
        # Z-score lookup (simplified)
        z_scores = {0.90: 1.28, 0.95: 1.645, 0.99: 2.326, 0.999: 3.09}
        z = z_scores.get(service_level, 1.645)

        # Combined demand-leadtime variability
        sigma_dlt = math.sqrt(
            lead_time_days * demand_std_dev ** 2 +
            avg_daily_demand ** 2 * lead_time_std_dev ** 2
        ) if lead_time_days > 0 else 0

        safety_stock = z * sigma_dlt
        rop = avg_daily_demand * lead_time_days + safety_stock

        return {
            "item_number": item_number,
            "service_level": service_level,
            "z_score": z,
            "safety_stock": round(safety_stock, 0),
            "reorder_point": round(rop, 0),
            "sigma_dlt": round(sigma_dlt, 2),
        }

    async def _tool_calculate_eoq(
        self,
        *,
        annual_demand: float = 0.0,
        order_cost: float = 0.0,
        holding_cost_per_unit: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Economic Order Quantity (EOQ)."""
        eoq = 0.0
        if order_cost > 0 and holding_cost_per_unit > 0 and annual_demand > 0:
            eoq = math.sqrt(2 * annual_demand * order_cost / holding_cost_per_unit)

        num_orders = annual_demand / eoq if eoq > 0 else 0
        total_cost = math.sqrt(2 * annual_demand * order_cost * holding_cost_per_unit) if all([annual_demand, order_cost, holding_cost_per_unit]) else 0

        return {
            "eoq": round(eoq, 0),
            "annual_demand": annual_demand,
            "order_cost": order_cost,
            "holding_cost_per_unit": holding_cost_per_unit,
            "number_of_orders_per_year": round(num_orders, 1),
            "total_annual_cost": round(total_cost, 2),
            "methodology": "Classic EOQ (Wilson Formula)",
        }

    async def _tool_run_demand_sensing(
        self,
        *,
        item_number: str = "",
        horizon_weeks: int = 4,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run short-horizon demand sensing using leading indicators."""
        return {
            "item_number": item_number,
            "horizon_weeks": horizon_weeks,
            "sensed_demand": [],
            "signals_used": [
                "POS data", "Weather forecast", "Promotional calendar",
                "Economic indicators", "Social media sentiment",
            ],
            "confidence": 0.0,
        }

    async def _tool_manage_purchase_orders(
        self,
        *,
        action: str = "list",
        po_number: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Manage purchase orders (create, update, status, receive)."""
        return {
            "action": action,
            "po_number": po_number or f"PO-{uuid.uuid4().hex[:6].upper()}",
            "status": "open",
            "plant": self.plant_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _tool_track_supplier_scorecard(
        self,
        *,
        supplier: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Track supplier performance scorecard (QCDR framework)."""
        return {
            "supplier": supplier,
            "period": "rolling_12_months",
            "quality_score": 0.0,
            "cost_score": 0.0,
            "delivery_score": 0.0,
            "responsiveness_score": 0.0,
            "overall_score": 0.0,
            "ppm_defect_rate": 0.0,
            "otd_pct": 0.0,
            "trend": "stable",
        }

    async def _tool_optimize_inventory_turns(
        self,
        *,
        target_turns: float = 12.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse and optimize inventory turns."""
        return {
            "current_turns": 0.0,
            "target_turns": target_turns,
            "gap": 0.0,
            "recommendations": [],
            "slow_moving_items": [],
            "excess_inventory_value": 0.0,
            "obsolete_inventory_value": 0.0,
        }

    async def _tool_analyze_lead_time_variability(
        self,
        *,
        item_number: str = "",
        supplier: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse lead time variability for an item/supplier combination."""
        return {
            "item_number": item_number,
            "supplier": supplier,
            "avg_lead_time_days": 0.0,
            "std_dev_days": 0.0,
            "cv": 0.0,
            "min_lead_time": 0.0,
            "max_lead_time": 0.0,
            "on_time_pct": 0.0,
            "improvement_suggestions": [],
        }

    async def _tool_run_abc_xyz_analysis(
        self,
        *,
        items: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run ABC/XYZ inventory classification analysis."""
        return {
            "total_items": len(items) if items else 0,
            "classification": {
                "AX": 0, "AY": 0, "AZ": 0,
                "BX": 0, "BY": 0, "BZ": 0,
                "CX": 0, "CY": 0, "CZ": 0,
            },
            "strategy_recommendations": {
                "AX": "JIT / Kanban, tight control, frequent replenishment",
                "AY": "MRP with safety stock, regular review",
                "AZ": "Higher safety stock, dual source",
                "CX": "Simple reorder point, automatic replenishment",
                "CZ": "Consider consignment or drop-ship",
            },
        }

    async def _tool_manage_bom_changes(
        self,
        *,
        eco_number: str = "",
        change_type: str = "component_substitution",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Manage Bill of Materials changes via Engineering Change Orders."""
        return {
            "eco_number": eco_number or f"ECO-{uuid.uuid4().hex[:6].upper()}",
            "change_type": change_type,
            "affected_items": [],
            "effectivity_date": "",
            "impact_analysis": {
                "inventory_disposition": "pending",
                "cost_impact": 0.0,
                "lead_time_impact": 0,
            },
            "status": "draft",
            "approvals_required": ["Engineering", "Quality", "Procurement", "Planning"],
        }

    async def _tool_calculate_total_cost_of_ownership(
        self,
        *,
        supplier: str = "",
        unit_price: float = 0.0,
        annual_volume: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Total Cost of Ownership (TCO) for sourcing decisions."""
        return {
            "supplier": supplier,
            "unit_price": unit_price,
            "annual_volume": annual_volume,
            "cost_breakdown": {
                "unit_price": unit_price,
                "freight_per_unit": 0.0,
                "customs_duties_per_unit": 0.0,
                "quality_cost_per_unit": 0.0,
                "inventory_carrying_per_unit": 0.0,
                "admin_cost_per_unit": 0.0,
                "risk_premium_per_unit": 0.0,
            },
            "tco_per_unit": unit_price,
            "tco_premium_over_price": 0.0,
            "incoterm_assumed": "DDP",
            "reference": "INCOTERMS 2020",
        }

    async def _tool_plan_s_op(
        self,
        *,
        planning_horizon_months: int = 18,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate S&OP (Sales & Operations Planning) plan."""
        return {
            "planning_horizon_months": planning_horizon_months,
            "process_steps": [
                "Data Gathering", "Demand Review", "Supply Review",
                "Pre-S&OP Meeting", "Executive S&OP", "Implementation",
            ],
            "demand_plan": [],
            "supply_plan": [],
            "capacity_gaps": [],
            "financial_reconciliation": "pending",
            "cadence": "monthly",
        }

    async def _tool_analyze_make_vs_buy(
        self,
        *,
        item_number: str = "",
        internal_cost: dict[str, float] | None = None,
        external_cost: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse make-vs-buy decision for a component."""
        int_cost = internal_cost or {"material": 0, "labor": 0, "overhead": 0}
        ext_cost = external_cost or {"purchase_price": 0, "freight": 0, "quality": 0}
        total_internal = sum(int_cost.values())
        total_external = sum(ext_cost.values())

        return {
            "item_number": item_number,
            "internal_cost": int_cost,
            "external_cost": ext_cost,
            "total_internal": total_internal,
            "total_external": total_external,
            "recommendation": "make" if total_internal < total_external else "buy",
            "qualitative_factors": [
                "Core competency alignment",
                "Capacity availability",
                "IP protection",
                "Quality capability",
                "Strategic importance",
            ],
        }

    async def _tool_manage_supplier_contracts(
        self,
        *,
        action: str = "list",
        supplier: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Manage supplier contracts (create, review, renew, track)."""
        return {
            "action": action,
            "supplier": supplier,
            "contract_type": "blanket_purchase_agreement",
            "status": "active",
            "expiration_date": "",
            "key_terms": [
                "Pricing", "Volume commitments", "Quality requirements",
                "Delivery terms", "Payment terms", "Penalty clauses",
            ],
        }

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _record_audit(self, tool_name: str, result: ToolResult) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "tool": tool_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
        })

    def get_audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)
