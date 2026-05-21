from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CreditSignal:
    selection: float = 0.0
    utilization: float = 0.0
    distillation: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"selection": self.selection, "utilization": self.utilization, "distillation": self.distillation}


@dataclass
class CreditRecord:
    step: int
    selection: float
    utilization: float
    distillation: float
    outcome: float
    timestamp: float = field(default_factory=time.time)


class CreditLedger:
    def __init__(self, db_path: str | Path = ".agent-credit.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS credit_history (id INTEGER PRIMARY KEY AUTOINCREMENT, step INTEGER NOT NULL, selection REAL NOT NULL DEFAULT 0.0, utilization REAL NOT NULL DEFAULT 0.0, distillation REAL NOT NULL DEFAULT 0.0, outcome REAL NOT NULL DEFAULT 0.0, timestamp REAL NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_credit_step ON credit_history(step)")
            conn.commit()
        finally:
            conn.close()

    def record(self, step: int, signal: CreditSignal, outcome: float) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("INSERT INTO credit_history (step, selection, utilization, distillation, outcome, timestamp) VALUES (?, ?, ?, ?, ?, ?)", (step, signal.selection, signal.utilization, signal.distillation, outcome, time.time()))
            conn.commit()
        finally:
            conn.close()

    def history(self, limit: int = 100) -> list[CreditRecord]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("SELECT step, selection, utilization, distillation, outcome, timestamp FROM credit_history ORDER BY step ASC LIMIT ?", (limit,)).fetchall()
            return [CreditRecord(step=r[0], selection=r[1], utilization=r[2], distillation=r[3], outcome=r[4], timestamp=r[5]) for r in rows]
        finally:
            conn.close()

    def curve_data(self) -> dict[str, list[float]]:
        records = self.history(limit=200)
        return {"steps": [r.step for r in records], "selection": [r.selection for r in records], "utilization": [r.utilization for r in records], "distillation": [r.distillation for r in records], "outcomes": [r.outcome for r in records]}

    def clear(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DELETE FROM credit_history")
            conn.commit()
        finally:
            conn.close()


class AdvantageTracker:
    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self._outcomes: list[float] = []

    def record(self, outcome: float) -> None:
        self._outcomes.append(outcome)
        if len(self._outcomes) > self.window_size * 3:
            self._outcomes = self._outcomes[-self.window_size * 2:]

    def compute(self) -> CreditSignal:
        n = len(self._outcomes)
        if n < 3:
            return CreditSignal(0.5, 0.5, 0.5)
        recent = self._outcomes[-min(self.window_size, n):]
        utilization = sum(recent) / len(recent)
        all_avg = sum(self._outcomes) / n
        variance = sum((o - all_avg) ** 2 for o in self._outcomes) / n if n > 1 else 0.0
        return CreditSignal(selection=all_avg, utilization=utilization, distillation=min(1.0, variance * 0.5) if n > 5 else 0.0)

    def stats(self) -> dict[str, Any]:
        return {"episodes": len(self._outcomes), "avg_outcome": sum(self._outcomes) / len(self._outcomes) if self._outcomes else 0.0, "recent_avg": sum(self._outcomes[-min(self.window_size, len(self._outcomes)):]) / min(self.window_size, len(self._outcomes)) if self._outcomes else 0.0}
