"""Horizon Orchestra — Lease Management Agent.

Provides a domain-specialized agent for commercial lease management
workflows including lease abstracting, rent escalation calculation,
CAM reconciliation, and tenant credit analysis.

Industry references:
- ASC 842 / IFRS 16 (Lease Accounting)
- BOMA (Building Owners and Managers Association) measurement standards
- IREM (Institute of Real Estate Management) best practices
- UCC (Uniform Commercial Code) for lease provisions
- SNDA (Subordination, Non-Disturbance, and Attornment)
- Estoppel certificates
- CAM (Common Area Maintenance) reconciliation per BOMA

Target customers: CBRE, JLL, Brookfield, Prologis, and comparable
commercial real estate operators and investors.
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

__all__ = ["LeaseManagementAgent"]

log = logging.getLogger("orchestra.verticals.real_estate.lease_management")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class LeaseType(Enum):
    """Commercial lease types."""
    GROSS = "gross"
    MODIFIED_GROSS = "modified_gross"
    NNN = "triple_net"
    ABSOLUTE_NET = "absolute_net"
    PERCENTAGE = "percentage"
    GROUND = "ground"


class EscalationType(Enum):
    """Rent escalation types."""
    FIXED = "fixed"
    CPI = "cpi"
    MARKET_RESET = "market_reset"
    STEP_UP = "step_up"
    PERCENTAGE = "percentage"


@dataclass
class LeaseTerms:
    """Key lease terms."""
    tenant: str = ""
    landlord: str = ""
    premises: str = ""
    rentable_sf: float = 0.0
    usable_sf: float = 0.0
    lease_type: str = "NNN"
    commencement: str = ""
    expiration: str = ""
    base_rent_psf: float = 0.0
    escalation_type: str = "fixed"
    escalation_rate: float = 0.03
    renewal_options: int = 0
    renewal_notice_days: int = 180
    termination_option: bool = False
    ti_allowance_psf: float = 0.0
    free_rent_months: int = 0


@dataclass
class CAMReconciliation:
    """Common Area Maintenance reconciliation."""
    year: int = 0
    base_year: int = 0
    actual_cam: float = 0.0
    base_year_cam: float = 0.0
    tenant_share_pct: float = 0.0
    estimated_payments: float = 0.0
    actual_share: float = 0.0
    adjustment: float = 0.0


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
# Lease Management Agent
# ---------------------------------------------------------------------------

class LeaseManagementAgent:
    """Domain-specialized agent for commercial lease management.

    Covers lease abstracting, rent escalation modelling, critical date
    tracking, tenant credit analysis, CAM reconciliation, and lease
    administration.

    Attributes
    ----------
    TOOLS : list[str]
        The 14 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = LeaseManagementAgent()
        result = await agent.execute_tool("abstract_lease_terms", document="...")
    """

    TOOLS: list[str] = [
        "abstract_lease_terms",
        "calculate_rent_escalations",
        "track_critical_dates",
        "analyze_tenant_creditworthiness",
        "generate_lease_amendment",
        "calculate_cam_reconciliation",
        "analyze_lease_vs_buy",
        "generate_tenant_notice",
        "track_lease_expirations",
        "calculate_leasing_costs",
        "analyze_sublease_market",
        "draft_letter_of_intent",
        "generate_lease_comparison",
        "analyze_tenant_mix",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        portfolio: str = "default",
    ) -> None:
        self.agent_id = agent_id or f"lease-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.portfolio = portfolio
        self._audit_log: list[dict[str, Any]] = []
        log.info("LeaseManagementAgent %s initialised (portfolio=%s)", self.agent_id, portfolio)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for lease management.

        Returns a comprehensive prompt embedding lease administration
        knowledge, accounting standards, and commercial lease practices.
        """
        return (
            "You are a senior lease administrator with deep expertise in "
            "commercial real estate leasing, lease accounting, and tenant "
            "relations. You ensure accurate lease administration, timely "
            "billings, and compliance with ASC 842.\n\n"
            "LEASE TYPES:\n"
            "- Gross: Landlord pays all operating expenses. Rent typically "
            "higher. Common in multi-tenant office.\n"
            "- Modified Gross: Tenant pays base year + increases in specified "
            "expenses (taxes, insurance, CAM).\n"
            "- NNN (Triple Net): Tenant pays pro-rata share of taxes, "
            "insurance, and CAM in addition to base rent. Common in retail "
            "and industrial. Net effective rent = base + NNN estimates.\n"
            "- Absolute Net: Tenant responsible for ALL expenses including "
            "structural repairs and roof. Single-tenant net-lease.\n"
            "- Percentage Rent: Retail — base rent + percentage of sales "
            "above a breakpoint (natural or artificial).\n"
            "- Ground Lease: Long-term (50-99 years), tenant builds on land.\n\n"
            "RENT ESCALATIONS:\n"
            "- Fixed: Annual increase at stated percentage (e.g., 3%/year).\n"
            "- CPI-Linked: Adjusted annually by CPI increase. May have "
            "floor (min 1%) and cap (max 4%).\n"
            "- Market Reset: Rent resets to market rate at specified "
            "intervals. Appraisal or arbitration process.\n"
            "- Step-Up: Predetermined rent amounts at specific dates.\n"
            "- Compounding vs simple increase matters for long-term leases.\n\n"
            "LEASE ACCOUNTING (ASC 842 / IFRS 16):\n"
            "- Lessee: Right-of-use (ROU) asset and lease liability on "
            "balance sheet for all leases > 12 months.\n"
            "- Finance Lease: Front-loaded expense (interest + depreciation).\n"
            "- Operating Lease: Straight-line lease expense.\n"
            "- Lease modifications: Remeasure liability, adjust ROU asset.\n"
            "- Discount rate: Implicit rate or incremental borrowing rate.\n"
            "- Variable lease payments: Excluded from liability if not "
            "based on index/rate.\n\n"
            "CAM RECONCILIATION:\n"
            "- Annual reconciliation: Actual expenses vs estimated billings.\n"
            "- Controllable vs non-controllable expenses. Many leases cap "
            "controllable CAM increases (e.g., 5%/year).\n"
            "- Audit rights: Tenants typically have right to audit CAM "
            "within 90-180 days of reconciliation.\n"
            "- Gross-up: Adjust expenses for vacancy to prevent remaining "
            "tenants from bearing vacant space costs.\n"
            "- BOMA measurement standard for pro-rata share calculation.\n\n"
            "CRITICAL DATES:\n"
            "- Lease expiration, renewal option deadlines, termination "
            "option deadlines, rent commencement, escalation dates, "
            "tenant improvement deadlines, SNDA execution dates.\n"
            "- Missing critical dates can result in significant financial "
            "exposure (e.g., losing renewal option = relocation costs).\n"
            "- Track 12/6/3 months ahead with automated alerts.\n\n"
            "TENANT CREDIT:\n"
            "- Financial statements analysis: Revenue trends, profitability, "
            "liquidity (current ratio), leverage, cash flow.\n"
            "- Credit rating (S&P/Moody's) for rated tenants.\n"
            "- Altman Z-Score for bankruptcy prediction.\n"
            "- Guaranty structure: Corporate vs personal. Burn-off provisions.\n"
            "- Security deposit: Typically 1-3 months rent. Letter of credit "
            "for larger tenants.\n\n"
            "LEASING COSTS:\n"
            "- Tenant Improvements (TI): Landlord contribution for build-out. "
            "Varies by market, property type, deal size.\n"
            "- Leasing Commissions (LC): Typically 4-6% of total lease value "
            "for new leases, 2-3% for renewals.\n"
            "- Free Rent: Concession period, typically 1 month per year of "
            "term for office.\n"
            "- Net Effective Rent: Adjusts for concessions over lease term.\n"
            f"- Portfolio: {self.portfolio}\n"
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

    async def _tool_abstract_lease_terms(
        self, *, document: str = "", tenant: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Abstract key terms from a lease document."""
        return {
            "tenant": tenant,
            "abstracted_terms": {
                "premises": "",
                "rentable_sf": 0.0,
                "lease_type": "NNN",
                "commencement": "",
                "expiration": "",
                "base_rent": 0.0,
                "escalations": "",
                "renewal_options": "",
                "termination_options": "",
                "ti_allowance": 0.0,
                "free_rent": "",
                "security_deposit": 0.0,
                "permitted_use": "",
                "exclusivity": "",
                "assignment_subletting": "",
                "co_tenancy": "",
            },
            "critical_dates": [],
            "status": "abstracted",
            "requires_review": True,
        }

    async def _tool_calculate_rent_escalations(
        self, *, base_rent: float = 0.0, escalation_type: str = "fixed",
        rate: float = 0.03, term_years: int = 10, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate rent escalation schedule over the lease term."""
        schedule = []
        rent = base_rent
        for yr in range(1, term_years + 1):
            if yr > 1:
                rent = rent * (1 + rate)
            schedule.append({
                "year": yr,
                "annual_rent": round(rent, 2),
                "monthly_rent": round(rent / 12, 2),
            })

        total_rent = sum(s["annual_rent"] for s in schedule)
        return {
            "escalation_type": escalation_type,
            "rate": rate,
            "term_years": term_years,
            "schedule": schedule,
            "total_lease_value": round(total_rent, 2),
            "avg_annual_rent": round(total_rent / term_years, 2),
        }

    async def _tool_track_critical_dates(
        self, *, property_id: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Track critical lease dates across a portfolio."""
        return {
            "property_id": property_id,
            "portfolio": self.portfolio,
            "upcoming_dates": [],
            "overdue_actions": [],
            "alert_thresholds": {"12_months": 0, "6_months": 0, "3_months": 0},
        }

    async def _tool_analyze_tenant_creditworthiness(
        self, *, tenant: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse tenant creditworthiness for leasing decisions."""
        return {
            "tenant": tenant,
            "credit_rating": "",
            "altman_z_score": 0.0,
            "financial_metrics": {
                "revenue": 0.0,
                "net_income": 0.0,
                "current_ratio": 0.0,
                "debt_to_equity": 0.0,
            },
            "risk_level": "moderate",
            "security_requirement": "Letter of Credit recommended",
        }

    async def _tool_generate_lease_amendment(
        self, *, tenant: str = "", amendment_type: str = "rent_adjustment", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a lease amendment document."""
        return {
            "tenant": tenant,
            "amendment_type": amendment_type,
            "amendment_number": 1,
            "effective_date": "",
            "modified_terms": [],
            "status": "draft",
            "requires_legal_review": True,
        }

    async def _tool_calculate_cam_reconciliation(
        self, *, year: int = 0, actual_cam: float = 0.0, estimated_billings: float = 0.0,
        tenant_share_pct: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate CAM reconciliation for a tenant."""
        actual_share = actual_cam * tenant_share_pct
        adjustment = actual_share - estimated_billings
        return {
            "year": year,
            "actual_total_cam": actual_cam,
            "tenant_share_pct": tenant_share_pct,
            "tenant_actual_share": round(actual_share, 2),
            "estimated_billings": estimated_billings,
            "adjustment": round(adjustment, 2),
            "adjustment_type": "charge" if adjustment > 0 else "credit",
            "cam_cap_applied": False,
            "gross_up_applied": False,
            "reference": "BOMA Standard; Lease Section [X]",
        }

    async def _tool_analyze_lease_vs_buy(
        self, *, annual_lease_cost: float = 0.0, purchase_price: float = 0.0,
        holding_period: int = 10, **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse lease vs buy decision for corporate occupiers."""
        return {
            "annual_lease_cost": annual_lease_cost,
            "purchase_price": purchase_price,
            "holding_period": holding_period,
            "npv_lease": 0.0,
            "npv_own": 0.0,
            "recommendation": "lease" if annual_lease_cost * holding_period < purchase_price else "buy",
            "factors": [
                "Capital allocation", "Flexibility", "Tax treatment (ASC 842)",
                "Maintenance responsibility", "Appreciation potential",
            ],
        }

    async def _tool_generate_tenant_notice(
        self, *, tenant: str = "", notice_type: str = "rent_increase", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a formal tenant notice."""
        return {
            "tenant": tenant,
            "notice_type": notice_type,
            "effective_date": "",
            "delivery_method": "certified_mail",
            "status": "draft",
            "requires_legal_review": True,
        }

    async def _tool_track_lease_expirations(
        self, *, horizon_months: int = 24, **kwargs: Any,
    ) -> dict[str, Any]:
        """Track lease expirations across the portfolio."""
        return {
            "portfolio": self.portfolio,
            "horizon_months": horizon_months,
            "expirations": [],
            "total_expiring_sf": 0.0,
            "total_expiring_rent": 0.0,
            "retention_strategy": [],
        }

    async def _tool_calculate_leasing_costs(
        self, *, deal_size_sf: float = 0.0, term_years: int = 10,
        base_rent_psf: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate total leasing costs (TI, LC, free rent)."""
        total_lease_value = deal_size_sf * base_rent_psf * term_years
        return {
            "deal_size_sf": deal_size_sf,
            "term_years": term_years,
            "total_lease_value": round(total_lease_value, 2),
            "estimated_ti_psf": 0.0,
            "total_ti": 0.0,
            "commission_pct": 0.05,
            "total_commission": round(total_lease_value * 0.05, 2),
            "free_rent_months": 0,
            "free_rent_cost": 0.0,
            "total_leasing_cost": 0.0,
            "net_effective_rent_psf": 0.0,
        }

    async def _tool_analyze_sublease_market(
        self, *, market: str = "", property_type: str = "office", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse the sublease market in a given area."""
        return {
            "market": market,
            "property_type": property_type,
            "sublease_availability_sf": 0.0,
            "sublease_pct_of_total": 0.0,
            "avg_sublease_discount": 0.0,
            "trend": "stable",
        }

    async def _tool_draft_letter_of_intent(
        self, *, tenant: str = "", property_name: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Draft a Letter of Intent (LOI) for a lease transaction."""
        return {
            "tenant": tenant,
            "property_name": property_name,
            "loi_terms": {
                "premises": "",
                "term": "",
                "base_rent": "",
                "escalations": "",
                "ti_allowance": "",
                "free_rent": "",
                "commencement": "",
                "permitted_use": "",
            },
            "non_binding": True,
            "status": "draft",
        }

    async def _tool_generate_lease_comparison(
        self, *, proposals: list[dict[str, Any]] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a side-by-side lease proposal comparison."""
        return {
            "proposals_compared": len(proposals) if proposals else 0,
            "comparison_metrics": [
                "Net Effective Rent", "Total Occupancy Cost", "TI Allowance",
                "Free Rent", "Term", "Escalations", "Renewal Options",
            ],
            "ranking": [],
            "recommendation": "",
        }

    async def _tool_analyze_tenant_mix(
        self, *, property_id: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse tenant mix for diversification and risk."""
        return {
            "property_id": property_id,
            "tenant_count": 0,
            "industry_concentration": {},
            "credit_quality_distribution": {},
            "largest_tenant_pct": 0.0,
            "walt_years": 0.0,
            "risk_score": 0.0,
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
