"""
orchestra/news_connector.py
─────────────────────────────
Publisher API adapters for Orchestra's news & media layer.

Each adapter implements the NewsAdapter interface:
  fetch_headlines(category, limit) -> list[Article]
  search(query, from_date, limit)  -> list[Article]

Adapters:
  NewsAPIAdapter     — newsapi.org (150k sources)
  NewsDataAdapter    — newsdata.io
  GuardianAdapter    — content.guardianapis.com
  NYTimesAdapter     — api.nytimes.com
  ArxivAdapter       — export.arxiv.org (no auth)
  HackerNewsAdapter  — hacker-news.firebaseio.com (no auth)
  RedditAdapter      — reddit.com JSON API (no auth for public)
  RSSAdapter         — universal RSS/Atom reader for all RSS sources
  PubMedAdapter      — eutils.ncbi.nlm.nih.gov
  NewsConnector      — unified façade over all adapters

All adapters degrade gracefully when API keys are missing.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx


# ──────────────────────────────────────────────
# Unified Article model
# ──────────────────────────────────────────────

@dataclass
class Article:
    title: str
    url: str
    source_id: str
    source_name: str
    snippet: str = ""
    author: str = ""
    published_at: Optional[str] = None
    category: str = ""
    image_url: Optional[str] = None
    score: float = 0.0          # Relevance / upvote score for ranking

    @property
    def fingerprint(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source_name,
            "source_id": self.source_id,
            "snippet": self.snippet,
            "author": self.author,
            "published_at": self.published_at,
            "category": self.category,
            "score": self.score,
        }


# ──────────────────────────────────────────────
# Base adapter
# ──────────────────────────────────────────────

class NewsAdapter(ABC):
    SOURCE_ID: str = ""
    SOURCE_NAME: str = ""

    def __init__(self, api_key: str = "", timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get(self, url: str, params: dict = None,
                   headers: dict = None) -> dict | list:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @abstractmethod
    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        pass

    @abstractmethod
    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        pass

    def _ts(self) -> str:
        """ISO timestamp 24h ago for default date ranges."""
        return (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────
# NewsAPI.org adapter
# ──────────────────────────────────────────────

class NewsAPIAdapter(NewsAdapter):
    SOURCE_ID = "newsapi"
    SOURCE_NAME = "NewsAPI"
    BASE = "https://newsapi.org/v2"

    CATEGORY_MAP = {
        "tech": "technology", "finance": "business", "science": "science",
        "health": "health", "sports": "sports", "politics": "general",
        "world": "general", "general": "general", "entertainment": "entertainment",
    }

    async def fetch_headlines(self, category: str = "general", limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        cat = self.CATEGORY_MAP.get(category.lower(), "general")
        data = await self._get(f"{self.BASE}/top-headlines", params={
            "category": cat, "pageSize": min(limit, 100),
            "apiKey": self.api_key, "language": "en",
        })
        return [self._to_article(a) for a in data.get("articles", [])[:limit]]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        params = {
            "q": query, "pageSize": min(limit, 100),
            "apiKey": self.api_key, "language": "en", "sortBy": "publishedAt",
            "from": from_date or self._ts(),
        }
        data = await self._get(f"{self.BASE}/everything", params=params)
        return [self._to_article(a) for a in data.get("articles", [])[:limit]]

    async def search_source(self, query: str, source_newsapi_id: str,
                             limit: int = 10) -> list[Article]:
        """Search within a specific NewsAPI source ID."""
        if not self.api_key:
            return []
        data = await self._get(f"{self.BASE}/everything", params={
            "q": query, "sources": source_newsapi_id,
            "pageSize": min(limit, 100), "apiKey": self.api_key,
            "sortBy": "publishedAt",
        })
        return [self._to_article(a) for a in data.get("articles", [])[:limit]]

    def _to_article(self, raw: dict) -> Article:
        src = raw.get("source", {})
        return Article(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            source_id=src.get("id") or "newsapi",
            source_name=src.get("name", "NewsAPI"),
            snippet=raw.get("description") or raw.get("content", "")[:300],
            author=raw.get("author", ""),
            published_at=raw.get("publishedAt"),
            image_url=raw.get("urlToImage"),
        )


# ──────────────────────────────────────────────
# NewsData.io adapter
# ──────────────────────────────────────────────

class NewsDataAdapter(NewsAdapter):
    SOURCE_ID = "newsdata"
    SOURCE_NAME = "NewsData.io"
    BASE = "https://newsdata.io/api/1"

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        data = await self._get(f"{self.BASE}/latest", params={
            "apikey": self.api_key, "language": "en",
            "category": category, "size": min(limit, 50),
        })
        return [self._to_article(a) for a in data.get("results", [])[:limit]]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        data = await self._get(f"{self.BASE}/latest", params={
            "apikey": self.api_key, "q": query, "language": "en",
            "size": min(limit, 50),
        })
        return [self._to_article(a) for a in data.get("results", [])[:limit]]

    def _to_article(self, raw: dict) -> Article:
        return Article(
            title=raw.get("title", ""),
            url=raw.get("link", ""),
            source_id="newsdata",
            source_name=raw.get("source_id", "NewsData"),
            snippet=raw.get("description") or raw.get("content", "")[:300],
            author=", ".join(raw.get("creator", []) or []),
            published_at=raw.get("pubDate"),
            category=", ".join(raw.get("category", []) or []),
            image_url=raw.get("image_url"),
        )


# ──────────────────────────────────────────────
# Guardian adapter
# ──────────────────────────────────────────────

class GuardianAdapter(NewsAdapter):
    SOURCE_ID = "guardian"
    SOURCE_NAME = "The Guardian"
    BASE = "https://content.guardianapis.com"

    SECTION_MAP = {
        "tech": "technology", "finance": "business", "science": "science",
        "world": "world", "politics": "politics", "sport": "sport",
        "general": "news",
    }

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        section = self.SECTION_MAP.get(category.lower(), "news")
        params = {
            "section": section, "page-size": min(limit, 200),
            "show-fields": "trailText,byline,thumbnail",
            "order-by": "newest",
        }
        if self.api_key:
            params["api-key"] = self.api_key
        else:
            params["api-key"] = "test"  # Guardian provides a free test key

        data = await self._get(f"{self.BASE}/search", params=params)
        results = data.get("response", {}).get("results", [])
        return [self._to_article(a) for a in results[:limit]]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        params = {
            "q": query, "page-size": min(limit, 200),
            "show-fields": "trailText,byline,thumbnail",
            "order-by": "relevance",
            "api-key": self.api_key or "test",
        }
        if from_date:
            params["from-date"] = from_date[:10]
        data = await self._get(f"{self.BASE}/search", params=params)
        results = data.get("response", {}).get("results", [])
        return [self._to_article(a) for a in results[:limit]]

    def _to_article(self, raw: dict) -> Article:
        fields = raw.get("fields", {})
        return Article(
            title=raw.get("webTitle", ""),
            url=raw.get("webUrl", ""),
            source_id="guardian",
            source_name="The Guardian",
            snippet=fields.get("trailText", "")[:300],
            author=fields.get("byline", ""),
            published_at=raw.get("webPublicationDate"),
            category=raw.get("sectionName", ""),
            image_url=fields.get("thumbnail"),
        )


# ──────────────────────────────────────────────
# New York Times adapter
# ──────────────────────────────────────────────

class NYTimesAdapter(NewsAdapter):
    SOURCE_ID = "nytimes"
    SOURCE_NAME = "The New York Times"
    BASE = "https://api.nytimes.com/svc"

    SECTION_MAP = {
        "tech": "technology", "finance": "business",
        "world": "world", "science": "science",
        "health": "health", "sports": "sports",
        "politics": "politics", "general": "home",
    }

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        section = self.SECTION_MAP.get(category.lower(), "home")
        data = await self._get(
            f"{self.BASE}/topstories/v2/{section}.json",
            params={"api-key": self.api_key}
        )
        results = data.get("results", [])
        return [self._to_article(a) for a in results[:limit]]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        if not self.api_key:
            return []
        params = {
            "q": query, "api-key": self.api_key,
            "sort": "newest", "fl": "headline,abstract,web_url,byline,pub_date,section_name",
        }
        if from_date:
            params["begin_date"] = from_date[:10].replace("-", "")
        data = await self._get(
            f"{self.BASE}/search/v2/articlesearch.json", params=params
        )
        docs = data.get("response", {}).get("docs", [])
        return [self._to_search_article(d) for d in docs[:limit]]

    def _to_article(self, raw: dict) -> Article:
        multimedia = raw.get("multimedia", [{}])
        img = multimedia[0].get("url") if multimedia else None
        return Article(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            source_id="nytimes",
            source_name="New York Times",
            snippet=raw.get("abstract", "")[:300],
            author=raw.get("byline", ""),
            published_at=raw.get("published_date"),
            category=raw.get("section", ""),
            image_url=img,
        )

    def _to_search_article(self, raw: dict) -> Article:
        headline = raw.get("headline", {})
        byline = raw.get("byline", {})
        return Article(
            title=headline.get("main", ""),
            url=raw.get("web_url", ""),
            source_id="nytimes",
            source_name="New York Times",
            snippet=raw.get("abstract", "")[:300],
            author=byline.get("original", ""),
            published_at=raw.get("pub_date"),
            category=raw.get("section_name", ""),
        )


# ──────────────────────────────────────────────
# arXiv adapter (no auth)
# ──────────────────────────────────────────────

class ArxivAdapter(NewsAdapter):
    SOURCE_ID = "arxiv"
    SOURCE_NAME = "arXiv"
    BASE = "https://export.arxiv.org/api/query"

    CATEGORY_MAP = {
        "ai": "cs.AI", "ml": "cs.LG", "nlp": "cs.CL",
        "robotics": "cs.RO", "math": "math", "physics": "physics",
        "general": "cs.AI", "tech": "cs.AI", "science": "cs",
    }

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        cat = self.CATEGORY_MAP.get(category.lower(), "cs.AI")
        return await self._query(f"cat:{cat}", limit)

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        return await self._query(f"all:{query}", limit)

    async def _query(self, search_query: str, limit: int) -> list[Article]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.BASE, params={
                "search_query": search_query,
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            })
            resp.raise_for_status()
        return self._parse_atom(resp.text)

    def _parse_atom(self, xml_text: str) -> list[Article]:
        NS = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        root = ET.fromstring(xml_text)
        articles = []
        for entry in root.findall("atom:entry", NS):
            title = (entry.findtext("atom:title", "", NS) or "").strip()
            url = entry.findtext("atom:id", "", NS)
            summary = (entry.findtext("atom:summary", "", NS) or "")[:400]
            published = entry.findtext("atom:published", "", NS)
            authors = [
                a.findtext("atom:name", "", NS)
                for a in entry.findall("atom:author", NS)
            ]
            articles.append(Article(
                title=title, url=url,
                source_id="arxiv", source_name="arXiv",
                snippet=summary.strip(),
                author=", ".join(authors[:3]),
                published_at=published,
                category="preprint",
            ))
        return articles


# ──────────────────────────────────────────────
# Hacker News adapter (no auth)
# ──────────────────────────────────────────────

class HackerNewsAdapter(NewsAdapter):
    SOURCE_ID = "hackernews"
    SOURCE_NAME = "Hacker News"
    BASE = "https://hacker-news.firebaseio.com/v0"
    ALGOLIA = "https://hn.algolia.com/api/v1"

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        feed = "topstories" if category in ("general", "tech") else "beststories"
        ids = await self._get(f"{self.BASE}/{feed}.json")
        items = await asyncio.gather(*[
            self._get(f"{self.BASE}/item/{i}.json") for i in ids[:limit]
        ])
        return [self._to_article(i) for i in items if i and i.get("type") == "story"]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        data = await self._get(f"{self.ALGOLIA}/search", params={
            "query": query, "hitsPerPage": min(limit, 100),
            "tags": "story",
        })
        return [self._algolia_to_article(h) for h in data.get("hits", [])[:limit]]

    def _to_article(self, raw: dict) -> Article:
        return Article(
            title=raw.get("title", ""),
            url=raw.get("url") or f"https://news.ycombinator.com/item?id={raw.get('id')}",
            source_id="hackernews",
            source_name="Hacker News",
            snippet=f"{raw.get('score', 0)} points | {raw.get('descendants', 0)} comments",
            author=raw.get("by", ""),
            published_at=datetime.fromtimestamp(
                raw.get("time", 0), tz=timezone.utc
            ).isoformat() if raw.get("time") else None,
            category="tech",
            score=float(raw.get("score", 0)),
        )

    def _algolia_to_article(self, raw: dict) -> Article:
        return Article(
            title=raw.get("title", ""),
            url=raw.get("url") or f"https://news.ycombinator.com/item?id={raw.get('objectID')}",
            source_id="hackernews",
            source_name="Hacker News",
            snippet=f"{raw.get('points', 0)} points | {raw.get('num_comments', 0)} comments",
            author=raw.get("author", ""),
            published_at=raw.get("created_at"),
            category="tech",
            score=float(raw.get("points", 0)),
        )


# ──────────────────────────────────────────────
# Reddit adapter (public JSON, no auth)
# ──────────────────────────────────────────────

class RedditAdapter(NewsAdapter):
    SOURCE_ID = "reddit"
    SOURCE_NAME = "Reddit"

    DEFAULT_SUBS = [
        "worldnews", "technology", "science", "MachineLearning",
        "artificial", "LocalLLaMA", "singularity", "geopolitics",
    ]

    def __init__(self, api_key: str = "", subreddits: list[str] = None, **kwargs):
        super().__init__(api_key, **kwargs)
        self.subreddits = subreddits or self.DEFAULT_SUBS

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        sub_map = {
            "tech": ["technology", "MachineLearning", "artificial", "LocalLLaMA"],
            "world": ["worldnews", "geopolitics", "europe", "MiddleEast"],
            "science": ["science", "physics", "biology"],
            "finance": ["investing", "wallstreetbets", "Economics"],
            "general": self.subreddits,
        }
        subs = sub_map.get(category.lower(), self.subreddits)
        tasks = [self._fetch_subreddit(s, limit // len(subs) + 1) for s in subs[:5]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles = []
        for r in results:
            if isinstance(r, list):
                articles.extend(r)
        return sorted(articles, key=lambda a: -a.score)[:limit]

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "Orchestra/1.0 (news-connector)"},
        ) as client:
            resp = await client.get(
                "https://www.reddit.com/search.json",
                params={"q": query, "sort": "new", "limit": min(limit, 100), "type": "link"},
            )
            resp.raise_for_status()
            data = resp.json()
        posts = data.get("data", {}).get("children", [])
        return [self._to_article(p["data"]) for p in posts[:limit]]

    async def _fetch_subreddit(self, subreddit: str, limit: int) -> list[Article]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "Orchestra/1.0"},
        ) as client:
            resp = await client.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json",
                params={"limit": min(limit, 25)},
            )
            resp.raise_for_status()
            data = resp.json()
        posts = data.get("data", {}).get("children", [])
        return [self._to_article(p["data"]) for p in posts]

    def _to_article(self, raw: dict) -> Article:
        url = raw.get("url", "")
        if url.startswith("/r/"):
            url = f"https://www.reddit.com{url}"
        return Article(
            title=raw.get("title", ""),
            url=url,
            source_id="reddit",
            source_name=f"r/{raw.get('subreddit', 'reddit')}",
            snippet=f"{raw.get('score', 0)} upvotes | {raw.get('num_comments', 0)} comments",
            author=raw.get("author", ""),
            published_at=datetime.fromtimestamp(
                raw.get("created_utc", 0), tz=timezone.utc
            ).isoformat() if raw.get("created_utc") else None,
            category=raw.get("subreddit", ""),
            score=float(raw.get("score", 0)),
        )


# ──────────────────────────────────────────────
# PubMed adapter
# ──────────────────────────────────────────────

class PubMedAdapter(NewsAdapter):
    SOURCE_ID = "pubmed"
    SOURCE_NAME = "PubMed"
    BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        term_map = {
            "ai": "artificial intelligence[MeSH]",
            "health": "public health[MeSH]",
            "science": "biomedical research[MeSH]",
            "general": "medicine[MeSH]",
        }
        return await self.search(term_map.get(category.lower(), "medicine"), limit=limit)

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        params = {
            "db": "pubmed", "term": query, "retmax": min(limit, 100),
            "retmode": "json", "sort": "pub_date",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        search_data = await self._get(f"{self.BASE}/esearch.fcgi", params=params)
        ids = search_data.get("esearchresult", {}).get("idlist", [])[:limit]
        if not ids:
            return []
        summary_data = await self._get(f"{self.BASE}/esummary.fcgi", params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "json",
        })
        articles = []
        result = summary_data.get("result", {})
        for pmid in ids:
            item = result.get(pmid, {})
            if not item:
                continue
            authors = [a.get("name", "") for a in item.get("authors", [])[:3]]
            articles.append(Article(
                title=item.get("title", ""),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source_id="pubmed",
                source_name="PubMed",
                snippet=", ".join(item.get("elocationid", []))[:200],
                author=", ".join(authors),
                published_at=item.get("pubdate"),
                category="biomedical",
            ))
        return articles


# ──────────────────────────────────────────────
# Universal RSS adapter
# ──────────────────────────────────────────────

class RSSAdapter(NewsAdapter):
    """
    Universal RSS/Atom reader. Supports any feed URL.
    Used as fallback for all sources that provide RSS.
    """
    SOURCE_ID = "rss"
    SOURCE_NAME = "RSS"

    NS_ATOM = "http://www.w3.org/2005/Atom"
    NS_DC = "http://purl.org/dc/elements/1.1/"
    NS_MEDIA = "http://search.yahoo.com/mrss/"

    async def fetch_feed(self, feed_url: str, source_id: str,
                          source_name: str, limit: int = 20) -> list[Article]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "Orchestra/1.0 (news-reader)"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return []

        # Detect RSS vs Atom
        if root.tag == f"{{{self.NS_ATOM}}}feed":
            return self._parse_atom(root, source_id, source_name, limit)
        return self._parse_rss(root, source_id, source_name, limit)

    def _parse_rss(self, root: ET.Element, sid: str, sname: str,
                    limit: int) -> list[Article]:
        channel = root.find("channel")
        if channel is None:
            channel = root
        articles = []
        for item in list(channel.findall("item"))[:limit]:
            title = item.findtext("title", "").strip()
            url = item.findtext("link", "").strip()
            snippet = item.findtext("description", "")
            snippet = re.sub(r"<[^>]+>", "", snippet)[:300]
            author = (
                item.findtext(f"{{{self.NS_DC}}}creator")
                or item.findtext("author", "")
            )
            pub = item.findtext("pubDate") or item.findtext("dc:date")
            media = item.find(f"{{{self.NS_MEDIA}}}thumbnail")
            img = media.get("url") if media is not None else None
            if title and url:
                articles.append(Article(
                    title=title, url=url,
                    source_id=sid, source_name=sname,
                    snippet=snippet.strip(), author=author or "",
                    published_at=pub, image_url=img,
                ))
        return articles

    def _parse_atom(self, root: ET.Element, sid: str, sname: str,
                     limit: int) -> list[Article]:
        NS = self.NS_ATOM
        articles = []
        for entry in list(root.findall(f"{{{NS}}}entry"))[:limit]:
            title = (entry.findtext(f"{{{NS}}}title") or "").strip()
            # Atom links: find rel=alternate or first link
            url = ""
            for link in entry.findall(f"{{{NS}}}link"):
                if link.get("rel", "alternate") == "alternate":
                    url = link.get("href", "")
                    break
            if not url:
                url = (entry.findtext(f"{{{NS}}}id") or "")
            summary = re.sub(r"<[^>]+>",
                              "",
                              (entry.findtext(f"{{{NS}}}summary") or ""))[:300]
            pub = (entry.findtext(f"{{{NS}}}published")
                   or entry.findtext(f"{{{NS}}}updated"))
            author_el = entry.find(f"{{{NS}}}author")
            author = ""
            if author_el is not None:
                author = author_el.findtext(f"{{{NS}}}name", "")
            if title and url:
                articles.append(Article(
                    title=title, url=url,
                    source_id=sid, source_name=sname,
                    snippet=summary.strip(), author=author,
                    published_at=pub,
                ))
        return articles

    async def fetch_headlines(self, category: str = "general",
                              limit: int = 10) -> list[Article]:
        return []  # RSSAdapter must be called with explicit feed URLs

    async def search(self, query: str, from_date: Optional[str] = None,
                     limit: int = 10) -> list[Article]:
        return []  # RSS doesn't support search — use NewsAPI fallback


# ──────────────────────────────────────────────
# Unified NewsConnector façade
# ──────────────────────────────────────────────

class NewsConnector:
    """
    Unified façade over all news adapters.
    Automatically selects the best available adapter per source
    and falls back to RSS when API keys are unavailable.
    """

    def __init__(self, keys: dict[str, str] = None, subreddits: list[str] = None):
        keys = keys or {}
        k = lambda name: keys.get(name) or os.environ.get(name, "")

        self.newsapi    = NewsAPIAdapter(api_key=k("NEWSAPI_KEY"))
        self.newsdata   = NewsDataAdapter(api_key=k("NEWSDATA_KEY"))
        self.guardian   = GuardianAdapter(api_key=k("GUARDIAN_API_KEY"))
        self.nytimes    = NYTimesAdapter(api_key=k("NYT_API_KEY"))
        self.arxiv      = ArxivAdapter()
        self.hackernews = HackerNewsAdapter()
        self.reddit     = RedditAdapter(subreddits=subreddits)
        self.pubmed     = PubMedAdapter(api_key=k("PUBMED_API_KEY"))
        self.rss        = RSSAdapter()

        # Map source_id → adapter
        self._adapters: dict[str, NewsAdapter] = {
            "newsapi":     self.newsapi,
            "newsdata":    self.newsdata,
            "guardian":    self.guardian,
            "nytimes":     self.nytimes,
            "arxiv":       self.arxiv,
            "hackernews":  self.hackernews,
            "reddit":      self.reddit,
            "pubmed":      self.pubmed,
        }

    # ── Core API ──────────────────────────────────────────────────────────────

    async def headlines(self, category: str = "general",
                         sources: list[str] = None,
                         limit: int = 10) -> list[Article]:
        """Fetch headlines from multiple sources in parallel."""
        from .news_sources import SOURCES, get_rss_sources

        if sources is None:
            # Default: top aggregators + key publications
            sources = ["newsapi", "guardian", "hackernews", "reddit"]

        tasks = []
        for source_id in sources:
            adapter = self._adapters.get(source_id)
            if adapter:
                tasks.append(self._safe_fetch(adapter, category, limit))
            else:
                # Fall back to RSS for this source
                src = SOURCES.get(source_id)
                if src and src.supports_rss and src.rss_urls:
                    for url in src.rss_urls[:1]:  # Primary feed only
                        tasks.append(self._safe_rss(url, src.id, src.name, limit))

        results = await asyncio.gather(*tasks)
        articles = self._merge_deduplicate(results, limit * len(sources))
        return articles[:limit]

    async def search(self, query: str,
                      sources: list[str] = None,
                      from_date: Optional[str] = None,
                      limit: int = 10) -> list[Article]:
        """Search across multiple sources in parallel."""
        if sources is None:
            sources = ["newsapi", "guardian", "nytimes", "hackernews", "arxiv"]

        tasks = [
            self._safe_search(self._adapters[sid], query, from_date, limit)
            for sid in sources if sid in self._adapters
        ]
        results = await asyncio.gather(*tasks)
        articles = self._merge_deduplicate(results, limit * len(sources))
        return sorted(articles, key=lambda a: a.published_at or "", reverse=True)[:limit]

    async def fetch_rss_source(self, source_id: str, limit: int = 20) -> list[Article]:
        """Fetch all RSS feeds for a registered source."""
        from .news_sources import SOURCES
        src = SOURCES.get(source_id)
        if not src or not src.supports_rss:
            return []
        tasks = [
            self._safe_rss(url, src.id, src.name, limit)
            for url in src.rss_urls
        ]
        results = await asyncio.gather(*tasks)
        return self._merge_deduplicate(results, limit)

    async def multi_source_headlines(self, limit_per_source: int = 5) -> dict[str, list[Article]]:
        """Fetch headlines from ALL sources simultaneously. Returns dict keyed by source_id."""
        from .news_sources import SOURCES

        async def _fetch_one(source_id: str, src) -> tuple[str, list[Article]]:
            adapter = self._adapters.get(source_id)
            if adapter:
                articles = await self._safe_fetch(adapter, "general", limit_per_source)
            elif src.supports_rss and src.rss_urls:
                articles = await self._safe_rss(src.rss_urls[0], src.id, src.name, limit_per_source)
            else:
                articles = []
            return source_id, articles

        tasks = [_fetch_one(sid, src) for sid, src in SOURCES.items()]
        results = await asyncio.gather(*tasks)
        return {sid: articles for sid, articles in results}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _safe_fetch(self, adapter: NewsAdapter, category: str,
                           limit: int) -> list[Article]:
        try:
            return await adapter.fetch_headlines(category, limit)
        except Exception:
            return []

    async def _safe_search(self, adapter: NewsAdapter, query: str,
                            from_date: Optional[str], limit: int) -> list[Article]:
        try:
            return await adapter.search(query, from_date, limit)
        except Exception:
            return []

    async def _safe_rss(self, feed_url: str, source_id: str,
                         source_name: str, limit: int) -> list[Article]:
        try:
            return await self.rss.fetch_feed(feed_url, source_id, source_name, limit)
        except Exception:
            return []

    def _merge_deduplicate(self, result_lists: list, max_total: int) -> list[Article]:
        seen: set[str] = set()
        merged: list[Article] = []
        for articles in result_lists:
            if isinstance(articles, list):
                for a in articles:
                    if a.fingerprint not in seen and a.title and a.url:
                        seen.add(a.fingerprint)
                        merged.append(a)
        return merged[:max_total]
