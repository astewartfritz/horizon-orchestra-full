from __future__ import annotations

import json
import logging
import time
import unittest

from orchestra.code_agent.adk.governance import AdkGovernanceMonitor
from orchestra.code_agent.adk.intents import IntentLibrary, IntentTemplate, QueryBuilder
from orchestra.code_agent.adk.playbook import PlaybookEntry, PromptPlaybook, ReplayEngine, ReplayRecord
from orchestra.code_agent.adk.testing_sandbox import AgentTestingSandbox, MockApiResponse, ScenarioDefinition
from orchestra.code_agent.agent_headers.models import Intent
from orchestra.code_agent.logging.json import JsonFormatter, setup_json_logging
from orchestra.code_agent.sla.calculator import SlaGuarantee, SlaTracker


# ── Structured JSON Logging ────────────────────────────────────────────

class TestJsonLogging(unittest.TestCase):

    def test_json_formatter_outputs_valid_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "mod.py", 42, "hello world", (), None)
        output = formatter.format(record)
        parsed = json.loads(output)
        self.assertEqual(parsed["message"], "hello world")
        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["logger"], "test")

    def test_json_formatter_includes_location(self):
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.WARNING, "app.py", 99, "warn", (), None)
        output = json.loads(formatter.format(record))
        self.assertEqual(output["module"], "app")
        self.assertEqual(output["line"], 99)

    def test_json_formatter_exception_info(self):
        formatter = JsonFormatter()
        import sys
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
            record = logging.LogRecord("test", logging.ERROR, "x.py", 1, "fail", (), exc_info=exc_info)
        output = json.loads(formatter.format(record))
        self.assertIn("exception", output)
        self.assertEqual(output["exception"]["type"], "ValueError")
        self.assertIn("test error", output["exception"]["value"])

    def test_setup_json_logging_does_not_crash(self):
        setup_json_logging()
        root = logging.getLogger()
        self.assertTrue(any(isinstance(h.formatter, JsonFormatter) for h in root.handlers))


# ── SLA Guarantees ──────────────────────────────────────────────────────

class TestSlaTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = SlaTracker()
        self.tracker.register(SlaGuarantee("test_api", 100.0, 99.0, "Test SLA"))

    def test_register_and_list(self):
        guarantees = self.tracker.list_guarantees()
        names = [g.name for g in guarantees]
        self.assertIn("test_api", names)

    def test_record_and_report(self):
        for _ in range(10):
            self.tracker.record("test_api", 50.0)
        report = self.tracker.report("test_api", 3600.0)
        self.assertIsNotNone(report)
        self.assertEqual(report.total_requests, 10)
        self.assertEqual(report.met, 10)
        self.assertAlmostEqual(report.compliance_pct, 100.0)

    def test_report_with_violations(self):
        for _ in range(8):
            self.tracker.record("test_api", 50.0)
        for _ in range(2):
            self.tracker.record("test_api", 200.0)
        report = self.tracker.report("test_api")
        self.assertEqual(report.violated, 2)
        self.assertAlmostEqual(report.compliance_pct, 80.0)

    def test_report_nonexistent_guarantee(self):
        self.assertIsNone(self.tracker.report("nope"))

    def test_default_guarantees(self):
        defaults = SlaTracker.default_guarantees()
        self.assertGreater(len(defaults), 0)
        names = [g.name for g in defaults]
        self.assertIn("chat_completion", names)
        self.assertIn("api_gateway", names)

    def test_report_percentiles(self):
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            self.tracker.record("test_api", ms)
        report = self.tracker.report("test_api")
        self.assertIn(report.p50_ms, (50.0, 55.0, 60.0))
        self.assertAlmostEqual(report.p95_ms, 95.0, delta=10)

    def test_prune_does_not_crash(self):
        self.tracker.record("test_api", 10.0)
        pruned = self.tracker.prune(max_age=0)
        self.assertGreaterEqual(pruned, 0)


# ── ADK: Prompt Playbook ────────────────────────────────────────────────

