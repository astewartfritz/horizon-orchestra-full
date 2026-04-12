"""Horizon Orchestra — Pre-Built Healthcare Teams.

Factory functions that return fully configured :class:`OrchestraTeam`
instances with domain-specialist agents pre-registered for common
healthcare workflows.

Factories
---------
:func:`clinical_development_team`
    Full clinical development: protocol + safety + regulatory + data.

:func:`pharmacovigilance_team`
    PV: literature monitoring + signal detection + PSUR authoring.

:func:`revenue_cycle_team`
    RCM: coding + billing + compliance + denial management.

:func:`regulatory_affairs_team`
    Regulatory: submissions + labeling + competitive intelligence.

Example::

    from orchestra.verticals.healthcare.pre_built_teams import (
        clinical_development_team,
    )
    team = clinical_development_team()
    result = await team.run("Design Phase III protocol for mRNA vaccine")

Target customers
----------------
Johnson & Johnson, Moderna, Pfizer, Merck, AstraZeneca, Roche,
Mayo Clinic, HCA Healthcare.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

# ---------------------------------------------------------------------------
# Team infrastructure (try/except guard for standalone testing)
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except ImportError:  # pragma: no cover
    OrchestraTeam = None  # type: ignore[assignment,misc]
    TeamConfig = None      # type: ignore[assignment,misc]
    Specialist = None      # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Healthcare agents
# ---------------------------------------------------------------------------
from .clinical_trials import ClinicalTrialAgent
from .pharmacovigilance import PharmacovigilanceAgent
from .fhir_integration import FHIRAgent
from .medical_coding import MedicalCodingAgent
from .regulatory_submissions import RegulatoryAgent

__all__ = [
    "clinical_development_team",
    "pharmacovigilance_team",
    "revenue_cycle_team",
    "regulatory_affairs_team",
]

log = logging.getLogger("orchestra.verticals.healthcare.pre_built_teams")


# ---------------------------------------------------------------------------
# Helper: synchronous specialist registration
# ---------------------------------------------------------------------------

def _make_specialist(
    name: str,
    capabilities: list[str],
    model: str = "kimi-k2.5",
    arch: str = "A",
) -> dict:
    """Create a specialist descriptor dict.

    When :class:`OrchestraTeam` is available, returns a :class:`Specialist`
    instance.  Otherwise returns a plain dict for standalone testing.
    """
    if Specialist is not None:
        return Specialist(
            name=name,
            capabilities=capabilities,
            architecture=arch,
            model=model,
            connectors=[],
            agent_id=f"hc-{name}-{uuid.uuid4().hex[:6]}",
        )
    return {
        "name": name,
        "capabilities": capabilities,
        "model": model,
        "architecture": arch,
    }


def _build_team(
    team_name: str,
    specialists: list,
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Build an :class:`OrchestraTeam` with pre-registered specialists.

    Falls back to a stub object when the team module is unavailable
    (e.g. during standalone import testing).
    """
    if OrchestraTeam is None or TeamConfig is None:
        # Lightweight stub for import-time testing
        class _StubTeam:
            def __init__(self, name: str, specs: list) -> None:
                self.name = name
                self.specialists = specs
            async def run(self, goal: str) -> dict:
                return {"team": self.name, "goal": goal, "status": "stub"}
        return _StubTeam(team_name, specialists)  # type: ignore[return-value]

    config = TeamConfig(
        name=team_name,
        coordinator_model=coordinator_model,
        max_specialists=len(specialists) + 2,
        max_concurrent_tasks=4,
    )
    team = OrchestraTeam(config)

    for spec in specialists:
        if isinstance(spec, dict):
            # Dict-based specialist
            s = Specialist(
                name=spec["name"],
                capabilities=spec["capabilities"],
                architecture=spec.get("architecture", "A"),
                model=spec.get("model", coordinator_model),
                connectors=[],
                agent_id=f"hc-{spec['name']}-{uuid.uuid4().hex[:6]}",
            )
        else:
            s = spec
        team._specialists[s.name] = s  # noqa: SLF001 — direct registration for factory

    log.info(
        "Built healthcare team '%s' with %d specialists",
        team_name,
        len(specialists),
    )
    return team


# ===================================================================
# Team factories
# ===================================================================

