"""Market data client for Orchestra Finance.

Sources (in fallback order):
  1. Yahoo Finance v8/chart  — no key, working as of 2026
  2. Finnhub                 — FINNHUB_API_KEY  (free: 60 req/min)
  3. Alpha Vantage           — ALPHA_VANTAGE_KEY (free: 25 req/day)
  4. CoinGecko               — no key, crypto only

All methods are async (httpx). Results are TTL-cached.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
import xml.etree.ElementTree as ET
import html as _html
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("code_agent.finance.market")

try:
    import httpx as _httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False

# ── Config ────────────────────────────────────────────────────────────────────

FINNHUB_KEY   = os.environ.get("FINNHUB_API_KEY", "")
ALPHA_KEY     = os.environ.get("ALPHA_VANTAGE_KEY", "")

_YF_BASE      = "https://query1.finance.yahoo.com"
_YF_BASE2     = "https://query2.finance.yahoo.com"
_FINNHUB_BASE = "https://finnhub.io/api/v1"
_AV_BASE      = "https://www.alphavantage.co/query"
_CG_BASE      = "https://api.coingecko.com/api/v3"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── TTL cache ─────────────────────────────────────────────────────────────────

@dataclass
class _CE:
    data: Any
    ts: float

class _TTLCache:
    def __init__(self, ttl: float = 30.0) -> None:
        self._s: dict[str, _CE] = {}
        self.ttl = ttl

    def get(self, k: str, ttl: float | None = None) -> Any:
        e = self._s.get(k)
        return e.data if (e and time.time() - e.ts < (ttl or self.ttl)) else None

    def set(self, k: str, v: Any) -> None:
        self._s[k] = _CE(v, time.time())


# ── Shapes ────────────────────────────────────────────────────────────────────

def _qs() -> dict:
    """Empty quote skeleton — field names match the JS."""
    return {
        "symbol": "", "name": "", "exchange": "", "currency": "USD",
        "price": None, "previous_close": None, "open": None,
        "high": None, "low": None, "change": None, "change_pct": None,
        "volume": None, "market_cap": None, "pe_ratio": None,
        "week_52_high": None, "week_52_low": None,
        "market_state": "REGULAR", "source": "yahoo",
    }

def _candle(date: str, o: float, h: float, l: float, c: float, v: int) -> dict:
    return {"time": date, "open": round(o, 4), "high": round(h, 4),
            "low": round(l, 4), "close": round(c, 4), "volume": v}

def _f(v, digits=4) -> float | None:
    try:
        x = float(v)
        return round(x, digits) if x else None
    except (TypeError, ValueError):
        return None

def _i(v) -> int | None:
    try:
        x = int(v)
        return x if x else None
    except (TypeError, ValueError):
        return None


# ── Client ────────────────────────────────────────────────────────────────────

class MarketClient:

    def __init__(self) -> None:
        # Use the shared TTLCache; longer TTLs reduce Yahoo Finance pressure
        try:
            from orchestra.code_agent.cache.ttl import price_cache, news_cache, search_cache
            self._price_cache = price_cache
            self._news_cache = news_cache
            self._search_cache = search_cache
        except Exception:
            self._price_cache = _TTLCache(ttl=60.0)
            self._news_cache = _TTLCache(ttl=300.0)
            self._search_cache = _TTLCache(ttl=600.0)
        # Historical data doesn't change fast — 5 min TTL
        self._hist_cache = _TTLCache(ttl=300.0)

    def _cache_get(self, key: str, ttl: float | None = None) -> Any:
        if key.startswith("q:") or key.startswith("mv:"):
            return self._price_cache.get(key)
        if key.startswith("n:"):
            return self._news_cache.get(key)
        if key.startswith("s:"):
            return self._search_cache.get(key)
        if key.startswith("h:"):
            return self._hist_cache.get(key)
        return None

    def _cache_set(self, key: str, val: Any) -> None:
        if key.startswith("q:") or key.startswith("mv:"):
            self._price_cache.set(key, val)
        elif key.startswith("n:"):
            self._news_cache.set(key, val)
        elif key.startswith("s:"):
            self._search_cache.set(key, val)
        elif key.startswith("h:"):
            self._hist_cache.set(key, val)

    # ── Public API ────────────────────────────────────────────────────────

    async def quote(self, symbol: str) -> dict:
        sym = symbol.upper().strip()
        cached = self._cache_get(f"q:{sym}")
        if cached:
            return cached
        if sym.endswith("-USD") or sym in _CRYPTO_COINS:
            data = await self._cg_quote(sym)
        else:
            data = await self._yf_quote(sym)
            if data.get("price") is None and FINNHUB_KEY:
                data = await self._fh_quote(sym)
        if data.get("price") is not None:
            self._cache_set(f"q:{sym}", data)
        return data

    async def batch_quotes(self, symbols: list[str]) -> list[dict]:
        syms = [s.upper().strip() for s in symbols]
        crypto = [s for s in syms if s.endswith("-USD") or s in _CRYPTO_COINS]
        equities = [s for s in syms if s not in crypto]

        tasks = [self._yf_quote(s) for s in equities] + [self._cg_quote(s) for s in crypto]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out = []
        for res in results:
            if isinstance(res, Exception):
                continue
            if res.get("price") is not None:
                out.append(res)
        return out

    async def historical(self, symbol: str, range: str = "6mo", interval: str = "1d") -> list[dict]:
        sym = symbol.upper().strip()
        key = f"h:{sym}:{range}:{interval}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        candles = await self._yf_chart(sym, range, interval)
        if not candles and ALPHA_KEY:
            candles = await self._av_chart(sym, interval)
        self._cache_set(key, candles)
        return candles

    async def news(self, symbol: str = "", limit: int = 10) -> list[dict]:
        sym = symbol.upper().strip()
        key = f"n:{sym}:{limit}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        articles: list[dict] = []
        if FINNHUB_KEY:
            articles = await self._fh_news(sym, limit)
        if not articles:
            articles = await self._yf_news(sym, limit)
        if not articles:
            articles = await self._rss_news(sym, limit)
        self._cache_set(key, articles)
        return articles

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        key = f"s:{query}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        results = await self._yf_search(query, limit)
        self._cache_set(key, results)
        return results

    async def movers(self, direction: str = "gainers") -> list[dict]:
        key = f"mv:{direction}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = await self._yf_movers(direction)
        self._cache_set(key, data)
        return data

    async def indices(self) -> list[dict]:
        """S&P 500, Nasdaq, Dow, Russell, VIX — returned as a list."""
        syms = ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"]
        return await self.batch_quotes(syms)

    # =========================================================================
    # Private — Yahoo Finance v8/chart (quotes + history)
    # =========================================================================

    async def _yf_quote(self, symbol: str) -> dict:
        """Single quote via v8/chart meta — the only YF endpoint that still works."""
        url = f"{_YF_BASE}/v8/finance/chart/{symbol}"
        try:
            async with _http() as c:
                r = await c.get(url, params={"interval": "1d", "range": "5d"})
            raw = r.json()
            chart = raw.get("chart", {})
            if chart.get("error"):
                return {**_qs(), "symbol": symbol, "source": "yahoo"}
            result = (chart.get("result") or [])
            if not result:
                return {**_qs(), "symbol": symbol, "source": "yahoo"}
            meta = result[0].get("meta", {})
            price = _f(meta.get("regularMarketPrice"))
            prev  = _f(meta.get("chartPreviousClose") or meta.get("previousClose"))
            if price is None:
                return {**_qs(), "symbol": symbol}
            change = round(price - (prev or price), 4) if prev else None
            change_pct = round(change / prev * 100, 2) if (change is not None and prev) else None
            q = _qs()
            q.update({
                "symbol":       meta.get("symbol", symbol),
                "name":         meta.get("longName") or meta.get("shortName", ""),
                "exchange":     meta.get("fullExchangeName") or meta.get("exchangeName", ""),
                "currency":     meta.get("currency", "USD"),
                "price":        price,
                "previous_close": prev,
                "open":         _f(meta.get("regularMarketOpen")),
                "high":         _f(meta.get("regularMarketDayHigh")),
                "low":          _f(meta.get("regularMarketDayLow")),
                "change":       change,
                "change_pct":   change_pct,
                "volume":       _i(meta.get("regularMarketVolume")),
                "market_cap":   _i(meta.get("marketCap")),
                "pe_ratio":     _f(meta.get("trailingPE"), 2),
                "week_52_high": _f(meta.get("fiftyTwoWeekHigh")),
                "week_52_low":  _f(meta.get("fiftyTwoWeekLow")),
                "market_state": meta.get("marketState", "REGULAR"),
                "source":       "yahoo",
            })
            return q
        except Exception as exc:
            log.debug("YF quote error %s: %s", symbol, exc)
            return {**_qs(), "symbol": symbol}

    async def _yf_chart(self, symbol: str, range: str, interval: str) -> list[dict]:
        url = f"{_YF_BASE}/v8/finance/chart/{symbol}"
        try:
            async with _http() as c:
                r = await c.get(url, params={"range": range, "interval": interval, "includeAdjustedClose": "true"})
            raw = r.json()
            chart = raw.get("chart", {})
            if chart.get("error"):
                return []
            result = (chart.get("result") or [])
            if not result:
                return []
            res = result[0]
            timestamps = res.get("timestamp") or []
            ind = res.get("indicators", {})
            ohlcv = (ind.get("quote") or [{}])[0]
            opens  = ohlcv.get("open",   [])
            highs  = ohlcv.get("high",   [])
            lows   = ohlcv.get("low",    [])
            closes = ohlcv.get("close",  [])
            vols   = ohlcv.get("volume", [])
            candles = []
            for i, ts in enumerate(timestamps):
                if ts is None:
                    continue
                o  = opens[i]  if i < len(opens)  and opens[i]  is not None else None
                h  = highs[i]  if i < len(highs)  and highs[i]  is not None else None
                l  = lows[i]   if i < len(lows)   and lows[i]   is not None else None
                cl = closes[i] if i < len(closes) and closes[i] is not None else None
                v  = vols[i]   if i < len(vols)   and vols[i]   is not None else 0
                if None in (o, h, l, cl):
                    continue
                date = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
                candles.append(_candle(date, o, h, l, cl, int(v or 0)))
            return candles
        except Exception as exc:
            log.debug("YF chart error %s: %s", symbol, exc)
            return []

    async def _yf_news(self, symbol: str, limit: int) -> list[dict]:
        # v2 news — may return 401; falls through to RSS if so
        url = (f"{_YF_BASE}/v2/finance/news?symbol={symbol}&newsCount={limit}"
               if symbol else f"{_YF_BASE}/v2/finance/news?category=generalnews&newsCount={limit}")
        try:
            async with _http() as c:
                r = await c.get(url)
            if r.status_code != 200:
                return []
            raw = r.json()
            items = raw.get("items", {}).get("result", raw.get("news", []))
            return [_norm_article(n) for n in items[:limit]]
        except Exception:
            return []

    async def _yf_search(self, query: str, limit: int) -> list[dict]:
        url = f"{_YF_BASE}/v1/finance/search"
        try:
            async with _http() as c:
                r = await c.get(url, params={"q": query, "quotesCount": limit, "newsCount": 0})
            raw = r.json()
            return [{"symbol": q.get("symbol",""), "name": q.get("longname") or q.get("shortname",""),
                     "type": q.get("quoteType",""), "exchange": q.get("exchange","")}
                    for q in raw.get("quotes", [])[:limit]]
        except Exception:
            return []

    async def _yf_movers(self, direction: str) -> list[dict]:
        slug = {"gainers": "day-gainers", "losers": "day-losers", "active": "most-actives"}.get(direction, "day-gainers")
        url = f"{_YF_BASE}/screener/predefined/saved"
        try:
            async with _http() as c:
                r = await c.get(url, params={"formatted": "false", "scrIds": slug, "count": 20})
            raw = r.json()
            rows = (raw.get("finance", {}).get("result") or [{}])[0].get("quotes", [])
            return [{"symbol": q.get("symbol",""), "name": q.get("shortName",""),
                     "price": _f(q.get("regularMarketPrice"), 2),
                     "change_pct": _f(q.get("regularMarketChangePercent"), 2),
                     "volume": _i(q.get("regularMarketVolume"))} for q in rows]
        except Exception:
            return []

    # =========================================================================
    # Private — Finnhub
    # =========================================================================

    async def _fh_quote(self, symbol: str) -> dict:
        try:
            async with _http() as c:
                r = await c.get(f"{_FINNHUB_BASE}/quote", params={"symbol": symbol, "token": FINNHUB_KEY})
            q = r.json()
            if not q.get("c"):
                return {**_qs(), "symbol": symbol}
            price = _f(q.get("c"))
            prev  = _f(q.get("pc"))
            out = _qs()
            out.update({
                "symbol": symbol, "price": price, "previous_close": prev,
                "high": _f(q.get("h")), "low": _f(q.get("l")), "open": _f(q.get("o")),
                "change": _f(q.get("d")), "change_pct": _f(q.get("dp"), 2),
                "source": "finnhub",
            })
            return out
        except Exception:
            return {**_qs(), "symbol": symbol}

    async def _fh_news(self, symbol: str, limit: int) -> list[dict]:
        today = datetime.date.today()
        from_d = (today - datetime.timedelta(days=7)).isoformat()
        to_d = today.isoformat()
        url = (f"{_FINNHUB_BASE}/company-news" if symbol else f"{_FINNHUB_BASE}/news")
        params = ({"symbol": symbol, "from": from_d, "to": to_d, "token": FINNHUB_KEY}
                  if symbol else {"category": "general", "token": FINNHUB_KEY})
        try:
            async with _http() as c:
                r = await c.get(url, params=params)
            items = r.json()
            if not isinstance(items, list):
                return []
            return [{"title": n.get("headline",""), "summary": n.get("summary",""),
                     "url": n.get("url",""), "source": n.get("source",""),
                     "published_at": n.get("datetime", 0), "image": n.get("image","")}
                    for n in items[:limit]]
        except Exception:
            return []

    # =========================================================================
    # Private — Alpha Vantage (historical fallback)
    # =========================================================================

    async def _av_chart(self, symbol: str, interval: str) -> list[dict]:
        fn_map = {"1d": "TIME_SERIES_DAILY_ADJUSTED", "1wk": "TIME_SERIES_WEEKLY_ADJUSTED", "1mo": "TIME_SERIES_MONTHLY_ADJUSTED"}
        fn = fn_map.get(interval)
        if not fn:
            mins = interval.replace("m", "").replace("min", "")
            fn = "TIME_SERIES_INTRADAY"
            ts_key = f"Time Series ({mins}min)"
            params = {"function": fn, "symbol": symbol, "interval": f"{mins}min", "outputsize": "compact", "apikey": ALPHA_KEY}
        else:
            ts_key = {"TIME_SERIES_DAILY_ADJUSTED": "Time Series (Daily)",
                      "TIME_SERIES_WEEKLY_ADJUSTED": "Weekly Adjusted Time Series",
                      "TIME_SERIES_MONTHLY_ADJUSTED": "Monthly Adjusted Time Series"}[fn]
            params = {"function": fn, "symbol": symbol, "outputsize": "compact", "apikey": ALPHA_KEY}
        try:
            async with _http() as c:
                r = await c.get(_AV_BASE, params=params)
            series = r.json().get(ts_key, {})
            return [_candle(d, float(v.get("1. open",0)), float(v.get("2. high",0)),
                            float(v.get("3. low",0)),
                            float(v.get("5. adjusted close", v.get("4. close",0))),
                            int(v.get("6. volume", v.get("5. volume",0))))
                    for d, v in sorted(series.items())]
        except Exception:
            return []

    # =========================================================================
    # Private — CoinGecko (crypto)
    # =========================================================================

    async def _cg_quote(self, symbol: str) -> dict:
        coin_id = _cg_id(symbol)
        try:
            async with _http() as c:
                r = await c.get(f"{_CG_BASE}/simple/price", params={
                    "ids": coin_id, "vs_currencies": "usd",
                    "include_market_cap": "true", "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                })
            d = r.json().get(coin_id, {})
            if not d:
                return {**_qs(), "symbol": symbol}
            price = float(d.get("usd", 0))
            chg_pct = float(d.get("usd_24h_change", 0))
            prev = price / (1 + chg_pct / 100) if chg_pct else price
            change = round(price - prev, 6)
            out = _qs()
            out.update({
                "symbol": symbol, "name": coin_id.replace("-", " ").title(),
                "price": round(price, 6), "previous_close": round(prev, 6),
                "change": round(change, 6), "change_pct": round(chg_pct, 2),
                "volume": _i(d.get("usd_24h_vol")),
                "market_cap": _i(d.get("usd_market_cap")),
                "currency": "USD", "source": "coingecko",
            })
            return out
        except Exception as exc:
            log.debug("CoinGecko error %s: %s", symbol, exc)
            return {**_qs(), "symbol": symbol}

    # =========================================================================
    # Private — RSS news fallback
    # =========================================================================

    async def _rss_news(self, symbol: str, limit: int) -> list[dict]:
        q = symbol if symbol else "stock market"
        url = f"https://news.google.com/rss/search?q={q}+finance&hl=en-US&gl=US&ceid=US:en"
        try:
            async with _http() as c:
                r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.text)
            return [{"title": _html.unescape(item.findtext("title","")),
                     "url":   item.findtext("link",""),
                     "source": item.findtext("source","Google News"),
                     "published_at": 0, "summary": "", "image": ""}
                    for item in root.findall(".//item")[:limit]]
        except Exception:
            return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _http():
    if not _HTTPX:
        raise ImportError("httpx required: pip install httpx")
    return _httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True)

def _norm_article(n: dict) -> dict:
    return {
        "title":        n.get("title") or n.get("headline", ""),
        "summary":      n.get("summary", ""),
        "url":          n.get("link") or n.get("url", ""),
        "source":       n.get("publisher") or n.get("source", ""),
        "published_at": n.get("providerPublishTime") or n.get("datetime", 0),
        "image":        (n.get("thumbnail", {}) or {}).get("resolutions", [{}])[0].get("url", ""),
    }

_CRYPTO_COINS = {
    "BTC-USD","ETH-USD","SOL-USD","ADA-USD","XRP-USD","DOGE-USD",
    "AVAX-USD","DOT-USD","MATIC-USD","LINK-USD","BNB-USD","LTC-USD",
    "ATOM-USD","UNI-USD","NEAR-USD",
}

_CG_MAP = {
    "BTC-USD":"bitcoin","ETH-USD":"ethereum","SOL-USD":"solana",
    "ADA-USD":"cardano","XRP-USD":"ripple","DOGE-USD":"dogecoin",
    "AVAX-USD":"avalanche-2","DOT-USD":"polkadot","MATIC-USD":"matic-network",
    "LINK-USD":"chainlink","BNB-USD":"binancecoin","LTC-USD":"litecoin",
    "ATOM-USD":"cosmos","UNI-USD":"uniswap","NEAR-USD":"near",
}

def _cg_id(symbol: str) -> str:
    if symbol in _CG_MAP:
        return _CG_MAP[symbol]
    return symbol.replace("-USD","").replace("USDT","").lower()


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: MarketClient | None = None

def get_client() -> MarketClient:
    global _client
    if _client is None:
        _client = MarketClient()
    return _client
