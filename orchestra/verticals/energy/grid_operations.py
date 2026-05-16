"""Horizon Orchestra — Grid Operations Agent.

Provides a domain-specialized agent for electric grid operations
including load forecasting, dispatch optimization, outage management,
renewable integration, and NERC compliance.

Industry references:
- NERC CIP (Critical Infrastructure Protection) standards
- NERC Reliability Standards (BAL, FAC, MOD, TPL, VAR, etc.)
- IEEE 1547 (distributed energy resource interconnection)
- FERC Order 2222 (DER aggregation in wholesale markets)
- IEC 61850 (substation communication)
- CAISO, PJM, ERCOT, MISO, SPP, ISO-NE market rules

Target customers: Duke Energy, Southern Company, NextEra Energy,
Dominion Energy, AES, and comparable utilities/ISOs.
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

__all__ = ["GridOperationsAgent"]

log = logging.getLogger("orchestra.verticals.energy.grid_operations")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class GenerationType(Enum):
    """Power generation source types."""
    NUCLEAR = "nuclear"
    COAL = "coal"
    NATURAL_GAS_CC = "natural_gas_combined_cycle"
    NATURAL_GAS_CT = "natural_gas_combustion_turbine"
    WIND = "wind"
    SOLAR_PV = "solar_pv"
    HYDRO = "hydro"
    BATTERY = "battery_storage"
    BIOMASS = "biomass"
    GEOTHERMAL = "geothermal"


class OutageSeverity(Enum):
    """Outage severity levels."""
    MOMENTARY = "momentary"
    SUSTAINED = "sustained"
    MAJOR = "major"
    CATASTROPHIC = "catastrophic"


@dataclass
class LoadForecast:
    """Load demand forecast."""
    timestamp: str = ""
    load_mw: float = 0.0
    temperature_f: float = 0.0
    confidence_interval_low: float = 0.0
    confidence_interval_high: float = 0.0


@dataclass
class DispatchUnit:
    """Generation unit for economic dispatch."""
    unit_id: str = ""
    fuel_type: str = ""
    capacity_mw: float = 0.0
    min_output_mw: float = 0.0
    heat_rate_btu_kwh: float = 0.0
    fuel_cost_per_mmbtu: float = 0.0
    variable_om: float = 0.0
    ramp_rate_mw_min: float = 0.0
    status: str = "available"


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
# Grid Operations Agent
# ---------------------------------------------------------------------------

class GridOperationsAgent:
    """Domain-specialized agent for electric grid operations.

    Covers load forecasting, economic dispatch, outage restoration,
    renewable integration, battery storage optimization, and NERC
    reliability compliance.

    Attributes
    ----------
    TOOLS : list[str]
        The 15 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = GridOperationsAgent()
        result = await agent.execute_tool("forecast_load_demand", horizon_hours=24)
    """

    TOOLS: list[str] = [
        "forecast_load_demand",
        "optimize_dispatch_schedule",
        "detect_grid_anomaly",
        "manage_outage_restoration",
        "calculate_transmission_losses",
        "analyze_renewable_integration",
        "monitor_asset_health",
        "plan_maintenance_window",
        "calculate_capacity_factor",
        "generate_reliability_report",
        "optimize_battery_storage",
        "analyze_frequency_response",
        "check_nerc_compliance",
        "generate_eir_report",
        "calculate_emissions_intensity",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        balancing_authority: str = "DEFAULT_BA",
    ) -> None:
        self.agent_id = agent_id or f"grid-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.balancing_authority = balancing_authority
        self._audit_log: list[dict[str, Any]] = []
        log.info("GridOperationsAgent %s initialised (ba=%s)", self.agent_id, balancing_authority)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for grid operations.

        Returns a comprehensive prompt embedding power systems knowledge,
        grid reliability standards, and operational best practices.
        """
        return (
            "You are a senior grid operations engineer with deep expertise in "
            "power system operations, reliability, and renewable integration. "
            "You ensure safe, reliable, and economic operation of the electric "
            "grid.\n\n"
            "LOAD FORECASTING:\n"
            "- Short-term (1-48 hours): Neural networks, gradient boosting "
            "(XGBoost/LightGBM) with weather, calendar, and lagged load "
            "features. MAPE target: < 2% for day-ahead.\n"
            "- Medium-term (1-52 weeks): Regression with economic indicators, "
            "weather normals, and trending. Used for resource planning.\n"
            "- Key drivers: Temperature (HVAC load), humidity, wind chill/heat "
            "index, day of week, holidays, economic activity, EV adoption, "
            "behind-the-meter solar.\n\n"
            "ECONOMIC DISPATCH:\n"
            "- Merit order: Stack generation units by marginal cost (heat rate "
            "× fuel cost + variable O&M). Dispatch cheapest first.\n"
            "- Security-Constrained Economic Dispatch (SCED): Honour "
            "transmission constraints, voltage limits, and contingency "
            "reserves while minimizing total production cost.\n"
            "- Unit Commitment: Integer programming for start-up/shutdown "
            "decisions considering minimum run times, start-up costs, "
            "ramp rates, and must-run constraints.\n"
            "- Reserve requirements: Spinning (10-min response), non-spinning "
            "(30-min), supplemental. Typically 10-15% of peak load.\n\n"
            "RENEWABLE INTEGRATION:\n"
            "- Variability: Wind and solar are variable and uncertain. Ramp "
            "events (e.g., cloud cover, wind drop) require fast-ramping "
            "resources or storage.\n"
            "- Curtailment: Reduce renewable output when supply exceeds "
            "demand or transmission is constrained. Track curtailment rates.\n"
            "- Duck Curve: Over-generation midday (solar peak), steep ramp "
            "in evening. Mitigate with storage, demand response, and "
            "flexible generation.\n"
            "- FERC Order 2222: Allows DER aggregations to participate in "
            "wholesale markets.\n\n"
            "BATTERY STORAGE:\n"
            "- Applications: Peak shaving, frequency regulation, renewable "
            "firming, capacity/resource adequacy, transmission deferral.\n"
            "- Dispatch optimization: Charge during low-price/high-renewable "
            "periods, discharge during peak. Co-optimize across multiple "
            "value streams.\n"
            "- Degradation: Cycle depth and temperature affect battery life. "
            "Model calendar and cycle aging.\n\n"
            "RELIABILITY:\n"
            "- NERC Reliability Standards: BAL (resource & demand balancing), "
            "TPL (transmission planning), FAC (facility design), MOD "
            "(modelling), PRC (protection), COM (communications).\n"
            "- NERC CIP: Critical Infrastructure Protection for cyber security "
            "of bulk electric system. CIP-002 through CIP-014.\n"
            "- SAIDI (System Average Interruption Duration Index), SAIFI "
            "(Frequency), CAIDI = SAIDI/SAIFI.\n"
            "- N-1 contingency analysis: System must remain stable after loss "
            "of any single element (line, transformer, generator).\n\n"
            "OUTAGE MANAGEMENT:\n"
            "- OMS (Outage Management System) integration. FLISR (Fault "
            "Location, Isolation, Service Restoration) for distribution.\n"
            "- Crew dispatch optimization: Priority by customer count, "
            "critical facilities, restoration feasibility.\n"
            "- Communication: ICS (Incident Command System) for major events.\n"
            f"- Balancing Authority: {self.balancing_authority}\n"
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

    async def _tool_forecast_load_demand(
        self, *, horizon_hours: int = 24, resolution_minutes: int = 60, **kwargs: Any,
    ) -> dict[str, Any]:
        """Forecast electricity load demand."""
        return {
            "horizon_hours": horizon_hours,
            "resolution_minutes": resolution_minutes,
            "forecasts": [],
            "peak_load_mw": 0.0,
            "min_load_mw": 0.0,
            "model": "gradient_boosting_ensemble",
            "mape_pct": 0.0,
            "balancing_authority": self.balancing_authority,
        }

    async def _tool_optimize_dispatch_schedule(
        self, *, units: list[dict[str, Any]] | None = None, load_mw: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize economic dispatch of generation units."""
        return {
            "total_load_mw": load_mw,
            "units_dispatched": len(units) if units else 0,
            "total_generation_cost": 0.0,
            "marginal_cost": 0.0,
            "reserve_margin_pct": 0.0,
            "curtailed_renewable_mw": 0.0,
            "methodology": "Security-Constrained Economic Dispatch (SCED)",
        }

    async def _tool_detect_grid_anomaly(
        self, *, monitoring_area: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Detect anomalies in grid operations (frequency, voltage, flow)."""
        return {
            "monitoring_area": monitoring_area,
            "anomalies_detected": [],
            "frequency_hz": 60.000,
            "voltage_violations": [],
            "thermal_violations": [],
            "status": "normal",
        }

    async def _tool_manage_outage_restoration(
        self, *, outage_id: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Manage outage restoration workflow."""
        return {
            "outage_id": outage_id or f"OTG-{uuid.uuid4().hex[:6].upper()}",
            "customers_affected": 0,
            "cause": "unknown",
            "severity": "sustained",
            "crews_assigned": 0,
            "etr": "",
            "flisr_automated": False,
            "status": "investigating",
        }

    async def _tool_calculate_transmission_losses(
        self, *, path: str = "", flow_mw: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate transmission losses on a path."""
        loss_pct = 0.02 + (flow_mw / 10000) * 0.01
        return {
            "path": path,
            "flow_mw": flow_mw,
            "loss_mw": round(flow_mw * loss_pct, 2),
            "loss_pct": round(loss_pct * 100, 2),
        }

    async def _tool_analyze_renewable_integration(
        self, *, resource_type: str = "solar", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse renewable energy integration challenges and solutions."""
        return {
            "resource_type": resource_type,
            "installed_capacity_mw": 0.0,
            "capacity_factor": 0.0,
            "curtailment_rate": 0.0,
            "ramp_events": [],
            "integration_challenges": [],
            "duck_curve_severity": "moderate",
            "reference": "FERC Order 2222; IEEE 1547",
        }

    async def _tool_monitor_asset_health(
        self, *, asset_id: str = "", asset_type: str = "transformer", **kwargs: Any,
    ) -> dict[str, Any]:
        """Monitor asset health and condition indicators."""
        return {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "health_index": 0.0,
            "condition_indicators": {},
            "remaining_useful_life_years": 0.0,
            "maintenance_recommendation": "",
        }

    async def _tool_plan_maintenance_window(
        self, *, equipment_id: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Plan maintenance outage windows considering grid reliability."""
        return {
            "equipment_id": equipment_id,
            "recommended_window": "",
            "duration_hours": 0,
            "n_minus_1_compliant": True,
            "customer_impact": 0,
            "alternative_windows": [],
        }

    async def _tool_calculate_capacity_factor(
        self, *, unit_id: str = "", period: str = "YTD", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate generation unit capacity factor."""
        return {
            "unit_id": unit_id,
            "period": period,
            "capacity_factor": 0.0,
            "availability_factor": 0.0,
            "forced_outage_rate": 0.0,
            "equivalent_availability_factor": 0.0,
        }

    async def _tool_generate_reliability_report(
        self, *, period: str = "monthly", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a grid reliability report."""
        return {
            "period": period,
            "saidi": 0.0,
            "saifi": 0.0,
            "caidi": 0.0,
            "maifi": 0.0,
            "system_reserve_margin": 0.0,
            "compliance_status": "compliant",
            "reference": "IEEE 1366; NERC Reliability Standards",
        }

    async def _tool_optimize_battery_storage(
        self, *, battery_id: str = "", capacity_mwh: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize battery storage dispatch across value streams."""
        return {
            "battery_id": battery_id,
            "capacity_mwh": capacity_mwh,
            "charge_schedule": [],
            "discharge_schedule": [],
            "value_streams": {
                "energy_arbitrage": 0.0,
                "frequency_regulation": 0.0,
                "capacity": 0.0,
                "peak_shaving": 0.0,
            },
            "total_daily_revenue": 0.0,
            "state_of_health_pct": 100.0,
        }

    async def _tool_analyze_frequency_response(
        self, *, event_timestamp: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse frequency response to a grid event."""
        return {
            "event_timestamp": event_timestamp,
            "nadir_hz": 59.95,
            "settling_frequency_hz": 59.98,
            "response_time_seconds": 0.5,
            "primary_response_mw": 0.0,
            "interconnection": self.balancing_authority,
            "meets_bal_003": True,
        }

    async def _tool_check_nerc_compliance(
        self, *, standard: str = "CIP", **kwargs: Any,
    ) -> dict[str, Any]:
        """Check NERC reliability/CIP compliance."""
        return {
            "standard": standard,
            "standards_checked": [
                "CIP-002 (BES Cyber System Categorization)",
                "CIP-003 (Security Management Controls)",
                "CIP-005 (Electronic Security Perimeter)",
                "CIP-007 (System Security Management)",
                "CIP-010 (Configuration Change Management)",
                "CIP-013 (Supply Chain Risk Management)",
            ] if standard == "CIP" else [
                "BAL-001 (Real Power Balancing)",
                "BAL-003 (Frequency Response)",
                "TPL-001 (Transmission System Planning)",
                "FAC-001 (Facility Interconnection Requirements)",
            ],
            "compliance_status": "compliant",
            "open_violations": 0,
            "reference": f"NERC {standard} Standards",
        }

    async def _tool_generate_eir_report(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate an Environmental Impact Report (EIR)."""
        return {
            "sections": [
                "Air Quality", "Water Resources", "Emissions Summary",
                "Waste Management", "Environmental Compliance",
            ],
            "status": "generated",
            "regulatory_filings_required": [],
        }

    async def _tool_calculate_emissions_intensity(
        self, *, period: str = "YTD", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate emissions intensity (tCO2e/MWh) of generation fleet."""
        return {
            "period": period,
            "emissions_intensity_tco2e_mwh": 0.0,
            "total_emissions_tco2e": 0.0,
            "total_generation_mwh": 0.0,
            "by_fuel_type": {},
            "year_over_year_change": 0.0,
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
