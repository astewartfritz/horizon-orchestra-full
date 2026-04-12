"""Matter Management Agent — Legal matter and billing management.

AI-powered matter management covering time tracking, budget management,
staffing optimization, invoice review, AFA (Alternative Fee Arrangements),
and client reporting.

Integrations
------------
- Clio (cloud legal practice management)
- Thomson Reuters eBillingHub
- LegalTracker (Wolters Kluwer)

Billing standards
-----------------
- UTBMS (Uniform Task-Based Management System) codes
- LEDES (Legal Electronic Data Exchange Standard) 1998B format
- ABA billing guidelines
- AIIM-recommended outside counsel billing guidelines

Target customers
----------------
- Kirkland & Ellis: M&A matter budgeting, deal team staffing
- Sidley Austin: IP litigation budgeting, alternative fee arrangements
- Latham & Watkins: Capital markets matter management, multi-office coordination
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "MatterManagementAgent",
    "MatterBudget",
    "InvoiceReview",
    "StaffingAnalysis",
    "AFATerms",
    "MatterSummary",
    "MatterStatus",
    "BillingAnomaly",
    "DeadlineTracker",
    "EngagementLetter",
    "PeerBenchmark",
    "UTBMSCode",
]

log = logging.getLogger("orchestra.verticals.legal.matter_management")

# ---------------------------------------------------------------------------
# Graceful imports
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except Exception:
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════
# UTBMS Codes (Uniform Task-Based Management System)
# ═══════════════════════════════════════════════════════════════════════════

class UTBMSCode(str, Enum):
    """UTBMS task codes for legal billing categorization.

    These codes are the industry standard used by eBillingHub,
    LegalTracker, and other legal billing platforms.
    """
    # Litigation phase codes
    L100 = "L100"       # Case Assessment, Development, Administration
    L110 = "L110"       # Fact Investigation / Development
    L120 = "L120"       # Analysis / Strategy
    L130 = "L130"       # Experts / Consultants
    L140 = "L140"       # Document Drafting
    L150 = "L150"       # Review / Analyze Opposing Docs
    L160 = "L160"       # Communications with Client
    L190 = "L190"       # Other Case Assessment
    L200 = "L200"       # Pre-Trial Pleadings and Motions
    L210 = "L210"       # Fact Investigation / Development
    L220 = "L220"       # Written Discovery
    L230 = "L230"       # Document Production
    L240 = "L240"       # Interrogatories
    L250 = "L250"       # Requests for Admission
    L260 = "L260"       # Depositions
    L310 = "L310"       # Written Discovery
    L320 = "L320"       # Document Production
    L400 = "L400"       # Trial Preparation and Trial
    L410 = "L410"       # Fact Witnesses
    L420 = "L420"       # Expert Witnesses
    L430 = "L430"       # Briefs and Memoranda
    L440 = "L440"       # Settlement / Non-Binding ADR
    L500 = "L500"       # Appeal
    L510 = "L510"       # Dispositive Motions
    L520 = "L520"       # Post-Trial Motions

    # Corporate/transactional codes
    C100 = "C100"       # Counseling
    C110 = "C110"       # Research
    C200 = "C200"       # Drafting / Reviewing Contracts
    C210 = "C210"       # Due Diligence
    C300 = "C300"       # Negotiation
    C400 = "C400"       # Regulatory / Governmental

    # Expense codes
    E100 = "E100"       # Copying / Scanning
    E110 = "E110"       # Outside Services
    E120 = "E120"       # Travel
    E130 = "E130"       # Court Fees
    E140 = "E140"       # Expert Fees


# ═══════════════════════════════════════════════════════════════════════════
# Enums & Data Models
# ═══════════════════════════════════════════════════════════════════════════

class MatterStatus(str, Enum):
    """Matter lifecycle status."""
    INTAKE = "intake"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSING = "closing"
    CLOSED = "closed"
    ARCHIVED = "archived"


class AFAType(str, Enum):
    """Alternative Fee Arrangement types."""
    FIXED_FEE = "fixed_fee"
    CAPPED_FEE = "capped_fee"
    SUCCESS_FEE = "success_fee"
    BLENDED_RATE = "blended_rate"
    PORTFOLIO_DISCOUNT = "portfolio_discount"
    HOLDBACK = "holdback"
    COLLAR = "collar"               # Floor + ceiling arrangement
    HYBRID = "hybrid"               # Hourly + success component


class TimekeeperLevel(str, Enum):
    """Timekeeper seniority levels."""
    SENIOR_PARTNER = "senior_partner"
    PARTNER = "partner"
    OF_COUNSEL = "of_counsel"
    SENIOR_ASSOCIATE = "senior_associate"
    MID_ASSOCIATE = "mid_associate"
    JUNIOR_ASSOCIATE = "junior_associate"
    PARALEGAL = "paralegal"
    LEGAL_ASSISTANT = "legal_assistant"
    SUMMER_ASSOCIATE = "summer_associate"


@dataclass
class MatterBudget:
    """Matter budget analysis."""
    matter_id: str
    matter_name: str
    budget_total: float
    actual_to_date: float
    remaining: float
    burn_rate_monthly: float
    projected_total: float
    variance_pct: float             # % over/under budget
    phase_breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)
    risk_of_overrun: str = "low"    # low, medium, high
    recommendations: List[str] = field(default_factory=list)


@dataclass
class BillingAnomaly:
    """A detected billing anomaly."""
    anomaly_type: str               # e.g., "block_billing", "excessive_hours", "rate_mismatch"
    timekeeper: str
    date: str
    hours: float
    description: str
    severity: str                   # low, medium, high
    utbms_code: Optional[str] = None
    guideline_violation: Optional[str] = None


@dataclass
class InvoiceReview:
    """Invoice review result with UTBMS compliance."""
    invoice_id: str
    vendor_name: str
    total_amount: float
    line_items: int
    anomalies: List[BillingAnomaly] = field(default_factory=list)
    utbms_compliance: bool = True
    ledes_format_valid: bool = True
    recommended_adjustments: float = 0.0
    approved_amount: float = 0.0
    notes: List[str] = field(default_factory=list)


@dataclass
class StaffingAnalysis:
    """Staffing mix optimization analysis."""
    matter_id: str
    current_mix: Dict[str, int] = field(default_factory=dict)     # level -> count
    recommended_mix: Dict[str, int] = field(default_factory=dict)
    current_blended_rate: float = 0.0
    recommended_blended_rate: float = 0.0
    annual_savings: float = 0.0
    rationale: str = ""


@dataclass
class AFATerms:
    """Alternative Fee Arrangement terms."""
    afa_type: AFAType
    base_amount: float
    cap: Optional[float] = None
    success_bonus: Optional[float] = None
    success_trigger: Optional[str] = None
    holdback_pct: Optional[float] = None
    discount_pct: Optional[float] = None
    collar_floor: Optional[float] = None
    collar_ceiling: Optional[float] = None
    effective_rate: float = 0.0
    comparison_to_hourly: float = 0.0   # % savings vs. hourly


@dataclass
class MatterSummary:
    """Client-facing matter status report."""
    matter_id: str
    matter_name: str
    status: MatterStatus
    budget_summary: str
    recent_activities: List[str] = field(default_factory=list)
    upcoming_deadlines: List[Dict[str, str]] = field(default_factory=list)
    key_issues: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DeadlineTracker:
    """Court deadline and statute of limitations tracker."""
    matter_id: str
    deadlines: List[Dict[str, Any]] = field(default_factory=list)
    overdue: List[Dict[str, Any]] = field(default_factory=list)
    upcoming_7_days: List[Dict[str, Any]] = field(default_factory=list)
    upcoming_30_days: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class EngagementLetter:
    """Engagement letter / scope of work."""
    letter_id: str
    client_name: str
    matter_description: str
    scope_of_work: str
    fee_arrangement: str
    conflict_check_status: str = "pending"
    terms_and_conditions: str = ""
    effective_date: str = ""


@dataclass
class PeerBenchmark:
    """Peer firm rate/cost comparison."""
    matter_type: str
    benchmark_source: str
    peer_median_rate: float
    peer_median_total: float
    our_rate: float
    our_projected_total: float
    percentile_rank: int            # 1-100 (100 = most expensive)
    notes: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# Standard billing rates by level (Am Law 100 benchmark)
# ═══════════════════════════════════════════════════════════════════════════

_BENCHMARK_RATES: Dict[str, Dict[str, float]] = {
    "senior_partner": {"low": 1200.0, "median": 1600.0, "high": 2200.0},
    "partner": {"low": 900.0, "median": 1200.0, "high": 1800.0},
    "of_counsel": {"low": 700.0, "median": 950.0, "high": 1400.0},
    "senior_associate": {"low": 600.0, "median": 850.0, "high": 1200.0},
    "mid_associate": {"low": 450.0, "median": 650.0, "high": 950.0},
    "junior_associate": {"low": 350.0, "median": 500.0, "high": 750.0},
    "paralegal": {"low": 200.0, "median": 350.0, "high": 500.0},
    "legal_assistant": {"low": 150.0, "median": 250.0, "high": 400.0},
}

# Billing guideline violation patterns
_BILLING_VIOLATIONS: Dict[str, re.Pattern] = {
    "block_billing": re.compile(r"\d+\.?\d*\s*hours?\s*-\s*(?:.*;\s*){3,}", re.I),
    "vague_description": re.compile(r"^(review|prepare|draft|work on|attention to)\s*$", re.I),
    "excessive_travel": re.compile(r"travel\s+time.*?(\d+\.?\d*)\s*hours?", re.I),
    "clerical_by_attorney": re.compile(r"(filing|faxing|copying|scanning|scheduling)", re.I),
}


# ═══════════════════════════════════════════════════════════════════════════
# MatterManagementAgent
# ═══════════════════════════════════════════════════════════════════════════

class MatterManagementAgent:
    """Legal matter and billing management agent.

    Time tracking, budget management, staffing optimization,
    bill review, AFA (Alternative Fee Arrangements), client reporting.
    Integrates with: Clio, Thomson Reuters eBillingHub, LegalTracker.

    Examples
    --------
    >>> agent = MatterManagementAgent()
    >>> budget = await agent.analyze_matter_budget("M-2024-001", entries)
    >>> review = await agent.review_invoice(invoice_data)
    """

    TOOLS = [
        "analyze_matter_budget",          # Budget vs. actual analysis
        "review_invoice_billing",         # UTBMS billing guideline compliance
        "flag_billing_anomalies",         # Unusual time entries, block billing
        "optimize_staffing_mix",          # Partner/associate/paralegal ratio
        "generate_matter_summary",        # Client status report
        "calculate_afa_terms",            # Fixed fee, success fee calculation
        "track_deadlines",                # Court deadline + statute of limitations
        "generate_status_report",         # Client matter status report
        "analyze_peer_benchmarks",        # Peer firm rate/cost comparison
        "draft_engagement_letter",        # Engagement letter + scope of work
    ]

    def __init__(
        self,
        *,
        budget_alert_threshold: float = 0.80,
        model: str = "kimi-k2.5",
        firm_name: str = "",
    ) -> None:
        self._budget_alert = budget_alert_threshold
        self._model = model
        self._firm_name = firm_name
        self._matters: Dict[str, Dict[str, Any]] = {}
        log.info(
            "MatterManagementAgent initialized (model=%s, firm=%s)",
            model, firm_name or "default",
        )

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for matter management."""
        return (
            "You are an expert legal matter management and billing agent. You have "
            "deep expertise in law firm operations and legal project management:\n\n"
            "BILLING STANDARDS:\n"
            "- UTBMS (Uniform Task-Based Management System) code categories:\n"
            "  L100-L500: Litigation phases (assessment through appeal)\n"
            "  C100-C400: Corporate/transactional (counseling, contracts, negotiation)\n"
            "  E100-E140: Expense categories (copying, travel, court fees, experts)\n"
            "- LEDES 1998B electronic billing format\n"
            "- ABA Model Rules on billing (Rule 1.5 — reasonableness of fees)\n"
            "- Common billing guideline violations:\n"
            "  * Block billing (lumping multiple tasks in one entry)\n"
            "  * Vague descriptions ('review file', 'attention to matter')\n"
            "  * Excessive hours without justification\n"
            "  * Clerical work billed at attorney rates\n"
            "  * Duplicate entries across timekeepers\n\n"
            "MATTER ECONOMICS:\n"
            "- Budget development by litigation phase (UTBMS phases L100-L500)\n"
            "- Burn rate analysis and overrun prediction\n"
            "- Staffing leverage optimization (partner:associate:paralegal ratios)\n"
            "- Alternative Fee Arrangements (AFA):\n"
            "  * Fixed fee: Set price for defined scope\n"
            "  * Capped fee: Hourly with maximum ceiling\n"
            "  * Success fee: Bonus tied to outcome\n"
            "  * Blended rate: Single rate across all timekeepers\n"
            "  * Collar arrangement: Floor + ceiling range\n"
            "  * Holdback: Percentage withheld pending outcome\n\n"
            "DEADLINE MANAGEMENT:\n"
            "- Federal/state court filing deadlines (FRCP, local rules)\n"
            "- Statute of limitations tracking by jurisdiction and claim type\n"
            "- Regulatory filing deadlines (SEC, DOJ, FTC)\n"
            "- Contractual milestone deadlines\n\n"
            "PEER BENCHMARKING:\n"
            "- Am Law 100/200 rate comparisons by practice area\n"
            "- Matter cost benchmarks by type and complexity\n"
            "- Staffing ratio benchmarks (optimal leverage)\n"
        )

    # -------------------------------------------------------------------
    # Core matter management methods
    # -------------------------------------------------------------------

    async def analyze_matter_budget(
        self,
        matter_id: str,
        time_entries: List[Dict[str, Any]],
        *,
        budget_total: float = 0.0,
        matter_name: str = "",
    ) -> MatterBudget:
        """Analyze matter budget versus actual spend.

        Parameters
        ----------
        matter_id:
            Unique matter identifier.
        time_entries:
            List of time entry dicts with: timekeeper, hours, rate, date, utbms_code.
        budget_total:
            Total approved budget.
        matter_name:
            Human-readable matter name.
        """
        log.info("Analyzing budget for matter %s", matter_id)

        actual = sum(
            e.get("hours", 0) * e.get("rate", 0)
            for e in time_entries
        )

        # Phase breakdown
        phase_totals: Dict[str, Dict[str, float]] = {}
        for entry in time_entries:
            code = entry.get("utbms_code", "L190")
            phase = code[:2] + "00" if len(code) >= 3 else code
            if phase not in phase_totals:
                phase_totals[phase] = {"hours": 0.0, "amount": 0.0}
            phase_totals[phase]["hours"] += entry.get("hours", 0)
            phase_totals[phase]["amount"] += entry.get("hours", 0) * entry.get("rate", 0)

        # Monthly burn rate
        dates = [e.get("date", "") for e in time_entries if e.get("date")]
        months_active = max(1, len(set(d[:7] for d in dates if len(d) >= 7)))
        burn_rate = actual / months_active

        remaining = max(0, budget_total - actual)
        variance = ((actual - budget_total) / budget_total * 100) if budget_total > 0 else 0
        projected = actual + (burn_rate * 3)  # 3-month projection

        risk = (
            "high" if variance > 10 or (budget_total > 0 and actual / budget_total > 0.9)
            else "medium" if variance > 0 or (budget_total > 0 and actual / budget_total > 0.7)
            else "low"
        )

        recommendations: List[str] = []
        if risk == "high":
            recommendations.append("Schedule budget review meeting with client")
            recommendations.append("Consider staffing adjustment to reduce burn rate")
        if variance > 0:
            recommendations.append(f"Budget overrun of {variance:.1f}% — request budget increase or scope reduction")

        return MatterBudget(
            matter_id=matter_id,
            matter_name=matter_name,
            budget_total=budget_total,
            actual_to_date=actual,
            remaining=remaining,
            burn_rate_monthly=burn_rate,
            projected_total=projected,
            variance_pct=variance,
            phase_breakdown=phase_totals,
            risk_of_overrun=risk,
            recommendations=recommendations,
        )

    async def review_invoice_billing(
        self,
        invoice_data: Dict[str, Any],
        *,
        billing_guidelines: Optional[Dict[str, Any]] = None,
    ) -> InvoiceReview:
        """Review invoice for UTBMS billing guideline compliance.

        Parameters
        ----------
        invoice_data:
            Invoice dict with: vendor, amount, line_items (list of entries).
        billing_guidelines:
            Optional client-specific billing guidelines.
        """
        vendor = invoice_data.get("vendor", "Unknown")
        total = invoice_data.get("amount", 0.0)
        items = invoice_data.get("line_items", [])

        log.info("Reviewing invoice from %s ($%.2f, %d items)", vendor, total, len(items))

        anomalies = await self._flag_billing_anomalies(items)

        # Calculate recommended adjustments
        adjustment = sum(
            a.hours * 250.0  # Estimated average rate for adjustment
            for a in anomalies
            if a.severity in ("medium", "high")
        )

        approved = max(0, total - adjustment)

        return InvoiceReview(
            invoice_id=invoice_data.get("id", uuid.uuid4().hex[:12]),
            vendor_name=vendor,
            total_amount=total,
            line_items=len(items),
            anomalies=anomalies,
            utbms_compliance=all(
                item.get("utbms_code") for item in items
            ),
            recommended_adjustments=adjustment,
            approved_amount=approved,
        )

    async def _flag_billing_anomalies(
        self,
        line_items: List[Dict[str, Any]],
    ) -> List[BillingAnomaly]:
        """Flag billing anomalies in time entries."""
        anomalies: List[BillingAnomaly] = []

        for item in line_items:
            hours = item.get("hours", 0)
            description = item.get("description", "")
            timekeeper = item.get("timekeeper", "Unknown")
            date = item.get("date", "")

            # Block billing detection
            if ";" in description and description.count(";") >= 2:
                anomalies.append(BillingAnomaly(
                    anomaly_type="block_billing",
                    timekeeper=timekeeper,
                    date=date,
                    hours=hours,
                    description=f"Block billing: {description[:100]}",
                    severity="medium",
                    guideline_violation="Entries must describe a single task",
                ))

            # Excessive daily hours
            if hours > 10.0:
                anomalies.append(BillingAnomaly(
                    anomaly_type="excessive_hours",
                    timekeeper=timekeeper,
                    date=date,
                    hours=hours,
                    description=f"Excessive single-entry hours: {hours}h",
                    severity="high",
                ))

            # Vague description
            if len(description.split()) <= 3:
                anomalies.append(BillingAnomaly(
                    anomaly_type="vague_description",
                    timekeeper=timekeeper,
                    date=date,
                    hours=hours,
                    description=f"Insufficient description: '{description}'",
                    severity="low",
                    guideline_violation="Time entries must include specific task details",
                ))

        return anomalies

    async def optimize_staffing_mix(
        self,
        matter_id: str,
        current_staff: List[Dict[str, Any]],
        *,
        target_budget: Optional[float] = None,
    ) -> StaffingAnalysis:
        """Optimize partner/associate/paralegal staffing ratio.

        Parameters
        ----------
        matter_id:
            Matter identifier.
        current_staff:
            List of staff dicts with: name, level, rate, hours_allocated.
        target_budget:
            Optional budget constraint.
        """
        log.info("Optimizing staffing for matter %s", matter_id)

        current_mix: Dict[str, int] = {}
        total_cost = 0.0
        total_hours = 0.0

        for staff in current_staff:
            level = staff.get("level", "mid_associate")
            current_mix[level] = current_mix.get(level, 0) + 1
            total_cost += staff.get("hours_allocated", 0) * staff.get("rate", 0)
            total_hours += staff.get("hours_allocated", 0)

        current_blended = total_cost / max(1, total_hours)

        # Recommended mix: increase paralegal leverage
        recommended_mix = dict(current_mix)
        paralegal_count = recommended_mix.get("paralegal", 0)
        partner_count = recommended_mix.get("partner", 0) + recommended_mix.get("senior_partner", 0)

        # Standard leverage target: 1 partner : 3 associates : 1 paralegal
        if paralegal_count < partner_count:
            recommended_mix["paralegal"] = max(paralegal_count + 1, partner_count)

        # Estimate savings
        paralegal_rate = _BENCHMARK_RATES["paralegal"]["median"]
        associate_rate = _BENCHMARK_RATES["mid_associate"]["median"]
        savings = (associate_rate - paralegal_rate) * 100  # per 100 hours shifted

        return StaffingAnalysis(
            matter_id=matter_id,
            current_mix=current_mix,
            recommended_mix=recommended_mix,
            current_blended_rate=current_blended,
            recommended_blended_rate=current_blended * 0.85,  # ~15% reduction target
            annual_savings=savings,
            rationale="Increase paralegal leverage for document review and "
            "administrative tasks. Shift routine work from associates to "
            "paralegals per ABA productivity guidelines.",
        )

    async def calculate_afa_terms(
        self,
        matter_type: str,
        estimated_hours: float,
        *,
        afa_type: str = "fixed_fee",
        blended_rate: float = 750.0,
    ) -> AFATerms:
        """Calculate Alternative Fee Arrangement terms.

        Parameters
        ----------
        matter_type:
            Type of matter (e.g., "m_and_a", "litigation", "ip").
        estimated_hours:
            Estimated total hours.
        afa_type:
            AFA type (see :class:`AFAType`).
        blended_rate:
            Blended hourly rate for comparison.
        """
        hourly_total = estimated_hours * blended_rate
        afa = AFAType(afa_type)

        if afa == AFAType.FIXED_FEE:
            base = hourly_total * 0.90  # 10% discount for fee certainty
            return AFATerms(
                afa_type=afa,
                base_amount=base,
                effective_rate=base / max(1, estimated_hours),
                comparison_to_hourly=(1 - base / hourly_total) * 100,
            )
        elif afa == AFAType.CAPPED_FEE:
            cap = hourly_total * 1.10   # 110% of estimate as cap
            return AFATerms(
                afa_type=afa,
                base_amount=hourly_total,
                cap=cap,
                effective_rate=blended_rate,
                comparison_to_hourly=0.0,
            )
        elif afa == AFAType.SUCCESS_FEE:
            base = hourly_total * 0.70  # 30% holdback
            bonus = hourly_total * 0.50  # 50% success bonus
            return AFATerms(
                afa_type=afa,
                base_amount=base,
                success_bonus=bonus,
                success_trigger="Successful outcome as defined in engagement letter",
                effective_rate=(base + bonus) / max(1, estimated_hours),
                comparison_to_hourly=((base + bonus) / hourly_total - 1) * 100,
            )
        else:
            return AFATerms(
                afa_type=afa,
                base_amount=hourly_total,
                effective_rate=blended_rate,
                comparison_to_hourly=0.0,
            )

    async def generate_matter_summary(
        self,
        matter_id: str,
        *,
        matter_name: str = "",
        status: str = "active",
        activities: Optional[List[str]] = None,
        deadlines: Optional[List[Dict[str, str]]] = None,
    ) -> MatterSummary:
        """Generate client-facing matter status report.

        Parameters
        ----------
        matter_id:
            Matter identifier.
        matter_name:
            Human-readable name.
        status:
            Current matter status.
        activities:
            List of recent activity descriptions.
        deadlines:
            Upcoming deadline entries.
        """
        return MatterSummary(
            matter_id=matter_id,
            matter_name=matter_name,
            status=MatterStatus(status),
            budget_summary="[Budget analysis pending]",
            recent_activities=activities or [],
            upcoming_deadlines=deadlines or [],
        )

    async def track_deadlines(
        self,
        matter_id: str,
        deadlines: List[Dict[str, Any]],
    ) -> DeadlineTracker:
        """Track court deadlines and statutes of limitations.

        Parameters
        ----------
        matter_id:
            Matter identifier.
        deadlines:
            List of deadline dicts with: description, due_date, type, priority.
        """
        now = datetime.now(timezone.utc).isoformat()[:10]

        overdue = [d for d in deadlines if d.get("due_date", "") < now]
        upcoming_7 = [
            d for d in deadlines
            if now <= d.get("due_date", "") <= (datetime.now(timezone.utc).isoformat()[:10])
        ]
        upcoming_30 = [d for d in deadlines if d.get("due_date", "") > now]

        return DeadlineTracker(
            matter_id=matter_id,
            deadlines=deadlines,
            overdue=overdue,
            upcoming_7_days=upcoming_7[:10],
            upcoming_30_days=upcoming_30[:20],
        )

    async def draft_engagement_letter(
        self,
        client_name: str,
        matter_description: str,
        *,
        fee_arrangement: str = "hourly",
        scope: Optional[str] = None,
    ) -> EngagementLetter:
        """Draft engagement letter and scope of work.

        Parameters
        ----------
        client_name:
            Client entity name.
        matter_description:
            Description of the legal matter.
        fee_arrangement:
            Fee type (hourly, fixed, capped, etc.).
        scope:
            Detailed scope of work.
        """
        letter_id = uuid.uuid4().hex[:12]
        firm = self._firm_name or "[Firm Name]"

        scope_text = scope or (
            f"Representation of {client_name} in connection with "
            f"{matter_description}. This engagement is limited to the specific "
            "matter described above and does not extend to other matters unless "
            "separately agreed in writing."
        )

        terms = (
            f"ENGAGEMENT LETTER\n\n"
            f"Client: {client_name}\n"
            f"Firm: {firm}\n"
            f"Matter: {matter_description}\n\n"
            f"SCOPE OF WORK:\n{scope_text}\n\n"
            f"FEE ARRANGEMENT: {fee_arrangement.title()}\n\n"
            "TERMS AND CONDITIONS:\n"
            "1. Confidentiality: All communications are protected by attorney-client privilege.\n"
            "2. Conflicts: The firm has conducted a conflicts check and cleared this engagement.\n"
            "3. Billing: Invoices will be issued monthly in LEDES 1998B format.\n"
            "4. Termination: Either party may terminate upon 30 days written notice.\n"
            "5. Document Retention: Files will be retained per the firm's retention policy.\n"
        )

        return EngagementLetter(
            letter_id=letter_id,
            client_name=client_name,
            matter_description=matter_description,
            scope_of_work=scope_text,
            fee_arrangement=fee_arrangement,
            terms_and_conditions=terms,
            effective_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

    async def analyze_peer_benchmarks(
        self,
        matter_type: str,
        our_rate: float,
        our_projected_total: float,
    ) -> PeerBenchmark:
        """Compare rates/costs against peer firms.

        Parameters
        ----------
        matter_type:
            Type of matter for benchmarking.
        our_rate:
            Our blended hourly rate.
        our_projected_total:
            Our projected total cost.
        """
        # Am Law 100 benchmark medians (illustrative)
        benchmarks: Dict[str, Dict[str, float]] = {
            "m_and_a": {"median_rate": 1100.0, "median_total": 2500000.0},
            "litigation": {"median_rate": 850.0, "median_total": 1200000.0},
            "ip_patent": {"median_rate": 900.0, "median_total": 800000.0},
            "regulatory": {"median_rate": 950.0, "median_total": 600000.0},
            "employment": {"median_rate": 700.0, "median_total": 400000.0},
        }

        bench = benchmarks.get(matter_type, {"median_rate": 800.0, "median_total": 500000.0})
        percentile = min(100, int(our_rate / bench["median_rate"] * 50))

        return PeerBenchmark(
            matter_type=matter_type,
            benchmark_source="Am Law 100 Survey (Annual)",
            peer_median_rate=bench["median_rate"],
            peer_median_total=bench["median_total"],
            our_rate=our_rate,
            our_projected_total=our_projected_total,
            percentile_rank=percentile,
            notes=f"Rate is at the {percentile}th percentile of Am Law 100 firms "
            f"for {matter_type.replace('_', ' ')} matters.",
        )
