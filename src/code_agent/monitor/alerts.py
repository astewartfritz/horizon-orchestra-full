from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from code_agent.monitor.collector import METRIC_DB, MetricsCollector


class AlertCondition(str, Enum):
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"


class AlertState(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    name: str
    metric_name: str
    condition: AlertCondition
    threshold: float
    cooldown_seconds: float = 300.0
    channels: list[str] = field(default_factory=lambda: ["log"])
    enabled: bool = True


@dataclass
class AlertEvent:
    rule_name: str
    state: AlertState
    metric_value: float
    threshold: float
    message: str
    timestamp: float


AlertCallback = Callable[[AlertEvent], None]


class AlertManager:
    def __init__(self, db_path: str | Path = METRIC_DB):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._callbacks: list[AlertCallback] = []
        self._last_fired: dict[str, float] = {}

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
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

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._init_db()
        return self._local.conn

    def add_rule(self, rule: AlertRule) -> None:
        conn = self._conn
        conn.execute(
            "INSERT OR REPLACE INTO alert_rules (name, metric_name, condition, threshold, cooldown_seconds, channels, enabled, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (rule.name, rule.metric_name, rule.condition.value, rule.threshold, rule.cooldown_seconds, json.dumps(rule.channels), 1 if rule.enabled else 0, time.time()),
        )
        conn.commit()

    def remove_rule(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM alert_rules WHERE name=?", (name,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_rules(self) -> list[AlertRule]:
        cur = self._conn.execute("SELECT * FROM alert_rules ORDER BY name")
        return [
            AlertRule(
                name=r["name"],
                metric_name=r["metric_name"],
                condition=AlertCondition(r["condition"]),
                threshold=r["threshold"],
                cooldown_seconds=r["cooldown_seconds"],
                channels=json.loads(r["channels"]),
                enabled=bool(r["enabled"]),
            )
            for r in cur.fetchall()
        ]

    def on_alert(self, callback: AlertCallback) -> None:
        self._callbacks.append(callback)

    def check(self, collector: MetricsCollector) -> list[AlertEvent]:
        fired: list[AlertEvent] = []
        now = time.time()
        for rule in self.list_rules():
            if not rule.enabled:
                continue
            agg = collector.aggregate(rule.metric_name)
            if agg["count"] == 0:
                continue
            value = agg["last"]
            triggered = False
            if rule.condition == AlertCondition.GT and value > rule.threshold:
                triggered = True
            elif rule.condition == AlertCondition.LT and value < rule.threshold:
                triggered = True
            elif rule.condition == AlertCondition.GTE and value >= rule.threshold:
                triggered = True
            elif rule.condition == AlertCondition.LTE and value <= rule.threshold:
                triggered = True

            if triggered:
                last_fired = self._last_fired.get(rule.name, 0)
                if now - last_fired < rule.cooldown_seconds:
                    continue
                self._last_fired[rule.name] = now
                state = AlertState.CRITICAL if abs(value - rule.threshold) / max(rule.threshold, 0.001) > 0.5 else AlertState.WARNING
                event = AlertEvent(
                    rule_name=rule.name,
                    state=state,
                    metric_value=value,
                    threshold=rule.threshold,
                    message=f"Alert '{rule.name}': {rule.metric_name}={value:.2f} {rule.condition.value} {rule.threshold:.2f}",
                    timestamp=now,
                )
                self._persist_event(event)
                for cb in self._callbacks:
                    cb(event)
                fired.append(event)
        return fired

    def _persist_event(self, event: AlertEvent) -> None:
        self._conn.execute(
            "INSERT INTO alert_events (rule_name, state, metric_value, threshold, message, timestamp) VALUES (?,?,?,?,?,?)",
            (event.rule_name, event.state.value, event.metric_value, event.threshold, event.message, event.timestamp),
        )
        self._conn.commit()

    def get_history(self, rule_name: str | None = None, limit: int = 100) -> list[AlertEvent]:
        if rule_name:
            cur = self._conn.execute(
                "SELECT * FROM alert_events WHERE rule_name=? ORDER BY timestamp DESC LIMIT ?",
                (rule_name, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM alert_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [
            AlertEvent(
                rule_name=r["rule_name"],
                state=AlertState(r["state"]),
                metric_value=r["metric_value"],
                threshold=r["threshold"],
                message=r["message"],
                timestamp=r["timestamp"],
            )
            for r in cur.fetchall()
        ]
