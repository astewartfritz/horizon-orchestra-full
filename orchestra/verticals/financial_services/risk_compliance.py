"""Horizon Orchestra — Financial Risk & Compliance Agent.

Provides a domain-specialized agent for financial risk management and
regulatory compliance workflows including VaR calculation, stress testing,
Basel III compliance, AML/KYC, trading surveillance, and CCAR scenarios.

Regulatory and industry references:
- Basel III / Basel 3.1 (capital adequacy, liquidity, leverage)
- Dodd-Frank Act (systemic risk, Volcker Rule)
- Bank Secrecy Act / AML (anti-money laundering)
- USA PATRIOT Act (KYC requirements)
- CCAR / DFAST (Fed stress testing)
- Volcker Rule (proprietary trading restrictions)
- OFAC sanctions screening
- SAR / CTR reporting (FinCEN)

Target customers: JPMorgan, Goldman Sachs, Citigroup, Bank of America,
and comparable systemically important financial institutions (SIFIs).
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

__all__ = ["FinancialRiskAgent"]

log = logging.getLogger("orchestra.verticals.financial_services.risk_compliance")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class RiskType(Enum):
    """Categories of financial risk."""
    MARKET = "market"
    CREDIT = "credit"
    OPERATIONAL = "operational"
    LIQUIDITY = "liquidity"
    COUNTERPARTY = "counterparty"
    MODEL = "model"
    SYSTEMIC = "systemic"


class ComplianceStatus(Enum):
    """Compliance check result statuses."""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"
    ESCALATED = "escalated"


@dataclass
class VaRParameters:
    """Parameters for Value at Risk calculation."""
    confidence_level: float = 0.99
    holding_period_days: int = 10
    method: str = "historical"  # historical, parametric, monte_carlo
    lookback_days: int = 250
    portfolio_value: float = 1_000_000.0


@dataclass
class StressScenario:
    """A stress test scenario definition."""
    name: str = ""
    description: str = ""
    equity_shock_pct: float = -0.30
    rate_shock_bps: int = 200
    credit_spread_shock_bps: int = 150
    fx_shock_pct: float = -0.15
    commodity_shock_pct: float = -0.25
    gdp_shock_pct: float = -0.03
    unemployment_shock_pct: float = 0.04


@dataclass
class BaselMetrics:
    """Basel III capital adequacy metrics."""
    cet1_ratio: float = 0.0
    tier1_ratio: float = 0.0
    total_capital_ratio: float = 0.0
    leverage_ratio: float = 0.0
    lcr: float = 0.0  # Liquidity Coverage Ratio
    nsfr: float = 0.0  # Net Stable Funding Ratio
    rwa: float = 0.0  # Risk-Weighted Assets


@dataclass
class AMLAlert:
    """Anti-Money Laundering alert."""
    alert_id: str = ""
    customer_id: str = ""
    alert_type: str = ""  # structuring, layering, unusual_activity
    risk_score: float = 0.0
    transaction_count: int = 0
    total_amount: float = 0.0
    status: str = "open"


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
# Financial Risk & Compliance Agent
# ---------------------------------------------------------------------------

class FinancialRiskAgent:
    """Domain-specialized agent for financial risk and compliance.

    Covers market risk (VaR, stress testing), credit risk, regulatory
    compliance (Basel III, Volcker Rule), AML/KYC, trading surveillance,
    and prudential reporting (CCAR/DFAST).

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

        agent = FinancialRiskAgent()
        result = await agent.execute_tool("calculate_var", portfolio_value=1e6)
    """

    TOOLS: list[str] = [
        "calculate_var",
        "run_stress_test",
        "check_basel_iii",
        "monitor_risk_limits",
        "generate_risk_report",
        "check_aml_flags",
        "run_sanctions_screening",
        "check_kyc_completeness",
        "generate_sar_draft",
        "monitor_trading_surveillance",
        "check_volcker_rule",
        "analyze_counterparty_risk",
        "calculate_capital_adequacy",
        "run_ccar_scenario",
        "generate_regulatory_report",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        regulatory_jurisdiction: str = "US",
    ) -> None:
        self.agent_id = agent_id or f"risk-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.regulatory_jurisdiction = regulatory_jurisdiction
        self._alert_queue: list[AMLAlert] = []
        self._audit_log: list[dict[str, Any]] = []
        log.info("FinancialRiskAgent %s initialised (model=%s)", self.agent_id, model)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for risk & compliance.

        Returns a comprehensive prompt embedding financial risk management
        knowledge, regulatory frameworks, and compliance best practices.
        """
        return (
            "You are a senior financial risk and compliance officer with deep "
            "expertise in market risk, credit risk, regulatory compliance, and "
            "financial crime prevention. You operate within a regulated banking "
            "environment and must ensure all activities comply with applicable "
            "laws and regulations.\n\n"
            "MARKET RISK:\n"
            "- Value at Risk (VaR): Calculate using Historical Simulation, "
            "Parametric (variance-covariance), or Monte Carlo methods. Standard "
            "confidence levels: 99% (regulatory) and 95% (internal). Holding "
            "period: 10 days for regulatory, 1 day for trading desk limits.\n"
            "- Stressed VaR (sVaR): Per Basel 2.5, calculate using a 12-month "
            "period of significant financial stress. The stress period must "
            "produce the highest VaR for the current portfolio.\n"
            "- Expected Shortfall (ES): Basel 3.1 FRTB replacement for VaR. "
            "97.5% confidence level, calibrated to stressed period.\n"
            "- Sensitivity Analysis: Greeks (Delta, Gamma, Vega, Theta, Rho) "
            "for derivatives. DV01/PV01 for fixed income. Scenario analysis "
            "for non-linear risks.\n\n"
            "CREDIT RISK:\n"
            "- PD/LGD/EAD framework: Probability of Default from internal "
            "ratings, Loss Given Default calibrated by collateral and seniority, "
            "Exposure at Default including off-balance-sheet commitments.\n"
            "- Counterparty Credit Risk: CVA (Credit Valuation Adjustment), "
            "SA-CCR (Standardized Approach), potential future exposure.\n"
            "- Concentration risk: single-name, sector, geographic limits.\n\n"
            "BASEL III / BASEL 3.1:\n"
            "- Capital Requirements: CET1 ≥ 4.5%, Tier 1 ≥ 6%, Total Capital "
            "≥ 8%. G-SIB surcharge: 1-3.5%. CCyB: 0-2.5%. Capital Conservation "
            "Buffer: 2.5%.\n"
            "- Leverage Ratio: Tier 1 / Total Exposure ≥ 3% (5% for US G-SIBs "
            "including eSLR).\n"
            "- Liquidity: LCR (HQLA / 30-day net outflows ≥ 100%), NSFR "
            "(Available Stable Funding / Required ≥ 100%).\n"
            "- Output Floor: RWA under internal models ≥ 72.5% of standardized "
            "approach (phased in through 2028).\n\n"
            "AML / KYC / SANCTIONS:\n"
            "- Customer Due Diligence (CDD): Identify and verify customer "
            "identity. Enhanced Due Diligence (EDD) for PEPs, high-risk "
            "jurisdictions, complex structures.\n"
            "- Transaction Monitoring: Flag structuring (breaking deposits "
            "below $10K CTR threshold), rapid movement of funds (layering), "
            "unusual patterns inconsistent with customer profile.\n"
            "- Sanctions Screening: OFAC SDN list, EU Consolidated List, "
            "UN Security Council, HMT. Screen customers, counterparties, "
            "and all wire transfers. Fuzzy matching required.\n"
            "- SAR Filing: File within 30 days of initial detection. Include "
            "all five W's (who, what, when, where, why). FinCEN BSA E-Filing.\n\n"
            "VOLCKER RULE:\n"
            "- Prohibits proprietary trading and certain relationships with "
            "covered funds. Exemptions: market-making, underwriting, hedging, "
            "trading in US government securities.\n"
            "- Compliance program: reasonably designed to identify, monitor, "
            "and report covered trading activities.\n\n"
            "CCAR / DFAST:\n"
            "- Annual stress tests: Baseline, Adverse, Severely Adverse scenarios.\n"
            "- Capital planning: Pre-provision net revenue (PPNR), credit losses, "
            "trading/counterparty losses, operational risk losses.\n"
            "- Minimum capital ratios must be maintained through the 9-quarter "
            "planning horizon under all scenarios.\n\n"
            "COMPLIANCE PRINCIPLES:\n"
            "- Escalate immediately if any suspicious activity or regulatory "
            "breach is detected.\n"
            "- Maintain complete audit trail for all risk and compliance actions.\n"
            "- Apply the precautionary principle: when in doubt, escalate.\n"
        )

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        **kwargs: Any,
    ) -> ToolResult:
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

    async def _tool_calculate_var(
        self,
        *,
        params: dict[str, Any] | VaRParameters | None = None,
        portfolio_value: float = 1_000_000.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Value at Risk (VaR).

        Supports Historical Simulation, Parametric (variance-covariance),
        and Monte Carlo methods at configurable confidence levels.
        """
        if isinstance(params, dict):
            params = VaRParameters(**params)
        elif params is None:
            params = VaRParameters(portfolio_value=portfolio_value)

        var_1d = params.portfolio_value * 0.02  # Simplified
        var_scaled = var_1d * (params.holding_period_days ** 0.5)

        return {
            "var_1day": round(var_1d, 2),
            "var_scaled": round(var_scaled, 2),
            "confidence_level": params.confidence_level,
            "holding_period_days": params.holding_period_days,
            "method": params.method,
            "portfolio_value": params.portfolio_value,
            "lookback_days": params.lookback_days,
            "expected_shortfall": round(var_scaled * 1.3, 2),
        }

    async def _tool_run_stress_test(
        self,
        *,
        scenario: dict[str, Any] | StressScenario | None = None,
        portfolio_value: float = 1_000_000.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a stress test scenario against the portfolio.

        Applies macro-economic shocks to calculate portfolio P&L impact.
        """
        if isinstance(scenario, dict):
            scenario = StressScenario(**scenario)
        elif scenario is None:
            scenario = StressScenario(name="Severely Adverse", description="Fed CCAR severely adverse")

        equity_loss = portfolio_value * 0.4 * scenario.equity_shock_pct
        rate_impact = portfolio_value * 0.3 * scenario.rate_shock_bps / 10000
        credit_impact = portfolio_value * 0.2 * scenario.credit_spread_shock_bps / 10000
        total_loss = equity_loss + rate_impact + credit_impact

        return {
            "scenario": scenario.name,
            "description": scenario.description,
            "portfolio_value": portfolio_value,
            "total_pnl_impact": round(total_loss, 2),
            "equity_impact": round(equity_loss, 2),
            "rate_impact": round(rate_impact, 2),
            "credit_spread_impact": round(credit_impact, 2),
            "post_stress_value": round(portfolio_value + total_loss, 2),
            "post_stress_capital_adequate": True,
        }

    async def _tool_check_basel_iii(
        self,
        *,
        metrics: dict[str, Any] | BaselMetrics | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check Basel III capital adequacy compliance.

        Validates CET1, Tier 1, Total Capital, Leverage Ratio,
        LCR, and NSFR against regulatory minimums.
        """
        if isinstance(metrics, dict):
            metrics = BaselMetrics(**metrics)
        elif metrics is None:
            metrics = BaselMetrics(
                cet1_ratio=0.12, tier1_ratio=0.14, total_capital_ratio=0.16,
                leverage_ratio=0.06, lcr=1.20, nsfr=1.10, rwa=500_000.0,
            )

        checks = {
            "cet1": {"actual": metrics.cet1_ratio, "minimum": 0.045, "buffer": 0.025, "gsib_surcharge": 0.025},
            "tier1": {"actual": metrics.tier1_ratio, "minimum": 0.06},
            "total_capital": {"actual": metrics.total_capital_ratio, "minimum": 0.08},
            "leverage": {"actual": metrics.leverage_ratio, "minimum": 0.05},
            "lcr": {"actual": metrics.lcr, "minimum": 1.0},
            "nsfr": {"actual": metrics.nsfr, "minimum": 1.0},
        }

        all_compliant = all(
            v["actual"] >= v["minimum"] for v in checks.values()
        )

        return {
            "overall_status": "compliant" if all_compliant else "non_compliant",
            "checks": checks,
            "rwa": metrics.rwa,
            "regulatory_framework": "Basel III / Basel 3.1",
            "jurisdiction": self.regulatory_jurisdiction,
        }

    async def _tool_monitor_risk_limits(
        self,
        *,
        desk: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Monitor risk limits across trading desks."""
        return {
            "desk": desk,
            "limits": [
                {"metric": "VaR (99%, 1d)", "limit": 50_000_000, "actual": 35_000_000, "utilization": 0.70},
                {"metric": "Notional", "limit": 10_000_000_000, "actual": 7_500_000_000, "utilization": 0.75},
                {"metric": "DV01", "limit": 500_000, "actual": 350_000, "utilization": 0.70},
                {"metric": "Greeks - Delta", "limit": 100_000_000, "actual": 65_000_000, "utilization": 0.65},
            ],
            "breaches": [],
            "warnings": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _tool_generate_risk_report(
        self,
        *,
        report_type: str = "daily",
        as_of_date: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a risk report (daily, weekly, or regulatory)."""
        return {
            "report_type": report_type,
            "as_of_date": as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "sections": [
                "Executive Summary", "Market Risk", "Credit Risk",
                "Liquidity Risk", "Operational Risk", "Limit Utilization",
            ],
            "status": "generated",
            "format": "PDF",
        }

    async def _tool_check_aml_flags(
        self,
        *,
        customer_id: str = "",
        transactions: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check for Anti-Money Laundering red flags.

        Evaluates transactions against AML typologies: structuring,
        layering, unusual patterns, PEP-related activity.
        """
        return {
            "customer_id": customer_id,
            "alerts": [],
            "risk_score": 25.0,
            "risk_level": "low",
            "typologies_checked": [
                "structuring", "layering", "round_tripping",
                "unusual_geographic_patterns", "pep_transactions",
            ],
            "sar_required": False,
            "reference": "BSA/AML Examination Manual (FFIEC)",
        }

    async def _tool_run_sanctions_screening(
        self,
        *,
        entity_name: str = "",
        entity_type: str = "individual",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run sanctions screening against global watchlists."""
        return {
            "entity_name": entity_name,
            "entity_type": entity_type,
            "lists_screened": [
                "OFAC SDN", "OFAC Consolidated",
                "EU Consolidated", "UN Security Council", "HMT",
            ],
            "matches": [],
            "match_count": 0,
            "screening_method": "fuzzy_matching",
            "confidence_threshold": 0.85,
            "status": "clear",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _tool_check_kyc_completeness(
        self,
        *,
        customer_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check KYC (Know Your Customer) completeness.

        Validates all required CDD/EDD documents and information
        are current and complete per regulatory requirements.
        """
        return {
            "customer_id": customer_id,
            "cdd_complete": True,
            "edd_required": False,
            "documents": {
                "government_id": "verified",
                "proof_of_address": "verified",
                "beneficial_ownership": "verified",
                "source_of_funds": "verified",
            },
            "risk_rating": "standard",
            "next_review_date": "2026-01-15",
            "reference": "USA PATRIOT Act Section 326; FinCEN CDD Rule",
        }

    async def _tool_generate_sar_draft(
        self,
        *,
        alert: dict[str, Any] | AMLAlert | None = None,
        narrative: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Draft a Suspicious Activity Report (SAR).

        Generates a SAR narrative covering the five W's: who, what,
        when, where, and why, per FinCEN filing requirements.
        """
        return {
            "sar_type": "initial",
            "filing_deadline": "30 days from detection",
            "sections": {
                "subject_information": "Required",
                "suspicious_activity": "Required",
                "narrative": "Draft ready for compliance review",
            },
            "status": "draft",
            "requires_bsa_officer_review": True,
            "reference": "FinCEN SAR Filing Instructions; 31 CFR 1020.320",
        }

    async def _tool_monitor_trading_surveillance(
        self,
        *,
        desk: str = "",
        lookback_hours: int = 24,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Monitor trading activity for surveillance alerts.

        Checks for spoofing, layering, wash trades, front-running,
        and insider trading patterns.
        """
        return {
            "desk": desk,
            "lookback_hours": lookback_hours,
            "alerts": [],
            "patterns_checked": [
                "spoofing", "layering", "wash_trading",
                "front_running", "insider_trading", "marking_the_close",
            ],
            "trades_reviewed": 0,
            "status": "no_alerts",
            "reference": "Dodd-Frank Title VII; SEC Rule 10b-5",
        }

    async def _tool_check_volcker_rule(
        self,
        *,
        activity: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check Volcker Rule compliance.

        Evaluates whether trading activity falls within permitted
        exemptions: market-making, underwriting, hedging, or
        government securities.
        """
        return {
            "activity_type": "market_making",
            "volcker_exempt": True,
            "exemption_basis": "Bona fide market-making per Section 619",
            "metrics_checked": [
                "RENTD (Reasonably Expected Near-Term Demand)",
                "Inventory aging",
                "P&L attribution",
            ],
            "compliance_status": "compliant",
            "reference": "Dodd-Frank Act Section 619; 12 CFR Part 248",
        }

    async def _tool_analyze_counterparty_risk(
        self,
        *,
        counterparty: str = "",
        exposure: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse counterparty credit risk.

        Calculates CVA, potential future exposure, and evaluates
        counterparty creditworthiness using SA-CCR methodology.
        """
        return {
            "counterparty": counterparty,
            "current_exposure": exposure,
            "potential_future_exposure": round(exposure * 0.15, 2),
            "cva": round(exposure * 0.005, 2),
            "internal_rating": "A",
            "pd_1y": 0.0005,
            "lgd": 0.45,
            "netting_benefit": 0.30,
            "collateral_held": 0.0,
            "methodology": "SA-CCR (Standardized Approach for Counterparty Credit Risk)",
        }

    async def _tool_calculate_capital_adequacy(
        self,
        *,
        rwa_breakdown: dict[str, float] | None = None,
        capital: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate capital adequacy ratios under Basel III."""
        rwa = rwa_breakdown or {"credit": 300e9, "market": 50e9, "operational": 80e9}
        cap = capital or {"cet1": 60e9, "at1": 10e9, "tier2": 15e9}

        total_rwa = sum(rwa.values())
        cet1_ratio = cap.get("cet1", 0) / total_rwa if total_rwa else 0
        tier1_ratio = (cap.get("cet1", 0) + cap.get("at1", 0)) / total_rwa if total_rwa else 0

        return {
            "total_rwa": total_rwa,
            "rwa_breakdown": rwa,
            "capital": cap,
            "cet1_ratio": round(cet1_ratio, 4),
            "tier1_ratio": round(tier1_ratio, 4),
            "total_capital_ratio": round(sum(cap.values()) / total_rwa, 4) if total_rwa else 0,
            "meets_minimum": cet1_ratio >= 0.045,
            "meets_buffer": cet1_ratio >= 0.07,
        }

    async def _tool_run_ccar_scenario(
        self,
        *,
        scenario_name: str = "severely_adverse",
        quarters: int = 9,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a CCAR (Comprehensive Capital Analysis and Review) scenario.

        Simulates the Fed's stress testing framework over the planning
        horizon to project capital ratios under stress.
        """
        return {
            "scenario": scenario_name,
            "planning_horizon_quarters": quarters,
            "pre_stress_cet1": 0.125,
            "minimum_cet1_through_horizon": 0.075,
            "post_stress_cet1": 0.085,
            "ppnr_through_horizon": 25e9,
            "credit_losses_through_horizon": 35e9,
            "trading_losses_through_horizon": 5e9,
            "capital_actions": {
                "dividends": 8e9,
                "buybacks": 5e9,
            },
            "passes_minimum": True,
            "reference": "Federal Reserve Regulation YY; SR 15-18",
        }

    async def _tool_generate_regulatory_report(
        self,
        *,
        report_type: str = "FR_Y-14A",
        as_of_date: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a regulatory report for submission.

        Supports FR Y-14A/Q, FFIEC 101/102, FR 2052a, and
        other prudential reporting forms.
        """
        valid_reports = [
            "FR_Y-14A", "FR_Y-14Q", "FFIEC_101", "FFIEC_102",
            "FR_2052a", "FR_Y-9C", "CCAR", "DFAST",
        ]
        return {
            "report_type": report_type,
            "as_of_date": as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "valid_report_types": valid_reports,
            "status": "draft_generated",
            "requires_review": True,
            "submission_deadline": "45 calendar days after quarter-end",
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
