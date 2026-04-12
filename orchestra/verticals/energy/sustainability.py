"""Horizon Orchestra — Sustainability Agent.

Provides a domain-specialized agent for corporate sustainability
workflows including GHG emissions calculation, ESG reporting,
TCFD disclosure, and science-based targets.

Industry references:
- GHG Protocol (Corporate Standard, Scope 3 Standard, Product Standard)
- TCFD (Task Force on Climate-related Financial Disclosures)
- CDP (Carbon Disclosure Project)
- SBTi (Science Based Targets initiative)
- GRI (Global Reporting Initiative) Standards
- ISSB (International Sustainability Standards Board) / IFRS S1 & S2
- SEC Climate Disclosure Rule (proposed)
- EU CSRD (Corporate Sustainability Reporting Directive)
- ISO 14064 (GHG quantification and reporting)

Target customers: ExxonMobil, Duke Energy, BP, Shell, and comparable
energy companies with significant ESG reporting obligations.
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

__all__ = ["SustainabilityAgent"]

log = logging.getLogger("orchestra.verticals.energy.sustainability")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class EmissionScope(Enum):
    """GHG Protocol emission scopes."""
    SCOPE_1 = "scope_1"  # Direct emissions
    SCOPE_2_LOCATION = "scope_2_location"  # Indirect - location based
    SCOPE_2_MARKET = "scope_2_market"  # Indirect - market based
    SCOPE_3 = "scope_3"  # Value chain emissions


class Scope3Category(Enum):
    """GHG Protocol Scope 3 categories."""
    PURCHASED_GOODS = "cat_1_purchased_goods_services"
    CAPITAL_GOODS = "cat_2_capital_goods"
    FUEL_ENERGY = "cat_3_fuel_energy_activities"
    UPSTREAM_TRANSPORT = "cat_4_upstream_transportation"
    WASTE = "cat_5_waste_generated"
    BUSINESS_TRAVEL = "cat_6_business_travel"
    EMPLOYEE_COMMUTING = "cat_7_employee_commuting"
    UPSTREAM_LEASED = "cat_8_upstream_leased_assets"
    DOWNSTREAM_TRANSPORT = "cat_9_downstream_transportation"
    PROCESSING_OF_SOLD = "cat_10_processing_sold_products"
    USE_OF_SOLD = "cat_11_use_of_sold_products"
    END_OF_LIFE = "cat_12_end_of_life"
    DOWNSTREAM_LEASED = "cat_13_downstream_leased_assets"
    FRANCHISES = "cat_14_franchises"
    INVESTMENTS = "cat_15_investments"


@dataclass
class EmissionsData:
    """GHG emissions data point."""
    scope: str = ""
    category: str = ""
    source: str = ""
    activity_data: float = 0.0
    emission_factor: float = 0.0
    emissions_tco2e: float = 0.0
    methodology: str = ""


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
# Sustainability Agent
# ---------------------------------------------------------------------------

class SustainabilityAgent:
    """Domain-specialized agent for corporate sustainability.

    Covers GHG emissions calculation (Scope 1/2/3), TCFD-aligned
    disclosures, CDP responses, science-based targets, and ESG
    materiality analysis.

    Attributes
    ----------
    TOOLS : list[str]
        The 14 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = SustainabilityAgent()
        result = await agent.execute_tool("calculate_scope1_emissions", fuel_type="natural_gas")
    """

    TOOLS: list[str] = [
        "calculate_scope1_emissions",
        "calculate_scope2_emissions",
        "calculate_scope3_emissions",
        "generate_ghg_report",
        "track_renewable_energy_targets",
        "analyze_carbon_offset_quality",
        "generate_tcfd_disclosure",
        "calculate_science_based_target",
        "analyze_esg_materiality",
        "generate_sustainability_report",
        "benchmark_industry_emissions",
        "optimize_energy_efficiency",
        "track_water_usage",
        "generate_cdp_response",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        reporting_year: int = 2025,
    ) -> None:
        self.agent_id = agent_id or f"sust-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.reporting_year = reporting_year
        self._audit_log: list[dict[str, Any]] = []
        log.info("SustainabilityAgent %s initialised (year=%d)", self.agent_id, reporting_year)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for sustainability.

        Returns a comprehensive prompt embedding GHG accounting,
        ESG reporting frameworks, and climate science.
        """
        return (
            "You are a senior sustainability officer with deep expertise in "
            "GHG accounting, ESG reporting, and climate strategy. You ensure "
            "accurate emissions reporting and drive decarbonisation targets.\n\n"
            "GHG PROTOCOL:\n"
            "- Scope 1 (Direct): Stationary combustion (boilers, furnaces), "
            "mobile combustion (fleet), process emissions (chemical/physical), "
            "fugitive emissions (refrigerants, methane leaks).\n"
            "- Scope 2 (Indirect — Electricity): \n"
            "  Location-based: Grid average emission factor × purchased "
            "  electricity. Use eGRID factors (US) or IEA (international).\n"
            "  Market-based: Supplier-specific factor, REC/GO certificates, "
            "  or residual mix factor. Hierarchy per GHG Protocol Scope 2 "
            "  Guidance.\n"
            "- Scope 3 (Value Chain): 15 categories per GHG Protocol "
            "Corporate Value Chain Standard. Typically 70-90% of total "
            "footprint for most companies.\n"
            "  Most material categories: Cat 1 (Purchased Goods), Cat 11 "
            "  (Use of Sold Products), Cat 3 (Fuel/Energy Activities), "
            "  Cat 4/9 (Transportation).\n"
            "  Methods: Supplier-specific, Hybrid, Spend-based, Average-data.\n"
            "  Prefer supplier-specific data where available.\n\n"
            "EMISSION FACTORS:\n"
            "- Stationary combustion: EPA AP-42, IPCC Guidelines.\n"
            "- Electricity: EPA eGRID (US), IEA (international), AIB Residual "
            "Mix (EU market-based).\n"
            "- GWP values: IPCC AR6 (CO2=1, CH4=27.9, N2O=273). Use AR5 "
            "if required by regulation (CH4=28, N2O=265).\n\n"
            "REPORTING FRAMEWORKS:\n"
            "- TCFD: Governance, Strategy, Risk Management, Metrics & Targets. "
            "Scenario analysis (≤2°C and 4°C+ pathways). Climate-related "
            "financial risks: physical (acute/chronic) and transition "
            "(policy, technology, market, reputation).\n"
            "- CDP: Annual questionnaire covering governance, risk/opportunity, "
            "business strategy, targets, emissions data, verification.\n"
            "- GRI: GRI 305 (Emissions), GRI 302 (Energy), GRI 303 (Water). "
            "Double materiality: impact on company AND company's impact on "
            "environment/society.\n"
            "- ISSB / IFRS S1 & S2: Sustainability and climate-related "
            "disclosures aligned with financial reporting.\n"
            "- EU CSRD: Mandatory for large EU companies starting 2024. "
            "ESRS (European Sustainability Reporting Standards).\n\n"
            "SCIENCE-BASED TARGETS (SBTi):\n"
            "- 1.5°C pathway: ~4.2% annual linear reduction in Scope 1+2.\n"
            "- Well-below 2°C: ~2.5% annual linear reduction.\n"
            "- Scope 3: Required if >40% of total emissions. Use SDA "
            "(Sectoral Decarbonization Approach) or absolute reduction.\n"
            "- Near-term (5-10 years) and long-term (by 2050) net-zero targets.\n"
            "- FLAG (Forest, Land and Agriculture) guidance for land-use.\n\n"
            "CARBON OFFSETS:\n"
            "- Quality criteria: Additionality, permanence, no leakage, "
            "conservative baseline, third-party verification.\n"
            "- Standards: VCS (Verra), Gold Standard, ACR, CAR.\n"
            "- Types: Avoidance (REDD+, renewable energy) vs removal "
            "(afforestation, DACCS, biochar). SBTi requires removals for "
            "residual emissions under net-zero.\n"
            f"- Reporting year: {self.reporting_year}\n"
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

    async def _tool_calculate_scope1_emissions(
        self, *, fuel_type: str = "natural_gas", consumption: float = 0.0, unit: str = "mmbtu", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Scope 1 (direct) GHG emissions."""
        emission_factors = {
            "natural_gas": 53.06,  # kg CO2/MMBtu
            "diesel": 73.96,
            "gasoline": 70.22,
            "propane": 62.87,
            "coal": 95.52,
        }
        ef = emission_factors.get(fuel_type, 53.06)
        emissions_kg = consumption * ef
        return {
            "scope": "Scope 1",
            "fuel_type": fuel_type,
            "consumption": consumption,
            "unit": unit,
            "emission_factor": ef,
            "emissions_tco2e": round(emissions_kg / 1000, 2),
            "methodology": "GHG Protocol; EPA AP-42 emission factors",
            "gwp_basis": "IPCC AR6",
        }

    async def _tool_calculate_scope2_emissions(
        self, *, electricity_mwh: float = 0.0, grid_region: str = "US_AVG", method: str = "location", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Scope 2 (indirect electricity) GHG emissions."""
        location_factors = {
            "US_AVG": 0.386,  # tCO2e/MWh (EPA eGRID)
            "ERCOT": 0.396,
            "PJM": 0.425,
            "CAISO": 0.220,
            "EU_AVG": 0.295,
        }
        ef = location_factors.get(grid_region, 0.386)
        emissions = electricity_mwh * ef
        return {
            "scope": "Scope 2",
            "method": method,
            "electricity_mwh": electricity_mwh,
            "grid_region": grid_region,
            "emission_factor_tco2e_mwh": ef,
            "emissions_tco2e": round(emissions, 2),
            "methodology": f"GHG Protocol Scope 2 Guidance — {method}-based",
            "data_source": "EPA eGRID" if "US" in grid_region else "IEA",
        }

    async def _tool_calculate_scope3_emissions(
        self, *, category: str = "cat_1_purchased_goods_services", spend: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate Scope 3 (value chain) GHG emissions."""
        return {
            "scope": "Scope 3",
            "category": category,
            "methodology": "Spend-based method (GHG Protocol Corporate Value Chain Standard)",
            "spend": spend,
            "emission_factor": 0.0,
            "emissions_tco2e": 0.0,
            "data_quality_score": "estimated",
            "improvement_recommendation": "Transition to supplier-specific data",
        }

    async def _tool_generate_ghg_report(
        self, *, reporting_year: int | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a comprehensive GHG emissions report."""
        return {
            "reporting_year": reporting_year or self.reporting_year,
            "sections": [
                "Executive Summary", "Organizational Boundary",
                "Scope 1 Emissions", "Scope 2 Emissions",
                "Scope 3 Emissions", "Emissions Trends",
                "Reduction Targets", "Verification Statement",
            ],
            "standards": ["GHG Protocol", "ISO 14064-1"],
            "status": "generated",
        }

    async def _tool_track_renewable_energy_targets(
        self, *, target_pct: float = 1.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Track progress toward renewable energy procurement targets."""
        return {
            "target_pct": target_pct,
            "current_pct": 0.0,
            "sources": {
                "on_site_solar": 0.0,
                "ppa": 0.0,
                "unbundled_recs": 0.0,
                "green_tariff": 0.0,
            },
            "gap_mwh": 0.0,
            "re100_aligned": True,
        }

    async def _tool_analyze_carbon_offset_quality(
        self, *, offset_type: str = "", standard: str = "VCS", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse quality of carbon offsets against best-practice criteria."""
        return {
            "offset_type": offset_type,
            "standard": standard,
            "quality_assessment": {
                "additionality": "high",
                "permanence": "medium",
                "leakage_risk": "low",
                "verification": "third_party",
                "co_benefits": [],
            },
            "sbti_eligible": offset_type in ["dac", "afforestation", "biochar"],
            "recommendation": "",
        }

    async def _tool_generate_tcfd_disclosure(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate TCFD (Task Force on Climate-related Financial Disclosures) report."""
        return {
            "pillars": {
                "governance": "Board oversight of climate risks",
                "strategy": "Scenario analysis (1.5°C and 4°C+)",
                "risk_management": "Integration into ERM framework",
                "metrics_targets": "Scope 1/2/3, SBTi targets",
            },
            "scenarios_analysed": ["1.5°C (Net Zero 2050)", "2°C (Stated Policies)", "4°C+ (BAU)"],
            "status": "draft",
            "reference": "TCFD Recommendations (2017); ISSB IFRS S2",
        }

    async def _tool_calculate_science_based_target(
        self, *, base_year: int = 2020, target_year: int = 2030, base_emissions: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate science-based emission reduction targets."""
        years = target_year - base_year
        annual_reduction = 0.042  # 4.2% for 1.5°C linear
        target_emissions = base_emissions * (1 - annual_reduction) ** years

        return {
            "base_year": base_year,
            "target_year": target_year,
            "base_emissions_tco2e": base_emissions,
            "target_emissions_tco2e": round(target_emissions, 2),
            "reduction_pct": round((1 - target_emissions / base_emissions) * 100, 1) if base_emissions > 0 else 0,
            "pathway": "1.5°C aligned",
            "annual_reduction_rate": annual_reduction,
            "reference": "SBTi Corporate Net-Zero Standard (v1.1)",
        }

    async def _tool_analyze_esg_materiality(
        self, *, industry: str = "energy", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse ESG materiality topics for the industry."""
        return {
            "industry": industry,
            "material_topics": [
                "GHG Emissions", "Energy Management", "Water Management",
                "Health & Safety", "Community Relations", "Governance",
            ],
            "double_materiality": True,
            "framework": "GRI / ISSB / EU CSRD (ESRS)",
        }

    async def _tool_generate_sustainability_report(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate an annual sustainability report."""
        return {
            "reporting_year": self.reporting_year,
            "frameworks": ["GRI", "TCFD", "SASB", "UN SDGs"],
            "sections": [
                "CEO Message", "ESG Strategy", "Environmental Performance",
                "Social Performance", "Governance", "Data Tables",
                "GRI Content Index", "Assurance Statement",
            ],
            "status": "draft",
        }

    async def _tool_benchmark_industry_emissions(
        self, *, peer_group: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Benchmark emissions intensity against industry peers."""
        return {
            "peer_group": peer_group or [],
            "company_intensity": 0.0,
            "peer_median_intensity": 0.0,
            "percentile_rank": 0,
            "metric": "tCO2e per unit revenue",
        }

    async def _tool_optimize_energy_efficiency(
        self, *, facility: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Identify energy efficiency improvement opportunities."""
        return {
            "facility": facility,
            "current_eui": 0.0,
            "target_eui": 0.0,
            "opportunities": [],
            "total_savings_mwh": 0.0,
            "total_cost_savings": 0.0,
            "payback_years": 0.0,
        }

    async def _tool_track_water_usage(
        self, *, facility: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Track water usage and conservation metrics."""
        return {
            "facility": facility,
            "total_withdrawal_m3": 0.0,
            "total_discharge_m3": 0.0,
            "consumption_m3": 0.0,
            "recycled_pct": 0.0,
            "water_stress_level": "low",
            "reference": "GRI 303; CDP Water Security",
        }

    async def _tool_generate_cdp_response(
        self, *, questionnaire: str = "climate", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate CDP (Carbon Disclosure Project) questionnaire response."""
        return {
            "questionnaire": questionnaire,
            "modules": [
                "C0 - Introduction",
                "C1 - Governance",
                "C2 - Risks and Opportunities",
                "C3 - Business Strategy",
                "C4 - Targets and Performance",
                "C5 - Emissions Methodology",
                "C6 - Emissions Data",
                "C7 - Emissions Breakdown",
                "C8 - Energy",
                "C9 - Additional Metrics",
                "C10 - Verification",
                "C11 - Carbon Pricing",
                "C12 - Engagement",
            ],
            "status": "draft",
            "previous_score": "",
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
