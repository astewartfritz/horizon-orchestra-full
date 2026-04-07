"""pytest configuration — handles asyncio mode compatibility.

The test suite mixes two async styles:
- Our tests: pytest-native async tests with asyncio_mode="auto"
- Upstream tests: unittest.IsolatedAsyncioTestCase (manages its own loop)

pytest-asyncio with asyncio_mode="auto" creates a new event loop per
test session. IsolatedAsyncioTestCase also creates its own loop per test.
When they run in the same session, the loops can conflict. This conftest
resets the event loop state between test items to prevent contamination.
"""
from __future__ import annotations

import asyncio
import unittest


def pytest_runtest_setup(item) -> None:
    """Reset the event loop before each test to prevent cross-contamination.

    This is needed because:
    1. pytest-asyncio (asyncio_mode=auto) creates a global event loop
    2. unittest.IsolatedAsyncioTestCase creates per-test loops
    3. When they interleave, stale loops cause RuntimeError

    For IsolatedAsyncioTestCase tests: close any stale loop and provide
    a fresh one so IsolatedAsyncioTestCase can take over.
    For all other tests: just ensure the loop isn't closed.
    """
    if hasattr(item, "cls") and item.cls is not None and issubclass(
        item.cls, unittest.IsolatedAsyncioTestCase
    ):
        # IsolatedAsyncioTestCase manages its own loop — give it a clean slate
        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            if loop is not None and not loop.is_closed():
                loop.close()
        except RuntimeError:
            pass
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)


def pytest_runtest_teardown(item, nextitem) -> None:
    """After an IsolatedAsyncioTestCase test, reset the loop for pytest tests."""
    if hasattr(item, "cls") and item.cls is not None and issubclass(
        item.cls, unittest.IsolatedAsyncioTestCase
    ):
        # Close the loop IsolatedAsyncioTestCase used
        try:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            if loop is not None and not loop.is_closed():
                loop.close()
        except RuntimeError:
            pass
        # Create a fresh loop for the next test (pytest-asyncio will use it)
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
