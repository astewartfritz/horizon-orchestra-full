"""Frontier Browser — Agent Bridge (RPC dispatch between LLM and sandbox).

RPC dispatch layer between the LLM agent and the browser sandbox.
Like Comet's comet-agent service worker, this routes LLM commands to
specific browser actions within an isolated sandbox.

Handles:
    - Command dispatch (navigate, click, type, extract, etc.)
    - DOM state refresh after each action
    - Screenshot capture on significant state changes
    - Error recovery (retry, fallback to coordinate-based clicks)
    - Action logging for audit trail

The bridge runs within a sandbox — it can only access pages owned
by that sandbox.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AgentBridge",
    "BrowserCommand",
    "CommandResult",
    "LLMActionPlanner",
]

log = logging.getLogger("orchestra.frontier.agent_bridge")

# ---------------------------------------------------------------------------
# Optional imports from core layer — graceful degradation
# ---------------------------------------------------------------------------
try:
    from orchestra.frontier.dom_interpreter import (
        DOMInterpreter,
        DOMSnapshot,
        DOMNode,
        DOMAction,
        InteractableElement,
        FormGroup,
    )
except Exception:  # pragma: no cover
    DOMInterpreter = Any  # type: ignore[assignment,misc]
    DOMSnapshot = Any  # type: ignore[assignment,misc]
    DOMNode = Any  # type: ignore[assignment,misc]
    DOMAction = Any  # type: ignore[assignment,misc]
    InteractableElement = Any  # type: ignore[assignment,misc]
    FormGroup = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.context_store import ContextStore, PageContext
except Exception:  # pragma: no cover
    ContextStore = Any  # type: ignore[assignment,misc]
    PageContext = Any  # type: ignore[assignment,misc]

try:
    from orchestra.frontier.safety import FrontierSafetyGuard
except Exception:  # pragma: no cover
    FrontierSafetyGuard = Any  # type: ignore[assignment,misc]

try:
    from orchestra.router import ModelRouter
except Exception:  # pragma: no cover
    ModelRouter = Any  # type: ignore[assignment,misc]


# =========================================================================
# Command data types
# =========================================================================

# All supported command types
COMMAND_TYPES: frozenset[str] = frozenset({
    "navigate", "click", "type", "select", "scroll", "screenshot",
    "extract", "evaluate_js", "go_back", "go_forward", "new_tab",
    "close_tab", "switch_tab", "hover", "wait", "submit_form",
})


@dataclass
class BrowserCommand:
    """A command from the LLM agent to execute in the browser.

    Each command has a type, a target (node_id, URL, or CSS selector),
    an optional value (text to type, JS to evaluate, etc.), and metadata.
    """

    command_type: str    # One of COMMAND_TYPES
    target: str          # node_id, URL, or CSS selector
    value: str = ""      # text to type, option to select, JS to evaluate
    timeout_ms: int = 10_000
    description: str = ""  # human-readable description

    def __post_init__(self) -> None:
        if self.command_type not in COMMAND_TYPES:
            log.warning(
                "Unknown command type %r — known types: %s",
                self.command_type,
                ", ".join(sorted(COMMAND_TYPES)),
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "command_type": self.command_type,
            "target": self.target,
            "value": self.value,
            "timeout_ms": self.timeout_ms,
            "description": self.description,
        }


@dataclass
class CommandResult:
    """Result of a browser command execution."""

    success: bool
    command: BrowserCommand
    data: dict[str, Any] = field(default_factory=dict)
    dom_changed: bool = False
    new_url: str = ""
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "success": self.success,
            "command": self.command.to_dict(),
            "data": self.data,
            "dom_changed": self.dom_changed,
            "new_url": self.new_url,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# =========================================================================
# AgentBridge — RPC dispatcher
# =========================================================================

class AgentBridge:
    """RPC bridge between LLM agent and browser sandbox.

    Like Comet's comet-agent, this receives high-level commands from
    the LLM and translates them into Playwright actions within the
    sandbox. Handles:

    - Command dispatch (navigate, click, type, extract, etc.)
    - DOM state refresh after each action
    - Screenshot capture on significant state changes
    - Error recovery (retry, fallback to coordinate-based clicks)
    - Action logging for audit trail

    The bridge runs within a sandbox — it can only access pages
    owned by that sandbox.
    """

    # Mapping of command_type → handler method name
    _HANDLERS: dict[str, str] = {
        "navigate": "navigate",
        "click": "click",
        "type": "type_text",
        "select": "select_option",
        "scroll": "scroll",
        "screenshot": "screenshot",
        "extract": "extract_data",
        "evaluate_js": "evaluate_js",
        "go_back": "go_back",
        "go_forward": "go_forward",
        "new_tab": "new_tab",
        "close_tab": "close_tab",
        "switch_tab": "_switch_tab",
        "hover": "hover",
        "wait": "wait",
        "submit_form": "submit_form",
    }

    def __init__(
        self,
        sandbox: Any,
        dom_interpreter: Any,
        context_store: Any,
        safety: Any | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._dom = dom_interpreter
        self._context_store = context_store
        self._safety = safety
        self._action_log: list[dict[str, Any]] = []
        self._step_counter: int = 0
        log.info("AgentBridge initialised (sandbox=%s)", getattr(sandbox, "id", "?"))

    # -----------------------------------------------------------------
    # Command dispatch
    # -----------------------------------------------------------------

    async def dispatch(self, command: BrowserCommand) -> CommandResult:
        """Dispatch a BrowserCommand to the appropriate handler.

        This is the primary entry point. It validates the command,
        runs a safety check (if a guard is configured), executes the
        action, refreshes DOM state, and logs the result.
        """
        start = time.monotonic()
        self._step_counter += 1
        step = self._step_counter

        log.debug("[step %d] dispatch %s → %s", step, command.command_type, command.target)

        # Safety check
        if self._safety is not None and hasattr(self._safety, "check_action"):
            try:
                allowed, reason, needs_approval = await self._safety.check_action(
                    command, None, self._current_url(),
                )
                if not allowed:
                    return self._fail(command, f"Blocked by safety guard: {reason}", start)
                if needs_approval:
                    return self._fail(
                        command,
                        f"Action requires user approval: {reason}",
                        start,
                    )
            except Exception as exc:
                log.warning("Safety check error: %s", exc)

        # Resolve handler
        handler_name = self._HANDLERS.get(command.command_type)
        if handler_name is None:
            return self._fail(command, f"Unknown command type: {command.command_type}", start)

        handler = getattr(self, handler_name, None)
        if handler is None:
            return self._fail(command, f"Handler not implemented: {handler_name}", start)

        # Execute
        try:
            result = await self._execute_handler(handler, command)
        except Exception as exc:
            log.error("[step %d] %s failed: %s", step, command.command_type, exc, exc_info=True)
            result = self._fail(command, str(exc), start)

        result.duration_ms = (time.monotonic() - start) * 1000.0

        # Log
        self._record_action(step, command, result)
        return result

    async def _execute_handler(
        self,
        handler: Any,
        command: BrowserCommand,
    ) -> CommandResult:
        """Route the command to the correct handler with arguments."""
        cmd_type = command.command_type
        target = command.target
        value = command.value

        if cmd_type == "navigate":
            return await handler(url=target)
        elif cmd_type == "click":
            return await handler(node_id=self._parse_int(target))
        elif cmd_type == "type":
            return await handler(node_id=self._parse_int(target), text=value)
        elif cmd_type == "select":
            return await handler(node_id=self._parse_int(target), value=value)
        elif cmd_type == "scroll":
            direction = value or "down"
            amount = self._parse_int(target, default=300)
            return await handler(direction=direction, amount=amount)
        elif cmd_type == "screenshot":
            full_page = value.lower() == "true" if value else False
            return await handler(full_page=full_page)
        elif cmd_type == "extract":
            return await handler()
        elif cmd_type == "evaluate_js":
            return await handler(js=value or target)
        elif cmd_type in ("go_back", "go_forward"):
            return await handler()
        elif cmd_type == "new_tab":
            return await handler(url=target)
        elif cmd_type == "close_tab":
            return await handler(page_id=target)
        elif cmd_type == "switch_tab":
            return await handler(page_id=target)
        elif cmd_type == "hover":
            return await handler(node_id=self._parse_int(target))
        elif cmd_type == "wait":
            timeout = self._parse_int(value, default=5000)
            return await handler(selector=target, timeout_ms=timeout)
        elif cmd_type == "submit_form":
            return await handler(form_id=target)
        else:
            return CommandResult(
                success=False,
                command=command,
                error=f"Unhandled command type: {cmd_type}",
            )

    # -----------------------------------------------------------------
    # Individual action handlers
    # -----------------------------------------------------------------

    async def navigate(self, url: str, page_id: str = "") -> CommandResult:
        """Navigate to a URL."""
        command = BrowserCommand("navigate", url, description=f"Navigate to {url}")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "goto"):
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "navigate"):
                await self._sandbox.navigate(url, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No page or sandbox navigate")

            new_url = self._current_url()
            dom_changed = new_url != url
            return CommandResult(
                success=True,
                command=command,
                new_url=new_url,
                dom_changed=True,
            )
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def click(self, node_id: int, page_id: str = "") -> CommandResult:
        """Click an element by node ID."""
        command = BrowserCommand("click", str(node_id), description=f"Click node {node_id}")
        try:
            page = self._get_page(page_id)
            selector = self._node_id_to_selector(node_id)
            if page is not None and hasattr(page, "click"):
                await page.click(selector, timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "click"):
                await self._sandbox.click(node_id, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No click method")

            await self._wait_for_navigation(page)
            return CommandResult(
                success=True,
                command=command,
                dom_changed=True,
                new_url=self._current_url(),
            )
        except Exception as exc:
            log.warning("Click node %d failed: %s — trying coordinate fallback", node_id, exc)
            return await self._click_fallback(node_id, page_id, command, exc)

    async def type_text(self, node_id: int, text: str, page_id: str = "") -> CommandResult:
        """Type text into an input element."""
        command = BrowserCommand("type", str(node_id), value=text, description=f"Type into node {node_id}")
        try:
            page = self._get_page(page_id)
            selector = self._node_id_to_selector(node_id)
            if page is not None and hasattr(page, "fill"):
                await page.fill(selector, text, timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "type_text"):
                await self._sandbox.type_text(node_id, text, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No type method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def select_option(self, node_id: int, value: str, page_id: str = "") -> CommandResult:
        """Select an option in a dropdown."""
        command = BrowserCommand("select", str(node_id), value=value, description=f"Select {value!r} in node {node_id}")
        try:
            page = self._get_page(page_id)
            selector = self._node_id_to_selector(node_id)
            if page is not None and hasattr(page, "select_option"):
                await page.select_option(selector, value=value, timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "select_option"):
                await self._sandbox.select_option(node_id, value, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No select method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def scroll(self, direction: str = "down", amount: int = 300, page_id: str = "") -> CommandResult:
        """Scroll the page."""
        command = BrowserCommand("scroll", str(amount), value=direction, description=f"Scroll {direction} {amount}px")
        try:
            page = self._get_page(page_id)
            delta_y = amount if direction == "down" else -amount
            delta_x = 0
            if direction == "right":
                delta_x, delta_y = amount, 0
            elif direction == "left":
                delta_x, delta_y = -amount, 0

            if page is not None and hasattr(page, "evaluate"):
                await page.evaluate(f"window.scrollBy({delta_x}, {delta_y})")
            elif self._sandbox is not None and hasattr(self._sandbox, "scroll"):
                await self._sandbox.scroll(direction, amount, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No scroll method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def screenshot(self, page_id: str = "", full_page: bool = False) -> CommandResult:
        """Take a screenshot of the current page."""
        command = BrowserCommand("screenshot", "", description="Take screenshot")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "screenshot"):
                raw_bytes = await page.screenshot(full_page=full_page)
                encoded = base64.b64encode(raw_bytes).decode("ascii")
                return CommandResult(
                    success=True,
                    command=command,
                    data={"screenshot_b64": encoded, "format": "png"},
                )
            elif self._sandbox is not None and hasattr(self._sandbox, "screenshot"):
                result = await self._sandbox.screenshot(page_id=page_id, full_page=full_page)
                return CommandResult(success=True, command=command, data={"screenshot": result})
            else:
                return CommandResult(success=False, command=command, error="No screenshot method")
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def extract_data(self, page_id: str = "") -> CommandResult:
        """Extract structured data from the current page using DOMInterpreter."""
        command = BrowserCommand("extract", "", description="Extract page data")
        try:
            dom_snapshot = await self.get_current_dom(page_id)
            if dom_snapshot is None:
                return CommandResult(success=False, command=command, error="Could not get DOM")

            data: dict[str, Any] = {}
            if hasattr(dom_snapshot, "to_dict"):
                data = dom_snapshot.to_dict()
            elif hasattr(dom_snapshot, "text_content"):
                data = {"text": dom_snapshot.text_content}
            else:
                data = {"snapshot": str(dom_snapshot)}

            return CommandResult(success=True, command=command, data=data)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def evaluate_js(self, js: str, page_id: str = "") -> CommandResult:
        """Evaluate JavaScript in the page context."""
        command = BrowserCommand("evaluate_js", "", value=js, description="Evaluate JS")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "evaluate"):
                result = await page.evaluate(js)
                return CommandResult(
                    success=True,
                    command=command,
                    data={"result": result},
                )
            elif self._sandbox is not None and hasattr(self._sandbox, "evaluate_js"):
                result = await self._sandbox.evaluate_js(js, page_id=page_id)
                return CommandResult(success=True, command=command, data={"result": result})
            else:
                return CommandResult(success=False, command=command, error="No evaluate method")
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def go_back(self, page_id: str = "") -> CommandResult:
        """Navigate back in browser history."""
        command = BrowserCommand("go_back", "", description="Go back")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "go_back"):
                await page.go_back(timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "go_back"):
                await self._sandbox.go_back(page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No go_back method")

            return CommandResult(
                success=True, command=command, dom_changed=True, new_url=self._current_url(),
            )
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def go_forward(self, page_id: str = "") -> CommandResult:
        """Navigate forward in browser history."""
        command = BrowserCommand("go_forward", "", description="Go forward")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "go_forward"):
                await page.go_forward(timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "go_forward"):
                await self._sandbox.go_forward(page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No go_forward method")

            return CommandResult(
                success=True, command=command, dom_changed=True, new_url=self._current_url(),
            )
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def new_tab(self, url: str = "") -> CommandResult:
        """Open a new browser tab."""
        command = BrowserCommand("new_tab", url, description=f"New tab: {url}")
        try:
            if self._sandbox is not None and hasattr(self._sandbox, "new_tab"):
                result = await self._sandbox.new_tab(url)
                page_id = result if isinstance(result, str) else getattr(result, "id", "")
                return CommandResult(
                    success=True, command=command,
                    data={"page_id": page_id}, new_url=url, dom_changed=True,
                )
            elif self._sandbox is not None and hasattr(self._sandbox, "create_page"):
                page = await self._sandbox.create_page(url)
                page_id = getattr(page, "id", str(uuid.uuid4())[:8])
                return CommandResult(
                    success=True, command=command,
                    data={"page_id": page_id}, new_url=url, dom_changed=True,
                )
            else:
                return CommandResult(success=False, command=command, error="No new_tab method")
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def close_tab(self, page_id: str = "") -> CommandResult:
        """Close a browser tab."""
        command = BrowserCommand("close_tab", page_id, description=f"Close tab {page_id}")
        try:
            if self._sandbox is not None and hasattr(self._sandbox, "close_tab"):
                await self._sandbox.close_tab(page_id)
            elif self._sandbox is not None and hasattr(self._sandbox, "close_page"):
                await self._sandbox.close_page(page_id)
            else:
                return CommandResult(success=False, command=command, error="No close_tab method")

            return CommandResult(success=True, command=command)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def _switch_tab(self, page_id: str = "") -> CommandResult:
        """Switch to a different browser tab."""
        command = BrowserCommand("switch_tab", page_id, description=f"Switch to tab {page_id}")
        try:
            if self._sandbox is not None and hasattr(self._sandbox, "switch_tab"):
                await self._sandbox.switch_tab(page_id)
            elif self._sandbox is not None and hasattr(self._sandbox, "focus_page"):
                await self._sandbox.focus_page(page_id)
            else:
                return CommandResult(success=False, command=command, error="No switch_tab method")

            return CommandResult(
                success=True, command=command, dom_changed=True, new_url=self._current_url(),
            )
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def hover(self, node_id: int, page_id: str = "") -> CommandResult:
        """Hover over an element."""
        command = BrowserCommand("hover", str(node_id), description=f"Hover node {node_id}")
        try:
            page = self._get_page(page_id)
            selector = self._node_id_to_selector(node_id)
            if page is not None and hasattr(page, "hover"):
                await page.hover(selector, timeout=10_000)
            elif self._sandbox is not None and hasattr(self._sandbox, "hover"):
                await self._sandbox.hover(node_id, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No hover method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def wait(self, selector: str = "", timeout_ms: int = 5000, page_id: str = "") -> CommandResult:
        """Wait for a selector to appear or for a timeout."""
        command = BrowserCommand("wait", selector, value=str(timeout_ms), description=f"Wait for {selector or 'timeout'}")
        try:
            page = self._get_page(page_id)
            if selector and page is not None and hasattr(page, "wait_for_selector"):
                await page.wait_for_selector(selector, timeout=timeout_ms)
            elif selector and self._sandbox is not None and hasattr(self._sandbox, "wait_for_selector"):
                await self._sandbox.wait_for_selector(selector, timeout_ms=timeout_ms, page_id=page_id)
            else:
                # Plain time-based wait
                await asyncio.sleep(timeout_ms / 1000.0)

            return CommandResult(success=True, command=command)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def submit_form(self, form_id: str, page_id: str = "") -> CommandResult:
        """Submit a form by form ID or selector."""
        command = BrowserCommand("submit_form", form_id, description=f"Submit form {form_id}")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "evaluate"):
                js = (
                    f"(() => {{"
                    f"  const f = document.querySelector('#{form_id}') "
                    f"    || document.querySelector('form[name=\"{form_id}\"]')"
                    f"    || document.querySelector('{form_id}');"
                    f"  if (f) {{ f.submit(); return true; }}"
                    f"  return false;"
                    f"}})()"
                )
                submitted = await page.evaluate(js)
                if not submitted:
                    return CommandResult(success=False, command=command, error=f"Form {form_id!r} not found")
            elif self._sandbox is not None and hasattr(self._sandbox, "submit_form"):
                await self._sandbox.submit_form(form_id, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No submit_form method")

            await self._wait_for_navigation(page)
            return CommandResult(
                success=True, command=command, dom_changed=True, new_url=self._current_url(),
            )
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    # -----------------------------------------------------------------
    # State queries
    # -----------------------------------------------------------------

    async def get_current_dom(self, page_id: str = "") -> Any:
        """Get the current DOM snapshot via DOMInterpreter.

        Returns a DOMSnapshot if the interpreter is available,
        otherwise ``None``.
        """
        try:
            if self._dom is not None and hasattr(self._dom, "parse_page"):
                page = self._get_page(page_id)
                return await self._dom.parse_page(page)
            elif self._dom is not None and hasattr(self._dom, "snapshot"):
                return await self._dom.snapshot(page_id=page_id)
            elif self._sandbox is not None and hasattr(self._sandbox, "get_dom"):
                return await self._sandbox.get_dom(page_id=page_id)
        except Exception as exc:
            log.warning("get_current_dom failed: %s", exc)
        return None

    async def get_page_text(self, page_id: str = "") -> str:
        """Get the visible text content of the current page."""
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "evaluate"):
                return await page.evaluate("document.body?.innerText || ''")
            elif self._sandbox is not None and hasattr(self._sandbox, "get_page_text"):
                return await self._sandbox.get_page_text(page_id=page_id)
        except Exception as exc:
            log.warning("get_page_text failed: %s", exc)
        return ""

    # -----------------------------------------------------------------
    # Fallback actions (coordinate-based)
    # -----------------------------------------------------------------

    async def click_by_coordinates(self, x: int, y: int, page_id: str = "") -> CommandResult:
        """Fallback: click at specific viewport coordinates."""
        command = BrowserCommand("click", f"{x},{y}", description=f"Click at ({x}, {y})")
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "mouse"):
                await page.mouse.click(x, y)
            elif self._sandbox is not None and hasattr(self._sandbox, "click_at"):
                await self._sandbox.click_at(x, y, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No coordinate click method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    async def type_by_coordinates(self, x: int, y: int, text: str, page_id: str = "") -> CommandResult:
        """Fallback: click at coordinates then type text."""
        command = BrowserCommand("type", f"{x},{y}", value=text, description=f"Type at ({x},{y})")
        try:
            click_result = await self.click_by_coordinates(x, y, page_id)
            if not click_result.success:
                return CommandResult(success=False, command=command, error=click_result.error)

            page = self._get_page(page_id)
            if page is not None and hasattr(page, "keyboard"):
                await page.keyboard.type(text)
            elif self._sandbox is not None and hasattr(self._sandbox, "keyboard_type"):
                await self._sandbox.keyboard_type(text, page_id=page_id)
            else:
                return CommandResult(success=False, command=command, error="No keyboard type method")

            return CommandResult(success=True, command=command, dom_changed=True)
        except Exception as exc:
            return CommandResult(success=False, command=command, error=str(exc))

    # -----------------------------------------------------------------
    # Action history
    # -----------------------------------------------------------------

    def get_action_log(self) -> list[dict[str, Any]]:
        """Return the full action log for audit purposes."""
        return list(self._action_log)

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _get_page(self, page_id: str = "") -> Any:
        """Get a Playwright page handle from the sandbox."""
        if self._sandbox is None:
            return None
        if page_id:
            if hasattr(self._sandbox, "get_page"):
                try:
                    return self._sandbox.get_page(page_id)
                except Exception:
                    pass
        # Return the current/active page
        for attr in ("current_page", "active_page", "page"):
            val = getattr(self._sandbox, attr, None)
            if val is not None:
                return val
        return None

    def _current_url(self) -> str:
        """Get the current page URL."""
        page = self._get_page()
        if page is not None and hasattr(page, "url"):
            try:
                return page.url
            except Exception:
                pass
        if self._sandbox is not None and hasattr(self._sandbox, "current_url"):
            return self._sandbox.current_url
        return ""

    @staticmethod
    def _node_id_to_selector(node_id: int) -> str:
        """Convert a node ID to a CSS selector.

        Uses the ``data-frontier-id`` attribute convention set by
        the DOMInterpreter when annotating the DOM.
        """
        return f"[data-frontier-id='{node_id}']"

    @staticmethod
    def _parse_int(value: str, default: int = 0) -> int:
        """Safely parse an integer from a string."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    async def _wait_for_navigation(self, page: Any, timeout_ms: int = 3000) -> None:
        """Wait briefly for navigation after an action."""
        if page is None:
            return
        try:
            if hasattr(page, "wait_for_load_state"):
                await asyncio.wait_for(
                    page.wait_for_load_state("domcontentloaded"),
                    timeout=timeout_ms / 1000.0,
                )
        except (asyncio.TimeoutError, Exception):
            pass  # Best-effort

    async def _click_fallback(
        self,
        node_id: int,
        page_id: str,
        command: BrowserCommand,
        original_error: Exception,
    ) -> CommandResult:
        """Fallback when normal click fails — try coordinate-based click."""
        try:
            page = self._get_page(page_id)
            if page is not None and hasattr(page, "evaluate"):
                coords = await page.evaluate(
                    f"""(() => {{
                        const el = document.querySelector('[data-frontier-id="{node_id}"]');
                        if (!el) return null;
                        const r = el.getBoundingClientRect();
                        return {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
                    }})()"""
                )
                if coords:
                    return await self.click_by_coordinates(
                        int(coords["x"]), int(coords["y"]), page_id,
                    )
        except Exception as fallback_exc:
            log.debug("Coordinate fallback also failed: %s", fallback_exc)

        return CommandResult(
            success=False,
            command=command,
            error=f"Click failed (node {node_id}): {original_error}",
        )

    def _record_action(self, step: int, command: BrowserCommand, result: CommandResult) -> None:
        """Record an action in the audit log."""
        entry = {
            "step": step,
            "timestamp": time.time(),
            "command": command.to_dict(),
            "success": result.success,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "dom_changed": result.dom_changed,
            "new_url": result.new_url,
        }
        self._action_log.append(entry)
        if len(self._action_log) > 5_000:
            self._action_log = self._action_log[-2_500:]

    @staticmethod
    def _fail(command: BrowserCommand, error: str, start: float) -> CommandResult:
        """Create a failed CommandResult."""
        return CommandResult(
            success=False,
            command=command,
            error=error,
            duration_ms=(time.monotonic() - start) * 1000.0,
        )


