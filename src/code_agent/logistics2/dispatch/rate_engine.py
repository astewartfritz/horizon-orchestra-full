"""Rate engine — rate recommendation and carrier rate comparison."""

from __future__ import annotations

from typing import Any

from code_agent.logistics2.optimization.dynamic_pricing import DynamicPricingEngine


class RateEngine:
    """Rate recommendation engine with carrier comparison."""

    def __init__(self):
        self.pricing = DynamicPricingEngine()
        self._carrier_rates: dict[str, float] = {}

    def register_carrier_rate(self, carrier: str, rate_per_km: float) -> None:
        self._carrier_rates[carrier] = rate_per_km

    def recommend_rate(self, distance_km: float, weight_kg: float = 0,
                       demand_supply: float = 1.0, urgency: str = "standard",
                       is_reefer: bool = False, hazmat: bool = False) -> dict[str, Any]:
        """Recommend optimal rate with market comparison."""
        market = self.pricing.calculate_rate(
            distance_km, weight_kg, demand_supply, urgency, is_reefer=is_reefer, hazmat=hazmat)

        carrier_comparison = []
        for carrier, rate_km in self._carrier_rates.items():
            carrier_rate = rate_km * distance_km
            diff = carrier_rate - market["total_rate"]
            carrier_comparison.append({
                "carrier": carrier,
                "rate": round(carrier_rate, 2),
                "vs_market": round(diff, 2),
                "vs_market_pct": round(diff / market["total_rate"] * 100, 1),
                "cheaper": carrier_rate < market["total_rate"],
            })
        carrier_comparison.sort(key=lambda x: x["rate"])

        return {
            "market_rate": market["total_rate"],
            "recommended_rate": round(market["total_rate"] * 1.05, 2),
            "rate_breakdown": market["breakdown"],
            "cost_per_km": market["metrics"]["cost_per_km"],
            "carrier_comparison": carrier_comparison,
            "cheapest_carrier": carrier_comparison[0]["carrier"] if carrier_comparison else None,
            "savings_vs_market": round(market["total_rate"] - (carrier_comparison[0]["rate"] if carrier_comparison else market["total_rate"]), 2),
        }

    def benchmark_lane(self, origin: str, dest: str, distance_km: float,
                       volume: int = 100) -> dict[str, Any]:
        """Benchmark a lane's rate against market."""
        rate = self.pricing.calculate_rate(distance_km, demand_supply_ratio=1.0)
        annual_value = rate["total_rate"] * volume * 12
        return {
            "lane": f"{origin} → {dest}",
            "distance_km": round(distance_km, 1),
            "rate_per_shipment": rate["total_rate"],
            "monthly_volume": volume,
            "annual_lane_value": round(annual_value, 2),
            "cost_per_km": rate["metrics"]["cost_per_km"],
            "fuel_portion": rate["metrics"]["fuel_portion_pct"],
        }
