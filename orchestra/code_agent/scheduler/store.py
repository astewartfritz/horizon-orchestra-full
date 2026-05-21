from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from orchestra.code_agent.scheduler.base import RetryPolicy, ScheduledTask, TaskStatus

SCHEDULER_DB = ".agent-scheduler.db"


class SchedulerStore:
    def __init__(self, db_path: str | Path = SCHEDULER_DB):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                name TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                cron TEXT NOT NULL DEFAULT '',
                interval_seconds INTEGER NOT NULL DEFAULT 3600,
                profile TEXT NOT NULL DEFAULT 'minimal',
                enabled INTEGER NOT NULL DEFAULT 1,
                tags TEXT NOT NULL DEFAULT '[]',
                retry_policy TEXT,
                max_execution_seconds REAL NOT NULL DEFAULT 600,
                timeout_seconds REAL NOT NULL DEFAULT 300,
                last_run REAL NOT NULL DEFAULT 0,
                next_run REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                run_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT 'ollama'
            )
        """)
        # migrate existing tables if column missing
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN provider TEXT NOT NULL DEFAULT 'ollama'")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_deps (
                task_name TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                PRIMARY KEY (task_name, depends_on),
                FOREIGN KEY (task_name) REFERENCES tasks(name) ON DELETE CASCADE,
                FOREIGN KEY (depends_on) REFERENCES tasks(name) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at REAL,
                finished_at REAL,
                duration_ms REAL NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 1,
                error TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_history_name ON task_history(task_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_history_status ON task_history(status)
        """)
        conn.commit()
        conn.close()

    def save_task(self, task: ScheduledTask) -> None:
        conn = self._conn
        tags_str = json.dumps(task.tags)
        rp_str = json.dumps(task.retry_policy.__dict__) if task.retry_policy else None
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (name, task, cron, interval_seconds, profile, enabled, tags, retry_policy,
                max_execution_seconds, timeout_seconds, last_run, next_run, status,
                run_count, success_count, failure_count, last_error, provider)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task.name, task.task, task.cron, task.interval_seconds, task.profile,
             1 if task.enabled else 0, tags_str, rp_str,
             task.max_execution_seconds, task.timeout_seconds,
             task.last_run, task.next_run, task.status.value,
             task.run_count, task.success_count, task.failure_count, task.last_error,
             task.provider),
        )
        conn.commit()

    def load_task(self, name: str) -> ScheduledTask | None:
        cur = self._conn.execute("SELECT * FROM tasks WHERE name=?", (name,))
        row = cur.fetchone()
        return self._row_to_task(row) if row else None

    def load_all(self) -> list[ScheduledTask]:
        cur = self._conn.execute("SELECT * FROM tasks ORDER BY name")
        return [self._row_to_task(r) for r in cur.fetchall()]

    def load_due(self, now: float) -> list[ScheduledTask]:
        cur = self._conn.execute(
            "SELECT * FROM tasks WHERE enabled=1 AND status='pending' AND next_run<=? ORDER BY next_run",
            (now,),
        )
        return [self._row_to_task(r) for r in cur.fetchall()]

    def delete_task(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM tasks WHERE name=?", (name,))
        self._conn.execute("DELETE FROM task_deps WHERE task_name=? OR depends_on=?", (name, name))
        self._conn.commit()
        return cur.rowcount > 0

    def update_status(self, name: str, status: TaskStatus, **extra: Any) -> None:
        sets = ["status=?"]
        values: list[Any] = [status.value]
        for k, v in extra.items():
            sets.append(f"{k}=?")
            values.append(v)
        values.append(name)
        self._conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE name=?", values)
        self._conn.commit()

    def add_dependency(self, task_name: str, depends_on: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO task_deps (task_name, depends_on) VALUES (?,?)",
            (task_name, depends_on),
        )
        self._conn.commit()

    def remove_dependency(self, task_name: str, depends_on: str) -> None:
        self._conn.execute(
            "DELETE FROM task_deps WHERE task_name=? AND depends_on=?",
            (task_name, depends_on),
        )
        self._conn.commit()

    def get_dependencies(self, task_name: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT depends_on FROM task_deps WHERE task_name=?", (task_name,)
        )
        return [r["depends_on"] for r in cur.fetchall()]

    def get_dependents(self, task_name: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT task_name FROM task_deps WHERE depends_on=?", (task_name,)
        )
        return [r["task_name"] for r in cur.fetchall()]

    def save_history(self, entry: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """INSERT INTO task_history
               (task_name, status, started_at, finished_at, duration_ms, attempt, error, output, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (entry["task_name"], entry["status"], entry.get("started_at"),
             entry.get("finished_at"), entry.get("duration_ms", 0),
             entry.get("attempt", 1), entry.get("error", ""),
             entry.get("output", ""), entry.get("created_at", time.time())),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def load_history(self, task_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if task_name:
            cur = self._conn.execute(
                "SELECT * FROM task_history WHERE task_name=? ORDER BY created_at DESC LIMIT ?",
                (task_name, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM task_history ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in cur.fetchall()]

    def task_stats(self, task_name: str) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed, AVG(duration_ms) as avg_dur FROM task_history WHERE task_name=?",
            (task_name,),
        )
        row = cur.fetchone()
        return dict(row) if row else {"total": 0, "completed": 0, "failed": 0, "avg_dur": 0}

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> ScheduledTask:
        keys = set(row.keys())
        rp_raw = row["retry_policy"] if "retry_policy" in keys and row["retry_policy"] else None
        rp_data = json.loads(rp_raw) if rp_raw else None
        tags_raw = row["tags"] if "tags" in keys and row["tags"] else "[]"
        return ScheduledTask(
            name=row["name"],
            task=row["task"],
            cron=row["cron"],
            interval_seconds=row["interval_seconds"],
            profile=row["profile"],
            enabled=bool(row["enabled"]),
            tags=json.loads(tags_raw) if isinstance(tags_raw, str) else [],
            retry_policy=RetryPolicy(**rp_data) if rp_data else None,
            max_execution_seconds=row["max_execution_seconds"],
            timeout_seconds=row["timeout_seconds"],
            last_run=row["last_run"],
            next_run=row["next_run"],
            status=TaskStatus(row["status"]),
            run_count=row["run_count"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            last_error=row["last_error"],
            provider=row["provider"] if "provider" in keys and row["provider"] else "ollama",
        )
