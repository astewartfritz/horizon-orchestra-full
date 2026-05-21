from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.agent_headers.models import Intent

__all__ = [
    "IntentLibrary",
    "IntentTemplate",
    "QueryBuilder",
]


@dataclass
class IntentTemplate:
    """A ready-made intent template aligned with the intent-based API."""
    id: str = ""
    intent: Intent = Intent.UNKNOWN
    name: str = ""
    description: str = ""
    header_value: str = ""
    query_structure: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)
    example_prompt: str = ""


class QueryBuilder:
    """Helps developers build structured queries for intent-based APIs.

    Validates required fields and produces a normalized query dict
    that matches the API's intent schema.
    """

    def __init__(self, template: IntentTemplate) -> None:
        self._template = template

    def build(self, fields: dict[str, Any]) -> dict[str, Any]:
        missing = [f for f in self._template.required_fields if f not in fields]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        query = dict(self._template.query_structure)
        query.update(fields)
        return query

    def validate(self, fields: dict[str, Any]) -> list[str]:
        return [f for f in self._template.required_fields if f not in fields]

    @property
    def template(self) -> IntentTemplate:
        return self._template


class IntentLibrary:
    """Registry of intent templates and query builders.

    Provides ready-made templates that align with the
    intent-based API header system so agents produce
    structured, compliant queries automatically.
    """

    def __init__(self) -> None:
        self._templates: dict[str, IntentTemplate] = {}

    def register(self, template: IntentTemplate) -> None:
        self._templates[template.id or template.name] = template

    def get(self, template_id: str) -> IntentTemplate | None:
        return self._templates.get(template_id)

    def find_by_intent(self, intent: Intent) -> list[IntentTemplate]:
        return [t for t in self._templates.values() if t.intent == intent]

    def list_all(self) -> list[IntentTemplate]:
        return list(self._templates.values())

    def create_builder(self, template_id: str) -> QueryBuilder | None:
        template = self._templates.get(template_id)
        if template is None:
            return None
        return QueryBuilder(template)

    def remove(self, template_id: str) -> bool:
        return self._templates.pop(template_id, None) is not None

    @staticmethod
    def default_templates() -> list[IntentTemplate]:
        return [
            IntentTemplate(
                name="check_order",
                intent=Intent.ORDER_STATUS_CHECK,
                description="Check the status of a customer order",
                header_value="order_status_check",
                query_structure={
                    "order_id": "",
                    "customer_id": "",
                    "include_history": False,
                },
                required_fields=["order_id"],
                example_prompt="Check status of order ORD-123 for customer CUST-456",
            ),
            IntentTemplate(
                name="run_data_query",
                intent=Intent.DATA_QUERY,
                description="Execute a data query against a dataset",
                header_value="data_query",
                query_structure={
                    "dataset": "",
                    "query": "",
                    "format": "json",
                    "max_rows": 100,
                },
                required_fields=["dataset", "query"],
                example_prompt="Query the sales dataset for Q4 2025 totals",
            ),
            IntentTemplate(
                name="perform_analysis",
                intent=Intent.ANALYSIS,
                description="Run analysis with optional anomaly detection",
                header_value="analysis",
                query_structure={
                    "metric": "",
                    "period": "",
                    "segment": "",
                    "detect_anomalies": True,
                },
                required_fields=["metric", "period"],
                example_prompt="Analyze revenue trends over the last 30 days",
            ),
            IntentTemplate(
                name="generate_report",
                intent=Intent.REPORT_GENERATION,
                description="Generate a structured report",
                header_value="report_generation",
                query_structure={
                    "report_type": "",
                    "entity": "",
                    "date_range": "",
                    "sections": [],
                    "format": "markdown",
                },
                required_fields=["report_type", "entity", "date_range"],
                example_prompt="Generate a monthly performance report for team Alpha covering Jan 2026",
            ),
            IntentTemplate(
                name="troubleshoot_issue",
                intent=Intent.TROUBLESHOOTING,
                description="Diagnose and resolve a technical issue",
                header_value="troubleshooting",
                query_structure={
                    "service": "",
                    "symptoms": "",
                    "log_source": "",
                    "severity": "medium",
                },
                required_fields=["service", "symptoms"],
                example_prompt="Troubleshoot the database connection pool exhaustion",
            ),
        ]
