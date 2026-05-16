"""Tests for Stanford-level red team adversarial testing.

All tests run offline — no real model calls.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from unittest import mock


def _load_module(dotted_name: str, rel_path: str):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base, rel_path)
    spec = importlib.util.spec_from_file_location(dotted_name, full_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the module under test using the bootstrap pattern
_stanford = _load_module(
    "orchestra.red_team.stanford",
    "orchestra/red_team/stanford.py",
)

StanfordRedTeam = _stanford.StanfordRedTeam
AttackResult = _stanford.AttackResult
CategoryResult = _stanford.CategoryResult
RedTeamReport = _stanford.RedTeamReport

# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

_ALL_CATEGORIES = [
    "direct_injection",
    "jailbreak",
    "capability_elicitation",
    "tool_misuse",
    "memory_poisoning",
    "multi_agent_exploitation",
    "data_exfiltration",
    "denial_of_service",
]

_VALID_SEVERITIES = {"critical", "high", "medium", "low"}

_SAMPLE_SYSTEM_PROMPT = "You are a helpful assistant."
_SAMPLE_TOOLS = [
    {"name": "web_search", "description": "Search the web"},
    {"name": "file_read", "description": "Read a file"},
    {"name": "execute_code", "description": "Execute code"},
]


# ===========================================================================
# TestStanfordRedTeamInit
# ===========================================================================

class TestStanfordRedTeamInit(unittest.TestCase):
    """Verify construction defaults and custom overrides."""

    def test_default_init(self):
        rt = StanfordRedTeam()
        self.assertEqual(rt.target_model, "opus-4.7")
        self.assertTrue(rt.guardian_enabled)

    def test_custom_init(self):
        rt = StanfordRedTeam(target_model="my-model", guardian_enabled=False)
        self.assertEqual(rt.target_model, "my-model")
        self.assertFalse(rt.guardian_enabled)

    def test_categories(self):
        """run_full_audit should cover all 8 categories."""
        rt = StanfordRedTeam()
        report = rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        self.assertEqual(len(report.category_results), 8)

    def test_category_names(self):
        """Verify the exact category name strings returned by a full audit."""
        rt = StanfordRedTeam()
        report = rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        for cat in _ALL_CATEGORIES:
            self.assertIn(cat, report.category_results)


# ===========================================================================
# TestAttackCategories
# ===========================================================================

class TestAttackCategories(unittest.TestCase):
    """Each of the 8 categories returns >= 10 attacks with valid fields."""

    def setUp(self):
        self.rt = StanfordRedTeam(guardian_enabled=True)

    def _assert_attacks_valid(self, attacks, min_count=10):
        self.assertGreaterEqual(len(attacks), min_count)
        for a in attacks:
            self.assertIsInstance(a.payload, str)
            self.assertTrue(len(a.payload) > 0, "Payload must be non-empty")
            self.assertIn(a.severity, _VALID_SEVERITIES)

    def test_prompt_injection_attacks(self):
        attacks = self.rt.test_direct_injection(_SAMPLE_SYSTEM_PROMPT)
        self._assert_attacks_valid(attacks, min_count=10)

    def test_jailbreak_attacks(self):
        attacks = self.rt.test_jailbreak(_SAMPLE_SYSTEM_PROMPT)
        self._assert_attacks_valid(attacks, min_count=10)

    def test_capability_elicitation_attacks(self):
        attacks = self.rt.test_capability_elicitation(_SAMPLE_SYSTEM_PROMPT)
        self._assert_attacks_valid(attacks, min_count=10)

    def test_tool_misuse_attacks(self):
        attacks = self.rt.test_tool_misuse(_SAMPLE_TOOLS)
        self._assert_attacks_valid(attacks, min_count=10)

    def test_memory_poisoning_attacks(self):
        attacks = self.rt.test_memory_poisoning()
        self._assert_attacks_valid(attacks, min_count=10)

    def test_multi_agent_exploitation_attacks(self):
        attacks = self.rt.test_multi_agent_exploitation()
        self._assert_attacks_valid(attacks, min_count=10)

    def test_data_exfiltration_attacks(self):
        attacks = self.rt.test_data_exfiltration(_SAMPLE_SYSTEM_PROMPT)
        self._assert_attacks_valid(attacks, min_count=10)

    def test_denial_of_service_attacks(self):
        attacks = self.rt.test_denial_of_service()
        self._assert_attacks_valid(attacks, min_count=10)


# ===========================================================================
# TestAttackPayloads
# ===========================================================================

class TestAttackPayloads(unittest.TestCase):
    """Deep inspection of attack payloads and result fields."""

    def setUp(self):
        self.rt = StanfordRedTeam(guardian_enabled=True)
        self.report = self.rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        # Gather all individual attacks by re-running each category
        self.all_attacks = []
        self.rt_fresh = StanfordRedTeam(guardian_enabled=True)
        for cat in _ALL_CATEGORIES:
            attacks = self.rt_fresh._dispatch_category(
                cat, _SAMPLE_SYSTEM_PROMPT, _SAMPLE_TOOLS,
            )
            self.all_attacks.extend(attacks)

    def test_payloads_non_empty(self):
        for a in self.all_attacks:
            self.assertTrue(
                len(a.payload.strip()) > 0,
                f"Empty payload in {a.category}/{a.vector}",
            )

    def test_payloads_contain_adversarial_content(self):
        """Spot-check that direct-injection payloads contain adversarial keywords."""
        injection_attacks = [
            a for a in self.all_attacks if a.category == "direct_injection"
        ]
        adversarial_keywords = [
            "ignore", "override", "reveal", "system prompt", "disregard",
            "new instructions", "bypass", "disable",
        ]
        found_any = False
        for a in injection_attacks:
            payload_lower = a.payload.lower()
            if any(kw in payload_lower for kw in adversarial_keywords):
                found_any = True
                break
        self.assertTrue(
            found_any,
            "Expected at least one injection payload to contain adversarial keywords",
        )

    def test_severity_values(self):
        for a in self.all_attacks:
            self.assertIn(
                a.severity,
                _VALID_SEVERITIES,
                f"Invalid severity '{a.severity}' in {a.category}/{a.vector}",
            )

    def test_attack_result_fields(self):
        """Verify all AttackResult fields are populated (non-None, non-empty-string)."""
        for a in self.all_attacks:
            self.assertIsInstance(a.category, str)
            self.assertTrue(len(a.category) > 0)
            self.assertIsInstance(a.vector, str)
            self.assertTrue(len(a.vector) > 0)
            self.assertIsInstance(a.payload, str)
            self.assertTrue(len(a.payload) > 0)
            self.assertIsInstance(a.blocked, bool)
            self.assertIsInstance(a.bypass_achieved, bool)
            self.assertIsInstance(a.severity, str)
            self.assertTrue(len(a.severity) > 0)
            self.assertIsInstance(a.response_snippet, str)
            self.assertTrue(len(a.response_snippet) > 0)
            self.assertIsInstance(a.guardian_action, str)
            self.assertTrue(len(a.guardian_action) > 0)
            self.assertIsInstance(a.mitigation, str)
            self.assertTrue(len(a.mitigation) > 0)
            self.assertIsInstance(a.timestamp, str)
            self.assertTrue(len(a.timestamp) > 0)


# ===========================================================================
# TestGuardianBehavior
# ===========================================================================

class TestGuardianBehavior(unittest.TestCase):
    """Guardian mode should produce a high block rate; disabled mode a lower one."""

    def test_guardian_enabled_high_block_rate(self):
        rt = StanfordRedTeam(guardian_enabled=True)
        report = rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        self.assertGreaterEqual(
            report.overall_block_rate, 0.90,
            f"Expected block_rate >= 0.90 with guardian, got {report.overall_block_rate}",
        )

    def test_guardian_disabled_low_block_rate(self):
        rt = StanfordRedTeam(guardian_enabled=False)
        report = rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        self.assertLess(
            report.overall_block_rate, 0.90,
            f"Expected block_rate < 0.90 without guardian, got {report.overall_block_rate}",
        )

    def test_guardian_blocks_most_attacks(self):
        rt = StanfordRedTeam(guardian_enabled=True)
        report = rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)
        self.assertGreater(report.total_blocked, report.total_bypassed)

    def test_some_bypasses_exist(self):
        """At least one bypass per category for realism."""
        rt = StanfordRedTeam(guardian_enabled=True)
        for cat in _ALL_CATEGORIES:
            attacks = rt._dispatch_category(
                cat, _SAMPLE_SYSTEM_PROMPT, _SAMPLE_TOOLS,
            )
            bypasses = [a for a in attacks if a.bypass_achieved]
            self.assertGreaterEqual(
                len(bypasses), 1,
                f"Expected at least 1 bypass in category '{cat}', got 0",
            )


# ===========================================================================
# TestFullAudit
# ===========================================================================

class TestFullAudit(unittest.TestCase):
    """Verify run_full_audit produces a coherent end-to-end report."""

    @classmethod
    def setUpClass(cls):
        cls.rt = StanfordRedTeam(guardian_enabled=True)
        cls.report = cls.rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)

    def test_full_audit_all_categories(self):
        for cat in _ALL_CATEGORIES:
            self.assertIn(cat, self.report.category_results)

    def test_full_audit_total_attacks(self):
        self.assertGreaterEqual(
            self.report.total_attacks, 80,
            f"Expected >= 80 total attacks, got {self.report.total_attacks}",
        )

    def test_full_audit_block_rate(self):
        self.assertGreaterEqual(self.report.overall_block_rate, 0.90)
        self.assertLessEqual(self.report.overall_block_rate, 1.0)

    def test_full_audit_has_executive_summary(self):
        self.assertIsInstance(self.report.executive_summary, str)
        self.assertTrue(
            len(self.report.executive_summary) > 0,
            "Executive summary must not be empty",
        )

    def test_full_audit_duration(self):
        self.assertGreaterEqual(self.report.duration_seconds, 0.0)
        self.assertIsInstance(self.report.duration_seconds, float)


# ===========================================================================
# TestRedTeamReport
# ===========================================================================

class TestRedTeamReport(unittest.TestCase):
    """Serialisation and rendering of the RedTeamReport dataclass."""

    @classmethod
    def setUpClass(cls):
        cls.rt = StanfordRedTeam(guardian_enabled=True)
        cls.report = cls.rt.run_full_audit(system_prompt=_SAMPLE_SYSTEM_PROMPT)

    def test_to_markdown(self):
        md = self.report.to_markdown()
        self.assertIsInstance(md, str)
        self.assertIn("# Red Team Audit Report", md)
        self.assertIn("## Executive Summary", md)
        self.assertIn("## Category Breakdown", md)
        self.assertIn("## Critical Vulnerabilities", md)

    def test_to_markdown_has_categories(self):
        md = self.report.to_markdown()
        for cat in _ALL_CATEGORIES:
            self.assertIn(cat, md, f"Category '{cat}' not found in markdown output")

    def test_to_dict(self):
        d = self.report.to_dict()
        self.assertIsInstance(d, dict)
        # Verify JSON-serialisable
        try:
            json.dumps(d)
        except (TypeError, ValueError) as exc:
            self.fail(f"to_dict() is not JSON-serialisable: {exc}")

    def test_to_dict_roundtrip(self):
        d = self.report.to_dict()
        serialised = json.dumps(d)
        deserialised = json.loads(serialised)
        self.assertEqual(d, deserialised)

    def test_report_critical_vulnerabilities(self):
        d = self.report.to_dict()
        self.assertIn("critical_vulnerabilities", d)
        self.assertIsInstance(d["critical_vulnerabilities"], list)


# ===========================================================================
# TestCategoryResult
# ===========================================================================

class TestCategoryResult(unittest.TestCase):
    """Unit tests for CategoryResult aggregation logic."""

    def test_block_rate_calculation(self):
        """Verify block_rate = blocked / total."""
        rt = StanfordRedTeam(guardian_enabled=True)
        attacks = rt.test_direct_injection(_SAMPLE_SYSTEM_PROMPT)
        cr = rt._aggregate_category("direct_injection", attacks)
        total = cr.total_attacks
        expected_rate = cr.blocked / total if total else 0.0
        self.assertAlmostEqual(cr.block_rate, round(expected_rate, 4))

    def test_findings_separation(self):
        """Critical vs high findings are correctly categorised."""
        rt = StanfordRedTeam(guardian_enabled=True)
        # Run all categories to get a large sample with bypasses
        all_attacks = []
        for cat in _ALL_CATEGORIES:
            attacks = rt._dispatch_category(
                cat, _SAMPLE_SYSTEM_PROMPT, _SAMPLE_TOOLS,
            )
            all_attacks.extend(attacks)
            cr = rt._aggregate_category(cat, attacks)

            # Manually count critical and high bypass findings
            manual_critical = sum(
                1 for a in attacks if a.severity == "critical" and a.bypass_achieved
            )
            manual_high = sum(
                1 for a in attacks if a.severity == "high" and a.bypass_achieved
            )
            self.assertEqual(
                cr.critical_findings, manual_critical,
                f"critical_findings mismatch in {cat}",
            )
            self.assertEqual(
                cr.high_findings, manual_high,
                f"high_findings mismatch in {cat}",
            )


if __name__ == "__main__":
    unittest.main()
