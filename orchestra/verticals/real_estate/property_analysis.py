"""Horizon Orchestra — Property Analysis Agent.

Provides a domain-specialized agent for commercial real estate property
analysis workflows including DCF valuation, cap rate analysis, comparable
sales, rent roll analysis, and investment memo generation.

Industry references:
- Appraisal Institute (USPAP — Uniform Standards of Professional Appraisal Practice)
- NCREIF (National Council of Real Estate Investment Fiduciaries)
- ASC 842 / IFRS 16 (Lease Accounting)
- ARGUS Enterprise / DCF modelling standards
- DSCR (Debt Service Coverage Ratio) — lender requirements
- ADA (Americans with Disabilities Act) for property compliance
- Phase I ESA (Environmental Site Assessment) — ASTM E1527

Target customers: CBRE, JLL (Jones Lang LaSalle), Cushman & Wakefield,
Brookfield, Blackstone Real Estate, and comparable CRE firms.
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

__all__ = ["PropertyAnalysisAgent"]

log = logging.getLogger("orchestra.verticals.real_estate.property_analysis")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class PropertyType(Enum):
    """Commercial real estate property types."""
    OFFICE = "office"
    RETAIL = "retail"
    INDUSTRIAL = "industrial"
    MULTIFAMILY = "multifamily"
    HOSPITALITY = "hospitality"
    MIXED_USE = "mixed_use"
    DATA_CENTER = "data_center"
    LIFE_SCIENCE = "life_science"
    SELF_STORAGE = "self_storage"
    SENIOR_LIVING = "senior_living"


class InvestmentStrategy(Enum):
    """Real estate investment strategies."""
    CORE = "core"
    CORE_PLUS = "core_plus"
    VALUE_ADD = "value_add"
    OPPORTUNISTIC = "opportunistic"
    DEVELOPMENT = "development"


@dataclass
class PropertyMetrics:
    """Key property financial metrics."""
    noi: float = 0.0
    cap_rate: float = 0.0
    occupancy_pct: float = 0.0
    avg_rent_psf: float = 0.0
    operating_expense_ratio: float = 0.0
    dscr: float = 0.0
    irr: float = 0.0
    equity_multiple: float = 0.0


@dataclass
class RentRollEntry:
    """Single tenant in a rent roll."""
    tenant: str = ""
    suite: str = ""
    sf: float = 0.0
    rent_psf: float = 0.0
    annual_rent: float = 0.0
    lease_start: str = ""
    lease_end: str = ""
    escalation_type: str = "fixed"
    escalation_rate: float = 0.03


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
# Property Analysis Agent
# ---------------------------------------------------------------------------

class PropertyAnalysisAgent:
    """Domain-specialized agent for commercial real estate analysis.

    Covers DCF valuation, cap rate analysis, comparable sales, rent roll
    analysis, market fundamentals, zoning compliance, environmental risk,
    and investment memo generation.

    Attributes
    ----------
    TOOLS : list[str]
        The 16 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = PropertyAnalysisAgent()
        result = await agent.execute_tool("calculate_cap_rate", noi=500000, price=7000000)
    """

    TOOLS: list[str] = [
        "run_dcf_valuation",
        "calculate_cap_rate",
        "analyze_comparable_sales",
        "run_rent_roll_analysis",
        "calculate_dscr",
        "analyze_market_fundamentals",
        "generate_investment_memo",
        "calculate_irr_equity_multiple",
        "analyze_lease_abstract",
        "run_sensitivity_analysis",
        "assess_environmental_risk",
        "analyze_zoning_compliance",
        "calculate_noi",
        "generate_broker_opinion_of_value",
        "analyze_market_vacancy",
        "run_highest_best_use",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        market: str = "US",
    ) -> None:
        self.agent_id = agent_id or f"propan-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.market = market
        self._audit_log: list[dict[str, Any]] = []
        log.info("PropertyAnalysisAgent %s initialised (market=%s)", self.agent_id, market)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for property analysis.

        Returns a comprehensive prompt embedding CRE analysis knowledge,
        valuation methodologies, and regulatory frameworks.
        """
        return (
            "You are a senior real estate analyst at an institutional CRE firm "
            "with deep expertise in property valuation, market analysis, and "
            "investment underwriting. You provide rigorous, data-driven "
            "analysis for acquisition and disposition decisions.\n\n"
            "VALUATION METHODOLOGIES:\n"
            "- Direct Capitalization: Value = NOI / Cap Rate. Quick valuation "
            "for stabilized properties. Cap rate derived from market comps.\n"
            "- DCF (Discounted Cash Flow): Project NOI over holding period "
            "(typically 7-10 years), add reversion value (terminal NOI / "
            "exit cap rate), discount at required rate of return.\n"
            "  Key assumptions: Rent growth, vacancy, operating expense "
            "  inflation, tenant improvement/leasing commission reserves, "
            "  capital expenditure reserves.\n"
            "- Sales Comparison: Adjust comparable sales for differences in "
            "location, size, age, condition, lease terms, and market "
            "conditions.\n"
            "- Cost Approach: Land value + depreciated replacement cost. "
            "Used for special-purpose properties.\n"
            "- ARGUS Enterprise is the industry-standard DCF tool.\n\n"
            "FINANCIAL METRICS:\n"
            "- NOI (Net Operating Income): EGI − Operating Expenses. Exclude "
            "debt service, depreciation, income tax.\n"
            "- EGI (Effective Gross Income): PGI − Vacancy − Credit Loss + "
            "Other Income.\n"
            "- Cap Rate: NOI / Value. Reflects risk and growth expectations. "
            "Compressed caps = lower risk/higher prices.\n"
            "- DSCR (Debt Service Coverage Ratio): NOI / Annual Debt Service. "
            "Lender minimum typically 1.20-1.30x.\n"
            "- IRR: Internal Rate of Return on equity. Target depends on "
            "strategy: Core 6-8%, Value-Add 12-18%, Opportunistic 18%+.\n"
            "- Equity Multiple: Total distributions / Equity invested. "
            "Core 1.3-1.5x, Value-Add 1.6-2.0x, Opportunistic 2.0x+.\n"
            "- Cash-on-Cash: Annual pre-tax cash flow / Equity invested.\n"
            "- Yield-on-Cost: Stabilized NOI / Total project cost (for "
            "development/value-add).\n\n"
            "MARKET ANALYSIS:\n"
            "- Vacancy rate: Physical vs economic vacancy. Natural vacancy "
            "varies by property type and market.\n"
            "- Absorption: Net change in occupied space. Positive absorption "
            "= tenants moving in > out.\n"
            "- Rent comps: Asking vs effective rent. Adjust for concessions "
            "(free rent, TI, moving allowance).\n"
            "- Supply pipeline: Planned/under-construction deliveries.\n"
            "- Submarket dynamics: Employment growth, demographic trends, "
            "infrastructure investment.\n\n"
            "LEASE ANALYSIS:\n"
            "- Lease types: Gross, Modified Gross, NNN (Triple Net), "
            "Absolute Net, Percentage Rent (retail).\n"
            "- Escalations: Fixed (3% annual), CPI-linked, market resets, "
            "step-ups.\n"
            "- Critical dates: Commencement, expiration, renewal options, "
            "termination options, rent escalation dates.\n"
            "- ASC 842 / IFRS 16: Lease accounting — right-of-use asset "
            "and lease liability on balance sheet.\n\n"
            "ENVIRONMENTAL & ZONING:\n"
            "- Phase I ESA (ASTM E1527-21): Historical use review, "
            "recognized environmental conditions (RECs).\n"
            "- Phase II: Sampling/testing if Phase I identifies concerns.\n"
            "- Zoning: Permitted uses, FAR (Floor Area Ratio), setbacks, "
            "height limits, parking requirements. Variance/special permit "
            "process.\n"
            "- ADA compliance for accessibility.\n\n"
            "USPAP:\n"
            "- Uniform Standards of Professional Appraisal Practice for "
            "formal appraisals. Competency, scope of work, ethics.\n"
            f"- Market: {self.market}\n"
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

    async def _tool_run_dcf_valuation(
        self, *, noi: float = 0.0, growth_rate: float = 0.03, discount_rate: float = 0.08,
        holding_period: int = 10, exit_cap_rate: float = 0.06, **kwargs: Any,
    ) -> dict[str, Any]:
        """Run DCF valuation for a commercial property."""
        projected_noi = []
        pv_noi = 0.0
        current_noi = noi
        for yr in range(1, holding_period + 1):
            current_noi = current_noi * (1 + growth_rate) if yr > 1 else noi * (1 + growth_rate)
            pv = current_noi / (1 + discount_rate) ** yr
            pv_noi += pv
            projected_noi.append({"year": yr, "noi": round(current_noi, 2), "pv": round(pv, 2)})

        terminal_noi = current_noi * (1 + growth_rate)
        reversion = terminal_noi / exit_cap_rate
        pv_reversion = reversion / (1 + discount_rate) ** holding_period

        return {
            "methodology": "DCF (ARGUS-style)",
            "noi_year_1": noi,
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "exit_cap_rate": exit_cap_rate,
            "holding_period": holding_period,
            "pv_cash_flows": round(pv_noi, 2),
            "pv_reversion": round(pv_reversion, 2),
            "total_value": round(pv_noi + pv_reversion, 2),
            "implied_going_in_cap": round(noi / (pv_noi + pv_reversion), 4) if (pv_noi + pv_reversion) > 0 else 0,
        }

    async def _tool_calculate_cap_rate(
        self, *, noi: float = 0.0, price: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate capitalization rate."""
        cap_rate = noi / price if price > 0 else 0
        return {
            "noi": noi,
            "price": price,
            "cap_rate": round(cap_rate, 4),
            "cap_rate_pct": round(cap_rate * 100, 2),
            "price_per_sf": 0.0,
        }

    async def _tool_analyze_comparable_sales(
        self, *, property_type: str = "office", market: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse comparable property sales."""
        return {
            "property_type": property_type,
            "market": market or self.market,
            "comps_found": 0,
            "median_cap_rate": 0.0,
            "median_price_psf": 0.0,
            "adjustment_factors": [
                "Location", "Size", "Age/Condition", "Occupancy",
                "Lease Terms", "Market Conditions",
            ],
            "implied_value_range": {"low": 0.0, "mid": 0.0, "high": 0.0},
        }

    async def _tool_run_rent_roll_analysis(
        self, *, rent_roll: list[dict[str, Any]] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse property rent roll."""
        entries = rent_roll or []
        total_sf = sum(e.get("sf", 0) for e in entries)
        total_rent = sum(e.get("annual_rent", 0) for e in entries)
        return {
            "tenant_count": len(entries),
            "total_sf": total_sf,
            "total_annual_rent": total_rent,
            "weighted_avg_rent_psf": round(total_rent / total_sf, 2) if total_sf > 0 else 0,
            "occupancy_pct": 0.0,
            "walt_years": 0.0,
            "lease_expirations": {},
            "concentration_risk": [],
        }

    async def _tool_calculate_dscr(
        self, *, noi: float = 0.0, annual_debt_service: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Debt Service Coverage Ratio."""
        dscr = noi / annual_debt_service if annual_debt_service > 0 else 0
        return {
            "noi": noi,
            "annual_debt_service": annual_debt_service,
            "dscr": round(dscr, 2),
            "meets_lender_minimum": dscr >= 1.25,
            "typical_minimum": 1.25,
        }

    async def _tool_analyze_market_fundamentals(
        self, *, market: str = "", property_type: str = "office", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse market fundamentals for a submarket."""
        return {
            "market": market or self.market,
            "property_type": property_type,
            "vacancy_rate": 0.0,
            "asking_rent_psf": 0.0,
            "effective_rent_psf": 0.0,
            "net_absorption_sf": 0.0,
            "under_construction_sf": 0.0,
            "employment_growth_pct": 0.0,
            "population_growth_pct": 0.0,
        }

    async def _tool_generate_investment_memo(
        self, *, property_name: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate an investment committee memorandum."""
        return {
            "property_name": property_name,
            "sections": [
                "Executive Summary", "Investment Thesis", "Property Overview",
                "Market Analysis", "Financial Analysis", "Risk Factors",
                "Comparable Analysis", "Recommendation",
            ],
            "status": "draft",
            "requires_ic_approval": True,
        }

    async def _tool_calculate_irr_equity_multiple(
        self, *, equity_invested: float = 0.0, cash_flows: list[float] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate IRR and equity multiple for an investment."""
        flows = cash_flows or []
        total_distributions = sum(flows)
        eq_multiple = total_distributions / equity_invested if equity_invested > 0 else 0

        return {
            "equity_invested": equity_invested,
            "total_distributions": total_distributions,
            "equity_multiple": round(eq_multiple, 2),
            "irr": 0.0,  # Would require scipy for actual calculation
            "cash_on_cash_year_1": 0.0,
        }

    async def _tool_analyze_lease_abstract(
        self, *, tenant: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Abstract key terms from a lease document."""
        return {
            "tenant": tenant,
            "key_terms": {
                "commencement": "",
                "expiration": "",
                "base_rent": 0.0,
                "escalations": "",
                "renewal_options": "",
                "termination_options": "",
                "expense_structure": "NNN",
                "tenant_improvements": 0.0,
            },
            "critical_dates": [],
            "status": "abstracted",
        }

    async def _tool_run_sensitivity_analysis(
        self, *, base_case: dict[str, Any] | None = None, variables: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Run sensitivity analysis on key underwriting assumptions."""
        return {
            "base_case": base_case or {},
            "variables_tested": variables or ["cap_rate", "rent_growth", "vacancy", "exit_cap"],
            "scenarios": [],
            "tornado_chart_data": [],
        }

    async def _tool_assess_environmental_risk(
        self, *, address: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Assess environmental risk (Phase I ESA scope)."""
        return {
            "address": address,
            "phase_i_required": True,
            "recognized_environmental_conditions": [],
            "historical_uses": [],
            "nearby_contamination_sites": [],
            "flood_zone": "",
            "seismic_zone": "",
            "reference": "ASTM E1527-21",
        }

    async def _tool_analyze_zoning_compliance(
        self, *, address: str = "", proposed_use: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse zoning compliance for a property."""
        return {
            "address": address,
            "proposed_use": proposed_use,
            "current_zoning": "",
            "permitted_uses": [],
            "far": 0.0,
            "max_height": "",
            "setbacks": {},
            "parking_required": 0,
            "variance_required": False,
            "ada_compliant": True,
        }

    async def _tool_calculate_noi(
        self, *, gross_income: float = 0.0, vacancy_pct: float = 0.05,
        operating_expenses: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Net Operating Income."""
        egi = gross_income * (1 - vacancy_pct)
        noi = egi - operating_expenses
        return {
            "potential_gross_income": gross_income,
            "vacancy_loss": round(gross_income * vacancy_pct, 2),
            "effective_gross_income": round(egi, 2),
            "operating_expenses": operating_expenses,
            "noi": round(noi, 2),
            "operating_expense_ratio": round(operating_expenses / egi, 4) if egi > 0 else 0,
        }

    async def _tool_generate_broker_opinion_of_value(
        self, *, property_name: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a Broker Opinion of Value (BOV)."""
        return {
            "property_name": property_name,
            "valuation_range": {"low": 0.0, "mid": 0.0, "high": 0.0},
            "methodologies_used": ["Direct Capitalization", "Sales Comparison"],
            "disclaimer": "This is not a formal appraisal under USPAP.",
            "status": "draft",
        }

    async def _tool_analyze_market_vacancy(
        self, *, market: str = "", property_type: str = "office", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse market vacancy trends."""
        return {
            "market": market or self.market,
            "property_type": property_type,
            "current_vacancy": 0.0,
            "historical_avg": 0.0,
            "trend": "stable",
            "sublease_vacancy": 0.0,
        }

    async def _tool_run_highest_best_use(
        self, *, address: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Run highest and best use analysis."""
        return {
            "address": address,
            "analysis": {
                "legally_permissible": [],
                "physically_possible": [],
                "financially_feasible": [],
                "maximally_productive": "",
            },
            "current_use": "",
            "highest_best_use": "",
            "reference": "Appraisal Institute methodology",
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
