"""Tests for Claude Opus 4.6 native provider.

All tests run offline — every API call is mocked.
Modules are loaded directly (bypassing orchestra/__init__.py) to avoid
the agent_loop ↔ security circular import that exists in the package init.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

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
    """Install minimal stubs and load required modules."""
    if "orchestra.router" in sys.modules:
        return  # already bootstrapped

    # 1. Load the router (no problematic deps)
    _load_module("orchestra.router", "orchestra/router.py")

    # 2. Provide a stub for agent_loop so security.py doesn't circular-import
    al_stub = types.ModuleType("orchestra.agent_loop")

    class _ToolCallEvent:
        def __init__(self, iteration=0, tool_name="", arguments=None, tool_call_id=""):
            self.iteration = iteration
            self.tool_name = tool_name
            self.arguments = arguments or {}
            self.tool_call_id = tool_call_id

    class _ToolResultEvent:
        def __init__(self, iteration=0, tool_name="", result="", success=True, duration=0.0):
            self.iteration = iteration
            self.tool_name = tool_name
            self.result = result
            self.success = success
            self.duration = duration

    al_stub.ToolCallEvent = _ToolCallEvent
    al_stub.ToolResultEvent = _ToolResultEvent
    sys.modules["orchestra.agent_loop"] = al_stub

    # 3. Now load opus4_provider (only depends on router)
    _load_module("orchestra.opus4_provider", "orchestra/opus4_provider.py")


_bootstrap()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_block(text: str):
    return types.SimpleNamespace(type="text", text=text)


def _make_thinking_block(summary: str):
    return types.SimpleNamespace(type="thinking", thinking=summary)


def _make_tool_use_block(name: str, arguments: dict, call_id: str = "call_1"):
    return types.SimpleNamespace(
        type="tool_use",
        name=name,
        input=arguments,
        id=call_id,
    )


def _make_usage(input_tokens: int = 100, output_tokens: int = 50):
    return types.SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _make_response(content_blocks, usage=None):
    return types.SimpleNamespace(
        content=content_blocks,
        usage=usage or _make_usage(),
    )


# ===========================================================================
# Opus4Config tests
# ===========================================================================

class Opus4ConfigTests(unittest.TestCase):

    def test_default_config(self):
        from orchestra.opus4_provider import Opus4Config
        cfg = Opus4Config()
        self.assertEqual(cfg.model, "claude-opus-4-6")
        self.assertEqual(cfg.effort, "high")
        self.assertEqual(cfg.max_output_tokens, 128_000)
        self.assertEqual(cfg.temperature, 1.0)
        self.assertFalse(cfg.enable_compaction)
        self.assertFalse(cfg.fast_mode)
        self.assertEqual(cfg.backend, "anthropic")

    def test_custom_config(self):
        from orchestra.opus4_provider import Opus4Config
        cfg = Opus4Config(
            model="claude-sonnet-4-6",
            effort="low",
            max_output_tokens=4_096,
            temperature=0.7,
            enable_compaction=True,
            fast_mode=True,
            backend="vertex",
        )
        self.assertEqual(cfg.model, "claude-sonnet-4-6")
        self.assertEqual(cfg.effort, "low")
        self.assertEqual(cfg.max_output_tokens, 4_096)
        self.assertEqual(cfg.temperature, 0.7)
        self.assertTrue(cfg.enable_compaction)
        self.assertTrue(cfg.fast_mode)
        self.assertEqual(cfg.backend, "vertex")

    def test_effort_levels(self):
        from orchestra.opus4_provider import _EFFORT_LEVELS
        self.assertIn("low", _EFFORT_LEVELS)
        self.assertIn("medium", _EFFORT_LEVELS)
        self.assertIn("high", _EFFORT_LEVELS)
        self.assertIn("max", _EFFORT_LEVELS)
        self.assertEqual(len(_EFFORT_LEVELS), 4)


# ===========================================================================
# Opus4Provider init tests
# ===========================================================================

class Opus4ProviderInitTests(unittest.TestCase):

    def test_provider_init_defaults(self):
        from orchestra.opus4_provider import Opus4Provider, Opus4Config
        provider = Opus4Provider()
        self.assertIsInstance(provider.config, Opus4Config)
        self.assertEqual(provider.config.model, "claude-opus-4-6")
        self.assertIsNone(provider._anthropic_client)

    def test_provider_init_custom(self):
        from orchestra.opus4_provider import Opus4Provider, Opus4Config
        from orchestra.router import ModelRouter
        cfg = Opus4Config(model="claude-haiku-4-5", effort="low")
        router = ModelRouter()
        provider = Opus4Provider(router=router, config=cfg)
        self.assertEqual(provider.config.model, "claude-haiku-4-5")
        self.assertEqual(provider.config.effort, "low")
        self.assertIs(provider.router, router)


# ===========================================================================
# Opus4Provider._get_anthropic_client tests
# ===========================================================================

class Opus4ClientTests(unittest.TestCase):

    def test_get_anthropic_client_no_sdk(self):
        """RuntimeError when anthropic SDK is not installed."""
        opus4_mod = sys.modules["orchestra.opus4_provider"]
        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        with mock.patch.object(opus4_mod, "HAS_ANTHROPIC", False):
            with self.assertRaises(RuntimeError) as ctx:
                provider._get_anthropic_client()
        self.assertIn("anthropic SDK", str(ctx.exception))

    def test_get_anthropic_client_no_key(self):
        """RuntimeError when ANTHROPIC_API_KEY is missing."""
        opus4_mod = sys.modules["orchestra.opus4_provider"]
        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        with mock.patch.object(opus4_mod, "HAS_ANTHROPIC", True):
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    provider._get_anthropic_client()
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


# ===========================================================================
# Opus4Provider.think tests
# ===========================================================================

class Opus4ThinkTests(unittest.IsolatedAsyncioTestCase):

    def _make_provider_with_response(self, response):
        from orchestra.opus4_provider import Opus4Provider

        async def fake_create(**kwargs):
            return response

        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )
        return provider

    async def test_think_constructs_correct_params(self):
        """think() passes thinking config, temperature=1.0, and effort to API."""
        from orchestra.opus4_provider import Opus4Provider, get_effort_config

        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _make_response([
                _make_thinking_block("reasoning"),
                _make_text_block("answer"),
            ])

        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )

        await provider.think("hello", effort="medium")

        self.assertEqual(captured["temperature"], 1.0)
        self.assertEqual(captured["effort"], "medium")
        self.assertEqual(captured["thinking"], get_effort_config("medium"))
        self.assertEqual(captured["model"], "claude-opus-4-6")

    async def test_think_parses_thinking_blocks(self):
        """think() correctly fills ThinkingResponse from thinking + text blocks."""
        response = _make_response(
            [_make_thinking_block("I thought about it"), _make_text_block("42")],
            usage=_make_usage(input_tokens=50, output_tokens=20),
        )
        provider = self._make_provider_with_response(response)
        result = await provider.think("What is 6×7?")
        self.assertEqual(result.thinking_summary, "I thought about it")
        self.assertEqual(result.answer, "42")
        self.assertEqual(result.model, "claude-opus-4-6")

    async def test_think_effort_high(self):
        """effort='high' sends budget_tokens=16384."""
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _make_response([_make_text_block("ok")])

        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )
        await provider.think("hi", effort="high")
        self.assertEqual(captured["thinking"]["budget_tokens"], 16_384)

    async def test_think_effort_max(self):
        """effort='max' sends budget_tokens=32768."""
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _make_response([_make_text_block("ok")])

        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )
        await provider.think("hi", effort="max")
        self.assertEqual(captured["thinking"]["budget_tokens"], 32_768)


# ===========================================================================
# Opus4Provider.vision tests
# ===========================================================================

class Opus4VisionTests(unittest.IsolatedAsyncioTestCase):

    def _make_provider_with_response(self, response):
        from orchestra.opus4_provider import Opus4Provider

        async def fake_create(**kwargs):
            return response

        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )
        return provider

    async def test_vision_builds_image_url_blocks(self):
        """image_url VisionInput becomes a URL-source image block."""
        from orchestra.opus4_provider import VisionInput, _build_vision_block

        inp = VisionInput(
            type="image_url",
            content="https://example.com/cat.jpg",
            mime_type="image/jpeg",
        )
        block = _build_vision_block(inp)
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["type"], "url")
        self.assertEqual(block["source"]["url"], "https://example.com/cat.jpg")

    async def test_vision_builds_base64_blocks(self):
        """image_bytes VisionInput becomes a base64-source image block."""
        import base64
        from orchestra.opus4_provider import VisionInput, _build_vision_block

        raw = b"\x89PNG\r\n"
        inp = VisionInput(type="image_bytes", content=raw, mime_type="image/png")
        block = _build_vision_block(inp)
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["type"], "base64")
        self.assertEqual(block["source"]["media_type"], "image/png")
        self.assertEqual(block["source"]["data"], base64.b64encode(raw).decode())

    async def test_vision_builds_pdf_blocks(self):
        """pdf_bytes VisionInput becomes a document block."""
        from orchestra.opus4_provider import VisionInput, _build_vision_block

        raw = b"%PDF-1.4"
        inp = VisionInput(type="pdf_bytes", content=raw, mime_type="application/pdf")
        block = _build_vision_block(inp)
        self.assertEqual(block["type"], "document")
        self.assertEqual(block["source"]["type"], "base64")
        self.assertEqual(block["source"]["media_type"], "application/pdf")

    async def test_vision_enforces_600_limit(self):
        """vision() raises ValueError when more than 600 visual inputs are given."""
        from orchestra.opus4_provider import Opus4Provider, VisionInput

        provider = Opus4Provider()
        provider._anthropic_client = object()  # unreachable — error is raised before API call

        inputs = [
            VisionInput(
                type="image_url",
                content=f"https://img.example.com/{i}.png",
                mime_type="image/png",
            )
            for i in range(601)
        ]
        with self.assertRaises(ValueError) as ctx:
            await provider.vision(inputs)
        self.assertIn("600", str(ctx.exception))


# ===========================================================================
# Opus4Provider.function_call tests
# ===========================================================================

class Opus4FunctionCallTests(unittest.IsolatedAsyncioTestCase):

    def _make_provider_with_response(self, response):
        from orchestra.opus4_provider import Opus4Provider

        async def fake_create(**kwargs):
            return response

        provider = Opus4Provider()
        provider._anthropic_client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=fake_create)
        )
        return provider

    async def test_function_call_parses_tool_use(self):
        """function_call() correctly parses tool_use blocks into Opus4FunctionCall."""
        response = _make_response([
            _make_tool_use_block("search_web", {"query": "latest news"}, "call_abc"),
        ])
        provider = self._make_provider_with_response(response)

        tools = [{"name": "search_web", "description": "Search", "input_schema": {}}]
        text, calls = await provider.function_call("Search for news", tools=tools)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search_web")
        self.assertEqual(calls[0].arguments, {"query": "latest news"})
        self.assertEqual(calls[0].call_id, "call_abc")
        self.assertEqual(text, "")

    async def test_function_call_handles_text_and_tools(self):
        """function_call() collects both text blocks and tool_use blocks."""
        response = _make_response([
            _make_text_block("I'll search for that."),
            _make_tool_use_block("search_web", {"query": "AI news"}, "call_xyz"),
        ])
        provider = self._make_provider_with_response(response)

        tools = [{"name": "search_web", "description": "Search", "input_schema": {}}]
        text, calls = await provider.function_call("Find AI news", tools=tools)

        self.assertEqual(text, "I'll search for that.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search_web")


# ===========================================================================
# Opus4Provider.get_model_card tests
# ===========================================================================

class Opus4ModelCardTests(unittest.TestCase):

    def test_get_model_card_opus(self):
        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        card = provider.get_model_card("claude-opus-4-6")
        self.assertEqual(card["name"], "claude-opus-4-6")
        self.assertEqual(card["family"], "claude-opus-4")
        self.assertEqual(card["max_context"], 1_000_000)
        self.assertEqual(card["max_output"], 128_000)
        self.assertTrue(card["capabilities"]["extended_thinking"])
        self.assertTrue(card["capabilities"]["interleaved_thinking"])
        self.assertTrue(card["capabilities"]["vision"])
        self.assertTrue(card["capabilities"]["tool_use"])
        self.assertEqual(card["cost"]["input_per_1m_standard"], 5.0)
        self.assertEqual(card["cost"]["output_per_1m_standard"], 25.0)

    def test_get_model_card_sonnet(self):
        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        card = provider.get_model_card("claude-sonnet-4-6")
        self.assertTrue(card["capabilities"]["extended_thinking"])
        self.assertFalse(card["capabilities"]["interleaved_thinking"])
        self.assertEqual(card["max_output"], 64_000)
        self.assertEqual(card["cost"]["input_per_1m_standard"], 3.0)

    def test_get_model_card_haiku(self):
        from orchestra.opus4_provider import Opus4Provider
        provider = Opus4Provider()
        card = provider.get_model_card("claude-haiku-4-5")
        self.assertFalse(card["capabilities"]["extended_thinking"])
        self.assertFalse(card["capabilities"]["interleaved_thinking"])
        self.assertEqual(card["max_context"], 200_000)
        self.assertEqual(card["cost"]["input_per_1m_standard"], 1.0)


# ===========================================================================
# Helper function: get_effort_config tests
# ===========================================================================

class GetEffortConfigTests(unittest.TestCase):

    def test_get_effort_config_low(self):
        from orchestra.opus4_provider import get_effort_config
        cfg = get_effort_config("low")
        self.assertEqual(cfg["type"], "adaptive")
        self.assertEqual(cfg["budget_tokens"], 1_024)

    def test_get_effort_config_medium(self):
        from orchestra.opus4_provider import get_effort_config
        cfg = get_effort_config("medium")
        self.assertEqual(cfg["type"], "adaptive")
        self.assertEqual(cfg["budget_tokens"], 4_096)

    def test_get_effort_config_high(self):
        from orchestra.opus4_provider import get_effort_config
        cfg = get_effort_config("high")
        self.assertEqual(cfg["type"], "adaptive")
        self.assertEqual(cfg["budget_tokens"], 16_384)

    def test_get_effort_config_max(self):
        from orchestra.opus4_provider import get_effort_config
        cfg = get_effort_config("max")
        self.assertEqual(cfg["type"], "adaptive")
        self.assertEqual(cfg["budget_tokens"], 32_768)

    def test_get_effort_config_invalid(self):
        from orchestra.opus4_provider import get_effort_config
        with self.assertRaises(ValueError) as ctx:
            get_effort_config("ultra")
        self.assertIn("ultra", str(ctx.exception))

    def test_get_effort_config_case_insensitive(self):
        from orchestra.opus4_provider import get_effort_config
        cfg = get_effort_config("HIGH")
        self.assertEqual(cfg["budget_tokens"], 16_384)


# ===========================================================================
# Helper function: estimate_cost tests
# ===========================================================================

class EstimateCostTests(unittest.TestCase):

    def test_estimate_cost_opus(self):
        from orchestra.opus4_provider import estimate_cost
        # 10k input @ $5/1M + 2k output @ $25/1M = 0.05 + 0.05 = 0.10
        cost = estimate_cost(10_000, 2_000, "claude-opus-4-6")
        self.assertAlmostEqual(cost, 0.10, places=5)

    def test_estimate_cost_sonnet(self):
        from orchestra.opus4_provider import estimate_cost
        # 1M input @ $3/1M + 1M output @ $15/1M = 18.0
        cost = estimate_cost(1_000_000, 1_000_000, "claude-sonnet-4-6")
        self.assertAlmostEqual(cost, 18.0, places=5)

    def test_estimate_cost_fast_mode(self):
        from orchestra.opus4_provider import estimate_cost
        # fast mode: $30/$150 per 1M — 1M in + 1M out = 180
        cost_fast = estimate_cost(1_000_000, 1_000_000, "claude-opus-4-6", fast_mode=True)
        cost_std = estimate_cost(1_000_000, 1_000_000, "claude-opus-4-6", fast_mode=False)
        self.assertGreater(cost_fast, cost_std)
        self.assertAlmostEqual(cost_fast, 180.0, places=5)

    def test_estimate_cost_zero_tokens(self):
        from orchestra.opus4_provider import estimate_cost
        cost = estimate_cost(0, 0, "claude-haiku-4-5")
        self.assertAlmostEqual(cost, 0.0, places=6)


# ===========================================================================
# Dataclass field tests
# ===========================================================================

class ThinkingResponseDataclassTests(unittest.TestCase):

    def test_thinking_response_dataclass(self):
        from orchestra.opus4_provider import ThinkingResponse
        resp = ThinkingResponse(
            thinking_summary="I reasoned about this",
            answer="42",
            model="claude-opus-4-6",
            thinking_tokens=1000,
            answer_tokens=5,
            total_tokens=1105,
            effort_used="high",
        )
        self.assertEqual(resp.thinking_summary, "I reasoned about this")
        self.assertEqual(resp.answer, "42")
        self.assertEqual(resp.thinking_tokens, 1000)
        self.assertEqual(resp.effort_used, "high")

    def test_thinking_response_defaults(self):
        from orchestra.opus4_provider import ThinkingResponse
        resp = ThinkingResponse(thinking_summary="x", answer="y")
        self.assertEqual(resp.model, "")
        self.assertEqual(resp.thinking_tokens, 0)
        self.assertEqual(resp.effort_used, "high")


class VisionInputDataclassTests(unittest.TestCase):

    def test_vision_input_dataclass(self):
        from orchestra.opus4_provider import VisionInput
        vi = VisionInput(
            type="image_url",
            content="https://example.com/img.png",
            mime_type="image/png",
            detail="high",
        )
        self.assertEqual(vi.type, "image_url")
        self.assertEqual(vi.detail, "high")

    def test_vision_input_default_detail(self):
        from orchestra.opus4_provider import VisionInput
        vi = VisionInput(
            type="image_url",
            content="https://x.com/a.jpg",
            mime_type="image/jpeg",
        )
        self.assertEqual(vi.detail, "auto")


class Opus4FunctionCallDataclassTests(unittest.TestCase):

    def test_opus4_function_call_dataclass(self):
        from orchestra.opus4_provider import Opus4FunctionCall
        fc = Opus4FunctionCall(
            name="get_weather",
            arguments={"city": "Tokyo"},
            call_id="call_99",
        )
        self.assertEqual(fc.name, "get_weather")
        self.assertEqual(fc.arguments["city"], "Tokyo")
        self.assertEqual(fc.call_id, "call_99")

    def test_opus4_function_call_default_call_id(self):
        from orchestra.opus4_provider import Opus4FunctionCall
        fc = Opus4FunctionCall(name="noop", arguments={})
        self.assertEqual(fc.call_id, "")


if __name__ == "__main__":
    unittest.main()
