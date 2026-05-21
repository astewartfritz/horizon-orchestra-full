from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_lock = threading.Lock()


class UserStore:
    """SQLite-backed persistent user store.

    Shares the same database file as SubscriptionStore
    so user accounts and billing are in one place.
    """

    _instance: UserStore | None = None

    def __init__(self, db_path: str | Path = "orchestra_billing.db") -> None:
        self._path = str(db_path)
        self._init_db()
        type(self)._instance = self

    @classmethod
    def get(cls) -> UserStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with _lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id            TEXT PRIMARY KEY,
                    email         TEXT UNIQUE NOT NULL,
                    name          TEXT DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role          TEXT DEFAULT 'user',
                    tier          TEXT DEFAULT 'free',
                    stripe_customer_id TEXT,
                    created_at    REAL NOT NULL,
                    metadata      TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """)

    def create_user(self, email: str, password_hash: str, name: str = "",
                    role: str = "user", tier: str = "free") -> dict[str, Any]:
        with _lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE email=?", (email,)
            ).fetchone()
            if existing:
                raise ValueError("Email already registered")

            user_id = str(uuid.uuid4())
            now = time.time()
            conn.execute("""
                INSERT INTO users(id, email, name, password_hash, role, tier, created_at, metadata)
                VALUES(?,?,?,?,?,?,?,?)
            """, (user_id, email, name, password_hash, role, tier, now, "{}"))
            return self._row_to_dict(conn, user_id)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email=?", (email,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_user(self, user_id: str, **kwargs: Any) -> dict[str, Any] | None:
        allowed = {"name", "role", "tier", "stripe_customer_id", "metadata", "password_hash"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_user_by_id(user_id)

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [user_id]

        with _lock, self._conn() as conn:
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id=?", values
            )
            return self._row_to_dict(conn, user_id)

    def set_stripe_customer(self, user_id: str, stripe_id: str) -> None:
        with _lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET stripe_customer_id=? WHERE id=?",
                (stripe_id, user_id),
            )

    def delete_user(self, user_id: str) -> bool:
        with _lock, self._conn() as conn:
            c = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            return c.rowcount > 0

    def list_users(self, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, role, tier, created_at FROM users "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_users(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
            return row["cnt"] if row else 0

    def _row_to_dict(self, conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
