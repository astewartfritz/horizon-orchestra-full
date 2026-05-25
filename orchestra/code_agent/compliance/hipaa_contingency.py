"""
HIPAA §164.312(a)(2)(iv) / §164.308(a)(7) — Contingency Plan implementation.

Required implementation specifications:
  (i)  Data backup plan — create and maintain retrievable exact copies of ePHI
  (ii) Disaster recovery plan — restore loss of data (procedures)
  (iii) Emergency mode operation plan — critical business processes during emergency
  (iv) Testing and revision procedures — test and revise contingency plans
  (v)  Applications and data criticality analysis — assess criticality of apps/data

This module stores plans and test results. Actual backup execution is out-of-scope
(handled by infrastructure layer), but the plan documentation and test records live here.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DB_PATH = Path.home() / ".orchestra_hipaa_contingency.db"
_lock = threading.Lock()


@dataclass
class ContingencyPlan:
    id: str
    org_id: str
    plan_type: str          # data_backup | disaster_recovery | emergency_mode | testing | criticality
    title: str
    description: str
    procedures: str         # JSON list of procedure steps
    responsible_party: str
    review_frequency_days: int
    last_reviewed_at: float | None
    last_tested_at: float | None
    next_review_due: float | None
    status: str             # draft | active | archived
    created_by: str
    created_at: float
    updated_at: float


@dataclass
class ContingencyTestResult:
    id: str
    plan_id: str
    org_id: str
    test_type: str          # tabletop | functional | full_scale
    tested_by: str
    tested_at: float
    outcome: str            # pass | fail | partial
    findings: str
    corrective_actions: str
    next_test_due: float | None


_PLAN_TYPES = frozenset({
    "data_backup", "disaster_recovery", "emergency_mode", "testing", "criticality"
})


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contingency_plans (
                id                   TEXT PRIMARY KEY,
                org_id               TEXT NOT NULL,
                plan_type            TEXT NOT NULL,
                title                TEXT NOT NULL,
                description          TEXT NOT NULL DEFAULT '',
                procedures           TEXT NOT NULL DEFAULT '[]',
                responsible_party    TEXT NOT NULL DEFAULT '',
                review_frequency_days INTEGER NOT NULL DEFAULT 365,
                last_reviewed_at     REAL,
                last_tested_at       REAL,
                next_review_due      REAL,
                status               TEXT NOT NULL DEFAULT 'draft',
                created_by           TEXT NOT NULL DEFAULT '',
                created_at           REAL NOT NULL,
                updated_at           REAL NOT NULL,
                UNIQUE(org_id, plan_type)
            );
            CREATE INDEX IF NOT EXISTS idx_cp_org ON contingency_plans(org_id);

            CREATE TABLE IF NOT EXISTS contingency_test_results (
                id                 TEXT PRIMARY KEY,
                plan_id            TEXT NOT NULL REFERENCES contingency_plans(id) ON DELETE CASCADE,
                org_id             TEXT NOT NULL,
                test_type          TEXT NOT NULL DEFAULT 'tabletop',
                tested_by          TEXT NOT NULL DEFAULT '',
                tested_at          REAL NOT NULL,
                outcome            TEXT NOT NULL DEFAULT 'partial',
                findings           TEXT NOT NULL DEFAULT '',
                corrective_actions TEXT NOT NULL DEFAULT '',
                next_test_due      REAL
            );
            CREATE INDEX IF NOT EXISTS idx_ctr_plan ON contingency_test_results(plan_id);
        """)


def _plan_row(r) -> ContingencyPlan:
    return ContingencyPlan(**{k: r[k] for k in ContingencyPlan.__dataclass_fields__})


def _test_row(r) -> ContingencyTestResult:
    return ContingencyTestResult(**{k: r[k] for k in ContingencyTestResult.__dataclass_fields__})


