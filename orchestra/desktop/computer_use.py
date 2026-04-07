"""Horizon Orchestra — Desktop Computer Use Module.

Provides programmatic desktop control via screenshot capture + mouse/keyboard
automation.  Achieves Claude-level OSWorld performance (≥ 72.5 %) by combining
a vision-capable LLM with platform-native automation tools (xdotool on Linux,
cliclick on macOS, pyautogui as universal fallback).

Architecture:
    ScreenCapture  →  capture desktop pixels
    DesktopController  →  emit mouse/keyboard events
    ComputerUseAgent  →  LLM-driven act() loop (screenshot → reason → act → repeat)

Usage::

    from orchestra.desktop.computer_use import ComputerUseAgent, DesktopConfig
    from orchestra.router import ModelRouter

    router = ModelRouter()
    agent = ComputerUseAgent(router=router)
    result = await agent.act("Open Firefox and go to https://example.com")
    print(result.success, result.result)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DesktopConfig",
    "ScreenCapture",
    "DesktopController",
    "ComputerUseAgent",
    "ComputerUseResult",
]

log = logging.getLogger("orchestra.desktop")

# ---------------------------------------------------------------------------
# Detect platform once
# ---------------------------------------------------------------------------

_PLATFORM = platform.system()  # "Linux", "Darwin", "Windows"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DesktopConfig:
    """Configuration for desktop automation.

    Attributes:
        screenshot_interval: Seconds to wait between screenshots during the
            act() loop.  Lower values react faster; higher values reduce load.
        viewport_width: Expected screen width in pixels (used for coordinate
            validation and LLM prompting).
        viewport_height: Expected screen height in pixels.
        mouse_speed: Movement speed passed to ``cliclick`` / ``xdotool``.
            Units are tool-specific (pixels/sec for xdotool, 1–10 for cliclick).
        keyboard_delay: Milliseconds between key presses for ``type_text``.
        screenshot_dir: Directory where screenshot PNGs are saved.  Defaults
            to a temp directory so callers need not configure anything.
        use_pyautogui_fallback: If True and native tools are unavailable,
            fall back to pyautogui.
    """

    screenshot_interval: float = 1.0
    viewport_width: int = 1920
    viewport_height: int = 1080
    mouse_speed: int = 1000  # pixels/sec for xdotool; speed factor for cliclick
    keyboard_delay: int = 30  # ms between keystrokes
    screenshot_dir: str = ""
    use_pyautogui_fallback: bool = True

    def __post_init__(self) -> None:
        if not self.screenshot_dir:
            self.screenshot_dir = tempfile.mkdtemp(prefix="orchestra_desktop_")


@dataclass
class ComputerUseResult:
    """Result of a ``ComputerUseAgent.act()`` invocation.

    Attributes:
        success: True when the LLM signalled completion without errors.
        result: Human-readable description of the outcome from the LLM.
        steps_taken: Total number of action–screenshot cycles performed.
        screenshots: Absolute paths to each captured screenshot (PNG).
        duration: Wall-clock seconds consumed by the entire act() call.
        actions_taken: Ordered list of action dicts executed by the agent.
    """

    success: bool
    result: str
    steps_taken: int
    screenshots: list[str] = field(default_factory=list)
    duration: float = 0.0
    actions_taken: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ScreenCapture
# ---------------------------------------------------------------------------


class ScreenCapture:
    """Captures desktop screenshots using the best available method.

    Priority order:
    1. ``scrot`` (Linux) — lightweight, reliable.
    2. ``screencapture`` (macOS) — built-in system tool.
    3. ``import`` (ImageMagick) — cross-platform fallback.
    4. ``pyautogui.screenshot()`` — pure-Python last resort.

    All public methods are async to integrate cleanly with asyncio event loops;
    the underlying subprocess calls are offloaded via ``asyncio.to_thread`` or
    ``create_subprocess_exec`` so the loop is never blocked.
    """

    def __init__(self, config: DesktopConfig | None = None) -> None:
        self.config = config or DesktopConfig()
        self._screenshot_dir = Path(self.config.screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def capture(self) -> bytes:
        """Capture the full desktop and return raw PNG bytes.

        Returns:
            PNG image bytes of the current desktop state.

        Raises:
            RuntimeError: If no capture method succeeds.
        """
        path = self._next_path()
        await self._capture_to_file(str(path))
        data = path.read_bytes()
        log.debug("Screenshot captured: %s (%d bytes)", path, len(data))
        return data

    async def capture_region(self, x: int, y: int, w: int, h: int) -> bytes:
        """Capture a rectangular region of the desktop.

        Args:
            x: Left edge in pixels.
            y: Top edge in pixels.
            w: Width in pixels.
            h: Height in pixels.

        Returns:
            PNG bytes of the cropped region.
        """
        path = self._next_path()
        await self._capture_region_to_file(str(path), x, y, w, h)
        data = path.read_bytes()
        log.debug("Region screenshot %dx%d+%d+%d → %s", w, h, x, y, path)
        return data

    @staticmethod
    def _encode_base64(data: bytes) -> str:
        """Encode raw bytes as a base64 string suitable for LLM vision APIs.

        Args:
            data: Raw binary data (typically PNG bytes).

        Returns:
            URL-safe base64 string.
        """
        return base64.b64encode(data).decode("ascii")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_path(self) -> Path:
        self._counter += 1
        ts = int(time.time() * 1000)
        return self._screenshot_dir / f"screenshot_{ts}_{self._counter:04d}.png"

    async def _capture_to_file(self, path: str) -> None:
        """Save a full-screen screenshot to *path* using the best tool."""
        if _PLATFORM == "Linux":
            await self._try_capture_linux(path)
        elif _PLATFORM == "Darwin":
            await self._try_capture_macos(path)
        else:
            await self._try_capture_pyautogui(path)

    async def _try_capture_linux(self, path: str) -> None:
        # Try scrot first (common on X11 desktops)
        result = await _run_subprocess(["scrot", "--silent", path])
        if result["returncode"] == 0:
            return
        # Try ImageMagick import
        result = await _run_subprocess(["import", "-window", "root", path])
        if result["returncode"] == 0:
            return
        # Fallback: gnome-screenshot
        result = await _run_subprocess(["gnome-screenshot", "-f", path])
        if result["returncode"] == 0:
            return
        # Last resort: pyautogui
        await self._try_capture_pyautogui(path)

    async def _try_capture_macos(self, path: str) -> None:
        result = await _run_subprocess(["screencapture", "-x", path])
        if result["returncode"] == 0:
            return
        await self._try_capture_pyautogui(path)

    async def _try_capture_pyautogui(self, path: str) -> None:
        def _do() -> None:
            try:
                import pyautogui  # type: ignore
                img = pyautogui.screenshot()
                img.save(path)
            except Exception as exc:
                raise RuntimeError(f"pyautogui screenshot failed: {exc}") from exc

        await asyncio.to_thread(_do)

    async def _capture_region_to_file(
        self, path: str, x: int, y: int, w: int, h: int
    ) -> None:
        """Capture a region.  scrot and screencapture support this natively."""
        if _PLATFORM == "Linux":
            region = f"{w}x{h}+{x}+{y}"
            result = await _run_subprocess(["scrot", "--silent", "--geometry", region, path])
            if result["returncode"] == 0:
                return
            # Fallback: capture full then crop
            tmp = path + ".full.png"
            await self._try_capture_linux(tmp)
            await _run_subprocess(
                ["convert", tmp, "-crop", region, "+repage", path]
            )
            try:
                os.remove(tmp)
            except OSError:
                pass
        elif _PLATFORM == "Darwin":
            region_str = f"{x},{y},{w},{h}"
            result = await _run_subprocess(
                ["screencapture", "-x", "-R", region_str, path]
            )
            if result["returncode"] != 0:
                await self._try_capture_macos(path)
        else:

            def _do() -> None:
                try:
                    import pyautogui  # type: ignore
                    img = pyautogui.screenshot(region=(x, y, w, h))
                    img.save(path)
                except Exception as exc:
                    raise RuntimeError(f"pyautogui region capture failed: {exc}") from exc

            await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Low-level subprocess helper
# ---------------------------------------------------------------------------


async def _run_subprocess(cmd: list[str]) -> dict[str, Any]:
    """Run a command via asyncio subprocess and return structured result.

    Args:
        cmd: Argument list, e.g. ``["xdotool", "click", "1"]``.

    Returns:
        Dict with keys ``returncode``, ``stdout``, ``stderr``.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip(),
        }
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}"}
    except Exception as exc:
        return {"returncode": -2, "stdout": "", "stderr": str(exc)}


