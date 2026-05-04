"""Horizon Orchestra — Real Estate Pre-Built Teams.

Production-ready team factories for real estate workflows.

Teams
-----
:func:`acquisitions_team`
    Acquisitions pipeline (analyst, underwriter, legal).

:func:`asset_management_team`
    Asset management (property manager, leasing agent, financial analyst).

:func:`leasing_team`
    Leasing team (leasing agent, market analyst, legal).
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "acquisitions_team",
    "asset_management_team",
    "leasing_team",
]

log = logging.getLogger("orchestra.verticals.real_estate.pre_built_teams")

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
# Acquisitions Team
# ===========================================================================

def acquisitions_team(
    name: str = "acquisitions",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a real estate acquisitions team.

    Specialists
    -----------
    - **acquisition-analyst** — DCF valuation, cap rate analysis, comps,
      market fundamentals, investment memo, sensitivity analysis.
    - **underwriter** — Rent roll analysis, DSCR, debt sizing, capital
      structure, environmental/zoning due diligence.
    - **legal-reviewer** — Lease review, title/survey, environmental
      liability, closing documentation.

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
        name="acquisition-analyst",
        capabilities=[
            "dcf-valuation", "cap-rate-analysis", "comparable-sales",
            "market-fundamentals", "investment-memo", "sensitivity-analysis",
            "highest-best-use",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["argus", "costar", "real-capital-analytics"],
    )

    _add_specialist_sync(
        team,
        name="underwriter",
        capabilities=[
            "rent-roll-analysis", "dscr-calculation", "debt-sizing",
            "capital-structure", "environmental-assessment", "zoning-review",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["argus", "lender-platforms"],
    )

    _add_specialist_sync(
        team,
        name="legal-reviewer",
        capabilities=[
            "lease-review", "title-survey", "environmental-liability",
            "closing-documentation", "snda-review", "estoppel-review",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["legal-database", "document-management"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Asset Management Team
# ===========================================================================

def asset_management_team(
    name: str = "asset-management-re",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a real estate asset management team.

    Specialists
    -----------
    - **property-manager** — Lease administration, CAM reconciliation,
      critical dates, tenant relations, maintenance oversight.
    - **leasing-agent** — Tenant prospecting, LOI negotiation, lease
      comparison, market analysis, tenant credit evaluation.
    - **financial-analyst** — NOI tracking, budget vs actual, capital
      planning, disposition analysis, investor reporting.

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
        name="property-manager",
        capabilities=[
            "lease-administration", "cam-reconciliation", "critical-dates",
            "tenant-relations", "maintenance-oversight", "vendor-management",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["yardi", "mri-software", "building-engines"],
    )

    _add_specialist_sync(
        team,
        name="leasing-agent",
        capabilities=[
            "tenant-prospecting", "loi-negotiation", "lease-comparison",
            "market-analysis", "tenant-credit", "sublease-analysis",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["costar", "crm", "listing-platforms"],
    )

    _add_specialist_sync(
        team,
        name="financial-analyst",
        capabilities=[
            "noi-tracking", "budget-variance", "capital-planning",
            "disposition-analysis", "investor-reporting", "waterfall-modelling",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["argus", "yardi", "excel"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Leasing Team
# ===========================================================================

def leasing_team(
    name: str = "leasing",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a leasing team.

    Specialists
    -----------
    - **leasing-agent** — Tenant prospecting, tours, LOI drafting,
      deal negotiation, lease execution, move-in coordination.
    - **market-analyst** — Market vacancy, rent comps, absorption trends,
      competitive set analysis, sublease market.
    - **lease-attorney** — Lease drafting, amendment negotiation, SNDA,
      estoppel, legal compliance.

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
        name="leasing-agent",
        capabilities=[
            "tenant-prospecting", "tours", "loi-drafting",
            "deal-negotiation", "lease-execution", "move-in-coordination",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["crm", "listing-platforms", "marketing"],
    )

    _add_specialist_sync(
        team,
        name="market-analyst",
        capabilities=[
            "market-vacancy", "rent-comps", "absorption-trends",
            "competitive-set", "sublease-market", "demographic-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["costar", "reis", "census-data"],
    )

    _add_specialist_sync(
        team,
        name="lease-attorney",
        capabilities=[
            "lease-drafting", "amendment-negotiation", "snda",
            "estoppel", "legal-compliance", "tenant-notices",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["legal-database", "document-management"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team
