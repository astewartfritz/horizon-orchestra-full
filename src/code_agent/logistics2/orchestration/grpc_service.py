"""gRPC service definitions for logistics — protobuf-compatible interface."""

from __future__ import annotations

from typing import Any

from code_agent.logistics2.optimization.vrp_solver import VRPSolver, VRPConstraints, VRPStop
from code_agent.logistics2.optimization.demand_forecast import DemandForecaster
from code_agent.logistics2.dispatch.load_matcher import LoadMatcher, Load


class GRPCService:
    """gRPC-compatible service interface for logistics operations.

    Provides a protocol-buffer-style API that can be served over HTTP/2.
    Each method accepts dicts (protobuf message equivalents) and returns dicts.
    """

    def __init__(self):
        self.vrp = VRPSolver()
        self.forecaster = DemandForecaster()
        self.load_matcher = LoadMatcher()

    # ── VRP Service ──────────────────────────

    def solve_vrp(self, request: dict[str, Any]) -> dict[str, Any]:
        stops_data = request.get("stops", [])
        stops = [
            VRPStop(id=s.get("id", f"stop_{i}"),
                    lat=s.get("lat", 0), lng=s.get("lng", 0),
                    weight_kg=s.get("weight_kg", 0))
            for i, s in enumerate(stops_data)
        ]
        num_vehicles = request.get("num_vehicles", 5)
        result = self.vrp.solve(stops, num_vehicles)
        return {
            "routes": result.routes,
            "total_distance_km": result.total_distance,
            "total_duration_hours": result.total_duration,
            "vehicle_utilization": result.vehicle_utilization,
            "unassigned": result.unassigned,
        }

    def optimize_tsp(self, request: dict[str, Any]) -> dict[str, Any]:
        from code_agent.logistics2.optimization.tsp_solver import TSPSolver
        stops_data = request.get("stops", [])
        stops = [VRPStop(lat=s["lat"], lng=s["lng"]) for s in stops_data]
        tsp = TSPSolver()
        route = tsp.solve(stops)
        return {"route": route}

    # ── Forecast Service ─────────────────────

    def forecast_demand(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.forecaster.forecast(
            historical=request.get("historical", []),
            horizon=request.get("horizon", 7),
            method=request.get("method", "ensemble"),
        )

    # ── Load Matching Service ────────────────

    def match_loads(self, request: dict[str, Any]) -> dict[str, Any]:
        loads = [
            Load(id=l.get("id", f"load_{i}"),
                 origin_lat=l.get("origin_lat", 0),
                 origin_lng=l.get("origin_lng", 0),
                 dest_lat=l.get("dest_lat", 0),
                 dest_lng=l.get("dest_lng", 0),
                 weight_kg=l.get("weight_kg", 0),
                 rate=l.get("rate", 0))
            for i, l in enumerate(request.get("loads", []))
        ]
        vehicles = request.get("vehicles", [])
        matches = self.load_matcher.match(loads, vehicles)
        return {
            "matches": [
                {"load_id": m.load_id, "vehicle_id": m.vehicle_id,
                 "score": m.score, "distance_km": m.distance_km,
                 "deadhead_km": m.deadhead_km}
                for m in matches[:request.get("top_k", 10)]
            ],
        }

    # ── Health ───────────────────────────────

    def health(self) -> dict[str, Any]:
        return {"service": "logistics-grpc", "status": "serving"}

    def service_list(self) -> list[dict[str, str]]:
        return [
            {"name": "vrp.SolveVRP", "description": "Solve vehicle routing problem"},
            {"name": "vrp.OptimizeTSP", "description": "Solve traveling salesman problem"},
            {"name": "forecast.Demand", "description": "Forecast demand using ensemble methods"},
            {"name": "matching.MatchLoads", "description": "Match loads to available vehicles"},
        ]
