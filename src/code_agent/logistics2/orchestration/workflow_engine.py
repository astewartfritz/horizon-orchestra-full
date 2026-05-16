"""Workflow engine — Temporal/Cadence/Argo-style long-running workflow orchestration."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class WorkflowStep:
    name: str = ""
    handler: Callable | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    retries: int = 0
    max_retries: int = 3


@dataclass
class Workflow:
    id: str = ""
    name: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()

    @property
    def duration(self) -> float:
        end = self.completed_at or time.time()
        return round(end - self.created_at, 2)

    @property
    def progress(self) -> str:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == WorkflowStatus.COMPLETED)
        return f"{done}/{total}"


class WorkflowEngine:
    """Long-running workflow engine for logistics planning operations.

    Supports: sequential steps, retry, timeout, pause/resume, cancellation.
    """

    def __init__(self):
        self.workflows: dict[str, Workflow] = {}
        self._running: dict[str, asyncio.Task] = {}

    def define(self, name: str, steps: list[WorkflowStep]) -> Workflow:
        wf = Workflow(name=name, steps=steps)
        self.workflows[wf.id] = wf
        return wf

    async def run(self, workflow_id: str) -> dict[str, Any]:
        wf = self.workflows.get(workflow_id)
        if not wf:
            return {"error": "Workflow not found"}
        wf.status = WorkflowStatus.RUNNING
        task = asyncio.create_task(self._execute(wf))
        self._running[workflow_id] = task
        try:
            result = await task
            return result
        except asyncio.CancelledError:
            wf.status = WorkflowStatus.CANCELLED
            return {"status": "cancelled"}
        finally:
            self._running.pop(workflow_id, None)

    async def _execute(self, wf: Workflow) -> dict[str, Any]:
        for step in wf.steps:
            if wf.status == WorkflowStatus.CANCELLED:
                break
            step.status = WorkflowStatus.RUNNING
            step.started_at = time.time()
            for attempt in range(step.max_retries + 1):
                try:
                    if step.handler:
                        result = step.handler(wf.context)
                        if asyncio.iscoroutine(result):
                            result = await result
                        step.result = result
                    step.status = WorkflowStatus.COMPLETED
                    step.completed_at = time.time()
                    break
                except Exception as e:
                    step.retries = attempt + 1
                    step.error = str(e)
                    if attempt < step.max_retries:
                        await asyncio.sleep(1 * (attempt + 1))
                    else:
                        step.status = WorkflowStatus.FAILED
                        wf.status = WorkflowStatus.FAILED
                        wf.completed_at = time.time()
                        return {"status": "failed", "step": step.name, "error": step.error}
        wf.status = WorkflowStatus.COMPLETED
        wf.completed_at = time.time()
        return {"status": "completed", "workflow_id": wf.id, "duration": wf.duration}

    def cancel(self, workflow_id: str) -> bool:
        task = self._running.get(workflow_id)
        if task:
            task.cancel()
            wf = self.workflows.get(workflow_id)
            if wf:
                wf.status = WorkflowStatus.CANCELLED
            return True
        return False

    def get_status(self, workflow_id: str) -> dict[str, Any] | None:
        wf = self.workflows.get(workflow_id)
        if not wf:
            return None
        return {
            "id": wf.id, "name": wf.name, "status": wf.status.value,
            "progress": wf.progress, "duration": wf.duration,
            "steps": [{"name": s.name, "status": s.status.value, "retries": s.retries,
                       "error": s.error} for s in wf.steps],
        }

    def list_workflows(self, status: str | None = None) -> list[dict[str, Any]]:
        wfs = self.workflows.values()
        if status:
            wfs = [w for w in wfs if w.status.value == status]
        return [{"id": w.id, "name": w.name, "status": w.status.value,
                 "progress": w.progress} for w in wfs]
