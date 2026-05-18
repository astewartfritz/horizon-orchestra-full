"""Tests for Claude Opus 4.7 provider.

All tests run offline — API calls are mocked.
Modules are loaded directly (bypassing orchestra/__init__.py) to avoid
circular import issues that exist in the package init.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock
import asyncio
import json
import base64


# ---------------------------------------------------------------------------
# Bootstrap: load submodules directly to avoid circular __init__ import
# ---------------------------------------------------------------------------

def _load_module(dotted_name: str, rel_path: str):
    """Load a module from a relative file path, registering it in sys.modules."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base, rel_path)
    spec = importlib.util.spec_from_file_location(dotted_name, full_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _bootstrap():
    """Install minimal stubs and load the opus47 provider module."""
    if "orchestra.providers.opus47" in sys.modules:
        return sys.modules["orchestra.providers.opus47"]

    # Ensure orchestra.providers package exists in sys.modules
    if "orchestra" not in sys.modules:
        orchestra_stub = types.ModuleType("orchestra")
        orchestra_stub.__path__ = [
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "orchestra",
            )
        ]
        sys.modules["orchestra"] = orchestra_stub

    if "orchestra.providers" not in sys.modules:
        providers_stub = types.ModuleType("orchestra.providers")
        providers_stub.__path__ = [
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "orchestra",
                "providers",
            )
        ]
        sys.modules["orchestra.providers"] = providers_stub

    mod = _load_module(
        "orchestra.providers.opus47",
        "orchestra/providers/opus47.py",
    )
    return mod


_opus47 = _bootstrap()


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mock response helpers
# ---------------------------------------------------------------------------

def _mock_api_response(
    content_blocks=None,
    model="claude-opus-4-7",
    stop_reason="end_turn",
    usage=None,
    budget_remaining=None,
):
    """Build a dict that mimics an Anthropic Messages API JSON response."""
    if content_blocks is None:
        content_blocks = [{"type": "text", "text": "Hello from Opus 4.7!"}]
    if usage is None:
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
        }
    data = {
        "id": "msg_test_123",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "usage": usage,
    }
    if budget_remaining is not None:
        data["budget_remaining"] = budget_remaining
    return data


def _mock_httpx_response(data, status_code=200):
    """Create a mock httpx.Response object."""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


def _make_mock_client(response_data, status_code=200):
    """Create a mock httpx.AsyncClient that returns the given response."""
    mock_response = _mock_httpx_response(response_data, status_code)

    async def mock_post(*args, **kwargs):
        return mock_response

    mock_client = mock.MagicMock()
    mock_client.post = mock_post
    # Store the last post call args for inspection
    mock_client._last_post_args = None
    mock_client._last_post_kwargs = None

    original_post = mock_client.post

    async def tracking_post(*args, **kwargs):
        mock_client._last_post_args = args
        mock_client._last_post_kwargs = kwargs
        return mock_response

    mock_client.post = tracking_post
    return mock_client


# ===========================================================================
# TestOpus47Init
# ===========================================================================

