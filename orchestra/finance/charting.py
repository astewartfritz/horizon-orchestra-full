"""Charting Engine — candlestick, technical indicators, overlays, multi-timeframe.

Generates publication-quality financial charts with technical analysis overlays.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..skills.base import run_code_in_sandbox

__all__ = ["ChartingEngine"]
log = logging.getLogger("orchestra.finance.charting")


class ChartingEngine:
    """Financial charting with technical analysis."""

    async def candlestick(
        self, symbol: str, period: str = "6mo", interval: str = "1d",
        indicators: list[str] | None = None, output: str = "",
    ) -> dict[str, Any]:
        """Generate a candlestick chart with optional technical indicators.

        Indicators: sma_20, sma_50, sma_200, ema_12, ema_26, bollinger, macd, rsi, volume.
        """
        indicators = indicators or ["sma_20", "sma_50", "volume"]
        ind_json = json.dumps(indicators)
        out = output or f"/tmp/horizon_workspace/{symbol}_chart.png"
        code = f"""
import json
try:
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    import numpy as np
    import pandas as pd

    t = yf.Ticker("{symbol}")
    df = t.history(period="{period}", interval="{interval}")
    if df.empty:
        print(json.dumps({{"error": "No data"}}))
    else:
        indicators = json.loads('{ind_json}')

        # How many subplots
        n_sub = 1
        if "macd" in indicators: n_sub += 1
        if "rsi" in indicators: n_sub += 1
        if "volume" in indicators and n_sub == 1: n_sub += 1

        fig, axes = plt.subplots(n_sub, 1, figsize=(14, 4 * n_sub), gridspec_kw={{"height_ratios": [3] + [1] * (n_sub - 1)}}, sharex=True)
        if n_sub == 1: axes = [axes]
        ax = axes[0]

        # Candlestick (simplified with colored bars)
        colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["Open"], df["Close"])]
        ax.bar(range(len(df)), df["Close"] - df["Open"], bottom=df["Open"], color=colors, width=0.8)
        ax.vlines(range(len(df)), df["Low"], df["High"], colors=colors, linewidth=0.5)

        # Moving averages
        if "sma_20" in indicators:
            ax.plot(df["Close"].rolling(20).mean(), color="#ff9800", linewidth=1, label="SMA 20", alpha=0.8)
        if "sma_50" in indicators:
            ax.plot(df["Close"].rolling(50).mean(), color="#2196f3", linewidth=1, label="SMA 50", alpha=0.8)
        if "sma_200" in indicators:
            ax.plot(df["Close"].rolling(200).mean(), color="#9c27b0", linewidth=1, label="SMA 200", alpha=0.8)
        if "ema_12" in indicators:
            ax.plot(df["Close"].ewm(span=12).mean(), color="#4caf50", linewidth=1, label="EMA 12", alpha=0.8)
        if "ema_26" in indicators:
            ax.plot(df["Close"].ewm(span=26).mean(), color="#f44336", linewidth=1, label="EMA 26", alpha=0.8)

        # Bollinger Bands
        if "bollinger" in indicators:
            sma = df["Close"].rolling(20).mean()
            std = df["Close"].rolling(20).std()
            ax.fill_between(range(len(df)), sma - 2 * std, sma + 2 * std, alpha=0.1, color="#2196f3")
            ax.plot(sma, color="#2196f3", linewidth=0.5, linestyle="--")

        ax.set_title(f"{symbol} — {"{period}"} ({"{interval}"})", fontsize=14, fontweight="bold")
        ax.legend(loc="upper left", fontsize=8)
        ax.set_ylabel("Price ($)")
        ax.grid(True, alpha=0.3)

        sub_idx = 1

        # Volume
        if "volume" in indicators and sub_idx < n_sub:
            vol_ax = axes[sub_idx]
            vol_ax.bar(range(len(df)), df["Volume"], color=colors, alpha=0.5, width=0.8)
            vol_ax.set_ylabel("Volume")
            vol_ax.grid(True, alpha=0.3)
            sub_idx += 1

        # MACD
        if "macd" in indicators and sub_idx < n_sub:
            macd_ax = axes[sub_idx]
            ema12 = df["Close"].ewm(span=12).mean()
            ema26 = df["Close"].ewm(span=26).mean()
            macd_line = ema12 - ema26
            signal = macd_line.ewm(span=9).mean()
            hist = macd_line - signal
            macd_ax.plot(macd_line.values, color="#2196f3", linewidth=1, label="MACD")
            macd_ax.plot(signal.values, color="#ff9800", linewidth=1, label="Signal")
            macd_ax.bar(range(len(hist)), hist.values, color=["#26a69a" if v >= 0 else "#ef5350" for v in hist.values], alpha=0.5, width=0.8)
            macd_ax.legend(fontsize=8)
            macd_ax.set_ylabel("MACD")
            macd_ax.grid(True, alpha=0.3)
            sub_idx += 1

        # RSI
        if "rsi" in indicators and sub_idx < n_sub:
            rsi_ax = axes[sub_idx]
            delta = df["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_ax.plot(rsi.values, color="#9c27b0", linewidth=1)
            rsi_ax.axhline(70, color="#ef5350", linestyle="--", linewidth=0.5)
            rsi_ax.axhline(30, color="#26a69a", linestyle="--", linewidth=0.5)
            rsi_ax.fill_between(range(len(rsi)), 30, 70, alpha=0.05, color="gray")
            rsi_ax.set_ylabel("RSI")
            rsi_ax.set_ylim(0, 100)
            rsi_ax.grid(True, alpha=0.3)

        # X-axis dates
        tick_positions = list(range(0, len(df), max(len(df) // 8, 1)))
        tick_labels = [str(df.index[i].date()) for i in tick_positions if i < len(df)]
        axes[-1].set_xticks(tick_positions[:len(tick_labels)])
        axes[-1].set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=8)

        plt.tight_layout()
        plt.savefig("{out}", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close()

        print(json.dumps({{
            "chart": "{symbol}", "period": "{period}", "interval": "{interval}",
            "indicators": indicators, "path": "{out}",
            "data_points": len(df),
            "price_range": [round(float(df["Low"].min()), 2), round(float(df["High"].max()), 2)],
        }}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=45)
        return result.get("data", {})

    async def comparison_chart(
        self, symbols: list[str], period: str = "1y", output: str = "",
    ) -> dict[str, Any]:
        """Normalized price comparison chart (rebased to 100)."""
        sym_str = json.dumps(symbols)
        out = output or "/tmp/horizon_workspace/comparison_chart.png"
        code = f"""
import json
try:
    import yfinance as yf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    symbols = json.loads('{sym_str}')
    df = yf.download(symbols, period="{period}", interval="1d", progress=False)["Close"]
    normalized = df / df.iloc[0] * 100

    fig, ax = plt.subplots(figsize=(14, 7))
    for sym in symbols:
        col = sym if sym in normalized.columns else normalized.columns[0]
        ax.plot(normalized.index, normalized[col], linewidth=1.5, label=sym)

    ax.set_title("Price Comparison (Rebased to 100)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Indexed Price")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig("{out}", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()

    returns = {{sym: round(float((normalized[sym].iloc[-1] / 100 - 1) * 100), 2) for sym in symbols if sym in normalized.columns}}
    print(json.dumps({{"chart": "comparison", "symbols": symbols, "path": "{out}", "returns": returns}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        result = await run_code_in_sandbox(code, timeout=45)
        return result.get("data", {})

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_chart", "description": "Generate a candlestick chart with technical indicators (SMA, EMA, Bollinger, MACD, RSI, Volume).", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "period": {"type": "string"}, "interval": {"type": "string"}, "indicators": {"type": "array", "items": {"type": "string"}, "description": "sma_20, sma_50, sma_200, ema_12, ema_26, bollinger, macd, rsi, volume"}, "output": {"type": "string"}}, "required": ["symbol"]}}},
            {"type": "function", "function": {"name": "fin_comparison_chart", "description": "Normalized price comparison chart for multiple stocks.", "parameters": {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "period": {"type": "string"}, "output": {"type": "string"}}, "required": ["symbols"]}}},
        ]
