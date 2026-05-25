"""
Conversation history persistence — store, search, and manage chat sessions.

Each ConversationRecord captures: user_id, title, model, messages (JSON),
token counts, timestamps. Full-text search via SQLite FTS5.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DB_PATH = Path.home() / ".orchestra_history.db"
_lock = threading.Lock()


@dataclass
class ConversationRecord:
    id: str
    user_id: str
    title: str
    model: str
    provider: str
    message_count: int
    total_tokens: int
    created_at: float
    updated_at: float
    archived: bool
    pinned: bool
    tags: str       # JSON list


@dataclass
class MessageRecord:
    id: str
    conversation_id: str
    role: str           # user | assistant | system | tool
    content: str
    token_count: int
    model: str
    created_at: float
    metadata: str       # JSON


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id            TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                title         TEXT NOT NULL DEFAULT 'New conversation',
                model         TEXT NOT NULL DEFAULT '',
                provider      TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                total_tokens  INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL,
                archived      INTEGER NOT NULL DEFAULT 0,
                pinned        INTEGER NOT NULL DEFAULT 0,
                tags          TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at);

            CREATE TABLE IF NOT EXISTS messages (
                id               TEXT PRIMARY KEY,
                conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role             TEXT NOT NULL,
                content          TEXT NOT NULL,
                token_count      INTEGER NOT NULL DEFAULT 0,
                model            TEXT NOT NULL DEFAULT '',
                created_at       REAL NOT NULL,
                metadata         TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                title, content='conversations', content_rowid='rowid'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content, content='messages', content_rowid='rowid'
            );
        """)
        # FTS triggers for auto-sync
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS conv_ai AFTER INSERT ON conversations BEGIN
                INSERT INTO conversations_fts(rowid, title) VALUES (new.rowid, new.title);
            END;
            CREATE TRIGGER IF NOT EXISTS conv_au AFTER UPDATE ON conversations BEGIN
                INSERT INTO conversations_fts(conversations_fts, rowid, title) VALUES('delete', old.rowid, old.title);
                INSERT INTO conversations_fts(rowid, title) VALUES (new.rowid, new.title);
            END;
            CREATE TRIGGER IF NOT EXISTS conv_ad AFTER DELETE ON conversations BEGIN
                INSERT INTO conversations_fts(conversations_fts, rowid, title) VALUES('delete', old.rowid, old.title);
            END;
            CREATE TRIGGER IF NOT EXISTS msg_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
        """)


def _conv_row(r) -> ConversationRecord:
    d = dict(r)
    d["archived"] = bool(d["archived"])
    d["pinned"] = bool(d["pinned"])
    return ConversationRecord(**d)


def _msg_row(r) -> MessageRecord:
    return MessageRecord(**{k: r[k] for k in MessageRecord.__dataclass_fields__})


# ── Conversation CRUD ─────────────────────────────────────────────────────────

def create_conversation(
    user_id: str,
    title: str = "New conversation",
    model: str = "",
    provider: str = "",
    tags: list[str] | None = None,
) -> ConversationRecord:
    now = time.time()
    cid = str(uuid.uuid4())
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO conversations(id,user_id,title,model,provider,message_count,"
            "total_tokens,created_at,updated_at,archived,pinned,tags) VALUES(?,?,?,?,?,0,0,?,?,0,0,?)",
            (cid, user_id, title, model, provider, now, now, json.dumps(tags or [])),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return _conv_row(row)


def get_conversation(conversation_id: str, user_id: str) -> ConversationRecord | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        ).fetchone()
    return _conv_row(row) if row else None


def list_conversations(
    user_id: str,
    archived: bool = False,
    pinned_first: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationRecord]:
    order = "pinned DESC, updated_at DESC" if pinned_first else "updated_at DESC"
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM conversations WHERE user_id=? AND archived=? "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            (user_id, int(archived), limit, offset),
        ).fetchall()
    return [_conv_row(r) for r in rows]


def update_conversation(conversation_id: str, user_id: str, **kwargs: Any) -> ConversationRecord | None:
    allowed = {"title", "model", "provider", "archived", "pinned", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "tags" in updates and isinstance(updates["tags"], list):
        updates["tags"] = json.dumps(updates["tags"])
    if "archived" in updates:
        updates["archived"] = int(updates["archived"])
    if "pinned" in updates:
        updates["pinned"] = int(updates["pinned"])
    updates["updated_at"] = time.time()
    if not updates:
        return get_conversation(conversation_id, user_id)
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _lock, _db() as conn:
        conn.execute(
            f"UPDATE conversations SET {set_clause} WHERE id=? AND user_id=?",
            (*updates.values(), conversation_id, user_id),
        )
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        ).fetchone()
    return _conv_row(row) if row else None


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute(
            "DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        )
    return c.rowcount > 0


# ── Messages ──────────────────────────────────────────────────────────────────

def add_message(
    conversation_id: str,
    role: str,
    content: str,
    token_count: int = 0,
    model: str = "",
    metadata: dict | None = None,
) -> MessageRecord:
    now = time.time()
    mid = str(uuid.uuid4())
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO messages(id,conversation_id,role,content,token_count,model,created_at,metadata) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (mid, conversation_id, role, content, token_count, model, now, json.dumps(metadata or {})),
        )
        # Update conversation stats
        conn.execute(
            "UPDATE conversations SET message_count=message_count+1, "
            "total_tokens=total_tokens+?, updated_at=? WHERE id=?",
            (token_count, now, conversation_id),
        )
        row = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    return _msg_row(row)


def list_messages(conversation_id: str, limit: int = 200, offset: int = 0) -> list[MessageRecord]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at LIMIT ? OFFSET ?",
            (conversation_id, limit, offset),
        ).fetchall()
    return [_msg_row(r) for r in rows]


# ── Full-text search ──────────────────────────────────────────────────────────

def search_conversations(user_id: str, query: str, limit: int = 20) -> list[ConversationRecord]:
    """Search conversation titles and message content."""
    with _db() as conn:
        # Title search
        title_ids = {
            row[0]
            for row in conn.execute(
                "SELECT c.id FROM conversations c JOIN conversations_fts f ON c.rowid=f.rowid "
                "WHERE f.title MATCH ? AND c.user_id=? ORDER BY rank LIMIT ?",
                (query, user_id, limit),
            ).fetchall()
        }
        # Content search
        content_ids = {
            row[0]
            for row in conn.execute(
                "SELECT m.conversation_id FROM messages m JOIN messages_fts f ON m.rowid=f.rowid "
                "JOIN conversations c ON m.conversation_id=c.id "
                "WHERE f.content MATCH ? AND c.user_id=? ORDER BY rank LIMIT ?",
                (query, user_id, limit),
            ).fetchall()
        }
        all_ids = list(title_ids | content_ids)[:limit]
        if not all_ids:
            return []
        placeholders = ",".join("?" * len(all_ids))
        rows = conn.execute(
            f"SELECT * FROM conversations WHERE id IN ({placeholders}) ORDER BY updated_at DESC",
            all_ids,
        ).fetchall()
    return [_conv_row(r) for r in rows]


def conversation_stats(user_id: str) -> dict:
    with _db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(message_count) as msgs, SUM(total_tokens) as tokens "
            "FROM conversations WHERE user_id=? AND archived=0",
            (user_id,),
        ).fetchone()
    return {
        "total_conversations": row["total"] or 0,
        "total_messages": row["msgs"] or 0,
        "total_tokens": row["tokens"] or 0,
    }
