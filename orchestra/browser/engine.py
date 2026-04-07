"""Chromium Browser Engine — persistent browser pool with page management.

Manages a pool of Chromium instances via Playwright. Each instance
can hold multiple pages (tabs), reuse sessions, and persist state
across agent interactions.

Unlike the simple browser tool in tools/browser.py, this is a full
browser infrastructure layer:
- Browser pool with configurable concurrency
- Persistent contexts with cookie/localStorage state
- Page lifecycle management (create, navigate, close)
- Resource interception (block ads/trackers for speed)
- Automatic cleanup and health monitoring
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["BrowserEngine", "BrowserPool", "EngineConfig", "PageHandle"]

log = logging.getLogger("orchestra.browser.engine")


@dataclass
class EngineConfig:
    headless: bool = True
    max_browsers: int = 5
    max_pages_per_browser: int = 10
    default_timeout: int = 30_000       # ms
    viewport_width: int = 1280
    viewport_height: int = 800
    user_data_dir: str = ""             # persistent profile directory
    block_resources: list[str] = field(default_factory=lambda: [
        "image", "media", "font",       # block for speed (enable per-task)
    ])
    stealth_mode: bool = True           # anti-detection measures
    proxy: str = ""                     # proxy URL


@dataclass
class PageHandle:
    """Handle to a browser page (tab)."""
    id: str
    browser_id: str
    url: str = ""
    title: str = ""
    created_at: float = field(default_factory=time.time)
    _page: Any = field(default=None, repr=False)


class BrowserEngine:
    """Manages a single Chromium instance with multiple pages."""

    def __init__(self, engine_id: str = "", config: EngineConfig | None = None) -> None:
        self.id = engine_id or str(uuid.uuid4())[:8]
        self.config = config or EngineConfig()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._pages: dict[str, PageHandle] = {}
        self._alive = False

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def page_count(self) -> int:
        return len(self._pages)

    async def start(self) -> None:
        """Launch the Chromium instance."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError("pip install playwright && playwright install chromium")

        self._playwright = await async_playwright().start()

        launch_args = ["--disable-blink-features=AutomationControlled"] if self.config.stealth_mode else []
        if self.config.proxy:
            launch_args.extend(["--proxy-server=" + self.config.proxy])

        if self.config.user_data_dir:
            # Persistent context — cookies and localStorage survive restarts
            Path(self.config.user_data_dir).mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                self.config.user_data_dir,
                headless=self.config.headless,
                viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
                args=launch_args,
            )
            self._browser = None  # persistent context IS the browser
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless,
                args=launch_args,
            )
            self._context = await self._browser.new_context(
                viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
            )

        # Resource blocking for speed
        if self.config.block_resources:
            await self._context.route("**/*", self._route_handler)

        self._alive = True
        log.info("Browser engine %s started (headless=%s)", self.id, self.config.headless)

    async def _route_handler(self, route: Any) -> None:
        """Block specified resource types for performance."""
        if route.request.resource_type in self.config.block_resources:
            await route.abort()
        else:
            await route.continue_()

    async def stop(self) -> None:
        """Close all pages and the browser."""
        for page_handle in list(self._pages.values()):
            await self.close_page(page_handle.id)
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._alive = False
        log.info("Browser engine %s stopped", self.id)

    # -- page management ----------------------------------------------------

    async def new_page(self, url: str = "") -> PageHandle:
        """Create a new page (tab) in this browser."""
        if self.page_count >= self.config.max_pages_per_browser:
            # Close the oldest page
            oldest = min(self._pages.values(), key=lambda p: p.created_at)
            await self.close_page(oldest.id)

        page = await self._context.new_page()
        page.set_default_timeout(self.config.default_timeout)

        handle = PageHandle(
            id=str(uuid.uuid4())[:8],
            browser_id=self.id,
            _page=page,
        )

        if url:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded")
                handle.url = page.url
                handle.title = await page.title()
            except Exception as exc:
                log.warning("Navigation failed: %s", exc)

        self._pages[handle.id] = handle
        return handle

    async def close_page(self, page_id: str) -> bool:
        handle = self._pages.pop(page_id, None)
        if handle and handle._page:
            try:
                await handle._page.close()
            except Exception:
                pass
            return True
        return False

    def get_page(self, page_id: str) -> PageHandle | None:
        return self._pages.get(page_id)

    async def navigate(self, page_id: str, url: str) -> dict[str, Any]:
        """Navigate an existing page to a new URL."""
        handle = self._pages.get(page_id)
        if not handle or not handle._page:
            return {"error": f"Page {page_id} not found"}
        try:
            resp = await handle._page.goto(url, wait_until="domcontentloaded")
            handle.url = handle._page.url
            handle.title = await handle._page.title()
            return {"url": handle.url, "title": handle.title, "status": resp.status if resp else 0}
        except Exception as exc:
            return {"error": str(exc)}

    async def execute_on_page(self, page_id: str, action: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an action on a specific page."""
        handle = self._pages.get(page_id)
        if not handle or not handle._page:
            return {"error": f"Page {page_id} not found"}

        page = handle._page
        try:
            if action == "click":
                await page.click(kwargs.get("selector", ""))
                return {"clicked": True}
            elif action == "fill":
                await page.fill(kwargs.get("selector", ""), kwargs.get("value", ""))
                return {"filled": True}
            elif action == "type":
                await page.type(kwargs.get("selector", ""), kwargs.get("value", ""))
                return {"typed": True}
            elif action == "press":
                await page.press(kwargs.get("selector", "body"), kwargs.get("key", "Enter"))
                return {"pressed": True}
            elif action == "select":
                await page.select_option(kwargs.get("selector", ""), kwargs.get("value", ""))
                return {"selected": True}
            elif action == "scroll":
                await page.evaluate(f"window.scrollBy(0, {kwargs.get('pixels', 500)})")
                return {"scrolled": True}
            elif action == "wait":
                await page.wait_for_selector(kwargs.get("selector", ""), timeout=kwargs.get("timeout", 10000))
                return {"found": True}
            elif action == "screenshot":
                path = kwargs.get("path", f"/tmp/horizon_workspace/screenshot_{page_id}.png")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=path, full_page=kwargs.get("full_page", True))
                return {"path": path}
            elif action == "pdf":
                path = kwargs.get("path", f"/tmp/horizon_workspace/page_{page_id}.pdf")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                await page.pdf(path=path)
                return {"path": path}
            elif action == "evaluate":
                result = await page.evaluate(kwargs.get("expression", "document.title"))
                return {"result": result}
            elif action == "content":
                html = await page.content()
                return {"html_length": len(html), "html": html[:100_000]}
            elif action == "text":
                text = await page.text_content("body") or ""
                return {"text_length": len(text), "text": text[:50_000]}
            elif action == "title":
                return {"title": await page.title(), "url": page.url}
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}

    def list_pages(self) -> list[dict[str, Any]]:
        return [
            {"id": h.id, "url": h.url, "title": h.title, "age": round(time.time() - h.created_at)}
            for h in self._pages.values()
        ]

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "id": self.id, "alive": self._alive,
            "pages": self.page_count,
            "headless": self.config.headless,
            "has_persistent_profile": bool(self.config.user_data_dir),
        }


# ---------------------------------------------------------------------------
# Browser pool
# ---------------------------------------------------------------------------

class BrowserPool:
    """Pool of BrowserEngine instances with load balancing.

    Distributes pages across multiple Chromium instances for
    parallelism and fault isolation.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self._engines: dict[str, BrowserEngine] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str = "") -> BrowserEngine:
        """Get a browser engine, creating one if needed."""
        async with self._lock:
            # Find an engine with capacity
            for engine in self._engines.values():
                if engine.alive and engine.page_count < self.config.max_pages_per_browser:
                    return engine

            # Create a new one if under limit
            if len(self._engines) < self.config.max_browsers:
                cfg = EngineConfig(
                    headless=self.config.headless,
                    max_pages_per_browser=self.config.max_pages_per_browser,
                    viewport_width=self.config.viewport_width,
                    viewport_height=self.config.viewport_height,
                    user_data_dir=(
                        f"{self.config.user_data_dir}/{user_id}" if self.config.user_data_dir and user_id else ""
                    ),
                    block_resources=self.config.block_resources,
                    stealth_mode=self.config.stealth_mode,
                )
                engine = BrowserEngine(config=cfg)
                await engine.start()
                self._engines[engine.id] = engine
                return engine

            # All engines full — return the one with fewest pages
            return min(self._engines.values(), key=lambda e: e.page_count)

    async def release(self, engine_id: str) -> None:
        """Release a browser engine (close if empty)."""
        engine = self._engines.get(engine_id)
        if engine and engine.page_count == 0:
            await engine.stop()
            del self._engines[engine_id]

    async def shutdown(self) -> None:
        """Stop all browser engines."""
        for engine in list(self._engines.values()):
            await engine.stop()
        self._engines.clear()
        log.info("Browser pool shut down")

    def stats(self) -> dict[str, Any]:
        return {
            "engines": len(self._engines),
            "total_pages": sum(e.page_count for e in self._engines.values()),
            "max_browsers": self.config.max_browsers,
            "engines_detail": [e.stats for e in self._engines.values()],
        }
