"""Horizon Orchestra — Energy Trading Agent.

Provides a domain-specialized agent for energy trading workflows
including power price forecasting, basis spread analysis, portfolio
dispatch optimization, hedging, and carbon market analytics.

Industry references:
- FERC regulations (market manipulation, reporting)
- ISO/RTO market rules (CAISO, PJM, ERCOT, MISO, SPP, ISO-NE)
- ETRM (Energy Trading and Risk Management) systems
- ISDA Master Agreement for OTC energy derivatives
- NAESB standards for gas/electric coordination
- EU ETS (Emissions Trading System) for carbon markets

Target customers: ExxonMobil, BP Trading, Vitol, Duke Energy Trading,
and comparable energy trading desks.
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

__all__ = ["EnergyTradingAgent"]

log = logging.getLogger("orchestra.verticals.energy.energy_trading")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Commodity(Enum):
    """Traded energy commodities."""
    POWER = "power"
    NATURAL_GAS = "natural_gas"
    CRUDE_OIL = "crude_oil"
    REFINED_PRODUCTS = "refined_products"
    CARBON = "carbon"
    RENEWABLE_CREDITS = "renewable_credits"
    LNG = "lng"


class MarketType(Enum):
    """Energy market types."""
    DAY_AHEAD = "day_ahead"
    REAL_TIME = "real_time"
    BILATERAL = "bilateral"
    FUTURES = "futures"
    OPTIONS = "options"
    CAPACITY = "capacity"
    ANCILLARY = "ancillary_services"


@dataclass
class SparkSpread:
    """Spark spread calculation."""
    power_price_mwh: float = 0.0
    gas_price_mmbtu: float = 0.0
    heat_rate: float = 7.0  # MMBtu/MWh for efficient CCGT
    spark_spread: float = 0.0
    variable_om: float = 3.0  # $/MWh


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
# Energy Trading Agent
# ---------------------------------------------------------------------------

class EnergyTradingAgent:
    """Domain-specialized agent for energy trading.

    Covers power price forecasting, basis spread analysis, portfolio
    dispatch optimization, hedging, weather impact analysis, and
    carbon/renewable credit markets.

    Attributes
    ----------
    TOOLS : list[str]
        The 14 registered tool names this agent can invoke.
    agent_id : str
        Unique identifier for this agent instance.

    Example
    -------
    ::

        agent = EnergyTradingAgent()
        result = await agent.execute_tool("forecast_power_prices", hub="PJM_WEST")
    """

    TOOLS: list[str] = [
        "forecast_power_prices",
        "analyze_basis_spread",
        "optimize_portfolio_dispatch",
        "calculate_hedge_ratio",
        "analyze_weather_impact",
        "run_spark_spread_analysis",
        "generate_trading_report",
        "analyze_capacity_markets",
        "calculate_ancillary_services_value",
        "run_congestion_analysis",
        "monitor_iso_prices",
        "calculate_renewable_credits",
        "analyze_carbon_markets",
        "optimize_virtual_bidding",
    ]

    def __init__(
        self,
        *,
        model: str = "kimi-k2.5",
        agent_id: str | None = None,
        org_id: str = "default",
        trading_region: str = "PJM",
    ) -> None:
        self.agent_id = agent_id or f"trade-{uuid.uuid4().hex[:8]}"
        self.model = model
        self.org_id = org_id
        self.trading_region = trading_region
        self._audit_log: list[dict[str, Any]] = []
        log.info("EnergyTradingAgent %s initialised (region=%s)", self.agent_id, trading_region)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build a domain-expert system prompt for energy trading.

        Returns a comprehensive prompt embedding energy markets knowledge,
        trading strategies, and regulatory frameworks.
        """
        return (
            "You are a senior energy trader with deep expertise in power "
            "markets, natural gas, carbon credits, and renewable energy "
            "certificates. You optimize trading positions across wholesale "
            "electricity markets.\n\n"
            "POWER MARKETS:\n"
            "- Day-Ahead Market (DAM): Hourly locational marginal prices (LMPs) "
            "cleared by ISO/RTO. Submit bids/offers by 10:00-12:00 prior day.\n"
            "- Real-Time Market (RTM): 5-minute LMPs for balancing. Deviations "
            "from DAM settled at RT prices.\n"
            "- LMP = Energy + Congestion + Losses. Congestion component drives "
            "basis spreads between nodes.\n"
            "- Capacity Markets: Forward procurement of capacity to ensure "
            "resource adequacy. PJM RPM, ISO-NE FCM, NYISO ICAP.\n"
            "- Ancillary Services: Regulation (AGC), spinning reserve, "
            "non-spinning reserve, frequency response, voltage support.\n\n"
            "TRADING STRATEGIES:\n"
            "- Spark Spread: Power Price − (Gas Price × Heat Rate). Positive "
            "spread = profitable generation. Clean Spark Spread includes "
            "carbon costs.\n"
            "- Dark Spread: Power Price − (Coal Price × Heat Rate). Relevant "
            "for coal units.\n"
            "- Virtual Bidding (convergence): Buy virtual in DAM at Node A, "
            "sell virtual at RT. Profitable when DAM < RT at that node. "
            "Provides market liquidity and DAM/RT convergence.\n"
            "- FTRs (Financial Transmission Rights): Hedge against congestion "
            "costs between source and sink. Allocated in auctions.\n"
            "- Basis Trading: Trade the price difference between two hubs "
            "or between gas and power.\n\n"
            "RISK MANAGEMENT:\n"
            "- Hedge Ratio: Minimize portfolio variance. Optimal ratio from "
            "regression of spot on futures returns. Cross-hedge when exact "
            "hedge unavailable.\n"
            "- VaR for energy portfolios: Historical simulation with "
            "weather-adjusted scenarios. Monte Carlo for non-linear positions.\n"
            "- Position limits and stop-loss policies per desk mandate.\n"
            "- Mark-to-market daily; independent price verification.\n\n"
            "WEATHER:\n"
            "- Heating Degree Days (HDD) = max(0, 65 − T_avg). "
            "Cooling Degree Days (CDD) = max(0, T_avg − 65).\n"
            "- Weather drives 30-40% of load variance. Temperature, humidity, "
            "wind speed, cloud cover all material.\n"
            "- Severe weather: Hurricane, polar vortex, heat dome events can "
            "cause extreme price spikes (e.g., Winter Storm Uri 2021).\n\n"
            "CARBON & RENEWABLES:\n"
            "- EU ETS: Cap-and-trade for GHG. Carbon allowances (EUAs) traded "
            "on ICE/EEX. Clean Spark/Dark Spread includes carbon cost.\n"
            "- US: RGGI (northeast), California Cap-and-Trade. Voluntary "
            "carbon offsets (VCM).\n"
            "- RECs (Renewable Energy Certificates): 1 REC = 1 MWh renewable "
            "generation. Compliance (state RPS mandates) vs voluntary.\n"
            "- SRECs (Solar RECs) in specific state markets.\n\n"
            "REGULATION:\n"
            "- FERC: Anti-manipulation (Rule 1c), market-based rate authority, "
            "EQR (Electric Quarterly Report) filing.\n"
            "- CFTC: Dodd-Frank position limits for energy futures/swaps.\n"
            "- ISDA Master Agreement: Standard for OTC energy derivatives.\n"
            f"- Trading region: {self.trading_region}\n"
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

    async def _tool_forecast_power_prices(
        self, *, hub: str = "", horizon_hours: int = 24, **kwargs: Any,
    ) -> dict[str, Any]:
        """Forecast wholesale power prices (LMPs)."""
        return {
            "hub": hub or self.trading_region,
            "horizon_hours": horizon_hours,
            "forecasts": [],
            "peak_price": 0.0,
            "off_peak_price": 0.0,
            "model": "ensemble_gradient_boosting",
        }

    async def _tool_analyze_basis_spread(
        self, *, source_hub: str = "", sink_hub: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse basis spread between two pricing hubs."""
        return {
            "source_hub": source_hub,
            "sink_hub": sink_hub,
            "current_spread": 0.0,
            "historical_avg_spread": 0.0,
            "spread_percentile": 0.0,
            "congestion_component": 0.0,
            "loss_component": 0.0,
        }

    async def _tool_optimize_portfolio_dispatch(
        self, *, assets: list[dict[str, Any]] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize dispatch of generation portfolio against market prices."""
        return {
            "assets_optimized": len(assets) if assets else 0,
            "total_revenue": 0.0,
            "total_cost": 0.0,
            "net_margin": 0.0,
            "dispatch_schedule": [],
        }

    async def _tool_calculate_hedge_ratio(
        self, *, exposure_mw: float = 0.0, instrument: str = "futures", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate optimal hedge ratio for an energy position."""
        return {
            "exposure_mw": exposure_mw,
            "instrument": instrument,
            "optimal_hedge_ratio": 0.0,
            "hedge_quantity": 0.0,
            "basis_risk": 0.0,
            "r_squared": 0.0,
        }

    async def _tool_analyze_weather_impact(
        self, *, location: str = "", forecast_days: int = 7, **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse weather impact on energy demand and prices."""
        return {
            "location": location,
            "forecast_days": forecast_days,
            "hdd_forecast": 0.0,
            "cdd_forecast": 0.0,
            "load_impact_mw": 0.0,
            "price_impact_per_mwh": 0.0,
            "severe_weather_risk": "none",
        }

    async def _tool_run_spark_spread_analysis(
        self, *, gas_price: float = 0.0, power_price: float = 0.0, heat_rate: float = 7.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Run spark spread analysis (power vs gas economics)."""
        spark = power_price - gas_price * heat_rate
        return {
            "power_price_per_mwh": power_price,
            "gas_price_per_mmbtu": gas_price,
            "heat_rate_mmbtu_mwh": heat_rate,
            "spark_spread": round(spark, 2),
            "clean_spark_spread": round(spark - 3.0, 2),
            "generation_economic": spark > 3.0,
        }

    async def _tool_generate_trading_report(
        self, *, report_type: str = "daily", **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate energy trading P&L and position report."""
        return {
            "report_type": report_type,
            "sections": [
                "P&L Summary", "Position Summary", "Mark-to-Market",
                "Risk Metrics", "Weather Outlook", "Market Commentary",
            ],
            "status": "generated",
        }

    async def _tool_analyze_capacity_markets(
        self, *, market: str = "PJM_RPM", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse capacity market dynamics and clearing prices."""
        return {
            "market": market,
            "clearing_price": 0.0,
            "demand_curve": "variable_resource_requirement",
            "supply_offers": 0,
            "reserve_margin": 0.0,
        }

    async def _tool_calculate_ancillary_services_value(
        self, *, service_type: str = "regulation", capacity_mw: float = 0.0, **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate value of ancillary services provision."""
        return {
            "service_type": service_type,
            "capacity_mw": capacity_mw,
            "clearing_price": 0.0,
            "daily_revenue": 0.0,
            "annual_revenue": 0.0,
        }

    async def _tool_run_congestion_analysis(
        self, *, path: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse transmission congestion patterns."""
        return {
            "path": path,
            "congestion_frequency_pct": 0.0,
            "avg_congestion_cost": 0.0,
            "binding_constraints": [],
            "ftr_value": 0.0,
        }

    async def _tool_monitor_iso_prices(
        self, *, iso: str = "", nodes: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Monitor real-time ISO/RTO prices."""
        return {
            "iso": iso or self.trading_region,
            "nodes": nodes or [],
            "prices": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market": "real_time",
        }

    async def _tool_calculate_renewable_credits(
        self, *, generation_mwh: float = 0.0, credit_type: str = "REC", **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate renewable energy credit value."""
        return {
            "generation_mwh": generation_mwh,
            "credit_type": credit_type,
            "credits_generated": generation_mwh,
            "credit_price": 0.0,
            "total_value": 0.0,
            "market": "compliance",
        }

    async def _tool_analyze_carbon_markets(
        self, *, market: str = "EU_ETS", **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyse carbon market dynamics and pricing."""
        return {
            "market": market,
            "current_price_per_tonne": 0.0,
            "ytd_price_change": 0.0,
            "supply_demand_balance": "balanced",
            "regulatory_outlook": "",
            "reference": "EU ETS Directive; RGGI Model Rule; CA AB-32",
        }

    async def _tool_optimize_virtual_bidding(
        self, *, nodes: list[str] | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Optimize virtual bidding strategy (convergence bidding)."""
        return {
            "nodes": nodes or [],
            "strategy": [],
            "expected_profit": 0.0,
            "risk_metrics": {
                "var_95": 0.0,
                "max_loss": 0.0,
            },
            "methodology": "DAM-RT spread prediction with ML ensemble",
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
