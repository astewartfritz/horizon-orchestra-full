"""Horizon Orchestra — Pharmacovigilance Agent.

Drug safety surveillance and signal detection across the product
lifecycle.  Handles spontaneous report triage, literature monitoring,
disproportionality-based signal detection, PSUR/PBRER authoring,
REMS compliance monitoring, and benefit-risk assessment.

Regulatory alignment
--------------------
* FDA MedWatch (21 CFR 314.80 / 314.98)
* EMA EudraVigilance Regulation (EC) No 726/2004
* ICH E2C(R2) Periodic Benefit-Risk Evaluation Reports
* ICH E2D Post-Approval Safety Data Management
* ICH E2F Development Safety Update Report
* ICH E2B(R3) Individual Case Safety Reports

Signal detection methods
------------------------
* Proportional Reporting Ratio (PRR)
* Reporting Odds Ratio (ROR)
* Empirical Bayes Geometric Mean (EBGM / Multi-item Gamma Poisson Shrinker)
* Information Component (IC / Bayesian Confidence Propagation NN)

Target customers
----------------
Johnson & Johnson, Moderna, Pfizer, Merck, AstraZeneca, Roche.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

# ---------------------------------------------------------------------------
# HIPAA / audit guardrails
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
# Optional HTTP client for PubMed / FAERS / EudraVigilance
# ---------------------------------------------------------------------------
try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

__all__ = [
    "PharmacovigilanceAgent",
    "SafetySignal",
    "SignalStrength",
    "SpontaneousReport",
    "BenefitRiskFramework",
    "ReportingTimeline",
]

log = logging.getLogger("orchestra.verticals.healthcare.pharmacovigilance")

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class SignalStrength(str, Enum):
    """Strength of a detected safety signal."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


class WHOCausality(str, Enum):
    """WHO-UMC system for standardised causality assessment."""
    CERTAIN = "certain"
    PROBABLE = "probable/likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    CONDITIONAL = "conditional/unclassified"
    UNASSESSABLE = "unassessable/unclassifiable"


class ReportCompleteness(str, Enum):
    """Vigibase-style completeness rating."""
    WELL_DOCUMENTED = "well_documented"
    SUFFICIENT = "sufficient_information"
    INSUFFICIENT = "insufficient_information"
    EMPTY = "empty"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SpontaneousReport:
    """Individual spontaneous safety report (FAERS-style)."""
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    report_type: str = "spontaneous"       # spontaneous, literature, study
    source: str = "healthcare_professional"  # HCP, consumer, literature
    country: str = "US"
    received_date: str = ""
    patient_age: Optional[int] = None
    patient_sex: Optional[str] = None
    suspect_drugs: List[str] = field(default_factory=list)
    concomitant_drugs: List[str] = field(default_factory=list)
    reactions: List[str] = field(default_factory=list)
    meddra_pts: List[int] = field(default_factory=list)
    serious: bool = False
    seriousness_criteria: List[str] = field(default_factory=list)
    outcome: str = ""
    narrative: str = ""
    completeness: ReportCompleteness = ReportCompleteness.SUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "source": self.source,
            "country": self.country,
            "received_date": self.received_date,
            "patient_age": self.patient_age,
            "patient_sex": self.patient_sex,
            "suspect_drugs": self.suspect_drugs,
            "reactions": self.reactions,
            "meddra_pts": self.meddra_pts,
            "serious": self.serious,
            "seriousness_criteria": self.seriousness_criteria,
            "outcome": self.outcome,
            "completeness": self.completeness.value,
        }


@dataclass
class SafetySignal:
    """A detected safety signal from disproportionality analysis."""
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    drug: str = ""
    event_pt: str = ""
    event_pt_code: int = 0
    prr: float = 0.0
    ror: float = 0.0
    ebgm: float = 0.0
    ic: float = 0.0
    case_count: int = 0
    expected_count: float = 0.0
    strength: SignalStrength = SignalStrength.NONE
    chi_squared: float = 0.0
    p_value: Optional[float] = None
    date_detected: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "drug": self.drug,
            "event_pt": self.event_pt,
            "event_pt_code": self.event_pt_code,
            "prr": round(self.prr, 3),
            "ror": round(self.ror, 3),
            "ebgm": round(self.ebgm, 3),
            "ic": round(self.ic, 3),
            "case_count": self.case_count,
            "expected_count": round(self.expected_count, 3),
            "strength": self.strength.value,
            "chi_squared": round(self.chi_squared, 3),
            "p_value": round(self.p_value, 6) if self.p_value is not None else None,
            "date_detected": self.date_detected,
        }


