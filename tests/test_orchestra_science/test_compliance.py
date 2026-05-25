from __future__ import annotations

import time
import unittest

from orchestra.code_agent.compliance.consent_docs import (
    ConsentDocManager,
    ConsentDocStatus,
)
from orchestra.code_agent.compliance.data_lifecycle import (
    DataLifecycleManager,
    LegalHold,
    RetentionPolicy,
)
from orchestra.code_agent.compliance.disclaimers import (
    DisclaimerSystem,
    ProfessionalDisclaimer,
)
from orchestra.code_agent.compliance.emergency import (
    BreakGlassAccess,
    BreakGlassEvent,
)
from orchestra.code_agent.compliance.encryption import (
    FieldEncryptor,
    decrypt_field,
    encrypt_field,
)
from orchestra.code_agent.compliance.reporting import (
    ComplianceReportGenerator,
)
from orchestra.code_agent.compliance.roles import (
    ProfessionalRole,
    RoleManager,
)
from orchestra.code_agent.sessions.hardening import (
    SessionHardener,
    SessionPolicy,
    SessionRecord,
)


# ── Encryption at rest ─────────────────────────────────────────────────

class TestFieldEncryption(unittest.TestCase):

    def setUp(self):
        self.enc = FieldEncryptor("ab" * 32)

    def test_encrypt_decrypt_roundtrip(self):
        plain = "patient SSN: 078-05-1120"
        cipher = self.enc.encrypt(plain)
        self.assertNotEqual(cipher, plain)
        self.assertIn("=", cipher)
        decrypted = self.enc.decrypt(cipher)
        self.assertEqual(decrypted, plain)

    def test_different_keys_produce_different_ciphertexts(self):
        e1 = FieldEncryptor("aa" * 32)
        e2 = FieldEncryptor("bb" * 32)
        c1 = e1.encrypt("hello")
        c2 = e2.encrypt("hello")
        self.assertNotEqual(c1, c2)

    def test_module_level_encrypt_decrypt(self):
        plain = "test-data-123"
        cipher = encrypt_field(plain)
        self.assertEqual(decrypt_field(cipher), plain)

    def test_empty_string(self):
        cipher = self.enc.encrypt("")
        self.assertEqual(self.enc.decrypt(cipher), "")

    def test_unicode(self):
        plain = "Médecine légale — 患者情報"
        cipher = self.enc.encrypt(plain)
        self.assertEqual(self.enc.decrypt(cipher), plain)


# ── Professional roles ─────────────────────────────────────────────────

class TestProfessionalRoles(unittest.TestCase):

    def setUp(self):
        self.mgr = RoleManager()

    def test_assign_and_check_role(self):
        self.mgr.assign("user-1", ProfessionalRole.DOCTOR)
        self.assertTrue(self.mgr.has_role("user-1", ProfessionalRole.DOCTOR))

    def test_remove_role(self):
        self.mgr.assign("user-1", ProfessionalRole.NURSE)
        self.assertTrue(self.mgr.remove("user-1", ProfessionalRole.NURSE))
        self.assertFalse(self.mgr.has_role("user-1", ProfessionalRole.NURSE))

    def test_get_roles(self):
        self.mgr.assign("user-1", ProfessionalRole.ATTORNEY)
        roles = self.mgr.get_roles("user-1")
        self.assertIn(ProfessionalRole.ATTORNEY, roles)

    def test_has_any_role(self):
        self.mgr.assign("user-1", ProfessionalRole.BANKER)
        self.assertTrue(self.mgr.has_any_role("user-1", [ProfessionalRole.BANKER, ProfessionalRole.ADMIN]))
        self.assertFalse(self.mgr.has_any_role("user-1", [ProfessionalRole.DOCTOR]))

    def test_check_permission_healthcare(self):
        self.mgr.assign("user-1", ProfessionalRole.DOCTOR)
        self.assertTrue(self.mgr.check_permission("user-1", "healthcare", "view_phi"))
        self.assertTrue(self.mgr.check_permission("user-1", "healthcare", "write_phi"))
        self.assertFalse(self.mgr.check_permission("user-1", "healthcare", "view_financial"))

    def test_check_permission_legal(self):
        self.mgr.assign("user-1", ProfessionalRole.PARALEGAL)
        self.assertTrue(self.mgr.check_permission("user-1", "legal", "view_confidential"))
        self.assertTrue(self.mgr.check_permission("user-1", "legal", "write_confidential"))
        self.assertFalse(self.mgr.check_permission("user-1", "legal", "billing_access"))

    def test_check_permission_financial(self):
        self.mgr.assign("user-1", ProfessionalRole.COMPLIANCE_OFFICER)
        self.assertTrue(self.mgr.check_permission("user-1", "financial", "fraud_alert_access"))
        self.assertTrue(self.mgr.check_permission("user-1", "financial", "approve_large_transaction"))

    def test_emergency_capability(self):
        self.mgr.assign("user-1", ProfessionalRole.DOCTOR)
        self.assertTrue(self.mgr.has_emergency_capability("user-1"))
        self.mgr.assign("user-2", ProfessionalRole.NURSE)
        self.assertFalse(self.mgr.has_emergency_capability("user-2"))

    def test_multiple_roles(self):
        self.mgr.assign("user-1", ProfessionalRole.DOCTOR)
        self.mgr.assign("user-1", ProfessionalRole.ADMIN)
        self.assertEqual(len(self.mgr.get_roles("user-1")), 2)

    def test_unknown_user_returns_empty(self):
        self.assertEqual(self.mgr.get_roles("nobody"), [])

    def test_enum_values(self):
        self.assertEqual(ProfessionalRole.DOCTOR.value, "doctor")
        self.assertEqual(ProfessionalRole.ATTORNEY.value, "attorney")
        self.assertEqual(ProfessionalRole.BANKER.value, "banker")


