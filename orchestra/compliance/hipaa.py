"""
HIPAA Compliance Controls.

Protected Health Information (PHI) handling controls including PHI
scanning/redaction, access logging, encryption, minimum necessary
rule enforcement, and Business Associate Agreement (BAA) tracking.
Covers all 18 HIPAA identifiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

__all__ = [
    "PHIField",
    "PHIMatch",
    "PHIScanner",
    "HIPAAControls",
    "BAARecord",
    "BAATracker",
]


# ---------------------------------------------------------------------------
# Try to import cryptography for AES-256-GCM; fall back to XOR
# ---------------------------------------------------------------------------

_HAS_CRYPTOGRAPHY = False
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# PHI Field Enum — all 18 HIPAA identifiers
# ---------------------------------------------------------------------------

class PHIField(str, Enum):
    """All 18 HIPAA identifiers (45 CFR §164.514(b)(2))."""
    NAME = "name"
    GEOGRAPHIC = "geographic"
    DATE = "date"
    PHONE = "phone"
    FAX = "fax"
    EMAIL = "email"
    SSN = "ssn"
    MRN = "mrn"  # Medical Record Number
    HEALTH_PLAN_ID = "health_plan_id"
    ACCOUNT_NUMBER = "account_number"
    CERTIFICATE_LICENSE = "certificate_license"
    VEHICLE_ID = "vehicle_id"
    DEVICE_ID = "device_id"
    URL = "url"
    IP_ADDRESS = "ip_address"
    BIOMETRIC = "biometric"
    PHOTO = "photo"
    OTHER_UNIQUE = "other_unique"


# ---------------------------------------------------------------------------
# PHI Match result
# ---------------------------------------------------------------------------

@dataclass
class PHIMatch:
    """A detected PHI instance in text."""
    field_type: PHIField
    value: str
    start: int
    end: int
    confidence: float = 0.9
    pattern_name: str = ""

    def to_dict(self) -> dict:
        return {
            "field_type": self.field_type.value,
            "value": self.value,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "pattern_name": self.pattern_name,
        }


# ---------------------------------------------------------------------------
# PHI Scanner — 30+ regex patterns for all 18 HIPAA identifiers
# ---------------------------------------------------------------------------

class PHIScanner:
    """
    Scans LLM input/output for Protected Health Information (PHI).

    Uses 30+ regex patterns covering all 18 HIPAA identifiers.
    Supports scanning, redaction, and safety checks.
    """

    # Pattern registry: (PHIField, pattern_name, regex, confidence)
    _PATTERNS: List[Tuple[PHIField, str, re.Pattern, float]] = []

    @classmethod
    def _build_patterns(cls) -> None:
        """Build regex patterns for all 18 HIPAA identifiers."""
        if cls._PATTERNS:
            return  # Already built

        patterns: List[Tuple[PHIField, str, str, float]] = [
            # 1. Names
            (PHIField.NAME, "name_prefix_pattern",
             r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", 0.85),
            (PHIField.NAME, "name_patient_label",
             r"(?:patient|name|subject)[\s:]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", 0.90),

            # 2. Geographic (zip codes, addresses)
            (PHIField.GEOGRAPHIC, "zip_code_full",
             r"\b\d{5}(?:-\d{4})?\b", 0.70),
            (PHIField.GEOGRAPHIC, "street_address",
             r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Ave|Blvd|Dr|Ln|Rd|Way|Ct|Pl|Cir)\b", 0.80),
            (PHIField.GEOGRAPHIC, "po_box",
             r"(?i)\bP\.?O\.?\s*Box\s+\d+\b", 0.85),

            # 3. Dates (birth dates, admission dates, etc.)
            (PHIField.DATE, "date_mdy_slash",
             r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b", 0.80),
            (PHIField.DATE, "date_ymd_dash",
             r"\b(?:19|20)\d{2}-(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])\b", 0.80),
            (PHIField.DATE, "date_written",
             r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b", 0.85),
            (PHIField.DATE, "date_dob_label",
             r"(?i)(?:DOB|date\s+of\s+birth|birth\s*date)[\s:]+(\S+)", 0.95),

            # 4. Phone numbers
            (PHIField.PHONE, "phone_us_standard",
             r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", 0.85),
            (PHIField.PHONE, "phone_international",
             r"\b\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b", 0.80),

            # 5. Fax numbers
            (PHIField.FAX, "fax_labeled",
             r"(?i)fax[\s:]+(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}", 0.90),

            # 6. Email addresses
            (PHIField.EMAIL, "email_standard",
             r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", 0.95),

            # 7. Social Security Numbers
            (PHIField.SSN, "ssn_standard",
             r"\b\d{3}-\d{2}-\d{4}\b", 0.95),
            (PHIField.SSN, "ssn_no_dash",
             r"(?i)(?:SSN|social\s+security)[\s:#]+(\d{9})", 0.95),

            # 8. Medical Record Numbers
            (PHIField.MRN, "mrn_labeled",
             r"(?i)(?:MRN|medical\s+record|patient\s+(?:id|number))[\s:#]+([A-Z0-9-]{4,20})", 0.95),
            (PHIField.MRN, "mrn_pattern",
             r"\bMRN[\s:#]+\d{6,10}\b", 0.95),

            # 9. Health plan beneficiary numbers
            (PHIField.HEALTH_PLAN_ID, "health_plan_id",
             r"(?i)(?:health\s+plan|insurance|member)\s*(?:id|number|#)[\s:]+([A-Z0-9-]{6,20})", 0.90),
            (PHIField.HEALTH_PLAN_ID, "medicare_id",
             r"\b\d{1}[A-Z]{1,2}\d{1,2}[A-Z]{1,2}\d{1,2}\b", 0.80),

            # 10. Account numbers
            (PHIField.ACCOUNT_NUMBER, "account_labeled",
             r"(?i)(?:account|acct)\s*(?:number|#|no)[\s:]+([A-Z0-9-]{6,20})", 0.85),
            (PHIField.ACCOUNT_NUMBER, "bank_routing",
             r"\b\d{9}\b(?=.*(?:routing|ABA))", 0.80),

            # 11. Certificate/license numbers
            (PHIField.CERTIFICATE_LICENSE, "license_number",
             r"(?i)(?:license|certificate|DEA)\s*(?:number|#|no)[\s:]+([A-Z0-9-]{5,15})", 0.85),
            (PHIField.CERTIFICATE_LICENSE, "npi_number",
             r"\bNPI[\s:#]+\d{10}\b", 0.95),
            (PHIField.CERTIFICATE_LICENSE, "drivers_license",
             r"(?i)(?:driver'?s?\s+license|DL)\s*(?:#|number|no)[\s:]+([A-Z0-9-]{5,15})", 0.90),

            # 12. Vehicle identifiers
            (PHIField.VEHICLE_ID, "vin_number",
             r"\b[A-HJ-NPR-Z0-9]{17}\b", 0.70),
            (PHIField.VEHICLE_ID, "license_plate",
             r"(?i)(?:plate|tag)\s*(?:#|number)[\s:]+([A-Z0-9-]{4,8})", 0.80),

            # 13. Device identifiers and serial numbers
            (PHIField.DEVICE_ID, "device_serial",
             r"(?i)(?:serial|device|UDI)\s*(?:number|#|no)[\s:]+([A-Z0-9-]{6,25})", 0.85),
            (PHIField.DEVICE_ID, "imei_number",
             r"\b\d{15,17}\b(?=.*(?:IMEI|device))", 0.85),

            # 14. URLs
            (PHIField.URL, "url_pattern",
             r"https?://(?:www\.)?[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}(?:/[^\s]*)?", 0.60),

            # 15. IP addresses
            (PHIField.IP_ADDRESS, "ipv4_address",
             r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b", 0.85),
            (PHIField.IP_ADDRESS, "ipv6_address",
             r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b", 0.85),

            # 16. Biometric identifiers (labeled references)
            (PHIField.BIOMETRIC, "biometric_labeled",
             r"(?i)(?:fingerprint|retina|iris|voice\s+print|facial\s+recognition)\s*(?:id|data|hash)[\s:]+\S+", 0.90),

            # 17. Photo references
            (PHIField.PHOTO, "photo_reference",
             r"(?i)(?:photo|image|headshot|portrait)\s*(?:id|file|ref)[\s:]+\S+", 0.75),

            # 18. Other unique identifiers
            (PHIField.OTHER_UNIQUE, "dea_number",
             r"\b[A-Z]{2}\d{7}\b", 0.70),
            (PHIField.OTHER_UNIQUE, "group_number",
             r"(?i)(?:group|plan)\s*(?:number|#|no)[\s:]+([A-Z0-9-]{4,12})", 0.75),
        ]

        cls._PATTERNS = [
            (phi_field, name, re.compile(pattern), confidence)
            for phi_field, name, pattern, confidence in patterns
        ]

    def __init__(self, min_confidence: float = 0.7):
        self._build_patterns()
        self.min_confidence = min_confidence

    def scan(self, text: str) -> List[PHIMatch]:
        """
        Scan text for PHI patterns.

        Returns a list of PHIMatch objects for each detected PHI instance.
        """
        matches: List[PHIMatch] = []
        seen_spans: Set[Tuple[int, int]] = set()

        for phi_field, name, pattern, confidence in self._PATTERNS:
            if confidence < self.min_confidence:
                continue

            for m in pattern.finditer(text):
                span = (m.start(), m.end())
                # Avoid overlapping matches
                if any(
                    s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1]
                    for s in seen_spans
                ):
                    continue

                matches.append(PHIMatch(
                    field_type=phi_field,
                    value=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    confidence=confidence,
                    pattern_name=name,
                ))
                seen_spans.add(span)

        # Sort by position
        matches.sort(key=lambda x: x.start)
        return matches

    def redact(self, text: str) -> Tuple[str, List[PHIMatch]]:
        """
        Redact PHI from text.

        Returns the redacted text and a list of PHI matches that were redacted.
        Replaces PHI with [REDACTED:<type>] tokens.
        """
        matches = self.scan(text)
        if not matches:
            return text, []

        # Process in reverse order to preserve positions
        result = text
        for match in reversed(matches):
            replacement = f"[REDACTED:{match.field_type.value.upper()}]"
            result = result[:match.start] + replacement + result[match.end:]

        return result, matches

    def is_phi_safe(self, text: str) -> bool:
        """Check if text is free of PHI. Returns True if no PHI detected."""
        return len(self.scan(text)) == 0


# ---------------------------------------------------------------------------
# BAA (Business Associate Agreement) Tracker
# ---------------------------------------------------------------------------

@dataclass
class BAARecord:
    """Business Associate Agreement record."""
    id: str = ""
    org_id: str = ""
    associate_name: str = ""
    associate_type: str = ""  # e.g., "cloud_provider", "subcontractor"
    effective_date: str = ""
    expiration_date: str = ""
    signed: bool = False
    signer_name: str = ""
    signer_email: str = ""
    document_ref: str = ""
    status: str = "active"  # active | expired | terminated

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "associate_name": self.associate_name,
            "associate_type": self.associate_type,
            "effective_date": self.effective_date,
            "expiration_date": self.expiration_date,
            "signed": self.signed,
            "signer_name": self.signer_name,
            "signer_email": self.signer_email,
            "document_ref": self.document_ref,
            "status": self.status,
        }


class BAATracker:
    """
    Track Business Associate Agreements (BAAs) for HIPAA compliance.

    Manages BAA lifecycle including creation, signing, expiration,
    and compliance status checks.
    """

    def __init__(self) -> None:
        self._baas: Dict[str, BAARecord] = {}

    async def create_baa(
        self,
        org_id: str,
        associate_name: str,
        associate_type: str = "cloud_provider",
        effective_date: str = "",
        expiration_date: str = "",
    ) -> BAARecord:
        """Create a new BAA record."""
        baa = BAARecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            associate_name=associate_name,
            associate_type=associate_type,
            effective_date=effective_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            expiration_date=expiration_date,
            status="active",
        )
        self._baas[baa.id] = baa
        return baa

    async def sign_baa(
        self,
        baa_id: str,
        signer_name: str,
        signer_email: str,
        document_ref: str = "",
    ) -> BAARecord:
        """Record BAA signature."""
        baa = self._baas.get(baa_id)
        if not baa:
            raise ValueError(f"BAA '{baa_id}' not found")
        baa.signed = True
        baa.signer_name = signer_name
        baa.signer_email = signer_email
        baa.document_ref = document_ref
        return baa

    async def get_baa(self, baa_id: str) -> BAARecord | None:
        """Get a BAA by ID."""
        return self._baas.get(baa_id)

    async def list_baas(self, org_id: str | None = None) -> List[BAARecord]:
        """List BAAs, optionally filtered by org_id."""
        baas = list(self._baas.values())
        if org_id:
            baas = [b for b in baas if b.org_id == org_id]
        return baas

    async def check_baa_coverage(self, org_id: str) -> Dict[str, Any]:
        """Check BAA coverage status for an organization."""
        baas = await self.list_baas(org_id)
        active = [b for b in baas if b.status == "active" and b.signed]
        unsigned = [b for b in baas if not b.signed]
        expired = [b for b in baas if b.status == "expired"]

        return {
            "org_id": org_id,
            "total_baas": len(baas),
            "active_signed": len(active),
            "unsigned": len(unsigned),
            "expired": len(expired),
            "compliant": len(unsigned) == 0 and len(active) > 0,
            "associates": [b.associate_name for b in active],
        }

    async def terminate_baa(self, baa_id: str) -> None:
        """Terminate a BAA."""
        baa = self._baas.get(baa_id)
        if baa:
            baa.status = "terminated"


# ---------------------------------------------------------------------------
# HIPAA Controls
# ---------------------------------------------------------------------------

class HIPAAControls:
    """
    HIPAA compliance controls for PHI handling.

    Provides PHI scanning, access logging, encryption, minimum necessary
    rule enforcement, and BAA management.
    """

    def __init__(
        self,
        encryption_key: bytes | None = None,
        baa_tracker: BAATracker | None = None,
    ):
        self._scanner = PHIScanner()
        self._access_log: List[Dict[str, Any]] = []
        self._baa_tracker = baa_tracker or BAATracker()
        self._baa_required_orgs: Set[str] = set()

        # Encryption setup
        self._encryption_key = encryption_key or os.urandom(32)
        self._use_aes = _HAS_CRYPTOGRAPHY

    # -- PHI Scanning (delegated to PHIScanner) -----------------------------

    def scan_phi(self, text: str) -> List[PHIMatch]:
        """Scan text for PHI. Convenience wrapper around PHIScanner."""
        return self._scanner.scan(text)

    def redact_phi(self, text: str) -> Tuple[str, List[PHIMatch]]:
        """Redact PHI from text. Convenience wrapper around PHIScanner."""
        return self._scanner.redact(text)

    # -- BAA checks ---------------------------------------------------------

    async def check_baa_required(self, user_id: str, org_id: str) -> bool:
        """
        Check if a Business Associate Agreement is required.

        A BAA is required when the org handles PHI or has been flagged
        for HIPAA compliance.
        """
        if org_id in self._baa_required_orgs:
            return True
        # Check if org has active BAAs (implies HIPAA scope)
        coverage = await self._baa_tracker.check_baa_coverage(org_id)
        return coverage["total_baas"] > 0

    def set_baa_required(self, org_id: str) -> None:
        """Flag an organization as requiring BAA coverage."""
        self._baa_required_orgs.add(org_id)

    # -- PHI Access Logging -------------------------------------------------

    async def log_phi_access(
        self,
        user_id: str,
        phi_type: PHIField | str,
        purpose: str,
        resource_id: str = "",
        action: str = "read",
    ) -> None:
        """
        Log PHI access event (HIPAA §164.312(b) — audit controls).

        All PHI access must be logged with who, what, when, and why.
        """
        entry = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "phi_type": phi_type.value if isinstance(phi_type, PHIField) else phi_type,
            "purpose": purpose,
            "resource_id": resource_id,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._access_log.append(entry)

    async def get_phi_access_log(
        self,
        user_id: str | None = None,
        phi_type: str | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve PHI access log entries.

        Optionally filtered by user_id and/or phi_type.
        """
        entries = list(self._access_log)
        if user_id:
            entries = [e for e in entries if e["user_id"] == user_id]
        if phi_type:
            entries = [e for e in entries if e["phi_type"] == phi_type]
        return entries[-limit:]

    # -- PHI Encryption -----------------------------------------------------

    async def encrypt_phi(self, data: str) -> bytes:
        """
        Encrypt PHI data using AES-256-GCM.

        Falls back to XOR cipher if the cryptography library is unavailable.
        """
        plaintext = data.encode("utf-8")

        if self._use_aes:
            nonce = os.urandom(12)
            aes = AESGCM(self._encryption_key)
            ciphertext = aes.encrypt(nonce, plaintext, None)
            return nonce + ciphertext
        else:
            # XOR fallback (NOT production-grade — for testing only)
            return self._xor_encrypt(plaintext)

    async def decrypt_phi(self, ciphertext: bytes) -> str:
        """
        Decrypt PHI data.

        Uses AES-256-GCM if available, XOR fallback otherwise.
        """
        if self._use_aes:
            nonce = ciphertext[:12]
            ct = ciphertext[12:]
            aes = AESGCM(self._encryption_key)
            plaintext = aes.decrypt(nonce, ct, None)
            return plaintext.decode("utf-8")
        else:
            return self._xor_decrypt(ciphertext).decode("utf-8")

    def _xor_encrypt(self, data: bytes) -> bytes:
        """XOR-based encryption fallback (NOT secure — testing only)."""
        key = self._encryption_key
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def _xor_decrypt(self, data: bytes) -> bytes:
        """XOR-based decryption fallback."""
        return self._xor_encrypt(data)  # XOR is symmetric

    # -- Minimum Necessary Rule ---------------------------------------------

    async def minimum_necessary_check(
        self,
        data: Dict[str, Any],
        purpose: str,
    ) -> Dict[str, Any]:
        """
        Apply HIPAA minimum necessary rule (§164.502(b)).

        Returns only the data fields necessary for the stated purpose.
        Fields not required for the purpose are excluded.
        """
        # Purpose-to-fields mapping
        purpose_fields: Dict[str, Set[str]] = {
            "treatment": {
                "patient_name", "dob", "mrn", "diagnosis", "medications",
                "allergies", "vital_signs", "lab_results", "treatment_plan",
            },
            "payment": {
                "patient_name", "mrn", "insurance_id", "procedure_codes",
                "diagnosis_codes", "dates_of_service", "charges",
            },
            "operations": {
                "mrn", "department", "dates_of_service", "procedure_codes",
                "provider_id",
            },
            "research": {
                "age_range", "diagnosis_codes", "procedure_codes",
                "lab_results", "demographics_deidentified",
            },
            "audit": {
                "user_id", "action", "timestamp", "resource_id",
            },
        }

        allowed_fields = purpose_fields.get(purpose.lower(), set())

        if not allowed_fields:
            # If purpose not recognized, deny all PHI fields
            return {
                "_minimum_necessary": True,
                "_purpose": purpose,
                "_warning": "Unrecognized purpose — all PHI fields excluded",
            }

        filtered = {"_minimum_necessary": True, "_purpose": purpose}
        for key, value in data.items():
            if key.lower() in allowed_fields or key.startswith("_"):
                filtered[key] = value
            else:
                filtered[f"_{key}_excluded"] = "[EXCLUDED: minimum necessary]"

        return filtered

    # -- Reporting ----------------------------------------------------------

    async def generate_hipaa_report(self) -> Dict[str, Any]:
        """
        Generate a HIPAA compliance status report.

        Includes PHI access statistics, BAA status, encryption status,
        and compliance recommendations.
        """
        total_accesses = len(self._access_log)
        phi_types_accessed: Dict[str, int] = {}
        users_accessing_phi: Set[str] = set()

        for entry in self._access_log:
            pt = entry.get("phi_type", "unknown")
            phi_types_accessed[pt] = phi_types_accessed.get(pt, 0) + 1
            users_accessing_phi.add(entry.get("user_id", ""))

        return {
            "report_type": "HIPAA Compliance Status",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "encryption": {
                "algorithm": "AES-256-GCM" if self._use_aes else "XOR (fallback)",
                "production_ready": self._use_aes,
            },
            "phi_access": {
                "total_accesses": total_accesses,
                "unique_users": len(users_accessing_phi),
                "by_phi_type": phi_types_accessed,
            },
            "baa_status": {
                "orgs_requiring_baa": len(self._baa_required_orgs),
                "tracker_available": True,
            },
            "scanner": {
                "patterns_loaded": len(PHIScanner._PATTERNS),
                "hipaa_identifiers_covered": len(PHIField),
            },
            "recommendations": self._generate_recommendations(),
        }

    def _generate_recommendations(self) -> List[str]:
        """Generate HIPAA compliance recommendations."""
        recs: List[str] = []

        if not self._use_aes:
            recs.append(
                "CRITICAL: Install 'cryptography' package for AES-256-GCM encryption. "
                "Current XOR fallback is NOT suitable for production PHI handling."
            )

        if not self._baa_required_orgs:
            recs.append(
                "INFO: No organizations flagged as requiring BAA coverage. "
                "Ensure all HIPAA-covered entities are properly configured."
            )

        if len(self._access_log) == 0:
            recs.append(
                "INFO: No PHI access events logged. Ensure all PHI access "
                "is being routed through log_phi_access()."
            )

        recs.extend([
            "Conduct regular HIPAA risk assessments (§164.308(a)(1)(ii)(A)).",
            "Ensure workforce training on PHI handling (§164.308(a)(5)).",
            "Maintain contingency and disaster recovery plans (§164.308(a)(7)).",
            "Review and update access controls periodically (§164.312(a)(1)).",
        ])

        return recs

    @property
    def baa_tracker(self) -> BAATracker:
        """Access the BAA tracker instance."""
        return self._baa_tracker
