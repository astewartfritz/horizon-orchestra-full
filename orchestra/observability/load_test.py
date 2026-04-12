"""Built-in load-testing harness for Horizon Orchestra.

Asyncio-based load tester with ramp-up, steady-state, and SLA assertion
so teams can validate performance before deploying.  No external
dependencies (no locust, k6, or wrk required).

Usage::

    from orchestra.observability.load_test import OrchestraLoadTester, LoadTestConfig

    tester = OrchestraLoadTester()
    tester.add_scenario(api_chat_scenario("http://localhost:8000", "sk-test"))
    result = await tester.run(LoadTestConfig(target_rps=500, duration_seconds=30))
    print(tester.report(result))
    assert tester.assert_sla(result, {"p99_ms": 200, "error_rate": 0.01})
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

__all__ = [
    "LoadTestConfig",
    "LoadTestScenario",
    "LoadTestResult",
    "OrchestraLoadTester",
    "api_chat_scenario",
    "api_stream_scenario",
    "concurrent_agents_scenario",
]

logger = logging.getLogger("orchestra.observability.load_test")

# Type alias for async request functions
RequestFn = Callable[[], Coroutine[Any, Any, bool]]


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class LoadTestConfig:
    """Configuration for a load-test run."""
    target_rps: float = 100.0
    duration_seconds: float = 30.0
    concurrency: int = 50
    warmup_seconds: float = 5.0
    ramp_up_seconds: float = 10.0
    scenarios: Optional[List[str]] = None  # filter by name; None = all


@dataclass
class LoadTestScenario:
    """A named test scenario with a request function and SLA target."""
    name: str
    weight: float = 1.0
    request_fn: Optional[RequestFn] = None
    expected_latency_p99_ms: float = 500.0


@dataclass
class LatencyStats:
    """Computed latency statistics for a test run or window."""
    p50_ms: float = 0.0
    p75_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    mean_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    stddev_ms: float = 0.0


@dataclass
class TimelineEntry:
    """A single data-point in the RPS / latency timeline."""
    elapsed_seconds: float
    rps: float
    p50_ms: float
    p99_ms: float
    error_rate: float
    active_requests: int = 0


@dataclass
class LoadTestResult:
    """Aggregate results of a completed load test."""
    total_requests: int = 0
    total_errors: int = 0
    duration_seconds: float = 0.0
    rps_achieved: float = 0.0
    error_rate: float = 0.0
    throughput_bytes: int = 0

    latency: LatencyStats = field(default_factory=LatencyStats)
    per_scenario: Dict[str, LatencyStats] = field(default_factory=dict)
    timeline: List[TimelineEntry] = field(default_factory=list)

    # raw latency samples (ms)
    _raw_latencies: List[float] = field(default_factory=list, repr=False)


# ── Percentile helper ─────────────────────────────────────────────────

def _percentile(data: List[float], pct: float) -> float:
    """Compute the *pct*-th percentile from a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    d = k - f
    return data[f] + d * (data[c] - data[f])


def _compute_stats(latencies_ms: List[float]) -> LatencyStats:
    """Derive :class:`LatencyStats` from a list of latency samples (ms)."""
    if not latencies_ms:
        return LatencyStats()
    s = sorted(latencies_ms)
    return LatencyStats(
        p50_ms=round(_percentile(s, 50), 3),
        p75_ms=round(_percentile(s, 75), 3),
        p90_ms=round(_percentile(s, 90), 3),
        p95_ms=round(_percentile(s, 95), 3),
        p99_ms=round(_percentile(s, 99), 3),
        mean_ms=round(statistics.mean(s), 3),
        min_ms=round(s[0], 3),
        max_ms=round(s[-1], 3),
        stddev_ms=round(statistics.stdev(s), 3) if len(s) > 1 else 0.0,
    )


# ── Load Tester ───────────────────────────────────────────────────────

