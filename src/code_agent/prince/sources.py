from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    id: int
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    source_type: str = "web"  # web, code, doc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title[:120],
            "url": self.url[:300],
            "snippet": self.snippet[:300],
            "source_type": self.source_type,
        }


class SourceTracker:
    def __init__(self):
        self._sources: list[Source] = []
        self._seen_urls: set[str] = set()

    def add(self, title: str, url: str, snippet: str = "", content: str = "", source_type: str = "web") -> int:
        if url in self._seen_urls:
            for s in self._sources:
                if s.url == url:
                    return s.id
        sid = len(self._sources) + 1
        self._sources.append(Source(id=sid, title=title, url=url, snippet=snippet, content=content, source_type=source_type))
        self._seen_urls.add(url)
        return sid

    def get(self, sid: int) -> Source | None:
        for s in self._sources:
            if s.id == sid:
                return s
        return None

    def all(self) -> list[Source]:
        return list(self._sources)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._sources]

    def format_citation(self, sid: int) -> str:
        return f"[{sid}]"

    def annotate_answer(self, answer: str) -> str:
        return re.sub(r'\[(\d+)\]', lambda m: f'<sup class="citation" data-id="{m.group(1)}">[{m.group(1)}]</sup>', answer)

    def render_html(self) -> str:
        if not self._sources:
            return ""
        html = '<div class="sources-section"><h4 class="sources-title">Sources</h4><div class="sources-list">'
        for s in self._sources:
            favicon = f'<img class="source-favicon" src="https://www.google.com/s2/favicons?domain={s.url.split("/")[2] if "//" in s.url else ""}&sz=16" alt="" onerror="this.style.display=\'none\'" loading="lazy">' if "//" in s.url else ""
            html += f'<a class="source-card" href="{s.url}" target="_blank" rel="noopener">'
            html += f'<span class="source-num">{s.id}</span>'
            html += f'<span class="source-body">{favicon}<span class="source-title">{s.title[:80]}</span>'
            html += f'<span class="source-url">{s.url[:60]}</span></span></a>'
        html += '</div></div>'
        return html

    def clear(self) -> None:
        self._sources.clear()
        self._seen_urls.clear()
