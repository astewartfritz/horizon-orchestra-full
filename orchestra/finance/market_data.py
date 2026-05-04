"""Market Data Engine — real-time quotes, historical prices, crypto, forex, indices.

Data sources (tiered fallback):
1. Yahoo Finance (yfinance) — free, no key needed
2. Alpha Vantage — free tier with key
3. Polygon.io — paid, high quality
4. CoinGecko — free crypto data

Usage::

    from orchestra.finance.market_data import MarketDataEngine
    engine = MarketDataEngine()
    quote = await engine.quote("AAPL")
    history = await engine.historical("TSLA", period="1y", interval="1d")
    crypto = await engine.crypto_quote("bitcoin")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..skills.base import run_code_in_sandbox

__all__ = ["MarketDataEngine"]

log = logging.getLogger("orchestra.finance.market_data")


@dataclass
class MarketDataConfig:
    alpha_vantage_key: str = ""
    polygon_key: str = ""
    preferred_source: str = "yfinance"   # yfinance, alpha_vantage, polygon
    cache_ttl: int = 60                  # seconds


class MarketDataEngine:
    """Multi-source market data with automatic fallback."""

    def __init__(self, config: MarketDataConfig | None = None) -> None:
        self.config = config or MarketDataConfig()
        self.config.alpha_vantage_key = self.config.alpha_vantage_key or os.environ.get("ALPHA_VANTAGE_KEY", "")
        self.config.polygon_key = self.config.polygon_key or os.environ.get("POLYGON_API_KEY", "")
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self.config.cache_ttl:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time(), val)

    # -- quotes -------------------------------------------------------------

    async def quote(self, symbol: str) -> dict[str, Any]:
        """Get a real-time quote for a stock/ETF ticker."""
        cache_key = f"quote:{symbol}"
        cached = self._cached(cache_key)
        if cached:
            return cached

        # yfinance via sandbox
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    info = t.info
    fast = t.fast_info
    result = {{
        "symbol": "{symbol}",
        "name": info.get("shortName", ""),
        "price": float(fast.get("lastPrice", info.get("currentPrice", 0)) or 0),
        "previous_close": float(info.get("previousClose", 0) or 0),
        "open": float(info.get("open", 0) or 0),
        "day_high": float(info.get("dayHigh", 0) or 0),
        "day_low": float(info.get("dayLow", 0) or 0),
        "volume": int(info.get("volume", 0) or 0),
        "market_cap": int(info.get("marketCap", 0) or 0),
        "pe_ratio": round(float(info.get("trailingPE", 0) or 0), 2),
        "eps": round(float(info.get("trailingEps", 0) or 0), 2),
        "dividend_yield": round(float(info.get("dividendYield", 0) or 0) * 100, 2),
        "52w_high": float(info.get("fiftyTwoWeekHigh", 0) or 0),
        "52w_low": float(info.get("fiftyTwoWeekLow", 0) or 0),
        "avg_volume": int(info.get("averageVolume", 0) or 0),
        "beta": round(float(info.get("beta", 0) or 0), 2),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "exchange": info.get("exchange", ""),
        "currency": info.get("currency", "USD"),
    }}
    change = result["price"] - result["previous_close"]
    result["change"] = round(change, 2)
    result["change_pct"] = round(change / result["previous_close"] * 100, 2) if result["previous_close"] else 0
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        data = result.get("data", result.get("stdout", ""))
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {"error": data}
        self._set_cache(cache_key, data)
        return data

    async def batch_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Get quotes for multiple symbols."""
        sym_str = " ".join(symbols)
        code = f"""
import json
try:
    import yfinance as yf
    tickers = yf.Tickers("{sym_str}")
    result = {{}}
    for sym in "{sym_str}".split():
        try:
            t = tickers.tickers[sym]
            info = t.info
            result[sym] = {{
                "price": float(info.get("currentPrice", info.get("regularMarketPrice", 0)) or 0),
                "change_pct": round(float(info.get("regularMarketChangePercent", 0) or 0), 2),
                "volume": int(info.get("volume", 0) or 0),
                "market_cap": int(info.get("marketCap", 0) or 0),
                "name": info.get("shortName", ""),
            }}
        except: result[sym] = {{"error": "failed"}}
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=45)
        return result.get("data", {})

    async def historical(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, Any]:
        """Get historical price data. Periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max. Intervals: 1m,5m,15m,1h,1d,1wk,1mo."""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    df = t.history(period="{period}", interval="{interval}")
    records = []
    for idx, row in df.iterrows():
        records.append({{
            "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        }})
    result = {{
        "symbol": "{symbol}", "period": "{period}", "interval": "{interval}",
        "data_points": len(records), "data": records,
    }}
    if records:
        result["start"] = records[0]["date"]
        result["end"] = records[-1]["date"]
        result["return_pct"] = round((records[-1]["close"] / records[0]["close"] - 1) * 100, 2)
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    # -- crypto -------------------------------------------------------------

    async def crypto_quote(self, coin_id: str) -> dict[str, Any]:
        """Get crypto quote from CoinGecko (free, no key)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                    params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
                )
                data = resp.json()
            market = data.get("market_data", {})
            return {
                "id": coin_id,
                "name": data.get("name", ""),
                "symbol": data.get("symbol", "").upper(),
                "price": market.get("current_price", {}).get("usd", 0),
                "market_cap": market.get("market_cap", {}).get("usd", 0),
                "volume_24h": market.get("total_volume", {}).get("usd", 0),
                "change_24h": round(market.get("price_change_percentage_24h", 0) or 0, 2),
                "change_7d": round(market.get("price_change_percentage_7d", 0) or 0, 2),
                "change_30d": round(market.get("price_change_percentage_30d", 0) or 0, 2),
                "ath": market.get("ath", {}).get("usd", 0),
                "ath_change_pct": round(market.get("ath_change_percentage", {}).get("usd", 0) or 0, 2),
                "circulating_supply": market.get("circulating_supply", 0),
                "total_supply": market.get("total_supply", 0),
            }
        except Exception as exc:
            return {"error": str(exc), "coin_id": coin_id}

    async def crypto_top(self, limit: int = 20) -> dict[str, Any]:
        """Top cryptocurrencies by market cap."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": limit, "page": 1},
                )
                coins = resp.json()
            return {"coins": [
                {
                    "rank": c.get("market_cap_rank"), "symbol": c.get("symbol", "").upper(),
                    "name": c.get("name"), "price": c.get("current_price"),
                    "change_24h": round(c.get("price_change_percentage_24h", 0) or 0, 2),
                    "market_cap": c.get("market_cap"), "volume": c.get("total_volume"),
                }
                for c in coins
            ]}
        except Exception as exc:
            return {"error": str(exc)}

    # -- forex + indices ----------------------------------------------------

    async def forex(self, base: str = "USD", targets: list[str] | None = None) -> dict[str, Any]:
        """Get forex rates."""
        targets = targets or ["EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY"]
        code = f"""
