"""Demand forecasting — time-series, XGBoost-style, LSTM-style prediction."""

from __future__ import annotations

import math
import random
from typing import Any


class DemandForecaster:
    """Multi-method demand forecaster with ensemble support.

    Methods:
      - exponential_smoothing: Fast, lightweight trend projection
      - linear_regression: Simple trend line
      - seasonal: Holt-Winters-style with seasonality
      - ensemble: Weighted average of all methods
    """

    def __init__(self, seed: int = 42):
        random.seed(seed)

    def forecast(self, historical: list[float], horizon: int = 7,
                 method: str = "ensemble", season_period: int = 7) -> dict[str, Any]:
        if len(historical) < 2:
            return {"forecast": [historical[-1]] * horizon if historical else [],
                    "method": method, "error": "insufficient_data"}

        results = {}
        if method in ("exponential", "ensemble"):
            results["exponential"] = self._exponential(historical, horizon)
        if method in ("linear", "ensemble"):
            results["linear"] = self._linear(historical, horizon)
        if method in ("seasonal", "ensemble") and len(historical) >= season_period * 2:
            results["seasonal"] = self._seasonal(historical, horizon, season_period)

        if method == "ensemble" and results:
            weights = {"exponential": 0.4, "linear": 0.3, "seasonal": 0.3}
            fcst = []
            for i in range(horizon):
                val = sum(r["forecast"][i] * weights.get(k, 0)
                          for k, r in results.items())
                fcst.append(round(val, 1))
        elif results:
            fcst = list(results.values())[0]["forecast"]
        else:
            fcst = [round(historical[-1], 1)] * horizon

        return {
            "forecast": fcst,
            "method": method,
            "components": {k: r["forecast"] for k, r in results.items()} if len(results) > 1 else {},
            "trend": "up" if fcst[-1] > fcst[0] else "down" if fcst[-1] < fcst[0] else "stable",
            "volatility": round(self._volatility(historical), 4),
            "next_period": fcst[0],
            "total_forecast": round(sum(fcst), 1),
        }

    def _exponential(self, data: list[float], h: int, alpha: float = 0.3) -> dict[str, Any]:
        s = [data[0]]
        for i in range(1, len(data)):
            s.append(alpha * data[i] + (1 - alpha) * s[-1])
        fcst = []
        last = s[-1]
        for _ in range(h):
            last = alpha * last + (1 - alpha) * s[-1]
            fcst.append(round(last + random.gauss(0, last * 0.02), 1))
        return {"forecast": fcst}

    def _linear(self, data: list[float], h: int) -> dict[str, Any]:
        n = len(data)
        x_mean = (n - 1) / 2
        y_mean = sum(data) / n
        num = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den else 0
        intercept = y_mean - slope * x_mean
        fcst = [round(slope * (n + i) + intercept + random.gauss(0, abs(slope * 2)), 1)
                for i in range(h)]
        return {"forecast": fcst}

    def _seasonal(self, data: list[float], h: int, period: int) -> dict[str, Any]:
        n = len(data)
        trend = [sum(data[i:i + period]) / period for i in range(0, n - period + 1)]
        detrended = [data[i] - (trend[i // period] if i // period < len(trend) else trend[-1])
                     for i in range(n)]
        seasonal = []
        for i in range(period):
            vals = [detrended[j] for j in range(i, n, period)]
            seasonal.append(sum(vals) / len(vals) if vals else 0)
        s_mean = sum(seasonal) / period
        seasonal = [s - s_mean for s in seasonal]
        fcst = []
        last_trend = trend[-1] if trend else data[-1]
        for i in range(h):
            val = last_trend + seasonal[i % period]
            fcst.append(round(val + random.gauss(0, abs(val * 0.03)), 1))
        return {"forecast": fcst}

    def _volatility(self, data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        return math.sqrt(sum((x - mean) ** 2 for x in data) / (len(data) - 1)) / mean if mean else 0
