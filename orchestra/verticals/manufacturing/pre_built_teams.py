"""Horizon Orchestra — Manufacturing Pre-Built Teams.

Production-ready team factories for manufacturing workflows.

Teams
-----
:func:`lean_manufacturing_team`
    Lean manufacturing pipeline (planner, quality, continuous improvement).

:func:`quality_ops_team`
    Quality operations (quality engineer, supplier quality, audit).

:func:`scm_team`
    Supply chain management (procurement, logistics, demand planner).
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "lean_manufacturing_team",
    "quality_ops_team",
    "scm_team",
]

log = logging.getLogger("orchestra.verticals.manufacturing.pre_built_teams")

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
# Lean Manufacturing Team
# ===========================================================================

def lean_manufacturing_team(
    name: str = "lean-manufacturing",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a lean manufacturing team.

    Specialists
    -----------
    - **production-planner** — MRP, scheduling, capacity planning, OEE,
      bottleneck analysis, changeover optimization.
    - **quality-engineer** — SPC, FMEA, capability studies, root cause
      analysis, continuous improvement.
    - **ci-specialist** — Value stream mapping, kaizen, 5S, waste
      elimination, standard work.

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
        architecture="C",
        context_bus_capacity=8_000,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team,
        name="production-planner",
        capabilities=[
            "mrp", "scheduling", "capacity-planning", "oee",
            "bottleneck-analysis", "changeover-optimization",
            "work-order-management", "shift-scheduling",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["erp", "mes", "scada"],
    )

    _add_specialist_sync(
        team,
        name="quality-engineer",
        capabilities=[
            "spc", "fmea", "cpk-ppk", "root-cause-analysis",
            "8d-reporting", "iso9001", "gauge-rr",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["qms", "spc-system"],
    )

    _add_specialist_sync(
        team,
        name="ci-specialist",
        capabilities=[
            "value-stream-mapping", "kaizen", "5s", "waste-elimination",
            "standard-work", "tpm", "lean-six-sigma",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["erp", "project-management"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Quality Operations Team
# ===========================================================================

def quality_ops_team(
    name: str = "quality-ops",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a quality operations team.

    Specialists
    -----------
    - **quality-engineer** — SPC, FMEA, capability studies, control plans,
      8D reporting, customer complaint handling.
    - **supplier-quality** — Supplier audits, incoming inspection,
      supplier scorecards, PPAP approval.
    - **quality-auditor** — ISO 9001 / AS9100 audits, compliance checks,
      management review preparation.

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
        name="quality-engineer",
        capabilities=[
            "spc", "fmea", "cpk-ppk", "control-plans",
            "8d-reporting", "customer-complaints", "capa",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["qms", "spc-system"],
    )

    _add_specialist_sync(
        team,
        name="supplier-quality",
        capabilities=[
            "supplier-audits", "incoming-inspection", "ppap",
            "supplier-scorecards", "supplier-development",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["qms", "erp"],
    )

    _add_specialist_sync(
        team,
        name="quality-auditor",
        capabilities=[
            "iso9001-audit", "as9100-audit", "iatf16949-audit",
            "compliance-checks", "management-review",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["qms", "document-management"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team


# ===========================================================================
# Supply Chain Management Team
# ===========================================================================

def scm_team(
    name: str = "scm",
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build a supply chain management team.

    Specialists
    -----------
    - **procurement** — Strategic sourcing, supplier management, contract
      negotiation, cost reduction, TCO analysis.
    - **logistics** — Inbound/outbound logistics, warehouse optimization,
      transportation planning, INCOTERMS.
    - **demand-planner** — Demand forecasting, S&OP, inventory optimization,
      ABC/XYZ analysis, safety stock.

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
        name="procurement",
        capabilities=[
            "strategic-sourcing", "supplier-management", "contract-negotiation",
            "cost-reduction", "tco-analysis", "rfx-process",
        ],
        arch="E",
        model="kimi-k2.5",
        connectors=["erp", "supplier-portal", "spend-analytics"],
    )

    _add_specialist_sync(
        team,
        name="logistics",
        capabilities=[
            "inbound-logistics", "outbound-logistics", "warehouse-optimization",
            "transportation-planning", "incoterms", "customs",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["tms", "wms", "erp"],
    )

    _add_specialist_sync(
        team,
        name="demand-planner",
        capabilities=[
            "demand-forecasting", "s-op", "inventory-optimization",
            "abc-xyz-analysis", "safety-stock", "demand-sensing",
        ],
        arch="A",
        model="kimi-k2.5",
        connectors=["erp", "demand-planning-system"],
    )

    log.info("Built %s with %d specialists", name, len(team.specialists))
    return team