# =========================================================================
# LLMActionPlanner — decides the next action via LLM
# =========================================================================

_SYSTEM_PROMPT = """\
You are MILES, the AI assistant powering Horizon Orchestra's Frontier browser.
You are an expert web automation agent. Given a task description and the
current state of a web page (represented as a markdown table of interactable
elements), you decide the SINGLE next browser action to take.

RULES:
- Output EXACTLY ONE action as a JSON object.
- The JSON must have keys: "command_type", "target", "value", "description".
- command_type must be one of: navigate, click, type, select, scroll,
  screenshot, extract, evaluate_js, go_back, go_forward, new_tab,
  close_tab, hover, wait, submit_form.
- target: For click/type/select/hover use the node_id (integer as string).
  For navigate/new_tab use the URL. For scroll use the amount.
  For wait use a CSS selector. For evaluate_js, target can be empty.
- value: For type, the text to enter. For select, the option value.
  For scroll, the direction (up/down/left/right). For evaluate_js, the
  JavaScript code. Otherwise empty string.
- description: A brief human-readable explanation of what you're doing.
- If the task appears complete, output: {"command_type": "DONE", "target": "", "value": "", "description": "Task completed: <summary>"}
- NEVER make up information. Only act on what you see in the DOM.
- Be efficient — take the most direct path to completing the task.
"""

