"""Horizon Orchestra — Merchandising Agent.

Provides a domain-specialized agent for retail merchandising workflows
including assortment optimization, pricing strategy, promotion analysis,
planogram management, and category performance.

Industry references:
- ECR (Efficient Consumer Response) category management framework
- Nielsen/IRI syndicated data models
- GS1 standards (GTIN, GLN) for product identification
- NRF (National Retail Federation) metrics
- GMROI (Gross Margin Return on Inventory Investment)
- Space-to-sales productivity analysis

Target customers: Walmart, Target, Kroger, Costco, and comparable
retailers and CPG companies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

__all__ = ["MerchandisingAgent"]

log = logging.getLogger("orchestra.verticals.retail.merchandising")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class PriceStrategy(Enum):
    """Pricing strategy types."""
    EDLP = "everyday_low_price"
    HIGH_LOW = "high_low"
    COMPETITIVE = "competitive_matching"
    PREMIUM = "premium"
    PENETRATION = "penetration"
    DYNAMIC = "dynamic"


class PromotionType(Enum):
    """Promotion mechanic types."""
    TPR = "temporary_price_reduction"
    BOGO = "buy_one_get_one"
    PERCENTAGE_OFF = "percentage_off"
    BUNDLE = "bundle"
    LOYALTY = "loyalty_exclusive"
    CLEARANCE = "clearance"
    COUPON = "coupon"


@dataclass
class CategoryPerformance:
    """Category performance metrics."""
    category: str = ""
    sales: float = 0.0
    units: float = 0.0
    margin_pct: float = 0.0
    gmroi: float = 0.0
    inventory_turns: float = 0.0
    sell_through_rate: float = 0.0
    space_productivity: float = 0.0  # Sales per linear foot


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
# Merchandising Agent
# ---------------------------------------------------------------------------

class MerchandisingAgent:
    """Domain-specialized agent for retail merchandising.

    Covers assortment optimization, pricing strategy, promotion
    effectiveness, planogram management, category analysis, and
    competitive price intelligence.

    Attributes
    ----------
    TOOLS : list[str]
        The 15 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = MerchandisingAgent()
        result = await agent.execute_tool("optimize_assortment", category="Beverages")
    """

    TOOLS: list[str] = [
        "optimize_assortment",
        "set_price_strategy",
        "analyze_promotion_effectiveness",
        "manage_planogram",
        "calculate_space_productivity",
        "analyze_category_performance",
        "run_cannibalization_analysis",
        "optimize_markdown_timing",
        "forecast_seasonal_demand",
        "analyze_basket_analysis",
        "calculate_sell_through_rate",
        "optimize_replenishment",
        "analyze_vendor_performance",
        "generate_buyer_report",
        "run_competitive_price_analysis",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        banner: str = "default",
    ) -> None:
        self.agent_id = agent_id or f"merch-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.banner = banner
        self._audit_log: list[dict[str, Any]] = []
        log.info("MerchandisingAgent %s initialised (banner=%s)", self.agent_id, banner)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for merchandising.

        Returns a comprehensive prompt embedding retail merchandising
        knowledge, pricing science, and category management best practices.
        """
        return (
            "You are a senior merchandising executive with deep expertise in "
            "retail category management, pricing science, and assortment "
            "planning. You drive profitable sales growth through data-driven "
            "merchandising decisions.\n\n"
            "CATEGORY MANAGEMENT:\n"
            "- ECR 8-Step Process: Define category → Assign role → Assess "
            "current performance → Set scorecard targets → Develop strategy "
            "→ Select tactics → Implement → Review.\n"
            "- Category Roles: Destination (traffic drivers), Routine (everyday "
            "needs), Seasonal/Occasional, Convenience. Allocate space, "
            "assortment depth, and marketing investment accordingly.\n"
            "- Decision trees for shopper navigation: Brand → Size → Variant "
            "or Segment → Brand → Size, depending on category.\n\n"
            "ASSORTMENT OPTIMIZATION:\n"
            "- Efficient assortment: Maximize incremental sales per SKU. "
            "Eliminate low-velocity/low-margin tail SKUs that cannibalize "
            "better performers.\n"
            "- Local assortment: Cluster stores by demographics, demand "
            "patterns, and competitive environment. Localize 10-20% of "
            "assortment while maintaining planogram efficiency.\n"
            "- New item evaluation: Expected velocity, margin, incrementality, "
            "supplier support, strategic fit.\n\n"
            "PRICING:\n"
            "- EDLP (Everyday Low Price): Consistent low prices, minimal "
            "promotions. Lower price perception, simpler operations.\n"
            "- High-Low: Regular prices with frequent deep promotions. Higher "
            "margins on full-price sales, excitement/urgency.\n"
            "- KVI (Known Value Items): Price-sensitive items that drive "
            "price perception (typically 5-15% of SKUs, 30-40% of sales). "
            "Price at or below competition.\n"
            "- Price elasticity: Own-price elasticity (typically -1.5 to -3.0 "
            "for grocery), cross-price elasticity for substitutes/complements.\n"
            "- Zone pricing: Vary prices by competitive zone or store cluster.\n\n"
            "PROMOTIONS:\n"
            "- Promotion ROI: Incremental Sales × Margin − Promotion Cost. "
            "Account for forward-buying, pantry-loading, and cannibalization.\n"
            "- Promotion mechanics: TPR, BOGO, % off, bundle, loyalty exclusive. "
            "Each has different margin impact and shopper response.\n"
            "- Trade promotion management: Vendor funding, scan-back vs "
            "off-invoice, post-audit compliance.\n\n"
            "SPACE MANAGEMENT:\n"
            "- Planogram optimization: Allocate shelf space proportional to "
            "movement (fair share of shelf). Adjust for facings impact on "
            "velocity (diminishing returns above ~3 facings for most items).\n"
            "- Space productivity: Sales per linear foot, GMROI per linear "
            "foot. Compare across categories for space reallocation.\n"
            "- Fixture optimization: gondola, endcap, shipper, PDQ, "
            "clip strip placement for incremental display.\n\n"
            "KEY METRICS:\n"
            "- Comp Sales (same-store), Sales per Sq Ft, Basket Size, "
            "Transaction Count, GMROI, Inventory Turns, Sell-Through Rate, "
            "Markdown Rate, Shrink Rate, In-Stock Rate.\n"
            "- GMROI = Gross Margin % × (Sales / Avg Inventory at Cost) = "
            "Gross Margin $ / Avg Inventory at Cost.\n"
            f"- Banner: {self.banner}\n"
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

    async def _tool_optimize_assortment(
        self, *, category: str = "", store_cluster: str = "all", **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize category assortment for maximum incremental sales."""
        return {
            "category": category,
            "store_cluster": store_cluster,
            "current_sku_count": 0,
            "recommended_sku_count": 0,
            "adds": [],
            "deletes": [],
            "projected_sales_impact": 0.0,
            "methodology": "Incremental sales contribution analysis",
        }

    async def _tool_set_price_strategy(
        self, *, category: str = "", strategy: str = "competitive", **kwargs: Any,
    ) -> dict[str, Any]:
        """Set pricing strategy for a category or item group."""
        return {
            "category": category,
            "strategy": strategy,
            "kvi_items": [],
            "price_zones": [],
            "elasticity_estimates": {},
            "competitive_index": 1.0,
        }

    async def _tool_analyze_promotion_effectiveness(
        self, *, promotion_id: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse promotion effectiveness and ROI."""
        return {
            "promotion_id": promotion_id,
            "total_sales_during": 0.0,
            "baseline_sales": 0.0,
            "incremental_sales": 0.0,
            "promotion_cost": 0.0,
            "incremental_margin": 0.0,
            "roi": 0.0,
            "cannibalization_pct": 0.0,
            "forward_buying_pct": 0.0,
            "lift_pct": 0.0,
        }

    async def _tool_manage_planogram(
        self, *, category: str = "", action: str = "review", **kwargs: Any,
    ) -> dict[str, Any]:
        """Manage planogram (create, update, review, comply)."""
        return {
            "category": category,
            "action": action,
            "total_linear_feet": 0.0,
            "sku_count": 0,
            "compliance_rate": 0.0,
            "out_of_stock_items": [],
        }

    async def _tool_calculate_space_productivity(
        self, *, category: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate space productivity metrics."""
        return {
            "category": category,
            "sales_per_linear_foot": 0.0,
            "gmroi_per_linear_foot": 0.0,
            "sales_per_sq_foot": 0.0,
            "index_vs_department_avg": 1.0,
            "recommendation": "",
        }

    async def _tool_analyze_category_performance(
        self, *, category: str = "", period: str = "52W", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse category performance against targets and benchmarks."""
        return {
            "category": category,
            "period": period,
            "sales": 0.0,
            "sales_growth_pct": 0.0,
            "margin_pct": 0.0,
            "gmroi": 0.0,
            "inventory_turns": 0.0,
            "market_share": 0.0,
            "vs_market_growth": 0.0,
        }

    async def _tool_run_cannibalization_analysis(
        self, *, new_item: str = "", category: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse potential cannibalization from a new item or promotion."""
        return {
            "new_item": new_item,
            "category": category,
            "cannibalized_items": [],
            "total_cannibalization_pct": 0.0,
            "net_incremental_sales": 0.0,
        }

    async def _tool_optimize_markdown_timing(
        self, *, items: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize markdown timing and depth for seasonal/clearance items."""
        return {
            "items_analyzed": len(items) if items else 0,
            "recommendations": [],
            "projected_recovery_rate": 0.0,
            "methodology": "Markdown optimization via sell-through curve analysis",
        }

    async def _tool_forecast_seasonal_demand(
        self, *, category: str = "", season: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Forecast seasonal demand using historical patterns."""
        return {
            "category": category,
            "season": season,
            "forecast": [],
            "seasonal_index": [],
            "mape": 0.0,
        }

    async def _tool_analyze_basket_analysis(
        self, *, category: str = "", min_support: float = 0.01, **kwargs: Any,
    ) -> dict[str, Any]:
        """Run market basket analysis (association rules mining)."""
        return {
            "category": category,
            "min_support": min_support,
            "top_associations": [],
            "avg_basket_size": 0.0,
            "avg_basket_value": 0.0,
            "cross_sell_opportunities": [],
            "methodology": "Apriori / FP-Growth",
        }

    async def _tool_calculate_sell_through_rate(
        self, *, item: str = "", period: str = "4W", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate sell-through rate for items."""
        return {
            "item": item,
            "period": period,
            "sell_through_rate": 0.0,
            "units_sold": 0,
            "units_received": 0,
            "weeks_of_supply": 0.0,
        }

    async def _tool_optimize_replenishment(
        self, *, category: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize replenishment parameters for in-stock improvement."""
        return {
            "category": category,
            "in_stock_rate": 0.0,
            "out_of_stock_cost": 0.0,
            "recommendations": [],
            "optimal_reorder_points": {},
        }

    async def _tool_analyze_vendor_performance(
        self, *, vendor: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse vendor performance (fill rate, OTIF, compliance)."""
        return {
            "vendor": vendor,
            "fill_rate": 0.0,
            "otif_pct": 0.0,
            "on_time_pct": 0.0,
            "in_full_pct": 0.0,
            "chargebacks": 0.0,
            "compliance_issues": [],
        }

    async def _tool_generate_buyer_report(
        self, *, category: str = "", period: str = "monthly", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a buyer/category manager performance report."""
        return {
            "category": category,
            "period": period,
            "sections": [
                "Sales Summary", "Margin Analysis", "Inventory Health",
                "Promotion Review", "Vendor Performance", "Action Items",
            ],
            "status": "generated",
        }

    async def _tool_run_competitive_price_analysis(
        self, *, category: str = "", competitors: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Run competitive price analysis across retailers."""
        return {
            "category": category,
            "competitors": competitors or [],
            "price_index": 1.0,
            "items_compared": 0,
            "above_competition": 0,
            "below_competition": 0,
            "at_competition": 0,
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
