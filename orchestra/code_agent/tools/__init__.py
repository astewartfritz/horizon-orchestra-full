from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.tools.file_ops import ReadTool, WriteTool, EditTool, GlobTool
from orchestra.code_agent.tools.bash import BashTool
from orchestra.code_agent.tools.search import GrepTool
from orchestra.code_agent.tools.web import WebFetchTool, WebSearchTool
from orchestra.code_agent.tools.git_ops import GitTool
from orchestra.code_agent.tools.agent_tools import TaskTool
from orchestra.code_agent.tools.diff_ops import DiffTool, PatchTool, ApplyEditTool
from orchestra.code_agent.tools.weather import WeatherTool
from orchestra.code_agent.tools.news import NewsTool
from orchestra.code_agent.tools.realtime import CryptoTool, CurrencyTool, WikipediaTool, GitHubSearchTool, NASATool
from orchestra.code_agent.tools.science import SemanticScholarTool, PubMedTool
from orchestra.code_agent.vector.indexer import IndexerTool
from orchestra.code_agent.analysis.tool import AnalyzeTool
from orchestra.code_agent.output.testgen import TestGenTool
from orchestra.code_agent.watcher.tool import WatchTool
from orchestra.code_agent.sandbox.docker import DockerSandbox
from orchestra.code_agent.scaffold.generator import ScaffoldGenerator
__all__ = [
    "Tool", "ToolResult", "ToolSpec",
    "ReadTool", "WriteTool", "EditTool", "GlobTool",
    "BashTool",
    "GrepTool",
    "WebFetchTool", "WebSearchTool",
    "WeatherTool", "NewsTool",
    "CryptoTool", "CurrencyTool", "WikipediaTool", "GitHubSearchTool", "NASATool",
    "SemanticScholarTool", "PubMedTool",
    "GitTool",
    "TaskTool",
    "DiffTool", "PatchTool", "ApplyEditTool",
    "IndexerTool",
    "AnalyzeTool",
    "TestGenTool",
    "WatchTool",
    "DockerSandbox",
    "ScaffoldGenerator",
]

CORE_TOOLS: list[type[Tool]] = [
    ReadTool,
    WriteTool,
    EditTool,
    GlobTool,
    BashTool,
    GrepTool,
    WebFetchTool,
    WebSearchTool,
    WeatherTool,
    NewsTool,
    CryptoTool,
    SemanticScholarTool,
    PubMedTool,
    CurrencyTool,
    WikipediaTool,
    GitHubSearchTool,
    NASATool,
    GitTool,
    TaskTool,
    DiffTool,
    PatchTool,
    ApplyEditTool,
    IndexerTool,
    AnalyzeTool,
    TestGenTool,
    WatchTool,
    DockerSandbox,
    ScaffoldGenerator,
]


def get_all_tools() -> list[type[Tool]]:
    extra = []
    try:
        from orchestra.code_agent.sandbox.tool import SandboxExecuteTool
        extra.append(SandboxExecuteTool)
    except ImportError:
        pass
    try:
        from orchestra.code_agent.scaffold.rust import RustScaffold
        from orchestra.code_agent.scaffold.typescript import TypeScriptScaffold
        from orchestra.code_agent.scaffold.mojo import MojoScaffold
        extra.extend([RustScaffold, TypeScriptScaffold, MojoScaffold])
    except ImportError:
        pass
    try:
        from orchestra.code_agent.browser.tool import BrowserTool
        extra.append(BrowserTool)
    except ImportError:
        pass
    try:
        from orchestra.code_agent.improve.tool import ImproveTool
        from orchestra.code_agent.workflow.tool import WorkflowTool
        from orchestra.code_agent.docs.generator import DocGenTool
        from orchestra.code_agent.visualize.graph import GraphVizTool
        extra.extend([ImproveTool, WorkflowTool, DocGenTool, GraphVizTool])
    except ImportError:
        pass

    try:
        from orchestra.code_agent.knowledge.tool import KnowledgeTool
        extra.append(KnowledgeTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.data.api_tool import ApiTool
        from orchestra.code_agent.data.sql_tool import SqlTool
        extra.extend([ApiTool, SqlTool])
    except ImportError:
        pass

    try:
        from orchestra.code_agent.nb.tool import NbTool
        extra.append(NbTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.swarm.tool import SwarmTool
        extra.append(SwarmTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.agentic.review import ReviewTool
        extra.append(ReviewTool)
    except ImportError:
        pass
    try:
        from orchestra.code_agent.transform.tool import TransformTool
        extra.append(TransformTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.security.tool import SecurityAuditTool
        extra.append(SecurityAuditTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.multilang.analyzer import MultiLangTool
        extra.append(MultiLangTool)
    except ImportError:
        pass

    try:
        from orchestra.code_agent.tools.terraform import TERRAFORM_TOOLS
        # Terraform tools use the function-dict schema rather than the Tool class
        # pattern; they are registered separately by callers that support it.
        # Here we just ensure the module is importable.
        _ = TERRAFORM_TOOLS
    except ImportError:
        pass

    return CORE_TOOLS + extra
