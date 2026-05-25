"""Tests for the nemotron routing module."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.code_agent.active_agents.base import AgentHealthStatus, AgentResult, AgentStatus
from orchestra.code_agent.active_agents.registry import ActiveAgentRegistry
from orchestra.code_agent.nemotron.classifier import ClassificationResult, NemotronClassifier
from orchestra.code_agent.nemotron.dispatch import NemotronDispatch
from orchestra.code_agent.nemotron.router import NemotronRouter, RoutingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_dict(name: str, priority: int = 50, caps: list[str] | None = None):
    caps = caps or ["coding"]
    return {
        "name": name,
        "display_name": name.title(),
        "priority": priority,
        "capabilities": [
            {"name": c, "description": c, "intent_keywords": [c]}
            for c in caps
        ],
    }


def _make_registry_with_agents(*names: str) -> ActiveAgentRegistry:
    from orchestra.code_agent.active_agents.base import AgentCapability

    class _StubAgent:
        def __init__(self, n, priority=50):
            self.name = n
            self.display_name = n.title()
            self.priority = priority
            self.capabilities = [
                AgentCapability("coding", "code", ["code", "write", "implement"])
            ]

        def can_handle(self, intent):
            return any(kw in intent.lower() for kw in ["code", "write", "implement"])

        def capability_names(self):
            return ["coding"]

        def to_dict(self):
            return {
                "name": self.name,
                "display_name": self.display_name,
                "priority": self.priority,
                "capabilities": [{"name": "coding", "description": "code"}],
            }

        async def execute(self, task, context=None):
            return AgentResult(agent_name=self.name, output=f"{self.name} output", success=True)

        async def health_check(self):
            return AgentHealthStatus(self.name, AgentStatus.AVAILABLE)

    reg = ActiveAgentRegistry()
    for i, n in enumerate(names):
        reg._agents[n] = _StubAgent(n, priority=(i + 1) * 10)
    return reg


# ---------------------------------------------------------------------------
# NemotronClassifier
# ---------------------------------------------------------------------------

class TestNemotronClassifier:
    def test_classify_empty_agents(self):
        clf = NemotronClassifier()
        result = asyncio.run(clf.classify("do something", []))
        assert result.agent_name == ""
        assert result.confidence == 0.0

    def test_keyword_classify_matches(self):
        clf = NemotronClassifier()
        agents = [
            _make_agent_dict("claude_code", 10, ["code", "write"]),
            _make_agent_dict("openclaw", 30, ["analyze", "search"]),
        ]
        result = clf._keyword_classify("write a function", agents, 0)
        assert result.agent_name == "claude_code"
        assert result.confidence > 0.3
        assert result.via == "keyword"

    def test_keyword_classify_no_match_picks_highest_priority(self):
        clf = NemotronClassifier()
        agents = [
            _make_agent_dict("agent_a", 10, ["alpha"]),
            _make_agent_dict("agent_b", 20, ["beta"]),
        ]
        result = clf._keyword_classify("unrelated task", agents, 0)
        # lowest priority number wins
        assert result.agent_name == "agent_a"
        assert result.confidence == 0.3

    def test_classify_ollama_success(self):
        clf = NemotronClassifier()
        agents = [_make_agent_dict("claude_code", 10)]
        ollama_resp = {
            "response": json.dumps({
                "agent": "claude_code",
                "confidence": 0.92,
                "reason": "coding task",
                "fallback_agents": [],
            })
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = ollama_resp

        async def _run():
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await clf.classify("write a sort function", agents)

        result = asyncio.run(_run())
        assert result.agent_name == "claude_code"
        assert result.confidence == pytest.approx(0.92)
        assert result.via == "nemotron"

    def test_classify_ollama_failure_falls_back_to_keyword(self):
        clf = NemotronClassifier()
        agents = [_make_agent_dict("claude_code", 10, ["code"])]

        async def _run():
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await clf.classify("write code", agents)

        result = asyncio.run(_run())
        assert result.agent_name == "claude_code"
        assert result.via == "keyword"

    def test_classify_duration_ms_set(self):
        clf = NemotronClassifier()
        agents = [_make_agent_dict("x", 10, ["alpha"])]

        async def _run():
            with patch.object(clf, "_call_ollama", new_callable=AsyncMock, return_value=None):
                return await clf.classify("alpha task", agents)

        result = asyncio.run(_run())
        assert result.duration_ms >= 0.0

    def test_format_agents(self):
        clf = NemotronClassifier()
        agents = [_make_agent_dict("foo", 10, ["coding", "git"])]
        text = clf._format_agents(agents)
        assert "foo" in text
        assert "10" in text


# ---------------------------------------------------------------------------
# NemotronRouter
# ---------------------------------------------------------------------------

class TestNemotronRouter:
    def _mock_classifier(self, agent_name: str, confidence: float = 0.8) -> NemotronClassifier:
        clf = MagicMock(spec=NemotronClassifier)
        clf.classify = AsyncMock(return_value=ClassificationResult(
            agent_name=agent_name,
            confidence=confidence,
            reason="test",
            fallback_agents=[],
        ))
        return clf

    def test_route_selects_classified_agent(self):
        reg = _make_registry_with_agents("claude_code", "codex")
        clf = self._mock_classifier("claude_code", 0.85)
        router = NemotronRouter(reg, clf)

        decision = asyncio.run(router.route("write a function", skip_health_check=True))
        assert decision.selected_agent == "claude_code"

    def test_route_overrides_low_confidence(self):
        reg = _make_registry_with_agents("claude_code", "codex")
        clf = self._mock_classifier("codex", 0.1)  # below threshold
        router = NemotronRouter(reg, clf, confidence_threshold=0.3)

        decision = asyncio.run(router.route("write a function", skip_health_check=True))
        # Should fall back to highest-priority available agent
        assert decision.selected_agent == "claude_code"

    def test_route_overrides_unknown_agent(self):
        reg = _make_registry_with_agents("claude_code", "codex")
        clf = self._mock_classifier("ghost_agent", 0.99)
        router = NemotronRouter(reg, clf)

        async def _run():
            with patch.object(reg, "run_health_checks", new_callable=AsyncMock,
                              return_value={
                                  "claude_code": AgentHealthStatus("claude_code", AgentStatus.AVAILABLE),
                                  "codex": AgentHealthStatus("codex", AgentStatus.AVAILABLE),
                              }):
                return await router.route("task")

        decision = asyncio.run(_run())
        assert decision.selected_agent in ("claude_code", "codex")

    def test_route_builds_fallback_chain(self):
        reg = _make_registry_with_agents("claude_code", "codex", "openclaw")
        clf = self._mock_classifier("claude_code", 0.9)
        clf.classify = AsyncMock(return_value=ClassificationResult(
            agent_name="claude_code",
            confidence=0.9,
            reason="best",
            fallback_agents=["codex"],
        ))
        router = NemotronRouter(reg, clf)

        decision = asyncio.run(router.route("task", skip_health_check=True))
        assert decision.selected_agent == "claude_code"
        assert "codex" in decision.fallback_chain

    def test_route_and_execute_success(self):
        reg = _make_registry_with_agents("claude_code")
        clf = self._mock_classifier("claude_code", 0.9)
        router = NemotronRouter(reg, clf)

        decision, result = asyncio.run(
            router.route_and_execute("write code", skip_health_check=True)
        )
        assert result.success is True
        assert result.output == "claude_code output"

    def test_route_and_execute_fallback_on_failure(self):
        reg = _make_registry_with_agents("claude_code", "codex")
        clf = self._mock_classifier("claude_code", 0.9)
        router = NemotronRouter(reg, clf)

        # Make claude_code fail
        async def _fail(task, context=None):
            return AgentResult(agent_name="claude_code", output="", success=False, error="fail")

        reg._agents["claude_code"].execute = _fail

        decision, result = asyncio.run(
            router.route_and_execute("write code", skip_health_check=True)
        )
        # Should have fallen back to codex
        assert result.success is True
        assert result.agent_name == "codex"

    def test_route_no_agents(self):
        reg = ActiveAgentRegistry()
        clf = self._mock_classifier("any", 0.5)
        router = NemotronRouter(reg, clf)

        decision, result = asyncio.run(
            router.route_and_execute("task", skip_health_check=True)
        )
        assert result.success is False

    def test_health_filtered_flag(self):
        reg = _make_registry_with_agents("claude_code", "codex")
        clf = self._mock_classifier("claude_code", 0.9)
        router = NemotronRouter(reg, clf)

        async def _run():
            # Only one healthy agent
            with patch.object(reg, "run_health_checks", new_callable=AsyncMock,
                              return_value={
                                  "claude_code": AgentHealthStatus("claude_code", AgentStatus.AVAILABLE),
                                  "codex": AgentHealthStatus("codex", AgentStatus.UNAVAILABLE),
                              }):
                return await router.route("task")

        decision = asyncio.run(_run())
        assert decision.health_filtered is True


# ---------------------------------------------------------------------------
# NemotronDispatch
# ---------------------------------------------------------------------------

class TestNemotronDispatch:
    def _make_dispatch(self, success: bool = True, agent: str = "claude_code") -> NemotronDispatch:
        router = MagicMock(spec=NemotronRouter)
        router.route_and_execute = AsyncMock(return_value=(
            RoutingDecision(
                classification=ClassificationResult(
                    agent_name=agent, confidence=0.9, reason="test"
                ),
                selected_agent=agent,
            ),
            AgentResult(agent_name=agent, output="ok", success=success),
        ))
        dispatch = NemotronDispatch(router)
        # expose router for test access
        dispatch._router = router
        return dispatch

    def test_dispatch_returns_record(self):
        d = self._make_dispatch()
        record = asyncio.run(d.dispatch("write code"))
        assert record.result.success is True
        assert record.total_duration_ms >= 0

    def test_dispatch_records_history(self):
        d = self._make_dispatch()
        asyncio.run(d.dispatch("task one"))
        asyncio.run(d.dispatch("task two"))
        assert len(d._history) == 2

    def test_history_limit(self):
        d = self._make_dispatch()
        d._history_limit = 3
        for i in range(5):
            asyncio.run(d.dispatch(f"task {i}"))
        assert len(d._history) == 3

    def test_history_returns_dicts(self):
        d = self._make_dispatch()
        asyncio.run(d.dispatch("test task"))
        h = d.history(limit=5)
        assert len(h) == 1
        assert "agent_used" in h[0]
        assert "success" in h[0]

    def test_stats_empty(self):
        d = self._make_dispatch()
        s = d.stats()
        assert s["total"] == 0
        assert s["success_rate"] == 0.0

    def test_stats_with_dispatches(self):
        router = MagicMock(spec=NemotronRouter)
        results = [True, True, False]
        call_count = [0]

        async def _route(task, context=None, skip_health_check=False):
            success = results[call_count[0] % len(results)]
            call_count[0] += 1
            return (
                RoutingDecision(
                    classification=ClassificationResult("a", 0.9, "t"),
                    selected_agent="a",
                ),
                AgentResult(agent_name="a", output="", success=success),
            )

        router.route_and_execute = _route
        d = NemotronDispatch(router)
        for i in range(3):
            asyncio.run(d.dispatch(f"task {i}"))

        s = d.stats()
        assert s["total"] == 3
        assert abs(s["success_rate"] - 2 / 3) < 0.01
        assert s["agents_used"]["a"] == 3

    def test_record_to_dict(self):
        d = self._make_dispatch()
        record = asyncio.run(d.dispatch("a long task that gets truncated " * 5))
        data = record.to_dict()
        assert len(data["task_preview"]) <= 120
        assert "routing" in data
        assert "total_duration_ms" in data