class TestOpus47Init(unittest.TestCase):
    """Tests for module-level constants and Opus47Provider initialization."""

    def test_model_id(self):
        """MODEL_ID is 'claude-opus-4-7'."""
        self.assertEqual(_opus47.MODEL_ID, "claude-opus-4-7")

    def test_context_window(self):
        """CONTEXT_WINDOW is 1,000,000."""
        self.assertEqual(_opus47.CONTEXT_WINDOW, 1_000_000)

    def test_max_output(self):
        """MAX_OUTPUT_TOKENS is 128,000."""
        self.assertEqual(_opus47.MAX_OUTPUT_TOKENS, 128_000)

    def test_pricing(self):
        """PRICING dict has correct standard rates."""
        self.assertEqual(_opus47.PRICING, {"input": 5.0, "output": 25.0})

    def test_premium_pricing(self):
        """PREMIUM_PRICING dict has correct premium rates."""
        self.assertEqual(_opus47.PREMIUM_PRICING, {"input": 10.0, "output": 37.50})

    def test_effort_levels(self):
        """All 4 effort levels are present including 'xhigh'."""
        self.assertEqual(len(_opus47.EFFORT_LEVELS), 4)
        self.assertIn("low", _opus47.EFFORT_LEVELS)
        self.assertIn("medium", _opus47.EFFORT_LEVELS)
        self.assertIn("high", _opus47.EFFORT_LEVELS)
        self.assertIn("xhigh", _opus47.EFFORT_LEVELS)

    def test_beta_headers(self):
        """BETA_HEADERS contains the task_budgets header string."""
        self.assertIn("task_budgets", _opus47.BETA_HEADERS)
        self.assertEqual(
            _opus47.BETA_HEADERS["task_budgets"],
            "task-budgets-2026-03-13",
        )

    def test_default_init(self):
        """Opus47Provider defaults: effort='xhigh', task_budget=None."""
        provider = _opus47.Opus47Provider(api_key="test-key")
        self.assertEqual(provider.effort, "xhigh")
        self.assertIsNone(provider.task_budget)
        self.assertEqual(provider.api_key, "test-key")
        self.assertEqual(provider.base_url, "https://api.anthropic.com")
        self.assertIsNone(provider.client)

    def test_custom_init(self):
        """Opus47Provider accepts custom params."""
        provider = _opus47.Opus47Provider(
            api_key="sk-custom",
            base_url="https://custom.api.example.com/",
            effort="medium",
            task_budget=100_000,
        )
        self.assertEqual(provider.api_key, "sk-custom")
        self.assertEqual(provider.base_url, "https://custom.api.example.com")
        self.assertEqual(provider.effort, "medium")
        self.assertEqual(provider.task_budget, 100_000)


# ===========================================================================
# TestOpus47CostEstimation
# ===========================================================================

class TestOpus47CostEstimation(unittest.TestCase):
    """Tests for Opus47Provider.estimate_cost()."""

    def setUp(self):
        self.provider = _opus47.Opus47Provider(api_key="test-key")

    def test_standard_pricing(self):
        """Input < 200k uses standard pricing ($5/$25 per MTok)."""
        # 10k input @ $5/1M = 0.05, 2k output @ $25/1M = 0.05
        cost = self.provider.estimate_cost(10_000, 2_000)
        self.assertAlmostEqual(cost["input_cost"], 0.05, places=4)
        self.assertAlmostEqual(cost["output_cost"], 0.05, places=4)
        self.assertAlmostEqual(cost["total_cost"], 0.10, places=4)

    def test_premium_pricing(self):
        """Input > 200k uses premium pricing ($10/$37.50 per MTok)."""
        # 300k input @ $10/1M = 3.0, 10k output @ $37.50/1M = 0.375
        cost = self.provider.estimate_cost(300_000, 10_000)
        self.assertAlmostEqual(cost["input_cost"], 3.0, places=4)
        self.assertAlmostEqual(cost["output_cost"], 0.375, places=4)
        self.assertAlmostEqual(cost["total_cost"], 3.375, places=4)

    def test_boundary_200k(self):
        """Exactly 200k input tokens uses standard pricing (not premium)."""
        cost = self.provider.estimate_cost(200_000, 1_000)
        # 200k @ $5/1M = 1.0 (standard), 1k @ $25/1M = 0.025
        self.assertAlmostEqual(cost["input_cost"], 1.0, places=4)
        self.assertAlmostEqual(cost["output_cost"], 0.025, places=4)
        self.assertAlmostEqual(cost["total_cost"], 1.025, places=4)

    def test_zero_tokens(self):
        """Zero tokens yields zero cost."""
        cost = self.provider.estimate_cost(0, 0)
        self.assertEqual(cost["input_cost"], 0.0)
        self.assertEqual(cost["output_cost"], 0.0)
        self.assertEqual(cost["total_cost"], 0.0)

    def test_large_output(self):
        """Large output token counts are calculated correctly."""
        # 1k input @ $5/1M = 0.005, 128k output @ $25/1M = 3.2
        cost = self.provider.estimate_cost(1_000, 128_000)
        self.assertAlmostEqual(cost["input_cost"], 0.005, places=4)
        self.assertAlmostEqual(cost["output_cost"], 3.2, places=4)
        self.assertAlmostEqual(cost["total_cost"], 3.205, places=4)


# ===========================================================================
# TestOpus47Chat
# ===========================================================================