def clinical_development_team(
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Full clinical development team: protocol + safety + regulatory + data.

    Specialists
    -----------
    * **protocol-designer** — Protocol synopsis generation, eligibility
      criteria, study design optimisation.
    * **safety-monitor** — AE analysis, CIOMS/E2B(R3) reporting,
      CTCAE grading, causality assessment.
    * **regulatory-specialist** — eCTD section drafting, IND/NDA
      requirements, FDA guidance search.
    * **data-manager** — 21 CFR Part 11 compliance, data integrity,
      CDISC SDTM/ADaM.
    * **biostatistician** — Enrollment forecasting, interim analysis,
      sample size estimation.
    * **medical-writer** — CSR section drafting, ICF authoring,
      protocol amendments.

    Returns
    -------
    OrchestraTeam
        Configured team ready for clinical development workflows.
    """
    specialists = [
        _make_specialist(
            "protocol-designer",
            [
                "protocol_design", "eligibility_criteria", "study_design",
                "generate_protocol_synopsis", "draft_informed_consent",
                "inclusion_exclusion_review",
            ],
        ),
        _make_specialist(
            "safety-monitor",
            [
                "adverse_event_analysis", "cioms_generation", "e2b_reporting",
                "ctcae_grading", "causality_assessment", "meddra_coding",
                "safety_signal_detection", "dsmb_reporting",
            ],
        ),
        _make_specialist(
            "regulatory-specialist",
            [
                "ectd_drafting", "ind_nda_requirements", "fda_guidance_search",
                "submission_tracking", "label_review", "cmc_review",
            ],
        ),
        _make_specialist(
            "data-manager",
            [
                "data_integrity_21cfr11", "cdisc_sdtm", "cdisc_adam",
                "edit_check_programming", "query_management",
                "database_lock_review",
            ],
        ),
        _make_specialist(
            "biostatistician",
            [
                "enrollment_forecasting", "interim_analysis", "sample_size",
                "statistical_analysis_plan", "randomization_design",
                "multiplicity_adjustment",
            ],
        ),
        _make_specialist(
            "medical-writer",
            [
                "csr_drafting", "icf_authoring", "protocol_amendment",
                "investigator_brochure", "plain_language_review",
            ],
        ),
    ]

    return _build_team(
        "clinical-development",
        specialists,
        coordinator_model=coordinator_model,
    )


def pharmacovigilance_team(
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """PV team: literature monitoring + signal detection + PSUR authoring.

    Specialists
    -----------
    * **literature-monitor** — PubMed/EMBASE screening, article triage.
    * **signal-analyst** — Disproportionality analysis (PRR, ROR, EBGM),
      signal evaluation and validation.
    * **case-processor** — ICSR triage, completeness check, causality
      assessment, expedited reporting timelines.
    * **aggregate-reporter** — PSUR/PBRER/DSUR section authoring,
      benefit-risk assessment.
    * **pv-medical-writer** — Safety narrative authoring, label safety
      section updates, medical writing.

    Returns
    -------
    OrchestraTeam
        Configured team ready for pharmacovigilance workflows.
    """
    specialists = [
        _make_specialist(
            "literature-monitor",
            [
                "pubmed_screening", "embase_screening", "article_triage",
                "literature_case_identification", "systematic_review",
            ],
        ),
        _make_specialist(
            "signal-analyst",
            [
                "disproportionality_analysis", "prr_calculation",
                "ror_calculation", "ebgm_calculation",
                "signal_evaluation", "signal_validation",
                "temporal_analysis", "subgroup_analysis",
            ],
        ),
        _make_specialist(
            "case-processor",
            [
                "icsr_triage", "completeness_check", "causality_assessment",
                "who_umc_assessment", "expedited_reporting",
                "reporting_timeline_calculation", "faers_search",
                "eudravigilance_search",
            ],
        ),
        _make_specialist(
            "aggregate-reporter",
            [
                "psur_authoring", "pbrer_authoring", "dsur_authoring",
                "benefit_risk_assessment", "brat_framework",
                "rems_monitoring", "aggregate_data_analysis",
            ],
        ),
        _make_specialist(
            "pv-medical-writer",
            [
                "safety_narrative", "label_safety_update",
                "medical_writing", "risk_management_plan",
                "patient_safety_communication",
            ],
        ),
    ]

    return _build_team(
        "pharmacovigilance",
        specialists,
        coordinator_model=coordinator_model,
    )


def revenue_cycle_team(
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """RCM team: coding + billing + compliance + denial management.

    Specialists
    -----------
    * **diagnosis-coder** — ICD-10-CM assignment, HCC risk adjustment,
      POA indicators.
    * **procedure-coder** — CPT/HCPCS coding, ICD-10-PCS, modifier
      validation, E/M level assignment.
    * **drg-specialist** — MS-DRG/AP-DRG grouping, case mix analysis,
      relative weight optimisation.
    * **compliance-auditor** — NCCI edits, LCD/NCD checks, coding
      compliance audits, superbill validation.
    * **denial-manager** — Claim denial analysis, appeal letter
      drafting, payer rule interpretation.

    Returns
    -------
    OrchestraTeam
        Configured team ready for revenue cycle workflows.
    """
    specialists = [
        _make_specialist(
            "diagnosis-coder",
            [
                "icd10_cm_coding", "hcc_risk_adjustment",
                "poa_assignment", "diagnosis_sequencing",
                "icd10_codebook_search", "specificity_review",
            ],
        ),
        _make_specialist(
            "procedure-coder",
            [
                "cpt_coding", "hcpcs_coding", "icd10_pcs_coding",
                "modifier_validation", "em_coding",
                "surgical_coding", "anesthesia_coding",
            ],
        ),
        _make_specialist(
            "drg-specialist",
            [
                "drg_assignment", "case_mix_analysis",
                "relative_weight_calculation", "drg_optimization",
                "mdc_analysis", "cc_mcc_review",
            ],
        ),
        _make_specialist(
            "compliance-auditor",
            [
                "ncci_edits", "lcd_ncd_check", "coding_audit",
                "superbill_validation", "modifier_compliance",
                "oig_compliance", "false_claims_review",
            ],
        ),
        _make_specialist(
            "denial-manager",
            [
                "denial_analysis", "appeal_drafting",
                "payer_rule_interpretation", "prior_authorization",
                "medical_necessity_review", "ar_follow_up",
            ],
        ),
    ]

    return _build_team(
        "revenue-cycle",
        specialists,
        coordinator_model=coordinator_model,
    )


def regulatory_affairs_team(
    coordinator_model: str = "kimi-k2.5",
) -> "OrchestraTeam":
    """Regulatory team: submissions + labeling + competitive intelligence.

    Specialists
    -----------
    * **submission-manager** — eCTD assembly, IND/NDA/BLA checklists,
      FDA/EMA submission tracking.
    * **labeling-specialist** — Label drafting, PLR formatting, safety
      section authoring, PI/PPI/MedGuide.
    * **cmc-specialist** — CMC section review, drug substance/product
      documentation, stability assessment.
    * **regulatory-intelligence** — FDA guidance monitoring, competitor
      approval tracking, patent/exclusivity research.
    * **agency-liaison** — Complete Response Letter drafting, pre-IND
      meeting prep, advisory committee analysis.

    Returns
    -------
    OrchestraTeam
        Configured team ready for regulatory affairs workflows.
    """
    specialists = [
        _make_specialist(
            "submission-manager",
            [
                "ectd_assembly", "submission_checklist",
                "ind_requirements", "nda_requirements", "bla_requirements",
                "submission_tracking", "lifecycle_management",
            ],
        ),
        _make_specialist(
            "labeling-specialist",
            [
                "label_drafting", "plr_formatting", "safety_section",
                "pi_authoring", "ppi_authoring", "medication_guide",
                "label_comparison", "boxed_warning_review",
            ],
        ),
        _make_specialist(
            "cmc-specialist",
            [
                "cmc_review", "drug_substance_docs", "drug_product_docs",
                "stability_assessment", "specifications_review",
                "manufacturing_process", "analytical_methods",
            ],
        ),
        _make_specialist(
            "regulatory-intelligence",
            [
                "fda_guidance_search", "ema_guidance_search",
                "competitor_tracking", "approval_database",
                "patent_exclusivity", "pdufa_calendar",
                "advisory_committee_monitoring",
            ],
        ),
        _make_specialist(
            "agency-liaison",
            [
                "crl_response", "pre_ind_meeting", "pre_nda_meeting",
                "advisory_committee_prep", "type_a_meeting",
                "type_b_meeting", "type_c_meeting",
            ],
        ),
    ]

    return _build_team(
        "regulatory-affairs",
        specialists,
        coordinator_model=coordinator_model,
    )
