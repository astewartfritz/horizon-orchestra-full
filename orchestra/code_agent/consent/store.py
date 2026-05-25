"""
Consent document trail — signed BAAs, HIPAA notices, engagement letters,
financial advisory agreements, and any other consent instrument.

Every signed document is stored with:
  - Cryptographic hash of the document content (SHA-256)
  - Signer identity, timestamp, IP address, user agent
  - Version tracking for document updates
  - Revocation support

Required for:
  HIPAA: Business Associate Agreements (§164.308(b))
  Legal: Engagement letters before representation
  Finance: Investment advisory agreements, risk disclosures
  GDPR: Explicit consent records with withdrawal support
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_DB_PATH = Path.home() / ".orchestra_consent.db"
_lock = threading.Lock()

DOCUMENT_TYPES = {
    # Healthcare
    "baa":              "Business Associate Agreement (HIPAA §164.308(b))",
    "hipaa_notice":     "HIPAA Notice of Privacy Practices",
    "informed_consent": "Patient Informed Consent",
    "research_consent": "Research Participation Consent",
    # Legal
    "engagement_letter":"Attorney-Client Engagement Letter",
    "conflict_waiver":  "Conflict of Interest Waiver",
    "limited_scope":    "Limited Scope Representation Agreement",
    "fee_agreement":    "Fee Agreement",
    # Finance
    "advisory_agreement":   "Investment Advisory Agreement",
    "risk_disclosure":      "Risk Disclosure Statement",
    "margin_agreement":     "Margin Account Agreement",
    "privacy_notice":       "Gramm-Leach-Bliley Privacy Notice",
    # General
    "terms_of_service": "Terms of Service",
    "gdpr_consent":     "GDPR Data Processing Consent",
    "data_processing":  "Data Processing Agreement",
}

STATUS_ACTIVE   = "active"
STATUS_REVOKED  = "revoked"
STATUS_EXPIRED  = "expired"
STATUS_PENDING  = "pending_signature"


@dataclass
class ConsentDocument:
    id: str
    doc_type: str          # key from DOCUMENT_TYPES
    doc_version: str       # e.g. "2026-01" — bump on material change
    resource_id: str       # patient_id, client_id, account_id, user_id
    resource_type: str     # "patient" | "client" | "account" | "user"
    signer_user_id: str    # user who signed
    signer_name: str       # display name at time of signing
    signer_ip: str
    signer_ua: str         # user agent
    signed_at: float       # unix timestamp
    content_hash: str      # SHA-256 of the document content
    content_preview: str   # first 500 chars (not encrypted — not PHI)
    status: str            # active | revoked | expired | pending_signature
    revoked_at: float | None
    revoked_by: str
    revoke_reason: str
    expiry: float | None   # None = no expiry
    metadata: str          # JSON for extra fields


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consent_documents (
                id              TEXT PRIMARY KEY,
                doc_type        TEXT NOT NULL,
                doc_version     TEXT NOT NULL DEFAULT '',
                resource_id     TEXT NOT NULL DEFAULT '',
                resource_type   TEXT NOT NULL DEFAULT '',
                signer_user_id  TEXT NOT NULL,
                signer_name     TEXT NOT NULL DEFAULT '',
                signer_ip       TEXT NOT NULL DEFAULT '',
                signer_ua       TEXT NOT NULL DEFAULT '',
                signed_at       REAL NOT NULL,
                content_hash    TEXT NOT NULL,
                content_preview TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'active',
                revoked_at      REAL,
                revoked_by      TEXT NOT NULL DEFAULT '',
                revoke_reason   TEXT NOT NULL DEFAULT '',
                expiry          REAL,
                metadata        TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_consent_resource ON consent_documents(resource_id, resource_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_consent_signer   ON consent_documents(signer_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_consent_type     ON consent_documents(doc_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_consent_status   ON consent_documents(status)")


def _row(r: sqlite3.Row) -> ConsentDocument:
    return ConsentDocument(**{k: r[k] for k in ConsentDocument.__dataclass_fields__})


def record_consent(
    *,
    doc_type: str,
    doc_version: str,
    content: str,
    resource_id: str,
    resource_type: str,
    signer_user_id: str,
    signer_name: str = "",
    signer_ip: str = "",
    signer_ua: str = "",
    expiry_days: int | None = None,
    metadata: dict | None = None,
) -> ConsentDocument:
    """Record a new signed consent document."""
    now = time.time()
    doc = ConsentDocument(
        id=str(uuid.uuid4()),
        doc_type=doc_type,
        doc_version=doc_version,
        resource_id=resource_id,
        resource_type=resource_type,
        signer_user_id=signer_user_id,
        signer_name=signer_name,
        signer_ip=signer_ip,
        signer_ua=signer_ua,
        signed_at=now,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        content_preview=content[:500],
        status=STATUS_ACTIVE,
        revoked_at=None,
        revoked_by="",
        revoke_reason="",
        expiry=(now + expiry_days * 86400) if expiry_days else None,
        metadata=json.dumps(metadata or {}),
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO consent_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc.id, doc.doc_type, doc.doc_version, doc.resource_id, doc.resource_type,
             doc.signer_user_id, doc.signer_name, doc.signer_ip, doc.signer_ua,
             doc.signed_at, doc.content_hash, doc.content_preview, doc.status,
             doc.revoked_at, doc.revoked_by, doc.revoke_reason, doc.expiry, doc.metadata),
        )
    return doc


def revoke_consent(
    consent_id: str,
    revoked_by: str,
    reason: str = "",
) -> ConsentDocument | None:
    now = time.time()
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE consent_documents SET status=?, revoked_at=?, revoked_by=?, revoke_reason=? WHERE id=?",
            (STATUS_REVOKED, now, revoked_by, reason, consent_id),
        )
        row = conn.execute("SELECT * FROM consent_documents WHERE id=?", (consent_id,)).fetchone()
    return _row(row) if row else None


def get_consent(consent_id: str) -> ConsentDocument | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM consent_documents WHERE id=?", (consent_id,)).fetchone()
    return _row(row) if row else None


def list_consents(
    resource_id: str = "",
    resource_type: str = "",
    signer_user_id: str = "",
    doc_type: str = "",
    status: str = "",
    limit: int = 100,
) -> list[ConsentDocument]:
    clauses = ["1=1"]
    params: list[Any] = []
    for col, val in [("resource_id", resource_id), ("resource_type", resource_type),
                     ("signer_user_id", signer_user_id), ("doc_type", doc_type), ("status", status)]:
        if val:
            clauses.append(f"{col}=?"); params.append(val)
    params.append(limit)
    sql = f"SELECT * FROM consent_documents WHERE {' AND '.join(clauses)} ORDER BY signed_at DESC LIMIT ?"
    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rows]


def has_active_consent(resource_id: str, doc_type: str) -> bool:
    """Check if an active, non-expired consent of this type exists for the resource."""
    now = time.time()
    with _db() as conn:
        row = conn.execute(
            "SELECT id FROM consent_documents WHERE resource_id=? AND doc_type=? "
            "AND status='active' AND (expiry IS NULL OR expiry > ?)",
            (resource_id, doc_type, now),
        ).fetchone()
    return row is not None
