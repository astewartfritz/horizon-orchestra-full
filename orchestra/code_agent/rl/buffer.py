from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from orchestra.code_agent.rl.signal import TrainingSignal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    agent_name  TEXT NOT NULL,
    task_category TEXT NOT NULL,
    task_preview  TEXT NOT NULL,
    reward      REAL NOT NULL,
    council_mean REAL NOT NULL,
    passed_gate INTEGER NOT NULL,
    dimensions  TEXT NOT NULL,   -- JSON
    context     TEXT NOT NULL    -- JSON
);
CREATE INDEX IF NOT EXISTS idx_agent ON signals(agent_name);
CREATE INDEX IF NOT EXISTS idx_category ON signals(task_category);
CREATE INDEX IF NOT EXISTS idx_ts ON signals(timestamp);
"""


class ExperienceBuffer:
    """SQLite-backed replay buffer that persists training signals across restarts.

    Thread-safe via a lock. Uses WAL mode for concurrent reads during training.
    """

    def __init__(self, db_path: str = ".orchestra-experience.db"):
        self._path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def add(self, signal: TrainingSignal) -> int:
        """Persist a signal; returns its row id."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO signals
                        (timestamp, agent_name, task_category, task_preview,
                         reward, council_mean, passed_gate, dimensions, context)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal.timestamp,
                        signal.agent_name,
                        signal.task_category,
                        signal.task_preview,
                        signal.reward,
                        signal.council_mean,
                        int(signal.passed_gate),
                        json.dumps(signal.dimension_scores),
                        json.dumps(signal.context),
                    ),
                )
                conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
            finally:
                conn.close()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def for_agent(self, agent_name: str, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM signals WHERE agent_name=? ORDER BY timestamp DESC LIMIT ?",
                (agent_name, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def for_category(self, category: str, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM signals WHERE task_category=? ORDER BY timestamp DESC LIMIT ?",
                (category, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def preference_pairs(
        self,
        min_reward_gap: float = 0.15,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return (winner, loser) preference pairs for the same task_category.

        Used for DPO-style fine-tuning of the routing policy.
        """
        conn = self._connect()
        try:
            # Cross-join signals of same category, different agents, with reward gap
            rows = conn.execute(
                """
                SELECT
                    a.task_preview AS task,
                    a.agent_name   AS winner,
                    a.reward       AS winner_reward,
                    b.agent_name   AS loser,
                    b.reward       AS loser_reward,
                    a.task_category
                FROM signals a
                JOIN signals b
                    ON  a.task_category = b.task_category
                    AND a.agent_name   != b.agent_name
                    AND (a.reward - b.reward) >= ?
                ORDER BY (a.reward - b.reward) DESC
                LIMIT ?
                """,
                (min_reward_gap, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            by_agent = conn.execute(
                """
                SELECT agent_name,
                       COUNT(*) as n,
                       AVG(reward) as avg_reward,
                       SUM(passed_gate) as passes
                FROM signals GROUP BY agent_name
                ORDER BY avg_reward DESC
                """
            ).fetchall()
            by_cat = conn.execute(
                """
                SELECT task_category,
                       COUNT(*) as n,
                       AVG(reward) as avg_reward
                FROM signals GROUP BY task_category
                ORDER BY n DESC
                """
            ).fetchall()
            return {
                "total_signals": total,
                "by_agent": [dict(r) for r in by_agent],
                "by_category": [dict(r) for r in by_cat],
            }
        finally:
            conn.close()

    def clear(self, before_timestamp: float | None = None) -> int:
        with self._lock:
            conn = self._connect()
            try:
                if before_timestamp is not None:
                    cur = conn.execute(
                        "DELETE FROM signals WHERE timestamp < ?", (before_timestamp,)
                    )
                else:
                    cur = conn.execute("DELETE FROM signals")
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["dimensions"] = json.loads(d.get("dimensions", "{}"))
        d["context"] = json.loads(d.get("context", "{}"))
        d["passed_gate"] = bool(d["passed_gate"])
        return d
