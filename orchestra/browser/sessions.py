"""Browser Session Manager — tab groups, cookie persistence, profile isolation.

Each user gets an isolated browser profile with persistent cookies,
localStorage, and session state. Tab groups organize related pages
(e.g., "research" tabs vs "work" tabs).

This is what makes Orchestra's browser fundamentally different from
other platforms — sessions survive across conversations. An agent
can log into a service once, and future sessions reuse that auth.

Usage::

    from orchestra.browser.sessions import SessionManager
    mgr = SessionManager(base_dir="~/.horizon/browser_profiles")
    session = await mgr.get_or_create("ashton")
    page = await session.open_tab("https://github.com", group="work")
    await session.save()
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import BrowserEngine, EngineConfig, PageHandle

__all__ = ["SessionManager", "BrowserSession", "TabGroup", "SessionConfig"]

log = logging.getLogger("orchestra.browser.sessions")


@dataclass
class SessionConfig:
    base_dir: str = ""                   # empty → ~/.horizon/browser_profiles
    max_tabs_per_group: int = 10
    max_groups: int = 10
    session_timeout_hours: int = 24
    persist_cookies: bool = True
    headless: bool = True


@dataclass
class TabGroup:
    """A named group of related browser tabs."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:6])
    name: str = "default"
    tabs: list[dict[str, str]] = field(default_factory=list)  # [{id, url, title}]
    created_at: float = field(default_factory=time.time)