class TestPromptPlaybook(unittest.TestCase):

    def setUp(self):
        self.playbook = PromptPlaybook()

    def test_register_and_get(self):
        entry = PlaybookEntry(name="test", intent=Intent.DATA_QUERY, prompt_template="Query {x}")
        self.playbook.register(entry)
        self.assertIsNotNone(self.playbook.get(entry.id))

    def test_build_prompt(self):
        entry = PlaybookEntry(name="test", intent=Intent.DATA_QUERY, prompt_template="Hello {name}")
        self.playbook.register(entry)
        prompt = self.playbook.build_prompt(entry.id, {"name": "World"})
        self.assertEqual(prompt, "Hello World")

    def test_build_prompt_missing_entry(self):
        self.assertIsNone(self.playbook.build_prompt("nope", {}))

    def test_find_by_intent(self):
        self.playbook.register(PlaybookEntry(name="a", intent=Intent.ANALYSIS, prompt_template=""))
        self.playbook.register(PlaybookEntry(name="b", intent=Intent.ANALYSIS, prompt_template=""))
        self.assertEqual(len(self.playbook.find_by_intent(Intent.ANALYSIS)), 2)

    def test_find_by_tag(self):
        entry = PlaybookEntry(name="x", intent=Intent.DATA_QUERY, prompt_template="", tags=["metrics"])
        self.playbook.register(entry)
        self.assertEqual(len(self.playbook.find_by_tag("metrics")), 1)

    def test_remove(self):
        entry = PlaybookEntry(name="del", intent=Intent.UNKNOWN, prompt_template="")
        self.playbook.register(entry)
        self.assertTrue(self.playbook.remove(entry.id))
        self.assertFalse(self.playbook.remove(entry.id))

    def test_default_entries(self):
        defaults = PromptPlaybook.default_entries()
        self.assertGreater(len(defaults), 0)
        names = [e.name for e in defaults]
        self.assertIn("order_status", names)
        self.assertIn("generate_report", names)

    def test_list_all(self):
        self.playbook.register(PlaybookEntry(name="a", intent=Intent.DATA_QUERY, prompt_template=""))
        self.assertEqual(len(self.playbook.list_all()), 1)


# ── ADK: Replay Engine ─────────────────────────────────────────────────

class TestReplayEngine(unittest.TestCase):

    def setUp(self):
        self.engine = ReplayEngine()

    def test_record_and_get(self):
        rid = self.engine.record(ReplayRecord(intent="data_query", prompt="q", response="a"))
        record = self.engine.get(rid)
        self.assertIsNotNone(record)
        self.assertEqual(record.prompt, "q")
        self.assertEqual(record.response, "a")

    def test_replay(self):
        rid = self.engine.record(ReplayRecord(intent="test", prompt="q", response="answer"))
        self.assertEqual(self.engine.replay(rid), "answer")

    def test_replay_missing(self):
        self.assertIsNone(self.engine.replay("nope"))

    def test_find_by_intent(self):
        self.engine.record(ReplayRecord(intent="orders", prompt="q1", response="a1"))
        self.engine.record(ReplayRecord(intent="orders", prompt="q2", response="a2"))
        results = self.engine.find_by_intent("orders")
        self.assertEqual(len(results), 2)

    def test_find_by_tag(self):
        self.engine.record(ReplayRecord(intent="t", prompt="q", response="a", tags=["bug"]))
        self.assertEqual(len(self.engine.find_by_tag("bug")), 1)

    def test_list_recent(self):
        self.engine.record(ReplayRecord(intent="t", prompt="q", response="a"))
        self.assertEqual(len(self.engine.list_recent(10)), 1)

    def test_export_json(self):
        rid = self.engine.record(ReplayRecord(intent="test", prompt="q", response="a"))
        data = self.engine.export(rid)
        self.assertIsNotNone(data)
        parsed = json.loads(data)
        self.assertEqual(parsed["intent"], "test")

    def test_import_json(self):
        data = json.dumps({"intent": "orders", "prompt": "check", "response": "ok"})
        rid = self.engine.import_json(data)
        self.assertIsNotNone(rid)
        self.assertEqual(self.engine.get(rid).intent, "orders")

    def test_import_invalid_json(self):
        self.assertIsNone(self.engine.import_json("not json"))

    def test_delete(self):
        rid = self.engine.record(ReplayRecord(intent="t", prompt="q", response="a"))
        self.assertTrue(self.engine.delete(rid))
        self.assertFalse(self.engine.delete(rid))

    def test_export_missing(self):
        self.assertIsNone(self.engine.export("nope"))


# ── ADK: Intent Templates & Query Builders ──────────────────────────────

