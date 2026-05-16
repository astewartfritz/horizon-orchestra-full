"""
tests/test_news.py
───────────────────
Full test suite for Orchestra's news & media connector layer.

Coverage:
  - news_sources.py: registry, helpers, category queries
  - news_connector.py: Article model, RSS parsing, deduplication, adapters (mocked)
  - news_feed.py: FeedProfile persistence, ranking, sectioning
  - news_tools.py: all 25 tool handlers, factory, can_handle
  - news_briefing_bridge.py: article → NewsItem conversion, deduplication
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from orchestra.news_sources import (
    SOURCES, SourceCategory, AuthType,
    get_source, get_sources_by_category, get_rss_sources,
    get_api_sources, get_free_sources, list_all_source_ids, source_summary,
)
from orchestra.news_connector import (
    Article, NewsConnector, NewsAPIAdapter, GuardianAdapter,
    NYTimesAdapter, ArxivAdapter, HackerNewsAdapter, RedditAdapter,
    PubMedAdapter, RSSAdapter,
)
from orchestra.news_feed import FeedProfile, FeedEngine, Digest, SOURCE_AUTHORITY
from orchestra.news_tools import (
    NEWS_TOOL_DEFINITIONS, NewsToolExecutor, get_news_tools,
)
from orchestra.news_briefing_bridge import MultiSourceSearchProvider


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def make_article(title="Test headline", url="https://example.com/1",
                 source_id="newsapi", source_name="TestSource",
                 snippet="snippet", score=0.0, published_at=None,
                 category="tech"):
    return Article(
        title=title, url=url, source_id=source_id, source_name=source_name,
        snippet=snippet, score=score,
        published_at=published_at or datetime.now(timezone.utc).isoformat(),
        category=category,
    )

def make_connector_with_mocks():
    connector = NewsConnector.__new__(NewsConnector)
    connector.newsapi    = AsyncMock()
    connector.newsdata   = AsyncMock()
    connector.guardian   = AsyncMock()
    connector.nytimes    = AsyncMock()
    connector.arxiv      = AsyncMock()
    connector.hackernews = AsyncMock()
    connector.reddit     = AsyncMock()
    connector.pubmed     = AsyncMock()
    connector.rss        = AsyncMock()
    connector._adapters  = {
        "newsapi":    connector.newsapi,
        "guardian":   connector.guardian,
        "nytimes":    connector.nytimes,
        "arxiv":      connector.arxiv,
        "hackernews": connector.hackernews,
        "reddit":     connector.reddit,
        "pubmed":     connector.pubmed,
    }
    return connector


# ──────────────────────────────────────────────
# news_sources.py tests
# ──────────────────────────────────────────────

class TestNewsSources(unittest.TestCase):

    def test_all_sources_have_required_fields(self):
        for sid, src in SOURCES.items():
            self.assertEqual(src.id, sid, f"{sid} id mismatch")
            self.assertIsInstance(src.name, str)
            self.assertIsInstance(src.category, SourceCategory)
            self.assertIsInstance(src.auth_type, AuthType)

    def test_source_count(self):
        self.assertGreaterEqual(len(SOURCES), 25)

    def test_get_source_existing(self):
        src = get_source("guardian")
        self.assertIsNotNone(src)
        self.assertEqual(src.name, "The Guardian")

    def test_get_source_nonexistent(self):
        self.assertIsNone(get_source("nonexistent_source"))

    def test_get_sources_by_category_tech(self):
        tech = get_sources_by_category(SourceCategory.TECH)
        self.assertGreater(len(tech), 0)
        for s in tech:
            self.assertEqual(s.category, SourceCategory.TECH)

    def test_get_sources_by_category_wire(self):
        wires = get_sources_by_category(SourceCategory.WIRE)
        ids = [s.id for s in wires]
        self.assertIn("reuters", ids)
        self.assertIn("ap", ids)

    def test_get_rss_sources(self):
        rss = get_rss_sources()
        self.assertGreater(len(rss), 10)
        for s in rss:
            self.assertTrue(s.supports_rss)
            self.assertGreater(len(s.rss_urls), 0)

    def test_get_api_sources(self):
        api = get_api_sources()
        self.assertGreater(len(api), 0)
        for s in api:
            self.assertNotEqual(s.auth_type, AuthType.NONE)

    def test_get_free_sources(self):
        free = get_free_sources()
        for s in free:
            self.assertFalse(s.requires_paid)

    def test_list_all_source_ids(self):
        ids = list_all_source_ids()
        self.assertIn("guardian", ids)
        self.assertIn("nytimes", ids)
        self.assertIn("hackernews", ids)

    def test_source_summary(self):
        summary = source_summary()
        self.assertIn("total", summary)
        self.assertIn("by_category", summary)
        self.assertGreaterEqual(summary["total"], 25)
        self.assertGreater(summary["rss_enabled"], 10)

    def test_bbc_has_rss(self):
        bbc = get_source("bbc")
        self.assertTrue(bbc.supports_rss)
        self.assertGreater(len(bbc.rss_urls), 0)

    def test_arxiv_is_free(self):
        arxiv = get_source("arxiv")
        self.assertFalse(arxiv.requires_paid)
        self.assertEqual(arxiv.auth_type, AuthType.NONE)

    def test_hackernews_no_auth(self):
        hn = get_source("hackernews")
        self.assertEqual(hn.auth_type, AuthType.NONE)

    def test_guardian_has_api_key_env(self):
        g = get_source("guardian")
        self.assertEqual(g.api_key_env, "GUARDIAN_API_KEY")

    def test_categories_have_multiple_sources(self):
        cats_with_sources = {
            SourceCategory.WIRE, SourceCategory.NEWSPAPER,
            SourceCategory.TECH, SourceCategory.FINANCE,
        }
        for cat in cats_with_sources:
            srcs = get_sources_by_category(cat)
            self.assertGreater(len(srcs), 0, f"No sources for {cat}")


# ──────────────────────────────────────────────
# Article model tests
# ──────────────────────────────────────────────

class TestArticle(unittest.TestCase):

    def test_fingerprint_unique_per_url(self):
        a1 = make_article(url="https://example.com/1")
        a2 = make_article(url="https://example.com/2")
        self.assertNotEqual(a1.fingerprint, a2.fingerprint)

    def test_fingerprint_consistent(self):
        a = make_article(url="https://example.com/1")
        self.assertEqual(a.fingerprint, a.fingerprint)

    def test_fingerprint_deduplication(self):
        a1 = make_article(url="https://example.com/same")
        a2 = make_article(url="https://example.com/same", title="Different title")
        self.assertEqual(a1.fingerprint, a2.fingerprint)

    def test_to_dict(self):
        a = make_article()
        d = a.to_dict()
        self.assertIn("title", d)
        self.assertIn("url", d)
        self.assertIn("source", d)
        self.assertIn("snippet", d)

    def test_article_fields(self):
        a = make_article(title="Breaking News", source_name="Reuters", score=100.0)
        self.assertEqual(a.title, "Breaking News")
        self.assertEqual(a.source_name, "Reuters")
        self.assertEqual(a.score, 100.0)


# ──────────────────────────────────────────────
# Adapter tests (mocked HTTP)
# ──────────────────────────────────────────────

class TestNewsAPIAdapter(unittest.TestCase):

    def test_returns_empty_without_key(self):
        adapter = NewsAPIAdapter(api_key="")
        result = asyncio.run(adapter.fetch_headlines())
        self.assertEqual(result, [])

    def test_returns_empty_search_without_key(self):
        adapter = NewsAPIAdapter(api_key="")
        result = asyncio.run(adapter.search("test query"))
        self.assertEqual(result, [])

    def test_to_article_conversion(self):
        adapter = NewsAPIAdapter(api_key="key")
        raw = {
            "title": "Test", "url": "https://test.com",
            "description": "desc", "author": "auth",
            "publishedAt": "2026-04-08T00:00:00Z",
            "source": {"id": "bbc", "name": "BBC"},
            "urlToImage": None, "content": None,
        }
        article = adapter._to_article(raw)
        self.assertEqual(article.title, "Test")
        self.assertEqual(article.source_id, "bbc")


class TestGuardianAdapter(unittest.TestCase):

    def test_category_map_covers_common_cats(self):
        adapter = GuardianAdapter()
        for cat in ["tech", "finance", "world", "science"]:
            self.assertIn(cat, adapter.SECTION_MAP)

    def test_to_article_conversion(self):
        adapter = GuardianAdapter()
        raw = {
            "webTitle": "Test Article",
            "webUrl": "https://guardian.com/test",
            "webPublicationDate": "2026-04-08T00:00:00Z",
            "sectionName": "Technology",
            "fields": {"trailText": "A trail text", "byline": "John Doe"},
        }
        article = adapter._to_article(raw)
        self.assertEqual(article.source_id, "guardian")
        self.assertEqual(article.category, "Technology")


class TestNYTimesAdapter(unittest.TestCase):

    def test_returns_empty_without_key(self):
        adapter = NYTimesAdapter(api_key="")
        result = asyncio.run(adapter.fetch_headlines())
        self.assertEqual(result, [])

    def test_section_map_covers_categories(self):
        adapter = NYTimesAdapter(api_key="test")
        for cat in ["tech", "finance", "world", "science", "health"]:
            self.assertIn(cat, adapter.SECTION_MAP)


class TestArxivAdapter(unittest.TestCase):

    def test_category_map(self):
        adapter = ArxivAdapter()
        self.assertIn("ai", adapter.CATEGORY_MAP)
        self.assertIn("ml", adapter.CATEGORY_MAP)
        self.assertIn("nlp", adapter.CATEGORY_MAP)

    def test_parse_atom_empty(self):
        adapter = ArxivAdapter()
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>ArXiv Query</title>
        </feed>"""
        articles = adapter._parse_atom(xml)
        self.assertEqual(articles, [])

    def test_parse_atom_single_entry(self):
        adapter = ArxivAdapter()
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://arxiv.org/abs/2601.00001</id>
            <title>Test Paper Title</title>
            <summary>This paper proposes a new method.</summary>
            <published>2026-01-01T00:00:00Z</published>
            <author><name>Jane Doe</name></author>
          </entry>
        </feed>"""
        articles = adapter._parse_atom(xml)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Test Paper Title")
        self.assertEqual(articles[0].source_id, "arxiv")


class TestHackerNewsAdapter(unittest.TestCase):

    def test_to_article_with_external_url(self):
        adapter = HackerNewsAdapter()
        raw = {
            "id": 123, "title": "HN Post", "url": "https://example.com",
            "score": 250, "by": "user1", "time": 1712534400,
            "type": "story", "descendants": 42,
        }
        article = adapter._to_article(raw)
        self.assertEqual(article.url, "https://example.com")
        self.assertEqual(article.score, 250.0)

    def test_to_article_without_url_uses_hn_link(self):
        adapter = HackerNewsAdapter()
        raw = {
            "id": 456, "title": "Ask HN: Something",
            "score": 100, "by": "user2", "time": 1712534400,
            "type": "story", "descendants": 10,
        }
        article = adapter._to_article(raw)
        self.assertIn("news.ycombinator.com", article.url)


class TestRedditAdapter(unittest.TestCase):

    def test_to_article_with_reddit_url(self):
        adapter = RedditAdapter()
        raw = {
            "title": "Reddit Post", "url": "/r/test/comments/abc",
            "score": 500, "author": "redditor", "subreddit": "test",
            "num_comments": 30, "created_utc": 1712534400,
        }
        article = adapter._to_article(raw)
        self.assertTrue(article.url.startswith("https://www.reddit.com"))
        self.assertEqual(article.score, 500.0)

    def test_default_subreddits(self):
        adapter = RedditAdapter()
        self.assertIn("worldnews", adapter.subreddits)
        self.assertIn("MachineLearning", adapter.subreddits)

    def test_custom_subreddits(self):
        adapter = RedditAdapter(subreddits=["LocalLLaMA", "singularity"])
        self.assertEqual(adapter.subreddits, ["LocalLLaMA", "singularity"])


# ──────────────────────────────────────────────
# RSS adapter tests
# ──────────────────────────────────────────────

class TestRSSAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = RSSAdapter()

    def test_parse_rss_single_item(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>RSS Test Item</title>
              <link>https://example.com/rss-item</link>
              <description>Test description &lt;b&gt;bold&lt;/b&gt;</description>
              <pubDate>Wed, 08 Apr 2026 08:00:00 +0000</pubDate>
            </item>
          </channel>
        </rss>"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        articles = self.adapter._parse_rss(root, "test", "Test Source", 10)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "RSS Test Item")
        self.assertEqual(articles[0].url, "https://example.com/rss-item")
        self.assertNotIn("<b>", articles[0].snippet)

    def test_parse_rss_skips_items_without_url(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item><title>No URL Item</title></item>
            <item>
              <title>With URL</title>
              <link>https://example.com/with-url</link>
            </item>
          </channel>
        </rss>"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        articles = self.adapter._parse_rss(root, "test", "Test", 10)
        # Only the one with URL should be included
        self.assertEqual(len(articles), 1)

    def test_parse_atom_single_entry(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Atom Entry</title>
            <link rel="alternate" href="https://example.com/atom-entry"/>
            <summary>Atom summary text</summary>
            <published>2026-04-08T00:00:00Z</published>
            <author><name>Author Name</name></author>
          </entry>
        </feed>"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        articles = self.adapter._parse_atom(root, "atom_test", "Atom Source", 10)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Atom Entry")
        self.assertEqual(articles[0].url, "https://example.com/atom-entry")


# ──────────────────────────────────────────────
# NewsConnector tests
# ──────────────────────────────────────────────

class TestNewsConnector(unittest.TestCase):

    def test_merge_deduplicate_removes_duplicates(self):
        connector = NewsConnector.__new__(NewsConnector)
        a1 = make_article(url="https://example.com/1")
        a2 = make_article(url="https://example.com/1")  # duplicate
        a3 = make_article(url="https://example.com/2")
        merged = connector._merge_deduplicate([[a1, a2], [a3]], 10)
        self.assertEqual(len(merged), 2)

    def test_merge_deduplicate_respects_limit(self):
        connector = NewsConnector.__new__(NewsConnector)
        articles = [make_article(url=f"https://example.com/{i}") for i in range(20)]
        merged = connector._merge_deduplicate([articles], 5)
        self.assertEqual(len(merged), 5)

    def test_merge_deduplicate_skips_empty_titles(self):
        connector = NewsConnector.__new__(NewsConnector)
        a1 = make_article(title="", url="https://example.com/no-title")
        a2 = make_article(title="Has Title", url="https://example.com/has-title")
        merged = connector._merge_deduplicate([[a1, a2]], 10)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Has Title")

    def test_connector_initializes_all_adapters(self):
        connector = NewsConnector(keys={})
        self.assertIsNotNone(connector.newsapi)
        self.assertIsNotNone(connector.guardian)
        self.assertIsNotNone(connector.nytimes)
        self.assertIsNotNone(connector.arxiv)
        self.assertIsNotNone(connector.hackernews)
        self.assertIsNotNone(connector.reddit)
        self.assertIsNotNone(connector.pubmed)
        self.assertIsNotNone(connector.rss)

    def test_safe_fetch_returns_empty_on_exception(self):
        connector = NewsConnector.__new__(NewsConnector)
        bad_adapter = MagicMock()
        bad_adapter.fetch_headlines = AsyncMock(side_effect=Exception("network error"))
        result = asyncio.run(connector._safe_fetch(bad_adapter, "general", 10))
        self.assertEqual(result, [])

    def test_safe_search_returns_empty_on_exception(self):
        connector = NewsConnector.__new__(NewsConnector)
        bad_adapter = MagicMock()
        bad_adapter.search = AsyncMock(side_effect=Exception("network error"))
        result = asyncio.run(connector._safe_search(bad_adapter, "test", None, 10))
        self.assertEqual(result, [])


# ──────────────────────────────────────────────
# FeedProfile tests
# ──────────────────────────────────────────────

class TestFeedProfile(unittest.TestCase):

    def test_default_interests(self):
        p = FeedProfile(user_id="u1")
        self.assertIn("tech", p.interests)
        self.assertIn("ai", p.interests)

    def test_serialization_roundtrip(self):
        p = FeedProfile(
            user_id="u1",
            interests=["ai", "finance"],
            preferred_sources=["guardian", "nytimes"],
            topic_queries=["Kimi K2.5 release"],
        )
        d = p.to_dict()
        restored = FeedProfile.from_dict(d)
        self.assertEqual(restored.user_id, "u1")
        self.assertEqual(restored.interests, ["ai", "finance"])
        self.assertEqual(restored.topic_queries, ["Kimi K2.5 release"])

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = FeedProfile(user_id="u2", interests=["tech"])
            p.save(data_dir=tmp)
            loaded = FeedProfile.load("u2", data_dir=tmp)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.interests, ["tech"])

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = FeedProfile.load("nonexistent", data_dir=tmp)
            self.assertIsNone(result)


# ──────────────────────────────────────────────
# FeedEngine tests
# ──────────────────────────────────────────────

class TestFeedEngine(unittest.TestCase):

    def _make_engine(self):
        connector = make_connector_with_mocks()
        for adapter in connector._adapters.values():
            adapter.fetch_headlines = AsyncMock(return_value=[])
            adapter.search = AsyncMock(return_value=[])
        connector._safe_fetch = AsyncMock(return_value=[])
        connector._safe_search = AsyncMock(return_value=[])
        connector.headlines = AsyncMock(return_value=[])
        connector.search = AsyncMock(return_value=[])
        return FeedEngine(connector)

    def test_recency_score_recent(self):
        engine = self._make_engine()
        now = datetime.now(timezone.utc)
        score = engine._recency_score(now.isoformat(), now - timedelta(hours=24))
        self.assertGreater(score, 0.8)

    def test_recency_score_old(self):
        engine = self._make_engine()
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        cutoff = now - timedelta(hours=24)
        score = engine._recency_score(old, cutoff)
        self.assertEqual(score, 0.0)

    def test_recency_score_unknown_date(self):
        engine = self._make_engine()
        score = engine._recency_score(None, datetime.now(timezone.utc))
        self.assertGreater(score, 0)

    def test_assign_section_by_source(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1")
        article = make_article(source_id="techcrunch")
        section = engine._assign_section(article, profile)
        self.assertEqual(section, "Technology")

    def test_assign_section_wire(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1")
        article = make_article(source_id="reuters")
        section = engine._assign_section(article, profile)
        self.assertEqual(section, "World News")

    def test_resolve_sources_enterprise_gets_all(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1", tier="enterprise")
        sources = engine._resolve_sources(profile)
        self.assertIn("guardian", sources)
        self.assertIn("nytimes", sources)
        self.assertIn("arxiv", sources)

    def test_resolve_sources_maker_is_limited(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1", tier="maker")
        sources = engine._resolve_sources(profile)
        self.assertIn("newsapi", sources)
        self.assertNotIn("nytimes", sources)  # Not in maker tier

    def test_resolve_sources_respects_exclusions(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1", tier="pro", excluded_sources=["reddit"])
        sources = engine._resolve_sources(profile)
        self.assertNotIn("reddit", sources)

    def test_flatten_deduplicate(self):
        engine = self._make_engine()
        a1 = make_article(url="https://example.com/1")
        a2 = make_article(url="https://example.com/1")  # duplicate
        a3 = make_article(url="https://example.com/2")
        result = engine._flatten_deduplicate([[a1, a2], [a3]])
        self.assertEqual(len(result), 2)

    def test_section_ordering(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1")
        from orchestra.news_feed import RankedArticle
        ranked = [
            RankedArticle(article=make_article(source_id="techcrunch"), rank_score=0.9, section="Technology"),
            RankedArticle(article=make_article(source_id="reuters"), rank_score=0.8, section="World News"),
        ]
        sections = engine._section(ranked, profile)
        section_keys = list(sections.keys())
        # World News should come before Technology
        self.assertLess(section_keys.index("World News"), section_keys.index("Technology"))

    def test_build_digest_returns_digest(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1")
        digest = asyncio.run(engine.build_digest(profile))
        self.assertIsInstance(digest, Digest)
        self.assertEqual(digest.user_id, "u1")

    def test_digest_plain_text_contains_header(self):
        engine = self._make_engine()
        profile = FeedProfile(user_id="u1", display_name="My Digest")
        digest = asyncio.run(engine.build_digest(profile))
        text = digest.to_plain_text()
        self.assertIn("MY DIGEST", text)


# ──────────────────────────────────────────────
# SOURCE_AUTHORITY tests
# ──────────────────────────────────────────────

class TestSourceAuthority(unittest.TestCase):

    def test_wire_services_highest_authority(self):
        self.assertEqual(SOURCE_AUTHORITY["reuters"], 1.0)
        self.assertEqual(SOURCE_AUTHORITY["ap"], 1.0)

    def test_social_lower_than_wire(self):
        self.assertLess(SOURCE_AUTHORITY["reddit"], SOURCE_AUTHORITY["reuters"])
        self.assertLess(SOURCE_AUTHORITY["hackernews"], SOURCE_AUTHORITY["nytimes"])

    def test_science_journals_high(self):
        self.assertGreaterEqual(SOURCE_AUTHORITY["nature"], 0.95)


# ──────────────────────────────────────────────
# NewsToolExecutor tests
# ──────────────────────────────────────────────

def make_executor(tmp_dir: str):
    connector = make_connector_with_mocks()
    connector.headlines = AsyncMock(return_value=[])
    connector.search = AsyncMock(return_value=[])
    connector.fetch_rss_source = AsyncMock(return_value=[])
    connector.multi_source_headlines = AsyncMock(return_value={})
    connector.rss.fetch_feed = AsyncMock(return_value=[])
    connector.guardian.search = AsyncMock(return_value=[])
    connector.nytimes.search = AsyncMock(return_value=[])
    connector.arxiv.search = AsyncMock(return_value=[])
    connector.arxiv.fetch_headlines = AsyncMock(return_value=[])
    connector.hackernews.fetch_headlines = AsyncMock(return_value=[])
    connector.hackernews.search = AsyncMock(return_value=[])
    connector.reddit.fetch_headlines = AsyncMock(return_value=[])
    connector.reddit.search = AsyncMock(return_value=[])
    connector.pubmed.search = AsyncMock(return_value=[])
    feed_engine = FeedEngine(connector)
    return NewsToolExecutor(connector, feed_engine, feed_data_dir=tmp_dir)


class TestNewsToolDefinitions(unittest.TestCase):

    def test_all_tools_have_required_fields(self):
        for tool in NEWS_TOOL_DEFINITIONS:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])

    def test_tool_count(self):
        self.assertEqual(len(NEWS_TOOL_DEFINITIONS), 25)

    def test_all_tool_names_unique(self):
        names = [t["function"]["name"] for t in NEWS_TOOL_DEFINITIONS]
        self.assertEqual(len(names), len(set(names)))


class TestNewsToolExecutor(unittest.TestCase):

    def test_can_handle_all_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            for tool in NEWS_TOOL_DEFINITIONS:
                self.assertTrue(executor.can_handle(tool["function"]["name"]))

    def test_cannot_handle_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            self.assertFalse(executor.can_handle("completely_unknown"))

    def test_headlines_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_headlines", {"category": "tech"}))
            data = json.loads(result)
            self.assertIn("articles", data)
            self.assertIn("count", data)

    def test_search_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_search", {"query": "AI news"}))
            data = json.loads(result)
            self.assertIn("articles", data)

    def test_source_list_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_source_list", {}))
            data = json.loads(result)
            self.assertIn("sources", data)
            self.assertGreater(len(data["sources"]), 20)

    def test_source_summary_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_source_summary", {}))
            data = json.loads(result)
            self.assertIn("total", data)

    def test_sources_by_category_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_sources_by_category", {"category": "tech"}))
            data = json.loads(result)
            self.assertIn("sources", data)

    def test_sources_by_category_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_sources_by_category", {"category": "invalid"}))
            data = json.loads(result)
            self.assertIn("error", data)

    def test_arxiv_headlines_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_arxiv_headlines", {"category": "ai"}))
            data = json.loads(result)
            self.assertIn("articles", data)

    def test_hackernews_top_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_hackernews_top", {"feed": "top"}))
            data = json.loads(result)
            self.assertIn("articles", data)

    def test_feed_profile_set_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            asyncio.run(executor.execute("news_feed_profile_set", {
                "user_id": "u1", "interests": ["ai", "tech"],
                "preferred_sources": ["guardian", "nytimes"],
            }))
            result = asyncio.run(executor.execute("news_feed_profile_get", {"user_id": "u1"}))
            data = json.loads(result)
            self.assertTrue(data["exists"])
            self.assertIn("ai", data["interests"])

    def test_feed_profile_get_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_feed_profile_get", {"user_id": "nonexistent"}))
            data = json.loads(result)
            self.assertFalse(data["exists"])

    def test_feed_profile_add_remove_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            asyncio.run(executor.execute("news_feed_profile_set", {"user_id": "u1"}))
            # Add
            r = json.loads(asyncio.run(executor.execute("news_feed_profile_add_source", {
                "user_id": "u1", "source_id": "guardian"
            })))
            self.assertIn("guardian", r["preferred_sources"])
            # Remove
            r2 = json.loads(asyncio.run(executor.execute("news_feed_profile_remove_source", {
                "user_id": "u1", "source_id": "guardian"
            })))
            self.assertNotIn("guardian", r2["preferred_sources"])

    def test_feed_profile_add_interest(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            asyncio.run(executor.execute("news_feed_profile_set", {"user_id": "u1"}))
            r = json.loads(asyncio.run(executor.execute("news_feed_profile_add_interest", {
                "user_id": "u1", "interest": "quantum"
            })))
            self.assertIn("quantum", r["interests"])

    def test_digest_build_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_digest_build", {"user_id": "u1"}))
            data = json.loads(result)
            self.assertIn("sections", data)
            self.assertIn("plain_text", data)

    def test_topic_watch_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("news_topic_watch", {"topic": "Kimi K2.5"}))
            data = json.loads(result)
            self.assertIn("topic", data)
            self.assertEqual(data["topic"], "Kimi K2.5")

    def test_unknown_tool_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = make_executor(tmp)
            result = asyncio.run(executor.execute("unknown_tool", {}))
            data = json.loads(result)
            self.assertIn("error", data)

    def test_get_news_tools_factory(self):
        defs, executor = get_news_tools()
        self.assertEqual(len(defs), 25)
        self.assertIsInstance(executor, NewsToolExecutor)


# ──────────────────────────────────────────────
# MultiSourceSearchProvider tests
# ──────────────────────────────────────────────

class TestMultiSourceSearchProvider(unittest.TestCase):

    def test_article_to_news_item_conversion(self):
        provider = MultiSourceSearchProvider.__new__(MultiSourceSearchProvider)
        a = make_article(title="Test", url="https://example.com", snippet="snippet")
        item = provider._article_to_news_item(a, "test query")
        self.assertEqual(item.title, "Test")
        self.assertEqual(item.url, "https://example.com")
        self.assertEqual(item.topic_name, "test query")

    def test_merge_deduplicate(self):
        provider = MultiSourceSearchProvider.__new__(MultiSourceSearchProvider)
        a1 = make_article(url="https://example.com/1")
        a2 = make_article(url="https://example.com/1")  # dup
        a3 = make_article(url="https://example.com/2")
        merged = provider._merge_deduplicate([a1, a2, a3])
        self.assertEqual(len(merged), 2)

    def test_search_returns_news_items(self):
        provider = MultiSourceSearchProvider.__new__(MultiSourceSearchProvider)
        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=[
            make_article(title="Art 1"), make_article(url="https://example.com/2", title="Art 2"),
        ])
        mock_connector.rss = MagicMock()
        mock_connector.rss.fetch_feed = AsyncMock(return_value=[])
        provider.connector = mock_connector
        provider._sonar = None

        items = asyncio.run(provider.search("test query", max_results=5))
        self.assertGreater(len(items), 0)
        for item in items:
            self.assertIsNotNone(item.title)


# ──────────────────────────────────────────────
# Integration test
# ──────────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def test_full_feed_profile_to_digest_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Build profile
            profile = FeedProfile(
                user_id="integration_user",
                interests=["tech", "ai"],
                preferred_sources=["hackernews"],
                tier="pro",
            )
            profile.save(data_dir=tmp)

            # Create executor with mocked connector
            executor = make_executor(tmp)

            # Set profile via tool
            asyncio.run(executor.execute("news_feed_profile_set", {
                "user_id": "integration_user",
                "interests": ["tech", "ai", "finance"],
                "topic_queries": ["Kimi K2.5"],
            }))

            # Add preferred source
            asyncio.run(executor.execute("news_feed_profile_add_source", {
                "user_id": "integration_user", "source_id": "guardian"
            }))

            # Get profile and verify
            r = json.loads(asyncio.run(executor.execute("news_feed_profile_get", {
                "user_id": "integration_user"
            })))
            self.assertIn("ai", r["interests"])
            self.assertIn("guardian", r["preferred_sources"])

            # Build digest
            digest_result = json.loads(asyncio.run(executor.execute("news_digest_build", {
                "user_id": "integration_user"
            })))
            self.assertIn("sections", digest_result)
            self.assertIn("plain_text", digest_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
