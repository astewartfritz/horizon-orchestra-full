"""Finance tool registry — wires all finance modules as agent tools."""

from __future__ import annotations

import json
import logging
from typing import Any

__all__ = ["register_finance_tools"]

log = logging.getLogger("orchestra.finance.registry")


def register_finance_tools(tool_registry: Any) -> None:
    """Register all finance tools into an agent ToolRegistry.

    Call this alongside create_default_tools() to give agents
    Bloomberg-grade financial capabilities.
    """
    from .market_data import MarketDataEngine
    from .fundamentals import FundamentalsAnalyzer
    from .screener import StockScreener
    from .portfolio import PortfolioTracker
    from .charting import ChartingEngine
    from .news import FinanceNews
    from .watchlist import WatchlistManager

    md = MarketDataEngine()
    fa = FundamentalsAnalyzer()
    sc = StockScreener()
    pt = PortfolioTracker()
    ch = ChartingEngine()
    nw = FinanceNews()
    wl = WatchlistManager()

    modules = [md, fa, sc, pt, ch, nw, wl]

    for module in modules:
        for tool_def in module.get_tool_definitions():
            fn = tool_def.get("function", {})
            tool_name = fn.get("name", "")
            if not tool_name:
                continue

            _mod = module
            _action = tool_name

            # Map tool name → method
            dispatch = _build_dispatch(_mod, _action)

            async def _handler(_d=dispatch, **kwargs: Any) -> str:
                result = await _d(**kwargs)
                return json.dumps(result) if isinstance(result, dict) else str(result)

            tool_registry.register(
                name=tool_name,
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {}),
                handler=_handler,
            )

    log.info("Registered %d finance tools", sum(len(m.get_tool_definitions()) for m in modules))


def _build_dispatch(module: Any, action: str) -> Any:
    """Build a dispatch function for a specific tool action."""
    # MarketDataEngine
    if action == "fin_quote":
        return lambda **kw: module.quote(kw.get("symbol", ""))
    if action == "fin_batch_quotes":
        return lambda **kw: module.batch_quotes(kw.get("symbols", []))
    if action == "fin_historical":
        return lambda **kw: module.historical(kw.get("symbol", ""), kw.get("period", "1y"), kw.get("interval", "1d"))
    if action == "fin_crypto":
        return lambda **kw: module.crypto_quote(kw.get("coin_id", ""))
    if action == "fin_crypto_top":
        return lambda **kw: module.crypto_top(kw.get("limit", 20))
    if action == "fin_forex":
        return lambda **kw: module.forex(kw.get("base", "USD"), kw.get("targets"))
    if action == "fin_market_overview":
        return lambda **kw: module.market_overview()

    # FundamentalsAnalyzer
    if action == "fin_financials":
        return lambda **kw: module.financials(kw.get("symbol", ""), kw.get("statement", "income"), kw.get("period", "annual"))
    if action == "fin_ratios":
        return lambda **kw: module.ratios(kw.get("symbol", ""))
    if action == "fin_earnings":
        return lambda **kw: module.earnings(kw.get("symbol", ""))
    if action == "fin_insiders":
        return lambda **kw: module.insiders(kw.get("symbol", ""))
    if action == "fin_compare":
        return lambda **kw: module.compare(kw.get("symbols", []))

    # Screener
    if action == "fin_screen":
        return lambda **kw: module.screen(kw.get("filters", {}), kw.get("universe", "sp500"), kw.get("limit", 20))
    if action == "fin_preset_screen":
        return lambda **kw: module.preset_screen(kw.get("preset", "value"), kw.get("limit", 20))

    # Portfolio
    if action == "fin_portfolio":
        return lambda **kw: module.analyze(kw.get("positions", []), kw.get("benchmark", "SPY"))

    # Charting
    if action == "fin_chart":
        return lambda **kw: module.candlestick(kw.get("symbol", ""), kw.get("period", "6mo"), kw.get("interval", "1d"), kw.get("indicators"), kw.get("output", ""))
    if action == "fin_comparison_chart":
        return lambda **kw: module.comparison_chart(kw.get("symbols", []), kw.get("period", "1y"), kw.get("output", ""))

    # News
    if action == "fin_news":
        return lambda **kw: module.ticker_news(kw.get("symbol", ""), kw.get("limit", 10))
    if action == "fin_market_news":
        return lambda **kw: module.market_news(kw.get("query", ""), kw.get("limit", 10))
    if action == "fin_sentiment":
        return lambda **kw: module.sentiment(kw.get("symbol", ""))
    if action == "fin_sector_sentiment":
        return lambda **kw: module.sector_sentiment(kw.get("sector", "Technology"))

    # Watchlist
    if action == "fin_create_watchlist":
        return lambda **kw: module.create_watchlist(kw.get("name", ""), kw.get("symbols", []))
    if action == "fin_watchlist":
        return lambda **kw: module.get_watchlist(kw.get("name", ""))
    if action == "fin_add_alert":
        return lambda **kw: module.add_alert(kw.get("watchlist", ""), kw.get("symbol", ""), kw.get("condition", ""), kw.get("threshold", 0))
    if action == "fin_list_watchlists":
        return lambda **kw: module.list_watchlists()

    # Fallback
    return lambda **kw: {"error": f"No dispatch for {action}"}
