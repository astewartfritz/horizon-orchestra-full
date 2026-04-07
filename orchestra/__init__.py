"""Horizon Orchestra — Agentic AI Harness.

Built on Kimi K2.5 as the core backbone, with multi-model routing,
parallel sub-agent swarms, Perplexity API integration, and persistent
cross-session memory.

Quick start::

    from orchestra import ModelRouter, AgentLoop, create_default_tools, AgentConfig

    router = ModelRouter()
    tools  = create_default_tools(router)
    config = AgentConfig(model="kimi-k2.5")
    agent  = AgentLoop(router, tools, config)

    async for event in agent.run("Build a REST API for task management"):
        print(event)
"""

from .router import ModelConfig, ModelRouter, DEFAULT_MODELS
from .agent_loop import (
    AgentConfig,
    AgentEvent,
    AgentLoop,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolRegistry,
    ToolResult,
    ToolResultEvent,
    ThinkingEvent,
    create_default_tools,
)
from .swarm import SubTask, SwarmCoordinator, SwarmResult
from .perplexity import (
    AgentResponse,
    PerplexityAgent,
    PerplexitySearch,
    SearchResult,
)
from .memory import (
    MemoryEntry,
    MemoryManager,
    MemoryStore,
    SessionContext,
    register_memory_tools,
)
from .arch_a import MonolithicAgent, MonolithicConfig
from .arch_c import SwarmAgent, SwarmConfig
from .arch_e import ProductionOrchestrator, ProductionConfig

__all__ = [
    # router
    "ModelConfig",
    "ModelRouter",
    "DEFAULT_MODELS",
    # agent loop
    "AgentConfig",
    "AgentEvent",
    "AgentLoop",
    "FinalAnswerEvent",
    "ErrorEvent",
    "ToolCallEvent",
    "ToolRegistry",
    "ToolResult",
    "ToolResultEvent",
    "ThinkingEvent",
    "create_default_tools",
    # swarm
    "SubTask",
    "SwarmCoordinator",
    "SwarmResult",
    # perplexity
    "AgentResponse",
    "PerplexityAgent",
    "PerplexitySearch",
    "SearchResult",
    # memory
    "MemoryEntry",
    "MemoryManager",
    "MemoryStore",
    "SessionContext",
    "register_memory_tools",
    # architectures
    "MonolithicAgent",
    "MonolithicConfig",
    "SwarmAgent",
    "SwarmConfig",
    "ProductionOrchestrator",
    "ProductionConfig",
]

__version__ = "0.1.0"
