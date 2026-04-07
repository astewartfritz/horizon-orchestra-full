"""Tests for Gemma 4 integration.

All tests run offline — every API call is mocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def run(coro):
    """Run an async coroutine in a fresh event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@mock.patch.dict(os.environ, {}, clear=True)
class _BaseTest(unittest.TestCase):
    pass


# ===========================================================================
# Router: Gemma 4 models
# ===========================================================================

class Gemma4RouterTests(_BaseTest):

    def test_gemma4_31b_in_default_models(self):
        from orchestra.router import DEFAULT_MODELS
        self.assertIn("gemma-4-31b", DEFAULT_MODELS)
        cfg = DEFAULT_MODELS["gemma-4-31b"]
        self.assertEqual(cfg.provider, "gemini")
        self.assertEqual(cfg.max_context, 256_000)
        self.assertTrue(cfg.supports_tools)
        self.assertTrue(cfg.supports_vision)
        self.assertTrue(cfg.supports_thinking)
        self.assertFalse(cfg.supports_audio)
        self.assertEqual(cfg.architecture, "dense")
        self.assertAlmostEqual(cfg.parameters_b, 30.7)

    def test_gemma4_26b_moe_in_default_models(self):
        from orchestra.router import DEFAULT_MODELS
        self.assertIn("gemma-4-26b-moe", DEFAULT_MODELS)
        cfg = DEFAULT_MODELS["gemma-4-26b-moe"]
        self.assertEqual(cfg.architecture, "moe")
        self.assertAlmostEqual(cfg.parameters_b, 25.2)
        self.assertIn("speed", cfg.strengths)

    def test_gemma4_e4b_has_audio(self):
        from orchestra.router import DEFAULT_MODELS
        cfg = DEFAULT_MODELS["gemma-4-e4b"]
        self.assertTrue(cfg.supports_audio)
        self.assertIn("audio", cfg.strengths)
        self.assertIn("on_device", cfg.strengths)
        self.assertEqual(cfg.max_context, 128_000)

    def test_gemma4_e2b_has_audio(self):
        from orchestra.router import DEFAULT_MODELS
        cfg = DEFAULT_MODELS["gemma-4-e2b"]
        self.assertTrue(cfg.supports_audio)
        self.assertFalse(cfg.supports_thinking)  # E2B doesn't support thinking
        self.assertEqual(cfg.architecture, "efficient")

    def test_all_gemma4_variants_registered(self):
        from orchestra.router import DEFAULT_MODELS
        gemma4_names = [n for n in DEFAULT_MODELS if n.startswith("gemma-4")]
        # 4 direct + 2 OpenRouter + 1 local vLLM + 2 Ollama = 9
        self.assertEqual(len(gemma4_names), 9)

    def test_is_gemma4_helper(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        self.assertTrue(router.is_gemma4("gemma-4-31b"))
        self.assertTrue(router.is_gemma4("gemma-4-ollama"))
        self.assertFalse(router.is_gemma4("kimi-k2.5"))
        self.assertFalse(router.is_gemma4("grok-3"))

    def test_get_config(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        cfg = router.get_config("gemma-4-31b")
        self.assertEqual(cfg.model_id, "gemma-4-31b-it")

    def test_gemma4_client_uses_openai_compat_url(self):
        from orchestra.router import ModelRouter
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            router = ModelRouter()
            client, model_id = router.get_client("gemma-4-31b")
        self.assertEqual(model_id, "gemma-4-31b-it")
        self.assertIn("openai", str(client.base_url))

    def test_route_picks_gemma4_for_vision_when_available(self):
        from orchestra.router import ModelRouter
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "gk"}):
            router = ModelRouter()
            pick = router.route("vision", constraints={"require_vision": True})
        cfg = router.models[pick]
        self.assertTrue(cfg.supports_vision)

    def test_list_models_includes_new_fields(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        models = router.list_models()
        gemma = next(m for m in models if m["name"] == "gemma-4-31b")
        self.assertIn("supports_audio", gemma)
        self.assertIn("supports_thinking", gemma)
        self.assertIn("architecture", gemma)
        self.assertIn("parameters_b", gemma)


# ===========================================================================
# Gemma 4 Provider tests
# ===========================================================================

class Gemma4ProviderTests(_BaseTest):

    def test_get_model_card(self):
        from orchestra.gemma4_provider import Gemma4Provider
        provider = Gemma4Provider()
        card = provider.get_model_card("gemma-4-31b")
        self.assertEqual(card["family"], "gemma-4")
        self.assertEqual(card["architecture"], "dense")
        self.assertEqual(card["license"], "Apache-2.0")
        self.assertTrue(card["capabilities"]["reasoning"])
        self.assertTrue(card["capabilities"]["vision"])
        self.assertTrue(card["capabilities"]["thinking"])
        self.assertTrue(card["capabilities"]["multilingual"])
        self.assertFalse(card["capabilities"]["audio"])

    def test_get_model_card_e4b_has_audio(self):
        from orchestra.gemma4_provider import Gemma4Provider
        provider = Gemma4Provider()
        card = provider.get_model_card("gemma-4-e4b")
        self.assertTrue(card["capabilities"]["audio"])
        self.assertTrue(card["capabilities"]["on_device"])

    def test_generate_ollama_modelfile(self):
        from orchestra.gemma4_provider import generate_ollama_modelfile
        content = generate_ollama_modelfile(variant="31b")
        self.assertIn("google/gemma-4-31B-it", content)
        self.assertIn("PARAMETER num_ctx", content)
        self.assertIn("Horizon Orchestra", content)

    def test_generate_ollama_modelfile_e4b(self):
        from orchestra.gemma4_provider import generate_ollama_modelfile
        content = generate_ollama_modelfile(variant="e4b")
        self.assertIn("google/gemma-4-E4B-it", content)

    def test_generate_vllm_command(self):
        from orchestra.gemma4_provider import generate_vllm_command
        cmd = generate_vllm_command(variant="31b", tensor_parallel=1)
        self.assertIn("vllm serve", cmd)
        self.assertIn("google/gemma-4-31B-it", cmd)
        self.assertIn("--enable-auto-tool-choice", cmd)
        self.assertIn("--dtype bfloat16", cmd)

    def test_generate_vllm_command_26b(self):
        from orchestra.gemma4_provider import generate_vllm_command
        cmd = generate_vllm_command(variant="26b-a4b", tensor_parallel=2, port=9000)
        self.assertIn("google/gemma-4-26B-A4B-it", cmd)
        self.assertIn("--tensor-parallel-size 2", cmd)
        self.assertIn("--port 9000", cmd)

    def test_generate_docker_service(self):
        from orchestra.gemma4_provider import generate_docker_service
        svc = generate_docker_service(variant="31b", gpu_count=1)
        self.assertEqual(svc["image"], "vllm/vllm-openai:nightly")
        self.assertIn("google/gemma-4-31B-it", svc["command"])
        self.assertIn("--enable-auto-tool-choice", svc["command"])

    def test_quant_table(self):
        from orchestra.gemma4_provider import _QUANT_TABLE
        self.assertIn("gemma-4-31b", _QUANT_TABLE)
        self.assertEqual(_QUANT_TABLE["gemma-4-31b"]["q4_0"], "17.4 GB")
        self.assertEqual(_QUANT_TABLE["gemma-4-e4b"]["bf16"], "15 GB")

    def test_think_openai_compat_parses_think_tags(self):
        """Test that _think_openai_compat extracts <think> blocks."""
        from orchestra.gemma4_provider import Gemma4Provider, Gemma4Config

        content = "<think>Let me reason about this...</think>The answer is 42."

        mock_msg = types.SimpleNamespace(content=content, tool_calls=None)
        mock_choice = types.SimpleNamespace(message=mock_msg)
        mock_usage = types.SimpleNamespace(completion_tokens=50, total_tokens=100)
        mock_resp = types.SimpleNamespace(choices=[mock_choice], usage=mock_usage)

        async def fake_create(**kwargs):
            return mock_resp

        config = Gemma4Config(model="gemma-4-31b-local", backend="openai_compat")
        provider = Gemma4Provider(config=config)

        with mock.patch.object(
            provider.router, "get_client",
            return_value=(types.SimpleNamespace(chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=fake_create)
            )), "google/gemma-4-31B-it"),
        ):
            result = run(provider._think_openai_compat(
                "What is 6 * 7?", "gemma-4-31b-local", "", 8192, 4096,
            ))

        self.assertEqual(result.thinking, "Let me reason about this...")
        self.assertEqual(result.answer, "The answer is 42.")
        self.assertEqual(result.answer_tokens, 50)


