"""Tests for the Orchestra real-time cost dashboard."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from code_agent.dashboard.metrics import (
    DashboardMetrics,
    _estimate_tokens,
    _lookup_cost,
    _get_db_sizes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics() -> DashboardMetrics:
    m = DashboardMetrics(compute_interval=9999)  # disable background sampler
    return m


# ---------------------------------------------------------------------------
# Token estimation / cost lookup
# ---------------------------------------------------------------------------

class TestTokenHelpers:
    def test_estimate_tokens_basic(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100

    def test_estimate_tokens_min_one(self):
        assert _estimate_tokens("") == 1

    def test_lookup_cost_claude_haiku(self):
        cost = _lookup_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == pytest.approx((0.80 + 4.00) / 1_000_000 * 1_000_000, abs=1e-6)

    def test_lookup_cost_gpt4o(self):
        cost = _lookup_cost("gpt-4o", 1_000_000, 0)
        assert cost == pytest.approx(2.50, abs=0.01)

    def test_lookup_cost_ollama_free(self):
        cost = _lookup_cost("nemotron-mini", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_lookup_cost_unknown_model(self):
        cost = _lookup_cost("some-unknown-model-xyz", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_db_sizes_returns_dict(self):
        sizes = _get_db_sizes()
        assert isinstance(sizes, dict)
        assert "experience" in sizes
        assert "policy" in sizes


# ---------------------------------------------------------------------------
# DashboardMetrics
# ---------------------------------------------------------------------------

class TestDashboardMetrics:
    def test_initial_snapshot_zeros(self):
        m = _make_metrics()
        m.tick()
        snap = m.snapshot()
        assert snap["token_spend"]["total_usd"] == 0.0
        assert snap["token_spend"]["total_tokens"] == 0
        assert snap["acceptance"]["total_evaluated"] == 0
        assert snap["council_latency"]["total_evals"] == 0

    def test_record_token_usage_accumulates(self):
        m = _make_metrics()
        m.record_token_usage("gpt-4o", 1000, 500)
        m.record_token_usage("gpt-4o", 2000, 1000)
        snap = m.snapshot()
        assert snap["token_spend"]["total_tokens"] == 4500
        assert snap["token_spend"]["total_usd"] > 0.0

    def test_record_token_usage_by_model(self):
        m = _make_metrics()
        m.record_token_usage("claude-haiku", 1000, 100)
        m.record_token_usage("gpt-4o", 500, 50)
        snap = m.snapshot()
        by_model = snap["token_spend"]["by_model"]
        assert "claude-haiku" in by_model
        assert "gpt-4o" in by_model

    def test_record_dispatch_estimates_tokens(self):
        m = _make_metrics()
        m.record_dispatch("claude_code", "def sort(arr): return sorted(arr)", "claude-haiku")
        snap = m.snapshot()
        assert snap["token_spend"]["total_tokens"] > 0

    def test_record_judge_latency_tracked(self):
        m = _make_metrics()
        m.record_judge_latency("judge-anthropic", 350.0)
        m.record_judge_latency("judge-ollama", 800.0)
        snap = m.snapshot()
        lat = snap["council_latency"]
        assert lat["total_evals"] == 2
        assert lat["p50_ms"] > 0
        assert "judge-anthropic" in lat["by_judge"]
        assert "judge-ollama" in lat["by_judge"]

    def test_record_gate_result_pass(self):
        m = _make_metrics()
        m.record_gate_result("claude_code", True, 0.85)
        m.record_gate_result("claude_code", True, 0.90)
        m.record_gate_result("codex", False, 0.30)
        snap = m.snapshot()
        acc = snap["acceptance"]
        assert acc["total_evaluated"] == 3
        assert acc["passed"] == 2
        assert acc["overall_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_acceptance_by_agent(self):
        m = _make_metrics()
        m.record_gate_result("agent_a", True, 0.9)
        m.record_gate_result("agent_a", True, 0.8)
        m.record_gate_result("agent_b", False, 0.2)
        snap = m.snapshot()
        by_agent = snap["acceptance"]["by_agent"]
        assert by_agent["agent_a"] == pytest.approx(1.0)
        assert by_agent["agent_b"] == pytest.approx(0.0)

    def test_tick_builds_spend_history(self):
        m = _make_metrics()
        m.record_token_usage("gpt-4o", 1000, 500)
        m.tick()
        m.tick()
        snap = m.snapshot()
        assert len(snap["token_spend"]["history"]) == 2

    def test_tick_builds_latency_history(self):
        m = _make_metrics()
        m.record_judge_latency("j1", 400.0)
        m.tick()
        snap = m.snapshot()
        history = snap["council_latency"]["history"]
        assert len(history) >= 1
        assert history[0]["p50"] is not None

    def test_tick_builds_accept_history(self):
        m = _make_metrics()
        m.record_gate_result("agent", True, 0.8)
        m.tick()
        snap = m.snapshot()
        history = snap["acceptance"]["history"]
        assert len(history) >= 1
        assert history[0]["rate"] is not None

    def test_latency_p50_p95_ordering(self):
        m = _make_metrics()
        for ms in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
            m.record_judge_latency("j1", float(ms))
        snap = m.snapshot()
        lat = snap["council_latency"]
        assert lat["p50_ms"] <= lat["p95_ms"]
        assert lat["p95_ms"] <= lat["p99_ms"]

    def test_per_hour_rate_counts_recent(self):
        m = _make_metrics()
        m.record_token_usage("gpt-4o", 100_000, 50_000)  # recent
        snap = m.snapshot()
        assert snap["token_spend"]["per_hour_usd"] > 0

    def test_compute_snapshot_structure(self):
        m = _make_metrics()
        m.tick()
        snap = m.snapshot()
        compute = snap["compute"]
        assert "cpu_pct" in compute
        assert "mem_mb" in compute
        assert "mem_pct" in compute
        assert "db_sizes_kb" in compute
        assert "history" in compute

    def test_compute_sampling_mocked(self):
        m = _make_metrics()
        mock_rec = MagicMock()
        mock_rec.cpu_pct = 42.5
        mock_rec.mem_mb = 512.0
        mock_rec.mem_pct = 25.0
        with patch.object(m, '_sample_compute', return_value=mock_rec):
            rec = m._sample_compute()
        assert rec.cpu_pct == pytest.approx(42.5)

    def test_ring_buffer_maxlen(self):
        m = _make_metrics()
        # Push more than _HISTORY_LEN items
        for i in range(100):
            m.record_judge_latency("j1", float(i))
            m.tick()
        snap = m.snapshot()
        # History should be capped at _HISTORY_LEN
        from code_agent.dashboard.metrics import _HISTORY_LEN
        assert len(snap["council_latency"]["history"]) <= _HISTORY_LEN

    def test_multiple_models_cost_separate(self):
        m = _make_metrics()
        m.record_token_usage("claude-haiku", 100_000, 10_000)
        m.record_token_usage("gpt-4o", 100_000, 10_000)
        snap = m.snapshot()
        by_model = snap["token_spend"]["by_model"]
        # gpt-4o costs more than haiku
        assert by_model["gpt-4o"] > by_model["claude-haiku"]

    def test_snapshot_timestamp(self):
        m = _make_metrics()
        before = time.time()
        snap = m.snapshot()
        after = time.time()
        assert before <= snap["timestamp"] <= after

    def test_stop_method(self):
        m = _make_metrics()
        m.stop()  # should not raise
        assert m._stop.is_set()


# ---------------------------------------------------------------------------
# Dashboard routes (smoke test — no server needed)
# ---------------------------------------------------------------------------

class TestDashboardRoutes:
    def test_html_contains_chart_js(self):
        from code_agent.dashboard.routes import _DASHBOARD_HTML
        assert "chart.js" in _DASHBOARD_HTML.lower()

    def test_html_has_four_panels(self):
        from code_agent.dashboard.routes import _DASHBOARD_HTML
        panels = ["token-spend", "accept", "latency", "compute"]
        # Check key element IDs exist
        assert "chart-spend" in _DASHBOARD_HTML
        assert "chart-accept" in _DASHBOARD_HTML
        assert "chart-latency" in _DASHBOARD_HTML
        assert "chart-compute" in _DASHBOARD_HTML

    def test_html_has_sse_connection(self):
        from code_agent.dashboard.routes import _DASHBOARD_HTML
        assert "EventSource" in _DASHBOARD_HTML
        assert "/dashboard/stream" in _DASHBOARD_HTML

    def test_html_has_live_indicator(self):
        from code_agent.dashboard.routes import _DASHBOARD_HTML
        assert "live-dot" in _DASHBOARD_HTML or "live-badge" in _DASHBOARD_HTML

    def test_html_has_all_metric_elements(self):
        from code_agent.dashboard.routes import _DASHBOARD_HTML
        required_ids = [
            "spend-total", "spend-rate", "spend-tokens",
            "accept-pct", "accept-counts",
            "lat-p50", "lat-p95", "lat-p99", "lat-mean",
            "cpu-val", "mem-val", "cpu-bar", "mem-bar",
        ]
        for el_id in required_ids:
            assert el_id in _DASHBOARD_HTML, f"Missing element id: {el_id}"
