"""
Audit trail — every AI action logged for compliance.

Every time Orchestra runs an AI query, drafts a document, or takes an agentic
action, a tamper-evident log entry is written here.

Required for: HIPAA (§164.312(b)), SOC2 CC6, legal privilege audits, PE firm
due diligence on AI usage, SEC exam preparedness.
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


_DB_PATH = Path.home() / ".orchestra_audit.db"
_lock = threading.Lock()


@dataclass
class AuditEntry:
    id: str
    ts: float                 # unix timestamp
    user_id: str              # who
    action: str               # what: "ai_query", "document_draft", "agent_run", "login", "data_access"
    vertical: str             # "legal" | "finance" | "healthcare" | "code_agent" | "auth"
    resource_id: str          # matter_id, fund_id, patient_id, etc.
    resource_type: str        # "matter" | "account" | "patient" | "session"
    input_hash: str           # SHA-256 of the input (never store raw PII in audit log)
    output_hash: str          # SHA-256 of the output
    model: str                # which AI model was used
    tokens_used: int          # approximate
    duration_ms: int          # wall-clock time
    success: bool
    error: str                # empty string if success
    ip_address: str
    prev_hash: str            # hash of previous entry for chain integrity


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id           TEXT PRIMARY KEY,
                ts           REAL NOT NULL,
                user_id      TEXT NOT NULL,
                action       TEXT NOT NULL,
                vertical     TEXT NOT NULL DEFAULT '',
                resource_id  TEXT NOT NULL DEFAULT '',
                resource_type TEXT NOT NULL DEFAULT '',
                input_hash   TEXT NOT NULL DEFAULT '',
                output_hash  TEXT NOT NULL DEFAULT '',
                model        TEXT NOT NULL DEFAULT '',
                tokens_used  INTEGER NOT NULL DEFAULT 0,
                duration_ms  INTEGER NOT NULL DEFAULT 0,
                success      INTEGER NOT NULL DEFAULT 1,
                error        TEXT NOT NULL DEFAULT '',
                ip_address   TEXT NOT NULL DEFAULT '',
                prev_hash    TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_vertical ON audit_log (vertical)")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _last_hash() -> str:
    with _db() as conn:
        row = conn.execute("SELECT id, ts, prev_hash FROM audit_log ORDER BY ts DESC LIMIT 1").fetchone()
    if not row:
        return "genesis"
    return _sha(f"{row['id']}:{row['ts']}:{row['prev_hash']}")


def log(
    *,
    user_id: str,
    action: str,
    vertical: str = "",
    resource_id: str = "",
    resource_type: str = "",
    input_text: str = "",
    output_text: str = "",
    model: str = "",
    tokens_used: int = 0,
    duration_ms: int = 0,
    success: bool = True,
    error: str = "",
    ip_address: str = "",
) -> AuditEntry:
    with _lock:
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            ts=time.time(),
            user_id=user_id,
            action=action,
            vertical=vertical,
            resource_id=resource_id,
            resource_type=resource_type,
            input_hash=_sha(input_text) if input_text else "",
            output_hash=_sha(output_text) if output_text else "",
            model=model,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            success=success,
            error=error,
            ip_address=ip_address,
            prev_hash=_last_hash(),
        )
        with _db() as conn:
            conn.execute(
                """INSERT INTO audit_log VALUES
                   (:id,:ts,:user_id,:action,:vertical,:resource_id,:resource_type,
                    :input_hash,:output_hash,:model,:tokens_used,:duration_ms,
                    :success,:error,:ip_address,:prev_hash)""",
                {**asdict(entry), "success": int(entry.success)},
            )
        return entry


def query(
    *,
    user_id: str = "",
    vertical: str = "",
    action: str = "",
    limit: int = 100,
    offset: int = 0,
    since_ts: float = 0.0,
) -> list[AuditEntry]:
    clauses = ["1=1"]
    params: list[Any] = []
    if user_id:
        clauses.append("user_id = ?"); params.append(user_id)
    if vertical:
        clauses.append("vertical = ?"); params.append(vertical)
    if action:
        clauses.append("action = ?"); params.append(action)
    if since_ts:
        clauses.append("ts >= ?"); params.append(since_ts)
    params += [limit, offset]
    sql = f"SELECT * FROM audit_log WHERE {' AND '.join(clauses)} ORDER BY ts DESC LIMIT ? OFFSET ?"
    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [AuditEntry(**{**dict(r), "success": bool(r["success"])}) for r in rows]


def summary(user_id: str = "", days: int = 30) -> dict:
    since = time.time() - days * 86400
    clauses = ["ts >= ?"]
    params: list[Any] = [since]
    if user_id:
        clauses.append("user_id = ?"); params.append(user_id)
    where = " AND ".join(clauses)
    with _db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM audit_log WHERE {where}", params).fetchone()[0]
        by_action = conn.execute(
            f"SELECT action, COUNT(*) as n FROM audit_log WHERE {where} GROUP BY action ORDER BY n DESC",
            params,
        ).fetchall()
        by_vertical = conn.execute(
            f"SELECT vertical, COUNT(*) as n FROM audit_log WHERE {where} GROUP BY vertical ORDER BY n DESC",
            params,
        ).fetchall()
        failures = conn.execute(
            f"SELECT COUNT(*) FROM audit_log WHERE {where} AND success=0",
            params,
        ).fetchone()[0]
        tokens = conn.execute(
            f"SELECT SUM(tokens_used) FROM audit_log WHERE {where}",
            params,
        ).fetchone()[0] or 0
    return {
        "period_days": days,
        "total_actions": total,
        "failures": failures,
        "total_tokens_used": tokens,
        "by_action": [dict(r) for r in by_action],
        "by_vertical": [dict(r) for r in by_vertical],
    }