# ── Consent documents ──────────────────────────────────────────────────

class TestConsentDocuments(unittest.TestCase):

    def setUp(self):
        self.mgr = ConsentDocManager()

    def test_create_document(self):
        doc = self.mgr.create_document("hipaa_consent", "patient-1", "dr-1")
        self.assertEqual(doc.status, ConsentDocStatus.PENDING)
        self.assertEqual(doc.patient_id, "patient-1")

    def test_sign_document(self):
        doc = self.mgr.create_document("baa", "patient-1")
        self.assertTrue(self.mgr.sign(doc.id))
        self.assertEqual(self.mgr.get(doc.id).status, ConsentDocStatus.SIGNED)

    def test_sign_nonexistent(self):
        self.assertFalse(self.mgr.sign("nope"))

    def test_revoke_document(self):
        doc = self.mgr.create_document("hipaa_consent", "patient-1")
        self.mgr.sign(doc.id)
        self.assertTrue(self.mgr.revoke(doc.id))
        self.assertEqual(self.mgr.get(doc.id).status, ConsentDocStatus.REVOKED)

    def test_revoke_unsigned_fails(self):
        doc = self.mgr.create_document("hipaa_consent", "patient-1")
        self.assertFalse(self.mgr.revoke(doc.id))

    def test_has_valid_consent(self):
        doc = self.mgr.create_document("hipaa_consent", "patient-1")
        self.mgr.sign(doc.id)
        self.assertTrue(self.mgr.has_valid_consent("patient-1", "hipaa_consent"))

    def test_has_valid_consent_revoked(self):
        doc = self.mgr.create_document("hipaa_consent", "patient-1")
        self.mgr.sign(doc.id)
        self.mgr.revoke(doc.id)
        self.assertFalse(self.mgr.has_valid_consent("patient-1", "hipaa_consent"))

    def test_list_by_patient(self):
        self.mgr.create_document("hipaa_consent", "patient-1")
        self.mgr.create_document("baa", "patient-1")
        self.assertEqual(len(self.mgr.list_by_patient("patient-1")), 2)

    def test_list_by_type(self):
        self.mgr.create_document("hipaa_consent", "p1")
        self.mgr.create_document("hipaa_consent", "p2")
        self.assertEqual(len(self.mgr.list_by_type("hipaa_consent")), 2)

    def test_get_patient_doc(self):
        self.mgr.create_document("baa", "patient-1")
        doc = self.mgr.get_patient_doc("patient-1", "baa")
        self.assertIsNotNone(doc)

    def test_templates_exist(self):
        from orchestra.code_agent.compliance.consent_docs import DOCUMENT_TEMPLATES
        self.assertIn("hipaa_consent", DOCUMENT_TEMPLATES)
        self.assertIn("baa", DOCUMENT_TEMPLATES)
        self.assertIn("engagement_letter", DOCUMENT_TEMPLATES)


