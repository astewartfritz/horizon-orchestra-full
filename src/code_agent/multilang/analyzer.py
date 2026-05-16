from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec


@dataclass
class AnalysisResult:
    language: str
    file: str
    imports: list[str] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    classes: list[dict[str, Any]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiLangAnalyzer:
    LANG_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
    }

    def analyze_file(self, path: str | Path) -> AnalysisResult:
        p = Path(path)
        ext = p.suffix.lower()
        lang = self.LANG_MAP.get(ext, "unknown")
        text = p.read_text(encoding="utf-8", errors="ignore")

        result = AnalysisResult(language=lang, file=str(p))

        if lang == "python":
            self._analyze_python(text, result)
        elif lang in ("javascript", "typescript"):
            self._analyze_js_ts(text, result)
        elif lang == "rust":
            self._analyze_rust(text, result)
        elif lang == "go":
            self._analyze_go(text, result)
        elif lang == "java":
            self._analyze_java(text, result)

        return result

    def _analyze_python(self, text: str, result: AnalysisResult) -> None:
        for m in re.finditer(r'^(?:from|import)\s+(\S+)', text, re.MULTILINE):
            result.imports.append(m.group(1))
        for m in re.finditer(r'^(?:async\s+)?def\s+(\w+)\s*\(', text, re.MULTILINE):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'^class\s+(\w+)', text, re.MULTILINE):
            result.classes.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})

    def _analyze_js_ts(self, text: str, result: AnalysisResult) -> None:
        for m in re.finditer(r'(?:import\s+|require\s*\([\'"])([^\'";]+)', text):
            result.imports.append(m.group(1).rstrip("'\"`"))
        for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', text):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', text):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'(?:export\s+)?class\s+(\w+)', text):
            result.classes.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)', text):
            result.exports.append(m.group(1))

    def _analyze_rust(self, text: str, result: AnalysisResult) -> None:
        for m in re.finditer(r'^use\s+(\S+)', text, re.MULTILINE):
            result.imports.append(m.group(1))
        for m in re.finditer(r'^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', text, re.MULTILINE):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'^(?:pub\s+)?(?:struct|enum|trait|impl)\s+(\w+)', text, re.MULTILINE):
            result.classes.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})

    def _analyze_go(self, text: str, result: AnalysisResult) -> None:
        for m in re.finditer(r'^(?:import\s+[\'"](\S+)[\'"]|import\s+\()', text, re.MULTILINE):
            result.imports.append(m.group(1) or "(block)")
        for m in re.finditer(r'^func\s+(?:\([^)]+\)\s+)?(\w+)', text, re.MULTILINE):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'^type\s+(\w+)\s+(?:struct|interface)', text, re.MULTILINE):
            result.classes.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})

    def _analyze_java(self, text: str, result: AnalysisResult) -> None:
        for m in re.finditer(r'^import\s+([\w.]+)', text, re.MULTILINE):
            result.imports.append(m.group(1))
        for m in re.finditer(r'(?:public|private|protected|static)?\s*(?:async\s+)?\w+\s+(\w+)\s*\(', text):
            result.functions.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})
        for m in re.finditer(r'(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)', text):
            result.classes.append({"name": m.group(1), "line": text[:m.start()].count("\n") + 1})

    def analyze_directory(self, path: str = ".", pattern: str = "**/*") -> dict[str, list[AnalysisResult]]:
        results: dict[str, list[AnalysisResult]] = {}
        for f in Path(path).glob(pattern):
            if f.is_file() and f.suffix.lower() in self.LANG_MAP:
                results.setdefault(self.LANG_MAP[f.suffix.lower()], []).append(self.analyze_file(f))
        return results


class MultiLangTool(Tool):
    spec = ToolSpec(
        name="multilang",
        description="Analyze code across multiple languages (Python, JS, TS, Rust, Go, Java). Extract imports, functions, classes.",
        parameters={
            "path": {"type": "string", "description": "File or directory to analyze", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern", "default": "**/*"},
            "action": {"type": "string", "description": "analyze, summary, languages", "default": "summary"},
        },
    )

    async def __call__(self, path: str = ".", pattern: str = "**/*", action: str = "summary") -> ToolResult:
        try:
            analyzer = MultiLangAnalyzer()
            p = Path(path)

            if p.is_file():
                results = [analyzer.analyze_file(p)]
            else:
                by_lang = analyzer.analyze_directory(path, pattern)
                results = [r for lst in by_lang.values() for r in lst]

            if action == "languages":
                langs = set(r.language for r in results)
                counts = {lang: sum(1 for r in results if r.language == lang) for lang in sorted(langs)}
                return ToolResult(output=f"Languages:\n" + "\n".join(f"  {lang}: {cnt}" for lang, cnt in counts.items()))

            if action == "summary":
                lines = [f"Analyzed {len(results)} files:\n"]
                for r in results[:30]:
                    funcs = ", ".join(f["name"] for f in r.functions[:5])
                    classes = ", ".join(c["name"] for c in r.classes[:5])
                    parts = []
                    if funcs:
                        parts.append(f"fn: {funcs}")
                    if classes:
                        parts.append(f"cls: {classes}")
                    lines.append(f"  {Path(r.file).name:25} [{r.language:10}] ({'; '.join(parts)})")
                if len(results) > 30:
                    lines.append(f"  ... and {len(results) - 30} more")
                return ToolResult(output="\n".join(lines))

            if action == "analyze":
                data = [r.to_dict() for r in results[:20]]
                return ToolResult(output=json.dumps(data, indent=2))

        except Exception as e:
            return ToolResult(error=str(e))
