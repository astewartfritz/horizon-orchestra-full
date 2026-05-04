"""Fundamentals Analyzer — financials, ratios, earnings, guidance, SEC filings.

Bloomberg-grade fundamental analysis: income statement, balance sheet,
cash flow, key ratios, earnings history, analyst estimates, and insider
transactions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..skills.base import run_code_in_sandbox

__all__ = ["FundamentalsAnalyzer"]

log = logging.getLogger("orchestra.finance.fundamentals")


class FundamentalsAnalyzer:
    """Deep fundamental analysis engine."""

    async def financials(self, symbol: str, statement: str = "income", period: str = "annual") -> dict[str, Any]:
        """Get financial statements (income, balance, cashflow)."""
        stmt_map = {"income": "income_stmt", "balance": "balance_sheet", "cashflow": "cashflow"}
        attr = stmt_map.get(statement, "income_stmt")
        suffix = "" if period == "annual" else "_quarterly" if "quarter" in period else ""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    df = getattr(t, "{attr}{suffix}", t.{attr})
    if df is None or df.empty:
        df = t.{attr}
    data = {{}}
    for col in df.columns[:8]:
        period_key = str(col.date()) if hasattr(col, "date") else str(col)
        data[period_key] = {{}}
        for idx in df.index:
            val = df.loc[idx, col]
            if val is not None and str(val) != "nan":
                data[period_key][str(idx)] = float(val) if isinstance(val, (int, float)) else str(val)
    print(json.dumps({{"symbol": "{symbol}", "statement": "{statement}", "period": "{period}", "data": data}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    async def ratios(self, symbol: str) -> dict[str, Any]:
        """Key financial ratios: valuation, profitability, liquidity, leverage."""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    info = t.info
    g = lambda k, d=0: round(float(info.get(k, d) or d), 4)
    ratios = {{
        "symbol": "{symbol}", "name": info.get("shortName", ""),
        "valuation": {{
            "pe_trailing": g("trailingPE"), "pe_forward": g("forwardPE"),
            "peg": g("pegRatio"), "ps": g("priceToSalesTrailing12Months"),
            "pb": g("priceToBook"), "ev_ebitda": g("enterpriseToEbitda"),
            "ev_revenue": g("enterpriseToRevenue"),
        }},
        "profitability": {{
            "gross_margin": g("grossMargins"), "operating_margin": g("operatingMargins"),
            "profit_margin": g("profitMargins"), "roe": g("returnOnEquity"),
            "roa": g("returnOnAssets"),
        }},
        "growth": {{
            "revenue_growth": g("revenueGrowth"), "earnings_growth": g("earningsGrowth"),
            "earnings_quarterly_growth": g("earningsQuarterlyGrowth"),
        }},
        "liquidity": {{
            "current_ratio": g("currentRatio"), "quick_ratio": g("quickRatio"),
        }},
        "leverage": {{
            "debt_to_equity": g("debtToEquity"), "total_debt": int(info.get("totalDebt", 0) or 0),
            "total_cash": int(info.get("totalCash", 0) or 0),
        }},
        "dividends": {{
            "yield": g("dividendYield") * 100 if info.get("dividendYield") else 0,
            "payout_ratio": g("payoutRatio"),
            "ex_date": info.get("exDividendDate", ""),
        }},
    }}
    print(json.dumps(ratios))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    async def earnings(self, symbol: str) -> dict[str, Any]:
        """Earnings history + analyst estimates."""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    # Earnings history
    eh = t.earnings_history
    hist = []
    if eh is not None and not eh.empty:
        for _, row in eh.iterrows():
            hist.append({{k: (round(float(v), 4) if isinstance(v, (int,float)) else str(v)) for k, v in row.items() if str(v) != "nan"}})
    # Analyst estimates
    rec = t.recommendations
    recs = []
    if rec is not None and not rec.empty:
        for _, row in rec.tail(5).iterrows():
            recs.append({{k: str(v) for k, v in row.items()}})
    # Earnings dates
    cal = t.calendar
    cal_data = {{}}
    if cal is not None:
        if hasattr(cal, "items"):
            cal_data = {{str(k): str(v) for k, v in cal.items()}}
        elif hasattr(cal, "to_dict"):
            cal_data = {{str(k): str(v) for k, v in cal.to_dict().items()}}
    print(json.dumps({{"symbol": "{symbol}", "earnings_history": hist[:12], "recommendations": recs, "calendar": cal_data}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    async def insiders(self, symbol: str) -> dict[str, Any]:
        """Insider transactions."""
        code = f"""
import json
try:
    import yfinance as yf
    t = yf.Ticker("{symbol}")
    ins = t.insider_transactions
    txns = []
    if ins is not None and not ins.empty:
        for _, row in ins.head(20).iterrows():
            txns.append({{k: str(v) for k, v in row.items() if str(v) != "nan"}})
    holders = t.major_holders
    major = []
    if holders is not None and not holders.empty:
        for _, row in holders.iterrows():
            major.append({{str(k): str(v) for k, v in row.items()}})
    inst = t.institutional_holders
    institutions = []
    if inst is not None and not inst.empty:
        for _, row in inst.head(10).iterrows():
            institutions.append({{k: (round(float(v), 2) if isinstance(v, (int,float)) else str(v)) for k, v in row.items() if str(v) != "nan"}})
    print(json.dumps({{"symbol": "{symbol}", "insider_transactions": txns, "major_holders": major, "institutional_holders": institutions}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=30)
        return result.get("data", {})

    async def compare(self, symbols: list[str]) -> dict[str, Any]:
        """Compare fundamentals across multiple stocks."""
        sym_str = repr(symbols)
        code = f"""
import json
try:
    import yfinance as yf
    result = {{}}
    for sym in {sym_str}:
        t = yf.Ticker(sym)
        info = t.info
        g = lambda k, d=0: round(float(info.get(k, d) or d), 2)
        result[sym] = {{
            "name": info.get("shortName", ""), "price": g("currentPrice"),
            "market_cap": int(info.get("marketCap", 0) or 0),
            "pe": g("trailingPE"), "pb": g("priceToBook"), "ps": g("priceToSalesTrailing12Months"),
            "roe": g("returnOnEquity"), "profit_margin": g("profitMargins"),
            "revenue_growth": g("revenueGrowth"), "debt_to_equity": g("debtToEquity"),
            "dividend_yield": g("dividendYield"), "beta": g("beta"),
            "sector": info.get("sector", ""),
        }}
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=60)
        return result.get("data", {})

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_financials", "description": "Get financial statements (income, balance sheet, cash flow).", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "statement": {"type": "string", "enum": ["income", "balance", "cashflow"]}, "period": {"type": "string", "enum": ["annual", "quarterly"]}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_ratios", "description": "Key financial ratios: valuation (P/E, P/B, EV/EBITDA), profitability (margins, ROE), growth, liquidity, leverage.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_earnings", "description": "Earnings history, analyst recommendations, and upcoming earnings dates.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_insiders", "description": "Insider transactions, major holders, and top institutional holders.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_compare", "description": "Compare fundamentals across multiple stocks side by side.", "parameters": {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}}, "required": ["symbols"]}}},
        ]