# ── Break-glass emergency access ───────────────────────────────────────

class TestBreakGlass(unittest.TestCase):

    def setUp(self):
        self.bg = BreakGlassAccess(auto_expire_seconds=900)

    def test_grant_access(self):
        event = self.bg.grant("dr-1", "Patient cardiac arrest", "phi/patient-5")
        self.assertIsNotNone(event.id)
        self.assertTrue(self.bg.is_active(event.id))

    def test_justify(self):
        event = self.bg.grant("dr-1", "emergency", "record-1")
        self.assertTrue(self.bg.justify(event.id, "Follow-up note added"))
        self.assertTrue(self.bg.get(event.id).justified)

    def test_justify_nonexistent(self):
        self.assertFalse(self.bg.justify("nope"))

    def test_list_events_by_user(self):
        self.bg.grant("dr-1", "emergency", "r1")
        self.bg.grant("dr-1", "emergency", "r2")
        events = self.bg.list_events("dr-1")
        self.assertEqual(len(events), 2)

    def test_recent_unjustified(self):
        self.bg.grant("dr-1", "emergency", "r1")
        unjustified = self.bg.recent_unjustified(10)
        self.assertEqual(len(unjustified), 1)

    def test_summary(self):
        self.bg.grant("dr-1", "emergency", "r1")
        self.bg.grant("dr-2", "emergency", "r2")
        s = self.bg.summary()
        self.assertEqual(s["total_events"], 2)
        self.assertEqual(s["unjustified"], 2)

    def test_auto_expire(self):
        bg = BreakGlassAccess(auto_expire_seconds=-1)
        event = bg.grant("dr-1", "test", "r1")
        self.assertFalse(bg.is_active(event.id))

    def test_get_nonexistent(self):
        self.assertIsNone(self.bg.get("nope"))


# ── Data lifecycle ─────────────────────────────────────────────────────

class TestDataLifecycle(unittest.TestCase):

    def setUp(self):
        self.lc = DataLifecycleManager()

    def test_default_policies(self):
        policies = self.lc.list_policies()
        self.assertGreater(len(policies), 0)

    def test_register_policy(self):
        p = RetentionPolicy(name="custom", data_category="custom_cat", retention_days=30)
        self.lc.register_policy(p)
        self.assertIsNotNone(self.lc.get_policy("custom_cat"))

    def test_is_expired(self):
        self.assertTrue(self.lc.is_expired("session", time.time() - 10000000))

    def test_is_expired_within_policy(self):
        self.assertFalse(self.lc.is_expired("session", time.time()))

    def test_legal_hold_overrides_expiry(self):
        self.lc.create_legal_hold("Case X", ["session"], "admin")
        self.assertFalse(self.lc.is_expired("session", time.time() - 10000000))

    def test_create_and_release_legal_hold(self):
        hold = self.lc.create_legal_hold("Case Y", ["phi"], "admin")
        self.assertTrue(hold.active)
        self.lc.release_legal_hold(hold.id)
        self.assertFalse(self.lc.get_legal_hold(hold.id).active)

    def test_list_legal_holds(self):
        self.lc.create_legal_hold("Case Z", ["audit_log"], "admin")
        self.assertEqual(len(self.lc.list_legal_holds()), 1)

    def test_get_nonexistent_policy(self):
        self.assertIsNone(self.lc.get_policy("nonexistent"))


# ── Professional disclaimers ───────────────────────────────────────────

class TestDisclaimers(unittest.TestCase):

    def setUp(self):
        self.ds = DisclaimerSystem()

    def test_get_healthcare_disclaimers(self):
        disclaimers = self.ds.get_disclaimers("healthcare")
        self.assertGreater(len(disclaimers), 0)

    def test_get_legal_disclaimers(self):
        disclaimers = self.ds.get_disclaimers("legal")
        self.assertGreater(len(disclaimers), 0)

    def test_get_financial_disclaimers(self):
        disclaimers = self.ds.get_disclaimers("financial")
        self.assertGreater(len(disclaimers), 0)

    def test_add_custom_disclaimer(self):
        d = ProfessionalDisclaimer(domain="healthcare", title="Custom", body="Test", severity="warning")
        self.ds.add_disclaimer("healthcare", d)
        self.assertIn(d, self.ds.get_disclaimers("healthcare"))

    def test_append_to_output(self):
        result = self.ds.append_to_output("legal", "Here is your document")
        self.assertIn("Here is your document", result)
        self.assertIn("attorney-client", result)

    def test_append_to_output_unknown_domain(self):
        result = self.ds.append_to_output("astronomy", "Star data")
        self.assertEqual(result, "Star data")

    def test_list_domains(self):
        domains = self.ds.list_domains()
        self.assertIn("healthcare", domains)
        self.assertIn("legal", domains)
        self.assertIn("financial", domains)

    def test_general_disclaimers(self):
        disclaimers = self.ds.get_disclaimers("general")
        self.assertGreater(len(disclaimers), 0)


