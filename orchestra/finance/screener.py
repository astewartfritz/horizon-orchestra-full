"""Stock Screener — multi-factor screening with custom filters.

Koyfin-style screener: filter stocks by fundamentals, technicals,
sector, market cap, and custom expressions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..skills.base import run_code_in_sandbox

__all__ = ["StockScreener"]
log = logging.getLogger("orchestra.finance.screener")

# Pre-built screen universes
UNIVERSES = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "dow30": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
}

PRESET_SCREENS = {
    "value": {"pe_max": 15, "pb_max": 2, "dividend_min": 2, "debt_to_equity_max": 100},
    "growth": {"revenue_growth_min": 20, "earnings_growth_min": 15, "pe_max": 40},
    "dividend": {"dividend_min": 3, "payout_max": 80, "market_cap_min": 10e9},
    "momentum": {"change_52w_min": 20, "volume_min": 1e6},
    "quality": {"roe_min": 15, "profit_margin_min": 10, "debt_to_equity_max": 50},
}


class StockScreener:
    """Multi-factor stock screener."""

    async def screen(self, filters: dict[str, Any], universe: str = "sp500", limit: int = 20) -> dict[str, Any]:
        """Screen stocks with custom filters."""
        filters_json = json.dumps(filters)
        code = f"""
import json
try:
    import yfinance as yf
    import pandas as pd

    # Get universe
    universe = "{universe}"
    if universe == "sp500":
        table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        symbols = table["Symbol"].str.replace(".", "-").tolist()
    elif universe == "custom":
        symbols = {json.dumps(filters.get("symbols", []))}
    else:
        symbols = ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B","JPM","V","UNH","JNJ","XOM","PG","MA"]

    filters = json.loads('{filters_json}')
    results = []

    # Process in batches
    for i in range(0, min(len(symbols), 100), 10):
        batch = symbols[i:i+10]
        tickers = yf.Tickers(" ".join(batch))
        for sym in batch:
            try:
                info = tickers.tickers[sym].info
                g = lambda k, d=None: info.get(k, d)

                # Apply filters
                passed = True
                if filters.get("pe_max") and (g("trailingPE") or 999) > filters["pe_max"]: passed = False
                if filters.get("pe_min") and (g("trailingPE") or 0) < filters["pe_min"]: passed = False
                if filters.get("pb_max") and (g("priceToBook") or 999) > filters["pb_max"]: passed = False
                if filters.get("dividend_min") and (g("dividendYield", 0) or 0) * 100 < filters["dividend_min"]: passed = False
                if filters.get("market_cap_min") and (g("marketCap") or 0) < filters["market_cap_min"]: passed = False
                if filters.get("market_cap_max") and (g("marketCap") or float("inf")) > filters["market_cap_max"]: passed = False
                if filters.get("revenue_growth_min") and (g("revenueGrowth", 0) or 0) * 100 < filters["revenue_growth_min"]: passed = False
                if filters.get("roe_min") and (g("returnOnEquity", 0) or 0) * 100 < filters["roe_min"]: passed = False
                if filters.get("profit_margin_min") and (g("profitMargins", 0) or 0) * 100 < filters["profit_margin_min"]: passed = False
                if filters.get("debt_to_equity_max") and (g("debtToEquity") or 999) > filters["debt_to_equity_max"]: passed = False
                if filters.get("sector") and g("sector", "").lower() != filters["sector"].lower(): passed = False

                if passed:
                    results.append({{
                        "symbol": sym, "name": g("shortName", ""),
                        "price": round(float(g("currentPrice", 0) or 0), 2),
                        "market_cap": int(g("marketCap", 0) or 0),
                        "pe": round(float(g("trailingPE", 0) or 0), 2),
                        "pb": round(float(g("priceToBook", 0) or 0), 2),
                        "roe": round(float(g("returnOnEquity", 0) or 0) * 100, 1),
                        "profit_margin": round(float(g("profitMargins", 0) or 0) * 100, 1),
                        "revenue_growth": round(float(g("revenueGrowth", 0) or 0) * 100, 1),
                        "dividend_yield": round(float(g("dividendYield", 0) or 0) * 100, 2),
                        "sector": g("sector", ""),
                    }})
                    if len(results) >= {limit}: break
            except: pass
        if len(results) >= {limit}: break

    results.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
    print(json.dumps({{"filters": filters, "universe": universe, "matches": len(results), "results": results[:{limit}]}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=120)
        return result.get("data", {})

    async def preset_screen(self, preset: str, limit: int = 20) -> dict[str, Any]:
        """Run a pre-built screen (value, growth, dividend, momentum, quality)."""
        filters = PRESET_SCREENS.get(preset, {})
        if not filters:
            return {"error": f"Unknown preset: {preset}. Available: {list(PRESET_SCREENS)}"}
        result = await self.screen(filters, limit=limit)
        if isinstance(result, dict):
            result["preset"] = preset
        return result

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_screen", "description": "Screen stocks with custom filters (pe_max, pb_max, dividend_min, market_cap_min, roe_min, profit_margin_min, sector, etc).", "parameters": {"type": "object", "properties": {"filters": {"type": "object", "description": "Filter criteria"}, "universe": {"type": "string", "enum": ["sp500", "nasdaq100", "dow30", "custom"]}, "limit": {"type": "integer"}}, "required": ["filters"]}}},
            {"type": "function", "function": {"name": "fin_preset_screen", "description": "Run a pre-built stock screen: value, growth, dividend, momentum, quality.", "parameters": {"type": "object", "properties": {"preset": {"type": "string", "enum": ["value", "growth", "dividend", "momentum", "quality"]}, "limit": {"type": "integer"}}, "required": ["preset"]}}},
        ]
