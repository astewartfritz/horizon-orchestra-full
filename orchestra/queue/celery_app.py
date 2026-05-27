from __future__ import annotations

"""Celery application for long-running data jobs.

Lightweight agent tasks (sub-second) stay on JobQueue/Worker.
Heavy data work (embeddings, science ingestion, LLM batch, reports) goes here
so it runs in separate OS processes and never blocks the async event loop.

The module is importable even when Celery is not installed — only task
submission and worker startup will fail.  Check _HAS_CELERY before use.

Configuration via environment variables:
    REDIS_URL           Redis DSN used for both broker and result backend.
                        Default: redis://redis:6379/0
    CELERY_CONCURRENCY  Worker process count.  Default: 4
"""

import os

# Celery is an optional dependency (pip install 'horizon-orchestra[queue]').
# Keep the module always importable so project-wide import smoke tests pass.
try:
    from celery import Celery  # type: ignore[import-untyped]
    _HAS_CELERY = True
except ImportError:
    Celery = None  # type: ignore[assignment,misc]
    _HAS_CELERY = False

REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

if _HAS_CELERY:
    celery_app = Celery("orchestra", broker=REDIS_URL, backend=REDIS_URL)  # type: ignore[misc]
    celery_app.conf.update(
        # Serialization
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        # Reliability settings for long-running jobs
        task_acks_late=True,            # ack *after* the task finishes (re-queue on crash)
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,   # one task at a time per process (fair dispatch)
        worker_max_tasks_per_child=200, # recycle processes to prevent memory leaks

        # Results
        result_expires=86_400,          # keep results for 24 hours
        task_track_started=True,        # expose STARTED state

        # Routing — separate queues per job class so you can scale independently
        task_routes={
            "orchestra.queue.tasks.embed_documents":     {"queue": "embeddings"},
            "orchestra.queue.tasks.ingest_science_data": {"queue": "science"},
            "orchestra.queue.tasks.run_llm_batch":       {"queue": "llm"},
            "orchestra.queue.tasks.generate_report":     {"queue": "reports"},
        },

        # Default queue for tasks not matched above
        task_default_queue="default",

        timezone="UTC",
        enable_utc=True,

        # ── Periodic tasks (celery beat) ─────────────────────────────────────
        # Start the scheduler with:
        #   celery -A orchestra.queue.celery_app:celery_app beat
        beat_schedule={
            # Re-embed documents added since the last run (every 6 hours).
            "refresh-embeddings": {
                "task": "orchestra.queue.tasks.embed_documents",
                "schedule": 6 * 3600,
                "kwargs": {"documents": [], "pipeline_config": {"incremental": True}},
                "options": {"queue": "embeddings"},
            },
        },
    )
else:
    celery_app = None  # type: ignore[assignment]
