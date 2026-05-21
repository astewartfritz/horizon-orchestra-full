"""AI Logistics Brain — route optimization, demand forecasting, anomaly detection."""

from __future__ import annotations

import math
import random
from typing import Any

from orchestra.code_agent.logistics.fleet import FleetEngine
from orchestra.code_agent.logistics.models import FleetMetrics, Shipment, ShipmentStatus, Vehicle, VehicleStatus
from orchestra.code_agent.logistics.routing import RoutingEngine
from orchestra.code_agent.logistics.supply_chain import SupplyChainEngine


class LogisticsBrain:
    """AI-native logistics intelligence — optimization, forecasting, anomaly detection."""

    def __init__(self, fleet: FleetEngine | None = None,
                 routing: RoutingEngine | None = None,
                 supply_chain: SupplyChainEngine | None = None):
        self.fleet = fleet or FleetEngine()
        self.routing = routing or RoutingEngine()
        self.supply_chain = supply_chain or SupplyChainEngine()
        self._llm_available = False
        self._init_llm()

    def _init_llm(self) -> None:
        try:
            from orchestra.code_agent.serving.providers import get_provider
            self._provider = get_provider()
            self._llm_available = self._provider is not None
        except Exception:
            self._llm_available = False

    # ── Route Optimization ──────────────────────

    def optimize_daily_routes(self) -> dict[str, Any]:
        """Suggest optimal route assignments based on available fleet and pending shipments."""
        shipments = self.supply_chain.get_shipments_by_status(ShipmentStatus.PENDING)
        pending = [s for s in shipments if s.status.value == "pending"]
        vehicles = [v for v in self.fleet.vehicles.values() if v.is_available]
        drivers = [d for d in self.fleet.drivers.values() if d.is_available]

        if not pending or not vehicles:
            return {"routes_created": 0, "message": "No pending shipments or available vehicles"}

        routes_created = 0
        for i, shipment in enumerate(pending[:len(vehicles)]):
            vehicle = vehicles[i % len(vehicles)]
            driver = drivers[i % len(drivers)] if drivers else None

            route = self.routing.create_route(
                name=f"AI-Optimized-{shipment.tracking_code}",
                vehicle_id=vehicle.id,
                driver_id=driver.id if driver else "",
                stops=[],
            )
            self.supply_chain.assign_to_route(shipment.id, vehicle.id, route.id)
            vehicle.status = VehicleStatus.IN_TRANSIT
            if driver:
                driver.status = "driving"
            routes_created += 1

        return {
            "routes_created": routes_created,
            "shipments_assigned": min(len(pending), len(vehicles)),
            "vehicles_used": min(len(pending), len(vehicles)),
            "drivers_assigned": min(len(pending), len(drivers)) if drivers else 0,
        }

    # ── Demand Forecasting ──────────────────────

    def forecast_demand(self, historical_data: list[float] | None = None,
                        horizon: int = 7) -> dict[str, Any]:
        """Forecast shipment/delivery demand using exponential smoothing."""
        data = historical_data or self._generate_historical()

        if len(data) < 2:
            return {"forecast": data, "method": "insufficient_data"}

        alpha = 0.3
        smoothed = [data[0]]
        for i in range(1, len(data)):
            smoothed.append(alpha * data[i] + (1 - alpha) * smoothed[-1])

        last = smoothed[-1]
        forecast = []
        for i in range(horizon):
            val = max(0, last * (1 + random.gauss(0, 0.05)))
            forecast.append(round(val))
            last = val

        return {
            "historical": data,
            "smoothed": [round(v) for v in smoothed],
            "forecast": forecast,
            "horizon": horizon,
            "method": "exponential_smoothing",
            "trend": "up" if forecast[-1] > forecast[0] else "down" if forecast[-1] < forecast[0] else "stable",
            "next_period_estimate": forecast[0],
        }

    def _generate_historical(self) -> list[float]:
        base = len(self.supply_chain.shipments)
        if base > 10:
            return [max(1, base + random.randint(-5, 10)) for _ in range(14)]
        return [random.randint(20, 50) for _ in range(14)]

    # ── Anomaly Detection ───────────────────────

    def detect_anomalies(self) -> list[dict[str, Any]]:
        """Detect operational anomalies in fleet, routes, and shipments."""
        anomalies = []

        # Overdue shipments
        for s in self.supply_chain.shipments.values():
            if not s.is_delivered and s.days_in_transit > 3:
                anomalies.append({
                    "type": "overdue_shipment",
                    "severity": "critical",
                    "entity_id": s.id,
                    "description": f"Shipment {s.tracking_code} overdue by {s.days_in_transit} days",
                    "recommendation": "Expedite delivery or contact customer",
                })

        # Vehicle maintenance needed
        for v in self.fleet.vehicles.values():
            if v.status == VehicleStatus.MAINTENANCE:
                anomalies.append({
                    "type": "vehicle_maintenance",
                    "severity": "warning",
                    "entity_id": v.id,
                    "description": f"Vehicle {v.name} ({v.plate}) in maintenance",
                    "recommendation": "Schedule backup vehicle",
                })

        # Driver hours exceeded
        for d in self.fleet.drivers.values():
            if d.hours_this_week > d.max_hours_per_week:
                anomalies.append({
                    "type": "driver_hours_exceeded",
                    "severity": "critical",
                    "entity_id": d.id,
                    "description": f"Driver {d.name} exceeded {d.max_hours_per_week}h/week",
                    "recommendation": "Assign relief driver immediately",
                })

        # Low inventory
        for item in self.supply_chain.get_items_needing_reorder():
            anomalies.append({
                "type": "low_inventory",
                "severity": "warning",
                "entity_id": item.sku,
                "description": f"'{item.name}' ({item.sku}) at {item.quantity} units — reorder point {item.reorder_point}",
                "recommendation": f"Reorder from {item.supplier or 'default supplier'}",
            })

        return anomalies

    # ── Fleet Health ────────────────────────────

    def fleet_health_score(self) -> dict[str, Any]:
        metrics = self.fleet.get_metrics()
        score = 100.0
        reasons = []

        if metrics.fleet_utilization < 50:
            score -= 15
            reasons.append("Low fleet utilization")
        if metrics.maintenance > metrics.total_vehicles * 0.2:
            score -= 10
            reasons.append("High maintenance ratio")
        if metrics.active_drivers < metrics.total_drivers * 0.5:
            score -= 10
            reasons.append("Low driver availability")

        on_time = self.supply_chain.get_on_time_rate()
        if on_time < 80:
            score -= 15
            reasons.append(f"Low on-time delivery rate ({on_time}%)")

        score = max(0, score)
        return {
            "score": round(score, 1),
            "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 50 else "D",
            "reasons": reasons,
            "metrics": {
                "fleet_utilization": round(metrics.fleet_utilization, 1),
                "on_time_rate": on_time,
                "available_vehicles": metrics.available,
                "active_drivers": metrics.active_drivers,
            },
        }

    # ── AI-Powered Analysis ─────────────────────

    async def llm_analyze(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        if not self._llm_available:
            return self._offline_analysis(prompt, context)
        ctx = context or {}
        full_prompt = f"""You are a logistics AI copilot analyzing operational data.

Context:
Fleet: {ctx.get('fleet', 'N/A')}
Routes: {ctx.get('routes', 'N/A')}
Shipments: {ctx.get('shipments', 'N/A')}

Question: {prompt}

Provide concise, actionable logistics analysis with specific numbers."""
        try:
            result = await self._provider.llm.invoke(full_prompt)
            return result
        except Exception as e:
            return f"Analysis error: {e}"

    def _offline_analysis(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        metrics = self.fleet.get_metrics()
        anomalies = self.detect_anomalies()
        return (
            f"📊 Fleet: {metrics.total_vehicles} vehicles ({metrics.available} available, "
            f"{metrics.in_transit} in transit, {metrics.maintenance} in maintenance).\n"
            f"👨‍✈️ Drivers: {metrics.total_drivers} total ({metrics.active_drivers} active).\n"
            f"📦 Shipments: {len(self.supply_chain.shipments)} total.\n"
            f"⚠️ Anomalies: {len(anomalies)} detected.\n\n"
            f"Your question: \"{prompt}\"\n\n"
            f"💡 Connect an LLM provider (Ollama/OpenAI) for full AI-powered analysis."
        )

    def get_summary(self) -> dict[str, Any]:
        fleet = self.fleet.get_metrics()
        anomalies = self.detect_anomalies()
        health = self.fleet_health_score()
        return {
            "fleet": {
                "total_vehicles": fleet.total_vehicles,
                "available": fleet.available,
                "utilization": round(fleet.fleet_utilization, 1),
            },
            "health_score": health["score"],
            "health_grade": health["grade"],
            "anomalies": len(anomalies),
            "critical_anomalies": sum(1 for a in anomalies if a["severity"] == "critical"),
            "llm_available": self._llm_available,
        }



