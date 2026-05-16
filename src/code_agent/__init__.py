__version__ = "0.4.0"

from code_agent.agent import Agent, AgentConfig
from code_agent.tools.base import Tool, ToolResult, ToolSpec
from code_agent.reviewer import CodeReviewer
from code_agent.session import Session, SessionManager
from code_agent.orchestrator import Orchestrator, SequentialOrchestrator, ParallelOrchestrator, VotingOrchestrator
from code_agent.benchmark import Benchmark, BenchmarkTask, BenchmarkResult
from code_agent.scaffold.generator import ScaffoldGenerator
from code_agent.config import LLMConfig
from code_agent.repl import REPLSession
from code_agent.cost import CostTracker
from code_agent.vector import VectorEngine
from code_agent.analysis import CodeAnalyzer
from code_agent.output import TestGenerator
from code_agent.watcher import FileWatcher
from code_agent.plugins import PluginLoader
from code_agent.monitor import MonitorDashboard, MetricsCollector
from code_agent.prompts import PromptLibrary
from code_agent.guardrails import Guardrails
from code_agent.workflow import WorkflowEngine
from code_agent.improve import SelfImprover
from code_agent.docs import DocGenerator
from code_agent.knowledge import KnowledgeBase
from code_agent.profiles import ProfileManager, Profile
from code_agent.logbook import AgentLogger
from code_agent.notify import Notifier
from code_agent.scheduler import AgentScheduler
from code_agent.security import SecretScanner
from code_agent.telemetry import AgentTracer
from code_agent.export import SessionExporter, FullExporter
from code_agent.compress import ConversationSummarizer
from code_agent.health import HealthChecker
from code_agent.multilang import MultiLangAnalyzer
from code_agent.context import ContextManager
from code_agent.mdconfig import (
    MdConfig, MdSection,
    parse_md, parse_md_text, extract_frontmatter,
    MarkdownConfigLoader, AgentMdConventions,
    generate_claude_md, generate_agents_md, generate_prompt_md,
    generate_tool_md, generate_workflow_md, write_config,
)
from code_agent.reasoning import (
    ReasoningEngine,
    ReasoningSession,
    ModuleSaver,
    ReasoningModule,
    ErrorPattern,
    get_strategy_prompt,
)
from code_agent.fallback import FallbackChain
from code_agent.ratelimit import RateLimiter
from code_agent.pipeline import PipelineEngine
from code_agent.optimizer import PromptOptimizer
from code_agent.learner import ErrorLearner
from code_agent.templates import TemplateManager
from code_agent.quality import QualityReporter
from code_agent.api import AgentAPI
from code_agent.github import GitHubWebhookHandler
from code_agent.explain import ExplanationTracer
from code_agent.smells import SmellDetector
from code_agent.validate import ConfigValidator
from code_agent.batch import BatchProcessor
from code_agent.licenses import LicenseScanner
from code_agent.autocomplete import TaskCompleter
from code_agent.promptversion import PromptVersionManager
from code_agent.memsearch import MemorySearcher
from code_agent.runner import AgentDaemon
from code_agent.market import PluginMarket
from code_agent.estimate import CostEstimator
from code_agent.abtest import ABTestRunner
from code_agent.depupdater import DepUpdater
from code_agent.testwatcher import TestWatcher
from code_agent.multimodal import ImageProcessor
from code_agent.sessearch import SessionSearchEngine
from code_agent.selfdiag import SelfDiagnosis
from code_agent.tenants import TenantManager
from code_agent.sbox import SubprocessSandbox
from code_agent.debugger import InteractiveDebugger
from code_agent.human import HumanInputHandler
from code_agent.diffview import DiffRenderer
from code_agent.collab import CollaborationManager
from code_agent.reviews import ReviewDashboard
from code_agent.nlquery import NLQueryEngine
from code_agent.archgen import ArchitectureGenerator
from code_agent.docssite import DocsSiteBuilder
from code_agent.codesearch import CodeSearchEngine, SymbolIndex, SymbolMatch
from code_agent.apidocs import ApiDocGenerator, Endpoint, ApiSpec
from code_agent.dataviz import ChartType, ChartConfig, DataVizEngine
from code_agent.profilers import CodeProfiler, ProfileResult, Hotspot
from code_agent.loganalyze import LogEntry, LogSummary, LogAnalyzer
from code_agent.coverage import CoverageAnalyzer, CoverageData, UncoveredLine
from code_agent.boilerplate import BoilerplateGenerator, BoilerplateTemplate
from code_agent.envmgr import EnvManager, VenvInfo
from code_agent.migrate import CodeMigrator, MigrationRule, MigrationPlan
from code_agent.playground import PlaygroundServer
from code_agent.privacy import PrivacyRouter, RouteDecision, SensitivityLevel
from code_agent.openshell import OpenShellPolicy, PolicyRule, PolicyProfile, Decision
from code_agent.browser import BrowserEngine, BrowserTab, BrowserResult
from code_agent.build_orchestrator import (
    BuildProfile, BuildTask, BuildStep, BuildResult, Patch, BuildMetrics,
    BuildStatus, BuildType, Platform, PatchStatus,
    BuildProfileManager, BuildEngine, PatchManager, BuildBrain,
)
from code_agent.channels import ChannelManager, Message, ChannelType
from code_agent.voice import VoiceEngine, VoiceResult
from code_agent.selflearn import SelfLearningEngine, Insight, LearningStore
from code_agent.integrations import CalendarIntegration, EmailIntegration
from code_agent.remote import RemoteAgent, RemoteHost, RemoteResult
from code_agent.backup import BackupManager, BackupEntry, RestoreResult
from code_agent.changelog import ChangelogGenerator, ChangelogEntry, Changelog
from code_agent.shield import InjectionShield, InjectionRisk, ShieldResult
from code_agent.toolbuilder import ToolBuilder, GeneratedTool
from code_agent.ws import WebSocketServer, WSEvent
from code_agent.memory.manager import MemoryManager
from code_agent.memory.store import MemoryStore, StoredMemory, EmbeddingEngine, MemoryEntity
from code_agent.memory.buffer import MemoryBuffer, BufferEntry
from code_agent.memory.retrieval import MemoryRetrieval, RetrievalResult
from code_agent.memory.consolidation import MemoryConsolidation, ConsolidationReport
from code_agent.memory.graph import MemoryGraph, GraphNode, GraphPath
from code_agent.memory.tool import MemoryTool
from code_agent.trace.collector import TraceCollector, AgentTrace, TraceEvent, EventType
from code_agent.trace.viewer import TraceViewer
from code_agent.trace.export import TraceExporter
from code_agent.desktop import DesktopGUI
from code_agent.skills.models import Skill, Embedder, TaskSpec
from code_agent.skills.store import SkillStore
from code_agent.skills.retriever import SkillRetriever
from code_agent.skills.policy import SkillPolicy, PolicyOutput
from code_agent.skills.runtime import EpisodeRuntime
from code_agent.skills.credit import CreditSignal, CreditLedger, AdvantageTracker
from code_agent.skills.distiller import SkillDistiller
from code_agent.skills.evaluator import EvalQueue, EvalResult
from code_agent.skills.pruning import SkillPruner
from code_agent.skills.safety import SafetyFilter
from code_agent.skills.base import SkillLibrary
from code_agent.skills.manager import SkillManager
from code_agent.skills.tool import SkillTool
from code_agent.skills.v2 import SkillManagerV2, MetaPolicy, WebShopEnv, RLTrainer
from code_agent import serving

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
]
