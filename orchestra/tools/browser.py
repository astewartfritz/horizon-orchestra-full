"""Horizon Orchestra — Playwright Browser Automation.

Real browser automation replacing the stub in agent_loop.py.
Supports navigation, clicking, form filling, text extraction,
screenshots, and JavaScript execution.

Requires: pip install playwright && playwright install chromium

Usage::

    from orchestra.tools.browser import BrowserTool
    browser = BrowserTool()
    await browser.start()
    result = await browser.navigate("https://example.com")
    text = await browser.extract("h1")
    await browser.screenshot("/tmp/page.png")
    await browser.stop()
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["BrowserTool", "register_browser_tools"]

log = logging.getLogger("orchestra.tools.browser")


@dataclass
class BrowserConfig:
    headless: bool = True
    timeout: int = 30_000          # ms
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 HorizonOrchestra/1.0"
    )


class BrowserTool:
    """Playwright-backed browser automation."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def start(self) -> None:
        """Launch the browser."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Playwright is required. Install with:\n"
                "  pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
        )
        self._context = await self._browser.new_context(
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            user_agent=self.config.user_agent,
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.timeout)
        log.info("Browser started (headless=%s)", self.config.headless)

    async def stop(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    async def _ensure_page(self) -> Any:
        if self._page is None:
            await self.start()
        return self._page

    # -- actions ------------------------------------------------------------

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        """Navigate to a URL."""
        page = await self._ensure_page()
        try:
            resp = await page.goto(url, wait_until=wait_until)
            status = resp.status if resp else 0
            title = await page.title()
            return {
                "url": page.url,
                "status": status,
                "title": title,
            }
        except Exception as exc:
            return {"error": str(exc), "url": url}

    async def click(self, selector: str) -> dict[str, Any]:
        """Click an element."""
        page = await self._ensure_page()
        try:
            await page.click(selector)
            await page.wait_for_load_state("domcontentloaded")
            return {"clicked": selector, "url": page.url}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def fill(self, selector: str, value: str) -> dict[str, Any]:
        """Fill a form field."""
        page = await self._ensure_page()
        try:
            await page.fill(selector, value)
            return {"filled": selector, "value_length": len(value)}
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def extract(self, selector: str = "body") -> dict[str, Any]:
        """Extract text content from elements matching a selector."""
        page = await self._ensure_page()
        try:
            elements = await page.query_selector_all(selector)
            texts = []
            for el in elements[:20]:  # limit to 20 elements
                text = await el.text_content()
                if text and text.strip():
                    texts.append(text.strip())
            return {
                "selector": selector,
                "count": len(texts),
                "texts": texts,
            }
        except Exception as exc:
            return {"error": str(exc), "selector": selector}

    async def screenshot(self, path: str = "") -> dict[str, Any]:
        """Take a screenshot. Returns path or base64 if no path given."""
        page = await self._ensure_page()
        try:
            if path:
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=path, full_page=True)
                return {"path": path, "size": p.stat().st_size}
            else:
                data = await page.screenshot(full_page=True)
                b64 = base64.b64encode(data).decode("ascii")
                return {"base64_length": len(b64), "format": "png"}
        except Exception as exc:
            return {"error": str(exc)}

    async def evaluate(self, js_code: str) -> dict[str, Any]:
        """Execute JavaScript in the page context."""
        page = await self._ensure_page()
        try:
            result = await page.evaluate(js_code)
            return {"result": result}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_page_content(self, max_length: int = 50_000) -> dict[str, Any]:
        """Get the full page text content."""
        page = await self._ensure_page()
        try:
            content = await page.text_content("body") or ""
            return {
                "url": page.url,
                "title": await page.title(),
                "length": len(content),
                "content": content[:max_length],
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def wait_for(self, selector: str, timeout: int = 10_000) -> dict[str, Any]:
        """Wait for an element to appear."""
        page = await self._ensure_page()
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return {"found": True, "selector": selector}
        except Exception as exc:
            return {"found": False, "selector": selector, "error": str(exc)}


# ---------------------------------------------------------------------------
# Singleton instance for tool handlers
# ---------------------------------------------------------------------------

_browser: BrowserTool | None = None


async def _get_browser() -> BrowserTool:
    global _browser
    if _browser is None:
        _browser = BrowserTool()
    return _browser


# ---------------------------------------------------------------------------
# Tool handler (replaces the stub in agent_loop.py)
# ---------------------------------------------------------------------------

async def tool_browser_action(
    url: str,
    action: str = "navigate",
    selector: str = "",
    value: str = "",
) -> str:
    """Full browser automation handler for the agent tool registry."""
    browser = await _get_browser()

    actions = {
        "navigate": lambda: browser.navigate(url),
        "click": lambda: browser.click(selector),
        "fill": lambda: browser.fill(selector, value),
        "extract": lambda: browser.extract(selector or "body"),
        "screenshot": lambda: browser.screenshot(value or ""),
        "evaluate": lambda: browser.evaluate(value),
        "content": lambda: browser.get_page_content(),
        "wait": lambda: browser.wait_for(selector),
    }

    handler = actions.get(action)
    if not handler:
        return json.dumps({"error": f"Unknown action: {action}. Available: {list(actions)}"})

    # Navigate first if URL provided and action isn't navigate itself
    if action != "navigate" and url:
        current_page = browser._page
        current_url = current_page.url if current_page else ""
        if current_url != url:
            await browser.navigate(url)

    result = await handler()
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_browser_tools(tool_registry: Any) -> None:
    """Replace the browser_action stub with the real Playwright implementation.

    Call this after create_default_tools() to upgrade the browser tool.
    """
    # Remove the stub if it exists
    if hasattr(tool_registry, "_tools") and "browser_action" in tool_registry._tools:
        del tool_registry._tools["browser_action"]

    tool_registry.register(
        name="browser_action",
        description=(
            "Perform browser automation using Playwright. "
            "Actions: navigate, click, fill, extract, screenshot, evaluate, content, wait. "
            "Requires a URL. Use 'selector' for click/fill/extract/wait. "
            "Use 'value' for fill text or JS code for evaluate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL"},
                "action": {
                    "type": "string",
                    "enum": ["navigate", "click", "fill", "extract", "screenshot", "evaluate", "content", "wait"],
                    "description": "Browser action to perform",
                },
                "selector": {"type": "string", "description": "CSS selector for click/fill/extract/wait"},
                "value": {"type": "string", "description": "Value for fill, path for screenshot, or JS code for evaluate"},
            },
            "required": ["url", "action"],
        },
        handler=tool_browser_action,
    )
