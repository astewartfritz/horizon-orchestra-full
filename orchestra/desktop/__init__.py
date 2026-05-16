"""Horizon Orchestra — Desktop Automation Package.

Provides programmatic desktop control via screenshot capture, mouse/keyboard
automation, and an LLM-driven computer-use agent loop.

Public API::

    from orchestra.desktop import (
        DesktopController,
        ScreenCapture,
        ComputerUseAgent,
        ComputerUseResult,
        DesktopConfig,
    )
"""

from __future__ import annotations

from .computer_use import (
    ComputerUseAgent,
    ComputerUseResult,
    DesktopConfig,
    DesktopController,
    ScreenCapture,
)

__all__ = [
    "DesktopController",
    "ScreenCapture",
    "ComputerUseAgent",
    "ComputerUseResult",
    "DesktopConfig",
]
