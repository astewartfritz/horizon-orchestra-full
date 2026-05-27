from __future__ import annotations

"""FastAPI router for long-running data jobs (Celery backend).

Mounts at /api/jobs/data.  Requires celery[redis] installed and REDIS_URL set.

Endpoints
---------
POST   /api/jobs/data           Submit a new data job → {"job_id": str}
GET    /api/jobs/data/{job_id}  Poll job status       → JobStatus
DELETE /api/jobs/data/{job_id}  Cancel a pending job  → {"cancelled": bool}
"""

from typing import Any

from pydantic import BaseModel, Field

# FastAPI is an optional dep — guard so the module can be imported anywhere.
try:
    from fastapi import APIRouter, HTTPException
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False


# ── Request / response models ──────────────────────────────────────────────────

class SubmitRequest(BaseModel):
    name: str = Field(
        ...,
        description=(
            "Task name: embed_documents | ingest_science_data | "
            "run_llm_batch | generate_report"
        ),
        examples=["embed_documents"],
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments forwarded to the task function.",
    )
    priority: int = Field(
        default=5,
        ge=0,
        le=9,
        description="Celery priority 0 (highest) … 9 (lowest).",
    )
    countdown: int = Field(
        default=0,
        ge=0,
        description="Delay in seconds before the task becomes eligible.",
    )


class JobStatus(BaseModel):
    job_id: str
    status: str                         # pending | running | done | failed | dead
    result: dict[str, Any] | None = None
    error: str | None = None


# ── Router factory ─────────────────────────────────────────────────────────────

def register_data_job_routes(app: Any, prefix: str = "/api/jobs/data") -> None:
    """Mount the data-jobs router onto *app*.

    Args:
        app:    FastAPI application instance.
        prefix: URL prefix (default /api/jobs/data).
    """
    if not _HAS_FASTAPI:
        raise ImportError("fastapi not installed — cannot mount data job routes.")

    from .celery_bridge import get_data_job_status, revoke_data_job, submit_data_job

    router = APIRouter(prefix=prefix, tags=["data-jobs"])

    @router.post("", response_model=dict, status_code=202)
    async def submit_job(req: SubmitRequest) -> dict:
        """Submit a long-running data job to Celery.

        Returns HTTP 202 Accepted with the Celery task ID so the caller can
        poll for completion.
        """
        try:
            job = submit_data_job(
                req.name,
                req.payload,
                priority=req.priority,
                countdown=req.countdown,
            )
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"job_id": job.id, "status": job.status}

    @router.get("/{job_id}", response_model=JobStatus)
    async def get_job(job_id: str) -> JobStatus:
        """Return the current status and result of a data job."""
        try:
            job = get_data_job_status(job_id)
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JobStatus(
            job_id=job_id,
            status=job.status,
            result=job.result,
            error=job.error,
        )

    @router.delete("/{job_id}", response_model=dict)
    async def cancel_job(job_id: str) -> dict:
        """Cancel a pending or running data job.

        Sends a REVOKE signal; running tasks are interrupted only if the
        worker has acks_late=True *and* the task checks for revocation.
        """
        try:
            revoke_data_job(job_id, terminate=False)
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"cancelled": True, "job_id": job_id}

    app.include_router(router)