class BrowserSession:
    """A user's persistent browser session with tab groups.

    Profile data (cookies, localStorage) persists to disk so
    authentication survives across conversations.
    """

    def __init__(
        self,
        user_id: str,
        profile_dir: Path,
        config: SessionConfig,
    ) -> None:
        self.user_id = user_id
        self.profile_dir = profile_dir
        self.config = config
        self._engine: BrowserEngine | None = None
        self._tab_groups: dict[str, TabGroup] = {"default": TabGroup(name="default")}
        self._page_to_group: dict[str, str] = {}  # page_id → group_name
        self._meta_file = profile_dir / "session_meta.json"
        self._load_meta()

    def _load_meta(self) -> None:
        if self._meta_file.exists():
            try:
                data = json.loads(self._meta_file.read_text())
                for g in data.get("groups", []):
                    self._tab_groups[g["name"]] = TabGroup(
                        id=g.get("id", ""),
                        name=g["name"],
                        tabs=g.get("tabs", []),
                        created_at=g.get("created_at", time.time()),
                    )
            except Exception:
                pass

    def _save_meta(self) -> None:
        data = {
            "user_id": self.user_id,
            "groups": [
                {
                    "id": g.id, "name": g.name,
                    "tabs": g.tabs, "created_at": g.created_at,
                }
                for g in self._tab_groups.values()
            ],
            "updated_at": time.time(),
        }
        self._meta_file.parent.mkdir(parents=True, exist_ok=True)
        self._meta_file.write_text(json.dumps(data, indent=2))

    async def _ensure_engine(self) -> BrowserEngine:
        """Start the browser engine if not running."""
        if self._engine and self._engine.alive:
            return self._engine

        engine_config = EngineConfig(
            headless=self.config.headless,
            user_data_dir=str(self.profile_dir / "chromium_data") if self.config.persist_cookies else "",
            block_resources=[],  # don't block in session mode — user may need full pages
            stealth_mode=True,
        )
        self._engine = BrowserEngine(config=engine_config)
        await self._engine.start()
        return self._engine

    # -- tab management -----------------------------------------------------

    async def open_tab(self, url: str, group: str = "default") -> PageHandle:
        """Open a new tab in a tab group."""
        engine = await self._ensure_engine()

        # Ensure group exists
        if group not in self._tab_groups:
            if len(self._tab_groups) >= self.config.max_groups:
                # Remove oldest empty group
                oldest = min(
                    (g for g in self._tab_groups.values() if not g.tabs),
                    key=lambda g: g.created_at,
                    default=None,
                )
                if oldest:
                    del self._tab_groups[oldest.name]
            self._tab_groups[group] = TabGroup(name=group)

        tab_group = self._tab_groups[group]

        # Enforce tab limit per group
        if len(tab_group.tabs) >= self.config.max_tabs_per_group:
            oldest_tab = tab_group.tabs[0]
            await engine.close_page(oldest_tab["id"])
            tab_group.tabs.pop(0)

        handle = await engine.new_page(url)
        tab_group.tabs.append({
            "id": handle.id,
            "url": handle.url,
            "title": handle.title,
        })
        self._page_to_group[handle.id] = group
        self._save_meta()

        return handle

    async def close_tab(self, page_id: str) -> bool:
        """Close a specific tab."""
        if not self._engine:
            return False
        group_name = self._page_to_group.pop(page_id, "")
        if group_name and group_name in self._tab_groups:
            self._tab_groups[group_name].tabs = [
                t for t in self._tab_groups[group_name].tabs if t["id"] != page_id
            ]
        result = await self._engine.close_page(page_id)
        self._save_meta()
        return result

    async def close_group(self, group_name: str) -> int:
        """Close all tabs in a group."""
        group = self._tab_groups.get(group_name)
        if not group:
            return 0
        closed = 0
        for tab in list(group.tabs):
            if self._engine:
                await self._engine.close_page(tab["id"])
            self._page_to_group.pop(tab["id"], None)
            closed += 1
        group.tabs.clear()
        self._save_meta()
        return closed

    # -- session lifecycle --------------------------------------------------

    async def save(self) -> None:
        """Persist session state (cookies saved automatically via persistent context)."""
        # Update tab metadata
        if self._engine:
            for group in self._tab_groups.values():
                for tab in group.tabs:
                    handle = self._engine.get_page(tab["id"])
                    if handle:
                        tab["url"] = handle.url
                        tab["title"] = handle.title
        self._save_meta()

    async def close(self) -> None:
        """Close the browser but keep the profile on disk."""
        if self._engine:
            await self._engine.stop()
            self._engine = None
        self._save_meta()
        log.info("Session closed for %s (profile preserved)", self.user_id)

    async def destroy(self) -> None:
        """Close the browser AND delete the profile from disk."""
        await self.close()
        if self.profile_dir.exists():
            shutil.rmtree(self.profile_dir, ignore_errors=True)
        log.info("Session destroyed for %s", self.user_id)

    # -- queries ------------------------------------------------------------

    def list_groups(self) -> list[dict[str, Any]]:
        return [
            {
                "name": g.name,
                "tab_count": len(g.tabs),
                "tabs": [{"id": t["id"], "url": t.get("url", ""), "title": t.get("title", "")} for t in g.tabs],
            }
            for g in self._tab_groups.values()
        ]

    def get_page(self, page_id: str) -> PageHandle | None:
        if self._engine:
            return self._engine.get_page(page_id)
        return None

    @property
    def stats(self) -> dict[str, Any]:
        total_tabs = sum(len(g.tabs) for g in self._tab_groups.values())
        return {
            "user_id": self.user_id,
            "profile_dir": str(self.profile_dir),
            "groups": len(self._tab_groups),
            "total_tabs": total_tabs,
            "engine_alive": self._engine.alive if self._engine else False,
            "persistent_cookies": self.config.persist_cookies,
        }


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class SessionManager:
    """Manages browser sessions across users.

    Each user gets an isolated Chromium profile directory. Sessions
    persist across conversations — login once, stay logged in.
    """

    def __init__(self, config: SessionConfig | None = None) -> None:
        self.config = config or SessionConfig()
        self._base_dir = Path(
            self.config.base_dir or (Path.home() / ".horizon" / "browser_profiles")
        )
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, BrowserSession] = {}

    async def get_or_create(self, user_id: str) -> BrowserSession:
        """Get an existing session or create a new one."""
        if user_id in self._sessions:
            return self._sessions[user_id]

        profile_dir = self._base_dir / user_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        session = BrowserSession(user_id, profile_dir, self.config)
        self._sessions[user_id] = session
        return session

    async def close_session(self, user_id: str) -> bool:
        session = self._sessions.pop(user_id, None)
        if session:
            await session.close()
            return True
        return False

    async def destroy_session(self, user_id: str) -> bool:
        session = self._sessions.pop(user_id, None)
        if session:
            await session.destroy()
            return True
        return False

    async def shutdown_all(self) -> int:
        count = len(self._sessions)
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        return count

    def list_sessions(self) -> list[dict[str, Any]]:
        return [s.stats for s in self._sessions.values()]

    async def cleanup_stale(self, max_age_hours: int = 0) -> int:
        """Remove profile directories older than max_age_hours."""
        max_age = max_age_hours or self.config.session_timeout_hours
        cutoff = time.time() - max_age * 3600
        removed = 0
        for user_dir in self._base_dir.iterdir():
            if user_dir.is_dir():
                meta = user_dir / "session_meta.json"
                if meta.exists() and meta.stat().st_mtime < cutoff:
                    shutil.rmtree(user_dir, ignore_errors=True)
                    self._sessions.pop(user_dir.name, None)
                    removed += 1
        return removed
