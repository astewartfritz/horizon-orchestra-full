"""Three observability layers for the agent harness.

§3.1 Component observability — failure-to-component mapping in harness substrate.
§3.2 Experience observability — layered evidence corpus with drill-down.
§3.3 Decision observability — change manifest with prediction + verification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════ §3.1
# Component Observability


class Component(str, Enum):
    """Every failure maps to exactly one component class."""
    LLM = "llm"
    TOOL = "tool"
    FILESYSTEM = "filesystem"
    CONFIG = "config"
    MEMORY = "memory"
    NETWORK = "network"
    HARNESS = "harness"
    REASONING = "reasoning"
    SKILL = "skill"
    UNKNOWN = "unknown"


FAILURE_PATTERNS: dict[str, Component] = {
    # LLM failures
    "rate_limit_exceeded": Component.LLM,
    "context_length_exceeded": Component.LLM,
    "invalid_api_key": Component.LLM,
    "model_not_found": Component.LLM,
    "api_timeout": Component.LLM,
    "llm_error": Component.LLM,
    # Tool failures
    "tool_not_found": Component.TOOL,
    "tool_execution_error": Component.TOOL,
    "invalid_tool_arguments": Component.TOOL,
    # Filesystem failures
    "permission_denied": Component.FILESYSTEM,
    "file_not_found": Component.FILESYSTEM,
    "outside_workspace": Component.FILESYSTEM,
    "extension_blocked": Component.FILESYSTEM,
    "secret_detected": Component.FILESYSTEM,
    # Config failures
    "config_read_only": Component.CONFIG,
    "frozen_config": Component.CONFIG,
    # Memory failures
    "memory_store_error": Component.MEMORY,
    "memory_retrieval_error": Component.MEMORY,
    # Network failures
    "dns_resolution_failed": Component.NETWORK,
    "connection_refused": Component.NETWORK,
    "request_timeout": Component.NETWORK,
    # Harness failures
    "dangerous_command": Component.HARNESS,
    "protected_directory": Component.HARNESS,
    "seed_prompt_removed": Component.HARNESS,
}


@dataclass
class ComponentEvent:
    """A single observability event tagged with its component class."""
    id: str = ""
    component: str = Component.UNKNOWN.value
    event_type: str = ""          # e.g. "tool_call", "tool_result", "failure", "prediction", "verification"
    name: str = ""                 # e.g. tool name, failure pattern, edit path
    outcome: str = ""              # "success", "failure", "blocked", "pending"
    detail: str = ""               # human-readable description
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    round_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComponentRegistry:
    """Maps failure patterns and events to component classes.

    The harness substrate calls ``register()`` on every tool execution,
    failure, and decision point. Each event is tagged with exactly one
    component class so that post-hoc analysis can attribute every outcome
    to a single component.
    """

    def __init__(self):
        self._events: list[ComponentEvent] = []
        self._run_id = ""
        self._round = 0

    def start_run(self, run_id: str) -> None:
        self._run_id = run_id
        self._round = 0
        self._events.clear()

    def next_round(self) -> int:
        self._round += 1
        return self._round

    def register(
        self,
        event_type: str,
        name: str = "",
        outcome: str = "success",
        detail: str = "",
        component: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ComponentEvent:
        """Record an event, auto-detecting component from failure patterns."""
        if not component:
            component = FAILURE_PATTERNS.get(name, FAILURE_PATTERNS.get(detail, Component.UNKNOWN)).value
        ev = ComponentEvent(
            id=uuid.uuid4().hex[:12],
            component=component,
            event_type=event_type,
            name=name,
            outcome=outcome,
            detail=detail,
            metadata=metadata or {},
            timestamp=time.time(),
            run_id=self._run_id,
            round_index=self._round,
        )
        self._events.append(ev)
        return ev

    def failures_by_component(self) -> dict[str, list[ComponentEvent]]:
        """Return all failure events grouped by component class."""
        groups: dict[str, list[ComponentEvent]] = {}
        for ev in self._events:
            if ev.outcome in ("failure", "blocked"):
                groups.setdefault(ev.component, []).append(ev)
        return groups

    def summary(self) -> dict[str, Any]:
        """Aggregate statistics per component."""
        counts: dict[str, dict[str, int]] = {}
        for ev in self._events:
            d = counts.setdefault(ev.component, {"total": 0, "success": 0, "failure": 0, "blocked": 0})
            d["total"] += 1
            if ev.outcome in counts[ev.component]:
                counts[ev.component][ev.outcome] += 1
        return counts

    @property
    def events(self) -> list[ComponentEvent]:
        return list(self._events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "total_events": len(self._events),
            "by_component": self.summary(),
            "failures": {c: [e.to_dict() for e in evs] for c, evs in self.failures_by_component().items()},
        }


# ═══════════════════════════════════════════════════════════════════ §3.2
# Experience Observability


@dataclass
class EvidenceEntry:
    """A single piece of evidence in the corpus."""
    id: str = ""
    level: str = "raw"            # "raw" | "distilled" | "indexed"
    category: str = ""             # "tool_call", "llm_response", "edit", "failure", "prediction", "verification"
    content: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    component: str = Component.UNKNOWN.value
    run_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceCorpus:
    """Layered evidence corpus distilled from raw rollouts.

    Three layers:
    - **Raw**: every tool call, LLM response, and event as-is.
    - **Distilled**: condensed summaries of each round (what happened, outcome).
    - **Indexed**: tagged by component, category, and tag for drill-down search.
    """

    RAW = "raw"
    DISTILLED = "distilled"
    INDEXED = "indexed"

    def __init__(self):
        self._entries: list[EvidenceEntry] = []
        self._run_id = ""

    def start_run(self, run_id: str) -> None:
        self._run_id = run_id
        self._entries.clear()

    def record_raw(
        self,
        category: str,
        content: str,
        component: str = Component.UNKNOWN.value,
        tags: list[str] | None = None,
    ) -> EvidenceEntry:
        entry = EvidenceEntry(
            id=uuid.uuid4().hex[:12],
            level=self.RAW,
            category=category,
            content=content,
            component=component,
            tags=tags or [],
            run_id=self._run_id,
        )
        self._entries.append(entry)
        return entry

    def record_distilled(
        self,
        category: str,
        summary: str,
        content: str = "",
        component: str = Component.UNKNOWN.value,
        tags: list[str] | None = None,
    ) -> EvidenceEntry:
        entry = EvidenceEntry(
            id=uuid.uuid4().hex[:12],
            level=self.DISTILLED,
            category=category,
            content=content,
            summary=summary,
            component=component,
            tags=tags or [],
            run_id=self._run_id,
        )
        self._entries.append(entry)
        return entry

    def record_indexed(
        self,
        category: str,
        summary: str,
        content: str = "",
        component: str = Component.UNKNOWN.value,
        tags: list[str] | None = None,
    ) -> EvidenceEntry:
        entry = EvidenceEntry(
            id=uuid.uuid4().hex[:12],
            level=self.INDEXED,
            category=category,
            content=content,
            summary=summary,
            component=component,
            tags=tags or [],
            run_id=self._run_id,
        )
        self._entries.append(entry)
        return entry

    def drill_down(self, level: str | None = None, category: str | None = None,
                   component: str | None = None, tag: str | None = None) -> list[EvidenceEntry]:
        """Filtered search across the corpus — drill-down from summary to detail."""
        results = self._entries
        if level:
            results = [e for e in results if e.level == level]
        if category:
            results = [e for e in results if e.category == category]
        if component:
            results = [e for e in results if e.component == component]
        if tag:
            results = [e for e in results if tag in e.tags]
        return results

    def summary(self) -> dict[str, Any]:
        counts = {"total": len(self._entries), "raw": 0, "distilled": 0, "indexed": 0}
        for e in self._entries:
            counts[e.level] = counts.get(e.level, 0) + 1
        return counts

    @property
    def entries(self) -> list[EvidenceEntry]:
        return list(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "summary": self.summary(),
            "entries": [e.to_dict() for e in self._entries],
        }


# ═══════════════════════════════════════════════════════════════════ §3.3
# Decision Observability


@dataclass
class ManifestEntry:
    """A single entry in the change manifest.

    Every edit is paired with the agent's self-declared prediction about
    what the edit will achieve. The next round checks whether that
    prediction held.
    """
    id: str = ""
    edit_path: str = ""            # file that was edited
    edit_summary: str = ""         # what changed (brief)
    prediction: str = ""           # agent's self-declared prediction
    predicted_outcome: str = ""    # what the agent said would happen
    actual_outcome: str = ""       # what actually happened (filled next round)
    prediction_held: bool | None = None  # verified next round
    round_index: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChangeManifest:
    """Pairs every edit with a self-declared prediction that the next round verifies.

    The harness intercepts write tool calls and, before executing, prompts
    the agent (via the event queue) for a prediction. That prediction is
    stored alongside the edit. On the next tool call or round end, the
    harness checks whether the agent's earlier prediction matched reality.
    """

    def __init__(self):
        self._entries: list[ManifestEntry] = []
        self._pending: ManifestEntry | None = None
        self._run_id = ""

    def start_run(self, run_id: str) -> None:
        self._run_id = run_id
        self._entries.clear()
        self._pending = None

    def record_edit(self, edit_path: str, summary: str, prediction: str,
                    predicted_outcome: str, round_index: int) -> ManifestEntry:
        """Record an edit with the agent's self-declared prediction."""
        entry = ManifestEntry(
            id=uuid.uuid4().hex[:12],
            edit_path=edit_path,
            edit_summary=summary,
            prediction=prediction,
            predicted_outcome=predicted_outcome,
            round_index=round_index,
        )
        self._entries.append(entry)
        self._pending = entry
        return entry

    def verify_pending(self, actual_outcome: str) -> ManifestEntry | None:
        """Verify the most recent pending prediction against reality."""
        if self._pending is None:
            return None
        self._pending.actual_outcome = actual_outcome
        self._pending.prediction_held = self._pending.predicted_outcome == actual_outcome
        entry = self._pending
        self._pending = None
        return entry

    @property
    def entries(self) -> list[ManifestEntry]:
        return list(self._entries)

    def accuracy(self) -> float:
        """Fraction of predictions that held."""
        verified = [e for e in self._entries if e.prediction_held is not None]
        if not verified:
            return 0.0
        return sum(1 for e in verified if e.prediction_held) / len(verified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "total_edits": len(self._entries),
            "accuracy": self.accuracy(),
            "entries": [e.to_dict() for e in self._entries],
        }


