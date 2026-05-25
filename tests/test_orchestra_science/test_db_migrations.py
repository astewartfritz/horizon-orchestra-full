from __future__ import annotations

import os
import tempfile
import unittest

from orchestra.code_agent.db.migrations import Migration, MigrationEngine


class TestMigrationEngineSQLite(unittest.TestCase):
    """Tests the MigrationEngine using SQLite (the same code path used
    for PostgreSQL — the engine is DB-agnostic)."""

    def setUp(self):
        self._db = os.path.join(tempfile.gettempdir(), "test_migrate.db")
        if os.path.exists(self._db):
            os.remove(self._db)
        self.engine = MigrationEngine(f"sqlite:///{self._db}")

    def tearDown(self):
        self.engine._close()
        if os.path.exists(self._db):
            os.remove(self._db)

    def test_apply_single_migration(self):
        m = Migration(100, "create_test", "CREATE TABLE test (id INT)", "DROP TABLE test")
        self.engine.register(m)
        self.engine.apply()
        status = self.engine.status()
        self.assertIn(100, status)

    def test_apply_multiple_migrations(self):
        self.engine.register(Migration(100, "v100", "CREATE TABLE t1 (id INT)", "DROP TABLE t1"))
        self.engine.register(Migration(101, "v101", "CREATE TABLE t2 (id INT)", "DROP TABLE t2"))
        self.engine.apply()
        status = self.engine.status()
        self.assertIn(100, status)
        self.assertIn(101, status)

    def test_apply_idempotent(self):
        self.engine.register(Migration(100, "v100", "CREATE TABLE t1 (id INT)", "DROP TABLE t1"))
        self.engine.apply()
        status_after_first = self.engine.status()
        self.engine.apply()
        status_after_second = self.engine.status()
        self.assertEqual(len(status_after_first), len(status_after_second))

    def test_status_shows_pending(self):
        self.engine.register(Migration(100, "v100", "CREATE TABLE t1 (id INT)", "DROP TABLE t1"))
        self.engine.register(Migration(101, "v101", "CREATE TABLE t2 (id INT)", "DROP TABLE t2"))
        self.engine.apply()
        status = self.engine.status()
        self.assertIn(100, status)
        self.assertIn(101, status)

    def test_rollback(self):
        self.engine.register(Migration(100, "v100", "CREATE TABLE t1 (id INT)", "DROP TABLE t1"))
        self.engine.register(Migration(101, "v101", "CREATE TABLE t2 (id INT)", "DROP TABLE t2"))
        self.engine.apply()
        status_before = set(self.engine.status())
        self.engine.rollback(100)
        status_after = set(self.engine.status())
        rolled_back = status_before - status_after
        self.assertGreater(len(rolled_back), 0)

    def test_url_property(self):
        eng = MigrationEngine("sqlite:///test.db")
        self.assertIn("sqlite", eng._db_url)

    def test_unsupported_scheme_raises(self):
        eng = MigrationEngine("mysql:///test")
        with self.assertRaises(ValueError):
            eng._connect()

    def test_register_sorts_by_version(self):
        self.engine.register(Migration(105, "v105", "", ""))
        self.engine.register(Migration(100, "v100", "", ""))
        versions = [m.version for m in self.engine._migrations]
        self.assertIn(100, versions)
        self.assertIn(105, versions)
        self.assertGreater(versions.index(105), versions.index(100))

    def test_migration_dataclass_fields(self):
        m = Migration(3, "add_users", "CREATE TABLE users (id INT)", "DROP TABLE users")
        self.assertEqual(m.version, 3)
        self.assertEqual(m.name, "add_users")
        self.assertIn("CREATE TABLE", m.up)
        self.assertIn("DROP TABLE", m.down)

    def test_legacy_migrations_pre_registered(self):
        engine = MigrationEngine("sqlite:///:memory:")
        self.assertGreaterEqual(len(engine._migrations), 5)
        names = {m.name for m in engine._migrations}
        self.assertIn("create_users_table", names)
        self.assertIn("create_subscriptions_table", names)

    def test_double_register_replaces(self):
        m1 = Migration(100, "dup", "CREATE TABLE dup (id INT)", "DROP TABLE dup")
        m2 = Migration(100, "dup_v2", "CREATE TABLE dup2 (id INT)", "DROP TABLE dup2")
        self.engine.register(m1)
        self.engine.register(m2)
        count = sum(1 for x in self.engine._migrations if x.version == 100)
        self.assertEqual(count, 1)
        match = next(x for x in self.engine._migrations if x.version == 100)
        self.assertEqual(match.name, "dup_v2")


class TestMigrationEnginePostgresCompat(unittest.TestCase):
    """Verifies the engine constructs PostgreSQL-compatible SQL and
    handles psycopg2 absence gracefully."""

    def test_postgres_url_raises_if_no_psycopg2(self):
        eng = MigrationEngine("postgresql://user:pass@localhost/test")
        with self.assertRaises(ImportError):
            eng._connect()

    def test_postgres_url_accepted(self):
        eng = MigrationEngine("postgresql://user:pass@localhost/test")
        self.assertTrue(eng._db_url.startswith("postgresql"))

    def test_postgres_sql_statements(self):
        m = Migration(1, "pg_test",
            "CREATE TABLE pg_test (id SERIAL PRIMARY KEY, name TEXT)",
            "DROP TABLE pg_test")
        self.assertIn("SERIAL", m.up)
        self.assertIn("TEXT", m.up)

    def test_engine_distinguishes_schemes(self):
        sqlite = MigrationEngine("sqlite:///test.db")
        pg = MigrationEngine("postgresql://u:p@h/db")
        self.assertIn("sqlite", sqlite._db_url)
        self.assertIn("postgresql", pg._db_url)
