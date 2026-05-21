from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImportInfo:
    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    line: int = 0


@dataclass
class Dependency:
    source: str
    target: str
    dep_type: str = "import"


@dataclass
class CallGraph:
    edges: list[tuple[str, str]] = field(default_factory=list)
    nodes: set[str] = field(default_factory=set)


@dataclass
class AnalysisResult:
    file_path: str
    imports: list[ImportInfo] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    classes: list[dict[str, Any]] = field(default_factory=list)
    deps: list[Dependency] = field(default_factory=list)
    call_graph: CallGraph = field(default_factory=CallGraph)
    lines_of_code: int = 0
    errors: list[str] = field(default_factory=list)


class CodeAnalyzer:
    def analyze_file(self, file_path: str) -> AnalysisResult:
        p = Path(file_path)
        if not p.exists():
            return AnalysisResult(file_path=file_path, errors=[f"File not found: {file_path}"])
        text = p.read_text("utf-8", errors="replace")
        return self._analyze(file_path, text)

    def analyze_text(self, text: str, filename: str = "<string>") -> AnalysisResult:
        return self._analyze(filename, text)

    def _analyze(self, file_path: str, text: str) -> AnalysisResult:
        result = AnalysisResult(file_path=file_path, lines_of_code=len(text.splitlines()))
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            result.errors.append(str(e))
            return result

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(ImportInfo(
                        module=alias.name,
                        names=[alias.asname or alias.name],
                        line=node.lineno,
                    ))
                    target = f"{alias.name}:{alias.asname}" if alias.asname else alias.name
                    result.deps.append(Dependency(
                        source=file_path,
                        target=target,
                        dep_type="import",
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    result.imports.append(ImportInfo(
                        module=module,
                        names=[alias.asname or alias.name],
                        line=node.lineno,
                    ))
                    result.deps.append(Dependency(
                        source=file_path,
                        target=f"{module}.{alias.name}",
                        dep_type="import",
                    ))
            elif isinstance(node, ast.FunctionDef):
                doc = ast.get_docstring(node) or ""
                result.functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "args": [a.arg for a in node.args.args],
                    "docstring": doc[:200] if doc else "",
                    "decorators": [self._get_decorator_name(d) for d in node.decorator_list],
                })
                result.call_graph.nodes.add(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                doc = ast.get_docstring(node) or ""
                result.functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "args": [a.arg for a in node.args.args],
                    "docstring": doc[:200] if doc else "",
                    "async": True,
                    "decorators": [self._get_decorator_name(d) for d in node.decorator_list],
                })
                result.call_graph.nodes.add(node.name)
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(item.name)
                result.classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "bases": [self._get_base_name(b) for b in node.bases],
                    "methods": methods,
                    "docstring": doc[:200] if doc else "",
                })
                result.call_graph.nodes.add(node.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        result.call_graph.edges.append(
                            (node.func.value.id, node.func.attr)
                        )
                        result.call_graph.nodes.add(node.func.value.id)
                        result.call_graph.nodes.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    result.call_graph.nodes.add(node.func.id)

        return result

    def analyze_directory(self, dir_path: str, pattern: str = "**/*.py") -> dict[str, AnalysisResult]:
        root = Path(dir_path)
        results: dict[str, AnalysisResult] = {}
        for p in root.glob(pattern):
            if p.is_file():
                results[str(p)] = self.analyze_file(str(p))
        return results

    def dep_graph(self, dir_path: str) -> dict[str, list[str]]:
        results = self.analyze_directory(dir_path)
        graph: dict[str, list[str]] = defaultdict(list)
        for fpath, analysis in results.items():
            for dep in analysis.deps:
                graph[fpath].append(dep.target)
        return dict(graph)

    @staticmethod
    def _get_decorator_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{CodeAnalyzer._get_decorator_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return CodeAnalyzer._get_decorator_name(node.func)
        return "?"

    @staticmethod
    def _get_base_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{CodeAnalyzer._get_base_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{CodeAnalyzer._get_base_name(node.value)}"
        return "?"
