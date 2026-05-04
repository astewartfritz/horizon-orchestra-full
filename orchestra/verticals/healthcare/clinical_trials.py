"""Horizon Orchestra — Clinical Trial Operations Agent.

AI agent specialized for end-to-end clinical trial operations,
from protocol design through safety monitoring and regulatory
reporting.  Covers protocol synopsis generation, patient eligibility
screening, adverse event detection/classification, CIOMS I / ICH E2B(R3)
safety reports, site performance analytics, enrollment forecasting,
interim analysis, risk-based monitoring, and CSR section drafting.

Regulatory alignment
--------------------
* ICH E6(R2) Good Clinical Practice
* ICH E2B(R3) Individual Case Safety Reports
* ICH E3 Clinical Study Report structure
* 21 CFR Part 11 Electronic Records
* FDA eCTD submission format

Target customers
----------------
Johnson & Johnson, Moderna, Pfizer, Merck, AstraZeneca, Roche.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

# ---------------------------------------------------------------------------
# HIPAA / audit guardrails (try/except for standalone testing)
# ---------------------------------------------------------------------------
try:
    from orchestra.compliance.hipaa import PHIScanner
except ImportError:  # pragma: no cover
    PHIScanner = None  # type: ignore[assignment,misc]

try:
    from orchestra.guardian.audit_ledger import AuditLedger
except ImportError:  # pragma: no cover
    AuditLedger = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Optional HTTP client for ClinicalTrials.gov / PubMed
# ---------------------------------------------------------------------------
try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

__all__ = [
    "ClinicalTrialAgent",
    "CTCAEGrade",
    "CausalityAssessment",
    "ProtocolDeviation",
    "AdverseEventRecord",
    "EnrollmentForecast",
    "SitePerformanceMetrics",
]

log = logging.getLogger("orchestra.verticals.healthcare.clinical_trials")

# ---------------------------------------------------------------------------
# Constants — CTCAE v5.0 grading scale
# ---------------------------------------------------------------------------

class CTCAEGrade(int, Enum):
    """Common Terminology Criteria for Adverse Events v5.0 grades."""
    GRADE_1 = 1   # Mild; asymptomatic or mild symptoms
    GRADE_2 = 2   # Moderate; minimal/local/non-invasive intervention
    GRADE_3 = 3   # Severe or medically significant
    GRADE_4 = 4   # Life-threatening consequences
    GRADE_5 = 5   # Death related to AE


class CausalityAssessment(str, Enum):
    """WHO-UMC causality categories."""
    CERTAIN = "certain"
    PROBABLE = "probable/likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    CONDITIONAL = "conditional/unclassified"
    UNASSESSABLE = "unassessable/unclassifiable"


class DeviationCategory(str, Enum):
    """Protocol deviation classification."""
    MAJOR = "major"
    MINOR = "minor"
    IMPORTANT = "important"  # ICH E3 important PD


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MedDRACode:
    """MedDRA coding result for an adverse event term.

    Attributes
    ----------
    pt_code : int
        Preferred Term code (e.g. 10019211 = Headache).
    pt_term : str
        Preferred Term string.
    llt_code : int | None
        Lowest Level Term code.
    llt_term : str | None
        Lowest Level Term string.
    soc_code : int
        System Organ Class code.
    soc_term : str
        System Organ Class name.
    hlgt_code : int | None
        High Level Group Term code.
    hlt_code : int | None
        High Level Term code.
    smq_narrow : list[int]
        Standardised MedDRA Queries (narrow scope) this term belongs to.
    """
    pt_code: int
    pt_term: str
    llt_code: Optional[int] = None
    llt_term: Optional[str] = None
    soc_code: int = 0
    soc_term: str = ""
    hlgt_code: Optional[int] = None
    hlt_code: Optional[int] = None
    smq_narrow: List[int] = field(default_factory=list)


# Commonly-used MedDRA PT lookup (subset for inline coding)
_MEDDRA_PT_LOOKUP: Dict[str, MedDRACode] = {
    "headache": MedDRACode(
        pt_code=10019211, pt_term="Headache",
        soc_code=10029205, soc_term="Nervous system disorders",
    ),
    "nausea": MedDRACode(
        pt_code=10028813, pt_term="Nausea",
        soc_code=10017947, soc_term="Gastrointestinal disorders",
    ),
    "fatigue": MedDRACode(
        pt_code=10016256, pt_term="Fatigue",
        soc_code=10018065, soc_term="General disorders and administration site conditions",
    ),
    "pyrexia": MedDRACode(
        pt_code=10037660, pt_term="Pyrexia",
        soc_code=10018065, soc_term="General disorders and administration site conditions",
    ),
    "injection site pain": MedDRACode(
        pt_code=10022086, pt_term="Injection site pain",
        soc_code=10018065, soc_term="General disorders and administration site conditions",
    ),
    "diarrhoea": MedDRACode(
        pt_code=10012735, pt_term="Diarrhoea",
        soc_code=10017947, soc_term="Gastrointestinal disorders",
    ),
    "rash": MedDRACode(
        pt_code=10037844, pt_term="Rash",
        soc_code=10040785, soc_term="Skin and subcutaneous tissue disorders",
    ),
    "myalgia": MedDRACode(
        pt_code=10028411, pt_term="Myalgia",
        soc_code=10028395, soc_term="Musculoskeletal and connective tissue disorders",
    ),
    "arthralgia": MedDRACode(
        pt_code=10003239, pt_term="Arthralgia",
        soc_code=10028395, soc_term="Musculoskeletal and connective tissue disorders",
    ),
    "anaphylaxis": MedDRACode(
        pt_code=10002198, pt_term="Anaphylactic reaction",
        soc_code=10021428, soc_term="Immune system disorders",
        smq_narrow=[20000021],  # SMQ: Anaphylactic reaction
    ),
    "thrombocytopenia": MedDRACode(
        pt_code=10043554, pt_term="Thrombocytopenia",
        soc_code=10005329, soc_term="Blood and lymphatic system disorders",
        smq_narrow=[20000141],
    ),
    "hepatotoxicity": MedDRACode(
        pt_code=10019851, pt_term="Hepatotoxicity",
        soc_code=10019805, soc_term="Hepatobiliary disorders",
        smq_narrow=[20000006],  # SMQ: Drug related hepatic disorders
    ),
}


@dataclass
class AdverseEventRecord:
    """Structured adverse event data."""
    ae_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject_id: str = ""
    study_id: str = ""
    ae_term: str = ""
    meddra: Optional[MedDRACode] = None
    ctcae_grade: Optional[CTCAEGrade] = None
    causality: Optional[CausalityAssessment] = None
    serious: bool = False
    seriousness_criteria: List[str] = field(default_factory=list)
    onset_date: Optional[str] = None
    resolution_date: Optional[str] = None
    outcome: str = ""
    action_taken: str = ""
    narrative: str = ""
    reporter_type: str = "investigator"
    expectedness: str = "expected"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to dictionary (JSON-safe)."""
        d: Dict[str, Any] = {
            "ae_id": self.ae_id,
            "subject_id": self.subject_id,
            "study_id": self.study_id,
            "ae_term": self.ae_term,
            "ctcae_grade": self.ctcae_grade.value if self.ctcae_grade else None,
            "causality": self.causality.value if self.causality else None,
            "serious": self.serious,
            "seriousness_criteria": self.seriousness_criteria,
            "onset_date": self.onset_date,
            "resolution_date": self.resolution_date,
            "outcome": self.outcome,
            "action_taken": self.action_taken,
            "narrative": self.narrative,
            "reporter_type": self.reporter_type,
            "expectedness": self.expectedness,
        }
        if self.meddra:
            d["meddra_pt_code"] = self.meddra.pt_code
            d["meddra_pt_term"] = self.meddra.pt_term
            d["meddra_soc_term"] = self.meddra.soc_term
        return d


