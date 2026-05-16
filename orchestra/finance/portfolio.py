"""Portfolio Tracker — holdings, P&L, allocation, risk metrics, benchmarking.

Track positions, compute returns, risk-adjusted metrics (Sharpe, Sortino,
max drawdown), sector allocation, and benchmark vs S&P 500.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..skills.base import run_code_in_sandbox

__all__ = ["PortfolioTracker"]
log = logging.getLogger("orchestra.finance.portfolio")


@dataclass
class Position:
    symbol: str
    shares: float
    cost_basis: float      # total cost (shares * avg_price_paid)


class PortfolioTracker:
    """Portfolio analysis engine."""

    def __init__(self) -> None:
        self._portfolios: dict[str, list[Position]] = {}

    def set_portfolio(self, name: str, positions: list[dict[str, Any]]) -> None:
        self._portfolios[name] = [
            Position(symbol=p["symbol"], shares=p["shares"], cost_basis=p["cost_basis"])
            for p in positions
        ]

    async def analyze(self, positions: list[dict[str, Any]], benchmark: str = "SPY") -> dict[str, Any]:
        """Full portfolio analysis: current value, P&L, allocation, risk, benchmark comparison."""
        pos_json = json.dumps(positions)
        code = f"""
import json
try:
    import yfinance as yf
    import numpy as np

    positions = json.loads('{pos_json}')
    benchmark = "{benchmark}"

    holdings = []
    total_value = 0
    total_cost = 0

    for p in positions:
        sym, shares, cost = p["symbol"], p["shares"], p["cost_basis"]
        try:
            t = yf.Ticker(sym)
            price = float(t.fast_info.get("lastPrice", 0) or 0)
            current_value = price * shares
            gain = current_value - cost
            holdings.append({{
                "symbol": sym, "shares": shares, "cost_basis": round(cost, 2),
                "current_price": round(price, 2), "current_value": round(current_value, 2),
                "gain_loss": round(gain, 2),
                "return_pct": round(gain / cost * 100, 2) if cost else 0,
                "weight": 0,  # filled in below
            }})
            total_value += current_value
            total_cost += cost
        except: pass

    # Compute weights
    for h in holdings:
        h["weight"] = round(h["current_value"] / total_value * 100, 2) if total_value else 0

    # Portfolio returns (1Y daily)
    symbols = [p["symbol"] for p in positions]
    weights_arr = [h["current_value"] / total_value if total_value else 0 for h in holdings]

    import pandas as pd
    prices = yf.download(symbols + [benchmark], period="1y", interval="1d", progress=False)["Close"]
    if len(symbols) == 1:
        prices = prices.to_frame(symbols[0])

    daily_returns = prices.pct_change().dropna()

    # Portfolio weighted returns
    port_returns = sum(daily_returns[sym] * w for sym, w in zip(symbols, weights_arr) if sym in daily_returns.columns)
    bench_returns = daily_returns[benchmark] if benchmark in daily_returns.columns else port_returns * 0

    # Risk metrics
    annual_return = float(port_returns.mean() * 252)
    annual_vol = float(port_returns.std() * np.sqrt(252))
    sharpe = round(annual_return / annual_vol, 2) if annual_vol else 0
    downside = port_returns[port_returns < 0].std() * np.sqrt(252)
    sortino = round(annual_return / float(downside), 2) if downside else 0

    # Max drawdown
    cumulative = (1 + port_returns).cumprod()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = round(float(drawdown.min()) * 100, 2)

    # Benchmark comparison
    bench_annual = float(bench_returns.mean() * 252)
    alpha = round((annual_return - bench_annual) * 100, 2)

    result = {{
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_gain": round(total_value - total_cost, 2),
        "total_return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
        "holdings": holdings,
        "risk_metrics": {{
            "annual_return_pct": round(annual_return * 100, 2),
            "annual_volatility_pct": round(annual_vol * 100, 2),
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown_pct": max_dd,
            "alpha_vs_benchmark": alpha,
            "benchmark": benchmark,
        }},
        "allocation": {{h["symbol"]: h["weight"] for h in holdings}},
    }}
    print(json.dumps(result))
except Exception as e:
    import traceback
    print(json.dumps({{"error": str(e), "trace": traceback.format_exc()[:500]}}))
"""
        result = await run_code_in_sandbox(code, timeout=60)
        return result.get("data", {})

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_portfolio", "description": "Analyze a portfolio: current value, P&L, allocation, Sharpe, Sortino, max drawdown, alpha vs benchmark.", "parameters": {"type": "object", "properties": {"positions": {"type": "array", "items": {"type": "object", "properties": {"symbol": {"type": "string"}, "shares": {"type": "number"}, "cost_basis": {"type": "number"}}, "required": ["symbol", "shares", "cost_basis"]}}, "benchmark": {"type": "string", "description": "Benchmark ticker (default: SPY)"}}, "required": ["positions"]}}},
        ]
