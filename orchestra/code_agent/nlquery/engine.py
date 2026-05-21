from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig


QUERY_PATTERNS: dict[str, str] = {
    "find_file": r"(?:find|search|locate|where)\s+(?:the\s+)?(?:file|class|function|method)\s+(\w+)",
    "count": r"(?:how many|count|number of)\s+(\w+)",
    "explain": r"(?:explain|describe|how does|what does)\s+(.+?)(?:\s+in\s+(\w+))?\s*(?:\?)?$",
    "summarize": r"(?:summarize|summary of|overview of)\s+(.+?)$",
    "find_bugs": r"(?:find|show|list)\s+(?:bugs|issues|problems|errors)",
    "show_deps": r"(?:dependencies|depends|imports|requirements)",
    "find_tests": r"(?:find|show|list)\s+(?:tests|test\s+cases)",
}


class NLQueryEngine:
    """Process natural language queries about the codebase."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace)
        self.patterns = QUERY_PATTERNS

    def classify(self, query: str) -> str:
        q = query.lower().strip()
        for intent, pattern in self.patterns.items():
            if re.search(pattern, q):
                return intent
        return "general"

    def extract_params(self, query: str, intent: str) -> dict[str, str]:
        params = {}
        q = query.lower().strip()

        if intent == "find_file":
            m = re.search(self.patterns[intent], q)
            if m:
                params["name"] = m.group(1)
        elif intent == "count":
            m = re.search(self.patterns[intent], q)
            if m:
                params["target"] = m.group(1)
        elif intent == "explain":
            m = re.search(self.patterns[intent], q)
            if m:
                params["target"] = m.group(1)
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    params["file"] = m.group(2)

        return params

    def execute(self, query: str) -> dict[str, Any]:
        intent = self.classify(query)
        params = self.extract_params(query, intent)

        print(f"  Classified as: {intent}")
        print(f"  Params: {params}")

        if intent == "find_file":
            return self._find_file(params.get("name", ""))
        elif intent == "count":
            return self._count(params.get("target", ""))
        elif intent == "explain":
            return self._explain(params.get("target", ""), params.get("file", ""))
        elif intent == "find_bugs":
            return {"result": "Run `code-agent audit` for security issues or `code-agent smells` for code smells."}
        elif intent == "show_deps":
            return self._show_deps()
        elif intent == "find_tests":
            return self._find_tests()
        else:
            return {"result": f"I understand you're asking about: {query[:100]}... Try a more specific query."}

    def _find_file(self, name: str) -> dict[str, Any]:
        if not name:
            return {"error": "No name provided"}
        results = []
        for f in self.workspace.rglob("**/*"):
            if f.is_file() and name.lower() in f.name.lower():
                results.append(str(f.relative_to(self.workspace)))
        if results:
            return {"result": f"Found {len(results)} files:", "files": results[:20]}
        return {"result": f"No files matching '{name}' found."}

    def _count(self, target: str) -> dict[str, Any]:
        target_lower = target.lower()
        if target_lower in ("files", "python files", ".py files"):
            count = len(list(self.workspace.rglob("**/*.py")))
            return {"result": f"{count} Python files found."}
        elif target_lower in ("functions", "funcs"):
            import ast
            count = 0
            for f in self.workspace.rglob("**/*.py"):
                try:
                    tree = ast.parse(f.read_text())
                    count += sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
                except (SyntaxError, OSError):
                    pass
            return {"result": f"{count} functions found."}
        elif target_lower in ("classes"):
            import ast
            count = 0
            for f in self.workspace.rglob("**/*.py"):
                try:
                    tree = ast.parse(f.read_text())
                    count += sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
                except (SyntaxError, OSError):
                    pass
            return {"result": f"{count} classes found."}
        return {"result": f"Count not implemented for '{target}'."}

    def _explain(self, target: str, file: str) -> dict[str, Any]:
        if not target:
            return {"error": "Nothing to explain"}
        return {"result": f"Run: code-agent run 'Explain {target}' for a detailed explanation."}

    def _show_deps(self) -> dict[str, Any]:
        from orchestra.code_agent.depupdater.updater import DepUpdater
        updater = DepUpdater()
        deps = []
        deps.extend(updater.scan_requirements())
        deps.extend(updater.scan_pyproject())
        deps.extend(updater.scan_npm())
        return {"result": f"{len(deps)} dependencies found.", "dependencies": [d.name for d in deps[:30]]}

    def _find_tests(self) -> dict[str, Any]:
        test_files = list(self.workspace.rglob("**/test_*.py")) + list(self.workspace.rglob("**/*_test.py"))
        if test_files:
            return {"result": f"Found {len(test_files)} test files.",
                    "files": [str(f.relative_to(self.workspace)) for f in test_files[:20]]}
        return {"result": "No test files found."}

    async def query(self, text: str) -> str:
        intent = self.classify(text)
        if intent != "general":
            result = self.execute(text)
            output = result.get("result", "")
            if "files" in result:
                output += "\n" + "\n".join(f"  - {f}" for f in result["files"][:10])
            if "dependencies" in result:
                output += "\n" + "\n".join(f"  - {d}" for d in result["dependencies"][:10])
            return output

        agent = Agent(AgentConfig(name="NLQuery", max_iterations=5))
        return await agent.run(f"Answer this question about the codebase:\n\n{text}")