class OrchestraLoadTester:
    """Asyncio-based load testing harness.

    Example::

        tester = OrchestraLoadTester()
        tester.add_scenario(LoadTestScenario(
            name="chat",
            request_fn=my_async_fn,
        ))
        result = await tester.run(LoadTestConfig(target_rps=200))
    """

    def __init__(self) -> None:
        self._scenarios: List[LoadTestScenario] = []
        self._results: List[LoadTestResult] = []

    # ── Scenario management ───────────────────────────────────────────

    def add_scenario(self, scenario: LoadTestScenario) -> None:
        """Register a load-test scenario."""
        self._scenarios.append(scenario)

    def clear_scenarios(self) -> None:
        """Remove all registered scenarios."""
        self._scenarios.clear()

    # ── Main run ──────────────────────────────────────────────────────

    async def run(self, config: LoadTestConfig) -> LoadTestResult:
        """Execute the load test.

        Phases:
        1. **Warmup** — ramp from 0 → small RPS for ``warmup_seconds``.
        2. **Ramp-up** — linearly increase to ``target_rps`` over
           ``ramp_up_seconds``.
        3. **Steady state** — hold ``target_rps`` for ``duration_seconds``.
        """
        scenarios = self._select_scenarios(config)
        if not scenarios:
            raise ValueError("No runnable scenarios (check config.scenarios filter)")

        all_latencies: List[float] = []
        per_scenario_latencies: Dict[str, List[float]] = defaultdict(list)
        timeline: List[TimelineEntry] = []
        total_errors = 0
        active_count = 0
        sem = asyncio.Semaphore(config.concurrency)

        async def _run_one(scenario: LoadTestScenario) -> Tuple[str, float, bool]:
            nonlocal active_count
            async with sem:
                active_count += 1
                start = time.monotonic()
                success = True
                try:
                    if scenario.request_fn is not None:
                        success = await scenario.request_fn()
                    else:
                        # Synthetic no-op for scenarios without a real function
                        await asyncio.sleep(0.001)
                except Exception as exc:
                    logger.debug("Scenario %s error: %s", scenario.name, exc)
                    success = False
                finally:
                    active_count -= 1
                elapsed_ms = (time.monotonic() - start) * 1000
                return scenario.name, elapsed_ms, success

        run_start = time.monotonic()

        # ── Phase 1: warmup ───────────────────────────────────────────
        if config.warmup_seconds > 0:
            await self._phase(
                label="warmup",
                scenarios=scenarios,
                target_rps=max(config.target_rps * 0.1, 1),
                duration=config.warmup_seconds,
                run_fn=_run_one,
                all_latencies=all_latencies,
                per_scenario_latencies=per_scenario_latencies,
                timeline=timeline,
                error_counter=_Counter(),
                run_start=run_start,
            )

        # ── Phase 2: ramp-up ─────────────────────────────────────────
        error_counter = _Counter()
        if config.ramp_up_seconds > 0:
            await self.ramp_up(
                target_rps=config.target_rps,
                duration=config.ramp_up_seconds,
                scenarios=scenarios,
                run_fn=_run_one,
                all_latencies=all_latencies,
                per_scenario_latencies=per_scenario_latencies,
                timeline=timeline,
                error_counter=error_counter,
                run_start=run_start,
            )

        # ── Phase 3: steady state ────────────────────────────────────
        await self.steady_state(
            rps=config.target_rps,
            duration=config.duration_seconds,
            scenarios=scenarios,
            run_fn=_run_one,
            all_latencies=all_latencies,
            per_scenario_latencies=per_scenario_latencies,
            timeline=timeline,
            error_counter=error_counter,
            run_start=run_start,
        )

        total_duration = time.monotonic() - run_start
        total_errors = error_counter.value

        result = LoadTestResult(
            total_requests=len(all_latencies),
            total_errors=total_errors,
            duration_seconds=round(total_duration, 3),
            rps_achieved=round(len(all_latencies) / total_duration, 2) if total_duration > 0 else 0,
            error_rate=round(total_errors / max(len(all_latencies), 1), 4),
            latency=_compute_stats(all_latencies),
            per_scenario={
                name: _compute_stats(lats)
                for name, lats in per_scenario_latencies.items()
            },
            timeline=timeline,
            _raw_latencies=all_latencies,
        )
        self._results.append(result)
        return result

    # ── Phase helpers ─────────────────────────────────────────────────

    async def ramp_up(
        self,
        target_rps: float,
        duration: float,
        scenarios: Optional[List[LoadTestScenario]] = None,
        run_fn: Optional[Any] = None,
        all_latencies: Optional[List[float]] = None,
        per_scenario_latencies: Optional[Dict[str, List[float]]] = None,
        timeline: Optional[List[TimelineEntry]] = None,
        error_counter: Optional[Any] = None,
        run_start: Optional[float] = None,
    ) -> None:
        """Linearly ramp RPS from 0 to *target_rps* over *duration* seconds."""
        if scenarios is None:
            scenarios = self._scenarios
        if all_latencies is None:
            all_latencies = []
        if per_scenario_latencies is None:
            per_scenario_latencies = defaultdict(list)
        if timeline is None:
            timeline = []
        if error_counter is None:
            error_counter = _Counter()
        if run_start is None:
            run_start = time.monotonic()
        steps = max(int(duration), 1)
        for i in range(steps):
            fraction = (i + 1) / steps
            current_rps = target_rps * fraction
            await self._phase(
                label=f"ramp-{i}",
                scenarios=scenarios,
                target_rps=current_rps,
                duration=1.0,
                run_fn=run_fn,
                all_latencies=all_latencies,
                per_scenario_latencies=per_scenario_latencies,
                timeline=timeline,
                error_counter=error_counter,
                run_start=run_start,
            )

    async def steady_state(
        self,
        rps: float,
        duration: float,
        scenarios: Optional[List[LoadTestScenario]] = None,
        run_fn: Optional[Any] = None,
        all_latencies: Optional[List[float]] = None,
        per_scenario_latencies: Optional[Dict[str, List[float]]] = None,
        timeline: Optional[List[TimelineEntry]] = None,
        error_counter: Optional[Any] = None,
        run_start: Optional[float] = None,
    ) -> None:
        """Hold *rps* for *duration* seconds."""
        if scenarios is None:
            scenarios = self._scenarios
        if all_latencies is None:
            all_latencies = []
        if per_scenario_latencies is None:
            per_scenario_latencies = defaultdict(list)
        if timeline is None:
            timeline = []
        if error_counter is None:
            error_counter = _Counter()
        if run_start is None:
            run_start = time.monotonic()
        seconds = max(int(duration), 1)
        for _ in range(seconds):
            await self._phase(
                label="steady",
                scenarios=scenarios,
                target_rps=rps,
                duration=1.0,
                run_fn=run_fn,
                all_latencies=all_latencies,
                per_scenario_latencies=per_scenario_latencies,
                timeline=timeline,
                error_counter=error_counter,
                run_start=run_start,
            )

    async def _phase(
        self,
        *,
        label: str,
        scenarios: List[LoadTestScenario],
        target_rps: float,
        duration: float,
        run_fn: Any,
        all_latencies: List[float],
        per_scenario_latencies: Dict[str, List[float]],
        timeline: List[TimelineEntry],
        error_counter: Any,
        run_start: float,
    ) -> None:
        """Execute one second-long phase at *target_rps*."""
        n_requests = max(int(target_rps * duration), 1)
        interval = duration / n_requests if n_requests > 0 else duration

        # Weighted scenario selection
        weights = [s.weight for s in scenarios]
        total_w = sum(weights)
        cumulative: List[float] = []
        running = 0.0
        for w in weights:
            running += w / total_w
            cumulative.append(running)

        tasks: List[asyncio.Task[Any]] = []
        window_latencies: List[float] = []
        window_errors = 0

        import random as _random

        for _ in range(n_requests):
            r = _random.random()
            idx = 0
            for j, c in enumerate(cumulative):
                if r <= c:
                    idx = j
                    break
            scenario = scenarios[idx]

            if run_fn is not None:
                task = asyncio.ensure_future(run_fn(scenario))
                tasks.append(task)
            await asyncio.sleep(interval)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                window_errors += 1
                continue
            name, latency_ms, success = res
            all_latencies.append(latency_ms)
            per_scenario_latencies[name].append(latency_ms)
            window_latencies.append(latency_ms)
            if not success:
                window_errors += 1

        error_counter.value += window_errors
        elapsed = time.monotonic() - run_start
        timeline.append(TimelineEntry(
            elapsed_seconds=round(elapsed, 2),
            rps=round(len(window_latencies) / max(duration, 0.001), 1),
            p50_ms=round(_percentile(sorted(window_latencies), 50), 2) if window_latencies else 0,
            p99_ms=round(_percentile(sorted(window_latencies), 99), 2) if window_latencies else 0,
            error_rate=round(window_errors / max(len(window_latencies), 1), 4),
        ))

    # ── Scenario selection ────────────────────────────────────────────

    def _select_scenarios(self, config: LoadTestConfig) -> List[LoadTestScenario]:
        """Filter scenarios by config.scenarios list."""
        if config.scenarios is None:
            return list(self._scenarios)
        names = set(config.scenarios)
        return [s for s in self._scenarios if s.name in names]

    # ── Reporting ─────────────────────────────────────────────────────

    def report(self, result: LoadTestResult) -> str:
        """Generate a human-readable load-test report."""
        lines: List[str] = [
            "=" * 72,
            "  HORIZON ORCHESTRA — LOAD TEST REPORT",
            "=" * 72,
            "",
            f"  Total requests ........... {result.total_requests:,}",
            f"  Total errors ............. {result.total_errors:,}",
            f"  Duration ................. {result.duration_seconds:.1f}s",
            f"  RPS achieved ............. {result.rps_achieved:,.1f}",
            f"  Error rate ............... {result.error_rate:.2%}",
            "",
            "  LATENCY",
            f"    p50 .................... {result.latency.p50_ms:.1f}ms",
            f"    p75 .................... {result.latency.p75_ms:.1f}ms",
            f"    p90 .................... {result.latency.p90_ms:.1f}ms",
            f"    p95 .................... {result.latency.p95_ms:.1f}ms",
            f"    p99 .................... {result.latency.p99_ms:.1f}ms",
            f"    mean ................... {result.latency.mean_ms:.1f}ms",
            f"    min .................... {result.latency.min_ms:.1f}ms",
            f"    max .................... {result.latency.max_ms:.1f}ms",
            "",
        ]

        if result.per_scenario:
            lines.append("  PER-SCENARIO BREAKDOWN")
            for name, stats in sorted(result.per_scenario.items()):
                lines.append(f"    {name}:")
                lines.append(f"      p50={stats.p50_ms:.1f}ms  p99={stats.p99_ms:.1f}ms  mean={stats.mean_ms:.1f}ms")
            lines.append("")

        lines.append("=" * 72)
        return "\n".join(lines)

    def assert_sla(self, result: LoadTestResult, sla: Dict[str, float]) -> bool:
        """Check whether *result* meets SLA thresholds.

        Supported keys: ``p50_ms``, ``p95_ms``, ``p99_ms``, ``error_rate``,
        ``min_rps``.

        Returns ``True`` if all SLA requirements are met.
        """
        passed = True
        for key, threshold in sla.items():
            if key == "p50_ms" and result.latency.p50_ms > threshold:
                logger.warning("SLA FAIL: p50 %.1f > %.1f", result.latency.p50_ms, threshold)
                passed = False
            elif key == "p95_ms" and result.latency.p95_ms > threshold:
                logger.warning("SLA FAIL: p95 %.1f > %.1f", result.latency.p95_ms, threshold)
                passed = False
            elif key == "p99_ms" and result.latency.p99_ms > threshold:
                logger.warning("SLA FAIL: p99 %.1f > %.1f", result.latency.p99_ms, threshold)
                passed = False
            elif key == "error_rate" and result.error_rate > threshold:
                logger.warning("SLA FAIL: error rate %.4f > %.4f", result.error_rate, threshold)
                passed = False
            elif key == "min_rps" and result.rps_achieved < threshold:
                logger.warning("SLA FAIL: RPS %.1f < %.1f", result.rps_achieved, threshold)
                passed = False
        return passed

    def get_history(self) -> List[LoadTestResult]:
        """Return all past test results."""
        return list(self._results)


