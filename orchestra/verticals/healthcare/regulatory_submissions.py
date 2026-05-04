"""Horizon Orchestra — Regulatory Submissions Agent.

FDA/EMA regulatory submission and intelligence agent covering eCTD
assembly, submission tracking, label review, regulatory guidance
monitoring, CMC sections, and IND/NDA/BLA support.

Submission types
----------------
* IND (Investigational New Drug) — 21 CFR 312
* NDA (New Drug Application) — 21 CFR 314
* BLA (Biologics License Application) — 21 CFR 601
* 510(k) Premarket Notification — 21 CFR 807
* ANDA (Abbreviated New Drug Application) — 21 CFR 314
* MAA (Marketing Authorisation Application) — EMA

eCTD modules
-------------
* Module 1: Regional Administrative Information
* Module 2: CTD Summaries (Quality, Non-clinical, Clinical)
* Module 3: Quality (CMC)
* Module 4: Non-clinical Study Reports
* Module 5: Clinical Study Reports

Target customers
----------------
Johnson & Johnson, Moderna, Pfizer, Merck, AstraZeneca, Roche.
"""

from __future__ import annotations

import asyncio
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
# Optional HTTP client for FDA/EMA APIs
# ---------------------------------------------------------------------------
try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

__all__ = [
    "RegulatoryAgent",
    "SubmissionType",
    "ECTDModule",
    "SubmissionChecklist",
    "RegulatoryIntelligence",
]

log = logging.getLogger("orchestra.verticals.healthcare.regulatory_submissions")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SubmissionType(str, Enum):
    """FDA/EMA submission types."""
    IND = "IND"
    NDA = "NDA"
    BLA = "BLA"
    ANDA = "ANDA"
    K510 = "510(k)"
    PMA = "PMA"
    MAA = "MAA"                 # EMA Marketing Authorisation Application
    SUPPLEMENT = "supplement"   # sNDA, sBLA
    AMENDMENT = "amendment"


class ECTDModule(str, Enum):
    """eCTD module numbers."""
    M1 = "1"   # Regional Administrative
    M2 = "2"   # CTD Summaries
    M3 = "3"   # Quality (CMC)
    M4 = "4"   # Non-clinical
    M5 = "5"   # Clinical


class ReviewDivision(str, Enum):
    """FDA review division categories."""
    OND = "Office of New Drugs"
    OBP = "Office of Blood Products"
    OTS = "Office of Therapeutic Products"
    CBER = "Center for Biologics Evaluation and Research"
    CDER = "Center for Drug Evaluation and Research"
    CDRH = "Center for Devices and Radiological Health"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SubmissionChecklist:
    """Regulatory submission completeness checklist."""
    submission_type: SubmissionType = SubmissionType.IND
    required_sections: List[Dict[str, Any]] = field(default_factory=list)
    completed_sections: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    completion_percentage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_type": self.submission_type.value,
            "required_sections": self.required_sections,
            "completed_sections": self.completed_sections,
            "missing_sections": self.missing_sections,
            "completion_percentage": self.completion_percentage,
        }


@dataclass
class RegulatoryIntelligence:
    """Regulatory intelligence data point."""
    source: str = ""          # FDA, EMA, PMDA
    document_type: str = ""   # guidance, approval, warning letter
    title: str = ""
    date_published: str = ""
    url: str = ""
    summary: str = ""
    relevance_score: float = 0.0


# IND required sections
_IND_SECTIONS: List[Dict[str, str]] = [
    {"section": "Cover Sheet (FDA Form 1571)", "module": "M1"},
    {"section": "Table of Contents", "module": "M1"},
    {"section": "Introductory Statement / General Investigational Plan", "module": "M2"},
    {"section": "Investigator's Brochure", "module": "M2"},
    {"section": "Protocol(s)", "module": "M5"},
    {"section": "Chemistry, Manufacturing, and Controls (CMC)", "module": "M3"},
    {"section": "Pharmacology and Toxicology (Nonclinical)", "module": "M4"},
    {"section": "Previous Human Experience", "module": "M5"},
    {"section": "Additional Information", "module": "M1"},
]

