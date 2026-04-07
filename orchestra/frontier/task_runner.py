"""Frontier Browser — Non-blocking Task Runner.

Non-blocking task orchestration for the Frontier browser. The user
submits a task, the runner spawns a sandbox, assigns an agent, and
streams progress via dual channels (SSE + WebSocket). Multiple tasks
run concurrently while the user continues browsing normally.

Design philosophy:
    Tasks run in sandboxes ASYNCHRONOUSLY. Each task gets:
    - Its own BrowserSandbox (isolated browser context)
    - Access to the shared ContextStore (read any page state)
    - An AgentBridge for executing browser actions
    - A FrontierSafetyGuard for enforcing boundaries

    The runner streams TaskEvents via dual channels:
    - SSE: reasoning, progress, results (for the sidebar UI)
    - WebSocket: real-time action feed (for the automation panel)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

__all__ = [
    "FrontierTaskRunner",
    "FrontierTask",
    "TaskEvent",
    "TaskRunnerConfig",
]

log = logging.getLogger("orchestra.frontier.task_runner")

# ---------------------------------------------------------------------------
# Optional imports from core/runtime layers — graceful degradation
# ---------------------------------------------------------------------------
try:
    from orchestra.frontier.context_store import ContextStore, PageContext, ContextEntry
except Exception:  # pragma: no cover
    ContextStore = Any  # type: ignore[assignment,misc]
    PageContext = Any  # type: ignore[assignment,misc]
    ContextEntry = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.sandbox import BrowserSandbox, SandboxPool, SandboxConfig, SandboxState
except Exception:  # pragma: no cover
    BrowserSandbox = Any  # type: ignore[assignment,misc]
    SandboxPool = Any  # type: ignore[assignment,misc]
    SandboxConfig = Any  # type: ignore[assignment,misc]
    SandboxState = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.dom_interpreter import DOMInterpreter, DOMSnapshot
except Exception:  # pragma: no cover
    DOMInterpreter = Any  # type: ignore[assignment,misc]
    DOMSnapshot = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.agent_bridge import AgentBridge, BrowserCommand, CommandResult, LLMActionPlanner
except Exception:  # pragma: no cover
    AgentBridge = Any  # type: ignore[assignment,misc]
    BrowserCommand = Any  # type: ignore[assignment,misc]
    CommandResult = Any  # type: ignore[assignment,misc]
    LLMActionPlanner = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.safety import FrontierSafetyGuard, SafetyConfig, ApprovalRequest
except Exception:  # pragma: no cover
    FrontierSafetyGuard = Any  # type: ignore[assignment,misc]
    SafetyConfig = Any  # type: ignore[assignment,misc]
    ApprovalRequest = Any  # type: ignore[assignment,misc]

try:
    from orchestra.router import ModelRouter
except Exception:  # pragma: no cover
    ModelRouter = Any  # type: ignore[assignment,misc]


# =========================================================================
# Task status constants
# =========================================================================

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_TERMINAL_STATUSES: frozenset[str] = frozenset({
    STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
})

# Event types
EVENT_TASK_STARTED = "task_started"
EVENT_PAGE_NAVIGATED = "page_navigated"
EVENT_ACTION_EXECUTED = "action_executed"
EVENT_THINKING = "thinking"
EVENT_DATA_EXTRACTED = "data_extracted"
EVENT_APPROVAL_NEEDED = "approval_needed"
EVENT_PROGRESS = "progress"
EVENT_ERROR = "error"
EVENT_SCREENSHOT = "screenshot"
EVENT_TASK_COMPLETED = "task_completed"
EVENT_TASK_FAILED = "task_failed"

# Channels
CHANNEL_SSE = "sse"
CHANNEL_WEBSOCKET = "websocket"


# =========================================================================
# Data classes
# =========================================================================

@dataclass
class FrontierTask:
    """A browser automation task submitted by the user.

    Each task tracks its full lifecycle from submission through
    execution to completion, including all pages visited and any
    data extracted.
    """

    task_id: str
    description: str               # Natural language: "Find cheapest flight SFO→LAX"
    user_id: str
    status: str = STATUS_QUEUED    # queued | running | paused | completed | failed | cancelled
    priority: int = 50             # 0-100
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # Execution config
    start_url: str = ""
    max_steps: int = 50
    timeout_seconds: float = 300.0
    require_approval: bool = False

    # Results
    result: str = ""
    extracted_data: dict[str, Any] = field(default_factory=dict)
    pages_visited: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    error: str = ""

    # Sandbox reference
    sandbox_id: str = ""
    agent_id: str = ""

    @property
    def is_terminal(self) -> bool:
        """Whether this task has reached a terminal state."""
        return self.status in _TERMINAL_STATUSES

    @property
    def elapsed(self) -> float:
        """Seconds since the task started (or 0 if not started)."""
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "user_id": self.user_id,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "start_url": self.start_url,
            "max_steps": self.max_steps,
            "timeout_seconds": self.timeout_seconds,
            "require_approval": self.require_approval,
            "result": self.result,
            "extracted_data": self.extracted_data,
            "pages_visited": self.pages_visited,
            "screenshots": self.screenshots,
            "error": self.error,
            "sandbox_id": self.sandbox_id,
            "agent_id": self.agent_id,
            "elapsed": self.elapsed,
        }


@dataclass
class TaskEvent:
    """Event emitted during task execution for real-time UI updates.

    Dual-channel:
    - SSE: conversation/reasoning events (shown in sidebar)
    - WebSocket: automation events (page actions, screenshots)
    """

    task_id: str
    event_type: str     # One of EVENT_* constants
    channel: str        # "sse" | "websocket"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """Format as Server-Sent Event string.

        Returns a string conforming to the SSE specification with
        ``event:`` and ``data:`` lines followed by a blank line.
        """
        payload = json.dumps(self.data, default=str)
        return f"event: {self.event_type}\ndata: {payload}\n\n"

    def to_ws_frame(self) -> str:
        """Format as WebSocket JSON frame.

        Returns a single JSON string suitable for sending over
        a WebSocket connection.
        """
        return json.dumps({
            "task_id": self.task_id,
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }, default=str)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "task_id": self.task_id,
            "event_type": self.event_type,
            "channel": self.channel,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class TaskRunnerConfig:
    """Configuration for FrontierTaskRunner."""

    max_concurrent_tasks: int = 10
    default_timeout: float = 300.0
    default_max_steps: int = 50
    event_buffer_size: int = 1000
    enable_screenshots: bool = True
    enable_approval_flow: bool = True
    model: str = "kimi-k2.5"
    user_id: str = ""

    # Internal tuning
    agent_loop_delay: float = 0.5      # seconds between agent steps
    completion_check_interval: int = 5  # check completion every N steps
    stale_task_timeout: float = 600.0   # force-fail tasks older than this


# =========================================================================
# FrontierTaskRunner
# =========================================================================

class FrontierTaskRunner:
    """Non-blocking task orchestration for Frontier browser.

    The core principle: tasks run in sandboxes ASYNCHRONOUSLY while the
    user continues working. Each task gets:
    - Its own BrowserSandbox (isolated browser context)
    - Access to the shared ContextStore (read any page state)
    - An AgentBridge for executing browser actions
    - A SafetyGuard for enforcing boundaries

    The runner streams TaskEvents via dual channels:
    - SSE: reasoning, progress, results (for the sidebar UI)
    - WebSocket: real-time action feed (for the automation panel)

    Multiple tasks can run simultaneously. The user can:
    - Submit new tasks while others are running
    - Pause/resume any task
    - Cancel any task
    - View real-time progress for all tasks
    - Approve/reject actions that need confirmation
    """

    def __init__(
        self,
        config: TaskRunnerConfig | None = None,
        context_store: Any | None = None,
        sandbox_pool: Any | None = None,
    ) -> None:
        self.config = config or TaskRunnerConfig()
        self._context_store = context_store
        self._sandbox_pool = sandbox_pool

        # Task registry
        self._tasks: dict[str, FrontierTask] = {}
        self._task_handles: dict[str, asyncio.Task[None]] = {}

        # Event buffers: task_id → deque of TaskEvent
        self._event_buffers: dict[str, list[TaskEvent]] = defaultdict(list)
        self._global_event_buffer: list[TaskEvent] = []

        # Event notification: wake up stream consumers
        self._event_notify: dict[str, asyncio.Event] = {}
        self._global_notify = asyncio.Event()

        # Pause/resume controls
        self._pause_events: dict[str, asyncio.Event] = {}

        # Approval flow
        self._approval_futures: dict[str, asyncio.Future[bool]] = {}

        # Safety guard (shared across tasks)
        self._safety: Any = None

        # Running flag
        self._running = False
        self._background_tasks: list[asyncio.Task[Any]] = []

        log.info(
            "FrontierTaskRunner created — max_concurrent=%d, model=%s, "
            "timeout=%.0fs, max_steps=%d",
            self.config.max_concurrent_tasks,
            self.config.model,
            self.config.default_timeout,
            self.config.default_max_steps,
        )

    # -----------------------------------------------------------------
    # Lifecycle — start / shutdown
    # -----------------------------------------------------------------

    async def start(self) -> None:
        """Start the task runner and background services.

        Initialises the safety guard and starts the stale-task reaper.
        """
        if self._running:
            log.warning("TaskRunner already running")
            return

        self._running = True

        # Initialise safety guard
        try:
            from orchestra.frontier.safety import FrontierSafetyGuard as _Guard, SafetyConfig as _SC
            self._safety = _Guard(_SC())
        except Exception:
            log.warning("Could not initialise FrontierSafetyGuard — running without safety")
            self._safety = None

        # Start background reaper
        reaper = asyncio.create_task(self._reap_stale_tasks())
        self._background_tasks.append(reaper)

        log.info("FrontierTaskRunner started")

    async def shutdown(self) -> None:
        """Gracefully shut down the task runner.

        Cancels all running tasks and background services, then
        cleans up resources.
        """
        log.info("FrontierTaskRunner shutting down…")
        self._running = False

        # Cancel all running tasks
        for task_id, handle in list(self._task_handles.items()):
            if not handle.done():
                handle.cancel()
                task = self._tasks.get(task_id)
                if task and not task.is_terminal:
                    task.status = STATUS_CANCELLED
                    task.completed_at = time.time()

        # Cancel background tasks
        for bg in self._background_tasks:
            if not bg.done():
                bg.cancel()

        # Wait for all to finish
        all_handles = list(self._task_handles.values()) + self._background_tasks
        if all_handles:
            await asyncio.gather(*all_handles, return_exceptions=True)

        self._task_handles.clear()
        self._background_tasks.clear()

        log.info("FrontierTaskRunner shut down — %d tasks processed", len(self._tasks))

    # -----------------------------------------------------------------
    # Task lifecycle — submit / cancel / pause / resume / approve
    # -----------------------------------------------------------------

    async def submit(self, description: str, user_id: str, **kwargs: Any) -> FrontierTask:
        """Submit a new browser automation task.

        The task is queued and then executed asynchronously via
        ``asyncio.create_task``. Returns immediately with the task
        object so the user can track progress.

        Args:
            description: Natural-language task description.
            user_id: ID of the user who submitted the task.
            **kwargs: Override defaults (start_url, max_steps, etc.).

        Returns:
            The created ``FrontierTask`` object.
        """
        # Check concurrency limit
        active = self.get_active_count()
        if active >= self.config.max_concurrent_tasks:
            raise RuntimeError(
                f"Concurrency limit reached ({active}/{self.config.max_concurrent_tasks}). "
                f"Cancel or wait for a running task."
            )

        task = FrontierTask(
            task_id=str(uuid.uuid4()),
            description=description,
            user_id=user_id,
            start_url=kwargs.get("start_url", ""),
            max_steps=kwargs.get("max_steps", self.config.default_max_steps),
            timeout_seconds=kwargs.get("timeout_seconds", self.config.default_timeout),
            require_approval=kwargs.get("require_approval", False),
            priority=kwargs.get("priority", 50),
        )

        self._tasks[task.task_id] = task
        self._event_notify[task.task_id] = asyncio.Event()
        self._pause_events[task.task_id] = asyncio.Event()
        self._pause_events[task.task_id].set()  # Not paused by default

        # Launch execution in background
        handle = asyncio.create_task(
            self._execute_task(task),
            name=f"frontier-task-{task.task_id[:8]}",
        )
        self._task_handles[task.task_id] = handle

        log.info(
            "Task submitted: id=%s desc=%r user=%s",
            task.task_id[:8], description[:80], user_id,
        )

        return task

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running or queued task.

        Returns ``True`` if the task was successfully cancelled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            log.warning("cancel: task %s not found", task_id)
            return False

        if task.is_terminal:
            log.debug("cancel: task %s already in terminal state %s", task_id[:8], task.status)
            return False

        task.status = STATUS_CANCELLED
        task.completed_at = time.time()

        # Cancel the asyncio task
        handle = self._task_handles.get(task_id)
        if handle and not handle.done():
            handle.cancel()

        self._emit_event(task_id, EVENT_TASK_FAILED, CHANNEL_SSE, {
            "reason": "cancelled",
            "message": "Task cancelled by user",
        })

        log.info("Task cancelled: %s", task_id[:8])
        return True

    async def pause(self, task_id: str) -> bool:
        """Pause a running task.

        The task's agent loop will pause at the next step boundary.
        Returns ``True`` if the task was successfully paused.
        """
        task = self._tasks.get(task_id)
        if task is None or task.status != STATUS_RUNNING:
            return False

        task.status = STATUS_PAUSED
        pause_event = self._pause_events.get(task_id)
        if pause_event:
            pause_event.clear()  # Block the agent loop

        self._emit_event(task_id, EVENT_PROGRESS, CHANNEL_SSE, {
            "message": "Task paused",
            "status": STATUS_PAUSED,
        })

        log.info("Task paused: %s", task_id[:8])
        return True

    async def resume(self, task_id: str) -> bool:
        """Resume a paused task.

        Returns ``True`` if the task was successfully resumed.
        """
        task = self._tasks.get(task_id)
        if task is None or task.status != STATUS_PAUSED:
            return False

        task.status = STATUS_RUNNING
        pause_event = self._pause_events.get(task_id)
        if pause_event:
            pause_event.set()  # Unblock the agent loop

        self._emit_event(task_id, EVENT_PROGRESS, CHANNEL_SSE, {
            "message": "Task resumed",
            "status": STATUS_RUNNING,
        })

        log.info("Task resumed: %s", task_id[:8])
        return True

    async def approve_action(self, task_id: str, approved: bool) -> bool:
        """Approve or reject a pending action for a task.

        Returns ``True`` if there was a pending approval to resolve.
        """
        future = self._approval_futures.pop(task_id, None)
        if future is None or future.done():
            log.debug("No pending approval for task %s", task_id[:8])
            return False

        future.set_result(approved)
        log.info("Action %s for task %s", "approved" if approved else "rejected", task_id[:8])
        return True

    # -----------------------------------------------------------------
    # Task execution
    # -----------------------------------------------------------------

    async def _execute_task(self, task: FrontierTask) -> None:
        """Execute a single task end-to-end.

        This is the top-level coroutine launched by ``submit``. It:
        1. Acquires a sandbox from the pool
        2. Creates an AgentBridge and LLMActionPlanner
        3. Runs the agent loop
        4. Records results and emits completion events
        """
        task.status = STATUS_RUNNING
        task.started_at = time.time()

        self._emit_event(task.task_id, EVENT_TASK_STARTED, CHANNEL_SSE, {
            "task_id": task.task_id,
            "description": task.description,
            "start_url": task.start_url,
        })

        sandbox = None
        bridge = None

        try:
            # Acquire sandbox
            sandbox = await self._acquire_sandbox(task)
            task.sandbox_id = getattr(sandbox, "id", str(uuid.uuid4())[:8])

            # Create DOM interpreter
            dom_interpreter = self._create_dom_interpreter()

            # Create agent bridge
            bridge = self._create_agent_bridge(sandbox, dom_interpreter)

            # Navigate to start URL if provided
            if task.start_url:
                self._emit_event(task.task_id, EVENT_THINKING, CHANNEL_SSE, {
                    "message": f"Navigating to {task.start_url}",
                })
                try:
                    await bridge.navigate(task.start_url)
                    task.pages_visited.append(task.start_url)
                except Exception as exc:
                    log.warning("Start URL navigation failed: %s", exc)

            # Run the agent loop with timeout
            try:
                await asyncio.wait_for(
                    self._run_agent_loop(task, sandbox, bridge),
                    timeout=task.timeout_seconds,
                )
            except asyncio.TimeoutError:
                task.error = f"Task timed out after {task.timeout_seconds}s"
                task.status = STATUS_FAILED
                log.warning("Task %s timed out", task.task_id[:8])
            except asyncio.CancelledError:
                if task.status != STATUS_CANCELLED:
                    task.status = STATUS_CANCELLED
                log.info("Task %s cancelled during execution", task.task_id[:8])
                raise

            # Mark completed if not already terminal
            if not task.is_terminal:
                task.status = STATUS_COMPLETED
                task.completed_at = time.time()
                self._emit_event(task.task_id, EVENT_TASK_COMPLETED, CHANNEL_SSE, {
                    "task_id": task.task_id,
                    "result": task.result,
                    "extracted_data": task.extracted_data,
                    "pages_visited": task.pages_visited,
                    "elapsed": task.elapsed,
                })
                log.info(
                    "Task %s completed in %.1fs — %d pages visited",
                    task.task_id[:8], task.elapsed, len(task.pages_visited),
                )

        except asyncio.CancelledError:
            if not task.is_terminal:
                task.status = STATUS_CANCELLED
                task.completed_at = time.time()
        except Exception as exc:
            task.status = STATUS_FAILED
            task.error = str(exc)
            task.completed_at = time.time()
            self._emit_event(task.task_id, EVENT_TASK_FAILED, CHANNEL_SSE, {
                "task_id": task.task_id,
                "error": str(exc),
            })
            log.error("Task %s failed: %s", task.task_id[:8], exc, exc_info=True)
        finally:
            # Release sandbox
            if sandbox is not None:
                await self._release_sandbox(sandbox)

    async def _run_agent_loop(
        self,
        task: FrontierTask,
        sandbox: Any,
        bridge: Any,
    ) -> None:
        """Run the plan-act-observe agent loop.

        Iterates up to ``task.max_steps`` times:
        1. Get current DOM state
        2. Ask LLMActionPlanner for the next action
        3. Execute the action via AgentBridge
        4. Check for completion periodically
        5. Stream events for each step

        Respects pause/resume and approval gates.
        """
        planner = self._create_planner()
        history: list[Any] = []
        step = 0

        while step < task.max_steps and not task.is_terminal:
            step += 1

            # Check pause gate
            pause_event = self._pause_events.get(task.task_id)
            if pause_event and not pause_event.is_set():
                self._emit_event(task.task_id, EVENT_PROGRESS, CHANNEL_SSE, {
                    "message": "Waiting for resume…",
                    "step": step,
                })
                await pause_event.wait()
                if task.is_terminal:
                    break

            # 1. Get DOM state
            dom = None
            if hasattr(bridge, "get_current_dom"):
                try:
                    dom = await bridge.get_current_dom()
                except Exception as exc:
                    log.debug("DOM fetch failed at step %d: %s", step, exc)

            # 2. Plan next action
            self._emit_event(task.task_id, EVENT_THINKING, CHANNEL_SSE, {
                "message": f"Step {step}/{task.max_steps}: Planning next action…",
                "step": step,
            })

            command = None
            if planner is not None:
                try:
                    command = await planner.plan_next_action(
                        task.description, dom, history, step, task.max_steps,
                    )
                except Exception as exc:
                    log.warning("Planner failed at step %d: %s", step, exc)

            # LLM signalled completion (returned None)
            if command is None:
                # Double-check via completion evaluator
                if planner is not None and history:
                    try:
                        completed, summary = await planner.evaluate_completion(
                            task.description, dom, history,
                        )
                        if completed:
                            task.result = summary
                            task.status = STATUS_COMPLETED
                            task.completed_at = time.time()
                            break
                    except Exception:
                        pass

                # If planner returned None but evaluation says not complete,
                # treat as completion anyway (agent has no more actions)
                task.result = "Agent finished (no further actions planned)"
                task.status = STATUS_COMPLETED
                task.completed_at = time.time()
                break

            # 3. Safety check & approval gate
            if self._safety is not None and hasattr(self._safety, "check_action"):
                try:
                    allowed, reason, needs_approval = await self._safety.check_action(
                        command, dom, self._get_current_url(bridge),
                    )
                    if not allowed:
                        self._emit_event(task.task_id, EVENT_ERROR, CHANNEL_SSE, {
                            "message": f"Action blocked: {reason}",
                            "step": step,
                        })
                        history.append(self._make_blocked_result(command, reason))
                        continue

                    if needs_approval and (task.require_approval or self.config.enable_approval_flow):
                        approved = await self._request_approval(task, command, reason)
                        if not approved:
                            self._emit_event(task.task_id, EVENT_PROGRESS, CHANNEL_SSE, {
                                "message": "Action rejected by user — skipping",
                                "step": step,
                            })
                            history.append(self._make_blocked_result(command, "Rejected by user"))
                            continue
                except Exception as exc:
                    log.debug("Safety check error at step %d: %s", step, exc)

            # 4. Execute action
            self._emit_event(task.task_id, EVENT_ACTION_EXECUTED, CHANNEL_WEBSOCKET, {
                "step": step,
                "command_type": command.command_type,
                "target": command.target,
                "description": command.description,
            })

            result = None
            if hasattr(bridge, "dispatch"):
                try:
                    result = await bridge.dispatch(command)
                except Exception as exc:
                    log.warning("Bridge dispatch failed at step %d: %s", step, exc)
                    result = self._make_error_result(command, str(exc))

            if result is not None:
                history.append(result)

                # Track pages visited
                new_url = getattr(result, "new_url", "")
                if new_url and new_url not in task.pages_visited:
                    task.pages_visited.append(new_url)
                    self._emit_event(task.task_id, EVENT_PAGE_NAVIGATED, CHANNEL_WEBSOCKET, {
                        "url": new_url,
                        "step": step,
                    })

                # Screenshot on significant DOM changes
                if (
                    self.config.enable_screenshots
                    and getattr(result, "dom_changed", False)
                    and hasattr(bridge, "screenshot")
                ):
                    try:
                        ss_result = await bridge.screenshot()
                        if getattr(ss_result, "success", False):
                            ss_data = getattr(ss_result, "data", {})
                            screenshot_id = f"step_{step}_{task.task_id[:8]}"
                            task.screenshots.append(screenshot_id)
                            self._emit_event(task.task_id, EVENT_SCREENSHOT, CHANNEL_WEBSOCKET, {
                                "screenshot_id": screenshot_id,
                                "step": step,
                                "format": ss_data.get("format", "png"),
                            })
                    except Exception:
                        pass

                # Handle extraction results
                if command.command_type == "extract" and getattr(result, "success", False):
                    extracted = getattr(result, "data", {})
                    task.extracted_data.update(extracted)
                    self._emit_event(task.task_id, EVENT_DATA_EXTRACTED, CHANNEL_SSE, {
                        "data": extracted,
                        "step": step,
                    })

                # Report errors
                if not getattr(result, "success", True):
                    error_msg = getattr(result, "error", "unknown error")
                    self._emit_event(task.task_id, EVENT_ERROR, CHANNEL_SSE, {
                        "message": f"Action failed: {error_msg}",
                        "step": step,
                    })

            # 5. Periodic completion check
            if step % self.config.completion_check_interval == 0 and planner is not None:
                try:
                    completed, summary = await planner.evaluate_completion(
                        task.description, dom, history,
                    )
                    if completed:
                        task.result = summary
                        task.status = STATUS_COMPLETED
                        task.completed_at = time.time()
                        break
                except Exception:
                    pass

            # Progress event
            self._emit_event(task.task_id, EVENT_PROGRESS, CHANNEL_SSE, {
                "step": step,
                "max_steps": task.max_steps,
                "progress_pct": round(step / task.max_steps * 100, 1),
                "pages_visited": len(task.pages_visited),
            })

            # Brief delay to avoid tight-looping
            await asyncio.sleep(self.config.agent_loop_delay)

        # Max steps reached without completion
        if not task.is_terminal:
            task.status = STATUS_FAILED
            task.error = f"Max steps ({task.max_steps}) reached without completing task"
            task.completed_at = time.time()

    # -----------------------------------------------------------------
    # Event streaming
    # -----------------------------------------------------------------

    async def stream_events(self, task_id: str) -> AsyncGenerator[TaskEvent, None]:
        """Stream events for a specific task.

        Yields ``TaskEvent`` objects as they are emitted. The generator
        completes when the task reaches a terminal state.
        """
        if task_id not in self._event_notify:
            self._event_notify[task_id] = asyncio.Event()

        cursor = 0
        while True:
            buffer = self._event_buffers.get(task_id, [])
            while cursor < len(buffer):
                yield buffer[cursor]
                cursor += 1

            # Check if task is done
            task = self._tasks.get(task_id)
            if task and task.is_terminal:
                # Yield any remaining events
                buffer = self._event_buffers.get(task_id, [])
                while cursor < len(buffer):
                    yield buffer[cursor]
                    cursor += 1
                return

            # Wait for new events
            notify = self._event_notify.get(task_id)
            if notify:
                notify.clear()
                try:
                    await asyncio.wait_for(notify.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass  # Re-check state

    async def stream_all_events(self, user_id: str) -> AsyncGenerator[TaskEvent, None]:
        """Stream events for ALL tasks owned by a user.

        Yields ``TaskEvent`` objects from all active tasks belonging
        to the specified user.
        """
        cursor = 0
        while True:
            while cursor < len(self._global_event_buffer):
                event = self._global_event_buffer[cursor]
                cursor += 1
                # Filter by user
                task = self._tasks.get(event.task_id)
                if task and task.user_id == user_id:
                    yield event

            # Check if any tasks are still active
            has_active = any(
                not t.is_terminal
                for t in self._tasks.values()
                if t.user_id == user_id
            )
            if not has_active and cursor >= len(self._global_event_buffer):
                return

            # Wait for new events
            self._global_notify.clear()
            try:
                await asyncio.wait_for(self._global_notify.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

    # -----------------------------------------------------------------
    # State queries
    # -----------------------------------------------------------------

    def get_task(self, task_id: str) -> FrontierTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self, user_id: str = "", status: str = "") -> list[FrontierTask]:
        """List tasks with optional filters.

        Args:
            user_id: Filter by user (empty = all users).
            status: Filter by status (empty = all statuses).

        Returns:
            List of matching ``FrontierTask`` objects, newest first.
        """
        result: list[FrontierTask] = []
        for task in self._tasks.values():
            if user_id and task.user_id != user_id:
                continue
            if status and task.status != status:
                continue
            result.append(task)
        result.sort(key=lambda t: t.created_at, reverse=True)
        return result

    def get_active_count(self) -> int:
        """Return the number of currently active (non-terminal) tasks."""
        return sum(
            1 for t in self._tasks.values()
            if not t.is_terminal
        )

    # -----------------------------------------------------------------
    # Internal — event emission
    # -----------------------------------------------------------------

    def _emit_event(
        self,
        task_id: str,
        event_type: str,
        channel: str,
        data: dict[str, Any],
    ) -> TaskEvent:
        """Create and buffer a TaskEvent, notifying stream consumers."""
        event = TaskEvent(
            task_id=task_id,
            event_type=event_type,
            channel=channel,
            data=data,
        )

        # Buffer per-task
        buf = self._event_buffers[task_id]
        buf.append(event)
        if len(buf) > self.config.event_buffer_size:
            self._event_buffers[task_id] = buf[-self.config.event_buffer_size:]

        # Global buffer
        self._global_event_buffer.append(event)
        if len(self._global_event_buffer) > self.config.event_buffer_size * 5:
            self._global_event_buffer = self._global_event_buffer[-(self.config.event_buffer_size * 3):]

        # Notify consumers
        notify = self._event_notify.get(task_id)
        if notify:
            notify.set()
        self._global_notify.set()

        return event

    # -----------------------------------------------------------------
    # Internal — sandbox management
    # -----------------------------------------------------------------

    async def _acquire_sandbox(self, task: FrontierTask) -> Any:
        """Acquire a sandbox from the pool or create one."""
        if self._sandbox_pool is not None and hasattr(self._sandbox_pool, "acquire"):
            try:
                sandbox = await self._sandbox_pool.acquire()
                log.debug("Acquired sandbox %s for task %s", getattr(sandbox, "id", "?"), task.task_id[:8])
                return sandbox
            except Exception as exc:
                log.warning("Pool acquire failed: %s — creating standalone", exc)

        # Create a lightweight mock sandbox for non-pool scenarios
        return _StandaloneSandbox(task_id=task.task_id)

    async def _release_sandbox(self, sandbox: Any) -> None:
        """Release a sandbox back to the pool."""
        if self._sandbox_pool is not None and hasattr(self._sandbox_pool, "release"):
            try:
                await self._sandbox_pool.release(sandbox)
                return
            except Exception as exc:
                log.debug("Pool release failed: %s", exc)

        # Standalone cleanup
        if hasattr(sandbox, "close"):
            try:
                await sandbox.close()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Internal — agent bridge / planner creation
    # -----------------------------------------------------------------

    def _create_dom_interpreter(self) -> Any:
        """Create a DOMInterpreter instance (or None if unavailable)."""
        try:
            from orchestra.frontier.dom_interpreter import DOMInterpreter as _DI
            return _DI()
        except Exception:
            return None

    def _create_agent_bridge(self, sandbox: Any, dom_interpreter: Any) -> Any:
        """Create an AgentBridge instance."""
        try:
            from orchestra.frontier.agent_bridge import AgentBridge as _AB
            return _AB(
                sandbox=sandbox,
                dom_interpreter=dom_interpreter,
                context_store=self._context_store,
                safety=self._safety,
            )
        except Exception as exc:
            log.warning("Could not create AgentBridge: %s — using fallback", exc)
            return _FallbackBridge(sandbox)

    def _create_planner(self) -> Any:
        """Create an LLMActionPlanner instance (or None)."""
        try:
            from orchestra.frontier.agent_bridge import LLMActionPlanner as _Planner
            router = self._get_router()
            return _Planner(
                router=router,
                config={
                    "model": self.config.model,
                    "max_steps": self.config.default_max_steps,
                },
            )
        except Exception as exc:
            log.warning("Could not create LLMActionPlanner: %s", exc)
            return None

    def _get_router(self) -> Any:
        """Get a ModelRouter instance."""
        try:
            from orchestra.router import ModelRouter as _MR
            return _MR()
        except Exception:
            return None

    # -----------------------------------------------------------------
    # Internal — approval flow
    # -----------------------------------------------------------------

    async def _request_approval(
        self,
        task: FrontierTask,
        command: Any,
        reason: str,
    ) -> bool:
        """Request user approval for a sensitive action.

        Pauses the agent loop and emits an ``approval_needed`` event.
        Returns ``True`` if approved, ``False`` if rejected or timed out.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._approval_futures[task.task_id] = future

        self._emit_event(task.task_id, EVENT_APPROVAL_NEEDED, CHANNEL_SSE, {
            "task_id": task.task_id,
            "command_type": getattr(command, "command_type", str(command)),
            "target": getattr(command, "target", ""),
            "description": getattr(command, "description", ""),
            "reason": reason,
        })

        try:
            approved = await asyncio.wait_for(
                future,
                timeout=self.config.default_timeout / 2,
            )
            return approved
        except asyncio.TimeoutError:
            log.info("Approval timed out for task %s", task.task_id[:8])
            return False

    # -----------------------------------------------------------------
    # Internal — background reaper
    # -----------------------------------------------------------------

    async def _reap_stale_tasks(self) -> None:
        """Background task that force-fails tasks exceeding the stale timeout."""
        while self._running:
            try:
                await asyncio.sleep(30.0)
                now = time.time()
                for task in list(self._tasks.values()):
                    if task.is_terminal:
                        continue
                    if task.started_at and (now - task.started_at) > self.config.stale_task_timeout:
                        log.warning("Reaping stale task %s (age=%.0fs)", task.task_id[:8], now - task.started_at)
                        task.status = STATUS_FAILED
                        task.error = "Task exceeded stale timeout"
                        task.completed_at = now
                        handle = self._task_handles.get(task.task_id)
                        if handle and not handle.done():
                            handle.cancel()
                        self._emit_event(task.task_id, EVENT_TASK_FAILED, CHANNEL_SSE, {
                            "error": task.error,
                        })
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log.debug("Reaper error: %s", exc)

    # -----------------------------------------------------------------
    # Internal — helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _get_current_url(bridge: Any) -> str:
        """Get the current URL from the bridge."""
        if hasattr(bridge, "_current_url"):
            try:
                return bridge._current_url()
            except Exception:
                pass
        return ""

    @staticmethod
    def _make_blocked_result(command: Any, reason: str) -> Any:
        """Create a failed CommandResult for a blocked action."""
        try:
            from orchestra.frontier.agent_bridge import CommandResult as _CR
            return _CR(success=False, command=command, error=f"Blocked: {reason}")
        except Exception:
            return {"success": False, "error": f"Blocked: {reason}"}

    @staticmethod
    def _make_error_result(command: Any, error: str) -> Any:
        """Create a failed CommandResult for an error."""
        try:
            from orchestra.frontier.agent_bridge import CommandResult as _CR
            return _CR(success=False, command=command, error=error)
        except Exception:
            return {"success": False, "error": error}


# =========================================================================
# Internal fallback classes (used when core layer isn't available)
# =========================================================================

class _StandaloneSandbox:
    """Minimal sandbox stand-in when no SandboxPool is available."""

    def __init__(self, task_id: str = "") -> None:
        self.id = f"standalone-{task_id[:8]}"
        self.current_url = ""
        self.page = None

    async def navigate(self, url: str, **kwargs: Any) -> None:
        self.current_url = url

    async def close(self) -> None:
        pass


class _FallbackBridge:
    """Minimal bridge stand-in when AgentBridge can't be created."""

    def __init__(self, sandbox: Any) -> None:
        self._sandbox = sandbox

    async def navigate(self, url: str, **kwargs: Any) -> Any:
        if hasattr(self._sandbox, "navigate"):
            await self._sandbox.navigate(url)

    async def dispatch(self, command: Any) -> Any:
        return None

    async def get_current_dom(self, page_id: str = "") -> None:
        return None

    async def screenshot(self, **kwargs: Any) -> Any:
        return None

    def _current_url(self) -> str:
        return getattr(self._sandbox, "current_url", "")