# ═══════════════════════════════════════════════════════════════════
# Combined observability facade


class Observability:
    """All three observability layers in one facade.

    Wired into the harness substrate so every tool call, failure, edit,
    and decision produces events across all three layers.
    """

    def __init__(self):
        self.components = ComponentRegistry()
        self.evidence = EvidenceCorpus()
        self.manifest = ChangeManifest()
        self._run_id = ""
        self._edit_count = 0

    def start_run(self, task: str) -> str:
        run_id = uuid.uuid4().hex[:16]
        self._run_id = run_id
        self._edit_count = 0
        self.components.start_run(run_id)
        self.evidence.start_run(run_id)
        self.manifest.start_run(run_id)
        self.evidence.record_raw("run_start", f"Task: {task}", tags=["run"])
        return run_id

    def end_run(self, result: str) -> dict[str, Any]:
        self.evidence.record_distilled(
            "run_end", f"Completed with {self._edit_count} edits, {len(self.manifest.entries)} predictions",
            content=result[:2000], tags=["run"],
        )
        return self.to_dict()

    def on_tool_call(self, tool_name: str, args: dict[str, Any]) -> None:
        round_idx = self.components.next_round()
        self.components.register("tool_call", name=tool_name, outcome="pending",
                                 metadata={"args": args})
        self.evidence.record_raw("tool_call", f"{tool_name}({args})",
                                 tags=[tool_name])

    def on_tool_result(self, tool_name: str, outcome: str, detail: str = "",
                       error: str | None = None) -> None:
        comp = Component.UNKNOWN.value
        if error:
            comp = FAILURE_PATTERNS.get(tool_name, FAILURE_PATTERNS.get(error, Component.UNKNOWN)).value
            outcome = "failure"
        self.components.register("tool_result", name=tool_name, outcome=outcome,
                                 detail=detail or error or "", component=comp)
        self.evidence.record_raw("tool_result", detail or error or "",
                                 component=comp, tags=[tool_name])

    def on_edit(self, edit_path: str, summary: str, prediction: str,
                predicted_outcome: str) -> ManifestEntry | None:
        self._edit_count += 1
        round_idx = self.components._round
        entry = self.manifest.record_edit(edit_path, summary, prediction,
                                          predicted_outcome, round_idx)
        self.components.register("edit", name=edit_path, outcome="pending",
                                 detail=summary, component=Component.FILESYSTEM.value)
        self.evidence.record_distilled("edit", f"{edit_path}: {summary}",
                                       f"Prediction: {prediction}",
                                       tags=["edit", f"round_{round_idx}"])
        return entry

    def on_failure(self, name: str, detail: str) -> ComponentEvent:
        comp = FAILURE_PATTERNS.get(name, FAILURE_PATTERNS.get(detail, Component.UNKNOWN)).value
        ev = self.components.register("failure", name=name, outcome="failure",
                                      detail=detail, component=comp)
        self.evidence.record_indexed("failure", f"{name}: {detail}",
                                     component=comp, tags=["failure"])
        return ev

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "components": self.components.to_dict(),
            "evidence": self.evidence.to_dict(),
            "manifest": self.manifest.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
