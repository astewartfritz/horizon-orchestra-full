"""Energy / Utilities vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for grid operations, energy trading,
and sustainability workflows. Designed for energy companies like
ExxonMobil, Duke Energy, NextEra, and similar enterprises.

Agents
------
:class:`GridOperationsAgent`
    Load forecasting, dispatch optimization, outage management,
    renewable integration, and NERC compliance.

:class:`EnergyTradingAgent`
    Power price forecasting, basis spread analysis, portfolio dispatch,
    hedging, and carbon market analytics.

:class:`SustainabilityAgent`
    GHG emissions calculation (Scope 1/2/3), TCFD disclosure, CDP
    response, science-based targets, and ESG reporting.

Pre-Built Teams
---------------
:func:`grid_ops_team`
    Grid operations centre (dispatcher, asset manager, reliability).

:func:`energy_trading_team`
    Energy trading desk (trader, risk analyst, meteorologist).

:func:`sustainability_team`
    Sustainability office (ESG analyst, emissions, reporting).
"""

from __future__ import annotations

from .grid_operations import GridOperationsAgent
from .energy_trading import EnergyTradingAgent
from .sustainability import SustainabilityAgent
from .pre_built_teams import (
    grid_ops_team,
    energy_trading_team,
    sustainability_team,
)

__all__ = [
    "GridOperationsAgent",
    "EnergyTradingAgent",
    "SustainabilityAgent",
    "grid_ops_team",
    "energy_trading_team",
    "sustainability_team",
]
