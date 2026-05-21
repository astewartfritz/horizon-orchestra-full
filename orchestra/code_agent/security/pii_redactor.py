from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "PIICategory",
    "PIIType",
    "PIIRedactor",
    "HIPAAContext",
    "GDPRContext",
]

_BIRTH_DEATH_WORDS = r"\b(born|birth|dob|date\s*of\s*birth|died|death|deceased|age|aged)\b"
_ADDRESS_KEYWORDS = r"(street|st\.|avenue|ave\.|road|rd\.|lane|ln\.|drive|dr\.|blvd|boulevard|way|court|ct\.|place|pl\.|circle|cir\.|highway|hwy|suite|ste\.|apt|apartment|floor|p\.?\s*o\.?\s*box|box)"
_NAME_CONTEXT = r"((?:[Mm]y|[Yy]our|[Hh]is|[Hh]er|[Oo]ur|[Tt]heir|[Cc]all|[Nn]ame|[Cc]alled|[Nn]amed|[Kk]nown as|[Pp]atient|[Dd]octor|[Dd]r\.|[Mm]r\.|[Mm]rs\.|[Mm]s\.)\s+)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
_DATE_PATTERNS = (
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|\b" + _BIRTH_DEATH_WORDS + r"\s*:?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4}"
)
_MRN_PATTERNS = (
    r"\bMRN[-: ]?\d{4,10}\b"
    r"|\b\d{4,10}\b(?=\s*[\[\(]?MRN[\]\)]?)"
    r"|\bmedical\s*record\s*(?:number|#)?\s*:?\s*\d{4,10}\b"
)
_PASSPORT_PATTERNS = (
    r"\b[A-Z]{1,2}\d{6,9}\b"
    r"|\bpassport\s*(?:number|#|no|no\.)?\s*:?\s*[A-Z0-9]{5,14}\b"
)
_BANK_ACCT_CONTEXT = r"(account|acct|bank|routing|ach|wire)\s*(?:number|#|no\.?)?\s*:?\s*\b\d{8,17}\b"


class PIICategory(Enum):
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    ADDRESS = "address"
    NAME = "name"
    DOB = "dob"
    IP_ADDRESS = "ip_address"
    MEDICAL_RECORD = "medical_record"
    LICENSE_PLATE = "license_plate"
    BANK_ACCOUNT = "bank_account"
    PASSPORT = "passport"
    API_KEY = "api_key"
    GENERIC_PII = "generic_pii"


@dataclass
class PIIType:
    category: PIICategory
    pattern: str
    replacement: str
    risk_level: int


# ---------------------------------------------------------------------------
# Luhn check
# ---------------------------------------------------------------------------

