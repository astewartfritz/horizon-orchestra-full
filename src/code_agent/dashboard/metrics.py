from __future__ import annotations

import collections
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Token cost table (USD per 1M tokens)
# ---------------------------------------------------------------------------
_COST_TABLE: dict[str, tuple[float, float]] = {
    # model-key            input $/1M    output $/1M
    "claude-haiku":        (0.80,         4.00),
    "claude-haiku-4-5":    (0.80,         4.00),
    "claude-sonnet":       (3.00,        15.00),
    "claude-sonnet-4-6":   (3.00,        15.00),
    "claude-opus":         (15.00,       75.00),
    "claude-opus-4-7":     (15.00,       75.00),
    "gpt-4o":              (2.50,        10.00),
    "gpt-3.5-turbo":       (0.50,         1.50),
    "codex-mini":          (1.50,         6.00),
    "nemotron-mini":       (0.00,         0.00),  # local Ollama
    "codellama":           (0.00,         0.00),
}

_CHARS_PER_TOKEN = 4  # rough estimate for English text

_HISTORY_LEN = 90   # ring-buffer depth (2s interval → 3 min window)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _lookup_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    model_lower = model.lower()
    for key, (inp_rate, out_rate) in _COST_TABLE.items():
        if key in model_lower:
            return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000
    return 0.0


# ---------------------------------------------------------------------------
# Ring-buffer helper
# ---------------------------------------------------------------------------

class _Ring:
    def __init__(self, maxlen: int):
        self._q: collections.deque = collections.deque(maxlen=maxlen)

    def push(self, item: Any) -> None:
        self._q.append(item)

    def to_list(self) -> list:
        return list(self._q)

    def __len__(self) -> int:
        return len(self._q)


# ---------------------------------------------------------------------------
# DashboardMetrics — central singleton
# ---------------------------------------------------------------------------

@dataclass
class _TokenRecord:
    ts: float
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class _LatencyRecord:
    ts: float
    judge_id: str
    duration_ms: float


@dataclass
class _AcceptRecord:
    ts: float
    agent_name: str
    passed: bool
    reward: float


@dataclass
class _ComputeRecord:
    ts: float
    cpu_pct: float
    mem_mb: float
    mem_pct: float


