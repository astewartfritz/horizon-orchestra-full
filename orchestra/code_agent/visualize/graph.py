from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.analysis.parser import CodeAnalyzer
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


def dep_graph_to_mermaid(graph: dict[str, list[str]]) -> str:
    lines = ["graph TD;"]
    for source, targets in graph.items():
        src_label = Path(source).stem
        for target in targets[:5]:
            tgt_label = target.split(".")[-1]
            lines.append(f'    {src_label}["{src_label}"] --> {tgt_label}["{tgt_label}"];')
    return "\n".join(lines)


def code_map(files: list[str], root_dir: str = ".") -> str:
    root = Path(root_dir)
    analyzer = CodeAnalyzer()
    lines = ["# Code Map\n"]
    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        analysis = analyzer.analyze_file(str(p))
        rel = p.relative_to(root) if p.is_absolute() else p
        lines.append(f"## {rel}")
        lines.append(f"- Lines: {analysis.lines_of_code}")
        if analysis.imports:
            lines.append(f"- Imports: {', '.join(i.module for i in analysis.imports[:10])}")
        if analysis.functions:
            lines.append(f"- Functions: {', '.join(fn['name'] for fn in analysis.functions[:10])}")
        if analysis.classes:
            lines.append(f"- Classes: {', '.join(cls['name'] for cls in analysis.classes[:5])}")
        lines.append("")
    return "\n".join(lines)


class GraphVizTool(Tool):
    spec = ToolSpec(
        name="graphviz",
        description="Generate visual code maps and dependency graphs as Mermaid markdown. Renders import/call graphs.",
        parameters={
            "path": {"type": "string", "description": "File or directory to visualize"},
            "type": {
                "type": "string",
                "description": "deps (dependency graph), codemap (file overview), or callgraph",
                "default": "deps",
            },
            "pattern": {"type": "string", "description": "File glob pattern", "default": "**/*.py"},
        },
    )

    async def __call__(self, path: str = ".", type: str = "deps", pattern: str = "**/*.py") -> ToolResult:
        try:
            p = Path(path)
            analyzer = CodeAnalyzer()

            if type == "codemap":
                files = []
                if p.is_dir():
                    files = [str(f) for f in p.glob(pattern) if f.is_file()]
                else:
                    files = [path]
                result = code_map(files, root_dir=str(p.parent if p.is_file() else p))
                return ToolResult(output=result)

            if type == "deps":
                if p.is_dir():
                    graph = analyzer.dep_graph(path)
                else:
                    analysis = analyzer.analyze_file(path)
                    graph = {path: [d.target for d in analysis.deps]}
                mermaid = dep_graph_to_mermaid(graph)
                return ToolResult(
                    output=f"```mermaid\n{mermaid}\n```\n\n"
                           f"Paste this into any Mermaid renderer (or use a GitHub markdown preview)."
                )

            if type == "callgraph":
                if p.is_dir():
                    results = analyzer.analyze_directory(path, pattern)
                else:
                    results = {path: analyzer.analyze_file(path)}

                edges: list[tuple[str, str]] = []
                for fpath, analysis in results.items():
                    for src, tgt in analysis.call_graph.edges:
                        edges.append((src, tgt))

                if not edges:
                    return ToolResult(output="(no calls found)")

                lines = ["graph TD;"]
                for src, tgt in edges[:50]:
                    lines.append(f'    {src} --> {tgt};')
                return ToolResult(
                    output=f"```mermaid\n{chr(10).join(lines)}\n```\n\n{len(edges)} total calls"
                )

            return ToolResult(error=f"Unknown viz type: {type}")

        except Exception as e:
            return ToolResult(error=str(e))
