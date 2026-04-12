"""Legal Vertical — Pre-Built Team Templates.

Production-ready team factories for common legal workflows.
Each factory returns a fully configured :class:`OrchestraTeam`
with domain-specialist agents pre-registered.

Teams
-----
:func:`ma_due_diligence_team`
    M&A deal team: contract analysis, research, eDiscovery, and
    matter management specialists for transaction due diligence.

:func:`litigation_support_team`
    Litigation support pipeline: eDiscovery operations combined
    with legal research and brief drafting.

:func:`corporate_legal_team`
    In-house legal operations: contract review, compliance
    monitoring, and matter management.

:func:`regulatory_counsel_team`
    Regulatory and government affairs: regulatory research,
    compliance analysis, and government filing support.
"""

from __future__ import annotations

import logging
from typing import Optional

__all__ = [
    "ma_due_diligence_team",
    "litigation_support_team",
    "corporate_legal_team",
    "regulatory_counsel_team",
]

log = logging.getLogger("orchestra.verticals.legal.pre_built_teams")

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
# Helper: synchronous specialist addition (mirrors teams/pre_built_teams.py)
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
# 1. M&A Due Diligence Team
# ═══════════════════════════════════════════════════════════════════════════

def ma_due_diligence_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create an M&A due diligence team.

    Specialists
    -----------
    - **contract_analyst**: SPA/APA review, rep & warranty analysis,
      indemnification, working capital adjustments, MAC clauses.
    - **legal_researcher**: Regulatory approvals, antitrust analysis,
      HSR Act compliance, precedent transaction research.
    - **ediscovery_specialist**: Data room document review, privilege
      screening, document clustering by deal issue.
    - **matter_manager**: Deal timeline tracking, budget management,
      client reporting, billing coordination.

    Returns
    -------
    OrchestraTeam
        Fully configured M&A due diligence team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="ma-due-diligence",
        coordinator_model=model,
        max_specialists=8,
        max_concurrent_tasks=4,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "contract_analyst",
        capabilities=[
            "contract_analysis", "spa_review", "apa_review",
            "indemnification_analysis", "rep_warranty_review",
            "mac_clause_analysis", "working_capital",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "legal_researcher",
        capabilities=[
            "case_law_research", "regulatory_analysis",
            "antitrust_review", "hsr_compliance",
            "precedent_transactions", "statutory_research",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "ediscovery_specialist",
        capabilities=[
            "document_review", "privilege_detection",
            "concept_clustering", "data_room_review",
            "deduplication", "production_management",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "matter_manager",
        capabilities=[
            "budget_management", "deadline_tracking",
            "client_reporting", "billing_review",
            "staffing_optimization", "engagement_letters",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created M&A due diligence team with 4 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 2. Litigation Support Team
# ═══════════════════════════════════════════════════════════════════════════

def litigation_support_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a litigation support team.

    Specialists
    -----------
    - **ediscovery_lead**: Full EDRM workflow management, TAR/CAL,
      privilege review, production management.
    - **research_analyst**: Case law research, brief drafting,
      precedent analysis, circuit split detection.
    - **trial_support**: Exhibit management, deposition prep,
      jury verdict research, expert witness coordination.

    Returns
    -------
    OrchestraTeam
        Fully configured litigation support team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="litigation-support",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "ediscovery_lead",
        capabilities=[
            "document_review", "privilege_log", "tar_cal",
            "deduplication", "concept_clustering",
            "production_management", "legal_hold",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "research_analyst",
        capabilities=[
            "case_law_research", "brief_drafting",
            "precedent_analysis", "circuit_split_detection",
            "statutory_research", "legal_memo",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "trial_support",
        capabilities=[
            "exhibit_management", "deposition_prep",
            "jury_verdict_research", "expert_witnesses",
            "timeline_construction", "trial_presentation",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created litigation support team with 3 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 3. Corporate Legal Team
# ═══════════════════════════════════════════════════════════════════════════

def corporate_legal_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a corporate legal / in-house team.

    Specialists
    -----------
    - **contracts_specialist**: MSA/NDA/SaaS review, playbook
      enforcement, redlining, vendor management.
    - **compliance_analyst**: Regulatory compliance monitoring,
      GDPR/CCPA audits, policy review.
    - **operations_manager**: Matter management, budgeting,
      outside counsel management, reporting.

    Returns
    -------
    OrchestraTeam
        Fully configured corporate legal team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="corporate-legal",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "contracts_specialist",
        capabilities=[
            "contract_review", "nda_review", "msa_review",
            "saas_review", "playbook_enforcement",
            "redlining", "vendor_management",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "compliance_analyst",
        capabilities=[
            "gdpr_compliance", "ccpa_compliance",
            "regulatory_monitoring", "policy_review",
            "audit_support", "risk_assessment",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "operations_manager",
        capabilities=[
            "matter_management", "budget_analysis",
            "outside_counsel_management", "billing_review",
            "staffing", "client_reporting",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created corporate legal team with 3 specialists")
    return team


# ═══════════════════════════════════════════════════════════════════════════
# 4. Regulatory Counsel Team
# ═══════════════════════════════════════════════════════════════════════════

def regulatory_counsel_team(
    *,
    model: str = "kimi-k2.5",
    org_id: str = "default",
) -> "OrchestraTeam":  # type: ignore[name-defined]
    """Create a regulatory counsel / government affairs team.

    Specialists
    -----------
    - **regulatory_researcher**: Federal Register monitoring, eCFR
      research, agency guidance tracking.
    - **compliance_advisor**: Regulatory compliance gap analysis,
      remediation planning, enforcement trends.
    - **government_affairs**: Government filing preparation, comment
      letter drafting, lobbying disclosure compliance.

    Returns
    -------
    OrchestraTeam
        Fully configured regulatory counsel team.
    """
    if not _HAS_TEAMS:
        raise RuntimeError("OrchestraTeam not available — install orchestra.teams")

    config = TeamConfig(
        name="regulatory-counsel",
        coordinator_model=model,
        max_specialists=6,
        max_concurrent_tasks=3,
    )
    team = OrchestraTeam(config)

    _add_specialist_sync(
        team, "regulatory_researcher",
        capabilities=[
            "federal_register", "ecfr_research",
            "agency_guidance", "rulemaking_tracking",
            "statutory_research", "regulatory_history",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "compliance_advisor",
        capabilities=[
            "compliance_gap_analysis", "remediation_planning",
            "enforcement_trends", "risk_assessment",
            "compliance_program_design", "audit_preparation",
        ],
        model=model, org_id=org_id,
    )

    _add_specialist_sync(
        team, "government_affairs",
        capabilities=[
            "government_filings", "comment_letters",
            "lobbying_disclosure", "congressional_research",
            "agency_engagement", "public_policy",
        ],
        model=model, org_id=org_id,
    )

    log.info("Created regulatory counsel team with 3 specialists")
    return team
