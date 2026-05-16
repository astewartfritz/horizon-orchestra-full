"""Agent orchestrator — multi-agent dispatch system (TypeScript-style orchestration in Python)."""

from __future__ import annotations

from typing import Any, Callable


class Agent:
    """A dispatch agent with a specific role."""
    def __init__(self, name: str, role: str, handler: Callable):
        self.name = name
        self.role = role
        self.handler = handler

    async def run(self, context: dict[str, Any]) -> Any:
        return await self.handler(context) if hasattr(self.handler, '__call__') else self.handler(context)


class AgentOrchestrator:
    """Orchestrates multiple dispatch agents — AI dispatcher, compliance, cost visibility.

    Agents:
      - dispatcher: Matches loads to trucks, plans routes
      - compliance: Validates driver hours, ELD, regulations
      - cost_visibility: Calculates profitability, recommends rates
      - exception_handler: Detects and resolves operational exceptions
    """

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._register_defaults()

    def _register_defaults(self):
        from code_agent.logistics2.dispatch.load_matcher import LoadMatcher
        lm = LoadMatcher()

        async def dispatcher(ctx):
            loads = ctx.get("loads", [])
            vehicles = ctx.get("vehicles", [])
            return {"matches": [m.__dict__ for m in lm.match(loads, vehicles)]}

        async def compliance(ctx):
            drivers = ctx.get("drivers", [])
            violations = []
            for d in drivers:
                if d.get("hours_this_week", 0) > d.get("max_hours_per_week", 60):
                    violations.append(f"Driver {d.get('name')} exceeds hours")
                if d.get("status") not in ("available", "driving"):
                    violations.append(f"Driver {d.get('name')} unavailable")
            return {"violations": violations, "compliant": len(violations) == 0}

        async def cost_visibility(ctx):
            from code_agent.logistics2.dispatch.rate_engine import RateEngine
            re = RateEngine()
            loads = ctx.get("loads", [])
            insights = []
            for load in loads:
                rate = re.pricing.calculate_rate(
                    haversine(load.get("origin_lat", 0), load.get("origin_lng", 0),
                              load.get("dest_lat", 0), load.get("dest_lng", 0)),
                    load.get("weight_kg", 0), demand_supply_ratio=1.0)
                insights.append(rate)
            return {"rate_insights": insights}

        async def exception_handler(ctx):
            anomalies = ctx.get("anomalies", [])
            resolved = []
            for a in anomalies:
                resolved.append({"anomaly": a, "action": "auto_resolved", "status": "closed"})
            return {"resolved": resolved}

        self.register_agent(Agent("dispatcher", "load_matching", dispatcher))
        self.register_agent(Agent("compliance", "regulatory", compliance))
        self.register_agent(Agent("cost_visibility", "analytics", cost_visibility))
        self.register_agent(Agent("exception_handler", "operations", exception_handler))

    def register_agent(self, agent: Agent) -> None:
        self.agents[agent.name] = agent

    async def run_all(self, context: dict[str, Any]) -> dict[str, Any]:
        results = {}
        for name, agent in self.agents.items():
            try:
                results[name] = await agent.run(context)
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    async def run_agent(self, name: str, context: dict[str, Any]) -> Any:
        agent = self.agents.get(name)
        if not agent:
            return {"error": f"Agent '{name}' not found"}
        return await agent.run(context)


def haversine(lat1, lng1, lat2, lng2):
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
