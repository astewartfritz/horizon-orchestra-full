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
                    prof_role     TEXT DEFAULT '',
                    stripe_customer_id TEXT,
                    created_at    REAL NOT NULL,
                    metadata      TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """)
            # Idempotent migrations for existing deployments
            for col, definition in [
                ("prof_role", "TEXT DEFAULT ''"),
                ("approved",  "INTEGER DEFAULT 0"),
                ("is_owner",  "INTEGER DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                except Exception:
                    pass

    def create_user(self, email: str, password_hash: str, name: str = "",
                    role: str = "user", tier: str = "free", prof_role: str = "",
                    approved: bool = False, is_owner: bool = False) -> dict[str, Any]:
        with _lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE email=?", (email,)
            ).fetchone()
            if existing:
                raise ValueError("Email already registered")

            user_id = str(uuid.uuid4())
            now = time.time()
            conn.execute("""
                INSERT INTO users(id, email, name, password_hash, role, tier, prof_role,
                                  approved, is_owner, created_at, metadata)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (user_id, email, name, password_hash, role, tier, prof_role,
                  1 if approved else 0, 1 if is_owner else 0, now, "{}"))
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

    def seed_owner(self, email: str, password_hash: str, name: str = "Owner") -> dict[str, Any]:
        """Ensure the owner account exists and is marked approved + is_owner. Idempotent."""
        with _lock, self._conn() as conn:
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET role='admin', tier='unlimited', approved=1, is_owner=1,"
                    " password_hash=? WHERE email=?",
                    (password_hash, email),
                )
                return self._row_to_dict(conn, row["id"])
            user_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO users(id, email, name, password_hash, role, tier, prof_role,
                                  approved, is_owner, created_at, metadata)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (user_id, email, name, password_hash, "admin", "unlimited", "",
                  1, 1, time.time(), "{}"))
            return self._row_to_dict(conn, user_id)

    def approve_user(self, user_id: str) -> bool:
        with _lock, self._conn() as conn:
            c = conn.execute("UPDATE users SET approved=1 WHERE id=?", (user_id,))
            return c.rowcount > 0

    def reject_user(self, user_id: str) -> bool:
        with _lock, self._conn() as conn:
            c = conn.execute("DELETE FROM users WHERE id=? AND is_owner=0", (user_id,))
            return c.rowcount > 0

    def get_pending_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, role, tier, created_at FROM users "
                "WHERE approved=0 ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, role, tier, approved, is_owner, created_at FROM users "
                "ORDER BY is_owner DESC, created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_user(self, user_id: str, **kwargs: Any) -> dict[str, Any] | None:
        allowed = {"name", "role", "tier", "prof_role", "stripe_customer_id", "metadata",
                   "password_hash", "approved", "is_owner"}
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
