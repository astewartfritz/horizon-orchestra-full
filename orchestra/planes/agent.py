"""AgentPlane — long-running, stateful, concurrency-limited agent jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from .config import PlaneConfig

log = logging.getLogger(__name__)

# Lazy import — AgentLoop may not be available in all deployments
try:
    from orchestra.agent_loop import AgentLoop as _AgentLoop
    _AGENT_LOOP_AVAILABLE = True
except ImportError:
    _AgentLoop = None  # type: ignore
    _AGENT_LOOP_AVAILABLE = False


class AgentPlane:
    """Manages long-running agent tasks behind a concurrency semaphore."""

    def __init__(self, config: PlaneConfig) -> None:
        self._config = config
        self._semaphore: asyncio.Semaphore | None = None
        self._jobs: dict[str, dict[str, Any]] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the concurrency semaphore."""
        self._semaphore = asyncio.Semaphore(self._config.agent_concurrency)
        log.info("AgentPlane started (concurrency=%d)", self._config.agent_concurrency)

    async def stop(self) -> None:
        """Cancel all running jobs and clean up."""
        running = [
            jid for jid, meta in self._jobs.items()
            if meta.get("status") == "running"
        ]
        for jid in running:
            task: asyncio.Task | None = self._jobs[jid].get("_task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            self._jobs[jid]["status"] = "failed"
            self._jobs[jid]["error"] = "plane stopped"
        log.info("AgentPlane stopped (%d jobs cancelled)", len(running))

    # ── Public API ─────────────────────────────────────────────────────────

    async def submit(
        self,
        task: str,
        tools: list[Any],
        model: str,
        context: dict[str, Any],
    ) -> str:
        """Submit a task and return a job_id immediately."""
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "_task": None,
        }
        bg_task = asyncio.create_task(
            self._run_job(job_id, task, tools, model, context),
            name=f"agent-job-{job_id[:8]}",
        )
        self._jobs[job_id]["_task"] = bg_task
        log.info("Submitted job %s model=%s", job_id, model)
        return job_id

    async def status(self, job_id: str) -> dict[str, Any]:
        """Return the current status snapshot for a job."""
        if job_id not in self._jobs:
            return {"status": "not_found", "result": None, "error": "unknown job_id"}
        meta = self._jobs[job_id]
        return {
            "status": meta["status"],
            "result": meta["result"],
            "error": meta["error"],
        }

    # ── Internal ───────────────────────────────────────────────────────────

    async def _run_job(
        self,
        job_id: str,
        task: str,
        tools: list[Any],
        model: str,
        context: dict[str, Any],
    ) -> None:
        """Execute one agent job under the semaphore, respecting timeout."""
        assert self._semaphore is not None, "AgentPlane.start() not called"
        async with self._semaphore:
            try:
                result = await asyncio.wait_for(
                    self._execute(job_id, task, tools, model, context),
                    timeout=self._config.agent_timeout_s,
                )
                self._jobs[job_id]["status"] = "done"
                self._jobs[job_id]["result"] = result
            except asyncio.TimeoutError:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = "timeout"
                log.warning("Job %s timed out after %ds", job_id, self._config.agent_timeout_s)
            except asyncio.CancelledError:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = "cancelled"
                raise
            except Exception as exc:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)
                log.exception("Job %s failed: %s", job_id, exc)

    async def _execute(
        self,
        job_id: str,
        task: str,
        tools: list[Any],
        model: str,
        context: dict[str, Any],
    ) -> Any:
        """Run the actual agent logic, using AgentLoop when available."""
        if _AGENT_LOOP_AVAILABLE and _AgentLoop is not None:
            # Import config class lazily too
            try:
                from orchestra.agent_loop import AgentConfig
                cfg = AgentConfig(model=model)
                try:
                    from orchestra.router import ModelRouter
                    router = ModelRouter()
                except ImportError:
                    router = None  # type: ignore

                loop = _AgentLoop(router, tools or [], cfg)
                events = []
                async for event in loop.run(task):
                    events.append(event)
                    # Attach streaming events to the job for WS consumers
                    if "_events" not in self._jobs[job_id]:
                        self._jobs[job_id]["_events"] = []
                    self._jobs[job_id]["_events"].append(event)
                return events[-1] if events else None
            except Exception as exc:
                log.warning("AgentLoop execution error for %s: %s", job_id, exc)
                raise
        else:
            # Stub execution when AgentLoop is unavailable
            log.debug("AgentLoop unavailable; using stub for job %s", job_id)
            await asyncio.sleep(0)
            return {"task": task, "model": model, "context": context, "note": "stub"}
