from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy (
    agent_name    TEXT NOT NULL,
    task_category TEXT NOT NULL,
    ema_reward    REAL NOT NULL DEFAULT 0.5,
    sample_count  INTEGER NOT NULL DEFAULT 0,
    last_updated  REAL NOT NULL,
    PRIMARY KEY (agent_name, task_category)
);
CREATE TABLE IF NOT EXISTS policy_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DEFAULT_EMA = 0.5
_ALPHA = 0.15        # EMA learning rate — ~6-7 samples to shift by ~50%
_PRIORITY_SCALE = 20 # max priority boost/penalty in priority units


class RoutingPolicy:
    """Learned agent preference table backed by SQLite.

    Tracks exponential moving average (EMA) of rewards per (agent, task_category).
    Provides priority boosts that the Nemotron router uses to bias agent selection.

    Priority boost semantics:
      - boost < 0 → increase priority (agent becomes more preferred)
      - boost > 0 → decrease priority (agent becomes less preferred)
    This matches the convention that lower priority number = higher preference.
    """

    def __init__(
        self,
        db_path: str = ".orchestra-policy.db",
        alpha: float = _ALPHA,
        priority_scale: float = _PRIORITY_SCALE,
    ):
        self._path = db_path
        self._alpha = alpha
        self._scale = priority_scale
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

    def update(self, agent_name: str, task_category: str, reward: float) -> float:
        """Apply EMA update; return new EMA value."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT ema_reward, sample_count FROM policy WHERE agent_name=? AND task_category=?",
                    (agent_name, task_category),
                ).fetchone()

                if row:
                    old_ema = row["ema_reward"]
                    count = row["sample_count"] + 1
                    # Warm-start: use higher alpha for early samples
                    effective_alpha = max(self._alpha, 1.0 / count) if count <= 10 else self._alpha
                    new_ema = effective_alpha * reward + (1 - effective_alpha) * old_ema
                    conn.execute(
                        """
                        UPDATE policy SET ema_reward=?, sample_count=?, last_updated=?
                        WHERE agent_name=? AND task_category=?
                        """,
                        (new_ema, count, time.time(), agent_name, task_category),
                    )
                else:
                    # First observation — use reward directly as starting EMA
                    new_ema = reward
                    conn.execute(
                        """
                        INSERT INTO policy (agent_name, task_category, ema_reward, sample_count, last_updated)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (agent_name, task_category, new_ema, time.time()),
                    )
                conn.commit()
                return new_ema
            finally:
                conn.close()

    def get_ema(self, agent_name: str, task_category: str) -> float:
        """Return current EMA reward for this (agent, category) pair."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT ema_reward FROM policy WHERE agent_name=? AND task_category=?",
                (agent_name, task_category),
            ).fetchone()
            return row["ema_reward"] if row else _DEFAULT_EMA
        finally:
            conn.close()

    def priority_boost(self, agent_name: str, task_category: str) -> float:
        """Return a priority delta to add to the agent's base priority.

        High EMA reward → negative delta (move up in priority list).
        Low EMA reward → positive delta (move down).
        Range: [-scale, +scale].
        """
        ema = self.get_ema(agent_name, task_category)
        # ema in [0, 1]; centre at 0.5; scale to [-scale, +scale]
        return -self._scale * (ema - 0.5) * 2

    def agent_rankings(self, task_category: str) -> list[dict[str, Any]]:
        """Return agents ranked by EMA reward for a given task category."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT agent_name, ema_reward, sample_count, last_updated
                FROM policy WHERE task_category=?
                ORDER BY ema_reward DESC
                """,
                (task_category,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def all_entries(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM policy ORDER BY task_category, ema_reward DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def reset_agent(self, agent_name: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM policy WHERE agent_name=?", (agent_name,))
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def reset_all(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM policy")
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def summary(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM policy").fetchone()[0]
            top = conn.execute(
                """
                SELECT agent_name, task_category, ema_reward, sample_count
                FROM policy ORDER BY ema_reward DESC LIMIT 10
                """
            ).fetchall()
            return {
                "total_entries": total,
                "top_performers": [dict(r) for r in top],
            }
        finally:
            conn.close()
