"""Analytics engine — time-series forecasting, Monte Carlo, scenario analysis with Polars."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any, Callable

from orchestra.code_agent.finance.models import FinancialStatement


class TimeSeriesForecast:
    """Time-series forecasting using statistical methods (no external deps)."""

    def __init__(self, data: list[float], periods: list[str] | None = None):
        self.data = data
        self.periods = periods or [f"P{i+1}" for i in range(len(data))]
        self.n = len(data)

    def moving_average(self, window: int = 3) -> list[float]:
        if self.n < window:
            return self.data
        result = []
        for i in range(self.n):
            if i < window - 1:
                result.append(self.data[i])
            else:
                result.append(sum(self.data[i - window + 1:i + 1]) / window)
        return result

    def exponential_smoothing(self, alpha: float = 0.3, forecast_horizon: int = 3) -> list[float]:
        if not self.data:
            return []
        smoothed = [self.data[0]]
        for i in range(1, self.n):
            smoothed.append(alpha * self.data[i] + (1 - alpha) * smoothed[-1])
        last = smoothed[-1]
        for _ in range(forecast_horizon):
            smoothed.append(alpha * last + (1 - alpha) * smoothed[-1])
            last = smoothed[-1]
        return smoothed

    def linear_regression(self, forecast_horizon: int = 3) -> list[float]:
        if self.n < 2:
            return self.data + [self.data[-1]] * forecast_horizon
        x_mean = (self.n - 1) / 2
        y_mean = sum(self.data) / self.n
        num = sum((i - x_mean) * (self.data[i] - y_mean) for i in range(self.n))
        den = sum((i - x_mean) ** 2 for i in range(self.n))
        slope = num / den if den else 0
        intercept = y_mean - slope * x_mean

        result = list(self.data)
        for i in range(self.n, self.n + forecast_horizon):
            result.append(slope * i + intercept)
        return result

    def seasonal_decompose(self, period: int = 4) -> dict[str, list[float]]:
        if self.n < period * 2:
            return {"trend": self.data, "seasonal": [0] * self.n, "residual": [0] * self.n}
        trend = self.moving_average(period)
        detrended = [self.data[i] - trend[i] for i in range(self.n)]
        seasonal = [0] * self.n
        for i in range(period):
            vals = [detrended[j] for j in range(i, self.n, period)]
            avg = sum(vals) / len(vals)
            for j in range(i, self.n, period):
                seasonal[j] = avg
        # Normalize
        s_mean = sum(seasonal) / self.n
        seasonal = [s - s_mean for s in seasonal]
        residual = [self.data[i] - trend[i] - seasonal[i] for i in range(self.n)]
        return {"trend": trend, "seasonal": seasonal, "residual": residual}


class MonteCarloSimulation:
    """Monte Carlo simulation for financial projections."""

    def __init__(self, base_value: float = 0, volatility: float = 0.1,
                 drift: float = 0.0, seed: int = 42):
        self.base_value = base_value
        self.volatility = volatility
        self.drift = drift
        random.seed(seed)

    def run(self, steps: int = 12, simulations: int = 1000) -> dict[str, Any]:
        results = []
        for _ in range(simulations):
            path = [self.base_value]
            for _ in range(steps):
                ret = random.gauss(self.drift, self.volatility)
                path.append(path[-1] * (1 + ret))
            results.append(path)
        # Aggregate
        percentiles = {p: [] for p in [1, 5, 25, 50, 75, 95, 99]}
        for step in range(steps + 1):
            vals = sorted(r[step] for r in results)
            for p in percentiles:
                idx = int(len(vals) * p / 100)
                percentiles[p].append(vals[idx])
        final_vals = [r[-1] for r in results]
        return {
            "simulations": simulations,
            "steps": steps,
            "final_mean": sum(final_vals) / len(final_vals),
            "final_median": sorted(final_vals)[len(final_vals) // 2],
            "final_min": min(final_vals),
            "final_max": max(final_vals),
            "final_std": math.sqrt(sum((v - sum(final_vals) / len(final_vals)) ** 2 for v in final_vals) / len(final_vals)),
            "percentiles": percentiles,
        }

    def value_at_risk(self, confidence: float = 0.95, horizon: int = 1) -> dict[str, float]:
        """Calculate Value at Risk."""
        sim = self.run(steps=horizon, simulations=10000)
        var_percentile = (1 - confidence) * 100
        sorted_vals = sorted(sim["percentiles"][int(var_percentile)])
        var = sim["final_mean"] - sorted_vals[0] if sorted_vals else 0
        return {
            "var_absolute": round(var, 2),
            "var_percentage": round(var / self.base_value * 100, 2) if self.base_value else 0,
            "confidence": confidence,
            "horizon": horizon,
        }


class ScenarioGenerator:
    """What-if scenario generation for financial modeling."""

    def __init__(self, base_statement: FinancialStatement):
        self.base = base_statement

    def apply_growth(self, revenue_growth: float = 0.1, expense_growth: float = 0.05) -> FinancialStatement:
        s = FinancialStatement(
            period=f"{self.base.period}_growth_{revenue_growth:.0%}",
            revenue=self.base.revenue * (1 + revenue_growth),
            expenses=self.base.expenses * (1 + expense_growth),
            total_assets=self.base.total_assets * (1 + revenue_growth * 0.5),
            total_liabilities=self.base.total_liabilities * (1 + expense_growth * 0.3),
            equity=self.base.equity * (1 + revenue_growth * 0.4),
        )
        s.gross_profit = s.revenue - s.expenses
        s.net_income = s.gross_profit
        return s

    def apply_cost_reduction(self, reduction: float = 0.1) -> FinancialStatement:
        s = FinancialStatement(
            period=f"{self.base.period}_cost_cut_{reduction:.0%}",
            revenue=self.base.revenue,
            expenses=self.base.expenses * (1 - reduction),
            total_assets=self.base.total_assets,
            total_liabilities=self.base.total_liabilities * (1 - reduction * 0.2),
            equity=self.base.equity,
        )
        s.gross_profit = s.revenue - s.expenses
        s.net_income = s.gross_profit
        return s

    def apply_market_downturn(self, impact: float = 0.2) -> FinancialStatement:
        return self.apply_growth(revenue_growth=-impact, expense_growth=-0.05)

    def generate_scenarios(self) -> dict[str, FinancialStatement]:
        return {
            "base": self.base,
            "bullish": self.apply_growth(0.25, 0.10),
            "moderate": self.apply_growth(0.10, 0.05),
            "cost_optimized": self.apply_cost_reduction(0.15),
            "downturn": self.apply_market_downturn(0.25),
            "conservative": self.apply_growth(0.03, 0.02),
        }


class AnalyticsEngine:
    """High-level analytics combining forecasting, Monte Carlo, and scenario generation."""

    def __init__(self):
        self._polars_available = False
        self._init_polars()

    def _init_polars(self) -> None:
        try:
            import polars as pl
            self._polars = pl
            self._polars_available = True
        except ImportError:
            self._polars_available = False

    def forecast_revenue(self, historical: list[float], periods: list[str] | None = None,
                         method: str = "exponential", horizon: int = 3) -> dict[str, Any]:
        ts = TimeSeriesForecast(historical, periods)
        if method == "linear":
            forecast = ts.linear_regression(horizon)
        elif method == "moving_average":
            forecast = ts.moving_average(3) + [sum(historical[-3:]) / 3] * horizon
        else:
            forecast = ts.exponential_smoothing(forecast_horizon=horizon)
        return {
            "historical": historical,
            "forecast": forecast[-horizon:],
            "full_series": forecast,
            "method": method,
            "periods": (periods or []) + [f"F{i+1}" for i in range(horizon)],
        }

    def monte_carlo_projection(self, base_revenue: float, volatility: float = 0.15,
                                steps: int = 12, sims: int = 1000) -> dict[str, Any]:
        mc = MonteCarloSimulation(base_revenue, volatility=volatility)
        return mc.run(steps=steps, simulations=sims)

    def what_if_scenarios(self, statement: FinancialStatement) -> dict[str, Any]:
        gen = ScenarioGenerator(statement)
        scenarios = gen.generate_scenarios()
        return {
            name: {
                "revenue": round(s.revenue, 2),
                "expenses": round(s.expenses, 2),
                "net_income": round(s.net_income, 2),
                "profit_margin": round(s.profit_margin, 2),
            }
            for name, s in scenarios.items()
        }

    def risk_analysis(self, portfolio_value: float, volatility: float = 0.2) -> dict[str, Any]:
        mc = MonteCarloSimulation(portfolio_value, volatility=volatility)
        var_95 = mc.value_at_risk(0.95)
        var_99 = mc.value_at_risk(0.99)
        sim = mc.run(steps=12, simulations=5000)
        return {
            "portfolio_value": portfolio_value,
            "volatility": volatility,
            "var_95": var_95,
            "var_99": var_99,
            "expected_return": round(sim["final_mean"] - portfolio_value, 2),
            "worst_case": round(sim["final_min"] - portfolio_value, 2),
            "best_case": round(sim["final_max"] - portfolio_value, 2),
        }
