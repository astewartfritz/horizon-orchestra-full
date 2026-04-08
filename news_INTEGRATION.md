# Orchestra News & Media Connector Layer

**Module**: `orchestra/news_*.py`  
**Tier gate**: All 25 tools available to Enterprise ($499/mo). A curated subset (free sources only) available to Pro and below.  
**Tests**: 89/89 passing — `python -m pytest tests/test_news.py -v`

---

## What's Included

| File | Purpose |
|------|---------|
| `orchestra/news_sources.py` | Registry of 30+ sources across 8 categories |
| `orchestra/news_connector.py` | API adapters: NewsAPI, NewsData, Guardian, NYT, arXiv, HackerNews, Reddit, PubMed, RSS (universal) |
| `orchestra/news_tools.py` | 25 agent-callable tools + `get_news_tools()` factory |
| `orchestra/news_feed.py` | Personalized feed engine, ranking, digest builder |
| `orchestra/news_briefing_bridge.py` | Drop-in replacement for `SonarSearchProvider` using multi-source search |
| `tests/test_news.py` | 89 tests covering all modules |

---

## Sources Covered (30+)

### Wire Services (authority: 1.0)
- Reuters, Associated Press (AP)

### Newspapers
- The Guardian, New York Times, Washington Post, Wall Street Journal, Financial Times, BBC News

### Tech & Science
- TechCrunch, The Verge, Ars Technica, Wired, MIT Technology Review, arXiv, Nature, PubMed

### Finance
- MarketWatch, Seeking Alpha, Bloomberg Wire

### Magazines & Long-Form
- The Atlantic, The New Yorker, Foreign Affairs, The Economist

### News Aggregators
- NewsAPI (aggregates 80,000+ sources), NewsData.io

### Social / Community
- Hacker News, Reddit (r/worldnews, r/technology, r/MachineLearning, r/LocalLLaMA, etc.)

### International
- Al Jazeera, Axios, Politico

---

## Environment Variables

```bash
# Required for API sources (all optional — free sources work without keys)
NEWSAPI_KEY=...           # newsapi.org — 100 req/day free, $449/mo for production
NEWSDATA_KEY=...          # newsdata.io — 200 req/day free
GUARDIAN_API_KEY=...      # theguardian.com — free tier available
NYT_API_KEY=...           # developer.nytimes.com — free
PUBMED_API_KEY=...        # ncbi.nlm.nih.gov — free
AP_API_KEY=...            # AP Content API — paid
REUTERS_API_KEY=...       # Reuters Connect — paid

# Reddit OAuth (optional — public JSON endpoints work without auth)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

**Zero-config sources** (no API key needed): arXiv, Hacker News, Reddit (public), Guardian (test key fallback), all RSS feeds.

---

## Drop Into agent_loop.py

```python
# In orchestra/agent_loop.py (or wherever tools are registered)
from .news_tools import get_news_tools

news_defs, news_executor = get_news_tools(
    keys={
        "newsapi":   os.getenv("NEWSAPI_KEY", ""),
        "newsdata":  os.getenv("NEWSDATA_KEY", ""),
        "guardian":  os.getenv("GUARDIAN_API_KEY", ""),
        "nytimes":   os.getenv("NYT_API_KEY", ""),
        "pubmed":    os.getenv("PUBMED_API_KEY", ""),
    },
    subreddits=["worldnews", "technology", "MachineLearning", "LocalLLaMA"],
    feed_data_dir="/var/orchestra/news_feeds",
)

# Add to agent tools
tools.extend(news_defs)
tool_executors["news"] = news_executor
```

### Tier-Gated Registration (Enterprise only for full set)

```python
if customer.tier == "enterprise":
    tools.extend(news_defs)
    tool_executors["news"] = news_executor
else:
    # Pro/Builder: only free sources (HN, arXiv, Guardian test key, Reddit)
    free_defs = [d for d in news_defs if d["function"]["name"] in FREE_TIER_TOOLS]
    tools.extend(free_defs)
    tool_executors["news"] = news_executor

FREE_TIER_TOOLS = {
    "news_headlines", "news_search", "news_hackernews_top",
    "news_arxiv_headlines", "news_source_list", "news_source_summary",
    "news_topic_watch",
}
```

---

## Upgrade briefing_monitor.py to Multi-Source

Replace Sonar-only search with multi-source search in `briefing_monitor.py`:

```python
# Before:
from .briefing_monitor import SonarSearchProvider
self.search = SonarSearchProvider(sonar_key)

# After:
from .news_briefing_bridge import MultiSourceSearchProvider
self.search = MultiSourceSearchProvider(
    sonar_key=sonar_key,       # Sonar still used as fallback
    news_keys={
        "newsapi":  os.getenv("NEWSAPI_KEY", ""),
        "guardian": os.getenv("GUARDIAN_API_KEY", ""),
        "nytimes":  os.getenv("NYT_API_KEY", ""),
    },
)
```

The bridge queries NewsAPI + Guardian + NYT + arXiv + HN + Reddit + RSS in parallel, then falls back to Sonar only when results are sparse (< 2 articles). This gives briefings much broader source coverage.

---

## The 25 Agent Tools

| Tool | Description |
|------|-------------|
| `news_headlines` | Top headlines by category (tech, finance, world, science, health) |
| `news_search` | Search across all sources by keyword |
| `news_guardian_search` | Guardian API targeted search |
| `news_nytimes_search` | NYT API targeted search |
| `news_arxiv_search` | arXiv paper search |
| `news_arxiv_headlines` | Latest arXiv papers by subject area (ai, ml, nlp, cs, physics, bio, math) |
| `news_hackernews_top` | HN top/new/ask/show feed |
| `news_hackernews_search` | HN story search (Algolia API) |
| `news_reddit_headlines` | Reddit subreddit hot posts |
| `news_reddit_search` | Reddit cross-subreddit search |
| `news_pubmed_search` | PubMed biomedical literature search |
| `news_rss_fetch` | Fetch any RSS/Atom feed by source ID |
| `news_multi_source_headlines` | Side-by-side headlines from multiple sources |
| `news_source_list` | List all registered sources |
| `news_source_summary` | Summary stats (counts by category, auth type, RSS) |
| `news_sources_by_category` | Sources filtered by category |
| `news_feed_profile_set` | Create/update a user's personalized feed profile |
| `news_feed_profile_get` | Get a user's feed profile |
| `news_feed_profile_add_source` | Add preferred source to profile |
| `news_feed_profile_remove_source` | Remove source from profile |
| `news_feed_profile_add_interest` | Add interest topic to profile |
| `news_digest_build` | Build personalized ranked digest for a user |
| `news_digest_email` | Render digest as plain-text email body |
| `news_topic_watch` | Search for a specific topic across all sources |
| `news_trending` | Trending topics based on recent high-score articles |

---

## Ranking Formula

```
score = recency × authority × category_weight × (0.5 + 0.5 × engagement)
```

- **Recency**: exponential decay over 24h window (recent articles score > 0.8)
- **Authority**: Reuters/AP = 1.0 · NYT/Guardian = 0.95 · Nature = 0.97 · HN = 0.70 · Reddit = 0.55
- **Category weight**: user-configurable per interest topic
- **Engagement**: normalized HN points / Reddit upvotes

---

## Running Tests

```bash
cd orchestra-news
pip install httpx feedparser pytest
python -m pytest tests/test_news.py -v
# Expected: 89 passed in ~0.3s
```
