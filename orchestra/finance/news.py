"""Finance News + Sentiment — financial news aggregation, NLP sentiment scoring.

Sources: Yahoo Finance RSS, Perplexity Sonar for live search, yfinance news API.
Sentiment via VADER or LLM-based scoring.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..skills.base import run_code_in_sandbox

__all__ = ["FinanceNews"]
log = logging.getLogger("orchestra.finance.news")


class FinanceNews:
    """Financial news aggregation with sentiment analysis."""

    async def ticker_news(self, symbol: str, limit: int = 10) -> dict[str, Any]:
        """Get recent news for a specific ticker."""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    news = t.news or []
    articles = []
    for n in news[:{limit}]:
        articles.append({{
            "title": n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "link": n.get("link", ""),
            "published": n.get("providerPublishTime", ""),
            "type": n.get("type", ""),
            "thumbnail": (n.get("thumbnail", {{}}) or {{}}).get("resolutions", [{{}}])[0].get("url", "") if n.get("thumbnail") else "",
        }})
    print(json.dumps({{"symbol": "{symbol}", "count": len(articles), "articles": articles}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=20)
        return result.get("data", {})

    async def market_news(self, query: str = "stock market today", limit: int = 10) -> dict[str, Any]:
        """Search financial news via web search."""
        # Use Perplexity Sonar for live financial news
        from ..perplexity import PerplexitySearch
        import os
        if os.environ.get("PERPLEXITY_API_KEY"):
            search = PerplexitySearch()
            result = await search.search(query, model="sonar", recency="day")
            return {
                "query": query,
                "content": result.content,
                "citations": result.citations,
                "source": "perplexity_sonar",
            }
        # Fallback: return stub
        return {"query": query, "note": "Set PERPLEXITY_API_KEY for live news search"}

    async def sentiment(self, symbol: str) -> dict[str, Any]:
        """Analyze news sentiment for a ticker using VADER + keyword scoring."""
        code = f"""
import json
try:
    import yfinance as yf

    t = yf.Ticker("{symbol}")
    news = t.news or []

    # Simple keyword sentiment scoring
    positive = ["surge","soar","beat","record","upgrade","outperform","bullish","profit","growth","rally","gain","positive","strong","exceed","buy"]
    negative = ["crash","plunge","miss","downgrade","underperform","bearish","loss","decline","sell","warning","risk","weak","cut","negative","concern","layoff"]

    scored = []
    total_score = 0
    for n in news[:15]:
        title = n.get("title", "").lower()
        pos = sum(1 for w in positive if w in title)
        neg = sum(1 for w in negative if w in title)
        score = pos - neg
        total_score += score
        sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        scored.append({{
            "title": n.get("title", ""),
            "sentiment": sentiment,
            "score": score,
            "publisher": n.get("publisher", ""),
        }})

    n_articles = len(scored) or 1
    avg = total_score / n_articles
    overall = "bullish" if avg > 0.3 else "bearish" if avg < -0.3 else "neutral"

    print(json.dumps({{
        "symbol": "{symbol}",
        "overall_sentiment": overall,
        "avg_score": round(avg, 2),
        "positive_count": sum(1 for s in scored if s["sentiment"] == "positive"),
        "negative_count": sum(1 for s in scored if s["sentiment"] == "negative"),
        "neutral_count": sum(1 for s in scored if s["sentiment"] == "neutral"),
        "articles": scored,
    }}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=20)
        return result.get("data", {})

    async def sector_sentiment(self, sector: str = "Technology") -> dict[str, Any]:
        """Aggregate sentiment for a sector."""
        sector_tickers = {
            "Technology": ["AAPL", "MSFT", "GOOGL", "NVDA", "META"],
            "Finance": ["JPM", "BAC", "GS", "MS", "WFC"],
            "Healthcare": ["UNH", "JNJ", "PFE", "ABBV", "MRK"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
            "Consumer": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
        }
        tickers = sector_tickers.get(sector, sector_tickers["Technology"])
        results = {}
        for sym in tickers[:5]:
            results[sym] = await self.sentiment(sym)
        # Aggregate
        total_score = sum(r.get("avg_score", 0) for r in results.values() if isinstance(r, dict))
        n = len(results) or 1
        return {
            "sector": sector,
            "overall": "bullish" if total_score / n > 0.2 else "bearish" if total_score / n < -0.2 else "neutral",
            "avg_score": round(total_score / n, 2),
            "tickers": {k: {"sentiment": v.get("overall_sentiment", ""), "score": v.get("avg_score", 0)} for k, v in results.items() if isinstance(v, dict)},
        }

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_news", "description": "Get recent news for a stock ticker.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_market_news", "description": "Search financial news on any topic.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "fin_sentiment", "description": "Analyze news sentiment for a ticker (bullish/bearish/neutral).", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_sector_sentiment", "description": "Aggregate sentiment for a sector (Technology, Finance, Healthcare, Energy, Consumer).", "parameters": {"type": "object", "properties": {"sector": {"type": "string", "enum": ["Technology", "Finance", "Healthcare", "Energy", "Consumer"]}}, "required": ["sector"]}}},
        ]
