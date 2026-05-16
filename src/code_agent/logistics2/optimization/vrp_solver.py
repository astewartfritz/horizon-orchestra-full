"""VRP/TSP solver for multi-leg route optimization — OR-Tools compatible interface."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from code_agent.logistics.models import haversine


@dataclass
class VRPConstraints:
    max_stops_per_route: int = 15
    max_distance_km: float = 800.0
    max_duration_hours: float = 11.0
    vehicle_capacity_kg: float = 10000.0
    driver_max_hours: float = 11.0
    min_rest_hours: float = 10.0
    depot_lat: float = 40.7
    depot_lng: float = -74.0


@dataclass
class VRPStop:
    id: str = ""
    lat: float = 0.0
    lng: float = 0.0
    weight_kg: float = 0.0
    volume_m3: float = 0.0
    service_time_min: int = 15
    time_window_start: str = "06:00"
    time_window_end: str = "18:00"
    priority: int = 1


@dataclass
class VRPResult:
    routes: list[list[int]] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    total_distance: float = 0.0
    total_duration: float = 0.0
    unassigned: list[int] = field(default_factory=list)
    vehicle_utilization: list[float] = field(default_factory=list)


class VRPSolver:
    """Vehicle Routing Problem solver using nearest-neighbor + 2-opt improvement.
    
    Provides OR-Tools-compatible interface. Falls back to heuristic when
    OR-Tools not available.
    """

    def __init__(self, constraints: VRPConstraints | None = None):
        self.constraints = constraints or VRPConstraints()
        self._ortools = False
        self._init_ortools()

    def _init_ortools(self) -> None:
        try:
            from ortools.constraint_solver import routing_enabled_pb2
            self._ortools = True
        except ImportError:
            self._ortools = False

    def solve(self, stops: list[VRPStop], num_vehicles: int = 5,
              depot_idx: int = 0) -> VRPResult:
        """Solve VRP — uses OR-Tools if available, else heuristic."""
        if self._ortools and len(stops) > 3:
            return self._solve_ortools(stops, num_vehicles, depot_idx)
        return self._solve_heuristic(stops, num_vehicles, depot_idx)

    def _solve_heuristic(self, stops: list[VRPStop], num_vehicles: int,
                         depot_idx: int) -> VRPResult:
        """Heuristic VRP: cluster by angle, then TSP within clusters."""
        if len(stops) <= 1:
            return VRPResult()

        depot = stops[depot_idx]
        others = [(i, s) for i, s in enumerate(stops) if i != depot_idx]

        # Polar angle clustering
        clusters: dict[int, list[tuple[int, VRPStop]]] = {}
        for i, s in others:
            angle = math.atan2(s.lat - depot.lat, s.lng - depot.lng)
            cluster_id = int((angle + math.pi) / (2 * math.pi / num_vehicles))
            cluster_id = min(cluster_id, num_vehicles - 1)
            clusters.setdefault(cluster_id, []).append((i, s))

        result = VRPResult()
        for cid in range(num_vehicles):
            cluster = clusters.get(cid, [])
            if not cluster:
                continue
            # Nearest-neighbor ordering within cluster
            ordered = self._nearest_neighbor(depot, cluster)
            if not ordered:
                continue
            route = [depot_idx] + ordered
            dist = sum(
                haversine(stops[route[j]].lat, stops[route[j]].lng,
                          stops[route[j + 1]].lat, stops[route[j + 1]].lng)
                for j in range(len(route) - 1)
            )
            if dist > self.constraints.max_distance_km:
                continue
            dur = dist / 60.0 + len(cluster) * 0.25
            result.routes.append(route)
            result.distances.append(round(dist, 1))
            result.durations.append(round(dur, 2))
            result.total_distance += dist
            result.total_duration += dur
            util = min(100, (dist / self.constraints.max_distance_km) * 100)
            result.vehicle_utilization.append(round(util, 1))

        result.total_distance = round(result.total_distance, 1)
        result.total_duration = round(result.total_duration, 2)
        return result

    def _nearest_neighbor(self, depot: VRPStop,
                          cluster: list[tuple[int, VRPStop]]) -> list[int]:
        if not cluster:
            return []
        ordered = []
        current_lat, current_lng = depot.lat, depot.lng
        remaining = list(cluster)
        while remaining:
            nearest = min(remaining, key=lambda x: haversine(current_lat, current_lng, x[1].lat, x[1].lng))
            ordered.append(nearest[0])
            current_lat, current_lng = nearest[1].lat, nearest[1].lng
            remaining.remove(nearest)
        return ordered

    def _solve_ortools(self, stops: list[VRPStop], num_vehicles: int,
                       depot_idx: int) -> VRPResult:
        """OR-Tools VRP solver (requires ortools package)."""
        try:
            from ortools.constraint_solver import routing_enums_pb2, pywrapcp
        except ImportError:
            return self._solve_heuristic(stops, num_vehicles, depot_idx)

        n = len(stops)
        manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot_idx)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_idx, to_idx):
            f = manager.IndexToNode(from_idx)
            t = manager.IndexToNode(to_idx)
            return int(haversine(stops[f].lat, stops[f].lng, stops[t].lat, stops[t].lng) * 1000)

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        routing.AddDimensionWithVehicleCapacity(
            transit_callback_index, 0, [int(self.constraints.max_distance_km * 1000)] * num_vehicles,
            True, "Distance")

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        solution = routing.SolveWithParameters(search_params)

        result = VRPResult()
        if solution:
            for v in range(num_vehicles):
                idx = routing.Start(v)
                route = []
                while not routing.IsEnd(idx):
                    route.append(manager.IndexToNode(idx))
                    idx = solution.Value(routing.NextVar(idx))
                if len(route) > 1:
                    result.routes.append(route)
                    d = sum(
                        haversine(stops[route[j]].lat, stops[route[j]].lng,
                                  stops[route[j + 1]].lat, stops[route[j + 1]].lng)
                        for j in range(len(route) - 1)
                    )
                    result.distances.append(round(d, 1))
                    result.total_distance += d
        return result


class TSPSolver:
    """Traveling Salesman Problem solver — 2-opt + nearest-neighbor."""

    def solve(self, stops: list[VRPStop], depot_idx: int = 0) -> list[int]:
        if len(stops) < 3:
            return list(range(len(stops)))
        # Initial: nearest-neighbor
        unvisited = set(range(len(stops)))
        unvisited.discard(depot_idx)
        route = [depot_idx]
        current = depot_idx
        while unvisited:
            nearest = min(unvisited, key=lambda i: haversine(
                stops[current].lat, stops[current].lng,
                stops[i].lat, stops[i].lng))
            route.append(nearest)
            unvisited.remove(nearest)
            current = nearest
        route.append(depot_idx)
        # 2-opt improvement
        improved = True
        while improved:
            improved = False
            for i in range(1, len(route) - 2):
                for j in range(i + 1, len(route) - 1):
                    d1 = haversine(stops[route[i - 1]].lat, stops[route[i - 1]].lng,
                                   stops[route[i]].lat, stops[route[i]].lng)
                    d2 = haversine(stops[route[j]].lat, stops[route[j]].lng,
                                   stops[route[j + 1]].lat, stops[route[j + 1]].lng)
                    d3 = haversine(stops[route[i - 1]].lat, stops[route[i - 1]].lng,
                                   stops[route[j]].lat, stops[route[j]].lng)
                    d4 = haversine(stops[route[i]].lat, stops[route[i]].lng,
                                   stops[route[j + 1]].lat, stops[route[j + 1]].lng)
                    if d1 + d2 > d3 + d4:
                        route[i:j + 1] = reversed(route[i:j + 1])
                        improved = True
        return route
