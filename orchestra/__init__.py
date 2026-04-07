"""Horizon Orchestra — Agentic AI Harness.

Multi-model orchestration framework with Kimi K2.5, Gemma 4, and
Claude Opus 4.6 as backbone models, plus Perplexity Sonar for web
search, unified speech/audio pipelines, 5-layer security middleware,
domain-aware routing, and persistent cross-session memory.

Quick start::

    from orchestra import ModelRouter, AgentLoop, create_default_tools, AgentConfig

    router = ModelRouter()
    tools  = create_default_tools(router)
    config = AgentConfig(model="claude-opus-4.6-openrouter")
    agent  = AgentLoop(router, tools, config)

    async for event in agent.run("Build a REST API for task management"):
        print(event)
"""

# ── Router ──────────────────────────────────────────────────────────────────
from .router import ModelConfig, ModelRouter, DEFAULT_MODELS

# ── Agent Loop ──────────────────────────────────────────────────────────────
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

# ── Swarm primitives ────────────────────────────────────────────────────────
from .swarm import SubTask, SwarmCoordinator, SwarmResult

# ── Perplexity ──────────────────────────────────────────────────────────────
from .perplexity import (
    AgentResponse,
    PerplexityAgent,
    PerplexitySearch,
    SearchResult,
)

# ── Memory ──────────────────────────────────────────────────────────────────
from .memory import (
    MemoryEntry,
    MemoryManager,
    MemoryStore,
    SessionContext,
    register_memory_tools,
)

# ── Architectures ───────────────────────────────────────────────────────────
from .arch_a import MonolithicAgent, MonolithicConfig
from .arch_c import SwarmAgent, SwarmConfig
from .arch_e import ProductionOrchestrator, ProductionConfig

# ── Gemma 4 Provider ────────────────────────────────────────────────────────
from .gemma4_provider import (
    Gemma4Provider,
    Gemma4Config,
    ThinkingResponse as Gemma4ThinkingResponse,
    MultimodalInput,
    Gemma4FunctionCall,
    generate_ollama_modelfile,
    generate_vllm_command,
)

# ── Opus 4.6 Provider ──────────────────────────────────────────────────────
try:
    from .opus4_provider import (
        Opus4Provider,
        Opus4Config,
        ThinkingResponse as Opus4ThinkingResponse,
        VisionInput,
        Opus4FunctionCall,
        get_effort_config,
        estimate_cost as estimate_opus4_cost,
    )
except ImportError:
    pass  # anthropic SDK not installed

# ── Security ────────────────────────────────────────────────────────────────
try:
    from .security import (
        SecurityMiddleware,
        PermissionPolicy,
        PermissionGate,
        InputSanitizer,
        OutputMonitor,
        RateLimiter,
        SecurityAlert,
        SecurityDecision,
        strict_policy,
        standard_policy,
        permissive_policy,
        safety_critical_policy,
    )
except ImportError:
    pass

# ── Domain Router ───────────────────────────────────────────────────────────
try:
    from .domain_router import (
        DomainRouter,
        TaskClassification,
        DomainRoute,
        DOMAIN_CONFIGS,
    )
except ImportError:
    pass

# ── Speech & Audio ──────────────────────────────────────────────────────────
try:
    from .speech_provider import (
        SpeechProvider,
        STTConfig,
        TTSConfig,
        STTBackend,
        TTSBackend,
        AudioFormat,
        TranscriptionResult,
        TTSResult,
    )
    from .audio_tools import register_audio_tools
except ImportError:
    pass  # speech deps not installed

# ── Browser Connector ────────────────────────────────────────────────────────────────────────────
try:
    from .browser_connector import (
        BrowserConnector,
        BrowserSession,
        BrowserConfig,
        PageState,
    )
except ImportError:
    pass  # playwright not installed

# ── Billing ─────────────────────────────────────────────────────────────────
try:
    from .stripe_billing import (
        BillingManager,
        NullBillingManager,
        PricingTier,
        UsageType,
        Customer,
        UsageSummary,
        BillingEvent,
    )
    from .usage_tracker import (
        UsageTracker,
        NullUsageTracker,
        UsageBudget,
        UsageSnapshot,
        TIER_LIMITS,
    )