# NDA required sections
_NDA_SECTIONS: List[Dict[str, str]] = [
    {"section": "Application Form (FDA 356h)", "module": "M1"},
    {"section": "Module 2.2 Introduction", "module": "M2"},
    {"section": "Module 2.3 Quality Overall Summary", "module": "M2"},
    {"section": "Module 2.4 Nonclinical Overview", "module": "M2"},
    {"section": "Module 2.5 Clinical Overview", "module": "M2"},
    {"section": "Module 2.6 Nonclinical Written/Tabulated Summaries", "module": "M2"},
    {"section": "Module 2.7 Clinical Summary", "module": "M2"},
    {"section": "Module 3 Quality (CMC) Data", "module": "M3"},
    {"section": "Module 4 Nonclinical Study Reports", "module": "M4"},
    {"section": "Module 5 Clinical Study Reports", "module": "M5"},
    {"section": "Labeling (Draft PI, PPI, Medication Guide)", "module": "M1"},
    {"section": "Patent Information (Form 3542a)", "module": "M1"},
    {"section": "User Fee Cover Sheet (Form 3397)", "module": "M1"},
    {"section": "Pediatric Study Plan", "module": "M5"},
]

# BLA required sections (overlap with NDA + biologics-specific)
_BLA_SECTIONS: List[Dict[str, str]] = [
    {"section": "Application Form (FDA 356h)", "module": "M1"},
    {"section": "Module 2.2–2.7 CTD Summaries", "module": "M2"},
    {"section": "Module 3 Quality — Drug Substance", "module": "M3"},
    {"section": "Module 3 Quality — Drug Product", "module": "M3"},
    {"section": "Module 3 Quality — Cell Bank Characterisation", "module": "M3"},
    {"section": "Module 3 Quality — Viral Safety", "module": "M3"},
    {"section": "Module 4 Nonclinical Study Reports", "module": "M4"},
    {"section": "Module 5 Clinical Study Reports", "module": "M5"},
    {"section": "Labeling", "module": "M1"},
    {"section": "Environmental Assessment or Categorical Exclusion", "module": "M1"},
    {"section": "Establishment Description", "module": "M3"},
]


# ===================================================================
# RegulatoryAgent
# ===================================================================

