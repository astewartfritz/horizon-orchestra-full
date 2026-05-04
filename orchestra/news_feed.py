"""
orchestra/news_feed.py
───────────────────────
Personalized news feed engine for Orchestra.

Features:
  - Per-user feed profiles (topic interests, source preferences, excluded sources)
  - Relevance ranking (recency × source authority × topic match × engagement score)
  - Deduplication across all sources
  - Digest builder: groups articles into labelled sections for email/UI delivery
  - Trending detection: surfaces articles with high velocity/score
  - Feed persistence: saves last-fetched cursor per user
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .news_connector import Article, NewsConnector
from .news_sources import SourceCategory, SOURCES


# ──────────────────────────────────────────────
# Feed profile
# ──────────────────────────────────────────────

@dataclass
class FeedProfile:
    """Per-user feed preferences."""
    user_id: str
    display_name: str = "My Feed"

    # Sources
    preferred_sources: list[str] = field(default_factory=list)
    excluded_sources: list[str] = field(default_factory=list)

    # Topic interests (maps to source category or search query)
    interests: list[str] = field(default_factory=lambda: [
        "tech", "ai", "world", "finance", "science"
    ])

    # Custom search topics (always fetched)
    topic_queries: list[str] = field(default_factory=list)

    # Source category weights (0.0 – 1.0)
    category_weights: dict[str, float] = field(default_factory=lambda: {
        "wire": 1.0, "newspaper": 0.9, "tech": 0.8,
        "science": 0.7, "finance": 0.8, "aggregator": 0.6,
        "social": 0.5, "magazine": 0.7, "rss": 0.6,
    })

    # Recency preference: how many hours back to look
    lookback_hours: int = 24

    # Max articles per digest section
    max_per_section: int = 5

    # Tier — affects which sources are available
    tier: str = "pro"  # "maker" | "builder" | "pro" | "enterprise"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "FeedProfile":
        return cls(**d)

    def save(self, data_dir: str = "orchestra/data/feeds") -> Path:
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        fp = path / f"{self.user_id}.json"
        fp.write_text(self.to_json())
        return fp

    @classmethod
    def load(cls, user_id: str,
             data_dir: str = "orchestra/data/feeds") -> Optional["FeedProfile"]:
        fp = Path(data_dir) / f"{user_id}.json"
        if not fp.exists():
            return None
        return cls.from_dict(json.loads(fp.read_text()))


# ──────────────────────────────────────────────
# Ranked article
# ──────────────────────────────────────────────

@dataclass
class RankedArticle:
    article: Article
    rank_score: float
    section: str  # Which digest section it belongs to


# ──────────────────────────────────────────────
# Digest
# ──────────────────────────────────────────────

@dataclass
class Digest:
    """Structured news digest ready for email or UI rendering."""
    user_id: str
    title: str
    date_label: str
    sections: dict[str, list[Article]]  # section_name → articles
    trending: list[Article]
    total_articles: int
    sources_used: list[str]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_plain_text(self) -> str:
        """Render digest as plain-text for email delivery."""
        lines = [
            f"{self.title.upper()} -- {self.date_label}",
            "=" * 60,
            "",
        ]
        for section, articles in self.sections.items():
            if not articles:
                continue
            lines.append(section.upper())
            lines.append("-" * 40)
            for a in articles:
                lines.append(f"- {a.title}")
                if a.snippet:
                    lines.append(f"  {a.snippet[:120]}...")
                lines.append(f"  {a.source_name}: {a.url}")
                lines.append("")
            lines.append("")

        if self.trending:
            lines.append("TRENDING NOW")
            lines.append("-" * 40)
            for a in self.trending[:3]:
                score_label = f"({int(a.score)} pts)" if a.score else ""
                lines.append(f"- {a.title} {score_label}")
                lines.append(f"  {a.source_name}: {a.url}")
            lines.append("")

        lines.append(f"Sources: {', '.join(self.sources_used)}")
        lines.append(f"Generated at {self.generated_at}")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# Feed Engine
# ──────────────────────────────────────────────

# Source authority scores (higher = more trusted)
SOURCE_AUTHORITY: dict[str, float] = {
    "reuters": 1.0, "ap": 1.0, "bbc": 0.95,
    "nytimes": 0.92, "guardian": 0.90, "ft": 0.92,
    "wsj": 0.90, "washingtonpost": 0.88, "economist": 0.88,
    "bloomberg_wire": 0.95, "nature": 0.98, "arxiv": 0.85,
    "techcrunch": 0.78, "theverge": 0.76, "arstechnica": 0.80,
    "wired": 0.78, "mit_tech_review": 0.88, "politico": 0.82,
    "axios": 0.80, "aljazeera": 0.78, "foreignaffairs": 0.85,
    "hackernews": 0.70, "reddit": 0.55,
    "newsapi": 0.65, "newsdata": 0.60,
}


class FeedEngine:
    """Builds personalized ranked digests from NewsConnector output."""

    def __init__(self, connector: NewsConnector):
        self.connector = connector

    # ── Public API ────────────────────────────────────────────────────────────

    async def build_digest(self, profile: FeedProfile) -> Digest:
        """Full pipeline: fetch → rank → section → digest."""
        # Determine which sources to use
        sources = self._resolve_sources(profile)

        # Parallel fetch: headlines + topic searches
        import asyncio
        headline_tasks = [
            self.connector.headlines(
                category=interest, sources=sources, limit=20
            )
            for interest in profile.interests
        ]
        search_tasks = [
            self.connector.search(
                query=q, sources=sources, limit=10
            )
            for q in profile.topic_queries
        ]

        results = await asyncio.gather(*(headline_tasks + search_tasks))
        all_articles = self._flatten_deduplicate(results)

        # Rank
        cutoff = datetime.now(timezone.utc) - timedelta(hours=profile.lookback_hours)
        ranked = [self._rank(a, profile, cutoff) for a in all_articles]
        ranked = [r for r in ranked if r.rank_score > 0]
        ranked.sort(key=lambda r: -r.rank_score)

        # Section into digest
        sections = self._section(ranked, profile)

        # Trending (highest social scores)
        trending = sorted(
            [r.article for r in ranked if r.article.score > 0],
            key=lambda a: -a.score
        )[:5]

        sources_used = list({a.article.source_name for a in ranked[:50]})

        return Digest(
            user_id=profile.user_id,
            title=profile.display_name,
            date_label=datetime.now(timezone.utc).strftime("%B %d, %Y"),
            sections=sections,
            trending=trending,
            total_articles=len(all_articles),
            sources_used=sources_used,
        )

    # ── Ranking ───────────────────────────────────────────────────────────────

    def _rank(self, article: Article, profile: FeedProfile,
               cutoff: datetime) -> RankedArticle:
        """
        Composite score = recency × authority × category_weight × engagement
        """
        # Recency score (exponential decay)
        recency = self._recency_score(article.published_at, cutoff)
        if recency <= 0:
            return RankedArticle(article=article, rank_score=0.0, section="other")

        # Authority
        authority = SOURCE_AUTHORITY.get(article.source_id, 0.6)

        # Category weight from profile
        src_obj = SOURCES.get(article.source_id)
        cat = src_obj.category.value if src_obj else "rss"
        cat_weight = profile.category_weights.get(cat, 0.6)

        # Engagement (normalized HN/Reddit score, 0–1)
        engagement = min(article.score / 1000.0, 1.0) if article.score > 0 else 0.5

        score = recency * authority * cat_weight * (0.5 + 0.5 * engagement)

        # Determine section
        section = self._assign_section(article, profile)

        return RankedArticle(article=article, rank_score=score, section=section)

    def _recency_score(self, published_at: Optional[str], cutoff: datetime) -> float:
        if not published_at:
            return 0.5  # Unknown date — moderate score
        try:
            # Try ISO format
            pub = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                return 0.0  # Too old
            # Hours ago → score 1.0 at 0h, approaching 0.1 at lookback_hours
            hours_ago = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            return max(0.1, math.exp(-0.1 * hours_ago))
        except (ValueError, TypeError):
            return 0.4

    def _assign_section(self, article: Article, profile: FeedProfile) -> str:
        """Map an article to a digest section based on source category."""
        src_obj = SOURCES.get(article.source_id)
        if src_obj:
            cat = src_obj.category
            section_map = {
                SourceCategory.WIRE: "World News",
                SourceCategory.NEWSPAPER: "Top Stories",
                SourceCategory.TECH: "Technology",
                SourceCategory.SCIENCE: "Science & Research",
                SourceCategory.FINANCE: "Markets & Finance",
                SourceCategory.MAGAZINE: "Analysis & Opinion",
                SourceCategory.SOCIAL: "Community Buzz",
                SourceCategory.AGGREGATOR: "Top Stories",
                SourceCategory.RSS: "Latest",
            }
            return section_map.get(cat, "Latest")
        # Fallback: use article's own category field
        cat_lower = (article.category or "").lower()
        if any(k in cat_lower for k in ("tech", "science", "ai", "software")):
            return "Technology"
        if any(k in cat_lower for k in ("business", "finance", "market", "econ")):
            return "Markets & Finance"
        if any(k in cat_lower for k in ("world", "politics", "nation", "global")):
            return "World News"
        return "Latest"

    # ── Sectioning ────────────────────────────────────────────────────────────

    def _section(self, ranked: list[RankedArticle],
                  profile: FeedProfile) -> dict[str, list[Article]]:
        """Group ranked articles into named sections."""
        sections: dict[str, list[Article]] = {}
        section_counts: dict[str, int] = {}

        for r in ranked:
            sec = r.section
            if sec not in sections:
                sections[sec] = []
                section_counts[sec] = 0
            if section_counts[sec] < profile.max_per_section:
                sections[sec].append(r.article)
                section_counts[sec] += 1

        # Ensure consistent ordering
        priority_order = [
            "World News", "Top Stories", "Technology",
            "Markets & Finance", "Science & Research",
            "Analysis & Opinion", "Community Buzz", "Latest",
        ]
        ordered = {}
        for sec in priority_order:
            if sec in sections and sections[sec]:
                ordered[sec] = sections[sec]
        for sec, articles in sections.items():
            if sec not in ordered and articles:
                ordered[sec] = articles
        return ordered

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_sources(self, profile: FeedProfile) -> list[str]:
        """Build source list respecting preferences and tier limits."""
        # Tier source allowlists
        tier_sources = {
            "maker":      ["newsapi", "hackernews", "reddit", "guardian"],
            "builder":    ["newsapi", "newsdata", "hackernews", "reddit",
                           "guardian", "arxiv", "bbc", "techcrunch"],
            "pro":        list(SOURCES.keys()),
            "enterprise": list(SOURCES.keys()),
        }
        allowed = set(tier_sources.get(profile.tier, tier_sources["builder"]))

        if profile.preferred_sources:
            sources = [s for s in profile.preferred_sources if s in allowed]
        else:
            sources = list(allowed)

        # Remove excluded
        sources = [s for s in sources if s not in profile.excluded_sources]
        return sources

    def _flatten_deduplicate(self, result_lists) -> list[Article]:
        seen: set[str] = set()
        merged: list[Article] = []
        for articles in result_lists:
            if isinstance(articles, list):
                for a in articles:
                    if a.fingerprint not in seen and a.title and a.url:
                        seen.add(a.fingerprint)
                        merged.append(a)
        return merged
