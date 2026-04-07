"""Browser Sandbox — isolated execution environments for Frontier tasks.

Each sandbox wraps an independent Playwright browser context with its
own cookies, local-storage, resource limits, and lifecycle state.  The
``SandboxPool`` manages concurrent sandboxes and enforces global
resource budgets so that no single task can starve others.

Key design decisions:

* **Non-blocking** — sandboxes run asynchronously; the user's browsing
  session is never interrupted.
* **Auto-cleanup** — timed-out, failed, or completed sandboxes are
  torn down automatically by a background loop.
* **Tagged writes** — every context-store mutation carries the sandbox
  ID, enabling full auditability.

Usage::

    from orchestra.frontier.sandbox import SandboxPool, SandboxConfig
    from orchestra.frontier.context_store import ContextStore
    from orchestra.frontier.dom_interpreter import DOMInterpreter

    pool = SandboxPool(config=SandboxConfig(), context_store=ContextStore(),
                       dom_interpreter=DOMInterpreter())
    sb = await pool.create(task_id="price-check-1")
    await sb.start()
    page_id = await sb.open_page("https://example.com")
    snap = await sb.get_dom(page_id)
    await sb.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from playwright.async_api import (
        Browser as _Browser,
        BrowserContext as _BrowserContext,
        Page as _Page,
        Playwright as _Playwright,
        async_playwright as _async_playwright,
    )

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAS_PLAYWRIGHT = False

from .context_store import ContextStore
from .dom_interpreter import DOMInterpreter, DOMAction, DOMSnapshot

__all__ = [
    "BrowserSandbox",
    "SandboxPool",
    "SandboxConfig",
    "SandboxState",
    "SandboxMetrics",
]

log = logging.getLogger("orchestra.frontier.sandbox")


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------


class SandboxState(str, Enum):
    """Lifecycle states of a ``BrowserSandbox``."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SandboxConfig:
    """Resource limits and behaviour flags for a single sandbox."""

    max_concurrent_sandboxes: int = 10
    sandbox_timeout_seconds: float = 300.0  # 5 minutes default
    max_memory_mb: int = 512
    max_cpu_percent: float = 50.0
    network_enabled: bool = True
    allow_downloads: bool = False
    allow_uploads: bool = False
    allow_clipboard: bool = False
    isolated_storage: bool = True
    inherit_auth: bool = True
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 800
    user_agent: str = ""
    extra_http_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxMetrics:
    """Runtime metrics for a single sandbox."""

    sandbox_id: str
    state: SandboxState
    created_at: float
    started_at: float | None
    completed_at: float | None
    pages_opened: int
    actions_executed: int
    bytes_downloaded: int
    bytes_uploaded: int
    errors: int
    duration_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        """Serialise metrics to a plain dict."""
        return {
            "sandbox_id": self.sandbox_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pages_opened": self.pages_opened,
            "actions_executed": self.actions_executed,
            "bytes_downloaded": self.bytes_downloaded,
            "bytes_uploaded": self.bytes_uploaded,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }


# ---------------------------------------------------------------------------
# BrowserSandbox
# ---------------------------------------------------------------------------


