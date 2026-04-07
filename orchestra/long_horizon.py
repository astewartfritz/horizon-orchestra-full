"""
orchestra/long_horizon.py
--------------------------
Long-horizon task runner — checkpoint/resume for multi-hour workflows.

Handles tasks that run for hours with automatic checkpointing, Lambda
timeout detection, and progress tracking with ETA estimation.
"""
from __future__ import annotations

__all__ = [
    "CheckpointStore",
    "ProgressTracker",
    "LongHorizonRunner",
    "LongHorizonResult",
    "LongHorizonConfig",
]

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import boto3
    from botocore.exceptions import ClientError
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover — optional cloud dependency
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]
    _HAS_BOTO3 = False

logger = logging.getLogger("orchestra.long_horizon")

_DEFAULT_TABLE = "horizon-checkpoints"
_FALLBACK_DIR = "/tmp/orchestra_checkpoints"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LongHorizonConfig:
    """Configuration for the LongHorizonRunner."""

    max_runtime_hours: float = 4.0
    checkpoint_interval_minutes: float = 5.0
    max_tool_calls: int = 1000
    lambda_timeout_seconds: float = 840.0  # 14 minutes — Lambda max is 15m
    model: str = "kimi-k2.5"
    enable_progress_streaming: bool = True


@dataclass
class LongHorizonResult:
    """Result from a completed or paused long-horizon run."""

    task_id: str
    status: str  # "completed" | "paused" | "needs_continuation" | "failed" | "cancelled"
    result: str
    steps_completed: int
    total_steps: int
    tool_calls: int
    duration_seconds: float
    checkpoint_id: str = ""
    progress: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# CheckpointStore
# ---------------------------------------------------------------------------

class CheckpointStore:
    """
    Persists task state to DynamoDB (primary) or local filesystem (fallback).

    DynamoDB table schema
    ---------------------
    PK : task_id (String)
    ttl : epoch (TTL attribute, 48 h)
    """

    _TTL_SECONDS = 48 * 3600  # 48 hours

    def __init__(
        self,
        table: str = _DEFAULT_TABLE,
        region: str = "us-east-1",
        use_local_fallback: bool = True,
    ) -> None:
        self._table_name = table
        self._region = region
        self._use_local = use_local_fallback
        try:
            if not _HAS_BOTO3:
                raise ImportError("boto3 not installed")
            self._dynamodb = boto3.resource("dynamodb", region_name=region)
            self._table = self._dynamodb.Table(table)
            self._dynamo_available = True
        except Exception:
            logger.warning("CheckpointStore: DynamoDB not available, using local fallback")
            self._dynamo_available = False

        if use_local_fallback:
            os.makedirs(_FALLBACK_DIR, exist_ok=True)

    async def save_checkpoint(self, task_id: str, state: dict) -> None:
        """Persist checkpoint state.

        ``state`` must include at minimum:
        - ``current_step`` (int)
        - ``plan`` (list[dict])
        - ``completed_results`` (list)
        - ``memory_snapshot`` (str)
        - ``tool_call_count`` (int)
        - ``elapsed_time`` (float)
        """
        ttl = int(time.time()) + self._TTL_SECONDS
        item = {
            "task_id": task_id,
            "state": json.dumps(state),
            "saved_at": time.time(),
            "ttl": ttl,
        }

        if self._dynamo_available:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._table.put_item(Item=item),
                )
                logger.debug("save_checkpoint: DynamoDB task_id=%s", task_id)
                return
            except ClientError:
                logger.warning(
                    "save_checkpoint: DynamoDB write failed, falling back to local"
                )

        # Local fallback
        path = os.path.join(_FALLBACK_DIR, f"{task_id}.json")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: _write_json(path, item))
        logger.debug("save_checkpoint: local file task_id=%s", task_id)

    async def load_checkpoint(self, task_id: str) -> dict | None:
        """Load a checkpoint. Returns None if not found."""
        if self._dynamo_available:
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._table.get_item(Key={"task_id": task_id}),
                )
                item = response.get("Item")
                if item:
                    state = json.loads(item.get("state", "{}"))
                    logger.debug("load_checkpoint: found task_id=%s (DynamoDB)", task_id)
                    return state
            except ClientError:
                logger.warning(
                    "load_checkpoint: DynamoDB read failed for task_id=%s", task_id
                )

        # Local fallback
        path = os.path.join(_FALLBACK_DIR, f"{task_id}.json")
        if os.path.exists(path):
            item = _read_json(path)
            logger.debug("load_checkpoint: found task_id=%s (local)", task_id)
            return json.loads(item.get("state", "{}"))

        return None

    async def delete_checkpoint(self, task_id: str) -> None:
        """Remove a checkpoint after successful completion."""
        if self._dynamo_available:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._table.delete_item(Key={"task_id": task_id}),
                )
            except ClientError:
                logger.warning("delete_checkpoint: DynamoDB error for task_id=%s", task_id)

        # Also clean local fallback
        path = os.path.join(_FALLBACK_DIR, f"{task_id}.json")
        if os.path.exists(path):
            os.remove(path)
        logger.debug("delete_checkpoint: task_id=%s", task_id)

    async def list_checkpoints(self, user_id: str) -> list[dict]:
        """List all checkpoints that belong to a user.

        Stores user_id in the state JSON; performs a scan filtered by user_id.
        (For production scale, add a GSI on user_id.)
        """
        results: list[dict] = []

        if self._dynamo_available:
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._table.scan(
                        FilterExpression=boto3.dynamodb.conditions.Attr("state").contains(
                            f'"user_id": "{user_id}"'
                        )
                    ),
                )
                for item in response.get("Items", []):
                    try:
                        state = json.loads(item.get("state", "{}"))
                        if state.get("user_id") == user_id:
                            results.append(
                                {
                                    "task_id": item["task_id"],
                                    "saved_at": item.get("saved_at", 0),
                                    "current_step": state.get("current_step", 0),
                                    "task": state.get("task", ""),
                                }
                            )
                    except (json.JSONDecodeError, KeyError):
                        continue
                return results
            except ClientError:
                logger.warning("list_checkpoints: DynamoDB scan failed for user_id=%s", user_id)

        # Local fallback
        for fname in os.listdir(_FALLBACK_DIR):
            if fname.endswith(".json"):
                try:
                    item = _read_json(os.path.join(_FALLBACK_DIR, fname))
                    state = json.loads(item.get("state", "{}"))
                    if state.get("user_id") == user_id:
                        results.append(
                            {
                                "task_id": fname[:-5],
                                "saved_at": item.get("saved_at", 0),
                                "current_step": state.get("current_step", 0),
                                "task": state.get("task", ""),
                            }
                        )
                except Exception:
                    continue

        return results


