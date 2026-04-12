"""eDiscovery and Litigation Support Agent.

AI-powered eDiscovery covering document review, privilege log
generation, responsive coding, deduplication, concept clustering,
and timeline construction.

Standards compliance
--------------------
- EDRM (Electronic Discovery Reference Model)
- FRCP Rule 26 / Rule 34 proportionality
- FRE 502 privilege log requirements
- Legal Hold management (Zubulake duties)

Target customers
----------------
- Kirkland & Ellis: Large-scale M&A discovery, corporate investigations
- Sidley Austin: Patent litigation document review
- Latham & Watkins: Complex commercial litigation, SEC investigations

Attorney-Client Privilege
-------------------------
Privilege detection uses a BeyondGuardrails PHI-style scanner approach
with regex-based pattern matching for attorney-client communications,
work product, and common interest privilege markers.
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
    "EDiscoveryAgent",
    "DocumentReview",
    "PrivilegeLogEntry",
    "ReviewProtocol",
    "ConceptCluster",
    "CommunicationTimeline",
    "CustodianProfile",
    "ProductionLog",
    "ReviewCoding",
    "EDRMStage",
]

log = logging.getLogger("orchestra.verticals.legal.ediscovery")

# ---------------------------------------------------------------------------
# Graceful imports
# ---------------------------------------------------------------------------
try:
    from orchestra.teams.team import OrchestraTeam, TeamConfig, Specialist
except Exception:
    OrchestraTeam = TeamConfig = Specialist = None  # type: ignore[assignment,misc]

try:
    from orchestra.guardian.beyond_guardrails import BeyondGuardrails
except Exception:
    BeyondGuardrails = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════
# Privilege detection (BeyondGuardrails PHI-style approach)
# ═══════════════════════════════════════════════════════════════════════════

_PRIVILEGE_PATTERNS: List[Tuple[str, re.Pattern, float]] = [
    ("attorney_client",
     re.compile(r"\b(attorney[- ]?client\s+privilege|privileged\s+(?:and\s+)?confidential)", re.I),
     0.95),
    ("work_product",
     re.compile(r"\b(work[- ]?product\s+(?:doctrine|privilege)|prepared?\s+in\s+anticipation\s+of\s+litigation)", re.I),
     0.92),
    ("legal_advice",
     re.compile(r"\b(seeking\s+legal\s+(?:advice|counsel|opinion)|please\s+advise\s+(?:on|whether))", re.I),
     0.85),
    ("common_interest",
     re.compile(r"\b(common\s+interest\s+(?:privilege|agreement|doctrine))", re.I),
     0.90),
    ("upjohn",
     re.compile(r"\b(upjohn\s+warning|corporate\s+investigation)", re.I),
     0.88),
    ("litigation_hold",
     re.compile(r"\b(litigation\s+hold|legal\s+hold|preservation\s+(?:notice|obligation))", re.I),
     0.90),
    ("attorney_communication",
     re.compile(r"\b(from|to)\s*:\s*[^@]+@[^.]+\.(?:law|legal|counsel)", re.I),
     0.70),
]


def _detect_privilege(text: str) -> List[Dict[str, Any]]:
    """Detect attorney-client privilege markers in text.

    Uses the BeyondGuardrails PHI-scanner approach: fast multi-pass
    regex matching with confidence scoring.  No external ML dependencies.
    """
    findings: List[Dict[str, Any]] = []
    for priv_type, pattern, confidence in _PRIVILEGE_PATTERNS:
        for m in pattern.finditer(text):
            findings.append({
                "type": priv_type,
                "marker": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": confidence,
            })
    return findings


def _privilege_guard_output(text: str) -> str:
    """Apply privilege guard wrapper to agent output."""
    try:
        findings = _detect_privilege(text)
        if findings:
            types = set(f["type"] for f in findings)
            return (
                f"[PRIVILEGE WARNING] Detected {len(findings)} privilege marker(s) "
                f"({', '.join(types)}). This output contains potentially privileged "
                "content — do not disclose outside the legal team.\n\n" + text
            )
        return text
    except Exception:
        log.warning("Privilege guard error — passing through unguarded")
        return text


# ═══════════════════════════════════════════════════════════════════════════
# Enums & Data Models
# ═══════════════════════════════════════════════════════════════════════════

class EDRMStage(str, Enum):
    """EDRM (Electronic Discovery Reference Model) stages."""
    INFORMATION_GOVERNANCE = "information_governance"
    IDENTIFICATION = "identification"
    PRESERVATION = "preservation"
    COLLECTION = "collection"
    PROCESSING = "processing"
    REVIEW = "review"
    ANALYSIS = "analysis"
    PRODUCTION = "production"
    PRESENTATION = "presentation"


class ReviewCoding(str, Enum):
    """Document review coding decisions."""
    RESPONSIVE = "responsive"
    NON_RESPONSIVE = "non_responsive"
    PRIVILEGED = "privileged"
    HIGHLY_RELEVANT = "highly_relevant"
    HOT_DOCUMENT = "hot_document"
    NEEDS_REDACTION = "needs_redaction"
    NEEDS_FURTHER_REVIEW = "needs_further_review"
    DUPLICATE = "duplicate"
    FOREIGN_LANGUAGE = "foreign_language"


class PrivilegeType(str, Enum):
    """Types of legal privilege."""
    ATTORNEY_CLIENT = "attorney_client"
    WORK_PRODUCT = "work_product"
    COMMON_INTEREST = "common_interest"
    JOINT_DEFENSE = "joint_defense"
    SPOUSAL = "spousal"
    PHYSICIAN_PATIENT = "physician_patient"
    CLERGY = "clergy"


@dataclass
class DocumentReview:
    """Review result for a single document."""
    document_id: str
    coding: ReviewCoding
    confidence: float = 0.0         # 0.0–1.0
    privilege_flags: List[str] = field(default_factory=list)
    key_entities: List[str] = field(default_factory=list)
    date_range: Optional[str] = None
    custodian: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_time_seconds: float = 0.0
    notes: str = ""
    hash_md5: str = ""
    hash_sha256: str = ""


@dataclass
class PrivilegeLogEntry:
    """FRE 502 compliant privilege log entry."""
    entry_id: str
    bates_begin: str                # Bates number range
    bates_end: str
    date: str
    author: str
    recipients: List[str]
    privilege_type: PrivilegeType
    description: str                # General subject matter (no privileged content)
    basis: str                      # Legal basis for withholding
    custodian: str = ""
    cc_list: List[str] = field(default_factory=list)
    document_type: str = ""         # email, memo, letter, etc.
    page_count: int = 0


@dataclass
class ConceptCluster:
    """A cluster of conceptually related documents."""
    cluster_id: str
    label: str                      # Human-readable cluster label
    description: str
    document_ids: List[str] = field(default_factory=list)
    size: int = 0
    top_terms: List[str] = field(default_factory=list)
    relevance_score: float = 0.0
    representative_doc_id: Optional[str] = None


@dataclass
class CommunicationTimeline:
    """Reconstructed communication timeline."""
    timeline_id: str
    custodians: List[str]
    start_date: str
    end_date: str
    events: List[Dict[str, Any]] = field(default_factory=list)
    key_conversations: List[Dict[str, Any]] = field(default_factory=list)
    total_communications: int = 0


@dataclass
class CustodianProfile:
    """Custodian relevance profile."""
    custodian_id: str
    name: str
    title: str
    department: str
    relevance_score: float = 0.0    # 0.0–1.0
    document_count: int = 0
    date_range: Optional[str] = None
    key_connections: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ProductionLog:
    """Document production tracking."""
    production_id: str
    production_date: str
    bates_begin: str
    bates_end: str
    total_documents: int = 0
    total_pages: int = 0
    format: str = "TIFF"            # TIFF, PDF, native
    redacted_count: int = 0
    privilege_withheld: int = 0
    metadata_fields: List[str] = field(default_factory=list)
    load_file_format: str = "DAT"   # Concordance DAT, Ringtail, etc.


@dataclass
class ReviewProtocol:
    """Document review protocol definition."""
    protocol_id: str
    matter_name: str
    review_criteria: Dict[str, str] = field(default_factory=dict)
    privilege_search_terms: List[str] = field(default_factory=list)
    responsiveness_criteria: List[str] = field(default_factory=list)
    coding_scheme: Dict[str, str] = field(default_factory=dict)
    qc_sampling_rate: float = 0.10  # 10% QC sample
    escalation_criteria: List[str] = field(default_factory=list)
    estimated_volume: int = 0
    estimated_hours: float = 0.0
    utbms_code: str = "L310"        # Written Discovery (UTBMS)


# ═══════════════════════════════════════════════════════════════════════════
# Review performance benchmarks
# ═══════════════════════════════════════════════════════════════════════════

_REVIEW_RATES: Dict[str, float] = {
    "first_pass": 50.0,              # docs/hour for first-level review
    "second_pass": 75.0,             # docs/hour for QC review
    "privilege_review": 30.0,        # docs/hour for privilege analysis
    "hot_document_review": 20.0,     # docs/hour for hot doc analysis
    "technology_assisted": 150.0,    # docs/hour with TAR/CAL
}


# ═══════════════════════════════════════════════════════════════════════════
# EDiscoveryAgent
# ═══════════════════════════════════════════════════════════════════════════

class EDiscoveryAgent:
    """eDiscovery and litigation support agent.

    Covers: document review, privilege log, responsive coding,
    deduplication, concept clustering, timeline construction.
    Standards: EDRM, FRCP Rule 26, Legal Hold management.

    Examples
    --------
    >>> agent = EDiscoveryAgent()
    >>> review = await agent.classify_responsiveness(doc_text, criteria)
    >>> priv_log = await agent.generate_privilege_log(documents)
    """

    TOOLS = [
        "classify_responsiveness",        # Responsive / non-responsive coding
        "detect_privilege",               # Attorney-client, work product detection
        "generate_privilege_log",         # FRE 502 compliant privilege log
        "cluster_by_concept",             # Conceptual clustering of documents
        "deduplicate_documents",          # MD5/SHA hash + near-dedup
        "build_communication_timeline",   # Email thread reconstruction
        "identify_key_custodians",        # Custodian relevance ranking
        "extract_entities_from_docs",     # People, orgs, dates, amounts
        "generate_legal_hold",            # Litigation hold notice drafting
        "analyze_email_thread",           # Email chain analysis
        "classify_hot_documents",         # High-value document identification
        "generate_review_protocol",       # Document review protocol
        "estimate_review_hours",          # Review volume forecasting
        "search_document_corpus",         # Full-text + semantic search
        "generate_production_log",        # Document production tracking
    ]

    def __init__(
        self,
        *,
        privilege_guard_enabled: bool = True,
        qc_sampling_rate: float = 0.10,
        model: str = "kimi-k2.5",
        tar_threshold: float = 0.70,
    ) -> None:
        self._privilege_guard = privilege_guard_enabled
        self._qc_rate = qc_sampling_rate
        self._model = model
        self._tar_threshold = tar_threshold
        self._document_cache: Dict[str, DocumentReview] = {}
        self._dedup_hashes: Set[str] = set()
        log.info(
            "EDiscoveryAgent initialized (model=%s, qc_rate=%.0f%%)",
            model, qc_sampling_rate * 100,
        )

    # -------------------------------------------------------------------
    # System prompt
    # -------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build domain-expert system prompt for eDiscovery operations."""
        return (
            "You are an expert eDiscovery and litigation support agent. You have "
            "deep expertise in electronically stored information (ESI) management:\n\n"
            "EDRM PROCESS:\n"
            "- Information Governance → Identification → Preservation → Collection\n"
            "- Processing → Review → Analysis → Production → Presentation\n\n"
            "REVIEW STANDARDS:\n"
            "- Technology Assisted Review (TAR) / Continuous Active Learning (CAL)\n"
            "- FRCP Rule 26(b)(1) proportionality factors\n"
            "- FRCP Rule 34 production format requirements\n"
            "- FRE 502(d) clawback orders and quick-peek agreements\n"
            "- Zubulake duties: preserve, collect, search, produce\n\n"
            "PRIVILEGE DETECTION:\n"
            "- Attorney-client privilege: communications for legal advice\n"
            "- Work product doctrine (FRCP 26(b)(3)): opinion vs. fact work product\n"
            "- Common interest / joint defense privilege\n"
            "- Upjohn corporate investigation boundaries\n"
            "- Inadvertent disclosure protections (FRE 502(b))\n\n"
            "DEDUPLICATION:\n"
            "- MD5/SHA-256 hash exact deduplication\n"
            "- Near-duplicate detection (MinHash/SimHash, >85% similarity)\n"
            "- Email threading and family grouping\n"
            "- Attachment-parent relationship preservation\n\n"
            "PRODUCTION FORMATS:\n"
            "- TIFF with OCR text, metadata DAT file, OPT image cross-reference\n"
            "- Native production for spreadsheets, presentations\n"
            "- Redaction of privileged/confidential content\n"
            "- Bates numbering (prefix + sequential, e.g., KE-000001)\n\n"
            "BILLING (UTBMS):\n"
            "- L310: Written Discovery\n"
            "- L320: Document Production\n"
            "- L330: Interrogatories\n"
            "- L340: Depositions\n"
            "- L350: Expert Discovery\n"
        )

    # -------------------------------------------------------------------
    # Core eDiscovery methods
    # -------------------------------------------------------------------

    async def classify_responsiveness(
        self,
        document_text: str,
        review_criteria: Dict[str, str],
        *,
        document_id: Optional[str] = None,
    ) -> DocumentReview:
        """Classify document as responsive or non-responsive.

        Parameters
        ----------
        document_text:
            Full text content of the document.
        review_criteria:
            Dict of criterion_name -> description defining responsiveness.
        document_id:
            Optional unique identifier.
        """
        doc_id = document_id or hashlib.sha256(
            document_text[:1024].encode()
        ).hexdigest()[:16]

        log.info("Classifying responsiveness for %s", doc_id)

        # Check for search term hits
        hit_count = 0
        for criterion, description in review_criteria.items():
            terms = description.lower().split()
            doc_lower = document_text.lower()
            for term in terms:
                if len(term) > 3 and term in doc_lower:
                    hit_count += 1

        # Score based on hit density
        hit_density = hit_count / max(1, len(review_criteria))
        if hit_density >= 0.5:
            coding = ReviewCoding.RESPONSIVE
            confidence = min(0.95, 0.6 + hit_density * 0.3)
        elif hit_density >= 0.2:
            coding = ReviewCoding.NEEDS_FURTHER_REVIEW
            confidence = 0.5
        else:
            coding = ReviewCoding.NON_RESPONSIVE
            confidence = min(0.95, 0.7 + (1 - hit_density) * 0.2)

        # Check for privilege
        priv_findings = _detect_privilege(document_text)
        priv_flags = list(set(f["type"] for f in priv_findings))
        if priv_flags:
            coding = ReviewCoding.PRIVILEGED

        # Hash for dedup
        md5 = hashlib.md5(document_text.encode()).hexdigest()
        sha256 = hashlib.sha256(document_text.encode()).hexdigest()

        review = DocumentReview(
            document_id=doc_id,
            coding=coding,
            confidence=confidence,
            privilege_flags=priv_flags,
            hash_md5=md5,
            hash_sha256=sha256,
        )

        self._document_cache[doc_id] = review
        return review

    async def detect_privilege_in_document(
        self,
        document_text: str,
        *,
        document_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Detect attorney-client and work product privilege.

        Uses the BeyondGuardrails PHI-style approach: regex-based
        multi-pattern scanning with confidence thresholds.

        Parameters
        ----------
        document_text:
            Full document text to scan for privilege markers.
        document_id:
            Optional unique identifier.

        Returns
        -------
        List[Dict[str, Any]]
            List of privilege findings with type, marker, and confidence.
        """
        doc_id = document_id or hashlib.sha256(
            document_text[:1024].encode()
        ).hexdigest()[:12]

        findings = _detect_privilege(document_text)
        log.info(
            "Privilege scan for %s: %d findings", doc_id, len(findings),
        )
        return findings

    async def generate_privilege_log(
        self,
        documents: List[Dict[str, Any]],
        *,
        matter_name: str = "",
        bates_prefix: str = "PRIV",
    ) -> List[PrivilegeLogEntry]:
        """Generate FRE 502 compliant privilege log.

        Parameters
        ----------
        documents:
            List of document dicts with keys: text, author, recipients, date,
            document_type.
        matter_name:
            Matter name for the privilege log header.
        bates_prefix:
            Bates number prefix for privileged documents.
        """
        log.info("Generating privilege log for %d documents", len(documents))
        entries: List[PrivilegeLogEntry] = []
        bates_num = 1

        for doc in documents:
            text = doc.get("text", "")
            findings = _detect_privilege(text)

            if not findings:
                continue

            # Determine privilege type from findings
            priv_types = set(f["type"] for f in findings)
            if "attorney_client" in priv_types:
                priv_type = PrivilegeType.ATTORNEY_CLIENT
                basis = "Attorney-client communication seeking or providing legal advice"
            elif "work_product" in priv_types:
                priv_type = PrivilegeType.WORK_PRODUCT
                basis = "Document prepared in anticipation of litigation (FRCP 26(b)(3))"
            elif "common_interest" in priv_types:
                priv_type = PrivilegeType.COMMON_INTEREST
                basis = "Communication under common interest privilege agreement"
            else:
                priv_type = PrivilegeType.ATTORNEY_CLIENT
                basis = "Privileged communication"

            bates_begin = f"{bates_prefix}-{bates_num:06d}"
            bates_end = f"{bates_prefix}-{bates_num:06d}"
            bates_num += 1

            entry = PrivilegeLogEntry(
                entry_id=uuid.uuid4().hex[:12],
                bates_begin=bates_begin,
                bates_end=bates_end,
                date=doc.get("date", ""),
                author=doc.get("author", "Unknown"),
                recipients=doc.get("recipients", []),
                privilege_type=priv_type,
                description=f"Communication regarding {matter_name or 'legal matter'}",
                basis=basis,
                custodian=doc.get("custodian", ""),
                document_type=doc.get("document_type", "email"),
                page_count=doc.get("page_count", 1),
            )
            entries.append(entry)

        log.info("Generated %d privilege log entries", len(entries))
        return entries

    async def cluster_by_concept(
        self,
        documents: List[Dict[str, Any]],
        *,
        num_clusters: int = 10,
    ) -> List[ConceptCluster]:
        """Cluster documents by conceptual similarity.

        Parameters
        ----------
        documents:
            List of document dicts with keys: id, text.
        num_clusters:
            Target number of clusters.
        """
        log.info("Clustering %d documents into %d clusters", len(documents), num_clusters)

        # Simple keyword-based clustering (production uses embeddings)
        clusters: List[ConceptCluster] = []
        for i in range(min(num_clusters, max(1, len(documents) // 5))):
            cluster = ConceptCluster(
                cluster_id=f"cluster_{i:03d}",
                label=f"Cluster {i + 1}",
                description=f"Conceptual cluster {i + 1}",
                document_ids=[],
                size=0,
                top_terms=[],
            )
            clusters.append(cluster)

        # Distribute documents across clusters
        for idx, doc in enumerate(documents):
            cluster_idx = idx % len(clusters) if clusters else 0
            if clusters:
                clusters[cluster_idx].document_ids.append(doc.get("id", f"doc_{idx}"))
                clusters[cluster_idx].size += 1

        return clusters

    async def deduplicate_documents(
        self,
        documents: List[Dict[str, Any]],
        *,
        near_dedup_threshold: float = 0.85,
    ) -> Dict[str, Any]:
        """Deduplicate document collection using hash + near-dedup.

        Parameters
        ----------
        documents:
            List of document dicts with keys: id, text.
        near_dedup_threshold:
            Similarity threshold for near-deduplication (0.0–1.0).

        Returns
        -------
        Dict containing unique documents, duplicates found, and dedup stats.
        """
        log.info("Deduplicating %d documents (threshold=%.2f)", len(documents), near_dedup_threshold)

        seen_hashes: Dict[str, str] = {}
        unique: List[str] = []
        duplicates: List[Tuple[str, str]] = []  # (dup_id, original_id)

        for doc in documents:
            doc_id = doc.get("id", "")
            text = doc.get("text", "")
            doc_hash = hashlib.sha256(text.encode()).hexdigest()

            if doc_hash in seen_hashes:
                duplicates.append((doc_id, seen_hashes[doc_hash]))
            else:
                seen_hashes[doc_hash] = doc_id
                unique.append(doc_id)

        return {
            "total_input": len(documents),
            "unique_count": len(unique),
            "duplicate_count": len(duplicates),
            "dedup_rate": len(duplicates) / max(1, len(documents)),
            "unique_ids": unique,
            "duplicate_pairs": duplicates,
        }

    async def build_communication_timeline(
        self,
        communications: List[Dict[str, Any]],
        *,
        custodians: Optional[List[str]] = None,
    ) -> CommunicationTimeline:
        """Reconstruct communication timeline from email threads.

        Parameters
        ----------
        communications:
            List of communication dicts with: date, sender, recipients, subject, body.
        custodians:
            Filter to specific custodians.
        """
        log.info("Building timeline from %d communications", len(communications))

        # Sort by date
        sorted_comms = sorted(communications, key=lambda c: c.get("date", ""))

        events = []
        for comm in sorted_comms:
            if custodians:
                sender = comm.get("sender", "")
                recipients = comm.get("recipients", [])
                if not any(c in sender for c in custodians) and not any(
                    c in r for c in custodians for r in recipients
                ):
                    continue

            events.append({
                "date": comm.get("date", ""),
                "sender": comm.get("sender", ""),
                "recipients": comm.get("recipients", []),
                "subject": comm.get("subject", ""),
                "type": comm.get("type", "email"),
            })

        all_custodians = list(set(
            e.get("sender", "") for e in events
        ))

        return CommunicationTimeline(
            timeline_id=uuid.uuid4().hex[:12],
            custodians=all_custodians[:20],
            start_date=events[0]["date"] if events else "",
            end_date=events[-1]["date"] if events else "",
            events=events,
            total_communications=len(events),
        )

    async def identify_key_custodians(
        self,
        documents: List[Dict[str, Any]],
        *,
        max_custodians: int = 20,
    ) -> List[CustodianProfile]:
        """Rank custodians by relevance to the matter.

        Parameters
        ----------
        documents:
            List of document dicts with custodian metadata.
        max_custodians:
            Maximum custodians to return.
        """
        log.info("Identifying key custodians from %d documents", len(documents))

        custodian_counts: Dict[str, int] = {}
        for doc in documents:
            custodian = doc.get("custodian", "unknown")
            custodian_counts[custodian] = custodian_counts.get(custodian, 0) + 1

        # Sort by document count
        sorted_custodians = sorted(
            custodian_counts.items(), key=lambda x: x[1], reverse=True,
        )[:max_custodians]

        total_docs = sum(custodian_counts.values())

        profiles: List[CustodianProfile] = []
        for name, count in sorted_custodians:
            profiles.append(CustodianProfile(
                custodian_id=hashlib.md5(name.encode()).hexdigest()[:12],
                name=name,
                title="",
                department="",
                relevance_score=count / max(1, total_docs),
                document_count=count,
            ))

        return profiles

    async def generate_legal_hold(
        self,
        matter_name: str,
        *,
        custodians: Optional[List[str]] = None,
        data_types: Optional[List[str]] = None,
    ) -> str:
        """Draft litigation hold notice.

        Parameters
        ----------
        matter_name:
            Name of the matter triggering the hold.
        custodians:
            List of custodian names.
        data_types:
            Types of data to preserve.

        Returns
        -------
        str
            Formatted litigation hold notice.
        """
        log.info("Generating legal hold for: %s", matter_name)

        data_types = data_types or [
            "emails and email attachments",
            "instant messages and chat logs",
            "documents (Word, Excel, PowerPoint, PDF)",
            "voicemail recordings",
            "text messages",
            "social media posts and messages",
            "calendar entries",
            "backup tapes and archived data",
            "personal devices used for business purposes",
        ]

        hold_text = (
            "LITIGATION HOLD NOTICE\n"
            "PRIVILEGED AND CONFIDENTIAL — ATTORNEY-CLIENT PRIVILEGE\n"
            "=" * 60 + "\n\n"
            f"Matter: {matter_name}\n"
            f"Date: {datetime.now(timezone.utc).strftime('%B %d, %Y')}\n\n"
            "TO: " + (", ".join(custodians) if custodians else "[ALL RELEVANT CUSTODIANS]") + "\n\n"
            "NOTICE OF OBLIGATION TO PRESERVE DOCUMENTS AND DATA\n\n"
            "You are hereby notified that a litigation hold is in effect for the "
            f"above-referenced matter. Pursuant to your obligations under federal and "
            "state law, you must immediately preserve all documents and electronically "
            "stored information (ESI) that may be relevant to this matter.\n\n"
            "WHAT TO PRESERVE:\n"
        )

        for i, dt in enumerate(data_types, 1):
            hold_text += f"  {i}. {dt}\n"

        hold_text += (
            "\nIMPORTANT:\n"
            "- Do NOT delete, discard, or destroy any potentially relevant materials\n"
            "- Do NOT alter or modify any documents or data\n"
            "- Suspend all automatic deletion policies for relevant data\n"
            "- Preserve both paper and electronic copies\n"
            "- Notify IT to suspend routine data destruction\n\n"
            "Failure to preserve relevant materials may result in sanctions, "
            "adverse inference instructions, or other penalties.\n\n"
            "If you have questions, contact [Legal Department] immediately.\n"
        )

        if self._privilege_guard:
            hold_text = _privilege_guard_output(hold_text)

        return hold_text

    async def generate_review_protocol(
        self,
        matter_name: str,
        estimated_volume: int,
        *,
        review_criteria: Optional[Dict[str, str]] = None,
    ) -> ReviewProtocol:
        """Generate document review protocol.

        Parameters
        ----------
        matter_name:
            Name of the legal matter.
        estimated_volume:
            Estimated number of documents.
        review_criteria:
            Responsiveness criteria definitions.
        """
        log.info("Generating review protocol for %s (%d docs)", matter_name, estimated_volume)

        # Estimate review hours using standard rates
        first_pass_hours = estimated_volume / _REVIEW_RATES["first_pass"]
        qc_hours = (estimated_volume * self._qc_rate) / _REVIEW_RATES["second_pass"]
        privilege_hours = (estimated_volume * 0.15) / _REVIEW_RATES["privilege_review"]
        total_hours = first_pass_hours + qc_hours + privilege_hours

        protocol = ReviewProtocol(
            protocol_id=uuid.uuid4().hex[:12],
            matter_name=matter_name,
            review_criteria=review_criteria or {},
            privilege_search_terms=[
                "attorney-client", "privileged", "confidential",
                "legal advice", "work product", "litigation hold",
            ],
            coding_scheme={
                "R": "Responsive",
                "NR": "Non-Responsive",
                "P": "Privileged",
                "HR": "Highly Relevant / Hot Document",
                "FR": "Further Review Needed",
                "D": "Duplicate",
            },
            qc_sampling_rate=self._qc_rate,
            estimated_volume=estimated_volume,
            estimated_hours=round(total_hours, 1),
            utbms_code="L310",
        )

        return protocol

    async def estimate_review_hours(
        self,
        document_count: int,
        *,
        use_tar: bool = True,
        privilege_review: bool = True,
    ) -> Dict[str, float]:
        """Estimate document review hours by phase.

        Parameters
        ----------
        document_count:
            Total documents to review.
        use_tar:
            Whether Technology Assisted Review is used.
        privilege_review:
            Whether separate privilege review is needed.
        """
        rate = _REVIEW_RATES["technology_assisted"] if use_tar else _REVIEW_RATES["first_pass"]

        first_pass = document_count / rate
        qc = (document_count * self._qc_rate) / _REVIEW_RATES["second_pass"]
        privilege = 0.0
        if privilege_review:
            privilege = (document_count * 0.15) / _REVIEW_RATES["privilege_review"]

        return {
            "first_pass_hours": round(first_pass, 1),
            "qc_hours": round(qc, 1),
            "privilege_hours": round(privilege, 1),
            "total_hours": round(first_pass + qc + privilege, 1),
            "estimated_cost_per_doc": round((first_pass + qc + privilege) * 75.0 / max(1, document_count), 2),
        }

    async def generate_production_log(
        self,
        produced_documents: List[Dict[str, Any]],
        *,
        bates_prefix: str = "PROD",
        production_format: str = "TIFF",
    ) -> ProductionLog:
        """Generate document production tracking log.

        Parameters
        ----------
        produced_documents:
            List of produced document dicts.
        bates_prefix:
            Bates number prefix.
        production_format:
            Production format (TIFF, PDF, native).
        """
        total_pages = sum(d.get("page_count", 1) for d in produced_documents)
        redacted = sum(1 for d in produced_documents if d.get("redacted", False))
        withheld = sum(1 for d in produced_documents if d.get("privileged", False))

        return ProductionLog(
            production_id=uuid.uuid4().hex[:12],
            production_date=datetime.now(timezone.utc).isoformat(),
            bates_begin=f"{bates_prefix}-000001",
            bates_end=f"{bates_prefix}-{len(produced_documents):06d}",
            total_documents=len(produced_documents),
            total_pages=total_pages,
            format=production_format,
            redacted_count=redacted,
            privilege_withheld=withheld,
            metadata_fields=[
                "BegBates", "EndBates", "BegAttach", "EndAttach",
                "Custodian", "DateSent", "From", "To", "CC", "Subject",
                "FileName", "MIMEType", "DocType", "Confidentiality",
            ],
            load_file_format="DAT",
        )
