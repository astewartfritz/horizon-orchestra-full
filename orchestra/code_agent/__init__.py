__version__ = "0.4.0"

from orchestra.code_agent.agent import Agent, AgentConfig
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.reviewer import CodeReviewer
from orchestra.code_agent.session import Session, SessionManager
from orchestra.code_agent.orchestrator import Orchestrator, SequentialOrchestrator, ParallelOrchestrator, VotingOrchestrator
from orchestra.code_agent.benchmark import Benchmark, BenchmarkTask, BenchmarkResult
from orchestra.code_agent.scaffold.generator import ScaffoldGenerator
from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.repl import REPLSession
from orchestra.code_agent.cost import CostTracker
from orchestra.code_agent.vector import VectorEngine
from orchestra.code_agent.analysis import CodeAnalyzer
from orchestra.code_agent.output import TestGenerator
from orchestra.code_agent.watcher import FileWatcher
from orchestra.code_agent.plugins import PluginLoader
from orchestra.code_agent.monitor import MonitorDashboard, MetricsCollector
from orchestra.code_agent.prompts import PromptLibrary
from orchestra.code_agent.guardrails import Guardrails
from orchestra.code_agent.workflow import WorkflowEngine
from orchestra.code_agent.improve import SelfImprover
from orchestra.code_agent.docs import DocGenerator
from orchestra.code_agent.knowledge import KnowledgeBase
from orchestra.code_agent.profiles import ProfileManager, Profile
from orchestra.code_agent.logbook import AgentLogger
from orchestra.code_agent.notify import Notifier
from orchestra.code_agent.scheduler import AgentScheduler
from orchestra.code_agent.security import SecretScanner
from orchestra.code_agent.telemetry import AgentTracer
from orchestra.code_agent.export import SessionExporter, FullExporter
from orchestra.code_agent.compress import ConversationSummarizer
from orchestra.code_agent.health import HealthChecker
from orchestra.code_agent.multilang import MultiLangAnalyzer
from orchestra.code_agent.context import ContextManager
from orchestra.code_agent.mdconfig import (
    MdConfig, MdSection,
    parse_md, parse_md_text, extract_frontmatter,
    MarkdownConfigLoader, AgentMdConventions,
    generate_claude_md, generate_agents_md, generate_prompt_md,
    generate_tool_md, generate_workflow_md, write_config,
)
from orchestra.code_agent.reasoning import (
    ReasoningEngine,
    ReasoningSession,
    ModuleSaver,
    ReasoningModule,
    ErrorPattern,
    get_strategy_prompt,
)
from orchestra.code_agent.fallback import FallbackChain
from orchestra.code_agent.ratelimit import RateLimiter
from orchestra.code_agent.pipeline import PipelineEngine
from orchestra.code_agent.optimizer import PromptOptimizer
from orchestra.code_agent.learner import ErrorLearner
from orchestra.code_agent.templates import TemplateManager
from orchestra.code_agent.quality import QualityReporter
from orchestra.code_agent.api import AgentAPI
from orchestra.code_agent.github import GitHubWebhookHandler
from orchestra.code_agent.explain import ExplanationTracer
from orchestra.code_agent.smells import SmellDetector
from orchestra.code_agent.validate import ConfigValidator
from orchestra.code_agent.batch import BatchProcessor
from orchestra.code_agent.licenses import LicenseScanner
from orchestra.code_agent.autocomplete import TaskCompleter
from orchestra.code_agent.promptversion import PromptVersionManager
from orchestra.code_agent.memsearch import MemorySearcher
from orchestra.code_agent.runner import AgentDaemon
from orchestra.code_agent.market import PluginMarket
from orchestra.code_agent.estimate import CostEstimator
from orchestra.code_agent.abtest import ABTestRunner
from orchestra.code_agent.depupdater import DepUpdater
from orchestra.code_agent.testwatcher import TestWatcher
from orchestra.code_agent.multimodal import ImageProcessor
from orchestra.code_agent.sessearch import SessionSearchEngine
from orchestra.code_agent.selfdiag import SelfDiagnosis
from orchestra.code_agent.tenants import TenantManager
from orchestra.code_agent.sbox import SubprocessSandbox
from orchestra.code_agent.debugger import InteractiveDebugger
from orchestra.code_agent.human import HumanInputHandler
from orchestra.code_agent.diffview import DiffRenderer
from orchestra.code_agent.collab import CollaborationManager
from orchestra.code_agent.reviews import ReviewDashboard
from orchestra.code_agent.nlquery import NLQueryEngine
from orchestra.code_agent.archgen import ArchitectureGenerator
from orchestra.code_agent.docssite import DocsSiteBuilder
from orchestra.code_agent.codesearch import CodeSearchEngine, SymbolIndex, SymbolMatch
from orchestra.code_agent.apidocs import ApiDocGenerator, Endpoint, ApiSpec
from orchestra.code_agent.dataviz import ChartType, ChartConfig, DataVizEngine
from orchestra.code_agent.profilers import CodeProfiler, ProfileResult, Hotspot
from orchestra.code_agent.loganalyze import LogEntry, LogSummary, LogAnalyzer
from orchestra.code_agent.coverage import CoverageAnalyzer, CoverageData, UncoveredLine
from orchestra.code_agent.boilerplate import BoilerplateGenerator, BoilerplateTemplate
from orchestra.code_agent.envmgr import EnvManager, VenvInfo
from orchestra.code_agent.migrate import CodeMigrator, MigrationRule, MigrationPlan
from orchestra.code_agent.playground import PlaygroundServer
from orchestra.code_agent.privacy import PrivacyRouter, RouteDecision, SensitivityLevel
from orchestra.code_agent.openshell import OpenShellPolicy, PolicyRule, PolicyProfile, Decision
from orchestra.code_agent.browser import BrowserEngine, BrowserTab, BrowserResult
from orchestra.code_agent.build_orchestrator import (
    BuildProfile, BuildTask, BuildStep, BuildResult, Patch, BuildMetrics,
    BuildStatus, BuildType, Platform, PatchStatus,
    BuildProfileManager, BuildEngine, PatchManager, BuildBrain,
)
from orchestra.code_agent.channels import ChannelManager, Message, ChannelType
from orchestra.code_agent.voice import VoiceEngine, VoiceResult
from orchestra.code_agent.selflearn import SelfLearningEngine, Insight, LearningStore
from orchestra.code_agent.integrations import CalendarIntegration, EmailIntegration
from orchestra.code_agent.remote import RemoteAgent, RemoteHost, RemoteResult
from orchestra.code_agent.backup import BackupManager, BackupEntry, RestoreResult
from orchestra.code_agent.changelog import ChangelogGenerator, ChangelogEntry, Changelog
from orchestra.code_agent.shield import InjectionShield, InjectionRisk, ShieldResult
from orchestra.code_agent.toolbuilder import ToolBuilder, GeneratedTool
from orchestra.code_agent.ws import WebSocketServer, WSEvent
from orchestra.code_agent.memory.manager import MemoryManager
from orchestra.code_agent.memory.store import MemoryStore, StoredMemory, EmbeddingEngine, MemoryEntity
from orchestra.code_agent.memory.buffer import MemoryBuffer, BufferEntry
from orchestra.code_agent.memory.retrieval import MemoryRetrieval, RetrievalResult
from orchestra.code_agent.memory.consolidation import MemoryConsolidation, ConsolidationReport
from orchestra.code_agent.memory.graph import MemoryGraph, GraphNode, GraphPath
from orchestra.code_agent.memory.tool import MemoryTool
from orchestra.code_agent.trace.collector import TraceCollector, AgentTrace, TraceEvent, EventType
from orchestra.code_agent.trace.viewer import TraceViewer
from orchestra.code_agent.trace.export import TraceExporter
from orchestra.code_agent.desktop import DesktopGUI
from orchestra.code_agent.skills.models import Skill, Embedder, TaskSpec
from orchestra.code_agent.skills.store import SkillStore
from orchestra.code_agent.skills.retriever import SkillRetriever
from orchestra.code_agent.skills.policy import SkillPolicy, PolicyOutput
from orchestra.code_agent.skills.runtime import EpisodeRuntime
from orchestra.code_agent.skills.credit import CreditSignal, CreditLedger, AdvantageTracker
from orchestra.code_agent.skills.distiller import SkillDistiller
from orchestra.code_agent.skills.evaluator import EvalQueue, EvalResult
from orchestra.code_agent.skills.pruning import SkillPruner
from orchestra.code_agent.skills.safety import SafetyFilter
from orchestra.code_agent.skills.base import SkillLibrary
from orchestra.code_agent.skills.manager import SkillManager
from orchestra.code_agent.skills.tool import SkillTool
from orchestra.code_agent.skills.v2 import SkillManagerV2, MetaPolicy, WebShopEnv, RLTrainer
from orchestra.code_agent.agentmesh import (
    AgentRegistry, AgentInfo, AgentType, AgentStatus,
    AgentNode, MeshNetwork, MeshRouter, MeshMessage, MessageType,
)
from orchestra.code_agent.teams import (
    TeamFactory, TeamFormationResult, TeamFormationStrategy,
    AgentTeam, TeamLeader, TeamResult, TeamStatus,
    SwarmCoordinator, SwarmResult,
)
from orchestra.code_agent.workflow_v2 import (
    DAGEngine, WorkflowManager, WorkflowInstance,
    DAGWorkflow, BaseStep, AgentStep, ToolStep, TransformStep,
    ParallelStep, ConditionStep, SwitchStep, LoopStep,
    HumanHandoffStep, SubWorkflowStep,
    DAGResult, WorkflowContext, StepStatus, WorkflowStatus,
    parse_workflow, parse_workflow_json, parse_workflow_yaml, workflow_to_dict,
)
from orchestra.code_agent import serving

