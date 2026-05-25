"""
Data lifecycle management — retention policies, scheduled deletion,
legal holds, and court-ordered preservation.

Regulatory retention requirements:
  HIPAA medical records:   6 years from creation (45 CFR §164.530(j))
  SOX financial records:   7 years
  GDPR:                    Erasure within 30 days of request
  Legal files:             Varies by jurisdiction (typically 7-10 years)
  SEC books & records:     3-6 years depending on record type (17 CFR §240.17a-4)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_DB_PATH = Path.home() / ".orchestra_lifecycle.db"
_lock = threading.Lock()


# ── Retention policies ───────────────────────────────────────────────────────

@dataclass
class RetentionPolicy:
    resource_type: str   # "patient" | "matter" | "portfolio" | "session" | "audit_log"
    retain_years: float  # minimum retention period
    regulation: str      # "HIPAA" | "SOX" | "GDPR" | "SEC" | "custom"
    deletion_method: str # "hard_delete" | "anonymize" | "archive"
    description: str


DEFAULT_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy("patient",    6.0,  "HIPAA",  "hard_delete", "Medical records — 45 CFR §164.530(j)"),
    RetentionPolicy("encounter",  6.0,  "HIPAA",  "hard_delete", "Clinical encounter notes"),
    RetentionPolicy("claim",      6.0,  "HIPAA",  "hard_delete", "Healthcare claims"),
    RetentionPolicy("matter",     7.0,  "SOX",    "archive",     "Legal matter files"),
    RetentionPolicy("invoice",    7.0,  "SOX",    "archive",     "Legal invoices — financial record"),
    RetentionPolicy("portfolio",  6.0,  "SEC",    "archive",     "Investment records — 17 CFR §240.17a-4"),
    RetentionPolicy("transaction",7.0,  "SOX",    "archive",     "Financial transactions"),
    RetentionPolicy("audit_log",  7.0,  "SOX",    "archive",     "Audit trail — never delete, archive only"),
    RetentionPolicy("session",    0.25, "custom", "hard_delete", "Auth sessions — 90-day retention"),
    RetentionPolicy("consent",    7.0,  "HIPAA",  "archive",     "Consent documents — HIPAA & GDPR"),
]

_POLICY_MAP: dict[str, RetentionPolicy] = {p.resource_type: p for p in DEFAULT_POLICIES}


# ── Legal holds ───────────────────────────────────────────────────────────────

@dataclass
class LegalHold:
    id: str
    resource_type: str
    resource_id: str           # specific record, or "*" for all of resource_type
    hold_reason: str           # e.g. "Litigation Matter #2024-CV-001" or "SEC Investigation"
    held_by: str               # user_id or external reference (court name)
    held_by_name: str
    hold_date: float
    release_date: float | None
    status: str                # "active" | "released"
    metadata: str              # JSON


@dataclass
class DeletionRequest:
    id: str
    resource_type: str
    resource_id: str
    requester_user_id: str
    request_type: str          # "gdpr_erasure" | "retention_expiry" | "manual"
    requested_at: float
    scheduled_for: float       # when deletion should execute
    status: str                # "pending" | "blocked_by_hold" | "completed" | "cancelled"
    hold_id: str               # if blocked
    completed_at: float | None
    deletion_method: str
    notes: str


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS legal_holds (
                id             TEXT PRIMARY KEY,
                resource_type  TEXT NOT NULL,
                resource_id    TEXT NOT NULL,
                hold_reason    TEXT NOT NULL,
                held_by        TEXT NOT NULL DEFAULT '',
                held_by_name   TEXT NOT NULL DEFAULT '',
                hold_date      REAL NOT NULL,
                release_date   REAL,
                status         TEXT NOT NULL DEFAULT 'active',
                metadata       TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_hold_resource ON legal_holds(resource_type, resource_id);
            CREATE INDEX IF NOT EXISTS idx_hold_status   ON legal_holds(status);

            CREATE TABLE IF NOT EXISTS deletion_requests (
                id                  TEXT PRIMARY KEY,
                resource_type       TEXT NOT NULL,
                resource_id         TEXT NOT NULL,
                requester_user_id   TEXT NOT NULL,
                request_type        TEXT NOT NULL,
                requested_at        REAL NOT NULL,
                scheduled_for       REAL NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending',
                hold_id             TEXT NOT NULL DEFAULT '',
                completed_at        REAL,
                deletion_method     TEXT NOT NULL DEFAULT 'hard_delete',
                notes               TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_del_status   ON deletion_requests(status);
            CREATE INDEX IF NOT EXISTS idx_del_resource ON deletion_requests(resource_type, resource_id);
        """)


def _hold_row(r) -> LegalHold:
    return LegalHold(
        id=r["id"], resource_type=r["resource_type"], resource_id=r["resource_id"],
        hold_reason=r["hold_reason"], held_by=r["held_by"], held_by_name=r["held_by_name"],
        hold_date=r["hold_date"], release_date=r["release_date"], status=r["status"],
        metadata=r["metadata"],
    )


