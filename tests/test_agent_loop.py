"""Tests for orchestra/agent_loop.py.

Covers: ToolRegistry, AgentConfig, AgentLoop iteration/tool-dispatch/max-steps,
        and create_default_tools factory.
Uses pytest-asyncio for async generator tests.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.agent_loop import (
    AgentConfig,
    AgentLoop,
    ErrorEvent,
    FinalAnswerEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolRegistry,
    ToolResult,
    ToolResultEvent,
    ToolSpec,
    create_default_tools,
)
from orchestra.router import ModelConfig, ModelRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _echo_handler(text: str = "") -> str:
    return f"echo: {text}"


async def _raise_handler(text: str = "") -> str:
    raise ValueError("boom")


def _fake_router() -> ModelRouter:
    """Router with a single fake model that needs no real API key."""
    router = ModelRouter()
    router.register(
        "test-model",
        ModelConfig(
            model_id="test-model",
            provider="test",
            base_url="http://localhost:9999/v1",
            api_key_env="",
            strengths=("reasoning",),
        ),
    )
    return router


def _make_openai_response(
    content: str = "Done.",
    tool_calls: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a minimal mock OpenAI chat completion response."""
    msg = MagicMock()
    msg.content = content
    if tool_calls:
        tc_mocks = []
        for tc in tool_calls:
            m = MagicMock()
            m.id = tc["id"]
            m.function.name = tc["name"]
            m.function.arguments = json.dumps(tc.get("args", {}))
            tc_mocks.append(m)
        msg.tool_calls = tc_mocks
    else:
        msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register("echo", "Echo text", {"type": "object"}, _echo_handler)
        spec = reg.get("echo")
        assert spec is not None
        assert spec.name == "echo"
        assert spec.description == "Echo text"

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_names_property(self):
        reg = ToolRegistry()
        reg.register("a", "A", {}, _echo_handler)
        reg.register("b", "B", {}, _echo_handler)
        assert set(reg.names) == {"a", "b"}

    def test_get_openai_tools_format(self):
        reg = ToolRegistry()
        reg.register(
            "search",
            "Search the web",
            {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
            _echo_handler,
        )
        tools = reg.get_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "search"

    @pytest.mark.asyncio
    async def test_execute_known_tool_success(self):
        reg = ToolRegistry()
        reg.register("echo", "Echo", {}, _echo_handler)
        result = await reg.execute("echo", {"text": "hello"}, call_id="call_1")
        assert result.success is True
        assert "echo: hello" in result.result
        assert result.tool_call_id == "call_1"
        assert result.name == "echo"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self):
        reg = ToolRegistry()
        result = await reg.execute("no_such_tool", {}, call_id="c1")
        assert result.success is False
        data = json.loads(result.result)
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_handler_exception(self):
        reg = ToolRegistry()
        reg.register("raise", "Raises", {}, _raise_handler)
        result = await reg.execute("raise", {}, call_id="c2")
        assert result.success is False
        data = json.loads(result.result)
        assert "boom" in data["error"]

    def test_subset_contains_only_requested(self):
        reg = ToolRegistry()
        reg.register("a", "A", {}, _echo_handler)
        reg.register("b", "B", {}, _echo_handler)
        reg.register("c", "C", {}, _echo_handler)
        sub = reg.subset(["a", "c"])
        assert set(sub.names) == {"a", "c"}
        assert sub.get("b") is None

    def test_subset_ignores_missing_names(self):
        reg = ToolRegistry()
        reg.register("a", "A", {}, _echo_handler)
        sub = reg.subset(["a", "z"])  # "z" not in registry
        assert set(sub.names) == {"a"}


# ---------------------------------------------------------------------------
# AgentConfig defaults
# ---------------------------------------------------------------------------

class TestAgentConfig:
    def test_default_model(self):
        cfg = AgentConfig()
        assert cfg.model == "kimi-k2.5"

    def test_default_max_iterations(self):
        cfg = AgentConfig()
        assert cfg.max_iterations == 300

    def test_custom_config(self):
        cfg = AgentConfig(model="gpt-4o", max_iterations=10, temperature=0.0)
        assert cfg.model == "gpt-4o"
        assert cfg.max_iterations == 10
        assert cfg.temperature == 0.0


# ---------------------------------------------------------------------------
# AgentLoop — event-stream behaviour
# ---------------------------------------------------------------------------