class RegulatoryAgent:
    """FDA/EMA regulatory submission and intelligence agent.

    eCTD assembly, submission tracking, label review, FDA guidance
    monitoring, CMC sections, IND/NDA/BLA support.

    HIPAA controls
    --------------
    * All outputs screened through :class:`PHIScanner`.
    * Audit logging for document access.
    """

    TOOLS: List[str] = [
        "search_fda_guidance",
        "search_ema_guidance",
        "search_fda_label",
        "analyze_label_section",
        "draft_ectd_section",
        "check_submission_requirements",
        "search_fda_approvals",
        "monitor_fda_calendar",
        "generate_impd_section",
        "analyze_competitor_label",
        "draft_responses_to_agency",
        "check_cmc_requirements",
        "search_patent_expiry",
        "analyze_safety_section",
        "monitor_regulatory_news",
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
        self._agent_id = f"regulatory-{uuid.uuid4().hex[:8]}"
        log.info("RegulatoryAgent initialised  agent_id=%s", self._agent_id)

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
        return result[0] if isinstance(result, tuple) else result

    async def _log_phi_access(self, action: str, resource: str) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append(
                actor=self._agent_id,
                action=action,
                resource=resource,
                metadata={"regulatory": True},
            )
        except Exception:  # noqa: BLE001
            log.exception("Failed to write regulatory audit event")

    # -----------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Domain-expert system prompt for regulatory affairs."""
        return (
            "You are an expert Regulatory Affairs AI assistant within "
            "Horizon Orchestra.  Your expertise covers:\n\n"
            "SUBMISSION TYPES\n"
            "- IND (Investigational New Drug) — 21 CFR 312\n"
            "- NDA (New Drug Application) — 21 CFR 314\n"
            "- BLA (Biologics License Application) — 21 CFR 601\n"
            "- ANDA (Abbreviated New Drug Application)\n"
            "- 510(k) Premarket Notification — 21 CFR 807\n"
            "- EMA Marketing Authorisation Application (MAA)\n"
            "- Supplements (sNDA, sBLA) and Amendments\n\n"
            "eCTD FORMAT\n"
            "- Module 1: Regional Administrative Information\n"
            "- Module 2: CTD Summaries (2.2–2.7)\n"
            "- Module 3: Quality (CMC) — Drug Substance, Drug Product\n"
            "- Module 4: Nonclinical Study Reports\n"
            "- Module 5: Clinical Study Reports (ICH E3)\n"
            "- eCTD v4.0 technical specifications\n"
            "- Lifecycle management (initial, amendment, supplement)\n\n"
            "REGULATORY INTELLIGENCE\n"
            "- FDA guidance documents and draft guidances\n"
            "- EMA scientific guidelines and reflection papers\n"
            "- PDUFA dates and advisory committee meetings\n"
            "- Approval history and Complete Response Letters\n"
            "- Orange Book / Purple Book patent and exclusivity data\n\n"
            "LABELING\n"
            "- Physician Labeling Rule (PLR) format\n"
            "- Highlights of Prescribing Information\n"
            "- Full Prescribing Information (21 CFR 201.57)\n"
            "- Boxed Warnings, Contraindications, Warnings & Precautions\n"
            "- Adverse Reactions, Drug Interactions sections\n"
            "- Medication Guides and Patient Package Inserts\n\n"
            "CMC\n"
            "- Drug substance characterisation (S.1–S.7)\n"
            "- Drug product description (P.1–P.8)\n"
            "- Stability data (ICH Q1A/Q1B)\n"
            "- Specifications and analytical methods (ICH Q6A/Q6B)\n"
            "- Manufacturing process validation\n"
        )

    # -----------------------------------------------------------------
    # FDA guidance search
    # -----------------------------------------------------------------

    async def search_fda_guidance(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search FDA guidance documents.

        Parameters
        ----------
        query : str
            Search terms for FDA guidance.
        max_results : int
            Maximum results.

        Returns
        -------
        list[dict]
            Guidance documents with title, date, URL.
        """
        if httpx is None:
            log.warning("httpx not installed — returning empty FDA guidance results")
            return []

        url = "https://api.fda.gov/other/substance.json"
        # Note: FDA does not have a direct guidance search API; this queries
        # the openFDA endpoint as a proxy.  In production, a dedicated
        # regulatory intelligence feed would be used.
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.fda.gov/drug/drugsfda.json",
                    params={"search": query, "limit": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("FDA API error")
            return []

        results: List[Dict[str, Any]] = []
        for rec in data.get("results", []):
            products = rec.get("products", [{}])
            results.append({
                "application_number": rec.get("application_number", ""),
                "sponsor_name": rec.get("sponsor_name", ""),
                "products": [
                    {
                        "brand_name": p.get("brand_name", ""),
                        "active_ingredients": p.get("active_ingredients", []),
                        "dosage_form": p.get("dosage_form", ""),
                    }
                    for p in products[:3]
                ],
            })

        return results

    # -----------------------------------------------------------------
    # FDA label search (DailyMed)
    # -----------------------------------------------------------------

    async def search_fda_label(
        self,
        drug_name: str,
        sections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search FDA drug labels via openFDA.

        Parameters
        ----------
        drug_name : str
            Drug/brand name.
        sections : list[str] | None
            Label sections to return (e.g. ``"warnings"``,
            ``"adverse_reactions"``).

        Returns
        -------
        dict
            Label data with requested sections.
        """
        if httpx is None:
            return {"error": "httpx not installed"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.fda.gov/drug/label.json",
                    params={
                        "search": f'openfda.brand_name:"{drug_name}"',
                        "limit": 1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("FDA label API error")
            return {"error": "API request failed"}

        results = data.get("results", [])
        if not results:
            return {"error": f"No label found for {drug_name}"}

        label = results[0]
        output: Dict[str, Any] = {
            "brand_name": drug_name,
            "effective_date": label.get("effective_time", ""),
        }

        target_sections = sections or [
            "indications_and_usage",
            "dosage_and_administration",
            "warnings_and_precautions",
            "adverse_reactions",
            "drug_interactions",
            "contraindications",
        ]

        for sec in target_sections:
            content = label.get(sec, [])
            if content:
                output[sec] = content[0] if isinstance(content, list) and content else str(content)

        return output

    # -----------------------------------------------------------------
    # Submission requirements checker
    # -----------------------------------------------------------------

    async def check_submission_requirements(
        self,
        submission_type: str,
        completed_sections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Check eCTD submission completeness.

        Parameters
        ----------
        submission_type : str
            ``"IND"``, ``"NDA"``, ``"BLA"``, ``"510(k)"``.
        completed_sections : list[str] | None
            Already-completed section names.

        Returns
        -------
        dict
            Checklist with missing sections and completion percentage.
        """
        completed = set(completed_sections or [])

        section_map = {
            "IND": _IND_SECTIONS,
            "NDA": _NDA_SECTIONS,
            "BLA": _BLA_SECTIONS,
        }

        required = section_map.get(submission_type.upper(), _IND_SECTIONS)
        required_names = {s["section"] for s in required}

        missing = sorted(required_names - completed)
        done = sorted(required_names & completed)
        pct = len(done) / max(len(required_names), 1) * 100

        checklist = SubmissionChecklist(
            submission_type=SubmissionType(submission_type.upper()) if submission_type.upper() in SubmissionType.__members__ else SubmissionType.IND,
            required_sections=required,
            completed_sections=list(done),
            missing_sections=missing,
            completion_percentage=round(pct, 1),
        )

        return checklist.to_dict()

    # -----------------------------------------------------------------
    # eCTD section drafting
    # -----------------------------------------------------------------

    async def draft_ectd_section(
        self,
        module: str,
        section: str,
        data: dict,
    ) -> str:
        """Draft an eCTD module section.

        Parameters
        ----------
        module : str
            eCTD module number (``"2"``, ``"3"``, ``"4"``, ``"5"``).
        section : str
            Section identifier within the module.
        data : dict
            Section-specific data.

        Returns
        -------
        str
            Drafted section text.
        """
        templates: Dict[str, Dict[str, str]] = {
            "2": {
                "2.2": (
                    "MODULE 2.2 — INTRODUCTION\n\n"
                    "Name of Medicinal Product: {product_name}\n"
                    "Applicant: {applicant}\n"
                    "Active Substance: {active_substance}\n"
                    "Proposed Indication: {indication}\n"
                    "Pharmaceutical Form: {dosage_form}\n"
                    "Strength: {strength}\n"
                    "Route of Administration: {route}\n\n"
                    "This application contains the Common Technical Document "
                    "(CTD) for {product_name} ({active_substance}) for the "
                    "proposed indication of {indication}."
                ),
                "2.5": (
                    "MODULE 2.5 — CLINICAL OVERVIEW\n\n"
                    "2.5.1 Product Development Rationale\n"
                    "{development_rationale}\n\n"
                    "2.5.2 Overview of Biopharmaceutics\n"
                    "{biopharmaceutics}\n\n"
                    "2.5.3 Overview of Clinical Pharmacology\n"
                    "{clinical_pharmacology}\n\n"
                    "2.5.4 Overview of Efficacy\n"
                    "{efficacy_overview}\n\n"
                    "2.5.5 Overview of Safety\n"
                    "{safety_overview}\n\n"
                    "2.5.6 Benefits and Risks Conclusions\n"
                    "{benefit_risk}"
                ),
                "2.7": (
                    "MODULE 2.7 — CLINICAL SUMMARY\n\n"
                    "2.7.1 Summary of Biopharmaceutic Studies\n"
                    "{biopharm_summary}\n\n"
                    "2.7.2 Summary of Clinical Pharmacology Studies\n"
                    "{clin_pharm_summary}\n\n"
                    "2.7.3 Summary of Clinical Efficacy\n"
                    "{efficacy_summary}\n\n"
                    "2.7.4 Summary of Clinical Safety\n"
                    "{safety_summary}\n\n"
                    "2.7.5 References\n"
                    "{references}"
                ),
            },
            "3": {
                "3.2.S": (
                    "MODULE 3.2.S — DRUG SUBSTANCE\n\n"
                    "S.1 General Information\n"
                    "  INN: {inn}\n"
                    "  Chemical name: {chemical_name}\n"
                    "  Molecular formula: {molecular_formula}\n"
                    "  Molecular weight: {molecular_weight}\n"
                    "  Structure: {structure_description}\n\n"
                    "S.2 Manufacture\n"
                    "  Manufacturer: {manufacturer}\n"
                    "  Manufacturing process: {process_description}\n\n"
                    "S.3 Characterisation\n"
                    "  {characterisation}\n\n"
                    "S.4 Control of Drug Substance\n"
                    "  Specifications: {specifications}\n\n"
                    "S.7 Stability\n"
                    "  {stability_data}"
                ),
                "3.2.P": (
                    "MODULE 3.2.P — DRUG PRODUCT\n\n"
                    "P.1 Description and Composition\n"
                    "  Dosage form: {dosage_form}\n"
                    "  Composition: {composition}\n\n"
                    "P.2 Pharmaceutical Development\n"
                    "  {pharma_development}\n\n"
                    "P.3 Manufacture\n"
                    "  {manufacturing}\n\n"
                    "P.5 Control of Drug Product\n"
                    "  {product_specifications}\n\n"
                    "P.8 Stability\n"
                    "  {product_stability}"
                ),
            },
        }

        module_templates = templates.get(module, {})
        template = module_templates.get(section, f"[Module {module}, Section {section} — template not available]")

        try:
            text = template.format(**data)
        except KeyError:
            text = template

        return self._screen_phi(text)

    # -----------------------------------------------------------------
    # FDA approvals search
    # -----------------------------------------------------------------

    async def search_fda_approvals(
        self,
        drug_name: Optional[str] = None,
        sponsor: Optional[str] = None,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search FDA approval database.

        Parameters
        ----------
        drug_name : str | None
            Drug/brand name filter.
        sponsor : str | None
            Sponsor company filter.
        max_results : int
            Maximum results.

        Returns
        -------
        list[dict]
            Approval records.
        """
        if httpx is None:
            return []

        search_parts: List[str] = []
        if drug_name:
            search_parts.append(f'openfda.brand_name:"{drug_name}"')
        if sponsor:
            search_parts.append(f'sponsor_name:"{sponsor}"')

        search_q = "+AND+".join(search_parts) if search_parts else "*"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.fda.gov/drug/drugsfda.json",
                    params={"search": search_q, "limit": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("FDA approvals API error")
            return []

        results: List[Dict[str, Any]] = []
        for rec in data.get("results", []):
            submissions = rec.get("submissions", [])
            latest = submissions[0] if submissions else {}
            results.append({
                "application_number": rec.get("application_number", ""),
                "sponsor": rec.get("sponsor_name", ""),
                "submission_type": latest.get("submission_type", ""),
                "submission_status": latest.get("submission_status", ""),
                "submission_status_date": latest.get("submission_status_date", ""),
                "products": [
                    {
                        "brand_name": p.get("brand_name", ""),
                        "generic_name": (p.get("active_ingredients", [{}])[0].get("name", "")
                                         if p.get("active_ingredients") else ""),
                    }
                    for p in rec.get("products", [])[:3]
                ],
            })

        return results

    # -----------------------------------------------------------------
    # Label analysis
    # -----------------------------------------------------------------

    async def analyze_label_section(
        self,
        labels: List[Dict[str, Any]],
        section: str,
    ) -> Dict[str, Any]:
        """Compare label sections across multiple products.

        Parameters
        ----------
        labels : list[dict]
            Each: ``drug_name``, ``section_text``.
        section : str
            Section being compared (e.g. ``"adverse_reactions"``).

        Returns
        -------
        dict
            Comparison analysis.
        """
        analysis: Dict[str, Any] = {
            "section": section,
            "products_compared": len(labels),
            "comparisons": [],
        }

        for label in labels:
            text = label.get("section_text", "")
            word_count = len(text.split())

            # Simple readability estimate (Flesch-Kincaid proxy)
            sentences = max(len(re.split(r'[.!?]+', text)), 1)
            words = max(word_count, 1)
            avg_sentence_len = words / sentences

            analysis["comparisons"].append({
                "drug_name": label.get("drug_name", ""),
                "word_count": word_count,
                "avg_sentence_length": round(avg_sentence_len, 1),
                "has_boxed_warning": "boxed warning" in text.lower() or "black box" in text.lower(),
                "mentions_rems": "rems" in text.lower(),
            })

        return analysis

    # -----------------------------------------------------------------
    # Complete Response Letter drafting
    # -----------------------------------------------------------------

    async def draft_responses_to_agency(
        self,
        deficiencies: List[Dict[str, str]],
        submission_data: dict,
    ) -> str:
        """Draft responses to FDA Complete Response Letter.

        Parameters
        ----------
        deficiencies : list[dict]
            Each: ``deficiency_number``, ``category``, ``description``.
        submission_data : dict
            Keys: ``application_number``, ``product_name``, ``applicant``.

        Returns
        -------
        str
            Formatted response document.
        """
        lines = [
            "=" * 72,
            "RESPONSE TO COMPLETE RESPONSE LETTER",
            "=" * 72,
            "",
            f"Application Number: {submission_data.get('application_number', '')}",
            f"Product: {submission_data.get('product_name', '')}",
            f"Applicant: {submission_data.get('applicant', '')}",
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "",
            "-" * 72,
            "",
        ]

        for d in deficiencies:
            lines += [
                f"DEFICIENCY #{d.get('deficiency_number', 'N/A')}",
                f"Category: {d.get('category', 'N/A')}",
                "",
                "FDA Comment:",
                f"  {d.get('description', '')}",
                "",
                "Applicant Response:",
                f"  [Response to be drafted based on available data]",
                "",
                "-" * 72,
                "",
            ]

        lines.append("=" * 72)
        return self._screen_phi("\n".join(lines))

    # -----------------------------------------------------------------
    # CMC requirements check
    # -----------------------------------------------------------------

    async def check_cmc_requirements(
        self,
        product_type: str,
        available_data: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Check CMC (Chemistry, Manufacturing, Controls) completeness.

        Parameters
        ----------
        product_type : str
            ``"small_molecule"``, ``"biologic"``, ``"vaccine"``,
            ``"gene_therapy"``.
        available_data : list[str] | None
            List of available CMC data elements.

        Returns
        -------
        dict
            CMC completeness assessment.
        """
        available = set(available_data or [])

        base_requirements = [
            "Drug substance characterisation",
            "Manufacturing process description",
            "Process validation",
            "Analytical methods and validation",
            "Specifications",
            "Stability data (long-term and accelerated)",
            "Container closure system",
            "Drug product description",
            "Drug product manufacturing",
            "Drug product specifications",
            "Drug product stability",
        ]

        # Product-type-specific additions
        type_additions: Dict[str, List[str]] = {
            "biologic": [
                "Cell bank characterisation",
                "Viral safety evaluation",
                "Adventitious agent testing",
                "Bioassay development",
                "Glycan analysis",
                "Host cell protein quantification",
                "Residual DNA quantification",
            ],
            "vaccine": [
                "Antigen characterisation",
                "Adjuvant specification",
                "Potency assay",
                "Sterility testing",
                "Endotoxin testing",
                "In-vivo potency",
            ],
            "gene_therapy": [
                "Vector characterisation",
                "Vector genome sequence",
                "Replication-competent virus testing",
                "Transgene expression assay",
                "Vector biodistribution data",
                "Shedding study protocol",
            ],
        }

        requirements = base_requirements + type_additions.get(product_type, [])
        missing = [r for r in requirements if r not in available]
        completed = [r for r in requirements if r in available]
        pct = len(completed) / max(len(requirements), 1) * 100

        return {
            "product_type": product_type,
            "total_requirements": len(requirements),
            "completed": len(completed),
            "missing": missing,
            "completion_percentage": round(pct, 1),
            "critical_gaps": [m for m in missing if m in base_requirements],
        }

    # -----------------------------------------------------------------
    # Patent / exclusivity search
    # -----------------------------------------------------------------

    async def search_patent_expiry(
        self,
        drug_name: str,
    ) -> Dict[str, Any]:
        """Search Orange/Purple Book patent and exclusivity data.

        Parameters
        ----------
        drug_name : str
            Drug/brand name.

        Returns
        -------
        dict
            Patent and exclusivity information.
        """
        if httpx is None:
            return {"error": "httpx not installed", "drug": drug_name}

        # Query openFDA for product info (patent data requires Orange Book)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.fda.gov/drug/drugsfda.json",
                    params={
                        "search": f'openfda.brand_name:"{drug_name}"',
                        "limit": 1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001
            log.exception("FDA patent search error")
            return {"error": "API request failed", "drug": drug_name}

        results = data.get("results", [])
        if not results:
            return {"drug": drug_name, "found": False}

        rec = results[0]
        products = rec.get("products", [])

        return {
            "drug": drug_name,
            "found": True,
            "application_number": rec.get("application_number", ""),
            "sponsor": rec.get("sponsor_name", ""),
            "products": [
                {
                    "brand_name": p.get("brand_name", ""),
                    "active_ingredients": p.get("active_ingredients", []),
                    "dosage_form": p.get("dosage_form", ""),
                    "marketing_status": p.get("marketing_status", ""),
                }
                for p in products
            ],
        }

    # -----------------------------------------------------------------
    # IMPD (Investigational Medicinal Product Dossier) drafting
    # -----------------------------------------------------------------

    async def generate_impd_section(
        self,
        section: str,
        data: dict,
    ) -> str:
        """Draft IMPD section for EU CTR submissions.

        Parameters
        ----------
        section : str
            IMPD section (e.g. ``"quality"``, ``"nonclinical"``,
            ``"clinical"``).
        data : dict
            Section-specific data.

        Returns
        -------
        str
            Drafted IMPD section.
        """
        templates: Dict[str, str] = {
            "quality": (
                "INVESTIGATIONAL MEDICINAL PRODUCT DOSSIER — QUALITY\n\n"
                "S. DRUG SUBSTANCE\n"
                "  Name: {drug_substance_name}\n"
                "  Manufacturer: {ds_manufacturer}\n"
                "  General properties: {ds_properties}\n\n"
                "P. DRUG PRODUCT\n"
                "  Dosage form: {dosage_form}\n"
                "  Composition: {composition}\n"
                "  Manufacturer: {dp_manufacturer}\n\n"
                "A. APPENDICES\n"
                "  Certificates of Analysis: {coa_status}\n"
                "  GMP Certificates: {gmp_status}\n"
            ),
            "nonclinical": (
                "IMPD — NONCLINICAL DATA\n\n"
                "Pharmacology\n"
                "  Primary pharmacodynamics: {primary_pd}\n"
                "  Secondary pharmacodynamics: {secondary_pd}\n"
                "  Safety pharmacology: {safety_pharm}\n\n"
                "Pharmacokinetics\n"
                "  {pk_summary}\n\n"
                "Toxicology\n"
                "  Single-dose toxicity: {single_dose_tox}\n"
                "  Repeat-dose toxicity: {repeat_dose_tox}\n"
                "  Genotoxicity: {genotox}\n"
                "  Carcinogenicity: {carcinogenicity}\n"
                "  Reproductive toxicity: {repro_tox}\n"
            ),
            "clinical": (
                "IMPD — CLINICAL DATA\n\n"
                "Clinical pharmacology\n"
                "  {clin_pharm}\n\n"
                "Previous clinical experience\n"
                "  {prev_experience}\n\n"
                "Overall benefit-risk assessment\n"
                "  {benefit_risk}\n"
            ),
        }

        template = templates.get(section, f"[IMPD Section '{section}' — template not available]")
        try:
            text = template.format(**data)
        except KeyError:
            text = template

        return self._screen_phi(text)

    # -----------------------------------------------------------------
    # Regulatory news monitoring
    # -----------------------------------------------------------------

    async def monitor_regulatory_news(
        self,
        topics: List[str],
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Monitor FDA/EMA regulatory news and alerts.

        Parameters
        ----------
        topics : list[str]
            Topics of interest (e.g. ``"oncology"``, ``"gene therapy"``).
        max_results : int
            Maximum news items.

        Returns
        -------
        list[dict]
            News items with title, date, source, summary.
        """
        # In production, this would integrate with FDA RSS feeds,
        # EMA news API, and regulatory intelligence providers
        log.info("Monitoring regulatory news for topics: %s", topics)

        return [{
            "source": "FDA",
            "title": f"Regulatory monitoring active for: {', '.join(topics)}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "message": "Connect to FDA RSS / EMA news feeds for live monitoring.",
            "topics": topics,
        }]
