import uuid
import time
import logging
from typing import Callable
from dataclasses import dataclass, field

from orchestra.code_agent.agentmesh import AgentRegistry, AgentInfo, AgentType, AgentStatus

logger = logging.getLogger(__name__)


class TeamFormationStrategy:
    def form(self, task: str, required_capabilities: list[str],
             registry: AgentRegistry) -> list[AgentInfo]:
        raise NotImplementedError


class BestFitStrategy(TeamFormationStrategy):
    def form(self, task: str, required_capabilities: list[str],
             registry: AgentRegistry) -> list[AgentInfo]:
        selected: set[str] = set()
        team: list[AgentInfo] = []
        for cap in required_capabilities:
            candidates = registry.discover_by_capability(cap)
            for c in candidates:
                if c.id not in selected and c.is_available():
                    selected.add(c.id)
                    team.append(c)
                    break
        return team


class LoadBalancedStrategy(TeamFormationStrategy):
    def form(self, task: str, required_capabilities: list[str],
             registry: AgentRegistry) -> list[AgentInfo]:
        selected: set[str] = set()
        team: list[AgentInfo] = []
        for cap in required_capabilities:
            candidates = registry.discover_by_capability(cap)
            candidates.sort(key=lambda a: (a.current_tasks, a.load_pct))
            for c in candidates:
                if c.id not in selected and c.is_available():
                    selected.add(c.id)
                    team.append(c)
                    break
        return team


class MinimumTeamStrategy(TeamFormationStrategy):
    def form(self, task: str, required_capabilities: list[str],
             registry: AgentRegistry) -> list[AgentInfo]:
        candidates = registry.discover_multi_capability(required_capabilities)
        best = None
        for c in candidates:
            if c.is_available():
                best = c
                break
        if best:
            return [best]
        return BestFitStrategy().form(task, required_capabilities, registry)


STRATEGIES: dict[str, type[TeamFormationStrategy]] = {
    "best_fit": BestFitStrategy,
    "load_balanced": LoadBalancedStrategy,
    "minimum_team": MinimumTeamStrategy,
}


@dataclass
class TeamFormationResult:
    team_id: str = ""
    members: list[AgentInfo] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    strategy_used: str = ""
    formation_time_ms: float = 0.0


class TeamFactory:
    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._strategies = {name: cls() for name, cls in STRATEGIES.items()}
        self._custom_strategies: dict[str, TeamFormationStrategy] = {}

    def register_strategy(self, name: str, strategy: TeamFormationStrategy):
        self._custom_strategies[name] = strategy

    def analyze_task(self, task: str) -> list[str]:
        capabilities = []
        task_lower = task.lower()
        keyword_map = {
            "code": "coding", "program": "coding", "implement": "coding",
            "function": "coding", "class": "coding", "sort": "coding",
            "algorithm": "coding", "api": "coding", "endpoint": "coding",
            "reason": "reasoning", "analyze": "reasoning", "think": "reasoning",
            "evaluate": "reasoning", "logic": "reasoning",
            "research": "research", "search": "research", "find": "research",
            "investigate": "research", "lookup": "research",
            "plan": "planning", "strategy": "planning", "design": "planning",
            "architect": "planning", "roadmap": "planning",
            "review": "code_review", "audit": "code_review", "validate": "code_review",
            "inspect": "code_review", "check": "code_review",
            "write": "writing", "document": "writing", "explain": "writing",
            "describe": "writing", "summarize": "writing",
            "debug": "debugging", "fix": "debugging", "bug": "debugging",
            "error": "debugging", "issue": "debugging",
        }
        for keyword, cap in keyword_map.items():
            if keyword in task_lower and cap not in capabilities:
                capabilities.append(cap)
        if not capabilities:
            capabilities.append("general")
        return capabilities

    async def form_team(self, task: str, required_capabilities: list[str] | None = None,
                        strategy: str = "best_fit", team_name: str = "") -> TeamFormationResult:
        start = time.time()
        if not required_capabilities:
            required_capabilities = self.analyze_task(task)

        strat = self._custom_strategies.get(strategy) or self._strategies.get(strategy)
        if not strat:
            strat = BestFitStrategy()

        members = strat.form(task, required_capabilities, self._registry)
        found_caps = set()
        for m in members:
            found_caps.update(m.capabilities)
        missing = [c for c in required_capabilities if c not in found_caps]

        result = TeamFormationResult(
            team_id=uuid.uuid4().hex,
            members=members,
            missing_capabilities=missing,
            strategy_used=strategy,
            formation_time_ms=(time.time() - start) * 1000,
        )
        return result
