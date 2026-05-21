from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent.skills.models import Embedder
from orchestra.code_agent.skills.store import SkillStore


@dataclass
class EvalResult:
    task_instruction: str
    skill_id: int
    reward: float
    success: bool
    steps: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"task_instruction": self.task_instruction, "skill_id": self.skill_id, "reward": self.reward, "success": self.success, "steps": self.steps}


class EvalQueue:
    def __init__(self, db_path: str | Path = ".agent-skills-eval.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS eval_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, skill_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS eval_results (id INTEGER PRIMARY KEY AUTOINCREMENT, task_instruction TEXT NOT NULL, skill_id INTEGER NOT NULL, reward REAL NOT NULL DEFAULT 0.0, success INTEGER NOT NULL DEFAULT 0, steps INTEGER NOT NULL DEFAULT 0, timestamp REAL NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_sid ON eval_results(skill_id)")
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, skill_id: int) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("INSERT INTO eval_queue (skill_id, status, created_at) VALUES (?, 'pending', ?)", (skill_id, time.time()))
            conn.commit()
        finally:
            conn.close()

    def dequeue(self) -> int | None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT id, skill_id FROM eval_queue WHERE status='pending' ORDER BY created_at ASC LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE eval_queue SET status='running' WHERE id=?", (row[0],))
                conn.commit()
                return row[1]
            return None
        finally:
            conn.close()

    def add_result(self, r: EvalResult) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("INSERT INTO eval_results (task_instruction, skill_id, reward, success, steps, timestamp) VALUES (?, ?, ?, ?, ?, ?)", (r.task_instruction, r.skill_id, r.reward, int(r.success), r.steps, r.timestamp))
            conn.commit()
        finally:
            conn.close()

    def results(self, skill_id: int | None = None, limit: int = 100) -> list[EvalResult]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            if skill_id is not None:
                rows = conn.execute("SELECT * FROM eval_results WHERE skill_id=? ORDER BY timestamp DESC LIMIT ?", (skill_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM eval_results ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            return [EvalResult(task_instruction=r[1], skill_id=r[2], reward=r[3], success=bool(r[4]), steps=r[5], timestamp=r[6]) for r in rows]
        finally:
            conn.close()

    def skill_stats(self, skill_id: int) -> dict[str, Any]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT COUNT(*), AVG(reward), SUM(success), AVG(CAST(success AS REAL)) FROM eval_results WHERE skill_id=?", (skill_id,)).fetchone()
            if row and row[0]:
                return {"count": row[0], "avg_reward": row[1] or 0.0, "successes": row[2] or 0, "success_rate": row[3] or 0.0}
            return {"count": 0, "avg_reward": 0.0, "successes": 0, "success_rate": 0.0}
        finally:
            conn.close()

    def comparison(self) -> list[dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("SELECT skill_id, COUNT(*) as n, AVG(reward) as avg_r, SUM(success) as succ, AVG(CAST(success AS REAL)) as avg_s FROM eval_results GROUP BY skill_id ORDER BY avg_r DESC").fetchall()
            return [{"skill_id": r[0], "count": r[1], "avg_reward": r[2], "successes": r[3], "success_rate": r[4]} for r in rows]
        finally:
            conn.close()


class Validator:
    def __init__(self, store: SkillStore, queue: EvalQueue):
        self.store = store
        self.queue = queue

    def validate_new_skill(self, skill_id: int) -> None:
        self.queue.enqueue(skill_id)
