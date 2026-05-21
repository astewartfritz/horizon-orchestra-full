"""Tests for battle-ready Orchestra Logistics v2."""

from __future__ import annotations

import pytest

from orchestra.code_agent.logistics2.data.htap_engine import HTAPEngine
from orchestra.code_agent.logistics2.data.what_if import FleetScenario, WhatIfSimulator
from orchestra.code_agent.logistics2.dispatch.agent_orchestrator import Agent, AgentOrchestrator
from orchestra.code_agent.logistics2.dispatch.load_matcher import Load, LoadMatcher, MatchScore
from orchestra.code_agent.logistics2.dispatch.nlp_agent import NLPAgent
from orchestra.code_agent.logistics2.dispatch.rate_engine import RateEngine
from orchestra.code_agent.logistics2.optimization.demand_forecast import DemandForecaster
from orchestra.code_agent.logistics2.optimization.dynamic_pricing import DynamicPricingEngine
from orchestra.code_agent.logistics2.optimization.vrp_solver import TSPSolver, VRPConstraints, VRPSolver, VRPStop
from orchestra.code_agent.logistics2.orchestration.grpc_service import GRPCService
from orchestra.code_agent.logistics2.orchestration.workflow_engine import WorkflowEngine, WorkflowStep
from orchestra.code_agent.logistics2.telemetry.event_ingester import EventIngester, TelemetryEvent
from orchestra.code_agent.logistics2.telemetry.streaming import EventStream


# ── VRP Solver ───────────────────────────────

class TestVRPSolver:
    def test_solve_returns_routes(self):
        solver = VRPSolver()
        stops = [VRPStop(lat=40.7, lng=-74.0)]
        for i in range(8):
            stops.append(VRPStop(lat=40.7 + i * 0.02, lng=-74.0 + i * 0.02))
        result = solver.solve(stops, num_vehicles=3)
        assert len(result.routes) > 0
        assert result.total_distance > 0

    def test_solve_single_stop(self):
        solver = VRPSolver()
        stops = [VRPStop(lat=40.7, lng=-74.0)]
        result = solver.solve(stops, num_vehicles=1)
        assert len(result.routes) == 0

    def test_constraints_defaults(self):
        c = VRPConstraints()
        assert c.max_stops_per_route == 15
        assert c.max_distance_km == 800.0


class TestTSPSolver:
    def test_solve_returns_route(self):
        solver = TSPSolver()
        stops = [VRPStop(lat=40.7 + i * 0.1, lng=-74.0 + i * 0.1) for i in range(5)]
        route = solver.solve(stops)
        assert len(route) == len(stops) + 1  # returns to depot
        assert route[0] == route[-1]  # starts and ends at depot

    def test_solve_two_stops(self):
        solver = TSPSolver()
        stops = [VRPStop(lat=40.7, lng=-74.0), VRPStop(lat=40.8, lng=-74.1)]
        route = solver.solve(stops)
        # For <3 stops, returns direct list without return-to-depot
        assert len(route) == 2


# ── Demand Forecast ──────────────────────────

class TestDemandForecaster:
    def test_forecast_exponential(self):
        f = DemandForecaster()
        result = f.forecast([100, 110, 120, 130, 140], horizon=3, method="exponential")
        assert len(result["forecast"]) == 3
        assert "trend" in result

    def test_forecast_linear(self):
        f = DemandForecaster()
        result = f.forecast([10, 20, 30, 40, 50], horizon=2, method="linear")
        assert len(result["forecast"]) == 2
        assert result["forecast"][0] > 50

    def test_forecast_ensemble(self):
        f = DemandForecaster()
        result = f.forecast([100, 105, 110, 115, 120], horizon=4, method="ensemble")
        assert len(result["forecast"]) == 4
        assert "components" in result

    def test_forecast_insufficient_data(self):
        f = DemandForecaster()
        result = f.forecast([100], horizon=3)
        assert "error" in result

    def test_forecast_volatility(self):
        f = DemandForecaster()
        result = f.forecast([100, 200, 50, 300, 75], horizon=2)
        assert result["volatility"] > 0


# ── Dynamic Pricing ──────────────────────────

