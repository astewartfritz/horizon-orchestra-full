"""
orchestra/news_briefing_bridge.py
───────────────────────────────────
Bridges the NewsConnector into BriefingMonitor.
Replaces the Sonar-only search with a multi-source search that:
  1. Queries all configured news sources in parallel
  2. Merges and deduplicates results
  3. Falls back to Sonar Pro for topics with no API coverage

Drop-in replacement for SonarSearchProvider inside briefing_monitor.py.
Just swap the search provider:

    # In briefing_monitor.py:
    from .news_briefing_bridge import MultiSourceSearchProvider
    self.search = MultiSourceSearchProvider(sonar_key, news_keys)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from .news_connector import NewsConnector, Article


@dataclass
class NewsItem:
    """
    Lightweight news item returned by search providers.
    Compatible with BriefingMonitor's NewsItem interface — can be used
    as a drop-in when briefing_monitor is present, or standalone.
    """
    title: str
    snippet: str
    url: str
    source: str
    topic_name: str
    published_at: Optional[str] = None
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "source": self.source,
            "topic_name": self.topic_name,
            "published_at": self.published_at,
            "score": self.score,
        }


class MultiSourceSearchProvider:
    """
    Replaces SonarSearchProvider with a parallel multi-source search.
    Queries NewsAPI + Guardian + NYT + arXiv + HN + Reddit + RSS in parallel,
    then falls back to Sonar for any topic that returns < 2 results.
    """

    def __init__(self, sonar_key: str = "", news_keys: dict[str, str] = None,
                 subreddits: list[str] = None):
        self.connector = NewsConnector(keys=news_keys or {}, subreddits=subreddits)
        self.sonar_key = sonar_key

        # Sonar fallback (lazy import to avoid circular deps)
        self._sonar = None
        if sonar_key:
            try:
                from .briefing_monitor import SonarSearchProvider
                self._sonar = SonarSearchProvider(sonar_key)
            except Exception:
                pass

    async def search(self, query: str, max_results: int = 5) -> list[NewsItem]:
        """
        Primary: multi-source search via NewsConnector.
        Fallback: Sonar Pro if results are sparse.
        """
        # Primary: search across all API-enabled sources
        primary_sources = [
            "newsapi", "guardian", "nytimes",
            "hackernews", "arxiv", "reddit",
        ]

        articles = await self.connector.search(
            query=query,
            sources=primary_sources,
            from_date=(
                datetime.now(timezone.utc) - timedelta(hours=36)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            limit=max_results + 5,
        )

        # Also search RSS sources for the query topic
        rss_articles = await self._rss_topic_search(query, max_results)
        articles = self._merge_deduplicate(articles + rss_articles)

        if len(articles) >= 2:
            return [self._article_to_news_item(a, query) for a in articles[:max_results]]

        # Fallback to Sonar
        if self._sonar:
            return await self._sonar.search(query, max_results)

        return [self._article_to_news_item(a, query) for a in articles[:max_results]]

    async def _rss_topic_search(self, query: str, limit: int) -> list[Article]:
        """
        Fetch RSS feeds for sources likely to cover the query topic.
        Uses keyword matching on topic to select relevant RSS feeds.
        """
        from .news_sources import SOURCES

        query_lower = query.lower()
        relevant_rss: list[tuple[str, str, str]] = []  # (url, source_id, source_name)

        # Select RSS feeds based on topic keywords
        for src in SOURCES.values():
            if not src.supports_rss or not src.rss_urls:
                continue

            # Match topic to appropriate source
            is_relevant = True  # Include all by default for breaking news
            if any(k in query_lower for k in ("arxiv", "preprint", "paper", "research")):
                is_relevant = src.id in ("arxiv", "nature", "pubmed")
            elif any(k in query_lower for k in ("stock", "market", "earnings", "trade")):
                is_relevant = src.id in ("wsj", "ft", "marketwatch", "bloomberg_wire", "reuters")
            elif any(k in query_lower for k in ("tech", "ai", "llm", "software")):
                is_relevant = src.id in ("techcrunch", "theverge", "arstechnica", "wired",
                                          "mit_tech_review", "hackernews", "reuters")

            if is_relevant:
                # Use primary feed URL
                relevant_rss.append((src.rss_urls[0], src.id, src.name))

        # Fetch top 5 relevant RSS feeds in parallel
        tasks = [
            self.connector.rss.fetch_feed(url, sid, sname, 10)
            for url, sid, sname in relevant_rss[:5]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles = []
        for r in results:
            if isinstance(r, list):
                # Filter to articles that contain query keywords
                for a in r:
                    text = (a.title + " " + a.snippet).lower()
                    if any(word.lower() in text for word in query.split()[:3]):
                        articles.append(a)
        return articles[:limit]

    def _article_to_news_item(self, article: Article, query: str) -> NewsItem:
        return NewsItem(
            title=article.title,
            snippet=article.snippet or article.title,
            url=article.url,
            source=article.source_name,
            topic_name=query,
            published_at=article.published_at,
        )

    def _merge_deduplicate(self, articles: list[Article]) -> list[Article]:
        seen: set[str] = set()
        merged = []
        for a in articles:
            if a.fingerprint not in seen and a.title and a.url:
                seen.add(a.fingerprint)
                merged.append(a)
        return merged
