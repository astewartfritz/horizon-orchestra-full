"""Horizon Orchestra — Energy Pre-Built Teams.

Production-ready team factories for energy/utilities workflows.

Teams
-----
:func:`grid_ops_team`
    Grid operations centre (dispatcher, asset manager, reliability).

:func:`energy_trading_team`
    Energy trading desk (trader, risk analyst, meteorologist).

:func:`sustainability_team`
    Sustainability office (ESG analyst, emissions, reporting).
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "grid_ops_team",
    "energy_trading_team",
    "sustainability_team",
]

log = logging.getLogger("orchestra.verticals.energy.pre_built_teams")

try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
    from orchestra.teams.context_bus import ContextBus
    from orchestra.teams.team_memory import TeamMemory
    from orchestra.teams.inter_agent_trust import InterAgentTrust, TrustLevel
    _HAS_TEAMS = True
except ImportError:
    _HAS_TEAMS = False


def _check_teams() -> None:
    if not _HAS_TEAMS:
        raise RuntimeError(
            "orchestra.teams is required for pre-built teams. "
            "Install with: pip install horizon-orchestra[teams]"
        )


def _add_specialist_sync(
    team: "OrchestraTeam",
    name: str,
    capabilities: list[str],
    arch: str = "A",
    model: str = "kimi-k2.5",
    connectors: list[str] | None = None,
    trust_level: str = "team",
    org_id: str = "default",
) -> "Specialist":
    """Synchronously create and register a Specialist."""
    import uuid
    connectors = connectors or []

    spec = Specialist(
        name=name,
        capabilities=capabilities,
        architecture=arch,
        model=model,
        connectors=connectors,
        trust_level=trust_level,
        org_id=org_id,
    )

    team._specialists[spec.agent_id] = spec
    team._bus.register_agent(spec.agent_id)

    if team._trust is not None:
        team._trust.register_agent(
            spec.agent_id,
            trust_level=TrustLevel.from_string(trust_level),
            org_id=org_id,
        )

    return spec


# ===========================================================================
# Grid Operations Team
# ===========================================================================

def grid_ops_team(
    name: str = "grid-ops",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a grid operations team.

    Specialists
    -----------
    - **dispatcher** — Load forecasting, economic dispatch, outage
      management, renewable integration, grid balancing.
    - **asset-manager** — Asset health monitoring, maintenance planning,
      capacity factor analysis, equipment lifecycle.
    - **reliability-engineer** — NERC compliance, frequency response,
      contingency analysis, reliability reporting.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    _check_teams()

    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=6,
        max_concurrent_tasks=30,
        architecture="E",
        context_bus_capacity=10_000,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team,
        name="dispatcher",
        capabilities=[
            "load-forecasting", "economic-dispatch", "outage-management",
            "renewable-integration", "grid-balancing", "battery-storage",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["ems", "scada", "weather-api"],
    )

    _add_specialist_sync(
        team,
        name="asset-manager",
        capabilities=[
            "asset-health", "maintenance-planning", "capacity-factor",
            "equipment-lifecycle", "condition-monitoring",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["eam", "historian", "gis"],
    )

    _add_specialist_sync(
        team,
        name="reliability-engineer",
        capabilities=[
            "nerc-compliance", "frequency-response", "contingency-analysis",
            "reliability-reporting", "protection-coordination",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["ems", "compliance-system"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Energy Trading Team
# ===========================================================================

def energy_trading_team(
    name: str = "energy-trading",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build an energy trading team.

    Specialists
    -----------
    - **trader** — Price forecasting, dispatch optimization, virtual
      bidding, spark spread analysis, position management.
    - **risk-analyst** — Hedge ratio calculation, VaR, counterparty risk,
      position limits, mark-to-market.
    - **meteorologist** — Weather impact analysis, load-weather models,
      severe weather alerts, seasonal outlooks.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    _check_teams()

    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=6,
        max_concurrent_tasks=20,
        architecture="E",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team,
        name="trader",
        capabilities=[
            "price-forecasting", "dispatch-optimization", "virtual-bidding",
            "spark-spread", "position-management", "carbon-trading",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["etrm", "iso-api", "ice"],
    )

    _add_specialist_sync(
        team,
        name="risk-analyst",
        capabilities=[
            "hedge-ratio", "var-calculation", "counterparty-risk",
            "position-limits", "mark-to-market", "regulatory-reporting",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["etrm", "risk-system"],
    )

    _add_specialist_sync(
        team,
        name="meteorologist",
        capabilities=[
            "weather-impact", "load-weather-models", "severe-weather",
            "seasonal-outlook", "hdd-cdd-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["weather-api", "noaa", "ecmwf"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Sustainability Team
# ===========================================================================

def sustainability_team(
    name: str = "sustainability",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a sustainability team.

    Specialists
    -----------
    - **esg-analyst** — ESG materiality, TCFD disclosure, sustainability
      reporting, benchmarking, CDP response.
    - **emissions-specialist** — Scope 1/2/3 calculations, GHG inventory,
      science-based targets, carbon offset evaluation.
    - **reporting-specialist** — GRI, ISSB, CSRD reporting, data
      collection, assurance coordination.

    Parameters
    ----------
    name:
        Team name.
    coordinator_model:
        LLM model for the coordinator.

    Returns
    -------
    OrchestraTeam
    """
    _check_teams()

    config = TeamConfig(
        name=name,
        coordinator_model=coordinator_model,
        max_specialists=6,
        max_concurrent_tasks=20,
        architecture="A",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team,
        name="esg-analyst",
        capabilities=[
            "esg-materiality", "tcfd-disclosure", "sustainability-reporting",
            "benchmarking", "cdp-response", "esg-ratings",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["esg-platform", "cdp", "msci-esg"],
    )

    _add_specialist_sync(
        team,
        name="emissions-specialist",
        capabilities=[
            "scope1-emissions", "scope2-emissions", "scope3-emissions",
            "ghg-inventory", "science-based-targets", "carbon-offsets",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["emissions-tracking", "epa-egrid", "supplier-data"],
    )

    _add_specialist_sync(
        team,
        name="reporting-specialist",
        capabilities=[
            "gri-reporting", "issb-reporting", "csrd-reporting",
            "data-collection", "assurance-coordination", "stakeholder-engagement",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["reporting-platform", "document-management"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team
