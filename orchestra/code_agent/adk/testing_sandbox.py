from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestra.code_agent.agent_headers.intent import Intent

__all__ = [
    "AgentTestingSandbox",
    "MockApiResponse",
    "ScenarioDefinition",
]


@dataclass
class MockApiResponse:
    """A simulated API response for sandbox testing."""
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    should_error: bool = False
    error_message: str = ""


@dataclass
class ScenarioDefinition:
    """A test scenario describing an agent interaction flow."""
    id: str = ""
    name: str = ""
    description: str = ""
    intent: Intent = Intent.UNKNOWN
    input_prompt: str = ""
    expected_mock_responses: list[MockApiResponse] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class AgentTestingSandbox:
    """Controlled environment for testing agent interactions.

    Simulates various API responses, edge cases, and error
    scenarios so developers can validate agent behavior
    against real-world conditions before deployment.
    """

    def __init__(self) -> None:
        self._scenarios: dict[str, ScenarioDefinition] = {}
        self._handlers: dict[str, Callable[..., MockApiResponse]] = {}
        self._results: dict[str, list[dict[str, Any]]] = {}

    def register_scenario(self, scenario: ScenarioDefinition) -> str:
        sid = scenario.id or str(uuid.uuid4())
        scenario.id = sid
        self._scenarios[sid] = scenario
        return sid

    def register_handler(
        self, scenario_id: str, handler: Callable[..., MockApiResponse]
    ) -> None:
        self._handlers[scenario_id] = handler

    def get_scenario(self, scenario_id: str) -> ScenarioDefinition | None:
        return self._scenarios.get(scenario_id)

    def list_scenarios(self) -> list[ScenarioDefinition]:
        return list(self._scenarios.values())

    def run_scenario(
        self,
        scenario_id: str,
        agent_fn: Callable[[str], str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            return {"error": f"Scenario {scenario_id} not found", "success": False}

        start = time.time()
        errors: list[str] = []
        responses: list[str] = []
        handler = self._handlers.get(scenario_id)

        try:
            response = agent_fn(scenario.input_prompt)
            responses.append(response)
            if handler:
                mock = handler(scenario.input_prompt)
                if mock.should_error:
                    errors.append(mock.error_message)
        except Exception as exc:
            errors.append(str(exc))

        elapsed = (time.time() - start) * 1000
        success = len(errors) == 0

        result = {
            "scenario_id": scenario_id,
            "scenario_name": scenario.name,
            "success": success,
            "latency_ms": round(elapsed, 1),
            "response_count": len(responses),
            "error_count": len(errors),
            "errors": errors,
            "responses": responses,
            "timestamp": time.time(),
        }
        self._results.setdefault(scenario_id, []).append(result)
        return result

    def get_results(self, scenario_id: str) -> list[dict[str, Any]]:
        return self._results.get(scenario_id, [])

    def summary(self) -> dict[str, Any]:
        total_runs = sum(len(v) for v in self._results.values())
        total_ok = sum(
            1 for runs in self._results.values() for r in runs if r.get("success")
        )
        return {
            "scenarios_registered": len(self._scenarios),
            "total_runs": total_runs,
            "passed": total_ok,
            "failed": total_runs - total_ok,
        }

    @staticmethod
    def default_scenarios() -> list[ScenarioDefinition]:
        return [
            ScenarioDefinition(
                name="order_status_happy",
                description="Customer order status lookup — normal flow",
                intent=Intent.ORDER_STATUS_CHECK,
                input_prompt="Check status of order ORD-123",
                expected_mock_responses=[
                    MockApiResponse(
                        status_code=200,
                        body={"order_id": "ORD-123", "status": "shipped"},
                    )
                ],
                tags=["orders", "happy-path"],
            ),
            ScenarioDefinition(
                name="order_status_not_found",
                description="Order ID not found — error case",
                intent=Intent.ORDER_STATUS_CHECK,
                input_prompt="Check status of order ORD-999",
                expected_mock_responses=[
                    MockApiResponse(
                        status_code=404,
                        body={"error": "Order not found"},
                    )
                ],
                tags=["orders", "error-case"],
            ),
            ScenarioDefinition(
                name="data_query_timeout",
                description="Data query that exceeds threshold — edge case",
                intent=Intent.DATA_QUERY,
                input_prompt="Run query: SELECT * FROM large_table",
                expected_mock_responses=[
                    MockApiResponse(
                        status_code=503,
                        body={"error": "Query timed out"},
                        latency_ms=30000.0,
                    )
                ],
                tags=["data", "timeout"],
            ),
            ScenarioDefinition(
                name="api_rate_limited",
                description="API returns 429 rate limit — recovery case",
                intent=Intent.DATA_QUERY,
                input_prompt="Fetch recent orders",
                expected_mock_responses=[
                    MockApiResponse(
                        status_code=429,
                        headers={"Retry-After": "30"},
                        body={"error": "Rate limit exceeded"},
                    )
                ],
                tags=["rate-limit", "recovery"],
            ),
            ScenarioDefinition(
                name="malformed_response",
                description="API returns unexpected data — robustness test",
                intent=Intent.ANALYSIS,
                input_prompt="Analyze sales data",
                expected_mock_responses=[
                    MockApiResponse(
                        status_code=200,
                        body={"unexpected": "format"},
                    )
                ],
                tags=["robustness", "edge-case"],
            ),
        ]
