from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("orchestra.db")

_MIGRATIONS: list[Migration] = []


@dataclass
class Migration:
    version: int
    name: str
    up: str
    down: str


class MigrationEngine:
    def __init__(self, db_url: str | None = None) -> None:
        self._db_url: str = db_url or os.environ.get(
            "DATABASE_URL", "sqlite:///orchestra_billing.db"
        )
        self._migrations: list[Migration] = list(_MIGRATIONS)
        self._conn: Any = None

    def register(self, migration: Migration) -> None:
        for i, existing in enumerate(self._migrations):
            if existing.version == migration.version:
                self._migrations[i] = migration
                return
        self._migrations.append(migration)
        self._migrations.sort(key=lambda m: m.version)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect(self) -> None:
        if self._conn is not None:
            return
        if self._db_url.startswith("sqlite"):
            path = self._db_url.replace("sqlite:///", "")
            self._conn = sqlite3.connect(path)
            self._conn.row_factory = sqlite3.Row
            log.info("connected to SQLite at %s", path)
        elif self._db_url.startswith("postgresql"):
            try:
                import psycopg2  # type: ignore[import-untyped]
            except ImportError:
                log.error("psycopg2 is not installed — cannot connect to PostgreSQL")
                raise
            self._conn = psycopg2.connect(self._db_url)
            log.info("connected to PostgreSQL at %s", self._db_url)
        else:
            msg = f"unsupported database URL scheme: {self._db_url}"
            log.error(msg)
            raise ValueError(msg)

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _execute(self, sql: str, params: tuple = ()) -> Any:
        cur = self._conn.cursor()
        # executescript handles multi-statement SQL but commits implicitly;
        # fall back to execute for single statements (which support params)
        if params or sql.strip().count(";") <= 1:
            cur.execute(sql.rstrip(";"), params)
        else:
            self._conn.executescript(sql)
        return cur

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def apply(self) -> None:
        self._connect()
        self._ensure_migrations_table()

        applied = set(self._query_applied())
        self._migrations.sort(key=lambda m: m.version)

        for mig in self._migrations:
            if mig.version in applied:
                continue
            log.info("applying migration %d: %s", mig.version, mig.name)
            try:
                self._execute(mig.up)
                self._record_migration(mig.version, mig.name)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                log.exception(
                    "migration %d (%s) failed — rolled back",
                    mig.version,
                    mig.name,
                )
                raise

        self._close()

    def rollback(self, step: int = 1) -> None:
        self._connect()
        applied = self._query_applied()
        applied.sort(reverse=True)

        self._migrations.sort(key=lambda m: m.version)
        rolled = 0

        for version in applied:
            if rolled >= step:
                break
            mig = next((m for m in self._migrations if m.version == version), None)
            if mig is None:
                log.warning("no migration record for version %d", version)
                continue
            log.info("rolling back migration %d: %s", mig.version, mig.name)
            try:
                self._execute(mig.down)
                self._remove_migration(mig.version)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                log.exception(
                    "rollback of %d (%s) failed — rolled back",
                    mig.version,
                    mig.name,
                )
                raise
            rolled += 1

        self._close()

    def status(self) -> list[int]:
        self._connect()
        try:
            return self._query_applied()
        finally:
            self._close()

    def _query_applied(self) -> list[int]:
        cur = self._execute(
            "SELECT version FROM _migrations ORDER BY version"
        )
        rows = cur.fetchall()
        return [int(r["version"]) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_migrations_table(self) -> None:
        if self._db_url.startswith("sqlite"):
            sql = (
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "version INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "applied_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        else:
            sql = (
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "version INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "applied_at TIMESTAMP DEFAULT NOW()"
                ")"
            )
        self._execute(sql)
        self._conn.commit()

    def _record_migration(self, version: int, name: str) -> None:
        self._execute(
            "INSERT INTO _migrations (version, name) VALUES (?, ?)",
            (version, name),
        )

    def _remove_migration(self, version: int) -> None:
        self._execute(
            "DELETE FROM _migrations WHERE version = ?", (version,)
        )


# ── Pre-registered migrations ──────────────────────────────────────

_MIGRATIONS.append(
    Migration(
        version=1,
        name="create_users_table",
        up=(
            "CREATE TABLE IF NOT EXISTS users ("
            "id TEXT PRIMARY KEY, "
            "email TEXT UNIQUE NOT NULL, "
            "name TEXT DEFAULT '', "
            "password_hash TEXT NOT NULL, "
            "role TEXT DEFAULT 'user', "
            "tier TEXT DEFAULT 'free', "
            "stripe_customer_id TEXT, "
            "created_at REAL NOT NULL, "
            "metadata TEXT DEFAULT '{}'"
            ")"
        ),
        down="DROP TABLE IF EXISTS users",
    )
)

_MIGRATIONS.append(
    Migration(
        version=2,
        name="create_subscriptions_table",
        up=(
            "CREATE TABLE IF NOT EXISTS subscriptions ("
            "stripe_sub_id TEXT PRIMARY KEY, "
            "stripe_cus_id TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "plan TEXT DEFAULT 'pro', "
            "current_period_end INTEGER DEFAULT 0, "
            "updated_at TEXT DEFAULT (datetime('now'))"
            ")"
        ),
        down="DROP TABLE IF EXISTS subscriptions",
    )
)

_MIGRATIONS.append(
    Migration(
        version=3,
        name="add_refresh_tokens_table",
        up=(
            "CREATE TABLE IF NOT EXISTS refresh_tokens ("
            "id TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, "
            "token_hash TEXT NOT NULL, "
            "expires_at REAL NOT NULL, "
            "revoked INTEGER DEFAULT 0, "
            "created_at REAL NOT NULL"
            ")"
        ),
        down="DROP TABLE IF EXISTS refresh_tokens",
    )
)

_MIGRATIONS.append(
    Migration(
        version=4,
        name="add_email_verifications_table",
        up=(
            "CREATE TABLE IF NOT EXISTS email_verifications ("
            "id TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, "
            "code TEXT NOT NULL, "
            "expires_at REAL NOT NULL, "
            "verified INTEGER DEFAULT 0, "
            "created_at REAL NOT NULL"
            ")"
        ),
        down="DROP TABLE IF EXISTS email_verifications",
    )
)

_MIGRATIONS.append(
    Migration(
        version=5,
        name="add_password_resets_table",
        up=(
            "CREATE TABLE IF NOT EXISTS password_resets ("
            "id TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, "
            "code TEXT NOT NULL, "
            "expires_at REAL NOT NULL, "
            "used INTEGER DEFAULT 0, "
            "created_at REAL NOT NULL"
            ")"
        ),
        down="DROP TABLE IF EXISTS password_resets",
    )
)

_MIGRATIONS.append(
    Migration(
        version=6,
        name="add_api_keys_table",
        up=(
            "CREATE TABLE IF NOT EXISTS api_keys ("
            "id TEXT PRIMARY KEY, "
            "user_id TEXT NOT NULL, "
            "provider TEXT NOT NULL, "
            "label TEXT NOT NULL DEFAULT '', "
            "ciphertext TEXT NOT NULL, "
            "created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL, "
            "last_used_at REAL"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_provider "
            "ON api_keys(user_id, provider)"
        ),
        down="DROP TABLE IF EXISTS api_keys",
    )
)

_MIGRATIONS.append(
    Migration(
        version=7,
        name="add_log_events_table",
        up=(
            "CREATE TABLE IF NOT EXISTS log_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts REAL NOT NULL, "
            "level TEXT NOT NULL, "
            "source TEXT NOT NULL DEFAULT '', "
            "message TEXT NOT NULL DEFAULT '', "
            "details TEXT, "
            "request_id TEXT DEFAULT ''"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_log_events_ts ON log_events(ts DESC);"
            "CREATE INDEX IF NOT EXISTS idx_log_events_level ON log_events(level);"
            "CREATE INDEX IF NOT EXISTS idx_log_events_level_ts "
            "ON log_events(level, ts DESC)"
        ),
        down="DROP TABLE IF EXISTS log_events",
    )
)

_MIGRATIONS.append(
    Migration(
        version=8,
        name="users_last_login_and_wal",
        up=(
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        ),
        down="SELECT 1",  # WAL mode can't be rolled back easily; no-op
    )
)


# ---------------------------------------------------------------------------
# Startup runner — call once from the app factory
# ---------------------------------------------------------------------------

def run_startup_migrations(db_path: str = "") -> list[int]:
    """Run all pending migrations at server startup. Returns applied versions."""
    from orchestra.code_agent.settings import settings
    path = db_path or settings.billing_db_path
    engine = MigrationEngine(db_url=f"sqlite:///{path}")
    engine.apply()
    applied = engine.status()
    log.info("Migrations status: %d total, %s applied", len(_MIGRATIONS), applied)
    return applied
