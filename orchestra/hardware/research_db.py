from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DesignProposal:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    isa_snapshot: dict[str, Any] = field(default_factory=dict)
    datapath_snapshot: dict[str, Any] = field(default_factory=dict)
    rtl_snapshot: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DesignProposal:
        return cls(**data)


@dataclass
class DesignIteration:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    proposal_id: str = ""
    iteration_number: int = 1
    diff_description: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    fitness_scores: dict[str, float] = field(default_factory=dict)
    fitness_overall: float = 0.0
    parent_iteration_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent_notes: str = ""
    simulation_result: dict[str, Any] | None = None
    synthesis_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    iteration_id: str = ""
    metric: str = ""
    score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchDB:
    def __init__(self, db_path: str | Path = "hardware_research.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                isa_snapshot TEXT,
                datapath_snapshot TEXT,
                rtl_snapshot TEXT,
                parent_id TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT,
                tags TEXT
            );

            CREATE TABLE IF NOT EXISTS iterations (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                iteration_number INTEGER NOT NULL,
                diff_description TEXT,
                changes TEXT,
                fitness_scores TEXT,
                fitness_overall REAL DEFAULT 0,
                parent_iteration_id TEXT,
                created_at TEXT NOT NULL,
                agent_notes TEXT,
                simulation_result TEXT,
                synthesis_result TEXT,
                FOREIGN KEY (proposal_id) REFERENCES proposals(id)
            );

            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iteration_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                score REAL NOT NULL,
                details TEXT,
                evaluated_at TEXT NOT NULL,
                FOREIGN KEY (iteration_id) REFERENCES iterations(id)
            );

            CREATE TABLE IF NOT EXISTS generated_rtl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iteration_id TEXT NOT NULL,
                module_name TEXT NOT NULL,
                verilog_source TEXT NOT NULL,
                file_hash TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (iteration_id) REFERENCES iterations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_iterations_proposal
                ON iterations(proposal_id);
            CREATE INDEX IF NOT EXISTS idx_evaluations_iteration
                ON evaluations(iteration_id);
        """)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def save_proposal(self, proposal: DesignProposal) -> str:
        self._conn.execute(
            """INSERT INTO proposals (id, name, isa_snapshot, datapath_snapshot,
               rtl_snapshot, parent_id, created_at, metadata, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id, proposal.name,
                json.dumps(proposal.isa_snapshot),
                json.dumps(proposal.datapath_snapshot),
                json.dumps(proposal.rtl_snapshot),
                proposal.parent_id, proposal.created_at,
                json.dumps(proposal.metadata),
                json.dumps(proposal.tags),
            ),
        )
        self._conn.commit()
        return proposal.id

    def get_proposal(self, proposal_id: str) -> DesignProposal | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        return DesignProposal(
            id=row["id"], name=row["name"],
            isa_snapshot=json.loads(row["isa_snapshot"] or "{}"),
            datapath_snapshot=json.loads(row["datapath_snapshot"] or "{}"),
            rtl_snapshot=json.loads(row["rtl_snapshot"] or "{}"),
            parent_id=row["parent_id"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"] or "{}"),
            tags=json.loads(row["tags"] or "[]"),
        )

    def list_proposals(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, name, created_at, tags FROM proposals ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def save_iteration(self, iteration: DesignIteration) -> str:
        self._conn.execute(
            """INSERT INTO iterations (id, proposal_id, iteration_number,
               diff_description, changes, fitness_scores, fitness_overall,
               parent_iteration_id, created_at, agent_notes,
               simulation_result, synthesis_result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                iteration.id, iteration.proposal_id, iteration.iteration_number,
                iteration.diff_description,
                json.dumps(iteration.changes),
                json.dumps(iteration.fitness_scores),
                iteration.fitness_overall,
                iteration.parent_iteration_id,
                iteration.created_at, iteration.agent_notes,
                json.dumps(iteration.simulation_result or {}),
                json.dumps(iteration.synthesis_result or {}),
            ),
        )
        self._conn.commit()
        return iteration.id

    def get_iteration(self, iteration_id: str) -> DesignIteration | None:
        row = self._conn.execute(
            "SELECT * FROM iterations WHERE id = ?", (iteration_id,)
        ).fetchone()
        if row is None:
            return None
        return DesignIteration(
            id=row["id"], proposal_id=row["proposal_id"],
            iteration_number=row["iteration_number"],
            diff_description=row["diff_description"],
            changes=json.loads(row["changes"] or "{}"),
            fitness_scores=json.loads(row["fitness_scores"] or "{}"),
            fitness_overall=row["fitness_overall"],
            parent_iteration_id=row["parent_iteration_id"],
            created_at=row["created_at"],
            agent_notes=row["agent_notes"] or "",
            simulation_result=json.loads(row["simulation_result"] or "null"),
            synthesis_result=json.loads(row["synthesis_result"] or "null"),
        )

    def list_iterations(self, proposal_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT id, iteration_number, fitness_overall, created_at
               FROM iterations WHERE proposal_id = ?
               ORDER BY iteration_number ASC""",
            (proposal_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_evaluation(self, evaluation: EvaluationResult) -> int:
        cur = self._conn.execute(
            """INSERT INTO evaluations (iteration_id, metric, score, details, evaluated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                evaluation.iteration_id, evaluation.metric,
                evaluation.score, json.dumps(evaluation.details),
                evaluation.evaluated_at,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_evaluations(self, iteration_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evaluations WHERE iteration_id = ? ORDER BY evaluated_at",
            (iteration_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_rtl(self, iteration_id: str, module_name: str,
                 verilog_source: str, file_hash: str = "") -> int:
        cur = self._conn.execute(
            """INSERT INTO generated_rtl (iteration_id, module_name,
               verilog_source, file_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                iteration_id, module_name, verilog_source,
                file_hash, datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_rtl(self, iteration_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM generated_rtl WHERE iteration_id = ? ORDER BY created_at",
            (iteration_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_proposal(self, proposal_id: str) -> None:
        self._conn.execute("DELETE FROM evaluations WHERE iteration_id IN "
                          "(SELECT id FROM iterations WHERE proposal_id = ?)",
                          (proposal_id,))
        self._conn.execute("DELETE FROM generated_rtl WHERE iteration_id IN "
                          "(SELECT id FROM iterations WHERE proposal_id = ?)",
                          (proposal_id,))
        self._conn.execute("DELETE FROM iterations WHERE proposal_id = ?",
                          (proposal_id,))
        self._conn.execute("DELETE FROM proposals WHERE id = ?", (proposal_id,))
        self._conn.commit()

    def fitness_history(self, proposal_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT i.iteration_number, i.fitness_overall, i.created_at
               FROM iterations i WHERE i.proposal_id = ?
               ORDER BY i.iteration_number ASC""",
            (proposal_id,),
        ).fetchall()
        return [dict(r) for r in rows]
