"""
GDPR Article 33 — Personal Data Breach Notification workflow.

Timeline: the controller must notify the supervisory authority no later than
72 hours after becoming aware of a breach (§33(1)).

States: draft → notified → closed | withdrawn
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_DB_PATH = Path.home() / ".orchestra_breach.db"
_lock = threading.Lock()

_72H = 72 * 3600


@dataclass
class BreachRecord:
    id: str
    org_id: str
    title: str
    discovered_at: float        # Unix ts when breach was discovered
    notified_at: float | None   # When supervisory authority was notified
    deadline_at: float          # discovered_at + 72h
    breach_type: str            # unauthorized_access | data_loss | ransomware | other
    data_subjects_count: int    # approximate number affected
    records_count: int          # approximate records affected
    categories: str             # JSON list: ["email","health","financial",…]
    likely_consequences: str
    measures_taken: str
    dpo_notified: bool
    status: str                 # draft | notified | closed | withdrawn
    reporter_user_id: str
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
            CREATE TABLE IF NOT EXISTS breach_records (
                id                  TEXT PRIMARY KEY,
                org_id              TEXT NOT NULL,
                title               TEXT NOT NULL,
                discovered_at       REAL NOT NULL,
                notified_at         REAL,
                deadline_at         REAL NOT NULL,
                breach_type         TEXT NOT NULL DEFAULT 'other',
                data_subjects_count INTEGER NOT NULL DEFAULT 0,
                records_count       INTEGER NOT NULL DEFAULT 0,
                categories          TEXT NOT NULL DEFAULT '[]',
                likely_consequences TEXT NOT NULL DEFAULT '',
                measures_taken      TEXT NOT NULL DEFAULT '',
                dpo_notified        INTEGER NOT NULL DEFAULT 0,
                status              TEXT NOT NULL DEFAULT 'draft',
                reporter_user_id    TEXT NOT NULL DEFAULT '',
                created_at          REAL NOT NULL,
                updated_at          REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_br_org ON breach_records(org_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_br_status ON breach_records(status)")


def _row(r) -> BreachRecord:
    d = dict(r)
    d["dpo_notified"] = bool(d["dpo_notified"])
    return BreachRecord(**d)


def create_breach(
    org_id: str,
    title: str,
    discovered_at: float,
    breach_type: str = "other",
    data_subjects_count: int = 0,
    records_count: int = 0,
    categories: list[str] | None = None,
    likely_consequences: str = "",
    measures_taken: str = "",
    reporter_user_id: str = "",
) -> BreachRecord:
    import json
    now = time.time()
    b = BreachRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        title=title,
        discovered_at=discovered_at,
        notified_at=None,
        deadline_at=discovered_at + _72H,
        breach_type=breach_type,
        data_subjects_count=data_subjects_count,
        records_count=records_count,
        categories=json.dumps(categories or []),
        likely_consequences=likely_consequences,
        measures_taken=measures_taken,
        dpo_notified=False,
        status="draft",
        reporter_user_id=reporter_user_id,
        created_at=now,
        updated_at=now,
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO breach_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.id, b.org_id, b.title, b.discovered_at, b.notified_at, b.deadline_at,
             b.breach_type, b.data_subjects_count, b.records_count, b.categories,
             b.likely_consequences, b.measures_taken, int(b.dpo_notified), b.status,
             b.reporter_user_id, b.created_at, b.updated_at),
        )
    return b


def update_breach(breach_id: str, org_id: str, **kwargs: Any) -> BreachRecord | None:
    import json
    allowed = {
        "title", "breach_type", "data_subjects_count", "records_count",
        "categories", "likely_consequences", "measures_taken", "dpo_notified",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "categories" in updates and isinstance(updates["categories"], list):
        updates["categories"] = json.dumps(updates["categories"])
    if "dpo_notified" in updates:
        updates["dpo_notified"] = int(updates["dpo_notified"])
    updates["updated_at"] = time.time()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _lock, _db() as conn:
        conn.execute(
            f"UPDATE breach_records SET {set_clause} WHERE id=? AND org_id=?",
            (*updates.values(), breach_id, org_id),
        )
        row = conn.execute("SELECT * FROM breach_records WHERE id=? AND org_id=?", (breach_id, org_id)).fetchone()
    return _row(row) if row else None


def notify_authority(breach_id: str, org_id: str) -> BreachRecord | None:
    """Mark breach as notified to supervisory authority."""
    now = time.time()
    with _lock, _db() as conn:
        row = conn.execute(
            "SELECT * FROM breach_records WHERE id=? AND org_id=? AND status='draft'",
            (breach_id, org_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE breach_records SET status='notified', notified_at=?, updated_at=? WHERE id=?",
            (now, now, breach_id),
        )
        row = conn.execute("SELECT * FROM breach_records WHERE id=?", (breach_id,)).fetchone()
    return _row(row)


def close_breach(breach_id: str, org_id: str) -> BreachRecord | None:
    now = time.time()
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE breach_records SET status='closed', updated_at=? WHERE id=? AND org_id=?",
            (now, breach_id, org_id),
        )
        row = conn.execute("SELECT * FROM breach_records WHERE id=?", (breach_id,)).fetchone()
    return _row(row) if row else None


def get_breach(breach_id: str, org_id: str) -> BreachRecord | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM breach_records WHERE id=? AND org_id=?", (breach_id, org_id)
        ).fetchone()
    return _row(row) if row else None


def list_breaches(org_id: str, status: str = "") -> list[BreachRecord]:
    with _db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM breach_records WHERE org_id=? AND status=? ORDER BY discovered_at DESC",
                (org_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM breach_records WHERE org_id=? ORDER BY discovered_at DESC",
                (org_id,),
            ).fetchall()
    return [_row(r) for r in rows]


def overdue_breaches(org_id: str | None = None) -> list[BreachRecord]:
    """Return draft breaches whose 72-hour notification deadline has passed."""
    now = time.time()
    with _db() as conn:
        if org_id:
            rows = conn.execute(
                "SELECT * FROM breach_records WHERE org_id=? AND status='draft' AND deadline_at<?",
                (org_id, now),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM breach_records WHERE status='draft' AND deadline_at<?", (now,)
            ).fetchall()
    return [_row(r) for r in rows]
