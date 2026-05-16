from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SymbolMatch:
    name: str
    kind: str
    file_path: str
    line: int
    column: int
    signature: str = ""


@dataclass
class SymbolIndex:
    symbols: list[SymbolMatch] = field(default_factory=list)
    _by_name: dict[str, list[SymbolMatch]] = field(default_factory=dict)
    _by_file: dict[str, list[SymbolMatch]] = field(default_factory=dict)
    _by_kind: dict[str, list[SymbolMatch]] = field(default_factory=dict)


_JS_TS_PATTERNS = [
    (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", "function"),
    (r"(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\(", "generator"),
    (r"(?:export\s+)?(?:async\s+)?\(?\s*(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*\w+)?\s*=>", "arrow_function"),
    (r"(?:export\s+)?class\s+(\w+)", "class"),
    (r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*\w+(?:<[^>]*>)?)?\s*=", "variable"),
    (r"(?:export\s+)?interface\s+(\w+)", "interface"),
    (r"(?:export\s+)?type\s+(\w+)\s*=", "type"),
    (r"(?:export\s+)?enum\s+(\w+)", "enum"),
    (r"(?:export\s+)?abstract\s+class\s+(\w+)", "abstract_class"),
    (r"(?:export\s+)?default\s+(?:function|class)\s+(\w+)", "default_export"),
    (r"(?:export\s+)?function\s+\*(\w+)\s*\(", "generator"),
]

_RUST_PATTERNS = [
    (r"fn\s+(\w+)\s*\(", "function"),
    (r"(?:pub\s+)?(?:unsafe\s+)?fn\s+(\w+)\s*\(", "function"),
    (r"(?:pub\s+)?struct\s+(\w+)", "struct"),
    (r"(?:pub\s+)?enum\s+(\w+)", "enum"),
    (r"(?:pub\s+)?trait\s+(\w+)", "trait"),
    (r"(?:pub\s+)?impl\s+(\w+)", "impl"),
    (r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(", "async_function"),
    (r"(?:pub\s+)?macro_rules!\s*(\w+)", "macro"),
    (r"(?:pub\s+)?type\s+(\w+)\s*=", "type_alias"),
    (r"(?:pub\s+)?(?:const|static)\s+(\w+)\s*:", "constant"),
    (r"(?:pub\s+)?mod\s+(\w+)", "module"),
    (r"(?:pub\s+)?use\s+(?:\w+::)*(\w+)", "use"),
]

_GO_PATTERNS = [
    (r"func\s+(\w+)\s*\(", "function"),
    (r"func\s+\([^)]*\)\s+(\w+)\s*\(", "method"),
    (r"type\s+(\w+)\s+struct", "struct"),
    (r"type\s+(\w+)\s+interface", "interface"),
    (r"type\s+(\w+)\s+", "type_def"),
    (r"const\s+(\w+)", "constant"),
    (r"var\s+(\w+)", "variable"),
    (r"func\s+\([^)]*\)\s+\([^)]*\)\s+(\w+)\s*\(", "method"),
]

_JAVA_PATTERNS = [
    (r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(", "method"),
    (r"(?:public|private|protected)\s+class\s+(\w+)", "class"),
    (r"(?:public|private|protected)\s+interface\s+(\w+)", "interface"),
    (r"(?:public|private|protected)\s+enum\s+(\w+)", "enum"),
    (r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:\[\])?)\s+(\w+)\s*(?:;|=)", "field"),
    (r"(?:public|private|protected)\s+@Override\s+(?:public\s+)?(?:\w+)\s+(\w+)\s*\(", "override_method"),
    (r"(?:public|private|protected)\s+(?:static\s+)?class\s+(\w+)", "class"),
    (r"(?:public|private|protected)\s+(?:abstract\s+)?class\s+(\w+)", "abstract_class"),
    (r"record\s+(\w+)", "record"),
    (r"@\w+\s+(?:public|private|protected)\s+(?:\w+)\s+(\w+)\s*\(", "annotated_method"),
]


class CodeSearchEngine:
    def __init__(self, root_path: str = "."):
        self.root = Path(root_path).resolve()
        self.index: SymbolIndex = SymbolIndex()
        self._built = False

    def build_index(self, paths: Optional[list[str]] = None) -> SymbolIndex:
        self.index = SymbolIndex()
        sources = paths or self._discover_sources()

        for fp in sources:
            p = Path(fp)
            if not p.exists() or p.suffix not in {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            suffix = p.suffix
            if suffix == ".py":
                self._index_python(str(p), text)
            elif suffix in {".js", ".ts", ".jsx", ".tsx"}:
                self._index_regex(str(p), text, _JS_TS_PATTERNS)
            elif suffix == ".rs":
                self._index_regex(str(p), text, _RUST_PATTERNS)
            elif suffix == ".go":
                self._index_regex(str(p), text, _GO_PATTERNS)
            elif suffix == ".java":
                self._index_regex(str(p), text, _JAVA_PATTERNS)

        self._built = True
        return self.index

    def find_definitions(self, name: str) -> list[SymbolMatch]:
        if not self._built:
            self.build_index()
        return self.index._by_name.get(name, [])

    def find_references(self, name: str) -> list[SymbolMatch]:
        if not self._built:
            self.build_index()
        refs: list[SymbolMatch] = []
        for sym in self.index.symbols:
            if sym.name == name:
                continue
            try:
                text = Path(sym.file_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if name in line:
                    refs.append(SymbolMatch(name=name, kind="reference", file_path=sym.file_path, line=i, column=line.index(name) + 1))
        return refs

    def find_by_file(self, file_path: str) -> list[SymbolMatch]:
        if not self._built:
            self.build_index()
        return self.index._by_file.get(file_path, [])

    def find_by_kind(self, kind: str) -> list[SymbolMatch]:
        if not self._built:
            self.build_index()
        return self.index._by_kind.get(kind, [])

    def search(self, query: str, kind: Optional[str] = None) -> list[SymbolMatch]:
        if not self._built:
            self.build_index()
        results: list[SymbolMatch] = []
        ql = query.lower()
        for sym in self.index.symbols:
            if ql in sym.name.lower() or ql in sym.signature.lower():
                if kind and sym.kind != kind:
                    continue
                results.append(sym)
        return results

    def _discover_sources(self) -> list[str]:
        exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java"}
        files = []
        for ext in exts:
            files.extend(str(p) for p in self.root.rglob(f"*{ext}") if "__pycache__" not in str(p) and ".git" not in str(p) and "node_modules" not in str(p))
        return sorted(files)

    def _index_python(self, file_path: str, text: str) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
                self._add_symbol(SymbolMatch(name=node.name, kind="function", file_path=file_path, line=node.lineno, column=node.col_offset, signature=sig))
            elif isinstance(node, ast.AsyncFunctionDef):
                sig = f"async def {node.name}({', '.join(a.arg for a in node.args.args)})"
                self._add_symbol(SymbolMatch(name=node.name, kind="async_function", file_path=file_path, line=node.lineno, column=node.col_offset, signature=sig))
            elif isinstance(node, ast.ClassDef):
                bases = [b.id if isinstance(b, ast.Name) else "" for b in node.bases]
                sig = f"class {node.name}({', '.join(b for b in bases if b)})"
                self._add_symbol(SymbolMatch(name=node.name, kind="class", file_path=file_path, line=node.lineno, column=node.col_offset, signature=sig))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._add_symbol(SymbolMatch(name=target.id, kind="variable", file_path=file_path, line=target.lineno, column=target.col_offset))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self._add_symbol(SymbolMatch(name=node.target.id, kind="annotated_variable", file_path=file_path, line=node.target.lineno, column=node.target.col_offset))

    def _index_regex(self, file_path: str, text: str, patterns: list[tuple[str, str]]) -> None:
        for pattern, kind in patterns:
            for m in re.finditer(pattern, text):
                name = m.group(1)
                line_num = text[: m.start()].count("\n") + 1
                col = m.start() - text.rfind("\n", 0, m.start()) - 1
                self._add_symbol(SymbolMatch(name=name, kind=kind, file_path=file_path, line=line_num, column=col))

    def _add_symbol(self, sym: SymbolMatch) -> None:
        self.index.symbols.append(sym)
        self.index._by_name.setdefault(sym.name, []).append(sym)
        self.index._by_file.setdefault(sym.file_path, []).append(sym)
        self.index._by_kind.setdefault(sym.kind, []).append(sym)
