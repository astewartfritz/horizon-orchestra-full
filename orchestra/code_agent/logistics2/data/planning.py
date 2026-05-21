"""Planning engine — lane/capacity planning and resource allocation."""

from __future__ import annotations

from typing import Any


class PlanningEngine:
    """Lane and capacity planning engine."""

    def __init__(self):
        self.lanes: dict[str, dict[str, Any]] = {}
        self.capacity_plans: dict[str, list[dict[str, Any]]] = {}

    def add_lane(self, lane_id: str, origin: str, dest: str,
                 distance_km: float, base_rate: float = 2.50) -> dict[str, Any]:
        lane = {"lane_id": lane_id, "origin": origin, "dest": dest,
                "distance_km": distance_km, "base_rate": base_rate}
        self.lanes[lane_id] = lane
        return lane

    def plan_capacity(self, lane_id: str, date: str, trucks_needed: int,
                      rate_per_truck: float = 2500) -> dict[str, Any]:
        plan = {"lane_id": lane_id, "date": date, "trucks_needed": trucks_needed,
                "rate_per_truck": rate_per_truck, "total_cost": trucks_needed * rate_per_truck}
        self.capacity_plans.setdefault(lane_id, []).append(plan)
        return plan

    def get_plans(self, lane_id: str) -> list[dict[str, Any]]:
        return self.capacity_plans.get(lane_id, [])
