"""Deprecated — import from ``orchestra.code_agent`` instead.

This shim exists for backward compatibility. New code should use::

    from orchestra.code_agent.xxx import yyy
"""

import importlib
import warnings
from typing import Any

warnings.warn(
    "Import from `code_agent` is deprecated. Use `orchestra.code_agent` instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Import top-level names so ``from code_agent import X`` works for names defined
# in orchestra/code_agent/__init__.py.
from orchestra.code_agent import *  # noqa: F401, F403

# Make subpackages accessible via ``code_agent.xxx`` so that
# ``from code_agent.context.manager import ContextManager`` still works.
_ORCHESTRA_PREFIX = "orchestra.code_agent."


def __getattr__(name: str) -> Any:
    try:
        return importlib.import_module(_ORCHESTRA_PREFIX + name)
    except ImportError:
        try:
            return importlib.import_module(name)
        except ImportError:
            raise AttributeError(f"module 'code_agent' has no attribute {name!r}")


def __dir__() -> list[str]:
    import orchestra.code_agent as _real
    return dir(_real)