_ACTION_PROMPT_TEMPLATE = """\
TASK: {task}

STEP: {step}/{max_steps}

CURRENT PAGE URL: {url}
PAGE TITLE: {title}

INTERACTABLE ELEMENTS:
{dom_table}

RECENT ACTIONS:
{history}

Decide the next action. Output ONLY a JSON object.
"""

_COMPLETION_PROMPT_TEMPLATE = """\
TASK: {task}

The agent has performed the following actions:
{history}

CURRENT PAGE URL: {url}
PAGE TITLE: {title}

VISIBLE TEXT (truncated):
{visible_text}

Has the task been completed? Respond with a JSON object:
{{"completed": true/false, "summary": "brief explanation"}}
"""


class LLMActionPlanner:
    """Plans browser actions using the LLM (Kimi K2.5).

    Given a task description and the current DOM state, asks the LLM
    to decide the next action. Uses the DOMInterpreter's markdown
    table format for efficient context.

    Plan-Act-Observe loop:
    1. PLAN: LLM sees task + DOM → decides next action
    2. ACT: AgentBridge executes the action
    3. OBSERVE: DOM refreshed, result evaluated
    4. Repeat until task complete or max_steps
    """

    def __init__(
        self,
        router: Any,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._router = router
        self._config = config or {}
        self._model = self._config.get("model", "kimi-k2.5")
        self._temperature = self._config.get("temperature", 0.2)
        self._max_tokens = self._config.get("max_tokens", 1024)
        log.info("LLMActionPlanner initialised (model=%s)", self._model)

    # -----------------------------------------------------------------
    # Plan next action
    # -----------------------------------------------------------------

    async def plan_next_action(
        self,
        task: str,
        dom: Any,
        history: list[CommandResult],
        step: int,
        max_steps: int,
    ) -> BrowserCommand | None:
        """Ask the LLM to decide the next browser action.

        Returns a ``BrowserCommand`` or ``None`` if the LLM signals
        task completion (command_type == "DONE").
        """
        system_prompt = self.build_system_prompt()
        action_prompt = self.build_action_prompt(task, dom, history, step)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": action_prompt},
        ]

        try:
            response = await self._call_llm(messages)
            parsed = self._parse_action_response(response)
            if parsed is None:
                log.warning("Could not parse LLM action response")
                return None

            if parsed.get("command_type") == "DONE":
                log.info("LLM signals task complete: %s", parsed.get("description", ""))
                return None

            return BrowserCommand(
                command_type=parsed.get("command_type", ""),
                target=str(parsed.get("target", "")),
                value=str(parsed.get("value", "")),
                description=str(parsed.get("description", "")),
            )
        except Exception as exc:
            log.error("LLM planning failed: %s", exc, exc_info=True)
            return None

    # -----------------------------------------------------------------
    # Evaluate completion
    # -----------------------------------------------------------------

    async def evaluate_completion(
        self,
        task: str,
        dom: Any,
        history: list[CommandResult],
    ) -> tuple[bool, str]:
        """Ask the LLM whether the task has been completed.

        Returns:
            (completed, summary)
        """
        url = self._dom_url(dom)
        title = self._dom_title(dom)
        visible_text = self._dom_visible_text(dom)[:3000]

        history_text = self._format_history(history, max_entries=10)

        prompt = _COMPLETION_PROMPT_TEMPLATE.format(
            task=task,
            history=history_text,
            url=url,
            title=title,
            visible_text=visible_text,
        )

        messages = [
            {"role": "system", "content": "You evaluate whether a browser automation task is complete."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self._call_llm(messages)
            parsed = self._parse_json_response(response)
            completed = bool(parsed.get("completed", False))
            summary = str(parsed.get("summary", ""))
            return completed, summary
        except Exception as exc:
            log.warning("Completion evaluation failed: %s", exc)
            return False, ""

    # -----------------------------------------------------------------
    # Prompt builders
    # -----------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Build the system prompt for the action-planning LLM call."""
        return _SYSTEM_PROMPT

    def build_action_prompt(
        self,
        task: str,
        dom: Any,
        history: list[CommandResult],
        step: int,
    ) -> str:
        """Build the user prompt with DOM state and action history.

        Uses the DOMInterpreter's markdown table format when available
        for compact, efficient context.
        """
        max_steps = self._config.get("max_steps", 50)
        url = self._dom_url(dom)
        title = self._dom_title(dom)
        dom_table = self._build_dom_table(dom)
        history_text = self._format_history(history, max_entries=8)

        return _ACTION_PROMPT_TEMPLATE.format(
            task=task,
            step=step,
            max_steps=max_steps,
            url=url,
            title=title,
            dom_table=dom_table,
            history=history_text,
        )

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call the LLM via ModelRouter."""
        if self._router is not None and hasattr(self._router, "chat"):
            response = await self._router.chat(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return response
        elif self._router is not None and hasattr(self._router, "complete"):
            response = await self._router.complete(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            if hasattr(response, "content"):
                return response.content
            return str(response)
        else:
            raise RuntimeError("No LLM router available for planning")

    def _parse_action_response(self, response: str) -> dict[str, Any] | None:
        """Parse the LLM's JSON action response."""
        return self._parse_json_response(response)

    @staticmethod
    def _parse_json_response(response: str) -> dict[str, Any]:
        """Extract and parse JSON from an LLM response string.

        Handles cases where the LLM wraps JSON in markdown code blocks.
        """
        text = response.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Try to find JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        # Last resort — try the whole string
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Could not parse JSON from LLM response: %s", text[:200])
            return {}

    def _build_dom_table(self, dom: Any) -> str:
        """Build a markdown table of interactable elements from the DOM.

        Prioritises the DOMInterpreter's built-in methods, falling back
        to a simple text representation.
        """
        if dom is None:
            return "(no DOM available)"

        # DOMInterpreter.to_markdown_table() is the preferred format
        if hasattr(dom, "to_markdown_table"):
            try:
                return dom.to_markdown_table()
            except Exception:
                pass

        # Fallback: build from interactable elements
        if hasattr(dom, "interactable_elements"):
            try:
                elements = dom.interactable_elements
                if not elements:
                    return "(no interactable elements)"
                lines = ["| ID | Tag | Text | Type | Href |", "|---|---|---|---|---|"]
                for el in elements[:80]:
                    eid = getattr(el, "node_id", getattr(el, "id", ""))
                    tag = getattr(el, "tag", "")
                    text = str(getattr(el, "text", ""))[:60].replace("|", "\\|")
                    etype = getattr(el, "element_type", getattr(el, "type", ""))
                    href = str(getattr(el, "href", ""))[:80].replace("|", "\\|")
                    lines.append(f"| {eid} | {tag} | {text} | {etype} | {href} |")
                return "\n".join(lines)
            except Exception:
                pass

        # Last fallback
        if hasattr(dom, "text_content"):
            return str(dom.text_content)[:2000]
        return str(dom)[:2000]

    @staticmethod
    def _format_history(history: list[CommandResult], max_entries: int = 8) -> str:
        """Format recent action history for the LLM prompt."""
        if not history:
            return "(no actions taken yet)"

        recent = history[-max_entries:]
        lines: list[str] = []
        for i, result in enumerate(recent, 1):
            cmd = result.command
            status = "OK" if result.success else f"FAILED: {result.error[:60]}"
            line = f"{i}. [{cmd.command_type}] {cmd.description or cmd.target} → {status}"
            if result.new_url:
                line += f" (now at {result.new_url})"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _dom_url(dom: Any) -> str:
        """Extract URL from a DOM snapshot."""
        for attr in ("url", "page_url", "current_url"):
            val = getattr(dom, attr, None)
            if val:
                return str(val)
        return ""

    @staticmethod
    def _dom_title(dom: Any) -> str:
        """Extract title from a DOM snapshot."""
        for attr in ("title", "page_title"):
            val = getattr(dom, attr, None)
            if val:
                return str(val)
        return ""

    @staticmethod
    def _dom_visible_text(dom: Any) -> str:
        """Extract visible text from a DOM snapshot."""
        for attr in ("visible_text", "text_content", "page_text"):
            val = getattr(dom, attr, None)
            if val and isinstance(val, str):
                return val
        if hasattr(dom, "get_text"):
            try:
                return dom.get_text()
            except Exception:
                pass
        return ""
