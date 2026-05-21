from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

__all__ = [
    "try_import",
    "try_register",
    "silent_import",
]

log = logging.getLogger("orchestra")

F = TypeVar("F", bound=Callable[..., Any])


def try_import(module_path: str, attr: str = "") -> Any:
    """Import a module/attribute, returning None instead of raising.

    Logs a debug message on failure (not warning — most optional modules
    are expected to be missing in development).
    """
    try:
        mod = __import__(module_path, fromlist=[attr] if attr else [])
        return getattr(mod, attr) if attr else mod
    except ImportError:
        log.debug("Optional import failed: %s%s", module_path, f".{attr}" if attr else "")
        return None


def try_register(app: Any, module_path: str, func_name: str) -> bool:
    """Safely import a ``register_*`` function and call it with *app*.

    Returns True if the registration succeeded.
    """
    try:
        mod_parts = module_path.rsplit(".", 1)
        mod = __import__(mod_parts[0], fromlist=[mod_parts[1]])
        func = getattr(mod, func_name)
        func(app)
        return True
    except Exception as exc:
        log.debug("Optional registration skipped: %s.%s (%s)", module_path, func_name, exc)
        return False


def silent_import(module_path: str) -> Any:
    """Import a module, returning None on *any* failure (not just ImportError).

    Use sparingly — only for truly optional features where a missing
    dependency should NEVER block the application.
    """
    try:
        return __import__(module_path, fromlist=[""])
    except Exception:
        return None
