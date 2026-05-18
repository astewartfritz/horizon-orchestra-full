"""Tests for the active_agents module."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_agent.active_agents.base import (
    ActiveAgent,
    AgentCapability,
    AgentHealthStatus,
    AgentResult,
    AgentStatus,
)
from code_agent.active_agents.claude_code import ClaudeCodeAgent
from code_agent.active_agents.codex import CodexAgent
from code_agent.active_agents.openclaw import OpenClawAgent
from code_agent.active_agents.registry import ActiveAgentRegistry, build_default_registry


# ---------------------------------------------------------------------------
# AgentResult / AgentHealthStatus
# ---------------------------------------------------------------------------

class TestAgentResult:
    def test_bool_true_on_success(self):
        r = AgentResult(agent_name="x", output="hi", success=True)
        assert bool(r) is True

    def test_bool_false_on_failure(self):
        r = AgentResult(agent_name="x", output="", success=False)
        assert bool(r) is False

    def test_default_fields(self):
        r = AgentResult(agent_name="x", output="ok", success=True)
        assert r.error == ""
        assert r.duration_ms == 0.0
        assert r.metadata == {}


class TestAgentHealthStatus:
    def test_fields(self):
        h = AgentHealthStatus(
            agent_name="a",
            status=AgentStatus.AVAILABLE,
            version="1.0",
            latency_ms=10.5,
            detail="ok",
        )
        assert h.agent_name == "a"
        assert h.status == AgentStatus.AVAILABLE


# ---------------------------------------------------------------------------
# ActiveAgent ABC / can_handle
# ---------------------------------------------------------------------------

class ConcreteAgent(ActiveAgent):
    name = "concrete"
    display_name = "Concrete"
    priority = 99
    capabilities = [
        AgentCapability(
            name="test_cap",
            description="test",
            intent_keywords=["alpha", "beta"],
        )
    ]

    async def execute(self, task, context=None):
        return AgentResult(agent_name=self.name, output="done", success=True)

    async def health_check(self):
        return AgentHealthStatus(agent_name=self.name, status=AgentStatus.AVAILABLE)


class TestActiveAgentBase:
    def test_can_handle_match(self):
        a = ConcreteAgent()
        assert a.can_handle("do alpha things") is True

    def test_can_handle_no_match(self):
        a = ConcreteAgent()
        assert a.can_handle("unrelated task") is False

    def test_capability_names(self):
        a = ConcreteAgent()
        assert "test_cap" in a.capability_names()

    def test_to_dict(self):
        a = ConcreteAgent()
        d = a.to_dict()
        assert d["name"] == "concrete"
        assert d["priority"] == 99
        assert len(d["capabilities"]) == 1

    def test_execute(self):
        a = ConcreteAgent()
        result = asyncio.run(a.execute("alpha task"))
        assert result.success is True

    def test_health_check(self):
        a = ConcreteAgent()
        h = asyncio.run(a.health_check())
        assert h.status == AgentStatus.AVAILABLE


# ---------------------------------------------------------------------------
# ClaudeCodeAgent
# ---------------------------------------------------------------------------

class TestClaudeCodeAgent:
    def test_defaults(self):
        a = ClaudeCodeAgent()
        assert a.name == "claude_code"
        assert a.priority == 10

    def test_can_handle_code(self):
        a = ClaudeCodeAgent()
        assert a.can_handle("write a function to sort a list") is True

    def test_can_handle_git(self):
        a = ClaudeCodeAgent()
        assert a.can_handle("create a git commit") is True

    def test_execute_cli_success(self):
        a = ClaudeCodeAgent()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"result output", b""))

        async def _run():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                return await a.execute("write hello world")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.output == "result output"
        assert result.metadata.get("via") != "api"

    def test_execute_cli_failure_falls_back(self):
        a = ClaudeCodeAgent()

        async def _run():
            with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
                with patch.object(a, "_api_fallback", new_callable=AsyncMock) as mock_fb:
                    mock_fb.return_value = AgentResult(
                        agent_name="claude_code", output="api result", success=True,
                        metadata={"via": "api"}
                    )
                    return await a.execute("write hello world")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.output == "api result"

    def test_execute_timeout(self):
        a = ClaudeCodeAgent(timeout=1)
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        async def _run():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                return await a.execute("task")

        result = asyncio.run(_run())
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_health_check_cli_available(self):
        a = ClaudeCodeAgent()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"claude 1.2.3\n", b""))

        async def _run():
            with patch("shutil.which", return_value="/usr/bin/claude"):
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    return await a.health_check()

        status = asyncio.run(_run())
        assert status.status == AgentStatus.AVAILABLE
        assert "1.2.3" in status.version

    def test_health_check_no_cli_with_sdk(self):
        a = ClaudeCodeAgent()

        async def _run():
            with patch("shutil.which", return_value=None):
                with patch.dict("sys.modules", {"anthropic": MagicMock()}):
                    return await a.health_check()

        status = asyncio.run(_run())
        assert status.status in (AgentStatus.DEGRADED, AgentStatus.UNAVAILABLE)


# ---------------------------------------------------------------------------
# CodexAgent
# ---------------------------------------------------------------------------

class TestCodexAgent:
    def test_defaults(self):
        a = CodexAgent()
        assert a.name == "codex"
        assert a.priority == 20

    def test_can_handle_refactor(self):
        a = CodexAgent()
        assert a.can_handle("refactor this module") is True

    def test_execute_cli_success(self):
        a = CodexAgent()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"codex output", b""))

        async def _run():
            with patch("shutil.which", return_value="/usr/bin/codex"):
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    return await a.execute("implement a sort function")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.metadata.get("via") == "cli"

    def test_execute_no_cli_uses_api(self):
        a = CodexAgent(api_key="sk-test")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "def sort(): pass"}}]
        }

        async def _run():
            with patch("shutil.which", return_value=None):
                import httpx
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_resp)
                with patch("httpx.AsyncClient", return_value=mock_client):
                    return await a.execute("write a sort function")

        result = asyncio.run(_run())
        assert result.success is True
        assert "sort" in result.output

    def test_execute_no_key_no_cli(self):
        a = CodexAgent(api_key="")

        async def _run():
            with patch("shutil.which", return_value=None):
                return await a.execute("task")

        result = asyncio.run(_run())
        assert result.success is False
        assert "OPENAI_API_KEY" in result.error


# ---------------------------------------------------------------------------
# OpenClawAgent
# ---------------------------------------------------------------------------

class TestOpenClawAgent:
    def test_defaults(self):
        a = OpenClawAgent()
        assert a.name == "openclaw"
        assert a.priority == 30

    def test_can_handle_test(self):
        a = OpenClawAgent()
        assert a.can_handle("generate unit tests for this module") is True

    def test_can_handle_analysis(self):
        a = OpenClawAgent()
        assert a.can_handle("analyze code quality") is True

    def test_execute_cli_success(self):
        a = OpenClawAgent()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"claw output", b""))

        async def _run():
            with patch("shutil.which", return_value="/usr/bin/openclaw"):
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    return await a.execute("analyze this code")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.metadata.get("via") == "cli"

    def test_execute_fallback_to_ollama(self):
        a = OpenClawAgent()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "ollama response"}
        }

        async def _run():
            with patch("shutil.which", return_value=None):
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_resp)
                with patch("httpx.AsyncClient", return_value=mock_client):
                    return await a.execute("find the bug")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.metadata.get("via") == "ollama"

    def test_health_check_ollama_model_present(self):
        a = OpenClawAgent(ollama_model="codellama")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "codellama:latest"}]}

        async def _run():
            with patch("shutil.which", return_value=None):
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=mock_resp)
                with patch("httpx.AsyncClient", return_value=mock_client):
                    return await a.health_check()

        status = asyncio.run(_run())
        assert status.status == AgentStatus.AVAILABLE

    def test_health_check_unavailable(self):
        a = OpenClawAgent()

        async def _run():
            with patch("shutil.which", return_value=None):
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(side_effect=Exception("refused"))
                with patch("httpx.AsyncClient", return_value=mock_client):
                    return await a.health_check()

        status = asyncio.run(_run())
        assert status.status == AgentStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# ActiveAgentRegistry
# ---------------------------------------------------------------------------

class TestActiveAgentRegistry:
    def _make_agent(self, name: str, priority: int = 50) -> ConcreteAgent:
        a = ConcreteAgent()
        a.name = name
        a.priority = priority
        return a

    def test_register_and_get(self):
        reg = ActiveAgentRegistry()
        a = self._make_agent("foo")
        reg.register(a)
        assert reg.get("foo") is a

    def test_unregister(self):
        reg = ActiveAgentRegistry()
        a = self._make_agent("foo")
        reg.register(a)
        assert reg.unregister("foo") is True
        assert reg.get("foo") is None

    def test_unregister_nonexistent(self):
        reg = ActiveAgentRegistry()
        assert reg.unregister("ghost") is False

    def test_all_agents_sorted_by_priority(self):
        reg = ActiveAgentRegistry()
        reg.register(self._make_agent("low", 80))
        reg.register(self._make_agent("high", 10))
        reg.register(self._make_agent("mid", 50))
        names = [a.name for a in reg.all_agents()]
        assert names == ["high", "mid", "low"]

    def test_agents_for_intent(self):
        reg = ActiveAgentRegistry()
        reg.register(ClaudeCodeAgent())
        reg.register(CodexAgent())
        matches = reg.agents_for_intent("write a function")
        assert len(matches) > 0

    def test_agents_by_capability(self):
        reg = ActiveAgentRegistry()
        reg.register(ClaudeCodeAgent())
        reg.register(CodexAgent())
        matches = reg.agents_by_capability("coding")
        assert len(matches) == 2
        assert matches[0].name == "claude_code"  # lower priority number

    def test_run_health_checks(self):
        reg = ActiveAgentRegistry()
        a1 = self._make_agent("a1")
        a2 = self._make_agent("a2")
        reg.register(a1)
        reg.register(a2)
        health = asyncio.run(reg.run_health_checks())
        assert "a1" in health
        assert "a2" in health
        assert health["a1"].status == AgentStatus.AVAILABLE

    def test_available_agents_filters_unavailable(self):
        reg = ActiveAgentRegistry()
        a1 = self._make_agent("avail")
        a2 = self._make_agent("gone")
        reg.register(a1)
        reg.register(a2)

        health = {
            "avail": AgentHealthStatus("avail", AgentStatus.AVAILABLE),
            "gone": AgentHealthStatus("gone", AgentStatus.UNAVAILABLE),
        }
        available = reg.available_agents(health)
        assert len(available) == 1
        assert available[0].name == "avail"

    def test_execute_with_fallback_success(self):
        reg = ActiveAgentRegistry()
        reg.register(self._make_agent("first", 10))

        result = asyncio.run(reg.execute_with_fallback("do alpha task", intent="alpha"))
        assert result.success is True

    def test_execute_with_fallback_tries_fallback(self):
        reg = ActiveAgentRegistry()

        class FailAgent(ConcreteAgent):
            name = "fail_agent"
            priority = 5

            async def execute(self, task, context=None):
                return AgentResult(agent_name=self.name, output="", success=False, error="fail")

        class SuccessAgent(ConcreteAgent):
            name = "success_agent"
            priority = 10

        reg.register(FailAgent())
        reg.register(SuccessAgent())
        result = asyncio.run(reg.execute_with_fallback("do alpha task", intent="alpha"))
        assert result.success is True
        assert "fail_agent" in result.metadata.get("attempted_agents", [])

    def test_execute_no_agents(self):
        reg = ActiveAgentRegistry()
        result = asyncio.run(reg.execute_with_fallback("task"))
        assert result.success is False

    def test_to_dict(self):
        reg = ActiveAgentRegistry()
        reg.register(self._make_agent("x"))
        d = reg.to_dict()
        assert d["count"] == 1
        assert len(d["agents"]) == 1


class TestBuildDefaultRegistry:
    def test_builds_without_error(self):
        reg = build_default_registry()
        assert isinstance(reg, ActiveAgentRegistry)
        # At least one agent should load even without CLIs installed
        assert len(reg.all_agents()) >= 1