except ImportError:
    pass

# ── Tasks ────────────────────────────────────────────────────────────────────
try:
    from .tasks import (
        TaskManager,
        TaskSpec,
        TaskStore,
        Task,
        TaskStatus,
        TaskPriority,
        Schedule,
        CheckIn,
        FileSystemIPC,
    )
except ImportError:
    pass

# ── Skills ───────────────────────────────────────────────────────────────────
try:
    from .skills import (
        Skill,
        SkillMatch,
        SkillChain,
        SkillRegistry,
        SkillLoader,
        SkillActivator,
        parse_skill_md,
        match_skills,
    )
except ImportError:
    pass

# ── Model Council ────────────────────────────────────────────────────────────
try:
    from .model_council import (
        ModelCouncil,
        CouncilConfig,
        CouncilResult,
        ModelVote,
        register_council_tools,
    )
except ImportError:
    pass

# ── Citation ─────────────────────────────────────────────────────────────────
try:
    from .citation import (
        CitationTracker,
        CitationMiddleware,
        CitationEnforcer,
        GroundedResponse,
        Source,
        Citation,
        auto_ground,
    )
except ImportError:
    pass

__all__ = [
    # router
    "ModelConfig", "ModelRouter", "DEFAULT_MODELS",
    # agent loop
    "AgentConfig", "AgentEvent", "AgentLoop",
    "FinalAnswerEvent", "ErrorEvent", "ToolCallEvent",
    "ToolRegistry", "ToolResult", "ToolResultEvent", "ThinkingEvent",
    "create_default_tools",
    # swarm
    "SubTask", "SwarmCoordinator", "SwarmResult",
    # perplexity
    "AgentResponse", "PerplexityAgent", "PerplexitySearch", "SearchResult",
    # memory
    "MemoryEntry", "MemoryManager", "MemoryStore",
    "SessionContext", "register_memory_tools",
    # architectures
    "MonolithicAgent", "MonolithicConfig",
    "SwarmAgent", "SwarmConfig",
    "ProductionOrchestrator", "ProductionConfig",
    # gemma 4 provider
    "Gemma4Provider", "Gemma4Config", "Gemma4ThinkingResponse",
    "MultimodalInput", "Gemma4FunctionCall",
    "generate_ollama_modelfile", "generate_vllm_command",
    # opus 4.6 provider
    "Opus4Provider", "Opus4Config", "Opus4ThinkingResponse",
    "VisionInput", "Opus4FunctionCall",
    "get_effort_config", "estimate_opus4_cost",
    # security
    "SecurityMiddleware", "PermissionPolicy", "PermissionGate",
    "InputSanitizer", "OutputMonitor", "RateLimiter",
    "SecurityAlert", "SecurityDecision",
    "strict_policy", "standard_policy", "permissive_policy", "safety_critical_policy",
    # domain router
    "DomainRouter", "TaskClassification", "DomainRoute", "DOMAIN_CONFIGS",
    # speech / audio
    "SpeechProvider", "STTConfig", "TTSConfig",
    "STTBackend", "TTSBackend", "AudioFormat",
    "TranscriptionResult", "TTSResult", "register_audio_tools",
    # browser connector
    "BrowserConnector", "BrowserSession", "BrowserConfig", "PageState",
    # billing
    "BillingManager", "NullBillingManager", "PricingTier", "UsageType",
    "Customer", "UsageSummary", "BillingEvent",
    "UsageTracker", "NullUsageTracker", "UsageBudget", "UsageSnapshot", "TIER_LIMITS",
    # tasks
    "TaskManager", "TaskSpec", "TaskStore", "Task",
    "TaskStatus", "TaskPriority", "Schedule", "CheckIn", "FileSystemIPC",
    # skills
    "Skill", "SkillMatch", "SkillChain", "SkillRegistry", "SkillLoader",
    "SkillActivator", "parse_skill_md", "match_skills",
    # model council
    "ModelCouncil", "CouncilConfig", "CouncilResult", "ModelVote",
    "register_council_tools",
    # citation
    "CitationTracker", "CitationMiddleware", "CitationEnforcer",
    "GroundedResponse", "Source", "Citation", "auto_ground",
]

__version__ = "0.3.0"