# ===========================================================================
# Architecture A with Gemma 4
# ===========================================================================

class ArchAGemma4Tests(_BaseTest):

    def test_monolithic_with_gemma4_model(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        config = MonolithicConfig(model="gemma-4-31b")
        agent = MonolithicAgent(config=config)
        self.assertEqual(agent.config.model, "gemma-4-31b")
        self.assertIn("memory_search", agent.tools.names)

    def test_system_prompt_includes_gemma4_name(self):
        from orchestra.arch_a import SYSTEM_TEMPLATE, _model_display_name, _thinking_block
        from orchestra.router import ModelRouter
        router = ModelRouter()
        display = _model_display_name("gemma-4-31b")
        thinking = _thinking_block("gemma-4-31b", router)
        self.assertIn("Gemma 4 31B Dense", display)
        self.assertIn("thinking", thinking.lower())

    def test_thinking_block_empty_for_non_thinking_model(self):
        from orchestra.arch_a import _thinking_block
        from orchestra.router import ModelRouter
        router = ModelRouter()
        thinking = _thinking_block("grok-3", router)
        self.assertEqual(thinking, "")


# ===========================================================================
# Architecture C with Gemma 4
# ===========================================================================

class ArchCGemma4Tests(_BaseTest):

    def test_swarm_with_gemma4_coordinator(self):
        from orchestra.arch_c import SwarmAgent, SwarmConfig
        config = SwarmConfig(coordinator_model="gemma-4-31b", default_agent_model="gemma-4-26b-moe")
        agent = SwarmAgent(config=config)
        self.assertEqual(agent.config.coordinator_model, "gemma-4-31b")
        self.assertEqual(agent.config.default_agent_model, "gemma-4-26b-moe")


# ===========================================================================
# Architecture E Docker Compose with Gemma 4
# ===========================================================================

class ArchEGemma4Tests(_BaseTest):

    def test_docker_compose_includes_gemma4_service(self):
        from orchestra.arch_e import generate_docker_compose
        import tempfile
        tmpdir = tempfile.mkdtemp()
        files = generate_docker_compose(tmpdir)
        compose = Path(files["docker-compose.yml"]).read_text()
        self.assertIn("gemma4-vllm", compose)
        self.assertIn("google/gemma-4-31B-it", compose)
        self.assertIn("GEMMA4_BASE_URL", compose)
        self.assertIn("GEMINI_API_KEY", compose)
        # Clean up
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_env_template_includes_gemini_key(self):
        from orchestra.arch_e import ENV_TEMPLATE
        self.assertIn("GEMINI_API_KEY", ENV_TEMPLATE)


# ===========================================================================
# Package-level imports
# ===========================================================================

class PackageImportTests(_BaseTest):

    def test_gemma4_provider_importable(self):
        from orchestra import (
            Gemma4Provider,
            Gemma4Config,
            Gemma4ThinkingResponse,
            MultimodalInput,
            Gemma4FunctionCall,
            generate_ollama_modelfile,
            generate_vllm_command,
        )
        self.assertTrue(callable(Gemma4Provider))
        self.assertTrue(callable(generate_ollama_modelfile))

    def test_full_package_import_smoke(self):
        """Import everything from orchestra — should not raise."""
        import orchestra
        self.assertTrue(hasattr(orchestra, "Gemma4Provider"))
        self.assertTrue(hasattr(orchestra, "ModelRouter"))
        self.assertTrue(hasattr(orchestra, "MonolithicAgent"))


if __name__ == "__main__":
    unittest.main()