def _luhn_checksum(card_number: str) -> bool:
    digits = [int(ch) for ch in card_number if ch.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        n = d * 2 if i % 2 == 1 else d
        checksum += n - 9 if n > 9 else n
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# Built-in PIIType definitions
# ---------------------------------------------------------------------------

_PII_TYPES: list[PIIType] = [
    PIIType(
        category=PIICategory.SSN,
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        replacement="[SSN REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.CREDIT_CARD,
        pattern=r"\b(?:\d[ -]*?){13,19}\b",
        replacement="[CC REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.MEDICAL_RECORD,
        pattern=r"(?i)" + _MRN_PATTERNS,
        replacement="[MRN REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.PASSPORT,
        pattern=r"(?i)" + _PASSPORT_PATTERNS,
        replacement="[PASSPORT REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.BANK_ACCOUNT,
        pattern=r"(?i)" + _BANK_ACCT_CONTEXT,
        replacement="[BANK ACCT REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.API_KEY,
        pattern=(
            r"(?i)sk-[a-zA-Z0-9_-]{8,}"
            r"|"
            r"api[-_]?key[-_]?['\"]?=?\s*['\"]?[a-zA-Z0-9_\-]{16,64}['\"]?"
        ),
        replacement="[API KEY REDACTED]",
        risk_level=5,
    ),
    PIIType(
        category=PIICategory.ADDRESS,
        pattern=(
            r"(?i)\b\d{1,5}\s+"
            r"(?:[A-Za-z]+\.?\s*)+"
            rf"{_ADDRESS_KEYWORDS}"
        ),
        replacement="[ADDRESS REDACTED]",
        risk_level=4,
    ),
    PIIType(
        category=PIICategory.DOB,
        pattern=r"(?i)" + _DATE_PATTERNS,
        replacement="[DOB REDACTED]",
        risk_level=4,
    ),
    PIIType(
        category=PIICategory.IP_ADDRESS,
        pattern=(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
            r"|"
            r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
        ),
        replacement="[IP REDACTED]",
        risk_level=2,
    ),
    PIIType(
        category=PIICategory.EMAIL,
        pattern=r"[\w.+-]+@[\w-]+\.[\w.-]+",
        replacement="[EMAIL REDACTED]",
        risk_level=3,
    ),
    PIIType(
        category=PIICategory.PHONE,
        pattern=r"\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}",
        replacement="[PHONE REDACTED]",
        risk_level=3,
    ),
    PIIType(
        category=PIICategory.NAME,
        pattern=_NAME_CONTEXT,
        replacement="[NAME REDACTED]",
        risk_level=3,
    ),
    PIIType(
        category=PIICategory.GENERIC_PII,
        pattern=(
            r"(?i)"
            r"\b(?:"
            r"mother[''']s\s+maiden\s+name"
            r"|social\s+security"
            r"|driver[''']s\s+license"
            r"|national\s+id(?:entity)?"
            r"|tax\s+id(?:entification)?"
            r"|employee\s+id"
            r"|student\s+id"
            r")\b\s*:?\s*['\"]?[A-Za-z0-9_\-]{4,}['\"]?"
        ),
        replacement="[GENERIC PII REDACTED]",
        risk_level=3,
    ),
    PIIType(
        category=PIICategory.LICENSE_PLATE,
        pattern=(
            r"(?i)"
            r"\b[A-Z]{1,3}\d{1,4}[A-Z]{0,2}\b"
            r"|"
            r"\b\d{1,4}[A-Z]{1,3}\d{1,4}\b"
        ),
        replacement="[LICENSE PLATE REDACTED]",
        risk_level=2,
    ),
]


# ---------------------------------------------------------------------------
# PIIRedactor
# ---------------------------------------------------------------------------

class PIIRedactor:
    """Redacts personally identifiable information from text, dicts, and JSON."""

    def __init__(self, categories: list[PIICategory] | None = None) -> None:
        self._types = [
            pt for pt in _PII_TYPES
            if categories is None or pt.category in categories
        ]
        self._compiled: list[tuple[PIICategory, re.Pattern, str, int]] = [
            (pt.category, re.compile(pt.pattern), pt.replacement, pt.risk_level)
            for pt in self._types
        ]
        self._stats: dict[str, int] = {cat.value: 0 for cat in PIICategory}
        self._stats["total"] = 0

    def redact(self, text: str, mask_char: str = "*", show_first: int = 0) -> str:
        result = text
        for category, pattern, replacement, _risk in self._compiled:
            def _replacer(m: re.Match, cat=category, repl=replacement) -> str:
                matched = m.group()
                if cat == PIICategory.CREDIT_CARD:
                    cleaned = "".join(ch for ch in matched if ch.isdigit())
                    if not _luhn_checksum(cleaned):
                        return matched
                self._stats[cat.value] += 1
                self._stats["total"] += 1

                if show_first > 0 and len(matched) > show_first:
                    prefix = matched[:show_first]
                    masked = mask_char * (len(matched) - show_first)
                    return prefix + masked
                if mask_char != "*":
                    return mask_char * len(matched)
                return repl

            result = pattern.sub(_replacer, result)
        return result

    def redact_dict(self, data: dict, path: str = "") -> dict:
        result: dict = {}
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, str):
                result[key] = self.redact(value)
            elif isinstance(value, dict):
                result[key] = self.redact_dict(value, path=current_path)
            elif isinstance(value, list):
                result[key] = [
                    self.redact_dict(item, path=current_path)
                    if isinstance(item, dict)
                    else self.redact(item)
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def redact_json(self, json_str: str) -> str:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return self.redact(json_str)

        if isinstance(data, dict):
            redacted = self.redact_dict(data)
        elif isinstance(data, list):
            redacted = [
                self.redact_dict(item) if isinstance(item, dict)
                else self.redact(item) if isinstance(item, str)
                else item
                for item in data
            ]
        else:
            redacted = self.redact(str(data))
        return json.dumps(redacted, indent=2, ensure_ascii=False)

    def find_pii(self, text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_spans: set[tuple[int, int]] = set()

        for category, pattern, _replacement, _risk in self._compiled:
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                overlapped = any(
                    s <= start < e or s < end <= e
                    for s, e in seen_spans
                )
                if overlapped:
                    continue
                if category == PIICategory.CREDIT_CARD:
                    cleaned = "".join(ch for ch in match.group() if ch.isdigit())
                    if not _luhn_checksum(cleaned):
                        continue
                seen_spans.add((start, end))
                preview = match.group()[:60]
                if len(match.group()) > 60:
                    preview += "..."
                results.append({
                    "category": category.value,
                    "start": start,
                    "end": end,
                    "text_preview": preview,
                })
        results.sort(key=lambda r: r["start"])
        return results

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)


# ---------------------------------------------------------------------------
# HIPAA 18 identifiers
# ---------------------------------------------------------------------------

_HIPAA_FIELD_NAMES: frozenset = frozenset([
    "name", "names", "patient_name", "patientname", "full_name", "fullname",
    "address", "street", "city", "state", "zip", "zipcode", "postal_code",
    "date", "dates", "dob", "date_of_birth", "birth_date", "birthdate",
    "admission_date", "discharge_date", "death_date", "age_over_90",
    "phone", "telephone", "phone_number", "telephone_number", "fax", "fax_number",
    "email", "email_address", "e_mail",
    "ssn", "social_security", "social_security_number",
    "mrn", "medical_record_number", "medical_record", "record_number",
    "health_plan", "health_plan_number", "health_plan_id", "insurance_id",
    "account_number", "account", "acct",
    "certificate_number", "certificate", "license_number",
    "vin", "vehicle_id", "vehicle_identification",
    "device_id", "device_identifier", "serial_number",
    "url", "uri", "website", "web_url",
    "ip", "ip_address", "ipv4", "ipv6",
    "biometric", "biometric_id", "fingerprint", "facial_scan", "retina_scan",
    "photo", "photograph", "image", "picture",
    "id_code", "unique_id", "unique_code", "identifier", "patient_id",
])


class HIPAAContext:
    """HIPAA compliance context for redacting Protected Health Information (PHI).

    Covers all 18 HIPAA identifiers as defined by the Privacy Rule.
    """

    HIPAA_18_IDENTIFIERS: list[str] = [
        "Names",
        "Geographic subdivisions (address, ZIP, etc.)",
        "Dates (except year)",
        "Telephone numbers",
        "Fax numbers",
        "Email addresses",
        "Social Security numbers",
        "Medical record numbers",
        "Health plan beneficiary numbers",
        "Account numbers",
        "Certificate/license numbers",
        "Vehicle identifiers (VIN)",
        "Device identifiers/serial numbers",
        "Web URLs",
        "IP addresses",
        "Biometric identifiers",
        "Full-face photographs",
        "Any other unique identifying number/code",
    ]

    def __init__(self) -> None:
        self._redactor = PIIRedactor()
        # Extra patterns for HIPAA-specific identifiers not covered by PIIType
        self._hipaa_extra: list[tuple[re.Pattern, str]] = [
            (re.compile(r"(?i)health\s*plan\s*(?:beneficiary\s*)?(?:number|id|#)?\s*:?\s*\S{4,30}"), "[HEALTH PLAN ID REDACTED]"),
            (re.compile(r"\bVIN[-: ]?[A-HJ-NPR-Z0-9]{11,17}\b"), "[VIN REDACTED]"),
            (re.compile(r"(?i)certificate\s*(?:number|#)?\s*:?\s*\d{6,20}"), "[CERTIFICATE REDACTED]"),
            (re.compile(r"(?i)(?:device\s*(?:id|identifier|serial|number)|serial\s*#?)\s*:?\s*[A-Za-z0-9\-]{6,30}"), "[DEVICE ID REDACTED]"),
            (re.compile(r"(?i)(?:biometric|fingerprint|retina|facial)\s*(?:id|identifier|scan|template)?\s*:?\s*\S{4,}"), "[BIOMETRIC REDACTED]"),
            (re.compile(r"(?i)full.?face|face.?photo|facial.?photo|patient.?photo"), "[PHOTO REDACTED]"),
        ]

    def redact_phi(self, text: str) -> str:
        result = self._redactor.redact(text)
        for pattern, replacement in self._hipaa_extra:
            result = pattern.sub(replacement, result)
        return result

    @staticmethod
    def is_phi_field(field_name: str) -> bool:
        normalised = field_name.strip().lower().replace("-", "_").replace(" ", "_")
        return normalised in _HIPAA_FIELD_NAMES


# ---------------------------------------------------------------------------
# GDPRContext
# ---------------------------------------------------------------------------

class GDPRContext:
    """GDPR compliance context for redacting PII with audit logging."""

    def __init__(self, audit_logger: Any | None = None) -> None:
        self._redactor = PIIRedactor()
        self._audit_logger = audit_logger

    def redact_pii(self, text: str) -> str:
        result = self._redactor.redact(text)
        stats = self._redactor.get_stats()
        if stats.get("total", 0) > 0:
            logger.info(
                "GDPR redaction applied: %d PII instances removed (%s)",
                stats["total"],
                ", ".join(f"{k}={v}" for k, v in stats.items() if v > 0 and k != "total"),
            )
            if self._audit_logger is not None:
                try:
                    self._audit_logger.log(
                        event_type="data_access",
                        user_id=None,
                        action="gdpr_pii_redaction",
                        details={"redacted_count": stats["total"], "categories": stats},
                        severity="low",
                    )
                except Exception:
                    logger.warning("GDPR audit log failed", exc_info=True)
        return result
