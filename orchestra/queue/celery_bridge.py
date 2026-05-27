from __future__ import annotations

"""Bridge between the Orchestra JobQueue interface and Celery.

Callers use the same submit/status pattern regardless of whether a job runs
on the in-process Worker or a Celery data-job worker.

Usage::

    from orchestra.queue.celery_bridge import submit_data_job, get_data_job_status

    job = submit_data_job("embed_documents", {"documents": [...], "pipeline_config": {}})
    print(job.id, job.status)   # "abc123", "pending"

    # Later:
    job = get_data_job_status(job.id)
    print(job.status, job.result)  # "done", {"embedded": 42, ...}
"""

import time
from typing import Any

from .job import Job

# Lazy import so the module is importable even without celery installed.
def _celery_app():  # type: ignore[return]
    from .celery_app import celery_app  # noqa: PLC0415
    return celery_app


# Map Celery task states → Job status values
_STATE_MAP: dict[str, str] = {
    "PENDING":  "pending",
    "RECEIVED": "pending",
    "STARTED":  "running",
    "RETRY":    "pending",
    "SUCCESS":  "done",
    "FAILURE":  "failed",
    "REVOKED":  "dead",
}

# Registered task names in celery_app
_TASK_NAMES: dict[str, str] = {
    "embed_documents":    "orchestra.queue.tasks.embed_documents",
    "ingest_science_data": "orchestra.queue.tasks.ingest_science_data",
    "run_llm_batch":       "orchestra.queue.tasks.run_llm_batch",
    "generate_report":     "orchestra.queue.tasks.generate_report",
}


def submit_data_job(
    name: str,
    payload: dict[str, Any],
    priority: int = 5,
    countdown: int = 0,
) -> Job:
    """Dispatch a data job to Celery and return a Job whose ID is the task ID.

    Args:
        name:      Short task name (key in _TASK_NAMES) or full dotted name.
        payload:   Keyword arguments forwarded to the task function.
        priority:  Celery priority 0–9 (maps to AMQP/Redis priority).
        countdown: Delay in seconds before the task becomes eligible.

    Returns:
        A Job object with status="pending" and id=<celery task id>.

    Raises:
        ValueError:  If *name* is not a known data job.
        ImportError: If celery is not installed.
    """
    task_name = _TASK_NAMES.get(name, name)
    app = _celery_app()
    result = app.send_task(
        task_name,
        kwargs=payload,
        priority=priority,
        countdown=countdown,
    )
    return Job(
        id=result.id,
        name=name,
        payload=payload,
        status="pending",
        priority=priority,
        created_at=time.time(),
    )


def get_data_job_status(job_id: str) -> Job:
    """Poll Celery for the current state of a data job.

    Args:
        job_id: The task ID returned by submit_data_job().

    Returns:
        A Job object reflecting the latest Celery task state.
    """
    from celery.result import AsyncResult  # type: ignore[import-untyped]

    ar = AsyncResult(job_id, app=_celery_app())
    state: str = ar.state  # e.g. "PENDING", "STARTED", "SUCCESS", "FAILURE"
    status = _STATE_MAP.get(state, "pending")

    result: dict[str, Any] | None = None
    error: str | None = None
    finished_at: float | None = None

    if state == "SUCCESS":
        raw = ar.result
        result = raw if isinstance(raw, dict) else {"value": raw}
        finished_at = time.time()
    elif state == "FAILURE":
        error = str(ar.result)
        finished_at = time.time()

    return Job(
        id=job_id,
        name="",        # task name not stored in AsyncResult by default
        payload={},
        status=status,
        result=result,
        error=error,
        finished_at=finished_at,
        created_at=0.0,
    )


def revoke_data_job(job_id: str, terminate: bool = False) -> None:
    """Cancel a pending (or running) data job.

    Args:
        job_id:    Task ID to revoke.
        terminate: If True, send SIGTERM to the worker process (running tasks).
    """
    _celery_app().control.revoke(job_id, terminate=terminate)