class TestOpus47Chat(unittest.TestCase):
    """Tests for Opus47Provider.chat() — all httpx calls are mocked."""

    def _make_provider(self, response_data=None, status_code=200):
        """Create a provider with a mocked httpx client."""
        if response_data is None:
            response_data = _mock_api_response()
        provider = _opus47.Opus47Provider(api_key="test-key")
        mock_client = _make_mock_client(response_data, status_code)
        provider.client = mock_client
        return provider, mock_client

    def test_chat_message_format(self):
        """chat() sends messages in the correct Anthropic format."""
        provider, mock_client = self._make_provider()
        messages = [{"role": "user", "content": "Hello!"}]

        run(provider.chat(messages=messages, system="Be helpful."))

        kwargs = mock_client._last_post_kwargs
        payload = kwargs["json"]
        self.assertEqual(payload["model"], "claude-opus-4-7")
        self.assertEqual(payload["messages"], messages)
        self.assertEqual(payload["system"], "Be helpful.")
        self.assertIn("max_tokens", payload)

    def test_chat_with_thinking(self):
        """chat() includes thinking config when thinking=True."""
        provider, mock_client = self._make_provider()
        messages = [{"role": "user", "content": "Think hard."}]

        run(provider.chat(messages=messages, thinking=True, effort="high"))

        payload = mock_client._last_post_kwargs["json"]
        self.assertIn("thinking", payload)
        self.assertEqual(payload["thinking"]["type"], "enabled")
        self.assertEqual(payload["thinking"]["budget_tokens"], 32_768)
        self.assertEqual(payload["temperature"], 1.0)

    def test_chat_with_tools(self):
        """chat() includes tool definitions when tools are provided."""
        provider, mock_client = self._make_provider()
        tools = [
            {
                "name": "search",
                "description": "Search the web",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
        messages = [{"role": "user", "content": "Search for something."}]

        run(provider.chat(messages=messages, tools=tools))

        payload = mock_client._last_post_kwargs["json"]
        self.assertIn("tools", payload)
        self.assertEqual(len(payload["tools"]), 1)
        self.assertEqual(payload["tools"][0]["name"], "search")

    def test_chat_effort_xhigh(self):
        """chat() with effort='xhigh' sets thinking budget to 65536."""
        provider, mock_client = self._make_provider()
        messages = [{"role": "user", "content": "Max effort."}]

        run(provider.chat(messages=messages, effort="xhigh", thinking=True))

        payload = mock_client._last_post_kwargs["json"]
        self.assertEqual(payload["thinking"]["budget_tokens"], 65_536)

    def test_chat_with_task_budget(self):
        """chat() includes task_budget and beta headers when specified."""
        provider, mock_client = self._make_provider()
        provider.task_budget = 100_000
        messages = [{"role": "user", "content": "Budget test."}]

        run(provider.chat(messages=messages))

        kwargs = mock_client._last_post_kwargs
        payload = kwargs["json"]
        headers = kwargs["headers"]
        self.assertEqual(payload["task_budget"], 100_000)
        self.assertIn("anthropic-beta", headers)
        self.assertEqual(headers["anthropic-beta"], "task-budgets-2026-03-13")

    def test_response_parsing(self):
        """chat() returns a correctly populated Opus47Response."""
        api_data = _mock_api_response(
            content_blocks=[
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "The answer is 42."},
            ],
            usage={
                "input_tokens": 150,
                "output_tokens": 30,
                "cache_creation_input_tokens": 200,
            },
            stop_reason="end_turn",
            budget_remaining=80_000,
        )
        provider, _ = self._make_provider(response_data=api_data)
        messages = [{"role": "user", "content": "What is the answer?"}]

        resp = run(provider.chat(messages=messages))

        self.assertIsInstance(resp, _opus47.Opus47Response)
        self.assertEqual(resp.content, "The answer is 42.")
        self.assertEqual(resp.thinking, "Let me think...")
        self.assertEqual(resp.model, "claude-opus-4-7")
        self.assertEqual(resp.stop_reason, "end_turn")
        self.assertEqual(resp.usage["input_tokens"], 150)
        self.assertEqual(resp.usage["output_tokens"], 30)
        self.assertEqual(resp.usage["thinking_tokens"], 200)
        self.assertEqual(resp.effort_used, "xhigh")
        self.assertEqual(resp.budget_remaining, 80_000)
        self.assertIsInstance(resp.tool_calls, list)
        self.assertEqual(len(resp.tool_calls), 0)


# ===========================================================================
# TestOpus47Vision
# ===========================================================================

class TestOpus47Vision(unittest.TestCase):
    """Tests for Opus47Provider.chat_with_vision() and image handling."""

    def test_vision_image_encoding(self):
        """chat_with_vision() base64-encodes image bytes into content blocks."""
        # PNG magic bytes
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

        api_data = _mock_api_response(
            content_blocks=[{"type": "text", "text": "I see an image."}],
        )
        provider = _opus47.Opus47Provider(api_key="test-key")
        mock_client = _make_mock_client(api_data)
        provider.client = mock_client

        messages = [{"role": "user", "content": "What is in this image?"}]
        run(provider.chat_with_vision(messages=messages, images=[png_bytes]))

        payload = mock_client._last_post_kwargs["json"]
        # The last user message should have image content blocks
        user_msg = None
        for msg in payload["messages"]:
            if msg.get("role") == "user":
                user_msg = msg
        self.assertIsNotNone(user_msg)
        self.assertIsInstance(user_msg["content"], list)

        # Find the image block
        image_blocks = [
            b for b in user_msg["content"] if b.get("type") == "image"
        ]
        self.assertEqual(len(image_blocks), 1)
        self.assertEqual(image_blocks[0]["source"]["type"], "base64")
        self.assertEqual(image_blocks[0]["source"]["media_type"], "image/png")
        expected_b64 = base64.b64encode(png_bytes).decode("utf-8")
        self.assertEqual(image_blocks[0]["source"]["data"], expected_b64)

    def test_vision_max_resolution(self):
        """Vision tool description mentions 2576px max resolution."""
        provider = _opus47.Opus47Provider(api_key="test-key")
        tools = provider.get_tools()
        vision_tool = [t for t in tools if t["name"] == "opus47_vision"][0]
        self.assertIn("2576", vision_tool["description"])


# ===========================================================================
# TestOpus47AgenticLoop
# ===========================================================================

class TestOpus47AgenticLoop(unittest.TestCase):
    """Tests for Opus47Provider.agentic_loop()."""

    def _make_provider_with_chat_sequence(self, responses):
        """Create a provider whose chat() returns responses in sequence."""
        provider = _opus47.Opus47Provider(api_key="test-key")
        call_count = {"n": 0}

        async def mock_chat(**kwargs):
            idx = min(call_count["n"], len(responses) - 1)
            call_count["n"] += 1
            return responses[idx]

        provider.chat = mock_chat
        return provider

    def test_agentic_budget_tracking(self):
        """Agentic loop correctly tracks and decrements thinking budget."""
        # First iteration: tool call with thinking tokens
        resp1 = _opus47.Opus47Response(
            content="I need to search.",
            thinking="Let me plan this.",
            tool_calls=[{"id": "tc_1", "name": "search", "input": {"q": "test"}}],
            model="claude-opus-4-7",
            usage={"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 5_000},
            stop_reason="tool_use",
            effort_used="xhigh",
            budget_remaining=None,
        )
        # Second iteration: end turn (no tool calls)
        resp2 = _opus47.Opus47Response(
            content="Done searching. The answer is 42.",
            thinking="Summarizing results.",
            tool_calls=[],
            model="claude-opus-4-7",
            usage={"input_tokens": 200, "output_tokens": 80, "thinking_tokens": 3_000},
            stop_reason="end_turn",
            effort_used="high",
            budget_remaining=None,
        )

        provider = self._make_provider_with_chat_sequence([resp1, resp2])
        tools = [{"name": "search", "description": "Search", "input_schema": {}}]

        result = run(provider.agentic_loop(
            task="Find the answer",
            tools=tools,
            budget_tokens=50_000,
            max_iterations=10,
        ))

        self.assertIsInstance(result, _opus47.AgenticResult)
        # Budget used = 5000 + 3000 = 8000
        self.assertEqual(result.budget_used, 8_000)
        self.assertEqual(result.budget_remaining, 42_000)
        self.assertEqual(result.total_tokens["thinking_tokens"], 8_000)

    def test_agentic_iteration_limit(self):
        """Agentic loop stops at max_iterations."""
        # Every iteration returns a tool call — loop should stop at max
        tool_resp = _opus47.Opus47Response(
            content="Still working...",
            thinking="Thinking...",
            tool_calls=[{"id": "tc_n", "name": "search", "input": {}}],
            model="claude-opus-4-7",
            usage={"input_tokens": 50, "output_tokens": 20, "thinking_tokens": 1_000},
            stop_reason="tool_use",
            effort_used="xhigh",
            budget_remaining=None,
        )

        provider = self._make_provider_with_chat_sequence([tool_resp])
        tools = [{"name": "search", "description": "Search", "input_schema": {}}]

        result = run(provider.agentic_loop(
            task="Infinite task",
            tools=tools,
            budget_tokens=1_000_000,
            max_iterations=3,
        ))

        self.assertEqual(result.iterations, 3)
        # 3 iterations * 1 tool call each = 3 tool calls
        self.assertEqual(len(result.tool_calls_made), 3)

    def test_agentic_result_fields(self):
        """AgenticResult has all expected fields populated."""
        resp = _opus47.Opus47Response(
            content="Final answer.",
            thinking="Deep thought.",
            tool_calls=[],
            model="claude-opus-4-7",
            usage={"input_tokens": 500, "output_tokens": 100, "thinking_tokens": 2_000},
            stop_reason="end_turn",
            effort_used="xhigh",
            budget_remaining=None,
        )

        provider = self._make_provider_with_chat_sequence([resp])
        tools = [{"name": "noop", "description": "No-op", "input_schema": {}}]

        result = run(provider.agentic_loop(
            task="Simple task",
            tools=tools,
            budget_tokens=10_000,
        ))

        self.assertIsInstance(result, _opus47.AgenticResult)
        self.assertEqual(result.final_response, "Final answer.")
        self.assertEqual(result.iterations, 1)
        self.assertIsInstance(result.tool_calls_made, list)
        self.assertIsInstance(result.total_tokens, dict)
        self.assertIn("input_tokens", result.total_tokens)
        self.assertIn("output_tokens", result.total_tokens)
        self.assertIn("thinking_tokens", result.total_tokens)
        self.assertEqual(result.budget_used, 2_000)
        self.assertEqual(result.budget_remaining, 8_000)
        self.assertIsInstance(result.thinking_trace, list)
        self.assertEqual(len(result.thinking_trace), 1)
        self.assertEqual(result.thinking_trace[0], "Deep thought.")
        self.assertIsInstance(result.cost, dict)
        self.assertIn("input_cost", result.cost)
        self.assertIn("output_cost", result.cost)
        self.assertIn("total_cost", result.cost)


# ===========================================================================
# TestOpus47Headers
# ===========================================================================

class TestOpus47Headers(unittest.TestCase):
    """Tests for Opus47Provider._build_headers()."""

    def test_headers_basic(self):
        """Basic headers include x-api-key, anthropic-version, content-type."""
        provider = _opus47.Opus47Provider(api_key="sk-test-123")
        headers = provider._build_headers()

        self.assertEqual(headers["x-api-key"], "sk-test-123")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertNotIn("anthropic-beta", headers)

    def test_headers_with_budget(self):
        """When task_budget is set, anthropic-beta header is added."""
        provider = _opus47.Opus47Provider(
            api_key="sk-test-456",
            task_budget=50_000,
        )
        headers = provider._build_headers()

        self.assertEqual(headers["x-api-key"], "sk-test-456")
        self.assertIn("anthropic-beta", headers)
        self.assertEqual(
            headers["anthropic-beta"],
            "task-budgets-2026-03-13",
        )


# ===========================================================================
# TestOpus47Tools
# ===========================================================================

class TestOpus47Tools(unittest.TestCase):
    """Tests for Opus47Provider.get_tools()."""

    def setUp(self):
        self.provider = _opus47.Opus47Provider(api_key="test-key")
        self.tools = self.provider.get_tools()

    def test_get_tools(self):
        """get_tools() returns exactly 3 tools."""
        self.assertEqual(len(self.tools), 3)

    def test_tool_names(self):
        """Correct tool names: opus47_chat, opus47_vision, opus47_agentic."""
        names = [t["name"] for t in self.tools]
        self.assertIn("opus47_chat", names)
        self.assertIn("opus47_vision", names)
        self.assertIn("opus47_agentic", names)


# ===========================================================================
# TestOpus47ThinkingBudget
# ===========================================================================

class TestOpus47ThinkingBudget(unittest.TestCase):
    """Tests for Opus47Provider._get_thinking_budget()."""

    def setUp(self):
        self.provider = _opus47.Opus47Provider(api_key="test-key")

    def test_low_budget(self):
        """Low effort thinking budget is 2048."""
        self.assertEqual(self.provider._get_thinking_budget("low"), 2_048)

    def test_medium_budget(self):
        """Medium effort thinking budget is 8192."""
        self.assertEqual(self.provider._get_thinking_budget("medium"), 8_192)

    def test_high_budget(self):
        """High effort thinking budget is 32768."""
        self.assertEqual(self.provider._get_thinking_budget("high"), 32_768)

    def test_xhigh_budget(self):
        """Xhigh effort thinking budget is 65536."""
        self.assertEqual(self.provider._get_thinking_budget("xhigh"), 65_536)

    def test_invalid_effort_raises(self):
        """Invalid effort level raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.provider._get_thinking_budget("ultra")
        self.assertIn("ultra", str(ctx.exception))

    def test_case_insensitive(self):
        """Effort level lookup is case-insensitive."""
        self.assertEqual(self.provider._get_thinking_budget("LOW"), 2_048)
        self.assertEqual(self.provider._get_thinking_budget("XHIGH"), 65_536)


# ===========================================================================
# TestOpus47ResponseParsing
# ===========================================================================

class TestOpus47ResponseParsing(unittest.TestCase):
    """Tests for Opus47Provider._parse_response() edge cases."""

    def setUp(self):
        self.provider = _opus47.Opus47Provider(api_key="test-key")

    def test_parse_text_only(self):
        """Parse a response with only text content."""
        data = _mock_api_response(
            content_blocks=[{"type": "text", "text": "Simple answer."}],
        )
        resp = self.provider._parse_response(data, "high")
        self.assertEqual(resp.content, "Simple answer.")
        self.assertIsNone(resp.thinking)
        self.assertEqual(resp.tool_calls, [])

    def test_parse_tool_use(self):
        """Parse a response with tool_use blocks."""
        data = _mock_api_response(
            content_blocks=[
                {"type": "text", "text": "Let me search."},
                {
                    "type": "tool_use",
                    "id": "toolu_abc",
                    "name": "web_search",
                    "input": {"query": "test"},
                },
            ],
            stop_reason="tool_use",
        )
        resp = self.provider._parse_response(data, "xhigh")
        self.assertEqual(resp.content, "Let me search.")
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0]["id"], "toolu_abc")
        self.assertEqual(resp.tool_calls[0]["name"], "web_search")
        self.assertEqual(resp.tool_calls[0]["input"], {"query": "test"})
        self.assertEqual(resp.stop_reason, "tool_use")

    def test_parse_multiple_thinking_blocks(self):
        """Multiple thinking blocks are joined with newlines."""
        data = _mock_api_response(
            content_blocks=[
                {"type": "thinking", "thinking": "First thought."},
                {"type": "thinking", "thinking": "Second thought."},
                {"type": "text", "text": "Final answer."},
            ],
        )
        resp = self.provider._parse_response(data, "high")
        self.assertEqual(resp.thinking, "First thought.\nSecond thought.")
        self.assertEqual(resp.content, "Final answer.")

    def test_parse_empty_content(self):
        """Parse a response with empty content list."""
        data = _mock_api_response(content_blocks=[])
        resp = self.provider._parse_response(data, "low")
        self.assertEqual(resp.content, "")
        self.assertIsNone(resp.thinking)
        self.assertEqual(resp.tool_calls, [])


# ===========================================================================
# TestOpus47Dataclasses
# ===========================================================================

class TestOpus47Dataclasses(unittest.TestCase):
    """Tests for Opus47Response and AgenticResult dataclasses."""

    def test_opus47_response_fields(self):
        """Opus47Response stores all fields correctly."""
        resp = _opus47.Opus47Response(
            content="Hello",
            thinking="I thought about it",
            tool_calls=[{"id": "t1", "name": "search", "input": {}}],
            model="claude-opus-4-7",
            usage={"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 50},
            stop_reason="end_turn",
            effort_used="high",
            budget_remaining=90_000,
        )
        self.assertEqual(resp.content, "Hello")
        self.assertEqual(resp.thinking, "I thought about it")
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.model, "claude-opus-4-7")
        self.assertEqual(resp.stop_reason, "end_turn")
        self.assertEqual(resp.effort_used, "high")
        self.assertEqual(resp.budget_remaining, 90_000)

    def test_agentic_result_fields(self):
        """AgenticResult stores all fields correctly."""
        result = _opus47.AgenticResult(
            final_response="Done.",
            iterations=3,
            tool_calls_made=[{"id": "t1"}, {"id": "t2"}],
            total_tokens={"input_tokens": 1000, "output_tokens": 500, "thinking_tokens": 2000},
            budget_used=2000,
            budget_remaining=48_000,
            thinking_trace=["thought1", "thought2"],
            cost={"input_cost": 0.005, "output_cost": 0.0125, "total_cost": 0.0175},
        )
        self.assertEqual(result.final_response, "Done.")
        self.assertEqual(result.iterations, 3)
        self.assertEqual(len(result.tool_calls_made), 2)
        self.assertEqual(result.budget_used, 2000)
        self.assertEqual(result.budget_remaining, 48_000)
        self.assertEqual(len(result.thinking_trace), 2)
        self.assertAlmostEqual(result.cost["total_cost"], 0.0175)


# ===========================================================================
# TestOpus47ImageMimeDetection
# ===========================================================================

class TestOpus47ImageMimeDetection(unittest.TestCase):
    """Tests for _detect_image_mime() helper."""

    def test_png_detection(self):
        """PNG magic bytes detected as image/png."""
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        self.assertEqual(_opus47._detect_image_mime(data), "image/png")

    def test_jpeg_detection(self):
        """JPEG magic bytes detected as image/jpeg."""
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        self.assertEqual(_opus47._detect_image_mime(data), "image/jpeg")

    def test_gif_detection(self):
        """GIF magic bytes detected as image/gif."""
        data = b"GIF89a" + b"\x00" * 20
        self.assertEqual(_opus47._detect_image_mime(data), "image/gif")

    def test_webp_detection(self):
        """WebP magic bytes detected as image/webp."""
        data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20
        self.assertEqual(_opus47._detect_image_mime(data), "image/webp")

    def test_unknown_fallback(self):
        """Unknown format falls back to image/png."""
        data = b"\x00\x01\x02\x03" + b"\x00" * 20
        self.assertEqual(_opus47._detect_image_mime(data), "image/png")


# ===========================================================================
# TestOpus47ChatErrors
# ===========================================================================

class TestOpus47ChatErrors(unittest.TestCase):
    """Tests for error handling in chat()."""

    def test_chat_api_error_raises(self):
        """chat() raises RuntimeError on non-2xx response."""
        error_data = {"error": {"type": "invalid_request_error", "message": "Bad request"}}
        provider = _opus47.Opus47Provider(api_key="test-key")
        mock_client = _make_mock_client(error_data, status_code=400)
        provider.client = mock_client

        messages = [{"role": "user", "content": "Hello"}]
        with self.assertRaises(RuntimeError) as ctx:
            run(provider.chat(messages=messages))
        self.assertIn("400", str(ctx.exception))

    def test_chat_no_httpx_raises(self):
        """chat() raises ImportError when httpx is not available."""
        provider = _opus47.Opus47Provider(api_key="test-key")
        with mock.patch.object(_opus47, "HAS_HTTPX", False):
            messages = [{"role": "user", "content": "Hello"}]
            with self.assertRaises(ImportError) as ctx:
                run(provider.chat(messages=messages))
            self.assertIn("httpx", str(ctx.exception))

    def test_chat_without_thinking(self):
        """chat() with thinking=False omits thinking config and temperature."""
        api_data = _mock_api_response()
        provider = _opus47.Opus47Provider(api_key="test-key")
        mock_client = _make_mock_client(api_data)
        provider.client = mock_client

        messages = [{"role": "user", "content": "Quick answer."}]
        run(provider.chat(messages=messages, thinking=False))

        payload = mock_client._last_post_kwargs["json"]
        self.assertNotIn("thinking", payload)
        self.assertNotIn("temperature", payload)


if __name__ == "__main__":
    unittest.main()