# ---------------------------------------------------------------------------
# ProgressTracker
# ---------------------------------------------------------------------------

class ProgressTracker:
    """Tracks progress of a long-horizon task with ETA estimation."""

    def __init__(self) -> None:
        self._step: int = 0
        self._total: int = 0
        self._message: str = ""
        self._start_time: float = time.time()
        self._tool_calls: dict[str, int] = {}
        self._total_tool_calls: int = 0
        self._completed_steps: list[dict] = []
        # Ring buffer of step completion times for ETA estimation
        self._step_times: list[float] = []

    def update(self, step: int, total: int, message: str) -> None:
        """Update current progress."""
        self._step = step
        self._total = total
        self._message = message
        logger.debug("progress: step=%d/%d %s", step, total, message)

    def get_progress(self) -> dict:
        """Return serialisable progress dict."""
        elapsed = time.time() - self._start_time
        pct = (self._step / self._total * 100) if self._total > 0 else 0.0
        eta = self._estimate_eta()
        return {
            "step": self._step,
            "total": self._total,
            "pct": round(pct, 1),
            "message": self._message,
            "elapsed": round(elapsed, 1),
            "eta_seconds": round(eta, 1),
            "tool_calls": self._tool_calls,
            "total_tool_calls": self._total_tool_calls,
        }

    def on_tool_call(self, tool_name: str) -> None:
        """Increment tool call counter."""
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1
        self._total_tool_calls += 1

    def on_step_complete(self, step_id: str, result: str) -> None:
        """Record a completed step with timing."""
        now = time.time()
        self._completed_steps.append(
            {"step_id": step_id, "result": result[:500], "completed_at": now}
        )
        self._step_times.append(now)
        # Keep only last 10 samples for rolling average
        if len(self._step_times) > 10:
            self._step_times = self._step_times[-10:]

    def to_dict(self) -> dict:
        """Return full serialisable state for WebSocket streaming."""
        return {
            **self.get_progress(),
            "completed_steps": self._completed_steps[-5:],  # last 5
            "start_time": self._start_time,
        }

    def _estimate_eta(self) -> float:
        """Estimate seconds remaining based on recent step rate."""
        remaining = self._total - self._step
        if remaining <= 0:
            return 0.0
        if len(self._step_times) < 2:
            # Fallback: linear estimate from elapsed time
            elapsed = time.time() - self._start_time
            if self._step > 0:
                return elapsed / self._step * remaining
            return 0.0

        # Rolling average of seconds-per-step from recent completions
        intervals = [
            self._step_times[i] - self._step_times[i - 1]
            for i in range(1, len(self._step_times))
        ]
        avg_interval = sum(intervals) / len(intervals)
        return avg_interval * remaining


