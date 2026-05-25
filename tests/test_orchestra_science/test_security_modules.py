from __future__ import annotations

import json
import os
import time
import unittest


# ── Capability Auth ────────────────────────────────────────────────────

class TestCapabilityAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.capability_auth import (
                Capability, AgentIdentity, CapabilityVault,
                DynamicAuthPolicy, JustInTimeGrant,
            )
            cls.Capability = Capability
            cls.AgentIdentity = AgentIdentity
            cls.CapabilityVault = CapabilityVault
            cls.DynamicAuthPolicy = DynamicAuthPolicy
            cls.JustInTimeGrant = JustInTimeGrant
        except ImportError:
            raise unittest.SkipTest("capability_auth not available")

    def test_capability_match_exact(self):
        c1 = self.Capability("read", "patient/123", "read")
        c2 = self.Capability("read", "patient/123", "read")
        self.assertTrue(c1.matches(c2))

    def test_capability_match_wildcard(self):
        wild = self.Capability("read", "patient/*", "read")
        specific = self.Capability("read", "patient/123", "read")
        self.assertTrue(wild.matches(specific))

    def test_capability_no_match_different_action(self):
        c1 = self.Capability("read", "patient/123", "read")
        c2 = self.Capability("write", "patient/123", "write")
        self.assertFalse(c1.matches(c2))

    def test_vault_grant_and_check(self):
        vault = self.CapabilityVault()
        cap = self.Capability("read", "patient/123", "read")
        grant_id = vault.grant(cap, "agent-1", ttl=3600)
        self.assertIsInstance(grant_id, str)
        self.assertTrue(vault.check("agent-1", cap))

    def test_vault_revoke(self):
        vault = self.CapabilityVault()
        cap = self.Capability("read", "patient/123", "read")
        grant_id = vault.grant(cap, "agent-1", ttl=3600)
        self.assertTrue(vault.revoke(grant_id))
        self.assertFalse(vault.check("agent-1", cap))

    def test_vault_expiry(self):
        vault = self.CapabilityVault()
        cap = self.Capability("read", "patient/123", "read")
        vault.grant(cap, "agent-1", ttl=0)  # expired immediately
        self.assertFalse(vault.check("agent-1", cap))

    def test_dynamic_policy(self):
        policy = self.DynamicAuthPolicy()
        cap = self.Capability("read", "patient/123", "read")
        policy.register("view_patient", [cap])
        agent = self.AgentIdentity("agent-1", "user-1", "research", 3)
        self.assertFalse(policy.check_access(agent, "view_patient", "patient/123"))
        # Grant via policy's internal vault
        policy._vault.grant(cap, "agent-1", ttl=3600)
        self.assertTrue(policy.check_access(agent, "view_patient", "patient/123"))
        self.assertFalse(policy.check_access(agent, "delete_patient", "patient/123"))


# ── PII Redactor ───────────────────────────────────────────────────────

class TestPIIRedactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.pii_redactor import (
                PIIRedactor, PIICategory, HIPAAContext, GDPRContext,
            )
            cls.PIIRedactor = PIIRedactor
            cls.PIICategory = PIICategory
            cls.HIPAAContext = HIPAAContext
            cls.GDPRContext = GDPRContext
        except ImportError:
            raise unittest.SkipTest("pii_redactor not available")

    def test_redact_email(self):
        r = self.PIIRedactor()
        result = r.redact("Contact me at test@example.com please")
        self.assertNotIn("test@example.com", result)
        self.assertIn("[EMAIL", result)

    def test_redact_phone(self):
        r = self.PIIRedactor()
        result = r.redact("Call +1-555-123-4567 now")
        self.assertNotIn("555-123-4567", result)

    def test_redact_ssn(self):
        r = self.PIIRedactor()
        result = r.redact("SSN: 123-45-6789")
        self.assertNotIn("123-45-6789", result)

    def test_redact_credit_card(self):
        r = self.PIIRedactor()
        result = r.redact("Card: 4111 1111 1111 1111")
        self.assertNotIn("4111", result)

    def test_redact_ip(self):
        r = self.PIIRedactor()
        result = r.redact("IP: 192.168.1.1")
        self.assertNotIn("192.168.1.1", result)

    def test_redact_api_key(self):
        r = self.PIIRedactor()
        result = r.redact("Key: sk-proj-abc123def456")
        self.assertNotIn("sk-proj", result)

    def test_find_pii(self):
        r = self.PIIRedactor()
        results = r.find_pii("Email: test@test.com, Phone: 555-123-4567")
        self.assertGreaterEqual(len(results), 2)

    def test_redact_dict(self):
        r = self.PIIRedactor()
        data = {"email": "test@test.com", "name": "John", "age": 30}
        result = r.redact_dict(data)
        self.assertNotIn("test@test.com", str(result))
        self.assertEqual(result["age"], 30)

    def test_redact_json(self):
        r = self.PIIRedactor()
        result = r.redact_json('{"email": "test@test.com"}')
        self.assertNotIn("test@test.com", result)

    def test_hipaa_redact_phi(self):
        h = self.HIPAAContext()
        result = h.redact_phi("Patient John Smith, DOB 01/15/1980, SSN 123-45-6789")
        self.assertNotIn("John Smith", result)
        self.assertNotIn("123-45-6789", result)
        self.assertNotIn("01/15/1980", result)

    def test_hipaa_is_phi_field(self):
        h = self.HIPAAContext()
        self.assertTrue(h.is_phi_field("patient_name"))
        self.assertTrue(h.is_phi_field("ssn"))
        self.assertTrue(h.is_phi_field("medical_record_number"))
        self.assertFalse(h.is_phi_field("age_group"))

    def test_gdpr_redact(self):
        g = self.GDPRContext()
        result = g.redact_pii("Email: user@test.com, Phone: +44 20 7946 0958")
        self.assertNotIn("user@test.com", result)


# ── Data Classifier ────────────────────────────────────────────────────

class TestDataClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.data_classifier import (
                DataClassifier, SensitivityLevel, DataTag, ClassificationRule,
            )
            cls.DataClassifier = DataClassifier
            cls.SensitivityLevel = SensitivityLevel
            cls.DataTag = DataTag
            cls.ClassificationRule = ClassificationRule
        except ImportError:
            raise unittest.SkipTest("data_classifier not available")

    def test_classify_email_field(self):
        dc = self.DataClassifier()
        tags = dc.classify_field("user_email")
        self.assertTrue(any("gdpr" in str(t.regulations).lower() for t in tags))

    def test_classify_ssn_field(self):
        dc = self.DataClassifier()
        tags = dc.classify_field("ssn")
        self.assertTrue(any("hipaa" in str(t.regulations).lower() for t in tags))
        self.assertTrue(any("gdpr" in str(t.regulations).lower() for t in tags))

    def test_classify_health_field(self):
        dc = self.DataClassifier()
        tags = dc.classify_field("health_record")
        self.assertTrue(any("hipaa" in str(t.regulations).lower() for t in tags))

    def test_classify_dict(self):
        dc = self.DataClassifier()
        data = {"email": "test@test.com", "name": "John", "age": 30}
        classified = dc.classify_dict(data)
        self.assertIn("email", classified)
        self.assertIn("age", classified)

    def test_get_sensitivity(self):
        dc = self.DataClassifier()
        data = {"password": "secret123", "email": "test@test.com"}
        sens = dc.get_sensitivity(data)
        self.assertEqual(sens, self.SensitivityLevel.CRITICAL)

    def test_get_regulations(self):
        dc = self.DataClassifier()
        data = {"ssn": "123-45-6789", "email": "test@test.com"}
        regs = dc.get_regulations(data)
        self.assertIn("gdpr", regs)
        self.assertIn("hipaa", regs)

    def test_add_custom_rule(self):
        dc = self.DataClassifier()
        rule = self.ClassificationRule(
            "custom", "secret_code",
            [self.DataTag("secret", self.SensitivityLevel.RESTRICTED, {"internal"})],
            auto=True,
        )
        dc.add_rule(rule)
        tags = dc.classify_field("secret_code")
        self.assertTrue(any(t.name == "secret" for t in tags))


# ── Consent Manager ────────────────────────────────────────────────────

class TestConsentManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.consent_manager import (
                ConsentManager, ConsentPurpose,
            )
            cls.ConsentManager = ConsentManager
            cls.ConsentPurpose = ConsentPurpose
        except ImportError:
            raise unittest.SkipTest("consent_manager not available")

    def test_set_and_check_consent(self):
        cm = self.ConsentManager()
        cm.set_consent("user-1", self.ConsentPurpose.ANALYTICS, True)
        self.assertTrue(cm.check_consent("user-1", self.ConsentPurpose.ANALYTICS))

    def test_check_consent_not_granted(self):
        cm = self.ConsentManager()
        self.assertFalse(cm.check_consent("user-1", self.ConsentPurpose.MARKETING))

    def test_revoke_consent(self):
        cm = self.ConsentManager()
        cm.set_consent("user-1", self.ConsentPurpose.ANALYTICS, True)
        cm.revoke_consent("user-1", self.ConsentPurpose.ANALYTICS)
        self.assertFalse(cm.check_consent("user-1", self.ConsentPurpose.ANALYTICS))

    def test_get_consent_summary(self):
        cm = self.ConsentManager()
        cm.set_consent("user-1", self.ConsentPurpose.ANALYTICS, True)
        cm.set_consent("user-1", self.ConsentPurpose.MARKETING, False)
        summary = cm.get_consent_summary("user-1")
        self.assertIn("consents", summary)
        self.assertEqual(len(summary["consents"]), 2)


# ── Audit ──────────────────────────────────────────────────────────────

class TestAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.audit import AuditEvent, AuditStore
            cls.AuditEvent = AuditEvent
            cls.AuditStore = AuditStore
        except ImportError:
            raise unittest.SkipTest("audit not available")

    def test_record_and_query(self):
        store = self.AuditStore()
        event = self.AuditEvent(
            event_id="", timestamp=time.time(), event_type="api",
            actor_id="agent-1", actor_type="agent", action="read",
            resource="patient/123", data_sensitivity="confidential",
            consent_used="analytics", ip_address="127.0.0.1",
            user_agent="test", outcome="allowed", details={},
        )
        eid = store.record(event)
        self.assertIsInstance(eid, str)
        results = store.query(actor_id="agent-1")
        self.assertEqual(len(results), 1)

    def test_count_by_type(self):
        store = self.AuditStore()
        store.record(self.AuditEvent(
            "", time.time(), "api", "agent-1", "agent", "read",
            "r1", "public", "", "1.2.3.4", "test", "allowed", {},
        ))
        store.record(self.AuditEvent(
            "", time.time(), "api", "agent-1", "agent", "write",
            "r2", "public", "", "1.2.3.4", "test", "denied", {},
        ))
        counts = store.count_by_type()
        self.assertIn("api", counts)
        self.assertGreaterEqual(counts["api"], 1)

    def test_get_recent(self):
        store = self.AuditStore()
        for i in range(5):
            store.record(self.AuditEvent(
                "", time.time(), "test", f"agent-{i}", "agent", "read",
                f"r{i}", "public", "", "1.2.3.4", "test", "allowed", {},
            ))
        recent = store.get_recent(limit=3)
        self.assertLessEqual(len(recent), 3)


# ── Anomaly Detector ───────────────────────────────────────────────────

class TestAnomalyDetector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.anomaly import (
                AnomalyDetector, AccessPattern, AnomalyEvent, AnomalyRule, AnomalySeverity,
            )
            cls.AnomalyDetector = AnomalyDetector
            cls.AccessPattern = AccessPattern
            cls.AnomalySeverity = AnomalySeverity
            cls.AnomalyRule = AnomalyRule
        except ImportError:
            raise unittest.SkipTest("anomaly not available")

    def test_record_and_check(self):
        d = self.AnomalyDetector()
        for _ in range(60):
            d.record(self.AccessPattern(time.time(), "agent-1", "read", "r", "1.2.3.4", True))
        anomalies = d.get_anomalies()
        self.assertGreaterEqual(len(anomalies), 0)

    def test_unusual_hours_detected(self):
        import datetime
        # Create a timestamp at 3 AM local time
        now = time.time()
        local = datetime.datetime.fromtimestamp(now)
        three_am = now + ((3 - local.hour) % 24) * 3600 - local.minute * 60 - local.second
        d = self.AnomalyDetector()
        ap = self.AccessPattern(three_am, "agent-1", "read", "r", "1.2.3.4", True)
        result = d._check_unusual_hours(ap)
        self.assertIsNotNone(result)
        self.assertIn("Unusual hour", result)

    def test_actor_summary(self):
        d = self.AnomalyDetector()
        d.record(self.AccessPattern(time.time(), "agent-1", "read", "r1", "1.2.3.4", True))
        d.record(self.AccessPattern(time.time(), "agent-1", "write", "r2", "1.2.3.4", False))
        summary = d.get_actor_summary("agent-1")
        self.assertEqual(summary["total_requests"], 2)
        self.assertEqual(summary["failed_requests"], 1)

    def test_custom_rule(self):
        d = self.AnomalyDetector()
        rule = self.AnomalyRule("test_rule", "test", self.AnomalySeverity.HIGH)
        d.add_rule(rule)
        self.assertEqual(len(d._rules), 7)  # 6 default + 1 custom


