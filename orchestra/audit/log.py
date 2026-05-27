"""Tamper-proof audit log engine.

Hash-chained, HMAC-signed, append-only. Each entry stores:
  SHA256(previous_hash || timestamp || actor || table || record_id || operation || JSON(data))
wrapped in an HMAC-SHA256 signature so that even with DB access,
an attacker cannot forge entries without the secret key.

SQLite triggers enforce append-only at the database level.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


AUDIT_KEY_ENV = "ORCHESTRA_AUDIT_KEY"
_DEFAULT_KEY = "change-me-in-production-32bytes!"  # 32 bytes


def _derive_key(master_key: str) -> bytes:
    """Derive a 32-byte HMAC key via SHA-256."""
    return hashlib.sha256(master_key.encode("utf-8")).digest()


def _get_key() -> bytes:
    key = os.environ.get(AUDIT_KEY_ENV, _DEFAULT_KEY)
    return _derive_key(key)


def _hash_entry(previous_hash: str, timestamp: str, actor: str,
                table: str, record_id: str, operation: str,
                data_json: str) -> str:
    h = hashlib.sha256()
    h.update(previous_hash.encode("utf-8"))
    h.update(timestamp.encode("utf-8"))
    h.update(actor.encode("utf-8"))
    h.update(table.encode("utf-8"))
    h.update(record_id.encode("utf-8"))
    h.update(operation.encode("utf-8"))
    h.update(data_json.encode("utf-8"))
    return h.hexdigest()


def _sign(entry_hash: str, key: bytes) -> str:
    return hmac.new(key, entry_hash.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class AuditEntry:
    id: int = 0
    previous_hash: str = ""
    entry_hash: str = ""
    hmac_signature: str = ""
    timestamp: str = ""
    actor: str = ""
    table_name: str = ""
    record_id: str = ""
    operation: str = ""  # CREATE | UPDATE | DELETE
    data_json: str = ""
    metadata: str = ""

    @property
    def data(self) -> dict[str, Any]:
        return json.loads(self.data_json) if self.data_json else {}

    def verify(self, key: bytes | None = None) -> bool:
        key = key or _get_key()
        expected_hash = _hash_entry(
            self.previous_hash, self.timestamp, self.actor,
            self.table_name, self.record_id, self.operation, self.data_json,
        )
        if expected_hash != self.entry_hash:
            return False
        expected_sig = _sign(self.entry_hash, key)
        return hmac.compare_digest(expected_sig, self.hmac_signature)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS tr_audit_log_prevent_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS tr_audit_log_prevent_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE forbidden');
END;
"""


