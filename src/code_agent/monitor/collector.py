from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

METRIC_DB = ".agent-metrics.db"


@dataclass
class MetricPoint:
    timestamp: float
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    metric_type: str = "counter"


class MetricsCollector:
    def __init__(self, db_path: str | Path = METRIC_DB):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._session_id = f"s{int(time.time() * 1000)}"
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=OFF")
        return self._local.conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                metric_type TEXT NOT NULL DEFAULT 'counter',
                labels TEXT NOT NULL DEFAULT '{}',
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_aggregates (
                name TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                labels TEXT NOT NULL DEFAULT '{}',
                count INTEGER NOT NULL DEFAULT 0,
                sum REAL NOT NULL DEFAULT 0,
                min REAL NOT NULL DEFAULT 0,
                max REAL NOT NULL DEFAULT 0,
                last REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (name, labels)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                metric_name TEXT NOT NULL,
                condition TEXT NOT NULL,
                threshold REAL NOT NULL,
                cooldown_seconds REAL NOT NULL DEFAULT 300,
                channels TEXT NOT NULL DEFAULT '["log"]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                state TEXT NOT NULL,
                metric_value REAL NOT NULL,
                threshold REAL NOT NULL,
                message TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        self._insert("counter", name, value, labels)

    def gauge(self, name: str, value: float, **labels: str) -> None:
        self._insert("gauge", name, value, labels)

    def observe(self, name: str, value: float, **labels: str) -> None:
        self._insert("histogram", name, value, labels)

    def _insert(self, metric_type: str, name: str, value: float, labels: dict[str, str]) -> None:
        labels_str = json.dumps(labels, sort_keys=True)
        now = time.time()
        conn = self._conn
        conn.execute(
            "INSERT INTO metrics (name, value, metric_type, labels, session_id, timestamp) VALUES (?,?,?,?,?,?)",
            (name, value, metric_type, labels_str, self._session_id, now),
        )
        conn.execute("""
            INSERT INTO metric_aggregates (name, metric_type, labels, count, sum, min, max, last, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(name, labels) DO UPDATE SET
                count = count + 1,
                sum = sum + excluded.sum,
                min = MIN(min, excluded.min),
                max = MAX(max, excluded.max),
                last = excluded.last,
                updated_at = excluded.updated_at
        """, (name, metric_type, labels_str, value, value, value, value, now))
        conn.commit()

    def query(self, name: str, since: float = 0, limit: int = 1000) -> list[MetricPoint]:
        cur = self._conn.execute(
            "SELECT name, value, metric_type, labels, timestamp FROM metrics WHERE name=? AND timestamp>=? ORDER BY timestamp DESC LIMIT ?",
            (name, since, limit),
        )
        return [
            MetricPoint(
                name=r["name"],
                value=r["value"],
                metric_type=r["metric_type"],
                labels=json.loads(r["labels"]),
                timestamp=r["timestamp"],
            )
            for r in cur.fetchall()
        ]

    def aggregate(self, name: str) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT count, sum, min, max, last FROM metric_aggregates WHERE name=?",
            (name,),
        )
        row = cur.fetchone()
        if not row:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "last": 0, "avg": 0}
        return {
            "count": row["count"],
            "sum": row["sum"],
            "min": row["min"],
            "max": row["max"],
            "last": row["last"],
            "avg": row["sum"] / row["count"] if row["count"] else 0,
        }

    def list_metrics(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT DISTINCT name, metric_type FROM metrics ORDER BY name"
        )
        results = []
        for r in cur.fetchall():
            agg = self.aggregate(r["name"])
            results.append({"name": r["name"], "type": r["metric_type"], **agg})
        return results

    def summary(self) -> dict[str, Any]:
        cur = self._conn.execute("SELECT COUNT(*) as total FROM metrics")
        total_points = cur.fetchone()["total"]
        cur = self._conn.execute("SELECT COUNT(DISTINCT name) as cnt FROM metrics")
        total_metrics = cur.fetchone()["cnt"]
        cur = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM metrics WHERE session_id=?", (self._session_id,)
        )
        session_points = cur.fetchone()["cnt"]
        return {
            "total_points": total_points,
            "total_metrics": total_metrics,
            "session_points": session_points,
            "session_id": self._session_id,
        }

    def prune(self, older_than: float) -> int:
        cur = self._conn.execute("DELETE FROM metrics WHERE timestamp<?", (older_than,))
        deleted = cur.rowcount
        self._conn.commit()
        return deleted

    def flush(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.commit()

    def close(self) -> None:
        self.flush()
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
