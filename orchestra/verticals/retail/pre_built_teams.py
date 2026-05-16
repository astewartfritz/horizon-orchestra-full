"""Horizon Orchestra — Retail Pre-Built Teams.

Production-ready team factories for retail workflows.

Teams
-----
:func:`category_management_team`
    Category management (buyer, analyst, pricing specialist).

:func:`cx_ops_team`
    Customer experience operations (CX analyst, loyalty, support).

:func:`digital_commerce_team`
    Digital commerce (e-commerce manager, SEO, marketing).
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "category_management_team",
    "cx_ops_team",
    "digital_commerce_team",
]

log = logging.getLogger("orchestra.verticals.retail.pre_built_teams")

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
# Category Management Team
# ===========================================================================

def category_management_team(
    name: str = "category-management",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a category management team.

    Specialists
    -----------
    - **buyer** — Assortment planning, vendor negotiation, seasonal buys,
      new item evaluation, planogram management.
    - **category-analyst** — Category performance analytics, market share,
      basket analysis, competitive intelligence.
    - **pricing-specialist** — Pricing strategy, promotion planning,
      markdown optimization, competitive price analysis.

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
        name="buyer",
        capabilities=[
            "assortment-planning", "vendor-negotiation", "seasonal-buys",
            "new-item-evaluation", "planogram-management", "replenishment",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["erp", "planogram-tool", "vendor-portal"],
    )

    _add_specialist_sync(
        team,
        name="category-analyst",
        capabilities=[
            "category-performance", "market-share", "basket-analysis",
            "competitive-intelligence", "syndicated-data", "trend-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["nielsen-iri", "pos-data", "analytics-platform"],
    )

    _add_specialist_sync(
        team,
        name="pricing-specialist",
        capabilities=[
            "pricing-strategy", "promotion-planning", "markdown-optimization",
            "competitive-pricing", "elasticity-modelling", "margin-analysis",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["pricing-engine", "competitive-intel"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# CX Operations Team
# ===========================================================================

def cx_ops_team(
    name: str = "cx-ops",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a customer experience operations team.

    Specialists
    -----------
    - **cx-analyst** — Customer sentiment, NPS analysis, journey mapping,
      churn prediction, segmentation.
    - **loyalty-manager** — Loyalty program management, offer targeting,
      VIP identification, program ROI.
    - **support-agent** — Customer inquiry routing, policy-based responses,
      escalation management.

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
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team,
        name="cx-analyst",
        capabilities=[
            "sentiment-analysis", "nps-analysis", "journey-mapping",
            "churn-prediction", "segmentation", "clv-calculation",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["cdp", "survey-tool", "analytics-platform"],
    )

    _add_specialist_sync(
        team,
        name="loyalty-manager",
        capabilities=[
            "loyalty-program", "offer-targeting", "vip-management",
            "program-roi", "reward-optimization", "member-engagement",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["loyalty-platform", "crm", "marketing-automation"],
    )

    _add_specialist_sync(
        team,
        name="support-agent",
        capabilities=[
            "inquiry-routing", "policy-responses", "escalation-management",
            "complaint-resolution", "returns-processing",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["helpdesk", "crm", "knowledge-base"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Digital Commerce Team
# ===========================================================================

def digital_commerce_team(
    name: str = "digital-commerce",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a digital commerce team.

    Specialists
    -----------
    - **ecommerce-manager** — Product listings, conversion optimization,
      checkout flow, fraud detection, marketplace management.
    - **seo-specialist** — Search ranking, site search, product schema,
      keyword optimization.
    - **digital-marketer** — Ad spend optimization, email campaigns,
      A/B testing, ROAS analysis, retargeting.

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
        name="ecommerce-manager",
        capabilities=[
            "product-listings", "conversion-optimization", "checkout-flow",
            "fraud-detection", "marketplace-management", "inventory-feed",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["ecommerce-platform", "marketplace-api", "pim"],
    )

    _add_specialist_sync(
        team,
        name="seo-specialist",
        capabilities=[
            "search-ranking", "site-search", "product-schema",
            "keyword-optimization", "technical-seo", "content-optimization",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["search-console", "analytics", "seo-tools"],
    )

    _add_specialist_sync(
        team,
        name="digital-marketer",
        capabilities=[
            "ad-spend-optimization", "email-campaigns", "ab-testing",
            "roas-analysis", "retargeting", "social-media-ads",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["google-ads", "meta-ads", "email-platform"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team
