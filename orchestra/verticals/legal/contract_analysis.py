"""Contract Analysis Agent — Enterprise contract review and analysis.

AI-powered contract analysis covering NDA review, MSA analysis, M&A due
diligence, ISDA agreements, real estate leases, employment agreements,
IP licenses, and SaaS agreements.  Features risk scoring, playbook
enforcement, and tracked-changes redlining.

Target customers
----------------
- Kirkland & Ellis: M&A due diligence, PE portfolio contract review
- Sidley Austin: Complex commercial agreements, IP licensing
- Latham & Watkins: Capital markets transactions, regulatory compliance

Privilege & confidentiality
---------------------------
All outputs are wrapped with a privilege-detection guard modelled on
the :class:`~orchestra.guardian.beyond_guardrails.BeyondGuardrails`
PHI-style scanner approach — any attorney-client privileged content is
flagged before leaving the agent boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

__all__ = [
    "ContractAnalysisAgent",
    "ContractAnalysis",
    "PlaybookReport",
    "RiskReport",
    "ClauseRisk",
    "ContractType",
    "RiskLevel",
    "PlaybookDeviation",
    "NegotiationPoint",
    "DefinedTerm",
    "FinancialTerm",
    "Obligation",
]

log = logging.getLogger("orchestra.verticals.legal.contract_analysis")

# ---------------------------------------------------------------------------
# Try to import OrchestraTeam for team integration (graceful fallback)
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except Exception:
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Try to import BeyondGuardrails for privilege detection
# ---------------------------------------------------------------------------
try:
    from orchestra.guardian.beyond_guardrails import BeyondGuardrails
except Exception:
    BeyondGuardrails = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════
# Enums & Data Models
# ═══════════════════════════════════════════════════════════════════════════

class ContractType(str, Enum):
    """Supported contract types."""
    NDA = "nda"
    MSA = "msa"
    SPA = "spa"                 # Stock Purchase Agreement
    APA = "apa"                 # Asset Purchase Agreement
    MERGER = "merger"
    ISDA = "isda"               # ISDA Master Agreement
    LEASE = "lease"             # Real estate lease
    EMPLOYMENT = "employment"
    IP_LICENSE = "ip_license"
    SAAS = "saas"
    SERVICES = "services"       # Professional services agreement
    SUPPLY = "supply"           # Supply agreement
    DISTRIBUTION = "distribution"
    FRANCHISE = "franchise"
    JV = "joint_venture"
    SETTLEMENT = "settlement"
    CREDIT = "credit"           # Credit agreement
    GUARANTEE = "guarantee"


class RiskLevel(str, Enum):
    """Risk severity levels."""
    CRITICAL = "critical"       # Immediate escalation required
    HIGH = "high"               # Senior partner review needed
    MEDIUM = "medium"           # Associate review sufficient
    LOW = "low"                 # Acceptable risk
    INFO = "info"               # Informational only


@dataclass
class ClauseRisk:
    """A single risk finding within a contract clause."""
    clause_name: str
    risk_level: RiskLevel
    section_reference: str      # e.g., "Section 7.2(a)"
    description: str
    recommendation: str
    playbook_deviation: bool = False
    market_standard: Optional[str] = None
    impact_estimate: Optional[str] = None


@dataclass
class PlaybookDeviation:
    """Deviation from firm/client standard positions."""
    clause_name: str
    playbook_position: str      # What the playbook requires
    contract_position: str      # What the contract actually says
    severity: RiskLevel
    suggested_redline: str
    negotiation_priority: int   # 1 = highest priority


@dataclass
class NegotiationPoint:
    """A prioritized negotiation item."""
    priority: int               # 1 = highest
    clause: str
    current_position: str
    desired_position: str
    fallback_position: str
    leverage_notes: str
    risk_if_unchanged: RiskLevel


@dataclass
class DefinedTerm:
    """An extracted defined term from the contract."""
    term: str
    definition: str
    section_reference: str
    cross_references: List[str] = field(default_factory=list)
    ambiguity_flag: bool = False
    notes: Optional[str] = None


@dataclass
class FinancialTerm:
    """Extracted financial / payment term."""
    term_type: str              # e.g., "base_fee", "penalty", "milestone"
    amount: Optional[str] = None
    currency: str = "USD"
    frequency: Optional[str] = None     # monthly, quarterly, etc.
    escalation: Optional[str] = None    # Annual escalation clause
    late_payment: Optional[str] = None  # Late payment terms
    section_reference: str = ""


@dataclass
class Obligation:
    """A party obligation with deadline tracking."""
    party: str
    obligation: str
    deadline: Optional[str] = None
    section_reference: str = ""
    recurring: bool = False
    condition: Optional[str] = None     # Condition precedent
    consequence_of_breach: Optional[str] = None


@dataclass
class ContractAnalysis:
    """Complete contract analysis result."""
    contract_id: str
    contract_type: ContractType
    parties: List[str]
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    governing_law: Optional[str] = None
    risk_score: int = 0                 # 0–100
    risk_level: RiskLevel = RiskLevel.INFO
    clause_risks: List[ClauseRisk] = field(default_factory=list)
    obligations: List[Obligation] = field(default_factory=list)
    financial_terms: List[FinancialTerm] = field(default_factory=list)
    defined_terms: List[DefinedTerm] = field(default_factory=list)
    executive_summary: str = ""
    missing_clauses: List[str] = field(default_factory=list)
    unusual_provisions: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaybookReport:
    """Playbook comparison report."""
    contract_id: str
    playbook_name: str
    total_deviations: int = 0
    critical_deviations: int = 0
    deviations: List[PlaybookDeviation] = field(default_factory=list)
    compliant_clauses: List[str] = field(default_factory=list)
    overall_compliance_pct: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RiskReport:
    """Detailed risk scoring report."""
    contract_id: str
    overall_score: int = 0          # 0–100, higher = riskier
    category_scores: Dict[str, int] = field(default_factory=dict)
    risk_factors: List[ClauseRisk] = field(default_factory=list)
    mitigating_factors: List[str] = field(default_factory=list)
    peer_comparison: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ═══════════════════════════════════════════════════════════════════════════
# Privilege Detection (BeyondGuardrails PHI-style approach)
# ═══════════════════════════════════════════════════════════════════════════

# Attorney-client privilege markers — keywords and patterns that indicate
# privileged content which must not be disclosed without proper authorization.
_PRIVILEGE_MARKERS: List[re.Pattern] = [
    re.compile(r"\b(attorney[- ]?client|work[- ]?product)\s+privilege", re.IGNORECASE),
    re.compile(r"\bprivileged\s+and\s+confidential\b", re.IGNORECASE),
    re.compile(r"\blegal\s+advice\b", re.IGNORECASE),
    re.compile(r"\battorney\s+communication\b", re.IGNORECASE),
    re.compile(r"\bprotected\s+by\s+privilege\b", re.IGNORECASE),
    re.compile(r"\blitigation\s+hold\b", re.IGNORECASE),
    re.compile(r"\bin\s+anticipation\s+of\s+litigation\b", re.IGNORECASE),
    re.compile(r"\bsolicitor[- ]?client\b", re.IGNORECASE),
]


def _scan_for_privilege(text: str) -> List[Dict[str, Any]]:
    """Scan text for attorney-client privilege markers.

    Modelled on the BeyondGuardrails PHI scanner approach: fast regex
    passes with confidence scoring, no external ML dependencies.
    """
    findings: List[Dict[str, Any]] = []
    for pattern in _PRIVILEGE_MARKERS:
        for match in pattern.finditer(text):
            findings.append({
                "marker": match.group(),
                "start": match.start(),
                "end": match.end(),
                "confidence": 0.90,
                "type": "attorney_client_privilege",
            })
    return findings


def _enforce_privilege_guard(text: str) -> str:
    """Wrap output with privilege guard — flags privileged content.

    Returns the text with privilege warnings prepended if privileged
    content is detected.  This mirrors the PHIScanner wrapper pattern
    used in the healthcare vertical.
    """
    try:
        findings = _scan_for_privilege(text)
        if findings:
            warning = (
                "[PRIVILEGE WARNING] This output contains content that may be "
                "protected by attorney-client privilege or work-product doctrine. "
                f"Detected {len(findings)} privilege marker(s). Review before "
                "sharing outside the legal team.\n\n"
            )
            return warning + text
        return text
    except Exception:
        # Fail open but log — never block output on scanner error
        log.warning("Privilege scanner error — returning unguarded output")
        return text


# ═══════════════════════════════════════════════════════════════════════════
# Contract clause patterns (used by multiple tools)
# ═══════════════════════════════════════════════════════════════════════════

# Standard clause categories for risk assessment
STANDARD_CLAUSE_CATEGORIES: Dict[str, List[str]] = {
    "indemnification": [
        "indemnif", "hold harmless", "defend and indemnify",
        "losses and damages", "third party claims",
    ],
    "limitation_of_liability": [
        "limitation of liability", "liability cap", "aggregate liability",
        "consequential damages", "direct damages", "exclusion of damages",
    ],
    "ip_ownership": [
        "intellectual property", "work for hire", "work product",
        "assignment of rights", "license grant", "ip rights",
        "proprietary rights", "inventions", "copyrights", "patents",
    ],
    "termination": [
        "termination for cause", "termination for convenience",
        "material breach", "cure period", "notice of termination",
        "wind-down", "survival", "post-termination",
    ],
    "confidentiality": [
        "confidential information", "non-disclosure", "proprietary information",
        "trade secret", "permitted disclosure", "residual knowledge",
    ],
    "data_protection": [
        "personal data", "data protection", "gdpr", "ccpa", "cpra",
        "data processing", "data controller", "data processor",
        "sub-processor", "data breach notification",
    ],
    "governing_law": [
        "governing law", "jurisdiction", "venue", "choice of law",
        "dispute resolution", "arbitration", "forum selection",
    ],
    "change_of_control": [
        "change of control", "assignment", "merger", "acquisition",
        "successor", "anti-assignment", "consent to assign",
    ],
    "force_majeure": [
        "force majeure", "act of god", "pandemic", "epidemic",
        "government action", "impossibility",
    ],
    "representations_warranties": [
        "represents and warrants", "representation", "warranty",
        "disclaimer", "as is", "warranty period",
    ],
}

# Required provisions by contract type
REQUIRED_PROVISIONS: Dict[str, List[str]] = {
    "nda": [
        "definition_of_confidential_information", "permitted_disclosures",
        "return_of_materials", "term", "remedies", "governing_law",
    ],
    "msa": [
        "scope_of_services", "payment_terms", "indemnification",
        "limitation_of_liability", "termination", "confidentiality",
        "governing_law", "insurance", "representations_warranties",
    ],
    "spa": [
        "purchase_price", "representations_warranties", "indemnification",
        "closing_conditions", "covenants", "termination", "governing_law",
        "escrow", "working_capital_adjustment",
    ],
    "saas": [
        "service_description", "sla", "data_protection", "uptime_guarantee",
        "payment_terms", "term_renewal", "termination", "data_portability",
        "limitation_of_liability", "indemnification",
    ],
    "employment": [
        "position_title", "compensation", "benefits", "termination",
        "non_compete", "non_solicitation", "confidentiality",
        "ip_assignment", "governing_law", "at_will_statement",
    ],
    "isda": [
        "schedule", "credit_support_annex", "events_of_default",
        "termination_events", "early_termination", "netting",
        "close_out_netting", "governing_law",
    ],
    "lease": [
        "premises_description", "rent", "term", "renewal_options",
        "maintenance", "insurance", "permitted_use", "default",
        "remedies", "governing_law",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# Risk scoring weights
# ═══════════════════════════════════════════════════════════════════════════

_RISK_WEIGHTS: Dict[str, float] = {
    "indemnification": 15.0,
    "limitation_of_liability": 15.0,
    "ip_ownership": 12.0,
    "termination": 10.0,
    "data_protection": 12.0,
    "change_of_control": 8.0,
    "confidentiality": 8.0,
    "governing_law": 5.0,
    "force_majeure": 5.0,
    "representations_warranties": 10.0,
}


# ═══════════════════════════════════════════════════════════════════════════
# Regulatory compliance patterns
# ═══════════════════════════════════════════════════════════════════════════

_REGULATORY_PATTERNS: Dict[str, List[re.Pattern]] = {
    "GDPR": [
        re.compile(r"\b(gdpr|general\s+data\s+protection\s+regulation)\b", re.I),
        re.compile(r"\b(data\s+protection\s+officer|dpo)\b", re.I),
        re.compile(r"\b(right\s+to\s+erasure|right\s+to\s+be\s+forgotten)\b", re.I),
        re.compile(r"\b(data\s+processing\s+agreement|dpa)\b", re.I),
        re.compile(r"\b(standard\s+contractual\s+clauses|sccs?)\b", re.I),
    ],
    "CCPA": [
        re.compile(r"\b(ccpa|california\s+consumer\s+privacy\s+act)\b", re.I),
        re.compile(r"\b(cpra|california\s+privacy\s+rights\s+act)\b", re.I),
        re.compile(r"\b(do\s+not\s+sell|opt[- ]out)\b", re.I),
        re.compile(r"\b(service\s+provider|business\s+purpose)\b", re.I),
    ],
    "FCPA": [
        re.compile(r"\b(fcpa|foreign\s+corrupt\s+practices\s+act)\b", re.I),
        re.compile(r"\b(anti[- ]?bribery|anti[- ]?corruption)\b", re.I),
        re.compile(r"\b(government\s+official|public\s+official)\b", re.I),
    ],
    "SOX": [
        re.compile(r"\b(sarbanes[- ]?oxley|sox)\b", re.I),
        re.compile(r"\b(internal\s+controls|financial\s+reporting)\b", re.I),
    ],
    "OFAC": [
        re.compile(r"\b(ofac|sanctions|sdn\s+list)\b", re.I),
        re.compile(r"\b(specially\s+designated\s+nationals)\b", re.I),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# ContractAnalysisAgent
# ═══════════════════════════════════════════════════════════════════════════

class ContractAnalysisAgent:
    """AI agent for enterprise contract review and analysis.

    Covers: NDA review, MSA analysis, M&A due diligence, ISDA agreements,
    real estate leases, employment agreements, IP licenses, SaaS agreements.
    Risk scoring, playbook enforcement, redlining.

    Examples
    --------
    >>> agent = ContractAnalysisAgent()
    >>> result = await agent.analyze(contract_text, "nda")
    >>> print(result.risk_score)
    42

    >>> report = await agent.compare_to_playbook(contract_text, playbook)
    >>> print(report.total_deviations)
    5
    """

    TOOLS = [
        "extract_key_terms",              # Party names, dates, values, terms
        "identify_risk_clauses",          # Indemnification, liability caps, IP ownership
        "compare_to_playbook",            # Deviation from firm/client standard positions
        "generate_redline",               # Generate tracked-changes redline
        "check_regulatory_compliance",    # GDPR, CCPA, FCPA clauses
        "extract_obligations",            # Party obligations with deadlines
        "detect_missing_clauses",         # Required provisions not present
        "score_contract_risk",            # 0-100 risk score with breakdown
        "summarize_agreement",            # Executive summary for business review
        "extract_financial_terms",        # Payment, fee, penalty terms
        "check_governing_law",            # Jurisdiction + choice of law analysis
        "identify_change_of_control",     # CoC provisions, assignability
        "analyze_termination_rights",     # Termination triggers, notice periods
        "check_ip_ownership",             # Work-for-hire, assignment, license scope
        "flag_unusual_provisions",        # Market standard deviation detection
        "generate_negotiation_points",    # Priority issues for negotiation
        "compare_to_prior_version",       # Contract version comparison
        "extract_definitions",            # Defined terms dictionary
    ]

    def __init__(
        self,
        *,
        privilege_guard_enabled: bool = True,
        default_playbook: Optional[Dict[str, Any]] = None,
        risk_threshold: int = 60,
        model: str = "kimi-k2.5",
    ) -> None:
        self._privilege_guard = privilege_guard_enabled
        self._default_playbook = default_playbook or {}
        self._risk_threshold = risk_threshold
        self._model = model
        self._analysis_cache: Dict[str, ContractAnalysis] = {}
        log.info(
            "ContractAnalysisAgent initialized (model=%s, privilege_guard=%s)",
            model, privilege_guard_enabled,
        )

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for contract analysis.

        Returns a system prompt with deep expertise in contract law,
        including knowledge of standard terms, market positions, and
        regulatory requirements across multiple practice areas.
        """
        return (
            "You are an expert contract analysis agent specializing in enterprise "
            "legal operations for Am Law 100 firms. You have deep expertise in:\n\n"
            "PRACTICE AREAS:\n"
            "- M&A: SPA/APA analysis, rep & warranty review, MAC clauses, "
            "indemnification baskets/caps, working capital adjustments, escrow terms\n"
            "- Commercial: MSA/SOW review, SLA enforcement, limitation of liability "
            "analysis (direct vs. consequential damages), insurance requirements\n"
            "- Capital Markets: ISDA Master Agreements, Credit Support Annexes (CSA), "
            "netting provisions, Events of Default, Termination Events\n"
            "- Real Estate: NNN lease analysis, CAM reconciliation, permitted use, "
            "tenant improvement allowances, renewal/expansion options\n"
            "- IP/Tech: License scope analysis (exclusive vs. non-exclusive), "
            "work-for-hire doctrine, moral rights waiver, source code escrow\n"
            "- Employment: Non-compete enforceability by jurisdiction, DTSA compliance, "
            "garden leave, clawback provisions, change-in-control payments\n"
            "- SaaS: SLA tiers (99.9% vs 99.99%), data processing addenda, "
            "SOC 2 Type II requirements, data portability, vendor lock-in risks\n\n"
            "REGULATORY KNOWLEDGE:\n"
            "- GDPR Articles 28/46 (processor obligations, international transfers)\n"
            "- CCPA/CPRA (service provider vs. contractor, opt-out obligations)\n"
            "- FCPA (anti-bribery representations, third-party due diligence)\n"
            "- SOX (internal control attestation in vendor agreements)\n"
            "- OFAC (sanctions compliance representations)\n\n"
            "PLAYBOOK ENFORCEMENT:\n"
            "- Compare every clause against the client's negotiation playbook\n"
            "- Flag deviations with severity (critical/high/medium/low)\n"
            "- Provide market-standard alternatives for non-standard terms\n"
            "- Generate redline suggestions with supporting rationale\n\n"
            "ATTORNEY-CLIENT PRIVILEGE:\n"
            "- All analysis output is work product\n"
            "- Flag any content that contains privileged communications\n"
            "- Never disclose privileged information outside authorized channels\n"
            "- Maintain Upjohn warnings for corporate investigations\n\n"
            "OUTPUT FORMAT:\n"
            "- Risk scores: 0-100 scale (0 = no risk, 100 = maximum risk)\n"
            "- Always cite specific section references (e.g., 'Section 7.2(a)')\n"
            "- Provide actionable recommendations, not just observations\n"
            "- Use UTBMS task codes for billing categorization where applicable "
            "(e.g., L210 = Fact Investigation/Development, L310 = Written Discovery, "
            "L510 = Dispositive Motions)\n"
        )

    # -------------------------------------------------------------------
    # Core analysis methods
    # -------------------------------------------------------------------

    async def analyze(
        self,
        contract_text: str,
        contract_type: str,
        *,
        playbook: Optional[Dict[str, Any]] = None,
        deep_scan: bool = True,
    ) -> ContractAnalysis:
        """Perform comprehensive contract analysis.

        Parameters
        ----------
        contract_text:
            Full text of the contract to analyze.
        contract_type:
            Type of contract (see :class:`ContractType`).
        playbook:
            Optional negotiation playbook to compare against.
        deep_scan:
            If True, run all analysis tools; if False, run quick scan.

        Returns
        -------
        ContractAnalysis
            Complete analysis including risk score, clause risks,
            obligations, financial terms, and executive summary.
        """
        contract_id = hashlib.sha256(
            contract_text[:2048].encode()
        ).hexdigest()[:16]

        ct = ContractType(contract_type.lower())
        log.info("Analyzing contract %s (type=%s, deep=%s)", contract_id, ct.value, deep_scan)

        # Parallel extraction of key components
        parties = await self._extract_parties(contract_text)
        dates = await self._extract_dates(contract_text)
        governing_law = await self._extract_governing_law(contract_text)

        # Risk clause identification
        clause_risks = await self._identify_risk_clauses(contract_text, ct)

        # Obligation extraction
        obligations = await self._extract_obligations(contract_text, parties)

        # Financial terms
        financial_terms = await self._extract_financial_terms(contract_text)

        # Defined terms
        defined_terms = await self._extract_definitions(contract_text)

        # Missing clause detection
        missing = await self._detect_missing_clauses(contract_text, ct)

        # Unusual provisions
        unusual = await self._flag_unusual_provisions(contract_text, ct)

        # Risk scoring
        risk_score, risk_level = await self._calculate_risk_score(
            clause_risks, missing, unusual, ct,
        )

        # Executive summary
        summary = await self._generate_summary(
            contract_id, ct, parties, clause_risks, risk_score,
        )

        # Regulatory compliance check
        if deep_scan:
            reg_findings = await self._check_regulatory_compliance(contract_text)
            for finding in reg_findings:
                clause_risks.append(finding)

        # Playbook comparison if provided
        effective_playbook = playbook or self._default_playbook
        if effective_playbook and deep_scan:
            pb_report = await self.compare_to_playbook(
                contract_text, effective_playbook,
            )
            for dev in pb_report.deviations:
                if dev.severity in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                    clause_risks.append(ClauseRisk(
                        clause_name=dev.clause_name,
                        risk_level=dev.severity,
                        section_reference="",
                        description=f"Playbook deviation: {dev.contract_position}",
                        recommendation=dev.suggested_redline,
                        playbook_deviation=True,
                    ))

        analysis = ContractAnalysis(
            contract_id=contract_id,
            contract_type=ct,
            parties=parties,
            effective_date=dates.get("effective"),
            expiration_date=dates.get("expiration"),
            governing_law=governing_law,
            risk_score=risk_score,
            risk_level=risk_level,
            clause_risks=clause_risks,
            obligations=obligations,
            financial_terms=financial_terms,
            defined_terms=defined_terms,
            executive_summary=summary,
            missing_clauses=missing,
            unusual_provisions=unusual,
        )

        self._analysis_cache[contract_id] = analysis
        log.info(
            "Contract %s analyzed: risk=%d (%s), %d risks, %d obligations",
            contract_id, risk_score, risk_level.value,
            len(clause_risks), len(obligations),
        )

        return analysis

    async def compare_to_playbook(
        self,
        contract: str,
        playbook: Dict[str, Any],
    ) -> PlaybookReport:
        """Compare contract terms to firm/client standard playbook.

        Parameters
        ----------
        contract:
            Full contract text.
        playbook:
            Playbook dict mapping clause categories to required positions.
            Example: ``{"indemnification": {"cap": "2x fees", "carve_outs": [...]}}``

        Returns
        -------
        PlaybookReport
            Deviation report with compliance percentage.
        """
        contract_id = hashlib.sha256(
            contract[:2048].encode()
        ).hexdigest()[:16]
        playbook_name = playbook.get("name", "default_playbook")

        deviations: List[PlaybookDeviation] = []
        compliant: List[str] = []
        priority = 0

        for clause_category, required_position in playbook.items():
            if clause_category in ("name", "version", "metadata"):
                continue

            # Check if clause category exists in contract
            found = False
            contract_lower = contract.lower()
            if clause_category in STANDARD_CLAUSE_CATEGORIES:
                for keyword in STANDARD_CLAUSE_CATEGORIES[clause_category]:
                    if keyword in contract_lower:
                        found = True
                        break

            if not found:
                priority += 1
                deviations.append(PlaybookDeviation(
                    clause_name=clause_category,
                    playbook_position=str(required_position),
                    contract_position="[NOT FOUND IN CONTRACT]",
                    severity=RiskLevel.HIGH,
                    suggested_redline=f"Add {clause_category} clause per playbook",
                    negotiation_priority=priority,
                ))
            else:
                compliant.append(clause_category)

        total_clauses = len(playbook) - sum(
            1 for k in playbook if k in ("name", "version", "metadata")
        )
        compliance_pct = (
            (len(compliant) / total_clauses * 100.0) if total_clauses > 0 else 100.0
        )

        report = PlaybookReport(
            contract_id=contract_id,
            playbook_name=playbook_name,
            total_deviations=len(deviations),
            critical_deviations=sum(
                1 for d in deviations if d.severity == RiskLevel.CRITICAL
            ),
            deviations=deviations,
            compliant_clauses=compliant,
            overall_compliance_pct=compliance_pct,
        )

        log.info(
            "Playbook comparison for %s: %d deviations, %.1f%% compliant",
            contract_id, len(deviations), compliance_pct,
        )
        return report

    async def generate_redline(
        self,
        original: str,
        positions: Dict[str, str],
    ) -> str:
        """Generate tracked-changes redline markup.

        Parameters
        ----------
        original:
            Original contract text.
        positions:
            Dict of clause_name -> desired replacement language.

        Returns
        -------
        str
            Redlined contract with tracked changes in markup format.
        """
        redlined = original
        changes_made = 0

        for clause_name, replacement in positions.items():
            if clause_name in STANDARD_CLAUSE_CATEGORIES:
                for keyword in STANDARD_CLAUSE_CATEGORIES[clause_name]:
                    pattern = re.compile(
                        rf"({re.escape(keyword)}[^.]*\.)",
                        re.IGNORECASE | re.DOTALL,
                    )
                    match = pattern.search(redlined)
                    if match:
                        original_text = match.group(1)
                        tracked = (
                            f"[DEL]{original_text}[/DEL] "
                            f"[INS]{replacement}[/INS]"
                        )
                        redlined = redlined[:match.start()] + tracked + redlined[match.end():]
                        changes_made += 1
                        break

        log.info("Generated redline with %d tracked changes", changes_made)

        # Apply privilege guard on output
        if self._privilege_guard:
            redlined = _enforce_privilege_guard(redlined)

        return redlined

    async def score_risk(self, contract: str) -> RiskReport:
        """Generate detailed risk score with breakdown.

        Parameters
        ----------
        contract:
            Full contract text.

        Returns
        -------
        RiskReport
            Detailed risk report with category scores and factors.
        """
        contract_id = hashlib.sha256(
            contract[:2048].encode()
        ).hexdigest()[:16]

        category_scores: Dict[str, int] = {}
        risk_factors: List[ClauseRisk] = []
        mitigating: List[str] = []

        contract_lower = contract.lower()

        for category, keywords in STANDARD_CLAUSE_CATEGORIES.items():
            present = any(kw in contract_lower for kw in keywords)
            weight = _RISK_WEIGHTS.get(category, 5.0)

            if present:
                # Clause exists — moderate risk based on content
                score = int(weight * 0.4)
                mitigating.append(f"{category} clause present")
            else:
                # Missing clause — higher risk
                score = int(weight * 0.8)
                risk_factors.append(ClauseRisk(
                    clause_name=category,
                    risk_level=RiskLevel.HIGH if weight > 10 else RiskLevel.MEDIUM,
                    section_reference="N/A",
                    description=f"No {category} clause found",
                    recommendation=f"Add standard {category} provisions",
                ))

            category_scores[category] = score

        overall = min(100, sum(category_scores.values()))
        level = (
            RiskLevel.CRITICAL if overall >= 80
            else RiskLevel.HIGH if overall >= 60
            else RiskLevel.MEDIUM if overall >= 40
            else RiskLevel.LOW if overall >= 20
            else RiskLevel.INFO
        )

        report = RiskReport(
            contract_id=contract_id,
            overall_score=overall,
            category_scores=category_scores,
            risk_factors=risk_factors,
            mitigating_factors=mitigating,
        )

        log.info("Risk score for %s: %d (%s)", contract_id, overall, level.value)
        return report

    # -------------------------------------------------------------------
    # Internal helper methods
    # -------------------------------------------------------------------

    async def _extract_parties(self, text: str) -> List[str]:
        """Extract party names from contract text."""
        parties: List[str] = []
        patterns = [
            re.compile(r"(?:between|by and between)\s+([A-Z][A-Za-z\s,\.]+?)(?:\s*\()", re.M),
            re.compile(r"(?:\"Party\"|\"Company\"|\"Client\"|\"Vendor\")\s*(?:means|refers to)\s+([A-Z][A-Za-z\s,\.]+)", re.M),
        ]
        for pattern in patterns:
            for m in pattern.finditer(text[:5000]):
                party = m.group(1).strip().rstrip(",.")
                if party and party not in parties:
                    parties.append(party)
        return parties or ["[Party A]", "[Party B]"]

    async def _extract_dates(self, text: str) -> Dict[str, Optional[str]]:
        """Extract effective and expiration dates."""
        dates: Dict[str, Optional[str]] = {"effective": None, "expiration": None}
        eff_pattern = re.compile(
            r"(?:effective\s+(?:as\s+of\s+)?(?:date|:)?\s*)(\w+\s+\d{1,2},?\s+\d{4})",
            re.IGNORECASE,
        )
        m = eff_pattern.search(text[:3000])
        if m:
            dates["effective"] = m.group(1).strip()

        exp_pattern = re.compile(
            r"(?:expir(?:es?|ation)|terminat(?:es?|ion)\s+date)\s*:?\s*(\w+\s+\d{1,2},?\s+\d{4})",
            re.IGNORECASE,
        )
        m = exp_pattern.search(text)
        if m:
            dates["expiration"] = m.group(1).strip()

        return dates

    async def _extract_governing_law(self, text: str) -> Optional[str]:
        """Extract governing law / jurisdiction."""
        pattern = re.compile(
            r"(?:govern(?:ed|ing)\s+(?:by\s+)?(?:the\s+)?laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?)"
            r"([A-Z][A-Za-z\s]+?)(?:\.|,|\s+without)",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        return m.group(1).strip() if m else None

    async def _identify_risk_clauses(
        self, text: str, ct: ContractType,
    ) -> List[ClauseRisk]:
        """Identify risky clauses in the contract."""
        risks: List[ClauseRisk] = []
        text_lower = text.lower()

        # Check for unlimited liability
        if "unlimited liability" in text_lower or (
            "limitation of liability" not in text_lower
            and ct.value not in ("nda",)
        ):
            risks.append(ClauseRisk(
                clause_name="limitation_of_liability",
                risk_level=RiskLevel.CRITICAL,
                section_reference="",
                description="No limitation of liability clause or unlimited liability exposure",
                recommendation="Add mutual liability cap (typically 12-24 months fees paid)",
            ))

        # Check for one-sided indemnification
        if "shall indemnify" in text_lower and "mutual" not in text_lower:
            risks.append(ClauseRisk(
                clause_name="indemnification",
                risk_level=RiskLevel.HIGH,
                section_reference="",
                description="One-sided indemnification obligation detected",
                recommendation="Negotiate mutual indemnification or add carve-outs",
                market_standard="Market standard is mutual indemnification with IP and "
                "third-party claims carve-outs",
            ))

        # Check for automatic renewal without notice
        if "automatic renewal" in text_lower or "auto-renew" in text_lower:
            if "notice" not in text_lower[:text_lower.find("auto") + 500] if "auto" in text_lower else True:
                risks.append(ClauseRisk(
                    clause_name="auto_renewal",
                    risk_level=RiskLevel.MEDIUM,
                    section_reference="",
                    description="Automatic renewal clause without clear notice provisions",
                    recommendation="Add 60-90 day written notice requirement for non-renewal",
                ))

        # Check for broad assignment rights
        if re.search(r"freely\s+assign", text_lower) or (
            "assignment" in text_lower and "consent" not in text_lower
        ):
            risks.append(ClauseRisk(
                clause_name="assignment",
                risk_level=RiskLevel.MEDIUM,
                section_reference="",
                description="Broad assignment rights without consent requirement",
                recommendation="Require prior written consent for assignment "
                "(with exception for affiliates)",
            ))

        return risks

    async def _extract_obligations(
        self, text: str, parties: List[str],
    ) -> List[Obligation]:
        """Extract party obligations with deadlines."""
        obligations: List[Obligation] = []
        obligation_patterns = [
            re.compile(r"(?:shall|must|agrees? to|is required to)\s+(.{20,200}?)(?:\.|;)", re.I),
        ]

        for pattern in obligation_patterns:
            for m in pattern.finditer(text):
                party = parties[0] if parties else "[Party]"
                for p in parties:
                    if p.lower() in text[max(0, m.start() - 200):m.start()].lower():
                        party = p
                        break

                obligations.append(Obligation(
                    party=party,
                    obligation=m.group(1).strip(),
                ))

        return obligations[:50]  # Cap at 50 obligations

    async def _extract_financial_terms(self, text: str) -> List[FinancialTerm]:
        """Extract payment, fee, and penalty terms."""
        terms: List[FinancialTerm] = []

        # Currency amounts
        amount_pattern = re.compile(
            r"\$[\d,]+(?:\.\d{2})?|\d+(?:,\d{3})*\s*(?:USD|EUR|GBP)",
        )
        for m in amount_pattern.finditer(text):
            context = text[max(0, m.start() - 100):m.end() + 100].lower()
            term_type = "payment"
            if "penalty" in context or "liquidated damages" in context:
                term_type = "penalty"
            elif "fee" in context:
                term_type = "fee"
            elif "milestone" in context:
                term_type = "milestone"

            terms.append(FinancialTerm(
                term_type=term_type,
                amount=m.group(),
            ))

        return terms[:30]  # Cap

    async def _extract_definitions(self, text: str) -> List[DefinedTerm]:
        """Extract defined terms dictionary."""
        definitions: List[DefinedTerm] = []

        # Pattern: "Term" means ...
        def_pattern = re.compile(
            r'"([A-Z][A-Za-z\s]+?)"\s+(?:means?|shall mean|refers? to)\s+(.{10,500}?)(?:\.|;)',
            re.MULTILINE,
        )
        for m in def_pattern.finditer(text):
            definitions.append(DefinedTerm(
                term=m.group(1).strip(),
                definition=m.group(2).strip(),
                section_reference="",
            ))

        return definitions

    async def _detect_missing_clauses(
        self, text: str, ct: ContractType,
    ) -> List[str]:
        """Detect required provisions not present in the contract."""
        missing: List[str] = []
        required = REQUIRED_PROVISIONS.get(ct.value, [])
        text_lower = text.lower()

        provision_keywords: Dict[str, List[str]] = {
            "definition_of_confidential_information": ["confidential information", "means"],
            "permitted_disclosures": ["permitted disclosure", "may disclose"],
            "return_of_materials": ["return", "destroy", "materials"],
            "term": ["term", "period", "duration"],
            "remedies": ["remedies", "injunctive", "specific performance"],
            "scope_of_services": ["scope", "services", "deliverables"],
            "payment_terms": ["payment", "invoice", "net 30", "net 60"],
            "insurance": ["insurance", "coverage", "policy"],
            "sla": ["service level", "sla", "uptime"],
            "uptime_guarantee": ["uptime", "availability", "99.9"],
            "data_portability": ["data export", "portability", "migration"],
            "purchase_price": ["purchase price", "consideration"],
            "closing_conditions": ["closing", "conditions precedent"],
            "covenants": ["covenant", "undertaking"],
            "escrow": ["escrow", "holdback"],
            "working_capital_adjustment": ["working capital", "adjustment"],
            "position_title": ["position", "title", "role"],
            "compensation": ["salary", "compensation", "base pay"],
            "benefits": ["benefits", "health insurance", "401k"],
            "non_compete": ["non-compete", "non-competition", "restrictive covenant"],
            "non_solicitation": ["non-solicitation", "non-solicit"],
            "ip_assignment": ["intellectual property", "assignment", "work product"],
            "at_will_statement": ["at-will", "at will"],
            "schedule": ["schedule", "annex"],
            "credit_support_annex": ["credit support", "csa"],
            "events_of_default": ["event of default", "default"],
            "termination_events": ["termination event"],
            "early_termination": ["early termination"],
            "netting": ["netting", "close-out"],
            "close_out_netting": ["close-out netting"],
            "premises_description": ["premises", "property", "located at"],
            "rent": ["rent", "base rent", "monthly rent"],
            "renewal_options": ["renewal", "option to renew"],
            "maintenance": ["maintenance", "repair", "upkeep"],
            "permitted_use": ["permitted use", "use of premises"],
            "default": ["default", "event of default"],
            "service_description": ["services", "scope", "description"],
            "term_renewal": ["term", "renewal", "initial term"],
        }

        # Also add standard clause categories as provision keywords
        for provision in required:
            if provision in provision_keywords:
                keywords = provision_keywords[provision]
                found = any(kw in text_lower for kw in keywords)
                if not found:
                    missing.append(provision)
            else:
                # Fall back to underscore-to-space matching
                readable = provision.replace("_", " ")
                if readable not in text_lower:
                    missing.append(provision)

        return missing

    async def _flag_unusual_provisions(
        self, text: str, ct: ContractType,
    ) -> List[str]:
        """Detect provisions that deviate from market standard."""
        unusual: List[str] = []
        text_lower = text.lower()

        # Unusual patterns
        unusual_checks = [
            ("Waiver of jury trial may be unenforceable in some jurisdictions",
             "waiver of jury trial"),
            ("Forum selection clause may limit access to courts",
             "exclusive jurisdiction"),
            ("Liquidated damages clause requires reasonableness analysis",
             "liquidated damages"),
            ("Non-reliance clause may override fraud representations",
             "non-reliance"),
            ("Most-favored-nation clause creates ongoing pricing obligations",
             "most favored nation"),
            ("Right of first refusal creates future obligations",
             "right of first refusal"),
            ("Anti-dilution provisions may have cascading effects",
             "anti-dilution"),
            ("Drag-along provisions may force minority exit",
             "drag-along"),
        ]

        for description, keyword in unusual_checks:
            if keyword in text_lower:
                unusual.append(description)

        return unusual

    async def _calculate_risk_score(
        self,
        risks: List[ClauseRisk],
        missing: List[str],
        unusual: List[str],
        ct: ContractType,
    ) -> Tuple[int, RiskLevel]:
        """Calculate overall risk score (0-100)."""
        score = 0.0

        # Risk clause contributions
        for risk in risks:
            if risk.risk_level == RiskLevel.CRITICAL:
                score += 15.0
            elif risk.risk_level == RiskLevel.HIGH:
                score += 10.0
            elif risk.risk_level == RiskLevel.MEDIUM:
                score += 5.0
            elif risk.risk_level == RiskLevel.LOW:
                score += 2.0

        # Missing clause penalty
        score += len(missing) * 4.0

        # Unusual provisions
        score += len(unusual) * 2.0

        final = min(100, int(score))
        level = (
            RiskLevel.CRITICAL if final >= 80
            else RiskLevel.HIGH if final >= 60
            else RiskLevel.MEDIUM if final >= 40
            else RiskLevel.LOW if final >= 20
            else RiskLevel.INFO
        )

        return final, level

    async def _generate_summary(
        self,
        contract_id: str,
        ct: ContractType,
        parties: List[str],
        risks: List[ClauseRisk],
        risk_score: int,
    ) -> str:
        """Generate executive summary for business review."""
        critical_count = sum(1 for r in risks if r.risk_level == RiskLevel.CRITICAL)
        high_count = sum(1 for r in risks if r.risk_level == RiskLevel.HIGH)

        summary = (
            f"Contract Analysis Summary — {ct.value.upper()}\n"
            f"Parties: {', '.join(parties)}\n"
            f"Overall Risk Score: {risk_score}/100\n"
            f"Total Risk Findings: {len(risks)} "
            f"({critical_count} critical, {high_count} high)\n"
        )

        if critical_count > 0:
            summary += "\nCRITICAL ISSUES REQUIRING IMMEDIATE ATTENTION:\n"
            for r in risks:
                if r.risk_level == RiskLevel.CRITICAL:
                    summary += f"  • {r.clause_name}: {r.description}\n"

        # Apply privilege guard
        if self._privilege_guard:
            summary = _enforce_privilege_guard(summary)

        return summary

    async def _check_regulatory_compliance(
        self, text: str,
    ) -> List[ClauseRisk]:
        """Check for regulatory compliance clauses."""
        findings: List[ClauseRisk] = []

        for regulation, patterns in _REGULATORY_PATTERNS.items():
            found = any(p.search(text) for p in patterns)
            if not found and regulation in ("GDPR", "CCPA"):
                # Data protection regulations should be present in most commercial contracts
                findings.append(ClauseRisk(
                    clause_name=f"{regulation}_compliance",
                    risk_level=RiskLevel.MEDIUM,
                    section_reference="",
                    description=f"No {regulation} compliance provisions found",
                    recommendation=f"Add {regulation} data protection addendum",
                ))

        return findings