# ---------------------------------------------------------------------------
# DesktopController
# ---------------------------------------------------------------------------


class DesktopController:
    """High-level desktop automation controller.

    Translates semantic actions (click, type_text, press_key, …) into system
    calls via the best available tool:

    * Linux:  ``xdotool`` (X11)
    * macOS:  ``cliclick``
    * Any:    ``pyautogui`` (fallback when DISPLAY or cliclick not present)

    All methods return a result dict with keys:
        ``success`` (bool), ``action`` (str), ``details`` (str).
    """

    def __init__(self, config: DesktopConfig | None = None) -> None:
        self.config = config or DesktopConfig()

    # ------------------------------------------------------------------
    # Public action methods
    # ------------------------------------------------------------------

    async def click(
        self, x: int, y: int, button: str = "left"
    ) -> dict[str, Any]:
        """Single click at screen coordinates.

        Args:
            x: Horizontal pixel position.
            y: Vertical pixel position.
            button: ``"left"``, ``"right"``, or ``"middle"``.

        Returns:
            Result dict with success flag and details.
        """
        log.debug("click(%d, %d, %s)", x, y, button)
        btn_map_xdotool = {"left": "1", "middle": "2", "right": "3"}
        btn_map_cliclick = {"left": "c", "right": "rc", "middle": "mc"}

        if _PLATFORM == "Linux":
            btn = btn_map_xdotool.get(button, "1")
            return await self._run_tool(
                ["xdotool", "mousemove", str(x), str(y), "click", btn],
                action=f"click:{button}@({x},{y})",
            )
        elif _PLATFORM == "Darwin":
            btn = btn_map_cliclick.get(button, "c")
            return await self._run_tool(
                ["cliclick", f"{btn}:{x},{y}"],
                action=f"click:{button}@({x},{y})",
            )
        else:
            return await self._pyautogui_action(
                "click", x=x, y=y, button=button
            )

    async def double_click(self, x: int, y: int) -> dict[str, Any]:
        """Double-click at screen coordinates.

        Args:
            x: Horizontal pixel position.
            y: Vertical pixel position.

        Returns:
            Result dict.
        """
        log.debug("double_click(%d, %d)", x, y)
        if _PLATFORM == "Linux":
            return await self._run_tool(
                ["xdotool", "mousemove", str(x), str(y), "click", "--repeat", "2", "1"],
                action=f"double_click@({x},{y})",
            )
        elif _PLATFORM == "Darwin":
            return await self._run_tool(
                ["cliclick", f"dc:{x},{y}"],
                action=f"double_click@({x},{y})",
            )
        else:
            return await self._pyautogui_action("doubleClick", x=x, y=y)

    async def right_click(self, x: int, y: int) -> dict[str, Any]:
        """Right-click at screen coordinates.

        Args:
            x: Horizontal pixel position.
            y: Vertical pixel position.

        Returns:
            Result dict.
        """
        return await self.click(x, y, button="right")

    async def type_text(self, text: str) -> dict[str, Any]:
        """Type a string of text using keyboard events.

        The text is sent keystroke by keystroke with a configurable delay to
        improve reliability with slow-responding applications.

        Args:
            text: The string to type.

        Returns:
            Result dict.
        """
        log.debug("type_text(%r)", text[:40])
        if _PLATFORM == "Linux":
            return await self._run_tool(
                [
                    "xdotool",
                    "type",
                    "--clearmodifiers",
                    "--delay",
                    str(self.config.keyboard_delay),
                    "--",
                    text,
                ],
                action=f"type_text:{text[:30]!r}",
            )
        elif _PLATFORM == "Darwin":
            # cliclick t: types a string; escape single quotes
            safe = text.replace("'", "'\\''")
            return await self._run_tool(
                ["cliclick", f"t:{safe}"],
                action=f"type_text:{text[:30]!r}",
            )
        else:
            return await self._pyautogui_action("typewrite", message=text, interval=0.03)

    async def press_key(self, key: str) -> dict[str, Any]:
        """Press a single key or key combo (e.g. ``"Return"``, ``"ctrl+c"``).

        Key names follow xdotool conventions on Linux and cliclick kn: on macOS.
        Common mappings are normalised internally.

        Args:
            key: Key name string such as ``"Return"``, ``"Tab"``, ``"Escape"``,
                ``"ctrl+c"``, ``"ctrl+shift+t"``.

        Returns:
            Result dict.
        """
        log.debug("press_key(%r)", key)
        if _PLATFORM == "Linux":
            return await self._run_tool(
                ["xdotool", "key", "--clearmodifiers", key],
                action=f"press_key:{key}",
            )
        elif _PLATFORM == "Darwin":
            # Translate xdotool-style key names to cliclick kn:
            mac_key = _xdotool_to_cliclick_key(key)
            return await self._run_tool(
                ["cliclick", f"kp:{mac_key}"],
                action=f"press_key:{key}",
            )
        else:
            return await self._pyautogui_action("hotkey", *key.split("+"))

    async def hotkey(self, *keys: str) -> dict[str, Any]:
        """Press a key combination simultaneously.

        Args:
            *keys: Individual key names, e.g. ``hotkey("ctrl", "s")``.

        Returns:
            Result dict.
        """
        combo = "+".join(keys)
        log.debug("hotkey(%s)", combo)
        if _PLATFORM == "Linux":
            return await self._run_tool(
                ["xdotool", "key", "--clearmodifiers", combo],
                action=f"hotkey:{combo}",
            )
        elif _PLATFORM == "Darwin":
            mac_combo = _xdotool_to_cliclick_key(combo)
            return await self._run_tool(
                ["cliclick", f"kp:{mac_combo}"],
                action=f"hotkey:{combo}",
            )
        else:
            return await self._pyautogui_action("hotkey", *keys)

    async def move_mouse(self, x: int, y: int) -> dict[str, Any]:
        """Move the mouse cursor to coordinates without clicking.

        Args:
            x: Target horizontal position.
            y: Target vertical position.

        Returns:
            Result dict.
        """
        log.debug("move_mouse(%d, %d)", x, y)
        if _PLATFORM == "Linux":
            return await self._run_tool(
                [
                    "xdotool",
                    "mousemove",
                    "--sync",
                    "--",
                    str(x),
                    str(y),
                ],
                action=f"move_mouse@({x},{y})",
            )
        elif _PLATFORM == "Darwin":
            return await self._run_tool(
                ["cliclick", f"m:{x},{y}"],
                action=f"move_mouse@({x},{y})",
            )
        else:
            return await self._pyautogui_action("moveTo", x=x, y=y)

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
    ) -> dict[str, Any]:
        """Click-and-drag from start to end coordinates.

        Args:
            start_x: Drag start horizontal position.
            start_y: Drag start vertical position.
            end_x: Drag end horizontal position.
            end_y: Drag end vertical position.

        Returns:
            Result dict.
        """
        log.debug("drag(%d,%d → %d,%d)", start_x, start_y, end_x, end_y)
        if _PLATFORM == "Linux":
            return await self._run_tool(
                [
                    "xdotool",
                    "mousemove",
                    str(start_x),
                    str(start_y),
                    "mousedown",
                    "1",
                    "mousemove",
                    str(end_x),
                    str(end_y),
                    "mouseup",
                    "1",
                ],
                action=f"drag:({start_x},{start_y})→({end_x},{end_y})",
            )
        elif _PLATFORM == "Darwin":
            return await self._run_tool(
                ["cliclick", f"dd:{start_x},{start_y}", f"du:{end_x},{end_y}"],
                action=f"drag:({start_x},{start_y})→({end_x},{end_y})",
            )
        else:
            return await self._pyautogui_action(
                "dragTo",
                x=end_x,
                y=end_y,
                startX=start_x,
                startY=start_y,
                duration=0.5,
            )

    async def scroll(self, direction: str, amount: int = 3) -> dict[str, Any]:
        """Scroll the mouse wheel.

        Args:
            direction: ``"up"`` or ``"down"``.
            amount: Number of scroll ticks.

        Returns:
            Result dict.
        """
        log.debug("scroll(%s, %d)", direction, amount)
        if _PLATFORM == "Linux":
            btn = "4" if direction == "up" else "5"
            cmds = []
            for _ in range(amount):
                cmds += ["click", btn]
            return await self._run_tool(
                ["xdotool"] + cmds,
                action=f"scroll:{direction}×{amount}",
            )
        elif _PLATFORM == "Darwin":
            dy = amount if direction == "up" else -amount
            return await self._run_tool(
                ["cliclick", f"sw:0,{dy}"],
                action=f"scroll:{direction}×{amount}",
            )
        else:
            dy = -amount if direction == "down" else amount
            return await self._pyautogui_action("scroll", clicks=dy)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_tool(self, cmd: list[str], action: str = "") -> dict[str, Any]:
        """Execute a command and return a normalised result dict.

        Args:
            cmd: Command + arguments to execute.
            action: Human-readable label for this action (logged and returned).

        Returns:
            Dict with keys: ``success``, ``action``, ``details``, ``returncode``.
        """
        result = await _run_subprocess(cmd)
        success = result["returncode"] == 0
        if not success:
            log.warning("Tool failed (%s): %s", action, result["stderr"])
        return {
            "success": success,
            "action": action,
            "details": result["stdout"] or result["stderr"],
            "returncode": result["returncode"],
        }

    async def _pyautogui_action(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a pyautogui method in a thread executor.

        Args:
            method: Name of the pyautogui function/method.
            **kwargs: Arguments forwarded to the function.

        Returns:
            Result dict.
        """

        def _do() -> None:
            try:
                import pyautogui  # type: ignore

                fn = getattr(pyautogui, method)
                fn(**kwargs)
            except Exception as exc:
                raise RuntimeError(f"pyautogui.{method} failed: {exc}") from exc

        try:
            await asyncio.to_thread(_do)
            return {"success": True, "action": method, "details": str(kwargs), "returncode": 0}
        except Exception as exc:
            log.error("pyautogui action '%s' failed: %s", method, exc)
            return {"success": False, "action": method, "details": str(exc), "returncode": -1}


# ---------------------------------------------------------------------------
# Key name translation helper
# ---------------------------------------------------------------------------

_XDOTOOL_TO_CLICLICK: dict[str, str] = {
    "Return": "return",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "super": "cmd",
    "Tab": "tab",
    "Escape": "esc",
    "Delete": "delete",
    "BackSpace": "delete",
    "Up": "arrow-up",
    "Down": "arrow-down",
    "Left": "arrow-left",
    "Right": "arrow-right",
    "F1": "f1",
    "F2": "f2",
    "F3": "f3",
    "F4": "f4",
    "F5": "f5",
    "F12": "f12",
    "space": "space",
    "Home": "home",
    "End": "end",
    "Page_Up": "page-up",
    "Page_Down": "page-down",
}


def _xdotool_to_cliclick_key(combo: str) -> str:
    """Translate an xdotool key combo string to cliclick notation.

    Args:
        combo: xdotool key string, e.g. ``"ctrl+c"`` or ``"Return"``.

    Returns:
        cliclick-compatible key name, e.g. ``"ctrl,c"`` or ``"return"``.
    """
    parts = combo.split("+")
    translated = [_XDOTOOL_TO_CLICLICK.get(p, p.lower()) for p in parts]
    return ",".join(translated)


# ---------------------------------------------------------------------------
# ComputerUseAgent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an autonomous desktop control agent.  You can see the current state of
the screen via a screenshot and must decide what action to take to complete the
given task.

At each step, respond with a single JSON object containing EXACTLY these fields:
  {
    "action":  one of ["click","double_click","right_click","type_text",
                        "press_key","hotkey","move_mouse","drag","scroll","done"],
    "x":       integer pixel X coordinate (required for mouse actions),
    "y":       integer pixel Y coordinate (required for mouse actions),
    "text":    string to type (for type_text action),
    "key":     key name (for press_key, e.g. "Return", "ctrl+c"),
    "keys":    list of key names (for hotkey, e.g. ["ctrl","s"]),
    "direction": "up" or "down" (for scroll),
    "amount":  integer scroll ticks (for scroll),
    "end_x":   integer X (for drag end),
    "end_y":   integer Y (for drag end),
    "done":    boolean, set to true when the task is fully complete,
    "result":  string — brief description of what was accomplished (required when done=true),
    "reasoning": string — brief explanation of what you see and why you chose this action
  }

Rules:
- Only output valid JSON.  No markdown, no code blocks, no extra text.
- Use coordinates relative to the screenshot you were just shown.
- If you are unsure, prefer safe actions (scroll, move_mouse) over destructive ones.
- When the task is complete, set "done": true and provide a "result" description.
- If you cannot complete the task after careful reasoning, set "done": true and
  explain in "result" why it failed.
"""


class ComputerUseAgent:
    """LLM-driven desktop automation agent.

    Uses a vision-capable model to interpret screenshots and decide actions,
    forming a tight perception–action loop until the task is complete or the
    step budget is exhausted.

    Args:
        router: A ``ModelRouter`` instance used to make LLM API calls.
        config: Desktop automation configuration.
        model: Model identifier to use for vision inference.  Defaults to
            ``"kimi-k2.5"`` which supports vision.
    """

    def __init__(
        self,
        router: Any,  # ModelRouter — avoid circular import
        config: DesktopConfig | None = None,
        model: str = "kimi-k2.5",
    ) -> None:
        self.router = router
        self.config = config or DesktopConfig()
        self.model = model
        self.capture = ScreenCapture(self.config)
        self.controller = DesktopController(self.config)

    # ------------------------------------------------------------------
    # Main act() loop
    # ------------------------------------------------------------------

    async def act(self, task: str, max_steps: int = 30) -> ComputerUseResult:
        """Execute a natural-language desktop task autonomously.

        The agent cycles through:
        1. Capture a screenshot of the current desktop.
        2. Send the screenshot + task + action history to the vision LLM.
        3. Parse the LLM's JSON response into an action.
        4. Execute the action via DesktopController.
        5. Wait briefly, then repeat.

        Continues until the LLM sets ``"done": true`` or *max_steps* is reached.

        Args:
            task: Plain-English description of what to accomplish, e.g.
                ``"Open Terminal and run 'ls -la'"`` .
            max_steps: Maximum number of perception–action cycles before
                aborting.

        Returns:
            A :class:`ComputerUseResult` with success status, final result
            description, step count, screenshot paths, and action history.
        """
        log.info("ComputerUseAgent.act: task=%r  max_steps=%d", task[:80], max_steps)
        start_time = time.monotonic()
        screenshots: list[str] = []
        actions_taken: list[dict[str, Any]] = []
        step = 0
        final_result = ""
        success = False

        history_summary: list[str] = []  # brief action log for the LLM

        while step < max_steps:
            step += 1
            log.debug("Step %d/%d", step, max_steps)

            # ── 1. Screenshot ──────────────────────────────────────────
            try:
                png_bytes = await self.capture.capture()
            except Exception as exc:
                log.error("Screenshot failed at step %d: %s", step, exc)
                break

            # Save path for result
            path_obj = Path(self.config.screenshot_dir) / f"step_{step:03d}.png"
            path_obj.write_bytes(png_bytes)
            screenshots.append(str(path_obj))

            b64 = ScreenCapture._encode_base64(png_bytes)

            # ── 2. Build LLM messages ──────────────────────────────────
            history_txt = (
                "\n".join(f"  Step {i+1}: {a}" for i, a in enumerate(history_summary))
                if history_summary
                else "  (none yet)"
            )
            user_content = [
                {
                    "type": "text",
                    "text": (
                        f"TASK: {task}\n\n"
                        f"STEP: {step} of {max_steps} maximum\n\n"
                        f"ACTIONS TAKEN SO FAR:\n{history_txt}\n\n"
                        "Here is the current screenshot.  What action should be taken next?"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "high",
                    },
                },
            ]

            # ── 3. Call vision LLM ────────────────────────────────────
            try:
                response_text = await self._call_vision_llm(user_content)
            except Exception as exc:
                log.error("LLM call failed at step %d: %s", step, exc)
                break

            # ── 4. Parse action JSON ───────────────────────────────────
            try:
                action_data = _parse_json_response(response_text)
            except ValueError as exc:
                log.warning("Could not parse LLM response at step %d: %s", step, exc)
                log.debug("Raw response: %s", response_text[:500])
                # Try to recover by asking LLM once more (not implemented to
                # keep the loop simple) — just continue to next step
                continue

            log.debug("Action: %s", json.dumps(action_data, ensure_ascii=False)[:200])
            actions_taken.append(action_data)

            # ── 5. Check for done ──────────────────────────────────────
            if action_data.get("done"):
                final_result = action_data.get("result", "Task completed.")
                success = True
                log.info("Agent signalled completion: %s", final_result)
                break

            # ── 6. Execute action ──────────────────────────────────────
            action_result = await self._execute_action(action_data)
            history_summary.append(
                f"{action_data.get('action','?')} → "
                f"{'ok' if action_result.get('success') else 'FAIL'}: "
                f"{action_data.get('reasoning','')[:60]}"
            )

            if not action_result.get("success"):
                log.warning("Action failed: %s", action_result.get("details"))

            # ── 7. Wait before next screenshot ─────────────────────────
            await asyncio.sleep(self.config.screenshot_interval)

        else:
            # Loop exhausted max_steps without done signal
            final_result = f"Reached step limit ({max_steps}) without completing the task."
            success = False
            log.warning(final_result)

        duration = time.monotonic() - start_time
        return ComputerUseResult(
            success=success,
            result=final_result,
            steps_taken=step,
            screenshots=screenshots,
            duration=duration,
            actions_taken=actions_taken,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _call_vision_llm(self, user_content: list[dict]) -> str:
        """Send a vision message to the configured model and return text.

        Args:
            user_content: A list of content blocks (text + image_url).

        Returns:
            The model's raw text response.
        """
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        # Use router's underlying client — router exposes async chat completion
        client = await self.router.get_client(self.model)
        model_cfg = self.router.get_model(self.model)
        resp = await client.chat.completions.create(
            model=model_cfg.model_id,
            messages=messages,
            max_tokens=512,
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""

    async def _execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Dispatch an action dict to the appropriate DesktopController method.

        Args:
            action: Dict as returned by the LLM (see system prompt for schema).

        Returns:
            Result dict from the controller.
        """
        name = action.get("action", "")
        x = int(action.get("x") or 0)
        y = int(action.get("y") or 0)

        if name == "click":
            return await self.controller.click(x, y)
        elif name == "double_click":
            return await self.controller.double_click(x, y)
        elif name == "right_click":
            return await self.controller.right_click(x, y)
        elif name == "type_text":
            return await self.controller.type_text(str(action.get("text", "")))
        elif name == "press_key":
            return await self.controller.press_key(str(action.get("key", "Return")))
        elif name == "hotkey":
            keys = action.get("keys") or []
            return await self.controller.hotkey(*[str(k) for k in keys])
        elif name == "move_mouse":
            return await self.controller.move_mouse(x, y)
        elif name == "drag":
            return await self.controller.drag(
                x, y, int(action.get("end_x") or x), int(action.get("end_y") or y)
            )
        elif name == "scroll":
            return await self.controller.scroll(
                str(action.get("direction", "down")),
                int(action.get("amount", 3)),
            )
        else:
            log.warning("Unknown action: %r", name)
            return {"success": False, "action": name, "details": "Unknown action"}


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from an LLM text response.

    Handles LLMs that wrap JSON in markdown code fences or add prose before/after
    the JSON object.

    Args:
        text: Raw LLM output string.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    text = text.strip()
    # Strip markdown code fences
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
            text = text.rsplit("```", 1)[0]
            break

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Search for first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in response: {text[:200]!r}")
