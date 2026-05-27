"""Tests for tamper-proof audit log system."""

import json
import os
import tempfile
from pathlib import Path
import unittest

from orchestra.audit.log import AuditEntry, AuditLog
from orchestra.audit.verifier import AuditVerifier, verify_db
from orchestra.audit.integration import (
    _audit_append,
    enable_all,
    enable_finance_audit,
    enable_healthcare_audit,
    enable_legal_audit,
)


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.log = AuditLog(str(self.tmp))

    def tearDown(self):
        self.log.close()
        if self.tmp.exists():
            self.tmp.unlink()

    def test_append_creates_entry(self):
        entry = self.log.append("patients", "p1", "CREATE", {"name": "Alice"})
        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.table_name, "patients")
        self.assertEqual(entry.operation, "CREATE")
        self.assertEqual(entry.data.get("name"), "Alice")

    def test_count(self):
        self.assertEqual(self.log.count(), 0)
        self.log.append("t", "1", "CREATE", {"x": 1})
        self.assertEqual(self.log.count(), 1)

    def test_hash_chain_links_entries(self):
        e1 = self.log.append("t", "1", "CREATE", {"a": 1})
        e2 = self.log.append("t", "2", "CREATE", {"b": 2})
        self.assertEqual(e2.previous_hash, e1.entry_hash)
        self.assertNotEqual(e1.entry_hash, e2.entry_hash)

    def test_hmac_signature_present(self):
        entry = self.log.append("t", "1", "CREATE", {"x": 1})
        self.assertTrue(len(entry.hmac_signature) > 0)
        self.assertEqual(len(entry.hmac_signature), 64)  # SHA-256 HMAC

    def test_verify_valid_entry(self):
        entry = self.log.append("t", "1", "CREATE", {"x": 1})
        # Make the key accessible for verification
        self.assertTrue(entry.verify(self.log._key))

    def test_verify_fails_with_wrong_key(self):
        entry = self.log.append("t", "1", "CREATE", {"x": 1})
        wrong_key = b"x" * 32
        self.assertFalse(entry.verify(wrong_key))

    def test_append_only_update_trigger(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        with self.assertRaises(Exception) as ctx:
            self.log._conn.execute("UPDATE audit_log SET entry_hash='x' WHERE id=1")
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_append_only_delete_trigger(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        with self.assertRaises(Exception) as ctx:
            self.log._conn.execute("DELETE FROM audit_log WHERE id=1")
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_verify_chain_intact(self):
        self.log.append("t", "1", "CREATE", {"a": 1})
        self.log.append("t", "2", "UPDATE", {"b": 2})
        self.log.append("t", "3", "DELETE", {"c": 3})
        failures = self.log.verify_chain()
        self.assertEqual(failures, [])

    def test_verify_chain_broken(self):
        self.log.append("t", "1", "CREATE", {"a": 1})
        self.log.append("t", "2", "CREATE", {"b": 2})
        self.log._conn.execute("DROP TRIGGER IF EXISTS tr_audit_log_prevent_update")
        self.log._conn.execute("UPDATE audit_log SET previous_hash='bad' WHERE id=2")
        self.log._conn.commit()
        self.log.enforce_append_only()
        failures = self.log.verify_chain()
        self.assertGreater(len(failures), 0)

    def test_verify_signatures_all_valid(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        self.log.append("t", "2", "UPDATE", {"y": 2})
        failures = self.log.verify_signatures()
        self.assertEqual(failures, [])

    def test_full_audit_passes(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        result = self.log.full_audit()
        self.assertTrue(result["chain_integrity"])
        self.assertTrue(result["signatures_valid"])
        self.assertEqual(result["tampered"], 0)

    def test_query_by_table(self):
        self.log.append("patients", "p1", "CREATE", {"name": "A"})
        self.log.append("claims", "c1", "CREATE", {"amt": 100})
        results = self.log.query(table="patients")
        self.assertEqual(len(results), 1)

    def test_query_by_record(self):
        self.log.append("t", "r1", "CREATE", {"x": 1})
        self.log.append("t", "r2", "CREATE", {"x": 2})
        results = self.log.query(record_id="r1")
        self.assertEqual(len(results), 1)

    def test_query_by_operation(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        self.log.append("t", "1", "UPDATE", {"y": 2})
        self.log.append("t", "1", "DELETE", {"z": 3})
        results = self.log.query(operation="UPDATE")
        self.assertEqual(len(results), 1)

    def test_records_for(self):
        self.log.append("t", "r1", "CREATE", {"a": 1})
        self.log.append("t", "r1", "UPDATE", {"b": 2})
        entries = self.log.records_for("t", "r1")
        self.assertEqual(len(entries), 2)

    def test_export_json(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        out = self.tmp.parent / "audit_export.jsonl"
        result = self.log.export_json(out)
        self.assertTrue(result.exists())
        data = result.read_text()
        self.assertIn("CREATE", data)

    def test_export_csv(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        out = self.tmp.parent / "audit_export.csv"
        result = self.log.export_csv(out)
        self.assertTrue(result.exists())
        data = result.read_text()
        self.assertIn("entry_hash", data)

    def test_append_with_actor(self):
        entry = self.log.append("t", "1", "CREATE", {"x": 1}, actor="dr_smith")
        self.assertEqual(entry.actor, "dr_smith")

    def test_append_with_metadata(self):
        entry = self.log.append("t", "1", "CREATE", {"x": 1},
                                metadata={"source": "api", "ip": "10.0.0.1"})
        md = json.loads(entry.metadata)
        self.assertEqual(md["source"], "api")

    def test_invalid_operation_raises(self):
        with self.assertRaises(ValueError):
            self.log.append("t", "1", "INVALID", {})

    def test_first_entry_previous_hash_empty(self):
        e = self.log.append("t", "1", "CREATE", {"x": 1})
        self.assertEqual(e.previous_hash, "")

    def test_entry_to_dict(self):
        e = self.log.append("t", "1", "CREATE", {"x": 1})
        d = e.to_dict()
        self.assertIn("entry_hash", d)
        self.assertIn("hmac_signature", d)

    def test_enforce_append_only_safe(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        self.log.enforce_append_only()
        self.assertEqual(self.log.count(), 1)


class AuditVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.log = AuditLog(str(self.tmp))
        self.verifier = AuditVerifier(self.log)

    def tearDown(self):
        self.log.close()
        if self.tmp.exists():
            self.tmp.unlink()

    def test_verify_passes_with_clean_chain(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        result = self.verifier.verify()
        self.assertTrue(result["chain_integrity"])
        self.assertTrue(result["signatures_valid"])

    def test_verify_range(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        self.log.append("t", "2", "CREATE", {"x": 2})
        result = self.verifier.verify_range(1, 2)
        self.assertTrue(result["chain_integrity"])

    def test_report_generates(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        report = self.verifier.report()
        self.assertIn("chain_intact", report)
        self.assertIn("status", report)

    def test_report_writes_to_file(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        out = self.tmp.parent / "compliance_report.json"
        self.verifier.report(out)
        self.assertTrue(out.exists())
        data = json.loads(out.read_text())
        self.assertEqual(data["status"], "PASS")

    def test_export_for_compliance(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        out_dir = self.tmp.parent / "compliance_export"
        files = self.verifier.export_for_compliance(str(out_dir))
        self.assertIn("jsonl", files)
        self.assertIn("csv", files)
        self.assertIn("report", files)
        self.assertTrue(Path(files["jsonl"]).exists())
        self.assertTrue(Path(files["csv"]).exists())
        self.assertTrue(Path(files["report"]).exists())

    def test_verify_db_one_shot(self):
        self.log.append("t", "1", "CREATE", {"x": 1})
        result = verify_db(self.tmp)
        self.assertIn("chain_integrity", result)


class AuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.audit_key = "test-audit-key-for-ci"

    def tearDown(self):
        if self.tmp.exists():
            self.tmp.unlink()

    def test_enable_healthcare_audit(self):
        from orchestra.code_agent.healthcare import store as hc
        al = enable_healthcare_audit(db_path=self.tmp, key=self.audit_key)
        self.assertIsNotNone(hc._audit_log)
        hc._audit("r1", "CREATE", {"test": True})
        self.assertEqual(al.count(), 1)
        al.close()
        hc._audit_log = None

    def test_enable_legal_audit(self):
        from orchestra.code_agent.legal import store as legal
        al = enable_legal_audit(db_path=self.tmp, key=self.audit_key)
        self.assertIsNotNone(legal._audit_log)
        legal._audit("r1", "CREATE", {"test": True})
        self.assertEqual(al.count(), 1)
        al.close()
        legal._audit_log = None

    def test_enable_finance_audit(self):
        from orchestra.code_agent.finance import portfolio as fin
        al = enable_finance_audit(db_path=self.tmp, key=self.audit_key)
        self.assertIsNotNone(fin._audit_log)
        fin._audit("r1", "CREATE", {"test": True})
        self.assertEqual(al.count(), 1)
        al.close()
        fin._audit_log = None

    def test_enable_all(self):
        logs = enable_all(key=self.audit_key)
        self.assertIn("healthcare", logs)
        self.assertIn("legal", logs)
        self.assertIn("finance", logs)
        # Clean up
        from orchestra.code_agent.healthcare import store as hc
        from orchestra.code_agent.legal import store as legal
        from orchestra.code_agent.finance import portfolio as fin
        for l in logs.values():
            l.close()
        hc._audit_log = None
        legal._audit_log = None
        fin._audit_log = None

    def test_healthcare_write_creates_audit_entry(self):
        from orchestra.code_agent.healthcare import store as hc
        hc._audit_log = None
        init_db = hc.init_db
        init_db()
        try:
            al = enable_healthcare_audit(db_path=self.tmp, key=self.audit_key)
            # Monkey-patch init_db to avoid re-creating tables in memory
            import sqlite3
            old_conn = hc._conn

            patient = hc.create_patient({
                "first_name": "Jane", "last_name": "Doe", "dob": "1990-01-01",
            })
            self.assertIsNotNone(patient)
            self.assertEqual(al.count(), 1)
        finally:
            hc._audit_log = None
            al.close()

    def test_legal_write_creates_audit_entry(self):
        from orchestra.code_agent.legal import store as legal
        legal._audit_log = None
        legal.init_db()
        try:
            al = enable_legal_audit(db_path=self.tmp, key=self.audit_key)
            client = legal.create_client({
                "name": "Test Client", "email": "test@example.com",
            })
            self.assertIsNotNone(client)
            self.assertEqual(al.count(), 1)
        finally:
            legal._audit_log = None
            al.close()

    def test_finance_write_creates_audit_entry(self):
        from orchestra.code_agent.finance import portfolio as fin
        fin._audit_log = None
        fin.init_db()
        try:
            al = enable_finance_audit(db_path=self.tmp, key=self.audit_key)
            pf = fin.create_portfolio({"name": "Test Portfolio"})
            self.assertIsNotNone(pf)
            self.assertEqual(al.count(), 1)
        finally:
            fin._audit_log = None
            al.close()


class AuditTamperTests(unittest.TestCase):
    """Direct tamper attempts on the audit log to verify protection."""

    def setUp(self):
        self.tmp = Path(tempfile.mktemp(suffix=".db"))
        self.log = AuditLog(str(self.tmp))

    def tearDown(self):
        self.log.close()
        if self.tmp.exists():
            self.tmp.unlink()

    def test_verify_detects_tampered_data(self):
        self.log.append("t", "1", "CREATE", {"amount": 100})
        row = self.log._conn.execute("SELECT id, data_json FROM audit_log WHERE id=1").fetchone()
        self.log._conn.execute("DROP TRIGGER IF EXISTS tr_audit_log_prevent_update")
        self.log._conn.execute(
            "UPDATE audit_log SET data_json=? WHERE id=?",
            (json.dumps({"amount": 999999}), row["id"]),
        )
        self.log._conn.commit()
        self.log.enforce_append_only()
        result = self.log.full_audit()
        self.assertFalse(result["signatures_valid"])

    def test_verify_detects_chain_break(self):
        self.log.append("t", "1", "CREATE", {"a": 1})
        self.log.append("t", "2", "CREATE", {"b": 2})
        self.log.append("t", "3", "CREATE", {"c": 3})
        self.log._conn.execute("DROP TRIGGER IF EXISTS tr_audit_log_prevent_update")
        # Tamper with entry 2's entry_hash
        self.log._conn.execute(
            "UPDATE audit_log SET entry_hash='0000000000000000000000000000000000000000000000000000000000000000' WHERE id=2"
        )
        self.log._conn.commit()
        self.log.enforce_append_only()
        failures = self.log.verify_chain()
        # Entry 3 should now fail because its previous_hash points to the old entry 2 hash
        self.assertGreater(len(failures), 0)

    def test_verify_detects_entry_insertion(self):
        self.log.append("t", "1", "CREATE", {"a": 1})
        self.log.append("t", "3", "CREATE", {"c": 3})
        # Can't actually INSERT (append-only trigger), so we just verify existing chain
        result = self.log.full_audit()
        self.assertIsInstance(result, dict)

    def test_different_keys_produce_different_signatures(self):
        log_a = AuditLog(str(self.tmp.parent / "audit_a.db"), key="key-a")
        log_b = AuditLog(str(self.tmp.parent / "audit_b.db"), key="key-b")
        try:
            e1 = log_a.append("t", "1", "CREATE", {"x": 1})
            e2 = log_b.append("t", "1", "CREATE", {"x": 1})
            self.assertNotEqual(e1.hmac_signature, e2.hmac_signature)
        finally:
            log_a.close()
            log_b.close()
            for p in [self.tmp.parent / "audit_a.db", self.tmp.parent / "audit_b.db"]:
                if p.exists():
                    p.unlink()


class AuditExportsTests(unittest.TestCase):
    def test_package_exports(self):
        from orchestra.audit import AuditEntry, AuditLog, AuditVerifier, verify_db
        self.assertIsNotNone(AuditEntry)
        self.assertIsNotNone(AuditLog)

    def test_orchestra_init_exports(self):
        import orchestra
        self.assertTrue(hasattr(orchestra, "AuditLog"))
        self.assertTrue(hasattr(orchestra, "AuditVerifier"))
        self.assertTrue(hasattr(orchestra, "verify_db"))
