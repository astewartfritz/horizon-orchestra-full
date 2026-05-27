from __future__ import annotations

"""Celery task definitions for long-running data jobs.

Each task runs in a separate worker process.  Async helpers are called via
asyncio.run() so they don't require an already-running event loop.

Task groups
-----------
embeddings  embed_documents
science     ingest_science_data
llm         run_llm_batch
reports     generate_report
"""

import asyncio
import logging
import time
from typing import Any

from .celery_app import celery_app, _HAS_CELERY

log = logging.getLogger(__name__)


def _task(**kwargs):
    """Return a Celery task decorator, or a pass-through when Celery is absent.

    Using this helper keeps every @_task(...) call valid at import time even
    when the optional celery dependency is not installed.
    """
    if celery_app is None:
        def _noop(fn):
            """Stub: raises ImportError at call time when celery is not installed."""
            def _raise(*a, **kw):
                raise ImportError(
                    "Celery not installed. Run: pip install 'horizon-orchestra[queue]'"
                )
            _raise.__name__ = fn.__name__
            return _raise
        return _noop
    return celery_app.task(**kwargs)


# ── Embeddings ─────────────────────────────────────────────────────────────────

@_task(
    name="orchestra.queue.tasks.embed_documents",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="embeddings",
)
def embed_documents(
    self,
    documents: list[dict[str, Any]],
    pipeline_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Embed a batch of documents through the EmbeddingPipeline.

    Args:
        documents: List of {"id": str, "text": str} dicts.
        pipeline_config: Optional PipelineConfig overrides (min_chunk_size, etc.).

    Returns:
        {"embedded": int, "failed": int, "duration_s": float}
    """
    t0 = time.monotonic()
    try:
        from orchestra.embeddings import EmbeddingPipeline, PipelineConfig  # type: ignore[import]

        cfg = PipelineConfig(**(pipeline_config or {}))
        pipeline = EmbeddingPipeline(cfg)
        result = asyncio.run(pipeline.run(documents))
        return {
            "embedded": result.get("embedded", len(documents)),
            "failed": result.get("failed", 0),
            "duration_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:
        log.warning("embed_documents failed (attempt %d): %s", self.request.retries, exc)
        raise self.retry(exc=exc)


# ── Science ingestion ──────────────────────────────────────────────────────────

@_task(
    name="orchestra.queue.tasks.ingest_science_data",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    queue="science",
    time_limit=3600,   # 1-hour hard limit for large molecular datasets
    soft_time_limit=3500,
)
def ingest_science_data(
    self,
    source: str,
    query: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest data from a science source (PubChem, RDKit, BioPython, etc.).

    Args:
        source: One of "pubchem", "rcsb", "biopython", "local".
        query:  Source-specific query string (compound name, PDB ID, etc.).
        options: Optional ingestion parameters forwarded to the adapter.

    Returns:
        {"records": int, "source": str, "duration_s": float}
    """
    t0 = time.monotonic()
    try:
        from orchestra_science.ingestion import ingest  # type: ignore[import]

        records = asyncio.run(ingest(source=source, query=query, **(options or {})))
        return {
            "records": records,
            "source": source,
            "duration_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:
        log.warning("ingest_science_data failed (attempt %d): %s", self.request.retries, exc)
        raise self.retry(exc=exc)


# ── LLM batch inference ────────────────────────────────────────────────────────

@_task(
    name="orchestra.queue.tasks.run_llm_batch",
    bind=True,
    max_retries=4,
    default_retry_delay=15,
    queue="llm",
    time_limit=7200,   # 2-hour hard limit for large batches
)
def run_llm_batch(
    self,
    prompts: list[str],
    model: str = "claude-haiku-4-5-20251001",
    system: str | None = None,
    max_tokens: int = 1024,
    provider: str = "anthropic",
) -> dict[str, Any]:
    """Run a batch of prompts through a model and return all responses.

    Args:
        prompts:    List of user-turn strings.
        model:      Model ID to use.
        system:     Optional system prompt applied to every request.
        max_tokens: Per-response token budget.
        provider:   "anthropic" | "openai" | "local".

    Returns:
        {"responses": list[str], "failed": int, "duration_s": float}
    """
    t0 = time.monotonic()
    try:
        from orchestra.providers import run_batch  # type: ignore[import]

        responses, failed = asyncio.run(
            run_batch(
                prompts=prompts,
                model=model,
                system=system,
                max_tokens=max_tokens,
                provider=provider,
            )
        )
        return {
            "responses": responses,
            "failed": failed,
            "duration_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:
        log.warning("run_llm_batch failed (attempt %d): %s", self.request.retries, exc)
        raise self.retry(exc=exc)


# ── Report generation ──────────────────────────────────────────────────────────

@_task(
    name="orchestra.queue.tasks.generate_report",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    queue="reports",
    time_limit=1800,
)
def generate_report(
    self,
    report_type: str,
    context: dict[str, Any],
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a structured report (lab, research paper, protocol, etc.).

    Args:
        report_type: One of "lab", "research", "protocol", "summary".
        context:     Input data dict consumed by the report template.
        output_path: Optional file path; if None returns content inline.

    Returns:
        {"report_type": str, "path": str | None, "chars": int, "duration_s": float}
    """
    t0 = time.monotonic()
    try:
        from orchestra_science.reporting import generate  # type: ignore[import]

        content = asyncio.run(
            generate(report_type=report_type, context=context, output_path=output_path)
        )
        return {
            "report_type": report_type,
            "path": output_path,
            "chars": len(content) if isinstance(content, str) else 0,
            "duration_s": round(time.monotonic() - t0, 3),
        }
    except Exception as exc:
        log.warning("generate_report failed (attempt %d): %s", self.request.retries, exc)
        raise self.retry(exc=exc)