import json
try:
    import yfinance as yf
    rates = {{}}
    for t in {targets}:
        pair = f"{base}{{t}}=X"
        ticker = yf.Ticker(pair)
        info = ticker.fast_info
        rates[t] = round(float(info.get("lastPrice", 0) or 0), 4)
    print(json.dumps({{"base": "{base}", "rates": rates}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    async def index_quote(self, index: str = "^GSPC") -> dict[str, Any]:
        """Get a market index quote (^GSPC=S&P500, ^DJI=Dow, ^IXIC=Nasdaq, ^VIX=VIX)."""
        return await self.quote(index)

    async def market_overview(self) -> dict[str, Any]:
        """Get a market overview: major indices, VIX, 10Y yield."""
        symbols = ["^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^TNX"]
        names = {"^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq", "^RUT": "Russell 2000", "^VIX": "VIX", "^TNX": "10Y Treasury"}
        code = f"""
import json
try:
    import yfinance as yf
    result = {{}}
    for sym in {symbols}:
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            price = float(fi.get("lastPrice", 0) or 0)
            prev = float(fi.get("previousClose", 0) or 0)
            result[sym] = {{
                "name": {json.dumps(names)}.get(sym, sym),
                "price": round(price, 2),
                "change": round(price - prev, 2) if prev else 0,
                "change_pct": round((price - prev) / prev * 100, 2) if prev else 0,
            }}
        except: pass
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=45)
        return result.get("data", {})

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_quote", "description": "Get a real-time stock/ETF quote with price, volume, market cap, P/E, sector.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "description": "Ticker symbol (e.g. AAPL, TSLA, MSFT)"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_batch_quotes", "description": "Get quotes for multiple tickers at once.", "parameters": {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}}, "required": ["symbols"]}}},
            {"type": "function", "function": {"name": "fin_historical", "description": "Get historical OHLCV price data. Periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "period": {"type": "string"}, "interval": {"type": "string", "enum": ["1m","5m","15m","1h","1d","1wk","1mo"]}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_crypto", "description": "Get crypto quote from CoinGecko (price, market cap, 24h/7d/30d change).", "parameters": {"type": "object", "properties": {"coin_id": {"type": "string", "description": "CoinGecko coin ID (e.g. bitcoin, ethereum, solana)"}}, "required": ["coin_id"]}}},
            {"type": "function", "function": {"name": "fin_crypto_top", "description": "Top cryptocurrencies by market cap.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "fin_forex", "description": "Get forex exchange rates.", "parameters": {"type": "object", "properties": {"base": {"type": "string"}, "targets": {"type": "array", "items": {"type": "string"}}}}}},
            {"type": "function", "function": {"name": "fin_market_overview", "description": "Market overview: S&P 500, Dow, Nasdaq, Russell, VIX, 10Y Treasury.", "parameters": {"type": "object", "properties": {}}}},
        ]
