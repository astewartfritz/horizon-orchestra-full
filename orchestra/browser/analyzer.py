"""Page Analyzer — structured data extraction, readability, screenshot intelligence.

Takes a raw page (HTML/DOM) and extracts structured information:
- Main content (article body, product info, pricing)
- Metadata (title, description, author, date)
- Links and navigation structure
- Tables and structured data
- Readability-cleaned text

Usage::

    from orchestra.browser.analyzer import PageAnalyzer
    analyzer = PageAnalyzer()
    data = await analyzer.analyze(engine, page_id)
    clean = await analyzer.extract_article(engine, page_id)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["PageAnalyzer", "PageData"]

log = logging.getLogger("orchestra.browser.analyzer")


@dataclass
class PageData:
    """Structured extraction from a web page."""
    url: str = ""
    title: str = ""
    description: str = ""
    main_content: str = ""
    author: str = ""
    published_date: str = ""
    language: str = ""
    word_count: int = 0
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    structured_data: dict[str, Any] = field(default_factory=dict)  # JSON-LD, OpenGraph


# JavaScript to extract structured page data
EXTRACT_JS = """
(() => {
    const result = {};

    // Metadata
    result.title = document.title || '';
    result.url = window.location.href;
    result.language = document.documentElement.lang || '';

    const getMeta = (name) => {
        const el = document.querySelector(
            `meta[name="${name}"], meta[property="${name}"], meta[property="og:${name}"]`
        );
        return el ? el.content : '';
    };

    result.description = getMeta('description') || getMeta('og:description') || '';
    result.author = getMeta('author') || getMeta('article:author') || '';
    result.published = getMeta('article:published_time') || getMeta('date') || '';
    result.image = getMeta('og:image') || '';
    result.site_name = getMeta('og:site_name') || '';
    result.type = getMeta('og:type') || '';

    // Main content extraction (heuristic: largest text block)
    const blocks = [...document.querySelectorAll('article, main, [role="main"], .content, .post, .article, #content')];
    if (blocks.length > 0) {
        // Pick the one with the most text
        blocks.sort((a, b) => (b.textContent?.length || 0) - (a.textContent?.length || 0));
        result.main_content = blocks[0].innerText?.slice(0, 20000) || '';
    } else {
        result.main_content = document.body?.innerText?.slice(0, 20000) || '';
    }

    // Links
    result.links = [...document.querySelectorAll('a[href]')].slice(0, 50).map(a => ({
        text: (a.textContent || '').trim().slice(0, 80),
        href: a.href
    })).filter(l => l.text && l.href.startsWith('http'));

    // Images
    result.images = [...document.querySelectorAll('img[src]')].slice(0, 20).map(img => ({
        alt: img.alt || '',
        src: img.src,
        width: img.naturalWidth,
        height: img.naturalHeight
    })).filter(i => i.width > 100);

    // Tables
    result.tables = [...document.querySelectorAll('table')].slice(0, 5).map(table => {
        return [...table.querySelectorAll('tr')].slice(0, 50).map(row =>
            [...row.querySelectorAll('th, td')].map(cell =>
                (cell.textContent || '').trim().slice(0, 200)
            )
        );
    });

    // JSON-LD structured data
    const jsonld = document.querySelector('script[type="application/ld+json"]');
    if (jsonld) {
        try { result.jsonld = JSON.parse(jsonld.textContent); } catch(e) {}
    }

    // OpenGraph
    result.og = {};
    document.querySelectorAll('meta[property^="og:"]').forEach(m => {
        result.og[m.getAttribute('property').replace('og:', '')] = m.content;
    });

    result.word_count = (result.main_content.match(/\\S+/g) || []).length;

    return result;
})()
"""

# JavaScript for extracting clean article text (readability-style)
READABILITY_JS = """
(() => {
    // Score paragraphs by content density
    const paragraphs = [...document.querySelectorAll('p, article p, .content p, main p')];
    const scored = paragraphs.map(p => ({
        text: p.textContent?.trim() || '',
        length: (p.textContent || '').length,
        linkDensity: (p.querySelectorAll('a').length) / Math.max(p.textContent?.split(' ').length || 1, 1),
        parent: p.parentElement?.tagName || ''
    })).filter(p => p.length > 40 && p.linkDensity < 0.3);

    const content = scored.map(p => p.text).join('\\n\\n');

    // Extract headings for structure
    const headings = [...document.querySelectorAll('h1, h2, h3, h4')].slice(0, 20).map(h => ({
        level: parseInt(h.tagName[1]),
        text: (h.textContent || '').trim().slice(0, 200)
    }));

    return {
        title: document.title,
        content: content.slice(0, 30000),
        headings,
        word_count: (content.match(/\\S+/g) || []).length,
        paragraph_count: scored.length
    };
})()
"""


class PageAnalyzer:
    """Extract structured data from browser pages."""

    async def analyze(self, engine: Any, page_id: str) -> PageData:
        """Full structured extraction from a page."""
        result = await engine.execute_on_page(page_id, "evaluate", expression=EXTRACT_JS)
        data = result.get("result", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {}

        return PageData(
            url=data.get("url", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            main_content=data.get("main_content", ""),
            author=data.get("author", ""),
            published_date=data.get("published", ""),
            language=data.get("language", ""),
            word_count=data.get("word_count", 0),
            links=data.get("links", []),
            images=data.get("images", []),
            tables=data.get("tables", []),
            metadata={
                "site_name": data.get("site_name", ""),
                "type": data.get("type", ""),
                "image": data.get("image", ""),
            },
            structured_data={
                "jsonld": data.get("jsonld", {}),
                "opengraph": data.get("og", {}),
            },
        )

    async def extract_article(self, engine: Any, page_id: str) -> dict[str, Any]:
        """Extract clean article text with readability heuristics."""
        result = await engine.execute_on_page(page_id, "evaluate", expression=READABILITY_JS)
        data = result.get("result", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {}
        return {
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "headings": data.get("headings", []),
            "word_count": data.get("word_count", 0),
            "paragraph_count": data.get("paragraph_count", 0),
        }

    async def extract_tables(self, engine: Any, page_id: str) -> list[list[list[str]]]:
        """Extract all HTML tables as nested arrays."""
        result = await engine.execute_on_page(page_id, "evaluate", expression="""
            [...document.querySelectorAll('table')].slice(0, 10).map(table =>
                [...table.querySelectorAll('tr')].slice(0, 100).map(row =>
                    [...row.querySelectorAll('th, td')].map(cell =>
                        (cell.textContent || '').trim().slice(0, 300)
                    )
                )
            )
        """)
        return result.get("result", [])

    async def extract_links(self, engine: Any, page_id: str, pattern: str = "") -> list[dict[str, str]]:
        """Extract links, optionally filtered by URL pattern."""
        result = await engine.execute_on_page(page_id, "evaluate", expression="""
            [...document.querySelectorAll('a[href]')].map(a => ({
                text: (a.textContent || '').trim().slice(0, 100),
                href: a.href
            })).filter(l => l.text && l.href.startsWith('http'))
        """)
        links = result.get("result", [])
        if pattern:
            links = [l for l in links if re.search(pattern, l.get("href", ""), re.IGNORECASE)]
        return links

    async def take_screenshot(self, engine: Any, page_id: str, path: str = "") -> dict[str, Any]:
        """Take a full-page screenshot."""
        if not path:
            path = f"/tmp/horizon_workspace/page_{page_id}.png"
        return await engine.execute_on_page(page_id, "screenshot", path=path, full_page=True)