__all__ = [
    "Agent", "AgentConfig", "LLMConfig",
    "Tool", "ToolResult", "ToolSpec",
    "CodeReviewer",
    "Session", "SessionManager",
    "Orchestrator", "SequentialOrchestrator", "ParallelOrchestrator", "VotingOrchestrator",
    "Benchmark", "BenchmarkTask", "BenchmarkResult",
    "ScaffoldGenerator",
    "REPLSession",
    "CostTracker",
    "VectorEngine",
    "CodeAnalyzer",
    "TestGenerator",
    "FileWatcher",
    "PluginLoader",
    "MonitorDashboard", "MetricsCollector",
    "PromptLibrary",
    "Guardrails",
    "WorkflowEngine",
    "SelfImprover",
    "DocGenerator",
    "KnowledgeBase",
    "ProfileManager", "Profile",
    "AgentLogger",
    "Notifier",
    "AgentScheduler",
    "SecretScanner",
    "AgentTracer",
    "SessionExporter", "FullExporter",
    "ConversationSummarizer",
    "HealthChecker",
    "MultiLangAnalyzer",
    "ContextManager",
    "MdConfig", "MdSection", "parse_md", "parse_md_text", "extract_frontmatter",
    "MarkdownConfigLoader", "AgentMdConventions",
    "generate_claude_md", "generate_agents_md", "generate_prompt_md",
    "generate_tool_md", "generate_workflow_md", "write_config",
    "ReasoningEngine", "ReasoningSession", "ModuleSaver", "ReasoningModule", "ErrorPattern", "get_strategy_prompt",
    "FallbackChain",
    "RateLimiter",
    "PipelineEngine",
    "PromptOptimizer",
    "ErrorLearner",
    "TemplateManager",
    "QualityReporter",
    "AgentAPI",
    "GitHubWebhookHandler",
    "ExplanationTracer",
    "SmellDetector",
    "ConfigValidator",
    "BatchProcessor",
    "LicenseScanner",
    "TaskCompleter",
    "PromptVersionManager",
    "MemorySearcher",
    "AgentDaemon",
    "PluginMarket",
    "CostEstimator",
    "ABTestRunner",
    "DepUpdater",
    "TestWatcher",
    "ImageProcessor",
    "SessionSearchEngine",
    "SelfDiagnosis",
    "TenantManager",
    "SubprocessSandbox",
    "InteractiveDebugger",
    "HumanInputHandler",
    "DiffRenderer",
    "CollaborationManager",
    "ReviewDashboard",
    "NLQueryEngine",
    "ArchitectureGenerator",
    "DocsSiteBuilder",
    "CodeSearchEngine", "SymbolIndex", "SymbolMatch",
    "ApiDocGenerator", "Endpoint", "ApiSpec",
    "ChartType", "ChartConfig", "DataVizEngine",
    "CodeProfiler", "ProfileResult", "Hotspot",
    "LogEntry", "LogSummary", "LogAnalyzer",
    "CoverageAnalyzer", "CoverageData", "UncoveredLine",
    "BoilerplateGenerator", "BoilerplateTemplate",
    "EnvManager", "VenvInfo",
    "CodeMigrator", "MigrationRule", "MigrationPlan",
    "PlaygroundServer",
    "PrivacyRouter", "RouteDecision", "SensitivityLevel",
    "OpenShellPolicy", "PolicyRule", "PolicyProfile", "Decision",
    "BrowserEngine", "BrowserTab", "BrowserResult",
    "ChannelManager", "Message", "ChannelType",
    "VoiceEngine", "VoiceResult",
    "SelfLearningEngine", "Insight", "LearningStore",
    "CalendarIntegration", "EmailIntegration",
    "RemoteAgent", "RemoteHost", "RemoteResult",
    "BackupManager", "BackupEntry", "RestoreResult",
    "ChangelogGenerator", "ChangelogEntry", "Changelog",
    "InjectionShield", "InjectionRisk", "ShieldResult",
    "ToolBuilder", "GeneratedTool",
    "WebSocketServer", "WSEvent",
    "DesktopGUI",
    "Skill", "SkillStore", "SkillLibrary", "SkillManager", "CreditSignal", "CreditLedger", "AdvantageTracker", "Embedder", "SkillTool", "TaskSpec",
    "SkillRetriever", "SkillPolicy", "PolicyOutput", "EpisodeRuntime", "SkillDistiller", "EvalQueue", "EvalResult", "SkillPruner", "SafetyFilter",
    "SkillManagerV2", "MetaPolicy", "WebShopEnv", "RLTrainer",
    "MemoryManager", "MemoryStore", "StoredMemory", "EmbeddingEngine", "MemoryEntity",
    "MemoryBuffer", "BufferEntry",
    "MemoryRetrieval", "RetrievalResult",
    "MemoryConsolidation", "ConsolidationReport",
    "MemoryGraph", "GraphNode", "GraphPath",
    "MemoryTool",
    "TraceCollector", "AgentTrace", "TraceEvent", "EventType",
    "TraceViewer",
    "TraceExporter",
    "serving",
    "BuildProfile", "BuildTask", "BuildStep", "BuildResult", "Patch", "BuildMetrics",
    "BuildStatus", "BuildType", "Platform", "PatchStatus",
    "BuildProfileManager", "BuildEngine", "PatchManager", "BuildBrain",
    "DAGEngine", "WorkflowManager", "WorkflowInstance",
    "DAGWorkflow", "BaseStep", "AgentStep", "ToolStep", "TransformStep",
    "ParallelStep", "ConditionStep", "SwitchStep", "LoopStep",
    "HumanHandoffStep", "SubWorkflowStep",
    "DAGResult", "WorkflowContext", "StepStatus", "WorkflowStatus",
    "parse_workflow", "parse_workflow_json", "parse_workflow_yaml", "workflow_to_dict",
    "AgentRegistry", "AgentInfo", "AgentType", "AgentStatus",
    "AgentNode", "MeshNetwork", "MeshRouter", "MeshMessage", "MessageType",
    "TeamFactory", "TeamFormationResult", "TeamFormationStrategy",
    "AgentTeam", "TeamLeader", "TeamResult", "TeamStatus",
    "SwarmCoordinator", "SwarmResult",
]