@dataclass
class BenefitRiskFramework:
    """Benefit-Risk Assessment Template (BRAT) framework output."""
    drug: str = ""
    indication: str = ""
    benefits: List[Dict[str, Any]] = field(default_factory=list)
    risks: List[Dict[str, Any]] = field(default_factory=list)
    overall_assessment: str = ""
    recommendation: str = ""
    uncertainty_factors: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)


@dataclass
class ReportingTimeline:
    """Expedited reporting deadline calculator."""
    case_id: str = ""
    serious: bool = False
    fatal_or_life_threatening: bool = False
    listed_expected: bool = True
    awareness_date: str = ""
    deadline_calendar_days: int = 0
    deadline_date: str = ""
    regulation: str = ""
    submitted: bool = False


# ===================================================================
# PharmacovigilanceAgent
# ===================================================================

class PharmacovigilanceAgent:
    """Drug safety surveillance and signal detection.

    Covers: literature monitoring, spontaneous report triage, signal
    detection, PSUR/PBRER authoring, REMS monitoring, benefit-risk
    assessment.

    Regulatory: FDA MedWatch, EMA EudraVigilance, ICH E2C/E2D/E2F.

    HIPAA controls
    --------------
    * All LLM outputs pass through :class:`PHIScanner` before return.
    * PHI access events logged to :class:`AuditLedger`.
    * Raw PHI never stored in conversation memory.
    """

    TOOLS: List[str] = [
        "monitor_medical_literature",
        "triage_spontaneous_report",
        "detect_safety_signal",
        "assess_signal_significance",
        "draft_psur_section",
        "generate_benefit_risk_framework",
        "monitor_rems_compliance",
        "search_faers_database",
        "search_eudravigilance",
        "calculate_reporting_timelines",
        "generate_aggregate_report",
        "screen_literature_pubmed",
        "assess_causality_who_umc",
        "generate_medical_writing",
        "submit_eudravigilance_xml",
    ]

    def __init__(
        self,
        model: str = "kimi-k2.5",
        audit_ledger: Any = None,
        phi_scanner: Any = None,
    ) -> None:
        self.model = model
        self._audit = audit_ledger
        self._phi = phi_scanner or (PHIScanner() if PHIScanner else None)
        self._agent_id = f"pv-{uuid.uuid4().hex[:8]}"
        log.info("PharmacovigilanceAgent initialised  agent_id=%s", self._agent_id)

    # -----------------------------------------------------------------
    # PHI guardrails
    # -----------------------------------------------------------------

    def _screen_phi(self, text: str) -> str:
        if self._phi is None:
            return text
        matches = self._phi.scan(text)
        if not matches:
            return text
        result = self._phi.redact(text)
        # redact() returns (redacted_text, matches) tuple
        redacted = result[0] if isinstance(result, tuple) else result
        log.warning("PHI detected in PV output — %d matches redacted", len(matches))
        return redacted

    async def _log_phi_access(self, action: str, resource: str) -> None:
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
            log.exception("Failed to write PV audit event")

    # -----------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Domain-expert system prompt for pharmacovigilance."""
        return (
            "You are an expert Pharmacovigilance AI assistant within "
            "Horizon Orchestra.  Your expertise spans:\n\n"
            "SAFETY SURVEILLANCE\n"
            "- Spontaneous report triage and completeness assessment\n"
            "- Individual Case Safety Report (ICSR) processing\n"
            "- Literature monitoring for adverse event signals\n"
            "- MedDRA coding and WHO Drug Dictionary mapping\n\n"
            "SIGNAL DETECTION & EVALUATION\n"
            "- Disproportionality analysis: PRR, ROR, EBGM (MGPS), IC (BCPNN)\n"
            "- Signal validation and clinical assessment\n"
            "- Time-to-onset analysis and temporal patterns\n"
            "- Subgroup analysis by age, sex, geography\n\n"
            "REGULATORY REPORTING\n"
            "- FDA MedWatch / FAERS (21 CFR 314.80)\n"
            "- EMA EudraVigilance (Regulation EC 726/2004)\n"
            "- Expedited reporting: 7-day (fatal/LT), 15-day (serious unexpected)\n"
            "- ICH E2B(R3) ICSR XML generation\n\n"
            "PERIODIC REPORTS\n"
            "- PSUR/PBRER authoring per ICH E2C(R2)\n"
            "- DSUR authoring per ICH E2F\n"
            "- Aggregate safety data analysis\n\n"
            "RISK MANAGEMENT\n"
            "- Benefit-risk assessment (BRAT framework)\n"
            "- REMS program compliance monitoring\n"
            "- Risk Evaluation and Mitigation Strategies\n\n"
            "HIPAA: Never output raw PHI. Use de-identified tokens only.\n"
        )

    # -----------------------------------------------------------------
    # Literature monitoring
    # -----------------------------------------------------------------

    async def screen_literature_pubmed(
        self,
        query: str,
        max_results: int = 20,
        date_range_days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Screen PubMed for adverse event literature.

        Uses NCBI E-utilities to search for recent publications
        mentioning the drug/AE combination.

        Parameters
        ----------
        query : str
            PubMed search query (drug + adverse event terms).
        max_results : int
            Maximum articles to return.
        date_range_days : int
            Look back period in days.

        Returns
        -------
        list[dict]
            Articles with PMID, title, authors, abstract snippet, date.
        """
        if httpx is None:
            log.warning("httpx not installed — returning empty PubMed results")
            return []

        base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        min_date = (datetime.now(timezone.utc) - timedelta(days=date_range_days)).strftime("%Y/%m/%d")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: ESearch
                search_resp = await client.get(
                    f"{base_url}/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": query,
                        "retmax": max_results,
                        "mindate": min_date,
                        "datetype": "pdat",
                        "retmode": "json",
                    },
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()
                pmids = search_data.get("esearchresult", {}).get("idlist", [])

                if not pmids:
                    return []

                # Step 2: ESummary
                summary_resp = await client.get(
                    f"{base_url}/esummary.fcgi",
                    params={
                        "db": "pubmed",
                        "id": ",".join(pmids),
                        "retmode": "json",
                    },
                )
                summary_resp.raise_for_status()
                summary_data = summary_resp.json()

        except Exception:  # noqa: BLE001
            log.exception("PubMed API error")
            return []

        results: List[Dict[str, Any]] = []
        for pmid in pmids:
            article = summary_data.get("result", {}).get(pmid, {})
            if not article or pmid == "uids":
                continue
            results.append({
                "pmid": pmid,
                "title": article.get("title", ""),
                "authors": [
                    a.get("name", "") for a in article.get("authors", [])[:5]
                ],
                "source": article.get("source", ""),
                "pub_date": article.get("pubdate", ""),
                "doi": article.get("elocationid", ""),
            })

        return results

    # -----------------------------------------------------------------
    # Spontaneous report triage
    # -----------------------------------------------------------------

    async def triage_spontaneous_report(
        self,
        report_data: dict,
    ) -> Dict[str, Any]:
        """Triage an incoming spontaneous safety report.

        Performs completeness check, seriousness assessment, causality
        preliminary evaluation, and determines reporting timeline.

        Parameters
        ----------
        report_data : dict
            Incoming report fields matching :class:`SpontaneousReport`.

        Returns
        -------
        dict
            ``triage_result`` with completeness, seriousness, priority,
            timeline, required_followup.
        """
        await self._log_phi_access("triage_report", report_data.get("report_id", "unknown"))

        # Completeness check (4 minimum criteria for valid ICSR)
        required_fields = ["suspect_drugs", "reactions", "source", "country"]
        missing = [f for f in required_fields if not report_data.get(f)]
        has_patient = bool(report_data.get("patient_age") or report_data.get("patient_sex"))

        if len(missing) == 0 and has_patient:
            completeness = ReportCompleteness.WELL_DOCUMENTED
        elif len(missing) <= 1:
            completeness = ReportCompleteness.SUFFICIENT
        elif len(missing) <= 2:
            completeness = ReportCompleteness.INSUFFICIENT
        else:
            completeness = ReportCompleteness.EMPTY

        # Seriousness assessment
        serious = report_data.get("serious", False)
        seriousness_criteria = report_data.get("seriousness_criteria", [])
        narrative = report_data.get("narrative", "").lower()

        serious_keywords = {
            "death": "results in death",
            "died": "results in death",
            "fatal": "results in death",
            "life-threatening": "life-threatening",
            "hospitalized": "requires hospitalisation",
            "hospitalised": "requires hospitalisation",
            "hospitalization": "requires hospitalisation",
            "disability": "persistent/significant disability",
            "congenital": "congenital anomaly/birth defect",
        }
        for kw, criterion in serious_keywords.items():
            if kw in narrative and criterion not in seriousness_criteria:
                seriousness_criteria.append(criterion)
                serious = True

        # Priority assignment
        fatal = "results in death" in seriousness_criteria
        life_threatening = "life-threatening" in seriousness_criteria

        if fatal or life_threatening:
            priority = "critical"
            deadline_days = 7
        elif serious:
            priority = "high"
            deadline_days = 15
        else:
            priority = "routine"
            deadline_days = 90

        # Follow-up requirements
        followup: List[str] = []
        if not has_patient:
            followup.append("Obtain patient demographics")
        if not report_data.get("narrative"):
            followup.append("Request detailed event narrative")
        if not report_data.get("concomitant_drugs"):
            followup.append("Request concomitant medication list")
        if serious and not report_data.get("outcome"):
            followup.append("Follow up on patient outcome")

        awareness_date = report_data.get(
            "received_date",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        return {
            "triage_result": {
                "completeness": completeness.value,
                "serious": serious,
                "seriousness_criteria": seriousness_criteria,
                "priority": priority,
                "reporting_deadline_days": deadline_days,
                "awareness_date": awareness_date,
                "deadline_date": (
                    datetime.now(timezone.utc) + timedelta(days=deadline_days)
                ).strftime("%Y-%m-%d"),
                "required_followup": followup,
                "missing_fields": missing,
                "valid_icsr": completeness != ReportCompleteness.EMPTY,
            }
        }

    # -----------------------------------------------------------------
    # Signal detection — disproportionality analysis
    # -----------------------------------------------------------------

    async def detect_safety_signal(
        self,
        drug: str,
        event_pt: str,
        contingency: Dict[str, int],
    ) -> SafetySignal:
        """Run disproportionality analysis for a drug-event pair.

        Computes PRR, ROR, EBGM, and IC from a 2×2 contingency table.

        Parameters
        ----------
        drug : str
            Drug name.
        event_pt : str
            MedDRA Preferred Term.
        contingency : dict
            2×2 table: ``a`` (drug+event), ``b`` (drug+no event),
            ``c`` (no drug+event), ``d`` (no drug+no event).

        Returns
        -------
        SafetySignal
            Signal with all disproportionality metrics.
        """
        a = contingency.get("a", 0)
        b = contingency.get("b", 0)
        c = contingency.get("c", 0)
        d = contingency.get("d", 0)

        N = a + b + c + d
        if N == 0:
            return SafetySignal(drug=drug, event_pt=event_pt)

        # Expected count under independence
        expected = ((a + b) * (a + c)) / max(N, 1)

        # PRR = (a/(a+b)) / (c/(c+d))
        prr = 0.0
        if (a + b) > 0 and (c + d) > 0 and c > 0:
            prr = (a / (a + b)) / (c / (c + d))

        # ROR = (a*d) / (b*c)
        ror = 0.0
        if b > 0 and c > 0:
            ror = (a * d) / (b * c)

        # Chi-squared
        chi_sq = 0.0
        if expected > 0:
            chi_sq = ((a - expected) ** 2) / expected

        # EBGM (simplified MGPS)
        ebgm = 0.0
        if expected > 0:
            # Posterior mean of Gamma(a + 0.5, 1/(expected + 1))
            ebgm = (a + 0.5) / (expected + 1)

        # Information Component (simplified BCPNN)
        ic = 0.0
        if expected > 0 and a > 0:
            ic = math.log2((a + 0.5) / (expected + 0.5))

        # Signal strength classification
        strength = SignalStrength.NONE
        if prr >= 2.0 and chi_sq >= 4.0 and a >= 3:
            strength = SignalStrength.STRONG
        elif prr >= 2.0 and a >= 3:
            strength = SignalStrength.MODERATE
        elif prr >= 1.5 and a >= 2:
            strength = SignalStrength.WEAK

        # Approximate p-value from chi-squared (1 df)
        p_value: Optional[float] = None
        if chi_sq > 0:
            # Approximation: p ≈ exp(-chi_sq/2) for chi_sq > 3
            p_value = math.exp(-chi_sq / 2) if chi_sq < 50 else 0.0

        return SafetySignal(
            drug=drug,
            event_pt=event_pt,
            prr=prr,
            ror=ror,
            ebgm=ebgm,
            ic=ic,
            case_count=a,
            expected_count=expected,
            strength=strength,
            chi_squared=chi_sq,
            p_value=p_value,
        )

    async def assess_signal_significance(
        self,
        signal: SafetySignal,
        clinical_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate clinical significance of a detected signal.

        Parameters
        ----------
        signal : SafetySignal
            Previously detected signal.
        clinical_context : dict | None
            Additional context: ``known_class_effect``, ``mechanism``,
            ``temporal_pattern``, ``dose_response``, ``dechallenge_rate``.

        Returns
        -------
        dict
            Clinical assessment with action recommendations.
        """
        ctx = clinical_context or {}
        assessment: Dict[str, Any] = {
            "signal_id": signal.signal_id,
            "drug": signal.drug,
            "event": signal.event_pt,
            "statistical_strength": signal.strength.value,
            "clinical_plausibility": "unknown",
            "action_required": [],
        }

        # Clinical plausibility
        plausibility_score = 0
        if ctx.get("known_class_effect"):
            plausibility_score += 2
            assessment["clinical_plausibility"] = "high"
        if ctx.get("mechanism"):
            plausibility_score += 1
        if ctx.get("temporal_pattern") == "consistent":
            plausibility_score += 1
        if ctx.get("dose_response"):
            plausibility_score += 1
        if ctx.get("dechallenge_rate", 0) > 0.5:
            plausibility_score += 1

        if plausibility_score >= 4:
            assessment["clinical_plausibility"] = "high"
        elif plausibility_score >= 2:
            assessment["clinical_plausibility"] = "moderate"
        else:
            assessment["clinical_plausibility"] = "low"

        # Action recommendations
        if signal.strength in (SignalStrength.STRONG, SignalStrength.MODERATE):
            assessment["action_required"].append("Initiate formal signal evaluation")
            assessment["action_required"].append("Perform targeted literature review")
            if signal.strength == SignalStrength.STRONG:
                assessment["action_required"].append("Consider regulatory notification")
                assessment["action_required"].append("Update PSUR/PBRER signal section")
                assessment["action_required"].append("Evaluate label update necessity")
        elif signal.strength == SignalStrength.WEAK:
            assessment["action_required"].append("Continue monitoring")
            assessment["action_required"].append("Include in next periodic signal review")

        assessment["overall_priority"] = (
            "immediate" if signal.strength == SignalStrength.STRONG
            else "elevated" if signal.strength == SignalStrength.MODERATE
            else "routine"
        )

        return assessment

    # -----------------------------------------------------------------
    # PSUR / PBRER section drafting
    # -----------------------------------------------------------------

    async def draft_psur_section(
        self,
        section: str,
        data: dict,
    ) -> str:
        """Draft a PSUR/PBRER section per ICH E2C(R2).

        Parameters
        ----------
        section : str
            Section name, e.g. ``"executive_summary"``,
            ``"worldwide_marketing_status"``, ``"estimated_exposure"``,
            ``"signal_evaluation"``, ``"benefit_risk_analysis"``.
        data : dict
            Section-specific data.

        Returns
        -------
        str
            Drafted section text.
        """
        templates: Dict[str, str] = {
            "executive_summary": (
                "PSUR/PBRER — EXECUTIVE SUMMARY\n\n"
                "Product: {product_name}\n"
                "Active substance: {active_substance}\n"
                "Reporting period: {period_start} to {period_end}\n"
                "International birth date: {ibd}\n\n"
                "During this reporting period, {total_icsrs} ICSRs were "
                "received ({serious_count} serious, {fatal_count} fatal).  "
                "{new_signals} new signals were detected.  The overall "
                "benefit-risk balance remains {br_conclusion}."
            ),
            "estimated_exposure": (
                "5. ESTIMATED EXPOSURE AND USE PATTERNS\n\n"
                "Cumulative patient exposure: {cumulative_patients} patients\n"
                "Patient exposure during reporting period: {period_patients}\n"
                "Estimated patient-years: {patient_years}\n"
                "Geographic distribution: {geo_distribution}\n"
                "Sources: {exposure_sources}"
            ),
            "signal_evaluation": (
                "16. SIGNAL AND RISK EVALUATION\n\n"
                "16.1 Summary of Safety Concerns\n"
                "During this period, {n_signals} signals were evaluated:\n"
                "{signal_summaries}\n\n"
                "16.2 Signal Evaluation\n"
                "{signal_details}\n\n"
                "16.3 Evaluation of Risks and New Information\n"
                "{risk_evaluation}"
            ),
            "benefit_risk_analysis": (
                "17. BENEFIT-RISK ANALYSIS\n\n"
                "17.1 Benefit Analysis\n"
                "{benefit_summary}\n\n"
                "17.2 Risk Analysis\n"
                "{risk_summary}\n\n"
                "17.3 Benefit-Risk Evaluation\n"
                "The benefit-risk balance for {product_name} in the approved "
                "indication(s) remains {br_conclusion}.  {additional_notes}"
            ),
        }

        template = templates.get(section, f"[Section '{section}' — template not available]")
        try:
            text = template.format(**data)
        except KeyError:
            text = template
        return self._screen_phi(text)

    # -----------------------------------------------------------------
    # Benefit-risk assessment (BRAT framework)
    # -----------------------------------------------------------------

    async def generate_benefit_risk_framework(
        self,
        drug: str,
        indication: str,
        benefits: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a Benefit-Risk Assessment using BRAT framework.

        Parameters
        ----------
        drug : str
            Drug name.
        indication : str
            Therapeutic indication.
        benefits : list[dict]
            Each: ``outcome``, ``magnitude``, ``certainty``, ``source``.
        risks : list[dict]
            Each: ``outcome``, ``frequency``, ``severity``, ``reversibility``,
            ``source``.

        Returns
        -------
        dict
            Structured BRAT assessment.
        """
        benefit_score = 0.0
        for b in benefits:
            mag = {"high": 3, "moderate": 2, "low": 1}.get(
                b.get("magnitude", "moderate"), 2
            )
            cert = {"high": 1.0, "moderate": 0.7, "low": 0.4}.get(
                b.get("certainty", "moderate"), 0.7
            )
            benefit_score += mag * cert

        risk_score = 0.0
        for r in risks:
            freq = {"very_common": 3, "common": 2.5, "uncommon": 2,
                     "rare": 1.5, "very_rare": 1}.get(
                r.get("frequency", "uncommon"), 2
            )
            sev = {"fatal": 5, "severe": 4, "moderate": 2.5, "mild": 1}.get(
                r.get("severity", "moderate"), 2.5
            )
            rev = {"irreversible": 1.0, "partially_reversible": 0.7,
                   "reversible": 0.4}.get(
                r.get("reversibility", "reversible"), 0.4
            )
            risk_score += freq * sev * rev

        ratio = benefit_score / max(risk_score, 0.01)

        if ratio > 2.0:
            conclusion = "favourable"
        elif ratio > 1.0:
            conclusion = "favourable with monitoring"
        elif ratio > 0.5:
            conclusion = "uncertain — additional data needed"
        else:
            conclusion = "unfavourable"

        return {
            "drug": drug,
            "indication": indication,
            "benefit_score": round(benefit_score, 2),
            "risk_score": round(risk_score, 2),
            "benefit_risk_ratio": round(ratio, 3),
            "conclusion": conclusion,
            "benefits": benefits,
            "risks": risks,
            "framework": "BRAT (Benefit-Risk Action Team)",
        }

    # -----------------------------------------------------------------
    # REMS monitoring
    # -----------------------------------------------------------------

    async def monitor_rems_compliance(
        self,
        program: dict,
    ) -> Dict[str, Any]:
        """Monitor REMS (Risk Evaluation and Mitigation Strategy) compliance.

        Parameters
        ----------
        program : dict
            REMS program data: ``drug``, ``rems_type``
            (e.g. medication_guide, etasu, communication_plan),
            ``elements`` (list of required elements with compliance status).

        Returns
        -------
        dict
            Compliance summary with non-compliant elements and actions.
        """
        elements = program.get("elements", [])
        compliant = [e for e in elements if e.get("compliant", False)]
        non_compliant = [e for e in elements if not e.get("compliant", False)]

        actions: List[str] = []
        for nc in non_compliant:
            actions.append(
                f"Address non-compliance: {nc.get('element_name', 'unknown')} — "
                f"{nc.get('issue', 'details not provided')}"
            )

        if non_compliant:
            actions.append("File REMS assessment report with FDA within 30 days")
            actions.append("Implement corrective action plan")

        return {
            "drug": program.get("drug", ""),
            "rems_type": program.get("rems_type", ""),
            "total_elements": len(elements),
            "compliant_count": len(compliant),
            "non_compliant_count": len(non_compliant),
            "compliance_rate": round(len(compliant) / max(len(elements), 1), 3),
            "non_compliant_elements": [
                {"element": e.get("element_name"), "issue": e.get("issue")}
                for e in non_compliant
            ],
            "required_actions": actions,
        }

    # -----------------------------------------------------------------
    # FAERS search
    # -----------------------------------------------------------------

    async def search_faers_database(
        self,
        drug_name: str,
        event: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query FDA FAERS public API.

        Parameters
        ----------
        drug_name : str
            Drug/brand name to search.
        event : str | None
            Adverse event MedDRA PT to filter on.
        limit : int
            Max results.

        Returns
        -------
        list[dict]
            FAERS records with reaction, drug, seriousness.
        """
        if httpx is None:
            log.warning("httpx not installed — returning empty FAERS results")
            return []

        base_url = "https://api.fda.gov/drug/event.json"
        search_parts = [f'patient.drug.medicinalproduct:"{drug_name}"']
        if event:
            search_parts.append(f'patient.reaction.reactionmeddrapt:"{event}"')
        search_q = "+AND+".join(search_parts)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    base_url,
                    params={"search": search_q, "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("FAERS API error")
            return []

        results: List[Dict[str, Any]] = []
        for rec in data.get("results", []):
            patient = rec.get("patient", {})
            reactions = [
                r.get("reactionmeddrapt", "")
                for r in patient.get("reaction", [])
            ]
            drugs = [
                d.get("medicinalproduct", "")
                for d in patient.get("drug", [])
            ]
            results.append({
                "safety_report_id": rec.get("safetyreportid", ""),
                "receive_date": rec.get("receivedate", ""),
                "serious": rec.get("serious", ""),
                "reactions": reactions,
                "drugs": drugs,
                "patient_sex": patient.get("patientsex", ""),
                "patient_age": patient.get("patientonsetage", ""),
            })

        return results

    # -----------------------------------------------------------------
    # Reporting timeline calculator
    # -----------------------------------------------------------------

    async def calculate_reporting_timelines(
        self,
        cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Calculate expedited reporting deadlines.

        Implements FDA 21 CFR 314.80 and EMA timelines.

        Parameters
        ----------
        cases : list[dict]
            Each: ``case_id``, ``serious``, ``fatal_or_life_threatening``,
            ``listed_expected``, ``awareness_date``.

        Returns
        -------
        list[dict]
            Per-case timeline with deadline dates and regulations.
        """
        timelines: List[Dict[str, Any]] = []

        for case in cases:
            serious = case.get("serious", False)
            fatal_lt = case.get("fatal_or_life_threatening", False)
            listed = case.get("listed_expected", True)
            awareness = case.get("awareness_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

            try:
                aware_dt = datetime.strptime(awareness, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                aware_dt = datetime.now(timezone.utc)

            if fatal_lt and not listed:
                deadline_days = 7
                regulation = "21 CFR 314.80(c)(1)(i) — 7-day IND safety report"
            elif serious and not listed:
                deadline_days = 15
                regulation = "21 CFR 314.80(c)(1)(ii) — 15-day expedited report"
            elif serious:
                deadline_days = 90
                regulation = "Periodic safety report (serious expected)"
            else:
                deadline_days = 90
                regulation = "Periodic safety report (non-serious)"

            deadline_dt = aware_dt + timedelta(days=deadline_days)

            timelines.append({
                "case_id": case.get("case_id", ""),
                "serious": serious,
                "fatal_or_life_threatening": fatal_lt,
                "listed_expected": listed,
                "awareness_date": awareness,
                "deadline_calendar_days": deadline_days,
                "deadline_date": deadline_dt.strftime("%Y-%m-%d"),
                "regulation": regulation,
                "days_remaining": (deadline_dt - datetime.now(timezone.utc)).days,
            })

        return timelines

    # -----------------------------------------------------------------
    # Causality assessment (WHO-UMC)
    # -----------------------------------------------------------------

    async def assess_causality_who_umc(
        self,
        case_data: dict,
    ) -> Dict[str, Any]:
        """WHO-UMC causality assessment.

        Parameters
        ----------
        case_data : dict
            Keys: ``time_to_onset_reasonable`` (bool), ``dechallenge``
            (bool/None), ``rechallenge`` (bool/None),
            ``alternative_explanation`` (bool), ``known_reaction`` (bool),
            ``dose_response`` (bool/None).

        Returns
        -------
        dict
            Causality category with supporting rationale.
        """
        await self._log_phi_access("causality_assessment", case_data.get("case_id", "unknown"))

        temporal = case_data.get("time_to_onset_reasonable", True)
        dechallenge = case_data.get("dechallenge")
        rechallenge = case_data.get("rechallenge")
        alternative = case_data.get("alternative_explanation", False)
        known = case_data.get("known_reaction", False)
        dose_resp = case_data.get("dose_response")

        rationale: List[str] = []

        # WHO-UMC decision tree
        if rechallenge and temporal and not alternative:
            category = WHOCausality.CERTAIN
            rationale.append("Positive rechallenge with plausible time relationship")
            rationale.append("No alternative explanation identified")
        elif temporal and dechallenge and known and not alternative:
            category = WHOCausality.PROBABLE
            rationale.append("Plausible time relationship with positive dechallenge")
            rationale.append("Known reaction; no alternative explanation")
        elif temporal and (known or dose_resp):
            category = WHOCausality.POSSIBLE
            rationale.append("Plausible time relationship")
            if alternative:
                rationale.append("Alternative explanation exists")
        elif not temporal:
            category = WHOCausality.UNLIKELY
            rationale.append("Time relationship not plausible")
        else:
            category = WHOCausality.CONDITIONAL
            rationale.append("Insufficient data for definitive assessment")

        return {
            "causality": category.value,
            "rationale": rationale,
            "factors_assessed": {
                "temporal_relationship": temporal,
                "dechallenge": dechallenge,
                "rechallenge": rechallenge,
                "alternative_explanation": alternative,
                "known_reaction": known,
                "dose_response": dose_resp,
            },
        }

    # -----------------------------------------------------------------
    # Aggregate report generation (DSUR/PBRER)
    # -----------------------------------------------------------------

    async def generate_aggregate_report(
        self,
        report_type: str,
        data: dict,
    ) -> str:
        """Generate DSUR or PBRER aggregate safety report.

        Parameters
        ----------
        report_type : str
            ``"dsur"`` or ``"pbrer"``.
        data : dict
            Report-specific data.

        Returns
        -------
        str
            Formatted report text.
        """
        if report_type.lower() == "dsur":
            lines = [
                "=" * 72,
                "DEVELOPMENT SAFETY UPDATE REPORT (ICH E2F)",
                "=" * 72,
                "",
                f"IND Number: {data.get('ind_number', 'N/A')}",
                f"Sponsor: {data.get('sponsor', 'N/A')}",
                f"Drug: {data.get('drug', 'N/A')}",
                f"Reporting period: {data.get('period_start', '')} to {data.get('period_end', '')}",
                "",
                "EXECUTIVE SUMMARY",
                f"  Total subjects exposed (cumulative): {data.get('cumulative_exposure', 'N/A')}",
                f"  Total subjects exposed (period): {data.get('period_exposure', 'N/A')}",
                f"  Ongoing studies: {data.get('ongoing_studies', 'N/A')}",
                f"  Completed studies: {data.get('completed_studies', 'N/A')}",
                "",
                "SAFETY INFORMATION",
                f"  Total SUSARs: {data.get('susar_count', 0)}",
                f"  New safety signals: {data.get('new_signals', 0)}",
                f"  Reference Safety Information changes: {data.get('rsi_changes', 'None')}",
                "",
                "OVERALL SAFETY EVALUATION",
                f"  {data.get('safety_evaluation', 'The benefit-risk profile remains acceptable.')}",
                "",
                "=" * 72,
            ]
        else:
            lines = [
                "=" * 72,
                "PERIODIC BENEFIT-RISK EVALUATION REPORT (ICH E2C(R2))",
                "=" * 72,
                "",
                f"Product: {data.get('product_name', 'N/A')}",
                f"Active substance: {data.get('active_substance', 'N/A')}",
                f"International birth date: {data.get('ibd', 'N/A')}",
                f"Reporting period: {data.get('period_start', '')} to {data.get('period_end', '')}",
                "",
                "ESTIMATED EXPOSURE",
                f"  Cumulative: {data.get('cumulative_patients', 'N/A')} patients",
                f"  Period: {data.get('period_patients', 'N/A')} patients",
                "",
                "SUMMARY TABULATIONS",
                f"  Total ICSRs (period): {data.get('total_icsrs', 0)}",
                f"  Serious ICSRs: {data.get('serious_icsrs', 0)}",
                f"  Fatal ICSRs: {data.get('fatal_icsrs', 0)}",
                "",
                "SIGNAL EVALUATION",
                f"  Signals detected: {data.get('signals_detected', 0)}",
                f"  Signals closed: {data.get('signals_closed', 0)}",
                "",
                "BENEFIT-RISK ANALYSIS",
                f"  {data.get('br_analysis', 'The benefit-risk balance remains favourable.')}",
                "",
                "=" * 72,
            ]

        return self._screen_phi("\n".join(lines))

    # -----------------------------------------------------------------
    # Medical writing (safety sections)
    # -----------------------------------------------------------------

    async def generate_medical_writing(
        self,
        document_type: str,
        section: str,
        data: dict,
    ) -> str:
        """Generate medical writing for safety documents.

        Parameters
        ----------
        document_type : str
            E.g. ``"csr"``, ``"ib"``, ``"label"``, ``"rmp"``.
        section : str
            Section identifier.
        data : dict
            Content data.

        Returns
        -------
        str
            Written section text.
        """
        header = f"[{document_type.upper()} — Section: {section}]\n\n"
        body_parts: List[str] = []

        if document_type == "ib":
            body_parts.append(
                f"The safety profile of {data.get('drug', 'the investigational product')} "
                f"is based on data from {data.get('n_subjects', 'N')} subjects "
                f"across {data.get('n_studies', 'N')} clinical studies.\n"
            )
            if data.get("common_aes"):
                body_parts.append("Most common adverse reactions (≥5%):\n")
                for ae in data["common_aes"]:
                    body_parts.append(f"  - {ae['term']} ({ae.get('rate', 'N/A')}%)\n")
        elif document_type == "label":
            body_parts.append(
                f"WARNINGS AND PRECAUTIONS\n\n"
                f"{data.get('warnings_text', 'See full prescribing information.')}\n"
            )
        else:
            body_parts.append(
                f"{data.get('content', 'Content not provided.')}\n"
            )

        text = header + "".join(body_parts)
        return self._screen_phi(text)
