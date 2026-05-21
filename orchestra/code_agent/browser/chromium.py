"""Chromium browser controller via Playwright + CDP.

Connects to Chrome/Edge/Microsoft Edge for:
- Page navigation and content extraction
- Screenshot capture (full page or viewport)
- JavaScript execution
- Form filling and clicking
- Console log monitoring
- Network request interception
- PDF generation
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChromiumTab:
    id: str
    url: str = ""
    title: str = ""
    content: str = ""
    screenshot: str = ""  # base64 PNG
    console_logs: list[str] = field(default_factory=list)
    network_requests: list[dict] = field(default_factory=list)


@dataclass
class ChromiumResult:
    success: bool
    data: ChromiumTab | None = None
    error: str = ""
    elapsed_ms: int = 0


class ChromiumController:
    """Controls Chromium-based browsers via Playwright.

    Launch headless or connect to an existing instance via CDP.
    Supports Chrome, Edge, and any Chromium-based browser.
    """

    def __init__(self, headless: bool = True, browser_path: str | None = None,
                 cdp_url: str | None = None, user_data_dir: str | None = None):
        self.headless = headless
        self.browser_path = browser_path or self._find_browser()
        self.cdp_url = cdp_url
        self.user_data_dir = user_data_dir
        self._browser = None
        self._context = None
        self._page = None
        self._tabs: dict[str, ChromiumTab] = {}
        self.logger = logging.getLogger("orchestra.chromium")

    def _find_browser(self) -> str:
        """Find Chrome/Edge/Chromium on the system."""
        candidates = [
            os.environ.get("CHROME_PATH", ""),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/microsoft-edge",
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return "chrome"

    async def launch(self) -> bool:
        """Launch or connect to browser."""
        if self._browser:
            return True
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright not installed. Install with: pip install playwright && playwright install chromium")
            return False

        try:
            p = await async_playwright().start()
            if self.cdp_url:
                self._browser = await p.chromium.connect_over_cdp(self.cdp_url)
            else:
                launch_args = [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ]
                if self.user_data_dir:
                    launch_args.append(f"--user-data-dir={self.user_data_dir}")
                self._browser = await p.chromium.launch(
                    headless=self.headless,
                    executable_path=self.browser_path if self.browser_path != "chrome" else None,
                    args=launch_args,
                )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )
            self._page = await self._context.new_page()
            self._setup_listeners(self._page)
            self.logger.info("Browser launched: %s (headless=%s)", self.browser_path, self.headless)
            return True
        except Exception as e:
            self.logger.error("Browser launch failed: %s", e)
            return False

    def _setup_listeners(self, page) -> None:
        try:
            page.on("console", lambda msg: self._on_console(msg))
            page.on("response", lambda resp: self._on_response(resp))
        except Exception:
            pass

    def _on_console(self, msg) -> None:
        tab_id = getattr(self._page, "_id", "default")
        tab = self._tabs.get(tab_id)
        if tab:
            tab.console_logs.append(f"[{msg.type}] {msg.text}")

    def _on_response(self, resp) -> None:
        tab_id = getattr(self._page, "_id", "default")
        tab = self._tabs.get(tab_id)
        if tab and len(tab.network_requests) < 50:
            tab.network_requests.append({
                "url": resp.url[:200],
                "status": resp.status,
                "type": resp.request.resource_type,
            })

    async def navigate(self, url: str, timeout: float = 30) -> ChromiumResult:
        start = time.time()
        if not self._page:
            if not await self.launch():
                return ChromiumResult(success=False, error="Failed to launch browser")
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await self._page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            await asyncio.sleep(0.5)
            content = await self._page.content()
            title = await self._page.title()
            tab = ChromiumTab(
                id=str(len(self._tabs) + 1),
                url=self._page.url,
                title=title,
                content=content[:100_000],
            )
            self._tabs[tab.id] = tab
            return ChromiumResult(success=True, data=tab, elapsed_ms=int((time.time() - start) * 1000))
        except Exception as e:
            return ChromiumResult(success=False, error=str(e), elapsed_ms=int((time.time() - start) * 1000))

    async def screenshot(self) -> ChromiumResult:
        """Capture full-page screenshot as base64."""
        if not self._page:
            return ChromiumResult(success=False, error="No page open")
        try:
            await self._page.screenshot(full_page=True)
            # Playwright doesn't support in-memory base64 directly, use temp file
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            await self._page.screenshot(path=tmp.name, full_page=True)
            with open(tmp.name, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            os.unlink(tmp.name)
            tab_id = str(len(self._tabs))
            tab = ChromiumTab(id=tab_id, screenshot=b64)
            self._tabs[tab_id] = tab
            return ChromiumResult(success=True, data=tab)
        except Exception as e:
            return ChromiumResult(success=False, error=str(e))

    async def evaluate(self, script: str) -> ChromiumResult:
        """Execute JavaScript in the page context."""
        if not self._page:
            return ChromiumResult(success=False, error="No page open")
        try:
            result = await self._page.evaluate(script)
            return ChromiumResult(success=True, data=ChromiumTab(
                id="eval", content=str(result)[:5000],
            ))
        except Exception as e:
            return ChromiumResult(success=False, error=str(e))

    async def click(self, selector: str) -> ChromiumResult:
        """Click an element by CSS selector."""
        if not self._page:
            return ChromiumResult(success=False, error="No page open")
        try:
            await self._page.click(selector)
            await asyncio.sleep(0.3)
            return ChromiumResult(success=True, data=ChromiumTab(id="click"))
        except Exception as e:
            return ChromiumResult(success=False, error=str(e))

    async def fill(self, selector: str, value: str) -> ChromiumResult:
        """Fill a form field by CSS selector."""
        if not self._page:
            return ChromiumResult(success=False, error="No page open")
        try:
            await self._page.fill(selector, value)
            return ChromiumResult(success=True, data=ChromiumTab(id="fill"))
        except Exception as e:
            return ChromiumResult(success=False, error=str(e))

    async def pdf(self, path: str = "") -> ChromiumResult:
        """Generate PDF of current page."""
        if not self._page:
            return ChromiumResult(success=False, error="No page open")
        try:
            out = path or f"browser-{int(time.time())}.pdf"
            await self._page.pdf(path=out, format="A4")
            return ChromiumResult(success=True, data=ChromiumTab(id="pdf", content=out))
        except Exception as e:
            return ChromiumResult(success=False, error=str(e))

    async def extract_text(self) -> str:
        """Extract visible text from page."""
        if not self._page:
            return ""
        try:
            text = await self._page.evaluate("document.body.innerText")
            return text[:20000]
        except Exception:
            return ""

    async def close(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page = None
