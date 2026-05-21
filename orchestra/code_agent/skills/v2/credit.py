from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent.skills.v2.rl import RLTrainer, CreditSignal


@dataclass
class CreditRecord:
    step: int
    selection: float
    utilization: float
    distillation: float
    outcome: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "selection": self.selection,
            "utilization": self.utilization,
            "distillation": self.distillation,
            "outcome": self.outcome,
            "timestamp": self.timestamp,
        }


class CreditStore:
    def __init__(self, db_path: str | Path = ".agent-credit.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS credit_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step INTEGER NOT NULL,
                    selection REAL NOT NULL DEFAULT 0.0,
                    utilization REAL NOT NULL DEFAULT 0.0,
                    distillation REAL NOT NULL DEFAULT 0.0,
                    outcome REAL NOT NULL DEFAULT 0.0,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_credit_step ON credit_history(step)")
            conn.commit()
        finally:
            conn.close()

    def record(self, step: int, credit: CreditSignal, outcome: float) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO credit_history (step, selection, utilization, distillation, outcome, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (step, credit.selection, credit.utilization, credit.distillation, outcome, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def history(self, limit: int = 100) -> list[CreditRecord]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT step, selection, utilization, distillation, outcome, timestamp FROM credit_history ORDER BY step ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [CreditRecord(step=r[0], selection=r[1], utilization=r[2], distillation=r[3], outcome=r[4], timestamp=r[5]) for r in rows]
        finally:
            conn.close()

    def latest(self) -> CreditRecord | None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT step, selection, utilization, distillation, outcome, timestamp FROM credit_history ORDER BY step DESC LIMIT 1"
            ).fetchone()
            return CreditRecord(step=row[0], selection=row[1], utilization=row[2], distillation=row[3], outcome=row[4], timestamp=row[5]) if row else None
        finally:
            conn.close()

    def curve_data(self) -> dict[str, list[float]]:
        records = self.history(limit=200)
        return {
            "steps": [r.step for r in records],
            "selection": [r.selection for r in records],
            "utilization": [r.utilization for r in records],
            "distillation": [r.distillation for r in records],
            "outcomes": [r.outcome for r in records],
        }

    def clear(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DELETE FROM credit_history")
            conn.commit()
        finally:
            conn.close()


class PersistentTrainer:
    def __init__(self, store: CreditStore | None = None, window_size: int = 20):
        self.store = store or CreditStore()
        self.trainer = RLTrainer(window_size=window_size)
        self._step = 0
        self._restore()

    def _restore(self) -> None:
        latest = self.store.latest()
        if latest:
            self._step = latest.step + 1

    def record_episode(self, outcome: float, selection_lp: float = 0.0, utilization_lp: float = 0.0, distillation_lp: float = 0.0) -> CreditSignal:
        self.trainer.record_episode(outcome, selection_lp, utilization_lp, distillation_lp)
        credit = self.trainer.compute_credit()
        self.store.record(self._step, credit, outcome)
        self._step += 1
        self.trainer.update()
        return credit

    def stats(self) -> dict[str, Any]:
        return {
            **self.trainer.stats(),
            "step": self._step,
            "curve": self.store.curve_data(),
        }
