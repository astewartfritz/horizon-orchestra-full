"""Task run history — persists every agentic task with its output."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

_lock = threading.Lock()
_DB_PATH = Path.home() / ".orchestra_runs.db"


class RunStore:
    _instance: RunStore | None = None

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = str(db_path)
        self._init()

    @classmethod
    def get(cls) -> RunStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with _lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id          TEXT PRIMARY KEY,
                    task        TEXT NOT NULL,
                    engine      TEXT DEFAULT '',
                    status      TEXT DEFAULT 'running',
                    result      TEXT DEFAULT '',
                    error       TEXT DEFAULT '',
                    cost_usd    REAL DEFAULT 0,
                    turns       INTEGER DEFAULT 0,
                    workspace   TEXT DEFAULT '',
                    created_at  TEXT DEFAULT (datetime('now')),
                    finished_at TEXT DEFAULT NULL
                )
            """)

    def create(self, run_id: str, task: str, engine: str = "", workspace: str = "") -> None:
        with _lock, self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO runs(id,task,engine,workspace) VALUES(?,?,?,?)",
                (run_id, task, engine, workspace),
            )

    def finish(self, run_id: str, result: str = "", error: str = "",
               cost_usd: float = 0.0, turns: int = 0) -> None:
        status = "error" if error else "done"
        with _lock, self._conn() as conn:
            conn.execute("""
                UPDATE runs SET status=?,result=?,error=?,cost_usd=?,turns=?,
                finished_at=datetime('now') WHERE id=?
            """, (status, result[:8000], error[:2000], cost_usd, turns, run_id))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def delete(self, run_id: str) -> None:
        with _lock, self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE id=?", (run_id,))

    def clear(self) -> None:
        with _lock, self._conn() as conn:
            conn.execute("DELETE FROM runs")


def register_runs_routes(app: Any) -> None:
    store = RunStore.get()
    router = APIRouter(prefix="/api/runs")

    @router.get("")
    async def list_runs(limit: int = 50):
        return {"runs": store.list(limit)}

    @router.get("/{run_id}")
    async def get_run(run_id: str):
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @router.delete("/{run_id}")
    async def delete_run(run_id: str):
        store.delete(run_id)
        return {"deleted": run_id}

    @router.delete("")
    async def clear_runs():
        store.clear()
        return {"cleared": True}

    app.include_router(router)