class TestIntentLibrary(unittest.TestCase):

    def setUp(self):
        self.library = IntentLibrary()

    def test_register_and_get(self):
        tpl = IntentTemplate(name="check_order", intent=Intent.ORDER_STATUS_CHECK,
                             header_value="order_status_check", required_fields=["order_id"])
        self.library.register(tpl)
        self.assertIsNotNone(self.library.get("check_order"))

    def test_find_by_intent(self):
        tpl = IntentTemplate(name="t1", intent=Intent.ANALYSIS, header_value="analysis")
        self.library.register(tpl)
        results = self.library.find_by_intent(Intent.ANALYSIS)
        self.assertEqual(len(results), 1)

    def test_create_builder(self):
        tpl = IntentTemplate(name="t1", intent=Intent.DATA_QUERY, header_value="dq",
                             query_structure={"q": ""}, required_fields=["q"])
        self.library.register(tpl)
        builder = self.library.create_builder("t1")
        self.assertIsNotNone(builder)

    def test_create_builder_missing(self):
        self.assertIsNone(self.library.create_builder("nope"))

    def test_remove(self):
        tpl = IntentTemplate(name="del", intent=Intent.UNKNOWN, header_value="x")
        self.library.register(tpl)
        self.assertTrue(self.library.remove("del"))
        self.assertFalse(self.library.remove("del"))

    def test_default_templates(self):
        defaults = IntentLibrary.default_templates()
        self.assertGreater(len(defaults), 0)
        names = [t.name for t in defaults]
        self.assertIn("check_order", names)
        self.assertIn("run_data_query", names)

    def test_list_all(self):
        self.library.register(IntentTemplate(name="a", intent=Intent.UNKNOWN, header_value="x"))
        self.assertEqual(len(self.library.list_all()), 1)


class TestQueryBuilder(unittest.TestCase):

    def test_build_valid(self):
        tpl = IntentTemplate(name="t", intent=Intent.DATA_QUERY, header_value="dq",
                             query_structure={"q": "", "limit": 10}, required_fields=["q"])
        builder = QueryBuilder(tpl)
        result = builder.build({"q": "SELECT 1"})
        self.assertEqual(result["q"], "SELECT 1")
        self.assertEqual(result["limit"], 10)

    def test_build_missing_field_raises(self):
        tpl = IntentTemplate(name="t", intent=Intent.DATA_QUERY, header_value="dq",
                             query_structure={}, required_fields=["required_field"])
        builder = QueryBuilder(tpl)
        with self.assertRaises(ValueError):
            builder.build({})

    def test_validate(self):
        tpl = IntentTemplate(name="t", intent=Intent.DATA_QUERY, header_value="dq",
                             required_fields=["a", "b"])
        builder = QueryBuilder(tpl)
        missing = builder.validate({"a": 1})
        self.assertEqual(missing, ["b"])

    def test_template_property(self):
        tpl = IntentTemplate(name="t", intent=Intent.UNKNOWN, header_value="x")
        builder = QueryBuilder(tpl)
        self.assertIs(builder.template, tpl)


# ── ADK: Testing Sandbox ───────────────────────────────────────────────

