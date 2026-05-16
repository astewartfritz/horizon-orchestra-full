"""Horizon Orchestra — Chromium Browser Connector.

Production-grade browser automation via Playwright, supporting:
- Local headless/headed Chromium
- Remote Chrome DevTools Protocol (Docker Playwright service, Browserless)
- Per-session context isolation
- Stealth mode (hides automation signals)
- Full page capture (screenshot, PDF, HTML, accessibility tree)
- DOM interaction (click, type, select, drag, hover, scroll)
- Multi-tab management
- Request interception (block ads/tracking, mock responses)
- Cookie/session management
- File upload and download
- JavaScript evaluation
- Network monitoring and HAR capture

Usage::

    from orchestra.browser_connector import BrowserConnector, BrowserSession

    # As a Connector (plugs into ConnectorRegistry)
    conn = BrowserConnector()
    await conn.connect({"mode": "local", "headless": "true"})
    result = await conn.execute("navigate", {"url": "https://example.com"})

    # As a standalone session
    async with BrowserSession() as browser:
        await browser.navigate("https://example.com")
        html = await browser.get_content()
        await browser.click("button#submit")
        screenshot = await browser.screenshot()
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    from playwright.async_api import (
        async_playwright,
        Browser,
        BrowserContext,
        Page,
        Playwright,
        Request,
        Route,
    )
    HAS_PLAYWRIGHT = True
except ImportError:
    async_playwright = None  # type: ignore[assignment]
    Browser = None  # type: ignore[assignment]
    BrowserContext = None  # type: ignore[assignment]
    Page = None  # type: ignore[assignment]
    Playwright = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    Route = None  # type: ignore[assignment]
    HAS_PLAYWRIGHT = False

from .arch_e import Connector

__all__ = [
    "BrowserConfig",
    "PageState",
    "ClickResult",
    "ExtractResult",
    "BrowserSession",
    "BrowserConnector",
    "AD_DOMAINS",
    "CHROMIUM_ARGS",
    "STEALTH_SCRIPT",
]

log = logging.getLogger("orchestra.browser_connector")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STEALTH_SCRIPT = """
() => {
    // Mask webdriver
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    // Mask plugins length
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    // Mask languages
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    // Remove automation-specific chrome properties
    window.chrome = {runtime: {}};
    // Mask permission query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : originalQuery(parameters)
    );
}
"""

AD_DOMAINS: frozenset[str] = frozenset([
    "googletagmanager.com", "google-analytics.com", "doubleclick.net",
    "googlesyndication.com", "amazon-adsystem.com", "facebook.com/tr",
    "connect.facebook.net", "analytics.twitter.com", "hotjar.com",
    "fullstory.com", "mixpanel.com", "segment.io", "segment.com",
    "intercom.io", "crisp.chat", "drift.com",
])

CHROMIUM_ARGS: list[str] = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--no-zygote",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--window-size=1280,720",
    "--disable-extensions",
    "--disable-plugins-discovery",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BrowserConfig:
    """Configuration for a BrowserSession or BrowserConnector."""

    mode: str = "local"                        # "local", "remote_cdp", "browserless"
    headless: bool = True
    remote_url: str = ""                       # ws:// URL for remote CDP
    user_agent: str = ""                       # custom UA; empty = Playwright default
    viewport_width: int = 1280
    viewport_height: int = 720
    locale: str = "en-US"
    timezone: str = "America/Chicago"
    stealth: bool = True                       # mask automation signals
    block_ads: bool = True                     # abort requests to ad/tracker domains
    block_resources: list[str] = field(
        default_factory=lambda: ["font"]
    )                                          # resource types to block for speed
    slow_mo: int = 0                           # ms delay between actions (0 = off)
    timeout: int = 30_000                      # default action timeout (ms)
    download_dir: str = "/tmp/orchestra_browser_downloads"
    proxy: str = ""                            # http://user:pass@host:port


@dataclass
class PageState:
    """Snapshot of the current page state."""

    url: str = ""
    title: str = ""
    content_length: int = 0
    tab_id: str = ""
    load_state: str = ""                       # "loading", "domcontentloaded", "networkidle"


@dataclass
class ClickResult:
    """Result of a click action."""

    success: bool
    selector: str
    element_text: str = ""
    new_url: str = ""


@dataclass
class ExtractResult:
    """Result of an extraction action."""

    success: bool
    selector: str
    count: int = 0
    items: list[dict] = field(default_factory=list)  # text, href, src, etc.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_ad_domain(url: str) -> bool:
    """Return True if *url* belongs to a known ad/tracker domain."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in AD_DOMAINS)
    except Exception:
        return False


def _normalize_selector(selector: str) -> str | None:
    """Return the selector unchanged; natural-language selectors are handled
    separately by the callers via Playwright's get_by_text / get_by_role.

    Returns ``None`` when the caller should fall back to text-based lookup.
    """
    # Heuristic: if it contains a space but no CSS combinators it is likely
    # a human-readable label rather than a CSS selector.
    css_indicators = re.compile(r"[#.\[\]:>+~]")
    if " " in selector and not css_indicators.search(selector):
        return None
    return selector


