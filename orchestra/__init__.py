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

from .router import ModelConfig, ModelRouter, DEFAULT_MODELS, GEMMA4_MODELS
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
from .arch_b import RAGPipeline, RAGConfig
from .arch_c import SwarmAgent, SwarmConfig
from .arch_d import MCPToolHub, MCPHubConfig
from .arch_e import ProductionOrchestrator, ProductionConfig

# ── Enterprise connectors (big 5 platforms) ───────────────────────────────
try:
    from .connectors.salesforce       import SalesforceConnector
    from .connectors.google_workspace  import GoogleWorkspaceConnector
    from .connectors.microsoft365      import Microsoft365Connector
    from .connectors.meta_business     import MetaBusinessConnector
    from .connectors.amazon_business   import AmazonBusinessConnector
except Exception:
    SalesforceConnector = GoogleWorkspaceConnector = Microsoft365Connector = None  # type: ignore
    MetaBusinessConnector = AmazonBusinessConnector = None  # type: ignore

# ── Multi-orchestrator teams + fleet + mesh ─────────────────────────────
try:
    from .teams import (
        OrchestraTeam, TeamConfig, ContextBus, TeamMemory, InterAgentTrust,
        OrchestraFleet, FleetConfig,
        AgentNegotiator, TaskBid, NegotiationResult,
        OrchestratorMesh, MeshNode, MeshConfig,
    )
    from .teams.pre_built_teams import (
        enterprise_connect_team, coding_team, research_team, sales_team
    )
except Exception:
    OrchestraTeam = TeamConfig = ContextBus = TeamMemory = InterAgentTrust = None  # type: ignore
    OrchestraFleet = FleetConfig = AgentNegotiator = TaskBid = NegotiationResult = None  # type: ignore
    OrchestratorMesh = MeshNode = MeshConfig = None  # type: ignore
    enterprise_connect_team = coding_team = research_team = sales_team = None  # type: ignore

# ── Security guardian (full stack) ────────────────────────────────────
try:
    from .guardian import (
        InferenceGateway, PolicyEngine,
        CapabilityLattice, AuditLedger, BeyondGuardrails,
    )
    from .guardian.code_guard import CodeGuard, CodeThreat, CodeScanResult
    from .guardian.ingestion_gate import IngestionGate, IngestionViolation, IngestionReport
    from .guardian.security_config import SecurityConfig, SECURITY_CONFIG
except Exception:
    InferenceGateway = PolicyEngine = CapabilityLattice = None  # type: ignore
    AuditLedger = BeyondGuardrails = None  # type: ignore
    CodeGuard = CodeThreat = CodeScanResult = None  # type: ignore
    IngestionGate = IngestionViolation = IngestionReport = None  # type: ignore
    SecurityConfig = SECURITY_CONFIG = None  # type: ignore

# Gemma 4 provider (lazy — only if available)
try:
    from .gemma4_provider import (
        Gemma4Provider,
        Gemma4Config,
        MultimodalInput,
        Gemma4FunctionCall,
        generate_ollama_modelfile,
        generate_vllm_command,
    )
    from .gemma4_provider import ThinkingResponse as Gemma4ThinkingResponse  # test alias
except Exception:
    Gemma4Provider = None  # type: ignore[assignment,misc]
    Gemma4Config = None  # type: ignore[assignment,misc]
    Gemma4ThinkingResponse = None  # type: ignore[assignment,misc]
    MultimodalInput = None  # type: ignore[assignment,misc]
    Gemma4FunctionCall = None  # type: ignore[assignment,misc]
    generate_ollama_modelfile = None  # type: ignore[assignment]
    generate_vllm_command = None  # type: ignore[assignment]

# Internal helpers used by tests via direct import from orchestra.arch_a
# These live in arch_a but tests import them as orchestra._thinking_block etc.
try:
    from .arch_a import _thinking_block, _model_display_name  # type: ignore[attr-defined]
except ImportError:
    def _thinking_block(text: str = "") -> str:  # type: ignore[misc]
        return f"<thinking>{text}</thinking>"
    def _model_display_name(model_id: str = "") -> str:  # type: ignore[misc]
        return model_id

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
    "RAGPipeline",
    "RAGConfig",
    "SwarmAgent",
    "SwarmConfig",
    "MCPToolHub",
    "MCPHubConfig",
    "ProductionOrchestrator",
    "ProductionConfig",
]

__version__ = "0.1.0"
