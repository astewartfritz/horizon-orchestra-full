from __future__ import annotations

import xml.etree.ElementTree as ET
from html import unescape

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OrchestraBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


def _strip_tags(text: str) -> str:
    import re
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


async def _fetch_rss(url: str, count: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(url, headers=_HEADERS)
        r.raise_for_status()
    root = ET.fromstring(r.text)
    ns = {"media": "http://search.yahoo.com/mrss/"}
    items = root.findall(".//item")
    results = []
    for item in items[:count]:
        title = _strip_tags(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        pub = _strip_tags(item.findtext("pubDate") or "")
        desc = _strip_tags(item.findtext("description") or "")[:200]
        source = _strip_tags(item.findtext("source") or "")
        results.append({"title": title, "link": link, "published": pub, "summary": desc, "source": source})
    return results


class NewsTool(Tool):
    spec = ToolSpec(
        name="news",
        description=(
            "Get real-time news headlines. Optionally filter by topic. "
            "Uses Google News RSS — no API key required."
        ),
        parameters={
            "query": {
                "type": "string",
                "description": "Topic or keyword to search for (optional — leave empty for top headlines)",
                "default": "",
            },
            "count": {
                "type": "integer",
                "description": "Number of headlines to return (1–20)",
                "default": 10,
            },
        },
    )

    async def __call__(self, query: str = "", count: int = 10) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed. Run: pip install httpx")
        count = max(1, min(20, int(count)))
        try:
            if query.strip():
                q = query.strip().replace(" ", "+")
                url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
                header = f'Top {count} news results for "{query.strip()}"'
            else:
                url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
                header = f"Top {count} global headlines"

            articles = await _fetch_rss(url, count)
            if not articles:
                return ToolResult(output="No articles found.")

            lines = [header, ""]
            for i, a in enumerate(articles, 1):
                src = f" [{a['source']}]" if a["source"] else ""
                lines.append(f"{i}. {a['title']}{src}")
                if a["published"]:
                    lines.append(f"   {a['published']}")
                if a["summary"]:
                    lines.append(f"   {a['summary']}")
                lines.append(f"   {a['link']}")
                lines.append("")
            return ToolResult(output="\n".join(lines).strip())
        except Exception as e:
            return ToolResult(error=f"News fetch failed: {e}")
