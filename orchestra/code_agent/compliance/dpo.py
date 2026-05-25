"""
GDPR Article 37-39 — Data Protection Officer (DPO) designation and contact tracking.

Orgs that process data at scale, process special categories, or monitor data subjects
systematically must designate a DPO. This module stores designation records.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_DB_PATH = Path.home() / ".orchestra_dpo.db"
_lock = threading.Lock()


@dataclass
class DPORecord:
    id: str
    org_id: str
    name: str
    email: str
    phone: str
    organization: str       # DPO's employer if external
    is_external: bool
    designated_at: float
    designation_expires_at: float | None
    published_to_authority: bool
    notes: str
    created_by: str
    created_at: float
    updated_at: float


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dpo_records (
                id                     TEXT PRIMARY KEY,
                org_id                 TEXT UNIQUE NOT NULL,
                name                   TEXT NOT NULL DEFAULT '',
                email                  TEXT NOT NULL DEFAULT '',
                phone                  TEXT NOT NULL DEFAULT '',
                organization           TEXT NOT NULL DEFAULT '',
                is_external            INTEGER NOT NULL DEFAULT 0,
                designated_at          REAL NOT NULL,
                designation_expires_at REAL,
                published_to_authority INTEGER NOT NULL DEFAULT 0,
                notes                  TEXT NOT NULL DEFAULT '',
                created_by             TEXT NOT NULL DEFAULT '',
                created_at             REAL NOT NULL,
                updated_at             REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dpo_org ON dpo_records(org_id)")


def _row(r) -> DPORecord:
    d = dict(r)
    d["is_external"] = bool(d["is_external"])
    d["published_to_authority"] = bool(d["published_to_authority"])
    return DPORecord(**d)


def upsert_dpo(
    org_id: str,
    name: str,
    email: str,
    phone: str = "",
    organization: str = "",
    is_external: bool = False,
    designated_at: float | None = None,
    designation_expires_at: float | None = None,
    published_to_authority: bool = False,
    notes: str = "",
    created_by: str = "",
) -> DPORecord:
    now = time.time()
    designated_at = designated_at or now
    with _lock, _db() as conn:
        existing = conn.execute("SELECT id FROM dpo_records WHERE org_id=?", (org_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE dpo_records SET name=?,email=?,phone=?,organization=?,is_external=?,"
                "designated_at=?,designation_expires_at=?,published_to_authority=?,notes=?,updated_at=? "
                "WHERE org_id=?",
                (name, email, phone, organization, int(is_external),
                 designated_at, designation_expires_at, int(published_to_authority),
                 notes, now, org_id),
            )
        else:
            conn.execute(
                "INSERT INTO dpo_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), org_id, name, email, phone, organization,
                 int(is_external), designated_at, designation_expires_at,
                 int(published_to_authority), notes, created_by, now, now),
            )
        row = conn.execute("SELECT * FROM dpo_records WHERE org_id=?", (org_id,)).fetchone()
    return _row(row)


def get_dpo(org_id: str) -> DPORecord | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM dpo_records WHERE org_id=?", (org_id,)).fetchone()
    return _row(row) if row else None


def delete_dpo(org_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute("DELETE FROM dpo_records WHERE org_id=?", (org_id,))
    return c.rowcount > 0
