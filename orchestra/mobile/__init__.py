"""
orchestra/mobile/__init__.py
----------------------------
Mobile PWA layer for Horizon Orchestra.

Exports all mobile components for Progressive Web App support:
manifest, service worker, offline queue, push notifications,
touch UI, and app shell generators.
"""
from __future__ import annotations

__all__ = [
    "manifest",
    "service_worker",
    "offline_queue",
    "push_notifications",
    "touch_ui",
    "app_shell",
]

from orchestra.mobile import (  # noqa: F401 — re-exported for convenience
    app_shell,
    manifest,
    offline_queue,
    push_notifications,
    service_worker,
    touch_ui,
)
