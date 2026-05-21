"""SQLite-backed event log — captures errors, warnings, and HTTP events."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_DB_PATH = Path.home() / ".orchestra_logs.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS log_events (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            source TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT DEFAULT '',
            request_id TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_log_ts ON log_events(ts DESC);
        CREATE INDEX IF NOT EXISTS ix_log_level ON log_events(level);
        CREATE INDEX IF NOT EXISTS ix_log_source ON log_events(source);
        """)


def add_event(
    level: str,
    source: str,
    message: str,
    details: Optional[dict] = None,
    request_id: str = "",
) -> None:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO log_events VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    level.upper()[:16],
                    source[:120],
                    message[:4000],
                    json.dumps(details) if details else "",
                    request_id[:64],
                ),
            )
            # Auto-purge: keep last 10,000 events
            c.execute(
                "DELETE FROM log_events WHERE id IN "
                "(SELECT id FROM log_events ORDER BY ts DESC LIMIT -1 OFFSET 10000)"
            )
    except Exception:
        pass  # Never crash the application because of logging


def list_events(
    level: str = "",
    source: str = "",
    search: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    wheres, params = [], []
    if level:
        wheres.append("level=?")
        params.append(level.upper())
    if source:
        wheres.append("source LIKE ?")
        params.append(f"%{source}%")
    if search:
        wheres.append("(message LIKE ? OR source LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    params.extend([min(limit, 500), max(0, offset)])
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM log_events {where_sql} ORDER BY ts DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
        by_level = {
            r[0]: r[1]
            for r in c.execute(
                "SELECT level, COUNT(*) FROM log_events GROUP BY level"
            ).fetchall()
        }
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        errors_1h = c.execute(
            "SELECT COUNT(*) FROM log_events WHERE level IN ('ERROR','CRITICAL') AND ts > ?",
            (one_hour_ago,),
        ).fetchone()[0]
        one_day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        errors_24h = c.execute(
            "SELECT COUNT(*) FROM log_events WHERE level IN ('ERROR','CRITICAL') AND ts > ?",
            (one_day_ago,),
        ).fetchone()[0]
        top_sources = [
            {"source": r[0], "count": r[1]}
            for r in c.execute(
                "SELECT source, COUNT(*) as cnt FROM log_events "
                "WHERE level IN ('ERROR','CRITICAL') "
                "GROUP BY source ORDER BY cnt DESC LIMIT 8"
            ).fetchall()
        ]
        recent_sources = sorted({
            r[0] for r in c.execute(
                "SELECT DISTINCT source FROM log_events ORDER BY ts DESC LIMIT 50"
            ).fetchall()
        })
    return {
        "total": total,
        "by_level": by_level,
        "errors_1h": errors_1h,
        "errors_24h": errors_24h,
        "top_error_sources": top_sources,
        "sources": recent_sources,
    }


def clear_events() -> int:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
        c.execute("DELETE FROM log_events")
    return n
