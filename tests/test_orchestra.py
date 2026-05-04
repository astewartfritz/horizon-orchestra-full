"""Tests for the orchestra package.

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine in a fresh event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# Ensure no real API keys leak into tests
@mock.patch.dict(os.environ, {}, clear=True)
class _BaseTest(unittest.TestCase):
    pass


# ===========================================================================
# Router tests
# ===========================================================================

class RouterTests(_BaseTest):

    def test_default_models_contains_kimi(self):
        from orchestra.router import DEFAULT_MODELS
        self.assertIn("kimi-k2.5", DEFAULT_MODELS)
        cfg = DEFAULT_MODELS["kimi-k2.5"]
        self.assertEqual(cfg.provider, "moonshot")
        self.assertEqual(cfg.max_context, 262_144)
        self.assertTrue(cfg.supports_tools)
        self.assertTrue(cfg.supports_vision)

    def test_default_models_contains_sonar(self):
        from orchestra.router import DEFAULT_MODELS
        self.assertIn("sonar-pro", DEFAULT_MODELS)
        self.assertIn("web_search", DEFAULT_MODELS["sonar-pro"].strengths)

    def test_get_client_returns_correct_base_url(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        with mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}):
            client, model_id = router.get_client("kimi-k2.5")
        self.assertEqual(model_id, "kimi-k2.5")
        self.assertEqual(str(client.base_url).rstrip("/"), "https://api.moonshot.ai/v1")

    def test_route_prefers_web_search_model(self):
        from orchestra.router import ModelRouter
        with mock.patch.dict(os.environ, {"PERPLEXITY_API_KEY": "pk"}):
            router = ModelRouter()
            pick = router.route("web_search")
        cfg = router.models[pick]
        self.assertIn("web_search", cfg.strengths)

    def test_route_cheapest_for_speed(self):
        from orchestra.router import ModelRouter
        # With local models available (no key needed), route should pick free ones
        router = ModelRouter()
        pick = router.route("speed")
        cfg = router.models[pick]
        # Should be one of the zero-cost models
        self.assertTrue(cfg.cost_input <= 0.55)

    def test_route_with_tool_constraint(self):
        from orchestra.router import ModelRouter
        with mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "mk"}):
            router = ModelRouter()
            pick = router.route("coding", constraints={"require_tools": True})
            cfg = router.models[pick]
        self.assertTrue(cfg.supports_tools)

    def test_list_models(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        models = router.list_models()
        self.assertIsInstance(models, list)
        names = {m["name"] for m in models}
        self.assertIn("kimi-k2.5", names)
        self.assertIn("sonar-pro", names)


# ===========================================================================
# Tool Registry tests
# ===========================================================================

class ToolRegistryTests(_BaseTest):

    def test_register_and_get_openai_format(self):
        from orchestra.agent_loop import ToolRegistry
        reg = ToolRegistry()

        async def handler(x: str) -> str:
            return x

        reg.register(
            name="echo",
            description="Echo input",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            handler=handler,
        )

        tools = reg.get_openai_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "echo")

    def test_execute_calls_handler(self):
        from orchestra.agent_loop import ToolRegistry

        async def adder(a: int, b: int) -> str:
            return json.dumps({"sum": a + b})

        reg = ToolRegistry()
        reg.register("add", "Add two numbers", {"type": "object", "properties": {}}, adder)

        result = run(reg.execute("add", {"a": 3, "b": 4}, call_id="c1"))
        self.assertTrue(result.success)
        self.assertEqual(json.loads(result.result)["sum"], 7)

    def test_execute_unknown_tool(self):
        from orchestra.agent_loop import ToolRegistry
        reg = ToolRegistry()
        result = run(reg.execute("nope", {}, call_id="c2"))
        self.assertFalse(result.success)
        self.assertIn("Unknown", result.result)

    def test_subset(self):
        from orchestra.agent_loop import ToolRegistry

        async def noop() -> str:
            return ""

        reg = ToolRegistry()
        reg.register("a", "A", {}, noop)
        reg.register("b", "B", {}, noop)
        reg.register("c", "C", {}, noop)

        sub = reg.subset(["a", "c"])
        self.assertEqual(sub.names, ["a", "c"])


# ===========================================================================
# Agent Loop tests
# ===========================================================================

class AgentLoopTests(_BaseTest):

    def test_final_answer_event(self):
        """Agent that returns immediately (no tool calls) yields FinalAnswerEvent."""
        from orchestra.agent_loop import AgentLoop, AgentConfig, ToolRegistry, FinalAnswerEvent
        from orchestra.router import ModelRouter

        # Mock a chat completion that has no tool calls
        mock_msg = types.SimpleNamespace(
            content="Done.",
            tool_calls=None,
        )
        mock_choice = types.SimpleNamespace(message=mock_msg)
        mock_resp = types.SimpleNamespace(choices=[mock_choice])

        async def fake_create(**kwargs):
            return mock_resp

        router = ModelRouter()
        with mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "k"}):
            client, _ = router.get_client("kimi-k2.5")

        with mock.patch.object(client.chat.completions, "create", side_effect=fake_create):
            agent = AgentLoop(router, ToolRegistry(), AgentConfig(model="kimi-k2.5"))
            events = []

            async def collect():
                async for ev in agent.run("Hello"):
                    events.append(ev)

            run(collect())

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], FinalAnswerEvent)
        self.assertEqual(events[0].content, "Done.")


# ===========================================================================
# Memory tests
# ===========================================================================

class MemoryStoreTests(_BaseTest):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_memory.db"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_and_search(self):
        from orchestra.memory import MemoryStore
        store = MemoryStore(db_path=self.db_path)

        entry = run(store.store("user1", "I work at Horizon as CEO", category="identity"))
        self.assertTrue(entry.id)
        self.assertEqual(entry.category, "identity")

        results = run(store.search("user1", "What company does the user work at?"))
        self.assertTrue(len(results) > 0)
        self.assertIn("Horizon", results[0].content)

    def test_store_dedup(self):
        from orchestra.memory import MemoryStore
        store = MemoryStore(db_path=self.db_path)

        run(store.store("user1", "I prefer Python"))
        run(store.store("user1", "I prefer Python"))  # exact duplicate

        all_mems = run(store.list_all("user1"))
        # Dedup should prevent two identical entries
        self.assertEqual(len(all_mems), 1)

    def test_list_by_category(self):
        from orchestra.memory import MemoryStore
        store = MemoryStore(db_path=self.db_path)

        run(store.store("user1", "I use AWS", category="tool"))
        run(store.store("user1", "My name is Ashton", category="identity"))

        tools = run(store.list_all("user1", category="tool"))
        self.assertEqual(len(tools), 1)
        self.assertIn("AWS", tools[0].content)

    def test_delete(self):
        from orchestra.memory import MemoryStore
        store = MemoryStore(db_path=self.db_path)

        entry = run(store.store("user1", "temp fact"))
        run(store.delete(entry.id))

        results = run(store.list_all("user1"))
        self.assertEqual(len(results), 0)

    def test_session_save_and_load(self):
        from orchestra.memory import MemoryStore, SessionContext
        store = MemoryStore(db_path=self.db_path)

        session = SessionContext(session_id="s1", user_id="user1")
        session.add_turn("user", "Hello")
        session.add_turn("assistant", "Hi there")

        run(store.save_session(session))
        loaded = run(store.load_session("s1"))

        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.turns), 2)
        self.assertEqual(loaded.turns[0]["role"], "user")


class MemoryManagerTests(_BaseTest):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_memory.db"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_context_block_empty(self):
        from orchestra.memory import MemoryStore, MemoryManager
        store = MemoryStore(db_path=self.db_path)
        mgr = MemoryManager(store=store, user_id="user1")

        block = run(mgr.get_context_block())
        self.assertEqual(block, "")

    def test_get_context_block_with_memories(self):
        from orchestra.memory import MemoryStore, MemoryManager
        store = MemoryStore(db_path=self.db_path)
        mgr = MemoryManager(store=store, user_id="user1")

        run(store.store("user1", "I am building Horizon Orchestra", category="project"))

        block = run(mgr.get_context_block())
        self.assertIn("<user_memory>", block)
        self.assertIn("Horizon Orchestra", block)

    def test_register_memory_tools(self):
        from orchestra.agent_loop import ToolRegistry
        from orchestra.memory import MemoryStore, MemoryManager, register_memory_tools

        store = MemoryStore(db_path=self.db_path)
        mgr = MemoryManager(store=store, user_id="user1")
        reg = ToolRegistry()
        register_memory_tools(reg, mgr)

        self.assertIn("memory_search", reg.names)
        self.assertIn("memory_store", reg.names)

        # Test the store tool works
        result = run(reg.execute("memory_store", {"content": "I love Rust", "category": "preference"}, call_id="t1"))
        self.assertTrue(result.success)
        data = json.loads(result.result)
        self.assertTrue(data["stored"])

        # Test the search tool works
        result = run(reg.execute("memory_search", {"query": "programming languages"}, call_id="t2"))
        self.assertTrue(result.success)
        hits = json.loads(result.result)
        self.assertTrue(len(hits) > 0)


# ===========================================================================
# Swarm tests
# ===========================================================================

class SwarmTests(_BaseTest):

    def test_dag_respects_dependencies(self):
        """Tasks with depends_on should wait for dependencies."""
        from orchestra.swarm import SwarmCoordinator, SubTask
        from orchestra.router import ModelRouter
        from orchestra.agent_loop import ToolRegistry

        execution_order: list[str] = []

        async def fake_run_subtask(self_coord, task):
            from orchestra.swarm import SwarmResult
            execution_order.append(task.id)
            await asyncio.sleep(0.01)
            return SwarmResult(
                task_id=task.id, output=f"output_{task.id}",
                model_used=task.model, duration_seconds=0.01, success=True,
            )

        tasks = [
            SubTask(id="a", description="First", model="kimi-k2.5"),
            SubTask(id="b", description="Second", model="kimi-k2.5", depends_on=["a"]),
            SubTask(id="c", description="Parallel with A", model="kimi-k2.5"),
        ]

        router = ModelRouter()
        coord = SwarmCoordinator(router, ToolRegistry())

        with mock.patch.object(SwarmCoordinator, "_run_subtask", fake_run_subtask):
            results = run(coord.execute(tasks))

        # a and c should both run before b
        idx_a = execution_order.index("a")
        idx_b = execution_order.index("b")
        idx_c = execution_order.index("c")
        self.assertLess(idx_a, idx_b)
        # c is parallel with a, so it should be in the first batch
        self.assertLess(idx_c, idx_b)

        self.assertTrue(results["a"].success)
        self.assertTrue(results["b"].success)
        self.assertTrue(results["c"].success)


# ===========================================================================
# Perplexity integration tests
# ===========================================================================

class PerplexitySearchTests(_BaseTest):

    def test_search_constructs_correct_call(self):
        from orchestra.perplexity import PerplexitySearch

        captured: dict[str, Any] = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            mock_msg = types.SimpleNamespace(content="Paris is the capital.")
            mock_choice = types.SimpleNamespace(message=mock_msg)
            return types.SimpleNamespace(
                choices=[mock_choice],
                citations=["https://example.com/paris"],
                model="sonar",
                usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=20),
            )

        search = PerplexitySearch(api_key="test-key")

        with mock.patch.object(search.client.chat.completions, "create", side_effect=fake_create):
            result = run(search.search("capital of France", recency="week"))

        self.assertEqual(result.content, "Paris is the capital.")
        self.assertEqual(result.citations, ["https://example.com/paris"])
        self.assertEqual(captured["model"], "sonar")
        self.assertIn("search_recency_filter", captured.get("extra_body", {}))


class PerplexityAgentTests(_BaseTest):

    def test_multi_model_council_runs_parallel(self):
        from orchestra.perplexity import PerplexityAgent

        call_count = 0

        async def fake_run(prompt, model="default", tools=None, instructions=""):
            nonlocal call_count
            call_count += 1
            from orchestra.perplexity import AgentResponse
            return AgentResponse(text=f"Response from {model}", model=model)

        agent = PerplexityAgent(api_key="test-key")

        with mock.patch.object(agent, "run", side_effect=fake_run):
            results = run(agent.multi_model_council("test prompt", models=["m1", "m2", "m3"]))

        self.assertEqual(len(results), 3)
        self.assertEqual(call_count, 3)
        self.assertEqual(results[0].model, "m1")


# ===========================================================================
# Integration: create_default_tools
# ===========================================================================

class DefaultToolsTests(_BaseTest):

    def test_creates_all_builtin_tools(self):
        from orchestra.agent_loop import create_default_tools

        reg = create_default_tools()
        expected = {"web_search", "fetch_url", "execute_code", "file_read", "file_write", "browser_action"}
        self.assertEqual(set(reg.names), expected)

    def test_openai_format_is_valid(self):
        from orchestra.agent_loop import create_default_tools

        reg = create_default_tools()
        tools = reg.get_openai_tools()
        for tool in tools:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])


if __name__ == "__main__":
    unittest.main()
