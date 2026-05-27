"""Audit-log integration helpers for healthcare, legal, and finance stores.

Usage::

    from orchestra.audit.integration import enable_healthcare_audit
    enable_healthcare_audit()

All write operations (CREATE / UPDATE / DELETE) across the three verticals
will then produce tamper-proof audit entries.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from orchestra.audit.log import AuditLog

_AUDIT_KEY_ENV = "ORCHESTRA_AUDIT_KEY"


def _audit_db_path(store_name: str) -> Path:
    return Path.home() / f".orchestra_{store_name}_audit.db"


def _resolve_key() -> str | None:
    return os.environ.get(_AUDIT_KEY_ENV)


def enable_healthcare_audit(db_path: str | Path | None = None,
                            key: str | None = None) -> AuditLog:
    """Enable tamper-proof audit logging for the healthcare store.

    Every create_patient / update_patient / delete_patient / create_appointment /
    update_appointment_status / create_encounter / update_encounter_soap /
    create_claim / update_claim call will produce a signed, chained audit entry.

    Returns the AuditLog instance (store holds a reference).
    """
    from orchestra.code_agent.healthcare import store as hc_store
    al = AuditLog(db_path or _audit_db_path("healthcare"), key=key or _resolve_key())
    hc_store._audit_log = al
    return al


def enable_legal_audit(db_path: str | Path | None = None,
                       key: str | None = None) -> AuditLog:
    """Enable tamper-proof audit logging for the legal store.

    Covers clients, matters, time entries, and invoices.
    """
    from orchestra.code_agent.legal import store as legal_store
    al = AuditLog(db_path or _audit_db_path("legal"), key=key or _resolve_key())
    legal_store._audit_log = al
    return al


def enable_finance_audit(db_path: str | Path | None = None,
                         key: str | None = None) -> AuditLog:
    """Enable tamper-proof audit logging for the finance store.

    Covers portfolios, positions, and deals.
    """
    from orchestra.code_agent.finance import portfolio as fin_store
    al = AuditLog(db_path or _audit_db_path("finance"), key=key or _resolve_key())
    fin_store._audit_log = al
    return al


def enable_all(key: str | None = None) -> dict[str, AuditLog]:
    """Enable audit logging for all three vertical stores at once."""
    key = key or _resolve_key()
    return {
        "healthcare": enable_healthcare_audit(key=key),
        "legal": enable_legal_audit(key=key),
        "finance": enable_finance_audit(key=key),
    }


def _audit_append(store_module: Any, table: str, record_id: str,
                  operation: str, data: dict[str, Any],
                  actor: str = "system") -> None:
    """Append an audit entry if the store has audit enabled (no-op otherwise)."""
    al: AuditLog | None = getattr(store_module, "_audit_log", None)
    if al is not None:
        al.append(table, record_id, operation, data, actor=actor)