# ── Compliance reporting ───────────────────────────────────────────────

class TestComplianceReporting(unittest.TestCase):

    def setUp(self):
        self.reporter = ComplianceReportGenerator()

    def test_generate_report(self):
        report = self.reporter.generate()
        self.assertIsNotNone(report.generated_at)
        self.assertIn("hipaa", report.checks)
        self.assertIn("sox", report.checks)
        self.assertIn("gdpr", report.checks)

    def test_report_contains_controls(self):
        report = self.reporter.generate()
        hipaa = report.checks["hipaa"]
        self.assertGreater(len(hipaa["controls"]), 0)

    def test_export_json(self):
        report = self.reporter.generate()
        exported = self.reporter.export_json(report)
        self.assertIn("hipaa_compliant", exported)
        self.assertIn("summary", exported)

    def test_report_summary_format(self):
        report = self.reporter.generate()
        self.assertIn("HIPAA", report.summary)
        self.assertIn("SOX", report.summary)
        self.assertIn("GDPR", report.summary)


# ── Session hardening ──────────────────────────────────────────────────

class TestSessionHardening(unittest.TestCase):

    def setUp(self):
        self.sh = SessionHardener(SessionPolicy(
            idle_timeout_seconds=3600,
            max_concurrent_sessions=3,
            absolute_max_lifetime_seconds=86400,
        ))

    def test_register_session(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.assertTrue(self.sh.register_session(rec))

    def test_touch_session(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.sh.register_session(rec)
        self.assertTrue(self.sh.touch("s1"))

    def test_touch_nonexistent(self):
        self.assertFalse(self.sh.touch("nope"))

    def test_is_valid(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.sh.register_session(rec)
        self.assertTrue(self.sh.is_valid("s1"))

    def test_is_valid_nonexistent(self):
        self.assertFalse(self.sh.is_valid("nope"))

    def test_revoke_session(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.sh.register_session(rec)
        self.assertTrue(self.sh.revoke("s1"))
        self.assertFalse(self.sh.is_valid("s1"))

    def test_revoke_all_for_user(self):
        for i in range(3):
            rec = SessionRecord(session_id=f"s{i}", user_id="u1", created_at=time.time(), last_activity=time.time())
            self.sh.register_session(rec)
        self.assertEqual(self.sh.revoke_all_for_user("u1"), 3)

    def test_max_concurrent_sessions(self):
        sh = SessionHardener(SessionPolicy(max_concurrent_sessions=2))
        for i in range(5):
            rec = SessionRecord(session_id=f"s{i}", user_id="u1", created_at=time.time(), last_activity=time.time())
            sh.register_session(rec)
        active = sh.get_active_sessions("u1")
        self.assertLessEqual(len(active), 2)

    def test_count_active(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.sh.register_session(rec)
        self.assertEqual(self.sh.count_active(), 1)

    def test_cleanup_expired(self):
        sh = SessionHardener(SessionPolicy(idle_timeout_seconds=-1))
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        sh.register_session(rec)
        cleaned = sh.cleanup_expired()
        self.assertGreaterEqual(cleaned, 1)

    def test_get_active_sessions(self):
        rec = SessionRecord(session_id="s1", user_id="u1", created_at=time.time(), last_activity=time.time())
        self.sh.register_session(rec)
        sessions = self.sh.get_active_sessions("u1")
        self.assertEqual(len(sessions), 1)

    def test_set_policy(self):
        new_policy = SessionPolicy(idle_timeout_seconds=600)
        self.sh.set_policy(new_policy)
        self.assertEqual(self.sh._policy.idle_timeout_seconds, 600)


if __name__ == "__main__":
    unittest.main()
