"""Load matcher — AI-powered load-to-truck matching engine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Load:
    id: str = ""
    origin_lat: float = 0.0
    origin_lng: float = 0.0
    dest_lat: float = 0.0
    dest_lng: float = 0.0
    weight_kg: float = 0.0
    volume_m3: float = 0.0
    pickup_time: str = ""
    delivery_time: str = ""
    rate: float = 0.0
    equipment_type: str = "dry_van"  # dry_van, reefer, flatbed, hazmat
    priority: int = 1


@dataclass
class MatchScore:
    load_id: str = ""
    vehicle_id: str = ""
    score: float = 0.0
    distance_km: float = 0.0
    deadhead_km: float = 0.0
    compatibility: float = 0.0
    profitability: float = 0.0
    timing_score: float = 0.0


class LoadMatcher:
    """Matches available loads to vehicles based on multi-factor scoring.

    Factors: proximity, equipment compatibility, profitability, timing, driver hours.
    """

    def __init__(self):
        from orchestra.code_agent.logistics.models import haversine as h
        self._haversine = h

    def match(self, loads: list[Load], vehicles: list[dict[str, Any]],
              drivers: list[dict[str, Any]] | None = None) -> list[MatchScore]:
        """Score all load-vehicle pairs and return ranked matches."""
        matches = []
        for load in loads:
            for v in vehicles:
                score = self._score_match(load, v)
                matches.append(score)
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    def best_match(self, load: Load, vehicles: list[dict[str, Any]]) -> MatchScore | None:
        """Find the single best vehicle for a load."""
        scored = self.match([load], vehicles)
        return scored[0] if scored else None

    def _score_match(self, load: Load, vehicle: dict[str, Any]) -> MatchScore:
        vlat = vehicle.get("current_lat", 0)
        vlng = vehicle.get("current_lng", 0)
        v_capacity = vehicle.get("capacity_kg", 10000)

        # Distance to pickup
        dist_to_pickup = self._haversine(vlat, vlng, load.origin_lat, load.origin_lng)
        # Haul distance
        haul_dist = self._haversine(load.origin_lat, load.origin_lng, load.dest_lat, load.dest_lng)
        # Deadhead (empty miles after delivery back to region)
        deadhead = self._haversine(load.dest_lat, load.dest_lng, vlat, vlng)

        # Compatibility (0-1)
        equip_ok = 1.0 if vehicle.get("type", "truck") == load.equipment_type or load.equipment_type == "dry_van" else 0.3
        cap_ok = min(1.0, v_capacity / max(load.weight_kg, 1))
        compat = equip_ok * cap_ok

        # Profitability
        rev_per_km = load.rate / max(haul_dist, 1) if haul_dist > 0 else 0
        cost_per_km = 2.50 + (vehicle.get("fuel_efficiency", 6.5) * 1.50) / 6.5
        profit_factor = max(0, (rev_per_km - cost_per_km) / rev_per_km) if rev_per_km > 0 else 0

        # Distance score (closer = better)
        dist_score = max(0, 1 - dist_to_pickup / 500)
        deadhead_ratio = deadhead / max(haul_dist, 1)
        deadhead_score = max(0, 1 - deadhead_ratio)

        # Final weighted score
        score = (dist_score * 0.25 + compat * 0.30 + profit_factor * 0.25 + deadhead_score * 0.20) * 100

        return MatchScore(
            load_id=load.id,
            vehicle_id=vehicle.get("id", ""),
            score=round(score, 1),
            distance_km=round(dist_to_pickup + haul_dist, 1),
            deadhead_km=round(deadhead, 1),
            compatibility=round(compat, 3),
            profitability=round(profit_factor, 3),
            timing_score=round(dist_score, 3),
        )
