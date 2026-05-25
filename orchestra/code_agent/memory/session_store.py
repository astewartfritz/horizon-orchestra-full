from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class StoredSession:
    """A persisted chat session, stored alongside memories in .agent-memory.db."""
    id: str = ""
    task: str = ""
    created_at: str = ""
    updated_at: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    finished: bool = False

    def add_message(self, role: str, content: str, **extra: Any) -> None:
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredSession:
        return cls(**data)


class SessionStore:
    """Unified session persistence backed by SQLite.

    Stores chat sessions and messages in the same database file as
    MemoryStore (``.agent-memory.db``), consolidating the old JSON-per-file
    approach into a single queryable backend.
    """

    def __init__(self, db_path: str | Path = ".agent-memory.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished INTEGER NOT NULL DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}',
                state_json TEXT NOT NULL DEFAULT '{}',
                result TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tool_call_id TEXT,
                name TEXT,
                tool_calls_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at);
        """)
        self.conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────────

    def save(self, session: StoredSession) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not session.id:
            session.id = uuid.uuid4().hex[:12]
        if not session.created_at:
            session.created_at = now
        session.updated_at = now

        self.conn.execute(
            """INSERT OR REPLACE INTO chat_sessions
               (id, task, created_at, updated_at, finished, config_json, state_json, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id, session.task, session.created_at, session.updated_at,
                int(session.finished),
                json.dumps(session.config), json.dumps(session.state),
                session.result,
            ),
        )
        # Replace messages: delete old, insert new
        self.conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session.id,))
        for msg in session.messages:
            self.conn.execute(
                """INSERT INTO chat_messages
                   (session_id, role, content, tool_call_id, name, tool_calls_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    msg.get("role", ""),
                    msg.get("content", ""),
                    msg.get("tool_call_id"),
                    msg.get("name"),
                    json.dumps(msg.get("tool_calls")) if msg.get("tool_calls") else None,
                    msg.get("created_at", now),
                ),
            )
        self.conn.commit()

    def load(self, sid: str) -> StoredSession | None:
        row = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (sid,)
        ).fetchone()
        if not row:
            return None

        session = StoredSession(
            id=row["id"],
            task=row["task"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished=bool(row["finished"]),
            config=json.loads(row["config_json"] or "{}"),
            state=json.loads(row["state_json"] or "{}"),
            result=row["result"],
        )

        msg_rows = self.conn.execute(
            "SELECT role, content, tool_call_id, name, tool_calls_json, created_at "
            "FROM chat_messages WHERE session_id = ? ORDER BY id",
            (sid,),
        ).fetchall()
        for m in msg_rows:
            msg: dict[str, Any] = {
                "role": m["role"],
                "content": m["content"],
                "created_at": m["created_at"],
            }
            if m["tool_call_id"]:
                msg["tool_call_id"] = m["tool_call_id"]
            if m["name"]:
                msg["name"] = m["name"]
            if m["tool_calls_json"]:
                msg["tool_calls"] = json.loads(m["tool_calls_json"])
            session.messages.append(msg)

        return session

    def delete(self, sid: str) -> bool:
        self.conn.execute("DELETE FROM chat_sessions WHERE id = ?", (sid,))
        self.conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
        self.conn.commit()
        return self.conn.total_changes > 0

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT s.id, s.task, s.created_at, s.updated_at, s.finished, s.result,
                      COUNT(m.id) as message_count
               FROM chat_sessions s
               LEFT JOIN chat_messages m ON m.session_id = s.id
               GROUP BY s.id
               ORDER BY s.updated_at DESC"""
        ).fetchall()

        results = []
        for row in rows:
            # Build last_response snippet
            last_msg = self.conn.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = ? AND role = 'assistant' AND content != '' "
                "ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            last_response = (last_msg["content"][:200] if last_msg else "")

            results.append({
                "id": row["id"],
                "task": (row["task"] or "")[:80],
                "created_at": row["created_at"] or "",
                "finished": bool(row["finished"]),
                "message_count": row["message_count"] or 0,
                "last_response": last_response,
            })
        return results

    def search_sessions(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across session tasks and message content."""
        q = f"%{query}%"
        rows = self.conn.execute(
            """SELECT DISTINCT s.id, s.task, s.created_at, s.updated_at, s.finished
               FROM chat_sessions s
               LEFT JOIN chat_messages m ON m.session_id = s.id
               WHERE s.task LIKE ? OR m.content LIKE ?
               ORDER BY s.updated_at DESC
               LIMIT ?""",
            (q, q, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Migration from JSON files ───────────────────────────────────────────

    def migrate_from_json(self, json_dir: str | Path) -> int:
        """Import sessions stored as JSON files into SQLite.

        Returns the number of sessions migrated. Idempotent — skips
        sessions whose ``id`` already exists in the database.
        """
        json_dir = Path(json_dir)
        if not json_dir.exists():
            return 0

        count = 0
        for p in sorted(json_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text("utf-8"))
                sid = data.get("id", p.stem)
                # Skip if already migrated
                existing = self.conn.execute(
                    "SELECT 1 FROM chat_sessions WHERE id = ?", (sid,)
                ).fetchone()
                if existing:
                    continue

                session = StoredSession(
                    id=sid,
                    task=data.get("task", ""),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    messages=data.get("messages", []),
                    config=data.get("config", {}),
                    state=data.get("state", {}),
                    result=data.get("result"),
                    finished=data.get("finished", False),
                )
                self.save(session)
                count += 1
            except Exception as exc:
                _log.warning("Failed to migrate %s: %s", p.name, exc)
                continue

        if count:
            _log.info("Migrated %d sessions from %s", count, json_dir)
        return count

    # ── Stats ───────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        session_count = self.conn.execute(
            "SELECT COUNT(*) FROM chat_sessions"
        ).fetchone()[0]
        msg_count = self.conn.execute(
            "SELECT COUNT(*) FROM chat_messages"
        ).fetchone()[0]
        finished = self.conn.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE finished = 1"
        ).fetchone()[0]
        return {
            "total_sessions": session_count,
            "total_messages": msg_count,
            "finished_sessions": finished,
            "in_progress_sessions": session_count - finished,
        }

    def close(self) -> None:
        self.conn.close()
