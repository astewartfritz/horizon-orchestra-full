"""Horizon Orchestra — Financial Services Pre-Built Teams.

Production-ready team factories for financial services workflows.
Each function returns a fully configured :class:`OrchestraTeam` with
domain specialists pre-registered.

Teams
-----
:func:`ma_advisory_team`
    M&A advisory pipeline (banker, risk analyst, legal reviewer).

:func:`risk_operations_team`
    Risk operations centre (risk analyst, compliance officer, surveillance).

:func:`asset_management_team`
    Asset management desk (PM, research analyst, trader).
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "ma_advisory_team",
    "risk_operations_team",
    "asset_management_team",
]

log = logging.getLogger("orchestra.verticals.financial_services.pre_built_teams")

# Guard import — OrchestraTeam may not be available in all environments
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
    """Synchronously create and register a :class:`Specialist`."""
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
# M&A Advisory Team
# ===========================================================================

def ma_advisory_team(
    name: str = "ma-advisory",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build an M&A advisory team.

    Specialists
    -----------
    - **ib-banker** — DCF, comps, LBO models, fairness opinions,
      deal structuring, IM/teaser drafting.
    - **risk-analyst** — Counterparty risk, covenant analysis, credit
      metrics, capital structure assessment.
    - **legal-reviewer** — HSR filing analysis, MNPI controls,
      regulatory compliance, disclosure review.

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
        name="ib-banker",
        capabilities=[
            "dcf-modelling", "comps-analysis", "lbo-modelling",
            "fairness-opinion", "deal-structuring", "im-drafting",
            "accretion-dilution", "capital-markets",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["bloomberg", "pitchbook", "sec-edgar"],
    )

    _add_specialist_sync(
        team,
        name="risk-analyst",
        capabilities=[
            "counterparty-risk", "covenant-analysis", "credit-metrics",
            "capital-structure", "stress-testing", "financial-modelling",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["bloomberg", "ratings-agencies"],
    )

    _add_specialist_sync(
        team,
        name="legal-reviewer",
        capabilities=[
            "hsr-filing", "mnpi-controls", "regulatory-compliance",
            "disclosure-review", "sec-regulations", "finra-rules",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["sec-edgar", "legal-database"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Risk Operations Team
# ===========================================================================

def risk_operations_team(
    name: str = "risk-operations",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a risk operations team.

    Specialists
    -----------
    - **risk-analyst** — VaR, stress testing, limit monitoring, capital
      adequacy, counterparty risk.
    - **compliance-officer** — AML/KYC, sanctions screening, SAR filing,
      Volcker Rule, regulatory reporting.
    - **surveillance-analyst** — Trading surveillance, market abuse
      detection, communications monitoring.

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
        name="risk-analyst",
        capabilities=[
            "var-calculation", "stress-testing", "limit-monitoring",
            "capital-adequacy", "counterparty-risk", "ccar-scenarios",
            "risk-reporting",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["risk-system", "bloomberg"],
    )

    _add_specialist_sync(
        team,
        name="compliance-officer",
        capabilities=[
            "aml-kyc", "sanctions-screening", "sar-filing",
            "volcker-rule", "regulatory-reporting", "policy-enforcement",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["compliance-system", "ofac", "fincen"],
    )

    _add_specialist_sync(
        team,
        name="surveillance-analyst",
        capabilities=[
            "trading-surveillance", "market-abuse-detection",
            "communications-monitoring", "insider-trading-detection",
            "pattern-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["trading-system", "surveillance-platform"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Asset Management Team
# ===========================================================================

def asset_management_team(
    name: str = "asset-management",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build an asset management team.

    Specialists
    -----------
    - **portfolio-manager** — Portfolio optimization, factor exposures,
      attribution, rebalancing, ESG integration.
    - **research-analyst** — Earnings analysis, investment thesis,
      security screening, fundamental research.
    - **trader** — Execution, best execution analysis, market impact,
      algorithmic trading, derivatives.

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
        name="portfolio-manager",
        capabilities=[
            "portfolio-optimization", "factor-analysis", "attribution",
            "rebalancing", "esg-integration", "risk-management",
            "asset-allocation",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["bloomberg", "barra", "portfolio-system"],
    )

    _add_specialist_sync(
        team,
        name="research-analyst",
        capabilities=[
            "earnings-analysis", "investment-thesis", "security-screening",
            "fundamental-research", "industry-analysis", "valuation",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["bloomberg", "refinitiv", "sec-edgar"],
    )

    _add_specialist_sync(
        team,
        name="trader",
        capabilities=[
            "execution", "best-execution", "market-impact",
            "algorithmic-trading", "derivatives", "fx-trading",
            "fixed-income-trading",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["ems", "oms", "exchange-connectivity"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team
