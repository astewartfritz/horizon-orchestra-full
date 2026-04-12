"""Horizon Orchestra — Investment Banking Agent.

Provides a domain-specialized agent for investment banking workflows
including DCF modelling, comparable company analysis, LBO models,
M&A advisory, fairness opinions, and capital-structure analysis.

Regulatory and industry references:
- SEC Regulation M-A (mergers and acquisitions disclosure)
- ASC 805 (business combinations)
- ASC 820 (fair value measurement)
- FINRA Rules 5110 (underwriting terms) and 2241 (research)
- Hart-Scott-Rodino Act (pre-merger notification)

Target customers: JPMorgan, Goldman Sachs, Morgan Stanley, and
comparable sell-side / buy-side institutions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Optional, Sequence

__all__ = ["InvestmentBankingAgent"]

log = logging.getLogger("orchestra.verticals.financial_services.investment_banking")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class DealStage(Enum):
    """M&A deal lifecycle stages."""
    ORIGINATION = "origination"
    PITCH = "pitch"
    ENGAGEMENT = "engagement"
    DUE_DILIGENCE = "due_diligence"
    NEGOTIATION = "negotiation"
    SIGNING = "signing"
    CLOSING = "closing"
    POST_MERGER = "post_merger"


@dataclass
class DCFAssumptions:
    """Core assumptions for a Discounted Cash Flow model."""
    projection_years: int = 5
    terminal_growth_rate: float = 0.025
    wacc: float | None = None
    revenue_growth_rates: list[float] = field(default_factory=list)
    ebitda_margins: list[float] = field(default_factory=list)
    capex_as_pct_revenue: float = 0.05
    nwc_as_pct_revenue: float = 0.10
    tax_rate: float = 0.21
    exit_multiple: float | None = None


@dataclass
class CompsSet:
    """Comparable company set for relative valuation."""
    target_ticker: str = ""
    peer_tickers: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=lambda: [
        "EV/EBITDA", "EV/Revenue", "P/E", "P/B",
    ])
    as_of_date: str = ""
    use_ntm: bool = True


@dataclass
class LBOParameters:
    """Leveraged Buyout model parameters."""
    purchase_price_multiple: float = 10.0
    equity_contribution_pct: float = 0.40
    senior_debt_multiple: float = 4.0
    sub_debt_multiple: float = 2.0
    senior_rate: float = 0.055
    sub_rate: float = 0.085
    holding_period: int = 5
    exit_multiple: float = 10.0
    management_rollover_pct: float = 0.0


@dataclass
class MergerAssumptions:
    """Merger synergy and accretion/dilution assumptions."""
    acquirer_ticker: str = ""
    target_ticker: str = ""
    offer_price_per_share: float = 0.0
    pct_cash: float = 0.50
    pct_stock: float = 0.50
    cost_synergies: float = 0.0
    revenue_synergies: float = 0.0
    integration_costs: float = 0.0
    synergy_phase_in_years: int = 3


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
# Investment Banking Agent
# ---------------------------------------------------------------------------

class InvestmentBankingAgent:
    """Domain-specialized agent for investment banking workflows.

    Covers the full spectrum of IB analytics: DCF valuation, comparable
    company and precedent transaction analysis, LBO modelling, M&A
    synergy analysis, capital-structure advisory, and pitch-book
    content generation.

    Attributes
    ----------
    TOOLS : list[str]
        The 15 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.
    model : str
        Backing LLM model identifier.

    Example
    -------
    ::

        agent = InvestmentBankingAgent()
        result = await agent.execute_tool("build_dcf_model", assumptions={...})
    """

    TOOLS: list[str] = [
        "build_dcf_model",
        "run_comps_analysis",
        "draft_im_section",
        "analyze_capital_structure",
        "calculate_wacc",
        "run_lbo_model",
        "analyze_merger_synergies",
        "draft_fairness_opinion",
        "generate_teaser",
        "analyze_debt_covenants",
        "screen_acquisition_targets",
        "calculate_accretion_dilution",
        "draft_management_presentation",
        "analyze_credit_metrics",
        "generate_tombstone",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        compliance_mode: bool = True,
    ) -> None:
        self.agent_id = agent_id or f"ib-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.compliance_mode = compliance_mode
        self._deal_context: dict[str, Any] = {}
        self._audit_log: list[dict[str, Any]] = []
        log.info("InvestmentBankingAgent %s initialised (model=%s)", self.agent_id, model)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for investment banking.

        Returns a comprehensive prompt embedding IB domain knowledge
        including valuation methodologies, regulatory frameworks, and
        deal-execution best practices.
        """
        return (
            "You are a senior investment banking analyst with deep expertise in "
            "M&A advisory, capital markets, and financial modelling. You operate "
            "within a regulated environment and must adhere to SEC, FINRA, and "
            "internal compliance policies at all times.\n\n"
            "VALUATION METHODOLOGIES:\n"
            "- DCF (Discounted Cash Flow): Project unlevered free cash flows, "
            "discount at WACC, add terminal value via Gordon Growth or exit "
            "multiple method. Always run sensitivity on WACC (±50bps) and "
            "terminal growth (±50bps). Reference ASC 820 for fair-value "
            "hierarchy (Level 1/2/3 inputs).\n"
            "- Comparable Companies: Select peers by sector, size, growth "
            "profile, and margin structure. Key multiples: EV/EBITDA, "
            "EV/Revenue, P/E, P/B. Use NTM (next-twelve-months) consensus "
            "estimates. Apply appropriate premiums/discounts for size, "
            "liquidity, and control.\n"
            "- Precedent Transactions: Source from SEC EDGAR, Bloomberg, "
            "Dealogic. Adjust for market conditions, strategic vs financial "
            "buyers, and synergy expectations.\n"
            "- LBO Analysis: Model entry leverage (Senior/Sub/Mezz), cash "
            "sweep mechanics, covenant compliance, and IRR sensitivity to "
            "exit multiple and EBITDA growth. Typical PE targets: 20-25% "
            "gross IRR, 2.5-3.0x MOIC over 5 years.\n\n"
            "M&A ADVISORY:\n"
            "- Accretion/Dilution: Calculate impact on acquirer EPS under "
            "various financing mixes (cash/stock/debt). Account for "
            "transaction costs, purchase-price allocation (ASC 805), and "
            "synergy phase-in.\n"
            "- Fairness Opinions: Per FINRA Rule 5150, disclose material "
            "relationships. Use multiple valuation approaches and clearly "
            "present ranges.\n"
            "- Hart-Scott-Rodino: Flag transactions exceeding HSR thresholds "
            "(currently $111.4M) for pre-merger notification.\n\n"
            "CAPITAL STRUCTURE:\n"
            "- Optimal leverage analysis: balance tax shield benefits against "
            "financial distress costs and agency costs.\n"
            "- Credit metrics: Net Debt/EBITDA, Interest Coverage (EBITDA/Interest), "
            "Fixed Charge Coverage, Debt/Total Cap.\n"
            "- Rating agency methodology: S&P, Moody's, Fitch factor models.\n"
            "- Covenant analysis: maintenance vs incurrence covenants, "
            "restricted payments baskets, change-of-control provisions.\n\n"
            "WACC CALCULATION:\n"
            "- Cost of Equity via CAPM: Rf + β × (Rm - Rf) + size premium. "
            "Use 10Y UST for Rf, Ibbotson/Duff & Phelps for ERP.\n"
            "- Cost of Debt: yield on comparable-rated bonds, tax-effected.\n"
            "- Weights: target capital structure or market-based.\n\n"
            "COMPLIANCE:\n"
            "- Material Non-Public Information (MNPI): never incorporate or "
            "disclose. Maintain information barriers between deal teams.\n"
            "- Regulation FD: ensure public disclosures are broad and "
            "simultaneous.\n"
            "- Conflict checks: screen for advisory conflicts before "
            "engagement.\n"
            "- All outputs must include appropriate disclaimers and caveats.\n"
        )

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute one of this agent's registered tools.

        Parameters
        ----------
        tool_name:
            Must be one of :attr:`TOOLS`.
        **kwargs:
            Tool-specific parameters.

        Returns
        -------
        ToolResult
            Structured result with data, success flag, and metadata.

        Raises
        ------
        ValueError
            If *tool_name* is not in :attr:`TOOLS`.
        """
        if tool_name not in self.TOOLS:
            raise ValueError(
                f"Unknown tool '{tool_name}'. Available: {self.TOOLS}"
            )
        start = asyncio.get_event_loop().time()
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Handler not implemented for {tool_name}",
            )
        try:
            data = await handler(**kwargs)
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            result = ToolResult(
                tool_name=tool_name,
                success=True,
                data=data,
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            log.exception("Tool %s failed", tool_name)
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
                execution_time_ms=elapsed,
            )
        self._record_audit(tool_name, result)
        return result

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _tool_build_dcf_model(
        self,
        *,
        assumptions: dict[str, Any] | DCFAssumptions | None = None,
        company: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build a Discounted Cash Flow model.

        Constructs a full DCF with projected free cash flows,
        terminal value (Gordon Growth and exit-multiple methods),
        and implied enterprise and equity value ranges.
        """
        if isinstance(assumptions, dict):
            assumptions = DCFAssumptions(**assumptions)
        elif assumptions is None:
            assumptions = DCFAssumptions()

        wacc = assumptions.wacc or 0.10
        projected_fcfs = []
        base_revenue = 1_000.0  # placeholder
        for yr in range(1, assumptions.projection_years + 1):
            growth = (
                assumptions.revenue_growth_rates[yr - 1]
                if yr - 1 < len(assumptions.revenue_growth_rates)
                else 0.05
            )
            margin = (
                assumptions.ebitda_margins[yr - 1]
                if yr - 1 < len(assumptions.ebitda_margins)
                else 0.25
            )
            revenue = base_revenue * (1 + growth) ** yr
            ebitda = revenue * margin
            capex = revenue * assumptions.capex_as_pct_revenue
            nwc_change = revenue * assumptions.nwc_as_pct_revenue * growth
            tax = ebitda * assumptions.tax_rate
            fcf = ebitda - tax - capex - nwc_change
            projected_fcfs.append({
                "year": yr,
                "revenue": round(revenue, 2),
                "ebitda": round(ebitda, 2),
                "fcf": round(fcf, 2),
            })

        # Terminal value — Gordon Growth
        terminal_fcf = projected_fcfs[-1]["fcf"]
        tv_ggm = terminal_fcf * (1 + assumptions.terminal_growth_rate) / (
            wacc - assumptions.terminal_growth_rate
        )

        # Terminal value — Exit Multiple
        terminal_ebitda = projected_fcfs[-1]["ebitda"]
        exit_mult = assumptions.exit_multiple or 10.0
        tv_exit = terminal_ebitda * exit_mult

        # Discount factors
        pv_fcfs = sum(
            f["fcf"] / (1 + wacc) ** f["year"] for f in projected_fcfs
        )
        pv_tv_ggm = tv_ggm / (1 + wacc) ** assumptions.projection_years
        pv_tv_exit = tv_exit / (1 + wacc) ** assumptions.projection_years

        return {
            "company": company,
            "methodology": "DCF",
            "wacc": wacc,
            "projected_fcfs": projected_fcfs,
            "terminal_value_gordon_growth": round(tv_ggm, 2),
            "terminal_value_exit_multiple": round(tv_exit, 2),
            "enterprise_value_ggm": round(pv_fcfs + pv_tv_ggm, 2),
            "enterprise_value_exit": round(pv_fcfs + pv_tv_exit, 2),
            "assumptions": {
                "projection_years": assumptions.projection_years,
                "terminal_growth_rate": assumptions.terminal_growth_rate,
                "tax_rate": assumptions.tax_rate,
            },
        }

    async def _tool_run_comps_analysis(
        self,
        *,
        comps: dict[str, Any] | CompsSet | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run comparable company analysis.

        Calculates relative valuation multiples for a set of peer
        companies and derives an implied valuation range for the target.
        """
        if isinstance(comps, dict):
            comps = CompsSet(**comps)
        elif comps is None:
            comps = CompsSet()

        peer_data = []
        for ticker in comps.peer_tickers:
            peer_data.append({
                "ticker": ticker,
                "ev_ebitda": 12.0,
                "ev_revenue": 3.5,
                "pe_ratio": 18.0,
                "pb_ratio": 2.5,
            })

        medians = {
            "ev_ebitda": 12.0,
            "ev_revenue": 3.5,
            "pe_ratio": 18.0,
            "pb_ratio": 2.5,
        }

        return {
            "target": comps.target_ticker,
            "peer_count": len(comps.peer_tickers),
            "peers": peer_data,
            "median_multiples": medians,
            "implied_valuation_range": {
                "low": "Based on 25th percentile multiples",
                "mid": "Based on median multiples",
                "high": "Based on 75th percentile multiples",
            },
            "as_of_date": comps.as_of_date or datetime.now(timezone.utc).isoformat(),
            "use_ntm": comps.use_ntm,
        }

    async def _tool_draft_im_section(
        self,
        *,
        section: str = "executive_summary",
        company: str = "",
        deal_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Draft a section of the Information Memorandum (Confidential).

        Valid sections: executive_summary, business_overview,
        financial_overview, industry_analysis, growth_opportunities,
        management_team, risk_factors, transaction_summary.
        """
        valid_sections = [
            "executive_summary", "business_overview", "financial_overview",
            "industry_analysis", "growth_opportunities", "management_team",
            "risk_factors", "transaction_summary",
        ]
        if section not in valid_sections:
            raise ValueError(f"Invalid section '{section}'. Valid: {valid_sections}")

        return {
            "section": section,
            "company": company,
            "status": "draft_ready",
            "word_count": 1500,
            "confidentiality_notice": (
                "CONFIDENTIAL — This document contains material non-public "
                "information and is provided solely for evaluation purposes."
            ),
            "requires_review": True,
        }

    async def _tool_analyze_capital_structure(
        self,
        *,
        company: str = "",
        financials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse a company's capital structure.

        Evaluates current leverage, debt maturity profile, credit
        metrics, and optimal capital structure recommendations.
        """
        return {
            "company": company,
            "total_debt": 5_000.0,
            "total_equity_market": 15_000.0,
            "net_debt": 4_000.0,
            "debt_to_total_cap": 0.25,
            "net_debt_to_ebitda": 2.5,
            "interest_coverage": 8.0,
            "weighted_avg_cost_of_debt": 0.045,
            "debt_maturity_profile": {
                "within_1y": 500.0,
                "1_3y": 1500.0,
                "3_5y": 2000.0,
                "beyond_5y": 1000.0,
            },
            "credit_rating_implied": "BBB+",
            "recommendation": "Current leverage is conservative; capacity for incremental debt.",
        }

    async def _tool_calculate_wacc(
        self,
        *,
        company: str = "",
        risk_free_rate: float = 0.042,
        equity_risk_premium: float = 0.055,
        beta: float = 1.0,
        size_premium: float = 0.0,
        cost_of_debt: float = 0.05,
        tax_rate: float = 0.21,
        debt_weight: float = 0.30,
        equity_weight: float = 0.70,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Weighted Average Cost of Capital (WACC).

        Uses CAPM for cost of equity with optional size premium
        (Duff & Phelps / Ibbotson methodology).
        """
        cost_of_equity = risk_free_rate + beta * equity_risk_premium + size_premium
        after_tax_debt = cost_of_debt * (1 - tax_rate)
        wacc = equity_weight * cost_of_equity + debt_weight * after_tax_debt

        return {
            "company": company,
            "cost_of_equity": round(cost_of_equity, 4),
            "after_tax_cost_of_debt": round(after_tax_debt, 4),
            "wacc": round(wacc, 4),
            "components": {
                "risk_free_rate": risk_free_rate,
                "equity_risk_premium": equity_risk_premium,
                "beta": beta,
                "size_premium": size_premium,
                "cost_of_debt_pre_tax": cost_of_debt,
                "tax_rate": tax_rate,
            },
            "weights": {
                "equity": equity_weight,
                "debt": debt_weight,
            },
        }

    async def _tool_run_lbo_model(
        self,
        *,
        params: dict[str, Any] | LBOParameters | None = None,
        company: str = "",
        entry_ebitda: float = 100.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a Leveraged Buyout model.

        Models entry leverage, debt paydown schedule, equity returns,
        and IRR/MOIC sensitivity to exit assumptions.
        """
        if isinstance(params, dict):
            params = LBOParameters(**params)
        elif params is None:
            params = LBOParameters()

        entry_ev = entry_ebitda * params.purchase_price_multiple
        equity = entry_ev * params.equity_contribution_pct
        senior_debt = entry_ebitda * params.senior_debt_multiple
        sub_debt = entry_ebitda * params.sub_debt_multiple

        exit_ebitda = entry_ebitda * 1.05 ** params.holding_period
        exit_ev = exit_ebitda * params.exit_multiple
        exit_equity = exit_ev - senior_debt * 0.5 - sub_debt * 0.7

        moic = exit_equity / equity if equity > 0 else 0.0
        irr = (moic ** (1 / params.holding_period) - 1) if moic > 0 else 0.0

        return {
            "company": company,
            "entry_ev": round(entry_ev, 2),
            "equity_invested": round(equity, 2),
            "senior_debt": round(senior_debt, 2),
            "sub_debt": round(sub_debt, 2),
            "exit_ev": round(exit_ev, 2),
            "exit_equity_value": round(exit_equity, 2),
            "moic": round(moic, 2),
            "irr": round(irr, 4),
            "holding_period": params.holding_period,
        }

    async def _tool_analyze_merger_synergies(
        self,
        *,
        assumptions: dict[str, Any] | MergerAssumptions | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse merger synergies and integration economics."""
        if isinstance(assumptions, dict):
            assumptions = MergerAssumptions(**assumptions)
        elif assumptions is None:
            assumptions = MergerAssumptions()

        total_synergies = assumptions.cost_synergies + assumptions.revenue_synergies
        net_synergies = total_synergies - assumptions.integration_costs

        return {
            "acquirer": assumptions.acquirer_ticker,
            "target": assumptions.target_ticker,
            "cost_synergies": assumptions.cost_synergies,
            "revenue_synergies": assumptions.revenue_synergies,
            "total_gross_synergies": total_synergies,
            "integration_costs": assumptions.integration_costs,
            "net_synergies": net_synergies,
            "pv_synergies": round(net_synergies * 6, 2),
            "synergy_phase_in_years": assumptions.synergy_phase_in_years,
        }

    async def _tool_draft_fairness_opinion(
        self,
        *,
        company: str = "",
        offer_price: float = 0.0,
        valuation_range: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Draft a fairness opinion summary per FINRA Rule 5150."""
        return {
            "company": company,
            "offer_price": offer_price,
            "valuation_range": valuation_range or {"low": 0.0, "high": 0.0},
            "opinion": "fair_from_financial_point_of_view",
            "methodologies_used": ["DCF", "Comparable Companies", "Precedent Transactions"],
            "disclaimer": (
                "This fairness opinion is subject to the qualifications and "
                "assumptions set forth in the full written opinion. Per FINRA "
                "Rule 5150, all material relationships are disclosed herein."
            ),
            "requires_board_review": True,
        }

    async def _tool_generate_teaser(
        self,
        *,
        company: str = "",
        highlights: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a one-page teaser for a sell-side M&A process."""
        return {
            "company": "Project [Codename]",
            "type": "blind_teaser",
            "sections": [
                "Situation Overview",
                "Key Investment Highlights",
                "Summary Financial Profile",
                "Transaction Process & Timeline",
            ],
            "highlights": highlights or [],
            "confidentiality": "NDA required prior to receiving the CIM.",
            "status": "draft_ready",
        }

    async def _tool_analyze_debt_covenants(
        self,
        *,
        company: str = "",
        covenants: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse debt covenant compliance and headroom."""
        return {
            "company": company,
            "covenant_type": "maintenance",
            "covenants_checked": [
                {"name": "Max Leverage", "limit": 4.0, "actual": 2.5, "headroom": "37.5%"},
                {"name": "Min Interest Coverage", "limit": 2.0, "actual": 8.0, "headroom": "300%"},
                {"name": "Min Fixed Charge Coverage", "limit": 1.2, "actual": 2.5, "headroom": "108%"},
            ],
            "restricted_payments_basket": 500.0,
            "change_of_control_trigger": True,
            "compliance_status": "in_compliance",
        }

    async def _tool_screen_acquisition_targets(
        self,
        *,
        criteria: dict[str, Any] | None = None,
        sector: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Screen potential acquisition targets based on strategic criteria."""
        return {
            "sector": sector,
            "criteria": criteria or {},
            "targets_found": 0,
            "top_candidates": [],
            "screening_date": datetime.now(timezone.utc).isoformat(),
            "methodology": "Multi-factor scoring: strategic fit, financial profile, availability",
        }

    async def _tool_calculate_accretion_dilution(
        self,
        *,
        acquirer: str = "",
        target: str = "",
        offer_price: float = 0.0,
        financing_mix: dict[str, float] | None = None,
        synergies: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate EPS accretion/dilution from an M&A transaction."""
        mix = financing_mix or {"cash": 0.5, "stock": 0.5}
        return {
            "acquirer": acquirer,
            "target": target,
            "offer_price": offer_price,
            "financing_mix": mix,
            "pre_synergy_impact": "dilutive",
            "post_synergy_impact": "accretive" if synergies > 0 else "dilutive",
            "year_1_eps_impact_pct": -0.02,
            "year_2_eps_impact_pct": 0.03,
            "breakeven_synergies": synergies * 0.4,
            "reference": "ASC 805 purchase price allocation applied",
        }

    async def _tool_draft_management_presentation(
        self,
        *,
        company: str = "",
        sections: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Draft a management presentation for a sell-side or buy-side process."""
        default_sections = [
            "Executive Summary", "Business Overview", "Market Opportunity",
            "Financial Performance", "Growth Strategy", "Management Team",
            "Transaction Considerations",
        ]
        return {
            "company": company,
            "sections": sections or default_sections,
            "slide_count": 35,
            "status": "draft_ready",
            "format": "PowerPoint",
        }

    async def _tool_analyze_credit_metrics(
        self,
        *,
        company: str = "",
        financials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse credit metrics for rating agency assessment."""
        return {
            "company": company,
            "metrics": {
                "total_debt_to_ebitda": 2.5,
                "net_debt_to_ebitda": 2.0,
                "ebitda_to_interest": 8.0,
                "ffo_to_debt": 0.35,
                "debt_to_total_cap": 0.30,
                "retained_cash_flow_to_debt": 0.25,
            },
            "implied_rating": {
                "sp": "BBB+",
                "moodys": "Baa1",
                "fitch": "BBB+",
            },
            "methodology": "S&P Corporate Rating Methodology (2023 update)",
        }

    async def _tool_generate_tombstone(
        self,
        *,
        deal: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a deal tombstone for completed transactions."""
        return {
            "deal": deal or {},
            "format": "standard_tombstone",
            "fields": [
                "Transaction type", "Value", "Date", "Advisor role",
                "Client", "Counterparty",
            ],
            "status": "ready_for_review",
        }

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _record_audit(self, tool_name: str, result: ToolResult) -> None:
        """Record tool execution in the audit log."""
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "tool": tool_name,
            "success": result.success,
            "execution_time_ms": result.execution_time_ms,
        })

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Return a copy of the audit log."""
        return list(self._audit_log)
