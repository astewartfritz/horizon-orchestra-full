"""orchestra.checkpoint — Durable workflow checkpointing.

Enables AgentLoop to serialize its full message history and iteration
count to disk after each step, so a crashed or interrupted workflow
can resume from where it left off rather than starting over.

Usage::

    store = CheckpointStore(".orchestra_checkpoints")
    loop = AgentLoop(router, tools, config, checkpoint_store=store, job_id="my-job")
    async for event in loop.run(task):
        ...
    # On restart, the loop detects the checkpoint and skips replayed history.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["WorkflowCheckpoint", "CheckpointStore"]

log = logging.getLogger(__name__)


@dataclass
class WorkflowCheckpoint:
    """Serializable snapshot of an in-progress AgentLoop run."""
    job_id: str
    task: str
    messages: list[dict[str, Any]]
    iteration: int = 0
    total_tool_calls: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CheckpointStore:
    """File-backed checkpoint store — one atomic JSON file per job_id.

    Writes are atomic (write to .tmp, then rename) so a crash during
    save cannot corrupt the previous checkpoint.

    Parameters
    ----------
    directory:
        Directory to store checkpoint files. Created if it does not exist.
    """

    def __init__(self, directory: str | Path = ".orchestra_checkpoints") -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Path helpers ───────────────────────────────────────────────────────

    def _path(self, job_id: str) -> Path:
        safe = job_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._dir / f"{safe}.json"

    # ── CRUD ───────────────────────────────────────────────────────────────

    def save(self, checkpoint: WorkflowCheckpoint) -> None:
        """Atomically persist *checkpoint* to disk."""
        checkpoint.updated_at = time.time()
        data = asdict(checkpoint)
        target = self._path(checkpoint.job_id)
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(target)
        except Exception as exc:
            log.warning("CheckpointStore.save failed for %s: %s", checkpoint.job_id, exc)
            tmp.unlink(missing_ok=True)

    def load(self, job_id: str) -> WorkflowCheckpoint | None:
        """Return the saved checkpoint for *job_id*, or ``None`` if absent."""
        p = self._path(job_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return WorkflowCheckpoint(**data)
        except Exception as exc:
            log.warning("CheckpointStore.load failed for %s: %s", job_id, exc)
            return None

    def delete(self, job_id: str) -> None:
        """Remove the checkpoint for *job_id* (call on successful completion)."""
        self._path(job_id).unlink(missing_ok=True)

    def list_jobs(self) -> list[str]:
        """Return all job_ids that have saved checkpoints."""
        return [p.stem for p in self._dir.glob("*.json")]