async def _page_state(page: Any, tab_id: str = "") -> PageState:
    """Capture a PageState from a live Playwright page."""
    try:
        title = await page.title()
        url = page.url
        content = await page.content()
        return PageState(
            url=url,
            title=title,
            content_length=len(content),
            tab_id=tab_id,
            load_state="networkidle",
        )
    except Exception as exc:
        log.debug("_page_state error: %s", exc)
        return PageState(url=getattr(page, "url", ""), tab_id=tab_id)


# ---------------------------------------------------------------------------
# BrowserSession — low-level direct API
# ---------------------------------------------------------------------------

class BrowserSession:
    """Low-level browser session with direct Playwright access.

    Use as an async context manager or call :meth:`start` / :meth:`close`
    manually.  Each session gets an isolated browser context with its own
    cookies, local storage, and tabs.

    Example::

        async with BrowserSession() as browser:
            await browser.navigate("https://example.com")
            html = await browser.get_content()
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config: BrowserConfig = config or BrowserConfig()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None                  # "active" page / tab
        self._tabs: dict[str, Any] = {}         # tab_id -> Page
        self._active_tab_id: str = ""
        self._network_log: list[dict] = []
        self._running: bool = False

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Launch or connect to Chromium and open an isolated context."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError(
                "playwright is required for BrowserSession. "
                "Install with: pip install playwright && playwright install chromium"
            )

        log.info(
            "Starting BrowserSession mode=%s headless=%s stealth=%s",
            self.config.mode,
            self.config.headless,
            self.config.stealth,
        )

        self._playwright = await async_playwright().start()

        # ── Connect / launch ────────────────────────────────────────────────
        if self.config.mode == "local":
            launch_kwargs: dict[str, Any] = {
                "headless": self.config.headless,
                "args": CHROMIUM_ARGS,
            }
            if self.config.slow_mo:
                launch_kwargs["slow_mo"] = self.config.slow_mo
            if self.config.proxy:
                launch_kwargs["proxy"] = {"server": self.config.proxy}
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        elif self.config.mode in ("remote_cdp", "browserless"):
            remote_url = (
                self.config.remote_url
                or os.environ.get("BROWSER_REMOTE_URL", "")
            )
            if self.config.mode == "browserless":
                token = os.environ.get("BROWSERLESS_TOKEN", "")
                if token and not remote_url:
                    remote_url = f"wss://chrome.browserless.io?token={token}"
            if not remote_url:
                raise RuntimeError(
                    "remote_url must be set for mode='remote_cdp'/'browserless'. "
                    "Set BROWSER_REMOTE_URL environment variable or pass remote_url."
                )
            log.info("Connecting to remote CDP: %s", remote_url)
            self._browser = await self._playwright.chromium.connect_over_cdp(remote_url)

        else:
            raise ValueError(f"Unknown browser mode: {self.config.mode!r}")

        # ── Isolated browser context ─────────────────────────────────────────
        context_kwargs: dict[str, Any] = {
            "viewport": {
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            "locale": self.config.locale,
            "timezone_id": self.config.timezone,
            "accept_downloads": True,
            "downloads_path": self.config.download_dir,
        }
        if self.config.user_agent:
            context_kwargs["user_agent"] = self.config.user_agent
        self._context = await self._browser.new_context(**context_kwargs)

        # ── Stealth init script ──────────────────────────────────────────────
        if self.config.stealth:
            await self._context.add_init_script(STEALTH_SCRIPT)

        # ── Request interception ─────────────────────────────────────────────
        if self.config.block_ads or self.config.block_resources:
            await self._context.route("**/*", self._route_handler)

        # ── Network log ──────────────────────────────────────────────────────
        self._context.on("request", self._on_request)
        self._context.on("response", self._on_response)

        # ── Initial page / tab ───────────────────────────────────────────────
        self._page = await self._context.new_page()
        tab_id = str(uuid.uuid4())[:8]
        self._tabs[tab_id] = self._page
        self._active_tab_id = tab_id

        os.makedirs(self.config.download_dir, exist_ok=True)
        self._running = True
        log.info("BrowserSession started (tab_id=%s)", tab_id)

    async def close(self) -> None:
        """Close the browser session and release all resources."""
        self._running = False
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            log.debug("Error during BrowserSession.close: %s", exc)
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._tabs.clear()
        log.info("BrowserSession closed")

    async def __aenter__(self) -> "BrowserSession":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # -- internal request handling -------------------------------------------

    async def _route_handler(self, route: Any) -> None:
        """Intercept and potentially abort outgoing requests."""
        req = route.request
        rtype = req.resource_type

        # Block by resource type
        if rtype in self.config.block_resources:
            await route.abort()
            return

        # Block ad/tracker domains
        if self.config.block_ads and _is_ad_domain(req.url):
            log.debug("Blocked ad domain: %s", req.url)
            await route.abort()
            return

        await route.continue_()

    def _on_request(self, request: Any) -> None:
        """Log outgoing requests for network monitoring."""
        self._network_log.append({
            "type": "request",
            "url": request.url,
            "method": request.method,
            "resource_type": request.resource_type,
            "timestamp": time.time(),
        })

    def _on_response(self, response: Any) -> None:
        """Log incoming responses for network monitoring."""
        self._network_log.append({
            "type": "response",
            "url": response.url,
            "status": response.status,
            "timestamp": time.time(),
        })

    # -- active page helper --------------------------------------------------

    def _active_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("BrowserSession is not started. Call start() first.")
        return self._page

    # ── Navigation ──────────────────────────────────────────────────────────

    async def navigate(self, url: str, wait_until: str = "networkidle") -> PageState:
        """Navigate to *url* and wait for the page to load.

        Args:
            url: Target URL (must include scheme, e.g. ``https://``).
            wait_until: Load event — ``"load"``, ``"domcontentloaded"``,
                        ``"networkidle"`` (default).

        Returns:
            :class:`PageState` snapshot after navigation.
        """
        page = self._active_page()
        log.info("Navigate → %s (wait_until=%s)", url, wait_until)
        try:
            await page.goto(
                url,
                wait_until=wait_until,
                timeout=self.config.timeout,
            )
        except Exception as exc:
            log.warning("navigate error (url=%s): %s", url, exc)
        return await _page_state(page, self._active_tab_id)

    async def go_back(self) -> PageState:
        """Navigate the active tab backwards in history."""
        page = self._active_page()
        await page.go_back(timeout=self.config.timeout)
        return await _page_state(page, self._active_tab_id)

    async def go_forward(self) -> PageState:
        """Navigate the active tab forward in history."""
        page = self._active_page()
        await page.go_forward(timeout=self.config.timeout)
        return await _page_state(page, self._active_tab_id)

    async def reload(self) -> PageState:
        """Reload the active tab."""
        page = self._active_page()
        await page.reload(timeout=self.config.timeout)
        return await _page_state(page, self._active_tab_id)

    async def wait_for_load(
        self,
        state: str = "networkidle",
        timeout: int = 30_000,
    ) -> None:
        """Wait until the page reaches *state*."""
        page = self._active_page()
        await page.wait_for_load_state(state, timeout=timeout or self.config.timeout)

    # ── Content ─────────────────────────────────────────────────────────────

    async def get_content(self) -> str:
        """Return the full outer HTML of the active page."""
        return await self._active_page().content()

    async def get_text(self) -> str:
        """Return visible text content with excessive whitespace stripped."""
        page = self._active_page()
        text: str = await page.evaluate("document.body.innerText")
        # Collapse runs of blank lines to a single newline
        text = re.sub(r"\n{3,}", "\n\n", text.strip())
        return text

    async def get_title(self) -> str:
        """Return the document title of the active page."""
        return await self._active_page().title()

    async def get_url(self) -> str:
        """Return the current URL of the active page."""
        return self._active_page().url

    async def get_accessibility_tree(self) -> str:
        """Return a simplified, indented accessibility tree as plain text."""
        page = self._active_page()
        snapshot = await page.accessibility.snapshot()
        if snapshot is None:
            return ""
        lines: list[str] = []

        def _walk(node: dict, depth: int = 0) -> None:
            role = node.get("role", "")
            name = node.get("name", "")
            value = node.get("value", "")
            label = f"{role}: {name}" if name else role
            if value:
                label += f" = {value!r}"
            lines.append("  " * depth + label)
            for child in node.get("children", []):
                _walk(child, depth + 1)

        _walk(snapshot)
        return "\n".join(lines)

    async def screenshot(self, full_page: bool = True, path: str = "") -> bytes:
        """Take a screenshot of the active page.

        Args:
            full_page: Capture the entire scrollable page (default ``True``).
            path: If provided, save to this file path in addition to returning bytes.

        Returns:
            Raw PNG bytes.
        """
        page = self._active_page()
        kwargs: dict[str, Any] = {"full_page": full_page}
        if path:
            kwargs["path"] = path
        return await page.screenshot(**kwargs)

    async def pdf(self, path: str = "") -> bytes:
        """Render the active page as a PDF.

        Args:
            path: If provided, also save to this file path.

        Returns:
            Raw PDF bytes.
        """
        page = self._active_page()
        kwargs: dict[str, Any] = {}
        if path:
            kwargs["path"] = path
        return await page.pdf(**kwargs)

    # ── DOM Interaction ──────────────────────────────────────────────────────

    async def click(self, selector: str, timeout: int = 0) -> ClickResult:
        """Click on an element identified by *selector*.

        Args:
            selector: CSS selector, XPath, or plain text label.
            timeout: Override default timeout (ms); 0 = use config default.

        Returns:
            :class:`ClickResult` with success status and post-click URL.
        """
        page = self._active_page()
        t = timeout or self.config.timeout
        elem_text = ""
        try:
            css = _normalize_selector(selector)
            if css is not None:
                locator = page.locator(css).first
            else:
                locator = page.get_by_text(selector, exact=False).first
            elem_text = (await locator.text_content() or "").strip()
            await locator.click(timeout=t)
            new_url = page.url
            log.debug("click(%r) → %s", selector, new_url)
            return ClickResult(
                success=True,
                selector=selector,
                element_text=elem_text,
                new_url=new_url,
            )
        except Exception as exc:
            log.warning("click(%r) failed: %s", selector, exc)
            return ClickResult(success=False, selector=selector, element_text=elem_text)

    async def type_text(
        self,
        selector: str,
        text: str,
        delay: int = 0,
    ) -> bool:
        """Type *text* into the element matching *selector* (keystroke-by-keystroke).

        Args:
            selector: CSS selector or text label.
            text: Characters to type.
            delay: Delay between keystrokes in ms (0 = as fast as possible).

        Returns:
            ``True`` on success.
        """
        page = self._active_page()
        try:
            css = _normalize_selector(selector)
            locator = page.locator(css).first if css else page.get_by_label(selector).first
            await locator.type(text, delay=delay, timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("type_text(%r) failed: %s", selector, exc)
            return False

    async def fill(self, selector: str, value: str) -> bool:
        """Clear the field at *selector* and fill it with *value*.

        Faster than :meth:`type_text` because it sets the field value directly.
        """
        page = self._active_page()
        try:
            css = _normalize_selector(selector)
            locator = page.locator(css).first if css else page.get_by_label(selector).first
            await locator.fill(value, timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("fill(%r) failed: %s", selector, exc)
            return False

    async def select(self, selector: str, value: str) -> bool:
        """Select *value* from a ``<select>`` element at *selector*."""
        page = self._active_page()
        try:
            await page.select_option(selector, value=value, timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("select(%r, %r) failed: %s", selector, value, exc)
            return False

    async def hover(self, selector: str) -> bool:
        """Move the mouse over *selector*."""
        page = self._active_page()
        try:
            css = _normalize_selector(selector)
            locator = page.locator(css).first if css else page.get_by_text(selector, exact=False).first
            await locator.hover(timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("hover(%r) failed: %s", selector, exc)
            return False

    async def scroll_to(
        self,
        selector: str = "",
        x: int = 0,
        y: int = 0,
    ) -> None:
        """Scroll the page to an element or absolute coordinates.

        Args:
            selector: CSS selector to scroll into view; ignored when empty.
            x: Horizontal scroll position (used when *selector* is empty).
            y: Vertical scroll position (used when *selector* is empty).
        """
        page = self._active_page()
        try:
            if selector:
                css = _normalize_selector(selector)
                locator = page.locator(css).first if css else page.get_by_text(selector, exact=False).first
                await locator.scroll_into_view_if_needed(timeout=self.config.timeout)
            else:
                await page.evaluate(f"window.scrollTo({x}, {y})")
        except Exception as exc:
            log.warning("scroll_to(%r, %d, %d) failed: %s", selector, x, y, exc)

    async def drag_and_drop(self, source: str, target: str) -> bool:
        """Drag from *source* and drop onto *target* (both CSS selectors).

        Returns:
            ``True`` on success.
        """
        page = self._active_page()
        try:
            await page.drag_and_drop(source, target, timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("drag_and_drop(%r → %r) failed: %s", source, target, exc)
            return False

    async def press_key(self, key: str) -> None:
        """Press a keyboard key on the active page.

        Args:
            key: Key name understood by Playwright, e.g. ``"Enter"``,
                 ``"Tab"``, ``"Escape"``, ``"ArrowDown"``.
        """
        await self._active_page().keyboard.press(key)

    # ── Extraction ───────────────────────────────────────────────────────────

    async def extract(
        self,
        selector: str,
        attributes: list[str] | None = None,
    ) -> ExtractResult:
        """Extract data from all elements matching *selector*.

        For each matched element the returned dict may contain:
        ``text``, ``href``, ``src``, ``value``, ``outerHTML`` (truncated to
        500 chars), plus any attribute names listed in *attributes*.

        Args:
            selector: CSS selector.
            attributes: Additional HTML attributes to extract.

        Returns:
            :class:`ExtractResult` with a list of per-element dicts.
        """
        page = self._active_page()
        extra_attrs: list[str] = attributes or []
        try:
            elements = await page.query_selector_all(selector)
            items: list[dict] = []
            for el in elements:
                item: dict[str, Any] = {}
                item["text"] = (await el.text_content() or "").strip()
                item["href"] = await el.get_attribute("href") or ""
                item["src"] = await el.get_attribute("src") or ""
                item["value"] = await el.get_attribute("value") or ""
                outer = await el.evaluate("el => el.outerHTML")
                item["outerHTML"] = (outer or "")[:500]
                for attr in extra_attrs:
                    item[attr] = await el.get_attribute(attr) or ""
                # Strip empty keys for cleaner output
                items.append({k: v for k, v in item.items() if v})
            return ExtractResult(
                success=True,
                selector=selector,
                count=len(items),
                items=items,
            )
        except Exception as exc:
            log.warning("extract(%r) failed: %s", selector, exc)
            return ExtractResult(success=False, selector=selector)

    async def extract_table(self, selector: str = "table") -> list[list[str]]:
        """Parse a ``<table>`` element into a list of rows.

        Each row is a list of cell text values.  The first row is usually
        the header row.

        Args:
            selector: CSS selector for the table element (default ``"table"``).

        Returns:
            List of rows; each row is a list of strings.
        """
        page = self._active_page()
        try:
            rows: list[list[str]] = await page.evaluate(
                f"""() => {{
                    const tbl = document.querySelector({selector!r});
                    if (!tbl) return [];
                    return Array.from(tbl.rows).map(r =>
                        Array.from(r.cells).map(c => c.innerText.trim())
                    );
                }}"""
            )
            return rows or []
        except Exception as exc:
            log.warning("extract_table(%r) failed: %s", selector, exc)
            return []

    async def find_element(self, selector: str) -> dict | None:
        """Return basic info about the first element matching *selector*,
        or ``None`` if not found."""
        page = self._active_page()
        try:
            el = await page.query_selector(selector)
            if el is None:
                return None
            return {
                "tag": await el.evaluate("el => el.tagName.toLowerCase()"),
                "text": (await el.text_content() or "").strip(),
                "visible": await el.is_visible(),
                "enabled": await el.is_enabled(),
            }
        except Exception as exc:
            log.debug("find_element(%r): %s", selector, exc)
            return None

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int = 0,
    ) -> bool:
        """Wait until *selector* appears in the DOM.

        Returns:
            ``True`` when the element appears, ``False`` on timeout.
        """
        page = self._active_page()
        t = timeout or self.config.timeout
        try:
            await page.wait_for_selector(selector, timeout=t)
            return True
        except Exception:
            return False

    # ── JavaScript ───────────────────────────────────────────────────────────

    async def evaluate(self, script: str) -> Any:
        """Execute *script* in the page context and return the result.

        Args:
            script: JavaScript expression or function body.

        Returns:
            Serialisable return value from the script.
        """
        return await self._active_page().evaluate(script)

    async def evaluate_on_element(self, selector: str, script: str) -> Any:
        """Execute *script* with the first element matching *selector* as
        the argument.

        The script receives the element as ``element``, e.g.::

            "element => element.getAttribute('data-id')"
        """
        page = self._active_page()
        el = await page.query_selector(selector)
        if el is None:
            raise ValueError(f"No element found for selector: {selector!r}")
        return await el.evaluate(script)

    # ── Files ─────────────────────────────────────────────────────────────────

    async def upload_file(self, selector: str, file_path: str) -> bool:
        """Set *file_path* as the value of the file-input at *selector*.

        Args:
            selector: CSS selector for the ``<input type="file">`` element.
            file_path: Absolute path on the local file system.

        Returns:
            ``True`` on success.
        """
        page = self._active_page()
        try:
            await page.set_input_files(selector, file_path, timeout=self.config.timeout)
            return True
        except Exception as exc:
            log.warning("upload_file(%r, %r) failed: %s", selector, file_path, exc)
            return False

    async def wait_for_download(self, trigger_selector: str) -> str:
        """Click *trigger_selector* and wait for the resulting file download.

        Args:
            trigger_selector: CSS selector for the download-trigger element.

        Returns:
            Path to the downloaded file on disk.
        """
        page = self._active_page()
        async with page.expect_download() as download_info:
            await page.click(trigger_selector, timeout=self.config.timeout)
        download = await download_info.value
        dest = os.path.join(self.config.download_dir, download.suggested_filename)
        await download.save_as(dest)
        log.info("Download saved: %s", dest)
        return dest

    # ── Network ───────────────────────────────────────────────────────────────

    async def intercept_requests(
        self,
        pattern: str,
        action: str = "block",
    ) -> None:
        """Add a request interception rule.

        Args:
            pattern: URL glob pattern, e.g. ``"**/*.png"``.
            action: ``"block"`` (abort matching requests) or ``"continue"``.
        """
        page = self._active_page()
        if action == "block":
            await page.route(pattern, lambda route: asyncio.ensure_future(route.abort()))
        else:
            await page.route(pattern, lambda route: asyncio.ensure_future(route.continue_()))

    async def get_network_log(self) -> list[dict]:
        """Return all captured request/response entries for this session."""
        return list(self._network_log)

    async def set_cookies(self, cookies: list[dict]) -> None:
        """Add cookies to the current browser context.

        Each cookie dict should include at minimum ``name``, ``value``, and
        ``url`` or ``domain``.
        """
        await self._context.add_cookies(cookies)

    async def get_cookies(self) -> list[dict]:
        """Return all cookies for the current context."""
        return await self._context.cookies()

    async def clear_cookies(self) -> None:
        """Remove all cookies from the current context."""
        await self._context.clear_cookies()

    # ── Multi-Tab ─────────────────────────────────────────────────────────────

    async def new_tab(self) -> str:
        """Open a new blank tab.

        Returns:
            The new tab's ID string.
        """
        page = await self._context.new_page()
        tab_id = str(uuid.uuid4())[:8]
        self._tabs[tab_id] = page
        self._page = page
        self._active_tab_id = tab_id
        log.debug("new_tab → tab_id=%s", tab_id)
        return tab_id

    async def switch_tab(self, tab_id: str) -> None:
        """Make the tab identified by *tab_id* the active page.

        Args:
            tab_id: ID returned by :meth:`new_tab`.

        Raises:
            KeyError: If *tab_id* is not recognised.
        """
        if tab_id not in self._tabs:
            raise KeyError(f"Unknown tab_id: {tab_id!r}")
        self._page = self._tabs[tab_id]
        self._active_tab_id = tab_id
        await self._page.bring_to_front()

    async def close_tab(self, tab_id: str) -> None:
        """Close the tab identified by *tab_id*.

        If the closed tab was active, the first remaining tab becomes active.
        """
        if tab_id not in self._tabs:
            return
        page = self._tabs.pop(tab_id)
        await page.close()
        if self._active_tab_id == tab_id:
            if self._tabs:
                first_id = next(iter(self._tabs))
                self._page = self._tabs[first_id]
                self._active_tab_id = first_id
            else:
                self._page = None
                self._active_tab_id = ""

    async def list_tabs(self) -> list[dict]:
        """Return metadata for all open tabs.

        Returns:
            List of dicts with keys ``tab_id``, ``url``, ``title``,
            ``active``.
        """
        results: list[dict] = []
        for tid, pg in self._tabs.items():
            results.append({
                "tab_id": tid,
                "url": pg.url,
                "title": await pg.title(),
                "active": tid == self._active_tab_id,
            })
        return results

    # ── State ─────────────────────────────────────────────────────────────────

    async def get_state(self) -> PageState:
        """Return the current :class:`PageState` of the active page."""
        return await _page_state(self._active_page(), self._active_tab_id)

    @property
    def is_running(self) -> bool:
        """``True`` if the session is currently active."""
        return self._running


# ---------------------------------------------------------------------------
# BrowserConnector — Connector subclass for ConnectorRegistry
# ---------------------------------------------------------------------------

class BrowserConnector(Connector):
    """Chromium browser connector for the Orchestra ConnectorRegistry.

    Plugs into ``arch_e.py``'s :class:`~orchestra.arch_e.ConnectorRegistry`
    and exposes all browser operations as OpenAI-format tools that agents
    can call.

    Each :meth:`connect` call creates a new isolated :class:`BrowserSession`.
    Multiple connectors can coexist — one per agent session.

    Example::

        conn = BrowserConnector()
        await conn.connect({"mode": "local", "headless": "true"})
        result = await conn.execute("navigate", {"url": "https://example.com"})
        print(result["url"])
        await conn.disconnect()
    """

    name = "browser"
    description = (
        "Full Chromium browser automation — navigate, interact, extract, screenshot."
    )

    def __init__(self) -> None:
        self._session: BrowserSession | None = None
        self._connected_flag: bool = False

    # -- Connector interface -------------------------------------------------

    @property
    def connected(self) -> bool:
        """``True`` while the underlying :class:`BrowserSession` is running."""
        return self._connected_flag and (
            self._session is not None and self._session.is_running
        )

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Initialise the browser.

        *credentials* keys:

        - ``mode`` — ``"local"`` (default), ``"remote_cdp"``, ``"browserless"``
        - ``headless`` — ``"true"`` / ``"false"`` (default ``"true"``)
        - ``remote_url`` — ``ws://`` URL for remote CDP
        - ``stealth`` — ``"true"`` / ``"false"`` (default ``"true"``)
        - ``block_ads`` — ``"true"`` / ``"false"`` (default ``"true"``)
        - ``user_agent`` — custom User-Agent string
        - ``proxy`` — ``http://user:pass@host:port``
        - ``timeout`` — action timeout in ms (default ``"30000"``)

        Returns:
            ``True`` on success.
        """
        if not HAS_PLAYWRIGHT:
            log.error(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            )
            return False

        def _bool(key: str, default: bool) -> bool:
            raw = credentials.get(key, "")
            if not raw:
                return default
            return raw.lower() not in ("false", "0", "no")

        config = BrowserConfig(
            mode=credentials.get("mode", "local"),
            headless=_bool("headless", True),
            remote_url=credentials.get(
                "remote_url",
                os.environ.get("BROWSER_REMOTE_URL", ""),
            ),
            user_agent=credentials.get("user_agent", ""),
            stealth=_bool("stealth", True),
            block_ads=_bool("block_ads", True),
            proxy=credentials.get("proxy", ""),
            timeout=int(credentials.get("timeout", "30000")),
        )

        # Close any existing session before creating a new one
        if self._session and self._session.is_running:
            await self._session.close()

        self._session = BrowserSession(config)
        try:
            await self._session.start()
            self._connected_flag = True
            log.info("BrowserConnector connected (mode=%s)", config.mode)
            return True
        except Exception as exc:
            log.error("BrowserConnector.connect failed: %s", exc)
            self._connected_flag = False
            return False

    async def execute(
        self,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a browser *action* with *params*.

        Supported actions: ``navigate``, ``click``, ``type``, ``fill``,
        ``select``, ``extract``, ``extract_table``, ``screenshot``,
        ``get_content``, ``get_text``, ``evaluate``, ``scroll``, ``hover``,
        ``press_key``, ``new_tab``, ``switch_tab``, ``close_tab``,
        ``list_tabs``, ``set_cookies``, ``get_cookies``, ``upload_file``,
        ``intercept_requests``, ``get_network_log``, ``pdf``, ``get_state``,
        ``go_back``, ``go_forward``, ``reload``, ``wait_for``,
        ``drag_and_drop``, ``find_element``, ``get_accessibility_tree``,
        ``get_title``, ``get_url``, ``clear_cookies``.

        Returns a dict with action results; on error includes an ``"error"``
        key.
        """
        if not self.connected or self._session is None:
            return {"error": "Browser not connected. Call connect() first."}

        s = self._session
        try:
            # ── Navigation ───────────────────────────────────────────────────
            if action == "navigate":
                state = await s.navigate(
                    params["url"],
                    wait_until=params.get("wait_until", "networkidle"),
                )
                return {
                    "url": state.url,
                    "title": state.title,
                    "content_length": state.content_length,
                    "tab_id": state.tab_id,
                }

            elif action == "go_back":
                state = await s.go_back()
                return {"url": state.url, "title": state.title}

            elif action == "go_forward":
                state = await s.go_forward()
                return {"url": state.url, "title": state.title}

            elif action == "reload":
                state = await s.reload()
                return {"url": state.url, "title": state.title}

            # ── DOM Interaction ───────────────────────────────────────────────
            elif action == "click":
                result = await s.click(
                    params["selector"],
                    timeout=int(params.get("timeout", 0)),
                )
                return {
                    "success": result.success,
                    "selector": result.selector,
                    "element_text": result.element_text,
                    "new_url": result.new_url,
                }

            elif action == "type":
                ok = await s.type_text(
                    params["selector"],
                    params["text"],
                    delay=int(params.get("delay", 0)),
                )
                return {"success": ok}

            elif action == "fill":
                ok = await s.fill(params["selector"], params["value"])
                return {"success": ok}

            elif action == "select":
                ok = await s.select(params["selector"], params["value"])
                return {"success": ok}

            elif action == "hover":
                ok = await s.hover(params["selector"])
                return {"success": ok}

            elif action == "scroll":
                await s.scroll_to(
                    selector=params.get("selector", ""),
                    x=int(params.get("x", 0)),
                    y=int(params.get("y", 0)),
                )
                return {"success": True}

            elif action == "press_key":
                await s.press_key(params["key"])
                return {"success": True}

            elif action == "drag_and_drop":
                ok = await s.drag_and_drop(params["source"], params["target"])
                return {"success": ok}

            # ── Extraction ───────────────────────────────────────────────────
            elif action == "extract":
                result = await s.extract(
                    params["selector"],
                    attributes=params.get("attributes"),
                )
                return {
                    "success": result.success,
                    "selector": result.selector,
                    "count": result.count,
                    "items": result.items,
                }

            elif action == "extract_table":
                rows = await s.extract_table(params.get("selector", "table"))
                return {"rows": rows, "row_count": len(rows)}

            elif action == "find_element":
                info = await s.find_element(params["selector"])
                return {"element": info}

            elif action == "wait_for":
                found = await s.wait_for_selector(
                    params["selector"],
                    timeout=int(params.get("timeout", 0)),
                )
                return {"found": found}

            # ── Content ──────────────────────────────────────────────────────
            elif action == "get_content":
                html = await s.get_content()
                return {"html": html, "length": len(html)}

            elif action == "get_text":
                text = await s.get_text()
                return {"text": text, "length": len(text)}

            elif action == "get_title":
                return {"title": await s.get_title()}

            elif action == "get_url":
                return {"url": await s.get_url()}

            elif action == "get_accessibility_tree":
                tree = await s.get_accessibility_tree()
                return {"tree": tree}

            elif action == "get_state":
                state = await s.get_state()
                return {
                    "url": state.url,
                    "title": state.title,
                    "content_length": state.content_length,
                    "tab_id": state.tab_id,
                    "load_state": state.load_state,
                }

            # ── Screenshot / PDF ─────────────────────────────────────────────
            elif action == "screenshot":
                raw = await s.screenshot(
                    full_page=params.get("full_page", True),
                    path=params.get("path", ""),
                )
                b64 = base64.b64encode(raw).decode()
                return {
                    "screenshot_base64": b64,
                    "size_bytes": len(raw),
                    "format": "png",
                }

            elif action == "pdf":
                raw = await s.pdf(path=params.get("path", ""))
                b64 = base64.b64encode(raw).decode()
                return {
                    "pdf_base64": b64,
                    "size_bytes": len(raw),
                }

            # ── JavaScript ───────────────────────────────────────────────────
            elif action == "evaluate":
                value = await s.evaluate(params["script"])
                return {"result": value}

            # ── Files ────────────────────────────────────────────────────────
            elif action == "upload_file":
                ok = await s.upload_file(params["selector"], params["file_path"])
                return {"success": ok}

            # ── Network ──────────────────────────────────────────────────────
            elif action == "intercept_requests":
                await s.intercept_requests(
                    params["pattern"],
                    action=params.get("intercept_action", "block"),
                )
                return {"success": True}

            elif action == "get_network_log":
                log_entries = await s.get_network_log()
                return {"entries": log_entries, "count": len(log_entries)}

            elif action == "set_cookies":
                await s.set_cookies(params["cookies"])
                return {"success": True}

            elif action == "get_cookies":
                cookies = await s.get_cookies()
                return {"cookies": cookies, "count": len(cookies)}

            elif action == "clear_cookies":
                await s.clear_cookies()
                return {"success": True}

            # ── Multi-Tab ────────────────────────────────────────────────────
            elif action == "new_tab":
                tab_id = await s.new_tab()
                return {"tab_id": tab_id}

            elif action == "switch_tab":
                await s.switch_tab(params["tab_id"])
                return {"success": True, "tab_id": params["tab_id"]}

            elif action == "close_tab":
                await s.close_tab(params["tab_id"])
                return {"success": True}

            elif action == "list_tabs":
                tabs = await s.list_tabs()
                return {"tabs": tabs, "count": len(tabs)}

            # ── Unknown ──────────────────────────────────────────────────────
            else:
                return {"error": f"Unknown browser action: {action!r}"}

        except Exception as exc:
            log.error("BrowserConnector.execute(%r) error: %s", action, exc, exc_info=True)
            return {"error": str(exc), "action": action}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool definitions for all browser actions.

        The following tools are exposed:
        ``browser_navigate``, ``browser_click``, ``browser_type``,
        ``browser_fill``, ``browser_select``, ``browser_extract``,
        ``browser_extract_table``, ``browser_screenshot``,
        ``browser_get_content``, ``browser_get_text``, ``browser_evaluate``,
        ``browser_scroll``, ``browser_hover``, ``browser_press_key``,
        ``browser_new_tab``, ``browser_switch_tab``, ``browser_set_cookies``,
        ``browser_get_cookies``, ``browser_upload_file``,
        ``browser_wait_for``, ``browser_get_state``.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": (
                        "Navigate to a URL in the current browser tab and wait for "
                        "the page to load.  Returns url, title, and content_length."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Full URL to navigate to (must include https:// or http://).",
                            },
                            "wait_until": {
                                "type": "string",
                                "enum": ["load", "domcontentloaded", "networkidle"],
                                "description": "Load event to wait for (default: networkidle).",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_click",
                    "description": (
                        "Click an element identified by a CSS selector or visible text label."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector or visible text of the element to click.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in ms (0 = use connector default).",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_type",
                    "description": "Type text into an input element keystroke-by-keystroke.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the input element.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to type.",
                            },
                            "delay": {
                                "type": "integer",
                                "description": "Delay between keystrokes in ms (default 0).",
                            },
                        },
                        "required": ["selector", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_fill",
                    "description": "Clear an input field and fill it with a value instantly (faster than type).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the input element.",
                            },
                            "value": {
                                "type": "string",
                                "description": "Value to fill into the field.",
                            },
                        },
                        "required": ["selector", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_select",
                    "description": "Select an option from a <select> dropdown element.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the <select> element.",
                            },
                            "value": {
                                "type": "string",
                                "description": "Option value or label to select.",
                            },
                        },
                        "required": ["selector", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_extract",
                    "description": (
                        "Extract text, links, images, and other data from all elements "
                        "matching a CSS selector.  Returns a list of items with keys "
                        "text, href, src, value, outerHTML."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector to match elements.",
                            },
                            "attributes": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Additional HTML attribute names to extract.",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_extract_table",
                    "description": "Parse a <table> element into a list of rows (list of string lists).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the table (default: 'table').",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_screenshot",
                    "description": (
                        "Take a screenshot of the current page and return it as a "
                        "base64-encoded PNG string."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "full_page": {
                                "type": "boolean",
                                "description": "Capture the full scrollable page (default true).",
                            },
                            "path": {
                                "type": "string",
                                "description": "Optional file path to save the screenshot.",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_content",
                    "description": "Return the full outer HTML of the current page.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_text",
                    "description": "Return the visible text of the current page with whitespace cleaned up.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_evaluate",
                    "description": "Execute a JavaScript expression in the page context and return the result.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script": {
                                "type": "string",
                                "description": "JavaScript code or expression to execute.",
                            },
                        },
                        "required": ["script"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_scroll",
                    "description": "Scroll the page to an element or absolute (x, y) coordinates.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector to scroll into view (optional).",
                            },
                            "x": {
                                "type": "integer",
                                "description": "Horizontal scroll offset in pixels.",
                            },
                            "y": {
                                "type": "integer",
                                "description": "Vertical scroll offset in pixels.",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_hover",
                    "description": "Move the mouse cursor over an element to trigger hover effects.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector or visible text of the element to hover.",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_press_key",
                    "description": "Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Playwright key name, e.g. 'Enter', 'Tab', 'Escape'.",
                            },
                        },
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_new_tab",
                    "description": "Open a new browser tab and make it active.  Returns the new tab_id.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_switch_tab",
                    "description": "Switch the active tab to the one identified by tab_id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tab_id": {
                                "type": "string",
                                "description": "Tab ID returned by browser_new_tab or browser_list_tabs.",
                            },
                        },
                        "required": ["tab_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_set_cookies",
                    "description": "Inject cookies into the current browser context.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cookies": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": (
                                    "List of cookie dicts.  Each must have 'name', 'value', "
                                    "and 'url' or 'domain'."
                                ),
                            },
                        },
                        "required": ["cookies"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_cookies",
                    "description": "Return all cookies stored in the current browser context.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_upload_file",
                    "description": "Set a local file as the value of a file-input element.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the <input type='file'> element.",
                            },
                            "file_path": {
                                "type": "string",
                                "description": "Absolute path on the host file system.",
                            },
                        },
                        "required": ["selector", "file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_wait_for",
                    "description": "Wait until an element matching a CSS selector appears in the DOM.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "CSS selector to wait for.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Max wait time in ms (0 = use connector default).",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_state",
                    "description": (
                        "Return the current state of the active tab: url, title, "
                        "content_length, tab_id, and load_state."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        ]

    async def disconnect(self) -> None:
        """Close the browser session and release all resources."""
        if self._session and self._session.is_running:
            await self._session.close()
        self._connected_flag = False
        self._session = None
        log.info("BrowserConnector disconnected")

    async def __aenter__(self) -> "BrowserConnector":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