def upsert_plan(
    org_id: str,
    plan_type: str,
    title: str,
    description: str = "",
    procedures: list[str] | None = None,
    responsible_party: str = "",
    review_frequency_days: int = 365,
    status: str = "draft",
    created_by: str = "",
) -> ContingencyPlan:
    if plan_type not in _PLAN_TYPES:
        raise ValueError(f"plan_type must be one of {sorted(_PLAN_TYPES)}")
    now = time.time()
    procs = json.dumps(procedures or [])
    next_review = now + review_frequency_days * 86400
    with _lock, _db() as conn:
        existing = conn.execute(
            "SELECT id FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE contingency_plans SET title=?,description=?,procedures=?,"
                "responsible_party=?,review_frequency_days=?,next_review_due=?,status=?,updated_at=? "
                "WHERE org_id=? AND plan_type=?",
                (title, description, procs, responsible_party, review_frequency_days,
                 next_review, status, now, org_id, plan_type),
            )
        else:
            plan_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO contingency_plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (plan_id, org_id, plan_type, title, description, procs,
                 responsible_party, review_frequency_days, None, None,
                 next_review, status, created_by, now, now),
            )
        row = conn.execute(
            "SELECT * FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
    return _plan_row(row)


def get_plan(org_id: str, plan_type: str) -> ContingencyPlan | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
    return _plan_row(row) if row else None


def list_plans(org_id: str) -> list[ContingencyPlan]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM contingency_plans WHERE org_id=? ORDER BY plan_type", (org_id,)
        ).fetchall()
    return [_plan_row(r) for r in rows]


def mark_reviewed(org_id: str, plan_type: str, reviewer: str = "") -> ContingencyPlan | None:
    now = time.time()
    with _lock, _db() as conn:
        row = conn.execute(
            "SELECT * FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
        if not row:
            return None
        freq = row["review_frequency_days"]
        conn.execute(
            "UPDATE contingency_plans SET last_reviewed_at=?,next_review_due=?,updated_at=? "
            "WHERE org_id=? AND plan_type=?",
            (now, now + freq * 86400, now, org_id, plan_type),
        )
        row = conn.execute(
            "SELECT * FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
    return _plan_row(row)


def add_test_result(
    org_id: str,
    plan_type: str,
    test_type: str = "tabletop",
    tested_by: str = "",
    outcome: str = "partial",
    findings: str = "",
    corrective_actions: str = "",
    next_test_days: int = 365,
) -> ContingencyTestResult | None:
    now = time.time()
    with _lock, _db() as conn:
        plan = conn.execute(
            "SELECT id FROM contingency_plans WHERE org_id=? AND plan_type=?", (org_id, plan_type)
        ).fetchone()
        if not plan:
            return None
        plan_id = plan["id"]
        test_id = str(uuid.uuid4())
        next_due = now + next_test_days * 86400
        conn.execute(
            "INSERT INTO contingency_test_results VALUES(?,?,?,?,?,?,?,?,?,?)",
            (test_id, plan_id, org_id, test_type, tested_by, now, outcome,
             findings, corrective_actions, next_due),
        )
        conn.execute(
            "UPDATE contingency_plans SET last_tested_at=?,updated_at=? WHERE id=?",
            (now, now, plan_id),
        )
        row = conn.execute("SELECT * FROM contingency_test_results WHERE id=?", (test_id,)).fetchone()
    return _test_row(row)


def list_test_results(plan_id: str) -> list[ContingencyTestResult]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM contingency_test_results WHERE plan_id=? ORDER BY tested_at DESC",
            (plan_id,),
        ).fetchall()
    return [_test_row(r) for r in rows]


def contingency_posture(org_id: str) -> dict:
    """Return a posture summary — which required plans exist, which are overdue."""
    plans = {p.plan_type: p for p in list_plans(org_id)}
    now = time.time()
    result = {}
    for pt in sorted(_PLAN_TYPES):
        p = plans.get(pt)
        overdue = (
            p is not None and p.next_review_due is not None and p.next_review_due < now
        ) or (p is not None and p.last_tested_at is None)
        result[pt] = {
            "present": p is not None,
            "status": p.status if p else "missing",
            "last_reviewed_at": p.last_reviewed_at if p else None,
            "last_tested_at": p.last_tested_at if p else None,
            "next_review_due": p.next_review_due if p else None,
            "overdue": overdue,
        }
    return {
        "org_id": org_id,
        "plans": result,
        "all_present": all(v["present"] for v in result.values()),
        "any_overdue": any(v["overdue"] for v in result.values()),
    }
