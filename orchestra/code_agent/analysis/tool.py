from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.analysis.parser import CodeAnalyzer


class AnalyzeTool(Tool):
    spec = ToolSpec(
        name="analyze",
        description="Analyze Python code files: extract imports, functions, classes, call graph, and dependencies.",
        parameters={
            "path": {"type": "string", "description": "File or directory to analyze"},
            "action": {
                "type": "string",
                "description": "Analysis type: summary, functions, classes, imports, deps, callgraph, all",
                "default": "summary",
            },
            "pattern": {"type": "string", "description": "Glob pattern for directories", "default": "**/*.py"},
        },
    )

    async def __call__(self, path: str, action: str = "summary", pattern: str = "**/*.py") -> ToolResult:
        try:
            analyzer = CodeAnalyzer()
            from pathlib import Path
            p = Path(path)

            if p.is_dir():
                results = analyzer.analyze_directory(path, pattern)
            else:
                results = {path: analyzer.analyze_file(path)}

            if not results:
                return ToolResult(output="(no files analyzed)")

            lines: list[str] = []
            for fpath, analysis in results.items():
                if analysis.errors:
                    lines.append(f"Errors in {fpath}: {analysis.errors}")
                    continue

                match action:
                    case "summary":
                        lines.append(
                            f"{fpath}: {len(analysis.functions)} functions, "
                            f"{len(analysis.classes)} classes, "
                            f"{len(analysis.imports)} imports, "
                            f"{analysis.lines_of_code} lines"
                        )
                    case "functions":
                        lines.append(f"Functions in {fpath}:")
                        for fn in analysis.functions:
                            args = ", ".join(fn.get("args", []))
                            lines.append(f"  {fn['name']}({args}) at line {fn['line']}")
                    case "classes":
                        lines.append(f"Classes in {fpath}:")
                        for cls in analysis.classes:
                            bases = ", ".join(cls.get("bases", []))
                            lines.append(f"  class {cls['name']}({bases}) at line {cls['line']}")
                            for m in cls.get("methods", [])[:5]:
                                lines.append(f"    .{m}()")
                    case "imports":
                        lines.append(f"Imports in {fpath}:")
                        for imp in analysis.imports:
                            names = ", ".join(imp.names)
                            lines.append(f"  line {imp.line}: from {imp.module} import {names}")
                    case "deps" | "dependencies":
                        for dep in analysis.deps:
                            target = dep.target[:80]
                            lines.append(f"  {Path(fpath).name} -> {target}")
                    case "callgraph":
                        lines.append(f"Call graph for {fpath}:")
                        for src, tgt in analysis.call_graph.edges:
                            lines.append(f"  {src} -> {tgt}")
                    case "all":
                        lines.append(f"=== {fpath} ===")
                        lines.append(f"Imports ({len(analysis.imports)}):")
                        for imp in analysis.imports:
                            lines.append(f"  line {imp.line}: {imp.module}.{', '.join(imp.names)}")
                        lines.append(f"Functions ({len(analysis.functions)}):")
                        for fn in analysis.functions:
                            lines.append(f"  {fn['name']} at line {fn['line']}")
                        lines.append(f"Classes ({len(analysis.classes)}):")
                        for cls in analysis.classes:
                            lines.append(f"  {cls['name']} at line {cls['line']}")

            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=str(e))