class AuditLog:
    def __init__(self, db_path: str | Path, key: str | None = None,
                 auto_create: bool = True):
        self.db_path = Path(db_path)
        self._key = _derive_key(key) if key else _get_key()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        if auto_create:
            self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                previous_hash   TEXT NOT NULL DEFAULT '',
                entry_hash      TEXT NOT NULL,
                hmac_signature  TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                actor           TEXT NOT NULL DEFAULT '',
                table_name      TEXT NOT NULL,
                record_id       TEXT NOT NULL,
                operation       TEXT NOT NULL CHECK(operation IN ('CREATE','UPDATE','DELETE')),
                data_json       TEXT NOT NULL DEFAULT '{}',
                metadata        TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_audit_table
                ON audit_log(table_name, record_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_actor
                ON audit_log(actor);
        """ + APPEND_ONLY_TRIGGER_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        if not self._conn:
            raise RuntimeError("AuditLog not initialized (call _init_db or pass auto_create=True)")
        yield self._conn.cursor()

    def _last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["entry_hash"] if row else ""

    def append(self, table: str, record_id: str, operation: str,
               data: dict[str, Any], actor: str = "system",
               metadata: dict[str, Any] | None = None) -> AuditEntry:
        if operation not in ("CREATE", "UPDATE", "DELETE"):
            raise ValueError(f"Invalid operation: {operation}")

        previous_hash = self._last_hash()
        timestamp = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(data, default=str, sort_keys=True)
        entry_hash = _hash_entry(previous_hash, timestamp, actor,
                                 table, record_id, operation, data_json)
        signature = _sign(entry_hash, self._key)

        entry = AuditEntry(
            previous_hash=previous_hash,
            entry_hash=entry_hash,
            hmac_signature=signature,
            timestamp=timestamp,
            actor=actor,
            table_name=table,
            record_id=record_id,
            operation=operation,
            data_json=data_json,
            metadata=json.dumps(metadata or {}),
        )

        self._conn.execute(
            """INSERT INTO audit_log
               (previous_hash, entry_hash, hmac_signature, timestamp,
                actor, table_name, record_id, operation, data_json, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.previous_hash, entry.entry_hash, entry.hmac_signature,
             entry.timestamp, entry.actor, entry.table_name, entry.record_id,
             entry.operation, entry.data_json, entry.metadata),
        )
        self._conn.commit()
        entry.id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return entry

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()
        return row["c"] if row else 0

    # ── Queries ─────────────────────────────────────────────────────────

    def query(self, table: str | None = None, record_id: str | None = None,
              operation: str | None = None, actor: str | None = None,
              limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if table:
            clauses.append("table_name = ?")
            params.append(table)
        if record_id:
            clauses.append("record_id = ?")
            params.append(record_id)
        if operation:
            clauses.append("operation = ?")
            params.append(operation)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)

        where = " AND ".join(clauses) if clauses else "1"
        sql = f"SELECT * FROM audit_log WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_entry(self, entry_id: int) -> AuditEntry | None:
        row = self._conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return None
        return AuditEntry(**row)

    def records_for(self, table: str, record_id: str) -> list[AuditEntry]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE table_name = ? AND record_id = ? ORDER BY id",
            (table, record_id),
        ).fetchall()
        return [AuditEntry(**r) for r in rows]

    # ── Chain integrity ─────────────────────────────────────────────────

    def verify_chain(self, from_id: int = 1, to_id: int | None = None) -> list[dict[str, Any]]:
        """Verify hash chain integrity. Returns list of broken links."""
        to_id = to_id or self.count()
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE id BETWEEN ? AND ? ORDER BY id",
            (from_id, to_id),
        ).fetchall()
        entries = [AuditEntry(**r) for r in rows]

        failures = []
        for i, entry in enumerate(entries):
            if i == 0:
                if entry.previous_hash != "":
                    failures.append({"id": entry.id, "reason": "first entry must have empty previous_hash"})
                continue
            expected_prev = entries[i - 1].entry_hash
            if entry.previous_hash != expected_prev:
                failures.append({
                    "id": entry.id,
                    "reason": f"previous_hash mismatch: expected {expected_prev[:16]}..., got {entry.previous_hash[:16]}...",
                    "expected_prev": expected_prev,
                    "actual_prev": entry.previous_hash,
                })

        return failures

    def verify_signatures(self, from_id: int = 1, to_id: int | None = None) -> list[dict[str, Any]]:
        """Verify HMAC signatures. Returns list of forged entries."""
        to_id = to_id or self.count()
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE id BETWEEN ? AND ? ORDER BY id",
            (from_id, to_id),
        ).fetchall()
        entries = [AuditEntry(**r) for r in rows]

        failures = []
        for entry in entries:
            if not entry.verify(self._key):
                failures.append({
                    "id": entry.id,
                    "reason": "HMAC signature mismatch (tampered data or wrong key)",
                })
        return failures

    def full_audit(self) -> dict[str, Any]:
        """Full compliance audit: chain integrity + signatures + stats."""
        chain_fails = self.verify_chain()
        sig_fails = self.verify_signatures()
        total = self.count()
        return {
            "total_entries": total,
            "chain_integrity": len(chain_fails) == 0,
            "signatures_valid": len(sig_fails) == 0,
            "tampered": len(chain_fails) + len(sig_fails),
            "chain_failures": chain_fails,
            "signature_failures": sig_fails,
        }

    # ── Compliance export ───────────────────────────────────────────────

    def export_json(self, output_path: str | Path, table: str | None = None,
                    record_id: str | None = None) -> Path:
        """Export audit trail as JSON-Lines for compliance review."""
        output = Path(output_path)
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY id"
        ).fetchall() if not table else self.query(table=table, record_id=record_id, limit=999999)

        with open(output, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(row), default=str) + "\n")
        return output

    def export_csv(self, output_path: str | Path) -> Path:
        """Export as minimal CSV."""
        import csv
        output = Path(output_path)
        rows = self._conn.execute(
            "SELECT id, timestamp, actor, table_name, record_id, operation, entry_hash FROM audit_log ORDER BY id"
        ).fetchall()
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "timestamp", "actor", "table_name", "record_id",
                "operation", "entry_hash",
            ])
            writer.writeheader()
            writer.writerows(dict(r) for r in rows)
        return output

    # ── Schema enforcement (re-init triggers on existing DBs) ────────────

    def enforce_append_only(self) -> None:
        """Re-apply append-only triggers (safe to call on existing DBs)."""
        self._conn.executescript(APPEND_ONLY_TRIGGER_SQL)
        self._conn.commit()
