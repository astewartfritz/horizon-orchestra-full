from code_agent.tools.base import Tool, ToolResult, ToolSpec
from code_agent.tools.file_ops import ReadTool, WriteTool, EditTool, GlobTool
from code_agent.tools.bash import BashTool
from code_agent.tools.search import GrepTool
from code_agent.tools.web import WebFetchTool, WebSearchTool
from code_agent.tools.git_ops import GitTool
from code_agent.tools.agent_tools import TaskTool
from code_agent.tools.diff_ops import DiffTool, PatchTool, ApplyEditTool
from code_agent.vector.indexer import IndexerTool
from code_agent.analysis.tool import AnalyzeTool
from code_agent.output.testgen import TestGenTool
from code_agent.watcher.tool import WatchTool
from code_agent.sandbox.docker import DockerSandbox
from code_agent.scaffold.generator import ScaffoldGenerator
__all__ = [
    "Tool", "ToolResult", "ToolSpec",
    "ReadTool", "WriteTool", "EditTool", "GlobTool",
    "BashTool",
    "GrepTool",
    "WebFetchTool", "WebSearchTool",
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
        from code_agent.sandbox.tool import SandboxExecuteTool
        extra.append(SandboxExecuteTool)
    except ImportError:
        pass
    try:
        from code_agent.scaffold.rust import RustScaffold
        from code_agent.scaffold.typescript import TypeScriptScaffold
        from code_agent.scaffold.mojo import MojoScaffold
        extra.extend([RustScaffold, TypeScriptScaffold, MojoScaffold])
    except ImportError:
        pass
    try:
        from code_agent.browser.tool import BrowserTool
        extra.append(BrowserTool)
    except ImportError:
        pass
    try:
        from code_agent.improve.tool import ImproveTool
        from code_agent.workflow.tool import WorkflowTool
        from code_agent.docs.generator import DocGenTool
        from code_agent.visualize.graph import GraphVizTool
        extra = [ImproveTool, WorkflowTool, DocGenTool, GraphVizTool]
    except ImportError:
        pass

    try:
        from code_agent.knowledge.tool import KnowledgeTool
        extra.append(KnowledgeTool)
    except ImportError:
        pass

    try:
        from code_agent.data.api_tool import ApiTool
        from code_agent.data.sql_tool import SqlTool
        extra.extend([ApiTool, SqlTool])
    except ImportError:
        pass

    try:
        from code_agent.nb.tool import NbTool
        extra.append(NbTool)
    except ImportError:
        pass

    try:
        from code_agent.swarm.tool import SwarmTool
        extra.append(SwarmTool)
    except ImportError:
        pass

    try:
        from code_agent.agentic.review import ReviewTool
        extra.append(ReviewTool)
    except ImportError:
        pass
    try:
        from code_agent.transform.tool import TransformTool
        extra.append(TransformTool)
    except ImportError:
        pass

    try:
        from code_agent.security.tool import SecurityAuditTool
        extra.append(SecurityAuditTool)
    except ImportError:
        pass

    try:
        from code_agent.multilang.analyzer import MultiLangTool
        extra.append(MultiLangTool)
    except ImportError:
        pass

    return CORE_TOOLS + extra
