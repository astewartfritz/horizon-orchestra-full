"""What-if simulator — scenario modeling for logistics planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.logistics2.optimization.dynamic_pricing import DynamicPricingEngine


@dataclass
class FleetScenario:
    name: str = ""
    num_trucks: int = 50
    avg_distance_km: float = 500.0
    avg_weight_kg: float = 8000.0
    avg_rate_per_km: float = 2.50
    fuel_cost: float = 1.50
    utilization_pct: float = 75.0
    on_time_rate: float = 92.0


class WhatIfSimulator:
    """Scenario simulator — "what happens if we add 50 trucks on 3 lanes"."""

    def __init__(self):
        self.pricing = DynamicPricingEngine()

    def simulate_fleet_expansion(self, base: FleetScenario,
                                  new_trucks: int = 50,
                                  lanes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Simulate adding trucks to specific lanes."""
        lanes = lanes or [
            {"name": "Lane A-B", "distance": 800, "volume": 200},
            {"name": "Lane C-D", "distance": 600, "volume": 150},
            {"name": "Lane E-F", "distance": 400, "volume": 300},
        ]

        # Current state
        current_revenue = base.num_trucks * base.avg_distance_km * base.avg_rate_per_km * (base.utilization_pct / 100)
        current_cost = current_revenue * 0.75  # 75% cost ratio
        current_profit = current_revenue - current_cost

        # Projected state
        additional_shipments = new_trucks * 4  # 4 trips/week per truck
        total_new_revenue = 0
        for lane in lanes:
            shipments_on_lane = int(additional_shipments / len(lanes))
            rate = self.pricing.calculate_rate(
                lane["distance"], base.avg_weight_kg,
                demand_supply_ratio=1.0 + (new_trucks / base.num_trucks) * 0.1,
            )
            lane_revenue = shipments_on_lane * rate["total_rate"]
            total_new_revenue += lane_revenue

        new_revenue = current_revenue + total_new_revenue
        new_cost = current_cost + total_new_revenue * 0.7  # marginal cost 70%
        new_profit = new_revenue - new_cost

        current_margin = (current_profit / current_revenue * 100) if current_revenue else 0
        new_margin = (new_profit / new_revenue * 100) if new_revenue else 0

        return {
            "scenario": f"Add {new_trucks} trucks across {len(lanes)} lanes",
            "current": {
                "revenue": round(current_revenue, 2),
                "cost": round(current_cost, 2),
                "profit": round(current_profit, 2),
                "margin_pct": round(current_margin, 1),
            },
            "projected": {
                "revenue": round(new_revenue, 2),
                "cost": round(new_cost, 2),
                "profit": round(new_profit, 2),
                "margin_pct": round(new_margin, 1),
            },
            "delta": {
                "revenue": round(total_new_revenue, 2),
                "profit": round(new_profit - current_profit, 2),
                "margin_change": round(new_margin - current_margin, 1),
                "additional_shipments": additional_shipments,
                "new_trucks": new_trucks,
            },
            "lanes": [
                {**lane, "estimated_revenue": round(total_new_revenue / len(lanes), 2)}
                for lane in lanes
            ],
            "roi_months": self._estimate_roi(new_trucks, total_new_revenue),
        }

    def _estimate_roi(self, num_trucks: int, monthly_revenue: float,
                      cost_per_truck: float = 150000) -> float:
        total_investment = num_trucks * cost_per_truck
        monthly_profit = monthly_revenue * 0.3  # 30% margin
        return round(total_investment / monthly_profit, 1) if monthly_profit else float("inf")

    def simulate_rate_change(self, current_volume: int, current_rate: float,
                             new_rate: float, elasticity: float = -0.5) -> dict[str, Any]:
        """Price elasticity simulation."""
        pct_change = (new_rate - current_rate) / current_rate
        volume_change = pct_change * elasticity
        new_volume = int(current_volume * (1 + volume_change))
        current_revenue = current_volume * current_rate
        new_revenue = new_volume * new_rate

        return {
            "current": {"volume": current_volume, "rate": current_rate, "revenue": round(current_revenue, 2)},
            "projected": {"volume": new_volume, "rate": new_rate, "revenue": round(new_revenue, 2)},
            "delta": {
                "rate_change_pct": round(pct_change * 100, 1),
                "volume_change_pct": round(volume_change * 100, 1),
                "revenue_change_pct": round((new_revenue - current_revenue) / current_revenue * 100, 1),
            },
            "elasticity": elasticity,
        }
