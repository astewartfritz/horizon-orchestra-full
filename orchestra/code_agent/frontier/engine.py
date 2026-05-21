from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.frontier.screener import ContentScreener, SafetyLevel


def _extract_links_from_html(html: str) -> list[tuple[str, str]]:
    links = []
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        url = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if title:
            links.append((title[:100], url))
    return links


@dataclass
class TabInfo:
    url: str
    title: str
    content: str = ""
    content_type: str = "html"
    status: int = 0


@dataclass
class FrontierResult:
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    tabs_used: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    screened: bool = False
    safety_level: str = "safe"
    latency_ms: int = 0
    error: str = ""


class FrontierEngine:
    """Research/search interface that works across tabs, summarizes content,
    and screens content before it reaches the assistant.

    Acts as a layer over page content rather than a separate destination.
    """

    def __init__(self, provider: str = "ollama", model: str = "nemotron-mini"):
        self.provider = provider
        self.model = model
        self._tabs: list[TabInfo] = []
        self._screener = ContentScreener()
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from orchestra.code_agent.llm.base import LLM
            self._llm = LLM(provider=self.provider, model=self.model, timeout=120)
        return self._llm

    def register_tab(self, url: str, title: str, content: str = "", content_type: str = "html") -> int:
        tab = TabInfo(url=url, title=title, content=content, content_type=content_type)
        self._tabs.append(tab)
        return len(self._tabs) - 1

    def get_tabs(self) -> list[TabInfo]:
        return list(self._tabs)

    def summarize_tab(self, index: int = -1) -> str:
        """Summarize a specific tab or the active one."""
        if not self._tabs:
            return "No tabs open."
        tab = self._tabs[index]
        if not tab.content:
            return f"Tab '{tab.title}' has no content loaded."
        return self._summarize(tab.content, tab.url)

    def summarize_all_tabs(self) -> str:
        """Summarize content across ALL open tabs — cross-tab research."""
        if not self._tabs:
            return "No tabs open."
        combined = "\n\n=== TAB ===\n".join(
            f"URL: {t.url}\nTitle: {t.title}\nContent: {t.content[:2000]}"
            for t in self._tabs if t.content
        )
        return self._summarize(combined, "multiple tabs")

    def _summarize(self, content: str, source: str) -> str:
        llm = self._get_llm()
        from orchestra.code_agent.llm.base import Message
        try:
            resp = llm.chat(messages=[
                Message(role="system", content="Summarize the following content concisely. Focus on key facts, data, and conclusions."),
                Message(role="user", content=f"Source: {source}\n\nContent:\n{content[:4000]}"),
            ])
            return resp.content or ""
        except Exception as e:
            return f"Error summarizing: {e}"

    async def research(self, query: str, search_query: str | None = None,
                       include_tabs: bool = True) -> FrontierResult:
        """Multi-source research: web search + open tabs + screened content."""
        start = time.time()
        result = FrontierResult()
        search_text = query

        # 1. Search web
        try:
            import httpx
            sq = search_query or query
            url = f"https://html.duckduckgo.com/html/?q={sq.replace(' ', '+')}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    snippets = []
                    for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', resp.text, re.DOTALL):
                        href = m.group(1)
                        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                        result.sources.append({"title": title, "url": href, "type": "web"})
                        snippets.append(f"[{len(result.sources)}] {title}: {href}")
                        if len(result.sources) >= 6:
                            break
                    if snippets:
                        search_text += "\n\nSearch Results:\n" + "\n".join(snippets)
        except Exception:
            pass

        # 2. Include tab content
        if include_tabs and self._tabs:
            tab_parts = []
            for t in self._tabs:
                if t.content:
                    tab_parts.append(f"Tab: {t.title} ({t.url})\nContent: {t.content[:1500]}")
                    result.tabs_used.append(t.url)
            if tab_parts:
                search_text += "\n\nOpen Tabs:\n" + "\n\n".join(tab_parts)

        # 3. Screen content before LLM
        screening = self._screener.screen(search_text)
        result.screened = True
        result.safety_level = screening.level.value
        if screening.level == SafetyLevel.UNSAFE:
            result.answer = "Content blocked by safety screening."
            result.latency_ms = round((time.time() - start) * 1000)
            return result

        # 4. Generate answer via LLM
        llm = self._get_llm()
        from orchestra.code_agent.llm.base import Message
        try:
            resp = await llm.chat(messages=[
                Message(role="system", content=(
                    "You are a research assistant. Answer using web search results and open tab content. "
                    "Cite sources as [1], [2] etc. Be concise and accurate."
                )),
                Message(role="user", content=f"Question: {query}\n\nContext:\n{search_text[:6000]}"),
            ])
            result.answer = resp.content or ""
        except Exception as e:
            result.answer = f"Error: {e}"
            result.error = str(e)

        result.latency_ms = round((time.time() - start) * 1000)
        return result

    async def research_browser(self, query: str) -> FrontierResult:
        """Research using a real Chromium browser for better page rendering."""
        start = time.time()
        result = FrontierResult()
        try:
            from orchestra.code_agent.browser.chromium import ChromiumController
            browser = ChromiumController(headless=True)
            # Search via DuckDuckGo
            search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            nav = await browser.navigate(search_url)
            if nav.success and nav.data:
                html = nav.data.content[:50000]
                links = _extract_links_from_html(html)
                for title, url in links[:5]:
                    result.sources.append({"title": title, "url": url, "type": "web"})
                # Fetch each result page
                combined = f"Search results for: {query}\n\n"
                for i, (title, url) in enumerate(links[:3]):
                    page = await browser.navigate(url)
                    if page.success and page.data:
                        text = await browser.extract_text()
                        combined += f"[Source {i+1}] {title}\n{url}\n{text[:1500]}\n\n"
                        result.tabs_used.append(url)
                search_text = combined
            else:
                search_text = f"Query: {query}"
        except Exception as e:
            result.error = str(e)
            search_text = f"Query: {query}"
        finally:
            try:
                await browser.close()
            except Exception:
                pass

        # Screen content
        screening = self._screener.screen(search_text)
        result.screened = True
        result.safety_level = screening.level.value
        if screening.level == SafetyLevel.UNSAFE:
            result.answer = "Content blocked by safety screening."
            result.latency_ms = round((time.time() - start) * 1000)
            return result

        # Generate answer
        llm = self._get_llm()
        from orchestra.code_agent.llm.base import Message
        try:
            resp = await llm.chat(messages=[
                Message(role="system", content=(
                    "You are a research assistant. Answer using the web page content provided. "
                    "Cite sources as [1], [2] etc. Be concise and accurate."
                )),
                Message(role="user", content=f"Question: {query}\n\nContent:\n{search_text[:6000]}"),
            ])
            result.answer = resp.content or ""
        except Exception as e:
            result.answer = f"Error: {e}"

        result.latency_ms = round((time.time() - start) * 1000)
        return result

    async def ask(self, question: str) -> FrontierResult:
        """Simple question-answering with content screening."""
        return await self.research(question)