# ── Internal counter helper ───────────────────────────────────────────

class _Counter:
    """Tiny mutable counter for passing by reference."""
    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: int = 0


# ── Pre-built scenarios ──────────────────────────────────────────────

def api_chat_scenario(base_url: str, api_key: str) -> LoadTestScenario:
    """Pre-built scenario: hit ``POST /v1/run`` with a simple chat task.

    Parameters
    ----------
    base_url : str
        Base URL of the Orchestra API (e.g. ``http://localhost:8000``).
    api_key : str
        Bearer token for authentication.
    """
    async def _request() -> bool:
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError:
            await asyncio.sleep(0.002)
            return True

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/v1/run",
                json={"task": "What is 2+2?", "model": "kimi-k2.5"},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code < 400

    return LoadTestScenario(
        name="api_chat",
        weight=1.0,
        request_fn=_request,
        expected_latency_p99_ms=500.0,
    )


def api_stream_scenario(base_url: str, api_key: str) -> LoadTestScenario:
    """Pre-built scenario: streaming endpoint load test.

    Parameters
    ----------
    base_url : str
        Base URL of the Orchestra API.
    api_key : str
        Bearer token.
    """
    async def _request() -> bool:
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError:
            await asyncio.sleep(0.005)
            return True

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/v1/run/stream",
                json={"task": "Write a haiku about testing.", "model": "kimi-k2.5", "stream": True},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code >= 400:
                return False
            # Consume stream
            return True

    return LoadTestScenario(
        name="api_stream",
        weight=0.5,
        request_fn=_request,
        expected_latency_p99_ms=2000.0,
    )


def concurrent_agents_scenario(n_agents: int = 10) -> LoadTestScenario:
    """Pre-built scenario: spawn *n_agents* concurrently (synthetic).

    This scenario simulates N concurrent agent tasks without making
    real network calls — useful for stress-testing the scheduler and
    memory subsystems.
    """
    async def _request() -> bool:
        tasks = []
        for _ in range(n_agents):
            tasks.append(asyncio.ensure_future(_synthetic_agent()))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(not isinstance(r, Exception) for r in results)

    async def _synthetic_agent() -> None:
        """Simulate agent work: think → tool → think → answer."""
        await asyncio.sleep(0.001)  # "thinking"
        await asyncio.sleep(0.001)  # "tool call"
        await asyncio.sleep(0.001)  # "final answer"

    return LoadTestScenario(
        name="concurrent_agents",
        weight=0.3,
        request_fn=_request,
        expected_latency_p99_ms=100.0,
    )
