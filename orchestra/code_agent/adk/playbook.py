from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.agent_headers.models import Intent

__all__ = [
    "PlaybookEntry",
    "PromptPlaybook",
    "ReplayEngine",
    "ReplayRecord",
]


@dataclass
class PlaybookEntry:
    """A single prompt template in the playbook."""
    id: str = ""
    name: str = ""
    intent: Intent = Intent.UNKNOWN
    prompt_template: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    required_params: list[str] = field(default_factory=list)
    expected_response_hint: str = ""


@dataclass
class ReplayRecord:
    """Captures a single agent interaction for replay."""
    id: str = ""
    timestamp: float = 0.0
    intent: str = ""
    prompt: str = ""
    response: str = ""
    latency_ms: float = 0.0
    success: bool = True
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptPlaybook:
    """Predefined prompt templates organized by intent.

    Helps developers build consistent agent interactions
    without reinventing prompts for common tasks.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PlaybookEntry] = {}

    def register(self, entry: PlaybookEntry) -> None:
        eid = entry.id or str(uuid.uuid4())
        entry.id = eid
        self._entries[eid] = entry

    def get(self, entry_id: str) -> PlaybookEntry | None:
        return self._entries.get(entry_id)

    def find_by_intent(self, intent: Intent) -> list[PlaybookEntry]:
        return [e for e in self._entries.values() if e.intent == intent]

    def find_by_tag(self, tag: str) -> list[PlaybookEntry]:
        return [e for e in self._entries.values() if tag in e.tags]

    def list_all(self) -> list[PlaybookEntry]:
        return list(self._entries.values())

    def build_prompt(self, entry_id: str, params: dict[str, str]) -> str | None:
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        prompt = entry.prompt_template
        for key, value in params.items():
            prompt = prompt.replace(f"{{{key}}}", value)
        return prompt

    def remove(self, entry_id: str) -> bool:
        return self._entries.pop(entry_id, None) is not None

    @staticmethod
    def default_entries() -> list[PlaybookEntry]:
        return [
            PlaybookEntry(
                name="order_status",
                intent=Intent.ORDER_STATUS_CHECK,
                prompt_template="Check the status of order {order_id} for customer {customer_id}.",
                description="Retrieve current status of a customer order",
                tags=["orders", "customer_service"],
                required_params=["order_id", "customer_id"],
            ),
            PlaybookEntry(
                name="data_query_sql",
                intent=Intent.DATA_QUERY,
                prompt_template="Run a SQL query against the {dataset} dataset: {query}. Return results as {format}.",
                description="Execute a SQL data query against a named dataset",
                tags=["data", "analytics"],
                required_params=["dataset", "query", "format"],
            ),
            PlaybookEntry(
                name="trend_analysis",
                intent=Intent.ANALYSIS,
                prompt_template="Analyze {metric} trends over the last {period} for {segment}. Highlight anomalies.",
                description="Perform trend analysis with anomaly detection",
                tags=["analytics", "metrics"],
                required_params=["metric", "period", "segment"],
            ),
            PlaybookEntry(
                name="generate_report",
                intent=Intent.REPORT_GENERATION,
                prompt_template="Generate a {report_type} report for {entity} covering {date_range}. Include {sections}.",
                description="Generate a structured report",
                tags=["reports", "documentation"],
                required_params=["report_type", "entity", "date_range", "sections"],
            ),
            PlaybookEntry(
                name="troubleshoot_service",
                intent=Intent.TROUBLESHOOTING,
                prompt_template="Troubleshoot {service} issue: {symptoms}. Check {log_source} for errors.",
                description="Diagnose and resolve service issues",
                tags=["ops", "support"],
                required_params=["service", "symptoms", "log_source"],
            ),
            PlaybookEntry(
                name="configure_resource",
                intent=Intent.CONFIGURATION,
                prompt_template="Configure {resource} with settings: {settings}. Validate the configuration.",
                description="Apply and validate resource configuration",
                tags=["ops", "admin"],
                required_params=["resource", "settings"],
            ),
        ]


class ReplayEngine:
    """Records and replays agent interactions for testing and debugging.

    Agents can replay prior interactions to verify multi-turn
    accuracy, diagnose regressions, and optimize prompts.
    """

    def __init__(self) -> None:
        self._records: dict[str, ReplayRecord] = {}

    def record(self, record: ReplayRecord) -> str:
        rid = record.id or str(uuid.uuid4())
        record.id = rid
        if record.timestamp == 0.0:
            record.timestamp = time.time()
        self._records[rid] = record
        return rid

    def get(self, record_id: str) -> ReplayRecord | None:
        return self._records.get(record_id)

    def replay(self, record_id: str) -> str | None:
        record = self._records.get(record_id)
        if record is None:
            return None
        return record.response

    def find_by_intent(self, intent: str) -> list[ReplayRecord]:
        return [r for r in self._records.values() if r.intent == intent]

    def find_by_tag(self, tag: str) -> list[ReplayRecord]:
        return [r for r in self._records.values() if tag in r.tags]

    def list_recent(self, limit: int = 50) -> list[ReplayRecord]:
        sorted_records = sorted(
            self._records.values(), key=lambda r: r.timestamp, reverse=True
        )
        return sorted_records[:limit]

    def export(self, record_id: str) -> str | None:
        record = self._records.get(record_id)
        if record is None:
            return None
        return json.dumps({
            "id": record.id,
            "timestamp": record.timestamp,
            "intent": record.intent,
            "prompt": record.prompt,
            "response": record.response,
            "latency_ms": record.latency_ms,
            "success": record.success,
            "tags": record.tags,
            "metadata": record.metadata,
        }, indent=2, default=str)

    def import_json(self, data: str) -> str | None:
        try:
            raw = json.loads(data)
            record = ReplayRecord(
                id=raw.get("id", ""),
                timestamp=raw.get("timestamp", time.time()),
                intent=raw.get("intent", ""),
                prompt=raw.get("prompt", ""),
                response=raw.get("response", ""),
                latency_ms=raw.get("latency_ms", 0.0),
                success=raw.get("success", True),
                tags=raw.get("tags", []),
                metadata=raw.get("metadata", {}),
            )
            return self.record(record)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def delete(self, record_id: str) -> bool:
        return self._records.pop(record_id, None) is not None
