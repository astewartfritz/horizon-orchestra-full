"""Tests for Architectures A, C, and E.

All tests run offline — every API call is mocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from orchestra.agent_loop import FinalAnswerEvent, ToolCallEvent


def run(coro):
    return asyncio.run(coro)


def _mock_chat_response(content="Done.", tool_calls=None):
    """Create a mock chat completion response."""
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = types.SimpleNamespace(message=msg)
    return types.SimpleNamespace(choices=[choice])


# ===========================================================================
# Architecture A tests
# ===========================================================================

@mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True)
class ArchitectureATests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_db = os.path.join(self.tmpdir, "mem.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_monolithic_agent_creates_with_memory(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        config = MonolithicConfig(
            model="kimi-k2.5", user_id="test", memory_db=self.mem_db,
        )
        agent = MonolithicAgent(config=config)

        # Should have memory tools registered
        self.assertIn("memory_search", agent.tools.names)
        self.assertIn("memory_store", agent.tools.names)
        # Plus standard tools
        self.assertIn("web_search", agent.tools.names)
        self.assertIn("execute_code", agent.tools.names)

    def test_monolithic_agent_stats(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        config = MonolithicConfig(
            model="kimi-k2.5", user_id="test", memory_db=self.mem_db,
        )
        agent = MonolithicAgent(config=config)
        stats = agent.stats
        self.assertEqual(stats["architecture"], "A")
        self.assertEqual(stats["model"], "kimi-k2.5")

    def test_monolithic_agent_run(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        from orchestra.router import ModelRouter

        config = MonolithicConfig(
            model="kimi-k2.5", user_id="test", memory_db=self.mem_db,
            auto_extract_memory=False,
        )
        router = ModelRouter()
        agent = MonolithicAgent(config=config, router=router)

        # Mock the chat completion
        client, _ = router.get_client("kimi-k2.5")
        async def fake_create(**kwargs):
            return _mock_chat_response("Architecture A result.")
        with mock.patch.object(client.chat.completions, "create", side_effect=fake_create):
            result = run(agent.run("Test task"))

        self.assertIn("Architecture A result", result)

    def test_monolithic_agent_recall_and_remember(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        config = MonolithicConfig(
            model="kimi-k2.5", user_id="test", memory_db=self.mem_db,
        )
        agent = MonolithicAgent(config=config)

        # Store a memory
        entry_id = run(agent.remember("I am building Horizon Orchestra", category="project"))
        self.assertTrue(entry_id)

        # Recall it
        results = run(agent.recall("What am I building?"))
        self.assertTrue(len(results) > 0)
        self.assertIn("Horizon", results[0]["content"])


# ===========================================================================
# Architecture C tests
# ===========================================================================

@mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True)
class ArchitectureCTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_db = os.path.join(self.tmpdir, "mem.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_swarm_agent_has_swarm_tools(self):
        from orchestra.arch_c import SwarmAgent, SwarmConfig
        config = SwarmConfig(
            user_id="test", memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
        )
        agent = SwarmAgent(config=config)
        # Swarm tools are registered during stream(), not init.
        # But we can check the stats structure.
        stats = agent.stats
        self.assertEqual(stats["architecture"], "C")
        self.assertEqual(stats["agents_spawned"], 0)

    def test_swarm_agent_run(self):
        from orchestra.arch_c import SwarmAgent, SwarmConfig
        from orchestra.router import ModelRouter

        config = SwarmConfig(
            coordinator_model="kimi-k2.5", user_id="test",
            memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
            auto_extract_memory=False,
        )
        router = ModelRouter()
        agent = SwarmAgent(config=config, router=router)

        client, _ = router.get_client("kimi-k2.5")
        async def fake_create(**kwargs):
            return _mock_chat_response("Swarm result — all agents merged.")
        with mock.patch.object(client.chat.completions, "create", side_effect=fake_create):
            result = run(agent.run("Multi-step research task"))

        self.assertIn("Swarm result", result)


# ===========================================================================
# Architecture E tests
# ===========================================================================

@mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True)
class ArchitectureETests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_db = os.path.join(self.tmpdir, "mem.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_production_orchestrator_creates(self):
        from orchestra.arch_e import ProductionOrchestrator, ProductionConfig
        config = ProductionConfig(
            architecture="A", model="kimi-k2.5", user_id="test",
            memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
        )
        orch = ProductionOrchestrator(config=config)
        stats = orch.stats
        self.assertIn("architecture", stats)

    def test_production_orchestrator_arch_c(self):
        from orchestra.arch_e import ProductionOrchestrator, ProductionConfig
        config = ProductionConfig(
            architecture="C", model="kimi-k2.5", user_id="test",
            memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
        )
        orch = ProductionOrchestrator(config=config)
        self.assertIn("E (C)", orch.stats["architecture_mode"])

    def test_connector_registry(self):
        from orchestra.connectors import ConnectorRegistry
        registry = ConnectorRegistry.default()
        connectors = registry.list_connectors()
        names = {c["name"] for c in connectors}
        self.assertIn("gmail", names)
        self.assertIn("slack", names)
        self.assertIn("github", names)

    def test_connector_registry_register_tools(self):
        from orchestra.connectors import ConnectorRegistry, GitHubConnector
        from orchestra.agent_loop import ToolRegistry

        registry = ConnectorRegistry()
        gh = GitHubConnector()
        # Manually "connect" the connector by setting token directly
        gh._token = "fake-token"
        registry.register(gh)

        tool_reg = ToolRegistry()
        registry.register_tools(tool_reg)
        self.assertIn("github_create_issue", tool_reg.names)
        self.assertIn("github_search_code", tool_reg.names)

    def test_task_queue(self):
        from orchestra.arch_e import TaskQueue

        queue = TaskQueue(max_concurrent=5)

        # Submit with no orchestrator — should complete with placeholder
        job_id = run(queue.submit("Test task", user_id="test"))
        self.assertTrue(job_id)

        # Give it a moment to execute
        run(asyncio.sleep(0.1))

        job = queue.get(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "complete")

    def test_generate_docker_compose(self):
        from orchestra.arch_e import generate_docker_compose

        output_dir = os.path.join(self.tmpdir, "docker")
        files = generate_docker_compose(output_dir)
        self.assertIn("docker-compose.yml", files)
        self.assertIn("Dockerfile", files)
        self.assertIn(".env.example", files)

        # Verify files exist and have content
        for name, path in files.items():
            self.assertTrue(Path(path).exists())
            self.assertTrue(Path(path).stat().st_size > 0)

    def test_production_orchestrator_run(self):
        from orchestra.arch_e import ProductionOrchestrator, ProductionConfig
        from orchestra.router import ModelRouter

        config = ProductionConfig(
            architecture="A", model="kimi-k2.5", user_id="test",
            memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
        )
        router = ModelRouter()
        orch = ProductionOrchestrator(config=config, router=router)

        client, _ = router.get_client("kimi-k2.5")
        async def fake_create(**kwargs):
            return _mock_chat_response("Production result.")
        with mock.patch.object(client.chat.completions, "create", side_effect=fake_create):
            result = run(orch.run("Test production task"))

        self.assertIn("Production result", result)


# ===========================================================================
# Cross-architecture memory persistence test
# ===========================================================================

@mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=True)
class MemoryPersistenceTests(unittest.TestCase):
    """Verify memory persists across Architecture A and C instances."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_db = os.path.join(self.tmpdir, "shared_mem.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_memory_shared_across_architectures(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        from orchestra.arch_c import SwarmAgent, SwarmConfig

        # Store memory via Architecture A
        config_a = MonolithicConfig(
            user_id="ashton", memory_db=self.mem_db,
        )
        agent_a = MonolithicAgent(config=config_a)
        run(agent_a.remember("I am building Horizon Orchestra", category="project"))

        # Retrieve from a new Architecture C instance (same DB)
        config_c = SwarmConfig(
            user_id="ashton", memory_db=self.mem_db,
            workspace_dir=os.path.join(self.tmpdir, "ws"),
        )
        agent_c = SwarmAgent(config=config_c)
        results = await_search(agent_c.memory_store, "ashton", "Horizon")
        self.assertTrue(len(results) > 0)
        self.assertIn("Horizon", results[0].content)


def await_search(store, user_id, query):
    return run(store.search(user_id, query))


if __name__ == "__main__":
    unittest.main()