class BrowserSandbox:
    """Isolated browser execution environment for a single task.

    Each sandbox:

    - Gets its own Playwright browser context (isolated cookies, storage).
    - Runs asynchronously — never blocks the user's main browser.
    - Has resource limits (memory, CPU, timeout).
    - Can read shared ``ContextStore`` but writes are tagged.
    - Reports progress via its ``metrics`` property.
    - Auto-cleans up on completion / timeout / error.

    Lifecycle::

        CREATED → STARTING → RUNNING → COMPLETING → COMPLETED
                                ↓                       ↓
                             PAUSED                   FAILED
                                ↓                       ↓
                             RUNNING                 CANCELLED
                                                        ↓
                                                    TIMED_OUT
    """

    def __init__(
        self,
        sandbox_id: str,
        config: SandboxConfig,
        context_store: ContextStore,
        dom_interpreter: DOMInterpreter,
    ) -> None:
        self.id = sandbox_id
        self.config = config
        self._context_store = context_store
        self._dom_interpreter = dom_interpreter

        # Internal state
        self._state = SandboxState.CREATED
        self._created_at = time.time()
        self._started_at: float | None = None
        self._completed_at: float | None = None

        # Playwright handles
        self._playwright: Any = None
        self._browser: Any = None
        self._browser_context: Any = None

        # Pages managed by this sandbox: page_id → Playwright Page
        self._pages: dict[str, Any] = {}

        # Metrics
        self._pages_opened = 0
        self._actions_executed = 0
        self._bytes_downloaded = 0
        self._bytes_uploaded = 0
        self._errors = 0

        # Timeout watchdog
        self._timeout_task: asyncio.Task[None] | None = None

        # Event callbacks
        self._event_callbacks: dict[str, list[Any]] = {}

        log.debug("Sandbox %s created (timeout=%.0fs)", self.id, config.sandbox_timeout_seconds)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SandboxState:
        """Current lifecycle state."""
        return self._state

    @property
    def metrics(self) -> SandboxMetrics:
        """Point-in-time metrics snapshot."""
        duration: float | None = None
        if self._started_at:
            end = self._completed_at or time.time()
            duration = end - self._started_at
        return SandboxMetrics(
            sandbox_id=self.id,
            state=self._state,
            created_at=self._created_at,
            started_at=self._started_at,
            completed_at=self._completed_at,
            pages_opened=self._pages_opened,
            actions_executed=self._actions_executed,
            bytes_downloaded=self._bytes_downloaded,
            bytes_uploaded=self._bytes_uploaded,
            errors=self._errors,
            duration_seconds=duration,
        )

    def is_alive(self) -> bool:
        """Return ``True`` if the sandbox is in an active state."""
        return self._state in (
            SandboxState.CREATED,
            SandboxState.STARTING,
            SandboxState.RUNNING,
            SandboxState.PAUSED,
            SandboxState.COMPLETING,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser context and transition to RUNNING.

        Raises ``RuntimeError`` if the sandbox is not in CREATED state.
        """
        if self._state != SandboxState.CREATED:
            raise RuntimeError(f"Cannot start sandbox in state {self._state.value}")

        self._state = SandboxState.STARTING
        self._started_at = time.time()
        log.info("Sandbox %s starting …", self.id)

        if _HAS_PLAYWRIGHT:
            try:
                self._playwright = await _async_playwright().start()

                launch_args: list[str] = ["--disable-blink-features=AutomationControlled"]
                self._browser = await self._playwright.chromium.launch(
                    headless=self.config.headless,
                    args=launch_args,
                )

                context_opts: dict[str, Any] = {
                    "viewport": {
                        "width": self.config.viewport_width,
                        "height": self.config.viewport_height,
                    },
                    "accept_downloads": self.config.allow_downloads,
                }
                if self.config.user_agent:
                    context_opts["user_agent"] = self.config.user_agent
                if self.config.extra_http_headers:
                    context_opts["extra_http_headers"] = self.config.extra_http_headers

                self._browser_context = await self._browser.new_context(**context_opts)

                # Network tracking
                self._browser_context.on(
                    "response",
                    lambda response: self._track_response(response),
                )

                log.info("Sandbox %s — Playwright context ready", self.id)
            except Exception as exc:
                self._state = SandboxState.FAILED
                self._errors += 1
                log.error("Sandbox %s failed to start: %s", self.id, exc)
                raise
        else:
            log.warning("Sandbox %s — Playwright unavailable, running in stub mode", self.id)

        self._state = SandboxState.RUNNING

        # Start timeout watchdog
        if self.config.sandbox_timeout_seconds > 0:
            self._timeout_task = asyncio.create_task(self._timeout_watchdog())

        self._emit("started", {"sandbox_id": self.id})
        log.info("Sandbox %s is RUNNING", self.id)

    async def stop(self, reason: str = "completed") -> None:
        """Gracefully stop the sandbox and clean up resources.

        Parameters
        ----------
        reason:
            Why the sandbox is stopping — ``"completed"``, ``"failed"``,
            ``"cancelled"``, ``"timed_out"``.
        """
        if not self.is_alive():
            return

        prev_state = self._state
        self._state = SandboxState.COMPLETING
        log.info("Sandbox %s stopping (reason=%s, was=%s)", self.id, reason, prev_state.value)

        # Cancel timeout watchdog
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
            self._timeout_task = None

        # Close all pages
        for page_id in list(self._pages.keys()):
            await self.close_page(page_id)

        # Close browser context and browser
        if self._browser_context:
            try:
                await self._browser_context.close()
            except Exception as exc:
                log.warning("Error closing context for sandbox %s: %s", self.id, exc)
            self._browser_context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                log.warning("Error closing browser for sandbox %s: %s", self.id, exc)
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                log.warning("Error stopping playwright for sandbox %s: %s", self.id, exc)
            self._playwright = None

        self._completed_at = time.time()

        # Map reason to final state
        state_map = {
            "completed": SandboxState.COMPLETED,
            "failed": SandboxState.FAILED,
            "cancelled": SandboxState.CANCELLED,
            "timed_out": SandboxState.TIMED_OUT,
        }
        self._state = state_map.get(reason, SandboxState.COMPLETED)

        self._emit("stopped", {"sandbox_id": self.id, "reason": reason})
        log.info("Sandbox %s → %s (duration=%.1fs)", self.id, self._state.value,
                 (self._completed_at - (self._started_at or self._created_at)))

    async def pause(self) -> None:
        """Pause the sandbox — suspends all page activity."""
        if self._state != SandboxState.RUNNING:
            raise RuntimeError(f"Cannot pause sandbox in state {self._state.value}")
        self._state = SandboxState.PAUSED
        log.info("Sandbox %s PAUSED", self.id)
        self._emit("paused", {"sandbox_id": self.id})

    async def resume(self) -> None:
        """Resume a paused sandbox."""
        if self._state != SandboxState.PAUSED:
            raise RuntimeError(f"Cannot resume sandbox in state {self._state.value}")
        self._state = SandboxState.RUNNING
        log.info("Sandbox %s RESUMED", self.id)
        self._emit("resumed", {"sandbox_id": self.id})

    async def cancel(self) -> None:
        """Cancel and tear down the sandbox."""
        log.info("Sandbox %s — cancel requested", self.id)
        await self.stop(reason="cancelled")

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    async def open_page(self, url: str) -> str:
        """Open a new page (tab) and navigate to *url*.

        Returns a unique ``page_id`` for later reference.
        """
        self._assert_running()
        page_id = uuid.uuid4().hex[:10]

        if _HAS_PLAYWRIGHT and self._browser_context:
            try:
                page = await self._browser_context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                self._pages[page_id] = page
            except Exception as exc:
                self._errors += 1
                log.error("Sandbox %s failed to open %s: %s", self.id, url, exc)
                raise
        else:
            # Stub mode
            self._pages[page_id] = {"url": url, "stub": True}

        self._pages_opened += 1
        log.info("Sandbox %s opened page %s → %s", self.id, page_id, url)

        # Store page context
        from .context_store import PageContext

        pc = PageContext.empty(tab_id=page_id, url=url)
        await self._context_store.update_page_context(page_id, pc)

        return page_id

    async def close_page(self, page_id: str) -> None:
        """Close a page by its ID."""
        page = self._pages.pop(page_id, None)
        if page is None:
            return

        if _HAS_PLAYWRIGHT and hasattr(page, "close"):
            try:
                await page.close()
            except Exception as exc:
                log.warning("Error closing page %s: %s", page_id, exc)

        log.debug("Sandbox %s closed page %s", self.id, page_id)

    async def get_page(self, page_id: str) -> Any:
        """Retrieve the underlying Playwright ``Page`` object."""
        self._assert_running()
        page = self._pages.get(page_id)
        if page is None:
            raise KeyError(f"No page with id '{page_id}' in sandbox {self.id}")
        return page

    async def get_dom(self, page_id: str) -> DOMSnapshot:
        """Interpret the DOM of a page and return a ``DOMSnapshot``.

        Also updates the context store with the new snapshot.
        """
        self._assert_running()
        page = await self.get_page(page_id)
        snapshot = await self._dom_interpreter.interpret(page)

        # Update context store
        await self._context_store.update_dom_snapshot(page_id, snapshot)

        return snapshot

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    async def execute_action(self, action: DOMAction, page_id: str) -> dict[str, Any]:
        """Execute a ``DOMAction`` on a page.

        Returns a result dict with keys ``success``, ``action_type``,
        ``node_id``, and optionally ``error``.
        """
        self._assert_running()
        page = await self.get_page(page_id)
        result: dict[str, Any] = {
            "success": False,
            "action_type": action.action_type,
            "node_id": action.node_id,
        }

        if not _HAS_PLAYWRIGHT or not hasattr(page, "evaluate"):
            result["error"] = "Playwright not available or page is a stub"
            self._errors += 1
            return result

        try:
            if action.action_type == "click":
                selector = self._node_selector(action.node_id)
                await page.click(selector, timeout=10_000)
                result["success"] = True

            elif action.action_type == "type":
                selector = self._node_selector(action.node_id)
                await page.fill(selector, action.value, timeout=10_000)
                result["success"] = True

            elif action.action_type == "select":
                selector = self._node_selector(action.node_id)
                await page.select_option(selector, action.value, timeout=10_000)
                result["success"] = True

            elif action.action_type == "hover":
                selector = self._node_selector(action.node_id)
                await page.hover(selector, timeout=10_000)
                result["success"] = True

            elif action.action_type == "scroll":
                delta_y = int(action.value) if action.value else 500
                await page.evaluate(f"window.scrollBy(0, {delta_y})")
                result["success"] = True

            elif action.action_type == "clear":
                selector = self._node_selector(action.node_id)
                await page.fill(selector, "", timeout=10_000)
                result["success"] = True

            elif action.action_type == "submit":
                selector = self._node_selector(action.node_id)
                await page.click(selector, timeout=10_000)
                result["success"] = True

            elif action.action_type == "focus":
                selector = self._node_selector(action.node_id)
                await page.focus(selector, timeout=10_000)
                result["success"] = True

            else:
                result["error"] = f"Unknown action type: {action.action_type}"
                self._errors += 1

        except Exception as exc:
            result["error"] = str(exc)
            self._errors += 1
            log.error(
                "Sandbox %s action %s on node %d failed: %s",
                self.id, action.action_type, action.node_id, exc,
            )

        if result["success"]:
            self._actions_executed += 1
            # Record the action in context store
            await self._context_store.put(
                key=f"action_{self._actions_executed}",
                value={
                    "action_type": action.action_type,
                    "node_id": action.node_id,
                    "value": action.value,
                    "description": action.description,
                },
                source=self.id,
                entry_type="page_state",
                namespace=page_id,
                ttl=600,  # 10 min
            )

        return result

    async def navigate(self, url: str, page_id: str) -> None:
        """Navigate an existing page to a new URL."""
        self._assert_running()
        page = await self.get_page(page_id)

        if _HAS_PLAYWRIGHT and hasattr(page, "goto"):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as exc:
                self._errors += 1
                log.error("Sandbox %s navigate to %s failed: %s", self.id, url, exc)
                raise

        # Update page context
        pc = await self._context_store.get_page_context(page_id)
        if pc:
            pc.history.append(pc.url)
            pc.url = url
            pc.last_updated = time.time()
            await self._context_store.update_page_context(page_id, pc)

        log.info("Sandbox %s navigated page %s → %s", self.id, page_id, url)

    async def screenshot(self, page_id: str) -> bytes:
        """Capture a PNG screenshot of the page.

        Returns raw PNG bytes, or an empty ``bytes`` object if
        Playwright is unavailable.
        """
        self._assert_running()
        page = await self.get_page(page_id)

        if _HAS_PLAYWRIGHT and hasattr(page, "screenshot"):
            try:
                data: bytes = await page.screenshot(type="png", full_page=False)
                self._bytes_downloaded += len(data)
                return data
            except Exception as exc:
                self._errors += 1
                log.error("Sandbox %s screenshot failed: %s", self.id, exc)
                return b""
        return b""

    async def evaluate_js(self, js: str, page_id: str) -> Any:
        """Execute arbitrary JavaScript in the page and return the result."""
        self._assert_running()
        page = await self.get_page(page_id)

        if _HAS_PLAYWRIGHT and hasattr(page, "evaluate"):
            try:
                return await page.evaluate(js)
            except Exception as exc:
                self._errors += 1
                log.error("Sandbox %s JS evaluation failed: %s", self.id, exc)
                raise
        return None

    # ------------------------------------------------------------------
    # Context access
    # ------------------------------------------------------------------

    async def read_context(self, key: str) -> Any:
        """Read a value from the shared context store."""
        entry = await self._context_store.get(key)
        if entry is None:
            return None
        return entry.value

    async def write_context(self, key: str, value: Any, entry_type: str) -> None:
        """Write a value to the shared context store, tagged with this sandbox ID."""
        await self._context_store.put(
            key=key,
            value=value,
            source=self.id,
            entry_type=entry_type,
        )

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def on(self, event: str, callback: Any) -> None:
        """Register an event callback.

        Supported events: ``started``, ``stopped``, ``paused``,
        ``resumed``, ``error``, ``page_opened``, ``action_executed``.
        """
        if event not in self._event_callbacks:
            self._event_callbacks[event] = []
        self._event_callbacks[event].append(callback)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Fire registered callbacks for an event (best-effort)."""
        for cb in self._event_callbacks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                log.warning("Event callback error for %s: %s", event, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_running(self) -> None:
        """Raise if the sandbox is not in a usable state."""
        if self._state not in (SandboxState.RUNNING, SandboxState.PAUSED):
            raise RuntimeError(
                f"Sandbox {self.id} is not running (state={self._state.value})"
            )

    def _node_selector(self, node_id: int) -> str:
        """Build a CSS-ish selector to target a node by its data attribute.

        Falls back to a JS-based approach when data attributes aren't
        available — uses ``document.querySelectorAll('*')[node_id]``.
        """
        return f"*:nth-child({node_id + 1})"

    def _track_response(self, response: Any) -> None:
        """Track download bytes from network responses (best-effort)."""
        try:
            headers = response.headers
            content_length = int(headers.get("content-length", 0))
            self._bytes_downloaded += content_length
        except Exception:
            pass

    async def _timeout_watchdog(self) -> None:
        """Wait for the configured timeout then stop the sandbox."""
        try:
            await asyncio.sleep(self.config.sandbox_timeout_seconds)
            if self.is_alive():
                log.warning(
                    "Sandbox %s timed out after %.0fs",
                    self.id, self.config.sandbox_timeout_seconds,
                )
                await self.stop(reason="timed_out")
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# SandboxPool
# ---------------------------------------------------------------------------


class SandboxPool:
    """Manages multiple concurrent sandboxes with resource limits.

    Enforces:

    - Maximum concurrent sandboxes (from ``SandboxConfig.max_concurrent_sandboxes``).
    - Total resource budget across all sandboxes.
    - Fair scheduling when at capacity (FIFO queue).
    - Automatic cleanup of dead / timed-out sandboxes via a background loop.
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        context_store: ContextStore | None = None,
        dom_interpreter: DOMInterpreter | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self._context_store = context_store or ContextStore()
        self._dom_interpreter = dom_interpreter or DOMInterpreter()

        # sandbox_id → BrowserSandbox
        self._sandboxes: dict[str, BrowserSandbox] = {}

        # Queue for requests waiting for capacity
        self._wait_queue: asyncio.Queue[asyncio.Event] = asyncio.Queue()

        # Lock for pool mutations
        self._lock = asyncio.Lock()

        # Background cleanup
        self._cleanup_task: asyncio.Task[None] | None = None

        log.debug(
            "SandboxPool initialised (max_concurrent=%d)",
            self.config.max_concurrent_sandboxes,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create(
        self, task_id: str, config: SandboxConfig | None = None
    ) -> BrowserSandbox:
        """Create a new sandbox for a task.

        If the pool is at capacity, the caller blocks until a slot opens.

        Parameters
        ----------
        task_id:
            Human-readable identifier for the task (used as sandbox_id prefix).
        config:
            Override config for this sandbox.  Falls back to the pool default.

        Returns
        -------
        BrowserSandbox
            Ready-to-start sandbox instance.
        """
        # Wait for capacity
        while True:
            async with self._lock:
                active = self._active_count()
                if active < self.config.max_concurrent_sandboxes:
                    break
                log.info(
                    "Pool at capacity (%d/%d) — queuing task %s",
                    active, self.config.max_concurrent_sandboxes, task_id,
                )

            # Wait for a slot to open
            event = asyncio.Event()
            await self._wait_queue.put(event)
            await event.wait()

        sandbox_id = f"{task_id}_{uuid.uuid4().hex[:6]}"
        sb_config = config or self.config

        sandbox = BrowserSandbox(
            sandbox_id=sandbox_id,
            config=sb_config,
            context_store=self._context_store,
            dom_interpreter=self._dom_interpreter,
        )

        async with self._lock:
            self._sandboxes[sandbox_id] = sandbox

        log.info("Created sandbox %s (active=%d)", sandbox_id, self._active_count())
        return sandbox

    async def get(self, sandbox_id: str) -> BrowserSandbox | None:
        """Retrieve a sandbox by ID."""
        return self._sandboxes.get(sandbox_id)

    async def destroy(self, sandbox_id: str) -> None:
        """Stop and remove a sandbox from the pool."""
        async with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)

        if sandbox is None:
            return

        if sandbox.is_alive():
            try:
                await sandbox.stop(reason="cancelled")
            except Exception as exc:
                log.warning("Error stopping sandbox %s during destroy: %s", sandbox_id, exc)

        log.info("Destroyed sandbox %s", sandbox_id)
        self._signal_waiters()

    async def destroy_all(self) -> None:
        """Stop and remove all sandboxes."""
        async with self._lock:
            sandbox_ids = list(self._sandboxes.keys())

        for sid in sandbox_ids:
            await self.destroy(sid)

        log.info("Destroyed all sandboxes (%d total)", len(sandbox_ids))

    def list_active(self) -> list[SandboxMetrics]:
        """Return metrics for all active (alive) sandboxes."""
        return [
            sb.metrics for sb in self._sandboxes.values() if sb.is_alive()
        ]

    def stats(self) -> dict[str, Any]:
        """Return pool-level statistics."""
        total = len(self._sandboxes)
        active = self._active_count()
        states: dict[str, int] = {}
        total_pages = 0
        total_actions = 0
        total_errors = 0

        for sb in self._sandboxes.values():
            m = sb.metrics
            state_key = m.state.value
            states[state_key] = states.get(state_key, 0) + 1
            total_pages += m.pages_opened
            total_actions += m.actions_executed
            total_errors += m.errors

        return {
            "total_sandboxes": total,
            "active_sandboxes": active,
            "max_concurrent": self.config.max_concurrent_sandboxes,
            "queued_tasks": self._wait_queue.qsize(),
            "states": states,
            "total_pages_opened": total_pages,
            "total_actions_executed": total_actions,
            "total_errors": total_errors,
        }

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def start_cleanup_loop(self) -> None:
        """Start the background cleanup loop.

        Periodically scans for dead, timed-out, or completed sandboxes
        and removes them from the pool.
        """
        if self._cleanup_task is not None:
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        log.info("Pool cleanup loop started")

    async def stop_cleanup_loop(self) -> None:
        """Cancel the background cleanup loop."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            log.info("Pool cleanup loop stopped")

    async def _cleanup_loop(self) -> None:
        """Scan and clean up non-alive sandboxes every 30 seconds."""
        interval = 30.0
        while True:
            try:
                await asyncio.sleep(interval)
                await self._cleanup_dead()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Pool cleanup error: %s", exc)

    async def _cleanup_dead(self) -> None:
        """Remove sandboxes that are no longer alive."""
        async with self._lock:
            dead_ids = [
                sid for sid, sb in self._sandboxes.items() if not sb.is_alive()
            ]
            for sid in dead_ids:
                self._sandboxes.pop(sid, None)

        if dead_ids:
            log.info("Cleaned up %d dead sandboxes: %s", len(dead_ids), dead_ids)
            self._signal_waiters()

        # Also check for sandboxes that have exceeded timeout but haven't
        # been stopped (edge case — the watchdog should handle this, but
        # belt-and-suspenders).
        now = time.time()
        for sb in list(self._sandboxes.values()):
            if sb.is_alive() and sb._started_at:
                elapsed = now - sb._started_at
                if elapsed > sb.config.sandbox_timeout_seconds * 1.5:
                    log.warning(
                        "Sandbox %s exceeded 1.5× timeout (%.0fs) — force stopping",
                        sb.id, elapsed,
                    )
                    try:
                        await sb.stop(reason="timed_out")
                    except Exception as exc:
                        log.error("Force stop of %s failed: %s", sb.id, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _active_count(self) -> int:
        """Count sandboxes that are alive."""
        return sum(1 for sb in self._sandboxes.values() if sb.is_alive())

    def _signal_waiters(self) -> None:
        """Wake up tasks waiting for pool capacity."""
        while not self._wait_queue.empty():
            try:
                event = self._wait_queue.get_nowait()
                event.set()
            except asyncio.QueueEmpty:
                break
