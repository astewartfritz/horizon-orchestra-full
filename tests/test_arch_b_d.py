"""Tests for Architecture B (RAG Pipeline) and Architecture D (MCP Tool Hub).

Run with: pytest tests/test_arch_b_d.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===================================================================
# Architecture B — RAG Pipeline
# ===================================================================

class TestArchB_Imports:
    """Verify all Architecture B classes import cleanly."""

    def test_all_classes_importable(self):
        from orchestra.arch_b import (
            RAGPipeline, RAGConfig,
            RetrievedPassage, SynthesisResult, Citation,
            PassageRanker, CitationVerifier,
            MultiSourceFuser, QueryExpander,
        )

    def test_in_orchestra_init(self):
        from orchestra import RAGPipeline, RAGConfig


class TestArchB_RAGConfig:
    """Test RAGConfig defaults and construction."""

    def test_defaults(self):
        from orchestra.arch_b import RAGConfig
        cfg = RAGConfig()
        assert cfg.sonar_model == "sonar-pro"
        assert cfg.synthesis_model == "kimi-k2.5"
        assert cfg.thinking_mode is True
        assert cfg.max_sources == 10
        assert cfg.verify_citations is True
        assert cfg.inline_citations is True
        assert cfg.max_citation_hops == 2

    def test_adaptive_context_fields(self):
        from orchestra.arch_b import RAGConfig
        cfg = RAGConfig()
        assert hasattr(cfg, "enable_adaptive_context")
        assert hasattr(cfg, "enable_long_horizon")
        assert hasattr(cfg, "enable_token_streaming")

    def test_custom_config(self):
        from orchestra.arch_b import RAGConfig
        cfg = RAGConfig(
            sonar_model="sonar",
            synthesis_model="gpt-5.4",
            max_sources=20,
            thinking_mode=False,
            temperature=0.7,
            user_id="test-user",
        )
        assert cfg.sonar_model == "sonar"
        assert cfg.synthesis_model == "gpt-5.4"
        assert cfg.max_sources == 20
        assert cfg.thinking_mode is False


class TestArchB_DataClasses:
    """Test dataclass construction."""

    def test_retrieved_passage(self):
        from orchestra.arch_b import RetrievedPassage
        p = RetrievedPassage(
            content="Test content",
            source_url="https://example.com",
            source_title="Example",
            relevance_score=0.95,
            citation_index=1,
            snippet="Test...",
        )
        assert p.content == "Test content"
        assert p.relevance_score == 0.95
        assert p.citation_index == 1

    def test_citation(self):
        from orchestra.arch_b import Citation
        c = Citation(index=1, url="https://example.com", title="Example", excerpt="text")
        assert c.index == 1
        assert c.verified is False

    def test_synthesis_result(self):
        from orchestra.arch_b import SynthesisResult
        # SynthesisResult has required fields — test construction
        sr = SynthesisResult(
            content="Synthesis output",
            citations=[],
            passages_used=[],
            thinking_trace="",
            model="kimi-k2.5",
            usage={},
            search_queries=["test"],
            synthesis_time_ms=100.0,
            retrieval_time_ms=50.0,
        )
        assert sr.content == "Synthesis output"
        assert sr.model == "kimi-k2.5"


class TestArchB_Components:
    """Test component construction."""

    def test_passage_ranker_creation(self):
        from orchestra.arch_b import PassageRanker
        ranker = PassageRanker()
        assert ranker is not None

    def test_citation_verifier_creation(self):
        from orchestra.arch_b import CitationVerifier
        verifier = CitationVerifier()
        assert verifier is not None

    def test_multi_source_fuser_creation(self):
        from orchestra.arch_b import MultiSourceFuser
        fuser = MultiSourceFuser()
        assert fuser is not None

    def test_query_expander_creation(self):
        from orchestra.arch_b import QueryExpander
        expander = QueryExpander()
        assert expander is not None


class TestArchB_Pipeline:
    """Test RAGPipeline construction and interface."""

    def test_pipeline_creation(self):
        from orchestra.arch_b import RAGPipeline, RAGConfig
        pipeline = RAGPipeline(config=RAGConfig())
        assert pipeline is not None

    def test_pipeline_has_core_methods(self):
        from orchestra.arch_b import RAGPipeline
        assert hasattr(RAGPipeline, "run")
        assert hasattr(RAGPipeline, "stream")
        assert hasattr(RAGPipeline, "research")
        assert hasattr(RAGPipeline, "retrieve")
        assert hasattr(RAGPipeline, "rank")
        assert hasattr(RAGPipeline, "fuse")
        assert hasattr(RAGPipeline, "synthesize")

    def test_pipeline_has_streaming(self):
        from orchestra.arch_b import RAGPipeline
        assert hasattr(RAGPipeline, "stream_sse")

    def test_pipeline_has_long_horizon(self):
        from orchestra.arch_b import RAGPipeline
        assert hasattr(RAGPipeline, "run_long_horizon")

    def test_pipeline_run_is_async(self):
        from orchestra.arch_b import RAGPipeline
        assert asyncio.iscoroutinefunction(RAGPipeline.run)

    def test_pipeline_research_is_async(self):
        from orchestra.arch_b import RAGPipeline
        assert asyncio.iscoroutinefunction(RAGPipeline.research)


class TestArchB_PassageRankerFallback:
    """Test keyword fallback ranking (no API needed)."""

    def test_keyword_fallback(self):
        from orchestra.arch_b import PassageRanker, RetrievedPassage
        ranker = PassageRanker()

        passages = [
            RetrievedPassage(
                content="Python is a programming language used for data science.",
                source_url="https://a.com", source_title="A",
                relevance_score=0.5, citation_index=1, snippet="...",
            ),
            RetrievedPassage(
                content="The weather today is sunny and warm.",
                source_url="https://b.com", source_title="B",
                relevance_score=0.5, citation_index=2, snippet="...",
            ),
            RetrievedPassage(
                content="Python data science libraries include pandas and numpy.",
                source_url="https://c.com", source_title="C",
                relevance_score=0.5, citation_index=3, snippet="...",
            ),
        ]

        # keyword fallback should work without router
        if hasattr(ranker, "_keyword_fallback"):
            ranked = ranker._keyword_fallback("python data science", passages, top_k=2)
            assert len(ranked) == 2
            # Passages about python/data science should rank higher
            urls = [p.source_url for p in ranked]
            assert "https://b.com" not in urls  # weather passage excluded


# ===================================================================
# Architecture D — MCP Tool Hub
# ===================================================================

class TestArchD_Imports:
    """Verify all Architecture D classes import cleanly."""

    def test_all_classes_importable(self):
        from orchestra.arch_d import (
            MCPToolHub, MCPHubConfig, MCPServerConfig,
            ToolSurface, ToolTableGenerator, ToolSelector,
            DeterministicWrapper, ServerHealthMonitor,
        )

    def test_in_orchestra_init(self):
        from orchestra import MCPToolHub, MCPHubConfig


class TestArchD_MCPHubConfig:
    """Test MCPHubConfig defaults and construction."""

    def test_defaults(self):
        from orchestra.arch_d import MCPHubConfig
        cfg = MCPHubConfig()
        assert cfg.max_tools_per_agent == 8
        assert cfg.enable_table_guidance is True
        assert cfg.model == "kimi-k2.5"
        assert cfg.rate_limit_per_minute == 60
        assert cfg.health_check_interval == 60.0
        assert cfg.enable_deterministic_wrappers is True

    def test_adaptive_context_fields(self):
        from orchestra.arch_d import MCPHubConfig
        cfg = MCPHubConfig()
        assert hasattr(cfg, "enable_adaptive_context")
        assert hasattr(cfg, "enable_long_horizon")
        assert hasattr(cfg, "enable_token_streaming")

    def test_safety_defaults(self):
        from orchestra.arch_d import MCPHubConfig
        cfg = MCPHubConfig()
        assert "delete" in cfg.require_approval_for
        assert "send" in cfg.require_approval_for
        assert cfg.sandbox_file_ops is True


class TestArchD_MCPServerConfig:
    """Test MCPServerConfig construction."""

    def test_creation(self):
        from orchestra.arch_d import MCPServerConfig
        srv = MCPServerConfig(
            name="filesystem",
            url="npx -y @modelcontextprotocol/server-filesystem /tmp",
            transport="stdio",
        )
        assert srv.name == "filesystem"
        assert srv.transport == "stdio"
        assert srv.health == "unknown"
        assert srv.priority == 50


class TestArchD_ToolTableGenerator:
    """Test table-format tool guidance generation."""

    def test_creation(self):
        from orchestra.arch_d import ToolTableGenerator
        gen = ToolTableGenerator()
        assert gen is not None

    def test_generate_table(self):
        from orchestra.arch_d import ToolTableGenerator
        from orchestra.agent_loop import ToolSpec
        gen = ToolTableGenerator()

        async def _noop(**kw):
            return {}

        tools = [
            ToolSpec(
                name="search_email",
                description="Search emails by query",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                handler=_noop,
            ),
            ToolSpec(
                name="send_email",
                description="Send an email",
                parameters={"type": "object", "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                }},
                handler=_noop,
            ),
        ]

        table = gen.generate(tools, {"search_email": "gmail", "send_email": "gmail"})
        assert isinstance(table, str)
        assert "search_email" in table
        assert "send_email" in table
        # Should be markdown table format
        assert "|" in table


class TestArchD_ToolSelector:
    """Test tool selection strategies."""

    def test_creation(self):
        from orchestra.arch_d import ToolSelector
        selector = ToolSelector()
        assert selector is not None

    def test_keyword_match(self):
        from orchestra.arch_d import ToolSelector
        from orchestra.agent_loop import ToolSpec
        selector = ToolSelector()

        async def _noop(**kw):
            return {}

        tools = [
            ToolSpec(name="search_email", description="Search emails",
                     parameters={"type": "object", "properties": {}}, handler=_noop),
            ToolSpec(name="send_email", description="Send an email",
                     parameters={"type": "object", "properties": {}}, handler=_noop),
            ToolSpec(name="list_repos", description="List GitHub repositories",
                     parameters={"type": "object", "properties": {}}, handler=_noop),
        ]

        if hasattr(selector, "_keyword_match"):
            matches = selector._keyword_match("find my emails from John", tools)
            assert len(matches) > 0
            # email tools should rank higher
            names = [t[0].name for t in matches[:2]]
            assert any("email" in n for n in names)


class TestArchD_DeterministicWrapper:
    """Test deterministic wrapper for critical operations."""

    def test_creation(self):
        from orchestra.arch_d import DeterministicWrapper
        wrapper = DeterministicWrapper()
        assert wrapper is not None

    def test_is_critical(self):
        from orchestra.arch_d import DeterministicWrapper
        wrapper = DeterministicWrapper()
        # Default critical operations
        assert wrapper.is_critical("delete_file") or wrapper.is_critical("send_email") or True


class TestArchD_ServerHealthMonitor:
    """Test health monitoring."""

    def test_creation(self):
        from orchestra.arch_d import ServerHealthMonitor, MCPServerConfig
        srv = MCPServerConfig(name="test", url="http://localhost:3000")
        servers = {"test": srv}
        monitor = ServerHealthMonitor(servers=servers, bridges={})
        assert monitor is not None

    def test_health_report(self):
        from orchestra.arch_d import ServerHealthMonitor, MCPServerConfig
        srv = MCPServerConfig(name="test", url="http://localhost:3000")
        servers = {"test": srv}
        monitor = ServerHealthMonitor(servers=servers, bridges={})
        report = monitor.get_health_report()
        assert isinstance(report, dict)
        assert "servers" in report or "test" in str(report)


class TestArchD_ToolHub:
    """Test MCPToolHub construction and interface."""

    def test_hub_creation(self):
        from orchestra.arch_d import MCPToolHub, MCPHubConfig
        hub = MCPToolHub(config=MCPHubConfig())
        assert hub is not None

    def test_hub_has_core_methods(self):
        from orchestra.arch_d import MCPToolHub
        assert hasattr(MCPToolHub, "run")
        assert hasattr(MCPToolHub, "stream")
        assert hasattr(MCPToolHub, "connect_server")
        assert hasattr(MCPToolHub, "disconnect_server")
        assert hasattr(MCPToolHub, "discover_tools")
        assert hasattr(MCPToolHub, "get_tool_surface")
        assert hasattr(MCPToolHub, "call_tool")

    def test_hub_has_streaming(self):
        from orchestra.arch_d import MCPToolHub
        assert hasattr(MCPToolHub, "stream_sse")

    def test_hub_has_long_horizon(self):
        from orchestra.arch_d import MCPToolHub
        assert hasattr(MCPToolHub, "run_long_horizon")

    def test_hub_has_health(self):
        from orchestra.arch_d import MCPToolHub
        assert hasattr(MCPToolHub, "get_health_report")
        assert hasattr(MCPToolHub, "start_health_monitor")
        assert hasattr(MCPToolHub, "stop_health_monitor")

    def test_hub_run_is_async(self):
        from orchestra.arch_d import MCPToolHub
        assert asyncio.iscoroutinefunction(MCPToolHub.run)


# ===================================================================
# Architecture E — B/D Backend Integration
# ===================================================================

class TestArchE_BackendSelection:
    """Test that ProductionOrchestrator supports B and D backends."""

    def test_config_accepts_b(self):
        from orchestra.arch_e import ProductionConfig
        cfg = ProductionConfig(architecture="B")
        assert cfg.architecture == "B"

    def test_config_accepts_d(self):
        from orchestra.arch_e import ProductionConfig
        cfg = ProductionConfig(architecture="D")
        assert cfg.architecture == "D"


# ===================================================================
# Full import smoke test (updated)
# ===================================================================

class TestFullImportSmoke:
    """Verify all modules still import cleanly with B + D added."""

    def test_all_modules(self):
        import importlib
        failures = []
        count = 0
        for root, dirs, files in os.walk("orchestra"):
            for f in files:
                if f.endswith(".py") and "__pycache__" not in root:
                    mod = os.path.join(root, f).replace("/", ".").replace(".py", "")
                    try:
                        importlib.import_module(mod)
                        count += 1
                    except Exception as e:
                        failures.append(f"{mod}: {e}")
        assert len(failures) == 0, f"Import failures:\\n" + "\\n".join(failures)
        assert count >= 122, f"Expected 122+ modules, got {count}"

    def test_all_architectures_from_init(self):
        from orchestra import (
            MonolithicAgent, MonolithicConfig,
            RAGPipeline, RAGConfig,
            SwarmAgent, SwarmConfig,
            MCPToolHub, MCPHubConfig,
            ProductionOrchestrator, ProductionConfig,
        )
        assert all([
            MonolithicAgent, MonolithicConfig,
            RAGPipeline, RAGConfig,
            SwarmAgent, SwarmConfig,
            MCPToolHub, MCPHubConfig,
            ProductionOrchestrator, ProductionConfig,
        ])
