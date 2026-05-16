"""Carrier Management Agent — Carrier relationship and procurement.

AI-powered carrier relationship management covering performance
scoring, rate contract negotiation, new carrier qualification,
RFP analysis, capacity monitoring, and insurance compliance.

Target customers
----------------
- DHL: Subcontractor carrier management
- Ryder: Dedicated carrier fleet procurement
- XPO Logistics: Carrier network optimization
- FedEx / UPS: Partner carrier management
- Maersk: Inland carrier + feeder vessel management
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "CarrierManagementAgent",
    "CarrierScorecard",
    "RateContract",
    "CarrierQualification",
    "RFPAnalysis",
    "CapacityForecast",
    "InsuranceCertificate",
    "CarrierTier",
]

log = logging.getLogger("orchestra.verticals.logistics.carrier_management")

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

class CarrierTier(str, Enum):
    """Carrier tier classification."""
    STRATEGIC = "strategic"     # Top-tier, high volume, preferred
    PRIMARY = "primary"         # Regular, reliable carriers
    SECONDARY = "secondary"     # Backup / overflow carriers
    SPOT = "spot"               # Spot market / one-off
    PROBATION = "probation"     # Under performance review
    INACTIVE = "inactive"       # No longer used


class ContractStatus(str, Enum):
    """Rate contract status."""
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"     # Within 90 days
    EXPIRED = "expired"
    TERMINATED = "terminated"
    UNDER_NEGOTIATION = "under_negotiation"


class InsuranceType(str, Enum):
    """Insurance coverage types."""
    AUTO_LIABILITY = "auto_liability"
    GENERAL_LIABILITY = "general_liability"
    CARGO = "cargo"
    WORKERS_COMP = "workers_comp"
    UMBRELLA = "umbrella"
    HAZMAT = "hazmat"


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CarrierScorecard:
    """Carrier performance scorecard."""
    carrier_id: str
    carrier_name: str
    period: str
    tier: CarrierTier
    overall_score: float = 0.0          # 0-100 weighted composite
    on_time_pickup_pct: float = 0.0
    on_time_delivery_pct: float = 0.0
    claims_ratio_pct: float = 0.0       # Claims $ / revenue $
    damage_rate_pct: float = 0.0
    os_d_rate_pct: float = 0.0          # Over-Short-Damage rate
    tender_acceptance_pct: float = 0.0
    avg_transit_days: float = 0.0
    cost_per_mile: float = 0.0
    total_shipments: int = 0
    total_revenue: float = 0.0
    safety_score: float = 0.0           # FMCSA SMS scores
    eld_compliance: bool = True
    smartway_certified: bool = False
    recommendations: List[str] = field(default_factory=list)


@dataclass
class RateContract:
    """Carrier rate contract."""
    contract_id: str
    carrier_id: str
    carrier_name: str
    status: ContractStatus
    effective_date: str
    expiration_date: str
    lanes: List[Dict[str, Any]] = field(default_factory=list)
    total_committed_volume: int = 0     # Annual shipments
    volume_discount_pct: float = 0.0
    fuel_surcharge_formula: str = ""
    accessorial_schedule: Dict[str, float] = field(default_factory=dict)
    minimum_charge: float = 0.0
    payment_terms: str = "Net 30"
    auto_renew: bool = False


@dataclass
class CarrierQualification:
    """New carrier onboarding qualification."""
    carrier_name: str
    mc_number: str              # Motor Carrier number
    dot_number: str             # USDOT number
    operating_authority: str
    insurance_verified: bool = False
    safety_rating: str = ""     # Satisfactory, Conditional, Unsatisfactory
    csa_scores: Dict[str, float] = field(default_factory=dict)
    years_in_business: int = 0
    fleet_size: int = 0
    equipment_types: List[str] = field(default_factory=list)
    references_checked: bool = False
    qualification_status: str = "pending"    # pending, approved, rejected
    rejection_reason: Optional[str] = None
    notes: str = ""


@dataclass
class RFPAnalysis:
    """Transportation RFP response analysis."""
    rfp_id: str
    lane_count: int
    respondent_count: int
    total_annual_spend: float = 0.0
    responses: List[Dict[str, Any]] = field(default_factory=list)
    recommended_awards: List[Dict[str, Any]] = field(default_factory=list)
    projected_savings_pct: float = 0.0
    projected_savings_amount: float = 0.0
    coverage_pct: float = 0.0           # % of lanes with valid bids


@dataclass
class CapacityForecast:
    """Carrier capacity availability forecast."""
    carrier_id: str
    carrier_name: str
    forecast_period: str
    available_trucks: int = 0
    committed_trucks: int = 0
    utilization_pct: float = 0.0
    capacity_by_lane: Dict[str, int] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class InsuranceCertificate:
    """Certificate of Insurance (COI) tracking."""
    certificate_id: str
    carrier_id: str
    carrier_name: str
    insurance_type: InsuranceType
    coverage_amount: float
    deductible: float = 0.0
    insurer: str = ""
    policy_number: str = ""
    effective_date: str = ""
    expiration_date: str = ""
    compliant: bool = True
    days_until_expiry: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Scorecard weights
# ═══════════════════════════════════════════════════════════════════════════

_SCORECARD_WEIGHTS: Dict[str, float] = {
    "on_time_delivery": 30.0,
    "on_time_pickup": 15.0,
    "claims_ratio": 15.0,
    "tender_acceptance": 15.0,
    "cost_competitiveness": 15.0,
    "safety": 10.0,
}

# Minimum insurance requirements
_INSURANCE_MINIMUMS: Dict[str, float] = {
    "auto_liability": 1_000_000.0,
    "general_liability": 1_000_000.0,
    "cargo": 250_000.0,
    "workers_comp": 500_000.0,
    "umbrella": 5_000_000.0,
}


# ═══════════════════════════════════════════════════════════════════════════
# CarrierManagementAgent
# ═══════════════════════════════════════════════════════════════════════════

class CarrierManagementAgent:
    """Carrier relationship, procurement, and performance management.

    Covers carrier scoring, rate procurement, new carrier qualification,
    RFP analysis, capacity monitoring, and insurance compliance.

    Examples
    --------
    >>> agent = CarrierManagementAgent()
    >>> scorecard = await agent.score_carrier_performance("CARR-001", shipment_data)
    >>> qual = await agent.qualify_new_carrier("Acme Trucking", mc="MC-123456")
    """

    TOOLS = [
        "score_carrier_performance",      # OTP, claims ratio, service quality
        "negotiate_rate_contracts",       # Rate tender analysis + negotiation support
        "qualify_new_carrier",            # Carrier onboarding + vetting
        "manage_carrier_contracts",       # Contract terms + expiry management
        "run_rfp_analysis",               # Transportation RFP response analysis
        "benchmark_market_rates",         # Spot vs contract rate benchmarking
        "monitor_carrier_capacity",       # Capacity availability tracking
        "manage_insurance_certificates",  # COI tracking + compliance
        "generate_scorecard",             # Carrier performance scorecard
        "optimize_carrier_mix",           # Primary/secondary carrier split
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        default_payment_terms: str = "Net 30",
        insurance_requirements: Optional[Dict[str, float]] = None,
    ) -> None:
        self._model = model
        self._payment_terms = default_payment_terms
        self._insurance_req = insurance_requirements or _INSURANCE_MINIMUMS
        self._carriers: Dict[str, Dict[str, Any]] = {}
        self._contracts: Dict[str, RateContract] = {}
        log.info("CarrierManagementAgent initialized (model=%s)", model)

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for carrier management."""
        return (
            "You are an expert carrier management and transportation procurement agent "
            "supporting enterprise shippers and 3PLs (DHL, Ryder, XPO, FedEx, UPS).\n\n"
            "CARRIER PERFORMANCE:\n"
            "- Weighted scorecard: OTD (30%), OTP (15%), Claims (15%), "
            "Tender Accept (15%), Cost (15%), Safety (10%)\n"
            "- FMCSA SMS/CSA scores: Unsafe Driving, HOS, Vehicle Maintenance, "
            "Controlled Substances, Hazmat, Crash Indicator\n"
            "- EPA SmartWay certification for sustainability goals\n"
            "- ELD mandate compliance verification\n\n"
            "RATE PROCUREMENT:\n"
            "- Annual bid / RFP process management\n"
            "- Lane-level rate analysis (origin-destination pairs)\n"
            "- Fuel surcharge formulas (DOE national average diesel)\n"
            "- Accessorial charges: detention ($75-$100/hr after 2h free), "
            "lumper ($150-$300), TONU ($250-$350), reweigh ($50)\n"
            "- Market rate benchmarking (DAT, Greenscreens, Chainalytics)\n\n"
            "CARRIER QUALIFICATION:\n"
            "- MC/DOT number verification via FMCSA SAFER\n"
            "- Operating authority (common, contract, broker)\n"
            "- Safety rating (Satisfactory, Conditional, Unsatisfactory)\n"
            "- Insurance verification: auto ($1M), GL ($1M), cargo ($250K)\n"
            "- References, financial stability, fleet size, equipment\n\n"
            "CONTRACT MANAGEMENT:\n"
            "- Rate contract terms: effective/expiry dates, volume commitments\n"
            "- Auto-renewal and termination provisions\n"
            "- Payment terms: Net 30 standard, quick pay discounts (2% Net 10)\n"
            "- Indemnification, liability caps, insurance requirements\n\n"
            "CAPACITY MANAGEMENT:\n"
            "- Primary carrier: 70-80% of volume\n"
            "- Secondary carrier: 15-25% of volume (backup)\n"
            "- Spot market: 5-10% (overflow / surge)\n"
            "- Seasonal capacity planning (Q4 peak, produce season)\n"
        )

    # -------------------------------------------------------------------
    # Core carrier management methods
    # -------------------------------------------------------------------

    async def score_carrier_performance(
        self,
        carrier_id: str,
        shipment_data: List[Dict[str, Any]],
        *,
        period: str = "",
    ) -> CarrierScorecard:
        """Calculate carrier performance scorecard.

        Parameters
        ----------
        carrier_id:
            Carrier identifier.
        shipment_data:
            List of shipment dicts with: on_time_pickup, on_time_delivery,
            claim_amount, revenue, transit_days.
        period:
            Reporting period.
        """
        log.info("Scoring carrier %s (%d shipments)", carrier_id, len(shipment_data))

        total = max(1, len(shipment_data))
        otp = sum(1 for s in shipment_data if s.get("on_time_pickup", True)) / total * 100
        otd = sum(1 for s in shipment_data if s.get("on_time_delivery", True)) / total * 100
        total_claims = sum(s.get("claim_amount", 0) for s in shipment_data)
        total_revenue = sum(s.get("revenue", 0) for s in shipment_data)
        claims_ratio = (total_claims / max(1, total_revenue)) * 100
        avg_transit = sum(s.get("transit_days", 0) for s in shipment_data) / total

        # Weighted score
        score = (
            otd * _SCORECARD_WEIGHTS["on_time_delivery"] / 100
            + otp * _SCORECARD_WEIGHTS["on_time_pickup"] / 100
            + max(0, 100 - claims_ratio * 10) * _SCORECARD_WEIGHTS["claims_ratio"] / 100
            + 80 * _SCORECARD_WEIGHTS["tender_acceptance"] / 100  # Default 80%
            + 70 * _SCORECARD_WEIGHTS["cost_competitiveness"] / 100
            + 85 * _SCORECARD_WEIGHTS["safety"] / 100
        )

        # Tier assignment
        if score >= 85:
            tier = CarrierTier.STRATEGIC
        elif score >= 70:
            tier = CarrierTier.PRIMARY
        elif score >= 55:
            tier = CarrierTier.SECONDARY
        else:
            tier = CarrierTier.PROBATION

        recommendations: List[str] = []
        if otd < 95:
            recommendations.append(f"On-time delivery at {otd:.1f}% — target 95%+")
        if claims_ratio > 1.0:
            recommendations.append(f"Claims ratio at {claims_ratio:.2f}% — investigate root causes")

        return CarrierScorecard(
            carrier_id=carrier_id,
            carrier_name=self._carriers.get(carrier_id, {}).get("name", carrier_id),
            period=period or datetime.now(timezone.utc).strftime("%Y-Q%q").replace("%q", str((datetime.now().month - 1) // 3 + 1)),
            tier=tier,
            overall_score=round(score, 1),
            on_time_pickup_pct=round(otp, 1),
            on_time_delivery_pct=round(otd, 1),
            claims_ratio_pct=round(claims_ratio, 2),
            avg_transit_days=round(avg_transit, 1),
            total_shipments=len(shipment_data),
            total_revenue=round(total_revenue, 2),
            recommendations=recommendations,
        )

    async def qualify_new_carrier(
        self,
        carrier_name: str,
        *,
        mc_number: str = "",
        dot_number: str = "",
        fleet_size: int = 0,
        equipment: Optional[List[str]] = None,
    ) -> CarrierQualification:
        """Qualify and onboard a new carrier.

        Parameters
        ----------
        carrier_name:
            Carrier company name.
        mc_number:
            Motor Carrier number (MC-XXXXXX).
        dot_number:
            USDOT number.
        fleet_size:
            Number of power units.
        equipment:
            Equipment types available.
        """
        log.info("Qualifying carrier: %s (MC=%s, DOT=%s)", carrier_name, mc_number, dot_number)

        # FMCSA SAFER system verification (mock)
        safety_rating = "Satisfactory" if mc_number else "Not Rated"

        # CSA scores (mock — real implementation queries FMCSA SMS API)
        csa_scores: Dict[str, float] = {
            "unsafe_driving": 0.0,
            "hours_of_service": 0.0,
            "vehicle_maintenance": 0.0,
            "controlled_substances": 0.0,
            "hazmat": 0.0,
            "crash_indicator": 0.0,
        }

        # Qualification decision
        qualified = bool(mc_number and safety_rating == "Satisfactory")

        return CarrierQualification(
            carrier_name=carrier_name,
            mc_number=mc_number,
            dot_number=dot_number,
            operating_authority="Common" if mc_number else "Unknown",
            insurance_verified=False,  # Requires COI submission
            safety_rating=safety_rating,
            csa_scores=csa_scores,
            fleet_size=fleet_size,
            equipment_types=equipment or [],
            qualification_status="approved" if qualified else "pending",
            notes="Pending insurance verification" if qualified else "MC/DOT verification needed",
        )

    async def run_rfp_analysis(
        self,
        rfp_responses: List[Dict[str, Any]],
        *,
        lanes: Optional[List[Dict[str, Any]]] = None,
        annual_volume: int = 0,
    ) -> RFPAnalysis:
        """Analyze transportation RFP responses.

        Parameters
        ----------
        rfp_responses:
            List of carrier RFP response dicts with: carrier, lanes (with rates).
        lanes:
            Lane definitions with: origin, destination, volume.
        annual_volume:
            Total annual shipment volume.
        """
        rfp_id = uuid.uuid4().hex[:12]
        log.info("Analyzing RFP %s (%d responses)", rfp_id, len(rfp_responses))

        lane_count = len(lanes) if lanes else 0
        total_spend = 0.0
        recommended: List[Dict[str, Any]] = []

        for response in rfp_responses:
            carrier = response.get("carrier", "")
            carrier_lanes = response.get("lanes", [])
            for lane in carrier_lanes:
                rate = lane.get("rate", 0.0)
                volume = lane.get("volume", 0)
                total_spend += rate * volume

        # Simple lowest-cost award recommendation
        for response in sorted(rfp_responses, key=lambda r: sum(
            l.get("rate", 0) for l in r.get("lanes", [])
        )):
            recommended.append({
                "carrier": response.get("carrier", ""),
                "lanes_awarded": len(response.get("lanes", [])),
                "total_commitment": sum(
                    l.get("rate", 0) * l.get("volume", 0)
                    for l in response.get("lanes", [])
                ),
            })

        return RFPAnalysis(
            rfp_id=rfp_id,
            lane_count=lane_count,
            respondent_count=len(rfp_responses),
            total_annual_spend=round(total_spend, 2),
            responses=rfp_responses,
            recommended_awards=recommended,
            projected_savings_pct=5.0,  # Typical RFP savings target
            projected_savings_amount=round(total_spend * 0.05, 2),
            coverage_pct=100.0 if rfp_responses else 0.0,
        )

    async def monitor_carrier_capacity(
        self,
        carrier_id: str,
        *,
        forecast_period: str = "",
    ) -> CapacityForecast:
        """Monitor carrier capacity availability.

        Parameters
        ----------
        carrier_id:
            Carrier to monitor.
        forecast_period:
            Period for forecast.
        """
        return CapacityForecast(
            carrier_id=carrier_id,
            carrier_name=self._carriers.get(carrier_id, {}).get("name", carrier_id),
            forecast_period=forecast_period or datetime.now(timezone.utc).strftime("%Y-%m"),
            available_trucks=0,
            committed_trucks=0,
            utilization_pct=0.0,
            confidence=0.5,
        )

    async def manage_insurance_certificates(
        self,
        carrier_id: str,
        certificates: List[Dict[str, Any]],
    ) -> List[InsuranceCertificate]:
        """Track and validate insurance certificates (COIs).

        Parameters
        ----------
        carrier_id:
            Carrier identifier.
        certificates:
            List of COI dicts with: type, coverage, expiration, insurer, policy_number.
        """
        results: List[InsuranceCertificate] = []

        for cert in certificates:
            ins_type = InsuranceType(cert.get("type", "auto_liability"))
            coverage = cert.get("coverage", 0.0)
            minimum = self._insurance_req.get(ins_type.value, 0.0)
            compliant = coverage >= minimum

            expiry = cert.get("expiration", "")
            days_left = 0
            if expiry:
                try:
                    exp_date = datetime.fromisoformat(expiry)
                    days_left = (exp_date - datetime.now(timezone.utc)).days
                except (ValueError, TypeError):
                    days_left = 0

            results.append(InsuranceCertificate(
                certificate_id=uuid.uuid4().hex[:10],
                carrier_id=carrier_id,
                carrier_name="",
                insurance_type=ins_type,
                coverage_amount=coverage,
                insurer=cert.get("insurer", ""),
                policy_number=cert.get("policy_number", ""),
                effective_date=cert.get("effective", ""),
                expiration_date=expiry,
                compliant=compliant,
                days_until_expiry=days_left,
            ))

        return results

    async def optimize_carrier_mix(
        self,
        lanes: List[Dict[str, Any]],
        carriers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Optimize primary/secondary carrier split.

        Parameters
        ----------
        lanes:
            Lane definitions with volume.
        carriers:
            Available carriers with performance and rate data.
        """
        log.info("Optimizing carrier mix for %d lanes, %d carriers", len(lanes), len(carriers))

        # Target allocation: 75% primary, 20% secondary, 5% spot
        total_volume = sum(l.get("volume", 0) for l in lanes)

        allocation = {
            "primary": {"target_pct": 75.0, "volume": int(total_volume * 0.75)},
            "secondary": {"target_pct": 20.0, "volume": int(total_volume * 0.20)},
            "spot": {"target_pct": 5.0, "volume": int(total_volume * 0.05)},
        }

        return {
            "total_volume": total_volume,
            "lane_count": len(lanes),
            "carrier_count": len(carriers),
            "allocation": allocation,
            "recommendation": (
                "Concentrate 75% of volume with top 2-3 strategic carriers "
                "to leverage volume discounts. Maintain 20% with secondary carriers "
                "for competitive pressure and backup capacity."
            ),
        }

    async def generate_scorecard(
        self,
        carrier_id: str,
        *,
        period: str = "",
    ) -> CarrierScorecard:
        """Generate formatted carrier performance scorecard.

        Parameters
        ----------
        carrier_id:
            Carrier identifier.
        period:
            Reporting period.
        """
        # Use cached data or generate empty scorecard
        return CarrierScorecard(
            carrier_id=carrier_id,
            carrier_name=self._carriers.get(carrier_id, {}).get("name", carrier_id),
            period=period,
            tier=CarrierTier.PRIMARY,
            overall_score=0.0,
        )

    async def benchmark_market_rates(
        self,
        lanes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Benchmark contract rates against spot market.

        Parameters
        ----------
        lanes:
            Lanes with current contract rates.
        """
        log.info("Benchmarking %d lanes against market rates", len(lanes))

        benchmarks: List[Dict[str, Any]] = []
        for lane in lanes:
            contract_rate = lane.get("contract_rate", 0.0)
            # Simplified spot rate estimation
            spot_rate = contract_rate * 1.15  # Spot typically 10-20% higher
            benchmarks.append({
                "origin": lane.get("origin", ""),
                "destination": lane.get("destination", ""),
                "contract_rate": contract_rate,
                "estimated_spot_rate": round(spot_rate, 2),
                "savings_vs_spot_pct": round((1 - contract_rate / max(1, spot_rate)) * 100, 1),
            })

        return {
            "lanes_benchmarked": len(benchmarks),
            "avg_savings_vs_spot_pct": round(
                sum(b["savings_vs_spot_pct"] for b in benchmarks) / max(1, len(benchmarks)), 1,
            ),
            "lanes": benchmarks,
        }
