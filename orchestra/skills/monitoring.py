"""Horizon Orchestra — Web Monitoring Skill.

Cron-based web monitoring with change detection, price tracking, and
notification integration.  Agents can schedule URLs to be watched and
receive alerts when content changes or prices drop.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from .base import Skill

__all__ = [
    "WebMonitor",
    "MonitorScheduler",
    "PageSnapshot",
    "ChangeResult",
    "PriceResult",
]

log = logging.getLogger("orchestra.skills.monitoring")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PageSnapshot:
    """A point-in-time snapshot of a web page."""

    url: str
    content: str                 # Extracted text (or selected element text)
    hash: str                    # SHA-256 of normalised content
    timestamp: float = field(default_factory=time.time)
    status_code: int = 200


@dataclass
class ChangeResult:
    """Result of a change-detection check."""

    url: str
    changed: bool
    old_hash: str
    new_hash: str
    diff_summary: str = ""       # Human-readable summary of what changed
    new_content: str = ""        # Current content if changed


@dataclass
class PriceResult:
    """Extracted price from a product page."""

    url: str
    price: float | None
    currency: str = "USD"
    product_name: str = ""
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# WebMonitor
# ---------------------------------------------------------------------------

class WebMonitor(Skill):
    """Fetch web pages, detect content changes, and track prices.

    Used by :class:`MonitorScheduler` to implement cron-based monitoring.
    Can also be called directly for one-off checks.
    """

    name: str = "web_monitor"
    description: str = (
        "Monitor web pages for changes or price updates. "
        "Fetch snapshots, compare against previous state, and extract prices."
    )

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    async def check_page(
        self,
        url: str,
        selector: str = "",
    ) -> PageSnapshot:
        """Fetch *url* and return a :class:`PageSnapshot`.

        Args:
            url: The URL to fetch.
            selector: Optional CSS selector or keyword to narrow the text.
                      If a CSS selector, attempts basic extraction.
                      If plain text, finds the containing line.
        """
        log.info("check_page() url=%s selector=%r", url, selector)
        try:
            import httpx  # type: ignore[import]

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; OrchestraBot/1.0; "
                    "+https://github.com/horizon-orchestra)"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)
                status = resp.status_code
                raw_html = resp.text

        except Exception as exc:
            log.error("check_page() fetch failed for %s: %s", url, exc)
            error_content = f"[Fetch error: {exc}]"
            return PageSnapshot(
                url=url,
                content=error_content,
                hash=self._hash_content(error_content),
                status_code=0,
            )

        # Extract text
        content = _extract_text_from_html(raw_html)

        # Apply selector filtering
        if selector:
            content = _apply_selector(content, selector, raw_html)

        snapshot = PageSnapshot(
            url=url,
            content=content,
            hash=self._hash_content(content),
            status_code=status,
        )
        log.debug("check_page() hash=%s status=%d len=%d", snapshot.hash, status, len(content))
        return snapshot

    async def detect_changes(
        self,
        url: str,
        previous_hash: str,
        selector: str = "",
    ) -> ChangeResult:
        """Compare current page content against *previous_hash*.

        Returns a :class:`ChangeResult` indicating whether and how the page changed.
        """
        snapshot = await self.check_page(url, selector)
        changed = snapshot.hash != previous_hash

        diff_summary = ""
        if changed:
            diff_summary = _summarise_diff(previous_hash, snapshot.content)
            log.info("detect_changes() CHANGED url=%s old=%s new=%s", url, previous_hash, snapshot.hash)
        else:
            log.debug("detect_changes() unchanged url=%s", url)

        return ChangeResult(
            url=url,
            changed=changed,
            old_hash=previous_hash,
            new_hash=snapshot.hash,
            diff_summary=diff_summary,
            new_content=snapshot.content if changed else "",
        )

    async def monitor_price(
        self,
        url: str,
        selector: str = "",
    ) -> PriceResult:
        """Fetch *url* and extract the current price.

        Args:
            url: Product page URL.
            selector: Optional CSS selector or keyword to help locate the price.

        Returns:
            :class:`PriceResult` with extracted price and currency.
        """
        log.info("monitor_price() url=%s selector=%r", url, selector)
        snapshot = await self.check_page(url, selector)

        # Extract product name — look for <title> or first heading
        product_name = _extract_product_name(snapshot.content)

        # Extract price
        price_text = snapshot.content
        if selector:
            price_text = _apply_selector(snapshot.content, selector, "")

        price, currency = self._extract_price_with_currency(price_text)

        return PriceResult(
            url=url,
            price=price,
            currency=currency,
            product_name=product_name,
        )

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _hash_content(self, text: str) -> str:
        """SHA-256 hash of normalised (whitespace-collapsed) text."""
        normalised = re.sub(r"\s+", " ", text).strip().lower()
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]

    def _extract_price(self, text: str) -> float | None:
        """Extract a dollar amount from text. Returns None if not found."""
        price, _ = self._extract_price_with_currency(text)
        return price

    def _extract_price_with_currency(self, text: str) -> tuple[float | None, str]:
        """Extract price and currency symbol from text."""
        # Currency patterns: $, €, £, ¥, or text
        patterns = [
            # Symbol before number: $12.99, €9.99, £5.00
            r"([\$€£¥₹])\s*(\d{1,6}(?:[,\s]\d{3})*(?:\.\d{1,2})?)",
            # Number before symbol: 12.99$
            r"(\d{1,6}(?:[,\s]\d{3})*(?:\.\d{1,2})?)\s*([\$€£¥₹])",
            # USD/EUR/GBP text notation: USD 12.99, 12.99 USD
            r"(?:USD|EUR|GBP|JPY|CAD|AUD)\s*(\d{1,6}(?:[,\s]\d{3})*(?:\.\d{1,2})?)",
            r"(\d{1,6}(?:[,\s]\d{3})*(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP|JPY|CAD|AUD)",
        ]

        currency_map = {
            "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
            "₹": "INR", "USD": "USD", "EUR": "EUR", "GBP": "GBP",
        }

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                # Find the numeric group
                for g in groups:
                    if g and re.match(r"[\d,\s]+\.?\d*$", g):
                        try:
                            # Remove commas and spaces used as thousand separators
                            price_str = re.sub(r"[,\s]", "", g)
                            price = float(price_str)
                            # Determine currency
                            currency = "USD"
                            for sym, cur in currency_map.items():
                                if sym in match.group(0):
                                    currency = cur
                                    break
                            return price, currency
                        except ValueError:
                            continue

        return None, "USD"

    # ------------------------------------------------------------------
    # Skill ABC interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "monitor_check_page",
                    "description": (
                        "Fetch a web page and return its content hash and text. "
                        "Used as a baseline for change detection."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL to check."},
                            "selector": {
                                "type": "string",
                                "description": "Optional CSS selector or keyword to narrow the monitored content.",
                                "default": "",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "monitor_watch_url",
                    "description": (
                        "Register a URL for continuous monitoring. "
                        "Checks the URL on a schedule and triggers a callback when it changes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL to watch."},
                            "interval_minutes": {
                                "type": "integer",
                                "description": "Check interval in minutes.",
                                "default": 60,
                            },
                            "selector": {
                                "type": "string",
                                "description": "Optional CSS selector or keyword to narrow monitoring.",
                                "default": "",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "monitor_check_price",
                    "description": "Fetch a product page and extract the current price.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Product page URL."},
                            "selector": {
                                "type": "string",
                                "description": "Optional CSS selector to locate the price element.",
                                "default": "",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "monitor_check_page":
            snap = await self.check_page(
                url=params["url"],
                selector=params.get("selector", ""),
            )
            return {
                "url": snap.url,
                "hash": snap.hash,
                "content_preview": snap.content[:500],
                "status_code": snap.status_code,
                "timestamp": snap.timestamp,
            }

        if action == "monitor_watch_url":
            # Scheduler integration — start watching
            scheduler = MonitorScheduler.get_global()
            watch_id = scheduler.add_watch(
                url=params["url"],
                interval_minutes=int(params.get("interval_minutes", 60)),
                selector=params.get("selector", ""),
                callback=None,
            )
            return {"watch_id": watch_id, "url": params["url"]}

        if action == "monitor_check_price":
            result = await self.monitor_price(
                url=params["url"],
                selector=params.get("selector", ""),
            )
            return {
                "url": result.url,
                "price": result.price,
                "currency": result.currency,
                "product_name": result.product_name,
                "timestamp": result.timestamp,
            }

        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# MonitorScheduler
# ---------------------------------------------------------------------------

_CallbackType = Callable[[ChangeResult], Coroutine[Any, Any, None]] | None


@dataclass
class _WatchEntry:
    watch_id: str
    url: str
    interval_minutes: int
    selector: str
    callback: _CallbackType
    last_hash: str = ""
    last_checked: float = 0.0
    created_at: float = field(default_factory=time.time)
    active: bool = True


class MonitorScheduler:
    """Cron-based scheduler for web monitoring watches.

    Maintains a registry of URLs to watch, runs periodic checks, and
    dispatches notifications when content changes are detected.

    Usage::

        scheduler = MonitorScheduler()
        watch_id = scheduler.add_watch(
            "https://example.com/price",
            interval_minutes=30,
            selector=".product-price",
            callback=my_async_callback,
        )
        await scheduler.start()    # runs background task
    """

    _global_instance: MonitorScheduler | None = None

    def __init__(
        self,
        notification_manager: Any | None = None,
    ) -> None:
        self._watches: dict[str, _WatchEntry] = {}
        self._monitor = WebMonitor()
        self._notification_manager = notification_manager
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def get_global(cls) -> MonitorScheduler:
        """Return (or create) the singleton MonitorScheduler."""
        if cls._global_instance is None:
            cls._global_instance = cls()
        return cls._global_instance

    # ------------------------------------------------------------------
    # Watch management
    # ------------------------------------------------------------------

    def add_watch(
        self,
        url: str,
        interval_minutes: int = 60,
        selector: str = "",
        callback: _CallbackType = None,
    ) -> str:
        """Register a URL to watch.

        Args:
            url: URL to monitor.
            interval_minutes: Polling interval.
            selector: Optional element selector for targeted monitoring.
            callback: Async callable called with ChangeResult when content changes.

        Returns:
            A unique ``watch_id`` string.
        """
        watch_id = f"watch_{uuid.uuid4().hex[:8]}"
        entry = _WatchEntry(
            watch_id=watch_id,
            url=url,
            interval_minutes=interval_minutes,
            selector=selector,
            callback=callback,
        )
        self._watches[watch_id] = entry
        log.info("add_watch() id=%s url=%s interval=%dm", watch_id, url, interval_minutes)
        return watch_id

    def remove_watch(self, watch_id: str) -> None:
        """Remove a watch by ID."""
        if watch_id in self._watches:
            del self._watches[watch_id]
            log.info("remove_watch() id=%s", watch_id)
        else:
            log.warning("remove_watch() unknown id=%s", watch_id)

    def list_watches(self) -> list[dict[str, Any]]:
        """Return all registered watches as serialisable dicts."""
        return [
            {
                "watch_id": w.watch_id,
                "url": w.url,
                "interval_minutes": w.interval_minutes,
                "selector": w.selector,
                "last_hash": w.last_hash,
                "last_checked": w.last_checked,
                "active": w.active,
            }
            for w in self._watches.values()
        ]

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._task and not self._task.done():
            log.warning("MonitorScheduler already running")
            return
        self._task = asyncio.create_task(self._scheduler_loop())
        log.info("MonitorScheduler started")

    async def stop(self) -> None:
        """Stop the background monitoring loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            log.info("MonitorScheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Background loop: check watches that are due."""
        while True:
            try:
                now = time.time()
                due_watches = [
                    w for w in self._watches.values()
                    if w.active and (now - w.last_checked) >= w.interval_minutes * 60
                ]
                if due_watches:
                    await self._check_all_due(due_watches)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("MonitorScheduler loop error: %s", exc)
            await asyncio.sleep(60)   # check the schedule every minute

    async def _check_all_due(self, watches: list[_WatchEntry]) -> list[ChangeResult]:
        """Run all due watches concurrently."""
        tasks = [self._check_one(w) for w in watches]
        results: list[ChangeResult] = []
        for outcome in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(outcome, ChangeResult):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                log.error("Watch check failed: %s", outcome)
        return results

    async def _check_all(self) -> list[ChangeResult]:
        """Run ALL watches and return change results.  Called directly for manual checks."""
        return await self._check_all_due(list(self._watches.values()))

    async def _check_one(self, watch: _WatchEntry) -> ChangeResult:
        """Check a single watch entry."""
        watch.last_checked = time.time()

        if not watch.last_hash:
            # First check — establish baseline
            snapshot = await self._monitor.check_page(watch.url, watch.selector)
            watch.last_hash = snapshot.hash
            return ChangeResult(
                url=watch.url,
                changed=False,
                old_hash="",
                new_hash=snapshot.hash,
                diff_summary="[Baseline established]",
            )

        result = await self._monitor.detect_changes(watch.url, watch.last_hash, watch.selector)

        if result.changed:
            # Update stored hash
            watch.last_hash = result.new_hash

            # Invoke callback
            if watch.callback:
                try:
                    await watch.callback(result)
                except Exception as exc:
                    log.error("Watch callback failed for %s: %s", watch.url, exc)

            # Send notification if manager available
            if self._notification_manager:
                await self._send_change_notification(watch, result)

        return result

    async def _send_change_notification(
        self,
        watch: _WatchEntry,
        result: ChangeResult,
    ) -> None:
        """Dispatch a notification for a detected change."""
        try:
            await self._notification_manager.send(
                user_id="system",
                title=f"Page changed: {watch.url[:60]}",
                body=result.diff_summary or "Content has changed",
                channel="in_app",
                data={
                    "url": watch.url,
                    "watch_id": watch.watch_id,
                    "old_hash": result.old_hash,
                    "new_hash": result.new_hash,
                },
            )
        except Exception as exc:
            log.error("Failed to send change notification: %s", exc)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _extract_text_from_html(html: str) -> str:
    """Extract visible text from HTML. Tries lxml/html.parser, falls back to regex."""
    try:
        from html.parser import HTMLParser  # stdlib

        class _TextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.texts: list[str] = []
                self._skip = False
                self._skip_tags = {"script", "style", "noscript", "meta", "head"}
                self._depth = 0

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag.lower() in self._skip_tags:
                    self._skip = True
                    self._depth += 1

            def handle_endtag(self, tag: str) -> None:
                if tag.lower() in self._skip_tags:
                    self._depth -= 1
                    if self._depth <= 0:
                        self._skip = False
                        self._depth = 0

            def handle_data(self, data: str) -> None:
                if not self._skip:
                    stripped = data.strip()
                    if stripped:
                        self.texts.append(stripped)

        extractor = _TextExtractor()
        extractor.feed(html)
        return " ".join(extractor.texts)

    except Exception:
        # Pure regex fallback
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _apply_selector(text: str, selector: str, raw_html: str) -> str:
    """Apply a basic CSS selector or keyword filter to extracted text."""
    # If it looks like a CSS selector, try beautifulsoup
    if re.search(r"[.#\[\]>:~+]", selector):
        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
            soup = BeautifulSoup(raw_html, "html.parser")
            elements = soup.select(selector)
            if elements:
                return " ".join(el.get_text(separator=" ", strip=True) for el in elements)
        except ImportError:
                        import logging as _log; _log.getLogger('skills.monitoring').debug('Suppressed exception', exc_info=True)
        except Exception as exc:
            log.debug("BS4 selector failed: %s", exc)

    # Keyword filter: return lines containing the keyword
    keyword = selector.strip().lower()
    if keyword:
        lines = text.splitlines()
        matching = [l for l in lines if keyword in l.lower()]
        if matching:
            return "\n".join(matching)

    return text


def _summarise_diff(old_hash: str, new_content: str) -> str:
    """Generate a brief diff summary for notifications."""
    # Simple heuristic: report content length and a preview
    preview = new_content[:200].replace("\n", " ").strip()
    return f"Content changed (new hash: {old_hash[:8]}… → ...). Preview: {preview}"


def _extract_product_name(text: str) -> str:
    """Attempt to extract a product name from page text."""
    # Look for common patterns
    for pattern in [
        r"^([^\n]{5,80})\n",   # First non-empty line up to 80 chars
    ]:
        m = re.search(pattern, text.strip())
        if m:
            return m.group(1).strip()
    return text[:60].strip()
