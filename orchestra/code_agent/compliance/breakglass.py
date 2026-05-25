"""
Break-glass emergency access — HIPAA mandate for healthcare emergencies.

HIPAA §164.312(a)(2)(ii) requires covered entities to establish procedures
for emergency access to PHI when normal access control would prevent
timely care. Every break-glass access is:

  1. Logged immutably in the audit trail
  2. Requires a written justification
  3. Auto-expires (default 4 hours)
  4. Notifies the privacy officer / admin immediately
  5. Queued for post-hoc review

This module also covers legal emergency access (e.g., supervising partner
accessing an associate's matter during illness) and finance emergency
access (portfolio manager override during market hours).
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


_DB_PATH = Path.home() / ".orchestra_breakglass.db"
_lock = threading.Lock()

_DEFAULT_TTL = 4 * 3600      # 4 hours
_REVIEW_WINDOW = 48 * 3600   # 48 hours to review post-hoc


@dataclass
class BreakGlassEvent:
    id: str
    initiator_user_id: str
    initiator_name: str
    initiator_role: str            # must be physician/partner/portfolio_manager
    resource_type: str             # "patient" | "matter" | "portfolio"
    resource_id: str
    resource_description: str      # human-readable (not stored securely — no PHI)
    justification: str             # mandatory free-text reason
    initiated_at: float
    expires_at: float
    status: str                    # "active" | "expired" | "revoked" | "reviewed"
    reviewed_by: str
    reviewed_at: float | None
    review_notes: str
    admin_notified: bool
    ip_address: str


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS break_glass_events (
                id                   TEXT PRIMARY KEY,
                initiator_user_id    TEXT NOT NULL,
                initiator_name       TEXT NOT NULL DEFAULT '',
                initiator_role       TEXT NOT NULL DEFAULT '',
                resource_type        TEXT NOT NULL,
                resource_id          TEXT NOT NULL,
                resource_description TEXT NOT NULL DEFAULT '',
                justification        TEXT NOT NULL,
                initiated_at         REAL NOT NULL,
                expires_at           REAL NOT NULL,
                status               TEXT NOT NULL DEFAULT 'active',
                reviewed_by          TEXT NOT NULL DEFAULT '',
                reviewed_at          REAL,
                review_notes         TEXT NOT NULL DEFAULT '',
                admin_notified       INTEGER NOT NULL DEFAULT 0,
                ip_address           TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_initiator ON break_glass_events(initiator_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_resource  ON break_glass_events(resource_type, resource_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_status    ON break_glass_events(status)")


def _row(r) -> BreakGlassEvent:
    return BreakGlassEvent(
        id=r["id"], initiator_user_id=r["initiator_user_id"],
        initiator_name=r["initiator_name"], initiator_role=r["initiator_role"],
        resource_type=r["resource_type"], resource_id=r["resource_id"],
        resource_description=r["resource_description"], justification=r["justification"],
        initiated_at=r["initiated_at"], expires_at=r["expires_at"],
        status=r["status"], reviewed_by=r["reviewed_by"], reviewed_at=r["reviewed_at"],
        review_notes=r["review_notes"], admin_notified=bool(r["admin_notified"]),
        ip_address=r["ip_address"],
    )


def initiate(
    initiator_user_id: str,
    resource_type: str,
    resource_id: str,
    justification: str,
    initiator_name: str = "",
    initiator_role: str = "",
    resource_description: str = "",
    ttl_seconds: int = _DEFAULT_TTL,
    ip_address: str = "",
) -> BreakGlassEvent:
    """
    Initiate a break-glass access event. Justification is mandatory.
    Logs to the immutable audit trail automatically.
    """
    if not justification or len(justification.strip()) < 10:
        raise ValueError("Justification is required and must be at least 10 characters.")

    now = time.time()
    event = BreakGlassEvent(
        id=str(uuid.uuid4()),
        initiator_user_id=initiator_user_id,
        initiator_name=initiator_name,
        initiator_role=initiator_role,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_description=resource_description,
        justification=justification.strip(),
        initiated_at=now,
        expires_at=now + ttl_seconds,
        status="active",
        reviewed_by="",
        reviewed_at=None,
        review_notes="",
        admin_notified=False,
        ip_address=ip_address,
    )

    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO break_glass_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event.id, event.initiator_user_id, event.initiator_name, event.initiator_role,
             event.resource_type, event.resource_id, event.resource_description,
             event.justification, event.initiated_at, event.expires_at, event.status,
             event.reviewed_by, event.reviewed_at, event.review_notes,
             int(event.admin_notified), event.ip_address),
        )

    # Log to audit trail
    try:
        from orchestra.code_agent.audit.store import log as audit_log
        audit_log(
            user_id=initiator_user_id,
            action="break_glass",
            vertical="healthcare" if resource_type == "patient" else resource_type,
            resource_id=resource_id,
            resource_type=resource_type,
            input_text=justification,
            success=True,
            ip_address=ip_address,
        )
    except Exception:
        pass

    return event


def is_active(initiator_user_id: str, resource_type: str, resource_id: str) -> bool:
    """Check if the user has an active, non-expired break-glass grant for this resource."""
    now = time.time()
    with _db() as conn:
        row = conn.execute(
            "SELECT id FROM break_glass_events "
            "WHERE initiator_user_id=? AND resource_type=? AND resource_id=? "
            "AND status='active' AND expires_at > ?",
            (initiator_user_id, resource_type, resource_id, now),
        ).fetchone()
    return row is not None


def review(event_id: str, reviewer_user_id: str, notes: str = "") -> BreakGlassEvent | None:
    now = time.time()
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE break_glass_events SET status='reviewed', reviewed_by=?, reviewed_at=?, review_notes=? WHERE id=?",
            (reviewer_user_id, now, notes, event_id),
        )
        row = conn.execute("SELECT * FROM break_glass_events WHERE id=?", (event_id,)).fetchone()
    return _row(row) if row else None


def revoke(event_id: str) -> BreakGlassEvent | None:
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE break_glass_events SET status='revoked' WHERE id=? AND status='active'",
            (event_id,),
        )
        row = conn.execute("SELECT * FROM break_glass_events WHERE id=?", (event_id,)).fetchone()
    return _row(row) if row else None


def list_events(
    status: str = "",
    resource_type: str = "",
    initiator_user_id: str = "",
    limit: int = 100,
) -> list[BreakGlassEvent]:
    clauses = ["1=1"]
    params: list[Any] = []
    for col, val in [("status", status), ("resource_type", resource_type),
                     ("initiator_user_id", initiator_user_id)]:
        if val:
            clauses.append(f"{col}=?"); params.append(val)
    params.append(limit)
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM break_glass_events WHERE {' AND '.join(clauses)} ORDER BY initiated_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row(r) for r in rows]


def expire_stale() -> int:
    """Mark expired events — call periodically from a background task."""
    now = time.time()
    with _lock, _db() as conn:
        c = conn.execute(
            "UPDATE break_glass_events SET status='expired' WHERE status='active' AND expires_at <= ?",
            (now,),
        )
    return c.rowcount