class TestAgentTestingSandbox(unittest.TestCase):

    def setUp(self):
        self.sandbox = AgentTestingSandbox()

    def test_register_and_get_scenario(self):
        sc = ScenarioDefinition(name="test", intent=Intent.ORDER_STATUS_CHECK,
                                input_prompt="check order")
        sid = self.sandbox.register_scenario(sc)
        self.assertIsNotNone(self.sandbox.get_scenario(sid))

    def test_list_scenarios(self):
        self.sandbox.register_scenario(ScenarioDefinition(name="s1", input_prompt="p"))
        self.assertEqual(len(self.sandbox.list_scenarios()), 1)

    def test_run_scenario_not_found(self):
        result = self.sandbox.run_scenario("nope", lambda x: "ok")
        self.assertFalse(result["success"])

    def test_run_scenario_success(self):
        sid = self.sandbox.register_scenario(
            ScenarioDefinition(name="s1", input_prompt="hello")
        )
        result = self.sandbox.run_scenario(sid, lambda x: "world")
        self.assertTrue(result["success"])
        self.assertEqual(result["responses"], ["world"])

    def test_run_scenario_with_handler(self):
        sid = self.sandbox.register_scenario(
            ScenarioDefinition(name="s2", input_prompt="trigger"),
        )
        self.sandbox.register_handler(sid, lambda x: MockApiResponse(status_code=200, body={"ok": True}))
        result = self.sandbox.run_scenario(sid, lambda x: "processed")
        self.assertTrue(result["success"])

    def test_run_scenario_agent_error(self):
        sid = self.sandbox.register_scenario(
            ScenarioDefinition(name="error", input_prompt="fail")
        )
        result = self.sandbox.run_scenario(sid, lambda x: (_ for _ in ()).throw(Exception("boom")))
        self.assertFalse(result["success"])
        self.assertIn("boom", result["errors"])

    def test_get_results(self):
        sid = self.sandbox.register_scenario(ScenarioDefinition(name="r", input_prompt="p"))
        self.sandbox.run_scenario(sid, lambda x: "ok")
        self.assertEqual(len(self.sandbox.get_results(sid)), 1)

    def test_summary(self):
        sid = self.sandbox.register_scenario(ScenarioDefinition(name="s", input_prompt="p"))
        self.sandbox.run_scenario(sid, lambda x: "ok")
        summary = self.sandbox.summary()
        self.assertEqual(summary["total_runs"], 1)
        self.assertEqual(summary["passed"], 1)

    def test_default_scenarios(self):
        defaults = AgentTestingSandbox.default_scenarios()
        self.assertGreater(len(defaults), 0)
        names = [s.name for s in defaults]
        self.assertIn("order_status_happy", names)
        self.assertIn("api_rate_limited", names)

    def test_handler_error_in_run(self):
        sid = self.sandbox.register_scenario(ScenarioDefinition(name="h", input_prompt="p"))
        self.sandbox.register_handler(sid, lambda x: (_ for _ in ()).throw(Exception("handler fail")))
        result = self.sandbox.run_scenario(sid, lambda x: "ok")
        self.assertFalse(result["success"])
        self.assertIn("handler fail", result["errors"])


# ── ADK: Governance Monitor ─────────────────────────────────────────────

class TestGovernanceMonitor(unittest.TestCase):

    def setUp(self):
        self.gov = AdkGovernanceMonitor()

    def test_record_call_success(self):
        self.gov.record_call("data_query", True, 50.0)
        report = self.gov.report()
        self.assertEqual(report.total_calls, 1)
        self.assertEqual(report.intent_success_count, 1)

    def test_record_call_failure(self):
        self.gov.record_call("data_query", False, 100.0, "timeout")
        report = self.gov.report()
        self.assertEqual(report.intent_failure_count, 1)
        self.assertEqual(report.error_count, 1)
        self.assertEqual(report.error_frequency.get("timeout"), 1)

    def test_record_anomaly(self):
        self.gov.record_anomaly("unusual spike")
        report = self.gov.report()
        self.assertEqual(report.anomaly_count, 1)

    def test_record_violation(self):
        self.gov.record_violation("rate_limit_exceeded")
        report = self.gov.report()
        self.assertEqual(report.governance_violations, 1)

    def test_intent_stats(self):
        self.gov.record_call("orders", True, 10.0)
        self.gov.record_call("orders", True, 20.0)
        stats = self.gov.intent_stats("orders")
        self.assertEqual(stats["total_calls"], 2)
        self.assertAlmostEqual(stats["success_rate"], 100.0)

    def test_intent_stats_empty(self):
        stats = self.gov.intent_stats("nonexistent")
        self.assertEqual(stats["total_calls"], 0)

    def test_recent_anomalies(self):
        self.gov.record_anomaly("anomaly-1")
        self.gov.record_anomaly("anomaly-2")
        anomalies = self.gov.recent_anomalies(10)
        self.assertEqual(len(anomalies), 2)

    def test_recent_violations(self):
        self.gov.record_violation("v1")
        violations = self.gov.recent_violations(10)
        self.assertEqual(len(violations), 1)

    def test_report_empty(self):
        report = self.gov.report()
        self.assertEqual(report.total_calls, 0)
        self.assertEqual(report.intent_success_rate, 0.0)

    def test_latency_tracking(self):
        self.gov.record_call("api", True, 100.0)
        self.gov.record_call("api", True, 200.0)
        report = self.gov.report()
        self.assertAlmostEqual(report.avg_latency_ms, 150.0, delta=1)


if __name__ == "__main__":
    unittest.main()
