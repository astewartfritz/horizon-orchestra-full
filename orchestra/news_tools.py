"""
orchestra/news_tools.py
────────────────────────
25 agent-callable tools for Orchestra's news & media connector layer.
Registers into agent_loop.py's tool registry.

Tools:
  news_headlines          Top headlines from all or specified sources
  news_search             Search across sources by keyword
  news_source_fetch       Fetch articles from one specific source
  news_rss_fetch          Fetch any RSS/Atom feed by URL
  news_source_list        List all available sources
  news_sources_by_category Sources by category (tech/finance/science/etc)
  news_guardian_search    The Guardian full-text search
  news_nytimes_search     NYT article search
  news_arxiv_search       arXiv preprint search
  news_arxiv_headlines    Latest arXiv papers by category
  news_hackernews_top     Hacker News top/best/new stories
  news_hackernews_search  Search Hacker News via Algolia
  news_reddit_headlines   Reddit hot posts by subreddit or topic
  news_reddit_search      Search Reddit
  news_pubmed_search      PubMed biomedical literature search
  news_multi_source       Headlines from all sources simultaneously
  news_trending           Articles sorted by social engagement score
  news_digest_build       Build a personalized digest for a user
  news_feed_profile_get   Get a user's feed profile
  news_feed_profile_set   Update a user's feed profile
  news_feed_profile_add_source   Add a source to preferred list
  news_feed_profile_remove_source Remove a source
  news_feed_profile_add_interest  Add a topic interest
  news_topic_watch        Fetch news for a custom topic query across sources
  news_source_summary     Summary of all available sources (count, categories)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any

from .news_connector import NewsConnector, Article
from .news_feed import FeedEngine, FeedProfile
from .news_sources import SOURCES, source_summary, get_sources_by_category, SourceCategory


# ──────────────────────────────────────────────
# Tool definitions (OpenAI function-calling format)
# ──────────────────────────────────────────────

NEWS_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "news_headlines",
            "description": "Fetch top headlines from news sources. Supports category filter and source selection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Category: general, tech, finance, science, world, health, sports, politics. Default: general."},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Source IDs to query. Omit for defaults."},
                    "limit": {"type": "integer", "description": "Max articles to return. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "Search for news articles by keyword across multiple sources simultaneously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Source IDs to search. Omit for defaults (newsapi, guardian, nytimes, hackernews, arxiv)."},
                    "from_date": {"type": "string", "description": "Start date ISO 8601 (YYYY-MM-DD). Default last 24h."},
                    "limit": {"type": "integer", "description": "Max articles per source. Default 10."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_source_fetch",
            "description": "Fetch all RSS feeds for a named news source (e.g. bbc, guardian, techcrunch, wsj).",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "Source ID from news_source_list."},
                    "limit": {"type": "integer", "description": "Max articles. Default 20."},
                },
                "required": ["source_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_rss_fetch",
            "description": "Fetch any RSS or Atom feed by URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full RSS/Atom feed URL."},
                    "source_name": {"type": "string", "description": "Display name for articles. Default: RSS Feed."},
                    "limit": {"type": "integer", "description": "Max articles. Default 20."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_source_list",
            "description": "List all available news sources with their IDs, categories, and capabilities.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_sources_by_category",
            "description": "Get sources filtered by category: wire, newspaper, tech, science, finance, aggregator, social, magazine, rss.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Source category."},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_guardian_search",
            "description": "Search The Guardian's 2M+ article archive by keyword, section, and date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "from_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_nytimes_search",
            "description": "Search the New York Times article archive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "from_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_arxiv_search",
            "description": "Search arXiv preprints. Great for AI/ML papers, physics, math, CS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "arXiv search query (e.g. 'large language model fine-tuning')."},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_arxiv_headlines",
            "description": "Latest arXiv preprints by category: ai, ml, nlp, robotics, math, physics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "ai | ml | nlp | robotics | math | physics | science. Default: ai."},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_hackernews_top",
            "description": "Get top/best/new stories from Hacker News.",
            "parameters": {
                "type": "object",
                "properties": {
                    "feed": {"type": "string", "description": "top | best | new. Default: top."},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_hackernews_search",
            "description": "Search Hacker News stories by keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_reddit_headlines",
            "description": "Get hot posts from Reddit. Specify subreddits or use a topic category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subreddits": {"type": "array", "items": {"type": "string"}, "description": "List of subreddit names. Omit for defaults."},
                    "category": {"type": "string", "description": "tech | world | science | finance | general. Used if subreddits not provided."},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_reddit_search",
            "description": "Search Reddit for posts by keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_pubmed_search",
            "description": "Search PubMed for biomedical research articles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_multi_source",
            "description": "Fetch headlines from ALL registered sources simultaneously. Returns a source-keyed dict.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit_per_source": {"type": "integer", "description": "Max articles per source. Default 5."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_trending",
            "description": "Get trending articles sorted by social engagement score (HN points, Reddit upvotes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_digest_build",
            "description": "Build a personalized ranked news digest for a user based on their feed profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_feed_profile_get",
            "description": "Get a user's news feed profile (sources, interests, preferences).",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_feed_profile_set",
            "description": "Create or fully replace a user's news feed profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "display_name": {"type": "string"},
                    "interests": {"type": "array", "items": {"type": "string"}, "description": "Topic interests: tech, ai, world, finance, science, health, politics, etc."},
                    "preferred_sources": {"type": "array", "items": {"type": "string"}},
                    "excluded_sources": {"type": "array", "items": {"type": "string"}},
                    "topic_queries": {"type": "array", "items": {"type": "string"}, "description": "Custom search queries always included in feed."},
                    "lookback_hours": {"type": "integer"},
                    "max_per_section": {"type": "integer"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_feed_profile_add_source",
            "description": "Add a source to a user's preferred sources list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["user_id", "source_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_feed_profile_remove_source",
            "description": "Remove a source from a user's preferred sources list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["user_id", "source_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_feed_profile_add_interest",
            "description": "Add a topic interest to a user's feed profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "interest": {"type": "string", "description": "Topic category or keyword."},
                },
                "required": ["user_id", "interest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_topic_watch",
            "description": "Search for a specific topic across all configured sources and return ranked results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to monitor, e.g. 'Kimi K2.5 release' or 'Strait of Hormuz'."},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_source_summary",
            "description": "Get a summary of all available news sources: total count, breakdown by category.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ──────────────────────────────────────────────
# Tool executor
# ──────────────────────────────────────────────

class NewsToolExecutor:
    """Dispatches all 25 news tool calls from the agent loop."""

    TOOL_NAMES = {d["function"]["name"] for d in NEWS_TOOL_DEFINITIONS}

    def __init__(self, connector: NewsConnector, feed_engine: FeedEngine,
                 feed_data_dir: str = "orchestra/data/feeds"):
        self.connector = connector
        self.feed_engine = feed_engine
        self.feed_data_dir = feed_data_dir

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self.TOOL_NAMES

    async def execute(self, tool_name: str, arguments: dict) -> str:
        handlers = {
            "news_headlines":                self._headlines,
            "news_search":                   self._search,
            "news_source_fetch":             self._source_fetch,
            "news_rss_fetch":                self._rss_fetch,
            "news_source_list":              self._source_list,
            "news_sources_by_category":      self._sources_by_category,
            "news_guardian_search":          self._guardian_search,
            "news_nytimes_search":           self._nytimes_search,
            "news_arxiv_search":             self._arxiv_search,
            "news_arxiv_headlines":          self._arxiv_headlines,
            "news_hackernews_top":           self._hn_top,
            "news_hackernews_search":        self._hn_search,
            "news_reddit_headlines":         self._reddit_headlines,
            "news_reddit_search":            self._reddit_search,
            "news_pubmed_search":            self._pubmed_search,
            "news_multi_source":             self._multi_source,
            "news_trending":                 self._trending,
            "news_digest_build":             self._digest_build,
            "news_feed_profile_get":         self._profile_get,
            "news_feed_profile_set":         self._profile_set,
            "news_feed_profile_add_source":  self._profile_add_source,
            "news_feed_profile_remove_source": self._profile_remove_source,
            "news_feed_profile_add_interest": self._profile_add_interest,
            "news_topic_watch":              self._topic_watch,
            "news_source_summary":           self._source_summary,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = await handler(arguments)
            return json.dumps(result, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _headlines(self, a: dict) -> dict:
        articles = await self.connector.headlines(
            category=a.get("category", "general"),
            sources=a.get("sources"),
            limit=a.get("limit", 10),
        )
        return {"articles": [art.to_dict() for art in articles], "count": len(articles)}

    async def _search(self, a: dict) -> dict:
        articles = await self.connector.search(
            query=a["query"], sources=a.get("sources"),
            from_date=a.get("from_date"), limit=a.get("limit", 10),
        )
        return {"articles": [art.to_dict() for art in articles], "count": len(articles)}

    async def _source_fetch(self, a: dict) -> dict:
        articles = await self.connector.fetch_rss_source(a["source_id"], a.get("limit", 20))
        return {"source_id": a["source_id"], "articles": [art.to_dict() for art in articles]}

    async def _rss_fetch(self, a: dict) -> dict:
        articles = await self.connector.rss.fetch_feed(
            a["url"], "rss", a.get("source_name", "RSS Feed"), a.get("limit", 20)
        )
        return {"url": a["url"], "articles": [art.to_dict() for art in articles]}

    async def _source_list(self, _: dict) -> dict:
        return {
            "sources": [
                {
                    "id": s.id, "name": s.name, "category": s.category.value,
                    "supports_search": s.supports_search,
                    "supports_rss": s.supports_rss, "auth_required": s.api_key_env,
                    "requires_paid": s.requires_paid,
                }
                for s in SOURCES.values()
            ]
        }

    async def _sources_by_category(self, a: dict) -> dict:
        try:
            cat = SourceCategory(a["category"].lower())
        except ValueError:
            return {"error": f"Unknown category: {a['category']}"}
        sources = get_sources_by_category(cat)
        return {"category": a["category"], "sources": [
            {"id": s.id, "name": s.name} for s in sources
        ]}

    async def _guardian_search(self, a: dict) -> dict:
        articles = await self.connector.guardian.search(
            a["query"], a.get("from_date"), a.get("limit", 10)
        )
        return {"articles": [art.to_dict() for art in articles]}

    async def _nytimes_search(self, a: dict) -> dict:
        articles = await self.connector.nytimes.search(
            a["query"], a.get("from_date"), a.get("limit", 10)
        )
        return {"articles": [art.to_dict() for art in articles]}

    async def _arxiv_search(self, a: dict) -> dict:
        articles = await self.connector.arxiv.search(a["query"], limit=a.get("limit", 10))
        return {"articles": [art.to_dict() for art in articles]}

    async def _arxiv_headlines(self, a: dict) -> dict:
        articles = await self.connector.arxiv.fetch_headlines(
            a.get("category", "ai"), a.get("limit", 10)
        )
        return {"articles": [art.to_dict() for art in articles]}

    async def _hn_top(self, a: dict) -> dict:
        feed = a.get("feed", "top")
        hn = self.connector.hackernews
        if feed == "best":
            articles = await hn.fetch_headlines("best", a.get("limit", 10))
        else:
            articles = await hn.fetch_headlines("tech", a.get("limit", 10))
        return {"feed": feed, "articles": [art.to_dict() for art in articles]}

    async def _hn_search(self, a: dict) -> dict:
        articles = await self.connector.hackernews.search(a["query"], limit=a.get("limit", 10))
        return {"articles": [art.to_dict() for art in articles]}

    async def _reddit_headlines(self, a: dict) -> dict:
        subs = a.get("subreddits")
        if subs:
            import httpx
            connector_with_subs = RedditConnector(subreddits=subs)
            articles = await connector_with_subs.fetch_headlines(
                a.get("category", "general"), a.get("limit", 10)
            )
        else:
            articles = await self.connector.reddit.fetch_headlines(
                a.get("category", "general"), a.get("limit", 10)
            )
        return {"articles": [art.to_dict() for art in articles]}

    async def _reddit_search(self, a: dict) -> dict:
        articles = await self.connector.reddit.search(a["query"], limit=a.get("limit", 10))
        return {"articles": [art.to_dict() for art in articles]}

    async def _pubmed_search(self, a: dict) -> dict:
        articles = await self.connector.pubmed.search(a["query"], limit=a.get("limit", 10))
        return {"articles": [art.to_dict() for art in articles]}

    async def _multi_source(self, a: dict) -> dict:
        result = await self.connector.multi_source_headlines(
            limit_per_source=a.get("limit_per_source", 5)
        )
        return {
            sid: [art.to_dict() for art in arts]
            for sid, arts in result.items()
        }

    async def _trending(self, a: dict) -> dict:
        # Fetch from social sources, sort by score
        articles = await self.connector.headlines(
            category="general",
            sources=["hackernews", "reddit"],
            limit=a.get("limit", 20),
        )
        sorted_arts = sorted(articles, key=lambda x: -x.score)
        return {"articles": [art.to_dict() for art in sorted_arts[:a.get("limit", 10)]]}

    async def _digest_build(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir)
        if not profile:
            profile = FeedProfile(user_id=a["user_id"])
        digest = await self.feed_engine.build_digest(profile)
        return {
            "user_id": digest.user_id,
            "title": digest.title,
            "date_label": digest.date_label,
            "total_articles": digest.total_articles,
            "sources_used": digest.sources_used,
            "sections": {
                sec: [art.to_dict() for art in arts]
                for sec, arts in digest.sections.items()
            },
            "trending": [art.to_dict() for art in digest.trending],
            "plain_text": digest.to_plain_text(),
        }

    async def _profile_get(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir)
        if not profile:
            return {"user_id": a["user_id"], "exists": False,
                    "message": "No profile found. Use news_feed_profile_set to create one."}
        return {"exists": True, **profile.to_dict()}

    async def _profile_set(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir) or FeedProfile(user_id=a["user_id"])
        for field in ["display_name", "interests", "preferred_sources",
                      "excluded_sources", "topic_queries", "lookback_hours", "max_per_section"]:
            if field in a:
                setattr(profile, field, a[field])
        profile.save(self.feed_data_dir)
        return {"success": True, "profile": profile.to_dict()}

    async def _profile_add_source(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir) or FeedProfile(user_id=a["user_id"])
        if a["source_id"] not in profile.preferred_sources:
            profile.preferred_sources.append(a["source_id"])
            profile.save(self.feed_data_dir)
        return {"success": True, "preferred_sources": profile.preferred_sources}

    async def _profile_remove_source(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir) or FeedProfile(user_id=a["user_id"])
        if a["source_id"] in profile.preferred_sources:
            profile.preferred_sources.remove(a["source_id"])
            profile.save(self.feed_data_dir)
        return {"success": True, "preferred_sources": profile.preferred_sources}

    async def _profile_add_interest(self, a: dict) -> dict:
        profile = FeedProfile.load(a["user_id"], self.feed_data_dir) or FeedProfile(user_id=a["user_id"])
        if a["interest"] not in profile.interests:
            profile.interests.append(a["interest"])
            profile.save(self.feed_data_dir)
        return {"success": True, "interests": profile.interests}

    async def _topic_watch(self, a: dict) -> dict:
        articles = await self.connector.search(
            query=a["topic"],
            sources=a.get("sources"),
            limit=a.get("limit", 15),
        )
        return {
            "topic": a["topic"],
            "articles": [art.to_dict() for art in articles],
            "count": len(articles),
        }

    async def _source_summary(self, _: dict) -> dict:
        return source_summary()


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────

def get_news_tools(
    keys: dict[str, str] = None,
    subreddits: list[str] = None,
    feed_data_dir: str = "orchestra/data/feeds",
) -> tuple[list[dict], NewsToolExecutor]:
    """
    Factory: returns (tool_definitions, executor) for agent_loop.py.

    Usage in agent_loop.py:
        from .news_tools import get_news_tools
        news_defs, news_executor = get_news_tools(keys=config["api_keys"])
        tools.extend(news_defs)
        tool_executors["news"] = news_executor
    """
    connector = NewsConnector(keys=keys, subreddits=subreddits)
    feed_engine = FeedEngine(connector)
    executor = NewsToolExecutor(connector, feed_engine, feed_data_dir)
    return NEWS_TOOL_DEFINITIONS, executor