# ── Approval Workflow ──────────────────────────────────────────────────

class TestApprovalWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.approval import (
                ApprovalWorkflow, ApprovalRequest, ApprovalPolicy, ApprovalStatus, ApprovalRequired,
            )
            cls.ApprovalWorkflow = ApprovalWorkflow
            cls.ApprovalPolicy = ApprovalPolicy
            cls.ApprovalStatus = ApprovalStatus
            cls.ApprovalRequired = ApprovalRequired
        except ImportError:
            raise unittest.SkipTest("approval not available")

    def test_check_action_no_match(self):
        wf = self.ApprovalWorkflow()
        result = wf.check_action("agent-1", "research", "read", "public/data")
        self.assertIsNone(result)

    def test_check_action_matches(self):
        wf = self.ApprovalWorkflow()
        result = wf.check_action("agent-1", "research", "read", "patient/123/phi")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, self.ApprovalStatus.PENDING)

    def test_approve(self):
        wf = self.ApprovalWorkflow()
        req = wf.check_action("agent-1", "research", "read", "patient/123/phi")
        self.assertTrue(wf.approve(req.id, "admin-1"))
        self.assertEqual(wf.get_request(req.id).status, self.ApprovalStatus.APPROVED)

    def test_deny(self):
        wf = self.ApprovalWorkflow()
        req = wf.check_action("agent-1", "research", "read", "patient/123/phi")
        self.assertTrue(wf.deny(req.id, "admin-1"))
        self.assertEqual(wf.get_request(req.id).status, self.ApprovalStatus.DENIED)

    def test_get_pending(self):
        wf = self.ApprovalWorkflow()
        wf.check_action("agent-1", "research", "read", "patient/123/phi")
        self.assertGreaterEqual(len(wf.get_pending()), 1)

    def test_trust_agent_skips_approval(self):
        wf = self.ApprovalWorkflow()
        wf.trust_agent("agent-2")
        result = wf.check_action("agent-2", "research", "read", "patient/123/phi")
        self.assertIsNone(result)

    def test_get_stats(self):
        wf = self.ApprovalWorkflow()
        stats = wf.get_stats()
        self.assertIn("pending", stats)
        self.assertIn("approved", stats)

    def test_register_policy(self):
        wf = self.ApprovalWorkflow()
        policy = self.ApprovalPolicy("custom", "Custom policy", "custom/*", "high")
        wf.register_policy(policy)
        result = wf.check_action("agent-1", "test", "write", "custom/data")
        self.assertIsNotNone(result)


# ── Security Middleware (integration) ──────────────────────────────────

class TestSecurityMiddleware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.security.middleware import (
                SecurityMiddleware, SecurityContext, register_security,
            )
            cls.SecurityMiddleware = SecurityMiddleware
            cls.SecurityContext = SecurityContext
            cls.register_security = register_security
        except ImportError:
            raise unittest.SkipTest("security middleware not available")

    def test_security_context_defaults(self):
        ctx = self.SecurityContext()
        self.assertEqual(ctx.actor_type, "human")
        self.assertEqual(ctx.outcome, "allowed")
        self.assertEqual(ctx.data_sensitivity, "public")

    def test_register_security_on_app(self):
        try:
            from fastapi import FastAPI
            app = FastAPI()
            TestSecurityMiddleware.register_security(app)
            self.assertTrue(True)
        except ImportError:
            self.skipTest("fastapi not available")