def _del_row(r) -> DeletionRequest:
    return DeletionRequest(
        id=r["id"], resource_type=r["resource_type"], resource_id=r["resource_id"],
        requester_user_id=r["requester_user_id"], request_type=r["request_type"],
        requested_at=r["requested_at"], scheduled_for=r["scheduled_for"],
        status=r["status"], hold_id=r["hold_id"], completed_at=r["completed_at"],
        deletion_method=r["deletion_method"], notes=r["notes"],
    )


# ── Legal hold operations ────────────────────────────────────────────────────

def place_hold(
    resource_type: str,
    resource_id: str,
    hold_reason: str,
    held_by: str = "",
    held_by_name: str = "",
    metadata: dict | None = None,
) -> LegalHold:
    hold = LegalHold(
        id=str(uuid.uuid4()),
        resource_type=resource_type,
        resource_id=resource_id,
        hold_reason=hold_reason,
        held_by=held_by,
        held_by_name=held_by_name,
        hold_date=time.time(),
        release_date=None,
        status="active",
        metadata=json.dumps(metadata or {}),
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO legal_holds VALUES (?,?,?,?,?,?,?,?,?,?)",
            (hold.id, hold.resource_type, hold.resource_id, hold.hold_reason,
             hold.held_by, hold.held_by_name, hold.hold_date, hold.release_date,
             hold.status, hold.metadata),
        )
        # Block any pending deletions for this resource
        conn.execute(
            "UPDATE deletion_requests SET status='blocked_by_hold', hold_id=? "
            "WHERE resource_type=? AND resource_id=? AND status='pending'",
            (hold.id, resource_type, resource_id),
        )
    return hold


def release_hold(hold_id: str) -> LegalHold | None:
    now = time.time()
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE legal_holds SET status='released', release_date=? WHERE id=?",
            (now, hold_id),
        )
        row = conn.execute("SELECT * FROM legal_holds WHERE id=?", (hold_id,)).fetchone()
        if row:
            # Unblock deletion requests that were blocked by this hold only
            conn.execute(
                "UPDATE deletion_requests SET status='pending', hold_id='' "
                "WHERE hold_id=? AND status='blocked_by_hold'",
                (hold_id,),
            )
    return _hold_row(row) if row else None


def is_on_hold(resource_type: str, resource_id: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT id FROM legal_holds WHERE resource_type=? AND (resource_id=? OR resource_id='*') "
            "AND status='active'",
            (resource_type, resource_id),
        ).fetchone()
    return row is not None


def list_holds(status: str = "active", resource_type: str = "") -> list[LegalHold]:
    clauses = ["1=1"]
    params: list[Any] = []
    if status:
        clauses.append("status=?"); params.append(status)
    if resource_type:
        clauses.append("resource_type=?"); params.append(resource_type)
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM legal_holds WHERE {' AND '.join(clauses)} ORDER BY hold_date DESC",
            params,
        ).fetchall()
    return [_hold_row(r) for r in rows]


# ── Deletion requests ────────────────────────────────────────────────────────

def request_deletion(
    resource_type: str,
    resource_id: str,
    requester_user_id: str,
    request_type: str = "gdpr_erasure",
    delay_days: int = 30,
    notes: str = "",
) -> DeletionRequest:
    """
    Request deletion of a resource. Automatically blocked if a legal hold exists.
    GDPR erasure requests are scheduled 30 days out by default.
    """
    now = time.time()
    policy = _POLICY_MAP.get(resource_type)
    deletion_method = policy.deletion_method if policy else "hard_delete"
    on_hold = is_on_hold(resource_type, resource_id)
    status = "blocked_by_hold" if on_hold else "pending"

    req = DeletionRequest(
        id=str(uuid.uuid4()),
        resource_type=resource_type,
        resource_id=resource_id,
        requester_user_id=requester_user_id,
        request_type=request_type,
        requested_at=now,
        scheduled_for=now + delay_days * 86400,
        status=status,
        hold_id="",
        completed_at=None,
        deletion_method=deletion_method,
        notes=notes,
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO deletion_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (req.id, req.resource_type, req.resource_id, req.requester_user_id,
             req.request_type, req.requested_at, req.scheduled_for, req.status,
             req.hold_id, req.completed_at, req.deletion_method, req.notes),
        )
    return req


def get_retention_schedule(resource_type: str) -> dict:
    policy = _POLICY_MAP.get(resource_type)
    if not policy:
        return {"resource_type": resource_type, "policy": "none", "retain_years": None}
    return {
        "resource_type": resource_type,
        "retain_years": policy.retain_years,
        "regulation": policy.regulation,
        "deletion_method": policy.deletion_method,
        "description": policy.description,
        "expiry_after_creation": f"{policy.retain_years} years",
    }


def list_policies() -> list[dict]:
    return [asdict(p) for p in DEFAULT_POLICIES]


def list_deletion_requests(status: str = "", resource_type: str = "") -> list[DeletionRequest]:
    clauses = ["1=1"]
    params: list[Any] = []
    if status:
        clauses.append("status=?"); params.append(status)
    if resource_type:
        clauses.append("resource_type=?"); params.append(resource_type)
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM deletion_requests WHERE {' AND '.join(clauses)} ORDER BY requested_at DESC",
            params,
        ).fetchall()
    return [_del_row(r) for r in rows]
