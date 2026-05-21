from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@dataclass
class BrowserTab:
    url: str
    title: str = ""
    content: str = ""
    screenshots: list[str] = field(default_factory=list)
    status: int = 0
    headers: dict = field(default_factory=dict)


@dataclass
class BrowserResult:
    success: bool
    data: Optional[BrowserTab] = None
    error: str = ""
    sources: list[dict] = field(default_factory=list)


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class BrowserEngine:
    def __init__(self, user_agent_index: int = 0):
        self.tabs: list[BrowserTab] = []
        self.active_tab: Optional[int] = None
        self.user_agent = _USER_AGENTS[user_agent_index % len(_USER_AGENTS)]

    def navigate(self, url: str, timeout: float = 30.0) -> BrowserResult:
        if not HAS_HTTPX:
            return BrowserResult(success=False, error="httpx not installed. Install with: pip install httpx")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(timeout),
                headers={"User-Agent": self.user_agent},
            ) as client:
                response = client.get(url)

                content_type = response.headers.get("content-type", "")
                text = ""
                if "text/html" in content_type or "application/json" in content_type:
                    text = response.text
                else:
                    text = f"[Binary content: {content_type}, {len(response.content)} bytes]"

                tab = BrowserTab(
                    url=str(response.url),
                    title=self._extract_title(text),
                    content=text[:100_000],
                    status=response.status_code,
                    headers=dict(response.headers),
                )

                self.tabs.append(tab)
                self.active_tab = len(self.tabs) - 1

                return BrowserResult(success=True, data=tab)

        except httpx.TimeoutException:
            return BrowserResult(success=False, error=f"Timeout after {timeout}s")
        except httpx.ConnectError as e:
            return BrowserResult(success=False, error=f"Connection error: {e}")
        except Exception as e:
            return BrowserResult(success=False, error=str(e))

    def search(self, query: str, num_results: int = 5) -> BrowserResult:
        search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
        result = self.navigate(search_url)
        if not result.success:
            return result

        if result.data and result.data.content:
            links = self._extract_links(result.data.content)
            result.sources = [{"title": l[0], "url": l[1]} for l in links[:num_results]]

        return result

    def extract_text(self, html: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n\s*\n", "\n", text)
        return text.strip()[:20000]

    def _extract_title(self, html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    def _extract_links(self, html: str) -> list[tuple[str, str]]:
        links = []
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if title:
                links.append((title[:100], url))
        return links

    def screenshot(self, url: str) -> BrowserResult:
        result = self.navigate(url)
        if result.success and result.data:
            result.data.screenshots.append("[screenshot capture requires Playwright: pip install playwright]")
        return result

    def multi_page_research(self, urls: list[str]) -> list[BrowserResult]:
        results = []
        for url in urls:
            result = self.navigate(url)
            results.append(result)
            time.sleep(0.5)
        return results

    def close_tab(self, index: int = -1) -> None:
        if self.tabs and abs(index) <= len(self.tabs):
            tab = self.tabs.pop(index)
            if self.active_tab and self.active_tab >= len(self.tabs):
                self.active_tab = len(self.tabs) - 1 if self.tabs else None
