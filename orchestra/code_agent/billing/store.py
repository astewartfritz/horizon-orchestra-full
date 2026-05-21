"""SQLite-backed subscription store.

Keyed by a client-generated UUID (stored in browser localStorage).
Maps that anonymous ID → Stripe customer ID → subscription status.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


_lock = threading.Lock()


class SubscriptionStore:
    _instance: SubscriptionStore | None = None

    def __init__(self, db_path: str | Path = "orchestra_billing.db") -> None:
        self._path = str(db_path)
        self._init_db()

    @classmethod
    def get(cls) -> SubscriptionStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with _lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS customers (
                    local_id      TEXT PRIMARY KEY,
                    stripe_id     TEXT UNIQUE,
                    email         TEXT DEFAULT '',
                    created_at    TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    stripe_sub_id TEXT PRIMARY KEY,
                    stripe_cus_id TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    plan          TEXT DEFAULT 'pro',
                    current_period_end INTEGER DEFAULT 0,
                    updated_at    TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_sub_cus ON subscriptions(stripe_cus_id);
            """)

    # ── Customer ──────────────────────────────────────────────────────────────

    def get_or_create_local(self, local_id: str, email: str = "") -> dict[str, Any]:
        with _lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM customers WHERE local_id=?", (local_id,)
            ).fetchone()
            if row:
                return dict(row)
            conn.execute(
                "INSERT INTO customers(local_id, email) VALUES(?,?)",
                (local_id, email),
            )
            return {"local_id": local_id, "stripe_id": None, "email": email}

    def link_stripe_customer(self, local_id: str, stripe_id: str) -> None:
        with _lock, self._conn() as conn:
            conn.execute(
                "UPDATE customers SET stripe_id=? WHERE local_id=?",
                (stripe_id, local_id),
            )

    def local_id_for_stripe(self, stripe_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT local_id FROM customers WHERE stripe_id=?", (stripe_id,)
            ).fetchone()
            return row["local_id"] if row else None

    def stripe_id_for_local(self, local_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT stripe_id FROM customers WHERE local_id=?", (local_id,)
            ).fetchone()
            return row["stripe_id"] if row else None

    # ── Subscription ─────────────────────────────────────────────────────────

    def upsert_subscription(self, sub: dict[str, Any]) -> None:
        with _lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO subscriptions(stripe_sub_id, stripe_cus_id, status, plan, current_period_end)
                VALUES(:id, :customer, :status, :plan, :period_end)
                ON CONFLICT(stripe_sub_id) DO UPDATE SET
                    status=excluded.status,
                    plan=excluded.plan,
                    current_period_end=excluded.current_period_end,
                    updated_at=datetime('now')
            """, {
                "id": sub["id"],
                "customer": sub["customer"],
                "status": sub["status"],
                "plan": "pro",
                "period_end": sub.get("current_period_end", 0),
            })

    def is_active(self, local_id: str) -> bool:
        stripe_id = self.stripe_id_for_local(local_id)
        if not stripe_id:
            return False
        with self._conn() as conn:
            row = conn.execute("""
                SELECT status FROM subscriptions
                WHERE stripe_cus_id=? AND status IN ('active','trialing')
                ORDER BY current_period_end DESC LIMIT 1
            """, (stripe_id,)).fetchone()
            return row is not None

    def subscription_info(self, local_id: str) -> dict[str, Any]:
        stripe_id = self.stripe_id_for_local(local_id)
        if not stripe_id:
            return {"plan": "free", "status": "none", "active": False}
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM subscriptions
                WHERE stripe_cus_id=?
                ORDER BY current_period_end DESC LIMIT 1
            """, (stripe_id,)).fetchone()
            if not row:
                return {"plan": "free", "status": "none", "active": False}
            active = row["status"] in ("active", "trialing")
            return {
                "plan": "pro" if active else "free",
                "status": row["status"],
                "active": active,
                "stripe_customer_id": stripe_id,
                "current_period_end": row["current_period_end"],
            }
