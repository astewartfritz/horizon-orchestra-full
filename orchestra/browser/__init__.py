"""Horizon Orchestra — Chromium Browser Architecture.

Persistent Chromium browser pool, autonomous web navigation,
DOM extraction, screenshot intelligence, and session management.

This is Horizon Prince's persistent
browser — but with persistent sessions, tab groups, and an
autonomous agent that can reason about web pages.
"""

from .engine import BrowserEngine, BrowserPool, EngineConfig
from .agent import BrowserAgent, BrowseResult
from .analyzer import PageAnalyzer, PageData
from .sessions import SessionManager, BrowserSession, SessionConfig

__all__ = [
    "BrowserEngine",
    "BrowserPool",
    "EngineConfig",
    "BrowserAgent",
    "BrowseResult",
    "PageAnalyzer",
    "PageData",
    "SessionManager",
    "BrowserSession",
    "SessionConfig",
]
