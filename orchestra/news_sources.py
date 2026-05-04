"""
orchestra/news_sources.py
──────────────────────────
Unified source registry for Orchestra's news & media connector layer.

Covers 30+ sources across 8 categories:
  WIRE        Reuters, AP, AFP, Bloomberg Wire
  NEWSPAPER   NYT, Guardian, Washington Post, WSJ, FT, Economist
  TECH        TechCrunch, The Verge, Ars Technica, Wired, MIT Tech Review
  SCIENCE     Nature, Science, arXiv, PubMed Central, Phys.org
  FINANCE     Bloomberg, MarketWatch, Seeking Alpha, Motley Fool
  AGGREGATOR  NewsAPI, NewsData, Hacker News, Reddit
  SOCIAL      Reddit (multi-subreddit), Hacker News
  RSS         Any RSS/Atom feed URL (universal fallback)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SourceCategory(str, Enum):
    WIRE        = "wire"
    NEWSPAPER   = "newspaper"
    TECH        = "tech"
    SCIENCE     = "science"
    FINANCE     = "finance"
    AGGREGATOR  = "aggregator"
    SOCIAL      = "social"
    MAGAZINE    = "magazine"
    RSS         = "rss"


class AuthType(str, Enum):
    API_KEY     = "api_key"
    BEARER      = "bearer"
    OAUTH2      = "oauth2"
    NONE        = "none"
    RSS         = "rss"


@dataclass
class NewsSource:
    id: str                              # Unique identifier, e.g. "nytimes"
    name: str                            # Display name
    category: SourceCategory
    base_url: str
    auth_type: AuthType
    api_key_env: Optional[str] = None   # Env var name for the API key
    rate_limit_rpm: int = 60            # Requests per minute
    supports_search: bool = True
    supports_headlines: bool = True
    supports_rss: bool = False
    rss_urls: list[str] = field(default_factory=list)
    requires_paid: bool = False          # True = enterprise/paid API
    description: str = ""
    newsapi_id: Optional[str] = None    # NewsAPI.org source ID for free fallback


# ──────────────────────────────────────────────
# Source Registry
# ──────────────────────────────────────────────

SOURCES: dict[str, NewsSource] = {

    # ── Wire Services ────────────────────────────────────────────────────────

    "reuters": NewsSource(
        id="reuters", name="Reuters",
        category=SourceCategory.WIRE,
        base_url="https://api.reutersagency.com",
        auth_type=AuthType.BEARER,
        api_key_env="REUTERS_API_KEY",
        rate_limit_rpm=30,
        requires_paid=True,
        supports_rss=True,
        rss_urls=[
            "https://feeds.reuters.com/reuters/topNews",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.reuters.com/reuters/technologyNews",
            "https://feeds.reuters.com/reuters/worldNews",
        ],
        description="World's largest news agency, GraphQL API",
        newsapi_id="reuters",
    ),

    "ap": NewsSource(
        id="ap", name="Associated Press",
        category=SourceCategory.WIRE,
        base_url="https://api.ap.org",
        auth_type=AuthType.API_KEY,
        api_key_env="AP_API_KEY",
        rate_limit_rpm=60,
        requires_paid=True,
        supports_rss=True,
        rss_urls=["https://rsshub.app/apnews/topics/apf-topnews"],
        description="AP Media API — text, photos, video",
        newsapi_id="associated-press",
    ),

    "bloomberg_wire": NewsSource(
        id="bloomberg_wire", name="Bloomberg",
        category=SourceCategory.WIRE,
        base_url="https://www.bloomberg.com",
        auth_type=AuthType.NONE,
        supports_rss=True,
        rss_urls=[
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.bloomberg.com/technology/news.rss",
            "https://feeds.bloomberg.com/politics/news.rss",
        ],
        description="Bloomberg wire via RSS (no auth required)",
        newsapi_id="bloomberg",
    ),

    # ── Newspapers ───────────────────────────────────────────────────────────

    "nytimes": NewsSource(
        id="nytimes", name="New York Times",
        category=SourceCategory.NEWSPAPER,
        base_url="https://api.nytimes.com/svc",
        auth_type=AuthType.API_KEY,
        api_key_env="NYT_API_KEY",
        rate_limit_rpm=10,
        supports_rss=True,
        rss_urls=[
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        ],
        description="NYT Article Search API v2 + Top Stories API",
        newsapi_id="the-new-york-times",
    ),

    "guardian": NewsSource(
        id="guardian", name="The Guardian",
        category=SourceCategory.NEWSPAPER,
        base_url="https://content.guardianapis.com",
        auth_type=AuthType.API_KEY,
        api_key_env="GUARDIAN_API_KEY",
        rate_limit_rpm=12,
        supports_rss=True,
        rss_urls=[
            "https://www.theguardian.com/world/rss",
            "https://www.theguardian.com/us-news/rss",
            "https://www.theguardian.com/technology/rss",
            "https://www.theguardian.com/science/rss",
            "https://www.theguardian.com/business/rss",
        ],
        description="Guardian Content API — 2M+ articles",
        newsapi_id="the-guardian-uk",
    ),

    "washingtonpost": NewsSource(
        id="washingtonpost", name="Washington Post",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.washingtonpost.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://feeds.washingtonpost.com/rss/national",
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.washingtonpost.com/rss/business/technology",
            "https://feeds.washingtonpost.com/rss/politics",
        ],
        description="WaPo via RSS",
        newsapi_id="the-washington-post",
    ),

    "wsj": NewsSource(
        id="wsj", name="Wall Street Journal",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.wsj.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
            "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
            "https://feeds.a.dj.com/rss/RSSWSJD.xml",
            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        ],
        description="WSJ via RSS feeds",
        newsapi_id="the-wall-street-journal",
    ),

    "ft": NewsSource(
        id="ft", name="Financial Times",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.ft.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://www.ft.com/rss/home",
            "https://www.ft.com/rss/markets",
            "https://www.ft.com/rss/technology",
        ],
        description="FT via RSS",
        newsapi_id="financial-times",
    ),

    "economist": NewsSource(
        id="economist", name="The Economist",
        category=SourceCategory.MAGAZINE,
        base_url="https://www.economist.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://www.economist.com/rss/the_world_this_week_rss.xml",
            "https://www.economist.com/rss/business_rss.xml",
            "https://www.economist.com/rss/finance_and_economics_rss.xml",
            "https://www.economist.com/rss/science_and_technology_rss.xml",
        ],
        description="The Economist via RSS",
        newsapi_id="the-economist",
    ),

    "bbc": NewsSource(
        id="bbc", name="BBC News",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.bbc.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        ],
        description="BBC News via RSS",
        newsapi_id="bbc-news",
    ),

    # ── Tech Publications ─────────────────────────────────────────────────────

    "techcrunch": NewsSource(
        id="techcrunch", name="TechCrunch",
        category=SourceCategory.TECH,
        base_url="https://techcrunch.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://techcrunch.com/feed/",
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://techcrunch.com/category/startups/feed/",
        ],
        description="TechCrunch via RSS",
        newsapi_id="techcrunch",
    ),

    "theverge": NewsSource(
        id="theverge", name="The Verge",
        category=SourceCategory.TECH,
        base_url="https://www.theverge.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://www.theverge.com/rss/index.xml",
            "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        ],
        description="The Verge via RSS",
        newsapi_id="the-verge",
    ),

    "arstechnica": NewsSource(
        id="arstechnica", name="Ars Technica",
        category=SourceCategory.TECH,
        base_url="https://arstechnica.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://feeds.arstechnica.com/arstechnica/index"],
        description="Ars Technica via RSS",
        newsapi_id="ars-technica",
    ),

    "wired": NewsSource(
        id="wired", name="Wired",
        category=SourceCategory.TECH,
        base_url="https://www.wired.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.wired.com/feed/rss"],
        description="Wired via RSS",
        newsapi_id="wired",
    ),

    "mit_tech_review": NewsSource(
        id="mit_tech_review", name="MIT Technology Review",
        category=SourceCategory.TECH,
        base_url="https://www.technologyreview.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.technologyreview.com/feed/"],
        description="MIT Technology Review via RSS",
        newsapi_id="techradar",
    ),

    # ── Science ───────────────────────────────────────────────────────────────

    "nature": NewsSource(
        id="nature", name="Nature",
        category=SourceCategory.SCIENCE,
        base_url="https://www.nature.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://www.nature.com/nature.rss",
            "https://www.nature.com/subjects/machine-learning.rss",
        ],
        description="Nature journal via RSS",
    ),

    "arxiv": NewsSource(
        id="arxiv", name="arXiv",
        category=SourceCategory.SCIENCE,
        base_url="https://export.arxiv.org/api",
        auth_type=AuthType.NONE,
        supports_search=True,
        supports_headlines=True,
        supports_rss=True,
        rss_urls=[
            "https://arxiv.org/rss/cs.AI",
            "https://arxiv.org/rss/cs.LG",
            "https://arxiv.org/rss/cs.CL",
            "https://arxiv.org/rss/cs.RO",
        ],
        description="arXiv preprints — Atom API, no auth required",
    ),

    "pubmed": NewsSource(
        id="pubmed", name="PubMed",
        category=SourceCategory.SCIENCE,
        base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        auth_type=AuthType.API_KEY,
        api_key_env="PUBMED_API_KEY",
        rate_limit_rpm=30,
        supports_search=True,
        supports_headlines=False,
        description="PubMed E-utilities API — biomedical literature",
    ),

    # ── Finance / Business ────────────────────────────────────────────────────

    "marketwatch": NewsSource(
        id="marketwatch", name="MarketWatch",
        category=SourceCategory.FINANCE,
        base_url="https://www.marketwatch.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "https://feeds.marketwatch.com/marketwatch/marketpulse/",
        ],
        description="MarketWatch via RSS",
        newsapi_id="market-news",
    ),

    "seekingalpha": NewsSource(
        id="seekingalpha", name="Seeking Alpha",
        category=SourceCategory.FINANCE,
        base_url="https://seekingalpha.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://seekingalpha.com/market-news/all/feed.xml"],
        description="Seeking Alpha market news via RSS",
        newsapi_id="seeking-alpha",
    ),

    # ── Aggregators ───────────────────────────────────────────────────────────

    "newsapi": NewsSource(
        id="newsapi", name="NewsAPI",
        category=SourceCategory.AGGREGATOR,
        base_url="https://newsapi.org/v2",
        auth_type=AuthType.API_KEY,
        api_key_env="NEWSAPI_KEY",
        rate_limit_rpm=100,
        supports_search=True,
        supports_headlines=True,
        description="150,000+ sources — everything + top-headlines endpoints",
    ),

    "newsdata": NewsSource(
        id="newsdata", name="NewsData.io",
        category=SourceCategory.AGGREGATOR,
        base_url="https://newsdata.io/api/1",
        auth_type=AuthType.API_KEY,
        api_key_env="NEWSDATA_KEY",
        rate_limit_rpm=30,
        supports_search=True,
        supports_headlines=True,
        description="NewsData.io — latest news, crypto news, archives",
    ),

    # ── Social / Community ────────────────────────────────────────────────────

    "hackernews": NewsSource(
        id="hackernews", name="Hacker News",
        category=SourceCategory.SOCIAL,
        base_url="https://hacker-news.firebaseio.com/v0",
        auth_type=AuthType.NONE,
        rate_limit_rpm=600,
        supports_search=True,
        supports_headlines=True,
        description="HN Firebase API — top/new/best stories, comments",
    ),

    "reddit": NewsSource(
        id="reddit", name="Reddit",
        category=SourceCategory.SOCIAL,
        base_url="https://www.reddit.com",
        auth_type=AuthType.OAUTH2,
        api_key_env="REDDIT_CLIENT_ID",
        rate_limit_rpm=60,
        supports_search=True,
        supports_headlines=True,
        description="Reddit JSON API — configurable subreddit list",
    ),

    # ── Magazines ─────────────────────────────────────────────────────────────

    "atlantic": NewsSource(
        id="atlantic", name="The Atlantic",
        category=SourceCategory.MAGAZINE,
        base_url="https://www.theatlantic.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.theatlantic.com/feed/all/"],
        description="The Atlantic via RSS",
        newsapi_id="the-american-conservative",
    ),

    "newyorker": NewsSource(
        id="newyorker", name="The New Yorker",
        category=SourceCategory.MAGAZINE,
        base_url="https://www.newyorker.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.newyorker.com/feed/everything"],
        description="The New Yorker via RSS",
        newsapi_id="the-new-yorker",
    ),

    "foreignaffairs": NewsSource(
        id="foreignaffairs", name="Foreign Affairs",
        category=SourceCategory.MAGAZINE,
        base_url="https://www.foreignaffairs.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.foreignaffairs.com/rss.xml"],
        description="Foreign Affairs via RSS",
    ),

    "politico": NewsSource(
        id="politico", name="Politico",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.politico.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=[
            "https://www.politico.com/rss/politicopicks.xml",
            "https://www.politico.com/rss/congress.xml",
        ],
        description="Politico via RSS",
        newsapi_id="politico",
    ),

    "axios": NewsSource(
        id="axios", name="Axios",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.axios.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://api.axios.com/feed/"],
        description="Axios via RSS",
        newsapi_id="axios",
    ),

    "aljazeera": NewsSource(
        id="aljazeera", name="Al Jazeera",
        category=SourceCategory.NEWSPAPER,
        base_url="https://www.aljazeera.com",
        auth_type=AuthType.NONE,
        supports_search=False,
        supports_rss=True,
        rss_urls=["https://www.aljazeera.com/xml/rss/all.xml"],
        description="Al Jazeera via RSS",
        newsapi_id="al-jazeera-english",
    ),
}


# ──────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────

def get_source(source_id: str) -> Optional[NewsSource]:
    return SOURCES.get(source_id)

def get_sources_by_category(category: SourceCategory) -> list[NewsSource]:
    return [s for s in SOURCES.values() if s.category == category]

def get_rss_sources() -> list[NewsSource]:
    return [s for s in SOURCES.values() if s.supports_rss]

def get_api_sources() -> list[NewsSource]:
    return [s for s in SOURCES.values() if s.auth_type != AuthType.NONE
            and s.auth_type != AuthType.RSS]

def get_free_sources() -> list[NewsSource]:
    return [s for s in SOURCES.values() if not s.requires_paid]

def list_all_source_ids() -> list[str]:
    return sorted(SOURCES.keys())

def source_summary() -> dict:
    cats: dict[str, list[str]] = {}
    for s in SOURCES.values():
        cats.setdefault(s.category.value, []).append(s.name)
    return {
        "total": len(SOURCES),
        "by_category": cats,
        "rss_enabled": len(get_rss_sources()),
        "api_enabled": len(get_api_sources()),
        "free": len(get_free_sources()),
    }