class TestDynamicPricing:
    def test_calculate_rate(self):
        p = DynamicPricingEngine()
        result = p.calculate_rate(500, 8000, demand_supply_ratio=1.0)
        assert result["total_rate"] > 0
        assert "breakdown" in result
        assert "metrics" in result

    def test_spot_market_rate(self):
        p = DynamicPricingEngine()
        result = p.spot_market_rate(500, 8000)
        assert result["spot_rate"] > 0

    def test_lane_profitability(self):
        p = DynamicPricingEngine()
        result = p.lane_profitability(1500, 1200, 500)
        assert result["is_profitable"] is True
        assert result["margin_pct"] == 20.0

    def test_unprofitable_lane(self):
        p = DynamicPricingEngine()
        result = p.lane_profitability(1000, 1500, 500)
        assert result["is_profitable"] is False

    def test_reefer_surcharge(self):
        p = DynamicPricingEngine()
        dry = p.calculate_rate(500, 5000)
        reefer = p.calculate_rate(500, 5000, is_reefer=True)
        assert reefer["total_rate"] > dry["total_rate"]


# ── HTAP Engine ─────────────────────────────

class TestHTAPEngine:
    def test_query(self):
        eng = HTAPEngine()
        result = eng.query("SELECT 1 as test")
        if not isinstance(result, list) or "error" in str(result):
            pytest.skip("DuckDB not available")
        assert result[0]["test"] == 1

    def test_insert_lanes(self):
        eng = HTAPEngine()
        if not eng._available:
            pytest.skip("DuckDB not available")
        count = eng.insert_lanes([{"lane_id": "L1", "origin": "NYC", "dest": "LA",
                                    "distance_km": 4000, "avg_rate": 2.50,
                                    "volume": 100, "carrier_count": 5, "on_time_rate": 92.0}])
        assert count == 1


# ── What-If Simulator ───────────────────────

class TestWhatIfSimulator:
    def test_simulate_fleet_expansion(self):
        sim = WhatIfSimulator()
        base = FleetScenario(num_trucks=50)
        result = sim.simulate_fleet_expansion(base, new_trucks=20)
        assert result["delta"]["new_trucks"] == 20
        assert result["projected"]["revenue"] > result["current"]["revenue"]

    def test_simulate_rate_change(self):
        sim = WhatIfSimulator()
        result = sim.simulate_rate_change(100, 2500, 2800, elasticity=-0.5)
        assert "current" in result and "projected" in result


# ── Load Matcher ────────────────────────────

class TestLoadMatcher:
    def test_match_returns_scores(self):
        matcher = LoadMatcher()
        loads = [Load(id="L1", origin_lat=40.7, origin_lng=-74.0,
                       dest_lat=41.9, dest_lng=-87.6, weight_kg=5000, rate=1500)]
        vehicles = [{"id": "V1", "current_lat": 40.7, "current_lng": -74.0,
                      "capacity_kg": 10000, "type": "dry_van"}]
        matches = matcher.match(loads, vehicles)
        assert len(matches) == 1
        assert matches[0].score > 0

    def test_best_match(self):
        matcher = LoadMatcher()
        load = Load(id="L1", origin_lat=40.7, origin_lng=-74.0,
                     dest_lat=41.9, dest_lng=-87.6, weight_kg=5000, rate=1500)
        vehicles = [{"id": "V1", "current_lat": 40.7, "current_lng": -74.0,
                      "capacity_kg": 10000, "type": "dry_van"}]
        best = matcher.best_match(load, vehicles)
        assert best is not None
        assert best.vehicle_id == "V1"

    def test_match_equipment_mismatch(self):
        matcher = LoadMatcher()
        load = Load(id="L1", origin_lat=40.7, origin_lng=-74.0,
                     dest_lat=41.9, dest_lng=-87.6, equipment_type="reefer")
        vehicles = [{"id": "V1", "current_lat": 40.7, "current_lng": -74.0,
                      "capacity_kg": 10000, "type": "dry_van"}]
        matches = matcher.match([load], vehicles)
        assert matches[0].compatibility < 0.5


# ── Rate Engine ─────────────────────────────

class TestRateEngine:
    def test_recommend_rate(self):
        eng = RateEngine()
        result = eng.recommend_rate(500, 8000)
        assert result["market_rate"] > 0
        assert result["recommended_rate"] > result["market_rate"]

    def test_benchmark_lane(self):
        eng = RateEngine()
        result = eng.benchmark_lane("NYC", "Chicago", 800, volume=200)
        assert result["annual_lane_value"] > 0


# ── Agent Orchestrator ──────────────────────

