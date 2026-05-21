"""Architecture navigation system — helps the agent understand and move through the system.

The agent can query this to discover:
- What tools are available and how to use them
- What API endpoints exist
- What the project structure looks like
- What workflows are pre-built
- What capabilities the system has
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from orchestra.code_agent.tools.base import Tool


class CapabilityRegistry:
    """Central registry of system capabilities the agent can discover dynamically."""

    def __init__(self):
        self._capabilities: dict[str, dict[str, Any]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register("file_operations", {
            "description": "Read, write, edit, and search files in the workspace",
            "tools": ["read", "write", "edit", "glob", "grep"],
            "skills": ["code-reading", "editing", "code-modification"],
        })
        self.register("shell_execution", {
            "description": "Run shell commands, execute scripts, manage processes",
            "tools": ["bash", "sandbox"],
            "skills": ["command-execution"],
        })
        self.register("code_intelligence", {
            "description": "Analyze, transform, refactor, and generate tests for code",
            "tools": ["analyze", "transform", "testgen", "review"],
            "skills": ["code-review", "testing", "refactoring"],
        })
        self.register("git_operations", {
            "description": "Version control, commits, branches, PRs",
            "tools": ["git"],
            "skills": ["git", "version-control"],
        })
        self.register("web_interaction", {
            "description": "Browse the web, search, fetch pages, interact with APIs",
            "tools": ["webfetch", "websearch", "browser"],
            "skills": ["web", "research"],
        })
        self.register("scaffolding", {
            "description": "Generate project scaffolds for Rust, TypeScript, Mojo, Python, web apps",
            "tools": ["scaffold", "scaffold_rust", "scaffold_ts", "scaffold_mojo"],
            "skills": ["project-setup", "scaffolding"],
        })
        self.register("knowledge_management", {
            "description": "Store, search, and retrieve knowledge, skills, and memories",
            "tools": ["skill", "memory", "knowledge"],
            "skills": ["knowledge", "memory"],
        })
        self.register("observability", {
            "description": "Monitor system health, metrics, traces, and logs",
            "endpoints": ["/api/health", "/api/metrics", "/observability", "/api/langfuse"],
        })

    def register(self, name: str, info: dict[str, Any]) -> None:
        self._capabilities[name] = info

    def list(self) -> list[dict[str, Any]]:
        return [{"name": k, **v} for k, v in self._capabilities.items()]

    def find(self, query: str) -> list[dict[str, Any]]:
        """Find capabilities matching a natural language query."""
        q = query.lower()
        results = []
        for name, info in self._capabilities.items():
            desc = info.get("description", "").lower()
            tools = " ".join(info.get("tools", [])).lower()
            skills = " ".join(info.get("skills", [])).lower()
            if q in desc or q in name or q in tools or q in skills:
                results.append({"name": name, **info})
        return results

    def get_tools_for(self, capability: str) -> list[str]:
        return self._capabilities.get(capability, {}).get("tools", [])

    def format_for_prompt(self) -> str:
        """Format capabilities for inclusion in the agent's system prompt."""
        lines = ["## Available Capabilities"]
        for name, info in self._capabilities.items():
            desc = info.get("description", "")
            tools = ", ".join(info.get("tools", []))
            lines.append(f"  • {name}: {desc}")
            if tools:
                lines.append(f"    Tools: {tools}")
        return "\n".join(lines)


class ProjectNavigator:
    """Helps the agent understand and navigate the project structure."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getcwd()).resolve()

    def get_structure(self, depth: int = 3) -> str:
        """Get a tree-like view of the project structure."""
        lines = [f"Project root: {self.root}", ""]

        def _walk(dir_path: Path, level: int = 0) -> None:
            if level >= depth:
                return
            try:
                entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            for entry in entries:
                if entry.name.startswith(".") or entry.name.startswith("__pycache__"):
                    continue
                indent = "  " * level
                if entry.is_dir():
                    lines.append(f"{indent}{entry.name}/")
                    _walk(entry, level + 1)
                else:
                    lines.append(f"{indent}{entry.name}")

        _walk(self.root)
        return "\n".join(lines)

    def find_files(self, pattern: str, max_results: int = 20) -> list[Path]:
        """Find files matching a pattern."""
        matches = []
        for p in self.root.rglob(pattern):
            if not any(part.startswith(".") or part.startswith("__pycache__") for part in p.parts):
                matches.append(p)
                if len(matches) >= max_results:
                    break
        return matches

    def summarize(self) -> dict[str, Any]:
        """Summarize the project: language, file types, size."""
        total_files = 0
        extensions: dict[str, int] = {}
        total_lines = 0
        for p in self.root.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                total_files += 1
                ext = p.suffix or "(no ext)"
                extensions[ext] = extensions.get(ext, 0) + 1
                try:
                    total_lines += len(p.read_text().splitlines())
                except Exception:
                    pass
        return {
            "root": str(self.root),
            "total_files": total_files,
            "total_lines": total_lines,
            "file_types": dict(sorted(extensions.items(), key=lambda x: -x[1])[:10]),
        }