class TestAgentLoop:
    def _make_loop(self, max_iterations: int = 5) -> tuple[AgentLoop, ToolRegistry]:
        router = _fake_router()
        tools = ToolRegistry()
        tools.register("echo", "Echo", {"type": "object"}, _echo_handler)
        cfg = AgentConfig(model="test-model", max_iterations=max_iterations)
        loop = AgentLoop(router=router, tools=tools, config=cfg)
        return loop, tools

    @pytest.mark.asyncio
    async def test_final_answer_on_first_iteration(self):
        loop, _ = self._make_loop()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("All done!")
        )

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            events = [e async for e in loop.run("Do a thing")]

        assert len(events) == 1
        assert isinstance(events[0], FinalAnswerEvent)
        assert events[0].content == "All done!"
        assert events[0].total_iterations == 1
        assert events[0].total_tool_calls == 0

    @pytest.mark.asyncio
    async def test_tool_call_then_final_answer(self):
        loop, _ = self._make_loop()
        mock_client = AsyncMock()

        # First call: model requests tool "echo"
        # Second call: model returns final answer
        mock_client.chat.completions.create = AsyncMock(side_effect=[
            _make_openai_response("", tool_calls=[{"id": "tc_1", "name": "echo", "args": {"text": "hi"}}]),
            _make_openai_response("Tool called, done."),
        ])

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            events = [e async for e in loop.run("Call echo")]

        event_types = [type(e).__name__ for e in events]
        assert "ToolCallEvent" in event_types
        assert "ToolResultEvent" in event_types
        assert "FinalAnswerEvent" in event_types

        tool_call = next(e for e in events if isinstance(e, ToolCallEvent))
        assert tool_call.tool_name == "echo"
        assert tool_call.arguments == {"text": "hi"}

        tool_result = next(e for e in events if isinstance(e, ToolResultEvent))
        assert tool_result.tool_name == "echo"
        assert tool_result.success is True

        final = next(e for e in events if isinstance(e, FinalAnswerEvent))
        assert final.content == "Tool called, done."
        assert final.total_tool_calls == 1

    @pytest.mark.asyncio
    async def test_max_iterations_termination(self):
        loop, _ = self._make_loop(max_iterations=3)
        mock_client = AsyncMock()
        # Always returns a tool call — loop should hit max_iterations
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(
                "", tool_calls=[{"id": "tc_x", "name": "echo", "args": {"text": "loop"}}]
            )
        )

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            events = [e async for e in loop.run("Infinite")]

        final = events[-1]
        assert isinstance(final, ErrorEvent)
        assert "Max iterations" in final.message
        assert final.recoverable is False
        # Should have tried 3 tool calls
        tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(tool_calls) == 3

    @pytest.mark.asyncio
    async def test_api_error_yields_error_event_and_stops(self):
        loop, _ = self._make_loop()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            events = [e async for e in loop.run("Fetch something")]

        assert len(events) >= 1
        error = events[-1]
        assert isinstance(error, ErrorEvent)
        assert error.recoverable is False
        assert "Network failure" in error.message

    @pytest.mark.asyncio
    async def test_context_is_prepended_to_messages(self):
        """When context is given, the first user message includes 'Prior context:'."""
        loop, _ = self._make_loop()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("Done with context.")
        )

        captured_messages: list[list] = []

        async def _capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return _make_openai_response("Done with context.")

        mock_client.chat.completions.create = _capture

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            _ = [e async for e in loop.run("Do task", context="Some prior context")]

        assert captured_messages
        user_msg = captured_messages[0][1]  # messages[0] = system, [1] = user
        assert "Prior context" in user_msg["content"]
        assert "Some prior context" in user_msg["content"]

    @pytest.mark.asyncio
    async def test_malformed_tool_args_fallback_to_empty_dict(self):
        """If the model returns invalid JSON for tool arguments, args default to {}."""
        loop, _ = self._make_loop()
        mock_client = AsyncMock()

        bad_args_response = _make_openai_response(
            "", tool_calls=[{"id": "tc_bad", "name": "echo", "args": {}}]
        )
        # Override the raw arguments string to be malformed JSON
        bad_args_response.choices[0].message.tool_calls[0].function.arguments = "{bad json"

        mock_client.chat.completions.create = AsyncMock(side_effect=[
            bad_args_response,
            _make_openai_response("Recovered."),
        ])

        with patch.object(loop.router, "get_client", return_value=(mock_client, "test-model")):
            events = [e async for e in loop.run("Bad args test")]

        tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
        assert tool_calls
        assert tool_calls[0].arguments == {}  # fell back to {}


# ---------------------------------------------------------------------------
# create_default_tools
# ---------------------------------------------------------------------------

class TestCreateDefaultTools:
    def test_returns_tool_registry(self):
        router = _fake_router()
        reg = create_default_tools(router)
        assert isinstance(reg, ToolRegistry)

    def test_core_tools_registered(self):
        reg = create_default_tools()
        expected = {
            "web_search", "fetch_url", "execute_code",
            "file_read", "file_write", "browser_action", "opencode_task",
        }
        for name in expected:
            assert name in reg.names, f"Expected tool {name!r} not in registry"

    @pytest.mark.asyncio
    async def test_web_search_stub_without_api_key(self):
        reg = create_default_tools()
        # Without PERPLEXITY_API_KEY, should return a stub JSON
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PERPLEXITY_API_KEY", None)
            result = await reg.execute("web_search", {"query": "test"})

        assert result.success is True
        data = json.loads(result.result)
        assert "note" in data or "results" in data

    @pytest.mark.asyncio
    async def test_execute_code_unsupported_language(self):
        reg = create_default_tools()
        result = await reg.execute("execute_code", {"code": "print('hi')", "language": "ruby"})
        assert result.success is True
        data = json.loads(result.result)
        assert "error" in data
        assert "Unsupported language" in data["error"]

    @pytest.mark.asyncio
    async def test_file_read_missing_file(self):
        reg = create_default_tools()
        result = await reg.execute("file_read", {"path": "/nonexistent/path/xyz.txt"})
        assert result.success is True
        data = json.loads(result.result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_browser_action_returns_stub(self):
        reg = create_default_tools()
        result = await reg.execute("browser_action", {"url": "https://example.com", "action": "navigate"})
        assert result.success is True
        data = json.loads(result.result)
        assert "note" in data
