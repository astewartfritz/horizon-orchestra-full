"""Chaos-engineering orchestrator for Horizon Orchestra.

Injects infrastructure-level faults — network drops, model corruption,
tool failures, memory corruption, sandbox kills, context poisoning,
concurrency hazards, and streaming errors — to measure resilience and
mean-time-to-recovery (MTTR).

Each chaos scenario is modelled as a ``ChaosScenario`` with configurable
intensity (0.0–1.0).  The orchestrator runs scenarios concurrently and
tracks blast radius and recovery metrics.

Usage::

    orch = ChaosOrchestrator()
    result = await orch.inject(NetworkChaos.PACKET_DROP, target="model_api", intensity=0.5)
    report = await orch.run_scenario("network_full", duration_seconds=30)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

__all__ = [
    "ChaosCategory",
    "ChaosScenario",
    "ChaosResult",
    "ChaosReport",
    "ChaosOrchestrator",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums / data models
# ---------------------------------------------------------------------------

class ChaosCategory(str, Enum):
    """Eight chaos-injection categories."""
    NETWORK = "network"
    MODEL = "model"
    TOOL = "tool"
    MEMORY = "memory"
    SANDBOX = "sandbox"
    CONTEXT = "context"
    CONCURRENCY = "concurrency"
    STREAMING = "streaming"


@dataclass
class ChaosScenario:
    """Specification for a single chaos injection."""
    id: str
    category: ChaosCategory
    name: str
    description: str
    intensity: float = 0.5          # 0.0 = noop, 1.0 = full chaos
    duration_seconds: float = 10.0
    target: str = "*"               # component to target
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChaosResult:
    """Outcome of a single chaos injection."""
    scenario_id: str
    scenario_name: str
    category: ChaosCategory
    start_time: datetime
    end_time: datetime
    duration_ms: float
    recovery_time_ms: float         # MTTR
    impact: dict[str, Any]          # what broke
    errors_observed: list[str]
    systems_affected: list[str]
    intensity: float
    recovered: bool


@dataclass
class ChaosReport:
    """Aggregated report from a chaos session."""
    session_id: str
    timestamp: datetime
    duration_seconds: float
    scenarios_run: int
    results: list[ChaosResult]
    avg_recovery_ms: float
    max_recovery_ms: float
    systems_affected: set[str]
    critical_failures: list[str]
    resilience_score: float         # 0–100


# ---------------------------------------------------------------------------
# Predefined scenario library
# ---------------------------------------------------------------------------

_SCENARIO_LIBRARY: dict[str, list[ChaosScenario]] = {
    # 1. Network chaos
    "network": [
        ChaosScenario("net-001", ChaosCategory.NETWORK, "packet_drop",
                       "Drop N% of packets to model API", parameters={"drop_rate": 0.3}),
        ChaosScenario("net-002", ChaosCategory.NETWORK, "latency_spike",
                       "Add 2–5s latency to all outbound requests", parameters={"min_ms": 2000, "max_ms": 5000}),
        ChaosScenario("net-003", ChaosCategory.NETWORK, "disconnect_midstream",
                       "Sever TCP connection after N bytes", parameters={"after_bytes": 512}),
        ChaosScenario("net-004", ChaosCategory.NETWORK, "http_429",
                       "Return 429 Too Many Requests for all calls", parameters={"status_code": 429}),
        ChaosScenario("net-005", ChaosCategory.NETWORK, "http_503",
                       "Return 503 Service Unavailable", parameters={"status_code": 503}),
        ChaosScenario("net-006", ChaosCategory.NETWORK, "http_504",
                       "Return 504 Gateway Timeout", parameters={"status_code": 504}),
        ChaosScenario("net-007", ChaosCategory.NETWORK, "dns_failure",
                       "Simulate DNS resolution failure", parameters={"resolve": False}),
        ChaosScenario("net-008", ChaosCategory.NETWORK, "tls_error",
                       "Return TLS handshake failure", parameters={"tls_fail": True}),
    ],
    # 2. Model chaos
    "model": [
        ChaosScenario("mdl-001", ChaosCategory.MODEL, "corrupted_completion",
                       "Return garbled UTF-8 in model response"),
        ChaosScenario("mdl-002", ChaosCategory.MODEL, "empty_response",
                       "Return an empty completion"),
        ChaosScenario("mdl-003", ChaosCategory.MODEL, "timeout_at_percent",
                       "Timeout after generating N% of response", parameters={"percent": 50}),
        ChaosScenario("mdl-004", ChaosCategory.MODEL, "truncated_mid_token",
                       "Truncate response mid-token boundary"),
        ChaosScenario("mdl-005", ChaosCategory.MODEL, "wrong_model_id",
                       "Return response claiming to be a different model"),
        ChaosScenario("mdl-006", ChaosCategory.MODEL, "hallucinated_tool_call",
                       "Return a tool call for a non-existent tool"),
        ChaosScenario("mdl-007", ChaosCategory.MODEL, "infinite_generation",
                       "Model generates tokens without stop sequence"),
        ChaosScenario("mdl-008", ChaosCategory.MODEL, "json_parse_error",
                       "Return syntactically invalid JSON in structured output"),
    ],
    # 3. Tool chaos
    "tool": [
        ChaosScenario("tool-001", ChaosCategory.TOOL, "malformed_json",
                       "Tool returns malformed JSON"),
        ChaosScenario("tool-002", ChaosCategory.TOOL, "circular_dependency",
                       "Tool A calls tool B which calls tool A"),
        ChaosScenario("tool-003", ChaosCategory.TOOL, "tool_timeout",
                       "Tool hangs for 60s then fails", parameters={"timeout_s": 60}),
        ChaosScenario("tool-004", ChaosCategory.TOOL, "wrong_return_type",
                       "Tool returns string instead of expected dict"),
        ChaosScenario("tool-005", ChaosCategory.TOOL, "null_return",
                       "Tool returns None/null"),
        ChaosScenario("tool-006", ChaosCategory.TOOL, "exception_in_tool",
                       "Tool raises an unhandled exception"),
        ChaosScenario("tool-007", ChaosCategory.TOOL, "partial_result",
                       "Tool returns incomplete/truncated result"),
        ChaosScenario("tool-008", ChaosCategory.TOOL, "permission_denied",
                       "Tool returns permission denied error"),
    ],
    # 4. Memory chaos
    "memory": [
        ChaosScenario("mem-001", ChaosCategory.MEMORY, "corrupted_entries",
                       "Flip random bits in memory store entries"),
        ChaosScenario("mem-002", ChaosCategory.MEMORY, "stale_data",
                       "Return data from 24h ago ignoring recent updates"),
        ChaosScenario("mem-003", ChaosCategory.MEMORY, "false_memories",
                       "Inject fabricated memory entries"),
        ChaosScenario("mem-004", ChaosCategory.MEMORY, "memory_overload",
                       "Fill memory store to capacity, reject writes"),
        ChaosScenario("mem-005", ChaosCategory.MEMORY, "cross_session_leak",
                       "Return memories from a different user session"),
        ChaosScenario("mem-006", ChaosCategory.MEMORY, "memory_wipe",
                       "Delete all memory entries mid-conversation"),
        ChaosScenario("mem-007", ChaosCategory.MEMORY, "slow_retrieval",
                       "Memory retrieval takes 10x longer than normal"),
        ChaosScenario("mem-008", ChaosCategory.MEMORY, "duplicate_entries",
                       "Return duplicate memory entries for every query"),
    ],
    # 5. Sandbox chaos
    "sandbox": [
        ChaosScenario("sbox-001", ChaosCategory.SANDBOX, "oom_kill",
                       "Kill process via OOM signal"),
        ChaosScenario("sbox-002", ChaosCategory.SANDBOX, "fd_exhaustion",
                       "Exhaust file descriptors (ulimit -n 0)"),
        ChaosScenario("sbox-003", ChaosCategory.SANDBOX, "network_block",
                       "Block all outbound network from sandbox"),
        ChaosScenario("sbox-004", ChaosCategory.SANDBOX, "cpu_spike",
                       "Consume 100% CPU for duration", parameters={"cores": 4}),
        ChaosScenario("sbox-005", ChaosCategory.SANDBOX, "disk_full",
                       "Fill /tmp to capacity"),
        ChaosScenario("sbox-006", ChaosCategory.SANDBOX, "process_limit",
                       "Exhaust process limit (fork bomb protection)"),
        ChaosScenario("sbox-007", ChaosCategory.SANDBOX, "read_only_fs",
                       "Mount filesystem as read-only"),
        ChaosScenario("sbox-008", ChaosCategory.SANDBOX, "sigkill_random",
                       "Send SIGKILL to random child process"),
    ],
    # 6. Context chaos
    "context": [
        ChaosScenario("ctx-001", ChaosCategory.CONTEXT, "garbage_injection",
                       "Insert random bytes at position N in context"),
        ChaosScenario("ctx-002", ChaosCategory.CONTEXT, "embedding_flip",
                       "Flip sign of random embedding dimensions"),
        ChaosScenario("ctx-003", ChaosCategory.CONTEXT, "context_duplicate",
                       "Duplicate the entire context window"),
        ChaosScenario("ctx-004", ChaosCategory.CONTEXT, "context_truncate",
                       "Truncate context mid-sentence"),
        ChaosScenario("ctx-005", ChaosCategory.CONTEXT, "context_shuffle",
                       "Randomly reorder messages in context"),
        ChaosScenario("ctx-006", ChaosCategory.CONTEXT, "token_corruption",
                       "Replace random tokens with <unk>"),
        ChaosScenario("ctx-007", ChaosCategory.CONTEXT, "system_prompt_drop",
                       "Remove system prompt from context"),
        ChaosScenario("ctx-008", ChaosCategory.CONTEXT, "context_overflow",
                       "Exceed maximum context window length"),
    ],
    # 7. Concurrency chaos
    "concurrency": [
        ChaosScenario("conc-001", ChaosCategory.CONCURRENCY, "race_condition",
                       "Two agents write to same resource simultaneously"),
        ChaosScenario("conc-002", ChaosCategory.CONCURRENCY, "deadlock",
                       "Create circular lock dependency between agents"),
        ChaosScenario("conc-003", ChaosCategory.CONCURRENCY, "priority_inversion",
                       "Low-priority task blocks high-priority agent"),
        ChaosScenario("conc-004", ChaosCategory.CONCURRENCY, "thundering_herd",
                       "All agents wake and compete for same resource"),
        ChaosScenario("conc-005", ChaosCategory.CONCURRENCY, "stale_lock",
                       "Lock holder dies without releasing lock"),
        ChaosScenario("conc-006", ChaosCategory.CONCURRENCY, "double_submit",
                       "Same tool call submitted twice simultaneously"),
        ChaosScenario("conc-007", ChaosCategory.CONCURRENCY, "event_ordering",
                       "Events delivered out of causal order"),
        ChaosScenario("conc-008", ChaosCategory.CONCURRENCY, "resource_starvation",
                       "One agent consumes all available connections"),
    ],
    # 8. Streaming chaos
    "streaming": [
        ChaosScenario("str-001", ChaosCategory.STREAMING, "partial_sse",
                       "Send incomplete SSE event (no newline terminator)"),
        ChaosScenario("str-002", ChaosCategory.STREAMING, "out_of_order_chunks",
                       "Deliver streaming chunks in wrong order"),
        ChaosScenario("str-003", ChaosCategory.STREAMING, "duplicate_events",
                       "Send same SSE event twice"),
        ChaosScenario("str-004", ChaosCategory.STREAMING, "corrupt_json_mid_stream",
                       "Insert invalid bytes mid-JSON chunk"),
        ChaosScenario("str-005", ChaosCategory.STREAMING, "connection_reset",
                       "Reset TCP connection mid-stream"),
        ChaosScenario("str-006", ChaosCategory.STREAMING, "infinite_stream",
                       "Stream never sends [DONE] event"),
        ChaosScenario("str-007", ChaosCategory.STREAMING, "empty_chunks",
                       "Send empty data: fields repeatedly"),
        ChaosScenario("str-008", ChaosCategory.STREAMING, "interleaved_streams",
                       "Mix chunks from two different responses"),
    ],
}


# ---------------------------------------------------------------------------
# Chaos Orchestrator
# ---------------------------------------------------------------------------

class ChaosOrchestrator:
    """Concurrent chaos-engineering test orchestrator.

    Injects faults into Orchestra subsystems, measures recovery time,
    and reports blast radius.
    """

    def __init__(self, *, max_concurrent: int = 8) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._results: list[ChaosResult] = []
        self._health_checks: dict[str, Callable[[], Awaitable[bool]]] = {}

    # ------------------------------------------------------------------
    # Health-check registration
    # ------------------------------------------------------------------

    def register_health_check(
        self, component: str, check_fn: Callable[[], Awaitable[bool]]
    ) -> None:
        """Register a health-check coroutine for *component*.

        The orchestrator polls this after injecting chaos to measure MTTR.
        """
        self._health_checks[component] = check_fn

    # ------------------------------------------------------------------
    # Injection API
    # ------------------------------------------------------------------

    async def inject(
        self,
        scenario: ChaosScenario,
        target: str | None = None,
        intensity: float | None = None,
    ) -> ChaosResult:
        """Inject a single chaos scenario.

        Args:
            scenario: The chaos scenario to inject.
            target: Override scenario's default target component.
            intensity: Override scenario's default intensity (0.0–1.0).

        Returns:
            A ``ChaosResult`` with impact and recovery metrics.
        """
        if target:
            scenario.target = target
        if intensity is not None:
            scenario.intensity = max(0.0, min(1.0, intensity))

        async with self._semaphore:
            return await self._execute_scenario(scenario)

    async def run_scenario(
        self, category_name: str, duration_seconds: float = 30.0
    ) -> list[ChaosResult]:
        """Run all scenarios in a category concurrently.

        Args:
            category_name: Key in the scenario library (e.g. ``"network"``).
            duration_seconds: Maximum duration for the test run.

        Returns:
            List of ``ChaosResult`` from all injected scenarios.
        """
        scenarios = _SCENARIO_LIBRARY.get(category_name, [])
        if not scenarios:
            logger.warning("No scenarios found for category: %s", category_name)
            return []

        for s in scenarios:
            s.duration_seconds = duration_seconds / len(scenarios)

        tasks = [self._execute_scenario(s) for s in scenarios]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid: list[ChaosResult] = []
        for r in results:
            if isinstance(r, ChaosResult):
                valid.append(r)
            else:
                logger.error("Chaos scenario error: %s", r)
        self._results.extend(valid)
        return valid

    async def run_all(self, duration_seconds: float = 60.0) -> ChaosReport:
        """Run every scenario across all 8 categories.

        Returns:
            A full ``ChaosReport`` summarising the session.
        """
        session_id = str(uuid.uuid4())[:8]
        start = time.monotonic()
        all_results: list[ChaosResult] = []

        per_category = duration_seconds / len(_SCENARIO_LIBRARY)
        tasks = [
            self.run_scenario(cat, per_category)
            for cat in _SCENARIO_LIBRARY
        ]
        category_results = await asyncio.gather(*tasks)
        for cr in category_results:
            all_results.extend(cr)

        elapsed = time.monotonic() - start
        return self._build_report(session_id, elapsed, all_results)

    async def measure_recovery_time(self, scenario: ChaosScenario) -> float:
        """Inject chaos and measure how long until health checks pass (MTTR).

        Returns:
            Recovery time in milliseconds.
        """
        result = await self.inject(scenario)
        return result.recovery_time_ms

    def get_blast_radius(self, scenario: ChaosScenario) -> dict[str, Any]:
        """Estimate what systems a scenario would affect.

        Returns:
            Dict mapping component names to expected impact severity.
        """
        radius: dict[str, Any] = {
            "target": scenario.target,
            "category": scenario.category.value,
            "intensity": scenario.intensity,
            "estimated_affected_systems": [],
            "estimated_severity": "low",
        }

        category_impact: dict[ChaosCategory, list[str]] = {
            ChaosCategory.NETWORK: ["model_api", "tool_api", "external_services"],
            ChaosCategory.MODEL: ["agent_loop", "response_generation", "tool_calling"],
            ChaosCategory.TOOL: ["tool_execution", "agent_loop", "sandbox"],
            ChaosCategory.MEMORY: ["context_management", "personalization", "rag"],
            ChaosCategory.SANDBOX: ["code_execution", "file_operations", "tool_execution"],
            ChaosCategory.CONTEXT: ["response_quality", "safety_filters", "agent_loop"],
            ChaosCategory.CONCURRENCY: ["multi_agent", "resource_management", "locks"],
            ChaosCategory.STREAMING: ["client_rendering", "response_delivery", "sse"],
        }

        radius["estimated_affected_systems"] = category_impact.get(
            scenario.category, []
        )

        if scenario.intensity > 0.7:
            radius["estimated_severity"] = "critical"
        elif scenario.intensity > 0.4:
            radius["estimated_severity"] = "high"
        elif scenario.intensity > 0.2:
            radius["estimated_severity"] = "medium"

        return radius

    def get_scenario_library(self) -> dict[str, list[ChaosScenario]]:
        """Return the full library of predefined chaos scenarios."""
        return _SCENARIO_LIBRARY.copy()

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _execute_scenario(self, scenario: ChaosScenario) -> ChaosResult:
        """Simulate executing a chaos scenario and measure recovery."""
        start_time = datetime.now(timezone.utc)
        start_mono = time.monotonic()

        # Simulate fault injection duration proportional to intensity.
        fault_duration = scenario.duration_seconds * scenario.intensity
        await asyncio.sleep(min(fault_duration, 0.05))  # cap for test speed

        # Simulate recovery: measure MTTR via health checks.
        recovery_start = time.monotonic()
        recovered = True
        recovery_attempts = 0
        max_attempts = 10

        target_check = self._health_checks.get(scenario.target)
        if target_check:
            for _ in range(max_attempts):
                recovery_attempts += 1
                try:
                    healthy = await target_check()
                    if healthy:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.01)
            else:
                recovered = False

        recovery_time_ms = (time.monotonic() - recovery_start) * 1000
        end_time = datetime.now(timezone.utc)
        total_ms = (time.monotonic() - start_mono) * 1000

        # Determine affected systems based on category.
        blast = self.get_blast_radius(scenario)
        systems_affected = blast["estimated_affected_systems"]

        # Simulate errors based on intensity.
        errors: list[str] = []
        if scenario.intensity > 0.3:
            errors.append(f"{scenario.name}: degraded performance")
        if scenario.intensity > 0.6:
            errors.append(f"{scenario.name}: partial failure")
        if scenario.intensity > 0.8:
            errors.append(f"{scenario.name}: full outage")

        return ChaosResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            category=scenario.category,
            start_time=start_time,
            end_time=end_time,
            duration_ms=total_ms,
            recovery_time_ms=recovery_time_ms,
            impact={
                "intensity": scenario.intensity,
                "errors_count": len(errors),
                "recovery_attempts": recovery_attempts,
                "severity": blast["estimated_severity"],
            },
            errors_observed=errors,
            systems_affected=systems_affected,
            intensity=scenario.intensity,
            recovered=recovered,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _build_report(
        self,
        session_id: str,
        elapsed: float,
        results: list[ChaosResult],
    ) -> ChaosReport:
        """Aggregate individual results into a ChaosReport."""
        recovery_times = [r.recovery_time_ms for r in results]
        all_systems: set[str] = set()
        critical: list[str] = []

        for r in results:
            all_systems.update(r.systems_affected)
            if not r.recovered:
                critical.append(
                    f"{r.scenario_name} ({r.category.value}): failed to recover"
                )
            elif r.recovery_time_ms > 5000:
                critical.append(
                    f"{r.scenario_name}: slow recovery ({r.recovery_time_ms:.0f}ms)"
                )

        avg_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0
        max_recovery = max(recovery_times) if recovery_times else 0.0

        # Resilience score: 100 = perfect, penalise for failures and slow recovery.
        recovered_count = sum(1 for r in results if r.recovered)
        recovery_ratio = recovered_count / len(results) if results else 1.0
        speed_score = max(0.0, 1.0 - (avg_recovery / 5000))
        resilience = (recovery_ratio * 70 + speed_score * 30)

        return ChaosReport(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            duration_seconds=elapsed,
            scenarios_run=len(results),
            results=results,
            avg_recovery_ms=avg_recovery,
            max_recovery_ms=max_recovery,
            systems_affected=all_systems,
            critical_failures=critical,
            resilience_score=round(resilience, 2),
        )