# ---------------------------------------------------------------------------
# LongHorizonRunner
# ---------------------------------------------------------------------------

class LongHorizonRunner:
    """
    Orchestrates multi-hour tasks with checkpointing and Lambda-aware pausing.

    The runner integrates with an agent ``router`` that exposes:
    - ``router.plan(task: str) -> list[dict]``    — break task into steps
    - ``router.execute_step(step: dict, context: dict) -> str``  — run one step
    """

    def __init__(
        self,
        router: Any,
        tools: list[Any],
        config: LongHorizonConfig,
        checkpoint_store: CheckpointStore,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self._router = router
        self._tools = tools
        self._config = config
        self._checkpoint_store = checkpoint_store
        self._progress_callback = progress_callback
        self._cancelled_tasks: set[str] = set()
        logger.info(
            "LongHorizonRunner initialised (model=%s, max_hours=%.1f)",
            config.model,
            config.max_runtime_hours,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        user_id: str,
        resume_from: str = "",
    ) -> LongHorizonResult:
        """Run (or resume) a long-horizon task.

        1. Load checkpoint if ``resume_from`` is provided.
        2. Plan the task via the router planner.
        3. Execute steps sequentially.
        4. Checkpoint regularly; pause near Lambda/runtime limits.
        5. Clean up checkpoint on completion.
        """
        task_id = resume_from or str(uuid.uuid4())
        start_time = time.time()
        tracker = ProgressTracker()

        # ----------------------------------------------------------------
        # Step 1 — Resume or start fresh
        # ----------------------------------------------------------------
        plan: list[dict] = []
        completed_results: list[str] = []
        start_step: int = 0
        memory_snapshot: str = ""

        if resume_from:
            checkpoint = await self._checkpoint_store.load_checkpoint(resume_from)
            if checkpoint:
                plan = checkpoint.get("plan", [])
                completed_results = checkpoint.get("completed_results", [])
                start_step = checkpoint.get("current_step", 0)
                memory_snapshot = checkpoint.get("memory_snapshot", "")
                task = checkpoint.get("task", task)
                logger.info(
                    "run: resuming task_id=%s from step=%d", task_id, start_step
                )
            else:
                logger.warning("run: checkpoint not found for task_id=%s", resume_from)

        # ----------------------------------------------------------------
        # Step 2 — Plan (if no checkpoint or plan is empty)
        # ----------------------------------------------------------------
        if not plan:
            try:
                plan = await self._plan_task(task)
                logger.info("run: planned task_id=%s steps=%d", task_id, len(plan))
            except Exception as exc:
                logger.exception("run: planning failed for task_id=%s", task_id)
                return LongHorizonResult(
                    task_id=task_id,
                    status="failed",
                    result=f"Planning failed: {exc}",
                    steps_completed=0,
                    total_steps=0,
                    tool_calls=0,
                    duration_seconds=time.time() - start_time,
                    progress=tracker.to_dict(),
                )

        total_steps = len(plan)
        tracker.update(start_step, total_steps, "Starting execution")

        # ----------------------------------------------------------------
        # Step 3 — Execute steps
        # ----------------------------------------------------------------
        last_checkpoint_time = time.time()

        for step_index in range(start_step, total_steps):
            # Check for cancellation
            if task_id in self._cancelled_tasks:
                self._cancelled_tasks.discard(task_id)
                logger.info("run: task_id=%s cancelled at step=%d", task_id, step_index)
                return LongHorizonResult(
                    task_id=task_id,
                    status="cancelled",
                    result="Task cancelled by user.",
                    steps_completed=step_index,
                    total_steps=total_steps,
                    tool_calls=tracker._total_tool_calls,
                    duration_seconds=time.time() - start_time,
                    progress=tracker.to_dict(),
                )

            elapsed_minutes = (time.time() - start_time) / 60
            step = plan[step_index]
            tracker.update(step_index, total_steps, f"Executing: {step.get('name', f'Step {step_index+1}')}")

            # Stream progress if callback set
            if self._config.enable_progress_streaming and self._progress_callback:
                try:
                    self._progress_callback(tracker.to_dict())
                except Exception:
                    pass

            # Check pause conditions before executing step
            if self._should_pause(elapsed_minutes, tracker._total_tool_calls):
                checkpoint_id = await self._save_state(
                    task_id, task, user_id, step_index, plan,
                    completed_results, memory_snapshot, tracker
                )
                status = (
                    "needs_continuation"
                    if elapsed_minutes >= (self._config.lambda_timeout_seconds / 60)
                    else "paused"
                )
                logger.info(
                    "run: pausing task_id=%s at step=%d status=%s", task_id, step_index, status
                )
                return LongHorizonResult(
                    task_id=task_id,
                    status=status,
                    result=f"Task paused at step {step_index}/{total_steps}. Resume with task_id={task_id}.",
                    steps_completed=step_index,
                    total_steps=total_steps,
                    tool_calls=tracker._total_tool_calls,
                    duration_seconds=time.time() - start_time,
                    checkpoint_id=checkpoint_id,
                    progress=tracker.to_dict(),
                )

            # Execute the step
            try:
                context = {
                    "task": task,
                    "step_index": step_index,
                    "completed_results": completed_results,
                    "memory": memory_snapshot,
                    "model": self._config.model,
                }
                result_text = await self._execute_step(step, context, tracker)
                completed_results.append(result_text)
                tracker.on_step_complete(
                    step.get("id", str(step_index)), result_text
                )
                # Update memory snapshot with key result
                memory_snapshot = self._update_memory(
                    memory_snapshot, step, result_text
                )
                logger.debug(
                    "run: step %d/%d completed task_id=%s",
                    step_index + 1,
                    total_steps,
                    task_id,
                )
            except Exception as exc:
                logger.exception(
                    "run: step %d failed for task_id=%s", step_index, task_id
                )
                # Save checkpoint on step failure for resumability
                checkpoint_id = await self._save_state(
                    task_id, task, user_id, step_index, plan,
                    completed_results, memory_snapshot, tracker
                )
                return LongHorizonResult(
                    task_id=task_id,
                    status="failed",
                    result=f"Step {step_index} failed: {exc}",
                    steps_completed=step_index,
                    total_steps=total_steps,
                    tool_calls=tracker._total_tool_calls,
                    duration_seconds=time.time() - start_time,
                    checkpoint_id=checkpoint_id,
                    progress=tracker.to_dict(),
                )

            # Periodic checkpoint
            if self._should_checkpoint(
                (time.time() - last_checkpoint_time) / 60
            ):
                await self._save_state(
                    task_id, task, user_id, step_index + 1, plan,
                    completed_results, memory_snapshot, tracker
                )
                last_checkpoint_time = time.time()
                logger.debug("run: periodic checkpoint at step=%d", step_index + 1)

        # ----------------------------------------------------------------
        # Step 4 — Completion
        # ----------------------------------------------------------------
        await self._checkpoint_store.delete_checkpoint(task_id)
        final_result = self._compile_results(task, completed_results)
        tracker.update(total_steps, total_steps, "Completed")

        logger.info(
            "run: task_id=%s completed steps=%d duration=%.1fs",
            task_id,
            total_steps,
            time.time() - start_time,
        )
        return LongHorizonResult(
            task_id=task_id,
            status="completed",
            result=final_result,
            steps_completed=total_steps,
            total_steps=total_steps,
            tool_calls=tracker._total_tool_calls,
            duration_seconds=time.time() - start_time,
            progress=tracker.to_dict(),
        )

    async def resume(self, task_id: str) -> LongHorizonResult:
        """Load a checkpoint and continue execution."""
        checkpoint = await self._checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            return LongHorizonResult(
                task_id=task_id,
                status="failed",
                result=f"Checkpoint not found: {task_id}",
                steps_completed=0,
                total_steps=0,
                tool_calls=0,
                duration_seconds=0.0,
            )

        task = checkpoint.get("task", "")
        user_id = checkpoint.get("user_id", "")
        return await self.run(task, user_id, resume_from=task_id)

    async def cancel(self, task_id: str) -> dict:
        """Signal a running task to cancel at the next checkpoint."""
        self._cancelled_tasks.add(task_id)
        # Also delete the checkpoint so resume is not possible
        await self._checkpoint_store.delete_checkpoint(task_id)
        logger.info("cancel: requested for task_id=%s", task_id)
        return {"task_id": task_id, "status": "cancel_requested"}

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    def _should_checkpoint(self, elapsed_since_last_minutes: float) -> bool:
        """True if it is time for a periodic checkpoint."""
        return elapsed_since_last_minutes >= self._config.checkpoint_interval_minutes

    def _should_pause(self, elapsed_minutes: float, tool_calls: int) -> bool:
        """True if approaching Lambda timeout, max runtime, or max tool calls."""
        lambda_limit_minutes = self._config.lambda_timeout_seconds / 60
        max_runtime_minutes = self._config.max_runtime_hours * 60

        if elapsed_minutes >= lambda_limit_minutes:
            logger.info("_should_pause: Lambda timeout imminent (%.1f min)", elapsed_minutes)
            return True
        if elapsed_minutes >= max_runtime_minutes:
            logger.info("_should_pause: max runtime reached (%.1f min)", elapsed_minutes)
            return True
        if tool_calls >= self._config.max_tool_calls:
            logger.info("_should_pause: max tool calls reached (%d)", tool_calls)
            return True
        return False

    def _estimate_eta(self, progress: dict) -> float:
        """Proxy to ProgressTracker ETA, used externally."""
        step = progress.get("step", 0)
        total = progress.get("total", 0)
        elapsed = progress.get("elapsed", 0.0)
        if step <= 0 or total <= 0:
            return 0.0
        return elapsed / step * (total - step)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _plan_task(self, task: str) -> list[dict]:
        """Generate a step plan from the router planner."""
        if hasattr(self._router, "plan"):
            plan = await self._router.plan(task)
            if isinstance(plan, list):
                return plan
        # Fallback: single-step plan
        return [{"id": "step_0", "name": "Execute task", "instruction": task}]

    async def _execute_step(
        self,
        step: dict,
        context: dict,
        tracker: ProgressTracker,
    ) -> str:
        """Run a single step using the router."""
        instruction = step.get("instruction", step.get("name", str(step)))

        if hasattr(self._router, "execute_step"):
            # Track tool calls via a wrapper if router supports it
            result = await self._router.execute_step(step, context)
            return str(result)

        # Fallback: generic completion call
        if hasattr(self._router, "complete"):
            result = await self._router.complete(
                instruction,
                model=context.get("model", self._config.model),
            )
            return str(result)

        return f"Step '{instruction}' completed (no router execute_step method)."

    async def _save_state(
        self,
        task_id: str,
        task: str,
        user_id: str,
        current_step: int,
        plan: list[dict],
        completed_results: list[str],
        memory_snapshot: str,
        tracker: ProgressTracker,
    ) -> str:
        """Persist checkpoint state. Returns task_id (checkpoint ID)."""
        state = {
            "task_id": task_id,
            "task": task,
            "user_id": user_id,
            "current_step": current_step,
            "plan": plan,
            "completed_results": completed_results[-50:],  # cap to last 50
            "memory_snapshot": memory_snapshot,
            "tool_call_count": tracker._total_tool_calls,
            "elapsed_time": time.time() - tracker._start_time,
            "progress": tracker.to_dict(),
            "saved_at": time.time(),
        }
        await self._checkpoint_store.save_checkpoint(task_id, state)
        return task_id

    @staticmethod
    def _update_memory(memory: str, step: dict, result: str) -> str:
        """Append a brief step summary to the rolling memory snapshot."""
        step_name = step.get("name", "step")
        summary = f"\n[{step_name}]: {result[:200]}"
        # Keep memory under 4000 chars
        combined = memory + summary
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    @staticmethod
    def _compile_results(task: str, results: list[str]) -> str:
        """Compile step results into a final answer."""
        if not results:
            return "Task completed with no output."
        if len(results) == 1:
            return results[0]
        parts = [f"**Task**: {task}\n\n**Results**:"]
        for i, r in enumerate(results, 1):
            parts.append(f"{i}. {r[:500]}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Local file I/O helpers (used by CheckpointStore fallback)
# ---------------------------------------------------------------------------

def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
