"""Logistics Vertical — Pre-Built Team Templates.

Production-ready team factories for common logistics workflows.
Each factory returns a fully configured :class:`OrchestraTeam`
with domain-specialist agents pre-registered.

Teams
-----
:func:`enterprise_logistics_team`
    Full logistics operations (DHL/Ryder-level): shipment tracking,
    route optimization, warehouse ops, customs, carrier management.

:func:`trade_compliance_team`
    International trade compliance: customs classification, OFAC
    screening, export controls, FTA qualification.

:func:`fleet_management_team`
    Fleet operations: routing, driver HOS compliance, warehouse
    coordination, capacity planning.

:func:`last_mile_team`
    Last-mile delivery optimization: route planning, dynamic
    dispatch, proof-of-delivery, exception management.
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "enterprise_logistics_team",
    "trade_compliance_team",
    "fleet_management_team",
    "last_mile_team",
]

log = logging.getLogger("orchestra.verticals.logistics.pre_built_teams")

# ---------------------------------------------------------------------------
# Graceful OrchestraTeam import
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
    from orchestra.teams.context_bus import ContextBus
    from orchestra.teams.team_memory import TeamMemory
    from orchestra.teams.inter_agent_trust import InterAgentTrust, TrustLevel
    _HAS_TEAMS = True
except Exception:
    _HAS_TEAMS = False
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]
    ContextBus = TeamMemory = InterAgentTrust = TrustLevel = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helper: synchronous specialist addition
# ---------------------------------------------------------------------------

def _add_specialist_sync(
    team: "OrchestraTeam",  # type: ignore[name-defined]
    name: str,
    capabilities: list[str],
    arch: str = "A",
    model: str = "kimi-k2.5",
    connectors: list[str] | None = None,
    trust_level: str = "team",
    org_id: str = "default",
) -> "Specialist":  # type: ignore[name-defined]
    """Synchronously register a specialist on the team."""
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Enterprise Logistics Team
# ═══════════════════════════════════════════════════════════════════════════

def enterprise_logistics_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a full enterprise logistics operations team.

    Specialists
    -----------
    - **shipment_tracker**: Multi-carrier tracking, exception
      management, ETA prediction, POD retrieval.
    - **route_optimizer**: VRP solving, dispatch planning, HOS
      compliance, fleet capacity management.
    - **warehouse_manager**: Slotting, pick path, labor planning,
      inventory management, dock scheduling.
    - **customs_officer**: HTS classification, OFAC screening,
      export controls, duty calculation.
    - **carrier_manager**: Carrier scoring, rate procurement,
      capacity monitoring, insurance compliance.

    Returns
    -------
    OrchestraTeam
        DHL/Ryder-level full logistics operations team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="enterprise-logistics",
        coordinator_model=model,
        max_specialists=10,
        max_concurrent_tasks=5,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "shipment_tracker",
        capabilities=[
            "multi_carrier_tracking", "exception_management",
            "eta_prediction", "pod_retrieval",
            "carbon_footprint", "landed_cost",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "route_optimizer",
        capabilities=[
            "vrp_optimization", "dispatch_planning",
            "hos_compliance", "hazmat_routing",
            "fleet_capacity", "fuel_optimization",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "warehouse_manager",
        capabilities=[
            "slotting_optimization", "pick_path",
            "labor_planning", "inventory_management",
            "dock_scheduling", "wave_planning",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "customs_officer",
        capabilities=[
            "hts_classification", "ofac_screening",
            "export_controls", "duty_calculation",
            "fta_qualification", "customs_entry",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "carrier_manager",
        capabilities=[
            "carrier_scoring", "rate_procurement",
            "capacity_monitoring", "insurance_compliance",
            "rfp_analysis", "contract_management",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created enterprise logistics team with 5 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 2. Trade Compliance Team
# ═══════════════════════════════════════════════════════════════════════════

def trade_compliance_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a trade compliance team.

    Specialists
    -----------
    - **classification_specialist**: HTS/HS tariff classification,
      ECCN determination, USML review.
    - **screening_analyst**: OFAC SDN screening, BIS denied party
      lists, EU/UK sanctions.
    - **compliance_advisor**: FTA qualification, duty drawback,
      import restrictions, audit support.

    Returns
    -------
    OrchestraTeam
        Customs + OFAC + export control compliance team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="trade-compliance",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "classification_specialist",
        capabilities=[
            "hts_classification", "eccn_determination",
            "usml_review", "gri_analysis",
            "binding_rulings", "tariff_engineering",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "screening_analyst",
        capabilities=[
            "ofac_screening", "denied_parties",
            "entity_list", "sanctions_compliance",
            "beneficial_ownership", "pep_screening",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "compliance_advisor",
        capabilities=[
            "fta_qualification", "duty_drawback",
            "import_restrictions", "compliance_audit",
            "voluntary_disclosure", "penalty_mitigation",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created trade compliance team with 3 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 3. Fleet Management Team
# ═══════════════════════════════════════════════════════════════════════════

def fleet_management_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a fleet management team.

    Specialists
    -----------
    - **dispatcher**: Route optimization, load assignment, dynamic
      rerouting, dispatch plan generation.
    - **safety_compliance**: Driver HOS monitoring, ELD compliance,
      FMCSA safety scores, hazmat compliance.
    - **warehouse_coordinator**: Dock scheduling, loading sequence,
      capacity planning, cross-dock operations.

    Returns
    -------
    OrchestraTeam
        Routing + drivers + warehouse operations team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="fleet-management",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "dispatcher",
        capabilities=[
            "route_optimization", "load_assignment",
            "dynamic_rerouting", "dispatch_planning",
            "backhaul_matching", "fuel_optimization",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "safety_compliance",
        capabilities=[
            "hos_monitoring", "eld_compliance",
            "fmcsa_safety", "hazmat_compliance",
            "driver_qualification", "accident_reporting",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "warehouse_coordinator",
        capabilities=[
            "dock_scheduling", "loading_sequence",
            "capacity_planning", "cross_dock",
            "yard_management", "trailer_tracking",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created fleet management team with 3 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 4. Last Mile Team
# ═══════════════════════════════════════════════════════════════════════════

def last_mile_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a last-mile delivery optimization team.

    Specialists
    -----------
    - **route_planner**: Last-mile route optimization with time
      windows, customer preferences, traffic integration.
    - **delivery_ops**: Real-time tracking, exception handling,
      proof-of-delivery capture, customer notifications.
    - **analytics_specialist**: Delivery KPIs, cost-per-stop
      analysis, driver performance, carbon tracking.

    Returns
    -------
    OrchestraTeam
        Last-mile optimization team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="last-mile",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "route_planner",
        capabilities=[
            "last_mile_routing", "time_window_optimization",
            "traffic_integration", "customer_preferences",
            "multi_stop_planning", "dynamic_rerouting",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "delivery_ops",
        capabilities=[
            "real_time_tracking", "exception_handling",
            "proof_of_delivery", "customer_notifications",
            "returns_management", "delivery_confirmation",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "analytics_specialist",
        capabilities=[
            "delivery_kpis", "cost_per_stop",
            "driver_performance", "carbon_tracking",
            "customer_satisfaction", "route_adherence",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created last-mile team with 3 specialists")
    return team
