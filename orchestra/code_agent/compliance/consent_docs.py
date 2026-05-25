from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class ConsentDocStatus(str, enum.Enum):
    PENDING = "pending"
    SIGNED = "signed"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class ConsentDocument:
    id: str = ""
    document_type: str = ""          # "baa", "hipaa_consent", "engagement_letter", "terms_of_service"
    patient_id: str = ""             # or client_id for legal
    provider_id: str = ""            # doctor/attorney/banker identifier
    status: ConsentDocStatus = ConsentDocStatus.PENDING
    signed_at: float = 0.0
    expires_at: float = 0.0
    version: str = "1.0"
    document_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


DOCUMENT_TEMPLATES: dict[str, str] = {
    "hipaa_consent": (
        "I consent to the use and disclosure of my protected health information "
        "for treatment, payment, and healthcare operations as described in the "
        "Notice of Privacy Practices. I understand I may revoke this consent in writing."
    ),
    "baa": (
        "This Business Associate Agreement governs the use and disclosure of "
        "protected health information between the Covered Entity and the Business "
        "Associate in compliance with HIPAA regulations (45 CFR Parts 160, 164)."
    ),
    "engagement_letter": (
        "This letter confirms the engagement of professional services. "
        "The scope of representation includes the matters described herein. "
        "This engagement is governed by the terms and conditions set forth below."
    ),
    "financial_consent": (
        "I authorize the access to and processing of my financial data for "
        "the purposes of account management, transaction processing, and "
        "regulatory compliance as described in the disclosure statement."
    ),
    "terms_of_service": (
        "By using this platform, I agree to the terms and conditions outlined "
        "in this document. I acknowledge that AI-generated outputs are for "
        "informational purposes and do not constitute professional advice."
    ),
}


class ConsentDocManager:
    """Tracks signed consent documents for HIPAA, legal engagement,
    financial authorization, and general terms of service.

    Supports lifecycle: pending → signed → (revoked | expired)
    """

    def __init__(self) -> None:
        self._docs: dict[str, ConsentDocument] = {}

    def create_document(
        self, doc_type: str, patient_id: str, provider_id: str = "",
        ttl_days: int = 365,
    ) -> ConsentDocument:
        doc = ConsentDocument(
            id=str(uuid.uuid4()),
            document_type=doc_type,
            patient_id=patient_id,
            provider_id=provider_id,
            status=ConsentDocStatus.PENDING,
            expires_at=time.time() + ttl_days * 86400,
            document_text=DOCUMENT_TEMPLATES.get(doc_type, ""),
        )
        self._docs[doc.id] = doc
        return doc

    def sign(self, doc_id: str) -> bool:
        doc = self._docs.get(doc_id)
        if doc is None or doc.status != ConsentDocStatus.PENDING:
            return False
        if time.time() > doc.expires_at:
            doc.status = ConsentDocStatus.EXPIRED
            return False
        doc.status = ConsentDocStatus.SIGNED
        doc.signed_at = time.time()
        return True

    def revoke(self, doc_id: str) -> bool:
        doc = self._docs.get(doc_id)
        if doc is None or doc.status != ConsentDocStatus.SIGNED:
            return False
        doc.status = ConsentDocStatus.REVOKED
        return True

    def get(self, doc_id: str) -> ConsentDocument | None:
        doc = self._docs.get(doc_id)
        if doc is None:
            return None
        if doc.status == ConsentDocStatus.SIGNED and time.time() > doc.expires_at:
            doc.status = ConsentDocStatus.EXPIRED
        return doc

    def list_by_patient(self, patient_id: str) -> list[ConsentDocument]:
        return [d for d in self._docs.values() if d.patient_id == patient_id]

    def list_by_type(self, doc_type: str) -> list[ConsentDocument]:
        return [d for d in self._docs.values() if d.document_type == doc_type]

    def has_valid_consent(self, patient_id: str, doc_type: str) -> bool:
        for doc in self._docs.values():
            if (doc.patient_id == patient_id and doc.document_type == doc_type
                    and doc.status == ConsentDocStatus.SIGNED
                    and time.time() <= doc.expires_at):
                return True
        return False

    def get_patient_doc(self, patient_id: str, doc_type: str) -> ConsentDocument | None:
        for doc in self._docs.values():
            if (doc.patient_id == patient_id and doc.document_type == doc_type):
                return doc
        return None