class TestAgentOrchestrator:
    @pytest.mark.asyncio
    async def test_run_all(self):
        orch = AgentOrchestrator()
        result = await orch.run_all({"loads": [], "vehicles": [], "drivers": []})
        assert "dispatcher" in result
        assert "compliance" in result

    @pytest.mark.asyncio
    async def test_run_specific_agent(self):
        orch = AgentOrchestrator()
        result = await orch.run_agent("compliance", {"drivers": [
            {"name": "Bob", "hours_this_week": 65, "max_hours_per_week": 60, "status": "driving"}
        ]})
        assert "violations" in result

    @pytest.mark.asyncio
    async def test_unknown_agent(self):
        orch = AgentOrchestrator()
        result = await orch.run_agent("nonexistent", {})
        assert "error" in result


# ── NLP Agent ───────────────────────────────

class TestNLPAgent:
    def test_parse_find_truck(self):
        agent = NLPAgent()
        result = agent.parse_intent("Find available trucks near Chicago")
        assert result["intent"] == "find_vehicle"
        assert "Chicago" in str(result["entities"])

    def test_parse_rate_query(self):
        agent = NLPAgent()
        result = agent.parse_intent("What's the rate for a 500-mile load?")
        assert result["intent"] == "rate_query"
        assert result["entities"].get("distance") == 500

    def test_parse_unknown(self):
        agent = NLPAgent()
        result = agent.parse_intent("Hello world")
        assert result["intent"] == "unknown"

    @pytest.mark.asyncio
    async def test_handle_find_vehicle(self):
        agent = NLPAgent()
        result = await agent.handle("Find trucks near NYC")
        assert result["intent"] == "find_vehicle"


# ── Event Ingester ──────────────────────────

class TestEventIngester:
    @pytest.mark.asyncio
    async def test_ingest(self):
        stream = EventStream()
        ingester = EventIngester(stream)
        received = []

        async def handler(event):
            received.append(event)

        ingester.on("location_update", handler)
        event = TelemetryEvent(source="gps", vehicle_id="V1")
        await ingester.ingest(event)
        assert len(received) == 1
        assert received[0].vehicle_id == "V1"

    @pytest.mark.asyncio
    async def test_ingest_batch(self):
        ingester = EventIngester()
        events = [TelemetryEvent(vehicle_id=f"V{i}") for i in range(5)]
        count = await ingester.ingest_batch(events)
        assert count == 5


# ── Event Stream ────────────────────────────

class TestEventStream:
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        stream = EventStream()
        received = []

        async def h(msg):
            received.append(msg)

        stream.subscribe("gps", h)
        await stream.publish("gps", {"lat": 40.7})
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_wildcard(self):
        stream = EventStream()
        received = []
        stream.subscribe_all(lambda m: received.append(m))
        await stream.publish("test", {})
        assert len(received) == 1

    def test_replay(self):
        stream = EventStream()
        stream._history = [{"topic": "gps", "data": {}}]
        events = stream.replay("gps")
        assert len(events) == 1

    def test_stats(self):
        stream = EventStream()
        stream._history = [{"topic": "gps", "data": {}}]
        stats = stream.stats()
        assert stats["total_events"] == 1


# ── Workflow Engine ─────────────────────────

class TestWorkflowEngine:
    @pytest.mark.asyncio
    async def test_define_and_run(self):
        engine = WorkflowEngine()
        steps = [WorkflowStep("step1", lambda ctx: {"result": 42})]
        wf = engine.define("test", steps)
        result = await engine.run(wf.id)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_workflow_failure(self):
        engine = WorkflowEngine()

        def fail(ctx):
            raise ValueError("boom")

        steps = [WorkflowStep("failing", fail, max_retries=1)]
        wf = engine.define("fail_test", steps)
        result = await engine.run(wf.id)
        assert result["status"] == "failed"

    def test_get_status(self):
        engine = WorkflowEngine()
        wf = engine.define("test", [WorkflowStep("s1", lambda c: None)])
        status = engine.get_status(wf.id)
        assert status is not None
        assert status["name"] == "test"

    def test_list_workflows(self):
        engine = WorkflowEngine()
        engine.define("w1", [])
        engine.define("w2", [])
        assert len(engine.list_workflows()) == 2


# ── gRPC Service ────────────────────────────

class TestGRPCService:
    def test_health(self):
        svc = GRPCService()
        assert svc.health()["status"] == "serving"

    def test_service_list(self):
        svc = GRPCService()
        services = svc.service_list()
        assert len(services) >= 4


# ── TelemetryEvent ──────────────────────────

class TestTelemetryEvent:
    def test_auto_id(self):
        e = TelemetryEvent(vehicle_id="V1")
        assert len(e.id) == 12
        assert e.timestamp > 0