class DashboardMetrics:
    """Collects live metrics for the Orchestra cost dashboard.

    Thread-safe. Call the `record_*` methods from dispatch/council code.
    `snapshot()` returns a dict that the SSE endpoint streams to the browser.
    """

    def __init__(self, compute_interval: float = 5.0):
        self._lock = threading.Lock()

        # Raw event ring-buffers
        self._tokens: _Ring = _Ring(_HISTORY_LEN * 10)
        self._latencies: _Ring = _Ring(_HISTORY_LEN * 20)
        self._accepts: _Ring = _Ring(_HISTORY_LEN * 10)
        self._computes: _Ring = _Ring(_HISTORY_LEN)

        # Time-series for charts (one point per tick)
        self._spend_ts: _Ring = _Ring(_HISTORY_LEN)
        self._accept_ts: _Ring = _Ring(_HISTORY_LEN)
        self._latency_ts: _Ring = _Ring(_HISTORY_LEN)
        self._compute_ts: _Ring = _Ring(_HISTORY_LEN)

        # Totals
        self._total_cost_usd: float = 0.0
        self._total_tokens: int = 0

        # Background compute sampler
        self._compute_interval = compute_interval
        self._stop = threading.Event()
        self._compute_thread = threading.Thread(
            target=self._sample_compute_loop, daemon=True
        )
        self._compute_thread.start()

    # ------------------------------------------------------------------
    # Record methods — called from FeedbackLoop and agent code
    # ------------------------------------------------------------------

    def record_token_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        cost = _lookup_cost(model, input_tokens, output_tokens)
        rec = _TokenRecord(
            ts=time.time(), model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost,
        )
        with self._lock:
            self._tokens.push(rec)
            self._total_cost_usd += cost
            self._total_tokens += input_tokens + output_tokens

    def record_dispatch(self, agent_name: str, output: str, model: str = "") -> None:
        """Estimate tokens from a completed agent dispatch."""
        out_tok = _estimate_tokens(output)
        in_tok = out_tok // 3  # rough input estimate
        self.record_token_usage(model or agent_name, in_tok, out_tok)

    def record_judge_latency(self, judge_id: str, duration_ms: float) -> None:
        with self._lock:
            self._latencies.push(_LatencyRecord(time.time(), judge_id, duration_ms))

    def record_gate_result(self, agent_name: str, passed: bool, reward: float) -> None:
        with self._lock:
            self._accepts.push(_AcceptRecord(time.time(), agent_name, passed, reward))

    # ------------------------------------------------------------------
    # Compute sampling (background thread)
    # ------------------------------------------------------------------

    def _sample_compute_loop(self) -> None:
        while not self._stop.wait(self._compute_interval):
            rec = self._sample_compute()
            with self._lock:
                self._computes.push(rec)

    def _sample_compute(self) -> _ComputeRecord:
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_info().rss / 1024 / 1024
            total_mem = psutil.virtual_memory().total / 1024 / 1024
            mem_pct = (mem / total_mem * 100) if total_mem else 0.0
        except Exception:
            cpu, mem, mem_pct = 0.0, 0.0, 0.0
        return _ComputeRecord(time.time(), cpu, mem, mem_pct)

    # ------------------------------------------------------------------
    # Snapshot — called by SSE tick
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Advance time-series ring-buffers once per SSE interval."""
        now = time.time()
        with self._lock:
            tokens = self._tokens.to_list()
            latencies = self._latencies.to_list()
            accepts = self._accepts.to_list()
            computes = self._computes.to_list()
            total_cost = self._total_cost_usd
            total_tok = self._total_tokens

        # --- spend time-series (cumulative USD at this tick) ---
        self._spend_ts.push({"t": now, "usd": round(total_cost, 6)})

        # --- acceptance rate at this tick (last 60s window) ---
        window = [a for a in accepts if now - a.ts < 60]
        rate = sum(1 for a in window if a.passed) / len(window) if window else None
        self._accept_ts.push({"t": now, "rate": round(rate, 3) if rate is not None else None})

        # --- council latency at this tick (last 60s window) ---
        lat_window = [l.duration_ms for l in latencies if now - l.ts < 60]
        p50 = statistics.median(lat_window) if lat_window else None
        p95 = sorted(lat_window)[int(len(lat_window) * 0.95)] if len(lat_window) >= 2 else p50
        self._latency_ts.push({"t": now, "p50": p50, "p95": p95})

        # --- compute at this tick ---
        last_cpu = computes[-1] if computes else None
        self._compute_ts.push({
            "t": now,
            "cpu": round(last_cpu.cpu_pct, 1) if last_cpu else 0.0,
            "mem": round(last_cpu.mem_mb, 1) if last_cpu else 0.0,
        })

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            tokens = self._tokens.to_list()
            latencies = self._latencies.to_list()
            accepts = self._accepts.to_list()
            computes = self._computes.to_list()
            total_cost = self._total_cost_usd
            total_tok = self._total_tokens

        # ---- token spend ----
        by_model: dict[str, float] = {}
        for r in tokens:
            by_model[r.model] = round(by_model.get(r.model, 0) + r.cost_usd, 6)

        # per-hour rate: sum last 3600s
        hour_cost = sum(r.cost_usd for r in tokens if now - r.ts < 3600)
        hour_tokens = sum(r.input_tokens + r.output_tokens for r in tokens if now - r.ts < 3600)

        # ---- acceptance ----
        all_pass = sum(1 for a in accepts if a.passed)
        all_total = len(accepts)
        by_agent_pass: dict[str, list[bool]] = {}
        for a in accepts:
            by_agent_pass.setdefault(a.agent_name, []).append(a.passed)
        by_agent = {
            k: round(sum(v) / len(v), 3) for k, v in by_agent_pass.items()
        }

        # rolling 60s acceptance
        recent = [a for a in accepts if now - a.ts < 60]
        recent_rate = sum(1 for a in recent if a.passed) / len(recent) if recent else None

        # ---- council latency ----
        all_ms = [l.duration_ms for l in latencies]
        by_judge: dict[str, list[float]] = {}
        for l in latencies:
            by_judge.setdefault(l.judge_id, []).append(l.duration_ms)
        judge_avg = {k: round(statistics.mean(v), 1) for k, v in by_judge.items()}

        p50 = round(statistics.median(all_ms), 1) if all_ms else 0.0
        p95 = round(sorted(all_ms)[int(len(all_ms) * 0.95)], 1) if len(all_ms) >= 2 else p50
        p99 = round(sorted(all_ms)[int(len(all_ms) * 0.99)], 1) if len(all_ms) >= 5 else p95
        mean_ms = round(statistics.mean(all_ms), 1) if all_ms else 0.0

        # ---- compute ----
        last_cpu = computes[-1] if computes else None
        db_sizes = _get_db_sizes()

        return {
            "timestamp": now,
            "token_spend": {
                "total_usd": round(total_cost, 6),
                "per_hour_usd": round(hour_cost, 6),
                "total_tokens": total_tok,
                "per_hour_tokens": hour_tokens,
                "by_model": by_model,
                "history": self._spend_ts.to_list(),
            },
            "acceptance": {
                "overall_rate": round(all_pass / all_total, 3) if all_total else None,
                "recent_rate": round(recent_rate, 3) if recent_rate is not None else None,
                "total_evaluated": all_total,
                "passed": all_pass,
                "by_agent": by_agent,
                "history": self._accept_ts.to_list(),
            },
            "council_latency": {
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "mean_ms": mean_ms,
                "total_evals": len(latencies),
                "by_judge": judge_avg,
                "history": self._latency_ts.to_list(),
            },
            "compute": {
                "cpu_pct": round(last_cpu.cpu_pct, 1) if last_cpu else 0.0,
                "mem_mb": round(last_cpu.mem_mb, 1) if last_cpu else 0.0,
                "mem_pct": round(last_cpu.mem_pct, 1) if last_cpu else 0.0,
                "db_sizes_kb": db_sizes,
                "history": self._compute_ts.to_list(),
            },
        }

    def stop(self) -> None:
        self._stop.set()


def _get_db_sizes() -> dict[str, float]:
    sizes = {}
    for name, path in [
        ("experience", ".orchestra-experience.db"),
        ("policy", ".orchestra-policy.db"),
        ("metrics", ".agent-metrics.db"),
    ]:
        try:
            sizes[name] = round(Path(path).stat().st_size / 1024, 1)
        except FileNotFoundError:
            sizes[name] = 0.0
    return sizes


# Module-level singleton
_metrics: DashboardMetrics | None = None


def get_metrics() -> DashboardMetrics:
    global _metrics
    if _metrics is None:
        _metrics = DashboardMetrics()
    return _metrics
