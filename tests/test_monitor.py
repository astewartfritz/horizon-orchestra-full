"""Tests for monitoring system (metrics, alerts, dashboard)."""

import json
import os
import time
from pathlib import Path

from orchestra.code_agent.monitor import (
    AlertCondition,
    AlertEvent,
    AlertManager,
    AlertRule,
    AlertState,
    MetricPoint,
    MetricsCollector,
    MonitorDashboard,
)

TEST_METRICS_DB = ".test-agent-metrics.db"


def _fresh_db():
    path = f".test-mon-{os.getpid()}-{time.time_ns()}.db"
    return path


def setup_function():
    Path(TEST_METRICS_DB).unlink(missing_ok=True)


def teardown_function():
    Path(TEST_METRICS_DB).unlink(missing_ok=True)


class TestMetricsCollector:
    def test_increment_and_query(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.increment("test_counter", 1.0, env="test")
            c.increment("test_counter", 2.0, env="test")
            pts = c.query("test_counter")
            assert len(pts) == 2
            assert pts[0].value == 2.0
            assert pts[0].labels == {"env": "test"}
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_gauge(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.gauge("memory_usage", 512.5, unit="MB")
            pts = c.query("memory_usage")
            assert len(pts) == 1
            assert pts[0].value == 512.5
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_observe_histogram(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            for v in [1.0, 2.0, 3.0]:
                c.observe("latency_ms", v)
            agg = c.aggregate("latency_ms")
            assert agg["count"] == 3
            assert agg["sum"] == 6.0
            assert agg["min"] == 1.0
            assert agg["max"] == 3.0
            assert agg["avg"] == 2.0
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_list_metrics(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.increment("a", 1)
            c.gauge("b", 2.0)
            c.observe("c", 3.0)
            metrics = c.list_metrics()
            names = {m["name"] for m in metrics}
            assert names == {"a", "b", "c"}
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_summary(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.increment("x", 1)
            s = c.summary()
            assert s["total_points"] == 1
            assert s["total_metrics"] == 1
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_prune(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.increment("old", 1)
            now = time.time()
            deleted = c.prune(now + 1)
            assert deleted <= 1
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)

    def test_multiple_labels(self):
        db = _fresh_db()
        c = MetricsCollector(db)
        try:
            c.increment("test", 1, env="prod", region="us-east-1")
            pts = c.query("test")
            assert pts[0].labels == {"env": "prod", "region": "us-east-1"}
        finally:
            c.close()
            Path(db).unlink(missing_ok=True)


class TestAlertManager:
    def test_add_and_list_rules(self):
        mgr = AlertManager(_fresh_db())
        rule = AlertRule(name="high_latency", metric_name="latency_ms", condition=AlertCondition.GT, threshold=1000)
        mgr.add_rule(rule)
        rules = mgr.list_rules()
        assert len(rules) == 1
        assert rules[0].name == "high_latency"
        assert rules[0].threshold == 1000

    def test_remove_rule(self):
        mgr = AlertManager(_fresh_db())
        rule = AlertRule(name="test_rule", metric_name="x", condition=AlertCondition.GT, threshold=10)
        mgr.add_rule(rule)
        assert mgr.remove_rule("test_rule") is True
        assert mgr.remove_rule("nonexistent") is False

    def test_alert_fires_when_threshold_exceeded(self):
        db = _fresh_db()
        collector = MetricsCollector(db)
        mgr = AlertManager(db)
        rule = AlertRule(name="high_cpu", metric_name="cpu", condition=AlertCondition.GT, threshold=80, cooldown_seconds=0)
        mgr.add_rule(rule)
        collector.gauge("cpu", 95.0)
        fired = mgr.check(collector)
        assert len(fired) == 1
        assert fired[0].rule_name == "high_cpu"
        assert fired[0].state in (AlertState.WARNING, AlertState.CRITICAL)
        collector.close()

    def test_alert_respects_cooldown(self):
        db = _fresh_db()
        collector = MetricsCollector(db)
        mgr = AlertManager(db)
        rule = AlertRule(name="cooldown_test", metric_name="cpu", condition=AlertCondition.GT, threshold=50, cooldown_seconds=3600)
        mgr.add_rule(rule)
        collector.gauge("cpu", 99.0)
        fired1 = mgr.check(collector)
        assert len(fired1) == 1
        fired2 = mgr.check(collector)
        assert len(fired2) == 0
        collector.close()

    def test_alert_callback(self):
        db = _fresh_db()
        collector = MetricsCollector(db)
        mgr = AlertManager(db)
        events = []
        mgr.on_alert(lambda e: events.append(e))
        rule = AlertRule(name="cb_test", metric_name="x", condition=AlertCondition.GT, threshold=0, cooldown_seconds=0)
        mgr.add_rule(rule)
        collector.increment("x", 1)
        mgr.check(collector)
        assert len(events) == 1
        collector.close()

    def test_get_history(self):
        mgr = AlertManager(_fresh_db())
        ev = AlertEvent(rule_name="test", state=AlertState.WARNING, metric_value=90, threshold=80, message="test alert", timestamp=time.time())
        mgr._persist_event(ev)
        history = mgr.get_history("test")
        assert len(history) == 1
        assert history[0].rule_name == "test"


class TestMonitorDashboard:
    def test_render_empty(self):
        import tempfile
        db = Path(tempfile.mktemp(suffix=".db"))
        try:
            c = MetricsCollector(db)
            dash = MonitorDashboard(c)
            output = dash.render()
            assert "CODE AGENT MONITOR DASHBOARD" in output
            assert "Overview" in output
            assert "Metrics" in output
            dash.close()
        finally:
            db.unlink(missing_ok=True)

    def test_render_with_metrics(self):
        import tempfile
        db = Path(tempfile.mktemp(suffix=".db"))
        try:
            c = MetricsCollector(db)
            c.increment("test_hits", 10, endpoint="/api")
            c.observe("latency", 45.0)
            dash = MonitorDashboard(c)
            output = dash.render()
            assert "test_hits" in output
            assert "latency" in output
            dash.close()
        finally:
            db.unlink(missing_ok=True)
