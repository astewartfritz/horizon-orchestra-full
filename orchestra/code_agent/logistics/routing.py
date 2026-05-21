"""Routing engine — route optimization, distance matrix, ETA, carbon tracking."""

from __future__ import annotations

from typing import Any

from orchestra.code_agent.logistics.models import Route, RouteStop, haversine


class DistanceMatrix:
    """In-memory distance matrix for route optimization."""

    def __init__(self):
        self._distances: dict[tuple[str, str], float] = {}
        self._durations: dict[tuple[str, str], float] = {}

    def add_entry(self, origin_id: str, dest_id: str,
                  distance_km: float, duration_hours: float) -> None:
        self._distances[(origin_id, dest_id)] = distance_km
        self._durations[(origin_id, dest_id)] = duration_hours

    def get_distance(self, origin_id: str, dest_id: str) -> float:
        return self._distances.get((origin_id, dest_id), 0.0)

    def get_duration(self, origin_id: str, dest_id: str) -> float:
        return self._durations.get((origin_id, dest_id), 0.0)

    def estimate_distance(self, lat1: float, lng1: float,
                          lat2: float, lng2: float) -> float:
        return haversine(lat1, lng1, lat2, lng2)

    def estimate_duration(self, distance_km: float, avg_speed: float = 60.0) -> float:
        return distance_km / avg_speed if avg_speed else 0


class RoutingEngine:
    """Route planning, optimization, and ETA calculation."""

    def __init__(self, distance_matrix: DistanceMatrix | None = None):
        self.routes: dict[str, Route] = {}
        self.distance_matrix = distance_matrix or DistanceMatrix()

    def create_route(self, name: str, vehicle_id: str, driver_id: str = "",
                     stops: list[RouteStop] | None = None) -> Route:
        route = Route(
            name=name,
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            stops=stops or [],
        )
        self._calculate_route_metrics(route)
        self.routes[route.id] = route
        return route

    def add_stop(self, route_id: str, stop: RouteStop) -> bool:
        route = self.routes.get(route_id)
        if not route:
            return False
        stop.sequence = len(route.stops)
        route.stops.append(stop)
        self._calculate_route_metrics(route)
        return True

    def optimize_stops(self, route_id: str) -> bool:
        """Nearest-neighbor optimization of route stops."""
        route = self.routes.get(route_id)
        if not route or len(route.stops) < 3:
            return False
        unvisited = list(route.stops[1:])
        optimized = [route.stops[0]] if route.stops else []
        while unvisited:
            current = optimized[-1]
            nearest = min(unvisited, key=lambda s: self._dist(current, s))
            optimized.append(nearest)
            unvisited.remove(nearest)
        route.stops = optimized
        for i, s in enumerate(route.stops):
            s.sequence = i
        self._calculate_route_metrics(route)
        return True

    def _dist(self, a: RouteStop, b: RouteStop) -> float:
        return self.distance_matrix.estimate_distance(a.lat, a.lng, b.lat, b.lng)

    def _calculate_route_metrics(self, route: Route) -> None:
        total_dist = 0.0
        for i in range(len(route.stops) - 1):
            a, b = route.stops[i], route.stops[i + 1]
            total_dist += self.distance_matrix.estimate_distance(a.lat, a.lng, b.lat, b.lng)
        route.total_distance_km = round(total_dist, 1)
        route.estimated_duration_hours = round(
            self.distance_matrix.estimate_duration(total_dist), 1
        )
        route.carbon_footprint_kg = round(total_dist * 0.27, 2)

    def get_route(self, route_id: str) -> Route | None:
        return self.routes.get(route_id)

    def get_active_routes(self) -> list[Route]:
        return [r for r in self.routes.values() if r.status == "active"]

    def update_status(self, route_id: str, status: str) -> bool:
        route = self.routes.get(route_id)
        if not route:
            return False
        route.status = status
        return True

    def estimate_eta(self, route_id: str, current_stop_index: int = 0) -> dict[str, Any]:
        route = self.routes.get(route_id)
        if not route:
            return {}
        remaining = route.stops[current_stop_index:]
        if not remaining:
            return {"eta": "delivered", "remaining_km": 0, "remaining_hours": 0}
        dist = sum(
            self.distance_matrix.estimate_distance(
                remaining[i].lat, remaining[i].lng,
                remaining[i + 1].lat, remaining[i + 1].lng,
            )
            for i in range(len(remaining) - 1)
        )
        hours = self.distance_matrix.estimate_duration(dist)
        return {
            "remaining_stops": len(remaining),
            "remaining_km": round(dist, 1),
            "remaining_hours": round(hours, 1),
            "estimated_completion": f"{hours:.1f}h from now",
        }
