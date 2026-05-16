"""Repo Indexer — full repository indexing with AST parsing and symbol extraction.

Indexes an entire codebase for the agent: file tree, symbol table
(functions, classes, imports), dependency graph, and semantic search.
This is what gives Orchestra Claude Code-level codebase awareness.

Usage::

    indexer = RepoIndexer("/path/to/repo")
    await indexer.index()
    results = indexer.search("authentication middleware")
    symbols = indexer.find_symbol("UserModel")
    deps = indexer.dependency_graph("auth/models.py")
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["RepoIndexer", "FileIndex", "SymbolIndex"]

log = logging.getLogger("orchestra.codebase.indexer")

# File patterns to index
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".rs", ".go",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".sql", ".sh", ".bash", ".yaml", ".yml",
    ".json", ".toml", ".md", ".txt", ".html", ".css", ".scss",
}
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".cargo",
}


@dataclass
class SymbolIndex:
    """A code symbol (function, class, variable, import)."""
    name: str
    kind: str               # function, class, method, import, variable
    file: str
    line: int
    end_line: int = 0
    signature: str = ""
    docstring: str = ""
    parent: str = ""        # parent class for methods


@dataclass
class FileIndex:
    """Index entry for a single file."""
    path: str
    relative_path: str
    language: str
    size: int
    lines: int
    hash: str
    symbols: list[SymbolIndex] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    content_preview: str = ""


class RepoIndexer:
    """Index a repository for agent-powered code navigation."""

    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path).resolve()
        self._files: dict[str, FileIndex] = {}
        self._symbols: dict[str, list[SymbolIndex]] = {}  # name → locations
        self._import_graph: dict[str, list[str]] = {}       # file → imported files
        self._indexed = False

    async def index(self) -> dict[str, Any]:
        """Index the entire repository."""
        self._files.clear()
        self._symbols.clear()
        self._import_graph.clear()

        file_count = 0
        symbol_count = 0

        for root, dirs, files in os.walk(self.repo_path):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext not in CODE_EXTENSIONS:
                    continue

                fpath = Path(root) / fname
                rel = str(fpath.relative_to(self.repo_path))

                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                lang = self._detect_language(ext)
                file_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

                # Extract symbols
                symbols = []
                imports = []
                if lang == "python":
                    symbols, imports = self._parse_python(content, rel)
                elif lang in ("javascript", "typescript"):
                    symbols, imports = self._parse_js_ts(content, rel)
                else:
                    symbols = self._parse_generic(content, rel)

                file_idx = FileIndex(
                    path=str(fpath),
                    relative_path=rel,
                    language=lang,
                    size=len(content),
                    lines=content.count("\n") + 1,
                    hash=file_hash,
                    symbols=symbols,
                    imports=imports,
                    content_preview=content[:500],
                )
                self._files[rel] = file_idx
                file_count += 1

                # Build symbol index
                for sym in symbols:
                    if sym.name not in self._symbols:
                        self._symbols[sym.name] = []
                    self._symbols[sym.name].append(sym)
                    symbol_count += 1

                # Build import graph
                self._import_graph[rel] = imports

        self._indexed = True
        log.info("Indexed %s: %d files, %d symbols", self.repo_path, file_count, symbol_count)
        return {
            "repo": str(self.repo_path),
            "files": file_count,
            "symbols": symbol_count,
            "languages": list(set(f.language for f in self._files.values())),
        }

    # -- search -------------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Keyword search across file contents and symbol names."""
        query_lower = query.lower()
        results: list[tuple[float, dict]] = []

        for rel, fidx in self._files.items():
            score = 0.0
            # Filename match
            if query_lower in rel.lower():
                score += 5.0
            # Symbol name match
            for sym in fidx.symbols:
                if query_lower in sym.name.lower():
                    score += 3.0
                if query_lower in sym.signature.lower():
                    score += 1.0
            # Content match
            preview = fidx.content_preview.lower()
            matches = preview.count(query_lower)
            score += matches * 0.5

            if score > 0:
                results.append((score, {
                    "file": rel,
                    "language": fidx.language,
                    "lines": fidx.lines,
                    "score": round(score, 1),
                    "symbols": [s.name for s in fidx.symbols if query_lower in s.name.lower()][:5],
                }))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results[:limit]]

    def find_symbol(self, name: str) -> list[SymbolIndex]:
        """Find all locations of a symbol by name."""
        return self._symbols.get(name, [])

    def find_symbol_fuzzy(self, query: str, limit: int = 10) -> list[SymbolIndex]:
        """Fuzzy symbol search."""
        query_lower = query.lower()
        matches: list[tuple[float, SymbolIndex]] = []
        for name, syms in self._symbols.items():
            if query_lower in name.lower():
                score = len(query_lower) / len(name)
                for s in syms:
                    matches.append((score, s))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in matches[:limit]]

    def get_file(self, path: str) -> FileIndex | None:
        return self._files.get(path)

    def read_file(self, path: str) -> str:
        """Read file contents."""
        fpath = self.repo_path / path
        if fpath.exists():
            return fpath.read_text(encoding="utf-8", errors="replace")
        return ""

    def dependency_graph(self, file_path: str) -> dict[str, Any]:
        """Get import/dependency graph for a file."""
        imports = self._import_graph.get(file_path, [])
        # Reverse: who imports this file?
        imported_by = [
            f for f, deps in self._import_graph.items()
            if any(file_path.replace("/", ".").replace(".py", "") in d for d in deps)
        ]
        return {
            "file": file_path,
            "imports": imports,
            "imported_by": imported_by,
        }

    def file_tree(self, max_depth: int = 4) -> list[str]:
        """Get the file tree as a list of paths."""
        return sorted(self._files.keys())[:500]

    def summary(self) -> dict[str, Any]:
        """Repository summary for injection into agent prompts."""
        lang_counts: dict[str, int] = {}
        total_lines = 0
        for f in self._files.values():
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
            total_lines += f.lines
        return {
            "repo": str(self.repo_path),
            "total_files": len(self._files),
            "total_lines": total_lines,
            "total_symbols": sum(len(v) for v in self._symbols.values()),
            "languages": lang_counts,
            "top_files": sorted(self._files.values(), key=lambda f: f.lines, reverse=True)[:10],
        }

    # -- parsers ------------------------------------------------------------

    def _parse_python(self, content: str, filepath: str) -> tuple[list[SymbolIndex], list[str]]:
        """Parse Python AST for symbols and imports."""
        symbols: list[SymbolIndex] = []
        imports: list[str] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return symbols, imports

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
                doc = ast.get_docstring(node) or ""
                parent = ""
                # Check if it's a method
                for parent_node in ast.walk(tree):
                    if isinstance(parent_node, ast.ClassDef):
                        if node in ast.walk(parent_node):
                            parent = parent_node.name
                            break
                symbols.append(SymbolIndex(
                    name=node.name, kind="method" if parent else "function",
                    file=filepath, line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=sig, docstring=doc[:200], parent=parent,
                ))
            elif isinstance(node, ast.ClassDef):
                bases = ", ".join(
                    getattr(b, "id", getattr(b, "attr", "")) for b in node.bases
                )
                sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
                symbols.append(SymbolIndex(
                    name=node.name, kind="class",
                    file=filepath, line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=sig, docstring=ast.get_docstring(node) or "",
                ))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        return symbols, imports

    def _parse_js_ts(self, content: str, filepath: str) -> tuple[list[SymbolIndex], list[str]]:
        """Regex-based JS/TS parsing."""
        symbols: list[SymbolIndex] = []
        imports: list[str] = []

        # Functions
        for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", content):
            line = content[:m.start()].count("\n") + 1
            symbols.append(SymbolIndex(name=m.group(1), kind="function", file=filepath, line=line, signature=f"function {m.group(1)}({m.group(2)})"))

        # Arrow functions
        for m in re.finditer(r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>", content):
            line = content[:m.start()].count("\n") + 1
            symbols.append(SymbolIndex(name=m.group(1), kind="function", file=filepath, line=line, signature=f"const {m.group(1)} = ({m.group(2)}) =>"))

        # Classes
        for m in re.finditer(r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", content):
            line = content[:m.start()].count("\n") + 1
            symbols.append(SymbolIndex(name=m.group(1), kind="class", file=filepath, line=line, signature=m.group(0)))

        # Imports
        for m in re.finditer(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content):
            imports.append(m.group(1))
        for m in re.finditer(r"require\(['\"]([^'\"]+)['\"]\)", content):
            imports.append(m.group(1))

        return symbols, imports

    def _parse_generic(self, content: str, filepath: str) -> list[SymbolIndex]:
        """Generic regex parsing for any language."""
        symbols: list[SymbolIndex] = []
        # Functions
        for m in re.finditer(r"(?:pub\s+)?(?:fn|func|def|function)\s+(\w+)", content):
            line = content[:m.start()].count("\n") + 1
            symbols.append(SymbolIndex(name=m.group(1), kind="function", file=filepath, line=line))
        # Types/structs/classes
        for m in re.finditer(r"(?:pub\s+)?(?:struct|class|interface|type|enum)\s+(\w+)", content):
            line = content[:m.start()].count("\n") + 1
            symbols.append(SymbolIndex(name=m.group(1), kind="class", file=filepath, line=line))
        return symbols

    @staticmethod
    def _detect_language(ext: str) -> str:
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".jsx": "javascript", ".java": "java",
            ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp",
            ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
            ".php": "php", ".swift": "swift", ".kt": "kotlin",
            ".scala": "scala", ".sql": "sql", ".sh": "bash",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json",
            ".toml": "toml", ".md": "markdown", ".html": "html",
            ".css": "css", ".scss": "scss",
        }
        return lang_map.get(ext, "unknown")