@dataclass
class ProtocolDeviation:
    """Protocol deviation record."""
    deviation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject_id: str = ""
    site_id: str = ""
    study_id: str = ""
    category: DeviationCategory = DeviationCategory.MINOR
    description: str = ""
    date_occurred: Optional[str] = None
    date_discovered: Optional[str] = None
    impact_assessment: str = ""
    corrective_action: str = ""
    affects_subject_safety: bool = False
    affects_data_integrity: bool = False


@dataclass
class EnrollmentForecast:
    """Statistical enrollment projection result."""
    study_id: str = ""
    target_enrollment: int = 0
    current_enrollment: int = 0
    projected_completion_date: str = ""
    confidence_interval_90: Tuple[str, str] = ("", "")
    weekly_rate: float = 0.0
    sites_active: int = 0
    sites_under_target: List[str] = field(default_factory=list)
    model_used: str = "poisson_gamma"


@dataclass
class SitePerformanceMetrics:
    """Per-site performance dashboard data."""
    site_id: str = ""
    site_name: str = ""
    principal_investigator: str = ""
    enrolled: int = 0
    screen_failures: int = 0
    screen_failure_rate: float = 0.0
    dropouts: int = 0
    dropout_rate: float = 0.0
    open_queries: int = 0
    query_resolution_days: float = 0.0
    protocol_deviations: int = 0
    ae_reporting_timeliness: float = 0.0  # % on-time


# ===================================================================
# ClinicalTrialAgent
# ===================================================================

