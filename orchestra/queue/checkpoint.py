from __future__ import annotations

"""Durable workflow checkpoint store.

Writes kernel state to a JSON file so long-running workflows can resume
after a process crash or restart — the simplest possible implementation
of Temporal-style durable execution without the Temporal dependency.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["WorkflowCheckpoint", "CheckpointStore"]

log = logging.getLogger("orchestra.queue.checkpoint")

_DEFAULT_DIR = Path(os.getenv("ORCHESTRA_CHECKPOINT_DIR", ".orchestra_checkpoints"))


@dataclass
class WorkflowCheckpoint:
    """Snapshot of a running workflow at a single point in time."""

    workflow_id: str
    goal: str
    plan: list[dict[str, Any]]          # serialised PlanStep dicts
    current_step: int
    total_tool_calls: int
    replans: int
    results: list[str]
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkflowCheckpoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class CheckpointStore:
    """Read / write workflow checkpoints as JSON files.

    One file per workflow_id under *directory*.  Small enough that SQLite
    is overkill; easy to inspect and debug by hand.
    """

    def __init__(self, directory: Path | str = _DEFAULT_DIR) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def save(self, cp: WorkflowCheckpoint) -> None:
        cp.updated_at = time.time()
        path = self._dir / f"{cp.workflow_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic rename
        log.debug("checkpoint saved: %s step=%d", cp.workflow_id, cp.current_step)

    def load(self, workflow_id: str) -> WorkflowCheckpoint | None:
        path = self._dir / f"{workflow_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkflowCheckpoint.from_dict(data)
        except Exception as exc:
            log.warning("checkpoint corrupt for %s: %s", workflow_id, exc)
            return None

    def delete(self, workflow_id: str) -> None:
        path = self._dir / f"{workflow_id}.json"
        path.unlink(missing_ok=True)

    def list_ids(self) -> list[str]:
        return [p.stem for p in self._dir.glob("*.json")]
