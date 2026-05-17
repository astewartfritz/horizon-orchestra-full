"""Root conftest.

Ensures top-level modules (e.g. ``horizon.py``) that live at the repo
root but aren't part of the installed ``orchestra`` package are on
``sys.path`` when tests run via ``pip install -e .`` in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
