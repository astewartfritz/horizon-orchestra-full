"""Dynamic pricing engine — rate recommendation, lane pricing, spot market."""

from __future__ import annotations

import math
import random
from typing import Any


class DynamicPricingEngine:
    """Rate recommendation and dynamic pricing for logistics lanes.

    Factors: distance, weight, demand/supply ratio, fuel cost, urgency, season.
    """

    def __init__(self, base_rate_per_km: float = 2.50,
                 fuel_cost_per_l: float = 1.50, vehicle_fuel_efficiency: float = 6.5):
        self.base_rate_per_km = base_rate_per_km
        self.fuel_cost_per_l = fuel_cost_per_l
        self.vehicle_fuel_efficiency = vehicle_fuel_efficiency

    def calculate_rate(self, distance_km: float, weight_kg: float = 0,
                       demand_supply_ratio: float = 1.0,
                       urgency: str = "standard",
                       season_factor: float = 1.0,
                       is_reefer: bool = False,
                       hazmat: bool = False) -> dict[str, Any]:
        """Calculate a recommended shipping rate with full breakdown."""
        fuel_cost = (distance_km / self.vehicle_fuel_efficiency) * self.fuel_cost_per_l

        weight_surcharge = max(0, (weight_kg - 5000) / 1000 * 0.05 * self.base_rate_per_km * distance_km / 100)
        demand_mult = 1.0 + (demand_supply_ratio - 1.0) * 0.5
        demand_mult = max(0.8, min(1.5, demand_mult))

        urgency_mult = {"economy": 0.85, "standard": 1.0, "express": 1.25, "emergency": 1.5}.get(urgency, 1.0)
        reefer_surcharge = distance_km * 0.35 if is_reefer else 0
        hazmat_surcharge = distance_km * 0.50 if hazmat else 0

        base = distance_km * self.base_rate_per_km * season_factor * demand_mult
        total = base + fuel_cost + weight_surcharge + reefer_surcharge + hazmat_surcharge
        total *= urgency_mult
        total = max(total, distance_km * 1.0)

        cost_per_kg = total / weight_kg if weight_kg > 0 else 0
        cost_per_km = total / distance_km if distance_km > 0 else 0

        return {
            "total_rate": round(total, 2),
            "breakdown": {
                "base_freight": round(base, 2),
                "fuel": round(fuel_cost, 2),
                "weight_surcharge": round(weight_surcharge, 2),
                "reefer_surcharge": round(reefer_surcharge, 2),
                "hazmat_surcharge": round(hazmat_surcharge, 2),
                "demand_multiplier": round(demand_mult, 3),
                "urgency_multiplier": urgency_mult,
            },
            "metrics": {
                "cost_per_km": round(cost_per_km, 2),
                "cost_per_kg": round(cost_per_kg, 4),
                "fuel_portion_pct": round(fuel_cost / total * 100, 1) if total else 0,
            },
            "distance_km": round(distance_km, 1),
            "weight_kg": weight_kg,
        }

    def spot_market_rate(self, distance_km: float, weight_kg: float = 0,
                         market_volatility: float = 0.15) -> dict[str, Any]:
        """Spot market rate with market volatility."""
        base = self.calculate_rate(distance_km, weight_kg, demand_supply_ratio=1.1)
        volatility_factor = 1.0 + random.gauss(0, market_volatility)
        spot = base["total_rate"] * volatility_factor
        return {
            "spot_rate": round(spot, 2),
            "vs_market": round((spot / base["total_rate"] - 1) * 100, 1),
            "market_volatility": market_volatility,
            **base,
        }

    def lane_profitability(self, revenue: float, cost: float,
                           distance_km: float) -> dict[str, Any]:
        margin = ((revenue - cost) / revenue * 100) if revenue else 0
        return {
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "profit": round(revenue - cost, 2),
            "margin_pct": round(margin, 1),
            "revenue_per_km": round(revenue / distance_km, 2) if distance_km else 0,
            "cost_per_km": round(cost / distance_km, 2) if distance_km else 0,
            "is_profitable": revenue > cost,
        }