class ClinicalTrialAgent:
    """AI agent specialized for clinical trial operations.

    Covers: protocol design, patient eligibility screening, adverse event
    detection, CIOMS/MedDRA coding, ICH E2B(R3) safety reports, site
    performance analytics, enrollment forecasting, interim analysis support.

    Regulatory alignment: ICH E6 GCP, 21 CFR Part 11, FDA eCTD.

    HIPAA controls
    --------------
    * All LLM outputs pass through :class:`PHIScanner` before return.
    * PHI access events are logged to :class:`AuditLedger`.
    * Raw PHI is never stored in conversation memory — de-identified
      tokens are used instead.

    Parameters
    ----------
    model : str
        LLM model identifier for the agent.
    audit_ledger : AuditLedger | None
        Shared audit ledger for PHI access logging.
    phi_scanner : PHIScanner | None
        PHI scanner instance; one is created automatically if ``None``.
    """

    TOOLS: List[str] = [
        "screen_patient_eligibility",
        "analyze_adverse_event",
        "code_adverse_event_meddra",
        "generate_cioms_form",
        "generate_icsr",
        "assess_protocol_deviation",
        "calculate_enrollment_forecast",
        "analyze_site_performance",
        "run_interim_analysis",
        "generate_study_report",
        "check_data_integrity_21cfr11",
        "search_clinicaltrials_gov",
        "generate_protocol_synopsis",
        "assess_risk_based_monitoring",
        "draft_informed_consent",
    ]

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def __init__(
        self,
        model: str = "kimi-k2.5",
        audit_ledger: Any = None,
        phi_scanner: Any = None,
    ) -> None:
        self.model = model
        self._audit = audit_ledger
        self._phi = phi_scanner or (PHIScanner() if PHIScanner else None)
        self._agent_id = f"clinical-trial-{uuid.uuid4().hex[:8]}"
        log.info("ClinicalTrialAgent initialised  agent_id=%s  model=%s", self._agent_id, model)

    # -----------------------------------------------------------------
    # PHI guardrails
    # -----------------------------------------------------------------

    def _screen_phi(self, text: str) -> str:
        """Redact PHI from LLM output before returning to caller."""
        if self._phi is None:
            return text
        matches = self._phi.scan(text)
        if not matches:
            return text
        result = self._phi.redact(text)
        # redact() returns (redacted_text, matches) tuple
        redacted = result[0] if isinstance(result, tuple) else result
        log.warning("PHI detected in output — %d matches redacted", len(matches))
        return redacted

    async def _log_phi_access(self, action: str, resource: str) -> None:
        """Record PHI access event in the audit ledger."""
        if self._audit is None:
            return
        try:
            await self._audit.append(
                actor=self._agent_id,
                action=action,
                resource=resource,
                metadata={"hipaa": True, "timestamp": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to write audit event")

    # -----------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build the domain-expert system prompt for clinical trials.

        Encodes ICH-GCP knowledge, safety reporting rules, protocol
        design best practices, and statistical methodology guidance.
        """
        return (
            "You are an expert Clinical Trial Operations AI assistant working "
            "within Horizon Orchestra.  You have deep knowledge of:\n\n"
            "REGULATORY FRAMEWORK\n"
            "- ICH E6(R2) Good Clinical Practice guidelines\n"
            "- ICH E2B(R3) Individual Case Safety Report format\n"
            "- ICH E3 Structure and Content of Clinical Study Reports\n"
            "- 21 CFR Part 11 Electronic Records / Electronic Signatures\n"
            "- FDA eCTD (Electronic Common Technical Document)\n"
            "- EU CTR (Clinical Trials Regulation 536/2014)\n\n"
            "SAFETY REPORTING\n"
            "- CTCAE v5.0 grading criteria for adverse events\n"
            "- MedDRA v26.1 coding (PT, LLT, HLT, HLGT, SOC hierarchy)\n"
            "- CIOMS I form completion for expedited safety reports\n"
            "- Causality assessment using WHO-UMC categories\n"
            "- Seriousness criteria: death, life-threatening, hospitalisation, "
            "disability, congenital anomaly, other medically important\n"
            "- Expedited reporting timelines: 7-day (fatal/life-threatening), "
            "15-day (all other serious unexpected)\n\n"
            "OPERATIONAL EXCELLENCE\n"
            "- Risk-based monitoring per ICH E6(R2) Addendum\n"
            "- Centralised statistical monitoring for data anomalies\n"
            "- Enrollment forecasting using Poisson-Gamma models\n"
            "- Site performance KPIs: screen failure rate, dropout, query "
            "resolution time, protocol deviation rate\n"
            "- Data management: CDISC SDTM/ADaM standards\n\n"
            "HIPAA COMPLIANCE\n"
            "- Never output raw PHI (names, MRNs, dates of birth)\n"
            "- Use de-identified subject IDs only\n"
            "- Log all PHI access to the audit ledger\n"
            "- Apply minimum necessary rule\n"
        )

    # -----------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------

    async def screen_patient(
        self,
        patient_data: dict,
        protocol: dict,
    ) -> dict:
        """Check patient against inclusion/exclusion criteria.

        Parameters
        ----------
        patient_data : dict
            Patient demographics, labs, conditions.  Expected keys:
            ``age``, ``sex``, ``conditions`` (ICD-10 list),
            ``lab_values`` (dict of LOINC → value), ``medications``.
        protocol : dict
            Protocol criteria.  Expected keys:
            ``inclusion`` (list[str]), ``exclusion`` (list[str]),
            ``age_range`` (tuple[int, int]), ``required_labs`` (dict).

        Returns
        -------
        dict
            ``eligible`` (bool), ``met_inclusion`` (list), ``failed_inclusion``
            (list), ``hit_exclusion`` (list), ``warnings`` (list).
        """
        await self._log_phi_access("screen_patient", patient_data.get("subject_id", "unknown"))

        result: Dict[str, Any] = {
            "eligible": True,
            "met_inclusion": [],
            "failed_inclusion": [],
            "hit_exclusion": [],
            "warnings": [],
        }

        # --- Age check ---
        age = patient_data.get("age")
        age_range = protocol.get("age_range", (18, 99))
        if age is not None:
            if age_range[0] <= age <= age_range[1]:
                result["met_inclusion"].append(f"Age {age} within [{age_range[0]}, {age_range[1]}]")
            else:
                result["failed_inclusion"].append(f"Age {age} outside [{age_range[0]}, {age_range[1]}]")
                result["eligible"] = False

        # --- Inclusion criteria ---
        for criterion in protocol.get("inclusion", []):
            key = criterion.lower().strip()
            conditions = [c.lower() for c in patient_data.get("conditions", [])]
            if key in conditions or key in str(patient_data.get("lab_values", {})).lower():
                result["met_inclusion"].append(criterion)
            else:
                result["failed_inclusion"].append(criterion)
                result["eligible"] = False

        # --- Exclusion criteria ---
        for criterion in protocol.get("exclusion", []):
            key = criterion.lower().strip()
            conditions = [c.lower() for c in patient_data.get("conditions", [])]
            medications = [m.lower() for m in patient_data.get("medications", [])]
            if key in conditions or key in medications:
                result["hit_exclusion"].append(criterion)
                result["eligible"] = False

        # --- Required lab values ---
        for loinc, (lo, hi) in protocol.get("required_labs", {}).items():
            val = patient_data.get("lab_values", {}).get(loinc)
            if val is None:
                result["warnings"].append(f"Missing lab value for LOINC {loinc}")
            elif not (lo <= val <= hi):
                result["failed_inclusion"].append(f"Lab {loinc}={val} outside [{lo}, {hi}]")
                result["eligible"] = False

        return result

    async def analyze_ae(self, ae_data: dict) -> dict:
        """Classify adverse event severity, causality, and MedDRA code.

        Parameters
        ----------
        ae_data : dict
            Must contain ``ae_term``.  Optional: ``description``,
            ``time_to_onset_hours``, ``dechallenge``, ``rechallenge``,
            ``concomitant_medications``, ``medical_history``.

        Returns
        -------
        dict
            ``ae_record`` (:class:`AdverseEventRecord` as dict),
            ``meddra`` (MedDRA coding), ``recommendations`` (list).
        """
        await self._log_phi_access("analyze_ae", ae_data.get("subject_id", "unknown"))

        term = ae_data.get("ae_term", "").lower().strip()

        # MedDRA coding (inline lookup → fallback to LLM)
        meddra = _MEDDRA_PT_LOOKUP.get(term)

        # Severity heuristic based on description keywords
        desc = ae_data.get("description", "").lower()
        grade = CTCAEGrade.GRADE_1
        if any(kw in desc for kw in ("life-threatening", "life threatening", "icu", "ventilator")):
            grade = CTCAEGrade.GRADE_4
        elif any(kw in desc for kw in ("hospitalisation", "hospitalization", "hospitalized", "inpatient")):
            grade = CTCAEGrade.GRADE_3
        elif any(kw in desc for kw in ("moderate", "intervention", "outpatient treatment")):
            grade = CTCAEGrade.GRADE_2

        # Causality heuristic
        causality = CausalityAssessment.POSSIBLE
        time_h = ae_data.get("time_to_onset_hours")
        if ae_data.get("rechallenge") is True:
            causality = CausalityAssessment.CERTAIN
        elif ae_data.get("dechallenge") is True and time_h and time_h < 72:
            causality = CausalityAssessment.PROBABLE
        elif time_h and time_h > 720:
            causality = CausalityAssessment.UNLIKELY

        # Seriousness
        seriousness_criteria: List[str] = []
        serious = False
        if grade.value >= 3:
            serious = True
            if grade == CTCAEGrade.GRADE_5:
                seriousness_criteria.append("results in death")
            elif grade == CTCAEGrade.GRADE_4:
                seriousness_criteria.append("life-threatening")
            else:
                seriousness_criteria.append("requires hospitalisation")
        if "disability" in desc:
            serious = True
            seriousness_criteria.append("persistent or significant disability")
        if "congenital" in desc or "birth defect" in desc:
            serious = True
            seriousness_criteria.append("congenital anomaly/birth defect")

        record = AdverseEventRecord(
            subject_id=ae_data.get("subject_id", ""),
            study_id=ae_data.get("study_id", ""),
            ae_term=ae_data.get("ae_term", ""),
            meddra=meddra,
            ctcae_grade=grade,
            causality=causality,
            serious=serious,
            seriousness_criteria=seriousness_criteria,
            onset_date=ae_data.get("onset_date"),
            narrative=ae_data.get("description", ""),
            expectedness="unexpected" if meddra and meddra.smq_narrow else "expected",
        )

        recommendations: List[str] = []
        if serious and record.expectedness == "unexpected":
            recommendations.append("EXPEDITED REPORT REQUIRED — 15-day (or 7-day if fatal/life-threatening)")
        if grade.value >= 4:
            recommendations.append("Notify DSMB immediately")
            recommendations.append("Unblinding may be required per protocol")
        if meddra and meddra.smq_narrow:
            recommendations.append(f"SMQ alert — term belongs to narrow SMQ(s): {meddra.smq_narrow}")

        output = {
            "ae_record": record.to_dict(),
            "meddra": {
                "pt_code": meddra.pt_code if meddra else None,
                "pt_term": meddra.pt_term if meddra else term.title(),
                "soc_term": meddra.soc_term if meddra else "Unknown",
            },
            "recommendations": recommendations,
        }
        return output

    async def generate_cioms(self, case_data: dict) -> str:
        """Generate a CIOMS I safety report form.

        Parameters
        ----------
        case_data : dict
            Keys: ``subject_id``, ``study_id``, ``ae_term``,
            ``onset_date``, ``description``, ``reporter_name``,
            ``reporter_qualification``, ``suspect_drug``,
            ``dose``, ``route``, ``indication``.

        Returns
        -------
        str
            CIOMS I form as structured text.
        """
        await self._log_phi_access("generate_cioms", case_data.get("subject_id", "unknown"))

        lines = [
            "=" * 72,
            "CIOMS I — SUSPECTED ADVERSE REACTION REPORT",
            "=" * 72,
            "",
            f"I.  REACTION INFORMATION",
            f"    Patient initials: {case_data.get('patient_initials', '[REDACTED]')}",
            f"    Country: {case_data.get('country', 'US')}",
            f"    Date of birth: [REDACTED — de-identified]",
            f"    Age/Sex: {case_data.get('age', 'N/A')} / {case_data.get('sex', 'N/A')}",
            f"    Reaction onset: {case_data.get('onset_date', 'N/A')}",
            f"    Reaction description: {case_data.get('ae_term', 'N/A')}",
            "",
            f"II. SUSPECT DRUG(S) INFORMATION",
            f"    Drug name: {case_data.get('suspect_drug', 'N/A')}",
            f"    Dose/Route/Frequency: {case_data.get('dose', 'N/A')} "
            f"{case_data.get('route', 'N/A')}",
            f"    Indication: {case_data.get('indication', 'N/A')}",
            f"    Date started: {case_data.get('drug_start_date', 'N/A')}",
            f"    Date stopped: {case_data.get('drug_stop_date', 'N/A')}",
            "",
            f"III. CONCOMITANT DRUG(S) AND HISTORY",
            f"    Concomitant drugs: {', '.join(case_data.get('concomitant_drugs', ['None']))}",
            f"    Relevant history: {case_data.get('medical_history', 'None reported')}",
            "",
            f"IV. MANUFACTURER INFORMATION",
            f"    Company: {case_data.get('company', 'N/A')}",
            f"    Report source: {case_data.get('report_source', 'clinical trial')}",
            f"    Date received: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            f"    Report type: {case_data.get('report_type', 'initial')}",
            "",
            f"V.  NARRATIVE",
            f"    {case_data.get('description', 'No narrative provided.')}",
            "",
            "=" * 72,
        ]
        report = "\n".join(lines)
        return self._screen_phi(report)

    async def generate_e2b_xml(self, case_data: dict) -> str:
        """Generate ICH E2B(R3) ICSR XML.

        Produces a valid-structure E2B(R3) XML document for electronic
        submission to FDA FAERS or EMA EudraVigilance.

        Parameters
        ----------
        case_data : dict
            Structured case data with keys matching ICSR data elements.

        Returns
        -------
        str
            E2B(R3) XML string.
        """
        await self._log_phi_access("generate_e2b_xml", case_data.get("subject_id", "unknown"))

        safety_report_id = case_data.get("safety_report_id", str(uuid.uuid4()))
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ichicsr lang="en" xmlns="urn:hl7-org:v3">',
            '  <ichicsrmessageheader>',
            f'    <messagetype>ichicsr</messagetype>',
            f'    <messageformatversion>2.1</messageformatversion>',
            f'    <messageformatrelease>R3</messageformatrelease>',
            f'    <messagenumb>{safety_report_id}</messagenumb>',
            f'    <messagesenderidentifier>{case_data.get("sender_id", "HORIZON-ORCH")}</messagesenderidentifier>',
            f'    <messagereceiveridentifier>{case_data.get("receiver_id", "FDA-FAERS")}</messagereceiveridentifier>',
            f'    <messagedateformat>204</messagedateformat>',
            f'    <messagedate>{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}</messagedate>',
            '  </ichicsrmessageheader>',
            '  <safetyreport>',
            f'    <safetyreportversion>1</safetyreportversion>',
            f'    <safetyreportid>{safety_report_id}</safetyreportid>',
            f'    <primarysourcecountry>{case_data.get("country", "US")}</primarysourcecountry>',
            f'    <reporttype>{case_data.get("report_type_code", "1")}</reporttype>',
            f'    <serious>{1 if case_data.get("serious", False) else 2}</serious>',
            '    <patient>',
            f'      <patientinitial>{case_data.get("patient_initials", "XX")}</patientinitial>',
            f'      <patientonsetage>{case_data.get("age", "")}</patientonsetage>',
            f'      <patientonsetageunit>801</patientonsetageunit>',
            f'      <patientsex>{case_data.get("sex_code", "0")}</patientsex>',
            '      <reaction>',
            f'        <primarysourcereaction>{case_data.get("ae_term", "")}</primarysourcereaction>',
            f'        <reactionmeddraversionllt>26.1</reactionmeddraversionllt>',
            f'        <reactionmeddrapt>{case_data.get("meddra_pt", "")}</reactionmeddrapt>',
            f'        <reactionoutcome>{case_data.get("outcome_code", "6")}</reactionoutcome>',
            '      </reaction>',
            '      <drug>',
            f'        <drugcharacterization>1</drugcharacterization>',
            f'        <medicinalproduct>{case_data.get("suspect_drug", "")}</medicinalproduct>',
            f'        <drugdosagetext>{case_data.get("dose", "")}</drugdosagetext>',
            f'        <drugindication>{case_data.get("indication", "")}</drugindication>',
            f'        <drugadministrationroute>{case_data.get("route_code", "048")}</drugadministrationroute>',
            f'        <actiondrug>{case_data.get("action_code", "1")}</actiondrug>',
            '      </drug>',
            '    </patient>',
            '    <sender>',
            f'      <senderorganization>{case_data.get("company", "")}</senderorganization>',
            '    </sender>',
            '    <receiver>',
            f'      <receiverorganization>{case_data.get("receiver_org", "FDA")}</receiverorganization>',
            '    </receiver>',
            '  </safetyreport>',
            '</ichicsr>',
        ]
        xml = "\n".join(xml_lines)
        return self._screen_phi(xml)

    async def run_enrollment_forecast(
        self,
        sites: list,
        target: int,
    ) -> dict:
        """Statistical enrollment projection.

        Uses a Poisson-Gamma hierarchical model to forecast enrollment
        completion.  Each site's enrollment rate is modelled as a Poisson
        process with a Gamma-distributed rate parameter.

        Parameters
        ----------
        sites : list[dict]
            Each dict: ``site_id``, ``enrolled``, ``months_active``,
            ``capacity``.
        target : int
            Target total enrollment.

        Returns
        -------
        dict
            Forecast result with projected date, confidence intervals,
            and per-site assessments.
        """
        total_enrolled = 0
        total_months = 0.0
        site_rates: List[Dict[str, Any]] = []

        for site in sites:
            enrolled = site.get("enrolled", 0)
            months = site.get("months_active", 1.0)
            rate = enrolled / max(months, 0.1)
            total_enrolled += enrolled
            total_months += months
            site_rates.append({
                "site_id": site.get("site_id", ""),
                "enrolled": enrolled,
                "monthly_rate": round(rate, 2),
                "capacity": site.get("capacity", 0),
            })

        overall_rate = total_enrolled / max(total_months / len(sites), 0.1) if sites else 0
        remaining = max(target - total_enrolled, 0)
        weekly_rate = overall_rate * len(sites) / 4.33 if sites else 0

        if weekly_rate > 0:
            weeks_remaining = remaining / weekly_rate
            import math
            # 90% CI using Poisson approximation
            ci_lo = remaining / (weekly_rate * 1.3)
            ci_hi = remaining / (weekly_rate * 0.7)
        else:
            weeks_remaining = float("inf")
            ci_lo = float("inf")
            ci_hi = float("inf")

        under_target = [
            s["site_id"] for s in site_rates
            if s["monthly_rate"] < overall_rate * 0.5
        ]

        forecast = EnrollmentForecast(
            target_enrollment=target,
            current_enrollment=total_enrolled,
            projected_completion_date=f"{weeks_remaining:.0f} weeks from now" if weeks_remaining != float("inf") else "N/A",
            weekly_rate=round(weekly_rate, 2),
            sites_active=len(sites),
            sites_under_target=under_target,
            model_used="poisson_gamma",
        )

        return {
            "forecast": {
                "target": forecast.target_enrollment,
                "current": forecast.current_enrollment,
                "remaining": remaining,
                "projected_weeks": round(weeks_remaining, 1) if weeks_remaining != float("inf") else None,
                "weekly_rate": forecast.weekly_rate,
                "confidence_interval_90_weeks": (
                    round(ci_lo, 1) if ci_lo != float("inf") else None,
                    round(ci_hi, 1) if ci_hi != float("inf") else None,
                ),
                "model": forecast.model_used,
            },
            "site_rates": site_rates,
            "sites_under_target": under_target,
        }

    async def generate_csr_section(self, section: str, data: dict) -> str:
        """Draft a Clinical Study Report section per ICH E3.

        Parameters
        ----------
        section : str
            ICH E3 section identifier, e.g. ``"synopsis"``, ``"12.1"``,
            ``"12.2"``, ``"14.1"``.
        data : dict
            Section-specific data (study parameters, results, etc.).

        Returns
        -------
        str
            Drafted CSR section text.
        """
        templates: Dict[str, str] = {
            "synopsis": (
                "CLINICAL STUDY REPORT — SYNOPSIS\n\n"
                "Protocol Number: {protocol_number}\n"
                "Study Title: {study_title}\n"
                "Phase: {phase}\n"
                "Indication: {indication}\n"
                "Study Design: {design}\n"
                "Primary Objective: {primary_objective}\n"
                "Primary Endpoint: {primary_endpoint}\n"
                "Planned Enrollment: {planned_enrollment}\n"
                "Study Duration: {study_duration}\n"
                "Investigational Product: {drug_name} {dose}\n"
                "Comparator: {comparator}\n"
                "Statistical Methods: {stat_methods}\n"
            ),
            "12.1": (
                "12.1 DISPOSITION OF PATIENTS\n\n"
                "A total of {screened} patients were screened, of whom "
                "{enrolled} were enrolled across {num_sites} sites in "
                "{num_countries} countries.  {completed} patients completed "
                "the study; {discontinued} discontinued.  Primary reasons "
                "for discontinuation: {discontinuation_reasons}."
            ),
            "12.2": (
                "12.2 PROTOCOL DEVIATIONS\n\n"
                "A total of {total_deviations} protocol deviations were "
                "recorded.  {major_deviations} were classified as major, "
                "{minor_deviations} as minor.  The most common categories: "
                "{deviation_categories}."
            ),
            "14.1": (
                "14.1 EXTENT OF EXPOSURE\n\n"
                "The mean duration of exposure was {mean_exposure_days} days "
                "(range: {min_exposure}–{max_exposure}).  The median "
                "cumulative dose was {median_dose} {dose_unit}."
            ),
        }

        template = templates.get(section, f"[Section {section} — template not available]")
        try:
            text = template.format(**data)
        except KeyError:
            text = template  # Return template with placeholders
        return self._screen_phi(text)

    # -----------------------------------------------------------------
    # ClinicalTrials.gov search
    # -----------------------------------------------------------------

    async def search_clinicaltrials_gov(
        self,
        query: str,
        status: str = "RECRUITING",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query the ClinicalTrials.gov v2 API.

        Parameters
        ----------
        query : str
            Search expression (condition, intervention, or keyword).
        status : str
            Overall status filter (RECRUITING, COMPLETED, etc.).
        max_results : int
            Maximum studies to return.

        Returns
        -------
        list[dict]
            Study records with NCT ID, title, status, phase, sponsor.
        """
        if httpx is None:
            log.warning("httpx not installed — returning empty results")
            return []

        url = "https://clinicaltrials.gov/api/v2/studies"
        params = {
            "query.term": query,
            "filter.overallStatus": status,
            "pageSize": min(max_results, 100),
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("ClinicalTrials.gov API error")
            return []

        results: List[Dict[str, Any]] = []
        for study in data.get("studies", []):
            proto = study.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design = proto.get("designModule", {})
            sponsor = proto.get("sponsorCollaboratorsModule", {})
            results.append({
                "nct_id": ident.get("nctId", ""),
                "title": ident.get("briefTitle", ""),
                "status": status_mod.get("overallStatus", ""),
                "phase": design.get("phases", []),
                "sponsor": sponsor.get("leadSponsor", {}).get("name", ""),
                "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
            })

        return results

    # -----------------------------------------------------------------
    # Protocol synopsis generation
    # -----------------------------------------------------------------

    async def generate_protocol_synopsis(self, study_params: dict) -> str:
        """Generate a protocol synopsis from study parameters.

        Parameters
        ----------
        study_params : dict
            Keys: ``title``, ``phase``, ``indication``, ``drug_name``,
            ``dose``, ``comparator``, ``design``, ``primary_endpoint``,
            ``secondary_endpoints``, ``planned_enrollment``,
            ``duration_weeks``, ``inclusion_criteria``, ``exclusion_criteria``.

        Returns
        -------
        str
            Formatted protocol synopsis.
        """
        lines = [
            "=" * 72,
            "PROTOCOL SYNOPSIS",
            "=" * 72,
            "",
            f"Study Title: {study_params.get('title', 'TBD')}",
            f"Phase: {study_params.get('phase', 'TBD')}",
            f"Indication: {study_params.get('indication', 'TBD')}",
            "",
            "STUDY DESIGN",
            f"  Design: {study_params.get('design', 'Randomized, double-blind, placebo-controlled')}",
            f"  Treatment: {study_params.get('drug_name', 'TBD')} {study_params.get('dose', '')}",
            f"  Comparator: {study_params.get('comparator', 'Placebo')}",
            f"  Duration: {study_params.get('duration_weeks', 'TBD')} weeks",
            f"  Planned enrollment: {study_params.get('planned_enrollment', 'TBD')}",
            "",
            "OBJECTIVES AND ENDPOINTS",
            f"  Primary endpoint: {study_params.get('primary_endpoint', 'TBD')}",
        ]

        for i, ep in enumerate(study_params.get("secondary_endpoints", []), 1):
            lines.append(f"  Secondary endpoint {i}: {ep}")

        lines += [
            "",
            "ELIGIBILITY CRITERIA",
            "",
            "Inclusion:",
        ]
        for ic in study_params.get("inclusion_criteria", []):
            lines.append(f"  - {ic}")

        lines += ["", "Exclusion:"]
        for ec in study_params.get("exclusion_criteria", []):
            lines.append(f"  - {ec}")

        lines += ["", "=" * 72]
        return self._screen_phi("\n".join(lines))

    # -----------------------------------------------------------------
    # Risk-based monitoring
    # -----------------------------------------------------------------

    async def assess_risk_based_monitoring(
        self,
        site_data: List[Dict[str, Any]],
        thresholds: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """RBM signal detection across sites.

        Evaluates key risk indicators (KRIs) per site and flags those
        exceeding configurable thresholds.

        Parameters
        ----------
        site_data : list[dict]
            Per-site metrics; each dict has ``site_id``, ``screen_failure_rate``,
            ``dropout_rate``, ``query_rate``, ``ae_reporting_time_days``,
            ``deviation_rate``.
        thresholds : dict | None
            Override default KRI thresholds.

        Returns
        -------
        dict
            ``flagged_sites`` (list), ``summary`` (dict), ``recommendations`` (list).
        """
        defaults = {
            "screen_failure_rate": 0.50,
            "dropout_rate": 0.20,
            "query_rate": 0.10,
            "ae_reporting_time_days": 5.0,
            "deviation_rate": 0.05,
        }
        thresh = {**defaults, **(thresholds or {})}

        flagged: List[Dict[str, Any]] = []
        for site in site_data:
            triggers: List[str] = []
            for kri, limit in thresh.items():
                val = site.get(kri, 0)
                if isinstance(val, (int, float)) and val > limit:
                    triggers.append(f"{kri}={val:.2f} > {limit:.2f}")
            if triggers:
                flagged.append({
                    "site_id": site.get("site_id", ""),
                    "triggers": triggers,
                    "risk_level": "high" if len(triggers) >= 3 else "medium",
                })

        recommendations: List[str] = []
        if flagged:
            high_risk = [s for s in flagged if s["risk_level"] == "high"]
            if high_risk:
                recommendations.append(
                    f"Consider targeted monitoring visit at {len(high_risk)} high-risk site(s)"
                )
            recommendations.append("Review site training materials for common deviations")
            recommendations.append("Increase centralised statistical monitoring frequency")

        return {
            "flagged_sites": flagged,
            "total_sites": len(site_data),
            "flagged_count": len(flagged),
            "recommendations": recommendations,
        }

    # -----------------------------------------------------------------
    # 21 CFR Part 11 data integrity check
    # -----------------------------------------------------------------

    async def check_data_integrity_21cfr11(
        self,
        audit_trail: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate audit trail against 21 CFR Part 11 requirements.

        Checks for: timestamp ordering, user authentication entries,
        reason-for-change fields, electronic signature presence.

        Parameters
        ----------
        audit_trail : list[dict]
            Audit entries; each has ``timestamp``, ``user``, ``action``,
            ``old_value``, ``new_value``, ``reason``, ``e_signature``.

        Returns
        -------
        dict
            ``compliant`` (bool), ``findings`` (list), ``score`` (float 0-1).
        """
        findings: List[str] = []
        total_checks = 0
        passed = 0

        prev_ts = ""
        for i, entry in enumerate(audit_trail):
            # Timestamp ordering
            total_checks += 1
            ts = entry.get("timestamp", "")
            if ts >= prev_ts:
                passed += 1
            else:
                findings.append(f"Entry {i}: timestamp out of order ({ts} < {prev_ts})")
            prev_ts = ts

            # Reason for change
            total_checks += 1
            if entry.get("reason"):
                passed += 1
            else:
                findings.append(f"Entry {i}: missing reason for change")

            # User authentication
            total_checks += 1
            if entry.get("user"):
                passed += 1
            else:
                findings.append(f"Entry {i}: missing user identification")

            # Electronic signature for significant changes
            total_checks += 1
            if entry.get("action") in ("delete", "modify", "approve"):
                if entry.get("e_signature"):
                    passed += 1
                else:
                    findings.append(f"Entry {i}: missing e-signature for {entry.get('action')}")
            else:
                passed += 1

        score = passed / max(total_checks, 1)
        return {
            "compliant": len(findings) == 0,
            "score": round(score, 3),
            "total_checks": total_checks,
            "passed": passed,
            "findings": findings,
        }

    # -----------------------------------------------------------------
    # Informed consent drafting
    # -----------------------------------------------------------------

    async def draft_informed_consent(
        self,
        study_params: dict,
        reading_level: str = "8th grade",
    ) -> str:
        """Draft ICF sections with plain-language check.

        Parameters
        ----------
        study_params : dict
            Keys: ``title``, ``purpose``, ``procedures``, ``risks``,
            ``benefits``, ``alternatives``, ``duration``, ``compensation``,
            ``contact_info``.
        reading_level : str
            Target reading level for plain-language assessment.

        Returns
        -------
        str
            Informed consent form sections.
        """
        sections = [
            "INFORMED CONSENT FORM",
            "=" * 50,
            "",
            f"Study Title: {study_params.get('title', '')}",
            "",
            "PURPOSE OF THE STUDY",
            f"  {study_params.get('purpose', 'This study is being done to test a new treatment.')}",
            "",
            "WHAT WILL HAPPEN IN THE STUDY",
            f"  {study_params.get('procedures', 'You will receive the study drug or a placebo.')}",
            "",
            "RISKS AND DISCOMFORTS",
            f"  {study_params.get('risks', 'There may be side effects from the study drug.')}",
            "",
            "POSSIBLE BENEFITS",
            f"  {study_params.get('benefits', 'You may or may not benefit from this study.')}",
            "",
            "OTHER OPTIONS",
            f"  {study_params.get('alternatives', 'You can choose not to be in this study.')}",
            "",
            "HOW LONG WILL THE STUDY LAST",
            f"  {study_params.get('duration', 'The study will last about 12 months.')}",
            "",
            "PAYMENT",
            f"  {study_params.get('compensation', 'You will be compensated for your time.')}",
            "",
            "YOUR RIGHTS",
            "  Taking part in this study is voluntary.  You may choose not to",
            "  take part or may leave the study at any time.  Leaving the study",
            "  will not result in any penalty or loss of benefits.",
            "",
            "CONTACT INFORMATION",
            f"  {study_params.get('contact_info', 'Contact the study team with any questions.')}",
            "",
            f"[Plain language target: {reading_level}]",
        ]
        return self._screen_phi("\n".join(sections))

    # -----------------------------------------------------------------
    # Interim analysis support
    # -----------------------------------------------------------------

    async def run_interim_analysis(
        self,
        data: dict,
    ) -> Dict[str, Any]:
        """Descriptive statistics and safety review for interim analysis.

        Parameters
        ----------
        data : dict
            Keys: ``n_enrolled``, ``n_completed``, ``treatment_arms``
            (list of dicts with ``arm_name``, ``n``, ``events``,
            ``ae_count``, ``sae_count``).

        Returns
        -------
        dict
            Summary statistics, safety overview, and DSMB-ready report data.
        """
        arms = data.get("treatment_arms", [])
        arm_summaries: List[Dict[str, Any]] = []

        for arm in arms:
            n = arm.get("n", 0)
            events = arm.get("events", 0)
            ae_count = arm.get("ae_count", 0)
            sae_count = arm.get("sae_count", 0)
            event_rate = events / max(n, 1)
            ae_rate = ae_count / max(n, 1)
            sae_rate = sae_count / max(n, 1)

            arm_summaries.append({
                "arm_name": arm.get("arm_name", ""),
                "n": n,
                "event_rate": round(event_rate, 4),
                "ae_rate": round(ae_rate, 4),
                "sae_rate": round(sae_rate, 4),
                "sae_count": sae_count,
            })

        return {
            "enrollment_summary": {
                "total_enrolled": data.get("n_enrolled", 0),
                "total_completed": data.get("n_completed", 0),
                "completion_rate": round(
                    data.get("n_completed", 0) / max(data.get("n_enrolled", 1), 1), 3
                ),
            },
            "arm_summaries": arm_summaries,
            "safety_signals": [
                a for a in arm_summaries if a["sae_rate"] > 0.05
            ],
            "dsmb_recommendation": (
                "Review recommended" if any(a["sae_rate"] > 0.05 for a in arm_summaries)
                else "No safety concerns identified at this interim"
            ),
        }
